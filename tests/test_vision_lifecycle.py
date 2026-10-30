# -*- coding: utf-8 -*-
"""视觉生命周期: backend 从哪来 / 能不能看图 / 失败几次算熔断。

三件事曾互相打架(真机 2026-10-28): 选个不支持图片的模型 → 2 次 2.4s 快速失败 →
进程级熔断 120s → 整个游戏阶段(唯一需要视觉 grounding 的阶段)全瞎; 而熔断只在任务
开始清零, 等于新任务替上个任务的模型选择受罚。

本组用例锁住分开后的契约:
- backend 是模块级登记, 不是 threading.local —— 后者不跨线程继承, 用户代码自起
  子线程调 ask_vision 会莫名拿不到;
- 能力失败(模型不能看图)不计熔断、不重试, 立刻结构化告知并转本地通道;
- 熔断按 backend 身份, 切模型即重置。
"""
import sys
import threading
import unittest
from pathlib import Path

import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import droid
import vision_llm

_IMG = np.zeros((32, 32, 3), dtype='uint8')


class _Backend:
    def __init__(self, name, boom=None):
        self.name, self.boom = name, boom


def _wire(be, boom=None):
    """把 ask_with_backend 换成可控假件; 返回调用计数。"""
    calls = {'n': 0}

    def fake(backend, image, prompt, **kw):
        calls['n'] += 1
        if getattr(backend, 'boom', None):
            raise RuntimeError(backend.boom)
        return 'ok'

    vision_llm.ask_with_backend = fake
    droid.set_active_backend(be)
    droid.reset_vision_fuse()
    return calls


class TestVisionLifecycle(unittest.TestCase):
    def setUp(self):
        droid.set_active_backend(None)
        droid.reset_vision_fuse()

    def tearDown(self):
        droid.set_active_backend(None)
        droid.reset_vision_fuse()
        vision_llm.ask_with_backend = _ORIG_ASK

    def test_active_backend_survives_child_thread(self):
        """用户代码自起子线程调 ask_vision: threading.local() 不跨线程继承。"""
        be = _Backend('a')
        droid.set_active_backend(be)
        box = {}
        t = threading.Thread(target=lambda: box.update(b=droid.active_backend()))
        t.start(); t.join()
        self.assertIs(box['b'], be)

    def test_non_multimodal_model_does_not_trip_fuse(self):
        """R3: 切到纯文本模型 → 第一次就明确拒绝, 且不计熔断。"""
        be = _Backend('text-only', boom='400 Bad Request: image not supported by this model')
        calls = _wire(be)
        for _ in range(5):
            with self.assertRaises(RuntimeError) as ctx:
                droid.ask_vision(_IMG, 'q')
            self.assertIn('不支持图片', str(ctx.exception))
        # 能力结果已缓存: 后续调用根本不出网
        self.assertEqual(calls['n'], 1)
        self.assertEqual(droid._fuse_state(be)['n'], 0)
        self.assertEqual(droid._vision_cap(be), 'no_vision')

    def test_transport_failure_trips_fuse_per_model(self):
        be = _Backend('flaky', boom='read timeout')
        _wire(be)
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                droid.ask_vision(_IMG, 'q')
        self.assertNotEqual(droid._vision_cap(be), 'no_vision')
        with self.assertRaises(RuntimeError) as ctx:
            droid.ask_vision(_IMG, 'q')
        self.assertIn('熔断', str(ctx.exception))

    def test_switching_model_resets_that_models_fuse(self):
        """上个模型的失败不该罚下一个模型。"""
        bad = _Backend('bad', boom='read timeout')
        droid.set_active_backend(bad)
        droid.reset_vision_fuse()
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                droid.ask_vision(_IMG, 'q')
        self.assertGreaterEqual(droid._fuse_state(bad)['n'], 2)
        self.assertEqual(droid._fuse_state(_Backend('good'))['n'], 0)

    def test_success_clears_that_models_fuse(self):
        be = _Backend('ok')
        _wire(be)
        self.assertEqual(droid.ask_vision(_IMG, 'q'), 'ok')
        self.assertEqual(droid._fuse_state(be)['n'], 0)
        self.assertEqual(droid._vision_cap(be), 'ok')

    def test_no_backend_is_an_explicit_error(self):
        """没有后端时把话说清, 不是静默不设然后报一句看不懂的错。"""
        droid.set_active_backend(None)
        with self.assertRaises(RuntimeError) as ctx:
            droid.ask_vision(_IMG, 'q')
        self.assertIn('没有可用模型后端', str(ctx.exception))

    def test_reset_vision_fuse_no_arg_clears_everything(self):
        be = _Backend('x', boom='read timeout')
        droid.set_active_backend(be)
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                droid.ask_vision(_IMG, 'q')
        droid.reset_vision_fuse()
        self.assertEqual(droid._fuse_state(be)['n'], 0)
        self.assertIsNone(droid._vision_cap(be))


_ORIG_ASK = vision_llm.ask_with_backend

if __name__ == '__main__':
    unittest.main()
