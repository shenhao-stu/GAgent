import asyncio
import json
from pathlib import Path
import sys
import types

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'app/src/main/assets/gacore'))
import service_config
from test_pclink_credentials import load_link


@pytest.fixture
def bootstrap(tmp_path, monkeypatch):
    path = tmp_path / 'pclink_defaults.json'
    monkeypatch.setattr(service_config, 'PCLINK_DEFAULTS', path)
    monkeypatch.setattr(service_config, 'load_config', lambda: {})
    return path


def test_unconfigured_status_is_actionable_without_network(bootstrap, monkeypatch):
    link = load_link()
    monkeypatch.setattr(link, '_paired', lambda: False)
    monkeypatch.setattr(link, '_ensure_loop', lambda: pytest.fail('no pairing: no network'))
    status = json.loads(link.handle('/pclink.status'))
    assert status['ok'] == 1 and status['configured'] is False
    assert status['paired'] is False and status['signal'] == ''


def test_defaults_pair_old_code_without_user_settings(bootstrap, monkeypatch):
    default = {'url': 'wss://relay.example/ws', 'token': 'synthetic-build-token'}
    bootstrap.write_text(json.dumps(default))
    link = load_link()
    calls = []
    async def connect(url, code, **kwargs):
        calls.append((url, code, kwargs['access_key']))
        return object()
    monkeypatch.setitem(sys.modules, 'p2p_ws_client', types.SimpleNamespace(connect_code=connect))
    monkeypatch.setattr(link, '_attach', lambda socket, config: calls.append(config))
    asyncio.run(link._pair('123456789'))
    assert calls == [(default['url'], '123456789', default['token']), default]
    assert service_config.public_config() == {}  # never reveal bootstrap credential


def test_custom_endpoint_never_inherits_bootstrap_token(bootstrap, monkeypatch):
    bootstrap.write_text(json.dumps({'url': 'wss://relay.example/ws', 'token': 'synthetic-default'}))
    custom = {'url': 'wss://private.example/ws', 'token': 'synthetic-custom'}
    monkeypatch.setattr(service_config, 'load_config', lambda: {'pclink': custom})
    assert service_config.pclink_config() == custom
    with pytest.raises(ValueError, match='token'):
        service_config.merge_config({}, {'pclink': {'url': custom['url'], 'token': ''}})
    monkeypatch.setattr(service_config, 'load_config', lambda: {})
    assert service_config.pclink_config()['token'] == 'synthetic-default'


def test_invalid_bootstrap_fails_closed(bootstrap):
    bootstrap.write_text(json.dumps({'url': 'http://relay.example/ws', 'token': 'synthetic'}))
    with pytest.raises(ValueError):
        service_config.pclink_config()


def test_bootstrap_audit_exception_is_narrow():
    import importlib.util
    spec = importlib.util.spec_from_file_location('audit_bootstrap', Path(__file__).parents[1] / 'tools/audit_source.py')
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    host = 'wss://' + 'p2p.' + 'gaagent' + '.ai/ws'
    data = json.dumps({'url': host, 'token': 'synthetic-relay-token'}).encode()
    assert audit.audit_blob('assets/gacore/pclink_defaults.json', data) == []
    assert audit.audit_blob('assets/other.json', data)
    assert audit.audit_blob('assets/gacore/pclink_defaults.json', data[:-1])
    assert audit.audit_blob('assets/gacore/pclink_defaults.json', json.dumps({'url': host, 'token': 'sk-' + 'x'*30}).encode())
