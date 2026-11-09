"""Coordinate actions must remain bound to the observed display, across form factors."""
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/src/main/assets/ga_runtime'))
import droid


@pytest.mark.parametrize('w,h,rot', [(320, 480, 0), (1080, 2424, 0), (2424, 1080, 1),
                                      (1080, 2424, 2), (1840, 2208, 0), (2208, 1840, 3)])
def test_coordinates_are_physical_pixels_of_the_supplied_frame(w, h, rot):
    screen = dict(w=w, h=h, rot=rot)
    with patch.object(droid, 'ping', return_value=screen), patch.object(droid, '_act', return_value={}) as act:
        droid.tap(w - 1, h - 1, verify=False, screen=screen)
    assert act.call_args.kwargs['expected_screen'] == screen
    assert (act.call_args.kwargs['x'], act.call_args.kwargs['y']) == (w - 1, h - 1)


@pytest.mark.parametrize('current', [dict(w=2400, h=1080, rot=1), dict(w=1080, h=2400, rot=2),
                                    dict(w=1840, h=2208, rot=0)])
def test_stale_rotation_or_fold_frame_never_dispatches(current):
    previous = dict(w=1080, h=2400, rot=0)
    with patch.object(droid, 'ping', return_value=current), patch.object(droid, '_act') as act:
        with pytest.raises(RuntimeError, match='changed'):
            droid.tap(10, 10, verify=False, screen=previous)
    act.assert_not_called()


@pytest.mark.parametrize('x,y', [(-1, 1), (1080, 1), (1, 2400), (float('nan'), 1)])
def test_invalid_coordinate_never_dispatches(x, y):
    with patch.object(droid, 'ping', return_value=dict(w=1080, h=2400, rot=0)), patch.object(droid, '_act') as act:
        with pytest.raises(ValueError):
            droid.tap(x, y, verify=False)
    act.assert_not_called()


def test_capture_rejects_rotation_even_when_pixel_dimensions_stay_equal():
    frames = [dict(w=40, h=80, rot=0), dict(w=40, h=80, rot=2)]
    with patch.object(droid, 'ping', side_effect=frames), patch.object(droid, 'shot', return_value=np.zeros((80, 40, 3))):
        with pytest.raises(RuntimeError, match='changed'):
            droid.capture()


def test_capture_rejects_screenshot_from_a_different_display_shape():
    with patch.object(droid, 'ping', return_value=dict(w=40, h=80, rot=0)), patch.object(droid, 'shot', return_value=np.zeros((40, 80, 3))):
        with pytest.raises(RuntimeError, match='geometry'):
            droid.capture()


def test_scroll_does_not_reuse_coordinates_after_rotation_between_segments():
    portrait = dict(w=1080, h=2400, rot=0, pkg='com.tencent.mm')
    landscape = dict(w=2400, h=1080, rot=1, pkg='com.tencent.mm')
    with patch.object(droid, 'ping', side_effect=[portrait, portrait, landscape]), patch.object(droid, '_act', return_value={}) as act:
        with pytest.raises(RuntimeError, match='changed'):
            droid.scroll(times=2, verify=False, settle=0)
    assert act.call_count == 1


def test_full_frame_scroll_clamps_to_last_pixel_before_native_safe_margins():
    screen = dict(w=320, h=480, rot=0, pkg='com.tencent.mm')
    with patch.object(droid, 'ping', return_value=screen), patch.object(droid, '_act', return_value={}) as act:
        droid.scroll(frac=1, verify=False, settle=0)
    payload = act.call_args.kwargs
    assert 0 <= payload['y1'] < 480 and 0 <= payload['y2'] < 480


def test_tap_rotation_during_verification_is_uncertain():
    with patch.object(droid, 'ping', return_value=dict(w=40, h=80, rot=0)), \
            patch.object(droid, 'shot', side_effect=[np.zeros((80, 40, 3), np.uint8), np.zeros((40, 80, 3), np.uint8)]), \
            patch.object(droid, '_act', return_value={}):
        result = droid.tap(10, 10, wait=0)
    assert result['uncertain'] is True
    assert result['verified'] is False
