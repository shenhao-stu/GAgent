"""The native swipe response acknowledges dispatch before the gesture ends."""
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'app/src/main/assets/ga_runtime'))
import droid


@pytest.fixture(params=[True, False], ids=['visual', 'nodes'])
def asynchronous_screen(monkeypatch, request):
    monkeypatch.setattr(droid, 'SAFE_MODE', request.param)
    state = {'now': 0.0, 'ends_at': 0.0, 'actions': [], 'observations': []}
    screen = dict(w=120, h=240, rot=0, pkg='com.android.settings')

    def dispatch(**body):
        assert state['now'] >= state['ends_at'], 'new gesture cancels the active one'
        state['ends_at'] = state['now'] + body['dur'] / 1000.0
        state['actions'].append(body)
        return {'ok': True}

    def sleep(seconds):
        state['now'] += seconds

    def observe(kind):
        if state['actions']:
            state['observations'].append((kind, state['now']))
        return bool(state['actions'])

    def dump():
        prefix = 'after' if observe('dump') else 'before'
        return [{'t': prefix + str(i)} for i in range(4)]

    def shot(**kwargs):
        return np.full((240, 120, 3), 255 if observe('shot') else 0, dtype=np.uint8)

    monkeypatch.setattr(droid, 'ping', lambda: dict(screen))
    def policy(path, **kwargs):
        assert path == '/a11y/policy'
        return {'visual_only': False}
    monkeypatch.setattr(droid, '_get', policy)
    monkeypatch.setattr(droid, '_act', dispatch)
    monkeypatch.setattr(droid, 'dump', dump)
    monkeypatch.setattr(droid, 'shot', shot)
    monkeypatch.setattr(droid.time, 'sleep', sleep)
    return state


@pytest.mark.parametrize('duration,settle', [(2000, .5), (260, 0)])
def test_scroll_observes_after_gesture_duration_and_settlement(asynchronous_screen, duration, settle):
    state = asynchronous_screen
    result = droid.scroll('up', dur=duration, settle=settle)
    assert result['scrolled'] is True
    assert {kind for kind, _ in state['observations']} == ({'shot'} if droid.SAFE_MODE else {'dump', 'shot'})
    assert all(at >= state['ends_at'] + settle for _, at in state['observations'])


def test_scroll_segments_do_not_cancel_each_other_without_verification(asynchronous_screen):
    result = droid.scroll('down', dur=900, times=2, verify=False, settle=0)
    assert len(asynchronous_screen['actions']) == 2
    assert asynchronous_screen['now'] >= asynchronous_screen['ends_at']
    assert result['performed'] is True
    assert result['verified'] is False


@pytest.mark.parametrize('finger,view,axis,sign', [
    ('up', 'down', 'y', -1), ('down', 'up', 'y', 1),
    ('left', 'right', 'x', -1), ('right', 'left', 'x', 1),
])
@pytest.mark.parametrize('verified', [True, False])
def test_scroll_feedback_distinguishes_finger_and_view_direction(
        asynchronous_screen, finger, view, axis, sign, verified):
    result = droid.scroll(finger, verify=verified)
    action = asynchronous_screen['actions'][0]
    assert (action[axis + '2'] - action[axis + '1']) * sign > 0
    assert result['finger_direction'] == finger
    assert result['view_direction'] == view
    # Direction is dispatch metadata, not proof of progress.
    if not verified:
        assert result['verified'] is False


def test_uncertain_scroll_still_reports_dispatched_direction(asynchronous_screen, monkeypatch):
    monkeypatch.setattr(droid, 'dump', lambda: [])
    monkeypatch.setattr(droid, 'shot', lambda **kwargs: None)
    result = droid.scroll('down')
    assert result['scrolled'] is False and result['uncertain'] is True
    assert result['finger_direction'] == 'down'
    assert result['view_direction'] == 'up'


@pytest.mark.parametrize('view,axis,sign', [
    ('down', 'y', -1), ('up', 'y', 1),
    ('right', 'x', -1), ('left', 'x', 1),
])
def test_scroll_view_moves_toward_requested_content(asynchronous_screen, view, axis, sign):
    result = droid.scroll_view(view, dur=900, frac=.2)
    action = asynchronous_screen['actions'][0]
    assert (action[axis + '2'] - action[axis + '1']) * sign > 0
    assert action['dur'] == 900
    assert result['view_direction'] == view
    assert result['scrolled'] is True
    assert result['evidence'] == ('pixel' if droid.SAFE_MODE else 'text')


def test_scroll_view_keeps_missing_observation_uncertain(asynchronous_screen, monkeypatch):
    monkeypatch.setattr(droid, 'dump', lambda: [])
    monkeypatch.setattr(droid, 'shot', lambda **kwargs: None)
    result = droid.scroll_view()
    assert result['view_direction'] == 'down'
    assert result['scrolled'] is False and result['uncertain'] is True


def test_scroll_view_rejects_invalid_direction_before_dispatch(asynchronous_screen):
    with pytest.raises(ValueError, match='direction'):
        droid.scroll_view('diagonal')
    assert asynchronous_screen['actions'] == []
