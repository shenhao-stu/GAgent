"""Regressions reproduced with GLM and the Android GUI task budget."""
import io
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/ga_runtime'
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(CORE / "gacore"))
import droid
from llmcore import ToolClient, _parse_text_tool_calls


class ToolArgumentsTest(unittest.TestCase):
    def parse(self, value):
        client = object.__new__(ToolClient)
        return client._parse_mixed_response('<tool_use>' + json.dumps(value) + '</tool_use>')

    def test_explicit_empty_arguments_do_not_absorb_metadata(self):
        result = self.parse({'name': 'no_arg_tool', 'arguments': {}, 'path': 'ignored'})
        self.assertEqual(json.loads(result.tool_calls[0].function.arguments), {})

    def test_nested_arguments_remain_authoritative(self):
        result = self.parse({'name': 'file_read', 'arguments': {'path': 'correct'}, 'path': 'ignored'})
        self.assertEqual(json.loads(result.tool_calls[0].function.arguments), {'path': 'correct'})

    def test_tool_tag_documentation_remains_plain_text(self):
        text = '工具调用使用 <tool_use> 标签。'
        self.assertEqual(_parse_text_tool_calls(text), ([], text))


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
    def test_droid_vision_entry_loads_user_adapter_only_when_called(self):
        from types import SimpleNamespace
        adapter = SimpleNamespace(ask_vision=lambda image, prompt, **kw: (image, prompt, kw))
        with patch.dict(sys.modules, {'vision_api': adapter}):
            self.assertEqual(droid.ask_vision('image', 'read', timeout=15),
                             ('image', 'read', {'timeout': 15}))

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
                cache = {'thumb': None, 'roi': None, 'dets': None}
                with patch.object(droid, '_LOOK_CACHE', cache), \
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
            with self.assertRaisesRegex(ValueError, 'ask_vision'):
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
        output = io.StringIO()
        with patch.object(droid, '_visual_only', return_value=True), patch.object(droid, '_act', return_value={'ok': True}) as act, redirect_stdout(output):
            result = droid.paste('search query')
        self.assertIn('尚未输入', output.getvalue())
        self.assertNotIn('search query', output.getvalue())
        self.assertEqual(act.call_args.kwargs['op'], 'clipboard')
        self.assertFalse(result['hit'])
        self.assertTrue(result['needs_gui_paste'])

    def test_dump_never_reads_sensitive_tree(self):
        with patch.object(droid, 'SAFE_MODE', True), patch.object(droid, '_get') as get:
            self.assertEqual(droid.dump(), [])
        get.assert_not_called()


if __name__ == '__main__': unittest.main()
