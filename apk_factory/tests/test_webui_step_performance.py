"""Production step/render/storage functions exercised in Chromium (no Android bridge).

Run with PLAYWRIGHT_CHROMIUM_EXECUTABLE pointing to a local Chrome if needed.
Assertions cover operation counts/DOM identity, not machine-dependent timing.
"""
import os
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / 'app/src/main/assets/ga_runtime/webui'


def section(src, start, end):
    return src[src.index(start):src.index(end, src.index(start))]


@pytest.fixture
def page():
    pw = pytest.importorskip('playwright.sync_api')
    src = (WEB / 'app.js').read_text(encoding='utf-8')
    chunks = [
        section(src, 'function stepCard(', 'const _LV_FUSE='),
        section(src, 'function cleanStepText(', '/* ════════ STEPLABEL'),
        section(src, 'function stepNumber(', 'function finish('),
        section(src, 'function stepFoldLive(', 'function foldSteps('),
        section(src, 'function patchReplaySteps(', 'function renderMsgs('),
        section(src, '// Stream updates mutate one step only.', 'function _recoverCorruptConvos('),
        section(src, 'function _twRow(', 'let _twLiveEl='),
        section(src, 'function finish(', '/* ════════ STEP_FOLD'),
    ]
    # Include the actual generation transition rather than a reimplementation.
    gen = section(src, '  if(ownRun&&task&&!replaying&&!task.done&&j.gen!=null)', '  if(task&&ownRun)(j.steps||[]).forEach(setStep);')
    with pw.sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True, executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page()
        page.route('http://ga.test/**', lambda route: route.fulfill(body='<div id="chat"></div>', content_type='text/html'))
        page.goto('http://ga.test/')
        page.add_script_tag(content=r'''
          let task=null,replaying=false,running=true,_noActs=false,_host=null;
          let convos=[],curConvo=null,runConvo=null,multi=false,runs=new Map();
          let _convoAuthLoaded=true,CONVO_KEEP=100,lang='zh';
          let saves=[],richCalls=0,liveCalls=0,twState={gen:null,box:null,evs:[]};
          const t=x=>x,applyStepDisplay=()=>{},_twStripText=x=>x;
          const kvSet=(k,v)=>{saves.push(JSON.parse(v));return true},_lsStoreKey=x=>x;
          const slimConvo=x=>x,pruneEmptyAssistants=()=>{},toast=()=>{};
          const extractFileDiffs=x=>({text:x,diffs:[]}),linkifyArtifactAnchors=()=>{};
          const _lvAppend=(sb,delta)=>sb.appendChild(document.createTextNode(delta));
          const _twLiveBar=()=>{liveCalls++},_twTitle=e=>({t:e.name,s:''});
          const _twLine=(x,n)=>String(x).slice(0,n),_twDur=x=>String(x),_twFail=e=>e.status==='error';
          const _twIcon=()=>'',_twResult=e=>e.output_summary,_twEsc=String;
          const toolDetail=()=>{},ICO_SPIN='',ICO_OK='',ICO_ERR='',ICO_TOOL='';
          const addActions=()=>{},renderCites=()=>{},renderArtifacts=()=>{},stripRunSpin=()=>{};
          const stopLive=()=>{},renderTaskStats=()=>{},estTok=x=>x.length,_ensureRunMeta=()=>{},fmtElapsed=String,fmtTok=String,scroll=()=>{};
          const GAT={emit:()=>{}};let _flIdx=null;let runStats={t0:0,ti:0,to:0,cr:0,cw:0},previewing=false;
          window.GA_FINALCARD_OFF=true;window.GA_CITE_OFF=true;
          function renderRich(text){richCalls++;const span=document.createElement('span');span.textContent=text;return span}
          function el(tag,cls,parent){const e=document.createElement(tag);e.className=cls;if(parent)parent.appendChild(e);return e}
          function setup(replay=false){
            document.getElementById('chat').textContent='';replaying=replay;
            const box=el('div','task',document.getElementById('chat'));
            task={box,sbox:el('div','ga-card--msg',box),steps:[],done:false,_gen:1,
                  msg:replay?null:{role:'assistant',steps:[],final:''}};
            box._stepCards=task.steps;curConvo={id:'test',msgs:task.msg?[task.msg]:[]};runConvo=curConvo;convos=[curConvo];
            saves=[];richCalls=0;twState={gen:null,box:null,evs:[]};return task;
          }
          function tool(i,turn,status='done'){return {id:i,turn,gen:1,status,name:'tool'+i,input_summary:'input',output_summary:'output',dur_ms:20}}
        ''' + '\n'.join(chunks) + '\nfunction changeGen(j){const ownRun=true;'+gen+'}\n')
        yield page
        browser.close()


def test_sparse_history_does_not_allocate_missing_cards(page):
    result = page.evaluate('''() => {setup(true);
      for(let n=2921;n<=3000;n++)setStep({n,summary:'step '+n,text:'body '+n});
      return {cards:task.steps.length,dom:task.box.querySelectorAll('.step').length,
              first:task.steps[0]._stepN,last:task.steps.at(-1)._stepN,saves:saves.length};}''')
    assert result == {'cards': 80, 'dom': 80, 'first': 2921, 'last': 3000, 'saves': 0}


def test_stream_updates_one_record_without_history_scan(page):
    result = page.evaluate('''() => {setup();
      for(let n=1;n<=1000;n++)setStep({n,summary:'step '+n,text:'body '+n});
      flushPendingConvos();saves=[];
      const first=task.msg.steps[0],last=task.msg.steps.at(-1);let scans=0,queries=0;
      const oldQuery=Element.prototype.querySelector;
      Element.prototype.querySelector=function(s){queries++;return oldQuery.call(this,s)};
      for(const k of ['map','forEach','slice'])task.steps[k]=()=>{scans++;throw Error('history scan')};
      setStep({n:1000,summary:'last',text:'updated'});
      Element.prototype.querySelector=oldQuery;
      return {scans,queries,firstSame:first===task.msg.steps[0],lastSame:last===task.msg.steps.at(-1),
              text:last.text,saves:saves.length,dirty:_dirtyStepMsgs.has(task.msg)};}''')
    assert result['scans'] == 0
    assert result['queries'] <= 5
    assert result['firstSame'] and result['lastSame'] and result['dirty']
    assert result['text'] == 'updated' and result['saves'] == 0


def test_out_of_order_updates_keep_number_data_and_dom_order(page):
    result = page.evaluate('''() => {setup();
      [9,3,7,9].forEach(n=>setStep({n,summary:'step '+n,text:'body '+n}));
      const before=task.steps[2];setStep({n:9,summary:'new',text:'changed'});
      return {nums:task.steps.map(c=>c._stepN),data:task.msg.steps.map(s=>s.n),
              dom:[...task.box.querySelectorAll('.step')].map(c=>c._stepN),
              final:task.steps.map(c=>!!c._final),same:before===task.steps[2]};}''')
    assert result == {'nums': [3, 7, 9], 'data': [3, 7, 9], 'dom': [3, 7, 9], 'final': [True, True, False], 'same': True}


def test_autofold_preserves_user_open_and_closed_choices(page):
    result = page.evaluate('''() => {setup();setStep({n:1,text:'one'});
      const a=task.steps[0];a._userOpen=true;
      setStep({n:2,text:'two'});const b=task.steps[1];b._userClosed=1;b.classList.remove('open');
      setStep({n:2,text:'two more'});const closed=!b.classList.contains('open');
      setStep({n:3,text:'three'});return {firstOpen:a.classList.contains('open'),closed,
        secondClosed:!b.classList.contains('open'),thirdOpen:task.steps[2].classList.contains('open')};}''')
    assert all(result.values())


def test_save_timer_coalesces_new_steps_and_flushes_latest_text(page):
    page.clock.install(time=0)
    page.clock.pause_at(1000)
    page.evaluate("setup();setStep({n:1,text:'first'});setStep({n:2,text:'second'});setStep({n:2,text:'latest'})")
    assert page.evaluate('saves.length') == 0
    page.clock.run_for(1499)
    assert page.evaluate('saves.length') == 0
    page.clock.run_for(1)
    assert page.evaluate('saves.length') == 1
    assert page.evaluate('saves[0][0].msgs[0].final') == 'first\n\nlatest'
    page.evaluate("setStep({n:2,text:'exit text'});window.dispatchEvent(new Event('pagehide'))")
    assert page.evaluate('saves.length') == 2
    assert page.evaluate('saves[1][0].msgs[0].steps[1].text') == 'exit text'
    page.clock.run_for(2000)
    assert page.evaluate('saves.length') == 2


def test_background_messages_flush_independently_of_active_task(page):
    result = page.evaluate('''() => {setup();setStep({n:1,text:'background'});const old=task.msg;
      task=null;flushPendingConvos();return {final:old.final,saved:saves[0][0].msgs[0].final,dirty:_dirtyStepMsgs.size};}''')
    assert result == {'final': 'background', 'saved': 'background', 'dirty': 0}


def test_generation_reset_discards_old_indices_and_pending_text(page):
    result = page.evaluate('''() => {setup();setStep({n:921,text:'old'});changeGen({gen:2});
      setStep({n:1,text:'new'});flushPendingConvos();return {nums:task.msg.steps.map(s=>s.n),
        cards:task.box.querySelectorAll('.step').length,key:task.steps[0].dataset.gk,final:task.msg.final};}''')
    assert result == {'nums': [1], 'cards': 1, 'key': '2:1', 'final': 'new'}


def test_pclink_patch_reuses_sparse_cards_without_saving(page):
    result = page.evaluate('''() => {setup(true);[921,922].forEach(n=>setStep({n,text:'old'}));
      const original=task,last=task.steps[1];
      patchReplaySteps(task.box,[{n:922,text:'new'},{n:923,text:'tail'}]);
      return {sameTask:task===original,sameCard:last===task.box.querySelectorAll('.step')[1],
              text:last._text,cards:task.box.querySelectorAll('.step').length,saves:saves.length};}''')
    assert result == {'sameTask': True, 'sameCard': True, 'text': 'new', 'cards': 3, 'saves': 0}


def test_tools_touch_only_occupied_cards_and_move_ahead_event(page):
    result = page.evaluate('''() => {setup();for(let n=1;n<=1000;n++)setStep({n,text:'x'});
      let scans=0;task.box.querySelectorAll=()=>{scans++;throw Error('full scan')};
      const event=tool(1,1001);renderTools({gen:1,running:true,tool_events:[event]});
      const old=task.steps.at(-1);const first=old.querySelector('.tsr');
      renderTools({gen:1,running:true,tool_events:[event]});const same=first===old.querySelector('.tsr');
      setStep({n:1001,text:'new'});renderTools({gen:1,running:true,tool_events:[event]});
      const moved=!old.querySelector('.tsr')&&!!task.steps.at(-1).querySelector('.tsr');
      renderTools({gen:1,running:false,tool_events:[]});
      const retained=!!task.steps.at(-1).querySelector('.tsr');
      renderTools({gen:1,running:false,tool_events:[tool(2,500)]});
      return {scans,same,moved,retained,cleared:!task.steps.at(-1).querySelector('.tsr')&&!!task.steps[499].querySelector('.tsr')};}''')
    assert result == {'scans': 0, 'same': True, 'moved': True, 'retained': True, 'cleared': True}


def test_finish_keeps_completed_dom_and_flushes_once(page):
    page.clock.install(time=0)
    page.clock.pause_at(1000)
    result = page.evaluate('''() => {setup();window.GA_STEPFOLD_OFF=true;
      setStep({n:1,text:'one'});const first=task.steps[0];first.classList.add('open');
      setStep({n:2,text:'two'});const body=first.querySelector('.sb').firstChild;
      finish();return {same:first.querySelector('.sb').firstChild===body,final:task.msg.final,
        done:task.done,saves:saves.length,dirty:_dirtyStepMsgs.size};}''')
    assert result == {'same': True, 'final': 'one\n\ntwo', 'done': True, 'saves': 1, 'dirty': 0}
    page.clock.run_for(2000)
    assert page.evaluate('saves.length') == 1


def test_late_text_after_finish_updates_the_persisted_record(page):
    page.clock.install(time=0)
    page.clock.pause_at(1000)
    result = page.evaluate("""() => {setup();window.GA_STEPFOLD_OFF=true;
      setStep({n:1,text:'partial'});finish();setStep({n:1,text:'complete'});
      flushPendingConvos();return {text:saves.at(-1)[0].msgs[0].steps[0].text,
        final:saves.at(-1)[0].msgs[0].final};}""")
    assert result == {'text': 'complete', 'final': 'complete'}
