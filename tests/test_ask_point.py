# -*- coding: utf-8 -*-
"""ask_point: 把"屏幕上某个东西在哪"固定成 0-1000 一问一答。

回归来源(真机 1200x2670, 2026-10-27):
- 17:48: 模型自己写的问句是"…占屏幕宽和高的**百分比**, 0-1000 归一化坐标"——百分数与
  千分比混在一句话里。VLM 回了一段自相矛盾的散文("靠右边距 15% 即 85% 位置"、又讲
  "左边缘约 10% 约 90% 位置")。模型乘 10 得 850、又猜了 y=45, 当 point 传进 gui_act →
  实际点 (1020,120) 状态栏, 搜索页从未打开, 而模型只看到 diff 29% 以为成功了。
- 17:57: 同一条路上 ask_vision 30s 读超时后按 max_retries=4 重试, 60.285s 被 code_run
  强杀并留下僵尸线程, 任务直接废掉。

所以这里把三件事定死: 提问词固定、单位只认 0-1000、百分号一律拒。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import droid
import geom


def _img():
    return np.zeros((40, 40, 3), dtype=np.uint8)


class ParsePointTest(unittest.TestCase):
    def test_plain_pair(self):
        self.assertEqual(droid._parse_point('831, 81'), (831, 81))
        self.assertEqual(droid._parse_point('x=831, y=81'), (831, 81))
        self.assertEqual(droid._parse_point('约 (831, 81)'), (831, 81))
        self.assertEqual(droid._parse_point('831 81'), (831, 81))
        self.assertEqual(droid._parse_point('831，81'), (831, 81))     # 全角逗号

    def test_percent_answer_is_rejected(self):
        """百分号是单位陷阱, 不是坐标: 放过它就会把 85% 当 850 用, 从标题行掉到状态栏。"""
        for bad in ('85%', '约 85%, 8%', 'x is 85 percent of width'):
            with self.assertRaises(ValueError) as cm:
                droid._parse_point(bad)
            self.assertIn('百分号', str(cm.exception), bad)

    def test_no_pair_is_rejected_with_the_original_answer(self):
        for bad in ('none', '看不到', 'the icon is on the right side'):
            with self.assertRaises(ValueError) as cm:
                droid._parse_point(bad)
            self.assertIn(bad[:6], str(cm.exception))

    def test_out_of_range_is_rejected(self):
        with self.assertRaises(ValueError):
            droid._parse_point('1200, 81')

    def test_first_two_integers_win_over_later_prose(self):
        self.assertEqual(droid._parse_point('831, 81 (标题行右侧)'), (831, 81))
        self.assertEqual(droid._parse_point('831 和 81'), (831, 81))

    def test_screen_size_answer_is_rejected_not_used(self):
        """回成屏幕尺寸(1200x2670)时必须拒: 夹取后它会变成一个看似合理的落点。"""
        with self.assertRaises(ValueError) as cm:
            droid._parse_point('1200x2670 上的 831, 81')
        self.assertIn('0-1000', str(cm.exception))


class AskPointTest(unittest.TestCase):
    def _patch_vision(self, answer):
        seen = {}

        def fake_ask_vision(image, prompt, roi=None, timeout=None, **kw):
            seen['prompt'] = prompt
            seen['roi'] = roi
            return answer
        ctx = patch.object(droid, 'ask_vision', fake_ask_vision)
        ctx.start(); self.addCleanup(ctx.stop)
        ctx2 = patch.object(droid, 'shot', lambda *a, **k: _img())
        ctx2.start(); self.addCleanup(ctx2.stop)
        return seen

    def test_prompt_is_fixed_and_demands_0_1000(self):
        seen = self._patch_vision('831, 81')
        self.assertEqual(droid.ask_point('放大镜'), (831, 81))
        p = seen['prompt']
        self.assertIn('0-1000', p)
        self.assertIn('ONLY two integers', p)
        self.assertIn('Do not use percent', p)
        self.assertIn('放大镜', p)                     # 目标仍然来自调用方

    def test_roi_is_resolved_before_sending(self):
        seen = self._patch_vision('831, 81')
        droid.ask_point('放大镜', roi='title')
        self.assertEqual(seen['roi'], droid._resolve_roi('title'))

    def test_crop_frame_answer_is_mapped_back_to_full_screen(self):
        """P0 回归: ask_vision 送图前就裁好了, VLM 只看到裁剪后的图, 它回的 0-1000 必然是
        **裁剪框**的。不映射回整屏就整体偏移——实测 roi='title' 时放大镜从 (996,215)
        偏到 (995,1068), 点进聊天列表, 而 tap 的 diff 很大、前台也没变, 模型会以为
        搜索页已经打开。"""
        # title 锚带 = 0-1000 的 y 55..120; 放大镜在整屏 ry=81, 即裁剪框内 40% 处
        roi = droid._resolve_roi('title')
        self.assertEqual(roi, (0, 55, 1000, 120))
        self._patch_vision('830, 400')            # VLM 看到的是裁剪后的图
        rx, ry = droid.ask_point('放大镜', roi='title')
        self.assertEqual((rx, ry), (830, 81))     # 必须还原成整屏坐标
        self.assertEqual(geom.to_px(rx, ry, 1200, 2670), (995, 216))   # 落在标题行

    def test_full_screen_answer_is_unchanged(self):
        self._patch_vision('831, 81')
        self.assertEqual(droid.ask_point('放大镜'), (831, 81))

    def test_vision_error_propagates(self):
        def boom(*a, **k):
            raise RuntimeError('视觉模型连续失败已熔断')
        with patch.object(droid, 'ask_vision', boom), \
             patch.object(droid, 'shot', lambda *a, **k: _img()):
            with self.assertRaises(RuntimeError):
                droid.ask_point('放大镜')

    def test_unparsable_answer_raises_not_guesses(self):
        """解析不出来必须抛错: 猜一个坐标就是 silent miss, 正是要消的那类失败。"""
        self._patch_vision('图标在右上角')
        with self.assertRaises(ValueError):
            droid.ask_point('放大镜')


if __name__ == '__main__':
    unittest.main()
