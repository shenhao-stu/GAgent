(function(){
  'use strict';
  const words={
    zh:{v_hold:'按住说话',v_relEnd:'松开结束 · 上滑取消',v_relCancel:'松开取消',v_noSound:'没听到声音',v_noText:'没识别到内容',v_modelDownloading:'正在下载离线语音模型',v_modelReady:'离线语音已就绪',v_modelFailed:'语音模型下载失败，请重试',v_micPermission:'请允许麦克风权限后再次按住说话',v_startFailed:'无法开始录音，请重试',v_recognizing:'正在识别…',v_recFailed:'语音识别失败，请重试',v_unavailable:'当前版本不支持离线语音'},
    en:{v_hold:'Hold to talk',v_relEnd:'Release to finish · slide up to cancel',v_relCancel:'Release to cancel',v_noSound:'No sound detected',v_noText:'Nothing recognized',v_modelDownloading:'Downloading the offline voice model',v_modelReady:'Offline voice is ready',v_modelFailed:'Voice model download failed. Please retry.',v_micPermission:'Allow microphone access, then hold to talk again.',v_startFailed:'Could not start recording. Please retry.',v_recognizing:'Recognizing…',v_recFailed:'Speech recognition failed. Please retry.',v_unavailable:'Offline voice is unavailable in this version'}
  };
  if(window.I18N)for(const lang of ['zh','en'])Object.assign(I18N[lang]||{},words[lang]);
  const isIOS=()=>!!(window.GA&&GA.platform==='ios');
  const tr=key=>{const value=window.t&&window.t(key);return value&&value!==key?value:(words[document.documentElement.lang==='en'?'en':'zh']||words.zh)[key];};
  const say=msg=>{if(window.toast)window.toast(msg);};
  const notice=key=>say(tr(key));
  function voiceError(code){
    const errors={
      permission_requested:['允许后请再次按住说话','After allowing access, hold again to talk'],
      microphone_denied:['请在设置中允许 GAgent 使用麦克风','Allow GAgent microphone access in Settings'],
      speech_denied:['请在设置中允许 GAgent 使用语音识别','Allow GAgent speech recognition in Settings'],
      local_speech_unavailable:['这台 iPhone 当前无法使用此语言的离线听写','On-device dictation is unavailable for this language'],
      microphone_busy:['麦克风正在使用中','The microphone is in use'],
      microphone_unavailable:['麦克风不可用，请检查音频输入','No microphone is available; check the audio input'],
      local_speech_failed:['本机听写未能完成，请检查系统听写是否可用','On-device transcription failed; check system dictation'],
      local_speech_timeout:['本机听写超时','On-device transcription timed out'],
      foreground_required:['请在 GAgent 前台按住说话','Hold to talk while GAgent is in the foreground'],
      recording_ended:['录音已中断','Recording was interrupted'],
      draft_changed:['草稿已更改，听写未覆盖输入内容','Draft changed; dictation did not overwrite your edits'],
      voice_bridge_error:['语音服务未就绪','Voice service is unavailable']
    };
    return (errors[code]||errors.voice_bridge_error)[document.documentElement.lang==='en'?1:0];
  }
  const bound=[];
  let owner=null,state='idle',run=0,session=0,timer=null,downloadTimer=null;
  let press=null,pendingStop=false,hint=null,draftEl=null,baseText='',expectedText='',curText='';
  const inputOf=o=>typeof o.input==='function'?o.input():typeof o.input==='string'?document.getElementById(o.input):o.input;
  const bridge=(method,...args)=>JSON.parse(GA[method](...args)||'{}');
  const sessionCall=method=>isIOS()?bridge(method,session||''):bridge(method,session);
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
    run++;stopTimer();hideHint();press=null;pendingStop=false;curText='';
    const id=session;session=0;
    if(id)try{isIOS()?GA.offAsrCancel(id):bridge('offAsrCancel',id);}catch(e){}
    setState('idle');
  }
  function writeTranscript(text){
    const input=owner&&inputOf(owner);
    if(!input||!text)return;
    if(isIOS()){
      if(input!==draftEl||input.value!==expectedText){say(voiceError('draft_changed'));return;}
      const sep=(baseText&&/\S$/.test(baseText))?' ':'';
      expectedText=baseText+sep+text;
      input.value=expectedText;
    }else{
      input.value+=(input.value&&/\S$/.test(input.value)?' ':'')+text;
    }
    input.dispatchEvent(new Event('input',{bubbles:true}));
    if(owner.onText)owner.onText(text);
  }
  function watchResult(token){
    if(token!==run)return;
    let result;
    try{result=sessionCall('offAsrPoll');}catch(e){isIOS()?say(voiceError('voice_bridge_error')):notice('v_recFailed');reset();return;}
    if(typeof result.text==='string'&&result.text&&result.text!==curText){
      curText=result.text;
      writeTranscript(result.text);
    }
    if(result.error){isIOS()?say(voiceError(result.error)):notice('v_recFailed');session=0;reset();return;}
    if(result.done){
      if(!curText)notice((result.peak||0)<0.02?'v_noSound':'v_noText');
      session=0;reset();
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
    if(isIOS()){
      if(!(window.GA&&GA.offAsrStart&&GA.offAsrPoll)){say(voiceError('voice_bridge_error'));return;}
    }else{
      if(!(window.GA&&GA.offAsrStart&&GA.offAsrStatus)){notice('v_unavailable');return;}
      let status;try{status=bridge('offAsrStatus');}catch(e){notice('v_startFailed');return;}
      if(!status.modelReady){download();return;}
    }
    draftEl=inputOf(owner);baseText=draftEl?(draftEl.value||''):'';expectedText=baseText;curText='';
    const token=++run;setState('starting');
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    if(token!==run)return;
    if(pendingStop){reset();return;}
    let result;try{result=isIOS()?bridge('offAsrStart',document.documentElement.lang):bridge('offAsrStart');}catch(e){result={};}
    const validId=isIOS()?!!result.id:Number.isInteger(result.id);
    if(!result.ok||!validId){
      if(isIOS())say(voiceError(result.error||'voice_bridge_error'));
      else notice(result.error==='no_mic_permission'?'v_micPermission':'v_startFailed');
      reset();return;
    }
    session=result.id;
    if(token!==run){reset();return;}
    setState('recording');
    timer=setInterval(()=>watchResult(token),300);
    if(pendingStop)stop();
  }
  function stop(){
    if(state==='starting'){pendingStop=true;return;}
    if(state!=='recording')return;
    setState('stopping');stopTimer();
    try{sessionCall('offAsrStop');}catch(e){isIOS()?say(voiceError('local_speech_failed')):notice('v_recFailed');reset();return;}
    const token=run,deadline=Date.now()+20000;
    timer=setInterval(()=>{
      watchResult(token);
      if(token===run&&Date.now()>=deadline){isIOS()?say(voiceError('local_speech_timeout')):notice('v_recFailed');reset();}
    },300);
  }
  function paintHint(){
    if(!press||!hint)return;
    hint.classList.toggle('cancel',press.cancel);
    hint.textContent=tr(press.cancel?'v_relCancel':'v_relEnd');
  }
  function showHint(){
    if(!hint){hint=document.createElement('div');hint.className='vHint';document.body.appendChild(hint);}
    hint.style.bottom=Math.max(8,(window.innerHeight||innerHeight)-owner.btn.getBoundingClientRect().top+12)+'px';
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
    if(current.cancel){reset();return;}
    if(Date.now()-current.at<300){reset();notice('v_hold');return;}
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
    button.addEventListener('pointercancel',event=>{if(owner===o&&press&&press.id===event.pointerId)reset();});
    button.addEventListener('lostpointercapture',event=>{if(owner===o&&press&&press.id===event.pointerId)reset();});
    button.addEventListener('click',event=>{event.preventDefault();if(event.detail===0)toggle(o);});
    return o;
  }
  const style=document.createElement('style');
  style.textContent='.vHold{touch-action:none;user-select:none;-webkit-touch-callout:none}.vHint{position:fixed;left:50%;transform:translateX(-50%);z-index:9999;padding:8px 14px;border-radius:18px;background:#222;color:#fff;font-size:14px;white-space:nowrap;pointer-events:none}.vHint.cancel{background:#b3261e}';
  document.head.appendChild(style);
  window.GAVoice={bind,toggle,active:o=>(state==='starting'||state==='recording')&&(!o||o===owner),stop:o=>{if(state!=='idle'&&(!o||o===owner))reset();}};
  if(document.dispatchEvent)document.dispatchEvent(new Event('ga:voice-ready'));
  const main=document.getElementById('voiceBtn');
  if(main)bind(main,{input:'in',onText:()=>{window._gaVoiceIn=1;}});
  document.addEventListener('click',event=>{
    const button=event.target&&event.target.closest&&event.target.closest('button,[role="button"],.btn,.cIcon');
    if(button&&!bound.some(o=>o.btn===button||o.btn.contains(button))){
      if(state==='recording')stop();
      else if(state!=='idle')reset();
    }
  },true);
  function hide(){reset();clearInterval(downloadTimer);downloadTimer=null;}
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')hide();});
  window.addEventListener('pagehide',hide);
  window.addEventListener('beforeunload',hide);
})();
