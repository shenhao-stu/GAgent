# -*- coding: utf-8 -*-
"""see(): 第一级视觉工具。

它解决的是"视觉调用在 code_run 里跟脚本抢 60s 预算"这个结构问题: 一次视觉调用实测
15-46s, 而 code_run 默认 60s, 于是旧实现要靠 4 个常量推导剩余、还要立"一轮最多一次"
的规矩。升为第一级工具后预算独立, 那套全删。

契约(模型侧只看这些):
- ok=true  → answer(自由文本) 或 rx,ry(want='point', 0-1000 可直接传 gui_act 的 rel)
- ok=false → reason + hint, **永不挂死**, 也从不要求重试
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
import ga_android
import droid
import vision_llm

_IMG = np.zeros((100, 200, 3), dtype='uint8')


class _Handler(ga_android.GenericAgentHandler):
    def __init__(self):
        self.working = {}; self.current_turn = 1; self.cwd = '.'
        self.code_stop_signal = []; self._done_hooks = []; self.print = lambda *a, **k: None
        self.history_info = []
        self.parent = types.SimpleNamespace(llmclient=None, task_dir=None, verbose=False,
                                            _turn_end_hooks={})


def _run(h, args):
    """do_see 直接返回 StepOutcome(它不是生成器, 没有 yield 进度)。
    agent_loop.dispatch 用 try_call_generator 兼容两种形状, 这里照它的写法。"""
    ret = h.do_see(args, None)
    return ret


def _wire(monkeypatch, answer='512,703', boom=None, cap=None):
    monkeypatch.setattr(droid, 'shot', lambda *a, **k: _IMG)
    monkeypatch.setattr(droid, 'screen', lambda: (200, 100))
    monkeypatch.setattr(droid, '_vision_cap', lambda be: cap)
    monkeypatch.setattr(droid, 'active_backend', lambda: object())

    def fake(backend, image, prompt, **kw):
        if boom:
            raise RuntimeError(boom)
        return answer
    monkeypatch.setattr(vision_llm, 'ask_with_backend', fake)


class TestSeeTool(unittest.TestCase):
    def setUp(self):
        droid.reset_vision_fuse()
        self.addCleanup(droid.reset_vision_fuse)

    def test_text_returns_envelope(self):
        h = _Handler()
        with patch.object(droid, 'shot', lambda *a, **k: _IMG), \
             patch.object(droid, '_vision_cap', lambda be: None), \
             patch.object(droid, 'active_backend', lambda: object()), \
             patch.object(vision_llm, 'ask_with_backend',
                          lambda b, i, p, **k: '大厅里有通行证入口'):
            out = json.loads(_run(h, {'question': '大厅里有什么'}).data)
        self.assertTrue(out['ok'])
        self.assertEqual(out['answer'], '大厅里有通行证入口')
        self.assertIn('ms', out)
        self.assertTrue(out['model'])

    def test_point_maps_crop_coordinates_back_to_full_screen(self):
        """roi='lower' = (0,500,1000,1000)。VLM 只看到裁剪后的图, 它的 0-1000 必然是
        **裁剪框**的, 必须映射回整屏 —— 否则整体偏移(真机实证: roi='title' 时放大镜会从
        (996,215) 偏到 (995,1068), 点进聊天列表, 而 tap 的 diff 很大、前台也没变)。"""
        h = _Handler()
        with patch.object(droid, 'shot', lambda *a, **k: _IMG), \
             patch.object(droid, '_vision_cap', lambda be: None), \
             patch.object(droid, 'active_backend', lambda: object()), \
             patch.object(vision_llm, 'ask_with_backend',
                          lambda b, i, p, **k: '约 (512, 703)'):
            out = json.loads(_run(h, {'question': '通行证在哪', 'want': 'point',
                                      'roi': 'lower'}).data)
        self.assertTrue(out['ok'])
        self.assertEqual(out['rx'], 512)                 # x 方向裁剪框就是全宽, 原样
        self.assertEqual(out['ry'], 852)                 # 500 + 703/1000*500

    def test_point_without_roi_returns_the_pair_unchanged(self):
        h = _Handler()
        with patch.object(droid, 'shot', lambda *a, **k: _IMG), \
             patch.object(droid, '_vision_cap', lambda be: None), \
             patch.object(droid, 'active_backend', lambda: object()), \
             patch.object(vision_llm, 'ask_with_backend',
                          lambda b, i, p, **k: '512,703'):
            out = json.loads(_run(h, {'question': 'x', 'want': 'point'}).data)
        self.assertEqual((out['rx'], out['ry']), (512, 703))

    def test_point_rejects_percent(self):
        """单位防线: VLM 回百分号一律拒, 不猜。"""
        h = _Handler()
        with patch.object(droid, 'shot', lambda *a, **k: _IMG), \
             patch.object(droid, '_vision_cap', lambda be: None), \
             patch.object(droid, 'active_backend', lambda: object()), \
             patch.object(vision_llm, 'ask_with_backend',
                          lambda b, i, p, **k: '85% 宽度处'):
            out = json.loads(_run(h, {'question': 'x', 'want': 'point'}).data)
        self.assertFalse(out['ok'])
        self.assertEqual(out['reason'], 'call_failed')

    def test_no_vision_model_is_structured_not_a_hang(self):
        """R3: 纯文本模型 → 立刻结构化拒绝, 不出网, 也不计入熔断。"""
        h = _Handler()
        with patch.object(droid, 'shot', lambda *a, **k: _IMG), \
             patch.object(droid, '_vision_cap', lambda be: 'no_vision'), \
             patch.object(droid, 'active_backend', lambda: object()):
            out = json.loads(_run(h, {'question': 'x'}).data)
        self.assertFalse(out['ok'])
        self.assertEqual(out['reason'], 'model_no_vision')
        self.assertIn('ocr', out['hint'])          # 告知转本地通道, 不是让重试
        self.assertNotIn('重试 see', out['hint'])

    def test_no_backend_is_structured(self):
        h = _Handler()
        with patch.object(droid, 'active_backend', lambda: None):
            out = json.loads(_run(h, {'question': 'x'}).data)
        self.assertFalse(out['ok'])
        self.assertEqual(out['reason'], 'no_backend')

    def test_transport_failure_is_structured_and_never_retries(self):
        h = _Handler()
        with patch.object(droid, 'shot', lambda *a, **k: _IMG), \
             patch.object(droid, '_vision_cap', lambda be: None), \
             patch.object(droid, 'active_backend', lambda: object()), \
             patch.object(vision_llm, 'ask_with_backend',
                          lambda b, i, p, **k: (_ for _ in ()).throw(RuntimeError('read timeout'))):
            out = json.loads(_run(h, {'question': 'x'}).data)
        self.assertFalse(out['ok'])
        self.assertEqual(out['reason'], 'call_failed')
        self.assertIn('不要重试', out['hint'])

    def test_question_is_required(self):
        h = _Handler()
        out = _run(h, {})
        self.assertIn('question', str(out.data))

    def test_bad_want_is_rejected(self):
        h = _Handler()
        with patch.object(droid, 'active_backend', lambda: object()), \
             patch.object(droid, '_vision_cap', lambda be: None):
            out = _run(h, {'question': 'x', 'want': 'nope'})
        self.assertIn('want', str(out.data))

    def test_see_uses_its_own_budget_not_code_runs(self):
        """预算独立: see() 使用自己的上限, 不从 code_run 剩余里扣。"""
        h = _Handler()
        seen = {}
        with patch.object(droid, 'shot', lambda *a, **k: _IMG), \
             patch.object(droid, '_vision_cap', lambda be: None), \
             patch.object(droid, 'active_backend', lambda: object()), \
             patch.object(vision_llm, 'ask_with_backend',
                          lambda b, i, p, **kw: seen.update(kw) or 'ok'):
            _run(h, {'question': 'x'})
        self.assertEqual(seen['timeout'], ga_android.GenericAgentHandler._SEE_BUDGET_S)

    # --- 1a: 描述性问句本地类别闸 / 1b: point 缺 roi 代价提示 ---

    def test_class_question_answered_locally_no_vision(self):
        """纯问画面类别 → 本地 screen_kind() 应答, 不打 VLM(省 15-40s)。"""
        h = _Handler()
        called = {'n': 0}

        def boom(*a, **k):
            called['n'] += 1
            return 'x'
        with patch.object(droid, 'shot', lambda *a, **k: _IMG), \
             patch.object(droid, '_vision_cap', lambda be: None), \
             patch.object(droid, 'active_backend', lambda: object()), \
             patch.object(droid, 'screen_kind', lambda: 'canvas'), \
             patch.object(vision_llm, 'ask_with_backend', boom):
            out = json.loads(_run(h, {'question': '当前画面是什么'}).data)
        self.assertTrue(out['ok'])
        self.assertEqual(out['kind'], 'canvas')
        self.assertEqual(out['source'], 'local')
        self.assertIn('want="point"', out['answer'])      # 明确指向定位通道
        self.assertEqual(called['n'], 0)                  # 视觉一次都没打

    def test_content_question_still_uses_vision(self):
        """内容/定位问句 → 仍走 VLM, 不进本地闸。"""
        h = _Handler()
        with patch.object(droid, 'shot', lambda *a, **k: _IMG), \
             patch.object(droid, '_vision_cap', lambda be: None), \
             patch.object(droid, 'active_backend', lambda: object()), \
             patch.object(droid, 'screen_kind', lambda: 'canvas'), \
             patch.object(vision_llm, 'ask_with_backend',
                           lambda b, i, p, **k: '有通行证和每日任务'):
            out = json.loads(_run(h, {'question': '大厅里有哪些模块'}).data)
        self.assertTrue(out['ok'])
        self.assertNotIn('source', out)                   # 不是本地应答
        self.assertEqual(out['answer'], '有通行证和每日任务')

    def test_class_intent_with_content_word_falls_through(self):
        """类别意图 + 内容词 → fail-safe 放行 VLM(问的是位置, 不是纯类别)。"""
        h = _Handler()
        with patch.object(droid, 'shot', lambda *a, **k: _IMG), \
             patch.object(droid, '_vision_cap', lambda be: None), \
             patch.object(droid, 'active_backend', lambda: object()), \
             patch.object(droid, 'screen_kind', lambda: 'canvas'), \
             patch.object(vision_llm, 'ask_with_backend',
                           lambda b, i, p, **k: 'VLM答'):
            out = json.loads(_run(h, {'question': '这是什么页面，通行证按钮在哪'}).data)
        self.assertTrue(out['ok'])
        self.assertNotIn('source', out)

    def test_class_question_unknown_kind_falls_through(self):
        """本地判不出可靠类别(unknown) → 回落 VLM, 不装懂。"""
        h = _Handler()
        with patch.object(droid, 'shot', lambda *a, **k: _IMG), \
             patch.object(droid, '_vision_cap', lambda be: None), \
             patch.object(droid, 'active_backend', lambda: object()), \
             patch.object(droid, 'screen_kind', lambda: 'unknown'), \
             patch.object(vision_llm, 'ask_with_backend',
                           lambda b, i, p, **k: 'VLM答'):
            out = json.loads(_run(h, {'question': '当前画面是什么'}).data)
        self.assertTrue(out['ok'])
        self.assertNotIn('source', out)

    def test_class_question_screen_kind_error_falls_through(self):
        """screen_kind() 抛异常 → 回落 VLM。"""
        h = _Handler()

        def boom(*a, **k):
            raise RuntimeError('dump failed')
        with patch.object(droid, 'shot', lambda *a, **k: _IMG), \
             patch.object(droid, '_vision_cap', lambda be: None), \
             patch.object(droid, 'active_backend', lambda: object()), \
             patch.object(droid, 'screen_kind', boom), \
             patch.object(vision_llm, 'ask_with_backend',
                           lambda b, i, p, **k: 'VLM答'):
            out = json.loads(_run(h, {'question': '当前画面是什么'}).data)
        self.assertTrue(out['ok'])
        self.assertNotIn('source', out)

    def test_point_without_roi_adds_cost_hint(self):
        """1b: want='point' 未传 roi → 成功信封带 roi 代价提示。"""
        h = _Handler()
        with patch.object(droid, 'shot', lambda *a, **k: _IMG), \
             patch.object(droid, '_vision_cap', lambda be: None), \
             patch.object(droid, 'active_backend', lambda: object()), \
             patch.object(vision_llm, 'ask_with_backend',
                           lambda b, i, p, **k: '512,703'):
            out = json.loads(_run(h, {'question': 'x', 'want': 'point'}).data)
        self.assertIn('hint', out)
        self.assertIn('roi', out['hint'])

    def test_point_with_roi_has_no_hint(self):
        """1b: 传了 roi 不加提示(只增字段, 不改成功路径)。"""
        h = _Handler()
        with patch.object(droid, 'shot', lambda *a, **k: _IMG), \
             patch.object(droid, '_vision_cap', lambda be: None), \
             patch.object(droid, 'active_backend', lambda: object()), \
             patch.object(vision_llm, 'ask_with_backend',
                           lambda b, i, p, **k: '512,703'):
            out = json.loads(_run(h, {'question': 'x', 'want': 'point', 'roi': 'lower'}).data)
        self.assertNotIn('hint', out)

    def test_looks_like_screen_class_question_truth_table(self):
        f = ga_android._looks_like_screen_class_question
        for q in ('当前画面是什么', '这是什么屏幕', '哪个页面', '是不是游戏',
                  '大厅吗', '主界面吗', '当前屏'):
            self.assertTrue(f(q), q)
        for q in ('大厅里有什么', '通行证按钮在哪', '这个页面写着什么', '有哪些模块',
                  '关闭按钮的坐标', '现在几点'):
            self.assertFalse(f(q), q)
        # 类别意图 + 内容词 → 放行; 空/None → False
        self.assertFalse(f('这是什么页面，通行证在哪'))
        self.assertFalse(f(''))
        self.assertFalse(f(None))


if __name__ == '__main__':
    unittest.main()
