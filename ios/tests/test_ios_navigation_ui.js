// Pure presentation rules: device readiness belongs to native state, titles to the display layer.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const base='app/src/main/assets/ga_runtime/webui/';
const {app,extract}=require('./webui_source.cjs');
const pc=fs.readFileSync(base+'pclink.js','utf8');
const c={t:key=>key,IS_IOS:true,window:{}};vm.createContext(c);
vm.runInContext(['iosBoardPresentation','iosFinalFailed','iosTaskOutcome','iosPollStatus','iosStatusText','setStatus'].map(n=>extract(app,n)).concat(['pcDisplayTitle','pcPeerLabel'].map(n=>extract(pc,n))).join('\n'),c);
const ready={ok:true,paired:true,connected:true,consent:true,hid_ready:true,capture_source:"replaykit",screen_sharing_active:true,mirroring:false,calibrated:true,ready:true};
for(const [patch,key] of [
  [{},'iosPhoneReady'],[{connected:false},'iosPhoneReconnect'],[{connected:false,paired:false},'iosPhoneConnect'],
  [{consent:false},'iosPhoneAuthorize'],[{hid_ready:false},'iosPhoneInput'],[{stream_broken:true},'iosPhoneReady'],
  [{screen_sharing_active:false},'iosPhoneShare'],[{calibrated:false},'iosPhoneCalibrate'],[{ready:false},'iosPhoneWaiting']]){
  const result=c.iosBoardPresentation({...ready,...patch});assert.equal(result.key,key);
  assert.equal(result.tone==='ready',key==='iosPhoneReady');
}
for(const unknown of [null,{}, {ok:false,ready:true}])assert.equal(c.iosBoardPresentation(unknown).key,'iosPhoneUnknown');
for(const title of [null,'',' (empty) ','EMPTY','Untitled','undefined'])assert.equal(c.pcDisplayTitle(title),'pcUntitled');
for(const title of ['整理项目','Empty the cache','这是 (empty) 的解释','<script>'])assert.equal(c.pcDisplayTitle(title),title);
assert.equal(c.pcPeerLabel('reflect_mac_terminal-49122'),'pcTerminal');
assert.equal(c.pcPeerLabel('d.session-id'),'pcDesktop');
assert.equal(c.pcPeerLabel('My_workstation-123'),'My workstation');
for(const [raw,zh,en] of [['idle','就绪','Ready'],[' Ready ','就绪','Ready'],['running','执行中','Running'],
  ['starting','启动中','Starting'],['booting','启动中','Starting'],['loading','加载中','Loading'],
  ['done','已完成','Completed'],['completed','已完成','Completed'],['stopped','已停止','Stopped'],
  ['aborted','已中止','Stopped'],['error','出现错误','Error']]){
  assert.equal(c.iosStatusText(raw,'zh'),zh);assert.equal(c.iosStatusText(raw,'en'),en);
}
for(const raw of ['GPT-6','正在分析画面','Running model GPT-6','constructor'])assert.equal(c.iosStatusText(raw,'zh'),raw);
assert.equal(c.iosStatusText(null,'zh'),'');
let busyState=null;c.sub={textContent:'',classList:{toggle:(name,on)=>{assert.equal(name,'busy');busyState=on}}};
c.lang='zh';c.isIOSClient=()=>true;c.setStatus('idle',false);assert.equal(c.sub.textContent,'就绪');assert.equal(busyState,false);
c.lang='en';c.setStatus('running',true);assert.equal(c.sub.textContent,'Running');assert.equal(busyState,true);
c.isIOSClient=()=>false;c.setStatus('idle',false);assert.equal(c.sub.textContent,'idle');
for(const final of ['!!!Error: HTTP 402: insufficient_credits','[Error: connection reset]',
  'Partial response\n\n!!!Error: SSE interrupted','Partial response\n\n[!!! 流异常中断 TimeoutError: timed out !!!]']){
  assert.equal(c.iosFinalFailed(final),true);
  assert.equal(c.iosPollStatus({running:false,status:'完成 · 3步',final}),'iosTaskFailed');
  assert.equal(c.iosPollStatus({running:true,status:'正在执行',final}),'正在执行');
}
for(const final of ['检查完成','HTTP 402 表示余额不足','Errors are handled correctly.',
  '示例：\n```text\n!!!Error: HTTP 402\n```','用户已停止任务',null])assert.equal(c.iosFinalFailed(final),false);
assert.equal(c.iosTaskOutcome(1,'!!!Error: cancelled'),'iosTaskInterrupted');
assert.equal(c.iosTaskOutcome(2,''),'iosTaskFailed');
assert.equal(c.iosTaskOutcome(0,'Done'),'');
assert.equal(c.iosPollStatus({running:false,status:'完成 · 9步'},1),'iosTaskInterrupted');
assert.equal(c.iosPollStatus({running:true,status:'正在执行'},1),'正在执行');

// New-chat focus should request a keyboard without scrolling the entire iOS document.
for(const ios of [true,false]){
  const focus=[];
  const context={multi:false,running:false,deviceState:{devices:['paired']},chat:{innerHTML:'old conversation'},
    inp:{value:'draft',focus:options=>focus.push(options)},isIOSClient:()=>ios,modelLabel:()=>'',
    stopRun(){},exitGoalMode(){},rememberView(){},refreshDeviceChip(){},dropEmpty(){},closeDrawer(){},
    setHeaderTitle(){},syncEmpty(){},renderDrawer(){},setStatus(){},updateScrollNav(){},toast(){},t:key=>key};
  vm.createContext(context);vm.runInContext(extract(app,'newConversation'),context);context.newConversation();
  assert.equal(focus.length,1);assert.equal(focus[0]?.preventScroll,ios?true:undefined);
  assert.equal(context.inp.value,'draft');assert.equal(context.chat.innerHTML,'');
  context.running=true;context.newConversation();assert.equal(focus.length,1);
}
console.log('PASS: native readiness, readable titles/statuses, terminal outcomes, and iOS-only non-scrolling new-chat focus.');
