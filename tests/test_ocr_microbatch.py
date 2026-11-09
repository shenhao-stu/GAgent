"""Scheduling may change, but per-crop normalized pixels and padding must not."""
from test_compact_ocr import load_engine
import numpy as np
import pytest


@pytest.mark.parametrize('count', [0, 1, 8, 16, 17, 35])
def test_microbatch_preserves_inputs(monkeypatch, count):
    pp = load_engine()
    batches = []
    class Session:
        def get_inputs(self):
            return [type('Input', (), {'name': 'x'})()]
        def run(self, _, feeds):
            x = feeds['x']
            batches.append(x.copy())
            return np.zeros((len(x), 1), np.int64), np.ones((len(x), 1), np.float32)
    monkeypatch.setattr(pp, '_session', lambda _: Session())
    rec = pp.TextRecognizer(cache_bytes=0)
    rng = np.random.default_rng(73)
    crops = [rng.integers(0, 256, (48, 31 + 37*i, 3), dtype=np.uint8) for i in range(count)]
    rng.shuffle(crops)
    expected = []
    ratios = [c.shape[1]/c.shape[0] for c in crops]
    order = np.argsort(np.array(ratios))
    for start in range(0, count, 16):
        parent = order[start:start+16]
        width = max(320/48, *(ratios[i] for i in parent))
        expected.extend((x.shape, x.tobytes()) for x in
                        (rec._resize_norm(crops[i], width) for i in parent))
    assert rec(crops) == [('', 0.0)] * count
    actual = [(x.shape, x.tobytes()) for batch in batches for x in batch]
    assert sorted(actual) == sorted(expected)
    assert all(len(batch) <= 8 for batch in batches)
    assert rec._cache_size == 0


def test_pipeline_filters_and_coordinates():
    pp = load_engine()
    engine = pp.PPOCR.__new__(pp.PPOCR)
    def box(y, height):
        return np.array([[5, y], [55, y], [55, y+height], [5, y+height]], dtype=np.float32)
    boxes = [box(5, 5), box(20, 12), box(45, 12)]
    engine.det = lambda image: boxes
    engine.cls = None
    def recognize(crops):
        assert len(crops) == 2
        return [('keep', 0.9), ('drop', 0.1)]
    engine.rec = recognize
    rows = engine(np.zeros((100, 100, 3), dtype=np.uint8))
    assert len(rows) == 1
    assert rows[0][1:] == ('keep', 0.9)
    np.testing.assert_array_equal(rows[0][0], boxes[1].astype(int))
