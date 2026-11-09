"""Compact OCR must preserve exact top-1 values and existing CTC behavior."""
from pathlib import Path
import importlib.util
import numpy as np
import pytest

ort = pytest.importorskip('onnxruntime')
pytest.importorskip('cv2')
ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'app/src/main/assets/ga_runtime/models/ui_detect_v1/ppocr_engine.py'
MODELS = ENGINE.parent / 'models'


def load_engine():
    spec = importlib.util.spec_from_file_location('compact_ocr_test_engine', ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def sessions():
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    return tuple(ort.InferenceSession(str(MODELS / name), options,
                                     providers=['CPUExecutionProvider']) for name in
                 ['ch_PP-OCRv4_rec_infer.onnx', 'ch_PP-OCRv4_rec_compact.onnx'])


@pytest.mark.parametrize('shape', [(1, 3, 48, 64), (2, 3, 48, 320), (4, 3, 48, 480)])
def test_exact_outputs_and_decode(sessions, shape):
    original, compact = sessions
    x = np.random.default_rng(42).uniform(-1, 1, shape).astype(np.float32)
    probabilities = original.run(None, {original.get_inputs()[0].name: x})[0]
    ids, scores = compact.run(None, {compact.get_inputs()[0].name: x})
    np.testing.assert_array_equal(ids, probabilities.argmax(axis=2))
    np.testing.assert_array_equal(scores, probabilities.max(axis=2))
    assert ids.nbytes + scores.nbytes < probabilities.nbytes / 2000
    recognizer = load_engine().TextRecognizer.__new__(load_engine().TextRecognizer)
    recognizer.character = ['blank'] + (MODELS / 'rec_keys.txt').read_text('utf-8').splitlines() + [' ']
    for p, i, s in zip(probabilities, ids, scores):
        assert recognizer._ctc_decode(p) == recognizer._ctc_decode_top1(i, s)


def test_model_selection_and_legacy_fallback(monkeypatch):
    pp = load_engine()
    selected = []
    class FakeSession:
        def get_inputs(self):
            return [type('Input', (), {'name': 'x'})()]
    monkeypatch.setattr(pp, '_session', lambda name: selected.append(name) or FakeSession())
    assert pp.TextRecognizer().compact
    assert selected[-1] == 'ch_PP-OCRv4_rec_compact.onnx'
    assert not pp.TextRecognizer(compact=False).compact
    assert selected[-1] == 'ch_PP-OCRv4_rec_infer.onnx'
    monkeypatch.setattr(pp.os.path, 'isfile', lambda path: False)
    assert not pp.TextRecognizer().compact
    assert selected[-1] == 'ch_PP-OCRv4_rec_infer.onnx'


def test_ctc_blank_repeat_and_tie():
    pp = load_engine()
    rec = pp.TextRecognizer.__new__(pp.TextRecognizer)
    rec.character = ['blank', 'a', 'b']
    p = np.array([[0, 1, 0], [0, 1, 0], [1, 0, 0], [0, 1, 0],
                  [0, 0.5, 0.5], [0, 0, 1]], dtype=np.float32)
    assert rec._ctc_decode(p)[0] == 'aab'
    assert rec._ctc_decode(p) == rec._ctc_decode_top1(p.argmax(1), p.max(1))
