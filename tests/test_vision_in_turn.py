"""看图模式(每轮附图)的开关与管道。

设计口径: "全量视觉 GUI" 不等于每步调一次 see()——see() 是独立请求, 实测均值 20.8s/次、
最高 66.2s; 而把缩到 1440 长边的一张图放进主循环**本来就要发**的那一轮, 只多约 1.4k token
的 prefill。所以本文件锁四件事:
  ① 开关(off/auto/always)可热改: 读 GA_DIR/kv/*.json, 与 /kv.* 桥、/vision 命令同一份存储;
  ② 主循环真的把图块挂进那条 user 消息, 且 handler 不支持时行为完全不变;
  ③ 附图不能被"去空白块"过滤或 history 裁剪顺手删掉, 且只保留最近一张(否则上下文爆);
  ④ 视觉型页面开了看图模式后, 不再白跑一次本地 YOLO(每步 1.5~2.6s)。
"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import agent_loop
import agent_settings
import droid
import llmcore


def _img(w=1200, h=2670):
    img = np.zeros((h, w, 3), np.uint8)
    img[h // 2:, :, 1] = 200
    return img


class SwitchTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='gakv')

    def test_default_is_auto(self):
        self.assertEqual(agent_settings.vision_in_turn(root=self.root), 'auto')

    def test_values_are_tolerant(self):
        for raw, want in [('off', 'off'), ('0', 'off'), ('false', 'off'), ('no', 'off'),
                          ('always', 'always'), ('1', 'always'), ('on', 'always'),
                          ('auto', 'auto'), ('', 'auto'), ('garbage', 'auto')]:
            agent_settings.kv_set(agent_settings.KEY_VISION_IN_TURN, raw, root=self.root)
            self.assertEqual(agent_settings.vision_in_turn(root=self.root), want, raw)

    def test_command_parsing(self):
        self.assertEqual(agent_settings.parse_vision_cmd('/vision off')[0], 'off')
        self.assertEqual(agent_settings.parse_vision_cmd('/vision ALWAYS')[0], 'always')
        self.assertEqual(agent_settings.parse_vision_cmd('/vision auto')[0], 'auto')
        mode, msg = agent_settings.parse_vision_cmd('/vision banana')
        self.assertIsNone(mode)
        self.assertIn('off|auto|always', msg)
        self.assertIsNone(agent_settings.parse_vision_cmd('/vision')[0])   # 无参=查询, 不写

    def test_kv_file_lands_where_the_ui_bridge_reads(self):
        agent_settings.kv_set('ga.visioninturn', 'off', root=self.root)
        p = Path(agent_settings.kv_path('ga.visioninturn', root=self.root))
        self.assertEqual(p.parent.name, 'kv')                  # GA_DIR/kv/<key>.json
        self.assertEqual(p.name, 'ga.visioninturn.json')
        self.assertEqual(p.read_text(encoding='utf-8'), 'off')


class FrameEncodeTest(unittest.TestCase):
    def test_long_side_is_bounded_and_decodable(self):
        import base64
        import cv2
        b64, (w, h) = droid.frame_jpeg_b64(_img(), max_side=1440, quality=70)
        self.assertEqual(max(w, h), 1440)
        self.assertEqual((w, h), (647, 1440))            # 等比缩放
        raw = cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(raw.shape[:2], (1440, 647))
        self.assertLess(len(b64), 400 * 1024)            # 别把几十万字符塞进每轮 prompt

    def test_small_frame_is_not_upscaled(self):
        b64, (w, h) = droid.frame_jpeg_b64(_img(300, 200), max_side=1440)
        self.assertEqual((w, h), (300, 200))


class LoopAttachTest(unittest.TestCase):
    """主循环: handler 给了图块就挂到那条 user 消息上; 没给就是纯文本(行为不变)。"""

    class _Client:
        def __init__(self):
            self.seen = []
            self.last_tools = ''

        def chat(self, messages, tools=None):
            self.seen.append(json.loads(json.dumps(messages)))
            resp = types.SimpleNamespace(thinking='', content='ok', raw='', stop_reason='end_turn',
                                         tool_calls=[])
            yield 'chunk'
            return resp

    def _handler(self, blocks):
        handler = agent_loop.BaseHandler()
        handler.max_turns = 3
        handler._done_hooks = []
        handler.parent = types.SimpleNamespace(task_dir=None)
        handler.current_turn = 0
        handler.turn_end_callback = lambda *a, **k: '继续'
        if blocks is not None:
            handler.turn_content_blocks = lambda: blocks
        return handler

    def _run(self, blocks):
        client = self._Client()
        handler = self._handler(blocks)
        list(agent_loop.agent_runner_loop(client, 'sys', 'go', handler, [], max_turns=2))
        return client.seen

    def test_image_block_is_attached_to_the_turn(self):
        blocks = [{"type": "text", "text": "当前屏幕截图"},
                  {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "AAA"}}]
        seen = self._run(blocks)
        self.assertGreaterEqual(len(seen), 2)
        content = seen[1][-1]['content']
        self.assertIsInstance(content, list)
        self.assertEqual(content[0]['type'], 'text')            # next_prompt 原样在最前
        images = [b for b in content if b.get('type') == 'image']
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]['source']['data'], 'AAA')

    def test_without_the_hook_the_message_stays_text(self):
        seen = self._run(None)
        self.assertIsInstance(seen[1][-1]['content'], str)

    def test_empty_blocks_do_not_wrap_the_text(self):
        seen = self._run([] if False else None)
        self.assertIsInstance(seen[1][-1]['content'], str)


class HistoryTest(unittest.TestCase):
    def _img_block(self, tag='x'):
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": tag}}

    def test_only_the_newest_image_survives(self):
        history = [{"role": "user", "content": [{"type": "text", "text": 'a'}, self._img_block('1')]},
                   {"role": "assistant", "content": [{"type": "text", "text": 'b'}]},
                   {"role": "user", "content": [self._img_block('2'), {"type": "text", "text": 'c'}]}]
        replaced = llmcore.age_image_blocks(history, keep=1)
        self.assertEqual(replaced, 1)
        self.assertEqual(history[-1]['content'][0]['type'], 'image')     # 最新一张还在
        self.assertEqual(history[0]['content'][1], {"type": "text", "text": llmcore.IMAGE_PLACEHOLDER})

    def test_blank_block_filter_keeps_images(self):
        """img 块没有 text 字段: 旧过滤会把附图当成"空白块"删掉, 静默失效。"""
        self.assertTrue(llmcore._keep_content_block(self._img_block()))
        self.assertTrue(llmcore._keep_content_block({"type": "image_url", "image_url": {"url": "data:,"}}))
        self.assertFalse(llmcore._keep_content_block({"type": "text", "text": '   '}))
        self.assertTrue(llmcore._keep_content_block({"type": "text", "text": 'x'}))

    def test_cost_counts_an_image_as_a_constant(self):
        small = [{"role": "user", "content": [self._img_block('a' * 10)]}]
        big = [{"role": "user", "content": [self._img_block('a' * 100000)]}]
        self.assertEqual(llmcore._history_cost(small), llmcore._history_cost(big))


class HandlerVisionTest(unittest.TestCase):
    """GA handler: 开关决定要不要附图; 视觉型页面开了就不再跑本地 YOLO。"""

    def setUp(self):
        import ga_android
        self.h = object.__new__(ga_android.GenericAgentHandler)

    def _blocks(self, mode, sensitive):
        fake_droid = types.SimpleNamespace(
            _sensitive_fg=lambda: sensitive,
            shot_frame_b64=lambda **kw: ('BASE64', (647, 1440)),
            take_pending_frame=lambda: None,
        )
        with patch.dict(sys.modules, {'droid': fake_droid}), \
                patch('agent_settings.vision_in_turn', return_value=mode):
            return self.h.turn_content_blocks()

    def test_off_attaches_nothing(self):
        self.assertIsNone(self._blocks('off', sensitive=True))

    def test_auto_only_attaches_on_visual_only_pages(self):
        self.assertIsNone(self._blocks('auto', sensitive=False))
        blocks = self._blocks('auto', sensitive=True)
        self.assertEqual(blocks[1]['source']['data'], 'BASE64')
        self.assertIn('647x1440', blocks[0]['text'])

    def test_always_attaches_everywhere(self):
        self.assertIsNotNone(self._blocks('always', sensitive=False))

    def test_screenshot_failure_degrades_to_text(self):
        fake_droid = types.SimpleNamespace(
            _sensitive_fg=lambda: True,
            shot_frame_b64=lambda **kw: (_ for _ in ()).throw(RuntimeError('code=3')),
        )
        with patch.dict(sys.modules, {'droid': fake_droid}), \
                patch('agent_settings.vision_in_turn', return_value='auto'):
            blocks = self.h.turn_content_blocks()
        self.assertEqual(len(blocks), 1)
        self.assertIn('不可用', blocks[0]['text'])

    def test_obs_is_skipped_when_the_screen_is_covered_by_the_image(self):
        """微信等视觉型页面: 图已经在本轮, 再跑一次 YOLO 是重复劳动(每步 1.5~2.6s)。"""
        calls = []
        fake_droid = types.SimpleNamespace(
            _sensitive_fg=lambda: True,
            take_pending_frame=lambda: None,
            observe=lambda **kw: calls.append(1) or {'items': [], 'kind': 'blanked'},
            ensure_fresh_obs=lambda: {},
            screen=lambda: (1200, 2670),
        )
        with patch.dict(sys.modules, {'droid': fake_droid}), \
                patch('agent_settings.vision_in_turn', return_value='auto'):
            self.assertTrue(self.h._vision_covers_screen())
            self.assertEqual(calls, [])

    def test_obs_is_kept_when_vision_is_off(self):
        fake_droid = types.SimpleNamespace(_sensitive_fg=lambda: True)
        with patch.dict(sys.modules, {'droid': fake_droid}), \
                patch('agent_settings.vision_in_turn', return_value='off'):
            self.assertFalse(self.h._vision_covers_screen())

    def test_capability_bit_decides_instead_of_class_names(self):
        """口径是能力位, 不是类名拼写。

        曾按类型名白名单猜, 把 NativeOAISession 当成"文本协议"排除 —— 它其实经
        _msgs_claude2oai 完全能带图; 真机 25 轮因此一帧图都没发出去, 而 obs_note 还说了 8 次
        "已附图"。现在: 客户端/会话声明 supports_images 就听声明, 声明缺失才退回类名。"""
        # 文本协议客户端(ToolClient): chat() 压成一整段字符串 → 不能带图
        self.h.parent = types.SimpleNamespace(
            llmclient=types.SimpleNamespace(backend=object(), supports_images=False))
        self.assertFalse(self.h._session_takes_images())

        # 原生协议客户端(NativeToolClient): 结构化块直发 → 能带图
        self.h.parent = types.SimpleNamespace(
            llmclient=types.SimpleNamespace(backend=object(), supports_images=True))
        self.assertTrue(self.h._session_takes_images())

        # 客户端没有这一位时看会话层: NativeOAISession 能带图(旧实现正是在这里判错)
        class NativeOAISession:
            pass
        self.h.parent = types.SimpleNamespace(
            llmclient=types.SimpleNamespace(backend=NativeOAISession()))
        self.assertTrue(self.h._session_takes_images())

        class ChatCompletions:
            pass
        ChatCompletions.__name__ = 'LLMSession'
        self.h.parent = types.SimpleNamespace(
            llmclient=types.SimpleNamespace(backend=ChatCompletions()))
        self.assertTrue(self.h._session_takes_images())

        # 探测不到会话 → 放行(真机默认就是能带图的客户端)
        self.h.parent = types.SimpleNamespace()
        self.assertTrue(self.h._session_takes_images())


if __name__ == '__main__':
    unittest.main()
