"""The status UI's snapshot against the real signed engine: what it reports, and that reading changes nothing.

Run in its own interpreter:  python3 -m pytest -q ios/Presence/Tests/test_presence_snapshot.py
"""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
import signed_runtime  # noqa: E402,F401  stages the signed runtime and puts it on sys.path
import android_entry as entry  # noqa: E402
import presence_snapshot  # noqa: E402

ASK = ('先确认门店。\n🛠️ Tool: `ask_user`  📥 args:\n````text\n'
       '{"question": "附近有两家门店，从哪一家下单？", "candidates": ["科技园店", "大学城店"]}\n````\n')


@pytest.fixture(autouse=True)
def engine(monkeypatch):
    monkeypatch.setattr(entry, '_INITED', True, raising=False)
    monkeypatch.setattr(entry, '_REG', {})
    yield


def session(cid='c1', **state):
    s = entry._Sess(cid)
    s.state.update(gen=7, prompt='帮我点一杯生椰拿铁，送到公司', **state)
    entry._REG[cid] = s
    return s


def event(name, status='done', gen=7, **fields):
    return {'gen': gen, 'name': name, 'status': status, 'desc': '', 'input_summary': '{}', **fields}


def runs():
    return json.loads(presence_snapshot.snapshot())['runs']


def test_nothing_is_reported_before_the_engine_starts(monkeypatch):
    session(running=True)
    monkeypatch.setattr(entry, '_INITED', False, raising=False)
    assert presence_snapshot.snapshot() == presence_snapshot.EMPTY


def test_a_running_step_reports_the_call_in_flight_but_never_its_typed_text():
    session(running=True, steps=[{'n': 1, 'summary': '打开外卖应用', 'text': '...'}, {'n': 2, 'summary': '', 'text': ''}],
            tool_events=[event('screen'), event('hid', 'running', desc='输入收货电话',
                         input_summary='{"action": "type", "text": "13800002046-secret"}')])
    run, = runs()
    assert run['running'] and run['step'] == 2 and run['used_phone']
    assert run['tool'] == {'name': 'hid', 'action': 'type', 'desc': '输入收货电话'}
    assert run['trail'] == ['打开外卖应用'] and run['title'] == '帮我点一杯生椰拿铁，送到公司'
    assert 'secret' not in presence_snapshot.snapshot()


def test_an_action_survives_a_truncated_argument_summary():
    session(running=True, tool_events=[event('hid', 'running', input_summary='{"action": "swipe", "x": 0.5, "y2": 0.')])
    assert runs()[0]['tool']['action'] == 'swipe'


def test_calls_of_an_earlier_task_do_not_count_for_this_one():
    session(running=True, tool_events=[event('hid', 'running', gen=6), event('code_run', gen=7)])
    run, = runs()
    assert run['tool'] is None and not run['used_phone']


def test_a_pending_question_is_read_without_being_consumed():
    s = session(steps=[{'n': 1, 'summary': '查看门店', 'text': ASK}], final='附近有两家门店，从哪一家下单？',
                ask={'question': 'kept for the chat page', 'candidates': []})
    before = copy.deepcopy(s.state)
    first, second = runs(), runs()
    assert first == second and s.state == before
    assert first[0]['ask'] == {'question': '附近有两家门店，从哪一家下单？', 'candidates': ['科技园店', '大学城店']}
    assert not first[0]['running'] and first[0]['tool'] is None
    json.loads(entry._poll_for(s, '0'))          # the chat page's poll does consume its copy ...
    assert not s.state['ask'] and runs()[0]['ask'] == first[0]['ask']   # ... and the snapshot still sees the question


@pytest.mark.parametrize('candidates', [
    ['Keep  all', '  Keep files  ', 'Line one\nline two', 'Use\tcurrent'],
    ['x' * 24, '保留 原文件'],
])
def test_native_candidate_answers_preserve_the_complete_original_strings(candidates, monkeypatch):
    monkeypatch.setattr(entry.sys, 'platform', 'ios')
    text = '🛠️ Tool: `ask_user`  📥 args:\n````text\n' + json.dumps(
        {'question': 'Choose an action', 'candidates': candidates}, ensure_ascii=False) + '\n````\n'
    s = session(steps=[{'text': text}])
    before = copy.deepcopy(s.state)
    assert runs()[0]['ask']['candidates'] == candidates
    assert s.state == before


@pytest.mark.parametrize('candidates', [
    ['Keep all original files and only remove caches', 'Delete all'],
    ['x' * 25, 'Keep'],
    ['保留' * 20, '删除'],
    [str(n) for n in range(7)],
])
def test_choices_that_cannot_fit_are_omitted_as_a_whole_for_chat_answering(candidates):
    text = '🛠️ Tool: `ask_user`  📥 args:\n````text\n' + json.dumps(
        {'question': 'Choose an action', 'candidates': candidates}, ensure_ascii=False) + '\n````\n'
    s = session(steps=[{'text': text}])
    before = copy.deepcopy(s.state)
    ask = runs()[0]['ask']
    assert ask['candidates'] == [], 'native actions must not contain truncated or partial choices'
    assert ask['question'] == 'Choose an action'
    assert entry._extract_ask(s.state['steps'][-1]['text'])['candidates'] == candidates
    assert s.state == before


def test_android_candidate_parser_keeps_its_existing_whitespace_normalization(monkeypatch):
    monkeypatch.setattr(entry.sys, 'platform', 'android')
    text = 'ask_user ' + json.dumps({'question': 'Choose', 'candidates': ['  Keep  files  ', '  ', 'Use\tcurrent']})
    assert entry._extract_ask(text)['candidates'] == ['Keep  files', 'Use\tcurrent']


def test_native_question_token_survives_poll_but_is_not_exposed_when_stopped(monkeypatch):
    monkeypatch.setattr(entry.sys, 'platform', 'ios')
    s = session(steps=[{'text': ASK}], ask=entry._extract_ask(ASK))
    s.agent = SimpleNamespace(is_running=False, stop_sig=False)
    token = runs()[0]['ask']['reply_token']
    assert token == entry._ios_question_token(s)
    entry._poll_for(s, '0')
    assert not s.state['ask'] and runs()[0]['ask']['reply_token'] == token
    s.agent.stop_sig = True
    assert 'reply_token' not in runs()[0]['ask']
    s.agent.stop_sig = False
    s._ios_cancelled_question_gen = s.state['gen']
    assert 'reply_token' not in runs()[0]['ask']


def test_native_question_token_changes_with_process_epoch_without_mutating_session(monkeypatch):
    monkeypatch.setattr(entry.sys, 'platform', 'ios')
    s = session(steps=[{'text': ASK}])
    s.agent = SimpleNamespace(is_running=False, stop_sig=False)
    before = copy.deepcopy(s.state)
    first = runs()[0]['ask']['reply_token']
    monkeypatch.setattr(entry, '_IOS_REPLY_EPOCH', 'new-process')
    assert runs()[0]['ask']['reply_token'] != first and s.state == before


def test_a_running_task_never_shows_the_previous_question():
    session(running=True, steps=[{'n': 1, 'summary': '', 'text': ASK}])
    assert runs()[0]['ask'] is None


@pytest.mark.parametrize('final,failed', [
    ('!!!Error: HTTP 429 too many requests', True),
    ('[Error: no provider]', True),
    ('做到一半\n!!!Error: 会话线程已退出, 任务未完成', True),
    ('已下单。\n```\n!!!Error: 只是示例\n```', False),
    ('已下单：生椰拿铁大杯，预计 14:35 送到。\n\n详情如下……', False),
])
def test_a_failed_ending_is_told_from_a_finished_one(final, failed):
    session(final=final)
    run, = runs()
    assert run['failed'] is failed
    assert '\n' not in run['final'] and len(run['final']) <= presence_snapshot.FINAL


def test_the_outcome_is_the_models_closing_words_not_the_transcript():
    # The engine's final text is the whole run: each turn opens with its own marker, and earlier turns carry
    # their thinking, captions and tool calls. A notification shows the closing turn's first line of prose.
    session(final='**LLM Running (Turn 1) ...**\n\n<summary>读屏</summary>\n🛠️ Tool: `screen`\n\n'
                  '**LLM Running (Turn 2) ...**\n\n<thinking>收尾</thinking>\n<summary>报告</summary>\n'
                  '已下单：生椰拿铁大杯。\n\n详情如下……')
    assert runs()[0]['final'] == '已下单：生椰拿铁大杯。'


def test_handoff_and_stop_in_progress_are_visible():
    s = session(running=True)
    s._phone_pause_token = 'ticket'
    s.agent = SimpleNamespace(stop_sig=True)
    run, = runs()
    assert run['paused'] and run['stopping']
    assert 'ticket' not in presence_snapshot.snapshot()


def test_retired_and_never_used_conversations_are_left_out():
    session('gone', running=True).retired = True
    fresh = entry._Sess('fresh'); entry._REG['fresh'] = fresh
    assert runs() == []


def test_long_text_is_cut_and_language_follows_the_engine(monkeypatch):
    s = session(running=True, steps=[{'n': 1, 'summary': '很' * 200, 'text': ''}])
    s.state['prompt'] = '第一行' + '长' * 200 + '\n第二行'
    monkeypatch.setattr(entry, '_LANG', 'en')
    report = json.loads(presence_snapshot.snapshot())
    run, = report['runs']
    assert report['lang'] == 'en'
    assert len(run['title']) == presence_snapshot.TITLE and run['title'].endswith('…') and '第二行' not in run['title']
    assert len(run['trail'][0]) == presence_snapshot.STEP
