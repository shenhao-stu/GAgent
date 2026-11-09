import json
from pathlib import Path
import sys

import pytest
CORE = Path(__file__).parents[1] / 'app/src/main/assets/ga_runtime'
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


def _detector_module(monkeypatch):
    # The restoration math is pure; stub the inference engines so this runs without onnxruntime.
    import importlib.util, types
    monkeypatch.setitem(sys.modules, 'onnxruntime', types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'ppocr_engine', types.SimpleNamespace(PPOCR=object))
    spec = importlib.util.spec_from_file_location('ui_detect_lite_under_test', CORE / 'models/ui_detect_v1/ui_detect_lite.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_detections_are_restored_into_the_observed_image(monkeypatch):
    lite = _detector_module(monkeypatch)
    # Portrait 1080x2340 → r=640/2340; a synthetic x padding of 32 exercises the left offset, y is unpadded.
    r, left, top, w, h = 640 / 2340, 32, 0, 1080, 2340
    rows = [[32 + 10 * r, 0 + 20 * r, 32 + 110 * r, 0 + 220 * r, 0.9, 8],   # inside
            [20, -6, 600, 300, 0.8, 11],                                      # crosses top/left padding
            [700, 10, 720, 30, 0.7, 8],                                       # entirely right of image
            [40, 40, 60, 60, 0.1, 8]]                                         # below confidence
    boxes = lite._restore(rows, 0.25, r, left, top, w, h)
    assert len(boxes) == 2
    assert [round(v) for v in boxes[0][:4]] == [10, 20, 110, 220]
    assert all(0 <= b[0] < b[2] <= w and 0 <= b[1] < b[3] <= h for b in boxes)
