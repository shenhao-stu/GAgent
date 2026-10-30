# -*- coding: utf-8 -*-
"""通用协议回归: 完成契约、第一级 observe/ocr、语义 target/expect、see 去重。

这些行为不依赖具体 App。测试只验证代码层契约, 不碰真机。
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
import agent_loop
import ga_android


def _drive(gen):
    """消费生成器并取 return 值(do_no_tool 既可能 yield 进度行, 也可能直接返回)。"""
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


def _handler(**attrs):
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
    h.parent = types.SimpleNamespace(verbose=False)
    for k, v in attrs.items():
        setattr(h, k, v)
    return h


class CompletionContractTest(unittest.TestCase):
    def test_control_markup_is_not_task_done(self):
        h = _handler(_gui_actions=1)
        out = _drive(h.do_no_tool({}, types.SimpleNamespace(
            content='<update_working_checkpoint>{"key_info":"搜索页"}</update_working_checkpoint>',
            thinking='')))
        self.assertIsNotNone(out.next_prompt)
        self.assertIn('finish_task', out.next_prompt)
        self.assertIsNot(out.should_exit, True)

    def test_progress_only_text_is_not_task_done(self):
        h = _handler(_gui_actions=2)
        out = _drive(h.do_no_tool({}, types.SimpleNamespace(
            content='已进入套牌页面，需要依次点击查看详情并复制代码。', thinking='')))
        self.assertIsNotNone(out.next_prompt)
        self.assertIn('finish_task', out.next_prompt)
        self.assertIsNot(out.should_exit, True)

    def test_clean_answer_without_gui_can_finish_normally(self):
        h = _handler(_gui_actions=0)
        out = _drive(h.do_no_tool({}, types.SimpleNamespace(
            content='北京明天晴，最高 26°C，最低 18°C。', thinking='')))
        self.assertIsNone(out.next_prompt)
        self.assertFalse(out.should_exit)

    def test_clean_gui_final_gets_one_finish_task_chance(self):
        h = _handler(_gui_actions=2)
        out = _drive(h.do_no_tool({}, types.SimpleNamespace(
            content='已复制三组代码，分别是甲、乙、丙。', thinking='')))
        self.assertIn('finish_task', out.next_prompt)
        self.assertIsNot(out.should_exit, True)
        self.assertFalse(h._task_finished)
        # 第二次仍不调用 finish_task 时允许结束, 避免把协议提示变成死循环。
        out = _drive(h.do_no_tool({}, types.SimpleNamespace(
            content='已复制三组代码，分别是甲、乙、丙。', thinking='')))
        self.assertIsNone(out.next_prompt)

    def test_finish_task_requires_evidence_after_gui_done(self):
        h = _handler(_gui_actions=1)
        out = h.do_finish_task({'status': 'done', 'result': '已复制三组代码'},
                               types.SimpleNamespace(content=''))
        self.assertIn('[Error]', out.data)
        self.assertIsNot(out.should_exit, True)
        out = h.do_finish_task({'status': 'done', 'result': '已复制三组代码',
                                'evidence': ['套牌详情页显示 3 组代码']},
                               types.SimpleNamespace(content=''))
        self.assertTrue(out.should_exit)
        self.assertEqual(out.data['result'], '已复制三组代码')
        self.assertTrue(h._task_finished)


class _ScriptedClient:
    last_tools = ''

    def __init__(self, script):
        self.script = list(script)
        self.backend = types.SimpleNamespace(history=[])
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        name, args, content = self.script.pop(0)
        tcs = []
        if name:
            tcs = [types.SimpleNamespace(
                function=types.SimpleNamespace(name=name, arguments=json.dumps(args)),
                id='tc1')]
        resp = types.SimpleNamespace(thinking='', content=content, raw='',
                                     tool_calls=tcs,
                                     stop_reason='tool_use' if tcs else 'end_turn')
        yield 'chunk'
        return resp


class FinishTaskLoopTest(unittest.TestCase):
    def test_finish_task_result_is_shown_and_end_reason_is_finish_task(self):
        handler = ga_android.GenericAgentHandler(types.SimpleNamespace(
            task_dir=None, verbose=False, _turn_end_hooks={}, llmclient=None))
        client = _ScriptedClient([(
            'finish_task',
            {'status': 'done', 'result': '最终交付：三组代码 A/B/C',
             'evidence': ['详情页显示 A/B/C']},
            '<summary>完成</summary>')])
        seen_exit = []
        orig_cb = handler.turn_end_callback
        def cap_cb(*a):
            if a and a[-1]:
                seen_exit.append(a[-1])
            return orig_cb(*a)
        handler.turn_end_callback = cap_cb
        chunks = list(agent_loop.agent_runner_loop(
            client, 'sys', 'task', handler, [], max_turns=3, verbose=False))
        text = ''.join(c for c in chunks if isinstance(c, str))
        self.assertIn('三组代码 A/B/C', text)
        self.assertNotIn('🛠️ finish_task', text)
        # 返回退出原因由调用方保存; 这里从 agent_after hook 的 ctx 取最后值。
        # 直接再读 handler 的状态不足以证明协议, 所以用 exit_reason 的公开语义:
        # 本轮只有一个工具且它完成退出。
        self.assertTrue(handler._task_finished)
        self.assertTrue(seen_exit)
        self.assertEqual(seen_exit[-1].get('result'), 'FINISH_TASK')


class ObserveOcrToolTest(unittest.TestCase):
    def test_observe_returns_compact_bounded_items(self):
        h = _handler()
        fake = types.SimpleNamespace(observe=lambda **kw: {
            'kind': 'tree', 'notes': [], 'needs_vision': False, 'ms': 3.0,
            'items': [
                {'src': 'tree', 't': '搜索框', 'desc': '', 'cls': 'EditText',
                 'x': 100, 'y': 200, 'rx': 83, 'ry': 75, 'click': True,
                 'bbox': [1, 2, 3, 4], 'conf': 0.9},
                {'src': 'yolo', 't': '取消', 'desc': '', 'cls': 'Icon',
                 'x': 300, 'y': 400, 'rx': 250, 'ry': 150, 'click': True,
                 'bbox': [5, 6, 7, 8], 'conf': 0.8},
            ]})
        with patch.dict(sys.modules, {'droid': fake}):
            out = h.do_observe({'limit': 1}, types.SimpleNamespace(content=''))
        data = json.loads(out.data)
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['t'], '搜索框')
        self.assertNotIn('bbox', data['items'][0])
        self.assertEqual(data['items'][0]['x'], 100)

    def test_ocr_maps_local_roi_boxes_back_to_screen(self):
        h = _handler()
        img = np.zeros((100, 200, 3), dtype='uint8')
        fake = types.SimpleNamespace(
            shot=lambda: img,
            _resolve_roi=lambda roi: (0, 0, 1000, 500),
            ocr=lambda crop: [(np.array([[10, 20], [30, 20], [30, 40], [10, 40]]),
                               '搜索', 0.95)])
        with patch.dict(sys.modules, {'droid': fake}):
            out = h.do_ocr({'roi': 'upper'}, types.SimpleNamespace(content=''))
        data = json.loads(out.data)
        item = data['items'][0]
        self.assertEqual(item['text'], '搜索')
        self.assertEqual((item['x'], item['y']), (20, 30))
        self.assertEqual(item['bbox'], [10, 20, 30, 40])


class SemanticActionTest(unittest.TestCase):
    def _fake_droid(self, find_hits, obs_items):
        taps = []

        def tap(x, y, **kw):
            taps.append((x, y))
            return {'diff': 'diff: 20.0% bbox=[0,0,9,9]'}

        return types.SimpleNamespace(
            find=lambda target, exact=False: [dict(n) for n in find_hits],
            tap=tap, swipe=lambda *a, **k: {'diff': 'diff: 20.0%'},
            longpress=lambda *a, **k: {'diff': 'diff: 20.0%'},
            screen=lambda: (1200, 2670),
            ensure_fresh_obs=lambda: None,
            wait_stable=lambda **kw: {'stable': True, 'wait_for': 0.0},
            _sensitive_fg=lambda: False,
            observe=lambda **kw: {'kind': 'tree', 'items': list(obs_items),
                                  'notes': [], 'needs_vision': False, 'ms': 1.0},
        ), taps

    def test_target_resolves_and_expect_verifies(self):
        h = _handler()
        fake, taps = self._fake_droid(
            [{'x': 600, 'y': 300, 't': '搜索', 'd': ''}],
            [{'src': 'tree', 't': '搜索结果', 'desc': '', 'cls': 'Text',
              'x': 600, 'y': 900, 'rx': 500, 'ry': 337, 'click': True}])
        with patch.dict(sys.modules, {'droid': fake}):
            out = h.do_gui_act({'action': 'tap', 'target': '搜索', 'expect': '搜索结果'},
                               types.SimpleNamespace(content=''))
        data = json.loads(out.data)
        self.assertEqual(taps, [(600, 300)])
        self.assertEqual(data['target']['matches'], 1)
        self.assertTrue(data['expect_verified'])

    def test_expect_miss_is_soft_not_action_failure(self):
        h = _handler()
        fake, taps = self._fake_droid(
            [{'x': 600, 'y': 300, 't': '搜索', 'd': ''}],
            [{'src': 'tree', 't': '其他结果', 'desc': '', 'cls': 'Text',
              'x': 600, 'y': 900, 'rx': 500, 'ry': 337, 'click': True}])
        # expect 未命中绝不能再截图/OCR: 每个动作多 1-3s 是被真机证实的退化。
        fake.ocr = lambda *a, **k: (_ for _ in ()).throw(AssertionError('expect must not OCR'))
        with patch.dict(sys.modules, {'droid': fake}):
            out = h.do_gui_act({'action': 'tap', 'point': [600, 300],
                                'expect': '进入搜索结果页面'},
                               types.SimpleNamespace(content=''))
        data = json.loads(out.data)
        self.assertEqual(taps, [(600, 300)])
        self.assertFalse(data['expect_verified'])
        self.assertEqual(data['expect_state'], 'not_seen')
        self.assertTrue(data['expect_soft'])
        self.assertNotIn('verified', data)
        self.assertNotIn('uncertain', data)
        self.assertIn('不是动作失败', data['hint'])

    def test_ambiguous_target_picks_topmost_and_returns_alternatives(self):
        # 旧契约是"同名多解就报错让模型重来一轮"。真机实证这条契约在烧轮次: 2026-10-29 的
        # 四个会话里它触发了 4 次, 每次白付一轮(5.6s); 而候选排序"完全相等 + 从上到下"选中的
        # 正是真正的结果行(微信搜索页 8 个候选中的 `元梦之星` @(306,527))。
        # 新契约: 选一个 + 把落选清单带回同一轮, 模型用 target_index 就地纠正。
        h = _handler()
        fake, taps = self._fake_droid(
            [{'x': 600, 'y': 300, 't': '搜索', 'd': ''},
             {'x': 700, 'y': 500, 't': '搜索', 'd': ''}], [])
        with patch.dict(sys.modules, {'droid': fake}):
            out = h.do_gui_act({'action': 'tap', 'target': '搜索'},
                               types.SimpleNamespace(content=''))
        data = json.loads(out.data)
        self.assertEqual(taps, [(600, 300)])
        self.assertEqual(data['target']['matches'], 2)
        self.assertEqual(data['target']['chosen_by'], 'auto')
        self.assertEqual([a['point'] for a in data['target']['alternatives']], [[700, 500]])
        self.assertIn('target_index', data['target']['hint'])

    def test_target_alongside_point_is_not_an_error(self):
        # 模型反复同时给 target 和 point("我要点的是这个 + 大致位置"), 旧实现直接 ValueError。
        # 契约演化: 现在两者共存不报错, 且**文字命中就用文字**(见下面那条)。
        h = _handler()
        fake, taps = self._fake_droid(
            [{'x': 600, 'y': 300, 't': '搜索', 'd': ''}], [])
        with patch.dict(sys.modules, {'droid': fake}):
            out = h.do_gui_act({'action': 'tap', 'target': '搜索', 'point': [640, 320]},
                               types.SimpleNamespace(content=''))
        data = json.loads(out.data)
        self.assertNotIn('error', data)
        self.assertEqual(data['point'], [600, 300])

    def test_target_wins_over_a_guessed_point(self):
        # 2026-10-30 09:45 三角洲会话: target="查看今日密码" + point=[513,115](那是 647x1440 附图
        # 上量的)。旧口径位置优先 → 落在 (951,213) 也就是标题栏右上角的「分享」图标, 一次"看密码"
        # 变成了打开分享面板, 之后在取消/返回里绕了 6 轮。文字是全分辨率 OCR, 与坐标单位无关。
        h = _handler()
        fake, taps = self._fake_droid(
            [{'x': 517, 'y': 1320, 't': '查看今日密码', 'd': ''}], [])
        with patch.dict(sys.modules, {'droid': fake}):
            out = h.do_gui_act({'action': 'tap', 'target': '查看今日密码', 'point': [513, 115]},
                               types.SimpleNamespace(content=''))
        data = json.loads(out.data)
        self.assertEqual(taps, [(517, 1320)])
        self.assertEqual(data['target']['text'], '查看今日密码')

    def test_target_miss_falls_back_to_the_point_but_says_so(self):
        # 文字这一屏没有(可能在弹层后), 但坐标给了: 允许试坐标, 同时把"文字没命中"带回去,
        # 免得模型以为文字已经找到。
        h = _handler()
        fake, taps = self._fake_droid([], [])
        with patch.dict(sys.modules, {'droid': fake}):
            out = h.do_gui_act({'action': 'tap', 'target': '不存在的字', 'point': [640, 320]},
                               types.SimpleNamespace(content=''))
        data = json.loads(out.data)
        self.assertEqual(taps, [(640, 320)])
        self.assertIn('target_miss', data)
        self.assertNotIn('target', data)


class SeeRoutingTest(unittest.TestCase):
    def test_content_question_is_not_misclassified_as_screen_class(self):
        q = '当前屏幕显示什么内容？是否在搜索页面？有没有输入框？'
        self.assertFalse(ga_android._looks_like_screen_class_question(q))
        self.assertTrue(ga_android._looks_like_screen_class_question('当前画面是什么'))

    def test_see_budget_is_bounded_for_fast_fallback(self):
        self.assertLessEqual(ga_android.GenericAgentHandler._SEE_BUDGET_S, 20)

    def test_text_see_is_rejected_when_image_was_attached(self):
        h = _handler(_vision_in_turn_attached=True)
        fake = types.SimpleNamespace(shot=lambda: (_ for _ in ()).throw(AssertionError('no shot')))
        with patch.dict(sys.modules, {'droid': fake}):
            out = h.do_see({'question': '当前页面有什么内容', 'want': 'text'},
                           types.SimpleNamespace(content=''))
        data = json.loads(out.data)
        self.assertFalse(data['ok'])
        self.assertEqual(data['reason'], 'redundant_image')

    def test_same_screen_same_question_hits_cache(self):
        h = _handler()
        seen = []
        img = np.zeros((30, 20, 3), dtype='uint8')
        backend = types.SimpleNamespace(model='m', name='', api_base='x', provider='p')
        fake = types.SimpleNamespace(
            shot=lambda: img,
            active_backend=lambda: backend,
            _vision_cap=lambda b: 'ok',
            _backend_id=lambda b: 'm|x',
            _resolve_roi=lambda roi: (0, 0, 1000, 1000),
            _ASK_POINT_PROMPT='%s',
            ask_vision=lambda img, q, **kw: seen.append(q) or '按钮在中间',
            _parse_point=lambda t: (500, 500))
        with patch.dict(sys.modules, {'droid': fake}):
            one = json.loads(h.do_see({'question': '当前页面有什么文字', 'want': 'text'},
                                      types.SimpleNamespace(content='')).data)
            two = json.loads(h.do_see({'question': '当前页面有什么文字', 'want': 'text'},
                                      types.SimpleNamespace(content='')).data)
        self.assertTrue(one['ok'])
        self.assertFalse(one.get('cached', False))
        self.assertTrue(two.get('cached'))
        self.assertEqual(len(seen), 1)
        self.assertIn('只回答当前画面可直接看到的事实', seen[0])

    def test_failed_see_is_not_retried_on_the_same_screen(self):
        h = _handler()
        calls = []
        img = np.zeros((30, 20, 3), dtype='uint8')
        backend = types.SimpleNamespace(model='m', name='', api_base='x', provider='p')
        def boom(*a, **k):
            calls.append(1)
            raise ConnectionError('empty response')
        fake = types.SimpleNamespace(
            shot=lambda: img,
            active_backend=lambda: backend,
            _vision_cap=lambda b: 'ok',
            _backend_id=lambda b: 'm|x',
            _resolve_roi=lambda roi: (0, 0, 1000, 1000),
            _ASK_POINT_PROMPT='%s',
            ask_vision=boom,
            _parse_point=lambda t: (500, 500))
        with patch.dict(sys.modules, {'droid': fake}):
            one = json.loads(h.do_see({'question': '当前页面有什么文字', 'want': 'text'},
                                      types.SimpleNamespace(content='')).data)
            two = json.loads(h.do_see({'question': '当前页面有什么文字', 'want': 'text'},
                                      types.SimpleNamespace(content='')).data)
        self.assertFalse(one['ok'])
        self.assertFalse(two['ok'])
        self.assertEqual(two['reason'], 'already_failed')
        self.assertEqual(len(calls), 1)

    def test_second_different_text_question_in_same_turn_is_rejected(self):
        h = _handler()
        img = np.zeros((30, 20, 3), dtype='uint8')
        backend = types.SimpleNamespace(model='m', name='', api_base='x', provider='p')
        asked = []
        fake = types.SimpleNamespace(
            shot=lambda: img,
            active_backend=lambda: backend,
            _vision_cap=lambda b: 'ok',
            _backend_id=lambda b: 'm|x',
            _resolve_roi=lambda roi: (0, 0, 1000, 1000),
            _ASK_POINT_PROMPT='%s',
            ask_vision=lambda img, q, **kw: asked.append(q) or '屏幕内容',
            _parse_point=lambda t: (500, 500))
        with patch.dict(sys.modules, {'droid': fake}):
            one = json.loads(h.do_see({'question': '当前页面有什么文字', 'want': 'text'},
                                      types.SimpleNamespace(content='')).data)
            two = json.loads(h.do_see({'question': '当前页面有哪些按钮', 'want': 'text'},
                                      types.SimpleNamespace(content='')).data)
        self.assertTrue(one['ok'])
        self.assertEqual(two['reason'], 'redundant_turn')
        self.assertEqual(len(asked), 1)


class NewToolSchemaTest(unittest.TestCase):
    def _tools(self, name):
        return json.loads((CORE / 'assets' / name).read_text(encoding='utf-8'))

    def test_new_tools_exist_with_expected_required_params(self):
        import inspect
        import ga_android
        impl = {
            'observe': inspect.getsource(ga_android.GenericAgentHandler.do_observe),
            'ocr': inspect.getsource(ga_android.GenericAgentHandler.do_ocr),
            'finish_task': inspect.getsource(ga_android.GenericAgentHandler.do_finish_task),
        }
        for name in ('tools_schema.json', 'tools_schema_cn.json'):
            by = {t['function']['name']: t['function'] for t in self._tools(name)}
            for tool in ('observe', 'ocr', 'finish_task'):
                self.assertIn(tool, by, name)
                for prop in by[tool]['parameters']['properties']:
                    self.assertIn("'%s'" % prop, impl[tool], (name, tool, prop))
            self.assertEqual(by['finish_task']['parameters']['required'], ['status', 'result'])


if __name__ == '__main__':
    unittest.main()
