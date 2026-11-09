(function(){
  'use strict';
  const words={
    zh:{v_hold:'按住说话',v_relEnd:'松开结束 · 上滑取消',v_relCancel:'松开取消',v_noSound:'没听到声音',v_noText:'没识别到内容',v_modelDownloading:'正在下载离线语音模型',v_modelReady:'离线语音已就绪',v_modelFailed:'语音模型下载失败，请重试',v_micPermission:'请允许麦克风权限后再次按住说话',v_startFailed:'无法开始录音，请重试',v_recognizing:'正在识别…',v_recFailed:'语音识别失败，请重试',v_unavailable:'当前版本不支持离线语音'},
    en:{v_hold:'Hold to talk',v_relEnd:'Release to finish · slide up to cancel',v_relCancel:'Release to cancel',v_noSound:'No sound detected',v_noText:'Nothing recognized',v_modelDownloading:'Downloading the offline voice model',v_modelReady:'Offline voice is ready',v_modelFailed:'Voice model download failed. Please retry.',v_micPermission:'Allow microphone access, then hold to talk again.',v_startFailed:'Could not start recording. Please retry.',v_recognizing:'Recognizing…',v_recFailed:'Speech recognition failed. Please retry.',v_unavailable:'Offline voice is unavailable in this version'}
  };
  if(window.I18N)for(const lang of ['zh','en'])Object.assign(I18N[lang]||{},words[lang]);
  const tr=key=>{const value=window.t&&window.t(key);return value&&value!==key?value:words.zh[key];};
  const notice=key=>{if(window.toast)window.toast(tr(key));};
  const bound=[];
  let owner=null,state='idle',run=0,session=0,timer=null,downloadTimer=null;
  let press=null,pendingStop=false,hint=null;
  const inputOf=o=>typeof o.input==='function'?o.input():typeof o.input==='string'?document.getElementById(o.input):o.input;
  const bridge=(method,...args)=>JSON.parse(GA[method](...args)||'{}');
  function setState(next){
    state=next;
    for(const o of bound){
      o.btn.classList.toggle('on',o===owner&&(next==='starting'||next==='recording'));
      o.btn.title=tr(next==='stopping'?'v_recognizing':'v_hold');
    }
  }
  function stopTimer(){clearInterval(timer);timer=null;}
  function hideHint(){if(hint)hint.style.display='none';}
  function reset(){
    run++;stopTimer();hideHint();press=null;pendingStop=false;
    const id=session;session=0;
    if(id)try{bridge('offAsrCancel',id);}catch(e){}
    setState('idle');
  }
  function append(text){
    const input=owner&&inputOf(owner);
    if(!input||!text)return;
    input.value+=(input.value&&/\S$/.test(input.value)?' ':'')+text;
    input.dispatchEvent(new Event('input',{bubbles:true}));
    if(owner.onText)owner.onText(text);
  }
  function watchResult(token){
    if(token!==run)return;
    let result;
    try{result=bridge('offAsrPoll',session);}catch(e){notice('v_recFailed');reset();return;}
    if(result.error){notice('v_recFailed');reset();return;}
    if(result.done){
      if(result.text)append(result.text);
      else notice((result.peak||0)<0.02?'v_noSound':'v_noText');
      reset();
    }
  }
  function download(){
    try{
      if(!bridge('offAsrDownload').ok){notice('v_modelFailed');return;}
      notice('v_modelDownloading');
      if(downloadTimer)return;
      downloadTimer=setInterval(()=>{
        let status;try{status=bridge('offAsrStatus');}catch(e){status={dlState:'error'};}
        if(status.dlState==='running')return;
        clearInterval(downloadTimer);downloadTimer=null;
        notice(status.modelReady?'v_modelReady':'v_modelFailed');
      },1000);
    }catch(e){notice('v_modelFailed');}
  }
  async function start(o){
    if(state!=='idle')return;
    owner=o;
    if(!(window.GA&&GA.offAsrStart&&GA.offAsrStatus)){notice('v_unavailable');return;}
    let status;try{status=bridge('offAsrStatus');}catch(e){notice('v_startFailed');return;}
    if(!status.modelReady){download();return;}
    const token=++run;setState('starting');
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    if(token!==run)return;
    let result;try{result=bridge('offAsrStart');}catch(e){result={};}
    if(!result.ok||!Number.isInteger(result.id)){
      notice(result.error==='no_mic_permission'?'v_micPermission':'v_startFailed');reset();return;
    }
    session=result.id;setState('recording');
    timer=setInterval(()=>watchResult(token),300);
    if(pendingStop)stop();
  }
  function stop(){
    if(state==='starting'){pendingStop=true;return;}
    if(state!=='recording')return;
    setState('stopping');stopTimer();
    try{bridge('offAsrStop',session);}catch(e){notice('v_recFailed');reset();return;}
    const token=run,deadline=Date.now()+20000;
    timer=setInterval(()=>{
      watchResult(token);
      if(token===run&&Date.now()>=deadline){notice('v_recFailed');reset();}
    },300);
  }
  function paintHint(){
    if(!press||!hint)return;
    hint.classList.toggle('cancel',press.cancel);
    hint.textContent=tr(press.cancel?'v_relCancel':'v_relEnd');
  }
  function showHint(){
    if(!hint){hint=document.createElement('div');hint.className='vHint';document.body.appendChild(hint);}
    hint.style.bottom=Math.max(8,innerHeight-owner.btn.getBoundingClientRect().top+12)+'px';
    hint.style.display='block';paintHint();
  }
  function down(o,event){
    if(event.button>0||press||state==='stopping')return;
    event.preventDefault();if(state!=='idle')reset();
    press={id:event.pointerId,at:Date.now(),y:event.clientY,cancel:false};
    try{o.btn.setPointerCapture(event.pointerId);}catch(e){}
    start(o);
    if(state!=='idle')showHint();
  }
  function up(event){
    if(!press||press.id!==event.pointerId)return;
    const current=press;press=null;hideHint();
    if(state==='idle')return;
    if(current.cancel||Date.now()-current.at<300){reset();return;}
    stop();
  }
  function toggle(o){
    if(!o)return;
    if(owner!==o&&state!=='idle')reset();
    if(state==='idle')start(o);else if(state==='recording'||state==='starting')stop();else reset();
  }
  function bind(button,options){
    if(!button)return null;
    const old=bound.find(o=>o.btn===button);if(old)return old;
    const o={btn:button,input:options&&options.input,onText:options&&options.onText};bound.push(o);
    button.classList.add('vHold');button.title=tr('v_hold');
    button.addEventListener('contextmenu',event=>event.preventDefault());
    button.addEventListener('pointerdown',event=>down(o,event));
    button.addEventListener('pointermove',event=>{
      if(press&&press.id===event.pointerId){press.cancel=press.y-event.clientY>60;paintHint();}
    });
    button.addEventListener('pointerup',up);
    button.addEventListener('pointercancel',()=>{if(owner===o)reset();});
    button.addEventListener('lostpointercapture',()=>{if(press&&owner===o)reset();});
    button.addEventListener('click',event=>{event.preventDefault();if(event.detail===0)toggle(o);});
    return o;
  }
  const style=document.createElement('style');
  style.textContent='.vHold{touch-action:none;user-select:none;-webkit-touch-callout:none}.vHint{position:fixed;left:50%;transform:translateX(-50%);z-index:9999;padding:8px 14px;border-radius:18px;background:#222;color:#fff;font-size:14px;white-space:nowrap;pointer-events:none}.vHint.cancel{background:#b3261e}';
  document.head.appendChild(style);
  window.GAVoice={bind,toggle,active:o=>(state==='starting'||state==='recording')&&(!o||o===owner),stop:o=>{if(!o||o===owner)reset();}};
  const main=document.getElementById('voiceBtn');
  if(main)bind(main,{input:'in',onText:()=>{window._gaVoiceIn=1;}});
  document.addEventListener('click',event=>{
    const button=event.target.closest&&event.target.closest('button,[role="button"],.btn,.cIcon');
    if(button&&!bound.some(o=>o.btn===button||o.btn.contains(button))&&state!=='idle')reset();
  },true);
  function hide(){reset();clearInterval(downloadTimer);downloadTimer=null;}
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')hide();});
  window.addEventListener('pagehide',hide);
  window.addEventListener('beforeunload',hide);
})();
