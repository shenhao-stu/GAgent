"""流式 chat_completions 的 usage 上报: 一次模型请求只能记一次。

真机回归(2026-10-27): UI 的 token 显示 91,093,037 / 3,622,929, 而 metrics 真实
359,835 / 16,578。原因: chat_completions 的 SSE 每个 chunk 都带 usage(累计值),
_parse_openai_sse 每见一次就调 _record_usage → patch_usage 把同一请求加了几百次。
run_metrics.note_tokens 用 max 规避, UI 侧的 patch_usage 没有。
"""
import sys
from pathlib import Path

CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import llmcore


def test_streaming_usage_is_recorded_once_with_the_last_value(monkeypatch):
    calls = []
    monkeypatch.setattr(llmcore, '_record_usage',
                        lambda usage, api_mode: calls.append((dict(usage), api_mode)))
    lines = [
        'data: {"choices":[{"delta":{"content":"a"}}],"usage":{"prompt_tokens":100,"completion_tokens":1}}',
        'data: {"choices":[{"delta":{"content":"b"}}],"usage":{"prompt_tokens":100,"completion_tokens":2}}',
        'data: [DONE]',
    ]
    list(llmcore._parse_openai_sse(iter(lines), 'chat_completions'))
    assert calls == [({'prompt_tokens': 100, 'completion_tokens': 2}, 'chat_completions')]


def test_stream_without_usage_records_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(llmcore, '_record_usage',
                        lambda usage, api_mode: calls.append((dict(usage), api_mode)))
    lines = ['data: {"choices":[{"delta":{"content":"a"}}]}', 'data: [DONE]']
    list(llmcore._parse_openai_sse(iter(lines), 'chat_completions'))
    assert calls == []
