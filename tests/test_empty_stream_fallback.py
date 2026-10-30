# -*- coding: utf-8 -*-
"""空流(HTTP 200 但零 chunk)的兜底与文案契约。

真机取证(2026-10-30, StepFun step_plan + step-3.7-flash): 20 条历史任务里 4 条死在
`!!!Error: ConnectionError: empty response`, 且都死在开局的第 2 回合左右 —— 用户看到的就是
"刚开始执行就报一堆 error"。这里锁三件事:

1. 空流先用**非流式**同请求再要一次(另一条网关路径), 拿到正文就直接继续, 不报错;
2. 中间重试不往正文塞 `!!!Error`(否则一次空流会连出好几行红字);
3. 真的全用尽了, 正文里那一条要说清"是上游的问题、过会儿重发就行", 而不是只甩异常名。
"""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import llmcore


class _FakeResp:
    def __init__(self, status=200, payload=None, lines=()):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self._lines = list(lines)

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def iter_lines(self): return iter(self._lines)
    def json(self): return self._payload


def _sess(**kw):
    base = dict(max_retries=0, connect_timeout=5, read_timeout=5, proxies=None, verify=False, stream=True)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _drive(gen):
    out = []
    try:
        while True: out.append(next(gen))
    except StopIteration as e:
        return out, (e.value or [])
    return out, []


class EmptyStreamFallbackTest(unittest.TestCase):
    def test_empty_stream_falls_back_to_non_stream_and_keeps_going(self):
        calls = []

        def fake_post(url, headers=None, json=None, **kw):
            calls.append(json)
            if json.get('stream'):
                return _FakeResp(lines=[])            # 流里一个 chunk 都没有
            return _FakeResp(payload={'choices': [{'message': {'content': '好的, 继续'}}]})

        parse_fn = lambda r: llmcore._parse_openai_sse(r.iter_lines(), 'chat_completions')
        json_fn = lambda r: llmcore._parse_openai_json(r.json(), 'chat_completions')
        payload = {'model': 'm', 'messages': [], 'stream': True, 'stream_options': {'include_usage': True}}
        with patch.object(llmcore.requests, 'post', fake_post), patch.object(llmcore, '_stream_diag', lambda *a, **k: None):
            chunks, ret = _drive(llmcore._stream_with_retry(_sess(), 'http://x', {}, payload, parse_fn, json_fn))

        self.assertEqual(len(calls), 2, '流式一次 + 非流式一次')
        self.assertFalse(calls[1].get('stream'), '兜底请求必须是 stream=False')
        self.assertNotIn('stream_options', calls[1], 'stream_options 只在流式下有效, 兜底要摘掉')
        self.assertEqual(chunks, ['好的, 继续'])
        self.assertTrue(any(b.get('type') == 'text' and b.get('text') == '好的, 继续' for b in ret))
        self.assertFalse(any('!!!Error' in c for c in chunks), '兜底成功时不该出现 !!!Error')

    def test_all_attempts_empty_yield_exactly_one_line_with_recovery_hint(self):
        def fake_post(url, headers=None, json=None, **kw):
            return _FakeResp(lines=[])

        parse_fn = lambda r: llmcore._parse_openai_sse(r.iter_lines(), 'chat_completions')
        json_fn = lambda r: llmcore._parse_openai_json(r.json(), 'chat_completions')
        payload = {'model': 'm', 'messages': [], 'stream': True}
        with patch.object(llmcore.requests, 'post', fake_post), patch.object(llmcore.time, 'sleep', lambda *_: None), patch.object(llmcore, '_stream_diag', lambda *a, **k: None):
            chunks, ret = _drive(llmcore._stream_with_retry(_sess(max_retries=3), 'http://x', {}, payload, parse_fn, json_fn))

        errs = [c for c in chunks if '!!!Error' in c]
        self.assertEqual(len(errs), 1, '中间重试必须静默, 否则一次空流会连出好几行红字: %r' % (chunks,))
        self.assertIn('empty response', errs[0])
        self.assertIn('不是任务做错', errs[0])
        self.assertEqual([b.get('text') for b in ret if b.get('type') == 'text'], errs)


    def test_gateway_error_event_is_surfaced_not_mistaken_for_empty_stream(self):
        """网关把错误包成 SSE 事件时以前会被静默忽略, 于是"一片 data 全是 error"也被判成空流。"""
        lines = [b'data: {"error": {"message": "upstream overloaded"}}', b'data: [DONE]']

        def fake_post(url, headers=None, json=None, **kw):
            return _FakeResp(lines=lines)

        parse_fn = lambda r: llmcore._parse_openai_sse(r.iter_lines(), 'chat_completions')
        payload = {'model': 'm', 'messages': [], 'stream': True}
        ctx1 = patch.object(llmcore.requests, 'post', fake_post)
        ctx2 = patch.object(llmcore, '_stream_diag', lambda *a, **k: None)
        with ctx1, ctx2:
            chunks, ret = _drive(llmcore._stream_with_retry(_sess(), 'http://x', {}, payload, parse_fn,
                                                           lambda r: []))
        self.assertTrue(any('upstream overloaded' in c for c in chunks), chunks)
        self.assertFalse(any('empty response' in c for c in chunks), '有 error 事件时不该再说空流')

    def test_empty_stream_writes_diagnostics(self):
        """空流必须留下现场(raw_lines/saw_done/首行), 便于事后判断到底是真空 body 还是解析没认出来。"""
        seen = []

        def fake_post(url, headers=None, json=None, **kw):
            r = _FakeResp(lines=[])
            r.headers = {'Content-Type': 'text/event-stream; charset=utf-8'}
            return r

        parse_fn = lambda r: llmcore._parse_openai_sse(r.iter_lines(), 'chat_completions')
        payload = {'model': 'm', 'messages': [], 'stream': True}
        ctx1 = patch.object(llmcore.requests, 'post', fake_post)
        ctx2 = patch.object(llmcore, '_stream_diag', lambda *a, **k: seen.append((a, k)))
        with ctx1, ctx2:
            _drive(llmcore._stream_with_retry(_sess(), 'http://x', {}, payload, parse_fn, lambda r: []))
        self.assertEqual(len(seen), 1, '空流应落一次诊断')
        self.assertEqual(seen[0][0][-1], 'empty response')

    def test_timing_wrapper_keeps_the_json_fn_parameter(self):
        """patches.patch_llm_timing 会猴补 _stream_with_retry; 它必须跟着新签名走,
        否则真机上第一个模型请求就以 TypeError: ... takes 5 positional arguments but 6 were given 直接失败。"""
        import inspect
        src = (Path(__file__).resolve().parents[1] / "app/src/main/assets/gacore/kernel_adapter/patches.py").read_text(encoding="utf-8")
        # 猴补只能原样转发: 抄一遍签名就会在下次改签名时把每个请求打成 TypeError。
        self.assertIn("def _stream_with_retry(*args, **kwargs):", src)
        self.assertIn("g = orig(*args, **kwargs)", src)
        self.assertNotIn("def _stream_with_retry(sess, url", src)
        self.assertIn("json_fn", inspect.signature(llmcore._stream_with_retry).parameters)
    def test_plain_timeout_keeps_old_behaviour(self):
        def fake_post(url, headers=None, json=None, **kw):
            raise llmcore.requests.Timeout('read timed out')

        parse_fn = lambda r: llmcore._parse_openai_sse(r.iter_lines(), 'chat_completions')
        payload = {'model': 'm', 'messages': [], 'stream': True}
        with patch.object(llmcore.requests, 'post', fake_post):
            chunks, ret = _drive(llmcore._stream_with_retry(_sess(), 'http://x', {}, payload, parse_fn,
                                                           lambda r: []))
        self.assertEqual(len(chunks), 1)
        self.assertIn('Timeout', chunks[0])
        self.assertNotIn('空流', chunks[0])


if __name__ == '__main__':
    unittest.main()
