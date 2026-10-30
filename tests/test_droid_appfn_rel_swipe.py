"""Offline regressions for the droid adapters added with the stepOS wave:
normalized tap (tap_rel), swipe post-action settle, and AppFunction shell calls.
All fixtures are synthetic; no device, bus, or model is touched."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import droid


PING = {'ver': 1, 'w': 1000, 'h': 2000, 'rot': 0, 'pkg': 'com.example.app'}


class TapRelTest(unittest.TestCase):
    def converts_with_the_observed_screen(self, rx, ry, expected):
        with patch.object(droid, 'screen', return_value=(1000, 2000)), patch.object(droid, 'tap', return_value={}) as tap:
            droid.tap_rel(rx, ry)
        tap.assert_called_once_with(*expected)

    def test_conversion_uses_observed_size_minus_one(self):
        self.converts_with_the_observed_screen(250, 750, (250, 1499))   # round(.25*999), round(.75*1999)

    def test_boundaries_map_to_screen_corners(self):
        self.converts_with_the_observed_screen(0, 0, (0, 0))
        self.converts_with_the_observed_screen(1000, 1000, (999, 1999))

    def test_forwards_tap_options_verbatim(self):
        with patch.object(droid, 'screen', return_value=(1000, 2000)), patch.object(droid, 'tap', return_value={}) as tap:
            droid.tap_rel(500, 500, wait=2, verify=False, human=True)
        tap.assert_called_once_with(500, 1000, wait=2, verify=False, human=True)

    def test_out_of_range_and_non_numeric_rejected(self):
        for args in ((1001, 500), (-1, 500), ('a', 500), (True, 500)):
            with patch.object(droid, 'screen', return_value=(1000, 2000)), patch.object(droid, 'tap') as tap:
                with self.assertRaises(ValueError):
                    droid.tap_rel(*args)
            tap.assert_not_called()

    def test_unknown_screen_size_fails_explicitly(self):
        with patch.object(droid, 'screen', return_value=(0, 0)), patch.object(droid, 'tap') as tap:
            with self.assertRaisesRegex(RuntimeError, '屏幕尺寸未知'):
                droid.tap_rel(500, 500)
        tap.assert_not_called()


class SwipeSettleTest(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((50, 100, 3), dtype=np.uint8)
        for name, value in (('ping', dict(PING, w=100, h=50)), ('shot', self.frame),
                            ('_act', {'ok': True, 'seq': 1}), ('_fg', 'com.example.app')):
            ctx = patch.object(droid, name, return_value=value); ctx.start(); self.addCleanup(ctx.stop)
        ctx = patch.object(droid, '_track'); self.tracker = ctx.start(); self.addCleanup(ctx.stop)

    def test_unchanged_screen_reports_miss_hint(self):
        ret = droid.swipe(10, 10, 20, 20, wait=0)
        self.assertTrue(ret['diff'].startswith('diff: 0.000%'))
        self.assertIn('没滚成', ret['hint'])
        self.assertEqual(ret['fg'], 'com.example.app')
        self.tracker.assert_called_once_with('droid_swipe_miss', {'diff_pct': 0.0})

    def test_changed_screen_has_no_hint(self):
        with patch.object(droid, 'shot', side_effect=[self.frame, self.frame + 30]):
            ret = droid.swipe(10, 10, 20, 20, wait=0)
        self.assertNotIn('hint', ret)
        self.assertFalse(ret['diff'].startswith('diff: 0.000%'))

    def test_shape_change_is_uncertain_not_success(self):
        with patch.object(droid, 'shot', side_effect=[self.frame, np.zeros((100, 50, 3), dtype=np.uint8)]):
            ret = droid.swipe(10, 10, 20, 20, wait=0)
        self.assertTrue(ret['uncertain'])
        self.assertFalse(ret['verified'])

    def test_verify_false_dispatches_without_either_frame(self):
        with patch.object(droid, 'shot') as shot:
            ret = droid.swipe(10, 10, 20, 20, verify=False)
        shot.assert_not_called()
        self.assertNotIn('diff', ret)

    def test_out_of_bounds_swipe_is_rejected_before_dispatch(self):
        with patch.object(droid, '_act') as act:
            with self.assertRaises(ValueError):
                droid.swipe(0, 0, 200, 25)   # x2=200 > observed w=100
        act.assert_not_called()

    def test_scroll_keeps_per_segment_settle_disabled(self):
        # scroll 自带稳态证据; 段内 swipe 必须关掉自带后验, 否则 times 段=2×times 次多余截图
        with patch.object(droid, 'swipe', return_value={'ok': True}) as swipe, \
             patch.object(droid, 'dump', return_value=[]), \
             patch.object(droid, '_resolve_fg', return_value='com.example.app'), \
             patch.object(droid, '_sensitive_fg', return_value=False):
            droid.scroll('up', times=2, settle=0, verify=False)
        self.assertFalse(swipe.call_args.kwargs.get('verify', True))


class AppfnTest(unittest.TestCase):
    def test_list_passes_command_and_parses_json(self):
        with patch.object(droid, 'adb_shell', return_value='[{"package": "com.x", "functionId": "a.B#c"}]') as shell:
            self.assertEqual(droid.appfn_list(), [{'package': 'com.x', 'functionId': 'a.B#c'}])
        self.assertEqual(shell.call_args.args[0], 'cmd app_function list-app-functions')

    def test_list_tolerates_surrounding_noise_lines(self):
        with patch.object(droid, 'adb_shell', return_value='Warning: something\n[{"a": 1}]\n'):
            self.assertEqual(droid.appfn_list(), [{'a': 1}])   # 提取首个 JSON 体(含方括号)原样返回

    def test_list_user_must_be_number_or_current(self):
        with patch.object(droid, 'adb_shell', return_value='[]') as shell:
            with self.assertRaises(ValueError):
                droid.appfn_list(user='all; rm -rf')
            droid.appfn_list(user='0')
        shell.assert_called_once()
        self.assertIn('--user 0', shell.call_args.args[0])

    def test_non_json_output_is_an_error_not_an_empty_list(self):
        with patch.object(droid, 'adb_shell', return_value='Error: function not found'):
            with self.assertRaisesRegex(RuntimeError, '不是 JSON'):
                droid.appfn_list()

    def test_call_builds_shell_safe_command(self):
        with patch.object(droid, 'adb_shell', return_value='{"ok": true}') as shell:
            self.assertEqual(droid.appfn_call('com.example.store', 'com.example.fn.Store#searchApp',
                                              {'keyword': '微信'}), {'ok': True})
        expected = ('cmd app_function execute-app-function --package \'com.example.store\''
                    ' --function \'com.example.fn.Store#searchApp\''
                    ' --parameters \'{"keyword": "\\u5fae\\u4fe1"}\'')
        self.assertEqual(shell.call_args.args[0], expected)
        self.assertNotIn('微信', shell.call_args.args[0])   # 中文转 \uXXXX: 纯 ASCII 过 shell 通道

    def test_call_escapes_single_quotes_in_parameters(self):
        with patch.object(droid, 'adb_shell', return_value='{}') as shell:
            droid.appfn_call('com.example.app', 'a.B#c', {'q': "it's"})
        expected_payload = "'" + '{"q": "it' + "'\\''" + 's"}' + "'"
        self.assertIn('--parameters ' + expected_payload, shell.call_args.args[0])

    def test_call_rejects_bad_inputs_without_touching_shell(self):
        for args in (('rm -rf', 'a.B#c'), ('com.x', 'a.Bc'), ('com.x', 'a.B#c', 'notdict')):
            with patch.object(droid, 'adb_shell') as shell:
                with self.assertRaises(ValueError):
                    droid.appfn_call(*args)
            shell.assert_not_called()


if __name__ == '__main__':
    unittest.main()
