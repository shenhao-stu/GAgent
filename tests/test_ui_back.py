"""回退一层: 先点屏上的返回/关闭按钮, 只有真没有按钮时才按系统 back。

为什么这条要单独钉住: 小程序/自绘 canvas/H5 页面会把系统返回键吃掉(back() 按了等于没按)。
真机 2026-10-30 09:15 的三角洲会话里, 目标入口在上一级页面, 模型只会在弹窗层里点"取消/×",
6 次点击 diff 全是 85.850%(同一 bbox) —— 一步没走。这类页面唯一的出口是屏幕上那个按钮。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import droid


IMG = np.zeros((2670, 1200, 3), dtype=np.uint8)


def _box(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


class UiBackTest(unittest.TestCase):
    def _run(self, ocr_items, tap_diffs, look_items=None, back_diff='diff: 12.000% bbox=(0,0,1200,2670)'):
        calls = {'tap': [], 'back': 0}

        def fake_tap(x, y, **kw):
            calls['tap'].append((x, y))
            d = tap_diffs.pop(0) if len(tap_diffs) > 1 else tap_diffs[0]
            return {'diff': d}

        def fake_back():
            calls['back'] += 1
            return {'diff': back_diff}

        with patch.object(droid, 'shot', lambda *a, **k: IMG), \
             patch.object(droid, 'ocr', lambda img: ocr_items), \
             patch.object(droid, 'tap', fake_tap), \
             patch.object(droid, 'longpress', fake_tap), \
             patch.object(droid, 'back', fake_back), \
             patch.object(droid, 'look', lambda *a, **k: (look_items or [])):
            res = droid.ui_back()
        return res, calls

    def test_text_button_in_the_title_band_wins(self):
        res, calls = self._run([(_box(40, 200, 160, 260), '返回', 0.98),
                                (_box(900, 2400, 1000, 2500), '关闭', 0.9)],
                               ['diff: 41.200% bbox=(0,0,1200,2670)'])
        self.assertTrue(res['ok'])
        self.assertEqual(res['via'], 'button')
        self.assertEqual(res['text'], '返回')
        self.assertEqual(calls['tap'], [(100, 230)])          # 中心点
        self.assertEqual(calls['back'], 0)                    # 点到了就不按系统返回

    def test_top_band_preferred_over_bottom(self):
        res, calls = self._run([(_box(900, 2400, 1000, 2500), '关闭', 0.9),
                                (_box(40, 200, 160, 260), '返回', 0.98)],
                               ['diff: 30.000%'])
        self.assertEqual(res['text'], '返回')

    def test_closedialog_then_system_back_when_nothing_moves(self):
        res, calls = self._run([(_box(900, 2400, 1000, 2500), '关闭', 0.9)],
                               ['diff: 0.000%', 'diff: 0.010%'],
                               back_diff='diff: 0.020%')
        self.assertEqual(calls['back'], 1)                    # 按钮没让画面变 → 退系统返回
        self.assertEqual(res['via'], 'system')
        self.assertFalse(res['ok'])                           # 系统返回也没变 → 如实报告
        self.assertEqual(len(res['tried']), 1)

    def test_untitled_icon_in_the_title_band_is_used(self):
        res, calls = self._run([], ['diff: 22.000%'],
                               look_items=[{'x': 60, 'y': 210, 'cls': 'Icon'},
                                           {'x': 1100, 'y': 210, 'cls': 'Icon'}])
        self.assertEqual(calls['tap'], [(60, 210)])
        self.assertEqual(res['via'], 'button')

    def test_no_button_and_no_icon_falls_back_to_system_back(self):
        # 系统返回后整页重绘(41%): 才算退层成功
        res, calls = self._run([], ['diff: 41.000%'],
                               look_items=[{'x': 1100, 'y': 210, 'cls': 'Icon'}],
                               back_diff='diff: 41.000% bbox=(0,0,1200,2670)')
        self.assertEqual(calls['tap'], [])
        self.assertEqual(calls['back'], 1)
        self.assertTrue(res['ok'])
        self.assertIn('没有找到返回/关闭按钮', res['hint'])

    def test_small_repaint_after_system_back_is_not_a_backed_out(self):
        # 真机 15:11 的教训: 0.2%/12% 这种抖动(时钟、卡片轮播)不是退层成功; 判成功会让
        # 模型带着「已经回上一级」的错觉继续点, 判失败才会真的再退一次。
        res, calls = self._run([], ['diff: 0.000%'],
                               back_diff='diff: 12.000% bbox=(0,0,1200,2670)')
        self.assertEqual(calls['back'], 1)
        self.assertFalse(res['ok'])

    def test_paragraph_text_is_not_a_button(self):
        res, calls = self._run([(_box(10, 900, 1100, 960),
                                 '点击返回可以回到上一页并重新选择你要查看的内容', 0.9)],
                               ['diff: 40.000%'])
        self.assertEqual(calls['tap'], [])                    # 长句是正文
        self.assertEqual(calls['back'], 1)

    def test_pct_parser(self):
        self.assertEqual(droid._pct_from_diff('diff: 83.904% bbox=[0,0,1199,2669]'), 83.904)
        self.assertEqual(droid._pct_from_diff('diff: 0.000%'), 0.0)
        self.assertIsNone(droid._pct_from_diff('diff: n/a'))


class GuiActBackUsesUiBackTest(unittest.TestCase):
    def test_back_action_reports_which_way_it_went(self):
        src = (CORE / 'ga_android.py').read_text(encoding='utf-8')
        i = src.find("elif act == 'back':")
        self.assertGreater(i, 0)
        block = src[i:i + 1200]
        self.assertIn('droid.ui_back(allow_system=not _layer)', block)
        # 弹层语义(目标里出现弹窗/弹层/对话框/窗口)不许按系统返回
        self.assertIn("'弹窗'", block)
        self.assertIn("'via'", block)
        self.assertNotIn('droid.back()', block)               # 不再直接按系统返回


if __name__ == '__main__':
    unittest.main()
