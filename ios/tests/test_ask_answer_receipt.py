"""Native reply receipts identify the preceding turn even if other sessions advance the global counter."""
import json
import copy
import itertools
import queue
import threading
from types import SimpleNamespace

import pytest
import signed_runtime  # noqa: F401
import android_entry as entry
import agentmain


ASK = ('🛠️ Tool: `ask_user`  📥 args:\n````text\n'
       '{"question": "Which one?", "candidates": ["Green", "Blue"]}\n````\n')


@pytest.fixture
def question(monkeypatch):
    monkeypatch.setattr(entry.sys, 'platform', 'ios')
    monkeypatch.setattr(entry, 'has_key', lambda: True)
    monkeypatch.setattr(entry, '_IOS_REPLY_EPOCH', 'process-a', raising=False)
    sess = entry._Sess('native-answer')
    sess.state.update(gen=71, prompt='question', steps=[{'text': ASK}], ask=entry._extract_ask(ASK))
    sent = []
    sources = []
    def enqueue(text, source='user'):
        sent.append(text)
        sources.append(source)
        return queue.Queue()
    sess.agent = SimpleNamespace(put_task=enqueue, sources=sources, is_running=False, stop_sig=False, abort=lambda: None)
    monkeypatch.setattr(entry, '_REG', {sess.cid: sess})
    monkeypatch.setattr(entry, '_focus_cid', sess.cid)
    monkeypatch.setattr(entry, '_next_gen', lambda seq=itertools.count(81): next(seq))
    monkeypatch.setattr(entry, 'threading', SimpleNamespace(Thread=lambda **kw: SimpleNamespace(start=lambda: None)))
    return sess, sent


def test_native_reply_is_accepted_once_even_after_poll_consumes_ask(question):
    sess, sent = question
    token = entry._ios_question_token(sess)
    entry._poll_for(sess, '0')
    assert not sess.state['ask'] and entry._ios_question_token(sess) == token
    assert entry.send2(sess.cid, 'Green', token) == ''
    assert sent == ['Green'] and sess.state['reply_to_gen'] == 71
    before = copy.deepcopy(sess.state)
    assert entry.send2(sess.cid, 'Blue', token)
    assert sess.state == before and sent == ['Green']


@pytest.mark.parametrize('invalid', ['new_gen', 'new_epoch', 'stop', 'pause', 'running', 'agent_running', 'retired', 'finished', 'no_agent', 'removed'])
def test_stale_or_inactive_native_reply_cannot_start_a_task(question, monkeypatch, invalid):
    sess, sent = question
    token = entry._ios_question_token(sess)
    if invalid == 'new_gen': sess.state['gen'] += 1
    elif invalid == 'new_epoch': monkeypatch.setattr(entry, '_IOS_REPLY_EPOCH', 'process-b')
    elif invalid == 'stop': sess.agent.stop_sig = True
    elif invalid == 'pause': sess._phone_pause_token = 'taken-over'
    elif invalid == 'running': sess.state['running'] = True
    elif invalid == 'agent_running': sess.agent.is_running = True
    elif invalid == 'retired': sess.retired = True
    elif invalid == 'finished': sess.state['steps'] = [{'text': 'Done'}]
    elif invalid == 'no_agent': sess.agent = None
    elif invalid == 'removed': entry._REG.pop(sess.cid)
    before = copy.deepcopy(sess.state)
    assert entry.send2(sess.cid, 'Green', token)
    assert sent == [] and sess.state == before
    if invalid == 'removed': assert sess.cid not in entry._REG


def test_two_concurrent_native_replies_cannot_both_enter_the_queue(question):
    sess, sent = question
    token = entry._ios_question_token(sess)
    barrier = threading.Barrier(3)
    results = []
    def answer(text):
        barrier.wait(timeout=2)
        results.append(entry.send2(sess.cid, text, token))
    threads = [threading.Thread(target=answer, args=(text,)) for text in ('Green', 'Blue')]
    for thread in threads: thread.start()
    barrier.wait(timeout=2)
    for thread in threads: thread.join(timeout=2)
    assert not any(thread.is_alive() for thread in threads)
    assert len(sent) == 1 and results.count('') == 1 and len(results) == 2


@pytest.mark.parametrize('text', ['/clear', '/resume', '/session.model=unwanted', '/kv.clear'])
def test_native_reply_slash_text_is_literal_at_both_dispatch_layers(question, monkeypatch, text):
    sess, sent = question
    def unexpected(*args):
        pytest.fail('a native answer reached the command dispatcher')
    monkeypatch.setattr(entry, '_dispatch_cmds', unexpected)
    monkeypatch.setattr(entry, '_ios_command', unexpected)
    assert entry.send2(sess.cid, text, entry._ios_question_token(sess)) == ''
    assert sess.state['prompt'] == text and sent == [text] and sess.agent.sources == ['answer']


@pytest.mark.parametrize('platform,source', [('ios', 'answer'), ('android', 'answer'), ('ios', 'user'), ('android', 'user')])
@pytest.mark.parametrize('text', ['/clear', '/resume', '/session.model=unwanted', '  /clear\n保持原文  '])
def test_real_agent_queue_treats_only_ios_answers_as_literal(monkeypatch, platform, source, text):
    monkeypatch.setattr(agentmain.sys, 'platform', platform)
    monkeypatch.setattr(agentmain.GenericAgent, 'load_llm_sessions', lambda self: None)
    monkeypatch.setattr(agentmain, 'get_system_prompt', lambda: '')
    monkeypatch.setattr(agentmain, 'GenericAgentHandler', lambda *a: SimpleNamespace(history_info=[], code_stop_signal=[]))
    seen = []
    def run_model(client, system, query, *args, **kwargs):
        seen.append(query)
        yield {'turn': 1}
        yield 'Done'
    monkeypatch.setattr(agentmain, 'agent_runner_loop', run_model)
    agent = agentmain.GenericAgent()
    agent.peer_hint = False
    agent.llmclient = SimpleNamespace(backend=SimpleNamespace(model='kept'))
    output = agent.put_task(text, source=source)
    agent.task_queue.put('quit')
    agent.run()
    done = list(output.queue)[-1]
    assert 'done' in done and 'Backend Error' not in done['done']
    if platform == 'ios' and source == 'answer':
        assert seen == [text] and agent.llmclient.backend.model == 'kept'
    elif text == '/session.model=unwanted':
        assert seen == [] and agent.llmclient.backend.model == 'unwanted'
    elif text == '/resume':
        assert len(seen) == 1 and seen != [text]
    else:
        assert seen == [text]


def test_android_keeps_normal_send2_command_behavior_even_with_a_third_argument(question, monkeypatch):
    sess, sent = question
    monkeypatch.setattr(entry.sys, 'platform', 'android')
    monkeypatch.setattr(entry, '_dispatch_cmds', lambda text, table: (True, 'ordinary-command'))
    assert entry.send2(sess.cid, '/clear') == 'ordinary-command'
    assert entry.send2(sess.cid, '/clear', 'irrelevant') == 'ordinary-command'
    assert sent == []


def test_stopping_a_waiting_question_revokes_its_reply_even_after_stop_flag_clears(question, monkeypatch):
    sess, sent = question
    token = entry._ios_question_token(sess)
    monkeypatch.setattr(entry, '_resolve_cid', lambda *a, **k: (sess, None))
    monkeypatch.setattr(entry.patches, 'abort_streams', lambda s: None)
    entry.abort2(sess.cid)
    sess.agent.stop_sig = False  # GenericAgent clears this in its finally block.
    assert entry._ios_question_token(sess) is None
    assert entry.send2(sess.cid, 'Green', token)
    assert sent == []


@pytest.mark.parametrize('platform', ['ios', 'android'])
def test_reply_receipt_survives_poll_and_tracks_only_the_immediate_previous_turn(monkeypatch, platform):
    monkeypatch.setattr(entry.sys, 'platform', platform)
    monkeypatch.setattr(entry, 'has_key', lambda: True)
    sent = []
    sess = entry._Sess('answer-receipt')
    monkeypatch.setattr(entry, 'threading', SimpleNamespace(Thread=lambda **kw: SimpleNamespace(start=lambda: None)))
    queued_receipts = []
    def enqueue(text):
        queued_receipts.append(sess.state.get('reply_to_gen'))
        sent.append(text)
    sess.agent = SimpleNamespace(put_task=enqueue)
    sess.state.update(gen=71, prompt='question', steps=[{'text': 'ask_user'}])
    gens = iter([81, 90])  # Other conversations can consume generation IDs between answers.
    monkeypatch.setattr(entry, '_next_gen', lambda: next(gens))
    assert entry._send_for(sess, 'Green') == ''
    first = json.loads(entry._poll_for(sess, '-1'))
    assert first['gen'] == 81 and first['prompt'] == 'Green'
    if platform == 'ios':
        assert first['reply_to_gen'] == 71
        assert json.loads(entry._poll_for(sess, '1'))['reply_to_gen'] == 71
        assert json.loads(entry._poll_for(sess, '1'))['reply_to_gen'] == 71
    else:
        assert 'reply_to_gen' not in first and 'reply_to_gen' not in sess.state
    sess.state['running'] = False
    monkeypatch.setattr(entry, 'has_key', lambda: False)
    entry._send_for(sess, 'rejected')
    assert sess.state['prompt'] == 'Green' and sent == ['Green']
    monkeypatch.setattr(entry, 'has_key', lambda: True)
    assert entry._send_for(sess, 'Blue') == ''
    second = json.loads(entry._poll_for(sess, '-1'))
    if platform == 'ios':
        assert second['reply_to_gen'] == 81  # Never attributes Blue to the old question 71.
    assert second['gen'] == 90 and second['prompt'] == 'Blue' and sent == ['Green', 'Blue']
    assert queued_receipts == ([None, 71] if platform == 'ios' else [None, None])
