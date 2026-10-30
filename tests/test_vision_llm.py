"""ask_vision 复用任务页当前选择的模型(多模态), 不要求单独的 vision_api 配置。"""
import sys
from pathlib import Path

import time

import numpy as np
import pytest

CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import vision_llm


class _FakeLLM:
    def __init__(self):
        self.system = 'MAIN SYSTEM'
        self.tools = [{'type': 'function'}]
        self.thinking_type = 'enabled'
        self.reasoning_effort = 'high'
        self.read_timeout = 240
        self.connect_timeout = 5
        self.max_retries = 4          # llmcore BaseSession 的默认值
        self.seen = None
        self.during = None

    def raw_ask(self, messages):
        self.seen = messages
        self.during = (self.system, self.tools, self.thinking_type,
                       self.reasoning_effort, self.read_timeout, self.max_retries)
        yield '视觉回答'


def _img():
    return np.zeros((20, 20, 3), dtype=np.uint8)


def test_oai_backend_reuses_its_config_and_clears_main_context():
    b = _FakeLLM()
    out = vision_llm.ask_with_backend(b, _img(), 'q', timeout=10)
    assert out == '视觉回答'
    # 主模型的 system/tools/思考档必须在看图时清空, 调用后恢复
    assert b.during == ('', None, 'disabled', None, 10.0, 0)
    assert (b.system, b.tools, b.thinking_type, b.reasoning_effort, b.read_timeout) == \
           ('MAIN SYSTEM', [{'type': 'function'}], 'enabled', 'high', 240)
    blocks = b.seen[0]['content']
    assert any(x.get('type') == 'image_url' for x in blocks)
    assert any(x.get('type') == 'text' for x in blocks)


def test_claude_backend_uses_anthropic_image_block():
    b = type('ClaudeSession', (_FakeLLM,), {})()
    out = vision_llm.ask_with_backend(b, _img(), 'q')
    assert out == '视觉回答'
    blocks = b.seen[0]['content']
    assert any(x.get('type') == 'image' for x in blocks)


def test_mixin_members_are_cleared_and_restored():
    b1, b2 = _FakeLLM(), _FakeLLM()

    class _Mixin:
        _sessions = [b1, b2]
        seen_during = None

        def _pick(self):
            return 0

        def raw_ask(self, messages):
            self.seen_during = (b1.system, b1.tools, b2.system, b2.tools)
            yield from b1.raw_ask(messages)

    m = _Mixin()
    out = vision_llm.ask_with_backend(m, _img(), 'q')
    assert out == '视觉回答'
    assert b1.during == ('', None, 'disabled', None, 240, 0)
    assert m.seen_during == ('', None, '', None)     # 失败转移成员同样清上下文
    assert b1.system == 'MAIN SYSTEM' and b2.thinking_type == 'enabled'


def test_error_answer_raises_for_the_fuse():
    class _Err(_FakeLLM):
        def raw_ask(self, messages):
            yield '!!!Error: upstream rejected image'

    with pytest.raises(RuntimeError):
        vision_llm.ask_with_backend(_Err(), _img(), 'q')


def test_empty_answer_raises():
    class _Empty(_FakeLLM):
        def raw_ask(self, messages):
            yield '  '

    with pytest.raises(RuntimeError):
        vision_llm.ask_with_backend(_Empty(), _img(), 'q')


def test_vision_call_never_retries():
    """回归(真机 1200x2670, 2026-10-27 17:57): ask_vision 在 30s 读超时后按
    llmcore 默认 max_retries=4 重试, 最坏 5×30s+退避≈160s, 而 code_run 默认只有 60s
    ——真机那次 60.285s 被强杀并留下僵尸线程, 下一个操作手机都被卡住, 任务直接废掉。
    视觉问答必须一次定生死: 不成立即失败, 交给 droid.ask_vision 的熔断与 SOP 的
    "超时即停"处理。"""
    seen = []

    class _Counts(_FakeLLM):
        def raw_ask(self, messages):
            seen.append(self.max_retries)
            yield '!!!Error: ReadTimeout'

    b = _Counts()
    with pytest.raises(RuntimeError):
        vision_llm.ask_with_backend(b, _img(), 'q', timeout=5)
    # 只发一次请求: 请求期间 max_retries 已被压成 0
    assert seen == [0], seen
    assert b.max_retries == 4          # 恢复原值, 不影响主任务后续调用


def test_mixin_shell_retry_count_is_zeroed_too():
    """回归: MixinSession.raw_ask 解析到 MixinSession._raw_ask, 循环上界是 self._retries
    (默认 3), 与成员的 max_retries 是两个属性且不在 _BROADCAST_ATTRS 里。只压成员压不到它,
    多供应商 fallback 组的视觉调用仍会重试到 210s, 正好是 vision_llm 声称已消除的那个
    "60.285s 被 code_run 强杀 + 僵尸线程" 失败。"""
    b1 = _FakeLLM()

    class _Mixin:
        _sessions = [b1]
        _retries = 3                      # llmcore MixinSession 自己的重试预算
        seen_retries = None

        def _pick(self):
            return 0

        def raw_ask(self, messages):
            self.seen_retries = self._retries
            yield from b1.raw_ask(messages)

    m = _Mixin()
    vision_llm.ask_with_backend(m, _img(), 'q', timeout=5)
    assert m.seen_retries == 0, m.seen_retries
    assert m._retries == 3                 # 调用后恢复


class _SlowLLM(_FakeLLM):
    """流式下 read_timeout 管不住的总时长: 一个 token 都不吐地跑很久, 单次读超时永不触发。"""

    def raw_ask(self, messages):
        time.sleep(3)
        yield 'too late'


def test_total_wall_clock_budget_beats_the_per_read_timeout():
    """回归(真机 2026-10-28 09:34): ask_point 跑了 46.8s 还没回来, 用户手动停止。
    根因是 read_timeout 是 requests 的**单次读**超时(流式下=两个 chunk 之间最多静默多久),
    思考型模型可以长时间不吐 token 而从不触发它; 而 code_run 默认只有 60s, 一个视觉调用
    就吃掉四分之三预算。必须按墙钟兜底。"""
    with pytest.raises(RuntimeError, match='总时长上限'):
        vision_llm.ask_with_backend(_SlowLLM(), _img(), 'q', timeout=1)


def test_no_deadline_when_timeout_not_given():
    b = _FakeLLM()
    assert vision_llm.ask_with_backend(b, _img(), 'q') == '视觉回答'
