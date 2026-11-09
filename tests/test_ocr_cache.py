from test_compact_ocr import load_engine
import numpy as np


def test_exact_batch_cache(monkeypatch):
    pp = load_engine()
    monkeypatch.setattr(pp, 'REC_WORKERS', 1)
    rec = pp.TextRecognizer(cache_bytes=400000)
    original = rec.sess
    class Count:
        calls = 0
        def run(self, *args):
            self.calls += 1
            return original.run(*args)
    proxy = Count()
    rec.sess = proxy
    a = np.zeros((48, 100, 3), dtype=np.uint8)
    first = rec([a])
    assert rec([a.copy()]) == first and proxy.calls == 1
    b = a.copy(); b[20:30] = 255
    rec([b]); assert proxy.calls == 2
    # 184320-byte inputs: a third unique entry evicts the oldest.
    c = a.copy(); c[10:20] = 255
    rec([c]); assert proxy.calls == 3
    assert rec._cache_size <= rec._cache_limit
    rec([a]); assert proxy.calls == 4
    rec._cache_limit = 0
    assert rec([a]) == first and proxy.calls == 5


def test_cache_same_image_output():
    pp = load_engine()
    rec = pp.TextRecognizer()
    rng = np.random.default_rng(23)
    crops = [rng.integers(0, 256, (48, w, 3), dtype=np.uint8) for w in [100, 400, 150, 190, 210, 600, 300]]
    a = rec(crops)
    b = rec(crops)
    rec._cache_limit = 0
    c = rec(crops)
    assert a == b == c
