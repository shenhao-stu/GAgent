import json
import os
import sys
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/ga_runtime'
sys.path.insert(0, str(CORE))
import bus_auth
import service_config as config


@pytest.fixture(autouse=True)
def private_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv('GA_DIR', str(tmp_path))
    return tmp_path


def test_unconfigured_services_make_no_network_request():
    assert config.public_config() == {}
    for service in config.SERVICES:
        with pytest.raises(ValueError, match='Configure'):
            config.get_service(service)


@pytest.mark.parametrize('url', [
    'http://service.example', 'https://user:password@service.example',
    'https://service.example?token=secret', 'https://service.example#secret',
    'https://service.example/\nHeader: value',
])
def test_unsafe_configuration_rejected_before_persistence(url):
    with pytest.raises(ValueError):
        config.save_config({'apk': {'url': url, 'token': 'test-service-token'}})
    assert not config.config_path().exists()


def test_token_never_exported_or_moved_to_a_different_host():
    config.save_config({'apk': {'url': 'https://build.example', 'token': 'test-service-token'}})
    public = config.public_config()
    assert public['apk']['has_token'] is True
    assert 'token' not in public['apk']
    config.save_config({'apk': {'url': 'https://build.example', 'token': ''}})
    assert config.get_service('apk')['token'] == 'test-service-token'
    with pytest.raises(ValueError):
        config.save_config({'apk': {'url': 'https://different.example', 'token': ''}})
    assert config.get_service('apk')['url'] == 'https://build.example'
    assert os.stat(config.config_path()).st_mode & 0o777 == 0o600
    config.save_config({'apk': {'url': ''}})
    assert config.public_config() == {}


def test_merge_does_not_mutate_callers():
    original = {'pclink': {'url': 'wss://pair.example/ws', 'token': 'sample-relay-credential'}}
    updates = {'voice': {'url': 'wss://asr.example', 'token': 'test-asr-token'}}
    snapshot = json.dumps([original, updates], sort_keys=True)
    result = config.merge_config(original, updates)
    assert json.dumps([original, updates], sort_keys=True) == snapshot
    assert result['pclink'] == original['pclink']


def test_missing_bus_capability_fails_closed_and_never_leaks_remotely(private_runtime):
    assert bus_auth.headers('https://models.example/v1') == {}
    assert bus_auth.headers('http://127.0.0.1:18766/ping') == {}
    assert bus_auth.headers('http://127.0.0.1.evil.example:18765/ping') == {}
    with pytest.raises(FileNotFoundError):
        bus_auth.headers(bus_auth.BUS_URL + '/ping')
    token = '1' * 64
    (private_runtime / '.bus_token').write_text(token)
    assert bus_auth.headers(bus_auth.BUS_URL + '/ping') == {'Authorization': 'Bearer ' + token}
    with pytest.raises(ValueError):
        bus_auth.headers('http://user:password@127.0.0.1:18765/ping')


def test_retired_commands_are_errors_without_an_agent(monkeypatch):
    import android_entry as entry
    monkeypatch.setattr(entry, 'has_key', lambda: pytest.fail('must not consult providers'))
    for command in ('/plan.status', '/billing.orders', '/points.checkin'):
        result = json.loads(entry._send_for(None, command))
        assert result['error'] == 'unknown_cmd'


def test_save_get_commands_work_without_model_credentials():
    import android_entry as entry
    request = {'pclink': {'url': 'wss://pair.example/ws', 'token': 'sample-relay-credential'}}
    assert json.loads(entry._send_for(None, '/integrations.save ' + json.dumps(request)))['ok']
    response = json.loads(entry._send_for(None, '/integrations.get'))
    assert response['pclink']['url'] == request['pclink']['url']
