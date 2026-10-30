# -*- coding: utf-8 -*-
"""YOLO 失败一律降级, 绝不外抛。

回归来源(真机 2026-10-28 10:22 那次 22 分钟的任务): 用户导入的 YOLO 模型在
user_models/, 而 detector_models.model_path() 做了 Path.resolve() —— Android 上
/data/user/0 是指向 /data/data 的符号链接, 路径因此落进 PC 映射分支被改成
models/ui_detect_v1/models/<name>, Kotlin 报 model not found。异常穿透
_yolo → detect → droid.look() → 整轮作废。

同一份代码里"没有注册表"时反而会静默降级成纯 OCR(if not os.path.isfile: return []),
即两种缺失状态行为相反。本组用例锁住统一后的降级契约。
"""
import sys
import unittest
from pathlib import Path

import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
BUNDLE = CORE / 'models' / 'ui_detect_v1'
sys.path.insert(0, str(BUNDLE))
# 无 onnxruntime 的机器(CI 的 requirements-test.txt 不装它; 本地可能也没装)不能连收集都过不去:
# 本组用例把 _session/_ocr_engine/_yolo 全 mock 掉, 根本不做真推理, 所以缺引擎时塞个占位模块即可。
# 与 tests/test_detector_models.py 同一手法。
if 'onnxruntime' not in sys.modules:
    try:
        import onnxruntime  # noqa: F401
    except Exception:
        import types as _types
        sys.modules['onnxruntime'] = _types.SimpleNamespace()
import ui_detect_lite


def _img():
    return np.zeros((64, 64, 3), dtype=np.uint8)


def _no_ocr(monkeypatch):
    monkeypatch.setattr(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([])))


class TestYoloDegrade(unittest.TestCase):
    def setUp(self):
        ui_detect_lite.LAST_YOLO_ERROR = None

    def test_registry_points_at_missing_file_degrades_to_ocr(self):
        import unittest.mock as mock
        import detector_models
        with mock.patch.object(detector_models, 'model_path',
                               side_effect=ValueError('Installed detector is missing or invalid')):
            with mock.patch.object(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([]))):
                out = ui_detect_lite.detect(_img(), yolo=True)      # 不得抛
        self.assertEqual(out, [])
        self.assertTrue(ui_detect_lite.LAST_YOLO_ERROR)
        self.assertIn('ValueError', ui_detect_lite.LAST_YOLO_ERROR)

    def test_onnx_session_failure_degrades(self):
        import unittest.mock as mock
        # 本机没有 YOLO 权重(.gitignore 排除), 先让 isfile 放行才能走到 _session 分支
        with mock.patch.object(ui_detect_lite.os.path, 'isfile', lambda p: True), \
             mock.patch.object(ui_detect_lite, '_session',
                               side_effect=RuntimeError('model not found: /data/x.onnx')):
            with mock.patch.object(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([]))):
                out = ui_detect_lite.detect(_img(), yolo=True)      # 不得抛
        self.assertEqual(out, [])
        self.assertIn('model not found', ui_detect_lite.LAST_YOLO_ERROR)

    def test_inference_failure_degrades(self):
        import unittest.mock as mock

        class _Boom:
            def run(self, *a, **k):
                raise RuntimeError('ORT: invalid tensor')

            def get_inputs(self):
                return [type('I', (), {'name': 'images'})()]

        with mock.patch.object(ui_detect_lite.os.path, 'isfile', lambda p: True), \
             mock.patch.object(ui_detect_lite, '_session', lambda p: _Boom()):
            with mock.patch.object(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([]))):
                out = ui_detect_lite.detect(_img(), yolo=True)      # 不得抛
        self.assertEqual(out, [])
        self.assertIn('invalid tensor', ui_detect_lite.LAST_YOLO_ERROR)

    def test_last_error_cleared_on_success(self):
        import unittest.mock as mock
        ui_detect_lite.LAST_YOLO_ERROR = 'stale from a previous call'
        with mock.patch.object(ui_detect_lite, '_yolo', lambda img, conf: ([], None)):
            with mock.patch.object(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([]))):
                ui_detect_lite.detect(_img(), yolo=True)
        self.assertIsNone(ui_detect_lite.LAST_YOLO_ERROR)

    def test_ocr_only_path_reports_no_yolo_error(self):
        import unittest.mock as mock
        with mock.patch.object(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([]))):
            ui_detect_lite.detect(_img(), yolo=False)
        self.assertIsNone(ui_detect_lite.LAST_YOLO_ERROR)

    def test_failed_session_is_not_cached(self):
        """失败会话不进 _SESSIONS: 否则下次 detect 直接拿坏会话, 连原因都读不到。"""
        import unittest.mock as mock
        ui_detect_lite._SESSIONS.clear()
        with mock.patch.object(ui_detect_lite, '_session',
                               side_effect=RuntimeError('model not found: /x')):
            with mock.patch.object(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([]))):
                ui_detect_lite.detect(_img(), yolo=True)
        self.assertEqual(ui_detect_lite._SESSIONS, {})


class TestOcrCostGate(unittest.TestCase):
    """YOLO 框太密就不跑全图 OCR。

    真机 2026-10-28 实测: PP-OCR 的识别耗时按文本框数量线性增长 —— 微信标题行 5 个框约 2s,
    小程序游戏 HUD 52 个框约 6s, 两者像素量完全相同。而那 52 个框是游戏美术资源, 模型读不出
    语义也点不动, 却每次 gui_act 都付一遍钱, 还照着它们点错地方(3 次 tap 摸索的来由)。
    """

    def setUp(self):
        ui_detect_lite.LAST_SKIP_REASON = None
        ui_detect_lite.LAST_YOLO_ERROR = None
        self.addCleanup(setattr, ui_detect_lite, 'LAST_SKIP_REASON', None)

    def _boxes(self, n):
        """n 个互不重叠的 YOLO 输出行。"""
        rows = []
        for i in range(n):
            x1 = (i % 8) * 80.0
            y1 = (i // 8) * 80.0
            rows.append([x1, y1, x1 + 60, y1 + 60, 0.9, 17])   # cls 17 = 'Text'
        return rows

    def _patch(self, n):
        """把 _yolo 换成返回 n 个框, OCR 换成空。返回 patcher 栈(调用方负责 stop)。"""
        import unittest.mock as mock
        stack = [
            mock.patch.object(ui_detect_lite, '_yolo', lambda img, conf: (self._boxes(n), None)),
            mock.patch.object(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([]))),
        ]
        for p in stack:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in stack])

    def test_dense_scene_skips_ocr_and_says_why(self):
        self._patch(52)
        out = ui_detect_lite.detect(_img(), yolo=True, ocr_max_boxes=ui_detect_lite.OCR_MAX_BOXES)
        self.assertEqual(out, [])
        self.assertIn('scene_too_dense', ui_detect_lite.LAST_SKIP_REASON)
        self.assertIn('52', ui_detect_lite.LAST_SKIP_REASON)

    def test_sparse_scene_still_runs_ocr(self):
        self._patch(5)
        out = ui_detect_lite.detect(_img(), yolo=True, ocr_max_boxes=ui_detect_lite.OCR_MAX_BOXES)
        self.assertIsNone(ui_detect_lite.LAST_SKIP_REASON)
        self.assertEqual(len(out), 5)        # 5 个 YOLO 框, OCR 为空所以没有额外文字项

    def test_gate_is_off_when_caller_passes_none(self):
        """显式 ocr_max_boxes=None = 不要闸门(PC 调试/回归对比用)。"""
        self._patch(52)
        out = ui_detect_lite.detect(_img(), yolo=True, ocr_max_boxes=None)
        self.assertIsNone(ui_detect_lite.LAST_SKIP_REASON)
        self.assertEqual(len(out), 52)

    def test_yolo_failure_takes_precedence_over_the_gate(self):
        """检测器挂了就报检测器的原因, 不要报成"画面太密"。"""
        import unittest.mock as mock
        p = mock.patch.object(ui_detect_lite, '_yolo',
                              lambda img, conf: ([], 'RuntimeError: model not found'))
        p.start(); self.addCleanup(p.stop)
        with mock.patch.object(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([]))):
            ui_detect_lite.detect(_img(), yolo=True, ocr_max_boxes=ui_detect_lite.OCR_MAX_BOXES)
        self.assertIn('model not found', ui_detect_lite.LAST_YOLO_ERROR)
        self.assertIsNone(ui_detect_lite.LAST_SKIP_REASON)


if __name__ == '__main__':
    unittest.main()
