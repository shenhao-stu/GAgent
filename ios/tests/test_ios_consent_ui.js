// Real UI functions with a small DOM/timer harness; no credentials or network.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const base='app/src/main/assets/ga_runtime/webui/';
const source=fs.readFileSync(base+'app.js','utf8');
const shell=fs.readFileSync(base+'ios_ui.js','utf8');
const settings=fs.readFileSync(base+'ios_settings.js','utf8');
const part=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));
const functions=[part('function gaModal(o){','\nfunction gaPrompt('),
  shell,
  fs.readFileSync(base+'ios_consent.js','utf8'),
  part('function asyncModels(cfg,','\nfunction fetchModels('),
  part('function submit(){','\nbtn.onclick=submit;'),
  part('function foNos(cfg){','\nfunction foEnabledNames('),
  part('function testConnection(){','\nfunction openSheet('),
  settings.slice(settings.indexOf('const IOS_CONNECTION='),settings.indexOf('\nfunction iosConfigureFailover('))].join('\n');
function scene(){
  const ids={},timers=[],calls=[],tasks=[],notices=[];let status={ok:true,pcAccepted:true,receivers:[],version:'v1',providerSignature:'old'},pending=true;
  class Element{
    constructor(){this.style={};this.dataset={};this.children=[];this.queries={};this.disabled=false;const classes=new Set();
      this.classList={add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)};}
    get textContent(){return (this._text||'')+this.children.map(child=>child.textContent).join('')}
    set textContent(value){this._text=String(value);this.children=[]}
    set innerHTML(value){this._text='';this.children=[];this.queries={};
      const selectors=value.includes('pcHead')?['h4','.pcSub','.pcBody','.pcFoot']:value.includes('modalBtns')?['h4','.msg','.cancel','.ok']:[];
      for(const key of selectors)this.queries[key]=new Element();
    }
    querySelector(key){return this.queries[key]||null}
    setAttribute(){}
    appendChild(child){this.children.push(child);if(child.id)ids[child.id]=child}
    click(){if(!this.disabled&&this.onclick)this.onclick({target:this})}
  }
  for(const id of ['modalMask','modalCard','setvTest','pvName','pvKey','pvBase','pvProxy'])ids[id]=new Element();
  for(const id of ['pvName','pvKey','pvBase','pvProxy'])ids[id].value=id==='pvBase'?'https://example.com/v1':'test-only';
  ids.setvTest.queries={span:new Element(),svg:new Element()};   // the label and icon the iOS settings chrome gives the test button
  const c={window:{GA:{platform:'ios'}},URL,document:{createElement:()=>new Element()},$:id=>ids[id],
    t:x=>x,toast:x=>notices.push(x),GAT:{emit(){},errCat:x=>x,errMsg:x=>x},provType:'oai',editing:{},
    inp:{value:'original draft',style:{}},pendingAtts:[{path:'attachment.png'}],curConvo:{id:'original'},
    multi:false,running:false,startTask:text=>tasks.push(text),
    isAuto:()=>false,curProvider:()=>null,providers:[],active:{auto:'auto'},mkMixins:[],foCfg:{llm_nos:[]},
    setTimeout(fn){const timer={fn,stopped:false};timers.push(timer);return timer},clearTimeout(timer){timer.stopped=true},
    GA:{platform:'ios',send(cmd){calls.push(cmd);if(cmd==='/ios.consent.status')return JSON.stringify(status);
      if(cmd.startsWith('/ios.consent.refresh'))return '{"job":"refresh-1"}';
      if(cmd.startsWith('/models '))return '{"job":"models-1"}';
      if(cmd.startsWith('/jobresult '))return JSON.stringify(pending?{pending:true}:{result:JSON.stringify(status)});
      if(cmd.startsWith('/ios.consent '))return JSON.stringify({ok:true,accepted:JSON.parse(cmd.slice('/ios.consent '.length)).accepted});
      throw Error('unexpected command: '+cmd);
    },openUrl(){}}
  };
  vm.createContext(c);vm.runInContext(fs.readFileSync('app/src/main/assets/ga_runtime/webui/assets/util.js','utf8')+'\n'+functions,c);
  return {c,ids,calls,tasks,notices,setResult(value){status=value;pending=false},tick(){const timer=timers.shift();if(timer&&!timer.stopped)timer.fn()}};
}
for(const mode of ['button','backdrop']){
  const {c,ids,calls,notices}=scene();c.testConnection();assert(ids.setvTest.classList.contains('spin'));
  assert.equal(ids.setvTest.dataset.state,'testing');
  if(mode==='button')ids.modalCard.querySelector('.cancel').click();else ids.modalMask.onclick({target:ids.modalMask});
  assert(!ids.setvTest.classList.contains('spin'));assert(!ids.modalMask.classList.contains('on'));
  // Declining the request is not a failed test: the button returns to rest and nothing is announced.
  assert.equal(ids.setvTest.dataset.state,'idle');assert.deepEqual(notices,[]);
  assert.equal(calls.length,0);c.testConnection();assert(ids.modalMask.classList.contains('on'));
}
// The button gives the outcome of a test; only a failure adds a toast, and that carries the reason alone.
for(const [result,state,notice] of [[{ok:true,models:['a','b']},'ok',[]],
    [{ok:false,error:"{'message': 'Incorrect API key provided', 'type': 'invalid_request_error'}"},'failed',['Incorrect API key provided']]]){
  const s=scene();s.c.testConnection();s.ids.modalCard.querySelector('.ok').click();
  assert(s.calls.some(x=>x.startsWith('/models ')));assert.equal(s.ids.setvTest.dataset.state,'testing');
  s.setResult(result);s.tick();
  assert.equal(s.ids.setvTest.dataset.state,state);assert.equal(s.ids.setvTest.queries.span.textContent,state==='ok'?'iosConnOk':'iosConnFailed');
  assert(!s.ids.setvTest.classList.contains('spin'));assert.deepEqual(s.notices,notice);
  s.tick();assert.equal(s.ids.setvTest.dataset.state,'idle');   // the outcome clears by itself
}
// A result that arrives after another provider was opened belongs to no button on screen.
{
  const s=scene();s.c.testConnection();s.ids.modalCard.querySelector('.ok').click();
  s.c.editing={};s.ids.setvTest.classList.remove('spin');s.c.iosConnectionState('idle');   // what editProvider does on iOS
  s.setResult({ok:false,error:'HTTP 401: denied'});s.tick();
  assert.equal(s.ids.setvTest.dataset.state,'idle');assert.deepEqual(s.notices,[]);
}
{
  const s=scene();let declined=0;s.c.showIOSDataConsent(null,false,()=>declined++);
  assert(s.ids.iosConsentAgree.disabled);assert(!s.ids.iosConsentDecline.disabled);
  s.ids.iosConsentAgree.click();assert(!s.calls.some(x=>x.startsWith('/ios.consent ')));
  s.ids.iosConsentDecline.click();s.setResult({ok:true,receivers:[]});s.tick();
  assert.equal(declined,1);assert(!s.ids.modalMask.classList.contains('on'));
}
{
  const s=scene();s.c.showIOSDataConsent(null,true);assert(!s.ids.iosConsentRevoke.disabled);
  s.ids.iosConsentRevoke.click();s.setResult({ok:true,receivers:[]});s.tick();
  assert(s.calls.includes('/ios.consent {"accepted":false}'));assert(!s.ids.modalMask.classList.contains('on'));
}
{
  const s=scene();let agreed=0;s.c.showIOSDataConsent(()=>agreed++,false);
  s.setResult({ok:true,receivers:[{endpoint:'https://new.example/v1',model:'new',recipients:['Provider']}],version:'v1',providerSignature:'fresh'});s.tick();
  assert(!s.ids.iosConsentAgree.disabled);assert(s.ids.modalCard.querySelector('.pcBody').textContent.includes('Provider'));
  assert(!s.ids.modalCard.querySelector('.pcBody').textContent.includes('https://new.example/v1'));
  // Grouped disclosure retains all prior information, including optional routes and withdrawal.
  const body=s.ids.modalCard.querySelector('.pcBody');assert.equal(body.children.filter(e=>e.className==='iosDisclosureSection').length,6);
  for(const key of ['iosSharingAI','iosSharingPC','iosSharingSensors','iosSharingRetention','iosSharingChoice'])assert(body.textContent.includes(key),key);
  for(const key of ['iosRecipients','iosSharedContent','iosOptionalComputer','iosOptionalPermissions','iosDataStorage','iosDataChoice'])assert(body.textContent.includes(key),key);

  s.ids.iosConsentAgree.click();s.tick();assert.equal(agreed,1);
  const grant=s.calls.find(x=>x.startsWith('/ios.consent '));assert.equal(JSON.parse(grant.slice('/ios.consent '.length)).providerSignature,'fresh');
}
{
  const s=scene();s.c.showIOSDataConsent(null,true);
  const declared='用户配置的服务商；其下游处理方由该服务商管理';
  s.setResult({ok:true,providerIds:{'Z.ai':'a','工作模型服务':'b'},receivers:[
    {providerId:'a',endpoint:'https://a.example/secret-path',model:'model-a',recipients:[declared]},
    {providerId:'b',endpoint:'https://b.example/secret-path',model:'model-b',recipients:[declared]}]});s.tick();
  const cards=s.ids.modalCard.querySelector('.pcBody').children[0].children.slice(1);
  assert.equal(cards.length,2);
  assert(cards[0].textContent.includes('Z.ai'));assert(cards[1].textContent.includes('工作模型服务'));
  for(const card of cards){assert(card.textContent.includes(declared));assert(!/https:|secret-path|model-[ab]/.test(card.textContent))}
}
{
  const s=scene();s.c.showIOSDataConsent(null,true);s.c.gaModal({title:'Another dialog'});
  const current=s.ids.modalCard.querySelector('h4');s.setResult({ok:true,receivers:[]});s.tick();
  assert.equal(s.ids.modalCard.querySelector('h4'),current);assert.equal(current.textContent,'Another dialog');
  assert.equal(s.calls.filter(x=>x.startsWith('/jobresult ')).length,0);
}
{
  const s=scene();s.setResult({ok:true,accepted:true,pcAccepted:true,needsRefresh:true});
  s.c.submit();s.c.submit();assert.equal(s.c.inp.value,'original draft');assert.equal(s.tasks.length,0);
  assert.equal(s.calls.filter(x=>x.startsWith('/ios.consent.refresh')).length,1);
  s.setResult({ok:true,accepted:true,pcAccepted:true,needsRefresh:false});s.tick();
  assert.equal(s.c.inp.value,'');assert.deepEqual(s.tasks,['original draft']);assert(!s.ids.modalMask.classList.contains('on'));
}
{
  const s=scene();s.setResult({ok:true,accepted:true,pcAccepted:true,needsRefresh:true});s.c.submit();
  s.setResult({ok:true,accepted:false,pcAccepted:true,needsRefresh:false,receivers:[]});s.tick();
  assert(s.ids.modalMask.classList.contains('on'));assert.equal(s.c.inp.value,'original draft');
  assert.equal(s.c.pendingAtts.length,1);assert.equal(s.tasks.length,0);
  s.ids.iosConsentDecline.click();s.tick();assert.equal(s.c.inp.value,'original draft');assert.equal(s.tasks.length,0);
}
{
  const s=scene();s.setResult({ok:true,accepted:true,pcAccepted:true,needsRefresh:true});s.c.submit();
  s.c.inp.value='edited while waiting';s.setResult({ok:true,accepted:true,pcAccepted:true,needsRefresh:false});s.tick();
  assert.equal(s.c.inp.value,'edited while waiting');assert.equal(s.tasks.length,0);
  s.c.submit();assert.deepEqual(s.tasks,['edited while waiting']);
}
{
  const s=scene();s.setResult({ok:true,accepted:true,pcAccepted:true,needsRefresh:true});
  assert.equal(s.c.iosEnsureDataConsent(()=>{throw Error('PC must not wait for model disclosure')},'pc'),true);
  assert(!s.calls.includes('/ios.consent.refresh'));
  s.setResult({ok:true,accepted:true,pcAccepted:true,needsRefresh:false,receivers:[{unavailable:true}]});s.c.submit();
  assert.deepEqual(s.tasks,['original draft']);assert(!s.calls.includes('/ios.consent.refresh'));
}
{
  const s=scene();s.c.curProvider=()=>({name:'GA Plan'});
  const state={ok:true,accepted:true,pcAccepted:true,providerIds:{'GA Plan':'key-a',Other:'key-b'}};
  s.setResult({...state,needsRefresh:true,receivers:[{providerId:'key-a',needsRefresh:true}]});s.c.submit();
  s.setResult({...state,needsRefresh:false,receivers:[
    {endpoint:'https://relay.example/v1',model:'same',providerId:'key-a',unavailable:true,disclosureError:'metadata HTTP 401'},
    {endpoint:'https://relay.example/v1',model:'same',providerId:'key-b',unavailable:false,accepted:true}]});s.tick();
  assert.equal(s.c.inp.value,'original draft');assert.equal(s.tasks.length,0);
  assert(s.notices.includes('metadata HTTP 401'));assert(!s.ids.modalMask.classList.contains('on'));
  s.c.curProvider=()=>({name:'Other'});s.c.submit();assert.deepEqual(s.tasks,['original draft']);
}
{
  const s=scene();s.c.isAuto=()=>true;s.c.providers=[{name:'Primary'},{name:'Fallback'},{name:'Unused'}];
  s.c.mkMixins=[{name:'auto',members:['Primary','Fallback']}];
  const state={ok:true,accepted:true,pcAccepted:true,needsRefresh:false,
    providerIds:{Primary:'a',Fallback:'b',Unused:'c'},receivers:[{providerId:'a',unavailable:true},{providerId:'b',accepted:true},{providerId:'c',accepted:true}]};
  s.setResult(state);s.c.submit();assert.deepEqual(s.tasks,['original draft']);
  s.c.inp.value='retain when every selected member is unavailable';state.receivers[1].unavailable=true;
  s.setResult(state);s.c.submit();s.tick();assert.equal(s.tasks.length,1);assert.equal(s.c.inp.value,'retain when every selected member is unavailable');
  assert.equal(s.calls.filter(x=>x.startsWith('/ios.consent.refresh')).length,1);
  s.c.submit();s.tick();assert.equal(s.calls.filter(x=>x.startsWith('/ios.consent.refresh')).length,2);assert.equal(s.tasks.length,1);
}
for(const nextSelection of [{pid:'provider-b',model:'model-a'},{pid:'provider-a',model:'model-b'},{pid:'__auto__',model:'auto',auto:'auto'}]){
  const s=scene();s.c.active={pid:'provider-a',model:'model-a'};
  s.setResult({ok:true,accepted:true,pcAccepted:true,needsRefresh:true});s.c.submit();
  s.c.active=nextSelection;s.setResult({ok:true,accepted:true,pcAccepted:true,needsRefresh:false});s.tick();
  assert.equal(s.c.inp.value,'original draft');assert.equal(s.tasks.length,0);
  s.c.submit();assert.deepEqual(s.tasks,['original draft']);
}
// Routine conversation/model changes reuse the selected recipient's durable grant.
{
  const s=scene();s.c.curProvider=()=>({name:'Current'});
  s.setResult({ok:true,pcAccepted:true,accepted:false,needsRefresh:true,
    providerIds:{Current:'current',Unused:'unused'},receivers:[
      {providerId:'current',accepted:true,needsRefresh:false},
      {providerId:'unused',accepted:false,needsRefresh:true}]});
  for(let i=0;i<3;i++){
    s.c.curConvo={id:'new-'+i};s.c.active.model='model-'+i;s.c.inp.value='test-'+i;s.c.submit();
  }
  assert.deepEqual(s.tasks,['test-0','test-1','test-2']);
  assert(!s.calls.some(x=>x.startsWith('/ios.consent.refresh')));
  assert(!s.ids.modalMask.classList.contains('on'));
  s.c.curProvider=()=>({name:'Unused'});s.c.inp.value='preserve';s.c.submit();
  assert(s.calls.includes('/ios.consent.refresh {"providerIds":["unused"]}'));
  s.setResult({ok:true,pcAccepted:true,accepted:false,providerIds:{Unused:'unused'},
    receivers:[{providerId:'unused',accepted:false,needsRefresh:false}]});s.tick();
  assert(s.ids.modalMask.classList.contains('on'));assert.equal(s.c.inp.value,'preserve');
}
{
  const s=scene();s.setResult({ok:false});s.c.submit();
  assert.equal(s.tasks.length,0);assert.equal(s.c.inp.value,'original draft');
  assert(!s.ids.modalMask.classList.contains('on'));
}
{
  const s=scene();s.c.isAuto=()=>true;s.c.providers=[{name:'Primary'},{name:'Fallback'}];
  s.c.mkMixins=[{name:'auto',members:['Primary','Fallback']}];
  s.setResult({ok:true,pcAccepted:true,providerIds:{Primary:'a',Fallback:'b'},
    receivers:[{providerId:'a',accepted:true},{providerId:'b',accepted:false}]});s.c.submit();
  assert(s.ids.modalMask.classList.contains('on'));assert.equal(s.tasks.length,0);
}
{
  const s=scene();s.c.curProvider=()=>({name:'New'});
  s.setResult({ok:true,pcAccepted:true,providerIds:{New:'new',Unused:'unused'},receivers:[
    {providerId:'new',endpoint:'https://new.example',model:'a',accepted:false},
    {providerId:'unused',endpoint:'https://unused.example',model:'b',accepted:false}]});
  s.c.submit();assert(s.calls.includes('/ios.consent.refresh {"providerIds":["new"]}'));
  assert(!s.ids.modalCard.querySelector('.pcBody').children.some(x=>x.textContent.includes('unused.example')));
  s.setResult({ok:true,version:'v1',providerSignature:'selected',receivers:[
    {providerId:'new',endpoint:'https://new.example',model:'a',accepted:false}]});s.tick();s.ids.iosConsentAgree.click();
  const grant=JSON.parse(s.calls.find(x=>x.startsWith('/ios.consent ')).slice('/ios.consent '.length));
  assert.deepEqual(grant.providerIds,['new']);assert.equal(grant.providerSignature,'selected');
}
for(const change of [s=>s.c.curConvo={id:'other'},s=>s.c.active={pid:'other'},s=>s.c.inp.value='changed',s=>s.c.pendingAtts=[]]){
  const s=scene();let retries=0;s.setResult({ok:true,accepted:false,receivers:[]});
  s.c.iosEnsureDataConsent(()=>retries++);
  s.setResult({ok:true,version:'v1',providerSignature:'fresh',receivers:[]});s.tick();
  change(s);s.ids.iosConsentAgree.click();s.tick();
  assert(s.calls.some(x=>x.startsWith('/ios.consent ')));assert.equal(retries,0);
}
console.log('PASS: model-discovery cancellation and outcome on the test button; asynchronous disclosure; decline/revoke/closed-dialog handling; preflight preserves drafts, prompts changed routes, cancels after provider/model/Auto changes, and leaves PC/unrelated providers available.');
