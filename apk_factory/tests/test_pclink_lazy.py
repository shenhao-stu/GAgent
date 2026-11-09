"""Real Chromium geometry + production loader/render lifecycle; no phone/network needed."""
import os
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / 'app/src/main/assets/ga_runtime/webui'


@pytest.fixture
def page():
    pw = pytest.importorskip('playwright.sync_api')
    source = (WEB / 'pclink.js').read_text(encoding='utf-8')
    fetch = source[source.index('function fetchSeg('):source.index('function pullMsgs(')]
    lazy = source[source.index('function prefetch('):source.index('/* ---- 启动:')]
    with pw.sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True, executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"))
        page = browser.new_page(viewport={'width': 400, 'height': 650})
        page.set_content('''<style>
          #pcMsgs {box-sizing:border-box;height:500px;overflow:auto;padding-bottom:var(--pcTail,0px);overflow-anchor:none}
          .pcTask {padding:10px} .step {min-height:70px} .answer {white-space:pre-wrap}
        </style><div id="pcView" class="on"><div id="pcMsgs"></div></div>''')
        page.add_script_tag(content='''
          let gen=1,curPeer='pc',segTxt={},taskSnap=[],peerRun=false,pendingPut=null;
          let sent=[],pending=[],renders=0;
          const t=x=>x,rememberPeer=()=>{},setRunBtn=x=>{peerRun=!!x};
          function alignTop(box,el,gap){const sr=box.getBoundingClientRect(),er=el.getBoundingClientRect();box.scrollTop+=(er.top-sr.top)-gap}
          function api(method,path,body,cb,alive){sent.push(path);pending.push({cb,alive})}
          function reply(content='body',n=4){const q=pending.shift();if(!q.alive||q.alive())q.cb({content,n,off:0})}
          function fail(){const q=pending.shift();q.cb({error:'timeout'})}
          function renderMsgsInto(w,msgs){renders++;const tb=document.createElement('div');tb.className='task';w.appendChild(tb);
            const u=document.createElement('div');u.textContent=msgs[0].text;tb.appendChild(u);
            msgs[1].steps.forEach(s=>{const c=document.createElement('div');c.className='step open';
              c.innerHTML='<div class="sh"></div><div class="sb answer"></div>';
              c.querySelector('.sh').textContent=s.summary;c.querySelector('.sb').textContent=s.text;tb.appendChild(c)})}
          function renderBody(){}
        ''' + fetch + lazy + '''
          const box=document.getElementById('pcMsgs');box.addEventListener('scroll',scheduleVisible);
          function setup(count=40){gen++;curPeer='pc';segTxt={};taskSnap=Array.from({length:count},(_,i)=>({i,input:'question '+i,steps:[{j:0,n:4,title:'answer'}]}));
            prefetch({tasks:taskSnap,run:false},gen,curPeer,()=>{});}
          function go(i){box._pcPinSeq=(box._pcPinSeq||0)+1;box._pcStick=false;
            box.scrollTop=box.querySelectorAll('.pcTask')[i].offsetTop-box.offsetTop;scheduleVisible()}
        ''')
        yield page
        browser.close()


def test_cold_view_scroll_and_cache(page):
    page.evaluate('setup()')
    page.wait_for_function('sent.length===1')
    assert '/seg/39/0?' in page.evaluate('sent[0]')
    assert page.evaluate("box.querySelectorAll('.pcTask').length") == 40
    page.evaluate("reply('latest answer',4)")
    page.wait_for_timeout(800)
    assert page.evaluate('sent.length') == 1  # offscreen history never prefetched
    assert abs(page.evaluate("box.querySelectorAll('.task')[39].getBoundingClientRect().top-box.getBoundingClientRect().top") - 6) < 2
    page.evaluate('go(0)')
    page.wait_for_function('sent.length===2')
    assert '/seg/0/0?' in page.evaluate('sent[1]')
    page.evaluate("reply('old answer\\n'.repeat(90),4)")
    page.wait_for_timeout(100)
    assert page.evaluate('sent.length') == 2  # reflow rescans, no old viewport queue
    page.evaluate('go(39)')
    page.wait_for_timeout(100)
    assert page.evaluate('sent.length') == 2  # cached body reused


def test_slow_reply_survives_poll_and_failure_retries_next_round(page):
    page.evaluate('setup(1)')
    page.wait_for_function('sent.length===1')
    page.evaluate('gen++;scheduleVisible()')
    page.wait_for_timeout(50)
    assert page.evaluate('sent.length') == 1
    page.evaluate("reply('body');")
    page.wait_for_function("box.textContent.includes('body')")
    page.evaluate('segTxt={};gen++;scheduleVisible()')
    page.wait_for_function('sent.length===2')
    page.evaluate('fail()')
    page.wait_for_timeout(80)
    assert page.evaluate('sent.length') == 2
    page.evaluate('gen++;scheduleVisible()')
    page.wait_for_function('sent.length===3')


def test_close_and_peer_switch_drop_stale_response(page):
    page.evaluate('setup(1)')
    page.wait_for_function('sent.length===1')
    page.evaluate("document.getElementById('pcView').classList.remove('on');reply('cached')")
    page.wait_for_timeout(80)
    assert page.evaluate('sent.length') == 1
    assert 'cached' not in page.locator('#pcMsgs').inner_text()
    page.evaluate("document.getElementById('pcView').classList.add('on');scheduleVisible()")
    page.wait_for_function("box.textContent.includes('cached')")
    page.evaluate('segTxt={};gen++;scheduleVisible()')
    page.wait_for_function('sent.length===2')
    page.evaluate("curPeer='other';segTxt={};taskSnap=[];reply('WRONG')")
    page.wait_for_timeout(80)
    assert page.evaluate('Object.keys(segTxt).length') == 0
    assert 'WRONG' not in page.locator('#pcMsgs').inner_text()


def test_latest_answer_finishes_offscreen_without_switching(page):
    page.evaluate('setup()')
    page.wait_for_function('sent.length===1')
    page.evaluate("reply('partial',7)")
    page.wait_for_timeout(800)
    page.evaluate("""() => {
      box._pcPinSeq++;
      box.scrollTop=0;
      segTxt['0/0']={txt:'old answer',n:4};
      taskSnap[39].steps[0].n=12;
      gen++;prefetch({tasks:taskSnap,run:true},gen,curPeer,()=>{});
    }""")
    page.wait_for_function('sent.length===2', timeout=2000)
    assert '/seg/39/0?' in page.evaluate('sent[1]')
    page.evaluate("""() => {
      taskSnap[39].steps[0].n=20;
      gen++;prefetch({tasks:taskSnap,run:false},gen,curPeer,()=>{});
      reply('intermediate',12);
    }""")
    page.wait_for_function('sent.length===3', timeout=2000)
    assert '/seg/39/0?' in page.evaluate('sent[2]')
    page.evaluate("reply('FINAL COMPLETE ANSWER',20)")
    page.wait_for_function("box.querySelectorAll('.pcTask')[39].textContent.includes('FINAL COMPLETE ANSWER')")
    assert page.evaluate('box.scrollTop') < 5
    assert page.evaluate('curPeer') == 'pc'


def test_latest_priority_over_visible_old_history(page):
    page.evaluate('setup()')
    page.wait_for_function('sent.length===1')
    page.evaluate("reply('partial',7)")
    page.wait_for_timeout(800)
    page.evaluate("""() => {
      box._pcPinSeq++;box.scrollTop=0;
      taskSnap[39].steps[0].n=20;
      gen++;prefetch({tasks:taskSnap,run:false},gen,curPeer,()=>{});
    }""")
    page.wait_for_function('sent.length===2', timeout=2000)
    assert '/seg/39/0?' in page.evaluate('sent[1]')
    page.evaluate("reply('FINAL COMPLETE ANSWER',20)")
    page.wait_for_function('sent.length===3', timeout=2000)
    assert '/seg/0/0?' in page.evaluate('sent[2]')
