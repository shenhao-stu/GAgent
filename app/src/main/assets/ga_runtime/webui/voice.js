(function(){
  'use strict';
  // 流式语音输入: WebView WS 设不了 Authorization 头, 故走原生桥(GA.stt*)→Python 后端跑 StepFun Realtime WS, 边说边出字。
  // 状态机: idle -> starting -> recording -> stopping -> idle。点击在 starting/stopping 期间忽略, 杜绝重入导致的多路 AudioContext。
  // 函数式复用: 语音输入不绑死某个输入框, 谁调(bind/toggle)就把字写给谁; 内部仍是全局唯一状态机(一台麦克风/一路 STT 会话)。
  // owner={btn,input,onText}: input 可为元素/元素 id/返回元素的函数; onText(text) 可选, 语音贡献文字后回调。
  const $=id=>document.getElementById(id);
  let owner=null;                 // 当前会话归属方; 状态高亮/识别文字只作用于它
  const bound=[];                 // 已绑定的全部语音按钮(用于「点其它按钮关麦」判定时豁免彼此, 切换交给 toggle)
  if(typeof I18N!=='undefined'){Object.assign(I18N.zh,{v_needConfig:'请先在可选组件中配置流式语音识别'});Object.assign(I18N.en,{v_needConfig:'Set up streaming speech recognition in Optional modules first'})}
  const T=(k,zh)=>{try{return(window.t&&window.t(k))||zh}catch(e){return zh}};   // i18n: 复用全局 t(), 缺键兜底中文(zh-en 键已在 app.js I18N 对齐)
  const hasBridge=()=>!!(window.GA&&GA.sttStart&&GA.sttSend&&GA.sttPoll&&GA.sttStop);
  let ctx=null, src=null, proc=null, stream=null;
  let state='idle';            // idle|starting|recording|stopping
  let runId=0;                 // 每次录音唯一 id, 泄漏的 onaudioprocess 据此自杀
  let pollTimer=null, baseText='', curText='', lastLivePoll=0;
  window.__voiceDbg={frames:0,sends:0,sendOk:0,sendFail:0,maxAmp:0,lastAmp:0,lastGain:1,lastSend:'',lastErr:'',lastPoll:null,startedAt:0,state:'idle',otherButtonStop:true,version:'voice-audioworklet-dataurl-20260726'};
  function dbg(k,v){try{window.__voiceDbg[k]=v;}catch(e){}}
  // 复用 index.html 的全局 toast(): 之前误调 window.GAWebUI.toast(不存在)→ 所有语音状态/错误被静默吞掉,
  // 表现为"点了没反应"。改为优先调真实全局 toast, 任何失败路径都能给用户可见反馈。
  function toast(m){try{if(window.toast)window.toast(m);else if(window.GAWebUI&&GAWebUI.toast)GAWebUI.toast(m)}catch(e){}}
  function track(ev,p){try{if(window.GAT&&GAT.emit)GAT.emit(ev,p||{})}catch(e){}}   // 埋点: 只报时长/字符数/终态枚举, 绝不含识别文本(与 Kotlin 侧 voice_start/voice_fail 配对成漏斗)
  function vms(){try{return Date.now()-(window.__voiceDbg.startedAt||Date.now())}catch(e){return 0}}
  // 'on' 高亮仅在真正采音的 recording/starting 态; stopping 态音频已停(cleanupAudio),
  // 按钮立即灭给即时反馈, 后台静默 finalize 收尾文字, 杜绝"点停止后按钮还亮着像没反应"的延迟感.
  function paintBtn(b,s){if(!b)return;b.classList.toggle('on',s==='recording'||s==='starting');b.title=(s==='idle')?T('v_voiceInput','语音输入'):(s==='stopping')?T('v_finalizing','识别收尾中…'):T('v_stopRec','停止录音并转写');}
  function setState(s){state=s;dbg('state',s);
    bound.forEach(o=>paintBtn(o.btn,(o===owner)?s:'idle'));   // 非归属按钮一律灭, 杜绝切换归属后旧按钮残亮
    if(owner&&bound.indexOf(owner)<0)paintBtn(owner.btn,s);}
  function inputOf(o){if(!o)return null;const i=o.input;try{return typeof i==='function'?i():(typeof i==='string'?$(i):i)}catch(e){return null}}
  function render(){
    const ta=inputOf(owner); if(!ta)return;
    const sep=(baseText&&/\S$/.test(baseText)&&curText)?' ':'';
    ta.value=baseText+(curText?sep+curText:'');
    if(curText&&owner.onText){try{owner.onText(curText)}catch(e){}}
    ta.dispatchEvent(new Event('input',{bubbles:true}));
  }
  function f32toPCM16(f32){
    const out=new Int16Array(f32.length);
    for(let i=0;i<f32.length;i++){let s=Math.max(-1,Math.min(1,f32[i]));out[i]=s<0?s*0x8000:s*0x7FFF;}
    return out;
  }
  function ab64(buf){
    let bin='',bytes=new Uint8Array(buf);
    for(let i=0;i<bytes.length;i++)bin+=String.fromCharCode(bytes[i]);
    return btoa(bin);
  }
  function cleanupAudio(){
    try{proc&&(proc.onaudioprocess=null);}catch(e){}
    try{proc&&proc.port&&(proc.port.onmessage=null);}catch(e){}
    try{proc&&proc.port&&proc.port.close();}catch(e){}
    try{proc&&proc.disconnect()}catch(e){}
    try{src&&src.disconnect()}catch(e){}
    try{ctx&&ctx.close()}catch(e){}
    try{stream&&stream.getTracks().forEach(t=>t.stop())}catch(e){}
    proc=src=ctx=stream=null;
  }
  function forceStop(reason){
    // WebView/Activity 多次打开后旧页面可能进入 hidden 但仍持有麦克风与 AudioContext，
    // 继续向全局 STT bridge 喂帧会造成多路录音现场与重复转写。页面不可见/卸载时必须硬停。
    const wasActive=(state==='recording'||state==='starting'||state==='stopping');
    runId++;
    stopPoll();
    cleanupAudio();
    try{
      if(wasActive){
        if(GA.sttCancel) GA.sttCancel(); else if(GA.sttStop) GA.sttStop();
      }
    }catch(e){}
    if(wasActive)track('voice_abort',{reason:String(reason||'force').slice(0,32),ms:vms()});   // 非正常终态: 会话被打断(切后台/点其它键/卡死重置), 与 voice_done 互斥
    curText='';
    setState('idle');
    dbg('lastErr', reason||'forceStop');
  }
  function stopPoll(){ if(pollTimer){clearInterval(pollTimer);pollTimer=null;} }
  function poll(){
    let r; try{r=JSON.parse(GA.sttPoll()||'{}')}catch(e){return null;}
    dbg('lastPoll',r);
    if(typeof r.text==='string'&&r.text!==curText){curText=r.text;render();}
    if(r.error){toast(T('v_recErr','识别错误：')+r.error);}
    return r;
  }
  const WORKLET_NAME='ga-voice-pcm-worklet';
  const WORKLET_SRC='class GaVoicePcmProcessor extends AudioWorkletProcessor{constructor(o){super(o);this._buf=new Float32Array(4096);this._idx=0;}process(inputs){const input=inputs[0];const ch=input&&input[0];if(ch&&ch.length){let off=0;while(off<ch.length){const need=4096-this._idx;const take=Math.min(need,ch.length-off);this._buf.set(ch.subarray(off,off+take),this._idx);this._idx+=take;off+=take;if(this._idx>=4096){this.port.postMessage(this._buf,[this._buf.buffer]);this._buf=new Float32Array(4096);this._idx=0;}}}return true;}}registerProcessor(\'ga-voice-pcm-worklet\',GaVoicePcmProcessor);';
  async function start(o){
    if(state!=='idle')return;
    owner=o||owner;
    if(!hasBridge()){toast(T('v_noStream','当前版本不支持流式语音'));return;}
    if(!navigator.mediaDevices||!navigator.mediaDevices.getUserMedia){toast(T('v_noRec','当前 WebView 不支持录音'));return;}
    setState('starting');
    const myId=++runId;
    const ta=inputOf(owner); baseText=ta?(ta.value||''):''; curText='';
    window.__voiceDbg={frames:0,sends:0,sendOk:0,sendFail:0,maxAmp:0,lastAmp:0,lastGain:1,lastSend:'',lastErr:'',lastPoll:null,startedAt:Date.now(),state:'starting'};
    // 让浏览器先把 starting 高亮绘出来, 再跑同步阻塞的 GA.sttStart()(开 WS 网络往返会冻结 JS 线程)
    await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
    if(myId!==runId){return;}
    // 1) 后端开 WS
    let st; try{st=JSON.parse(GA.sttStart()||'{}')}catch(e){st={};}
    if(myId!==runId){return;}                         // 期间被取消
    if(!st.ok){setState('idle');
      if(st.error==='voice_not_configured'){toast(T('v_needConfig','请先在可选组件中配置流式语音识别'));if(typeof openIntegrations==='function')openIntegrations('voice');return;}
      toast(T('v_connFail','语音连接失败：')+(st.error||'unknown'));return;}
    // 2) 取麦克风
    let s2;
    try{ s2=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:false,noiseSuppression:false,autoGainControl:false}}); }
    catch(e){ try{GA.sttCancel&&GA.sttCancel();}catch(_e){} if(myId===runId)setState('idle'); toast(T('v_startFail','无法启动录音：')+(e.message||e)); return; }
    if(myId!==runId){ try{s2.getTracks().forEach(t=>t.stop())}catch(_e){} return; }   // await 期间已被停止
    try{
      stream=s2;
      const AC=window.AudioContext||window.webkitAudioContext;
      ctx=new AC({sampleRate:16000});
      try{await ctx.resume();}catch(_e){}   // Android WebView 自动播放策略: 不 resume 则采几帧后挂死
      src=ctx.createMediaStreamSource(stream);
      try{
        if(!(ctx.audioWorklet&&ctx.audioWorklet.addModule))throw new Error('no-audioworklet');
        // file:// 不透明 origin 下 blob:null 被 worklet 模块加载器拒绝(华为ALT-AL00/Chrome114 WebView 真机实测 AbortError), data: URL 可过
        await ctx.audioWorklet.addModule('data:application/javascript;charset=utf-8,'+encodeURIComponent(WORKLET_SRC));
        if(myId!==runId)return;
        const node=new AudioWorkletNode(ctx,WORKLET_NAME,{numberOfInputs:1,numberOfOutputs:1,channelCount:1,channelCountMode:'explicit',outputChannelCount:[1]});
        proc=node;
        node.port.onmessage=(ev)=>{
          if(myId!==runId){
            try{node.port.close()}catch(_e){}
            try{node.disconnect()}catch(_e){}
            return;
          }
          const f=ev.data;
          let amp=0; for(let i=0;i<f.length;i++){const a=Math.abs(f[i]); if(a>amp)amp=a;}
          const gain=(amp>0&&amp<0.08)?Math.min(20,0.08/amp):1;
          const sendBuf=(gain>1)?new Float32Array(f.length):f;
          if(gain>1){for(let i=0;i<f.length;i++){sendBuf[i]=Math.max(-1,Math.min(1,f[i]*gain));}}
          try{const d=window.__voiceDbg; d.frames++; d.lastAmp=amp; d.lastGain=gain; if(amp>d.maxAmp)d.maxAmp=amp;}catch(_e){}
          const pcm=f32toPCM16(sendBuf);
          try{
            const ret=GA.sttSend(ab64(pcm.buffer));
            try{const d=window.__voiceDbg; d.sends++; d.lastSend=ret; if(String(ret).indexOf('"ok": true')>=0)d.sendOk++; else d.sendFail++;}catch(_e){}
            const now=Date.now();
            if(now-lastLivePoll>300){ lastLivePoll=now; try{poll();}catch(_e){} }
          }catch(err){dbg('lastErr',String(err)); try{window.__voiceDbg.sendFail++;}catch(_e){}}
        };
        node.onprocessorerror=()=>{ if(myId!==runId)return; forceStop('worklet_processor_error'); toast(T('v_recErr','识别错误：')+'audio worklet crashed'); };
        src.connect(node); node.connect(ctx.destination);
        setState('recording'); toast(T('v_recording','录音中，再点一次结束'));
        stopPoll(); pollTimer=setInterval(poll,300);
      }catch(werr){
        if(myId!==runId)return;
        try{proc&&proc.port&&(proc.port.onmessage=null);}catch(_e){}
        try{proc&&proc.disconnect&&proc.disconnect()}catch(_e){}
        proc=ctx.createScriptProcessor(4096,1,1);
        proc.onaudioprocess=(e)=>{
          if(myId!==runId){ try{e.target.disconnect()}catch(_e){} return; }   // 泄漏帧自杀
          const f=e.inputBuffer.getChannelData(0);
          let amp=0; for(let i=0;i<f.length;i++){const a=Math.abs(f[i]); if(a>amp)amp=a;}
          const gain=(amp>0&&amp<0.08)?Math.min(20,0.08/amp):1;
          const sendBuf=(gain>1)?new Float32Array(f.length):f;
          if(gain>1){for(let i=0;i<f.length;i++){sendBuf[i]=Math.max(-1,Math.min(1,f[i]*gain));}}
          try{const d=window.__voiceDbg; d.frames++; d.lastAmp=amp; d.lastGain=gain; if(amp>d.maxAmp)d.maxAmp=amp;}catch(_e){}
          const pcm=f32toPCM16(sendBuf);
          try{
            const ret=GA.sttSend(ab64(pcm.buffer));
            try{const d=window.__voiceDbg; d.sends++; d.lastSend=ret; if(String(ret).indexOf('"ok": true')>=0)d.sendOk++; else d.sendFail++;}catch(_e){}
            const now=Date.now();
            if(now-lastLivePoll>300){ lastLivePoll=now; try{poll();}catch(_e){} }
          }catch(err){dbg('lastErr',String(err)); try{window.__voiceDbg.sendFail++;}catch(_e){}}
        };
        src.connect(proc); proc.connect(ctx.destination);
        setState('recording'); toast(T('v_recording','录音中，再点一次结束'));
        stopPoll(); pollTimer=setInterval(poll,300);
      }
    }catch(e){ if(myId!==runId)return; try{GA.sttCancel&&GA.sttCancel();}catch(_e){} cleanupAudio(); if(myId===runId)setState('idle'); toast(T('v_startFail','无法启动录音：')+(e.message||e)); }
  }
  function stop(){
    if(state!=='recording')return;
    setState('stopping');
    runId++;                       // 作废当前录音, 残留 onaudioprocess 自杀
    cleanupAudio();
    try{GA.sttStop();}catch(e){}
    if(!curText) toast(T('v_recognizing','识别中…'));
    let waited=0;
    stopPoll();
    pollTimer=setInterval(()=>{
      const r=poll(); waited+=300;
      if((r&&r.done)||waited>=8000){ stopPoll(); setState('idle');
        track('voice_done',{end:(r&&r.done)?'done':'timeout',chars:(curText||'').length,ms:vms()}); }   // 正常终态: 录音→收尾完成(chars=识别出字符数, 只计数不含文本)
    },300);
  }
  // 强制收尾到 idle(立即关麦+关WS+作废残帧, 不等 finalize)。点击兜底与外部 GAVoice.stop 共用。
  function reset(){const wasActive=(state!=='idle');runId++;stopPoll();cleanupAudio();try{GA.sttStop&&GA.sttStop();}catch(e){}
    if(wasActive)track('voice_abort',{reason:'ext',ms:vms()});   // 外部收麦(发送/切会话时 GAVoice.stop): 识别文字已增量落输入框, 非丢失
    setState('idle');}
  // 单一入口: 同归属方=开/停/卡死重置; 换归属方(另一个界面的语音键)=立即收掉旧会话再为新归属方开录。
  function toggle(o){
    if(!o)return;
    if(state!=='idle'&&owner&&owner!==o){reset();start(o);return;}
    if(state==='recording'){stop();}
    else if(state==='idle'){start(o);}
    else { // starting/stopping 卡死兜底: 任何点击都强制收尾到 idle, 杜绝"关不掉"
      forceStop('manual_reset'); toast(T('v_reset','已重置'));
    }
  }
  // bind(btn,{input,onText}) → 返回 owner 句柄; 同一按钮重复 bind 幂等(返回原句柄)。
  function bind(b,opts){
    if(!b)return null;
    const old=bound.find(o=>o.btn===b);if(old)return old;
    const o={btn:b,input:(opts&&opts.input)||null,onText:(opts&&opts.onText)||null};
    bound.push(o);paintBtn(b,'idle');
    b.addEventListener('click',()=>toggle(o));
    return o;
  }
  // 公开 API(不暴露内部状态机): bind/toggle 给调用方接入; stop(o) 带句柄=仅当该归属方持麦时才收(关自家视图不误伤别人)。
  window.GAVoice={
    bind:bind, toggle:toggle,
    active:(o)=>(state==='recording'||state==='starting')&&(!o||owner===o),
    stop:(o)=>{ if(state!=='idle'&&(!o||owner===o))reset(); }
  };
  const mainBtn=$('voiceBtn');
  if(mainBtn)bind(mainBtn,{input:'in',onText:()=>{window._gaVoiceIn=1;}});   // 主界面: 语音贡献过输入内容→message_sent 带 voice 标记(发送后由 app.js 清零)
  document.addEventListener('click',(ev)=>{
    const t=ev.target;
    const otherBtn=t&&t.closest&&t.closest('button,[role="button"],.btn,.cIcon');
    if(!otherBtn||bound.some(o=>o.btn===otherBtn||o.btn.contains(otherBtn)))return;   // 语音键之间的切换由 toggle 处理
    // 用户点发送/清空/设置等其它按钮时，先把麦克风关掉，避免后台继续采音。
    // 不阻止原点击事件：录音会进入 stopping 并后台收尾，用户点的按钮照常执行。
    if(state==='recording')stop();
    else if(state==='starting'||state==='stopping')forceStop('other_button');
  },true);
  document.addEventListener('visibilitychange',()=>{
    if(document.visibilityState==='hidden') forceStop('page_hidden');
  });
  window.addEventListener('pagehide',()=>forceStop('pagehide'));
  window.addEventListener('beforeunload',()=>forceStop('beforeunload'));
})();
