"""llmcore 用量观察者: token 必须可按 turn 归集(原来三个协议分支只 print)。"""
import sys
from pathlib import Path

import pytest

CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import llmcore


@pytest.fixture
def seen():
    saved = list(llmcore._USAGE_OBSERVERS)
    box = []
    llmcore.add_usage_observer(lambda i, o, c: box.append((i, o, c)))
    yield box
    llmcore._USAGE_OBSERVERS[:] = saved


def test_chat_completions_usage_is_emitted_normalized(seen):
    llmcore._record_usage({'prompt_tokens': 100, 'completion_tokens': 20,
                           'prompt_tokens_details': {'cached_tokens': 40}}, 'chat_completions')
    assert seen == [(100, 20, 40)]


def test_messages_usage_counts_cache_creation_as_input(seen):
    llmcore._record_usage({'input_tokens': 10, 'output_tokens': 5,
                           'cache_creation_input_tokens': 7, 'cache_read_input_tokens': 3}, 'messages')
    assert seen == [(20, 5, 3)]


def test_responses_usage_is_emitted(seen):
    llmcore._record_usage({'input_tokens': 11, 'output_tokens': 22,
                           'input_tokens_details': {'cached_tokens': 5}}, 'responses')
    assert seen == [(11, 22, 5)]


def test_empty_usage_emits_nothing(seen):
    llmcore._record_usage({}, 'chat_completions')
    llmcore._record_usage(None, 'messages')
    assert seen == []


def test_observer_failure_is_swallowed(seen):
    def boom(i, o, c):
        raise RuntimeError('bad observer')

    llmcore.add_usage_observer(boom)
    llmcore._record_usage({'prompt_tokens': 1, 'completion_tokens': 1}, 'chat_completions')
    assert seen == [(1, 1, 0)]


CLAUDE_SSE = [
    b'data: {"type":"message_start","message":{"usage":{"input_tokens":1975,"output_tokens":1}}}',
    b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}',
    b'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":42}}',
    b'data: {"type":"message_stop"}',
]


def test_claude_streaming_output_tokens_reach_the_observer(seen):
    """Claude 流式 output_tokens 只走 message_delta(不经 _record_usage), 也必须可归集。"""
    gen = llmcore._parse_claude_sse(iter(CLAUDE_SSE))
    chunks = []
    try:
        while True:
            chunks.append(next(gen))
    except StopIteration as e:
        blocks = e.value or []
    assert ''.join(chunks) == 'ok'
    assert blocks == []                      # 没有 content_block_start/stop → 无结构化块, 只出文本
    assert seen == [(1975, 1, 0), (0, 42, 0)]
