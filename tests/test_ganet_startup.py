"""Optional mesh discovery must not obstruct first-run phone-only setup."""
import json
from pathlib import Path
import sys

import pytest

CORE = Path(__file__).parents[1] / 'app/src/main/assets/ga_runtime'
sys.path.insert(0, str(CORE))

import ganet
import service_config


@pytest.fixture
def phone_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv('GA_DIR', str(tmp_path))
    for name, filename in (
        ('_COMPUTERS_PATH', 'computers.json'),
        ('_BIND_PATH', 'bindings.json'),
        ('_ACTIVE_CONVO_PATH', 'active_convo'),
    ):
        monkeypatch.setattr(ganet, name, str(tmp_path / filename))

    def no_network(*args, **kwargs):
        pytest.fail('Phone-only discovery must not contact a service')

    monkeypatch.setattr(ganet, '_get', no_network)
    monkeypatch.setattr(ganet, '_post', no_network)
    return tmp_path


@pytest.mark.parametrize('command', [
    '/pc status', '/pc status ptest', '/pc list', '/ganet.devices',
])
def test_first_run_device_discovery_works_without_optional_config(phone_runtime, command):
    import android_entry

    result = json.loads(android_entry._send_for(None, command))
    assert result.get('ok') is True, result
    assert result['devices'] == []
    if command.startswith('/pc'):
        assert result['current'] is None
    assert list(phone_runtime.iterdir()) == []


def test_existing_pairing_still_requires_valid_configuration(phone_runtime):
    computer = {'deviceId': 'dev_example', 'pairingState': 'paired'}
    Path(ganet._COMPUTERS_PATH).write_text(json.dumps({'dev_example': computer}))
    with pytest.raises(ValueError, match='Configure ganet'):
        ganet.list_devices()


def test_configured_device_selection_is_preserved(phone_runtime):
    computer = {'deviceId': 'dev_example', 'pairingState': 'paired'}
    Path(ganet._COMPUTERS_PATH).write_text(json.dumps({'dev_example': computer}))
    Path(ganet._BIND_PATH).write_text(json.dumps({'ptest': 'dev_example'}))
    service_config.save_config({'ganet': {
        'url': 'https://mesh.example', 'token': 'sample-mesh-token', 'owner_id': '1',
    }})
    assert ganet.list_devices() == [computer]
    assert ganet.current_device(convo_id='ptest') == computer
