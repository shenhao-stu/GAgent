/* pclink.js — 连接 PC 端 GA(hub) 的可选模块: 设置页配对 + 主界面切换 PC 会话视图.
   依赖 app.js 全局: t/I18N/applyI18n/gaModal/gaPrompt/gaConfirm/toast/md/$; py 侧 gacore/pclink.py.
   与 py 通信走 GA.send('/pclink.*') 的 job 模式(立即返回 {job} → /jobresult 轮询). */
(function(){
'use strict';
if(typeof I18N!=='undefined'){
  Object.assign(I18N.zh,{pcLink:'链接 PC 端 GA',pcLinked:'已链接 PC 端 GA',pcPairTitle:'连接电脑',
    pcPairHint:'在电脑 GA → 设置 → 手机互联 出示二维码',pcPairing:'配对中…',pcPairOk:'配对成功',pcPairFail:'配对失败: ',
    pcCodeExpired:'二维码或配对码已过期，请在电脑上刷新后重新扫描或输入',
    pcScan:'扫码连接',pcManual:'手动输入 9 位码',pcScanCancel:'已取消扫码',pcScanBad:'无法识别二维码',
    pcScanNeedPerm:'需要相机权限才能扫码',pcScanNoCam:'当前版本不支持扫码',
    pcUnpair:'解除链接',pcUnpairAsk:'解除与 PC 端 GA 的链接？',pcUnpairFail:'解除链接失败: ',pcView:'PC 会话',pcBack:'返回本机',
    pcNoPeer:'暂无 PC 会话',pcOffline:'未连接(自动重连中)',pcSend:'发送到 PC',pcAbort:'停止',pcAborted:'已发送停止',
    pcSent:'已发送',pcRunning:'运行中',grpPcLink:'PC 互联',pcNoMsgs:'还没有消息',
    pcConfigure:'请先在可选组件中填写 PC Link 中继地址与访问凭据（与电脑端 GA 使用同一中继）',
    pcOn:'已连接',pcNotPaired:'未链接',pcPairSteps:'在电脑端 GA 打开「设置 → 手机互联」出示二维码，或打开 hub /pair 页面手输 9 位数字',
    pcIdle:'空闲',pcWaiting:'会话暂不可用，等待恢复或手动切换',pcNoGet:'不可读取',pcMsgsUnit:'条消息',pcRetry:'重新检查',pcGone:'该会话已在电脑上关闭',
    pcHomeT:'还没有可用的 PC 会话',
    pcHomeP:'手机已经链接到你的电脑，但电脑上没有正在运行的 GA 会话。',
    pcPickT:'选一个 PC 会话',
    pcPickP:'电脑上有 {n} 个正在运行的 GA 会话，挑一个继续。',
    pcStep1:'在电脑上运行 hub：python hub.py',
    pcStep2:'在同一台电脑上启动 GA，它会自动接入 hub',
    pcStep3:'回到这里点「重新检查」，会话会自动出现',
    pcOfflineT:'与电脑的连接断开了',pcOfflineP:'正在自动重连。如果一直连不上, 检查电脑端 hub 是否在运行。',
    pcRenderErr:'这条消息渲染失败，将自动重试',pcNotTaken:'电脑尚未接收',
    pcPin:'置顶',pcUnpin:'取消置顶',pcArch:'归档',pcUnarch:'恢复',pcArchived:'已归档',pcCancel:'取消',pcLlm:'模型',pcLlmOk:'已切换: ',
    pcNew:'新建会话',pcPickHub:'选择电脑',pcNewComputer:'新建电脑会话',pcClose:'关闭会话',pcCloseAsk:'关闭会话并停止当前任务？',pcStarting:'正在启动…',pcNewReady:'新会话已就绪',pcSendMaybe:'已发出，等电脑确认…',
    pcDone:'PC 任务完成',pcQc:'常用指令',
    pcQcCont:'继续',pcQcProg:'现在进展如何？',pcQcShot:'截个屏给我看看',pcQcSum:'总结一下结果',
    pcBootT:'正在启动引擎…',pcBootP:'首次启动需要几秒钟，马上就好',
    pcBootFailT:'引擎启动失败',pcBootFailP:'本机引擎没有起来，PC 会话暂时不可用。可以先用本机会话，或重试。',
    pcPairHeroT:'把手机连到电脑',pcPairHeroP:'连接后可以远程查看和指挥电脑上的 GA 会话',
    pcGoLocal:'先用本机会话',
    pcToday:'今天',pcYesterday:'昨天',pcWeek:'7 天内',pcEarlier:'更早',
    pcJustNow:'刚刚',pcMinAgo:'分钟前',pcHourAgo:'小时前',pcDayAgo:'天前',pcSyncing:'同步中…',pcResend:'未送达 · 重发',pcNoMatch:'无匹配会话'});
  Object.assign(I18N.en,{pcLink:'Link PC GA',pcLinked:'PC GA linked',pcPairTitle:'Link computer',
    pcPairHint:'On PC: Settings → Link phone → show QR',pcPairing:'Pairing…',pcPairOk:'Paired',pcPairFail:'Pair failed: ',
    pcCodeExpired:'This QR or pairing code has expired. Refresh it on your computer, then scan or enter the new code.',
    pcScan:'Scan QR',pcManual:'Enter 9-digit code',pcScanCancel:'Scan cancelled',pcScanBad:'Unrecognized QR',
    pcScanNeedPerm:'Camera permission required',pcScanNoCam:'QR scan not available',
    pcUnpair:'Unlink',pcUnpairAsk:'Unlink from PC GA?',pcUnpairFail:'Unlink failed: ',pcView:'PC Sessions',pcBack:'Back to local',
    pcNoPeer:'No PC sessions',pcOffline:'Offline (reconnecting)',pcSend:'Send to PC',pcAbort:'Abort',pcAborted:'Abort sent',
    pcSent:'Sent',pcRunning:'running',grpPcLink:'PC Link',pcNoMsgs:'No messages yet',
    pcConfigure:'Configure PC Link service first: add the relay URL and access credential your computer GA uses in Optional modules',
    pcOn:'Connected',pcNotPaired:'Not linked',pcPairSteps:'On PC open Settings → Link phone for the QR, or hub /pair and type the 9 digits',
    pcIdle:'idle',pcWaiting:'Session unavailable; waiting to reconnect or switch manually',pcNoGet:'no read access',pcMsgsUnit:'msgs',pcRetry:'Re-check',pcGone:'That session was closed on the computer',
    pcHomeT:'No PC session yet',
    pcHomeP:'Your phone is linked, but no GA session is running on the computer.',
    pcPickT:'Pick a PC session',
    pcPickP:'{n} GA sessions are running on your computer — pick one to continue.',
    pcStep1:'Run the hub on your computer: python hub.py',
    pcStep2:'Start GA on the same computer; it joins the hub automatically',
    pcStep3:'Come back here and tap Re-check; the session will show up',
    pcOfflineT:'Lost connection to the PC',pcOfflineP:'Reconnecting automatically. If it never comes back, check that the hub is still running on your computer.',
    pcRenderErr:'Failed to render; will retry',pcNotTaken:'not picked up yet',
    pcPin:'Pin',pcUnpin:'Unpin',pcArch:'Archive',pcUnarch:'Restore',pcArchived:'Archived',pcCancel:'Cancel',pcLlm:'Model',pcLlmOk:'Switched: ',
    pcNew:'New session',pcPickHub:'Choose PC',pcNewComputer:'New computer session',pcClose:'Close session',pcCloseAsk:'Close this session and stop its task?',pcStarting:'Starting…',pcNewReady:'New session ready',pcSendMaybe:'Sent — waiting for the PC to confirm…',
    pcDone:'PC task finished',pcQc:'Quick commands',
    pcQcCont:'Continue',pcQcProg:'How is it going?',pcQcShot:'Show me a screenshot',pcQcSum:'Summarize the results',
    pcBootT:'Starting engine…',pcBootP:'First launch takes a few seconds',
    pcBootFailT:'Engine failed to start',pcBootFailP:'The local engine did not come up, so PC sessions are unavailable. Use local chat for now, or retry.',
    pcPairHeroT:'Link your phone to a computer',pcPairHeroP:'Once linked, you can watch and drive the GA sessions running on your PC',
    pcGoLocal:'Use local chat for now',
    pcToday:'Today',pcYesterday:'Yesterday',pcWeek:'Past 7 days',pcEarlier:'Earlier',
    pcJustNow:'just now',pcMinAgo:'min ago',pcHourAgo:'hr ago',pcDayAgo:'d ago',pcSyncing:'Syncing…',pcResend:'Not delivered · Resend',pcNoMatch:'No matching sessions'});
}
const IS_IOS=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios');
if(IS_IOS){
  Object.assign(I18N.zh,{pcView:'电脑',pcLink:'电脑互联',pcLinked:'电脑互联',pcSend:'给电脑一个任务…',pcOffline:'正在重连',
    pcUntitled:'新会话',pcTerminal:'终端会话',pcDesktop:'桌面会话',pcStartTitle:'有什么可以帮你？',
    pcStartHint:'交给电脑执行，随时查看进展。',pcStartLabel:'电脑任务',pcStartFoot:'点选建议可编辑，发送后开始执行',pcStartSessions:'电脑会话',pcStartSessionsHint:'查看与切换会话',
    pcStarter1:'整理当前项目',pcStarterPrompt1:'查看当前工作目录，概括项目结构和主要文件。先不要修改文件。',
    pcStarter2:'帮我查一个问题',pcStarterPrompt2:'帮我调研一个问题。先问清楚我要了解的主题和范围，再开始查找。',
    pcStarter3:'检查运行状态',pcStarterPrompt3:'检查当前任务和运行环境的状态，指出需要我处理的问题，先不要修改配置。',
    pcStarter4:'整理文件',pcStarterPrompt4:'帮我整理文件。先确认目录和整理规则，给出方案，等我确认后再移动或重命名文件。',
    pcHomeT:'准备好连接电脑',pcHomeP:'连接已经建立。在电脑上打开一个 GA 会话，它就会出现在这里。',
    pcStep1:'在电脑上打开 GA，并保持手机互联服务运行',pcStep2:'新建一个会话，或打开之前的任务',pcStep3:'回到这里选择会话，继续工作',
    pcOfflineP:'正在自动重连。请确认电脑已开机，GA 和手机互联服务正在运行。',
    pcPairHeroT:'让电脑接着做',pcPairHeroP:'连接电脑上的 GAgent，随时查看进展、继续任务。',pcGoLocal:'返回助手'});
  Object.assign(I18N.en,{pcView:'Computer',pcLink:'Computer connection',pcLinked:'Computer connection',pcSend:'Give your computer a task…',pcOffline:'Reconnecting',
    pcUntitled:'New conversation',pcTerminal:'Terminal session',pcDesktop:'Desktop session',pcStartTitle:'What can I help with?',
    pcStartHint:'Work on your computer. Follow along here.',pcStartLabel:'COMPUTER TASKS',pcStartFoot:'Choose an idea to edit, then send to start',pcStartSessions:'Computer sessions',pcStartSessionsHint:'View and switch conversations',
    pcStarter1:'Explore a project',pcStarterPrompt1:'Inspect the working directory and summarize the project structure and key files. Do not modify files.',
    pcStarter2:'Research a question',pcStarterPrompt2:'Help research a question. First ask me about the topic and scope before searching.',
    pcStarter3:'Check the current status',pcStarterPrompt3:'Check the current task and environment, and identify anything needing my attention. Do not change configuration.',
    pcStarter4:'Organize files',pcStarterPrompt4:'Help organize files. First confirm the directory and rules, propose a plan, and wait for my approval before moving or renaming files.',
    pcHomeT:'Ready to connect',pcHomeP:'The connection is established. Open a GA session on your computer to see it here.',
    pcStep1:'Open GA on your computer and keep phone linking running',pcStep2:'Create a session or open an existing task',pcStep3:'Choose the session here to continue',
    pcOfflineP:'Reconnecting automatically. Check that your computer, GA and phone linking service are running.',
    pcPairHeroT:'Let your computer take over',pcPairHeroP:'Connect to GAgent on your computer to follow progress and continue tasks.',pcGoLocal:'Back to Assistant'});
}
/* ---- 桥: /pclink.* 全部走 job 轮询(配对/网络可 30s+, 不能阻塞 WebView) ---- */
function call(cmd,onResult,maxTries,alive){
  let resp;try{resp=JSON.parse(GA.send(cmd)||'{}')}catch(e){return onResult({ok:0,error:'bridge'})}
  if(!resp.job)return onResult(resp);
  let tries=0,delay=IS_IOS?80:400;const lim=maxTries||120,deadline=Date.now()+lim*400;
  const tick=()=>{if(alive&&!alive())return;
    let j;try{j=JSON.parse(GA.send('/jobresult '+resp.job)||'{}')}catch(e){return onResult({ok:0,error:'bridge'})}
    if(j.pending){if(IS_IOS?Date.now()>=deadline:++tries>lim)return onResult({ok:0,error:'timeout'});
      setTimeout(tick,delay);if(IS_IOS)delay=delay===80?180:400;return}
    let r;try{r=JSON.parse(j.result||'{}')}catch(e){r={ok:0,error:'parse'}}
    onResult(r)};
  setTimeout(tick,IS_IOS?40:300)}
function api(method,path,body,onResult,alive){
  call('/pclink.api '+method+' '+path+(body?' '+JSON.stringify(body):''),onResult,0,alive)}
let creatingPC=false;
function pcCreateError(r){
  const en=lang==='en';
  if([404,405,501].includes(r.status))return en?'Update the PC Link service on your computer.':'请更新电脑上的 PC Link 服务。';
  if(r.status===400)return en?'The computer rejected this request. Check the PC Link service version.':'电脑拒绝了请求，请检查两端 PC Link 版本。';
  return r.error||t('pcOffline');
}
function createPCSession(body){
  if(creatingPC)return;
  const viewGen=selectionGen,view=document.getElementById('pcView');
  if(!view?.classList.contains('on'))return;
  const alive=()=>viewGen===selectionGen&&view.classList.contains('on');
  if(IS_IOS&&!iosEnsureDataConsent(()=>{if(alive())createPCSession(body)},'pc'))return;
  creatingPC=true;updatePcSend();
  const buttons=[view.querySelector('#pcNewBtn'),view.querySelector('#pcSideNew')].filter(Boolean);
  buttons.forEach(b=>b.disabled=true);
  const finish=()=>{creatingPC=false;buttons.forEach(b=>b.disabled=false);updatePcSend()};
  const post=payload=>api('POST','/api/sessions',payload,r=>{
    finish();if(!alive())return;
    if(r.error){
      if([404,405,501].includes(r.status)){
        const legacy=lastPs.find(p=>isNew(p)&&(p.hub||'')===(payload.hub||''));
        if(legacy){view.classList.remove('side');selPeer(legacy.name);return}
      }
      return toast(pcCreateError(r));
    }
    if(!r.name)return toast(pcCreateError({status:501}));
    view.classList.remove('side');knownNames.add(r.name);selPeer(r.name);
  });
  if(body)return post(body);
  api('GET','/api/hubs',null,hs=>{
    if(!alive()){finish();return}
    if(Array.isArray(hs)){
      if(hs.length===1)return post({hub:hs[0]});
      finish();if(!hs.length)return toast(t('pcOffline'));
      return hubSheet(hs,hub=>{if(alive())createPCSession({hub})});
    }
    if(hs?.error&&![404,403,405,501].includes(hs.status)){finish();return toast(pcCreateError(hs))}
    post({});
  });
}
function track(ev,p){try{if(typeof GAT!=='undefined'&&GAT.emit)GAT.emit(ev,p||{})}catch(e){}}
/* ---- 状态 ---- */
let paired=false,connected=false,timer=null,curPeer=null,lastSig=null;
let offlineSince=0;
let idleRounds=0;
let tok=0;
let sigAge=0;
let pendingPut=null;
let runSeen={};
let putBusy=false;
let lastPut=null;
let pendingEcho=null;
let runT0={};
let bgTimer=null,tickTimer=null;
let offSince=0;
let newWatch=null;
let knownNames=new Set();
let archOpen=false;
let sideDayKey='';
let configError='';
let pairedKnown=false;
let bootWaited=false;
let statusWait=0;
const isNew=p=>{const n=typeof p==='string'?p:(p&&p.name||'');return /^d\.new(?:-\d+)?(?:@[^@]+)?$/.test(n)};
const PCWIDE=()=>{try{return matchMedia('(min-width:900px)').matches}catch(e){return false}};
function pcDisplayTitle(title){
  const value=String(title||'').trim();
  return value&&!/^(\(empty\)|empty|untitled|null|undefined)$/i.test(value)?value:t('pcUntitled');
}
function pcPeerLabel(peer){
  if(/^reflect_.*terminal(?:-|$)/i.test(peer))return t('pcTerminal');
  if(/^d\./.test(peer))return t('pcDesktop');
  return String(peer||'').replace(/-\d+$/,'').replace(/_/g,' ');
}
function renderStartConversation(box){
  if(box.querySelector('.pcStart'))return;
  box.innerHTML='';const card=document.createElement('section');card.className='pcEmpty pcStart';
  card.innerHTML='<div class="heroCore"><h2></h2><p></p><div class="pcStarterList"></div><button type="button" class="iosPhoneCard iosComputerCard"><span class="iosPhoneGlyph" aria-hidden="true">'+SVG_PC+'</span><span class="iosPhoneCopy"><b></b><span></span></span><span class="iosPhoneArrow" aria-hidden="true">›</span></button></div>';
  card.querySelector('h2').textContent=t('pcStartTitle');card.querySelector('p').textContent=t('pcStartHint');
  const sessions=card.querySelector('.iosComputerCard');sessions.querySelector('b').textContent=t('pcStartSessions');sessions.querySelector('.iosPhoneCopy>span').textContent=t('pcStartSessionsHint');
  sessions.onclick=()=>document.getElementById('pcView').classList.add('side');
  [1,2,3,4].forEach(i=>{const b=document.createElement('button');b.type='button';b.className='heroChip';b.innerHTML=_heroIcon(['folder','search','shot','folder'][i-1])+'<span class="cv"></span>';b.querySelector('span').textContent=t('pcStarter'+i);
    b.onclick=()=>{const input=document.getElementById('pcIn');input.value=t('pcStarterPrompt'+i);input.dispatchEvent(new Event('input'));input.focus()};card.querySelector('.pcStarterList').appendChild(b)});
  box.appendChild(card);
}

const LP_KEY='pclink.lastPeer';
const isAgent=p=>!!p&&(p.caps||[]).indexOf('get')>=0;
const hasPid=n=>/-\d+(@[^@]*)?$/.test(String(n||''));
const noHub=n=>String(n||'').replace(/@[^@]*$/,'');
const baseOf=n=>/^phone-\d+(?:@[^@]+)?$/.test(String(n||''))?String(n):String(n||'').replace(/-\d+(?=(@[^@]*)?$)/,'');
let lpCache=null;
function lastPeerSaved(){
  const u=typeof _authUid==='function'?_authUid():null;
  if(!lpCache||lpCache.uid!==u)lpCache={uid:u,val:LS.get(LP_KEY,null)||{}};
  return lpCache.val}
function pickPeer(ps){
  const ios=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios');
  const ag=(ps||[]).filter(isAgent);if(!ag.length)return null;
  if(curPeer&&ag.some(p=>p.name===curPeer))return curPeer;
  const cand=ios?ag.filter(p=>!isNew(p)):ag;
  if(!cand.length)return null;
  if(cand.length===1)return cand[0].name;
  const sv=lastPeerSaved();
  if(sv.name&&cand.some(p=>p.name===sv.name))return sv.name;
  if(sv.name&&hasPid(sv.name)){
    const b=baseOf(sv.name),c=cand.filter(p=>hasPid(p.name)&&(baseOf(p.name)===b||noHub(baseOf(p.name))===b));
    if(c.length===1)return c[0].name}
  return null}
function rememberPeer(name){
  if(!name||(lpCache&&lpCache.val&&lpCache.val.name===name))return;
  lpCache={uid:typeof _authUid==='function'?_authUid():null,val:{name:name}};
  try{LS.set(LP_KEY,{name:name})}catch(e){}}
const PM_KEY='pclink.peerMeta';
let pmCache=null;
function peerMeta(){
  const u=typeof _authUid==='function'?_authUid():null;
  if(!pmCache||pmCache.uid!==u)pmCache={uid:u,val:LS.get(PM_KEY,null)||{}};
  return pmCache.val}
function metaOf(name,m=peerMeta()){return m[baseOf(name)]||m[noHub(baseOf(name))]||{}}
function orderPeers(ps){
  const meta=peerMeta();
  return ps.sort((a,b)=>(Number(isNew(b))-Number(isNew(a)))
    ||(Number(!!metaOf(b.name,meta).pin)-Number(!!metaOf(a.name,meta).pin))
    ||((b.ts||0)-(a.ts||0)));
}
function setMeta(name,patch){
  const all=peerMeta(),k=baseOf(name),cur=Object.assign({},all[k]||{},patch);
  if(!cur.pin)delete cur.pin;if(!cur.arch)delete cur.arch;
  if(Object.keys(cur).length)all[k]=cur;else delete all[k];
  try{LS.set(PM_KEY,all)}catch(e){}}
const IC_PIN='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1z"/></svg>';
const IC_PIN_OFF='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 17v5"/><path d="M15 9.34V7h1a2 2 0 0 0 0-4H7.89"/><path d="m2 2 20 20"/><path d="M9 9v1.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h11"/></svg>';
const IC_ARCH='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/></svg>';
const IC_RESTORE='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="m9 15 3-3 3 3"/><path d="M12 18v-6"/></svg>';
const IC_MORE='<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="12" cy="19" r="1.8"/></svg>';
const IC_CHEV='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>';
function rowSheet(p){
  const ios=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios');
  const old=document.getElementById('pcSheetWrap');if(old)old.remove();
  const m=metaOf(p.name),w=document.createElement('div');w.id='pcSheetWrap';
  const it=(cls,ico,txt)=>'<button type="button" class="pcSheetIt'+(cls?' '+cls:'')+'">'
    +'<span class="pcShIco">'+ico+'</span><span class="pcShTxt">'+txt+'</span></button>';
  w.innerHTML='<div id="pcSheetMask"></div><div class="pcSheet" role="menu">'
    +'<div class="pcSheetGrip" aria-hidden="true"></div>'
    +'<div class="pcSheetHead"><div class="pcSheetTt"></div><div class="pcSheetSub"></div></div>'
    +(m.arch?it('',IC_RESTORE,t('pcUnarch'))
            :it('',m.pin?IC_PIN_OFF:IC_PIN,t(m.pin?'pcUnpin':'pcPin'))+it('warn',IC_ARCH,t('pcArch')))
    +((p.caps||[]).includes('llm')?'<div class="pcSheetLlm"><div class="pcSheetSub">'+t('pcLlm')+'</div></div>':'')
    +'<button type="button" class="pcSheetCancel">'+t('pcCancel')+'</button></div>';
  w.querySelector('.pcSheetTt').textContent=ios?pcDisplayTitle(p.title):(p.title||p.name);
  w.querySelector('.pcSheetSub').textContent=(ios?pcPeerLabel(p.name):p.name)+(p.n_msgs?(' · '+p.n_msgs+' '+t('pcMsgsUnit')):'');
  document.body.appendChild(w);
  const close=()=>{if(w.classList.contains('out'))return;w.classList.add('out');setTimeout(()=>w.remove(),160)};
  w._close=close;
  w.querySelector('#pcSheetMask').onclick=close;
  w.querySelector('.pcSheetCancel').onclick=close;
  const btns=w.querySelectorAll('.pcSheetIt');
  if(m.arch){btns[0].onclick=()=>{setMeta(p.name,{arch:0});close();track('pclink_meta',{op:'unarch'});pollNow()}}
  else{
    btns[0].onclick=()=>{setMeta(p.name,{pin:m.pin?0:1});close();track('pclink_meta',{op:m.pin?'unpin':'pin'});pollNow()};
    btns[1].onclick=()=>{setMeta(p.name,{arch:1,pin:0});close();track('pclink_meta',{op:'arch'});
      if(p.name===curPeer)setPeer(null);
      pollNow()}}
  if(/^phone-\d+(@[^@]*)?$/.test(p.name)){const b=document.createElement('button');b.className='pcSheetIt warn';b.textContent=t('pcClose');w.querySelector('.pcSheetCancel').before(b);
    b.onclick=()=>gaConfirm(t('pcClose'),t('pcCloseAsk'),()=>api('POST','/api/'+encodeURIComponent(p.name)+'/put',{text:'/exit'},r=>{if(r.error)return toast(r.error);close();if(curPeer===p.name)setPeer(null);pollNow()}),true)}
  const lb=w.querySelector('.pcSheetLlm');if(!lb)return;
  api('GET','/api/'+encodeURIComponent(p.name)+'/llms',null,r=>{if(!r||!r.items||!lb.isConnected)return;
    r.items.forEach((nm,i)=>{const b=document.createElement('button');b.type='button';b.className='pcSheetIt';
      b.innerHTML='<span class="pcShIco">'+(i===r.cur?'●':'○')+'</span><span class="pcShTxt"></span>';b.querySelector('.pcShTxt').textContent=nm;
      b.onclick=()=>api('POST','/api/'+encodeURIComponent(p.name)+'/llm',{no:i},q=>{close();track('pclink_llm',{ok:!(q&&q.error)});
        q&&q.error?toast(''+q.error):toast(t('pcLlmOk')+nm);pollNow()});
      lb.appendChild(b)})})}
function hubSheet(hs,go){
  const old=document.getElementById('pcSheetWrap');if(old)old.remove();
  const w=document.createElement('div');w.id='pcSheetWrap';
  w.innerHTML='<div id="pcSheetMask"></div><div class="pcSheet" role="menu"><div class="pcSheetGrip" aria-hidden="true"></div>'
    +'<div class="pcSheetHead"><div class="pcSheetTt"></div></div><button type="button" class="pcSheetCancel">'+t('pcCancel')+'</button></div>';
  w.querySelector('.pcSheetTt').textContent=t('pcPickHub');
  let picked=false;const close=()=>{if(w.classList.contains('out'))return;w.classList.add('out');setTimeout(()=>w.remove(),160)},cc=w.querySelector('.pcSheetCancel');
  w._close=close;w.querySelector('#pcSheetMask').onclick=cc.onclick=close;
  hs.forEach(h=>{const b=document.createElement('button');b.type='button';b.className='pcSheetIt';b.textContent=h;b.onclick=()=>{if(picked)return;picked=true;close();go(h)};cc.before(b)});
  document.body.appendChild(w)}
function bindLongPress(d,getPeer){
  let tm=null,fired=false;
  const cancel=()=>{if(tm){clearTimeout(tm);tm=null}};
  const fire=()=>{cancel();if(fired)return;fired=true;
    const p=getPeer();if(p&&!isNew(p))rowSheet(p)};
  d.addEventListener('contextmenu',e=>{e.preventDefault();fire()});
  d.addEventListener('touchstart',()=>{fired=false;tm=setTimeout(fire,550)},{passive:true});
  d.addEventListener('touchmove',cancel,{passive:true});
  d.addEventListener('touchend',e=>{cancel();if(fired){e.preventDefault()}},{passive:false});
  d.addEventListener('touchcancel',cancel,{passive:true})}
let lastPs=[];
let segTxt={};
let taskSnap=[];
let peerRun=false;
let selectionGen=0;
let gen=0;
function refreshStatus(cb,resume){call(resume?'/pclink.resume':'/pclink.status',r=>{
  configError=!r||!r.ok?String(r&&r.error||'PC Link status unavailable'):(r.configured===false?t('pcConfigure'):'');
  paired=!!(r&&r.paired);connected=!!(r&&r.connected);
  if(r&&!r.error)pairedKnown=true;
  if(!IS_IOS||pairedKnown)renderRow();
  showFab();
  if(document.getElementById('pcHdSub')&&!(IS_IOS&&!pairedKnown))setPcHd(undefined,curPeer||'',peerRun);
  cb&&cb(r)})}
function renderRow(){
  const home=document.getElementById('homePanel');if(!home)return;
  let sec=document.getElementById('pcLinkSec');
  if(!document.getElementById('pcLinkRow')){sec=document.createElement('div');sec.id='pcLinkSec';
    sec.innerHTML='<div class="secLbl"><span data-i18n="grpPcLink"></span></div><div class="card icoCard">'+
      '<button class="row rowBtn" id="pcLinkRow"><span class="rowIco ic-blue">'+
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>'+
      '</span><span class="k" id="pcLinkK"></span><span class="v"><span id="pcLinkV" class="vMut"></span>'+
      '<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg></span></button></div>';
    const ganetSec=document.getElementById('ganetHomeSec');
    if(ganetSec)home.insertBefore(sec,ganetSec);else home.appendChild(sec);applyI18n();
    document.getElementById('pcLinkRow').onclick=onRowTap}
  const card=IS_IOS&&document.getElementById('iosConnectionCard');
  if(card){const row=document.getElementById('pcLinkRow');if(row.parentElement!==card)card.insertBefore(row,document.getElementById('iosBoardSetup')?.nextSibling||null);if(sec)sec.remove()}
  document.getElementById('pcLinkK').textContent=t(paired?'pcLinked':'pcLink');
  const v=document.getElementById('pcLinkV');
  const key=paired?(connected?'pcOn':'pcOffline'):'pcNotPaired';
  v.textContent=configError||t(key);v.className=paired&&connected?'a11yValOn':(paired?'a11yValOff':'vMut')}
function parsePairPayload(raw){
  raw=String(raw||'').trim();
  const m=raw.match(/^ga-pclink:v1:(\d{9})$/i);
  if(m)return m[1];
  const digits=raw.replace(/[\s-]/g,'');
  return /^\d{9}$/.test(digits)?digits:null}
function doPair(code,via){
  const ios=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios');
  if(ios&&!iosEnsureDataConsent(()=>doPair(code,via),'pc'))return;
  toast(t('pcPairing'));
  call('/pclink.pair '+code,r=>{
    if(r&&r.ok){if(typeof configError!=='undefined')configError='';paired=connected=true;if(typeof pairedKnown!=='undefined')pairedKnown=true;renderRow();showFab();
      if(ios)pollNow();
      if(typeof document!=='undefined'&&typeof armBg==='function'){const v=document.getElementById('pcView');if(!v||!v.classList.contains('on'))armBg()}
      track('pclink_pair',{ok:true,via:via||'?'});toast(t('pcPairOk'))}
    else{const e=String((r&&r.error)||'?');track('pclink_pair',{ok:false,err:e.slice(0,40)});
      const msg=/short-code server rejected request:\s*410\b/.test(e)?t('pcCodeExpired'):e.split('(')[0].slice(0,60);
      toast(t('pcPairFail')+msg)}})}
function startScan(){
  if(typeof configError!=='undefined'&&configError){toast(configError);if(typeof openIntegrations==='function')openIntegrations('pclink');return}
  if(typeof GA==='undefined'||!GA.scanQr){toast(t('pcScanNoCam'));return}
  window.gaQrResult=function(text){
    try{delete window.gaQrResult}catch(e){window.gaQrResult=undefined}
    if(!text){toast(t('pcScanCancel'));return}
    const code=parsePairPayload(text);
    if(!code){toast(t('pcScanBad'));return}
    doPair(code,'qr')};
  let r='err';try{r=GA.scanQr()}catch(e){r='err'}
  if(r==='need-perm')toast(t('pcScanNeedPerm'));
  else if(r==='no-camera'||(r&&String(r).indexOf('err')===0)){
    delete window.gaQrResult;
    toast(r==='no-camera'?t('pcScanNoCam'):t('pcPairFail')+r)}}
function openManualPair(){
  if(typeof configError!=='undefined'&&configError){toast(configError);if(typeof openIntegrations==='function')openIntegrations('pclink');return}
  gaModal({title:t('pcManual'),msg:t('pcPairSteps'),input:t('pcPairHint'),value:'',onOk:v=>{
    const code=parsePairPayload(v);
    if(!code)return toast(t('pcPairFail')+'9?');
    doPair(code,'manual')}})}
function onRowTap(){
  const ios=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios');
  if(typeof configError!=='undefined'&&configError){toast(configError);if(typeof openIntegrations==='function')openIntegrations('pclink');return}
  if(paired){gaConfirm(t('pcUnpair'),t('pcUnpairAsk'),()=>call('/pclink.unpair',r=>{
    if(!r||!r.ok){toast(t('pcUnpairFail')+String((r&&r.error)||'?').split('(')[0].slice(0,60));return}
    paired=connected=false;if(ios&&typeof disarmBg==='function')disarmBg();renderRow();showFab();track('pclink_unpair');toast(t('pcUnpair'))}),true);return}
  if(ios&&!iosEnsureDataConsent(onRowTap,'pc'))return;
  gaModal({title:t('pcPairTitle'),msg:t('pcPairHint'),okText:t('pcScan'),cancelText:t('pcManual'),
    onOk:()=>startScan(),onCancel:()=>openManualPair()})}
const SVG_PC='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>';
const SVG_PHONE='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="7" y="2" width="10" height="20" rx="2.5"/><line x1="11" y1="18.5" x2="13" y2="18.5"/></svg>';
const LOCKUP='<div class="pcLink2" aria-hidden="true"><span class="pcLinkTile pcLinkGa">GA</span>'+
  '<span class="pcLinkWire"></span><span class="pcLinkTile pcLinkPc">'+SVG_PC+'</span></div>';
function showFab(){
  try{localStorage.setItem('ga.pcPaired',paired?'1':'0')}catch(e){}
  let b=document.getElementById('pcFab');
  const visible=paired||IS_IOS;
  document.body.classList.toggle('pcHubFabOn',visible);
  if(!visible){if(b)b.remove();return}
  if(!b){b=document.createElement('button');b.id='pcFab';b.setAttribute('aria-label','PC');
    b.innerHTML='<span class="fi fiPc" aria-hidden="true">'+SVG_PC+(IS_IOS?'<span data-i18n="iosComputer">'+t('iosComputer')+'</span>':'')+'</span><span class="fi fiPh" aria-hidden="true">'+SVG_PHONE+(IS_IOS?'<span data-i18n="iosThisPhone">'+t('iosThisPhone')+'</span>':'')+'</span>';
    b.onclick=()=>{const v=document.getElementById('pcView');if(v&&v.classList.contains('on'))closeView();else openView()};
    if(IS_IOS){b.setAttribute('data-i18n-aria','iosSwitchComputer');document.getElementById('hdr').insertBefore(b,document.getElementById('hdrMoreBtn'))}
    else document.body.appendChild(b);
    syncFab()}}
function syncFab(){
  const v=document.getElementById('pcView');if(!v)return;
  const on=v.classList.contains('on'),side=v.classList.contains('side');
  const mb=v.querySelector('#pcMenuBtn');if(mb)mb.setAttribute('aria-expanded',String(side));
  const b=document.getElementById('pcFab');if(!b)return;
  b.classList.toggle('rc',on);b.classList.toggle('hid',!PCWIDE()&&side);
  b.setAttribute('aria-label',IS_IOS?t('iosSwitchComputer'):(on?t('pcBack'):'PC'))}
function edgeFx(kind){if(IS_IOS)return;
  let f=document.getElementById('pcEdgeFx');
  if(!f){f=document.createElement('div');f.id='pcEdgeFx';document.body.appendChild(f)}
  f.className='';void f.offsetWidth;f.className=kind}
let pcVoice=null;
function bindPCVoice(){
  const button=document.getElementById('pcVoiceBtn');if(!button)return;
  pcVoice=window.GAVoice?.bind(button,{input:()=>document.getElementById('pcIn')})||null;
  button.hidden=peerRun||!pcVoice;
}
document.addEventListener('ga:voice-ready',bindPCVoice);
function ensureView(){
  let v=document.getElementById('pcView');if(v)return v;
  v=document.createElement('div');v.id='pcView';if(IS_IOS)v.classList.add('pcNoConversation');
  v.innerHTML='<div class="pcHd"><button class="iconbtn" id="pcMenuBtn" data-i18n-aria="pcView" aria-label="PC 会话" aria-expanded="false" aria-controls="pcSide">'+
      '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg></button>'+
      '<div class="pcHdMid"><span class="gaLogo" aria-hidden="true">GA</span>'+
      '<span class="pcHdCol"><b id="pcHdTitle" data-i18n="pcView">PC</b><span id="pcHdSub" class="pcHdSub" aria-live="polite"></span></span></div>'+
      '<span class="pcHdSp"></span><button class="iconbtn" id="pcNewBtn" data-i18n-aria="pcNew"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg></button></div>'+
    '<div class="pcBodyWrap"><div id="pcScrim"></div><div id="pcSide"></div><div id="pcMain"><div id="pcMsgs"></div>'+
      '<button id="pcDown" hidden aria-label="scroll to bottom"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg></button>'+
      '<button id="pcUp" hidden aria-label="scroll to top"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 15 12 9 18 15"/></svg></button>'+
      '<div id="pcInBar"><div id="pcChips" role="toolbar" data-i18n-aria="pcQc" aria-label="常用指令">'+
      ['pcQcCont','pcQcProg','pcQcShot','pcQcSum'].map(function(k){return '<button class="pcChip" data-i18n="'+k+'" data-track="pc_qc_'+k.slice(4).toLowerCase()+'"></button>'}).join('')+
      '</div><div class="cap" id="pcCap"><textarea id="pcIn" rows="1" data-i18n-ph="pcSend" data-i18n-aria="pcSend" aria-label="send"></textarea>'+
      '<div class="captools"><span class="sp"></span><button class="cIcon vBtn" id="pcVoiceBtn" aria-label="语音输入"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/></svg></button><button id="pcBtn" aria-label="send">'+
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="6 11 12 5 18 11"/></svg></button></div></div></div></div></div>';
  document.body.appendChild(v);
  applyI18n();
  if(IS_IOS){const create=v.querySelector('#pcNewBtn');create.classList.add('iosNewConversation');create.setAttribute('data-i18n-aria','pcNewComputer');create.setAttribute('aria-label',t('pcNewComputer'));create.title=t('pcNewComputer');
    create.innerHTML=IOS_COMPOSE_ICON;
    const local=document.createElement('button');local.id='pcLocalBtn';local.type='button';local.setAttribute('data-i18n-aria','iosSwitchPhone');local.setAttribute('aria-label',t('iosSwitchPhone'));
    local.innerHTML=SVG_PHONE+'<span data-i18n="iosThisPhone">'+t('iosThisPhone')+'</span>';local.onclick=()=>closeView();create.before(local);}
  v.querySelector('#pcNewBtn').onclick=IS_IOS?()=>createPCSession():e=>{const b=e.currentTarget;b.disabled=true;
    const go=hub=>{b.disabled=true;api('POST','/api/sessions',hub?{hub}:{},r=>{b.disabled=false;if(r.error)return toast(r.error);toast(t('pcStarting'));pollNow()})};
    api('GET','/api/hubs',null,hs=>{b.disabled=false;if(!Array.isArray(hs)){if(hs&&hs.error&&hs.status!==404&&hs.status!==403)return toast(hs.error);return go()}if(hs.length===1)return go(hs[0]);if(!hs.length)return toast(t('pcOffline'));hubSheet(hs,go)})};
  const _ta=v.querySelector('#pcIn');
  _ta.addEventListener('input',()=>{_ta.style.height='auto';_ta.style.height=Math.max(24,Math.min(_ta.scrollHeight,120))+'px';updatePcSend()});
  v.querySelector('#pcMenuBtn').onclick=()=>{closeSwipe();v.classList.toggle('side')};
  v.querySelector('#pcScrim').onclick=()=>{closeSwipe();v.classList.remove('side')};
  try{const mq=matchMedia('(min-width:900px)');const onMq=()=>{if(mq.matches)v.classList.remove('side')};
    mq.addEventListener?mq.addEventListener('change',onMq):mq.addListener(onMq);onMq()}catch(e){}
  v.querySelector('#pcBtn').onclick=()=>{if(peerRun)doAbort();else doPut()};
  bindPCVoice();
  if(IS_IOS&&window.IOSPCModels){
    const model=document.createElement('button');model.type='button';model.id='pcModelBtn';
    v.querySelector('#pcCap .captools').prepend(model);
    IOSPCModels.bind(model,{
      current:()=>({peer:curPeer,version:selectionGen,connected,running:peerRun}),
      request:api,changed:()=>pollNow()
    });
  }
  const box=v.querySelector('#pcMsgs');
  box.addEventListener('click',e=>{
    const c=e.target&&e.target.closest?e.target.closest('.step'):null;if(!c||c._pcGot||c.dataset.pcj==null)return;
    const tb=c.closest('.task');if(!tb||tb.dataset.pci==null)return;
    const i=tb.dataset.pci,j=c.dataset.pcj,p=curPeer;c._pcGot=1;
    const fill=txt=>{c._text=txt;const sb=c.querySelector('.sb');if(sb)sb._rendered=false;try{renderBody(c)}catch(e2){}};
    const n=+(c.dataset.pcn||0);
    fetchSeg(i,j,n,p,gen,ok=>{if(p!==curPeer)return;const got=segTxt[i+'/'+j];if(ok&&got)fill(got.txt);else c._pcGot=0})},true);
  new MutationObserver(syncFab).observe(v,{attributes:true,attributeFilter:['class']});
  const dn=v.querySelector('#pcDown');
  box._pcStick=true;box._pcPinSeq=0;box._pcUserScroll=false;let pcUserTimer=0;
  const nearBottom=()=>box.scrollHeight-box.scrollTop-box.clientHeight<=4;
  const userIntent=()=>{box._pcUserScroll=true;box._pcPinSeq++;clearTimeout(pcUserTimer);pcUserTimer=setTimeout(()=>{box._pcUserScroll=false},240)};
  box.addEventListener('wheel',userIntent,{passive:true});
  if(IS_IOS)box.addEventListener('click',e=>{
    if(e.target.closest&&e.target.closest('.cbcopy'))return;
    const pre=e.target.closest&&e.target.closest('pre.ga-card--code');if(!pre)return;
    if(!pre.classList.contains('open'))pre.classList.add('open');
    else if(e.target.closest('.cbhead'))pre.classList.remove('open')});
  let tchY0=0;box.addEventListener('touchstart',e=>{tchY0=e.touches[0].clientY},{passive:true});
  box.addEventListener('touchmove',e=>{userIntent();
    if(IS_IOS&&Math.abs(e.touches[0].clientY-tchY0)>8){const a=document.activeElement;if(a&&a.id==='pcIn')a.blur()}},{passive:true});
  box.addEventListener('keydown',e=>{if(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(e.key))userIntent()});
  box.addEventListener('pointerdown',e=>{const r=box.getBoundingClientRect();if(e.clientX>=r.right-20)userIntent()},{passive:true});
  const up=v.querySelector('#pcUp');
  if(IS_IOS){const nav=document.createElement('div');nav.id='pcNav';
    dn.parentElement.insertBefore(nav,dn);nav.appendChild(up);nav.appendChild(dn);
    v.querySelector('#pcMain').insertAdjacentHTML('afterbegin',
      '<div class="pcChatHead" id="pcChatHead" hidden><button type="button" class="pcLastMsg" id="pcLastMsg">'+
      '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>'+
      '<span id="pcLmText"></span></button></div>');
    v.querySelector('#pcLastMsg').onclick=()=>{const hd=document.getElementById('pcChatHead'),b=document.getElementById('pcMsgs');
      const cur=hd&&hd._cur;if(!b||!cur||!cur.isConnected)return;
      b._pcStick=false;b._pcPinSeq++;pcAlignTop(b,cur);reqPcHead();
      track('pclink_nav',{op:'jump_cur_q'})}}
  let lastTop=0,upIntent=false;
  box.addEventListener('scroll',()=>{
    const fromBottom=box.scrollHeight-box.scrollTop-box.clientHeight;
    if(box.scrollTop<lastTop-24&&fromBottom>150)upIntent=true;
    else if(box.scrollTop>lastTop+1)upIntent=false;
    lastTop=box.scrollTop;
    if(box._pcUserScroll){box._pcStick=nearBottom();
      if(box._pcStick){box.style.setProperty('--pcTail','0px');box.scrollTop=box.scrollHeight;clearUnread()}
      clearTimeout(pcUserTimer);pcUserTimer=setTimeout(()=>{box._pcUserScroll=false},240)}
    pcSyncDown(box);scheduleVisible();
    up.hidden=!(box.scrollHeight-box.clientHeight>600&&box.scrollTop>=400&&(!IS_IOS||upIntent));
    reqPcHead()});
  window.addEventListener('resize',scheduleVisible);
  if(IS_IOS&&window.ResizeObserver)new ResizeObserver(()=>{
    if(box._pcStick&&!box._pcUserScroll&&!box.querySelector('.pcStart'))box.scrollTop=box.scrollHeight;
    pcSyncDown(box);scheduleVisible();
  }).observe(box);
  dn.onclick=()=>{box._pcStick=true;box._pcPinSeq++;box.style.setProperty('--pcTail','0px');box.scrollTop=box.scrollHeight};
  dn.addEventListener('click',()=>{if(typeof clearUnread==='function')clearUnread()});
  up.onclick=()=>{box._pcStick=false;box._pcPinSeq++;box.scrollTop=0};
  const chips=v.querySelector('#pcChips');
  if(chips)chips.addEventListener('click',e=>{const b=e.target&&e.target.closest?e.target.closest('.pcChip'):null;if(!b)return;
    _ta.value=b.textContent||'';_ta.dispatchEvent(new Event('input'));_ta.focus()});
  try{const bar=v.querySelector('#pcInBar');
    const setH=()=>{try{document.documentElement.style.setProperty('--pcBarH',Math.round(bar.getBoundingClientRect().height)+'px')}catch(e){}};
    if(window.ResizeObserver)new ResizeObserver(setH).observe(bar);
    setH()}catch(e){}
  return v}
function bgPoll(){
  api('GET','/api/peers','',ps=>{
    const fb=document.getElementById('pcFab'),ok=Array.isArray(ps)&&!ps.error;
    if(fb)fb.classList.toggle('bgRun',ok&&ps.some(pr=>pr.run&&!isNew(pr)&&isAgent(pr)));
    if(ok)ps.forEach(pr=>{const was=runSeen[pr.name];runSeen[pr.name]=!!pr.run;
      if(pr.run&&!runT0[pr.name])runT0[pr.name]=Date.now();
      if(!pr.run)delete runT0[pr.name];
      if(was!==true||pr.run||isNew(pr)||!isAgent(pr)||metaOf(pr.name).arch)return;
      try{if(window.GA&&GA.notify)GA.notify(t('pcDone'),baseOf(pr.name))}catch(e){}})})}
let bgFirst=null;
function armBg(){if(!IS_IOS||bgTimer||!paired)return;bgTimer=setInterval(bgPoll,30000);bgFirst=setTimeout(()=>{bgFirst=null;bgPoll()},180)}
function disarmBg(){clearTimeout(bgFirst);bgFirst=null;if(bgTimer){clearInterval(bgTimer);bgTimer=null}
  const fb=document.getElementById('pcFab');if(fb)fb.classList.remove('bgRun')}
function openView(){
  const ios=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios'),from=arguments[0];
  const v=ensureView();if(ios&&v.classList.contains('on'))return;
  if(ios)iosPrepareModal();v.classList.add('on');v.classList.remove('side');
  track('view_enter',{view:'pclink',from:from||'user'});
  edgeFx('in');
  if(ios){disarmBg();offSince=0;
    if(!tickTimer)tickTimer=setInterval(()=>{if(peerRun)setPcHd(undefined,curPeer||'',peerRun)},1000)}
  lastSig=null;idleRounds=0;
  const box=document.getElementById('pcMsgs');if(box&&!box.firstElementChild)skel(box);
  const side=document.getElementById('pcSide');if(side&&!side.querySelector('.pcRow'))skelSide(side);
  if(ios){clearTimeout(timer);timer=setTimeout(()=>{timer=null;if(v.classList.contains('on')){refreshStatus(null,true);pollNow()}},iosReducedMotion()?0:180)}
  else{refreshStatus(null,true);pollNow()}}
function closeView(){
  const ios=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios');
  const v=document.getElementById('pcView');if(!v||!v.classList.contains('on'))return;
  if(ios)iosPrepareModal();
  v.classList.remove('on','side');
  if(ios)window.IOSPCModels?.close();
  if(window.GAVoice&&pcVoice)GAVoice.stop(pcVoice);
  edgeFx('out');
  if(ios){if(tickTimer){clearInterval(tickTimer);tickTimer=null}armBg();selectionGen++}
  gen++;tok++;
  const box=document.getElementById('pcMsgs');if(box)box._pcPinSeq=(box._pcPinSeq||0)+1;
  newWatch=null;
  if(timer){clearTimeout(timer);timer=null}}
function setPcHd(title,peer,run){
  const ios=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios');
  const b=document.getElementById('pcHdTitle'),s=document.getElementById('pcHdSub');
  if(b&&title!==undefined){b.textContent=ios?pcDisplayTitle(title):(title||peer||t('pcView'));if(ios)b.title=peer||'';}
  if(!s)return;
  if(connected)offlineSince=0;else if(!offlineSince)offlineSince=Date.now();
  const st=connected?(run?t('pcRunning'):t('pcOn')):((ios||Date.now()-offlineSince>=10000)?t('pcOffline'):'');
  let txt=ios?[pcPeerLabel(peer),st].filter(Boolean).join(' · '):(peer?(peer+(st?' · '+st:'')):st);
  if(ios&&run&&connected){const t0=runT0[peer];
    if(t0){const sec=Math.max(0,Math.floor((Date.now()-t0)/1000));txt+=' · '+String(Math.floor(sec/60)).padStart(2,'0')+':'+String(sec%60).padStart(2,'0')}}
  if(ios)s.setAttribute('aria-live',run?'off':'polite');
  if(s.textContent!==txt)s.textContent=txt;
  s.classList.toggle('busy',connected&&!!run)}
function setRunBtn(run){peerRun=!!run;
  const vb=document.getElementById('pcVoiceBtn');
  if(vb){vb.hidden=peerRun||!pcVoice;if(peerRun&&window.GAVoice&&pcVoice)GAVoice.stop(pcVoice)}
  const b=document.getElementById('pcBtn');if(!b)return;
  b.classList.toggle('stop',peerRun);b.setAttribute('aria-label',t(peerRun?'pcAbort':'pcSend'));
  b.innerHTML=peerRun?'<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>'
    :'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="6 11 12 5 18 11"/></svg>';
  updatePcSend()}
function doPut(){
  const ios=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios'),txt0=arguments[0];
  if(window.GAVoice){if(typeof pcVoice!=='undefined'&&pcVoice)window.GAVoice.stop(pcVoice);else window.GAVoice.stop()}
  const ta=document.getElementById('pcIn');const txt=(txt0||ta.value||'').trim();if(!txt||!curPeer||putBusy||(ios&&creatingPC))return;
  const peer=curPeer,viewGen=typeof selectionGen!=='undefined'?selectionGen:0,toNew=isNew(peer),before=typeof knownNames!=='undefined'?new Set(knownNames):new Set();
  if(ios&&!iosEnsureDataConsent(()=>{if(viewGen===selectionGen&&peer===curPeer&&(txt0||ta.value.trim()===txt))doPut(txt0)},'pc'))return;
  const key=(lastPut&&lastPut.text===txt&&lastPut.peer===curPeer)?lastPut.key
    :('ik'+Date.now().toString(36)+Math.random().toString(36).slice(2,8));
  lastPut={key:key,text:txt,peer:curPeer};
  putBusy=true;const btn=document.getElementById('pcBtn');if(btn)btn.classList.add('busy');
  api('POST','/api/'+encodeURIComponent(curPeer)+'/put',{text:txt,ikey:key},r=>{
    putBusy=false;if(btn)btn.classList.remove('busy');
    if((typeof selectionGen!=='undefined'&&viewGen!==selectionGen)||peer!==curPeer)return;
    const err=r&&r.error?String(r.error):'';
    if(err&&!(toNew&&/timeout|busy \(>/i.test(err))){
      track('pclink_send',{ok:false,kind:'put',err:err.slice(0,40)});
      if(ios&&!toNew){pendingEcho={peer:curPeer,text:txt,fail:true};
        const bx=document.getElementById('pcMsgs');if(bx){const e0=bx.querySelector('.pcEmpty');if(e0)e0.remove();syncEcho(bx,curPeer)}}
      return toast(err)}
    track('pclink_send',{ok:!err,kind:'put',maybe:!!err});
    if(!err)lastPut=null;
    if(toNew){
      newWatch={names:before,hub:peer.includes('@')?peer.split('@').pop():null,rounds:0,text:txt};
      if(!err&&ta.value.trim()===txt){ta.value='';ta.style.height='auto';if(ios)updatePcSend()}
      toast(t(err?'pcSendMaybe':'pcSent'))}
    else{
      pendingPut={n:taskSnap.length,ts:Date.now(),rounds:0};
      if(ios&&!err){pendingEcho={peer:curPeer,text:txt};
        const bx=document.getElementById('pcMsgs');if(bx){const e0=bx.querySelector('.pcEmpty');if(e0)e0.remove();syncEcho(bx,curPeer);
          bx._pcStick=false;bx._pcPinSeq++;
          const ew=bx.querySelector('.pcEchoW');
          if(ew){ew.style.marginBottom=Math.max(0,bx.clientHeight-72)+'px';
            pcAlignTop(bx,ew)}}}
      if(!txt0&&ta.value.trim()===txt){ta.value='';ta.style.height='auto';if(ios)updatePcSend()}
      toast(t('pcSent'))}
    pollNow()})}
function doAbort(){if(curPeer)api('POST','/api/'+encodeURIComponent(curPeer)+'/abort',{},r=>{track('pclink_send',{ok:!(r&&r.error),kind:'abort'});
  r&&r.error?toast(''+r.error):toast(t('pcAborted'))})}
function nextDelay(){
  if(peerRun)return 1500;
  return Math.min(curPeer?6000:20000,1200*Math.pow(2,Math.max(0,idleRounds-1)))}
function arm(){if(timer)clearTimeout(timer);const v=document.getElementById('pcView');if(!v||!v.classList.contains('on'))return;timer=setTimeout(poll,nextDelay())}
function guard(fn,done){try{fn()}catch(e){console.error('[pclink]',e);done()}}
function poll(){
  if(IS_IOS&&document.hidden)return;
  if(IS_IOS&&document.getElementById('setv')?.classList.contains('on')){if(timer)clearTimeout(timer);timer=setTimeout(poll,1000);return}
  const my=++tok;
  if(timer){clearTimeout(timer);timer=null}
  round(()=>{if(my===tok)arm()})}
function pollNow(){idleRounds=0;sigAge=0;poll()}
let offN=0;
function round(done){
  const ios=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios');
  const my=tok,alive=()=>my===tok;
  if(ios){
    const es=engineState();
    if(es==='boot'){bootWaited=true;statusWait=0;renderBooting();idleRounds=0;return done()}
    if(es==='err'){renderEngineFail();idleRounds++;return done()}
    if(bootWaited){bootWaited=false;refreshStatus()}
    if(!pairedKnown){
      if(++statusWait>8){renderEngineFail();idleRounds++;return done()}
      if(statusWait%3===0)refreshStatus();
      renderBooting();idleRounds=0;return done()}
    statusWait=0;
    if(!paired){renderUnpaired();idleRounds++;return done()}
    setHeroMode(false);
  }
  api('GET','/api/peers','',ps=>guard(()=>{
    if(!ps||ps.error||!Array.isArray(ps)){
      const box0=document.getElementById('pcMsgs');
      if(ios&&box0&&box0.querySelector&&box0.querySelector('.pcTask')){
        if(!offSince)offSince=Date.now();
        const grace=Date.now()-offSince<10000;
        const s0=document.getElementById('pcHdSub');
        if(grace){if(s0&&s0.textContent!==t('pcSyncing')){s0.textContent=t('pcSyncing');s0.classList.remove('busy')}}
        else{connected=false;renderRow();setRunBtn(false);setPcHd(undefined,curPeer||'',false);idleRounds++}
        return done()}
      if(++offN<2){idleRounds++;return done()}
      connected=false;idleRounds++;renderRow();setRunBtn(false);
      setPcHd(undefined,curPeer||'',false);renderOffline();return done()}
    if(ios)offSince=0;
    offN=0;
    if(!connected){connected=true;renderRow()}
    if(ios){
      ps=ps.filter(isAgent);
      setMsgsOff(false);
      ps.forEach(pr=>{const was=runSeen[pr.name];runSeen[pr.name]=!!pr.run;
        if(pr.run&&!runT0[pr.name])runT0[pr.name]=Date.now();
        if(!pr.run)delete runT0[pr.name];
        if(was!==true||pr.run||isNew(pr)||!isAgent(pr)||metaOf(pr.name).arch)return;
        if(pr.name===curPeer&&!document.hidden)return;
        try{if(window.GA&&GA.notify)GA.notify(t('pcDone'),baseOf(pr.name))}catch(e){}});
    }
    // Preserve selected chat across incomplete peer lists (d255e7d).
    const meta=typeof peerMeta==='function'?peerMeta():undefined;
    if(typeof orderPeers==='function'&&typeof peerMeta==='function')orderPeers(ps);
    else ps.sort((a,b)=>((isNew(b)?1:0)-(isNew(a)?1:0))||((metaOf(b.name).pin?1:0)-(metaOf(a.name).pin?1:0))||((b.ts||0)-(a.ts||0)));
    if(newWatch){
      const cand=ps.filter(p=>isAgent(p)&&!isNew(p)&&!newWatch.names.has(p.name)&&!metaOf(p.name,meta).arch&&(!newWatch.hub||p.hub===newWatch.hub));
      if(cand.length){
        cand.sort((a,b)=>(b.ts||0)-(a.ts||0));
        const nm=cand[0].name,sent=newWatch.text;newWatch=null;lastPut=null;
        const ta=document.getElementById('pcIn');
        if(ta&&ta.value&&ta.value.trim()===sent){ta.value='';ta.style.height='auto';if(ios)updatePcSend()}
        knownNames=new Set(ps.map(p=>p.name));
        toast(t('pcNewReady'));
        if(!curPeer||isNew(curPeer)){selPeer(nm);return done()}
      }
      else if(++newWatch.rounds>12){newWatch=null;lastPut=null}}
    knownNames=new Set(ps.map(p=>p.name));
    const vis=ps.filter(p=>!metaOf(p.name).arch);
    const pick=curPeer||pickPeer(vis);
    if(!(ios&&creatingPC)&&pick&&pick!==curPeer)setPeer(pick);
    renderSide(ps);
    if(!curPeer){idleRounds++;renderHome(vis);return done()}
    if(!ps.some(p=>p.name===curPeer)){
      idleRounds++;setRunBtn(false);
      const sub=document.getElementById('pcHdSub');if(sub)sub.textContent=(ios?pcPeerLabel(curPeer):curPeer)+' · '+t('pcWaiting');
      return done()}
    pullMsgs(done,0,alive)},done),alive)}
function setPeer(name){
  const ios=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios');
  if(ios&&name!==curPeer&&pcVoice&&window.GAVoice)GAVoice.stop(pcVoice);
  curPeer=name||null;if(ios)selectionGen++;gen++;lastSig=null;sigAge=0;segTxt={};taskSnap=[];idleRounds=0;pendingPut=null;
  if(ios){pendingEcho=null;clearUnread()}
  const b=document.getElementById('pcMsgs');if(b){
    b._pcPinSeq=(b._pcPinSeq||0)+1;
    b._pcStick=true;b._pcUserScroll=false;b.style.setProperty('--pcTail','0px');
    if(name)skel(b)}}
function sideHost(){
  const el=document.getElementById('pcSide');if(!el)return null;
  if(!IS_IOS)return el;
  let lst=el.querySelector('#pcSideList');
  if(!lst){
    el.innerHTML='<div class="dwSearch" id="pcSearch"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>'+
        '<input id="pcSearchIn" type="search" data-i18n-ph="searchConvo" placeholder="搜索会话" autocomplete="off"></div>'+
      '<button type="button" class="dwNew" id="pcSideNew" data-track="pc_side_new">'+
        '<svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>'+
        '<span data-i18n="newChat">新对话</span></button>'+
      '<div id="pcSideList"></div>'+
      '<div class="dwUserBar" id="pcSideBar">'+
        '<button type="button" class="dwUser" id="pcSideUser" data-i18n-aria="settings" aria-label="设置" data-track="pc_side_user">'+
          '<span class="userAvatar" id="pcDwAvatar" aria-hidden="true"></span>'+
          '<span class="dwUserName" id="pcDwUserName">我</span></button>'+
        '<button type="button" class="dwIcon" id="pcSideLang" data-i18n-aria="language" aria-label="语言 / Language">'+
          '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 8 6 6"/><path d="m4 14 6-6 2-3"/><path d="M2 5h12"/><path d="M7 2h1"/><path d="m22 22-5-10-5 10"/><path d="M14 18h6"/></svg></button>'+
        '<button type="button" class="dwIcon" id="pcSideSet" data-i18n-aria="settings" aria-label="设置" data-track="pc_side_settings">'+
          '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.01a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg></button></div>';
    iosSidebarChrome(el,'pcView',()=>{closeSwipe();document.getElementById('pcView').classList.remove('side')},()=>PCWIDE()||document.getElementById('pcView').classList.contains('side'),document.getElementById('pcView'));
    el.querySelector('#pcSideNew').onclick=()=>createPCSession();
    el.querySelector('#pcSideLang').onclick=()=>toggleLang();
    el.querySelector('#pcSideSet').onclick=()=>openSettings();
    el.querySelector('#pcSideUser').onclick=()=>openSettings();
    el.querySelector('#pcSearchIn').oninput=function(){pcQ=(this.value||'').trim().toLowerCase();renderSide(lastPs||[])};
    el.querySelector('#pcSearchIn').addEventListener('focus',pyLoad,{once:true});
    lst=el.querySelector('#pcSideList');
    lst.addEventListener('touchstart',e=>{const r=e.target.closest?e.target.closest('.pcRow'):null;
      swX0=e.touches[0].clientX;swY0=e.touches[0].clientY;swDrag=0;
      swRow=r;
      if(swipeOpen&&r!==swipeOpen)closeSwipe()},{passive:true});
    lst.addEventListener('touchmove',e=>{if(!swRow)return;
      if(!swRow.isConnected){swRow=null;swDrag=0;return}
      const dx=e.touches[0].clientX-swX0,dy=e.touches[0].clientY-swY0;
      if(!swDrag){if(Math.abs(dx)<12||Math.abs(dx)<Math.abs(dy)*1.2)return;swDrag=1;swRow.style.transition='none';
        const a0=document.getElementById('pcSwipeAct');if(a0)a0.hidden=true}
      const base=swRow===swipeOpen?-128:0;
      swRow.style.transform='translateX('+Math.max(-128,Math.min(0,dx+base))+'px)'},{passive:true});
    lst.addEventListener('touchend',e=>{if(!swRow)return;
      if(swDrag){e.preventDefault();
        const dx=e.changedTouches[0].clientX-swX0,x=dx+(swRow===swipeOpen?-128:0);
        swRow.style.transition='transform .18s';
        if(x<-64){swRow.style.transform='translateX(-128px)';swipeOpen=swRow;openSwipeAct(swRow)}
        else{swRow.style.transform='';if(swipeOpen===swRow)swipeOpen=null}}
      swRow=null;swDrag=0},{passive:false});
    lst.addEventListener('scroll',closeSwipe,{passive:true});
    applyI18n();
    refreshAvatarRow()}
  return lst}
let pcQ='',swipeOpen=null,swX0=0,swY0=0,swRow=null,swDrag=0;
let PY=null;
function pyEnsure(){if(PY)return true;if(!window.GA_PY_RAW)return false;PY={};
  window.GA_PY_RAW.split(';').forEach(seg=>{const i=seg.indexOf(':'),p=seg.slice(0,i),cs=seg.slice(i+1);for(const ch of cs)PY[ch]=p});
  return true}
function pyLoad(){if(window.GA_PY_RAW||document.getElementById('pyTable'))return;
  const s=document.createElement('script');s.id='pyTable';s.src='assets/pinyin.js';
  s.onload=()=>{if(pcQ)renderSide(lastPs||[])};document.head.appendChild(s)}
function pyOf(text){let full='',abbr='';for(const ch of text){const p=PY?PY[ch]:null;
  if(p){full+=p;abbr+=p[0]}else{full+=ch;abbr+=ch}}return{full:full,abbr:abbr}}
function ed1(a,b){
  if(a===b)return true;const d=a.length-b.length;if(d<-1||d>1)return false;
  if(d!==0){if(d<0){const t=a;a=b;b=t}
    let i=0;while(i<b.length&&a[i]===b[i])i++;
    return a.slice(i+1)===b.slice(i)}
  let diff=0;for(let i=0;i<a.length;i++)if(a[i]!==b[i]&&++diff>1)return false;return true}
function fuzzyScore(q,text){
  const tl=(text||'').toLowerCase(),idx=tl.indexOf(q);
  if(idx>=0)return 100+(idx===0?10:Math.max(0,8-idx));
  if(!pyEnsure())return 0;
  const tp=pyOf(tl);
  if(tp.full.indexOf(q)>=0)return 80;
  if(tp.abbr.indexOf(q)>=0)return 60;
  if(/[^\x00-\x7f]/.test(q)){const qf=pyOf(q).full;if(qf&&tp.full.indexOf(qf)>=0)return 40}
  if(q.length>=3&&/^[a-z0-9]+$/.test(q)){const f=tp.full;
    for(let i=0;i+q.length-1<=f.length;i++){
      if(ed1(q,f.slice(i,i+q.length))||ed1(q,f.slice(i,i+q.length+1)))return 20}}
  return 0}
function closeSwipe(){const a=document.getElementById('pcSwipeAct');if(a)a.hidden=true;
  if(swipeOpen){swipeOpen.style.transition='transform .18s';swipeOpen.style.transform='';swipeOpen=null}}
function openSwipeAct(row){
  let a=document.getElementById('pcSwipeAct');
  if(!a){a=document.createElement('div');a.id='pcSwipeAct';
    a.innerHTML='<button type="button" class="swPin"></button><button type="button" class="swArch"></button>';
    document.body.appendChild(a)}
  const p=(lastPs||[]).find(x=>x.name===row.dataset.peer);if(!p)return closeSwipe();
  const m=metaOf(p.name),bp=a.querySelector('.swPin'),ba=a.querySelector('.swArch');
  bp.textContent=t(m.pin?'pcUnpin':'pcPin');ba.textContent=t(m.arch?'pcUnarch':'pcArch');
  bp.onclick=()=>{setMeta(p.name,{pin:m.pin?0:1});closeSwipe();track('pclink_meta',{op:m.pin?'unpin':'pin',via:'swipe'});pollNow()};
  ba.onclick=()=>{setMeta(p.name,{arch:m.arch?0:1,pin:0});closeSwipe();track('pclink_meta',{op:m.arch?'unarch':'arch',via:'swipe'});pollNow()};
  const rc=row.getBoundingClientRect();
  a.style.top=rc.top+'px';a.style.height=rc.height+'px';a.hidden=false}
function sideRow(p){
  const d=document.createElement('button');d.type='button';d.dataset.peer=p.name;d.className='dwItem rowBtn pcRow';
  const st=document.createElement('span');st.className='cst';st.appendChild(document.createElement('i'));d.appendChild(st);
  const mid=document.createElement('span');mid.className='pcRowMid';
  const tl=document.createElement('span');tl.className='pcRowTt';
  const pin=document.createElement('span');pin.className='pcPinIc';pin.setAttribute('aria-hidden','true');pin.innerHTML=IC_PIN;tl.appendChild(pin);
  const tt=document.createElement('span');tt.className='t';tl.appendChild(tt);mid.appendChild(tl);
  const sb=document.createElement('span');sb.className='pcRowSub';mid.appendChild(sb);d.appendChild(mid);
  const more=document.createElement('span');more.className='pcRowMore';more.setAttribute('role','button');
  more.setAttribute('tabindex','0');more.setAttribute('aria-label','\u22ef');more.innerHTML=IC_MORE;
  more.onclick=e=>{e.stopPropagation();const pp=d._peer;if(pp&&!isNew(pp))rowSheet(pp)};
  d.appendChild(more);
  d.onclick=()=>{if(d.getAttribute('aria-disabled'))return;
    selPeer(d.dataset.peer);if(!PCWIDE())document.getElementById('pcView').classList.remove('side')};
  bindLongPress(d,()=>d._peer);
  return d}
function relTime(ts){
  if(!ts)return '';const ms=ts<1e12?ts*1000:ts,d=Date.now()-ms;
  if(d<60000)return t('pcJustNow');
  const m=Math.floor(d/60000);if(m<60)return m+' '+t('pcMinAgo');
  const h=Math.floor(m/60);if(h<24)return h+' '+t('pcHourAgo');
  const dd=Math.floor(h/24);if(dd<7)return dd+' '+t('pcDayAgo');
  try{return new Date(ms).toLocaleDateString()}catch(e){return ''}}
function updatePcSend(){
  if(!IS_IOS)return;const b=document.getElementById('pcBtn'),ta=document.getElementById('pcIn');
  window.IOSPCModels?.update();
  if(b&&ta){b.disabled=creatingPC&&!peerRun;b.classList.toggle('idleOff',!peerRun&&(!ta.value.trim()||creatingPC))}}
function markUnread(){
  if(!IS_IOS)return;const box=document.getElementById('pcMsgs'),dn=document.getElementById('pcDown');
  if(box&&dn&&box._pcStick===false){dn.classList.add('unread');dn.hidden=false}}
function clearUnread(){const dn=document.getElementById('pcDown');if(dn)dn.classList.remove('unread')}
function sideSync(d,p,meta=peerMeta()){
  d._peer=p;
  const usable=isAgent(p),m=metaOf(p.name,meta);
  d.className='dwItem rowBtn pcRow'+(p.name===curPeer?' cur':'')+(usable?'':' off')
    +(m.arch?' arch':'')+(m.pin&&!m.arch?' pin':'')+(isNew(p)?' new':'');
  if(p.name===curPeer)d.setAttribute('aria-current','true');else d.removeAttribute('aria-current');
  if(usable)d.removeAttribute('aria-disabled');else d.setAttribute('aria-disabled','true');
  d.querySelector('.cst').className='cst '+(p.run?'run':(usable?'done':'wait'));
  const tt=d.querySelector('.t'),tv=IS_IOS?pcDisplayTitle(p.title):(p.title||p.name);
  if(tt.textContent!==tv)tt.textContent=tv;
  const bits=IS_IOS?[pcPeerLabel(p.name)]:[p.name];
  if(IS_IOS){const rt=relTime(p.ts);if(rt)bits.unshift(rt)}
  if(p.n_msgs)bits.push(p.n_msgs+' '+t('pcMsgsUnit'));
  if(p.llm)bits.push(p.llm);
  bits.push(p.run?t('pcRunning'):(usable?t('pcIdle'):t('pcNoGet')));
  const sv=bits.join(' · '),sb=d.querySelector('.pcRowSub');if(sb.textContent!==sv)sb.textContent=sv}
function syncArchHd(hd,n){
  hd.classList.toggle('open',archOpen);
  const nb=hd.querySelector('.pcArchN'),lb=hd.querySelector('.pcArchLb');
  if(lb.textContent!==t('pcArchived'))lb.textContent=t('pcArchived');
  const nv=String(n);if(nb.textContent!==nv)nb.textContent=nv}
function buildArchHd(){
  const ah=document.createElement('button');ah.type='button';ah.className='pcArchHd';
  ah.innerHTML='<span class="pcArchChev" aria-hidden="true">'+IC_CHEV+'</span>'
    +'<span class="pcArchLb"></span><span class="pcArchN"></span>';
  return ah}
function groupByTime(rows,meta=peerMeta()){
  const now=new Date(),mid=new Date(now.getFullYear(),now.getMonth(),now.getDate()).getTime();
  const day=86400000,ms=x=>x<1e12?x*1000:x;
  const g={pin:[],today:[],yest:[],week:[],old:[]};
  rows.forEach(p=>{if(metaOf(p.name,meta).pin)return g.pin.push(p);
    const tt=ms(p.ts||0);
    if(tt>=mid)g.today.push(p);else if(tt>=mid-day)g.yest.push(p);else if(tt>=mid-7*day)g.week.push(p);else g.old.push(p)});
  return [{label:t('pinned'),rows:g.pin},{label:t('pcToday'),rows:g.today},{label:t('pcYesterday'),rows:g.yest},
          {label:t('pcWeek'),rows:g.week},{label:t('pcEarlier'),rows:g.old}]}
function renderSide(ps){
  const el=document.getElementById('pcSide');if(!el)return;
  el.classList.remove('pcSideOff');
  lastPs=ps;const meta=peerMeta();
  const host=sideHost();if(!host)return;
  let act=ps.filter(p=>!metaOf(p.name,meta).arch&&!(IS_IOS&&isNew(p))),arc=ps.filter(p=>metaOf(p.name,meta).arch);
  if(IS_IOS&&pcQ){const sc=p=>fuzzyScore(pcQ,(p.title||'')+' '+p.name);
    act=act.map(p=>[sc(p),p]).filter(x=>x[0]>0).sort((a,b)=>b[0]-a[0]||(b[1].ts||0)-(a[1].ts||0)).map(x=>x[1]);
    arc=arc.filter(p=>sc(p)>0)}
  const want=act.concat(archOpen?arc:[]);
  const hn=host.querySelector('.pcSideN'),rows=[].slice.call(host.querySelectorAll('.pcRow'));
  const hd2=host.querySelector('.pcArchHd');
  const dayKey=IS_IOS?new Date().toDateString():'';
  if(hn&&dayKey===sideDayKey&&(!!hd2===!!arc.length)&&rows.length===want.length&&rows.every((d,i)=>d.dataset.peer===want[i].name)){
    hn.textContent=act.length?String(act.length):'';
    rows.forEach((d,i)=>sideSync(d,want[i],meta));
    if(hd2)syncArchHd(hd2,arc.length);
    return}
  sideDayKey=dayKey;
  closeSwipe();
  host.innerHTML='';
  const hd=document.createElement('div');hd.className='pcSideHd';
  const ht=document.createElement('span');ht.textContent=t('pcView');hd.appendChild(ht);
  const n2=document.createElement('span');n2.className='pcSideN';n2.textContent=act.length?String(act.length):'';
  hd.appendChild(n2);host.appendChild(hd);
  if(!ps.length){const d=document.createElement('div');d.className='pcEmpty';d.textContent=t('pcNoPeer');host.appendChild(d);return}
  if(IS_IOS&&pcQ&&!want.length){const d=document.createElement('div');d.className='pcEmpty';d.textContent=t('pcNoMatch');host.appendChild(d);return}
  const buckets=(IS_IOS&&!pcQ&&act.some(p=>(p.ts||0)>0))?groupByTime(act,meta):null;
  if(buckets)buckets.forEach(gr=>{if(!gr.rows.length)return;
    const s=document.createElement('div');s.className='dwSec';s.textContent=gr.label;host.appendChild(s);
    gr.rows.forEach(p=>{const d=sideRow(p);sideSync(d,p,meta);host.appendChild(d)})});
  else act.forEach(p=>{const d=sideRow(p);sideSync(d,p,meta);host.appendChild(d)});
  if(arc.length){
    const ah=buildArchHd();
    syncArchHd(ah,arc.length);
    ah.onclick=()=>{archOpen=!archOpen;renderSide(lastPs)};
    host.appendChild(ah);
    if(archOpen)arc.forEach(p=>{const d=sideRow(p);sideSync(d,p,meta);host.appendChild(d)})}}
function skel(b){b.innerHTML='<div class="pcSkel" aria-hidden="true"><i></i><i></i><i></i></div>'}
function skelSide(s){const el=IS_IOS?sideHost():(s||sideHost());if(el)el.innerHTML='<div class="pcSkel pcSkelSide" aria-hidden="true"><i></i><i></i><i></i></div>'}
function renderHome(ps){
  if(IS_IOS)setHeroMode(true);
  const box=document.getElementById('pcMsgs');if(!box)return;
  setPcHd(t('pcView'),'',false);
  const ag=(ps||[]).filter(p=>isAgent(p)&&!(IS_IOS&&isNew(p)));
  let hero=box.querySelector('.pcHero');
  if(hero&&(hero.classList.contains('pcHeroOff')||hero.classList.contains('pcBootHero')||hero.classList.contains('pcPairHero')||hero.classList.contains('pcFailHero')))hero=null;
  if(!hero){
    box.innerHTML='';
    hero=document.createElement('div');hero.className='pcEmpty pcHero';
    hero.innerHTML=LOCKUP+
      '<h2></h2><p></p><ol class="pcSteps"><li><b>1</b><span></span></li><li><b>2</b><span></span></li><li><b>3</b><span></span></li></ol>'+
      '<div class="pcPickList"></div>'+
      '<div class="pcHeroAct"><button class="btnPrimary" id="pcHeroRetry" type="button"></button></div>';
    const li=hero.querySelectorAll('.pcSteps span');
    li[0].textContent=t('pcStep1');li[1].textContent=t('pcStep2');li[2].textContent=t('pcStep3');
    const rb=hero.querySelector('#pcHeroRetry');rb.textContent=t('pcRetry');
    rb.onclick=function retryConnection(){if(IS_IOS&&!iosEnsureDataConsent(retryConnection,'pc'))return;refreshStatus();pollNow()};
    box.appendChild(hero)}
  setHeroCopy(hero,ag)}
function setHeroCopy(hero,ag){
  const many=ag.length>1,meta=peerMeta(),set=(sel,v)=>{const n=hero.querySelector(sel);if(n.textContent!==v)n.textContent=v};
  hero.classList.toggle('pcHeroPick',many);
  set('h2',t(many?'pcPickT':'pcHomeT'));
  set('p',many?(IS_IOS?(lang==='en'?'Choose from {n} conversations.':'共有 {n} 个对话，选择一条查看。'):t('pcPickP')).replace('{n}',ag.length):t('pcHomeP'));
  const el=hero.querySelector('.pcPickList'),want=many?ag:[],rows=[].slice.call(el.querySelectorAll('.pcRow'));
  if(rows.length===want.length&&rows.every((d,i)=>d.dataset.peer===want[i].name))return rows.forEach((d,i)=>sideSync(d,want[i],meta));
  el.innerHTML='';want.forEach(p=>{const d=sideRow(p);sideSync(d,p,meta);el.appendChild(d)})}
function setMsgsOff(off){if(!IS_IOS)return;const b=document.getElementById('pcMsgs');if(b)b.classList.toggle('pcMsgsOff',!!off)}
function renderOffline(){
  const ios=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios');
  renderOfflineSide();
  const box=document.getElementById('pcMsgs');if(!box)return;
  if(ios)lastSig=null;
  if(ios?box.querySelector('.pcTask'):(box.firstElementChild&&!box.querySelector('.pcSkel,.pcHeroOff')))return;
  if(ios)setHeroMode(true);
  lastSig=null;
  if(ios)setMsgsOff(false);
  if(box.querySelector('.pcHeroOff'))return;
  box.innerHTML='';
  const d=document.createElement('div');d.className='pcEmpty pcHero pcHeroOff';
  d.innerHTML=LOCKUP+
    '<h2></h2><p></p><div class="pcHeroAct"><button class="btnPrimary" id="pcOffRetry" type="button"></button></div>';
  d.querySelector('h2').textContent=t('pcOfflineT');
  d.querySelector('p').textContent=t('pcOfflineP');
  const rb=d.querySelector('#pcOffRetry');rb.textContent=t('pcRetry');
  rb.onclick=function retryConnection(){if(ios&&!iosEnsureDataConsent(retryConnection,'pc'))return;refreshStatus();pollNow()};
  box.appendChild(d)}
function renderOfflineSide(){
  const el=document.getElementById('pcSide');if(!el)return;
  el.classList.add('pcSideOff');
  if(el.querySelector('.pcRow'))return;
  const h=sideHost();if(!h)return;
  h.innerHTML='';const d=document.createElement('div');d.className='pcEmpty';d.textContent=t('pcOffline');h.appendChild(d)}
function engineState(){if(!IS_IOS)return 'ok';
  let r='';try{r=(GA.ready&&GA.ready())||''}catch(e){}
  if(!r)return 'boot';
  return String(r).indexOf('ERR')===0?'err':'ok'}
function setHeroMode(on){const v=document.getElementById('pcView');if(!v)return;v.classList.toggle('pcHeroMode',!!on);
  if(on)setMsgsOff(false);
  if(!on){const bar=v.querySelector('#pcInBar');
    if(bar)requestAnimationFrame(()=>{try{document.documentElement.style.setProperty('--pcBarH',Math.round(bar.getBoundingClientRect().height)+'px')}catch(e){}})}}
function heroSide(){const el=document.getElementById('pcSide');if(!el||el.querySelector('.pcRow'))return;
  const h=sideHost();if(h)h.innerHTML=''}
function renderBooting(){const box=document.getElementById('pcMsgs');if(!box)return;
  const b=document.getElementById('pcHdTitle');if(b)b.textContent=t('pcView');
  const s=document.getElementById('pcHdSub');if(s){if(s.textContent!==t('pcBootT'))s.textContent=t('pcBootT');s.classList.add('busy')}
  setHeroMode(true);heroSide();
  if(box.querySelector('.pcBootHero'))return;
  box.innerHTML='';
  const d=document.createElement('div');d.className='pcEmpty pcHero pcBootHero';
  d.innerHTML=LOCKUP+'<h2></h2><p></p>';
  d.querySelector('h2').textContent=t('pcBootT');d.querySelector('p').textContent=t('pcBootP');
  box.appendChild(d)}
function renderEngineFail(){const box=document.getElementById('pcMsgs');if(!box)return;
  const b=document.getElementById('pcHdTitle');if(b)b.textContent=t('pcView');
  const s=document.getElementById('pcHdSub');if(s){if(s.textContent!==t('pcBootFailT'))s.textContent=t('pcBootFailT');s.classList.remove('busy')}
  setHeroMode(true);heroSide();
  if(box.querySelector('.pcFailHero'))return;
  box.innerHTML='';
  const d=document.createElement('div');d.className='pcEmpty pcHero pcFailHero';
  d.innerHTML=LOCKUP+'<h2></h2><p></p>'+
    '<div class="pcHeroAct"><button class="btnPrimary" id="pcFailRetry" type="button" data-track="pc_fail_retry"></button></div>'+
    '<button class="pcGoLocal" type="button" data-track="pc_golocal"></button>';
  d.querySelector('h2').textContent=t('pcBootFailT');d.querySelector('p').textContent=t('pcBootFailP');
  const rb=d.querySelector('#pcFailRetry');rb.textContent=t('pcRetry');
  rb.onclick=function retryConnection(){if(IS_IOS&&!iosEnsureDataConsent(retryConnection,'pc'))return;statusWait=0;bootWaited=true;refreshStatus();pollNow()};
  const gl=d.querySelector('.pcGoLocal');gl.textContent=t('pcGoLocal');gl.onclick=()=>closeView();
  box.appendChild(d)}
function renderUnpaired(){const box=document.getElementById('pcMsgs');if(!box)return;
  const b=document.getElementById('pcHdTitle');if(b)b.textContent=t('pcView');
  const s=document.getElementById('pcHdSub');if(s){if(s.textContent!==t('pcNotPaired'))s.textContent=t('pcNotPaired');s.classList.remove('busy')}
  setHeroMode(true);heroSide();
  if(box.querySelector('.pcPairHero'))return;
  box.innerHTML='';
  const d=document.createElement('div');d.className='pcEmpty pcHero pcPairHero';
  d.innerHTML=LOCKUP+'<h2></h2><p></p>'+
    '<div class="pcHeroAct"><button class="btnPrimary" id="pcPairScan" type="button" data-track="pc_pair_scan"></button></div>'+
    '<div class="pcHeroAct"><button class="pcBtnAlt" id="pcPairManual" type="button" data-track="pc_pair_manual"></button></div>'+
    '<button class="pcGoLocal" id="pcGoLocal" type="button" data-track="pc_golocal"></button>';
  d.querySelector('h2').textContent=t('pcPairHeroT');
  d.querySelector('p').textContent=t('pcPairHeroP');
  const sb=d.querySelector('#pcPairScan');sb.textContent=t('pcScan');sb.onclick=()=>startScan();
  const mb=d.querySelector('#pcPairManual');mb.textContent=t('pcManual');mb.onclick=()=>openManualPair();
  const gl=d.querySelector('#pcGoLocal');gl.textContent=t('pcGoLocal');gl.onclick=()=>closeView();
  box.appendChild(d)}
function selPeer(name){
  setPeer(name);rememberPeer(name);
  if(!IS_IOS||!connected||!name||!knownNames.has(name))return poll();
  setHeroMode(false);
  const my=++tok;if(timer){clearTimeout(timer);timer=null}
  if(lastPs)renderSide(lastPs);
  pullMsgs(()=>{if(my===tok)arm()},0,()=>my===tok);
}
function fetchSeg(i,j,n,p,g,cb,valid){
  const k=i+'/'+j;let ent=segTxt[k],raw=(ent&&ent.txt&&ent.n>=0&&ent.n<=n)?ent.txt:'';
  if(ent&&ent.n===n&&ent.txt!=null&&ent.txt!=='')return cb(true);
  const off=raw.length;
  api('GET','/api/'+encodeURIComponent(p)+'/seg/'+i+'/'+j+'?off='+off,'',sr=>{
    if(valid?!valid():g!==gen||p!==curPeer)return cb(false);
    if(!sr||sr.content==null)return cb(!!(ent&&ent.txt));
    if(sr.n!=null&&sr.n<off){delete segTxt[k];return fetchSeg(i,j,n,p,g,cb,valid)}
    raw=(sr.off===off?raw:'')+sr.content;
    segTxt[k]={txt:raw,n:(sr.n!=null?sr.n:n)};cb(true)},valid?undefined:()=>g===gen&&p===curPeer)}
function pullMsgs(done,depth,alive){
  depth=depth||0;if(depth>3)return done();
  const g=++gen,p=curPeer;
  const al=()=>g===gen&&p===curPeer&&(!alive||alive());
  if(++sigAge>=8){sigAge=0;lastSig=null}
  const olds=taskSnap.length,since=Math.max(0,olds-1);
  let q='/api/'+encodeURIComponent(p)+'/messages?detail=1&since='+since;
  if(lastSig)q+='&sig='+encodeURIComponent(lastSig);
  api('GET',q,'',r=>{
    if(g!==gen||p!==curPeer)return done();
    if(!r||r.error){idleRounds++;return done()}
    if(r.same){const was=peerRun;setRunBtn(r.run);setPcHd(undefined,p,r.run);idleRounds++;
      if(pendingPut&&++pendingPut.rounds>6){pendingPut=null;
        if(pendingEcho){pendingEcho.fail=true;
          const bx=document.getElementById('pcMsgs');if(bx)syncEcho(bx,curPeer)}
        const s=document.getElementById('pcHdSub');if(s)s.textContent+=' · '+t('pcNotTaken')}
      if(was&&!r.run){lastSig=null;idleRounds=0;return pullMsgs(done,depth+1,alive)}scheduleVisible();return done()}
    lastSig=r.sig||null;idleRounds=0;
    if(taskSnap.length)markUnread();
    setPcHd(r.title,p,r.run);
    const slice=r.tasks||[],hasNt=('nt' in r),total=hasNt?r.nt:slice.length;
    if(olds>total){lastSig=null;segTxt={};taskSnap=[];const b=document.getElementById('pcMsgs');if(b)skel(b);return pullMsgs(done,depth+1,alive)}
    if(!hasNt)taskSnap=slice;
    else{taskSnap=taskSnap.slice(0,since).concat(slice);
      if(taskSnap.length<total){lastSig=null;taskSnap=[];const b=document.getElementById('pcMsgs');if(b)skel(b);return pullMsgs(done,depth+1,alive)}
      if(taskSnap.length>total)taskSnap=taskSnap.slice(0,total)}
    prefetch({tasks:taskSnap,run:r.run},g,p,done)},al)}
function prefetch(r,g,p,done){
  paint(r,g,p,()=>{scheduleVisible();done()})}
let visibleFrame=0,visibleFlight=null;
function scheduleVisible(){
  if(!visibleFrame)visibleFrame=requestAnimationFrame(()=>{visibleFrame=0;loadVisible()})}
function loadVisible(){
  const box=document.getElementById('pcMsgs'),v=document.getElementById('pcView');
  if(document.hidden||!box||!v||!v.classList.contains('on'))return;
  const p=curPeer,cache=segTxt;
  if(visibleFlight&&visibleFlight.valid())return;
  const br=box.getBoundingClientRect();if(br.bottom<=br.top)return;
  const wrappers=[...box.querySelectorAll('.pcTask')],latest=taskSnap[taskSnap.length-1];
  wrappers.sort((a,b)=>Number(b.dataset.pci===String(latest&&latest.i))-Number(a.dataset.pci===String(latest&&latest.i)));
  for(const w of wrappers){
    const ti=taskSnap.findIndex(tk=>String(tk.i)===w.dataset.pci),tk=taskSnap[ti];if(!tk)continue;
    const st=tk.steps||[],s=st[st.length-1];if(!s)continue;
    const cards=w.querySelectorAll('.step'),card=cards[cards.length-1];if(!card)continue;
    const cr=card.getBoundingClientRect();if(tk!==latest&&(cr.height<=0||cr.bottom<=br.top||cr.top>=br.bottom))continue;
    const ent=cache[tk.i+'/'+s.j];
    if(ent&&ent.n===s.n){if(w.dataset.tsig!==tsigOf(tk,peerRun&&ti===taskSnap.length-1))fillVisible(box,w,tk);continue;}
    if(w._pcLazyTry===gen)continue;
    w._pcLazyTry=gen;
    const valid=()=>p===curPeer&&cache===segTxt&&taskSnap.some(t=>t.i===tk.i&&(t.steps||[]).some(x=>x.j===s.j));
    const flight={valid};visibleFlight=flight;
    fetchSeg(tk.i,s.j,s.n,p,gen,ok=>{
      if(visibleFlight===flight)visibleFlight=null;
      if(ok&&valid()&&!document.hidden&&v.classList.contains('on')&&w.isConnected){
        fillVisible(box,w,taskSnap.find(t=>t.i===tk.i));
      }
      scheduleVisible();
    },valid);
    return;
  }
}
function fillVisible(box,w,tk){
  const top=box.scrollTop,oldTop=w.getBoundingClientRect().top,fs=captureFold(w),idx=taskSnap.indexOf(tk);
  const live=peerRun&&idx===taskSnap.length-1;
  if(!(live&&w.dataset.pclive==='1'&&patchLiveTask(w,tk))){paintTask(w,tk,idx,taskSnap,peerRun);applyFold(w,fs,tk)}
  w.dataset.tsig=tsigOf(tk,live);
  box.scrollTop=top+w.getBoundingClientRect().top-oldTop;pcSyncDown(box);
}
function tsigOf(tk,live){const st=tk.steps||[],ls=st[st.length-1],cv=ls?(((segTxt[tk.i+'/'+ls.j])||{}).n||'-'):'-';
  return (live?'L':'D')+'|'+(tk.input||'').length+'|'+st.map(s=>s.j+':'+s.n).join(',')+'|'+cv}
function paintTask(wrapper,tk,ti,tasks,run){
  const st=tk.steps||[],live=run&&ti===tasks.length-1;
  const msgs=[{role:'user',text:tk.input||''},
    {role:'assistant',prompt:tk.input||'',model:'PC',live:live,
      steps:st.map((s,x)=>{const k=tk.i+'/'+s.j,got=segTxt[k];
        return {n:x+1,summary:s.title||('step '+(s.j+1)),text:(x===st.length-1&&got)?got.txt:''}})}];
  wrapper.dataset.pcq=tk.input||'';
  wrapper.innerHTML='';
  try{renderMsgsInto(wrapper,msgs,{noActions:true,detachTask:true})}
  catch(e){wrapper.innerHTML='';const d=document.createElement('div');d.className='pcEmpty';d.textContent=t('pcRenderErr');wrapper.appendChild(d);
    wrapper.dataset.pci=tk.i;wrapper.dataset.tsig='';return}
  const h=wrapper.querySelector('.assistHead');
  if(h){const nm=h.querySelector('.assistName');if(nm)nm.textContent='PC';
    const gl=h.querySelector('.glyph');
    if(gl){const sp=document.createElement('span');sp.className='glyph pcGlyph';sp.setAttribute('aria-hidden','true');
      sp.innerHTML='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>';
      gl.replaceWith(sp)}}
  if(h&&typeof copyText==='function'&&!h.querySelector('.pcCopy')){
    const cpb=document.createElement('button');cpb.className='pcCopy';cpb.setAttribute('data-track','pc_copy');
    cpb.setAttribute('aria-label',t('copyReply'));cpb.setAttribute('data-i18n-aria','copyReply');
    cpb.innerHTML=(typeof ICO_COPY!=='undefined')?ICO_COPY:'⧉';
    cpb.onclick=()=>{
      const tbEl=wrapper.querySelector('.task');const scs=tbEl?tbEl.querySelectorAll('.step'):[];
      const le=scs.length?scs[scs.length-1]:null;
      const k=(tbEl&&tbEl.dataset.pci!=null&&le&&le.dataset.pcj!=null)?(tbEl.dataset.pci+'/'+le.dataset.pcj):null;
      const got=k&&segTxt[k];let raw=(got&&got.txt)||'';
      if(!raw)raw=(le&&(le._text||le.textContent))||'';
      const txt=(typeof composeFinal==='function'&&typeof cleanReply==='function')?(composeFinal(cleanReply(raw),raw)||raw):raw;
      copyText(txt,()=>{cpb.innerHTML=(typeof ICO_OK!=='undefined')?ICO_OK:'✓';setTimeout(()=>{cpb.innerHTML=(typeof ICO_COPY!=='undefined')?ICO_COPY:'⧉'},1200)})};
    h.appendChild(cpb)}
  const tb=wrapper.querySelector('.task');
  if(tb){tb.dataset.pci=tk.i;
    tb.querySelectorAll('.step').forEach((sc,si)=>{const s=st[si];if(s){sc.dataset.pcj=s.j;sc.dataset.pcn=s.n;
      if(si===st.length-1&&segTxt[tk.i+'/'+s.j]&&segTxt[tk.i+'/'+s.j].n===s.n)sc._pcGot=1}})}
  wrapper.dataset.pci=tk.i;wrapper.dataset.tsig=tsigOf(tk,live);wrapper.dataset.pclive=live?'1':'0'}
function patchLiveTask(wrapper,tk){
  const tb=wrapper.querySelector('.task'),st=tk.steps||[];if(!tb||typeof patchReplaySteps!=='function')return false;
  const old=[].slice.call(tb.querySelectorAll('.step'));if(!old.length||st.length<old.length)return false;
  const from=Math.max(0,old.length-1),delta=st.slice(from).map((s,x)=>{const si=from+x,k=tk.i+'/'+s.j,got=segTxt[k],fresh=got&&got.n===s.n;
    return {n:si+1,summary:s.title||('step '+(s.j+1)),text:fresh?got.txt:((old[si]&&old[si]._text)||'')}});
  if(!patchReplaySteps(tb,delta))return false;
  tb.dataset.pci=tk.i;tb.querySelectorAll('.step').forEach((sc,si)=>{const s=st[si];if(!s)return;sc.dataset.pcj=s.j;sc.dataset.pcn=s.n;
    if(segTxt[tk.i+'/'+s.j]&&segTxt[tk.i+'/'+s.j].n===s.n)sc._pcGot=1;else delete sc._pcGot});
  wrapper.dataset.pci=tk.i;wrapper.dataset.pclive='1';return true}
function captureFold(wrapper){
  const fold=wrapper.querySelector('.stepsFold');
  return {foldOpen:!!(fold&&fold.classList.contains('open')),
    openJs:[].slice.call(wrapper.querySelectorAll('.step')).filter(c=>c.classList.contains('open')).map(c=>c.dataset.pcj)}}
function applyFold(wrapper,fs,tk){
  if(fs.foldOpen){const f=wrapper.querySelector('.stepsFold');if(f)f.classList.add('open')}
  if(!fs.openJs.length)return;
  wrapper.querySelectorAll('.step').forEach(c=>{
    if(c.dataset.pcj==null||fs.openJs.indexOf(c.dataset.pcj)<0||c.classList.contains('open'))return;
    c.classList.add('open');
    const k=tk.i+'/'+c.dataset.pcj,got=segTxt[k];
    if(got){c._text=got.txt;const sb=c.querySelector('.sb');if(sb)sb._rendered=false;c._pcGot=1}
    try{renderBody(c)}catch(e){}})}
function pcSyncDown(box){
  const ios=(typeof IS_IOS!=='undefined'&&IS_IOS)||!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios');
  const dn=document.getElementById('pcDown');if(!dn)return;
  if(ios&&box.querySelector('.pcStart')){dn.hidden=true;return}
  dn.hidden=!((ios||box.scrollHeight-box.clientHeight>600)&&box.scrollHeight-box.scrollTop-box.clientHeight>=150)&&!(ios&&dn.classList.contains('unread'))}
function pcScrollTxn(box){
  const ios=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios');
  const follow=box._pcStick!==false,top=box.scrollTop,seq=box._pcPinSeq||0;
  return ()=>{
    if((box._pcPinSeq||0)!==seq)return;
    if(ios&&box.querySelector('.pcStart')){pcSyncDown(box);return}
    if(!follow){box.scrollTop=top;pcSyncDown(box);return}
    let n=0;const pin=()=>{if((box._pcPinSeq||0)!==seq||box._pcStick===false||(ios&&box.querySelector('.pcStart')))return;box.scrollTop=box.scrollHeight;pcSyncDown(box);if(++n<6)requestAnimationFrame(pin)};
    pin();setTimeout(pin,160);setTimeout(pin,360)}
}
function pcAlignTop(box,el,pad){
  try{const sr=box.getBoundingClientRect(),er=el.getBoundingClientRect();box.scrollTop+=(er.top-sr.top)-(pad==null?6:pad)}catch(e){}}
let _pcHeadRaf=0;
function syncPcHead(){
  const ios=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios');
  if(!ios)return;
  const hd=document.getElementById('pcChatHead'),box=document.getElementById('pcMsgs'),v=document.getElementById('pcView');
  if(!hd||!box)return;
  const tks=box.querySelectorAll('.pcTask');
  if(!tks.length||(v&&v.classList.contains('pcHeroMode'))){hd.hidden=true;hd._cur=null;return}
  const bt=box.getBoundingClientRect().top;let cur=tks[0];
  for(const w of tks){if(w.getBoundingClientRect().top-bt<=10)cur=w;else break}
  const q=(cur.dataset.pcq||'').trim();
  hd.hidden=!q;hd._cur=q?cur:null;
  if(q){const el=document.getElementById('pcLmText');if(el&&el.textContent!==q)el.textContent=q}}
function reqPcHead(){const ios=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios');if(!ios||_pcHeadRaf)return;_pcHeadRaf=requestAnimationFrame(()=>{_pcHeadRaf=0;syncPcHead()})}
function syncEcho(box,p){
  let e=box.querySelector('.pcEchoW');
  if(!pendingEcho||pendingEcho.peer!==p){if(e)e.remove();return}
  if(!e){e=document.createElement('div');e.className='pcEchoW';const b=document.createElement('div');b.className='pcEcho';b.textContent=pendingEcho.text;e.appendChild(b)}
  e.classList.toggle('pcEchoFail',!!pendingEcho.fail);
  let f=e.querySelector('.pcEchoRe');
  if(pendingEcho.fail&&!f){f=document.createElement('button');f.className='pcEchoRe';f.type='button';f.textContent='!';f.setAttribute('aria-label',t('pcResend'));
    f.onclick=()=>{const tx=pendingEcho&&pendingEcho.text;if(tx&&!putBusy){pendingEcho=null;doPut(tx)}};e.insertBefore(f,e.firstChild)}
  if(!pendingEcho.fail&&f)f.remove();
  if(box.lastElementChild!==e)box.appendChild(e)}
function pcFitTail(box,wrapper){
  const el=wrapper&&(wrapper.querySelector('.task')||wrapper);if(box._pcStick!==false||!el){box.style.setProperty('--pcTail','0px');return}
  box.style.setProperty('--pcTail','0px');
  try{const sr=box.getBoundingClientRect(),er=el.getBoundingClientRect(),target=box.scrollTop+(er.top-sr.top)-6,max=box.scrollHeight-box.clientHeight;
    box.style.setProperty('--pcTail',Math.max(0,Math.ceil(target-max))+'px')}catch(e){}}
function pcPinTaskTop(box,wrapper){
  let el=wrapper&&(wrapper.querySelector('.task')||wrapper);if(!el)return;
  const seq=(box._pcPinSeq||0)+1;box._pcPinSeq=seq;box._pcUserScroll=false;box._pcStick=false;
  let n=0;const pin=()=>{if((box._pcPinSeq||0)!==seq||box._pcStick!==false)return;el=wrapper.querySelector('.task')||wrapper;pcFitTail(box,wrapper);alignTop(box,el,6);pcSyncDown(box);if(++n<8)requestAnimationFrame(pin)};
  pin();setTimeout(pin,200);setTimeout(pin,420);setTimeout(pin,700)}
function pcSwapEchoSlot(box,lastW){
  const ios=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios');
  if(!ios||!box._pcEchoSwap)return;
  box._pcEchoSwap=false;
  const tks=box.querySelectorAll('.pcTask');tks.forEach(w=>{if(w!==lastW&&w.style.minHeight)w.style.minHeight=''});
  lastW.style.minHeight=Math.max(0,box.clientHeight-12)+'px';
}
function paint(r,g,p,done){
  const ios=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios');
  const echoNow=typeof pendingEcho!=='undefined'?pendingEcho:null;
  if(g!==gen||p!==curPeer)return done();
  const box=document.getElementById('pcMsgs');if(!box)return done();
  const settleScroll=pcScrollTxn(box),finish=()=>{settleScroll();
    if(box._pcEchoSwap){box._pcEchoSwap=false;
      if(ios&&box._pcStick===false&&!box._pcUserScroll){
        const tks=box.querySelectorAll('.pcTask'),lastT=tks[tks.length-1];
        if(lastT){tks.forEach(w=>{if(w!==lastT&&w.style.minHeight)w.style.minHeight=''});
          lastT.style.minHeight=Math.max(0,box.clientHeight-12)+'px';pcAlignTop(box,lastT)}}}
    reqPcHead();
    done()};
  const tasks=r.tasks||[],run=!!r.run;
  if(ios)document.getElementById('pcView').classList.toggle('pcNoConversation',tasks.length===0);
  if(pendingPut&&tasks.length>pendingPut.n){pendingPut=null;if(typeof pendingEcho!=='undefined')pendingEcho=null;
    if(ios&&box._pcStick===false)box._pcEchoSwap=true}
  if(!tasks.length){
    if(echoNow&&echoNow.peer===p){const e0=box.querySelector('.pcEmpty');if(e0)e0.remove();syncEcho(box,p);setRunBtn(run);return finish()}
    const e0=box.querySelector('.pcEmpty');
    if(ios)renderStartConversation(box);
    else if(!e0||e0.parentElement!==box||e0.classList.contains('pcHero')){box.innerHTML='';const d=document.createElement('div');d.className='pcEmpty';d.textContent=t('pcNoMsgs');box.appendChild(d)}
    const ew=box.querySelector('.pcEchoW');if(ew)ew.remove();
    box.style.setProperty('--pcTail','0px');setRunBtn(run);return finish()}
  const emp=box.querySelector('.pcEmpty');if(emp)emp.remove();
  rememberPeer(p);
  const sk=box.querySelector('.pcSkel');if(sk)sk.remove();
  const existing=[].slice.call(box.children).filter(e=>e.classList&&e.classList.contains('pcTask'));
  let deg=existing.length>tasks.length;
  if(!deg)for(let i=0;i<existing.length;i++)if(String(existing[i].dataset.pci)!==String(tasks[i].i)){deg=true;break}
  if(deg){
    box.innerHTML='';let lastW=null;
    tasks.forEach((tk,ti)=>{const w=document.createElement('div');w.className='pcTask';box.appendChild(w);paintTask(w,tk,ti,tasks,run);lastW=w});
    if(typeof pendingEcho!=='undefined')syncEcho(box,p);
    setRunBtn(run);
    if(lastW){reqPcHead();pcPinTaskTop(box,lastW);done();return}
    return finish()}
  let grew=false,lastW=null;
  tasks.forEach((tk,ti)=>{
    const sig=tsigOf(tk,run&&ti===tasks.length-1);
    let w=existing[ti];
    if(!w){w=document.createElement('div');w.className='pcTask';box.appendChild(w);paintTask(w,tk,ti,tasks,run);grew=true;lastW=w;return}
    if(w.dataset.tsig===sig)return;
    const live=run&&ti===tasks.length-1;
    if(live&&w.dataset.pclive==='1'&&patchLiveTask(w,tk)){w.dataset.tsig=sig;return}
    const fs=captureFold(w);paintTask(w,tk,ti,tasks,run);applyFold(w,fs,tk)});
  if(typeof pendingEcho!=='undefined')syncEcho(box,p);
  setRunBtn(run);
  if(grew&&lastW){pcSwapEchoSlot(box,lastW);reqPcHead();pcPinTaskTop(box,lastW);done();return}
  pcFitTail(box,existing[tasks.length-1]);finish()}
/* ---- 启动: 等引擎就绪后静默探一次状态, 已配对才挂 FAB ---- */
let bootTries=0;
function boot(){
  if(!(window.GA&&GA.send)){if(++bootTries>20)return;return setTimeout(boot,1500)}
  refreshStatus();
}
setTimeout(boot,1200);
function _pcOptimisticFab(){try{if(localStorage.getItem('ga.pcPaired')==='1')paired=true;if(paired||IS_IOS)showFab()}catch(e){}}
if(document.body)_pcOptimisticFab();else document.addEventListener('DOMContentLoaded',_pcOptimisticFab);
let resumedAt=0;
function resume(){
  const ios=!!(typeof window!=='undefined'&&window.GA&&window.GA.platform==='ios');
  if(!(window.GA&&GA.send)||Date.now()-resumedAt<1000)return;
  resumedAt=Date.now();refreshStatus(null,true);
  if(ios&&bgTimer)bgPoll();
  const v=document.getElementById('pcView');if(v&&v.classList.contains('on'))pollNow()}
document.addEventListener('visibilitychange',()=>{
  if(document.hidden&&timer){clearTimeout(timer);timer=null}});
function reI18n(){
  const v=document.getElementById('pcView');if(!v)return;
  applyI18n();
  const hero=v.querySelector('.pcHero,.pcStart');if(hero){hero.remove();lastSig=null;}
  renderRow();setPcHd(undefined,curPeer||'',peerRun);
  if(v.classList.contains('on')){skelSide(document.getElementById('pcSide'));pollNow()}}
window.PCLINK={refreshStatus,openView,closeView,reI18n,resume};
if(IS_IOS){
  try{const st=document.createElement('style');
    st.textContent='#setv{z-index:64}#modelv{z-index:65}'
      +'.pcBtnAlt{flex:1;border:none;border-radius:var(--r-full);min-height:50px;padding:0 24px;font-size:16px;font-weight:600;color:var(--txt);background:var(--surface2);transition:transform .12s,background .2s}'
      +'.pcHeroAct .btnPrimary{min-height:50px;padding:0 24px;border-radius:var(--r-full)}'
      +'.pcHeroAct .btnPrimary:active,.pcBtnAlt:active{transform:scale(.97)}'
      +'.pcGoLocal{margin-top:14px;border:none;background:none;font-size:13px;color:var(--txt2);text-decoration:underline;text-underline-offset:3px}'
      +'#pcView.pcHeroMode #pcInBar{display:none}'
      +'#pcView #pcSide{display:flex;flex-direction:column;overflow:hidden;padding:0}'
      +'@media (min-width:900px){#pcView #pcSide{padding-left:env(safe-area-inset-left)}}'
      +'#pcSideList{flex:1 1 auto;overflow-y:auto;min-height:0;overscroll-behavior:contain;padding:4px 10px}'
      +':root{--fut:#0066CC;--futGlow:0 0 10px color-mix(in srgb,var(--fut) 38%,transparent)}'
      +':root[data-theme=dark]{--fut:#409CFF}'
      +'@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--fut:#409CFF}}'
      +'#pcBtn{background:var(--fut);box-shadow:var(--futGlow)}'
      +'#pcBtn.stop{background:var(--err);box-shadow:none}'
      +'#pcBtn.idleOff{background:var(--surface2);color:var(--mut);box-shadow:none}'
      +'#btn:not(:disabled){background:var(--fut);box-shadow:var(--futGlow)}'
      +'#btn.stop{background:var(--err);box-shadow:none}'
      +'#pcSide .cst.run i,.pcPickList .cst.run i,.dwItem .cst.run i{background:var(--fut)}'
      +'#pcSide .cst.run i::after,.pcPickList .cst.run i::after{background:var(--fut)}'
      +'.pcHdSub.busy::before{background:var(--fut);box-shadow:0 0 6px color-mix(in srgb,var(--fut) 45%,transparent)}'
      +'.dwItem.cur{box-shadow:inset 2px 0 0 var(--fut)}'
      +'.cap:focus-within{border-color:color-mix(in srgb,var(--fut) 45%,var(--line));box-shadow:0 0 0 4px color-mix(in srgb,var(--fut) 12%,transparent)}'
      +':focus-visible{outline-color:var(--fut)}'
      +'.btnPrimary{background:var(--fut)}.btnPrimary:disabled{background:var(--surface2);color:var(--mut);box-shadow:none}'
      +'#pcDown.unread::after{content:"";position:absolute;top:5px;right:5px;width:8px;height:8px;border-radius:50%;background:var(--fut);box-shadow:0 0 6px color-mix(in srgb,var(--fut) 50%,transparent)}'
      +'.pcHero:not(.pcHeroOff) .pcLinkWire{position:relative;overflow:hidden}'
      +'.pcHero:not(.pcHeroOff) .pcLinkWire::after{content:"";position:absolute;inset:-1px;background:linear-gradient(90deg,transparent,var(--fut) 50%,transparent);transform:translateX(-100%);animation:futFlow 2.4s ease-in-out infinite}'
      +'@keyframes futFlow{60%,100%{transform:translateX(100%)}}'
      +'@media (prefers-reduced-motion:reduce){.pcHero:not(.pcHeroOff) .pcLinkWire::after{animation:none;opacity:0}}'
      +'#pcChips{-webkit-mask-image:linear-gradient(90deg,#000,#000 calc(100% - 26px),transparent);mask-image:linear-gradient(90deg,#000,#000 calc(100% - 26px),transparent)}'
      +'.pcVerChip{background:none;box-shadow:none;color:var(--mut);font-size:11px;padding:6px 2px}'
      +'#pcSideList .dwSec{position:sticky;top:0;z-index:1;background:color-mix(in srgb,var(--surface) 92%,transparent);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px)}'
      +'#hdrsub.busy::before{background:var(--fut);box-shadow:0 0 6px color-mix(in srgb,var(--fut) 45%,transparent)}'
      +'.runMeta .spin{border-top-color:var(--fut)}'
      +'#snDown.pin{color:var(--fut)}#snDown.done{color:var(--fut)}'
      +'.assistHead .assistState.run::before{background:var(--fut);box-shadow:0 0 6px color-mix(in srgb,var(--fut) 45%,transparent)}'
      +'.bwshot.cur{border-color:var(--fut)}'
      +'.pcEchoW{display:flex;justify-content:flex-end;align-items:center;gap:8px;padding:2px 0 10px}'
      +'.pcEcho{max-width:82%;background:var(--uBubble);color:var(--uTxt);border-radius:var(--r-md);padding:10px 14px;font-size:15px;line-height:1.5;white-space:pre-wrap;word-break:break-word;opacity:.72}'
      +'.pcEchoFail .pcEcho{opacity:.55}'
      +'.pcEchoRe{position:relative;flex:none;width:22px;height:22px;border:none;border-radius:50%;background:var(--err);color:#fff;font-size:14px;font-weight:700;line-height:1;display:flex;align-items:center;justify-content:center;padding:0;-webkit-tap-highlight-color:transparent}'
      +'.pcEchoRe::before{content:"";position:absolute;top:50%;left:50%;width:40px;height:40px;transform:translate(-50%,-50%)}'
      +'.pcEchoRe:active{transform:scale(.88)}'
      +'#pcFab.bgRun::after{content:"";position:absolute;top:5px;right:5px;width:9px;height:9px;border-radius:50%;background:var(--fut);box-shadow:0 0 6px color-mix(in srgb,var(--fut) 50%,transparent);animation:pul 1s infinite alternate}'
      +'#pcMsgs.pcMsgsOff{filter:grayscale(.85);opacity:.55;transition:filter .3s,opacity .3s}'
      +'#pcSide .pcRow.cur .cst.run i::after,.pcPickList .pcRow.cur .cst.run i::after{animation:none;opacity:0}'
      +'@keyframes pcHalo{to{transform:scale(1.9);opacity:0}}'
      +'#pcSearch{flex:none;margin:6px var(--sp-3) var(--sp-2)}'
      +'#pcNav{position:absolute;right:14px;bottom:calc(var(--pcBarH,calc(136px + env(safe-area-inset-bottom))) + 10px + var(--pcFabClearance,0px));z-index:var(--z-scrollNav);display:flex;flex-direction:column;border-radius:var(--r-full);overflow:hidden;background:var(--chipBg);-webkit-backdrop-filter:saturate(180%) blur(20px);backdrop-filter:saturate(180%) blur(20px);box-shadow:inset 0 0 0 1px var(--line),var(--elev-1);transform:translateY(calc(-1*var(--kb,0px)));transition:transform .18s ease-out}'
      +'#pcNav:not(:has(button:not([hidden]))){display:none}'
      +'#pcNav #pcUp,#pcNav #pcDown{position:relative;inset:auto;width:44px;height:44px;border-radius:0;background:none;-webkit-backdrop-filter:none;backdrop-filter:none;box-shadow:none;z-index:auto;transform:none}'
      +'#pcNav #pcUp:not([hidden])+#pcDown:not([hidden]){border-top:1px solid var(--line)}'
      +'@media (min-width:900px){#pcNav{right:max(14px,calc((100% - var(--pcCol))/2 - 52px))}}'
      +'.pcChip{box-shadow:inset 0 0 0 1px var(--line)}'
      +'#pcCap{--line:var(--md-sys-color-outline-variant)}'
      +'.pcHd{box-shadow:none;padding-bottom:2px}'
      +'#pcSideList .pcSideHd{display:none}'
      +'#pcSideList .pcSideHd+.dwSec{padding-top:2px}'
      +'#pcView.side .pcChatHead{visibility:hidden}'
      +'#pcMsgs pre.ga-card--code>code{max-height:76px;overflow:hidden;-webkit-mask-image:linear-gradient(#000 45%,transparent);mask-image:linear-gradient(#000 45%,transparent)}'
      +'#pcMsgs pre.ga-card--code.open>code{max-height:none;-webkit-mask-image:none;mask-image:none}'
      +'#pcMsgs pre.ga-card--code .cbhead::after{content:"";flex:none;width:8px;height:8px;border-right:2px solid var(--txt2);border-bottom:2px solid var(--txt2);transform:rotate(45deg) translate(-1px,-1px);margin:0 4px 0 10px;transition:transform .2s}'
      +'#pcMsgs pre.ga-card--code.open .cbhead::after{transform:rotate(225deg) translate(-2px,-2px)}'
      +'.bwph svg,.bwhi svg,.bwfail svg{vertical-align:-2px}'
      +'.pcChatHead{flex:none;display:flex;padding:2px max(var(--sp-4),env(safe-area-inset-left)) 0 max(var(--sp-4),env(safe-area-inset-right))}'
      +'.pcChatHead[hidden]{display:none}'
      +'.pcLastMsg{display:flex;align-items:center;gap:8px;flex:1;min-width:0;padding:7px 14px;background:var(--surface2);border:1px solid var(--line);border-radius:var(--r-md);font-size:12px;color:var(--txt2);text-align:left;-webkit-tap-highlight-color:transparent;transition:background .15s}'
      +'.pcLastMsg:active{background:var(--surface3)}'
      +'.pcLastMsg svg{width:14px;height:14px;flex:none;opacity:.55}'
      +'.pcLastMsg span{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}'
      +'@media (min-width:900px){.pcChatHead{max-width:var(--pcCol);margin-inline:auto}}'
      +'#pcSwipeAct{position:fixed;right:0;z-index:63;display:flex;overflow:hidden}'
      +'#pcSwipeAct[hidden]{display:none}'
      +'#pcSwipeAct button{width:64px;border:none;font-size:13px;font-weight:600;color:#fff;-webkit-tap-highlight-color:transparent}'
      +'#pcSwipeAct .swPin{background:var(--acc2)}'
      +'#pcSwipeAct .swArch{background:var(--err)}'
      +'#pcFab{border:none;background:var(--chipBg);-webkit-backdrop-filter:saturate(180%) blur(20px);backdrop-filter:saturate(180%) blur(20px);box-shadow:inset 0 0 0 1px var(--line),var(--elev-1)}'
      +'#pcDown,#pcUp{width:44px;height:44px}';
    document.head.appendChild(st)}catch(e){console.error('[pclink] ios css',e)}
  try{
    ensureView();initIOSNavigation();
  }catch(e){console.error('[pclink] ios navigation boot',e)}
}
})();
