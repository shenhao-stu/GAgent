"""Foreground selection is independent of background tasks (pip install quickjs)."""
import json
from pathlib import Path
import pytest
quickjs = pytest.importorskip("quickjs")
SRC = (Path(__file__).resolve().parents[2] / "app/src/main/assets/ga_runtime/webui/app.js").read_text()


def context():
    c = quickjs.Context()
    c.eval("var window={}; var saved=null; function kvSet(k,v){saved=v}; function kvGet(){return saved};")
    return c


def test_js_syntax():
    context().eval("new Function(" + json.dumps(SRC) + ")")


@pytest.mark.parametrize("selected", ["A", "B", ""])
def test_boot_restores_view_not_running_session(selected):
    c=context()
    c.eval("var saved={id:"+json.dumps(selected)+"}; var live=[{id:'A'},{id:'B'}]; var j={running:true,active_convo:'B',prompt:'B only'}; var multi=true,running=false; var runs={}; function ensureRun(id){return runs[id]||(runs[id]={})}; function anyRunning(){return true}; function parseBridge(s){return JSON.parse(s)}; function bridgePollAll(){return JSON.stringify({sessions:[{cid:'B',running:true}]})}; function bridgePoll(id){return JSON.stringify({active_convo:id,running:id==='B',prompt:id+' only'})};")
    block=SRC[SRC.index('    let liveC='):SRC.index('    if(j.running&&liveC&&liveC.msgs)')]
    c.eval(block + "globalThis.result={id:liveC&&liveC.id,prompt:j.prompt};")
    result=json.loads(c.eval("JSON.stringify(result)"))
    assert result['id']==(selected or None)
    assert result.get('prompt')==(selected+' only' if selected else None)


def test_new_view_persistence():
    c=context()
    block=SRC[SRC.index('let _lastViewId='):SRC.index('function renderMsgs(c,skip)')]
    c.eval(block+"rememberView({id:'new'});")
    assert c.eval('saved.id')=='new'
    c.eval('rememberView(null)')
    assert c.eval('saved.id')==''
    assert 'startNew=false;rememberView(c);' in SRC
    assert 'activeCid=null;rememberView(null);' in SRC


@pytest.mark.parametrize('selected', [None,'A'])
@pytest.mark.parametrize('multi', [True,False])
def test_background_notification_cannot_select_view(selected,multi):
    c=context()
    c.eval("var curConvo="+json.dumps({'id':selected} if selected else None)+"; var multi="+json.dumps(multi)+"; var j={notif_pending:{cid:'B'},running:true}; var convos=[{id:'B'}]; var running=false; function ensureRun(){return {}}; function anyRunning(){return true}; function renderDrawer(){};")
    block=SRC[SRC.index('  if(j.notif_pending){'):SRC.index('  // 空闲 UI 发现后台')]
    c.eval(block)
    assert c.eval('curConvo&&curConvo.id')==selected


def test_resume_does_not_restore_selection():
    block=SRC[SRC.index('window.gaOnResume=function()'):SRC.index("document.addEventListener('visibilitychange'")]
    assert 'lastView' not in block
    assert 'curConvo=' not in block.replace('curConvo===','')
    assert 'const cid=curConvo&&curConvo.id;if(!cid)return;' in SRC
