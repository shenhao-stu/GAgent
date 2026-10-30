"""视觉型 App 的输入必须是"一次工具调用": 剪贴板 + 可见 GUI 粘贴 + 回读确认。

真机实证(微信搜索页, adb 直驱): 旧实现只把文本塞进剪贴板就返回 needs_gui_paste,
"长按输入框→点粘贴菜单/键盘剪贴板候选"全甩给模型, 每输入一次多花 2 轮(5 个任务里 4 个踩到)。
候选的位置随输入法/App 变, 所以判据只能来自当帧画面(OCR 行), 不能写死坐标——本文件锁三件事:
  ① 挑目标纯函数的优先级与防误判(搜索结果里的同样文字不是候选);
  ② _gui_paste 真的把两次手势 + 一次回读做完, 并在失败时保住旧契约(needs_gui_paste);
  ③ 截屏复用/条件等待不会退化成固定 sleep。
"""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import droid


def _box(cx, cy, w=200, h=60):
    return [[cx - w // 2, cy - h // 2], [cx + w // 2, cy - h // 2],
            [cx + w // 2, cy + h // 2], [cx - w // 2, cy + h // 2]]


class PickPasteTargetTest(unittest.TestCase):
    H = 2670

    def test_paste_menu_is_recognised_by_label(self):
        self.assertTrue(droid._is_paste_label('粘贴'))
        self.assertTrue(droid._is_paste_label('  粘貼 '))
        self.assertTrue(droid._is_paste_label('Paste'))
        self.assertFalse(droid._is_paste_label('粘贴板设置'))   # 子串不算, 免得点进设置
        self.assertFalse(droid._is_paste_label(''))

    def test_menu_below_the_anchor_wins_over_the_keyboard_chip(self):
        rows = [(_box(228, 434), '粘贴', 0.99),
                (_box(257, 1773), '炉石传说', 0.99)]
        kind, box, label = droid._pick_paste_target('炉石传说', rows, self.H, anchor=(600, 244))
        self.assertEqual((kind, label), ('menu', '粘贴'))

    def test_keyboard_chip_is_used_when_no_menu_is_open(self):
        rows = [(_box(257, 1773), '炉石传说', 0.99)]
        kind, box, label = droid._pick_paste_target('炉石传说', rows, self.H, anchor=(600, 244))
        self.assertEqual((kind, label), ('chip', '炉石传说'))
        self.assertEqual(box, _box(257, 1773))

    def test_same_text_above_the_keyboard_is_not_a_chip(self):
        """搜索结果里同样有这个名字, 只是 y 在上半屏: 点它会把页面点走。"""
        rows = [(_box(306, 528), '炉石传说', 0.99)]
        self.assertIsNone(droid._pick_paste_target('炉石传说', rows, self.H, anchor=(600, 244)))

    def test_menu_far_from_the_anchor_is_ignored(self):
        """锚点在底部输入框, 顶部那条"粘贴"不属于本次长按。"""
        rows = [(_box(600, 120), '粘贴', 0.99)]
        self.assertIsNone(droid._pick_paste_target('你好', rows, self.H, anchor=(600, 2400)))

    def test_empty_rows(self):
        self.assertIsNone(droid._pick_paste_target('x', [], self.H))


class GuiPasteFlowTest(unittest.TestCase):
    """_gui_paste 的行为: 手势序列 + 回读 + 失败时的旧契约。"""

    def setUp(self):
        self.acts = []
        self.frames = []
        self.ocr_by_call = []
        self.calls = {'shot': 0, 'ocr': 0}

    def _shot(self):
        idx = min(self.calls['shot'], len(self.frames) - 1)
        self.calls['shot'] += 1
        return self.frames[idx]

    def _ocr(self, img, x1, y1, x2, y2):
        idx = min(self.calls['ocr'], len(self.ocr_by_call) - 1)
        self.calls['ocr'] += 1
        return self.ocr_by_call[idx]

    def _act(self, **kw):
        self.acts.append(kw)
        return {}

    def _run(self, text='炉石传说', anchor=(600, 244), replace=False):
        self.frames = [np.zeros((2670, 1200, 3), np.uint8) for _ in range(4)]
        with patch.object(droid, '_act', self._act), \
                patch.object(droid, 'shot', self._shot), \
                patch.object(droid, '_ocr_region', self._ocr), \
                patch.object(droid.time, 'sleep', lambda s: None):
            return droid._gui_paste(text, anchor=anchor, replace=replace)

    def test_chip_tap_lands_in_one_call(self):
        self.ocr_by_call = [
            [(_box(257, 1773), '炉石传说', 0.99)],          # 第一次读屏: 键盘候选
            [(_box(328, 244), '炉石传说', 0.98)],           # 点击后回读: 框里已有文本
        ]
        ret = self._run()
        self.assertTrue(ret['hit'])
        self.assertEqual(ret['paste_via'], 'chip')
        self.assertEqual([a['op'] for a in self.acts], ['clipboard', 'tap'])
        self.assertEqual((self.acts[1]['x'], self.acts[1]['y']), (257, 1773))
        self.assertEqual(ret['text'], '炉石传说')

    def test_longpress_opens_the_menu_then_taps_it(self):
        self.ocr_by_call = [
            [],                                              # 当帧没有粘贴入口
            [(_box(228, 434), '粘贴', 0.99)],                # 长按后浮出菜单
            [(_box(328, 244), '炉石传说', 0.98)],            # 回读
        ]
        ret = self._run()
        self.assertTrue(ret['hit'])
        self.assertEqual(ret['paste_via'], 'menu')
        self.assertEqual([a['op'] for a in self.acts], ['clipboard', 'swipe', 'tap'])
        self.assertEqual(self.acts[1]['dur'], 800)           # 长按 = 同点 swipe
        self.assertIn('longpress', ret['steps'])

    def test_failure_keeps_the_needs_gui_paste_contract(self):
        self.ocr_by_call = [[]]
        ret = self._run(anchor=None)
        self.assertFalse(ret['hit'])
        self.assertTrue(ret['uncertain'])
        self.assertTrue(ret['needs_gui_paste'])
        self.assertIn('剪贴板', ret['hint'])
        self.assertEqual([a['op'] for a in self.acts], ['clipboard'])   # 没锚点就不乱长按

    def test_tap_without_confirmation_is_not_reported_as_a_hit(self):
        self.ocr_by_call = [
            [(_box(257, 1773), '炉石传说', 0.99)],
            [],                                              # 点了但框里没看到
        ]
        ret = self._run()
        self.assertFalse(ret['hit'])
        self.assertTrue(ret['uncertain'])
        self.assertIn('炉石传说', ret['hint'])        # 说清点的是哪个入口, 便于下一步判断


class WaitChangeTest(unittest.TestCase):
    """动作后取帧: 首帧变了立刻返回, 不陪跑到固定 1s。"""

    def test_returns_the_changed_frame(self):
        before = np.zeros((100, 100, 3), np.uint8)
        after = np.full((100, 100, 3), 255, np.uint8)
        shots = []

        def _shot():
            shots.append(1)
            return after

        with patch.object(droid, 'shot', _shot), patch.object(droid.time, 'sleep', lambda s: None):
            img, pct = droid._wait_change(before, max_s=1.0)
        self.assertIs(img, after)
        self.assertGreater(pct, 0)
        self.assertEqual(len(shots), 1)          # 只截一次, 不再多轮轮询

    def test_shot_failure_does_not_raise(self):
        with patch.object(droid, 'shot', lambda: (_ for _ in ()).throw(RuntimeError('code=3'))), \
                patch.object(droid.time, 'sleep', lambda s: None):
            img, pct = droid._wait_change(np.zeros((10, 10, 3), np.uint8), max_s=0.2)
        self.assertIsNone(img)
        self.assertEqual(pct, 0.0)


class ObserveFrameReuseTest(unittest.TestCase):
    """observe(img=...) 复用动作后验帧: 一次动作只该截一次后帧(截屏有最小间隔)。"""

    def test_given_frame_is_not_re_shot(self):
        frame = np.zeros((2670, 1200, 3), np.uint8)
        frame[:] = 7
        shots = []

        def _shot():
            shots.append(1)
            return np.zeros((2670, 1200, 3), np.uint8)

        with patch.object(droid, 'shot', _shot), \
                patch.object(droid, 'dump_state', lambda: {'pkg': 'com.tencent.mm', 'nodes': []}), \
                patch.object(droid, 'ping', lambda: {'w': 1200, 'h': 2670, 'rot': 0}), \
                patch.object(droid, 'ui_detect', lambda *a, **k: []), \
                patch.object(droid, '_detect_note', lambda: ''):
            droid._OBS_CACHE.update(res=None, thumb=None, roi=None, pkg=None, rot=None)
            res = droid.observe(img=frame)
        self.assertEqual(shots, [])
        self.assertIn('kind', res)

    def test_pending_frame_is_one_shot(self):
        frame = np.zeros((4, 4, 3), np.uint8)
        droid._stash_frame(frame)
        self.assertIs(droid.take_pending_frame(), frame)
        self.assertIsNone(droid.take_pending_frame())     # 取走即失效, 不会喂过期画面


if __name__ == '__main__':
    unittest.main()
