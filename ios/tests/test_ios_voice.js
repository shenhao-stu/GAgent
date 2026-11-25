// Exercise the shipped gesture controller, including the bridge results that arrive after a conversation changes.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('app/src/main/assets/ga_runtime/webui/voice.js','utf8');
const {EventTarget, Event} = global;
function element() {
  return Object.assign(new EventTarget(),{value:'',style:{},classList:{toggle(){},add(){}},
    getBoundingClientRect:()=>({top:100}),setPointerCapture(){},appendChild(){}});
}
function pointer(el,type,y=200) {
  el.dispatchEvent(Object.assign(new Event(type,{cancelable:true}),{button:0,pointerId:1,clientY:y}));
}
(async function(){
  let time=0, seq=0, capture=0, startError='', result={}, calls=[], messages=[];
  const intervals=new Map(), btn=element(), input=element(), pcBtn=element(), pc=element();
  const doc=Object.assign(new EventTarget(),{head:element(),body:element(),documentElement:{lang:'en'},
    createElement:element,getElementById:id=>({voiceBtn:btn,in:input})[id]});
  const ctx={document:doc,Event,Date:{now:()=>time},navigator:{},requestAnimationFrame:f=>f(),
    setTimeout:f=>f(),setInterval:f=>{const id=++seq;intervals.set(id,f);return id;},clearInterval:id=>intervals.delete(id),
    toast:m=>messages.push(m),innerHeight:800,addEventListener(){}};
  const GA={platform:'ios',offAsrStart(lang){assert.equal(lang,'en');calls.push('start');
      if(startError)return JSON.stringify({ok:false,error:startError});result={done:false};return JSON.stringify({ok:true,id:String(++capture)});},
    offAsrPoll(id){assert.equal(id,String(capture));return JSON.stringify(result);},
    offAsrStop(id){assert.equal(id,String(capture));calls.push('stop');},
    offAsrCancel(id){calls.push('cancel:'+id);},
    sttStart(){throw Error('Unexpected cloud recording');},offAsrDownload(){throw Error('Unexpected model download');}};
  ctx.window=ctx;ctx.GA=GA;vm.runInNewContext(source,ctx);
  const pcOwner=ctx.GAVoice.bind(pcBtn,{input:pc}), tick=()=>[...intervals.values()].forEach(f=>f());
  async function hold(el){pointer(el,'pointerdown');await Promise.resolve();await Promise.resolve();time+=500;}
  async function settle(){await Promise.resolve();await Promise.resolve();}
  input.value='draft'; await hold(btn);pointer(btn,'pointerup');assert.deepEqual(calls,['start','stop']);
  result={done:true,text:'dictation'};tick();assert.equal(input.value,'draft dictation');assert.equal(pc.value,'');
  pc.value='pc';await hold(pcBtn);pointer(pcBtn,'pointermove',80);pointer(pcBtn,'pointerup',80);
  assert.equal(calls.at(-1),'cancel:2');assert.equal(pc.value,'pc');assert.equal(ctx.GAVoice.active(),false);
  await hold(pcBtn);pointer(pcBtn,'pointercancel');assert.equal(calls.at(-1),'cancel:3');assert.equal(pc.value,'pc');
  await hold(pcBtn);pointer(pcBtn,'pointerup');ctx.GAVoice.stop(pcOwner);
  result={done:true,text:'wrong conversation'};pc.value='new draft';tick();assert.equal(pc.value,'new draft');
  await hold(btn);doc.visibilityState='hidden';doc.dispatchEvent(new Event('visibilitychange'));
  assert.equal(calls.at(-1),'cancel:5');result={done:true,text:'late'};tick();assert.equal(input.value,'draft dictation');
  startError='microphone_denied';await hold(btn);pointer(btn,'pointerup');assert.match(messages.at(-1),/microphone access/);
  assert.equal(ctx.GAVoice.active(),false);assert.equal(input.value,'draft dictation');
  startError='local_speech_unavailable';await hold(pcBtn);pointer(pcBtn,'pointerup');assert.match(messages.at(-1),/On-device dictation is unavailable/);
  startError='';pointer(btn,'pointerdown');pointer(btn,'pointerup');await settle();assert.equal(capture,5);
  await hold(pcBtn);pointer(pcBtn,'pointerup');pc.value='typed during recognition';result={done:true,text:'late'};tick();
  assert.equal(pc.value,'typed during recognition');assert.match(messages.at(-1),/did not overwrite/);
  await hold(pcBtn);pc.value='typed during recording';pointer(pcBtn,'pointercancel');assert.equal(pc.value,'typed during recording');
  console.log('PASS: both composers, capture ID ownership, swipe and pointer cancellation, late results, hiding, short press and explicit offline/permission errors.');
})().catch(e=>{console.error(e);process.exitCode=1;});
