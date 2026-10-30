"""Regressions reproduced with GLM and the Android GUI task budget."""
import io
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import droid
from llmcore import ToolClient, _parse_text_tool_calls


class ToolArgumentsTest(unittest.TestCase):
    def parse(self, value):
        client = object.__new__(ToolClient)
        return client._parse_mixed_response('<tool_use>' + json.dumps(value) + '</tool_use>')

    def test_glm_flat_file_read_retains_path(self):
        result = self.parse({'name': 'file_read', 'path': 'memory/phone_use.md', 'start': 1})
        self.assertEqual(json.loads(result.tool_calls[0].function.arguments),
                         {'path': 'memory/phone_use.md', 'start': 1})

    def test_flat_code_run_retains_execution_type(self):
        result = self.parse({'name': 'code_run', 'type': 'python', 'timeout': 20})
        self.assertEqual(json.loads(result.tool_calls[0].function.arguments),
                         {'type': 'python', 'timeout': 20})

    def test_explicit_empty_arguments_do_not_absorb_metadata(self):
        result = self.parse({'name': 'no_arg_tool', 'arguments': {}, 'path': 'ignored'})
        self.assertEqual(json.loads(result.tool_calls[0].function.arguments), {})

    def test_nested_arguments_remain_authoritative(self):
        result = self.parse({'name': 'file_read', 'arguments': {'path': 'correct'}, 'path': 'ignored'})
        self.assertEqual(json.loads(result.tool_calls[0].function.arguments), {'path': 'correct'})

    def test_glm_multiple_fenced_open_tags_keep_all_calls(self):
        client = object.__new__(ToolClient)
        result = client._parse_mixed_response(
            '```<tool_use>\n{"name":"file_read","path":"one"}\n```\n'
            '```<tool_use>\n{"name":"file_read","path":"two"}\n```')
        self.assertEqual([json.loads(t.function.arguments)['path'] for t in result.tool_calls], ['one', 'two'])

    def test_fence_inside_script_does_not_end_tool_json(self):
        client = object.__new__(ToolClient)
        value = {'name': 'code_run', 'script': "print('```')"}
        result = client._parse_mixed_response('```<tool_use>\n' + json.dumps(value) + '\n```')
        self.assertEqual(json.loads(result.tool_calls[0].function.arguments)['script'], value['script'])

    def test_malformed_tool_json_requests_repair_instead_of_final(self):
        text = '<tool_use>{"name":"code_run","arguments":{"script":"print(1)"}\n</tool_use>'
        calls, _ = _parse_text_tool_calls(text)
        self.assertEqual([c.function.name for c in calls], ['bad_json'])

    def test_truncated_tool_call_is_not_a_final_answer(self):
        calls, _ = _parse_text_tool_calls('<tool_use>{"name":"code_run","arguments":')
        self.assertEqual([c.function.name for c in calls], ['bad_json'])

    def test_malformed_batch_executes_nothing_before_repair(self):
        text = ('<tool_use>{"name":"code_run","arguments":{"script":"print(1)"}}</tool_use>'
                '<tool_use>{"name":"code_run","arguments":null}</tool_use>')
        calls, _ = _parse_text_tool_calls(text)
        self.assertEqual([c.function.name for c in calls], ['bad_json'])

    def test_tool_tag_documentation_remains_plain_text(self):
        text = '工具调用使用 <tool_use> 标签。'
        self.assertEqual(_parse_text_tool_calls(text), ([], text))

    def test_loop_repairs_malformed_call_then_executes_once(self):
        from types import SimpleNamespace
        from agent_loop import BaseHandler, StepOutcome, agent_runner_loop, exhaust
        replies = iter([
            '<tool_use>{"name":"code_run","arguments":{"script":"print(1)"}</tool_use>',
            '<tool_use>{"name":"code_run","arguments":{"script":"print(1)"}}</tool_use>',
            '完成',
        ])
        class Client:
            def chat(self, **kwargs):
                if False: yield
                return object.__new__(ToolClient)._parse_mixed_response(next(replies))
        class Handler(BaseHandler):
            parent = SimpleNamespace(task_dir='')
            _done_hooks = []
            calls = 0
            def do_code_run(self, args, response):
                self.calls += 1
                return StepOutcome('executed', next_prompt='verify result')
            def do_no_tool(self, args, response):
                return StepOutcome(response.content)
        handler = Handler()
        outcome = exhaust(agent_runner_loop(Client(), '', 'test', handler, [], max_turns=3))
        self.assertEqual(handler.calls, 1)
        self.assertEqual(outcome, {'result': 'CURRENT_TASK_DONE', 'data': '完成'})


class VisionResponseTest(unittest.TestCase):
    def test_claude_vision_uses_the_configured_output_budget(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('vision_template', CORE / 'memory/vision_api.template.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        cfg = {'apibase': 'https://example.test/anthropic', 'apikey': 'test-placeholder',
               'model': 'test', 'max_tokens': 4096}
        with patch.object(module, '_cfg', return_value=cfg), patch.object(module.requests, 'post') as post:
            post.return_value.json.return_value = {'content': [{'type': 'text', 'text': 'OK'}]}
            module._call_claude('fakeimage', 'read', 10)
            self.assertEqual(post.call_args.kwargs['json']['max_tokens'], 4096)
            module._call_claude('fakeimage', 'read', 10, max_tokens=2048)
            self.assertEqual(post.call_args.kwargs['json']['max_tokens'], 2048)

    def test_truncated_vision_answer_is_not_a_completed_observation(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('vision_template', CORE / 'memory/vision_api.template.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        cfg = {'apibase': 'https://example.test/anthropic', 'apikey': 'test-placeholder', 'model': 'test'}
        with patch.object(module, '_cfg', return_value=cfg), patch.object(module.requests, 'post') as post:
            for content in ([{'type': 'thinking', 'thinking': 'incomplete'}],
                            [{'type': 'text', 'text': 'The selected option is'}]):
                with self.subTest(content_type=content[0]['type']):
                    post.return_value.json.return_value = {'stop_reason': 'max_tokens', 'content': content}
                    with self.assertRaisesRegex(ValueError, 'truncated'):
                        module._call_claude('fakeimage', 'read', 10)

    def test_openai_vision_accepts_the_same_base_urls_as_text(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('vision_template', CORE / 'memory/vision_api.template.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        for base, expected in [
            ('https://example.test', 'https://example.test/v1/chat/completions'),
            ('https://example.test/v1/', 'https://example.test/v1/chat/completions'),
            ('https://example.test/api/v4', 'https://example.test/api/v4/chat/completions'),
            ('https://example.test/v1/chat/completions', 'https://example.test/v1/chat/completions'),
            ('https://example.test/custom$', 'https://example.test/custom'),
        ]:
            with self.subTest(base=base), patch.object(module.requests, 'post') as post:
                post.return_value.json.return_value = {'choices': [{'message': {'content': 'visible'}}]}
                result = module._call_openai_compat('image', 'read', 10, apibase=base,
                                                   apikey='fixture-credential', model='vision',
                                                   proxy='http://127.0.0.1:7890')
                self.assertEqual(result, 'visible')
                self.assertEqual(post.call_args.args[0], expected)
                self.assertEqual(post.call_args.kwargs['proxies']['https'], 'http://127.0.0.1:7890')

    def test_thinking_before_text_is_not_treated_as_missing_answer(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('vision_template', CORE / 'memory/vision_api.template.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        cfg = {'apibase': 'https://example.test/anthropic', 'apikey': 'test-placeholder', 'model': 'test', 'thinking_type': 'disabled'}
        with patch.object(module, '_cfg', return_value=cfg), patch.object(module.requests, 'post') as post:
            post.return_value.json.return_value = {'content': [
                {'type': 'thinking', 'thinking': 'internal'}, {'type': 'text', 'text': 'visible answer'}]}
            self.assertEqual(module._call_claude('fakeimage', 'locate button', 10), 'visible answer')
            self.assertEqual(post.call_args.kwargs['json']['thinking'], {'type': 'disabled'})


    def test_claude_vision_uses_provider_proxy(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('vision_template', CORE / 'memory/vision_api.template.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        cfg = {'apibase': 'https://example.test/anthropic', 'apikey': 'test-placeholder',
               'model': 'test', 'proxy': 'http://127.0.0.1:7890'}
        with patch.object(module, '_cfg', return_value=cfg), patch.object(module.requests, 'post') as post:
            post.return_value.json.return_value = {'content': [{'type': 'text', 'text': 'OK'}]}
            module._call_claude('fakeimage', 'read', 10)
            self.assertEqual(post.call_args.kwargs.get('proxies'),
                             {'http': cfg['proxy'], 'https': cfg['proxy']})


class VisionEntryTest(unittest.TestCase):
    """视觉入口的响应契约。

    机制已换: 旧走 memory/vision_api.py 用户适配器(要自己拷模板自己配 key), 现在走
    vision_llm.ask_with_backend 复用任务页当前模型。下面两条响应契约**原样保留**,
    只是换成了新后端——它们都是真机踩出来的, 与用哪个后端无关。
    """

    def _active(self):
        droid.set_active_backend(object())
        self.addCleanup(droid.set_active_backend, None)
        droid.reset_vision_fuse()
        self.addCleanup(droid.reset_vision_fuse)

    def test_entry_needs_no_vision_api_module(self):
        """视觉入口不得再依赖 memory/vision_api.py: 那个文件默认不存在(只有 .template.py),
        旧实现因此必然报"视觉不可用"。"""
        import vision_llm
        self._active()
        ask = Mock(wraps=lambda backend, image, prompt, **kw: 'ok')
        with patch.dict(sys.modules), patch.object(vision_llm, 'ask_with_backend', ask):
            sys.modules.pop('vision_api', None)
            self.assertEqual(droid.ask_vision('image', 'read', timeout=15), 'ok')
        self.assertEqual(ask.call_args.kwargs['timeout'], 15)

    def test_empty_vision_answer_raises_instead_of_passing_through_silently(self):
        # 真机实证: 某轮 ask_vision 返回空串, stdout 只剩 _prepare_image 的「缩放/Base64」两行 print,
        # agent 把"没有回答"当成功并整轮重问同一问题(白付一轮模型 + ~17s)。
        # 空/纯空白一律显式失败, 不让无信号结果流过。
        import vision_llm
        for empty in ('', '   ', '\n\t', None):
            self._active()
            with patch.object(vision_llm, 'ask_with_backend',
                              lambda backend, image, prompt, _v=empty, **kw: _v):
                with self.assertRaisesRegex(RuntimeError, '空响应'):
                    droid.ask_vision('image', 'read')

    def test_visible_error_string_still_passes_through(self):
        """"Error: ..." 是可见失败, 由调用方按错误处理; 不在此改写成异常。"""
        import vision_llm
        self._active()
        with patch.object(vision_llm, 'ask_with_backend',
                          lambda backend, image, prompt, **kw: 'Error: 请求超时'):
            self.assertEqual(droid.ask_vision('image', 'read'), 'Error: 请求超时')

    def test_code_run_exposes_lazy_vision_entry(self):
        import subprocess
        script = """
import sys, types
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).resolve().parents[1]))
header = Path(sys.argv[1]).read_text()
ns = {'__file__': '/tmp/ga/temp/_code_run.py'}
exec(compile(header, 'code_run_header.py', 'exec'), ns)
assert callable(ns.get('ask_vision')), 'code_run must expose ask_vision'
vision = types.ModuleType('vision_api')
vision.ask_vision = lambda image, prompt, **kw: (image, prompt, kw)
sys.modules['vision_api'] = vision
assert ns['ask_vision']('image', 'read', timeout=15) == ('image', 'read', {'timeout': 15})
"""
        result = subprocess.run([sys.executable, '-c', script, str(CORE / 'assets/code_run_header.py')],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


class VisualObservationTest(unittest.TestCase):
    def test_label_filter_keeps_all_matches_and_screen_coordinates(self):
        import numpy as np
        for height, width in [(200, 100), (100, 200), (240, 300)]:
            with self.subTest(size=(width, height)):
                frame = np.zeros((height, width, 3), dtype=np.uint8)
                detections = [{'bbox': [5, 6, 25, 26], 'label': '搜索入口'},
                              {'bbox': [30, 6, 50, 26], 'label': '搜索'},
                              {'bbox': [55, 6, 75, 26], 'label': '取消'},
                              {'bbox': [80, 6, 90, 26], 'label': None}]
                cache = {'thumb': None, 'roi': None, 'pkg': None, 'rot': None, 'res': None}
                with patch.object(droid, '_OBS_CACHE', cache), \
                     patch.object(droid, 'shot', return_value=frame) as shot, \
                     patch.object(droid, 'ui_detect', return_value=detections) as detect:
                    hits = droid.look(roi='lower', label='搜索')
                    self.assertEqual([d['label'] for d in hits], ['搜索入口', '搜索'])
                    self.assertEqual([(d['x'], d['y']) for d in hits],
                                     [(15, height // 2 + 16), (40, height // 2 + 16)])
                    other = droid.look(roi='lower', label='取消')
                    self.assertEqual([d['label'] for d in other], ['取消'])
                    self.assertTrue(other[0]['cached'])
                    self.assertEqual(len(droid.look(roi='lower')), 4)
                    self.assertEqual(droid.look(roi='lower', label='不存在'), [])
                    self.assertEqual(detect.call_count, 1)
                    self.assertEqual(shot.call_count, 4)

    def test_invalid_label_is_rejected_before_capture(self):
        with patch.object(droid, 'shot') as shot:
            with self.assertRaisesRegex(TypeError, 'label must be a string'):
                droid.look(label=123)
        shot.assert_not_called()

    def test_look_rejects_prompts_before_capturing_a_frame(self):
        with patch.object(droid, 'shot') as shot:
            with self.assertRaisesRegex(ValueError, 'see\\(\\)'):
                droid.look('read the first two cards')
        shot.assert_not_called()

    def test_icon_labels_are_safe_to_filter_as_text(self):
        import numpy as np
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        detections = [{'bbox': [10, 20, 30, 40], 'label': None, 'cls': 'Icon'},
                      {'bbox': [40, 50, 60, 70], 'label': '搜索', 'cls': 'Text'}]
        with patch.object(droid, 'shot', return_value=frame), patch.object(droid, 'ui_detect', return_value=detections):
            result = droid.look(cache=False)
        self.assertEqual([d['label'] for d in result], ['', '搜索'])
        self.assertEqual([d['label'] for d in result if '搜索' in d['label']], ['搜索'])


class TaskBudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, val in [('_UNLOCK_FILE', self.tmp.name + '/unlock.json'),
                          ('_RISK_FILE', self.tmp.name + '/risk.json')]:
            ctx = patch.object(droid, name, val); ctx.start(); self.addCleanup(ctx.stop)
        ctx = patch.dict(droid.SENSITIVE_APPS, {'com.tencent.mm': {
            **droid.SENSITIVE_APPS['com.tencent.mm'], 'min_gap': 0}})
        ctx.start(); self.addCleanup(ctx.stop)

    def test_gui_navigation_has_no_arbitrary_action_budget(self):
        for _ in range(100):
            droid._gate_injection('tap', 'com.tencent.mm')
        self.assertEqual(droid.sensitive_unlock('com.tencent.mm', actions=3), {})
        self.assertNotIn('budget', droid.SENSITIVE_APPS['com.tencent.mm'])

    def test_gui_policy_still_blocks_notification_send(self):
        with self.assertRaises(RuntimeError):
            droid._gate_injection('reply_notification', 'com.tencent.mm')

    def test_risk_event_stops_further_actions(self):
        droid.sensitive_risk_event('com.tencent.mm', kind='captcha')
        with self.assertRaises(RuntimeError): droid._gate_injection('tap', 'com.tencent.mm')

    def test_visual_only_paste_never_calls_node_paste(self):
        """视觉型 App 只能走"剪贴板 + 可见 GUI 粘贴": 无论自动那一步成不成, 都不许下发节点输入,
        而且必须如实说明文本仍在剪贴板(不能把"已设剪贴板"当成已输入)。"""
        output = io.StringIO()
        with patch.object(droid, '_sensitive_fg', return_value=True), patch.object(droid, '_act', return_value={'ok': True}) as act, redirect_stdout(output):
            result = droid.paste('search query')
        self.assertIn('剪贴板', output.getvalue())
        self.assertNotIn('search query', output.getvalue())
        self.assertNotIn('paste', [c.kwargs.get('op') for c in act.call_args_list])
        self.assertEqual(act.call_args_list[0].kwargs['op'], 'clipboard')
        self.assertFalse(result['hit'])
        self.assertTrue(result['needs_gui_paste'])

    def test_dump_never_reads_sensitive_tree(self):
        with patch.object(droid, '_fg', return_value='com.tencent.mm'), patch.object(droid, '_get') as get:
            self.assertEqual(droid.dump(), [])
        get.assert_not_called()


if __name__ == '__main__': unittest.main()
