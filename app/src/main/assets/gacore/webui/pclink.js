/* pclink.js — 连接 PC 端 GA(hub) 的可选模块: 设置页配对 + 主界面切换 PC 会话视图.
   依赖 app.js 全局: t/I18N/applyI18n/gaModal/gaPrompt/gaConfirm/toast/md/$; py 侧 gacore/pclink.py.
   与 py 通信走 GA.send('/pclink.*') 的 job 模式(立即返回 {job} → /jobresult 轮询).
   v2.2(PLAN_PCLINK_UI): 消息区弃自造 DOM, 数据适配后复用 app.js renderMsgsInto 回放管线(A 轻集成, Boss 2026-08-08 拍板)
   — 气泡/步卡/执行过程折叠/最终回答卡/弹簧收展全部与主界面同源; 运行中 task=快照重渲(#031-F5, 不接活体状态机).
   ⚠ hub 契约: tsigOf 依赖 tk.i / s.n; 另嵌 lsdefine 5e67d8b 协议 —
   messages?detail=1&since=&sig= + 应答 nt(旧 hub 无 nt=给全量); seg?off= 断点续拉(旧 hub 忽略 off 给全量)。
   hub 若改语义, 客户端表现为「不刷新」而非报错。
   v2.3(#036 加固): 轮次令牌唯一化 arm 权 + tick 可停; 断线落显式「未连通」态; 退避封顶 6s/20s; 递归止损; 侧栏 keyed diff; sig 定期全量对账。
   v2.4(r15 会话管理+双开修): ① put 在飞闸+幂等键(ikey, 同文案重试同键, hub 侧可去重) —— 双击/超时重发不再翻倍建会话;
   ② d.new 发送后侦察新 peer 自动切入(newWatch), 超时也按「可能已送达」处理, 杜绝「电脑尚未接收」假阴性诱导重发;
   ③ 端側置顶/归档(pclink.peerMeta, 按 baseOf 键控, PC 重启改 -pid 后缀不丢): 长按行出操作单, 归档收进底部「已归档」组可恢复,
   纯端側 UI 态 —— 协议无删除面, PC 侧会话原样健在。 */
(function(){
'use strict';
if(typeof I18N!=='undefined'){
  Object.assign(I18N.zh,{pcLink:'链接 PC 端 GA',pcLinked:'已链接 PC 端 GA',pcPairTitle:'连接电脑',
    pcPairHint:'在电脑 GA → 设置 → 手机互联 出示二维码',pcPairing:'配对中…',pcPairOk:'配对成功',pcPairFail:'配对失败: ',
    pcScan:'扫码连接',pcManual:'手动输入 9 位码',pcScanCancel:'已取消扫码',pcScanBad:'无法识别二维码',
    pcScanNeedPerm:'需要相机权限才能扫码',pcScanNoCam:'当前版本不支持扫码',
    pcUnpair:'解除链接',pcUnpairAsk:'解除与 PC 端 GA 的链接？',pcView:'PC 会话',pcBack:'返回本机',
    pcNoPeer:'暂无 PC 会话',pcOffline:'未连接(自动重连中)',pcSend:'发送到 PC',pcAbort:'停止',pcAborted:'已发送停止',
    pcSent:'已发送',pcRunning:'运行中',grpPcLink:'PC 互联',pcNoMsgs:'还没有消息',
    pcConfigure:'请先配置 PC Link 服务',pcOn:'已连接',pcNotPaired:'未链接',pcPairSteps:'在电脑端 GA 打开「设置 → 手机互联」出示二维码，或打开 hub /pair 页面手输 9 位数字',
    pcIdle:'空闲',pcNoGet:'不可读取',pcMsgsUnit:'条消息',pcRetry:'重新检查',pcGone:'该会话已在电脑上关闭',
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
    pcNew:'新建会话',pcClose:'关闭会话',pcCloseAsk:'关闭会话并停止当前任务？',pcStarting:'正在启动…',pcNewReady:'新会话已就绪',pcSendMaybe:'已发出，等电脑确认…'});
  Object.assign(I18N.en,{pcLink:'Link PC GA',pcLinked:'PC GA linked',pcPairTitle:'Link computer',
    pcPairHint:'On PC: Settings → Link phone → show QR',pcPairing:'Pairing…',pcPairOk:'Paired',pcPairFail:'Pair failed: ',
    pcScan:'Scan QR',pcManual:'Enter 9-digit code',pcScanCancel:'Scan cancelled',pcScanBad:'Unrecognized QR',
    pcScanNeedPerm:'Camera permission required',pcScanNoCam:'QR scan not available',
    pcUnpair:'Unlink',pcUnpairAsk:'Unlink from PC GA?',pcView:'PC Sessions',pcBack:'Back to local',
    pcNoPeer:'No PC sessions',pcOffline:'Offline (reconnecting)',pcSend:'Send to PC',pcAbort:'Abort',pcAborted:'Abort sent',
    pcSent:'Sent',pcRunning:'running',grpPcLink:'PC Link',pcNoMsgs:'No messages yet',
    pcConfigure:'Configure PC Link service first',pcOn:'Connected',pcNotPaired:'Not linked',pcPairSteps:'On PC open Settings → Link phone for the QR, or hub /pair and type the 9 digits',
    pcIdle:'idle',pcNoGet:'no read access',pcMsgsUnit:'msgs',pcRetry:'Re-check',pcGone:'That session was closed on the computer',
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
    pcNew:'New session',pcClose:'Close session',pcCloseAsk:'Close this session and stop its task?',pcStarting:'Starting…',pcNewReady:'New session ready',pcSendMaybe:'Sent — waiting for the PC to confirm…'});
}
/* ---- 桥: /pclink.* 全部走 job 轮询(配对/网络可 30s+, 不能阻塞 WebView) ---- */
function call(cmd,onResult,maxTries,alive){
  let resp;try{resp=JSON.parse(GA.send(cmd)||'{}')}catch(e){return onResult({ok:0,error:'bridge'})}
  if(!resp.job)return onResult(resp);                       // 兼容直接返回
  let tries=0;const lim=maxTries||120;                      // 120*400ms=48s 上限
  const tick=()=>{if(alive&&!alive())return;                // 链主已换代(新轮/切 peer/关视图)即停: 僵尸 tick 不再拖着 48s 跨 JNI 尾巴
    let j;try{j=JSON.parse(GA.send('/jobresult '+resp.job)||'{}')}catch(e){return onResult({ok:0,error:'bridge'})}
    if(j.pending){if(++tries>lim)return onResult({ok:0,error:'timeout'});return setTimeout(tick,400)}
    let r;try{r=JSON.parse(j.result||'{}')}catch(e){r={ok:0,error:'parse'}}
    onResult(r)};
  setTimeout(tick,300)}
function api(method,path,body,onResult,alive){call('/pclink.api '+method+' '+path+(body?' '+JSON.stringify(body):''),onResult,0,alive)}
function track(ev,p){try{if(typeof GAT!=='undefined'&&GAT.emit)GAT.emit(ev,p||{})}catch(e){}}   // 埋点: 结果类事件(点击已被全局 ui_action 覆盖); err 只取短错误码不含配对码/消息内容
/* ---- 状态 ---- */
let paired=false,connected=false,timer=null,curPeer=null,lastSig=null;
let offlineSince=0;                                       // 短断线静默，持续 10s 才在顶栏提示；聊天始终保留
let idleRounds=0;                                           // 连续无变化轮数, 驱动自适应退避(见 arm)
let tok=0;                                                  // 轮次令牌: poll=链出生点 ++tok, 只有持最新令牌的链有权 arm/续 tick, 僵尸链静默退场
let sigAge=0;                                               // 距上次全量对账的轮数: hub sig 有盲区(末步等长改写/非末 task 变化/同形状重建), 定期弃 sig 自愈
let pendingPut=null;                                        // {n,ts,rounds}: 送达对账——PC 面板没开时 put 落 inbox 永不变 task,「已发送」需要一个反证出口
let putBusy=false;                                          // put 在飞闸: 双击=两次 put=PC 上两个会话(双开修 ①), 响应回来才解锁
let lastPut=null;                                           // {key,text,peer}: 幂等键——同 peer 同文案的重试沿用同键, hub 侧可判重(超时重发不翻倍)
let newWatch=null;                                          // {names:Set,rounds}: d.new 发送后的侦察——新 peer 出现即自动切入(任务长在新会话里, 在 d.new 上对账永远假阴性)
let knownNames=new Set();                                   // 上一轮 peers 名单(newWatch 的「之前就有」基线)
let archOpen=false;                                         // 侧栏「已归档」组展开态(会话级, 不落盘)
const isNew=p=>{const n=typeof p==='string'?p:(p&&p.name||'');return n==='d.new'||n.indexOf('d.new-')===0};
const PCWIDE=()=>{try{return matchMedia('(min-width:900px)').matches}catch(e){return false}};   // 宽屏(PC/平板): 侧栏常驻, 不再是抽屉
/* 上次真正看过的会话。hub 的 peer 行里没有任何时间戳(name/title/n_msgs/sig/caps/run 全集),
   「最近一条对话」在协议层不可判定 —— n_msgs 是体量(老会话恒大, 当"最近"用方向是反的),
   列表序只是 WS hello 的连接序。所以不猜: 端侧自己记账, 记的是「用户真看过的那条」。 */
const LP_KEY='pclink.lastPeer';
const isAgent=p=>!!p&&(p.caps||[]).indexOf('get')>=0;       // 无 get 能力的 peer(通知器/调度器)点进去必 501
const hasPid=n=>/-\d+$/.test(String(n||''));
const baseOf=n=>String(n||'').replace(/-\d+$/,'');          // hub 非 fixed peer 名 = `${name}-${pid}`, PC 重启即变名
let lpCache=null;                                           // {uid,val}: LP_KEY 常驻缓存——LS.get 每次 2 跳同步 JNI+kv 文件 IO, 不配进轮询热路;
                                                            // _nsKey 按登录 uid 翻命名空间 ⇒ 读时比对 _authUid(1 跳, 且 A/D 前置后只剩歧义态才走到)
function lastPeerSaved(){
  const u=typeof _authUid==='function'?_authUid():null;
  if(!lpCache||lpCache.uid!==u)lpCache={uid:u,val:LS.get(LP_KEY,null)||{}};
  return lpCache.val}
function pickPeer(ps){
  const ag=(ps||[]).filter(isAgent);if(!ag.length)return null;
  if(curPeer&&ag.some(p=>p.name===curPeer))return curPeer;                 // A 本次生命周期已选且仍在线
  if(ag.length===1)return ag[0].name;                                      // D 全场唯一(前置: 无歧义就不必碰 kv 缓存)
  const sv=lastPeerSaved();
  if(sv.name&&ag.some(p=>p.name===sv.name))return sv.name;                 // B 精确名(PC 未重启)
  if(sv.name&&hasPid(sv.name)){                                            // C 去 -pid 前缀唯一命中 = PC 重启后的复原
    const b=baseOf(sv.name),c=ag.filter(p=>hasPid(p.name)&&baseOf(p.name)===b);
    if(c.length===1)return c[0].name}
  return null}                                                            // E 有歧义 → 首页让用户自己挑, 不瞎猜
function rememberPeer(name){
  if(!name||(lpCache&&lpCache.val&&lpCache.val.name===name))return;   // 已记同名即跳: paint 流式期间每轮都来, 不值得每次 2 跳 JNI 重写
  lpCache={uid:typeof _authUid==='function'?_authUid():null,val:{name:name}};   // 缓存与 kv 同步双写, 读侧才允许常驻
  try{LS.set(LP_KEY,{name:name})}catch(e){}}
/* ---- 端側会话管理(置顶/归档): 协议无隐藏/删除面(hub 只有 get/seg/put/abort), 全部是手机本地 UI 态。
   键 = baseOf(name): PC 重启 peer 名换 -pid 后缀, 按 base 键控才不丢标记; 与 lastPeer 同一套 uid 命名空间+常驻缓存。 */
const PM_KEY='pclink.peerMeta';
let pmCache=null;                                           // {uid,val}: 同 lpCache 纪律, 轮询热路不打 kv
function peerMeta(){
  const u=typeof _authUid==='function'?_authUid():null;
  if(!pmCache||pmCache.uid!==u)pmCache={uid:u,val:LS.get(PM_KEY,null)||{}};
  return pmCache.val}
function metaOf(name){return peerMeta()[baseOf(name)]||{}}
function setMeta(name,patch){
  const all=peerMeta(),k=baseOf(name),cur=Object.assign({},all[k]||{},patch);
  if(!cur.pin)delete cur.pin;if(!cur.arch)delete cur.arch;
  if(Object.keys(cur).length)all[k]=cur;else delete all[k];   // 全默认即删键: 存底只留有态的行
  try{LS.set(PM_KEY,all)}catch(e){}}
/* ── 会话管理图标(lucide 线稿, 与全局图标语言一致) ── */
const IC_PIN='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1z"/></svg>';
const IC_PIN_OFF='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 17v5"/><path d="M15 9.34V7h1a2 2 0 0 0 0-4H7.89"/><path d="m2 2 20 20"/><path d="M9 9v1.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h11"/></svg>';
const IC_ARCH='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/></svg>';
const IC_RESTORE='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="m9 15 3-3 3 3"/><path d="M12 18v-6"/></svg>';
const IC_MORE='<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="12" cy="19" r="1.8"/></svg>';
const IC_CHEV='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>';
/* 行操作单(底部动作面板): 行尾 ⋯ 或长按/右键弹出。不用 gaModal 二键复用 —— cancel 语义会把
   「点空白关掉」误读成「归档」, 破坏性操作绝不能挂在 dismiss 路径上。
   结构: 拖拽把手 + 会话头(标题/peer·消息数) + 图标动作行 + 分隔取消, 全部 textContent 注标题(远端字符串不进 innerHTML)。 */
function rowSheet(p){
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
  w.querySelector('.pcSheetTt').textContent=p.title||p.name;
  w.querySelector('.pcSheetSub').textContent=p.name+(p.n_msgs?(' · '+p.n_msgs+' '+t('pcMsgsUnit')):'');
  document.body.appendChild(w);
  const close=()=>{w.classList.add('out');setTimeout(()=>w.remove(),160)};   // 出场镜像入场弹簧, 不闪断
  w.querySelector('#pcSheetMask').onclick=close;
  w.querySelector('.pcSheetCancel').onclick=close;
  const btns=w.querySelectorAll('.pcSheetIt');
  if(m.arch){btns[0].onclick=()=>{setMeta(p.name,{arch:0});close();track('pclink_meta',{op:'unarch'});pollNow()}}
  else{
    btns[0].onclick=()=>{setMeta(p.name,{pin:m.pin?0:1});close();track('pclink_meta',{op:m.pin?'unpin':'pin'});pollNow()};
    btns[1].onclick=()=>{setMeta(p.name,{arch:1,pin:0});close();track('pclink_meta',{op:'arch'});
      if(p.name===curPeer)setPeer(null);   // 归档当前会话: 回 PC 首页(视图态), PC 側会话原样健在
      pollNow()}}
  if(/^phone-\d+$/.test(p.name)){const b=document.createElement('button');b.className='pcSheetIt warn';b.textContent=t('pcClose');w.querySelector('.pcSheetCancel').before(b);
    b.onclick=()=>gaConfirm(t('pcClose'),t('pcCloseAsk'),()=>api('POST','/api/'+encodeURIComponent(p.name)+'/put',{text:'/exit'},r=>{if(r.error)return toast(r.error);close();if(curPeer===p.name)setPeer(null);pollNow()}),true)}
  const lb=w.querySelector('.pcSheetLlm');if(!lb)return;   // LLM 渠道切换: hub op llm(no=None 列表 / no=N 切换), 运行中 hub 回 busy
  api('GET','/api/'+encodeURIComponent(p.name)+'/llms',null,r=>{if(!r||!r.items||!lb.isConnected)return;
    r.items.forEach((nm,i)=>{const b=document.createElement('button');b.type='button';b.className='pcSheetIt';
      b.innerHTML='<span class="pcShIco">'+(i===r.cur?'●':'○')+'</span><span class="pcShTxt"></span>';b.querySelector('.pcShTxt').textContent=nm;
      b.onclick=()=>api('POST','/api/'+encodeURIComponent(p.name)+'/llm',{no:i},q=>{close();track('pclink_llm',{ok:!(q&&q.error)});
        q&&q.error?toast(''+q.error):toast(t('pcLlmOk')+nm);pollNow()});
      lb.appendChild(b)})})}
function bindLongPress(d,getPeer){
  let tm=null,fired=false;
  const cancel=()=>{if(tm){clearTimeout(tm);tm=null}};
  const fire=()=>{cancel();if(fired)return;fired=true;   // 安卓长按 contextmenu(~500ms)与 550ms 计时器都会到场: 先到即消费, 后到不重弹
    const p=getPeer();if(p&&!isNew(p))rowSheet(p)};
  d.addEventListener('contextmenu',e=>{e.preventDefault();fire()});          // 宽屏右键/安卓长按的系统事件
  d.addEventListener('touchstart',()=>{fired=false;tm=setTimeout(fire,550)},{passive:true});
  d.addEventListener('touchmove',cancel,{passive:true});
  d.addEventListener('touchend',e=>{cancel();if(fired){e.preventDefault()}},{passive:false});   // 长按已弹单: 松手不再触发 click 选中
  d.addEventListener('touchcancel',cancel,{passive:true})}
let lastPs=[];                                              // 上一轮 peers 全量(归档组头点击重渲用, 不跨轮当真相)
let segTxt={};                                              // 'i/j' -> {txt,n}: seg 正文缓存(n=字节数; off 续拉累积; selPeer 清空)
let taskSnap=[];                                            // 当前 peer 全量 tasks 快照(since 切片合并后的权威序, 供 paint/tsig)
let peerRun=false;                                          // 当前 peer 运行态(messages.run), 驱动发送↔停止双态
let gen=0;                                                  // 世代守卫(#032-F2): pullMsgs 自增, 在飞回调世代不符即弃 → 切 peer 不串画/不错段, 并发轮询幂等去重(F6)
let configError='';
function refreshStatus(cb,resume){call(resume?'/pclink.resume':'/pclink.status',r=>{configError=!r||!r.ok?String(r&&r.error||'PC Link status unavailable'):(r.configured===false?t('pcConfigure'):'');paired=!!(r&&r.paired);connected=!!(r&&r.connected);renderRow();showFab();
  if(document.getElementById('pcHdSub'))setPcHd(undefined,curPeer||'',peerRun);cb&&cb(r)})}
/* ---- 设置页行(动态注入 homePanel 末尾, 不改 index.html 结构) ---- */
function renderRow(){
  const home=document.getElementById('homePanel');if(!home)return;
  let sec=document.getElementById('pcLinkSec');
  if(!sec){sec=document.createElement('div');sec.id='pcLinkSec';
    sec.innerHTML='<div class="secLbl"><span data-i18n="grpPcLink"></span></div><div class="card icoCard">'+
      '<button class="row rowBtn" id="pcLinkRow"><span class="rowIco ic-blue">'+
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>'+
      '</span><span class="k" id="pcLinkK"></span><span class="v"><span id="pcLinkV" class="vMut"></span>'+
      '<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg></span></button></div>';
    const ganetSec=document.getElementById('ganetHomeSec');
    if(ganetSec)home.insertBefore(sec,ganetSec);else home.appendChild(sec);applyI18n();
    document.getElementById('pcLinkRow').onclick=onRowTap}
  document.getElementById('pcLinkK').textContent=t(paired?'pcLinked':'pcLink');
  // 状态用词而非一个「●」: 已连/重连中/未链接三态各有下一步动作, 单字符既读不出也念不出(读屏)。
  // 配色复用设置页既有的 .a11yValOn/.a11yValOff, 不引入新色。
  const v=document.getElementById('pcLinkV');
  const key=paired?(connected?'pcOn':'pcOffline'):'pcNotPaired';
  v.textContent=configError||t(key);v.className=paired&&connected?'a11yValOn':(paired?'a11yValOff':'vMut')}
function parsePairPayload(raw){
  raw=String(raw||'').trim();
  const m=raw.match(/^ga-pclink:v1:(\d{9})$/i);
  if(m)return m[1];
  const digits=raw.replace(/\D/g,'');
  return digits.length===9?digits:null}
function doPair(code,via){
  toast(t('pcPairing'));
  call('/pclink.pair '+code,r=>{
    if(r&&r.ok){paired=connected=true;renderRow();showFab();track('pclink_pair',{ok:true,via:via||'?'});toast(t('pcPairOk'))}
    else{const e=String((r&&r.error)||'?');track('pclink_pair',{ok:false,err:e.slice(0,40)});
      toast(t('pcPairFail')+e.split('(')[0].slice(0,60))}})}
function startScan(){
  if(typeof GA==='undefined'||!GA.scanQr){toast(t('pcScanNoCam'));return}
  window.gaQrResult=function(text){
    try{delete window.gaQrResult}catch(e){window.gaQrResult=undefined}
    if(!text){toast(t('pcScanCancel'));return}
    const code=parsePairPayload(text);
    if(!code){toast(t('pcScanBad'));return}
    doPair(code,'qr')};
  let r='err';try{r=GA.scanQr()}catch(e){r='err'}
  if(r==='need-perm')toast(t('pcScanNeedPerm'));
  else if(r&&String(r).indexOf('err')===0)toast(t('pcPairFail')+r)}
function openManualPair(){
  gaModal({title:t('pcManual'),msg:t('pcPairSteps'),input:t('pcPairHint'),value:'',onOk:v=>{
    const code=parsePairPayload(v);
    if(!code)return toast(t('pcPairFail')+'9?');
    doPair(code,'manual')}})}
function onRowTap(){
  if(configError){toast(configError);if(typeof openIntegrations==='function')openIntegrations();return}
  if(paired){gaConfirm(t('pcUnpair'),t('pcUnpairAsk'),()=>call('/pclink.unpair',r=>{paired=connected=false;renderRow();showFab();track('pclink_unpair');toast(t('pcUnpair'))}),true);return}
  gaModal({title:t('pcPairTitle'),msg:t('pcPairHint'),okText:t('pcScan'),cancelText:t('pcManual'),
    onOk:()=>startScan(),onCancel:()=>openManualPair()})}
/* ---- 主界面悬浮切换钮(已配对才显示) ---- */
/* 两枚图形不带 width/height: 同一份 SVG 有两处消费者(44px 悬浮钮 20px / 锁定组 --lkTile 派生),
   带上属性就成了「CSS 没生效时静默回退到 20px」的暗门。尺寸由 app.css 的 #pcFab svg 与 .pcLinkPc svg 各自明写。 */
const SVG_PC='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>';
const SVG_PHONE='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="7" y="2" width="10" height="20" rx="2.5"/><line x1="11" y1="18.5" x2="13" y2="18.5"/></svg>';
/* pcHero 顶部的配对锁定组(首页/断线两态同一段标记, 差异全在 CSS 的 .pcHeroOff)。
   纯装饰: 状态语义由同屏 h2/p 文本承担, 故整组 aria-hidden, 不引入新文案键。
   尺寸不在这里写 —— 片/连线/图标几何由 app.css 的 .pcLink2{--lkTile} 单点派生。 */
const LOCKUP='<div class="pcLink2" aria-hidden="true"><span class="pcLinkTile pcLinkGa">GA</span>'+
  '<span class="pcLinkWire"></span><span class="pcLinkTile pcLinkPc">'+SVG_PC+'</span></div>';
function showFab(){
  try{localStorage.setItem('ga.pcPaired',paired?'1':'0')}catch(e){}   // 缓存配对态: 下次冷启动即时乐观显钮, 不等 /pclink.status 往返
  let b=document.getElementById('pcFab');
  document.body.classList.toggle('pcHubFabOn',paired);
  if(!paired){if(b)b.remove();return}
  if(!b){b=document.createElement('button');b.id='pcFab';b.setAttribute('aria-label','PC');
    b.innerHTML='<span class="fi fiPc" aria-hidden="true">'+SVG_PC+'</span><span class="fi fiPh" aria-hidden="true">'+SVG_PHONE+'</span>';   // #035: 单钮双态(切换开关的第一性: 一钮两态, 弃 pcBack 双钮), CSS .rc 交叉旋转淡换
    b.onclick=()=>{const v=document.getElementById('pcView');if(v&&v.classList.contains('on'))closeView();else openView()};
    document.body.appendChild(b);syncFab()}}
function syncFab(){   // #035-监察修: fab 双态/隐藏 + 汉堡 aria-expanded 的单一事实源=镜像 pcView 类(覆盖 gaOnBack 直改 class 等一切路径; 弃 :has 兼容险)
  const v=document.getElementById('pcView');if(!v)return;
  const on=v.classList.contains('on'),side=v.classList.contains('side');
  // 读屏态跟着类走: openView/closeView/选中会话/gaOnBack 都只改 class, 散写 aria-expanded 必漏 —— 收进这里(MutationObserver 驱动)才是结构保证
  const mb=v.querySelector('#pcMenuBtn');if(mb)mb.setAttribute('aria-expanded',String(side));
  const b=document.getElementById('pcFab');if(!b)return;
  // 宽屏侧栏常驻, .side 无意义 —— 此时绝不能藏出口钮(否则唯一的返回入口消失)
  b.classList.toggle('rc',on);b.classList.toggle('hid',!PCWIDE()&&side);
  b.setAttribute('aria-label',on?t('pcBack'):'PC')}
function edgeFx(kind){   // #035: 世界切换边缘光晕(进=主题色向内扩散, 出=暖色收拢回边缘), 纯装饰层 pointer-events:none
  let f=document.getElementById('pcEdgeFx');
  if(!f){f=document.createElement('div');f.id='pcEdgeFx';document.body.appendChild(f)}
  f.className='';void f.offsetWidth;f.className=kind}
/* ---- PC 会话视图(全屏覆盖层): 侧栏会话(scrim 点击可关) + 主管线消息区 + .cap 输入胶囊 + 同位返回 FAB ---- */
let pcVoice=null;   // GAVoice 归属句柄(ensureView 里绑定)
function ensureView(){
  let v=document.getElementById('pcView');if(v)return v;
  v=document.createElement('div');v.id='pcView';
  v.innerHTML='<div class="pcHd"><button class="iconbtn" id="pcMenuBtn" data-i18n-aria="pcView" aria-label="PC 会话" aria-expanded="false" aria-controls="pcSide">'+
      '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg></button>'+
      // 品牌回归: #pcView 是不透明整屏覆盖层, 带 .gaLogo 的 #hdr 被整块盖住 → 在这里补一枚字标。
      // 硬不变量(Boss): 两视图切换字标不许跳——样式就是同一 .gaLogo(负片变体已删), 几何由 app.css 的
      // #hdr,.pcHd / #hdrtitle,.pcHdMid 共享规则保证逐像素重合;「在 PC 那侧」由副标题 peer 名+连接态承担。
      '<div class="pcHdMid"><span class="gaLogo" aria-hidden="true">GA</span>'+
      '<span class="pcHdCol"><b id="pcHdTitle" data-i18n="pcView">PC</b><span id="pcHdSub" class="pcHdSub" aria-live="polite"></span></span></div>'+
      '<span class="pcHdSp"></span><button class="iconbtn" id="pcNewBtn" data-i18n-aria="pcNew"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg></button></div>'+   // 头部 ✕ 移除: 出口唯一化=左下同位返回 FAB(Boss B6: 与进入按钮同位置)
    '<div class="pcBodyWrap"><div id="pcScrim"></div><div id="pcSide"></div><div id="pcMain"><div id="pcMsgs"></div>'+
      '<button id="pcDown" hidden aria-label="scroll to bottom"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg></button>'+
      '<div id="pcInBar"><div class="cap" id="pcCap"><textarea id="pcIn" rows="1" data-i18n-ph="pcSend" data-i18n-aria="pcSend" aria-label="send"></textarea>'+
      '<div class="captools"><span class="sp"></span><button class="cIcon vBtn" id="pcVoiceBtn" aria-label="语音输入"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/></svg></button><button id="pcBtn" aria-label="send">'+
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="6 11 12 5 18 11"/></svg></button></div></div></div></div></div>';   // #035: pcBack 移除, 出口=同一 #pcFab 双态钮
  document.body.appendChild(v);
  applyI18n();   // 模板占位符走 data-i18n-ph(切语言即时刷新, 对齐 #in)
  v.querySelector('#pcNewBtn').onclick=e=>{const b=e.currentTarget;b.disabled=true;api('POST','/api/sessions',{},r=>{b.disabled=false;if(r.error)return toast(r.error);toast(t('pcStarting'));pollNow()})};
  const _ta=v.querySelector('#pcIn');
  _ta.addEventListener('input',()=>{_ta.style.height='auto';_ta.style.height=Math.max(24,Math.min(_ta.scrollHeight,120))+'px'});   // 自动增高镜像 #in, 上限=CSS max-height 120
  v.querySelector('#pcMenuBtn').onclick=()=>v.classList.toggle('side');   // aria-expanded 由 syncFab 统一同步(见下 MutationObserver), 此处只翻类
  v.querySelector('#pcScrim').onclick=()=>v.classList.remove('side');     // B1: 点侧栏外区域关闭(对齐 #mask 范式)
  // 宽屏切换: 进宽屏必须清 .side, 否则 syncFab 会把唯一出口 FAB 藏掉(#pcFab.hid)。
  // CSS 断点是真相源, 这里只负责把 JS 侧的状态位拨回一致。
  try{const mq=matchMedia('(min-width:900px)');const onMq=()=>{if(mq.matches)v.classList.remove('side')};
    mq.addEventListener?mq.addEventListener('change',onMq):mq.addListener(onMq);onMq()}catch(e){}
  v.querySelector('#pcBtn').onclick=()=>{if(peerRun)doAbort();else doPut()};
  // 语音输入复用主界面同一状态机(voice.js GAVoice.bind): 识别文字写进 #pcIn; voice.js 未加载/旧 WebUI 无 bind 则藏键不留死按钮
  {const vb=v.querySelector('#pcVoiceBtn');pcVoice=(window.GAVoice&&GAVoice.bind)?GAVoice.bind(vb,{input:()=>document.getElementById('pcIn')}):null;if(!pcVoice)vb.hidden=true}   // run 双态: idle=发送 / running=停止(真实 /abort 通道, 替代旧永 hidden 死代码)
  const box=v.querySelector('#pcMsgs');
  box.addEventListener('click',e=>{   // 懒拉钩子(capture): 点开非末步 → off 续拉 seg 回填(c._text + sb._rendered=false + renderBody)
    const c=e.target&&e.target.closest?e.target.closest('.step'):null;if(!c||c._pcGot||c.dataset.pcj==null)return;
    const tb=c.closest('.task');if(!tb||tb.dataset.pci==null)return;
    const i=tb.dataset.pci,j=c.dataset.pcj,p=curPeer;c._pcGot=1;
    const fill=txt=>{c._text=txt;const sb=c.querySelector('.sb');if(sb)sb._rendered=false;try{renderBody(c)}catch(e2){}};
    const n=+(c.dataset.pcn||0);
    fetchSeg(i,j,n,p,gen,ok=>{if(p!==curPeer)return;const got=segTxt[i+'/'+j];if(ok&&got)fill(got.txt);else c._pcGot=0})},true);
  new MutationObserver(syncFab).observe(v,{attributes:true,attributeFilter:['class']});   // #035-监察修: on/side 任意来源变更都同步 fab 与汉堡 aria-expanded
  const dn=v.querySelector('#pcDown');
  box._pcStick=true;box._pcPinSeq=0;box._pcUserScroll=false;let pcUserTimer=0;
  const nearBottom=()=>box.scrollHeight-box.scrollTop-box.clientHeight<=4;   // 只容忍像素取整误差; 用户哪怕稍微上滚也立即进入阅读态
  const userIntent=()=>{box._pcUserScroll=true;box._pcPinSeq++;clearTimeout(pcUserTimer);pcUserTimer=setTimeout(()=>{box._pcUserScroll=false},240)};
  box.addEventListener('wheel',userIntent,{passive:true});
  box.addEventListener('touchmove',userIntent,{passive:true});
  box.addEventListener('keydown',e=>{if(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(e.key))userIntent()});
  box.addEventListener('pointerdown',e=>{const r=box.getBoundingClientRect();if(e.clientX>=r.right-20)userIntent()},{passive:true});   // 只把拖滚动条算滚动意图, 普通点按内容不切态
  box.addEventListener('scroll',()=>{
    if(box._pcUserScroll){box._pcStick=nearBottom();if(box._pcStick){box.style.setProperty('--pcTail','0px');box.scrollTop=box.scrollHeight}clearTimeout(pcUserTimer);pcUserTimer=setTimeout(()=>{box._pcUserScroll=false},240)}
    pcSyncDown(box);scheduleVisible()});
  window.addEventListener('resize',scheduleVisible);
  dn.onclick=()=>{box._pcStick=true;box._pcPinSeq++;box.style.setProperty('--pcTail','0px');box.scrollTop=box.scrollHeight};
  return v}
/* 入口必须是干净的: 侧栏永不自动弹出。
   旧写法 `if(!curPeer)add('side')` 与 round() 里「!curPeer 时自动选 ps[0]」是一对矛盾 ——
   自动选中之后没有任何一处 remove('side'), 抽屉就此挂着不关; 而侧栏一开 syncFab 又把唯一出口 FAB 藏掉,
   于是「入口不干净」被放大成「入口像卡住了」。现在: 能确定复原上次那条对话就直进对话, 不能确定就落 PC 首页。 */
function openView(){const v=ensureView();v.classList.add('on');v.classList.remove('side');
  track('view_enter',{view:'pclink'});   // 与 app.js view_enter 同口径: PC 会话视图使用频次
  edgeFx('in');   // #035: 入场边缘光(fab 双态由 MutationObserver syncFab 统一驱动)
  lastSig=null;idleRounds=0;   // 重开同一会话只对账，不丢快照、正文或阅读位置
  const box=document.getElementById('pcMsgs');if(box&&!box.firstElementChild)skel(box);
  const side=document.getElementById('pcSide');if(side&&!side.querySelector('.pcRow'))skelSide(side);   // 同上: 上一屏的名单留着(断线时它是唯一还能看的东西), 只在真没内容时铺骨架
  refreshStatus(null,true);pollNow()}
function closeView(){const v=document.getElementById('pcView');if(!v||!v.classList.contains('on'))return;
  v.classList.remove('on','side');
  if(window.GAVoice&&pcVoice)GAVoice.stop(pcVoice);   // 离开 PC 视图: 只收 PC 自己持有的麦, 不误伤主界面
  edgeFx('out');   // #035: 出场边缘光(与入场异色异向; fab 翻态走 syncFab)
  gen++;tok++;   // 在飞回调作废(gen)+在飞轮次褫夺 arm 权(tok): 否则关闭瞬间那轮回来仍会 prefetch(烧 P2P 流量)、画进已隐藏的 #pcMsgs, 还经 arm 抢回定时器
  const box=document.getElementById('pcMsgs');if(box)box._pcPinSeq=(box._pcPinSeq||0)+1;   // 取消隐藏后仍会执行的 rAF/timeout 滚动事务
  newWatch=null;   // 侦察不跨视图生命周期: rounds 只在轮询里走, 留着它改天重开视图会对着无关的新会话代跳(Monitor C-2)
  if(timer){clearTimeout(timer);timer=null}}
/* 顶栏标题两行: 上=会话标题(hub 的 r.title, 即最后一条用户输入), 下=「peer 名 · 连接态」。
   旧版把一句被居中截断的用户 prompt 当顶栏, 既无品牌也无 peer 名, 更看不出连不连得上。 */
function setPcHd(title,peer,run){
  const b=document.getElementById('pcHdTitle'),s=document.getElementById('pcHdSub');
  if(b&&title!==undefined)b.textContent=title||peer||t('pcView');
  if(!s)return;
  if(connected)offlineSince=0;else if(!offlineSince)offlineSince=Date.now();
  const st=connected?(run?t('pcRunning'):t('pcOn')):(Date.now()-offlineSince>=10000?t('pcOffline'):'');
  const txt=peer?(peer+(st?' · '+st:'')):st;
  if(s.textContent!==txt)s.textContent=txt;   // 变更守卫: aria-live 不该被每轮轮询刷屏
  s.classList.toggle('busy',connected&&!!run)}
function setRunBtn(run){peerRun=!!run;
  const vb=document.getElementById('pcVoiceBtn');   // 停止态不显示麦克风: 麦与停止键相邻, 点歪=误中止 PC 任务; 发送态点歪无害(空消息 doPut 直接 return)
  if(vb){vb.hidden=peerRun||!pcVoice;if(peerRun&&window.GAVoice&&pcVoice)GAVoice.stop(pcVoice)}   // 录音中转入运行: 按钮消失的同时收麦, 不留隐形录音
  const b=document.getElementById('pcBtn');if(!b)return;
  b.classList.toggle('stop',peerRun);b.setAttribute('aria-label',t(peerRun?'pcAbort':'pcSend'));
  b.innerHTML=peerRun?'<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>'
    :'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="6 11 12 5 18 11"/></svg>'}
/* put 全链防双开(v2.4): ① putBusy 在飞闸挡双击; ② 幂等键 ikey —— 同 peer 同文案的重试沿用同一键
   (hub ≥r15 判重, 老 hub 忽略, 至少一次→至多一次); ③ d.new(新建入口)的送达真相在**新 peer 出现**而不在
   d.new 自己的任务数 —— 起 newWatch 侦察, 命中即自动切入新会话; 超时(hub 15s < 建会话耗时)按
   「可能已送达」处理: 文案留框但不诱导重发, watch 命中会代为清框。 */
function doPut(){if(window.GAVoice)GAVoice.stop();   // 发送前先关麦(对齐主界面 submit): 残余识别文字不许回灌已清空的输入框
  const ta=document.getElementById('pcIn');const txt=(ta.value||'').trim();if(!txt||!curPeer||putBusy)return;
  const toNew=isNew(curPeer);
  const key=(lastPut&&lastPut.text===txt&&lastPut.peer===curPeer)?lastPut.key
    :('ik'+Date.now().toString(36)+Math.random().toString(36).slice(2,8));
  lastPut={key:key,text:txt,peer:curPeer};
  putBusy=true;const btn=document.getElementById('pcBtn');if(btn)btn.classList.add('busy');
  api('POST','/api/'+encodeURIComponent(curPeer)+'/put',{text:txt,ikey:key},r=>{
    putBusy=false;if(btn)btn.classList.remove('busy');
    const err=r&&r.error?String(r.error):'';
    if(err&&!(toNew&&/timeout|busy \(>/i.test(err))){   // d.new 超时 ≠ 失败: hub 已把消息送进 WS, 只是建会话超了 15s 应答窗
      track('pclink_send',{ok:false,kind:'put',err:err.slice(0,40)});return toast(err)}
    track('pclink_send',{ok:!err,kind:'put',maybe:!!err});
    if(!err)lastPut=null;   // 确认成功即弃键: ikey 只护「失败重试」窗口——用户故意连发两遍同文案是两条新消息, 不许被 hub 判重吞掉
    if(toNew){
      newWatch={names:new Set(knownNames),rounds:0,text:txt};   // 基线=发送前名单, 新面孔=PC 为这条消息建的会话; text 供命中时只清自己那份草稿
      if(!err){ta.value='';ta.style.height='auto'}          // 确认送达才清框; 超时留框(watch 命中代清), 但不再喊「失败」
      toast(t(err?'pcSendMaybe':'pcSent'))}
    else{
      pendingPut={n:taskSnap.length,ts:Date.now(),rounds:0};   // 送达对账基线: tasks 长过这个数=真被接收(paint 关账)
      ta.value='';ta.style.height='auto';toast(t('pcSent'))}
    pollNow()})}
function doAbort(){if(curPeer)api('POST','/api/'+encodeURIComponent(curPeer)+'/abort',{},r=>{track('pclink_send',{ok:!(r&&r.error),kind:'abort'});
  r&&r.error?toast(''+r.error):toast(t('pcAborted'))})}   // 失败要说失败: 恒报「已发送停止」会让停不下来的任务显得像 app 坏了
/* ---- 轮询: peers → 侧栏; messages(detail+since+sig, nt 回退安全) → seg?off= 预拉末步 → 主管线分片增量重渲(自臂链) ----
   R1 单出口不变量(PLAN_CHATPOLISH §4): 一轮 = poll() 起、done()=arm() 终, 链上任何分支(成败/陈旧/无 peer)只准 return done(),
   不得自行 arm/不得吞掉 done —— 「每轮必 re-arm」是结构保证而非人肉纪律; arm() 的视图守卫是唯一熄火点。
   令牌修订: 并发轮次(6 处 pollNow 都能开新链)由 tok 串行化 —— done 里 my===tok 才 arm, 被换代的链 done 退化为 no-op、
   tick 被 alive 掐停; arm 权始终恰有一个持有者, 单出口语义在「活链」上成立, 僵尸链只跑完不再点火。 */
/* 自适应节流: 固定 10s 空闲间隔意味着「PC 刚开一个新会话」最坏要 10s+一轮往返才看得见, 观感就是"不实时"。
   改成跟着变化率走 —— 刚有过变化就贴身跟(1.2s), 连续无变化才逐步退避: 有会话封顶 6s;
   无 curPeer 的守望态(首页/断线未选中)每轮都是 2 跳 JNI + hub 唤醒 PC 全部 agent 跑 _build, 封顶放陡到 20s。运行中恒 1.5s。 */
function nextDelay(){
  if(peerRun)return 1500;
  return Math.min(curPeer?6000:20000,1200*Math.pow(2,Math.max(0,idleRounds-1)))}
function arm(){if(timer)clearTimeout(timer);const v=document.getElementById('pcView');if(!v||!v.classList.contains('on'))return;timer=setTimeout(poll,nextDelay())}
/* 渲染层抛异常不得吃掉本轮的 done —— 否则 arm() 永不执行、轮询链彻底熄火, 表现为「页面再也不刷新」且无任何线索。
   本轮刚在真机上被一次 sideRow 漏写 class 的 null 解引用打中: 侧栏只剩标题、主区全空、链死。
   失败半径大, 所以显式兜住并如实报到控制台; 单轮渲染失败下一轮自愈。 */
function guard(fn,done){try{fn()}catch(e){console.error('[pclink]',e);done()}}
function poll(){
  const my=++tok;                                           // 本链令牌: 此后任何新 poll/closeView 都会换代, 旧链从此只跑完不 arm
  if(timer){clearTimeout(timer);timer=null}
  round(()=>{if(my===tok)arm()})}
function pollNow(){idleRounds=0;sigAge=0;poll()}            // 即时轮=用户注意力回焦: 退避与 sig 对账一起归零
function round(done){
  const my=tok,alive=()=>my===tok;                     // poll ++tok 后同步进场, my 即本链令牌; 换代后本链所有 tick 停在下一拍
  api('GET','/api/peers','',ps=>guard(()=>{
    if(!ps||ps.error||!Array.isArray(ps)){             // 断线只更新状态，不撤走已有聊天；发送失败仍由操作回调反馈
      connected=false;idleRounds++;renderRow();setRunBtn(false);   // 运行态一并放下: 断线没有可信的 run, 也不该以 1.5s 空转
      setPcHd(undefined,curPeer||'',false);renderOffline();return done()}
    if(!connected){connected=true;renderRow()}         // 成功出口顺手校正: refreshStatus 只在进场/回前台采样, 断续之间靠这里
    // 选中的会话在电脑上消失了(进程重启 ⇒ peer 名里的 pid 变了, 或用户关了它)。
    // 旧代码只在 !curPeer 时才选 peer, 于是 curPeer 会一直指向一个不存在的 peer:
    // pullMsgs 拿到 404 offline 后走静默 return done(), 页面永久冻结在旧画面上 —— 这正是「PC 明明在跑却不刷新」。
    if(curPeer&&!ps.some(p=>p.name===curPeer))setPeer(null);
    // 会话排序三层: d.new(新建入口)恒顶 → 端側置顶(peerMeta.pin) → ts 倒序(会话 updated_at, 桌面 0.1.19+;
    // 无 ts 的旧桌面全为 0, 稳定排序保持原序不劣化)。
    ps.sort((a,b)=>((isNew(b)?1:0)-(isNew(a)?1:0))
      ||((metaOf(b.name).pin?1:0)-(metaOf(a.name).pin?1:0))
      ||((b.ts||0)-(a.ts||0)));
    // d.new 侦察(v2.4): 发送后新面孔 = PC 为那条消息建的会话 → 自动切入(送达真相在这, 不在 d.new 的任务数)。
    if(newWatch){
      const cand=ps.filter(p=>isAgent(p)&&!isNew(p)&&!newWatch.names.has(p.name)&&!metaOf(p.name).arch);
      if(cand.length){
        cand.sort((a,b)=>(b.ts||0)-(a.ts||0));
        const nm=cand[0].name,sent=newWatch.text;newWatch=null;lastPut=null;
        const ta=document.getElementById('pcIn');   // 只清「超时留框的那份」: 框里已是用户新草稿就不许动(Monitor C-2)
        if(ta&&ta.value&&ta.value.trim()===sent){ta.value='';ta.style.height='auto'}
        knownNames=new Set(ps.map(p=>p.name));
        toast(t('pcNewReady'));
        if(!curPeer||isNew(curPeer)){selPeer(nm);return done()}   // 只有还停在 d.new/首页才代跳; 用户已自行去了别的会话就不抢焦点
        }
      else if(++newWatch.rounds>12){newWatch=null;lastPut=null}}   // ~12 轮(贴身节奏 ≈15s)没长出来 = 判「PC 未收」;
      // 同时弃幂等键(Monitor C-1) —— 判了未收却留着键, 用户重发会被 hub 判重回假成功, 消息就真丢了。
      // 若其实是 PC 慢(判错), 重发最坏多建一个会话 —— 比静默丢消息便宜得多。
    knownNames=new Set(ps.map(p=>p.name));
    const vis=ps.filter(p=>!metaOf(p.name).arch);       // 归档会话不参与自动选中与首页挑选(用户显式藏起的东西不许自己弹回来)
    const pick=pickPeer(vis);
    if(pick&&pick!==curPeer)setPeer(pick);
    renderSide(ps);                                   // 侧栏拿全量(它要渲染「已归档」组); 选完再画: .cur 一次就标对
    if(!curPeer){idleRounds++;renderHome(vis);return done()}   // 守望态也计退避: 不许 1.2s 空转唤醒 PC 全部 agent
    pullMsgs(done,0,alive)},done),alive)}
function setPeer(name){   // 切换会话的唯一入口: 世代+缓存+快照+签名一起翻, 保证不串画不错段。
  // tok 故意不在这里翻: round 链内也会走到(自动选中/peer 消失), 翻了本链 done 即丢 arm 权 → 轮询熄火;
  // 用户显式切换走 selPeer→poll, 新令牌在链出生点发, 数据陈旧性由 gen 单独兜住。
  curPeer=name||null;gen++;lastSig=null;sigAge=0;segTxt={};taskSnap=[];idleRounds=0;pendingPut=null;
  const b=document.getElementById('pcMsgs');if(b){
    b._pcPinSeq=(b._pcPinSeq||0)+1;   // 取消旧 peer 的延迟贴底/顶置事务；否则切换后旧 timeout 会把新会话拽走
    b._pcStick=true;b._pcUserScroll=false;b.style.setProperty('--pcTail','0px');   // 阅读态/尾垫属于 peer，不得从上一会话泄漏
    if(name)skel(b)}}
/* 侧栏按 p.name 做 keyed diff: 每轮 innerHTML 全量重建会把焦点打回 body(读屏/键盘不可用)且整页在抖。
   会话行复用 drawer 的 .dwItem 语言(.cur 左缘 acc / .cst 状态点), 两行: 标题 + 「peer · N 条消息 · 状态」。 */
function sideRow(p){   // 首建一行: dataset.peer 即 diff 键; 可变部分全在 sideSync, 节点跨轮常驻
  const d=document.createElement('button');d.type='button';d.dataset.peer=p.name;d.className='dwItem rowBtn pcRow';
  const st=document.createElement('span');st.className='cst';st.appendChild(document.createElement('i'));d.appendChild(st);   // 类必须首建就有: sideSync 靠 .cst 定位它
  const mid=document.createElement('span');mid.className='pcRowMid';
  const tl=document.createElement('span');tl.className='pcRowTt';   // 标题行 = [置顶针][标题]: 针是独立节点, 标题仍走 textContent(不互相抹)
  const pin=document.createElement('span');pin.className='pcPinIc';pin.setAttribute('aria-hidden','true');pin.innerHTML=IC_PIN;tl.appendChild(pin);
  const tt=document.createElement('span');tt.className='t';tl.appendChild(tt);mid.appendChild(tl);
  const sb=document.createElement('span');sb.className='pcRowSub';mid.appendChild(sb);d.appendChild(mid);
  // 可见操作入口(发现性): 行尾 ⋯ 常驻, 长按/右键保留为快捷路径。行本身是 <button>, 内嵌只能用 role=button 的 span。
  const more=document.createElement('span');more.className='pcRowMore';more.setAttribute('role','button');
  more.setAttribute('tabindex','0');more.setAttribute('aria-label','\u22ef');more.innerHTML=IC_MORE;
  more.onclick=e=>{e.stopPropagation();const pp=d._peer;if(pp&&!isNew(pp))rowSheet(pp)};
  d.appendChild(more);
  d.onclick=()=>{if(d.getAttribute('aria-disabled'))return;   // 常绑+态判: caps 轮间可变, 点击权跟着 aria-disabled 走而不是跟着重建走
    selPeer(d.dataset.peer);if(!PCWIDE())document.getElementById('pcView').classList.remove('side')};
  bindLongPress(d,()=>d._peer);   // 长按/右键 → 置顶/归档操作单(d.new 入口除外, rowSheet 内部拦)
  return d}
function sideSync(d,p){
  d._peer=p;   // rowSheet 取最新行数据(title/caps 轮间可变)
  const usable=isAgent(p),m=metaOf(p.name);   // hub 会把通知器/调度器这类无 get 能力的 peer 也列进来, 点它必然 501 而 pullMsgs 静默吞掉 → 标灰禁用
  d.className='dwItem rowBtn pcRow'+(p.name===curPeer?' cur':'')+(usable?'':' off')
    +(m.arch?' arch':'')+(m.pin&&!m.arch?' pin':'')+(isNew(p)?' new':'');   // pin/new 态给 CSS: 针形显隐 + d.new 无 ⋯
  if(p.name===curPeer)d.setAttribute('aria-current','true');else d.removeAttribute('aria-current');
  if(usable)d.removeAttribute('aria-disabled');else d.setAttribute('aria-disabled','true');
  d.querySelector('.cst').className='cst '+(p.run?'run':(usable?'done':'wait'));
  const tt=d.querySelector('.t'),tv=p.title||p.name;
  if(tt.textContent!==tv)tt.textContent=tv;
  const bits=[p.name];
  if(p.n_msgs)bits.push(p.n_msgs+' '+t('pcMsgsUnit'));
  if(p.llm)bits.push(p.llm);
  bits.push(p.run?t('pcRunning'):(usable?t('pcIdle'):t('pcNoGet')));
  const sv=bits.join(' · '),sb=d.querySelector('.pcRowSub');if(sb.textContent!==sv)sb.textContent=sv}
function syncArchHd(hd,n){
  hd.classList.toggle('open',archOpen);   // 箭头旋转交给 CSS transition, 不重建节点
  const nb=hd.querySelector('.pcArchN'),lb=hd.querySelector('.pcArchLb');
  if(lb.textContent!==t('pcArchived'))lb.textContent=t('pcArchived');
  const nv=String(n);if(nb.textContent!==nv)nb.textContent=nv}
function buildArchHd(){
  const ah=document.createElement('button');ah.type='button';ah.className='pcArchHd';
  ah.innerHTML='<span class="pcArchChev" aria-hidden="true">'+IC_CHEV+'</span>'
    +'<span class="pcArchLb"></span><span class="pcArchN"></span>';
  return ah}
function renderSide(ps){
  const el=document.getElementById('pcSide');if(!el)return;
  el.classList.remove('pcSideOff');   // 有一轮成功即回全权: 断线降权只属于断线那段时间
  lastPs=ps;
  const act=ps.filter(p=>!metaOf(p.name).arch),arc=ps.filter(p=>metaOf(p.name).arch);
  const want=act.concat(archOpen?arc:[]);   // DOM 行序 = 活跃 + (展开时)归档, 与 .pcRow 查询序一致
  const hn=el.querySelector('.pcSideN'),rows=[].slice.call(el.querySelectorAll('.pcRow'));
  const hd2=el.querySelector('.pcArchHd');
  if(hn&&(!!hd2===!!arc.length)&&rows.length===want.length&&rows.every((d,i)=>d.dataset.peer===want[i].name)){   // 键序+归档组头结构一致: 只 diff 不重建
    hn.textContent=act.length?String(act.length):'';
    rows.forEach((d,i)=>sideSync(d,want[i]));
    if(hd2)syncArchHd(hd2,arc.length);
    return}
  el.innerHTML='';
  const hd=document.createElement('div');hd.className='pcSideHd';
  const ht=document.createElement('span');ht.textContent=t('pcView');hd.appendChild(ht);
  const n2=document.createElement('span');n2.className='pcSideN';n2.textContent=act.length?String(act.length):'';
  hd.appendChild(n2);el.appendChild(hd);
  if(!ps.length){const d=document.createElement('div');d.className='pcEmpty';d.textContent=t('pcNoPeer');el.appendChild(d);return}
  act.forEach(p=>{const d=sideRow(p);sideSync(d,p);el.appendChild(d)});
  if(arc.length){   // 「已归档」= 端側回收站: 收起只占一行, 展开可点行恢复(rowSheet)或直接进会话
    const ah=buildArchHd();
    syncArchHd(ah,arc.length);
    ah.onclick=()=>{archOpen=!archOpen;renderSide(lastPs)};
    el.appendChild(ah);
    if(archOpen)arc.forEach(p=>{const d=sideRow(p);sideSync(d,p);el.appendChild(d)})}}
function skel(b){b.innerHTML='<div class="pcSkel" aria-hidden="true"><i></i><i></i><i></i></div>'}   // P3: 首屏骨架(纯 CSS animation-delay .4s 防闪, 零计时器), paint 首拍移除
function skelSide(el){if(el)el.innerHTML='<div class="pcSkel pcSkelSide" aria-hidden="true"><i></i><i></i><i></i></div>'}
/* PC 首页: 主区在「没自动选中会话」时该长的样子, 两态同源。
   0 个可用会话 ⇒ 教人把 hub/GA 跑起来(旧代码这里 return done() 就走, 主区一片纯白);
   ≥2 个待选 ⇒ 这一屏的任务是挑一个: 文案换成「选一个」并就地列出可用会话 —— 照写「还没有可用的 PC 会话」
   与同屏侧栏自相矛盾, 且屏上没有任何挑选入口。列表不依赖抽屉 ⇒ 宽窄屏一致、不受 .side 状态影响。
   文案要精确: 能走到这个视图就说明已配对(showFab 只在 paired 时建钮), 所以不是"没配对", 而是"已链接但电脑上没有在跑的会话"。
   class 带 pcEmpty ⇒ paint() 里既有的 .pcEmpty 清场逻辑天然把它移走, 不必新增清理路径。 */
function renderHome(ps){
  const box=document.getElementById('pcMsgs');if(!box)return;
  setPcHd(t('pcView'),'',false);
  const ag=(ps||[]).filter(isAgent);
  let hero=box.querySelector('.pcHero');
  if(hero&&hero.classList.contains('pcHeroOff'))hero=null;   // 离线 hero 不是首页: 恢复后必须整个换掉
  if(!hero){
    box.innerHTML='';
    hero=document.createElement('div');hero.className='pcEmpty pcHero';
    hero.innerHTML=LOCKUP+
      '<h2></h2><p></p><ol class="pcSteps"><li><b>1</b><span></span></li><li><b>2</b><span></span></li><li><b>3</b><span></span></li></ol>'+
      '<div class="pcPickList"></div>'+   // 步骤 ↔ 挑选列表二选一, 由 CSS 按 .pcHeroPick 决定: 显隐不变量写进结构, 不靠每轮 JS 记得改
      '<div class="pcHeroAct"><button class="btnPrimary" id="pcHeroRetry" type="button"></button></div>';   // 命令已在第 1 步里, 底部不再重复一遍
    const li=hero.querySelectorAll('.pcSteps span');
    li[0].textContent=t('pcStep1');li[1].textContent=t('pcStep2');li[2].textContent=t('pcStep3');
    const rb=hero.querySelector('#pcHeroRetry');rb.textContent=t('pcRetry');   // 语言切换走 reI18n 整块重建, 故只在首建时写
    rb.onclick=()=>{refreshStatus();pollNow()};
    box.appendChild(hero)}
  setHeroCopy(hero,ag)}
function setHeroCopy(hero,ag){   // 文案与挑选列表每轮按 ag 现算: 复用同一个 hero 时只 toggle 类, 0↔N 切换后文案会卡在旧值
  const many=ag.length>1,set=(sel,v)=>{const n=hero.querySelector(sel);if(n.textContent!==v)n.textContent=v};
  hero.classList.toggle('pcHeroPick',many);
  set('h2',t(many?'pcPickT':'pcHomeT'));
  set('p',many?t('pcPickP').replace('{n}',ag.length):t('pcHomeP'));
  const el=hero.querySelector('.pcPickList'),want=many?ag:[],rows=[].slice.call(el.querySelectorAll('.pcRow'));
  if(rows.length===want.length&&rows.every((d,i)=>d.dataset.peer===want[i].name))return rows.forEach((d,i)=>sideSync(d,want[i]));   // 与侧栏同一套行/同一套 keyed diff: 键序一致只 diff, 免得每轮把焦点打回 body
  el.innerHTML='';want.forEach(p=>{const d=sideRow(p);sideSync(d,p);el.appendChild(d)})}
/* 已有内容时静默重连；只有首次加载无内容，才显示断线空态。 */
function renderOffline(){
  renderOfflineSide();
  const box=document.getElementById('pcMsgs');if(!box)return;
  if(box.firstElementChild&&!box.querySelector('.pcSkel,.pcHeroOff'))return;
  lastSig=null;   // 仅替换空态时弃签名；已有聊天保留 DOM 和增量缓存
  if(box.querySelector('.pcHeroOff'))return;
  box.innerHTML='';
  const d=document.createElement('div');d.className='pcEmpty pcHero pcHeroOff';
  d.innerHTML=LOCKUP+
    '<h2></h2><p></p><div class="pcHeroAct"><button class="btnPrimary" id="pcOffRetry" type="button"></button></div>';
  d.querySelector('h2').textContent=t('pcOfflineT');
  d.querySelector('p').textContent=t('pcOfflineP');
  const rb=d.querySelector('#pcOffRetry');rb.textContent=t('pcRetry');
  rb.onclick=()=>{refreshStatus();pollNow()};
  box.appendChild(d)}
function renderOfflineSide(){   // 侧栏的断线终态: openView 铺的骨架不在断线分支的重画范围内, 不落终态它就永远在假装加载(宽屏侧栏常驻时与主区的「连接断开」同屏打架)
  const el=document.getElementById('pcSide');if(!el)return;
  el.classList.add('pcSideOff');   // 保留上一屏但整体降权: 这是断线前的名单, 不是此刻的事实(renderSide 成功一轮即摘)
  if(el.querySelector('.pcRow'))return;
  el.innerHTML='';const d=document.createElement('div');d.className='pcEmpty';d.textContent=t('pcOffline');el.appendChild(d)}
function selPeer(name){setPeer(name);rememberPeer(name);poll()}   // R1: 直入也走 poll 统一收口(顺带刷侧栏 .cur); 显式选择立刻记账
function fetchSeg(i,j,n,p,g,cb,valid){   // lsdefine 5e67d8b: seg?off= 断点续拉; 旧 hub 忽略 off 给全量(sr.off!==off → 整段替换)
  const k=i+'/'+j;let ent=segTxt[k],raw=(ent&&ent.txt&&ent.n>=0&&ent.n<=n)?ent.txt:'';
  if(ent&&ent.n===n&&ent.txt!=null&&ent.txt!=='')return cb(true);
  const off=raw.length;
  api('GET','/api/'+encodeURIComponent(p)+'/seg/'+i+'/'+j+'?off='+off,'',sr=>{
    if(valid?!valid():g!==gen||p!==curPeer)return cb(false);
    if(!sr||sr.content==null)return cb(!!(ent&&ent.txt));
    if(sr.n!=null&&sr.n<off){delete segTxt[k];return fetchSeg(i,j,n,p,g,cb,valid)}   // /clear 后索引复用 → 全量重拉(off 归 0, 至多再一层)
    raw=(sr.off===off?raw:'')+sr.content;
    segTxt[k]={txt:raw,n:(sr.n!=null?sr.n:n)};cb(true)},valid?undefined:()=>g===gen&&p===curPeer)}
function pullMsgs(done,depth,alive){
  depth=depth||0;if(depth>3)return done();   // 自递归止损: 终止性不押在 hub 不变量上(分页/裁剪违契=本轮放弃, 下轮重来)
  const g=++gen,p=curPeer;   // #032-F2/F6: 本轮世代+peer 捕获; R1: 陈旧只跳落屏, done 照走
  const al=()=>g===gen&&p===curPeer&&(!alive||alive());   // tick 停机条件: 数据陈旧或链换代, 二者任一即弃
  if(++sigAge>=8){sigAge=0;lastSig=null}   // sig 盲区自愈: 末步等长改写/非末 task 变化对 sig 不可见 → 每 8 轮弃签名强制一次全量对账
  const olds=taskSnap.length,since=Math.max(0,olds-1);   // lsdefine: 已渲染任务不可变, 只请求末任务+新增(省 P2P 流量); 旧 hub 忽略 since 给全量
  let q='/api/'+encodeURIComponent(p)+'/messages?detail=1&since='+since;
  if(lastSig)q+='&sig='+encodeURIComponent(lastSig);
  api('GET',q,'',r=>{
    if(g!==gen||p!==curPeer)return done();
    if(!r||r.error){idleRounds++;return done()}   // 出错也计退避: 离线守望不该以 1.2s 空转
    if(r.same){const was=peerRun;setRunBtn(r.run);setPcHd(undefined,p,r.run);idleRounds++;
      if(pendingPut&&++pendingPut.rounds>6){pendingPut=null;   // put 后 6 轮零变化=PC 没在收(面板未开), 提示一次冲淡「已发送」的假成功
        const s=document.getElementById('pcHdSub');if(s)s.textContent+=' · '+t('pcNotTaken')}   // 只附一拍: 下轮 setPcHd 重算副标即自然消隐
      if(was&&!r.run){lastSig=null;idleRounds=0;return pullMsgs(done,depth+1,alive)}scheduleVisible();return done()}
    lastSig=r.sig||null;idleRounds=0;   // 有增量 ⇒ 贴身跟(nextDelay 回到 1.2s)
    setPcHd(r.title,p,r.run);
    const slice=r.tasks||[],hasNt=('nt' in r),total=hasNt?r.nt:slice.length;
    if(olds>total){lastSig=null;segTxt={};taskSnap=[];const b=document.getElementById('pcMsgs');if(b)skel(b);return pullMsgs(done,depth+1,alive)}   // /clear 回退(中间态给骨架不给白屏)
    if(!hasNt)taskSnap=slice;   // 旧 hub: 全量
    else{taskSnap=taskSnap.slice(0,since).concat(slice);
      if(taskSnap.length<total){lastSig=null;taskSnap=[];const b=document.getElementById('pcMsgs');if(b)skel(b);return pullMsgs(done,depth+1,alive)}   // 切片对不上 → 全量重来
      if(taskSnap.length>total)taskSnap=taskSnap.slice(0,total)}
    prefetch({tasks:taskSnap,run:r.run},g,p,done)},al)}
function prefetch(r,g,p,done){   // 先画目录/缓存；最新轮优先同步，旧正文按视口加载，不阻塞轮询。
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
  // 当前轮始终优先同步（含刚完结）；只有旧回答受视口限制。
  wrappers.sort((a,b)=>Number(b.dataset.pci===String(latest&&latest.i))-Number(a.dataset.pci===String(latest&&latest.i)));
  for(const w of wrappers){
    const ti=taskSnap.findIndex(tk=>String(tk.i)===w.dataset.pci),tk=taskSnap[ti];if(!tk)continue;
    const st=tk.steps||[],s=st[st.length-1];if(!s)continue;
    const cards=w.querySelectorAll('.step'),card=cards[cards.length-1];if(!card)continue;
    const cr=card.getBoundingClientRect();if(tk!==latest&&(cr.height<=0||cr.bottom<=br.top||cr.top>=br.bottom))continue;
    const ent=cache[tk.i+'/'+s.j];
    if(ent&&ent.n===s.n){if(w.dataset.tsig!==tsigOf(tk,peerRun&&ti===taskSnap.length-1))fillVisible(box,w,tk);continue;}
    if(w._pcLazyTry===gen)continue;   // 本轮失败不自旋；下一次对账可重试。
    w._pcLazyTry=gen;
    // 不绑轮询 gen：只要 peer/缓存/片段仍在，慢响应仍可用。
    const valid=()=>p===curPeer&&cache===segTxt&&taskSnap.some(t=>t.i===tk.i&&(t.steps||[]).some(x=>x.j===s.j));
    const flight={valid};visibleFlight=flight;
    fetchSeg(tk.i,s.j,s.n,p,gen,ok=>{
      if(visibleFlight===flight)visibleFlight=null;
      if(ok&&valid()&&!document.hidden&&v.classList.contains('on')&&w.isConnected){
        fillVisible(box,w,taskSnap.find(t=>t.i===tk.i));
      }
      scheduleVisible();
    },valid);
    return;   // 正文一次只拉一个，滚动后重新计算可见项，不排队预取旧屏。
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
  return (live?'L':'D')+'|'+(tk.input||'').length+'|'+st.map(s=>s.j+':'+s.n).join(',')+'|'+cv}   // 分片签名: live/输入长度/各步(索引:字节数)/末步缓存版本 — 预拉失败后补齐缓存也算变化, 重绘自愈(#032-F1 增量版)
function paintTask(wrapper,tk,ti,tasks,run){   // #031-F5: 适配 hub task → 主管线 msgs 形状, renderMsgsInto 重建本片(noActions 抑制跨通道操作行, detachTask 不碰主 app 全局 task)
  const st=tk.steps||[],live=run&&ti===tasks.length-1;
  const msgs=[{role:'user',text:tk.input||''},
    {role:'assistant',prompt:tk.input||'',model:'PC',live:live,   // #034-P2: 占位 model, 渲染后立刻改中性 PC 标(见下); 禁止把 peer 标题当模型名
      steps:st.map((s,x)=>{const k=tk.i+'/'+s.j,got=segTxt[k];
        return {n:x+1,summary:s.title||('step '+(s.j+1)),text:(x===st.length-1&&got)?got.txt:''}})}];
  wrapper.innerHTML='';
  try{renderMsgsInto(wrapper,msgs,{noActions:true,detachTask:true})}
  catch(e){wrapper.innerHTML='';const d=document.createElement('div');d.className='pcEmpty';d.textContent=t('pcRenderErr');wrapper.appendChild(d);
    wrapper.dataset.pci=tk.i;wrapper.dataset.tsig='';return}   // 吞错不吞画面: 半成品 DOM 清成可见降级行; 空签名与任何 sig 不等 ⇒ 下轮必重画自愈
  const h=wrapper.querySelector('.assistHead');   // #034-P2: 中性 PC glyph +「PC」文案; newTask 会用 curProvider().type 回落品牌 → 必须覆写
  if(h){const nm=h.querySelector('.assistName');if(nm)nm.textContent='PC';
    const gl=h.querySelector('.glyph');
    if(gl){const sp=document.createElement('span');sp.className='glyph pcGlyph';sp.setAttribute('aria-hidden','true');
      sp.innerHTML='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>';
      gl.replaceWith(sp)}}
  const tb=wrapper.querySelector('.task');
  if(tb){tb.dataset.pci=tk.i;   // DOM→(i,j,n) 映射: 懒拉钩子定位 seg + off 续拉目标字节数
    tb.querySelectorAll('.step').forEach((sc,si)=>{const s=st[si];if(s){sc.dataset.pcj=s.j;sc.dataset.pcn=s.n;
      if(si===st.length-1&&segTxt[tk.i+'/'+s.j]&&segTxt[tk.i+'/'+s.j].n===s.n)sc._pcGot=1}})}   // #032-F1: 仅预拉成功且 n 对齐才标已取
  wrapper.dataset.pci=tk.i;wrapper.dataset.tsig=tsigOf(tk,live);wrapper.dataset.pclive=live?'1':'0'}
function patchLiveTask(wrapper,tk){   // 流式末轮原位更新: 缓存既有步骤DOM，仅更新旧末步并追加新步骤；可见容器绝不清空
  const tb=wrapper.querySelector('.task'),st=tk.steps||[];if(!tb||typeof patchReplaySteps!=='function')return false;
  const old=[].slice.call(tb.querySelectorAll('.step'));if(!old.length||st.length<old.length)return false;
  const from=Math.max(0,old.length-1),delta=st.slice(from).map((s,x)=>{const si=from+x,k=tk.i+'/'+s.j,got=segTxt[k],fresh=got&&got.n===s.n;
    return {n:si+1,summary:s.title||('step '+(s.j+1)),text:fresh?got.txt:((old[si]&&old[si]._text)||'')}});
  if(!patchReplaySteps(tb,delta))return false;
  tb.dataset.pci=tk.i;tb.querySelectorAll('.step').forEach((sc,si)=>{const s=st[si];if(!s)return;sc.dataset.pcj=s.j;sc.dataset.pcn=s.n;
    if(segTxt[tk.i+'/'+s.j]&&segTxt[tk.i+'/'+s.j].n===s.n)sc._pcGot=1;else delete sc._pcGot});
  wrapper.dataset.pci=tk.i;wrapper.dataset.pclive='1';return true}
function captureFold(wrapper){   // 状态还原: 重渲前留快照(折叠组开合+已展开步骤 pcj 集), 重渲后原样还原, 不被打回折叠
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
  const dn=document.getElementById('pcDown');if(dn)dn.hidden=!(box.scrollHeight-box.clientHeight>600&&box.scrollHeight-box.scrollTop-box.clientHeight>=150)}
function pcScrollTxn(box){   // PC 消息区只有两态: 贴底跟随 / 用户阅读。DOM 重绘只消费状态, 绝不从重绘中的瞬时 scrollTop 反推用户意图
  const follow=box._pcStick!==false,top=box.scrollTop,seq=box._pcPinSeq||0;
  return ()=>{
    if((box._pcPinSeq||0)!==seq)return;   // 重绘后用户已滚动: 用户意图绝对优先, 旧事务不得再碰位置
    if(!follow){box.scrollTop=top;pcSyncDown(box);return}
    let n=0;const pin=()=>{if((box._pcPinSeq||0)!==seq||box._pcStick===false)return;box.scrollTop=box.scrollHeight;pcSyncDown(box);if(++n<6)requestAnimationFrame(pin)};
    pin();setTimeout(pin,160);setTimeout(pin,360)}   // WebView/Markdown 晚回流后仍贴底; 任一用户手势都会用 seq 立即取消
}
function pcFitTail(box,wrapper){   // 末 task 短于视口时浏览器会把 alignTop 夹在 maxScroll；动态尾垫补足差额，流式长高后同步收缩
  const el=wrapper&&(wrapper.querySelector('.task')||wrapper);if(box._pcStick!==false||!el){box.style.setProperty('--pcTail','0px');return}   // 贴底态绝不能保留尾垫，否则“到底”会落进空白区
  box.style.setProperty('--pcTail','0px');
  try{const sr=box.getBoundingClientRect(),er=el.getBoundingClientRect(),target=box.scrollTop+(er.top-sr.top)-6,max=box.scrollHeight-box.clientHeight;
    box.style.setProperty('--pcTail',Math.max(0,Math.ceil(target-max))+'px')}catch(e){}}
function pcPinTaskTop(box,wrapper){   // 首屏/新增 task 看回答开头而非末尾；同 task 流式更新仍由 pcScrollTxn 保持原阅读位置
  let el=wrapper&&(wrapper.querySelector('.task')||wrapper);if(!el)return;
  const seq=(box._pcPinSeq||0)+1;box._pcPinSeq=seq;box._pcUserScroll=false;box._pcStick=false;   // 新顶置先作废旧计时器；并清手势240ms余窗，免程序化 scroll 被误判为仍在手滚
  let n=0;const pin=()=>{if((box._pcPinSeq||0)!==seq||box._pcStick!==false)return;el=wrapper.querySelector('.task')||wrapper;pcFitTail(box,wrapper);alignTop(box,el,6);pcSyncDown(box);if(++n<8)requestAnimationFrame(pin)};
  pin();setTimeout(pin,200);setTimeout(pin,420);setTimeout(pin,700)}   // 与主聊天回流窗口同口径；用户任一滚动手势递增 seq 即刻取消
function paint(r,g,p,done){
  if(g!==gen||p!==curPeer)return done();   // #032-F2: 陈旧世代快照不落屏; R1: done 照走(单出口不变量)
  const box=document.getElementById('pcMsgs');if(!box)return done();
  const settleScroll=pcScrollTxn(box),finish=()=>{settleScroll();done()};
  const tasks=r.tasks||[],run=!!r.run;
  if(pendingPut&&tasks.length>pendingPut.n)pendingPut=null;   // 长出新 task=PC 真接收了, 送达对账关账
  if(!tasks.length){const e0=box.querySelector('.pcEmpty');
    if(!e0||e0.parentElement!==box||e0.classList.contains('pcHero')){box.innerHTML='';const d=document.createElement('div');d.className='pcEmpty';d.textContent=t('pcNoMsgs');box.appendChild(d)}   // hero(首页/离线)与步内降级行都不算"已是空态"
    box.style.setProperty('--pcTail','0px');setRunBtn(run);return finish()}
  const emp=box.querySelector('.pcEmpty');if(emp)emp.remove();
  rememberPeer(p);   // 只有真画出内容才记账: kv 里存的永远是「用户真看过的那条」, 而不是某轮自动猜中的
  const sk=box.querySelector('.pcSkel');if(sk)sk.remove();   // P3: 首屏骨架仅首拍存在, 存在性判定属交替态控制流(非兜底)
  const existing=[].slice.call(box.children).filter(e=>e.classList&&e.classList.contains('pcTask'));
  let deg=existing.length>tasks.length;
  if(!deg)for(let i=0;i<existing.length;i++)if(String(existing[i].dataset.pci)!==String(tasks[i].i)){deg=true;break}
  if(deg){
    box.innerHTML='';let lastW=null;
    tasks.forEach((tk,ti)=>{const w=document.createElement('div');w.className='pcTask';box.appendChild(w);paintTask(w,tk,ti,tasks,run);lastW=w});
    setRunBtn(run);if(lastW){pcPinTaskTop(box,lastW);done();return}return finish()}
  let grew=false,lastW=null;
  tasks.forEach((tk,ti)=>{
    const sig=tsigOf(tk,run&&ti===tasks.length-1);
    let w=existing[ti];
    if(!w){w=document.createElement('div');w.className='pcTask';box.appendChild(w);paintTask(w,tk,ti,tasks,run);grew=true;lastW=w;return}
    if(w.dataset.tsig===sig)return;
    const live=run&&ti===tasks.length-1;
    if(live&&w.dataset.pclive==='1'&&patchLiveTask(w,tk)){w.dataset.tsig=sig;return}   // 同一活体末轮只原位更新步骤，wrapper/问题行/回答卡均不重建
    const fs=captureFold(w);paintTask(w,tk,ti,tasks,run);applyFold(w,fs,tk)});
  setRunBtn(run);
  if(grew&&lastW){pcPinTaskTop(box,lastW);done();return}   // 新 task/首屏看开头；不可再调用 settleScroll，否则其延迟贴底会覆盖顶置
  pcFitTail(box,existing[tasks.length-1]);finish()}
/* ---- 启动: 静默查询一次(已配对则显示入口), 桥未就绪时重试 ---- */
let bootTries=0;
function boot(){
  if(!(window.GA&&GA.send)){if(++bootTries>20)return;return setTimeout(boot,1500)}   // 30s 封顶: 浏览器预览/旧壳里没有桥, 原来是无上限自旋
  refreshStatus();
}
setTimeout(boot,1200);
// PC Link 悬浮钮原来只在 boot(1.2s 后)→ /pclink.status 桥往返返回才出现, 视觉上「延迟一段才冒出来」。
// 上次已配对则据本地缓存立即乐观显钮(localStorage 同步、不依赖桥), 随后 refreshStatus 再校正(真解绑会移除)。
function _pcOptimisticFab(){try{if(localStorage.getItem('ga.pcPaired')==='1'){paired=true;showFab();}}catch(e){}}
if(document.body)_pcOptimisticFab();else document.addEventListener('DOMContentLoaded',_pcOptimisticFab);
// 原生 onResume 与 visibilitychange 共用 app.js 的 gaOnResume；短间隔双通知合并。
let resumedAt=0;
function resume(){
  if(!(window.GA&&GA.send)||Date.now()-resumedAt<1000)return;
  resumedAt=Date.now();refreshStatus(null,true);
  const v=document.getElementById('pcView');if(v&&v.classList.contains('on'))pollNow()}

document.addEventListener('visibilitychange',()=>{
  if(document.hidden&&timer){clearTimeout(timer);timer=null}});
function reI18n(){   // 切语言: 模板里的 data-i18n-* 由全局 applyI18n 扫到, 但 t() 直接写进 textContent 的节点扫不到
  const v=document.getElementById('pcView');if(!v)return;
  applyI18n();
  const hero=v.querySelector('.pcHero');if(hero)hero.remove();   // 下一轮 renderHome 用新语言重建
  renderRow();setPcHd(undefined,curPeer||'',peerRun);
  if(v.classList.contains('on')){skelSide(document.getElementById('pcSide'));pollNow()}}   // 侧栏 keyed diff 不再每轮重建 → 换语言须清场, 借下一轮全量重建
window.PCLINK={refreshStatus,openView,closeView,reI18n,resume};
})();
