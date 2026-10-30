"""UI 计时锚点: 后台运行中重新挂接时, 必须用后端 run 起点, 不能用 newTask 的 Date.now()。

真机回归(2026-10-27): 任务真实 387.6s, UI 在结束前 8s 才重新挂接 → 显示 8s。
"""
from playwright.sync_api import sync_playwright

from test_motion_navigation_ui import open_page


def test_new_task_uses_backend_start_and_backend_end():
    with sync_playwright() as engine:
        browser, page, errors = open_page(engine)
        got = page.evaluate('''()=>{
          const start=Date.now()-600000;
          newTask('p','m',Date.now(),null,start);
          const anchor=task.t0;
          const fake={_backendStartedAt:start,_backendEndedAt:start+387600,t0:Date.now()};
          const ms=taskElapsedMs(fake,Date.now());
          return {anchor,now:Date.now(),ms,text:fmtElapsed(ms)};
        }''')
        assert abs(got['anchor'] - (got['now'] - 600000)) < 5000
        assert got['ms'] == 387600
        assert got['text'] == '6:27'
        assert not errors
        browser.close()


def test_poll_attaching_to_a_running_task_uses_backend_start():
    """后台任务已经在跑: idle poll 接续时必须用 started_at, 不是接续那一刻。"""
    with sync_playwright() as engine:
        browser, page, errors = open_page(engine)
        got = page.evaluate('''()=>{
          const startSec=Math.floor(Date.now()/1000)-600;
          GA.poll=()=>JSON.stringify({running:true,active_convo:'c1',cid:'c1',prompt:'p',
            started_at:startSec,ended_at:0,gen:1,status:'running',steps:[],final:''});
          poll();
          return {t0:task&&task.t0,startSec,hasTask:!!task};
        }''')
        assert got['hasTask']
        assert abs(got['t0'] - got['startSec'] * 1000) < 5000
        assert not errors
        browser.close()


def test_new_task_without_backend_start_uses_now():
    with sync_playwright() as engine:
        browser, page, errors = open_page(engine)
        got = page.evaluate('''()=>{const before=Date.now();newTask('p','m',Date.now());
          return {delta:task.t0-before};}''')
        assert 0 <= got['delta'] < 5000
        assert not errors
        browser.close()
