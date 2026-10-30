# -*- coding: utf-8 -*-
"""附图坐标(img_point)换算: 图上的像素 ≠ 设备像素。

真机实证(run 1793267115173030065, 2026-10-29): 屏幕 1200x2670, 每轮附给主模型的截图是
647x1440, 而当时的提示词写的是"坐标按这张图的像素给 gui_act 的 point"。模型照做, 于是
`search_app` 之后每一步都点在偏左/偏上约 1.86 倍的位置, y>1440 的下半屏根本点不到 ——
用户看到的就是"能打开 App 并输入关键词, 但进了自绘页面之后漂得很厉害"。

所以坐标单位从两条变三条, 且换算归代码:
  point    = 设备像素(obs/ocr 的 x/y)
  rel      = 0-1000(See 的 rx/ry)
  img_point= 本轮附图上的像素(由 图→屏幕 比例换算)
单位仍然不猜: 三个字段只准给一个。
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
import ga_android

SCREEN = (1200, 2670)
IMAGED = (647, 1440)          # 1200x2670 按长边 1440 缩放


def _handler(img_wh=IMAGED, screen_wh=SCREEN):
    h = object.__new__(ga_android.GenericAgentHandler)
    h.history_info = ['[USER] 打开微信 搜炉石传说小程序 去看看套牌里的传说榜前三组套牌']
    h.current_turn = 3
    h.parent = types.SimpleNamespace(task_dir=None, verbose=False, _turn_end_hooks={})
    h.print = lambda *a, **k: None
    h._gui_actions = 0
    h._attached_img_wh = img_wh
    h._attached_screen_wh = screen_wh
    return h


class ResolveImgPointTest(unittest.TestCase):
    def setUp(self):
        self._p = patch.object(droid, 'screen', lambda: SCREEN)
        self._p.start()
        self.addCleanup(self._p.stop)

    def test_scales_image_pixels_to_device_pixels(self):
        h = _handler()
        # 图中心 → 屏幕中心
        self.assertEqual(h._resolve_point({'img_point': [323.5, 720]}, 'point', 'rel'),
                         (600, 1335))
        # 图的右下角 → 屏幕右下角(没有被夹死在图的尺寸里)
        x, y = h._resolve_point({'img_point': [647, 1440]}, 'point', 'rel')
        self.assertGreaterEqual(x, SCREEN[0] - 2)
        self.assertGreaterEqual(y, SCREEN[1] - 2)

    def test_lower_half_of_screen_is_reachable_from_the_image(self):
        # 旧行为: 直接把图坐标当设备像素, y 最大只有 1440, 屏幕下半部分(1440-2670)永远点不到
        h = _handler()
        _, y_low = h._resolve_point({'img_point': [300, 1430]}, 'point', 'rel')
        self.assertGreater(y_low, 2600)

    def test_requires_an_attached_screenshot(self):
        h = _handler(img_wh=None, screen_wh=None)
        with self.assertRaises(ValueError) as ctx:
            h._resolve_point({'img_point': [10, 10]}, 'point', 'rel')
        self.assertIn('img_point', str(ctx.exception))

    def test_outside_the_image_but_inside_the_screen_is_read_as_device_pixels(self):
        # 真机 2026-10-30 11:09 那次: 模型把设备像素 [680,156] 填进 img_point(图只有 647 宽)。
        # 旧行为直接报错, 白烧一轮(5-6s); 现在按设备像素用掉, 并把"我按 point 理解了"带回去。
        h = _handler()
        self.assertEqual(h._resolve_point({'img_point': [700, 100]}, 'point', 'rel'), (700, 100))
        self.assertTrue(any('设备像素' in n for n in h._unit_notes))

    def test_outside_the_screen_as_well_is_a_soft_failure(self):
        h = _handler()
        with self.assertRaises(ValueError) as ctx:
            h._resolve_point({'img_point': [5000, 5000]}, 'point', 'rel')
        self.assertIsInstance(ctx.exception, ga_android.SoftFail)
        self.assertEqual(ctx.exception.payload['img'], list(IMAGED))

    def test_takes_exactly_one_unit(self):
        h = _handler()
        with self.assertRaises(ValueError):
            h._resolve_point({'img_point': [10, 10], 'point': [600, 1200]}, 'point', 'rel')
        with self.assertRaises(ValueError):
            h._resolve_point({'img_point': [10, 10], 'rel': [500, 500]}, 'point', 'rel')

    def test_device_pixels_still_pass_through_unchanged(self):
        h = _handler()
        self.assertEqual(h._resolve_point({'point': [996, 211]}, 'point', 'rel'), (996, 211))

    def test_swipe_uses_img_point1_and_img_point2(self):
        h = _handler()
        self.assertEqual(h._resolve_point({'img_point1': [323.5, 720]}, 'point1', 'rel1'),
                         (600, 1335))
        self.assertEqual(h._resolve_point({'img_point2': [323.5, 720]}, 'point2', 'rel2'),
                         (600, 1335))


class TurnImageSizeTest(unittest.TestCase):
    """附图尺寸必须跟着这一轮走: 它是 img_point 的换算基准, 留着上一轮的比不留更糟。"""

    def _handler(self):
        h = object.__new__(ga_android.GenericAgentHandler)
        h.history_info = []
        h.parent = types.SimpleNamespace(task_dir=None, verbose=False, _turn_end_hooks={})
        h.print = lambda *a, **k: None
        h._vision_in_turn_attached = False
        h._attached_img_wh = (647, 1440)          # 上一轮残留
        h._attached_screen_wh = SCREEN
        h._vision_mode = lambda: 'auto'
        h._session_takes_images = lambda: True
        h._vision_covers_screen = lambda: True
        return h

    def test_attached_size_and_units_are_reported(self):
        img = np.zeros((2670, 1200, 3), np.uint8)
        h = self._handler()

        def fake_b64(max_side=1440, quality=70):
            return 'BASE64', (647, 1440)

        with patch.object(droid, 'shot_frame_b64', fake_b64), \
                patch.object(droid, 'screen', lambda: SCREEN):
            blocks = h.turn_content_blocks()
        self.assertIsNotNone(blocks)
        text = blocks[0]['text']
        self.assertEqual(h._attached_img_wh, (647, 1440))
        self.assertEqual(h._attached_screen_wh, SCREEN)
        self.assertIn('img_point', text)
        self.assertIn('1200x2670', text)
        self.assertIn('647x1440', text)

    def test_previous_turn_size_is_cleared_when_no_image_is_attached(self):
        h = self._handler()
        h._session_takes_images = lambda: False
        self.assertIsNone(h.turn_content_blocks())
        self.assertIsNone(h._attached_img_wh)
        self.assertIsNone(h._attached_screen_wh)

    def test_image_pixels_hint_replaces_the_old_lie(self):
        """obs_note 曾写"直接按图里的位置给 point" —— 那就是这次偏移的说明书写者。"""
        src = Path(ga_android.__file__).read_text(encoding='utf-8')
        self.assertNotIn('直接按图里的位置给 point', src)
        self.assertNotIn('坐标按这张图的像素给 gui_act 的 point', src)


class CoordSpaceHintTest(unittest.TestCase):
    """点了没变时, 要能问出"你是不是从附图量的坐标" —— 这是突然出现的高频静默失败。"""

    def test_hint_points_at_img_point_when_tap_did_nothing(self):
        h = _handler()
        out = {'diff': 'diff: 0.010% bbox=[431, 211, 435, 277]'}
        hint = h._coord_space_hint({'point': [350, 210]}, out)
        self.assertIn('img_point', hint)
        self.assertIn('647x1440', hint)

    def test_silent_when_the_tap_changed_the_screen(self):
        h = _handler()
        self.assertIsNone(h._coord_space_hint({'point': [350, 210]}, {'diff': 'diff: 25.172%'}))

    def test_silent_without_an_attached_image(self):
        h = _handler(img_wh=None, screen_wh=None)
        self.assertIsNone(h._coord_space_hint({'point': [350, 210]}, {'diff': 'diff: 0.010%'}))

    def test_silent_for_device_pixels_outside_the_image(self):
        h = _handler()
        self.assertIsNone(h._coord_space_hint({'point': [996, 211]}, {'diff': 'diff: 0.010%'}))

    def test_silent_when_rel_was_used(self):
        h = _handler()
        self.assertIsNone(h._coord_space_hint({'rel': [830, 79]}, {'diff': 'diff: 0.010%'}))


if __name__ == '__main__':
    unittest.main()
