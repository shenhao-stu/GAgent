"""PC Link must not ship shared relay signing material in source or APKs."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import types
import zipfile

import pytest

ROOT = Path(__file__).parents[1]
CORE = ROOT / 'app/src/main/assets/ga_runtime'
sys.path.insert(0, str(CORE))
import service_config
from test_pclink_credentials import load_link


def load_audit():
    spec = importlib.util.spec_from_file_location('audit_bootstrap', ROOT / 'tools/audit_source.py')
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    return audit


@pytest.fixture
def legacy_defaults(monkeypatch, tmp_path):
    # Simulate a device upgraded from a build that unpacked pclink_defaults.json.
    path = tmp_path / 'pclink_defaults.json'
    path.write_text(json.dumps({'url': 'wss://relay.example/ws', 'token': 'synthetic-build-token'}))
    # Older builds read this module attribute; keep it pointed at the stale file.
    monkeypatch.setattr(service_config, 'PCLINK_DEFAULTS', path, raising=False)
    monkeypatch.setattr(service_config, 'load_config', lambda: {})
    return path


def test_unconfigured_status_is_actionable_without_network(legacy_defaults, monkeypatch):
    link = load_link()
    monkeypatch.setattr(link, '_paired', lambda: False)
    monkeypatch.setattr(link, '_ensure_loop', lambda: pytest.fail('no pairing: no network'))
    status = json.loads(link.handle('/pclink.status'))
    assert status['ok'] == 1 and status['configured'] is False
    assert status['paired'] is False and status['signal'] == ''


def test_stale_bundled_defaults_are_never_used_to_sign(legacy_defaults, monkeypatch):
    link = load_link()
    async def forbidden(*args, **kwargs):
        pytest.fail('no relay request without a user-configured credential')
    monkeypatch.setitem(sys.modules, 'p2p_ws_client', types.SimpleNamespace(connect_code=forbidden))
    with pytest.raises(RuntimeError, match='PC Link is disabled'):
        asyncio.run(link._pair('123456789'))
    assert service_config.pclink_config() is None


def test_user_configured_relay_pairs_with_its_own_credential(monkeypatch):
    custom = {'url': 'wss://private.example/ws', 'token': 'synthetic-custom'}
    monkeypatch.setattr(service_config, 'load_config', lambda: {'pclink': custom})
    link = load_link()
    calls = []
    async def connect(url, code, **kwargs):
        calls.append((url, code, kwargs['access_key']))
        return object()
    monkeypatch.setitem(sys.modules, 'p2p_ws_client', types.SimpleNamespace(connect_code=connect))
    monkeypatch.setattr(link, '_attach', lambda socket, config: calls.append(config))
    asyncio.run(link._pair('123456789'))
    assert calls == [(custom['url'], '123456789', custom['token']), custom]
    assert service_config.public_config() == {'pclink': {'url': custom['url'], 'has_token': True}}


def test_build_never_injects_relay_defaults():
    workflow = (ROOT / '.github/workflows/android.yml').read_text(encoding='utf-8')
    assert 'GAGENT_PCLINK_DEFAULTS' not in workflow
    assert 'write_pclink_defaults' not in workflow
    assert not (ROOT / 'tools/write_pclink_defaults.py').exists()


@pytest.mark.parametrize('name', ['assets/ga_runtime/pclink_defaults.json',
                                  'app/src/main/assets/ga_runtime/pclink_defaults.json'])
def test_audit_rejects_bundled_relay_defaults_in_any_shape(name):
    audit = load_audit()
    host = 'wss://' + 'p2p.' + 'example' + '.org/ws'
    for blob in (json.dumps({'url': host, 'token': 'synthetic-relay-token'}).encode(), b'{}'):
        assert any(f['rule'] == 'credential-or-runtime-file' for f in audit.audit_blob(name, blob))


def test_apk_audit_fails_when_package_contains_relay_defaults(tmp_path, monkeypatch, capsys):
    audit = load_audit()
    apk = tmp_path / 'synthetic.apk'
    with zipfile.ZipFile(apk, 'w') as archive:
        archive.writestr('assets/ga_runtime/pclink.py', 'print(1)\n')
        archive.writestr('assets/ga_runtime/pclink_defaults.json', '{"token": "synthetic"}')
    monkeypatch.setattr(sys, 'argv', ['audit_source.py', '--apk', str(apk)])
    assert audit.main() is True
    report = json.loads(capsys.readouterr().out)
    assert [f['path'] for f in report['findings']] == ['assets/ga_runtime/pclink_defaults.json']


def test_audit_allows_the_public_relay_preset_only_in_its_file():
    audit = load_audit()
    relay = ("'wss://p2p." + 'gaagent' + ".ai/ws'").encode()
    src = b'const PUBLIC_RELAY={url:' + relay + b"};"
    assert audit.audit_blob('app/src/main/assets/ga_runtime/webui/integrations.js', src) == []
    assert audit.audit_blob('assets/ga_runtime/webui/integrations.js', src) == []      # same file inside the APK
    assert audit.audit_blob('app/src/main/assets/ga_runtime/webui/app.js', src)        # anywhere else still fails
    other = ("'wss://relay." + 'gaagent' + ".ai/ws'").encode()
    assert audit.audit_blob('app/src/main/assets/ga_runtime/webui/integrations.js', b'x=' + other)
    assert audit.audit_blob('app/src/main/assets/ga_runtime/webui/integrations.js', src + b'\nconst D=' + relay)   # a second copy fails
    assert audit.audit_blob('app/src/main/assets/ga_runtime/webui/integrations.js', b'url=' + relay)           # not the declared preset
