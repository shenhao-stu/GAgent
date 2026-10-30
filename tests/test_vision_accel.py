"""视觉调用的 ROI 裁剪与超时传递（通用机制，不针对具体 App）+ 动作后等页面稳定。

真机实证（羊了个羊 652s）：游戏段每步 1-2 次视觉问答，全屏 320 万像素 + 长 prompt，
单次 25-50s。通用修法是 roi（0-1000 归一化）裁剪后只送局部——像素量降 3-6 倍。
注意裁剪**不是**主要加速手段：大头是模型生成（15-46s），别把它当加速开关用。

熔断/能力分类/预算已搬到别处，不在这里重复：
- 能力分类与按模型熔断 → tests/test_vision_lifecycle.py
- see() 作为第一级工具的预算 → tests/test_see_tool.py
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
import vision_llm

IMG = np.zeros((2670, 1200, 3), dtype=np.uint8)


def _fake_backend(result="ok"):
    """替身 backend + 记录 ask_with_backend 实参。"""
    calls = []

    def fake(backend, image_input, prompt="", **kw):
        calls.append({"image": image_input, "prompt": prompt, "kw": kw})
        if isinstance(result, Exception):
            raise result
        return result
    fake.calls = calls
    return fake


class VisionRoiTest(unittest.TestCase):
    def setUp(self):
        droid.set_active_backend(object())     # ask_vision 要求有后端; 内容无关, 被打桩的是 ask_with_backend
        self.addCleanup(droid.set_active_backend, None)

    def _patch_vision(self, result="ok"):
        fake = _fake_backend(result)
        p = patch.object(vision_llm, 'ask_with_backend', fake)
        p.start(); self.addCleanup(p.stop)
        return fake

    def test_band_names_crop_to_the_measured_system_ui(self):
        """roi='title' 必须裁到 geom 实测的标题行(1200x2670 上 y 146..320),
        且与 look(roi='title') 裁的是同一块——否则"OCR 在标题行没看到图标, 用
        see() 看同一块"就落空, 模型得重新描述位置。"""
        import geom
        invoke = self._patch_vision()
        droid.ask_vision(IMG, "放大镜在哪", roi='title')
        img = invoke.calls[0]["image"]
        x1, y1, x2, y2 = geom.band('title', 1200, 2670)
        # _crop_roi 按 0-1000 比例切, 与 geom.band 的像素值有 1px 取舍差
        self.assertLessEqual(abs(img.shape[0] - (y2 - y1)), 2)
        self.assertLessEqual(abs(img.shape[1] - (x2 - x1)), 2)
        self.assertLess(img.shape[0], IMG.shape[0] * 0.2)      # 裁到 <20% 高度才叫"快"

    def test_unknown_roi_name_lists_the_available_bands(self):
        with self.assertRaises(ValueError) as cm:
            droid.ask_vision(IMG, "x", roi='nope')
        for name in ('title', 'status', 'navbar', 'top'):
            self.assertIn(name, str(cm.exception))

    def test_look_and_ask_vision_agree_on_the_same_band(self):
        import geom
        from_vision = droid._resolve_roi('title')
        from_look = tuple(int(round(v * geom.NORM)) for v in droid._ROI_NAMES['title'])
        self.assertEqual(from_vision, from_look)
        self.assertEqual(from_vision, geom.band_norm('title'))

    def test_roi_crops_before_send(self):
        invoke = self._patch_vision()
        droid.ask_vision(IMG, "棋盘", roi=[250, 200, 750, 550])
        img = invoke.calls[0]["image"]
        self.assertEqual(img.shape, (2670 * 35 // 100, 1200 * 50 // 100, 3))

    def test_no_roi_sends_full(self):
        invoke = self._patch_vision()
        droid.ask_vision(IMG, "全局")
        self.assertEqual(invoke.calls[0]["image"].shape, IMG.shape)

    def test_path_input_ignores_roi(self):
        invoke = self._patch_vision()
        droid.ask_vision("/sdcard/x.png", "棋盘", roi=[0, 0, 500, 500])
        self.assertEqual(invoke.calls[0]["image"], "/sdcard/x.png")

    def test_caller_can_raise_timeout(self):
        """调用方显式给的 timeout 必须原样传到后端(see() 就靠它带自己的预算)。"""
        invoke = self._patch_vision()
        droid.ask_vision(IMG, "x", timeout=90)
        self.assertEqual(invoke.calls[0]["kw"]["timeout"], 90)

    def test_timeout_defaults_to_the_read_timeout(self):
        invoke = self._patch_vision()
        droid.ask_vision(IMG, "x")
        self.assertEqual(invoke.calls[0]["kw"]["timeout"], droid._VISION_TIMEOUT_S)


class VisionFuseResetTest(unittest.TestCase):
    """回归: 熔断现在按模型身份走。曾经的进程级单例让"上个任务选了个不支持图片的模型"
    连撞两次失败之后, 新任务在整个游戏阶段连续 120s 拿不到任何观察。"""

    def setUp(self):
        droid.reset_vision_fuse()
        self.addCleanup(droid.reset_vision_fuse)

    def test_reset_clears_every_model(self):
        droid._FUSE['m1'] = {'n': 2, 'until': 9e9}
        droid._CAP['m1'] = 'no_vision'
        droid.reset_vision_fuse()
        self.assertEqual(droid._FUSE, {})
        self.assertEqual(droid._CAP, {})

    def test_reset_one_model_leaves_the_others(self):
        droid._FUSE['m1'] = {'n': 2, 'until': 9e9}
        droid._FUSE['m2'] = {'n': 1, 'until': 9e9}

        class _B:
            model = 'm1'
        droid.reset_vision_fuse(_B())
        self.assertNotIn('m1', droid._FUSE)
        self.assertEqual(droid._FUSE['m2']['n'], 1)


if __name__ == "__main__":
    unittest.main()


class StabilityWaitTest(unittest.TestCase):
    """F1: 动作后等页面稳定再决策(替代固定 sleep)。

    真机实证(对比方案): 固定 action_sleep=5 让 30 步白睡 150s; 而"立刻决策"在
    加载页上会点到未完成的界面。本方案: diff 持续 >阈值=还在动, 等到稳定或超时。
    经实测对比选择此方案效果更佳: 阈值 1.5%(与 scroll verdict 一致)、
    轮询 250ms、上限 3s——静态页几乎不花时间, 加载页不抢跑。
    """

    def test_static_page_returns_immediately(self):
        calls = {'n': 0}

        def shot():
            calls['n'] += 1
            return np.full((100, 100, 3), 128, dtype=np.uint8)
        with patch.object(droid, 'shot', side_effect=shot), \
             patch.object(droid.time, 'sleep'):
            r = droid.wait_stable()
        self.assertTrue(r['stable'])
        self.assertEqual(calls['n'], 2)          # 首帧 + 一次确认
        self.assertLessEqual(r['waited_s'], 0.5)

    def test_animating_page_waits_until_timeout(self):
        frames = [np.full((100, 100, 3), v, dtype=np.uint8) for v in range(0, 255, 25)]
        box = {'it': iter(frames)}

        def shot():
            # 无限交替: 永不用尽(用尽后帧相同会被判 stable, 那不是被测行为)
            try:
                return next(box['it'])
            except StopIteration:
                box['it'] = iter(frames); return next(box['it'])
        with patch.object(droid, 'shot', side_effect=shot), \
             patch.object(droid.time, 'sleep'):
            r = droid.wait_stable(max_wait=1.0, poll=0.25)
        self.assertFalse(r['stable'])
        self.assertGreaterEqual(r['waited_s'], 1.0)

    def test_change_then_stable_returns_stable(self):
        seq = [np.full((100, 100, 3), 0, dtype=np.uint8),
               np.full((100, 100, 3), 255, dtype=np.uint8),
               np.full((100, 100, 3), 255, dtype=np.uint8)]
        it = iter(seq)

        def shot():
            try:
                return next(it)
            except StopIteration:
                return seq[-1]
        with patch.object(droid, 'shot', side_effect=shot), \
             patch.object(droid.time, 'sleep'):
            r = droid.wait_stable(max_wait=3.0, poll=0.25)
        self.assertTrue(r['stable'])

    def test_shot_failure_degrades_to_stable(self):
        # 截图失败不阻塞: 当作"无法判定", 返回 stable=True 让上层继续(uncertain 由上层判)
        with patch.object(droid, 'shot', side_effect=RuntimeError('secure')), \
             patch.object(droid.time, 'sleep'):
            r = droid.wait_stable()
        self.assertTrue(r['stable'])
        self.assertTrue(r.get('uncertain'))
