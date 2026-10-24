"""Slow tasks must be attributable: main-model request timing, observation hops and vision cost are recorded
without changing what the wrapped calls return."""
import importlib.util
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))


@pytest.fixture
def entry(tmp_path, monkeypatch):
    monkeypatch.setenv('GA_DIR', str(tmp_path))
    import android_entry as entry
    for name in ('_save_hist', '_persist_convo'):
        monkeypatch.setattr(entry, name, lambda *a, **k: None)
    monkeypatch.setattr(entry, '_hist', [])
    return entry


def _bound_sess(entry, cid):
    sess = entry._Sess(cid)
    sess.state.update(running=True, gen=entry._next_gen(), steps=[], final='', prompt='p', end='')
    entry.patches.bind_sess(sess)
    return sess


class _Resp:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self):
        yield from self._lines

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


SSE = [b'event: message_start',
       b'data: {"type":"message_start","message":{"usage":{"input_tokens":0}}}',
       b'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"plan"}}',
       b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}',
       b'data: {"type":"content_block_start","content_block":{"type":"tool_use","id":"t1","name":"code_run"}}',
       b'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"input_tokens":1975,"output_tokens":42}}']


def test_main_model_request_records_phases_context_and_usage(entry, monkeypatch):
    import llmcore
    entry.patches.patch_abort()
    entry.patches.patch_llm_timing()
    sess = _bound_sess(entry, 'llmt')
    monkeypatch.setattr('requests.post', lambda *a, **k: _Resp(SSE))
    try:
        payload = {'model': 'm', 'messages': [{'role': 'user', 'content': [{'type': 'image', 'source': {}},
                                                                          {'type': 'text', 'text': 'x' * 500}]}],
                   'system': 'sys', 'tools': [{'name': 'code_run'}]}
        llm = SimpleNamespace(max_retries=0, stream=True, connect_timeout=1, read_timeout=1, proxies=None, verify=True)
        chunks = list(llmcore._stream_with_retry(llm, 'https://x.test/v1/messages', {}, payload,
                                                 lambda r: llmcore._parse_claude_sse(r.iter_lines())))
        assert 'ok' in ''.join(c for c in chunks if isinstance(c, str))
        d = __import__('json').loads(entry._poll_for(sess, '0'))
        assert len(d['llm']) == 1
        rec = d['llm'][0]
        assert rec['i'] == 1 and rec['attempts'] == 1 and rec['http'] == 200 and rec['errors'] == 0
        assert rec['ctx_chars'] > 500 and rec['n_img'] == 1 and rec['n_msgs'] == 1 and rec['tools_chars'] > 0
        assert rec['in_tok'] == 1975 and rec['out_tok'] == 42
        for key in ('hdr', 'first', 'think', 'text', 'tool', 'end'):
            assert isinstance(rec[key], float), key
        assert rec['first'] <= rec['think'] <= rec['text'] <= rec['tool'] <= rec['end']
    finally:
        entry.patches.bind_sess(None)


def test_request_records_are_scoped_to_the_current_task(entry, monkeypatch):
    sess = _bound_sess(entry, 'llmt2')
    try:
        a = entry.patches._llmt_open({'messages': []})
        sess.state['gen'] = entry._next_gen()
        b = entry.patches._llmt_open({'messages': []})
        assert [x['i'] for x in sess.state['llm']] == [1] and sess.state['llm'][0] is b and a is not b
        d = __import__('json').loads(entry._poll_for(sess, '0'))
        assert [x['gen'] for x in d['llm']] == [sess.state['gen']]
        assert __import__('json').loads(entry._poll_for(sess, '0', summary=True))['llm'] == []
    finally:
        entry.patches.bind_sess(None)


def test_unattributed_request_is_not_recorded(entry):
    entry.patches.bind_sess(None)
    assert entry.patches._llmt_open({'messages': []}) is None


def test_openai_placeholders_do_not_count_as_first_tokens(entry):
    rec = {'t_req': 0.0, 'first': None, 'think': None, 'text': None, 'tool': None,
           'in_tok': 0, 'out_tok': 0, 'cache_read': 0}
    with patch('time.time', return_value=5.0):
        entry.patches._llmt_line(rec, b'data: {"choices":[{"delta":{"role":"assistant","content":""}}],"usage":null}')
        assert rec['first'] == 5.0 and rec['text'] is None and rec['think'] is None
        entry.patches._llmt_line(rec, b'data: {"choices":[{"delta":{"reasoning_content":null,"content":"hi"}}]}')
        assert rec['text'] == 5.0 and rec['think'] is None
        entry.patches._llmt_line(rec, b'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":3}}')
        assert (rec['in_tok'], rec['out_tok']) == (10, 3)


def _template():
    spec = importlib.util.spec_from_file_location('vision_template', CORE / 'memory/vision_api.template.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vision_disables_extended_thinking_by_default_and_allows_provider_default():
    module = _template()
    cfg = {'apibase': 'https://example.test/anthropic', 'apikey': 'test-placeholder', 'model': 'test'}
    with patch.object(module, '_cfg', return_value=cfg), patch.object(module.requests, 'post') as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = {'content': [{'type': 'text', 'text': 'OK'}]}
        assert module._call_claude('img', 'read', 10) == 'OK'
        assert post.call_args.kwargs['json']['thinking'] == {'type': 'disabled'}
        module._call_claude('img', 'read', 10, thinking='auto')
        assert 'thinking' not in post.call_args.kwargs['json']


def test_vision_falls_back_once_when_provider_rejects_thinking_parameter():
    module = _template()
    cfg = {'apibase': 'https://example.test/anthropic', 'apikey': 'test-placeholder', 'model': 'test'}
    rejected = SimpleNamespace(status_code=400, raise_for_status=lambda: (_ for _ in ()).throw(AssertionError('no')))
    ok = SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                         json=lambda: {'content': [{'type': 'text', 'text': 'OK'}]})
    sent = []
    def post(*a, **k):
        sent.append(dict(k['json']))
        return rejected if len(sent) == 1 else ok
    with patch.object(module, '_cfg', return_value=cfg), patch.object(module.requests, 'post', side_effect=post):
        assert module._call_claude('img', 'read', 10) == 'OK'
    assert [('thinking' in p) for p in sent] == [True, False]


def test_vision_keeps_configured_disable_without_retry():
    module = _template()
    cfg = {'apibase': 'https://example.test/anthropic', 'apikey': 'test-placeholder', 'model': 'test',
           'thinking_type': 'disabled'}
    with patch.object(module, '_cfg', return_value=cfg), patch.object(module.requests, 'post') as post:
        post.return_value.status_code = 400
        post.return_value.raise_for_status.side_effect = RuntimeError('HTTP 400')
        with pytest.raises(RuntimeError):
            module._call_claude('img', 'read', 10, thinking='auto')
        assert post.call_count == 1 and post.call_args.kwargs['json']['thinking'] == {'type': 'disabled'}


def test_observation_hops_record_vision_cost_and_keep_results(entry):
    import droid
    from plugins import browser_events_hook as hook
    sess = _bound_sess(entry, 'hops')
    try:
        class Img:
            shape = (2340, 1080, 3)
            dtype = 'uint8'
        with patch.dict(sys.modules, {'vision_api': SimpleNamespace(ask_vision=lambda image, prompt, **kw: 'Error: 请求超时 (>60s)')}):
            assert droid.ask_vision(Img(), '抽屉是否打开') == 'Error: 请求超时 (>60s)'
        evs = [e for e in sess.state['tool_events'] if e.get('action') == 'vision']
        assert len(evs) == 1
        ev = evs[0]
        assert ev['name'] == 'droid.ask_vision' and ev['status'] == 'error' and ev['out_len'] > 0
        assert 'ndarray[2340, 1080, 3]' in ev['input_summary']
        for name in ('dump', 'find', 'look', 'ask_vision', 'scroll_view', 'tap_text'):
            assert getattr(getattr(droid, name), '_ga_bwev', False), name
    finally:
        entry.patches.bind_sess(None)


def test_list_observations_are_summarized_by_count(entry):
    from plugins import browser_events_hook as hook
    sess = _bound_sess(entry, 'lists')
    try:
        mod = SimpleNamespace(__name__='droidfake', dump=lambda: [{'t': str(i)} for i in range(60)])
        hook._wrap(mod, 'dump', 'dump', 'verifying')
        assert len(mod.dump()) == 60
        ev = [e for e in sess.state['tool_events'] if e.get('name') == 'droidfake.dump'][0]
        assert ev['result_summary'].startswith('n=60 ') and ev['status'] == 'done'
    finally:
        entry.patches.bind_sess(None)
