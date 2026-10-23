import json
from pathlib import Path
import sys

import pytest
CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import detector_models as detector


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv('GA_DIR', str(tmp_path))
    (tmp_path / 'uploads').mkdir()
    return tmp_path


def test_invalid_model_does_not_replace_working_model(runtime, monkeypatch):
    old = runtime / 'user_models/known.onnx'
    old.parent.mkdir();old.write_bytes(b'previous model')
    (runtime / 'kv').mkdir();config=runtime / 'kv/ga.detector.json'
    config.write_text(json.dumps({'file':old.name}))
    upload = runtime / 'uploads/bad.onnx';upload.write_bytes(b'invalid graph')
    monkeypatch.setattr(detector, 'validate_model', lambda p: (_ for _ in ()).throw(ValueError('invalid graph')))
    with pytest.raises(ValueError): detector.install(str(upload))
    assert detector.model_path() == old
    assert list(old.parent.iterdir()) == [old]
    assert upload.exists()


def test_validated_model_is_selected_and_upload_removed(runtime, monkeypatch):
    upload=runtime/'uploads/test.onnx';upload.write_bytes(b'synthetic model')
    checked=[];monkeypatch.setattr(detector,'validate_model',lambda p: checked.append(p.read_bytes()))
    result=detector.install(str(upload))
    assert result['installed'] and checked == [b'synthetic model']
    assert detector.model_path().read_bytes() == b'synthetic model'
    assert not upload.exists()
    assert len(result['sha256']) == 64


def test_import_rejects_non_upload_and_escaping_active_path(runtime):
    path=runtime/'outside.onnx';path.write_bytes(b'model')
    with pytest.raises(ValueError,match='uploaded'):detector.install(str(path))
    (runtime/'kv').mkdir();(runtime/'kv/ga.detector.json').write_text('{"file":"../outside.onnx"}')
    with pytest.raises(ValueError,match='invalid'):detector.model_path()


def test_status_is_usable_without_provider_or_model(runtime):
    assert detector.status() == {'ok':True,'installed':False,'bytes':0}
