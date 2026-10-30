"""F3: 历史压缩参数化 + 更激进的默认值。

真机实证: 长任务(30+ 轮)历史不压缩时 in_tok 从 11K 涨到 36K,
model_wait 从 3s 涨到 37s——上下文膨胀是后期变慢的主因。
经实测对比选择此方案效果更佳: keep_recent=4(只保留最近 4 轮完整)/max_len=600。

红线(评审实证): [0] 是协议载体(_build_protocol_prompt 把 system + 交互协议 +
工具清单 + L1 记忆索引拼成首条 prompt), 它不是"旧轮次"。裁它会让第 N 轮起
模型既看不到 <tool_use> 协议也看不到记忆路由——压缩把上下文治膨胀, 不能把协议治丢。
"""
import json
import sys
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
from llmcore import compress_history_tags, trim_messages_history


def _msgs(n):
    out = []
    for i in range(n):
        out.append({'role': 'user', 'content': '<tool_use>{"name":"code_run","arguments":{"script":"%s"}}</tool_use><tool_result>%s</tool_result>%s' % ('x' * 2000, 'y' * 2000, 'z' * 2000)})
    return out


def _protocol_prompt():
    """真实形态的首条 prompt: system + 交互协议 + 工具清单 + L1 记忆索引 + 用户任务。
    必须真的超过 max_len(600)——短样本踩不到截断分支, 测试会空转(评审实证:
    原测试只用 2000 字符的合成 tool_use 消息, 从未覆盖 message 0 承载协议的情形)。
    这里按真实首条 prompt 的量级拼(工具清单 JSON 占大头)。"""
    tools = [{"name": "gui_act", "description": "Phone GUI structured action. " * 12},
             {"name": "code_run", "description": "Code executor. " * 12},
             {"name": "file_read", "description": "Read file. " * 12},
             {"name": "ask_user", "description": "Interrupt task to ask user. " * 12}]
    return ('### 交互协议 (必须严格遵守，持续有效)\n'
            '1. **思考**: 在 `<thinking>` 标签中先进行思考，分析现状和策略。\n'
            '2. **总结**: 在 `<summary>` 中输出极为简短的高度概括的单行物理快照。\n'
            '3. **行动**: 如需调用工具，请在回复正文之后输出一个（或多个）<tool_use>块，然后结束。\n'
            '### Tools (mounted, always in effect):\n'
            + json.dumps(tools, ensure_ascii=False) + '\n'
            '<global_mem_insight>Canvas/self-drawn 页面视觉纪律: 禁把 tap diff 当成功证据、'
            '禁指纹比对认卡、层叠棋盘禁固定平面网格</global_mem_insight>\n'
            '用户任务: 打开美团帮我点一份外卖')


class _Sess:
    context_win = 10
    trim_keep_rate = 0.6


class _BigSess:
    """体积上限拉到极大, 单独验证条数上限——否则两条路径互相干扰, 测不到想测的那条。"""
    context_win = 10 ** 9
    trim_keep_rate = 0.6


class CompressionParamsTest(unittest.TestCase):
    def setUp(self):
        compress_history_tags._cd = 0
        self.addCleanup(lambda: setattr(compress_history_tags, '_cd', 0))

    def test_older_messages_truncated_recent_kept(self):
        msgs = _msgs(10)
        compress_history_tags(msgs, keep_recent=4, max_len=600, force=True)
        # [0] 是协议载体不动, 更早的轮次压到 max_len, 近期轮次压到 recent_max_len
        self.assertIn('[Truncated]', msgs[1]['content'])
        self.assertNotIn('[Truncated]', msgs[0]['content'])
        self.assertLess(len(msgs[1]['content']), 800)          # 旧轮次: 600 封顶
        self.assertLessEqual(len(msgs[-1]['content']), 3000)   # 近期轮次: 3000 封顶

    def test_recent_messages_get_a_generous_but_finite_cap(self):
        """回归(真机实证): 近期轮次原来完全不做限制, 平均 4922 字符、占 resend 的
        67%(19687/29287)——压缩把旧的压到 600, 体量全留给最新的几条, 每轮输入照样膨胀。
        in_tok 与 model_wait 相关系数 r=0.574(11.2K→6.0s, 14.5K→13.9s)。
        近期轮次必须也有上限, 但要比旧轮次宽松(它们对决策最有用)。"""
        msgs = _msgs(10)
        compress_history_tags(msgs, keep_recent=4, max_len=600, force=True)
        old = len(msgs[1]['content'])
        recent = len(msgs[-1]['content'])
        self.assertGreater(recent, old)                 # 近期确实更宽松
        self.assertLessEqual(recent, 3000)              # 但不是无限
        # 短于上限的近期消息不该被动
        short = [{'role': 'user', 'content': 'tiny'}]
        compress_history_tags(short, keep_recent=4, force=True)
        self.assertEqual(short[0]['content'], 'tiny')

    def test_recent_cap_is_overridable(self):
        msgs = _msgs(6)
        compress_history_tags(msgs, keep_recent=4, max_len=600, force=True, recent_max_len=1200)
        self.assertLessEqual(len(msgs[-1]['content']), 1200)

    def test_protocol_carrier_not_truncated(self):
        # 真实形态: [0]=协议载体 + 9 轮对话。第 5 轮起触发压缩, 协议必须完整存活。
        msgs = [{'role': 'user', 'content': _protocol_prompt()}] + _msgs(9)
        original = msgs[0]['content']
        self.assertGreater(len(original), 600)        # 样本必须真的踩到截断分支, 否则测试空转
        for _ in range(10):
            compress_history_tags(msgs, keep_recent=4, max_len=600, interval=5)
        self.assertEqual(msgs[0]['content'], original)
        for marker in ('交互协议', 'Tools (mounted', 'global_mem_insight', 'gui_act'):
            self.assertIn(marker, msgs[0]['content'])
        self.assertIn('[Truncated]', msgs[1]['content'])   # 压缩确实发生在旧轮次上

    def test_protocol_carrier_survives_over_cap_force_compression(self):
        # 超限强压(force=True)同样不能动协议载体
        msgs = [{'role': 'user', 'content': _protocol_prompt()}] + _msgs(12)
        original = msgs[0]['content']
        compress_history_tags(msgs, keep_recent=4, force=True)
        self.assertEqual(msgs[0]['content'], original)

    def test_system_message_not_truncated(self):
        msgs = [{'role': 'system', 'content': 'S' * 3000}] + _msgs(6)
        compress_history_tags(msgs, keep_recent=4, max_len=600, force=True)
        self.assertEqual(len(msgs[0]['content']), 3000)
        self.assertIn('[Truncated]', msgs[1]['content'])

    def test_truncation_keeps_head_and_tail(self):
        msgs = [{'role': 'user', 'content': _protocol_prompt()},
                {'role': 'user', 'content': '<tool_use>HEAD' + 'm' * 3000 + 'TAIL</tool_use>'}]
        compress_history_tags(msgs, keep_recent=0, max_len=600, force=True)
        self.assertIn('HEAD', msgs[1]['content'])
        self.assertIn('TAIL', msgs[1]['content'])
        self.assertIn('[Truncated]', msgs[1]['content'])

    def test_history_and_key_info_blocks_collapsed(self):
        body = '<history>' + 'h' * 3000 + '</history><key_info>' + 'k' * 1000 + '</key_info>'
        msgs = [{'role': 'user', 'content': _protocol_prompt()},
                {'role': 'user', 'content': body}]
        compress_history_tags(msgs, keep_recent=0, force=True)
        self.assertIn('<history>[...]</history>', msgs[1]['content'])
        self.assertIn('<key_info>[...]</key_info>', msgs[1]['content'])

    def test_interval_still_observed(self):
        # interval=5: 前 4 次调用不压缩, 第 5 次压缩
        msgs = [{'role': 'user', 'content': _protocol_prompt()}] + _msgs(10)
        for _ in range(4):
            compress_history_tags(msgs, keep_recent=4, max_len=600, interval=5)
        self.assertNotIn('[Truncated]', msgs[1]['content'])
        compress_history_tags(msgs, keep_recent=4, max_len=600, interval=5)
        self.assertIn('[Truncated]', msgs[1]['content'])


class ToolUseBlockCompressionTest(unittest.TestCase):
    """真实历史是 content-block 列表(assistant 的 tool_use.input), 不是纯字符串。

    真机回归(2026-10-27): 第 5 轮首次压缩时 `_cut(v)` 漏传 lim 直接
    `TypeError: _cut() missing 1 required positional argument: 'lim'`, 任务在第 5 轮
    崩溃。原测试只覆盖 `content` 为 str 的形态, 没走到 tool_use 分支。
    """

    def setUp(self):
        compress_history_tags._cd = 0
        self.addCleanup(lambda: setattr(compress_history_tags, '_cd', 0))

    def _block_msgs(self, script_len=5000):
        return [{'role': 'user', 'content': _protocol_prompt()},
                {'role': 'assistant', 'content': [
                    {'type': 'thinking', 'thinking': 'short'},
                    {'type': 'tool_use', 'id': 'call_1', 'name': 'code_run',
                     'input': {'script': 'x' * script_len, 'desc': 'd' * 5000,
                               'timeout': 30, 'dry_run': False}},
                ]}]

    def test_tool_use_input_strings_are_truncated_without_crashing(self):
        msgs = self._block_msgs()
        compress_history_tags(msgs, keep_recent=0, max_len=600, force=True)
        inp = msgs[1]['content'][1]['input']
        self.assertIn('[Truncated]', inp['script'])
        self.assertLessEqual(len(inp['script']), 600)
        self.assertLessEqual(len(inp['desc']), 600)
        # 非字符串参数原样保留(数字/布尔不能被当文本切)
        self.assertEqual(inp['timeout'], 30)
        self.assertIs(inp['dry_run'], False)


class TrimKeepsProtocolCarrierTest(unittest.TestCase):
    def test_over_cap_trim_never_drops_message_zero(self):
        msgs = [{'role': 'user', 'content': _protocol_prompt()}] + _msgs(20)
        protocol = msgs[0]['content']
        trim_messages_history(msgs, _Sess())
        self.assertEqual(msgs[0]['content'], protocol)      # 协议载体不因超限被 pop 掉
        self.assertIn('交互协议', msgs[0]['content'])
        self.assertLess(len(msgs), 21)                       # 旧轮次确实被裁掉了


class HistoryMessageCapTest(unittest.TestCase):
    """条数上限: 每轮重发全部历史, 条数不封顶则单轮成本随轮数线性涨、总时间平方涨。

    真机实证: 19 轮 resend 829→50017 字符(60x)、model_wait 3.1s→32.5s, 用户因太慢
    把任务取消。体积上限 context_win*3 高达 9 万字符, 那条路根本等不到——压缩只把
    单条压到 600, 压不掉条数本身。"""

    def _convo(self, turns):
        """turns 轮 user/assistant 交替的短消息(内容极小, 确保测的是条数不是体积)。"""
        out = [{'role': 'user', 'content': 'm0'}]
        out += [{'role': 'assistant', 'content': 'a%d' % i} for i in range(turns)]
        out += [{'role': 'user', 'content': 'm%d' % i} for i in range(1, turns)]
        return out

    def test_history_is_capped_regardless_of_total_size(self):
        msgs = self._convo(60)                    # 60 条也远低于体积上限
        trim_messages_history(msgs, _BigSess())
        self.assertLessEqual(len(msgs), 20)       # 默认 max_history_msgs=20

    def test_cap_keeps_the_head_and_the_recent_tail(self):
        msgs = self._convo(60)
        trim_messages_history(msgs, _BigSess())
        self.assertEqual(msgs[0]['content'], 'm0')           # 首条(任务描述)必须在
        self.assertEqual(msgs[-1]['content'], 'm59')         # 最新一轮必须在

    def test_short_history_is_untouched(self):
        msgs = self._convo(6)
        before = [m['content'] for m in msgs]
        trim_messages_history(msgs, _BigSess())
        self.assertEqual([m['content'] for m in msgs], before)

    def test_cap_is_overridable_per_session(self):
        msgs = self._convo(40)
        sess = type('S', (_BigSess,), {'max_history_msgs': 8})()
        trim_messages_history(msgs, sess)
        self.assertLessEqual(len(msgs), 8)
        self.assertEqual(msgs[0]['content'], 'm0')


if __name__ == '__main__':
    unittest.main()
