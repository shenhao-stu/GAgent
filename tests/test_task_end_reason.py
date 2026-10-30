"""A user stop or a dead worker must not be reported as a finished task by the floating capsule."""
import json
import queue
import sys
import threading
from pathlib import Path

import pytest

CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
FLOAT = Path(__file__).parents[1] / 'app/src/main/java/com/ljq/ga/FloatService.kt'


class _Agent:
    def __init__(self):
        self.aborted = False
        self.history = []

    def abort(self):
        self.aborted = True


@pytest.fixture
def entry(tmp_path, monkeypatch):
    monkeypatch.setenv('GA_DIR', str(tmp_path))
    import android_entry as entry
    for name in ('_save_hist', '_persist_convo'):
        monkeypatch.setattr(entry, name, lambda *a, **k: None)
    monkeypatch.setattr(entry, '_hist', [])
    monkeypatch.setattr(entry.patches, 'abort_streams', lambda s: None)
    return entry


def _running(entry, monkeypatch, cid):
    sess = entry._Sess(cid)
    sess.agent = _Agent()
    sess.state.update(running=True, status='思考中', steps=[], final='', prompt='p', gen=entry._next_gen(), end='')
    monkeypatch.setattr(entry, '_resolve_cid', lambda c, explicit=False, build=False: (sess, None))
    return sess


def _finish(entry, sess, item, outputs=('step text',)):
    q = queue.Queue()
    q.put({'turn': 2, 'outputs': list(outputs)})
    q.put(dict(item, turn=2, outputs=list(outputs)))
    t = threading.Thread(target=entry._drain, args=(q, sess.state['gen'], sess, 'c1'))
    t.start(); t.join(5)
    assert not t.is_alive()
    return json.loads(entry._poll_for(sess, '0', summary=True))


def test_normal_completion_is_done(entry, monkeypatch):
    poll = _finish(entry, _running(entry, monkeypatch, 'ga_done'), {'done': 'all good'})
    assert poll['end'] == 'done' and poll['status'].startswith('完成')


def test_poll_exposes_the_backend_run_span(entry, monkeypatch):
    """UI 计时必须以真实运行起点/终点为准，不能用以 WebView 挂接时刻新建的本地 t0。

    真机回归(2026-10-27): 任务跑了 387.6s，但 UI 在结束前 8s 才重新挂接，
    `newTask()` 用 Date.now() 重置计时锚 → 显示 8s。后端 t0 一直是对的，
    只是 poll 没把它交给前端。"""
    sess = _running(entry, monkeypatch, 'ga_span')
    sess.state['t0'] = 1234.5
    _finish(entry, sess, {'done': 'ok'})
    d = json.loads(entry._poll_for(sess, '0', summary=True))
    assert d['started_at'] == 1234.5
    assert d['ended_at'] >= 1234.5


def test_running_poll_exposes_started_at_before_the_run_ends(entry, monkeypatch):
    sess = _running(entry, monkeypatch, 'ga_span_live')
    sess.state['t0'] = 1234.5
    d = json.loads(entry._poll_for(sess, '0'))
    assert d['started_at'] == 1234.5
    assert d['ended_at'] == 0


@pytest.mark.parametrize('lang,label', [('zh', '待命'), ('en', 'Idle')])
def test_idle_status_is_shown_in_the_ui_language(entry, monkeypatch, lang, label):
    """The header and capsule show the backend status verbatim, so idle must not be the raw word 'idle'."""
    monkeypatch.setattr(entry, '_LANG', lang)
    assert entry._new_state()['status'] == label


def test_user_stop_is_reported_as_stopped(entry, monkeypatch):
    sess = _running(entry, monkeypatch, 'ga_stop')
    entry.abort2('c1')
    assert sess.agent.aborted
    poll = _finish(entry, sess, {'done': 'partial'})
    assert poll['end'] == 'stopped' and poll['status'].startswith('已停止') and not poll['running']


def test_stop_after_finish_does_not_relabel(entry, monkeypatch):
    sess = _running(entry, monkeypatch, 'ga_late')
    _finish(entry, sess, {'done': 'all good'})
    entry.abort2('c1')
    assert json.loads(entry._poll_for(sess, '0', summary=True))['end'] == 'done'


def test_error_final_is_reported_as_error(entry, monkeypatch):
    poll = _finish(entry, _running(entry, monkeypatch, 'ga_err'), {'done': '!!!Error: provider unreachable'}, outputs=())
    assert poll['end'] == 'error' and poll['status'].startswith('出错')


H1, H2 = '\n\nLLM Running (Turn 1) ...\n\n', '\n\n**Turn 2 ...**\n\n'
HTTP_429 = '!!!Error: HTTP 429: {"error":{"code":"1308","message":"Usage limit reached for 5 hour."}}'


def test_http_error_after_the_turn_header_is_an_error(entry, monkeypatch):
    """The kernel's done text starts with the turn header, so the old prefix test never fired (a 429 showed as Done)."""
    last = H2 + HTTP_429
    poll = _finish(entry, _running(entry, monkeypatch, 'ga_429'), {'done': H1 + 'opened settings' + last},
                   outputs=(H1 + 'opened settings', last))
    assert poll['end'] == 'error' and poll['status'].startswith('出错')


@pytest.mark.parametrize('last, end', [
    (H2 + '<thinking>x</thinking>!!!Error: ReadTimeout: read timed out', 'error'),
    (H2 + 'Partial answer\n\n[!!! 流异常中断 ChunkedEncodingError: reset !!!]', 'error'),
    (H2 + 'Done. Earlier the provider said !!!Error: HTTP 500 but the retry worked.' + ' Details follow.' * 10, 'done'),
    (H2 + 'All settings applied.', 'done'),
])
def test_end_reason_reads_the_last_turn_like_the_kernel(entry, last, end):
    assert entry._end_reason(False, H1 + '!!!Error: HTTP 429 on turn one' + last, last) == end
    assert entry._end_reason(True, '', last) == 'stopped'


def test_capsule_never_shows_done_for_stop_or_error():
    text = FLOAT.read_text(encoding='utf-8')
    assert 'val done = ended && !stopped && !failed' in text
    assert 's("■ 已停止", "■ Stopped")' in text and 's("⚠ 出错", "⚠ Error")' in text
    assert 'x.optString("end") != "stopped") notifyTaskEnd' in text


def test_pending_question_stays_visible_to_the_capsule_after_the_chat_reads_it(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv('GA_DIR', str(tmp_path))
    import android_entry as entry
    sess = entry._Sess('askcid')
    monkeypatch.setattr(entry, '_focus_cid', 'askcid')
    ask = {'question': 'Log in first?', 'candidates': ['Done', 'Skip']}
    sess.state.update(running=False, status='done', final='waiting', nsteps=1, steps=[{'n': 1}], ask=ask, ask_open=ask, end='done')
    assert json.loads(entry._poll_for(sess, '0'))['ask'] == ask            # chat consumes the one-shot field
    assert json.loads(entry._poll_for(sess, '0'))['ask'] in (None, '')
    assert json.loads(entry._poll_for(sess, '-1', summary=True))['ask'] == ask   # capsule (read-only) still sees it
    monkeypatch.setattr(entry, '_focus_cid', 'othercid')
    assert json.loads(entry._poll_for(sess, '-1', summary=True))['ask'] in (None, '')   # a background question does not take over
    monkeypatch.setattr(entry, '_focus_cid', 'askcid')
    sess.state.update(ask=None, ask_open=None)                              # what a new task does
    assert json.loads(entry._poll_for(sess, '-1', summary=True))['ask'] in (None, '')


def test_chat_divider_says_failed_for_an_error_end():
    """The chat's end-of-task divider follows the backend end reason instead of always saying "Task complete"."""
    from playwright.sync_api import sync_playwright
    from test_motion_navigation_ui import open_page
    with sync_playwright() as engine:
        browser, page, errors = open_page(engine)
        page.evaluate('''()=>{window.GA.notify=()=>{};onTaskDone(true,null,'error');onTaskDone(true,null,'done')}''')
        notes = page.evaluate('''()=>[...document.querySelectorAll('.doneNote')].map(n=>[n.className,n.textContent])''')
        assert notes[-2:] == [['doneNote err', 'Task failed'], ['doneNote', 'Task complete']]
        heads = page.evaluate('''()=>{const out=[];for(const er of [1,0]){newTask('p','m',Date.now());task._err=er;
          renderTaskStats({el:1000});const c=task.state.querySelector('.ck2');out.push([c.className,c.getAttribute('aria-label')])}return out}''')
        assert heads == [['ck2 err', 'Task failed'], ['ck2', 'Done']]
        saved = page.evaluate('''()=>JSON.parse(JSON.stringify(slimConvo({id:'c',msgs:[
          {role:'assistant',prompt:'p',final:'f',er:1,fa:1},{role:'assistant',prompt:'p',final:'f'}]}))).msgs.map(m=>[m.er,m.fa])''')
        assert saved == [[1, 1], [None, None]]   # the error mark survives the chat store, so a cold-start replay keeps the cross
        assert not errors
        browser.close()
