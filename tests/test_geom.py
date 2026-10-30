# -*- coding: utf-8 -*-
"""geom: 坐标换算与系统 UI 锚带。

回归来源(真机 1200x2670, 2026-10-27 实测): gui_act 的 point 与 look()/dump() 的
像素坐标靠「任一轴 >1000 就当像素」区分, 对屏幕上/左大半个区域恒错且不报错——
放大镜 (996,215) 被当成归一化点成 (1195,574)。修正方向是让单位显式化
(gui_act: point=像素 / rel=0-1000)并把换算收敛到本模块, 这些用例锁住收敛后的行为。
"""
import sys
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import geom

W, H = 1200, 2670          # 本机实测物理分辨率


class ConversionTest(unittest.TestCase):
    def test_norm_endpoint_lands_on_last_pixel(self):
        """归一化 1000 必须是 dim-1: 产出 dim 会被 _gesture_screen/requirePoint 当越界拒掉,
        整个轮次白废。旧实现 int(x/1000*w) 正是这个 bug, 且旧单测把 (1200,2670)
        当正确期望, 等于把 bug 固化。"""
        self.assertEqual(geom.to_px(1000, 1000, W, H), (W - 1, H - 1))
        self.assertEqual(geom.to_px(0, 0, W, H), (0, 0))

    def test_round_trip_is_stable(self):
        """端点是唯一的夹取点(1000→dim-1→999), 单独由夹取用例覆盖, 不进往返。"""
        for rx, ry in [(0, 0), (500, 500), (830, 80), (929, 81), (529, 92), (1, 999)]:
            x, y = geom.to_px(rx, ry, W, H)
            self.assertEqual(geom.to_norm(x, y, W, H), (rx, ry), (rx, ry))

    def test_real_device_anchors(self):
        """实测值(screencap 逐像素扫描): 放大镜中心 (996,215), 搜索框中心 (635,245)。
        round 跨度取 dim-1, 与实测有 ≤1px 取舍——断言容 2px, 并要求往返自洽。"""
        self.assertEqual(geom.to_norm(996, 215, W, H), (831, 81))
        self.assertEqual(geom.to_norm(635, 245, W, H), (530, 92))
        self.assertEqual(geom.to_px(831, 81, W, H), (996, 216))
        self.assertEqual(geom.to_px(530, 92, W, H), (635, 246))
        for rx, ry, px, py in [(831, 81, 996, 215), (929, 81, 1115, 217), (530, 92, 635, 245)]:
            gx, gy = geom.to_px(rx, ry, W, H)
            self.assertLessEqual(abs(gx - px), 2, (rx, ry))
            self.assertLessEqual(abs(gy - py), 2, (rx, ry))
            self.assertEqual(geom.to_norm(gx, gy, W, H), (rx, ry), (rx, ry))

    def test_out_of_range_norm_is_clamped_not_fatal(self):
        """VLM 估算溢出 1-2 个单位是常态噪声, 为它废一轮不划算。"""
        self.assertEqual(geom.to_px(1004, -3, W, H), (W - 1, 0))

    def test_bad_dimensions_rejected(self):
        for bad in (0, -1, None, 'x'):
            with self.assertRaises(ValueError):
                geom.to_px(500, 500, bad, H)

    def test_bad_coordinate_rejected(self):
        for bad in (None, 'x', True, [1]):
            with self.assertRaises(ValueError):
                geom.to_px(bad, 500, W, H)


class BandTest(unittest.TestCase):
    def test_measured_bands_cover_the_real_anchors(self):
        """锚带必须真的装下实测内容: 标题行装放大镜/+, 底栏装四个 tab。"""
        self.assertTrue(geom.in_band('title', 996, 215, W, H), '放大镜应在标题行')
        self.assertTrue(geom.in_band('title', 1115, 217, W, H), '+ 应在标题行')
        self.assertTrue(geom.in_band('navbar', 444, 2466, W, H), '底栏 tab 应在 navbar')
        self.assertTrue(geom.in_band('navbar', 1049, 2466, W, H))
        self.assertTrue(geom.in_band('status', 600, 70, W, H), '状态栏文字应在 status')
        self.assertFalse(geom.in_band('title', 600, 70, W, H), '状态栏不算标题行')

    def test_bands_scale_with_resolution(self):
        """比例记录的意义: 换分辨率仍然指向同一块系统 UI。"""
        self.assertTrue(geom.in_band('title', 664, 143, 800, 1780))
        self.assertTrue(geom.in_band('navbar', 296, 1644, 800, 1780))

    def test_band_norm_is_a_valid_roi(self):
        for name in geom.BANDS:
            x1, y1, x2, y2 = geom.band_norm(name)
            self.assertTrue(0 <= x1 <= x2 <= geom.NORM, name)
            self.assertTrue(0 <= y1 <= y2 <= geom.NORM, name)

    def test_unknown_band_lists_choices(self):
        with self.assertRaises(ValueError) as cm:
            geom.band('nope', W, H)
        self.assertIn('title', str(cm.exception))


if __name__ == '__main__':
    unittest.main()
