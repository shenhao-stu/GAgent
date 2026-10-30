# -*- coding: utf-8 -*-
"""软失败: 参数/命中类问题回"可行动的普通结果", 不再是 [Error] 红块。

真机实证(2026-10-29~30, 22 次会话, 45 条 `[Error]`): target 没命中 14 条、多解 6 条、
三单位二选一 5 条、状态栏 4 条、附图越界 2 条…… 真正的设备故障只有 2 条(无障碍未开)。
用户在界面上看到的就是"刚一执行就报一堆 error", 而模型还要多花一轮(5.0-5.6s)才知道该怎么改。

所以这些失败改成 SoftFail/SoftMiss: 仍是 ok:false, 但带 near(这一屏真实的近似文字)、
screen(当前屏幕)、rel_suggestion 等现场事实, 由 _do_gui_act 兜底转成普通结果。
"""
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import ga_android                                                      # noqa: E402

SCREEN = (1200, 2670)


def _box(x, y, w=200, h=40):
    return np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=np.int32)


class _Handler(object):
    """够用的 handler: 只给 gui_act 走路用到的那几个字段。"""

    def __init__(self):
        h = object.__new__(ga_android.GenericAgentHandler)
        h.working = {}
        h.history_info = []
        h.current_turn = 0
        h._gui_actions = 0
        h._task_finished = False
        h._no_tool_retries = 0
        h._vision_in_turn_attached = False
        h._see_cache = None
        h._memory_tip_shown = False
        h._last_bbox = None
        h._done_steps = []
        h._silent_exit_warned = False
        h._goal_text = ''
        h._screen_hist = None
        h._attached_img_wh = None
        h._attached_screen_wh = None
        h.parent = types.SimpleNamespace(verbose=False)
        self.h = h


def _fake(taps, ocr_items):
    return types.SimpleNamespace(
        find=lambda target, exact=False: [],
        tap=lambda x, y, **kw: (taps.append((x, y)), {'diff': 'diff: 0.000%'})[1],
        swipe=lambda *a, **k: {'diff': 'diff: 0.000%'},
        longpress=lambda *a, **k: {'diff': 'diff: 0.000%'},
        screen=lambda: SCREEN,
        ensure_fresh_obs=lambda: None,
        wait_stable=lambda **kw: {'stable': True, 'wait_for': 0.0},
        _sensitive_fg=lambda: True,
        shot=lambda: np.zeros((SCREEN[1], SCREEN[0], 3), dtype=np.uint8),
        ocr=lambda img: list(ocr_items),
        observe=lambda **kw: {'kind': 'blanked', 'items': [], 'notes': [],
                              'needs_vision': True, 'ms': 1.0},
    )


OCR = [(_box(300, 500), '三角洲行动小程序', 0.95),
       (_box(560, 300), '查看今日密码', 0.93),
       (_box(100, 900), '取消', 0.90)]


class TargetMissSoftResultTest(unittest.TestCase):

    def test_near_miss_text_is_a_match_not_an_error(self):
        # 模型把 OCR 的 '三角洲行动小程序' 写成 '三角洲行动 小程序'(多一个空格)。
        # 归一后 ratio=1.00 且远高于次名 → 直接命中, 并把 _fuzzy 写回结果。
        taps = []
        h = _Handler().h
        with patch.dict(sys.modules, {'droid': _fake(taps, OCR)}):
            out = h.do_gui_act({'action': 'tap', 'target': '三角洲行动 小程序'},
                               types.SimpleNamespace(content=''))
        self.assertEqual(len(taps), 1)
        self.assertNotIn('[Error]', out.data)
        data = json.loads(out.data)
        self.assertTrue(data.get('fuzzy') or data.get('_fuzzy') or 'fuzzy' in out.data)
        self.assertEqual(taps[0][1], 520)              # 300 + 200/2, 500 + 40/2

    def test_miss_returns_near_candidates_and_no_error(self):
        taps = []
        h = _Handler().h
        with patch.dict(sys.modules, {'droid': _fake(taps, OCR)}):
            out = h.do_gui_act({'action': 'tap', 'target': '完全不存在的东西'},
                               types.SimpleNamespace(content=''))
        self.assertEqual(taps, [])
        self.assertNotIn('[Error]', out.data)
        data = json.loads(out.data)
        self.assertFalse(data['ok'])
        self.assertTrue(data['soft'])
        self.assertEqual(data['target_miss'], '完全不存在的东西')
        self.assertIn('near', data)
        self.assertIn('上一级', data['hint'])


class PointSoftResultTest(unittest.TestCase):

    def test_status_bar_point_suggests_rel(self):
        taps = []
        h = _Handler().h
        with patch.dict(sys.modules, {'droid': _fake(taps, OCR)}):
            out = h.do_gui_act({'action': 'tap', 'point': [835, 80]},
                               types.SimpleNamespace(content=''))
        self.assertEqual(taps, [])
        self.assertNotIn('[Error]', out.data)
        data = json.loads(out.data)
        self.assertTrue(data['soft'])
        self.assertEqual(data['band'], 'status')
        self.assertEqual(len(data['rel_suggestion']), 2)

    def test_out_of_screen_point_carries_screen_size(self):
        taps = []
        h = _Handler().h
        with patch.dict(sys.modules, {'droid': _fake(taps, OCR)}):
            out = h.do_gui_act({'action': 'tap', 'point': [5000, 10]},
                               types.SimpleNamespace(content=''))
        self.assertEqual(taps, [])
        data = json.loads(out.data)
        self.assertTrue(data['soft'])
        self.assertEqual(data['screen'], list(SCREEN))

    def test_soft_failure_is_not_wrapped_as_error_in_source(self):
        src = (CORE / 'ga_android.py').read_text(encoding='utf-8')
        i = src.find('except (SoftFail, SoftMiss) as e:')
        self.assertGreater(i, 0)
        self.assertIn("'soft': True", src[i:i + 900])


class CloseForwardsStillThereTest(unittest.TestCase):
    """droid 关完会再 OCR 一次, 算出 still_there; 这个字段以前在 handler 里被丢掉了。"""

    def test_still_there_reaches_the_model(self):
        taps = []
        d = _fake(taps, OCR)
        seen = {}
        def _close(**kw):
            seen.update(kw)
            return {'ok': False, 'via': 'icon', 'text': '查看今日密码', 'point': [612, 315],
                    'diff': 'diff: 0.000%', 'tried': [{'text': '查看今日密码'}], 'still_there': True}
        d.close_dialog = _close
        h = _Handler().h
        with patch.dict(sys.modules, {'droid': d}):
            out = h.do_gui_act({'action': 'close', 'expect': '关闭今日密码弹窗'},
                               types.SimpleNamespace(content=''))
        data = json.loads(out.data)
        self.assertTrue(data['still_there'])
        self.assertNotIn('[Error]', out.data)
        # 期望文字要真的传给 droid, 否则它会拿"抖动"当"关上了"
        self.assertEqual(seen.get('expect_text'), '今日密码')


class CloseIconTargetSoftResultTest(unittest.TestCase):
    """target="X" 不能再当关闭键用: canvas 弹窗那个叉是画出来的, 文字层里没有它。"""

    def test_single_letter_x_target_is_refused_with_a_hint(self):
        taps = []
        h = _Handler().h
        with patch.dict(sys.modules, {'droid': _fake(taps, OCR)}):
            out = h.do_gui_act({'action': 'tap', 'target': 'X'},
                               types.SimpleNamespace(content=''))
        self.assertEqual(taps, [])
        self.assertNotIn('[Error]', out.data)
        data = json.loads(out.data)
        self.assertFalse(data['ok'])
        self.assertTrue(data['soft'])
        self.assertEqual(data['zone'], 'close_icon')
        self.assertIn('exit_miniapp', data['hint'])
        self.assertIn('"action":"close"', data['hint'])

    def test_letter_x_as_a_real_word_still_works(self):
        # 只拦"单字 X"; 正常文字里的 x 不受影响(例如 'Xbox')
        taps = []
        h = _Handler().h
        with patch.dict(sys.modules, {'droid': _fake(taps, [(_box(300, 500), 'Xbox', 0.9)])}):
            out = h.do_gui_act({'action': 'tap', 'target': 'Xbox'},
                               types.SimpleNamespace(content=''))
        self.assertEqual(len(taps), 1)
        self.assertNotIn('[Error]', out.data)

if __name__ == '__main__':
    unittest.main()
