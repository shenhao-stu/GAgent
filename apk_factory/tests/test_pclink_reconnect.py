"""PC Link reconnect regressions; Node runs the actual JS function bodies."""
import asyncio
import importlib.util
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from .test_pclink_scroll_contract import _func_body

CORE = Path(__file__).resolve().parents[2] / 'app/src/main/assets/ga_runtime'
sys.path.insert(0, str(CORE))


def test_chat_survives_disconnect_and_resume():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for JS behavior tests')
    src = (CORE / 'webui/pclink.js').read_text(encoding='utf-8')
    names = {'renderOffline': '', 'openView': '', 'setPcHd': 'title,peer,run',
             'resume': '', 'doPut': ''}
    funcs = '\n'.join('function %s(%s){%s}' % (n, args, _func_body(src, n))
                      for n, args in names.items())
    harness = r'''
const assert=require('assert');
let now=100000;Date.now=()=>now;
const classes=()=>({add(){},remove(){},contains(){return true},toggle(){}});
const task={folded:true};
const box={firstElementChild:task,innerHTML:'old chat',scrollTop:321,
  querySelector(){return null}};
const side={querySelector(){return {}}};
const sub={textContent:'',classList:classes()};
const input={value:'keep my draft',style:{}};
const view={classList:classes()};
const nodes={pcMsgs:box,pcSide:side,pcHdTitle:{},pcHdSub:sub,
  pcView:view,pcIn:input,pcBtn:{classList:classes()}};
const document={getElementById:id=>nodes[id]};
const window={GA:{send(){}}},GA=window.GA;
let connected=false,offlineSince=0,resumedAt=0,lastSig='old-sig',idleRounds=5;
let segTxt={'0/0':{txt:'answer'}},taskSnap=[{i:0}],curPeer='pc';
let putBusy=false,lastPut=null;
let polls=0,wakes=0,skels=0;
const ensureView=()=>view,track=()=>{},edgeFx=()=>{},t=k=>k;
const renderOfflineSide=()=>{},skel=()=>{skels++},skelSide=()=>{};
const refreshStatus=(cb,resume)=>{if(resume)wakes++},pollNow=()=>{polls++};
const snapshots=taskSnap,segments=segTxt;
renderOffline();
assert.equal(box.innerHTML,'old chat');assert.equal(lastSig,'old-sig');
openView();
assert.equal(skels,0);assert.strictEqual(taskSnap,snapshots);
assert.strictEqual(segTxt,segments);assert.strictEqual(box.firstElementChild,task);
assert.equal(box.scrollTop,321);assert.equal(input.value,'keep my draft');
assert.equal(task.folded,true);
setPcHd(undefined,'pc',true);assert.equal(sub.textContent,'pc');
now+=9999;setPcHd(undefined,'pc',false);assert.equal(sub.textContent,'pc');
now++;setPcHd(undefined,'pc',false);assert.equal(sub.textContent,'pc · pcOffline');
connected=true;setPcHd(undefined,'pc',false);
assert.equal(sub.textContent,'pc · pcOn');assert.equal(offlineSince,0);
connected=false;setPcHd(undefined,'pc',false);assert.equal(sub.textContent,'pc');
const before=polls;resume();resume();assert.equal(polls,before+1);
assert.equal(wakes,2);assert.equal(box.scrollTop,321);
// The real send callback must not clear the draft or report success on failure.
let notice='';const toast=s=>{notice=s},isNew=()=>false;
const api=(method,path,body,cb)=>cb({error:'not connected'});
doPut();assert.equal(input.value,'keep my draft');
assert.equal(notice,'not connected');assert.equal(putBusy,false);
console.log('chat preservation, status grace, resume dedup and failed-send draft: OK');
'''
    result = subprocess.run([node, '-e', funcs + '\n' + harness],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_peer_list_gaps_preserve_selected_chat():
    """A successful but incomplete peer list must not navigate or reset reading state."""
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for JS behavior tests')
    src = (CORE / 'webui/pclink.js').read_text(encoding='utf-8')
    names = {'round': 'done', 'setPeer': 'name', 'pickPeer': 'ps'}
    funcs = '\n'.join('function %s(%s){%s}' % (n, args, _func_body(src, n))
                      for n, args in names.items())
    harness = r'''
const assert=require('assert');
const original='chat-123@A',other={name:'other-1@B',caps:['get']};
let curPeer=original,tok=1,offN=0,connected=true,idleRounds=0,newWatch=null;
let knownNames=new Set(),gen=0,lastSig='sig',sigAge=0,pendingPut={text:'pending'};
let segTxt={'0/0':{txt:'answer'}},taskSnap=[{folded:true}];
const segments=segTxt,snapshots=taskSnap,pending=pendingPut;
const task={folded:true},box={firstElementChild:task,innerHTML:'old chat',scrollTop:321,
  _pcStick:false,_pcUserScroll:true,_pcPinSeq:7,style:{setProperty(){}}};
const input={value:'draft'},sub={textContent:''};
const document={getElementById:id=>({pcMsgs:box,pcIn:input,pcHdSub:sub})[id]};
const t=k=>k,metaOf=()=>({}),isNew=()=>false,isAgent=p=>p.caps.includes('get');
const lastPeerSaved=()=>({name:original}),lastPeer=lastPeerSaved,baseOf=n=>n.replace(/-\d+(?=@|$)/,''),noHub=n=>n.split('@')[0];
const hasPid=n=>/-\d+(?=@|$)/.test(n);
let response,doneCount=0,pulls=0,homes=0,skels=0,run=true,side;
const api=(m,p,b,cb)=>cb(response),guard=(fn)=>fn();
const renderRow=()=>{},renderOffline=()=>{},setRunBtn=v=>{run=v};
const setPcHd=()=>{sub.textContent='connected'},renderSide=ps=>{side=ps};
const renderHome=()=>{homes++},skel=()=>{skels++};
const pullMsgs=done=>{pulls++;done()};
function poll(ps){response=ps;const before=doneCount;round(()=>doneCount++);
  assert.equal(doneCount,before+1,'each round must re-arm exactly once')}
function preserved(){
  assert.equal(curPeer,original);assert.equal(gen,0);assert.equal(lastSig,'sig');
  assert.strictEqual(segTxt,segments);assert.strictEqual(taskSnap,snapshots);
  assert.strictEqual(pendingPut,pending);assert.strictEqual(box.firstElementChild,task);
  assert.equal(box.innerHTML,'old chat');assert.equal(box.scrollTop,321);
  assert.equal(box._pcStick,false);assert.equal(box._pcUserScroll,true);
  assert.equal(box._pcPinSeq,7);assert.equal(task.folded,true);assert.equal(input.value,'draft');
  assert.equal(homes,0);assert.equal(skels,0);
}
for(const ps of [[],[other],[other,{name:'other-2@B',caps:['get']}],
                [{name:'chat-456@A',caps:['get']}],[]]){
  poll(ps);preserved();assert.equal(pulls,0);assert.equal(run,false);
  assert.equal(sub.textContent,original+' · pcWaiting');assert.strictEqual(side,ps);
}
poll({error:'offline'});poll({error:'offline'});preserved();
poll([{name:original,caps:['get']}]);preserved();assert.equal(pulls,1);
// Explicit selection and the genuinely unselected home retain normal behavior.
setPeer(other.name);poll([other]);assert.equal(curPeer,other.name);assert.equal(pulls,2);
setPeer(null);poll([]);assert.equal(homes,1);
poll([other]);assert.equal(curPeer,other.name);assert.equal(pulls,3);
console.log('empty/partial lists, unrelated/restarted peers, recovery, manual selection: OK');
'''
    result = subprocess.run([node, '-e', funcs + '\n' + harness],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def _module():
    spec = importlib.util.spec_from_file_location('pclink_reconnect_test', CORE / 'pclink.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from unittest.mock import AsyncMock
    config = {'url': 'wss://relay.example/ws', 'token': 'synthetic'}
    mod.service_config = types.SimpleNamespace(pclink_config=lambda: config)
    mod._sock_config = config
    mod._sync_group = AsyncMock(return_value=False)
    return mod


def test_resume_interrupts_failed_connect_backoff(monkeypatch):
    mod = _module()

    async def scenario():
        failed, retried = asyncio.Event(), asyncio.Event()
        attempts = []
        sock = object()

        async def connect(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                failed.set()
                raise OSError('offline')
            retried.set()
            return sock

        config = {'url': 'wss://relay.example/ws', 'token': 'sample-relay-credential'}
        monkeypatch.setattr(mod.service_config, 'pclink_config', lambda: config)
        monkeypatch.setitem(sys.modules, 'p2p_ws_client', types.SimpleNamespace(
            connect_saved=connect, load_room=lambda *a, **k: {'signal_url': config['url']}))
        monkeypatch.setattr(mod, '_paired', lambda: True)
        def attach(s, configuration):
            mod._sock, mod._sock_config = s, configuration
        monkeypatch.setattr(mod, '_attach', attach)
        monkeypatch.setattr(mod, '_ensure_loop', lambda: mod._loop)
        monkeypatch.setattr(mod, '_signal', lambda: 'test')
        mod._loop = asyncio.get_running_loop()
        keeper = asyncio.create_task(mod._keeper())
        try:
            await asyncio.wait_for(failed.wait(), 0.5)
            # Minimum normal backoff is 1.5s; ordinary status must not bypass it.
            mod.handle('/pclink.status')
            await asyncio.sleep(0.03)
            assert len(attempts) == 1
            response = json.loads(mod.handle('/pclink.resume'))
            assert response['ok'] == 1
            await asyncio.wait_for(retried.wait(), 0.5)
            assert len(attempts) == 2
            assert mod._sock is sock
            # Foreground on a healthy socket must not replace or reconnect it.
            assert json.loads(mod.handle('/pclink.resume'))['connected']
            await asyncio.sleep(0.03)
            assert len(attempts) == 2
        finally:
            keeper.cancel()
            with pytest.raises(asyncio.CancelledError):
                await keeper

    asyncio.run(scenario())


def test_native_resume_reaches_pclink_before_local_early_returns():
    src = (CORE / 'webui/app.js').read_text(encoding='utf-8')
    body = src.split('window.gaOnResume=function(){', 1)[1].split('\n};', 1)[0]
    assert body.index('PCLINK.resume()') < body.index('if(!stick)return')
    js = (CORE / 'webui/pclink.js').read_text(encoding='utf-8')
    assert "resume?'/pclink.resume':'/pclink.status'" in js
    assert 'window.PCLINK={refreshStatus,openView,closeView,reI18n,resume}' in js
