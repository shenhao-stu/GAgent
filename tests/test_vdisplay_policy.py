"""Offscreen display policy: frame ownership/freshness, coordinate bounds, and launching without unreliable foreground identity guesses."""
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

PATH = Path(__file__).parents[1] / 'app/src/main/assets/ga_runtime/vdisplay.py'


def load(monkeypatch, droid):
    monkeypatch.setitem(sys.modules, 'droid', droid)
    spec = importlib.util.spec_from_file_location('vdisplay_policy_under_test', PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeDroid(ModuleType):
    def __init__(self, foreground='io.github.shenhaostu.gagent', status='DISPLAY_ID=9\nPID=42\nW=1080\nH=1920\n'):
        super().__init__('droid')
        self.foreground, self.status, self.calls = foreground, status, []

    def ping(self):
        return {'pkg': self.foreground}

    def adb_shell(self, command, **_):
        self.calls.append(command)
        if command.startswith('cat /data/local/tmp/ga_vd.status'):
            return self.status
        if command.startswith('cat /proc/42/cmdline'):
            return 'app_process\0com.ljq.ga.VdHelper'
        return ''


def test_parse_kv_ignores_partial_and_foreign_lines(monkeypatch):
    vd = load(monkeypatch, FakeDroid())
    assert vd._parse_kv('SEQ=3\nUPTIME_MS=12\nGA_CP_OK\nPID=\nW=1080x') == {'SEQ': 3, 'UPTIME_MS': 12}


def test_points_outside_virtual_display_are_rejected_before_injection(monkeypatch):
    vd = load(monkeypatch, FakeDroid())
    vd._check_point(1079, 1919, (1080, 1920))
    with pytest.raises(ValueError, match='1080x1920'):
        vd._check_point(540, 2200, (1080, 1920))   # main-screen coordinate on a shorter virtual display
    with pytest.raises(ValueError):
        vd._check_point(-1, 10, (1080, 1920))
    vd._check_point(5000, 5000, None)                # unknown size (legacy helper): no guess, no rejection


def test_frame_must_belong_to_current_helper_and_follow_last_input(monkeypatch):
    vd = load(monkeypatch, FakeDroid())
    fresh = {'SEQ': 5, 'PID': 42, 'UPTIME_MS': 10_500}
    stale = {'SEQ': 4, 'PID': 42, 'UPTIME_MS': 9_000}
    assert vd._frame_ready(fresh, 42, last_input=10.0, now=10.6, settle=1.5)
    assert not vd._frame_ready(stale, 42, last_input=10.0, now=10.6, settle=1.5)   # action's frame not on disk yet
    assert vd._frame_ready(stale, 42, last_input=10.0, now=11.6, settle=1.5)       # nothing changed on screen: deliver
    assert not vd._frame_ready({**fresh, 'PID': 7}, 42, last_input=0, now=99, settle=1.5)   # previous session's file
    assert not vd._frame_ready({}, 42, last_input=0, now=99, settle=1.5)


def test_vd_tap_rejects_out_of_bounds_without_sending_input(monkeypatch):
    droid = FakeDroid()
    vd = load(monkeypatch, droid)
    with pytest.raises(ValueError):
        vd.vd_tap(540, 2300)
    assert not [c for c in droid.calls if c.startswith('input')]
    vd.vd_tap(540, 1800)
    assert droid.calls[-1] == 'input -d 9 swipe 540 1800 540 1800 50'


def test_vd_start_uses_explicit_target_without_guessing_foreground(monkeypatch):
    droid = FakeDroid(foreground='com.android.settings')
    droid.ping = lambda: pytest.fail('foreground guesses must not control launches')
    vd = load(monkeypatch, droid)
    assert vd.vd_start('com.android.settings', activity='.Settings') == 9
    assert any('am start --display 9 -n com.android.settings/.Settings' == c for c in droid.calls)
    assert not any('force-stop' in c for c in droid.calls)


def test_vd_shot_refuses_frames_from_a_dead_helper(monkeypatch, tmp_path):
    droid = FakeDroid(status='DISPLAY_ID=9\nPID=77\nW=1080\nH=1920\n')
    vd = load(monkeypatch, droid)
    vd._vid = 9
    with pytest.raises(RuntimeError, match='helper 已退出'):
        vd.vd_shot(str(tmp_path / 'x.png'), wait=0)
