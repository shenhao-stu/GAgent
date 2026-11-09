"""Consecutive visual observations must not waste a planner turn on rate limits."""
from pathlib import Path
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'app/src/main/assets/ga_runtime'))
import droid


@pytest.mark.parametrize('prefix', ['', 'java.lang.RuntimeException: '])
def test_back_to_back_observations_receive_fresh_frames(monkeypatch, prefix):
    clock = [0.0]
    requests = []

    def get(path, **kwargs):
        assert path == '/a11y/shot'
        requests.append(clock[0])
        if len(requests) > 1 and clock[0] - requests[-2] < .333:
            raise RuntimeError(prefix + 'takeScreenshot failed code=3')
        pixels = np.full((8, 12, 3), 80 + len(requests), dtype=np.uint8)
        return cv2.imencode('.png', pixels)[1].tobytes()

    monkeypatch.setattr(droid, '_get', get)
    monkeypatch.setattr(droid, '_LAST_SHOT', float('-inf'))
    monkeypatch.setattr(droid.time, 'time', lambda: clock[0])
    monkeypatch.setattr(droid.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    first = droid.shot()
    second = droid.shot()
    assert len(requests) == 2
    assert .333 <= clock[0] <= .5
    assert not np.array_equal(first, second), 'a cached screenshot is not a fresh observation'


@pytest.mark.parametrize('message,attempts', [
    ('java.lang.RuntimeException: takeScreenshot failed code=3', 2),
    ('takeScreenshot failed code=4', 1),
    ('screenshot timeout', 1),
])
def test_unavailable_capture_remains_an_explicit_bounded_failure(monkeypatch, message, attempts):
    calls = []

    def get(*args, **kwargs):
        calls.append(1)
        raise RuntimeError(message)

    monkeypatch.setattr(droid, '_get', get)
    monkeypatch.setattr(droid.time, 'sleep', lambda seconds: None)
    with pytest.raises(RuntimeError, match=message):
        droid.shot()
    assert len(calls) == attempts
