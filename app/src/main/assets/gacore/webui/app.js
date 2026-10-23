
/* ════════════ 工具 / 状态 ════════════ */
const $=id=>document.getElementById(id), chat=$('chat'), inp=$('in'), btn=$('btn'), sub=$('hdrsub');
let running=false, task=null, timer=null, emptyEl=null;
let _host=chat,_noActs=false;   // PCLINK v2.2: renderMsgsInto 挂载靶(默认主聊天流, 仅同步窗口内切换)与操作行抑制开关(远程会话禁重跑/编辑等本地指令)
let runConvo=null;   // 在飞任务归属的会话(T2): newTask(非回放)置=curConvo, setRunning(false)清空。运行期恒等于后端 _active_convo; curConvo 可≠它(=只读预览态 T3)
let _abortWaitCid=null;   // 中止意图锚(T7): 用户已请求停但 abort 异步(agentmain chunk 间才 break)→ 前端 running=false 而后端 j.running 短暂仍 true 的窗口内, idle poll 不得把该会话当"新发现的后台任务"复活/重复补插 user 气泡。后端收敛(j.running=false)或焦点切走即清空
let pendingAsk=null; // 预览期错过的 ask_user 兜底(T6): 后端 ask 会被任何 /convo 切换清掉(_switch_convo 置 ask=None), 前端留 {cid,ask} 供回归属会话时重建; 新任务发出即作废
// P3a+P3b+P3c: caps/runs/send·abort 多路 + pollAll/pollC + render 串台守卫（无 caps → 现网单会话）
// multi 桥: GA.sendC / GA.pollC / GA.pollAll / GA.abortC；退化: GA.send / GA.poll / GA.abort
const caps = (()=>{try{const c=(typeof GA!=='undefined'&&GA.caps)?GA.caps():{};return (typeof c==='string')?JSON.parse(c||'{}'):(c&&typeof c==='object'?c:{});}catch(e){return{};}})();
const multi = !!caps.multi;
const runs = new Map(); // cid -> {running, gen, box, sinceCursor, stats, ask, task}
let activeCid = null; // 当前焦点 cid（与 curConvo.id 对齐；runConvo 仍表示「正在看的活体归属」兼容层）
// ── P3b helpers ──
function anyRunning(){if(!multi)return !!running;for(const r of runs.values())if(r&&r.running)return true;return false}
function focusRunning(){if(!multi)return !!running;const id=(curConvo&&curConvo.id)||activeCid;const r=id&&runs.get(id);return !!(r&&r.running)}
function ensureRun(cid){if(!cid)return null;let r=runs.get(cid);if(!r){r={running:false,gen:0,box:null,sinceCursor:0,stats:null,ask:null,task:null};runs.set(cid,r)}return r}
function bridgeSend(cid, text){
  if(multi && typeof GA.sendC==='function'){try{return GA.sendC(cid, text)}catch(e){return String(e&&e.message||e)}}
  try{return GA.send(text)}catch(e){return String(e&&e.message||e)}
}
function bridgeAbort(cid){
  if(multi && typeof GA.abortC==='function' && cid){try{GA.abortC(cid)}catch(e){}return}
  try{GA.abort()}catch(e){}
}
function parseBridge(raw){if(raw==null||raw==='')return null;if(typeof raw==='object')return raw;try{return JSON.parse(raw)}catch(e){return null}}
function bridgePoll(cid, since){
  if(multi && typeof GA.pollC==='function' && cid){try{return GA.pollC(cid, String(since))}catch(e){return null}}
  try{return GA.poll(String(since))}catch(e){return null}
}
function bridgePollAll(){
  if(multi && typeof GA.pollAll==='function'){try{return GA.pollAll()}catch(e){return null}}
  return null
}
/* ════════ 多用户数据隔离: key 命名空间 ════════
 * 登录后所有用户态数据自动加 'u<userId>.' 前缀, 不同账号数据互不可见。
 * 白名单 key 保持全局(跨用户共享/登录前需访问): 登录态/隐私同意/语言/主题/一次性迁移标记。
 * _authUid() 读 'ga.auth' 全局 key(本函数内不走命名空间, 避免循环依赖)。*/
const _NS_GLOBAL_KEYS = {auth:1, privacyConsent:1, privacyConsentAt:1, lang:1, theme:1,
  emptyMsgMig0:1, proxyMig0:1, nsMig0:1, authSkipped:1, 'chips.remote':1};   // nsMig0: 裸key→用户命名空间一次性迁移标记(也须全局,否则迁移后读不到)。authSkipped 也须全局: 访客期(无uid)写裸键, 登录后清裸键, 登出/过期 boot 读裸键, 三者须同命名空间, 否则登录后清不掉→登出后静默退回访客丢登录态数据。chips.remote: 起始页预置任务 OTA 缓存, 与账号无关跨用户共享
/* ════ 首次登录数据迁移(用户选A): 把登录前的裸 key 复制到 u<uid>. 前缀, 老用户历史会话/头像/偏好登录后仍可见 ════
 * 仅在该 uid 名下"从未迁移过"且裸 key 存在、目标 key 不存在时复制(幂等、不覆盖已有用户数据)。
 * 必须直接读写物理键 ga.<raw> / ga.u<uid>.<raw>, 不能用 LS/kvGet/kvSet(它们会再过 _nsKey 二次加前缀)。*/
function _migBareKeys(uid){
  if(!uid) return;
  uid = String(uid);
  const migMark = 'ga.u'+uid+'.nsMig0';
  try{ var done = GA.send('/kv.get '+migMark); if(done==='1') return; }catch(e){}
  try{ if(localStorage.getItem(migMark)==='1') return; }catch(e){}
  const MIG_KEYS = ['convoStore','active','favs','userAvatar','customRange','statRange',
    'heatMode','sessMeta','eff','floatOpacity','foCfg','seedVer','soundDone','providers','proxy'];
  function rawGet(pk){ var v=null;
    try{ var r=GA.send('/kv.get '+pk); if(r!=null&&r!=='') v=r; }catch(e){}
    if(v==null){ try{ var l=localStorage.getItem(pk); if(l!=null) v=l; }catch(e){} }
    return v; }
  function rawKv(pk){ try{ var r=GA.send('/kv.get '+pk); if(r!=null&&r!=='') return r; }catch(e){} return null; }   // 只读 kv 文件(不落 localStorage 兜底)
  function rawSet(pk,val){ try{ localStorage.setItem(pk,val); }catch(e){}
    try{ GA.send('/kv.set '+pk+' '+val); }catch(e){} }
  MIG_KEYS.forEach(function(k){
    var dst='ga.u'+uid+'.'+k;
    if(rawGet(dst)!=null||rawKv('u'+uid+'.'+k)!=null) return;   // 目标已有该用户数据(任一物理命名) → 不覆盖
    var src=rawKv(k)||rawGet('ga.'+k);          // 裸 kv 主存优先(kvSet 写的物理键无 'ga.' 前缀——访客 convoStore 真主存在此, 旧版漏读它=首登失忆), 再退 'ga.' 物理键/localStorage 快取
    if(src==null) return;                       // 均不存在 → 跳过
    rawSet(dst, src);                           // 复制(保留裸 key 不删, 兼容退回游客态)
    try{ GA.send('/kv.set u'+uid+'.'+k+' '+src); }catch(e){}   // 同步迁到 kvGet/kvSet 的物理命名(无 'ga.' 前缀), 否则登录后 boot 的 kvGet('convoStore') 看不见迁移数据
  });
  rawSet(migMark, '1');                          // 打迁移标记, 保证仅一次
}
var _lastUid=null;   // 最后已知 uid: 命名空间只随 auth 内容翻转(登录/显式登出); 有意不校验 exp(过期只门控后端调用, 不该藏本地会话), kv+localStorage 双读瞬时失败也不回退裸 key
function _authUid(){return null}
function _nsKey(k){ if(_NS_GLOBAL_KEYS[k]) return k; var u=_authUid(); return u? ('u'+u+'.'+k) : k; }  // 未登录回退裸 key(登录前只读白名单)
function _lsStoreKey(k){return 'ga.'+_nsKey(k)}
const LS={get:(k,d)=>{k=_nsKey(k);try{const r=GA.send('/kv.get '+'ga.'+k);if(r!=null&&r!=='')return JSON.parse(r)}catch(e){}   // 主存(权威·跨重启): 设备文件 kv。真机 localStorage 经 force-stop 丢未刷盘写→可能残留旧值, 故 kv 优先
            try{const v=localStorage.getItem('ga.'+k);if(v!=null)return JSON.parse(v)}catch(e){}   // 兜底: 浏览器预览 / kv 未就绪
            return d},
          set:(k,v)=>{k=_nsKey(k);const s=JSON.stringify(v);let ok=false;
            try{localStorage.setItem('ga.'+k,s);ok=true}catch(e){                                       // 快取(本会话快; 配额满→丢会话历史腾空间)
              try{for(let i=0;i<60;i++){if(!_pruneOneConvo())break;try{localStorage.setItem('ga.'+k,s);ok=true;break}catch(_){}}}catch(_){}}
            try{if(GA.send('/kv.set '+'ga.'+k+' '+s)==='ok')ok=true}catch(e){}                           // 主存: 始终镜像设备文件 kv→跨重启持久(真机 localStorage 不跨重启; 根治头像"附件保存失败"/设置丢失)
            return ok},   // 配额满: 丢会话历史腾空间
          del:(k)=>{k=_nsKey(k);try{localStorage.removeItem('ga.'+k)}catch(e){}try{GA.send('/kv.del '+'ga.'+k)}catch(e){}}};   // 删除镜像 get/set: 清 localStorage 快取 + kv 主存(同 _nsKey 推导) → 删除集≡读写集, 不再漂移
const PRIVACY_VERSION='2026-06-16-ui-action-v1';
let _privacyOk=false;   // 本会话已同意: 即使 kv 瞬时失败也不把用户钉在同意页
function _privacyRaw(v){if(v==null)return '';let s=String(v).trim();if(!s)return '';
  if(s.charAt(0)==='"'||s.charAt(0)==="'"){try{const j=JSON.parse(s);if(typeof j==='string')s=j}catch(e){}}
  return String(s).trim()}
function hasPrivacyConsent(){
  if(_privacyOk)return true;
  try{if(_privacyRaw(GA.send('/kv.get privacyConsent'))===PRIVACY_VERSION)return true}catch(e){}
  try{if(_privacyRaw(GA.send('/kv.get ga.privacyConsent'))===PRIVACY_VERSION)return true}catch(e){}
  try{if(LS.get('privacyConsent','')===PRIVACY_VERSION)return true}catch(e){}
  try{if(_privacyRaw(localStorage.getItem('ga.privacyConsent'))===PRIVACY_VERSION)return true}catch(e){}
  return false}
function setPrivacyConsent(){
  _privacyOk=true;
  try{localStorage.setItem('ga.privacyConsent',PRIVACY_VERSION)}catch(e){}
  try{LS.set('privacyConsent',PRIVACY_VERSION)}catch(e){}   // ga.privacyConsent JSON 镜像(与其它全局偏好同路径)
  try{GA.send('/kv.set privacyConsent '+PRIVACY_VERSION)}catch(e){}   // 历史裸键(hasPrivacyConsent 主读)
  try{GA.send('/kv.set privacyConsentAt '+Date.now())}catch(e){}}
function _pruneOneConvo(){try{const sk=_lsStoreKey('convoStore'),a=JSON.parse(localStorage.getItem(sk)||'[]');
    if(!Array.isArray(a)||!a.length)return false;
    const curId=(typeof curConvo!=='undefined'&&curConvo)?curConvo.id:null;   // 不动正在看的会话
    let i=a.findIndex(c=>!c.pinned&&c.id!==curId);
    if(i<0)i=a.findIndex(c=>c.id!==curId); if(i<0)i=0;     // 实在没有再退而求其次
    a.splice(i,1);
    localStorage.setItem(sk,JSON.stringify(a));
    return true}catch(e){return false}}   // 只剪 localStorage 快取副本: kv 主存无配额, 内存/主存不因快取满而永久删会话
/* ════════════ i18n 中英文 ════════════ */
let lang=LS.get('lang', /^en/i.test(navigator.language||'')?'en':'zh');
function t(k){return (I18N[lang]&&I18N[lang][k]!=null?I18N[lang][k]:(I18N.zh[k]!=null?I18N.zh[k]:k))}
function applyI18n(){
  document.querySelectorAll('[data-i18n]').forEach(e=>e.textContent=t(e.getAttribute('data-i18n')));
  document.querySelectorAll('[data-i18n-ph]').forEach(e=>e.setAttribute('placeholder',t(e.getAttribute('data-i18n-ph'))));
  document.querySelectorAll('[data-i18n-html]').forEach(e=>e.innerHTML=t(e.getAttribute('data-i18n-html')));
  document.querySelectorAll('[data-i18n-aria]').forEach(e=>e.setAttribute('aria-label',t(e.getAttribute('data-i18n-aria'))));
  document.querySelectorAll('#langSeg button').forEach(b=>b.classList.toggle('on',b.getAttribute('data-l')===lang));
  document.documentElement.lang=lang;
}
function setLang(l){lang=l;LS.set('lang',l);try{GA.send('/lang '+l)}catch(e){}
  applyI18n();refreshModelUI();renderDrawer();if(typeof refreshTip==='function')refreshTip();
  if(window.PCLINK&&PCLINK.reI18n)try{PCLINK.reI18n()}catch(e){}   // PC 互联页的侧栏/首页文案是 t() 直写 textContent, 全局 applyI18n 扫不到
  if(emptyEl)renderHeroChips();   // chips 文案是 JS 填充(远程数据无 data-i18n), 切语言须显式重渲
  if($('setv').classList.contains('on')&&setStack.length){const top=setStack[setStack.length-1];   // 设置页内切语言: 同步顶栏标题 + JS 填充的值(themeVal/provCount), 它们不带 data-i18n
    if(top.key)top.title=t(top.key);$('setvTitle').textContent=top.title;if(top.panel==='homePanel')refreshHome();else if(top.panel==='statsPanel')renderStats();else if(top.panel==='a11yPersistPanel')renderA11yPersistPage()}   // 统计页切语言: 重渲标签; 账户页: 重渲 #userPwdVal/状态/有效期等 JS 填充值(非 data-i18n)
  if(curConvo&&!running)renderConvo(curConvo);    // 重渲当前会话, 让已渲消息(步骤/工具条/代码块)也切语言
  else if(curConvo)setHeaderTitle();else if(!running)setStatus(modelLabel(),false);
  toast(l==='en'?'Language: English':'语言：中文');
  if(curConvo&&!running){stick=true;requestAnimationFrame(()=>scroll(1));setTimeout(()=>scroll(1),80)}}   // 切语言重渲后多帧重锚到底: renderConvo 的同步 scroll(1) 早于安卓异步回流→停在中间; rAF+延时再钉, 回到最新消息
function effName(v){return t((EFFS.find(e=>e.v===v)||EFFS[0]).k)}

let providers=[], active=LS.get('active',null), favs=LS.get('favs',[]),
    sessMeta=LS.get('sessMeta',{}), curEff=LS.get('eff',''), globalProxy=LS.get('proxy','');
let userAv=LS.get('userAvatar','person'), soundOn=LS.get('soundDone',true);   // 用户头像(模板 token 或 'img:'+dataURL) + 完成提示音(默认开)
let keepAwake=LS.get('keepAwake',true);   // 模型运行时阻止系统息屏(默认开): setRunning 据此调 GA.keepAwake, 仅运行中且开关开才保持亮屏
let showThinking=LS.get('showThinking',true);window.GA_THINKING_ON=showThinking;   // F1.3: 思考过程折叠块显示开关(默认开, KV 持久化); render.js 的 thinking 挂点按此渲染/跳过
let floatAlwaysOn=LS.get('floatAlwaysOn',false);   // 悬浮窗常开(默认关): 开启后悬浮球常驻不随回前台收起, 由 GA.setFloatAlwaysOn 落原生 SharedPreferences + 前台服务保活
let theme=LS.get('theme','system'), floatOpacity=LS.get('floatOpacity',0.9);   // 颜色模式(system/light/dark) + 悬浮窗透明度(0.3~1)
let sendReady=false;   // 发送按钮启用态单一真值: boot/ready/input/附件/模型切换/停止键均经 applySendEnabled 收口，避免 WebView 初始 disabled 灰住
let mkMixins=[];   // /config.items 中 type==='mixin' 的项(按 mykey.py 原始顺序), 供模型列表渲染
let configItems=[]; // /config.items 全量(mixin+provider 按 mykey.py 原始顺序), 用于模型列表混排渲染
let cfgLoaded=false;   // /config 是否已成功载入(ok=true): 区分「加载中」与「确认无服务商」, 防重建窗口把 loading 误判为未配置(P0-2)
let cfgFailed=false;   // /config 退避重试仍失败 → 进入可见错误态(状态栏可点重试), 绝不永久停在不可操作的「启动中」
let cfgUnconfigured=false;   // /config 失败但 errcat=unconfigured(mykey 不存在): 未配置态≠错误态, 引导配置不重试(#244)
let _lastCfgErrCat='';       // 后端 /config 结构化失败类别: 'unconfigured'|'load_error'|''(旧后端/解析失败)
let _bootT0=0;         // boot 起始时刻: 供 modelLabel 超时降级(>15s 仍未就绪则提示可重试, 不再一直「启动中」)
let _bootErrTries=0;   // Py.boot 确定性失败(ERR:前缀)累计重试次数: 超限暴露错误态, 不无限静默转圈
let _cfgRetryTimer=null;   // /config 退避重试定时器句柄(防重入)
let _lastCfgErr='';    // 最近一次 /config 失败原因(脱敏后上报, 不含 key/路径原文)
let foCfg=LS.get('foCfg',null);   // 故障转移配置(转移顺序/启用集/重试参数), UI 持久化
// 极简高端: 品牌强调色实底 + 几何居中、180°旋转对称的"自动循环/重试"近全环双箭字形
// (上下两段等长弧近闭合成圆 + 两个对称小箭尖; 故障转移=自动轮询重试; 与多彩服务商 logo 区隔, 双主题自适应)
const AUTO_GLYPH='<span class="glyph" style="background:var(--acc);color:var(--onAcc);box-shadow:inset 0 0 0 1px rgba(0,0,0,.06)"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4.2 9.5A8 8 0 0 1 19.8 9.5"/><path d="M16.6 9.2 20.2 9.9 20.4 6.2"/><path d="M19.8 14.5A8 8 0 0 1 4.2 14.5"/><path d="M7.4 14.8 3.8 14.1 3.6 17.8"/></svg></span>';
// providers 只从后端 /config(llmcore→mykey.py) 权威载入；favs 在载入后再按真实 provider 清理。
const EFFS=[{v:'',k:'eff_default'},{v:'minimal',k:'eff_minimal'},{v:'low',k:'eff_low'},
            {v:'medium',k:'eff_medium'},{v:'high',k:'eff_high'},{v:'xhigh',k:'eff_xhigh'},{v:'max',k:'eff_max'}];   // max 镜像上游 247cb23; 后端按模型钳制, 不会发出上游必拒档位
/* ── 服务商品牌图标: 官方彩色 logo(lobehub icons), 置于干净白底圆角片(类 cherry studio) ── */
// 品牌判定: 先看 model, 再看 name, 最后才回退 type。claude/anthropic 放 matcher 末位——
// 否则 anthropic 兼容端点跑 stepfun/kimi/glm 时, 供应商名/类型里的 'claude' 会盖过真正的型号品牌(用户只见 openai/claude 的根因)。
function _brandMatch(s){
  if(/gpt|openai|codex|chatgpt|davinci|\bo[1-4](-mini|-preview)?\b/.test(s))return 'openai';
  if(/gemini|gemma|google|palm|bison/.test(s))return 'gemini';
  if(/deepseek/.test(s))return 'deepseek'; if(/grok|xai/.test(s))return 'grok';
  if(/qwen|qwq|tongyi/.test(s))return 'qwen'; if(/glm|zhipu|bigmodel|chatglm/.test(s))return 'glm';
  if(/kimi|moonshot/.test(s))return 'kimi'; if(/minimax|abab/.test(s))return 'minimax';
  if(/mimo|xiaomi/.test(s))return 'mimo';
  if(/step-|stepfun|step[123]/.test(s))return 'step'; if(/mistral|mixtral|codestral/.test(s))return 'mistral';
  if(/llama|meta-/.test(s))return 'meta';
  if(/longcat/.test(s))return 'longcat'; if(/doubao|豆包/.test(s))return 'doubao';
  if(/hunyuan|混元/.test(s))return 'hunyuan'; if(/ernie|wenxin|文心/.test(s))return 'ernie';
  if(/spark|讯飞|星火|iflytek/.test(s))return 'spark'; if(/baichuan|百川/.test(s))return 'baichuan';
  if(/cohere|command|aya\b/.test(s))return 'cohere'; if(/\byi[- ]|\b0?1[ -]?ai\b|零一万物/.test(s))return 'yi';
  if(/claude|anthropic/.test(s))return 'claude';
  return null}
function brandKey(name,model,type){
  return _brandMatch((model||'').toLowerCase()) || _brandMatch((name||'').toLowerCase())
    || (type==='claude'?'claude':(type==='oai'?'openai':'generic'))}
const _dark=()=>document.documentElement.getAttribute('data-theme')==='dark'||(!document.documentElement.getAttribute('data-theme')&&matchMedia('(prefers-color-scheme:dark)').matches);
let _svgIdN=0;
function uniqIds(svg){const s='_g'+(++_svgIdN).toString(36);   // 每次渲染唯一化 svg 内部 id(+ url(#)/href 引用): 根治多实例同 id 渐变/裁剪互相覆盖→qwen 等"渐变-only"图标白片
  return svg.replace(/id="([^"]+)"/g,(_m,v)=>`id="${v}${s}"`)
            .replace(/url\(#([^)]+)\)/g,(_m,v)=>`url(#${v}${s})`)
            .replace(/(xlink:href|href)="#([^"]+)"/g,(_m,a,v)=>`${a}="#${v}${s}"`)}
function brandTile(key,cls){const b=BRAND[key]||BRAND.generic;   // 彩色 logo 上白底片; colored=内置多色, 否则上品牌色
  const col=b.colored?'':`color:${b.c||'#1d1d1f'}`;
  const inner=b.svg?uniqIds(b.svg):`<span style="font-weight:600;font-size:${(b.mono||'').length>2?10:12}px">${b.mono}</span>`;
  return `<span class="glyph ${cls||''}" style="background:${b.tile||'#fff'};${col};box-shadow:inset 0 0 0 1px rgba(0,0,0,.08)">${inner}</span>`}
function provGlyph(p){const t=typeof p==='string'?p:'';const name=typeof p==='object'?p.name:'';const model=typeof p==='object'?p.model:'';
  return brandTile(brandKey(name,model,typeof p==='object'?p.type:t))}
function modelGlyph(modelId,type){return brandTile(brandKey('',modelId,type))}
function uid(){return 'p'+Math.abs((Date.now()^(performance.now()*1e6|0))).toString(36)}
const ICON_SEND='<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="6 11 12 5 18 11"/></svg>';
const ICON_STOP='<svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor" stroke="none"><rect x="6" y="6" width="12" height="12" rx="2.5"/></svg>';
const AV_PERSON='<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="3.5"/><path d="M5.5 20a6.5 6.5 0 0 1 13 0"/></svg>';
const AV_PRESETS=['person','🙂','😎','🤓','🐱','🦊','🐼','🌟','🚀','🎯','🍀','🌈'];   // 极简: 默认线性人像 + 少量友好预设
function userAvatarInner(){if(userAv&&userAv.indexOf('img:')===0)return '<img src="'+userAv.slice(4)+'" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:inherit;display:block">';
  if(userAv&&userAv.indexOf('file:')===0)return '<img src="file://'+userAv.slice(5).replace(/"/g,'%22')+'" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:inherit;display:block">';   // 仅向后兼容: 旧 build 曾把头像存为 'file:'+落盘路径(原图仍在 files/ga/uploads); 新存一律 'img:'+dataURL
  return userAv==='person'?AV_PERSON:('<span class="em">'+userAv+'</span>')}
function fmtTime(ts){if(!ts)return nowHM();const d=new Date(ts),p=n=>(n<10?'0':'')+n;return p(d.getHours())+':'+p(d.getMinutes())}

/* ════════════ GA 专属细节 / 小彩蛋 (源自 tuiapp_v2 & tui_v3): gerund 动词 · 宠物 · 热度 · token · 计时 ════════════ */
const GERUNDS=["Pondering","Reticulating","Sleuthing","Hatching","Brewing","Sharpening","Untangling","Compiling","Unraveling","Distilling","Calibrating","Conjuring","Synthesizing","Threading","Resolving","Tuning"];
function gerund(sec){return GERUNDS[Math.floor(sec/6)%GERUNDS.length]}   // 思考动词轮播: 默认英文(不随 UI 语言切换), 仅作"还在干活"的轻量提示
function fmtElapsed(ms){const s=Math.floor(ms/1000);if(s<60)return s+'s';const m=Math.floor(s/60),r=s%60;return m+':'+(r<10?'0':'')+r}
function humanTok(n){n=Math.round(n||0);return n>=1e6?(n/1e6).toFixed(1)+'M':n>=1000?(n/1000).toFixed(1)+'k':String(n)}
function estTok(txt){if(!txt)return 0;const cjk=(txt.match(/[一-鿿　-ヿ＀-￯]/g)||[]).length;return Math.round(cjk*0.6+(txt.length-cjk)/4)}
const TIPS={en:["Tap the model chip up top to switch model or provider.","Every reply has copy · regenerate · read-aloud — no long-press needed.","No VPN needed by default — GA connects directly; only set a proxy in Settings ▸ Network if your network requires one.","Swipe in from the left edge to open past chats; pin the ones that matter.","GA runs the real GenericAgent engine — it executes tasks step by step."],
  zh:["点顶部模型胶囊即可切换模型或服务商。","每条回复都带复制 · 重做 · 朗读，无需长按。","默认无需 VPN，GA 直连可达；仅当你的网络需要代理时才到「设置 ▸ 网络」填。","从屏幕左缘向右滑可打开历史会话，重要的可置顶。","GA 跑的是真正的 GenericAgent 引擎，会分步执行任务。"]};
let _tipIdx=Math.floor(Math.random()*99);
function curTip(){const a=TIPS[lang]||TIPS.zh;return a[_tipIdx%a.length]}
function tokChips(tin,tout){return '<span class="tok" title="'+t('tokIn')+'">↑'+humanTok(tin)+'</span><span class="tok" title="'+t('tokOut')+'">↓'+humanTok(tout)+'</span>'}

/* 实时运行指示器 (独立于 700ms poll 的平滑动效): 英文 gerund + 计时 + token 统一落在消息下方 runMeta 行;
   顶栏标题只保留模型名 + 脉冲点, 消息头只保留脉冲点(已去掉宠物/动词/时间, 见 issue#4) */
let runStats={t0:0,tokIn:0,tokOut:0,cacheRead:0,cacheWrite:0,live:false};
let liveTimer=null;
function resetRunStats(){runStats={t0:Date.now(),tokIn:0,tokOut:0,cacheRead:0,cacheWrite:0,live:false}}   // 清零唯一点: newTask 活体出生; startLive 永不重置(防 multi 每拍/切焦点把总计时·token 打回 0)
function startLive(){   // 边沿幂等: 已 live 只保 timer; 不重置 t0/tok*; 完成态禁复活
  if(task&&task.done)return;
  runStats.live=true;
  if(liveTimer)return;liveTimer=setInterval(liveTick,500);liveTick()}   // 只刷新计时/token 文本(500ms 足够); 转圈交给 CSS .spin
function stripRunSpin(){try{const m=task&&task.meta;if(!m)return;   // 摘 spin 独立于 meta 重写(renderTaskStats 有 hasEl||hasTok 守卫, 统计全空时不覆盖 → 必须无条件摘)
  const sp=m.querySelector('.spin');if(sp)sp.remove();m._skel=0;m._sig=null;m._tin=m._tout=m._ger=m._el=null}catch(e){}}
function stopLive(){runStats.live=false;if(liveTimer){clearInterval(liveTimer);liveTimer=null}
  stripRunSpin();
  try{if(window.GA_PACE)GA_PACE.flushAll()}catch(e){}}   // M2 硬约束: 任务停止(完成/abort/失焦停表)瞬间 flush 全部 pacing 缓冲, 禁止「已停止还在打字」
// 转圈=CSS 动画(.spin, GPU 合成层, 主线程忙也不卡)→根治旧 90ms JS braille 的渲染卡顿。
// liveTick: 骨架只建一次; 之后只改 .tok/.ger2/.muL 的 textContent(estTok 每拍变也不整行 innerHTML → 不闪/spin 不重开)。
function _ensureRunMeta(m){if(m._skel&&m.querySelector('.spin'))return;   // 失焦摘 spin 后再回焦 → 重建带 spin 的骨架
  m.innerHTML='<span class="spin" aria-hidden="true"></span><span class="ger2"></span><span class="mdiv">·</span><span class="muL"></span>';   // R7 去噪(Boss 2026-08-08): 运行中不再常显 ↑↓token(估算值每拍跳=闪烁噪音), 只留 gerund+计时
  m.classList.remove('mx','open');m.onclick=null;
  m._skel=1;m._sig=null;m._tin=null;m._tout=null;m._ger=m.querySelector('.ger2');m._el=m.querySelector('.muL');m.style.display='flex'}
function liveTick(){if(!runStats.live||(task&&task.done))return;   // done 守卫: finish 后若定时器未清/竞态再入, 禁止复活 spin
  try{_twLiveTick()}catch(e){}   // v3.2-C: 钉底条+步内 .twdu 耗时复用本 500ms tick, 不另起定时器(#009 必修 3)
  if(task&&task.state&&!task.done)task.state.classList.add('run');   // 消息头仅脉冲点
  const m=task&&task.meta;if(!m)return;
  const t0=(task&&task.t0)||runStats.t0||Date.now();   // 总计时锚 task.t0(newTask 出生点); runStats.t0 仅兜底 → 切走再切回不从 0 重来
  const ms=Date.now()-t0;
  _ensureRunMeta(m);   // R7 去噪: token 不再每拍上屏(runStats 照常累计, finish 冻结落库不受影响)
  if(m._ger)m._ger.textContent=gerund(ms/1000);
  if(m._el)m._el.textContent=fmtElapsed(ms)}
/* ════════════ 渲染核心(经验证, 不动) ════════════ */
marked.setOptions({gfm:true,breaks:true});
function sanitize(h){return window.DOMPurify?DOMPurify.sanitize(h,{ADD_ATTR:['target','rel']}):h}
function md(t){try{return sanitize(marked.parse(t||''))}catch(e){const d=document.createElement('div');d.textContent=t||'';return d.innerHTML}}
function wrapTables(sb){sb.querySelectorAll('table').forEach(tb=>{const p=tb.parentNode;if(!p||(p.classList&&p.classList.contains('tw')))return;   // marked 产出裸<table>: 包一层可横滑容器, 窄表撑满/宽表横滑不撑破卡片
  const w=document.createElement('div');w.className='tw';p.insertBefore(w,tb);w.appendChild(tb)})}
let _hljs=null;
function ensureHljs(){if(window.hljs)return Promise.resolve(window.hljs);
  if(!_hljs)_hljs=new Promise(r=>{const s=document.createElement('script');s.src='vendor/highlight.min.js';s.onload=()=>r(window.hljs);s.onerror=()=>r(null);document.head.appendChild(s)});return _hljs}
function decorateCode(c){const bs=[...c.querySelectorAll('pre>code:not([data-deco])')];
  bs.forEach(code=>{code.setAttribute('data-deco','1');const pre=code.parentElement;
    if(pre)pre.classList.add('ga-card','ga-card--code');   // F2.1 代码入卡(新/legacy 双管线同经此处 → F1.1 字节等价保持)
    const lang=(code.className.match(/language-([\w-]+)/)||[])[1]||'';
    const head=document.createElement('div');head.className='cbhead';
    const ls=document.createElement('span');ls.className='lang';ls.textContent=lang||'text';head.appendChild(ls);
    const cp=document.createElement('button');cp.className='cbcopy';cp.setAttribute('aria-label',t('copyCode'));cp.innerHTML=ICO_COPY+'<span>'+t('copy')+'</span>';
    cp.onclick=()=>copyText(code.textContent,()=>{cp.classList.add('ok');cp.innerHTML=ICO_OK+'<span>'+t('copied')+'</span>';setTimeout(()=>{cp.classList.remove('ok');cp.innerHTML=ICO_COPY+'<span>'+t('copy')+'</span>'},1300)});
    head.appendChild(cp);pre.insertBefore(head,code)});
  if(bs.length)ensureHljs().then(h=>{if(h)bs.forEach(c=>{try{h.highlightElement(c)}catch(e){}})})}
function copyText(t,d){try{navigator.clipboard.writeText(t).then(d,()=>{ta(t);d&&d()})}catch(e){ta(t);d&&d()}}
function ta(t){const e=document.createElement('textarea');e.value=t;document.body.appendChild(e);e.select();try{document.execCommand('copy')}catch(x){}e.remove()}
let stick=true;
let pinned=false,_lastPin=0,_pinEl=null;   // _pinEl=顶置锚点; 短轮次顶置后天然 nearBottom, 不能再用 nb 清 pinned(现网「新回复未顶置」根因)
function nearBottom(){return chat.scrollHeight-chat.scrollTop-chat.clientHeight<150}
function pinElAtTop(){if(!_pinEl)return false;try{const sr=chat.getBoundingClientRect(),er=_pinEl.getBoundingClientRect();return Math.abs(er.top-sr.top)<80}catch(e){return false}}
chat.addEventListener('scroll',()=>{const nb=nearBottom();
  if(pinned&&Date.now()-_lastPin>800&&!pinElAtTop())pinned=false;   // 仅锚点离开顶带(=用户拖走)才退出阅读态; 短内容 nb 不再误伤
  stick=nb&&!pinned;$('hdr').classList.toggle('scrolled',chat.scrollTop>2);updateScrollNav()});
const _snav=$('scrollNav'),_snUp=$('snUp'),_snDown=$('snDown');   // 滚动导航: 双阈值(600px)按位置显隐; up=回顶 down=回底
function updateScrollNav(){if(!_snav)return;const up=chat.scrollTop>600,down=chat.scrollHeight-chat.clientHeight>600&&!nearBottom();
  _snUp.hidden=!up;_snDown.hidden=!down;_snav.classList.toggle('on',up||down);if(!down)_snDown.classList.remove('done');_snDown.classList.toggle('pin',pinned&&down)}
if(_snUp)_snUp.onclick=()=>{stick=false;chat.scrollTop=0};
if(_snDown)_snDown.onclick=()=>{stick=true;_snDown.classList.remove('done');pinBottom()};   // 即时跳+多帧重钉(content-visibility 下 smooth 会失准, 与仓库范式一致)
const _isAnd=/Android/i.test(navigator.userAgent);   // Android 走 manifest adjustResize, 系统布局收缩消化键盘, --kb 平移机制只保留给 iOS/浏览器
try{const _comp=$('comp');if(_comp&&window.ResizeObserver)new ResizeObserver(()=>{document.documentElement.style.setProperty('--compH',_comp.offsetHeight+'px');scroll()}).observe(_comp)}catch(e){}   // #scrollNav 底部跟随输入区实高(多行/附件时不遮挡拦截 composer); scroll() 补钉贴底跟随态(pinned 由其内部条件自动拦下)
let _vvQ=false;function _vvApply(){_vvQ=false;if(!_isAnd&&window.visualViewport){const vv=window.visualViewport,o=Math.max(0,innerHeight-vv.height-vv.offsetTop);document.documentElement.style.setProperty('--kb',o+'px')}scroll()}function _vvMark(){if(_vvQ)return;_vvQ=true;requestAnimationFrame(_vvApply)}
if(window.visualViewport){const vv=window.visualViewport;vv.addEventListener('resize',_vvMark);vv.addEventListener('scroll',_vvMark)}   // 输入框吸附键盘上沿: 仅 iOS/浏览器平移(Android adjustResize 不平移, --kb 恒 0px); rAF 合帧防中文候选栏展开/收起动画帧抖动
window.addEventListener('resize',_vvMark);
/* 从悬浮窗/后台返回前台: WebView 挂起期间布局/scrollHeight 变化会把列表停在中部。
   Android WebView 后台不可靠触发 visibilitychange/pageshow, 故由原生 MainActivity.onResume 经 gaOnResume 桥驱动;
   多帧重钉(覆盖恢复时的 visualViewport/字体/键盘二次重排, 并压过期间 scroll 事件把 stick 翻成 false);
   仅在原本贴底(stick)或任务运行中(看 agent 跑)才回底 → 用户主动上滑看历史时不打扰。 */
window.gaOnResume=function(){
  try{if(window.PCLINK)PCLINK.resume()}catch(e){}   // 原生前台通知也恢复 PC 互联，不能只靠 WebView 可见性事件
  try{_vvQ=false;_vvMark()}catch(e){}   // 防 ROM 差异(未复现): 理论上挂起期 pending rAF 会补发, 此行仅幂等重算一帧, 不得视为必然逻辑(R4)
  try{const k=kvGet('convoStore');if(Array.isArray(k)&&k.length){   // 后台 call_once/notif 可能已写 kv: 回前台合并进抽屉
    const have=new Set(convos.map(c=>c.id));let ch=false;
    k.forEach(c=>{if(c&&c.id&&!have.has(c.id)){convos.push(c);have.add(c.id);ch=true}});
    if(ch){try{renderDrawer()}catch(e){}}}}catch(e){}
  try{if(!timer)poll()}catch(e){}   // 消费 notif_pending / 发现后台 running
  if(running&&curConvo===runConvo&&task&&task.box){   // 运行中回前台: 锚在视口 ±1 屏内才重钉(修挂起期布局漂移); 超 1 屏不 return, 落到下方 stick 贴底修正(监察 R2: 用户滑到底后挂起回来仍归位)
    let _in=false;try{const sr=chat.getBoundingClientRect(),er=task.box.getBoundingClientRect();_in=Math.abs(er.top-sr.top)<chat.clientHeight}catch(e){}
    if(_in){pinReplyTop(task.box);return}}
  if(!stick)return;   // 本就贴底才回底; 用户上滑看历史不打扰
  pinBottom();
};
document.addEventListener('visibilitychange',()=>{if(!document.hidden)gaOnResume()});   // 兜底: 部分 ROM 仍会触发
function scroll(f){if(_host!==chat)return;if(f){pinned=false;_pinEl=null}if(f||(stick&&!pinned)){chat.scrollTop=chat.scrollHeight;stick=true}}   // PCLINK v2.2: 远程回放窗口内不碰主聊天滚动
function pinBottom(){pinned=false;_pinEl=null;let n=0;const pin=()=>{chat.scrollTop=chat.scrollHeight;stick=true;if(++n<8)requestAnimationFrame(pin)};   // 8 帧重钉+两拍延时: 抵消安卓 WebView 异步回流(content-visibility 高度重估/图片晚到)后底部后移
  pin();setTimeout(pin,200);setTimeout(pin,420)}
function alignTop(scroller,el,pad){   // 把 el 顶对齐到滚动容器可视区顶端(pad 像素留白); 用 rect 差量, 不依赖 offsetParent 链
  if(!scroller||!el)return;pad=pad||0;
  try{const sr=scroller.getBoundingClientRect(),er=el.getBoundingClientRect();
    scroller.scrollTop+=(er.top-sr.top)-pad}catch(e){}}
function pinReplyTop(el,scroller){   // 新 turn: 用户气泡顶锚 + 关 stick, 流式不再追底; 多帧重钉对付 content-visibility/IME 回流
  scroller=scroller||chat;if(!el)return;const mn=scroller===chat;if(mn){stick=false;pinned=true;_pinEl=el}
  let n=0;const pin=()=>{alignTop(scroller,el,6);if(mn)_lastPin=Date.now();if(++n<8)requestAnimationFrame(pin)};
  pin();setTimeout(pin,200);setTimeout(pin,420);setTimeout(pin,700);if(mn)updateScrollNav()}   // +700ms: 键盘收起/composer 缩高后再钉一拍
function el(tag,cls,p){const e=document.createElement(tag);if(cls)e.className=cls;(p||_host).appendChild(e);return e}   // PCLINK v2.2: 缺省父由 chat 改 _host(常态恒=chat, 零行为差异)
function bubble(cls,text){const b=el('div',cls);b.textContent=text;scroll(1);return b}
function nowHM(){const d=new Date(),p=n=>(n<10?'0':'')+n;return p(d.getHours())+':'+p(d.getMinutes())}
function toast(m){const t=$('toast');t.textContent=m;t.classList.add('on');clearTimeout(t._t);t._t=setTimeout(()=>t.classList.remove('on'),2200)}
/* 通用弹窗: Android WebView 默认禁用 window.prompt/confirm(返回 null/false)→ 代理编辑/清空对话/重命名全失效, 用自绘弹窗替代 */
function gaModal(o){const mask=$('modalMask'),card=$('modalCard');const hasInput=!!o.input;
  card.innerHTML='<h4></h4>'+(o.html?'<div class="modalBody"></div>':(o.msg?'<p class="msg"></p>':''))+(hasInput?'<input type="text" autocomplete="off">':'')+
    '<div class="modalBtns"><button class="cancel"></button><button class="ok'+(o.danger?' danger':'')+'"></button></div>';
  card.querySelector('h4').textContent=o.title||'';
  if(o.html)card.querySelector('.modalBody').innerHTML=o.html;else if(o.msg)card.querySelector('.msg').textContent=o.msg;   // html=受控富文本(标签/值行); msg=纯文本(textContent, 防注入)
  const ipt=card.querySelector('input');if(ipt){ipt.value=o.value||'';if(typeof o.input==='string')ipt.placeholder=o.input}
  const ca=card.querySelector('.cancel'),ok=card.querySelector('.ok');
  ca.textContent=o.cancelText||t('cancel');ok.textContent=o.okText||t('ok');if(o.noCancel)ca.style.display='none';
  const close=()=>{if(window.gaSpringModalClose){gaSpringModalClose(mask,card);return}mask.classList.remove('on')};   // M3: 弹层出场弹簧(helper 内先 remove('on') 语义不变; spring.js 缺席/GA_SPRING_OFF=原路径)
  ca.onclick=()=>{close();o.onCancel&&o.onCancel()};ok.onclick=()=>{const v=ipt?ipt.value:true;close();o.onOk&&o.onOk(v)};
  mask.onclick=e=>{if(e.target===mask)close()};
  mask.classList.add('on');
  if(window.gaSpringModalOpen)gaSpringModalOpen(card);   // M3: 弹层入场弹簧(关态零内联样式 → CSS scale 过渡回退不变)
  if(ipt){setTimeout(()=>{try{ipt.focus();ipt.select()}catch(e){}},60);ipt.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();ok.click()}}}}
function gaPrompt(title,value,onOk,ph){gaModal({title,input:ph||true,value,onOk})}
function gaConfirm(title,msg,onOk,danger){gaModal({title,msg,danger,okText:danger?t('del'):t('ok'),onOk:()=>onOk&&onOk()})}
function showPrivacyConsent(onAgree){
  const mask=$('modalMask'),card=$('modalCard');
  card.className='modalCard privacyCard';
  card.innerHTML='<div class="pcHead"><h4></h4><p class="pcSub"></p></div><div class="pcBody"><p></p></div><div class="pcFoot"><button type="button" class="pcAgree" data-track="privacy_agree"></button></div>';
  card.querySelector('h4').textContent=t('privacyTitle');
  card.querySelector('.pcSub').textContent=t('privacySub');
  card.querySelector('.pcBody p').textContent=t('privacyBody');
  const agree=card.querySelector('.pcAgree');agree.textContent=t('privacyAgree');
  const go=function(ev){if(ev){try{ev.preventDefault();ev.stopPropagation()}catch(e){}}
    if(agree._busy)return;agree._busy=1;
    try{setPrivacyConsent()}catch(e){}
    mask.classList.remove('on');card.className='modalCard';   // 先关页: 用户点同意=明确意图; kv 失败靠双写/内存旗, 不再用校验把人钉死
    try{GAT.emit('privacy_accept',{version:PRIVACY_VERSION})}catch(e){}
    setTimeout(function(){try{onAgree&&onAgree()}catch(e){try{toast(String(e&&e.message||e||'boot'))}catch(e2){}}},0)};
  agree.onclick=go;
  try{agree.addEventListener('pointerup',go,{passive:false})}catch(e){}
  mask.onclick=function(e){if(e.target!==mask)return;e.preventDefault();e.stopPropagation()};   // 只拦遮罩空白, 不吃掉按钮冒泡
  card.onclick=function(e){e.stopPropagation()};
  mask.classList.add('on');
  try{GAT.emit('privacy_shown',{version:PRIVACY_VERSION})}catch(e){}   // 同意页到达(算 →privacy_accept 转化率/卡同意页流失)
}
// 设置 → 关于 → 用户服务协议及隐私政策: 只读查看(可关闭, 不再要求同意)
function showPrivacyView(){const mask=$('modalMask'),card=$('modalCard');card.className='modalCard privacyCard';
  card.innerHTML='<div class="pcHead"><h4></h4></div><div class="pcBody"><p></p></div><div class="pcFoot"><button class="pcAgree"></button></div>';
  card.querySelector('h4').textContent=t('privacyTitle');card.querySelector('.pcBody p').textContent=t('privacyBody');
  const ok=card.querySelector('.pcAgree');ok.textContent=t('ok');
  const close=()=>{mask.classList.remove('on');card.className='modalCard'};
  ok.onclick=close;mask.onclick=e=>{if(e.target===mask)close()};
  mask.classList.add('on')}

/* 规范星标(v2.5 单一来源): 4 折对称凹边 sparkle, 几何居中(bbox 12,12), 用于 wordmark/提示行; index.html 的 .welcome/.otaSpark 内联同款 path 须与此同步。根治"多处星形不一致"。 */
const SPARK_SVG='<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2 C12.8 4 18 11.2 22 12 C20 12.8 12.8 18 12 22 C11.2 20 6 12.8 2 12 C4 11.2 11.2 6 12 2 Z"/></svg>';
function syncEmpty(){if(chat.children.length===0&&!emptyEl){emptyEl=el('div',null,chat);emptyEl.id='empty';
    // .heroCore 包一层: FX 视差帧顺带给文案组写反向 transform(单节点/合成器), 不动各子项布局
    emptyEl.innerHTML='<div class="heroCore"><div class="gaMark"><span class="spark" id="gaSpark" role="button" tabindex="0" aria-label="GenericAgent">'+SPARK_SVG+'</span><span class="gaWordmark">Generic Agent</span></div>'+
      '<h2 data-i18n="emptyH"></h2><p data-i18n="emptyP"></p><div class="tipLine" id="tipLine"></div>'+
      '<div id="heroChips" role="group" aria-label="suggestions"></div></div>';
    emptyEl.querySelector('h2').textContent=t('emptyH');emptyEl.querySelector('p').textContent=t('emptyP');
    refreshTip();bindSpark($('gaSpark'));renderHeroChips();FX.mount(emptyEl);}   // FX 生命周期与 emptyEl 完全绑定
  else if(chat.children.length>1&&emptyEl)dropEmpty()}
function dropEmpty(){if(_host!==chat)return;FX.destroy();if(emptyEl){emptyEl.remove();emptyEl=null}
  const sh=$('shareHintTip');if(sh)sh.remove()}   // emptyEl 所有移除路径唯一出口: 先断 FX(监听+rAF)再拆 DOM; 顺带清分享引导气泡(锚点按钮随会话切换消失→气泡悬空)
function refreshTip(){const e=$('tipLine');if(e)e.innerHTML='<span class="tipMark" aria-hidden="true">'+SPARK_SVG+'</span> '+curTip()}
/* ✦ 标记: 轻点切换提示(已移除宠物 / 长按彩蛋, 保持极简, 见 issue#4); 顺带换一批 chips(彩蛋联动) */
function bindSpark(e){if(!e)return;
  e.onclick=()=>{_tipIdx++;refreshTip();_chipOfs++;renderHeroChips()};
  e.onkeydown=ev=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();_tipIdx++;refreshTip();_chipOfs++;renderHeroChips()}}}

/* ════════════ 起始页预置任务 chips(内置默认 + OTA latest.json 远程覆盖) ════════════ */
// 图标白名单注册表: OTA 只下发图标名, 未知名回退 spark——远程禁注入 SVG(安全面收敛在本地)
const HERO_ICONS={
  boba:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8h12l-1.5 12a2 2 0 0 1-2 1.8h-5A2 2 0 0 1 7.5 20Z"/><path d="M5 8l1.2-3.5A2 2 0 0 1 8.1 3H12l7-1.5"/><circle cx="10" cy="14" r=".9"/><circle cx="13.5" cy="16.5" r=".9"/><circle cx="11" cy="18.5" r=".9"/></svg>',
  mail:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="m3.5 7 8.5 6 8.5-6"/></svg>',
  search:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  cal:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4.5" width="18" height="16" rx="3"/><path d="M8 2.5v4M16 2.5v4M3 9.5h18"/></svg>',
  shot:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2"/><circle cx="12" cy="12" r="3.2"/></svg>',
  spark:SPARK_SVG};
const _heroIcon=k=>Object.prototype.hasOwnProperty.call(HERO_ICONS,k)?HERO_ICONS[k]:HERO_ICONS.spark;   // hasOwn 化白名单查表: 防 'constructor' 等原型链键穿透(Monitor CONFIRMED)
const HERO_CHIPS={zh:[
    {icon:'boba', label:'点一杯奶茶',     prompt:'打开外卖软件，帮我点一杯常喝的奶茶，微糖去冰'},
    {icon:'mail', label:'整理重要邮件',   prompt:'查看我的邮箱，把今天重要的 email 信息整理成一份摘要给我'},
    {icon:'search',label:'小红书今日热门', prompt:'帮我在小红书上搜索今日热门话题，挑 3 个值得看的总结给我'},
    {icon:'cal',  label:'规划明天日程',   prompt:'看看我明天的日程安排，帮我规划出行时间并设好提醒'},
    {icon:'shot', label:'截屏识字记笔记', prompt:'截取当前屏幕并识别里面的文字，整理成一条笔记保存'}],
  en:[
    {icon:'boba', label:'Order bubble tea', prompt:'Open a food delivery app and order my usual bubble tea, less sugar, no ice'},
    {icon:'mail', label:'Digest my inbox',  prompt:'Check my email and summarize today’s important messages for me'},
    {icon:'search',label:'Trending on RED', prompt:'Search today’s trending topics on Xiaohongshu and brief me on the top 3'},
    {icon:'cal',  label:'Plan tomorrow',    prompt:'Look at my schedule for tomorrow, plan the commute and set reminders'},
    {icon:'shot', label:'Screenshot to note',prompt:'Take a screenshot, run OCR on it and save the text as a note'}]};
let _chipOfs=0;   // ✦ 彩蛋翻批偏移: >5 条数据源时轮换展示窗口
function heroChipsData(){
  const r=LS.get('chips.remote',null);
  const a=(r&&Array.isArray(r[lang])&&r[lang].length?r[lang]:HERO_CHIPS[lang]||HERO_CHIPS.zh).filter(c=>c&&c.label&&c.prompt);
  if(a.length<=5)return a;
  const o=_chipOfs%a.length;return a.slice(o,o+5).concat(a.slice(0,Math.max(0,o+5-a.length)))}
function renderHeroChips(){
  const box=emptyEl&&emptyEl.querySelector('#heroChips');if(!box)return;
  box.innerHTML='';
  heroChipsData().forEach((c,i)=>{
    const b=el('button','heroChip',box);b.type='button';
    b.style.setProperty('--d',(120+i*65)+'ms');                       // 渐入错峰
    b.innerHTML=_heroIcon(c.icon)+'<span class="cv"></span>';
    b.querySelector('.cv').textContent=c.label;
    b.setAttribute('aria-label',c.prompt);
    b.onclick=()=>{inp.value=c.prompt;inp.dispatchEvent(new Event('input'));inp.focus();   // 预填不发送(app.js adbAssist 先例): 用户可改写, 唯一发送口仍是发送键
      try{GAT.emit('hero_chip_tap',{i:i,icon:c.icon})}catch(e){}};
  })}
function _absorbHeroChips(m){   // OTA 渐进增强: 校验全过才落缓存, 任一不合格整体弃用(版本单调/壳版本门/长度/白名单图标)
  try{
    const h=m&&m.heroChips;if(!h)return;
    const cur=LS.get('chips.remote',null);
    if(!(+h.v>0)||(cur&&+h.v<=+cur.v))return;
    if(+h.minVc>0&&_appCode()<+h.minVc)return;
    const ok=a=>Array.isArray(a)&&a.length>=3&&a.length<=6&&a.every(c=>c&&typeof c.label==='string'&&c.label.length>0&&c.label.length<=20&&typeof c.prompt==='string'&&c.prompt.length>0&&c.prompt.length<=200);
    if(!ok(h.zh)||!ok(h.en))return;
    const clean=a=>a.map(c=>({icon:Object.prototype.hasOwnProperty.call(HERO_ICONS,c.icon)?c.icon:'spark',label:c.label,prompt:c.prompt}));
    LS.set('chips.remote',{v:+h.v,zh:clean(h.zh),en:clean(h.en)});
    if(emptyEl)renderHeroChips();
  }catch(e){}}

/* ════════════ 起始页交互特效(纯突发引擎)════════════
 * v2.23.1 用户定调: 背景回纯色(氛围光幕/网格/噪点/呼吸核全撤), 只留交互——
 * 触摸波纹+波前光尘(canvas) / 陀螺仪视差(heroCore 反向) lerp, 按需单 rAF, 帧末[无波纹 && 视差贴合]循环自灭 → 空闲恒 rAF=0。
 * 生命周期五闸: ①visibilitychange 停帧 ②dropEmpty 统一销毁 ③每次入帧/入波查 canvas.isConnected 自愈
 * ④reduced-motion → 不装(无常驻视觉可静态降级, 直接零监听零 DOM) ⑤低端档(内存<4G/核≤4)波纹减半+dpr≤1.5+30fps 帧闸。 */
const FX=(()=>{
  const LOW=((navigator.deviceMemory||8)<4)||((navigator.hardwareConcurrency||8)<=4);
  const reduced=()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let host=null,core=null,cvs=null,ctx=null,dpr=1,raf=0,alive=false;
  let rip=[],dust=[];               // 触摸波纹 / 波前光尘
  let tx=0,ty=0,cx=0,cy=0;          // 视差 目标/当前
  let ori0=null;                    // 陀螺仪基线(首个读数=自然持机角, 视差是相对量)
  let ripRGB='99,102,116',lastT=0;
  const GATE=LOW?1000/30:0, RIP_CAP=LOW?3:6, RIP_MS=900, DUST_MS=900;
  const clamp=v=>Math.max(-1,Math.min(1,v));
  function mount(emptyEl){
    if(alive)destroy();
    if(reduced())return;   // 纯交互引擎无静态档可言: reduced-motion 直接不装
    host=document.createElement('div');host.id='fx';host.setAttribute('aria-hidden','true');
    host.innerHTML='<canvas></canvas>';
    emptyEl.prepend(host);alive=true;
    core=emptyEl.querySelector('.heroCore');
    cvs=host.querySelector('canvas');ctx=cvs.getContext('2d');
    ripRGB=(getComputedStyle(host).getPropertyValue('--fxRip')||ripRGB).trim();
    resize();
    // 监听全挂 window/document + passive + 捕获, 不动任何元素 pointer-events(全局埋点先例)
    window.addEventListener('resize',resize);
    window.addEventListener('pointerdown',onDown,{capture:true,passive:true});
    window.addEventListener('deviceorientation',onOri,{passive:true});   // 无传感器/无权限=永不触发, 静默降级
    document.addEventListener('pointermove',onMouse,{passive:true});     // 仅 pointerType=mouse(桌面预览兜底), 真机触摸不冒充重力
    document.addEventListener('visibilitychange',onVis);
  }
  function resize(){if(!cvs||!cvs.isConnected)return;
    dpr=Math.min(window.devicePixelRatio||1,LOW?1.5:2);
    const r=cvs.getBoundingClientRect();
    cvs.width=Math.round(r.width*dpr);cvs.height=Math.round(r.height*dpr)}
  function onDown(e){
    if(!alive)return;
    if(!cvs||!cvs.isConnected){destroy();return}        // 自愈: emptyEl 已被外部整树移除 → 自行释放
    const r=cvs.getBoundingClientRect();
    const x=e.clientX-r.left,y=e.clientY-r.top;
    if(x<0||y<0||x>r.width||y>r.height)return;          // 只有 hero 区域内的触摸才生波纹
    if(rip.length>=RIP_CAP)rip.shift();
    const now=performance.now();
    rip.push({x:x*dpr,y:y*dpr,t:now});
    for(let i=0,n=LOW?2:3;i<n;i++){const a=Math.random()*6.2832,v=(18+Math.random()*26)*dpr/DUST_MS;   // 波前光尘: 涟漪"推开介质"的物质感
      dust.push({x:x*dpr,y:y*dpr,vx:Math.cos(a)*v,vy:Math.sin(a)*v,t:now});}
    if(dust.length>14)dust.splice(0,dust.length-14);
    wake();
  }
  function onOri(e){
    if(e.gamma==null&&e.beta==null)return;
    if(ori0===null)ori0={g:e.gamma||0,b:e.beta||0};
    tx=clamp(((e.gamma||0)-ori0.g)/26);ty=clamp(((e.beta||0)-ori0.b)/26);
    wake();
  }
  function onMouse(e){
    if(e.pointerType!=='mouse'||ori0!==null||!alive)return;
    tx=clamp((e.clientX/window.innerWidth-.5)*2);ty=clamp((e.clientY/window.innerHeight-.5)*2);
    wake();
  }
  function onVis(){
    if(document.hidden)stop();else wake()   // 不可见: rAF 停(无常驻 CSS 动画, 无需冻结)
  }
  function wake(){if(raf||!alive||document.hidden)return;raf=requestAnimationFrame(frame)}
  function stop(){if(raf){cancelAnimationFrame(raf);raf=0}}
  function frame(now){
    raf=0;
    if(!alive||!cvs||!cvs.isConnected){destroy();return}
    if(GATE&&now-lastT<GATE){raf=requestAnimationFrame(frame);return}
    lastT=now;
    cx+=(tx-cx)*.06;cy+=(ty-cy)*.06;   // 视差缓动: 只写 heroCore 一个反向 transform(合成器), 6/4.5px
    if(core)core.style.transform='translate3d('+(-cx*6).toFixed(2)+'px,'+(-cy*4.5).toFixed(2)+'px,0)';
    ctx.clearRect(0,0,cvs.width,cvs.height);
    rip=rip.filter(p=>now-p.t<RIP_MS);dust=dust.filter(p=>now-p.t<DUST_MS);
    for(const p of rip){
      const k=(now-p.t)/RIP_MS,r=(16+k*130)*dpr,a=.30*(1-k)*(1-k);
      const g=ctx.createRadialGradient(p.x,p.y,r*.5,p.x,p.y,r);
      g.addColorStop(0,'rgba('+ripRGB+',0)');g.addColorStop(.75,'rgba('+ripRGB+','+a.toFixed(3)+')');g.addColorStop(1,'rgba('+ripRGB+',0)');
      ctx.fillStyle=g;ctx.beginPath();ctx.arc(p.x,p.y,r,0,6.2832);ctx.fill();
      ctx.fillStyle='rgba('+ripRGB+','+(.5*(1-k)).toFixed(3)+')';
      ctx.beginPath();ctx.arc(p.x,p.y,2.2*dpr*(1-k),0,6.2832);ctx.fill();
    }
    for(const p of dust){
      const k=(now-p.t)/DUST_MS,dt=now-p.t;
      ctx.fillStyle='rgba('+ripRGB+','+(.55*(1-k)).toFixed(3)+')';
      ctx.beginPath();ctx.arc(p.x+p.vx*dt,p.y+p.vy*dt,1.4*dpr*(1-k)+.4,0,6.2832);ctx.fill();
    }
    const settled=Math.abs(tx-cx)<.004&&Math.abs(ty-cy)<.004;
    if(rip.length||dust.length||!settled)raf=requestAnimationFrame(frame);
    else{if(core)core.style.transform='translate3d('+(-tx*6).toFixed(2)+'px,'+(-ty*4.5).toFixed(2)+'px,0)';stop()}   // 循环自灭 → 空闲 rAF=0
  }
  function destroy(){
    stop();alive=false;
    window.removeEventListener('resize',resize);
    window.removeEventListener('pointerdown',onDown,{capture:true});
    window.removeEventListener('deviceorientation',onOri);
    document.removeEventListener('pointermove',onMouse);
    document.removeEventListener('visibilitychange',onVis);
    if(core)core.style.transform='';   // 归零残留视差: heroCore 属外部 DOM, 销毁不留痕
    if(host&&host.parentNode)host.remove();
    host=core=cvs=ctx=null;rip=[];dust=[];tx=ty=cx=cy=0;ori0=null;
  }
  return{mount,destroy,get alive(){return alive}};
})();

/* ════════════ 会话 / 抽屉(含 session 编辑) ════════════ */
/* 会话=独立屏(复刻 kelivo): 数据持久化到 localStorage, "新对话"清空面板, 抽屉点击重渲染 */
function _stripLangMsgs(cs){   // /lang 是纯控制命令, 永不留存于会话: 清历史遗留气泡 + 防经 hydrate 漏入模型上下文。幂等过滤(只删 user 的 /lang 轮, 无对应 assistant 轮可孤儿)
  if(Array.isArray(cs))cs.forEach(c=>{if(c&&Array.isArray(c.msgs))c.msgs=c.msgs.filter(m=>!(m&&m.role==='user'&&typeof m.text==='string'&&/^\/lang\b/i.test(m.text.trim())))});
  return cs}
let convos=_stripLangMsgs(LS.get('convoStore',[])); if(!Array.isArray(convos))convos=[];
let curConvo=null, startNew=true, replaying=false;   // 单会话引擎: 回滚前经 switchConvo 把后端对齐到目标会话(不再用侧信道标记"谁拥有 history")
function convoTitle(c){return (c.name||c.title||t('newChat')).replace(/\s+/g,' ').trim()||t('newChat')}
const SYS_CONVO_PREFIX='[通知触发上下文';let dwSysOpen=false;   // F0.2: 通知触发自动会话的标题前缀(android_entry.py:2205 实际为「[通知触发上下文·以下为…]」, 故不含右括号以兼容变体) + 抽屉「系统会话」组展开态(内存态, 默认折叠)
const CONVO_KEEP=200, STEP_CAP=1000, STEP_KEEP=80, STEP_CAP_LAST=8000;   // 会话存于设备文件(KV, 无配额)→ 上限放宽到 200; 每条消息只存最近 80 步、每步正文截 1000 字(仅防单条 runaway 过大); 末步放宽到 8000(对齐后端 _hist 上限): 末轮的 ask/报告是回放兜底渲染的数据源, 1000 字常被 checkpoint 参数占满→ask 被切掉→回放空白
/* 会话持久化: 主存=应用私有文件(GA /kv.*, 真·设备存储, 无配额) → 根治"存储空间不足"; localStorage 仅作启动快取与浏览器兜底 */
function kvSet(k,v){k=_nsKey(k);try{return GA.send('/kv.set '+k+' '+(typeof v==='string'?v:JSON.stringify(v)))==='ok'}catch(e){return false}}
const KV_CORRUPT={__corrupt:true};   // 哨兵: kv 文件非空但 JSON 损坏(截断)≠不存在 → 调用方须区分, 不可当空覆盖(失忆根因)
let _convoAuthLoaded=false;           // 写回门禁(I2): 本次启动是否已成功读到权威 convoStore(或确认主存确为空); false 时 saveConvos 不写 kv 主存, 只写 localStorage 快取
function kvGet(k){k=_nsKey(k);let r;try{r=GA.send('/kv.get '+k)}catch(e){return undefined}
  if(!r||(r[0]!=='['&&r[0]!=='{'))return undefined;   // 空/缺文件/非JSON(如"引擎未就绪") → 合法缺失
  try{return JSON.parse(r)}catch(e){return KV_CORRUPT}}   // 非空且像JSON却解析失败 → 损坏哨兵(不静默吞成 undefined)
function kvDel(k){k=_nsKey(k);try{GA.send('/kv.del '+k)}catch(e){}}   // 镜像 kvSet/kvGet: 删 kv 主存(_nsKey, 无 'ga.' 前缀; 即 saveConvos 经 kvSet 写入的那份)
function _slimCites(cs){   // 返工(监察#12): 落库侧防御性裁剪 — 与同行 artifacts:(m.artifacts||[]).slice(0,12) 同口径, 条数/字段长度不再只依赖 finish() 单一写点的 slice; 将来若出现第二个写 msg.cites 的路径, 落库体积仍有界
  try{if(!cs||!cs.length)return undefined;   // 空/缺失一律返回 undefined(JSON.stringify 直接丢键): 中断轮「不写不渲」语义与 H9 往返断言依赖此
    let n=5;try{n=CITE_KEEP}catch(e){}      // 单一真相=CITE_KEEP; try 兜 TDZ(本函数定义早于 const 声明行)
    return cs.slice(0,n).map(c=>{const o={u:String(c&&c.u||'').slice(0,300),h:String(c&&c.h||'').slice(0,60)};
      if(c&&c.t)o.t=String(c.t).slice(0,60);return o})
  }catch(e){return undefined}}
function slimConvo(c){return {id:c.id,title:c.title,name:c.name,label:c.label,pinned:c.pinned,deleted:c.deleted,ts:c.ts,
  msgs:(c.msgs||[]).map(m=>m.role==='user'?{role:'user',text:(m.text||'').slice(0,2000),atts:m.atts||[],ts:m.ts}
    :{role:'assistant',prompt:(m.prompt||'').slice(0,400),final:(m.final||'').slice(0,400),model:m.model,ts:m.ts,el:m.el,ti:m.ti,to:m.to,cr:m.cr,cw:m.cw,artifacts:(m.artifacts||[]).slice(0,12),
       fa:m.fa,cites:_slimCites(m.cites),   // U0.0(存量 bug 修复): fa 从未进白名单 → finish 写的中断标记落库即丢, 场景F回放冒充完成态; cites=D2 引用胶囊(纪律: 凡新增 task.msg.* 落库字段必须同改本白名单并以往返断言证明)
       steps:(m.steps||[]).slice(-STEP_KEEP).map((s,i,arr)=>({n:s.n,summary:s.summary,text:(s.text||'').slice(0,i===arr.length-1?STEP_CAP_LAST:STEP_CAP)}))})}}
function isEmptyAssistant(m){return m&&m.role==='assistant'&&!(m.steps&&m.steps.length)&&!(m.final&&m.final.trim())}
function pruneEmptyAssistants(c){if(!c||!c.msgs)return;   // P3d: 豁免所有 runs 在飞的 live msg + 全局 task.msg(多路并存不误剪)
  const lives=new Set();if(task&&task.msg)lives.add(task.msg);
  if(multi){for(const r of runs.values()){if(r&&r.running&&r.task&&r.task.msg)lives.add(r.task.msg)}}
  c.msgs=c.msgs.filter(m=>lives.has(m)||!isEmptyAssistant(m))}
let _saveT=0,_saveN=-1;
function saveConvosThrottled(n){const now=Date.now();if(n===_saveN&&now-_saveT<1500)return;   // 增量落库节流: saveConvos 全量序列化所有会话, 步数未变且距上次<1.5s 则跳过
  _saveT=now;_saveN=n;saveConvos()}
function saveConvos(){            // 仅保留最近 CONVO_KEEP 个(置顶恒留); 配额满则继续剪到能存下
  convos=convos.filter(c=>!c.deleted||c===curConvo);   // 已删会话彻底丢弃(连同正文), 不再占配额
  convos.forEach(pruneEmptyAssistants);                // 落库前剔除空/孤儿 assistant 轮(运行中的豁免) → 退出重进不再有空气泡/重复气泡
  const live=convos.filter(c=>!c.deleted);
  if(live.length>CONVO_KEEP){const kill=live.filter(c=>{if(c.pinned||c===curConvo||c===runConvo)return false;if(multi){const rr=runs.get(c.id);if(rr&&rr.running)return false}return true}).slice(0,live.length-CONVO_KEEP);   // P3d: 预览/多路在飞会话均不修剪
    convos=convos.filter(c=>!kill.includes(c))}
  const json=JSON.stringify(convos.filter(c=>!c.deleted).map(slimConvo));
  const kvok=_convoAuthLoaded&&kvSet('convoStore',json);     // 主存: 设备文件(无配额)。I2 门禁: 未成功读到权威会话前不写主存, 防降级空/旧数据覆盖(失忆固化根因)
  const sk=_lsStoreKey('convoStore');
  try{localStorage.setItem(sk,json)}                         // 快取: localStorage(可能满)
  catch(e){if(!kvok){                                        // 仅当文件存储也不可用(纯浏览器预览)才退回剪枝提示
      let pruned=false;
      while(true){const i=convos.findIndex(c=>{if(c.pinned||c===curConvo||c===runConvo||c.deleted)return false;if(multi){const rr=runs.get(c.id);if(rr&&rr.running)return false}return true});if(i<0)break;   // P3d: 配额回退同样豁免多路在飞
        convos.splice(i,1);pruned=true;
        try{localStorage.setItem(sk,JSON.stringify(convos.map(slimConvo)));break}catch(_){}}
      if(pruned)toast(t('t_pruned'));
    }}}                                                       // 文件存储已成功 → 静默忽略 localStorage 配额(数据已落设备存储)
function _recoverCorruptConvos(){   // 主存 JSON 损坏(只可能是本次原子写修复前遗留的旧截断文件; 原子写后新数据不会损坏)。隔离取证→localStorage 抢救→放行写回(损坏件已 quarantine, 让新会话能落盘, 不再每次启动卡在损坏态)
  try{const raw=GA.send('/kv.get '+_nsKey('convoStore'));if(raw)GA.send('/kv.set '+_nsKey('convoStore.corrupt')+' '+raw)}catch(e){}   // 隔离损坏主存供事后取证
  try{const ls=localStorage.getItem(_lsStoreKey('convoStore'));const a=ls&&JSON.parse(ls);if(Array.isArray(a))convos=_stripLangMsgs(a)}catch(e){}   // localStorage 快取抢救(能救多少救多少)
  _convoAuthLoaded=true;                                       // 损坏件已隔离+尽力抢救 → 放行写回
  try{saveConvos()}catch(e){}}                                 // 立即用抢救结果覆盖损坏主存 → 下次启动不再读到损坏再重复隔离(自愈, 不等用户交互)
function switchConvo(c){if(!c)return true;let r;try{r=GA.send('/convo '+c.id)}catch(e){}if(r==='busy'){toast(t('t_taskBusy'));return false}return true}  // 通知后端切到该会话上下文(根治串会话)+ 使其成为回滚目标(单会话引擎); 后端在飞任务停不下→回'busy'→不切并提示, 不静默吞
function ensureConvo(prompt){if(!curConvo||startNew){
    const c={id:uid(),title:(prompt||t('newChat')).slice(0,60),ts:Date.now(),msgs:[]};
    if(!switchConvo(c))return null;   // 后端在飞任务未停下(busy): 不开新会话, 让调用方中止本次发送(防发进未切的旧上下文); 已 toast 提示
    curConvo=c;convos.push(c);startNew=false;setHeaderTitle()}   // 新会话: 后端已开空上下文(不再串上个会话)
  else if(!switchConvo(curConvo))return null;   // 懒对齐(T5): 预览态消解后后端可能仍停在别会话, 发送咽喉统一收敛; 同 id 后端回 'same' 幂等免费
  return curConvo}
function userBubble(text,atts,ts,msgRef){
  dropEmpty();
  if(ts||!_noActs){const meta=el('div','uMeta');
    const ut=document.createElement('span');ut.className='ut';ut.textContent=fmtTime(ts);
    meta.appendChild(ut)}   // 去掉用户消息头像与「我」, 仅保留时间
  const w=el('div','uRow'), b=el('div','u',w);
  if(atts&&atts.length){const ab=el('div','att',b);atts.forEach(a=>{const ch=el('div','achip',ab);ch.innerHTML=ICO_FILE;const sp=document.createElement('span');sp.textContent=a.name;ch.appendChild(sp)})}
  const tx=document.createElement('span');tx.textContent=text;b.appendChild(tx);
  scroll(1);
  if(_noActs)return b;   // PCLINK v2.2: 远程会话不挂操作行(重试/编辑直发本机引擎=跨通道误发, #031-F4 同源风险)
  const r=el('div','uAct');
  const cp=el('button',null,r);cp.innerHTML=ICO_COPY;cp.setAttribute('aria-label',t('copy'));
  cp.onclick=()=>copyText(text,()=>{cp.classList.add('ok');cp.innerHTML=ICO_OK;setTimeout(()=>{cp.classList.remove('ok');cp.innerHTML=ICO_COPY},1200)});
  const rt=el('button',null,r);rt.innerHTML=ICO_REGEN;rt.setAttribute('aria-label',t('retry'));
  rt.onclick=()=>retryUserMsg(msgRef);   // 重试: 移除该轮(含回复)+ 回滚 → 把同一输入重新放回上下文重发(issue#4)
  const ed=el('button',null,r);ed.innerHTML=ICO_EDIT;ed.setAttribute('aria-label',t('editMsg'));
  ed.onclick=()=>editMsg(msgRef);   // 编辑: 截断该轮(含回复)+ 回滚 LLM 上下文 → 编辑后重发(issue#1)
  return b;   // 顺序: 复制 · 重试 · 编辑(issue#1)
}
function newTask(prompt,modelName,ts,stats){
  dropEmpty();
  task={box:el('div','task'),steps:[],done:false,prompt:prompt||'',t0:Date.now()};   // t0: task_aborted 埋点算"跑了多久才被按停"
  if(curConvo&&curConvo.id){task.box._cid=curConvo.id;task._cid=curConvo.id}   // P3c: per-run box 归属, render 串台守卫用
  const mdl=modelName||modelLabel();
  const h=el('div','assistHead',task.box);
  h.innerHTML=modelGlyph(dispModel(mdl),(curProvider()||{}).type)+'<span class="assistName"></span><span class="assistTime"></span><span class="assistState"></span>';
  h.querySelector('.assistName').textContent=dispModel(mdl);h.querySelector('.assistTime').textContent=fmtTime(ts);   // 回放也去 [1m]
  task.state=h.querySelector('.assistState');
  task.meta=el('div','runMeta',task.box);task.meta.style.display='none';     // 运行时间 + 输入/输出 token 渲染行
  task.sbox=el('div','ga-card ga-card--msg',task.box);                       // F2.1: 步骤流入正文卡; 头/统计/操作行留卡外(数据密度不回退); :empty 时 CSS 隐藏
  if(replaying){renderTaskStats(stats||{})}                                  // 回放: 渲染存档的 token/用时
  else{ensureConvo(prompt);runConvo=curConvo;   // 活体任务出生的唯一点(startTask/冷启接续都经此): 登记运行归属(T2)
    resetRunStats();runStats.t0=task.t0;   // 清零唯一点(与 startLive 边沿幂等配对): 总计时锚对齐 task.t0, 防 multi 每拍 startLive 把计时/token 打回 0
    task.state.classList.add('run');   // 运行态消息头仅脉冲点(动词/计时/token 在下方 runMeta 行), 不再叠加文字
    const ms=curConvo.msgs,tail=ms[ms.length-1];
    if(isEmptyAssistant(tail)&&(tail.prompt||'')===(prompt||'')){task.msg=tail;tail.model=mdl;tail.ts=Date.now()}   // 复用同 prompt 的尾部空回合, 不再追加重复空气泡
    else{task.msg={role:'assistant',prompt:prompt||'',model:mdl,ts:Date.now(),steps:[],final:''};ms.push(task.msg)}
    setHeaderTitle();renderDrawer()}   // 不在此落库: 空回合先不存, 等 setStep/finish 有内容再存(防退出重进出现空气泡)
  try{task.box.dataset.mk=((curConvo&&curConvo.id)||task._cid||'')+':'+((task.msg&&curConvo&&curConvo.msgs)?curConvo.msgs.indexOf(task.msg):'r')}catch(e){}   // F3.1 消息级稳定键(cid+msg 序; 回放='r'): 消息节点一次创建按键持有, poll 从不重建其它消息
  return task;
}
function renderTaskStats(s){if(!task)return;                                  // 完成态: 消息头只留 ✓; 用时·token 落在下方 runMeta 行
  stripRunSpin();   // 无条件摘 spin(在 hasEl||hasTok 守卫之前): 统计全空完成轮也不残留转圈
  const hasEl=s&&s.el!=null, hasTok=s&&(s.ti||s.to);
  if(task.state){task.state.classList.remove('run');task.state.innerHTML='<span class="ck2" aria-label="'+t('done')+'">'+ICO_CK+'</span>'}
  if(task.meta&&(hasEl||hasTok)){const m=task.meta;m.style.display='flex';m._skel=0;m._sig=null;m._tin=m._tout=m._ger=m._el=null;   // R7 去噪: 默认只留用时, token(含缓存)收进点按展开的详情; 归档 el/ti/to/cr/cw 格式零改动(纯显示层)
    let dt=hasTok?tokChips((s&&s.ti)||0,(s&&s.to)||0):'';
    if(s&&(s.cr||s.cw))dt+='<span class="tok" title="cache">⟲'+humanTok(s.cr||0)+(s.cw?('+'+humanTok(s.cw)):'')+'</span>';
    m.innerHTML=(hasEl?'<span class="muL">'+fmtElapsed(s.el)+'</span>':'')+(dt?'<span class="mChev" aria-hidden="true">›</span><span class="mtok">'+dt+'</span>':'');
    if(dt){m.classList.add('mx');if(!hasEl)m.classList.add('open');m.onclick=e=>{e.stopPropagation();m.classList.toggle('open')}}else{m.classList.remove('mx','open');m.onclick=null}}}
function setHeaderTitle(){const tt=$('hdrTitleTxt');   // 主页不再显示"GenericAgent"(与左侧 GA 字标重复); 仅会话内显示会话标题
  if(curConvo){tt.textContent=convoTitle(curConvo).slice(0,60);tt.style.display='';fitHeaderTitle()}
  else{tt.textContent='';tt.style.display='none'}}
function fitHeaderTitle(){const tt=$('hdrTitleTxt');if(!tt||tt.style.display==='none'||!tt.textContent)return;   // #1: 标题字号收缩到适配可用宽度(下限 13px)→ 长标题(任意语言)尽量多显, github 等关键词不被过早遮挡; 余下再 ellipsis 兜底
  tt.style.fontSize='';let px=17,guard=0;
  while(tt.scrollWidth>tt.clientWidth+1&&px>13&&guard++<6){px-=1;tt.style.fontSize=px+'px'}}
addEventListener('resize',()=>fitHeaderTitle());   // 旋转/键盘改变可用宽度 → 重新适配标题
function openDrawer(){GAT.emit('view_enter',{view:'drawer'});renderDrawer();$('drawer').classList.add('on');$('mask').classList.add('on');$('drawer').setAttribute('aria-hidden','false')}
function closeDrawer(){$('drawer').classList.remove('on');$('mask').classList.remove('on');$('drawer').setAttribute('aria-hidden','true')}
function gaPanelOpen(){return $('sheetMask').classList.contains('on')||['setv','modelv'].some(i=>{const e=$(i);return e&&e.classList.contains('on')})}
/* 边缘滑动手势(热更可用): 左缘右滑开抽屉 / 抽屉上左滑关。修复"左滑退出程序"; 系统返回手势另由 Kotlin onBackPressed→window.gaOnBack 接管 */
(function(){let sx=0,sy=0,track=false,edge=false;const EDGE=40,TH=55;
  addEventListener('touchstart',e=>{if(e.touches.length!==1||gaPanelOpen())return;const t=e.touches[0];sx=t.clientX;sy=t.clientY;
    const open=$('drawer').classList.contains('on');edge=sx<=EDGE;track=open||edge},{passive:true});
  addEventListener('touchmove',e=>{if(!track||e.touches.length!==1)return;const t=e.touches[0],dx=t.clientX-sx,dy=t.clientY-sy;
    if(Math.abs(dy)>Math.abs(dx))return;                                  // 竖向为主→交给页面滚动
    const open=$('drawer').classList.contains('on');
    if(!open&&edge&&dx>TH){openDrawer();track=false}
    else if(open&&dx<-TH){closeDrawer();track=false}},{passive:true});
  addEventListener('touchend',()=>{track=false;edge=false},{passive:true})})();
/* Kotlin 壳的返回(系统手势/返回键)会调用此函数: 有弹层/抽屉就先关(留在 app 内), 没有才返回 false 让壳退到后台 */
window.gaOnBack=function(){
  if($('shareMask')&&$('shareMask').classList.contains('on')){   // 分享预览浮层优先: 精修中首次返回=只取消精修(留在预览, 仿 OTA 下载中吞返回), 否则返回=关闭预览, 不退出 app
    if(typeof _shareRefineCancel==='function'&&_shareRefineCancel())return true;
    closeSharePreview();return true}
  if($('otaMask')&&$('otaMask').classList.contains('on')){if(_otaPoll||(_otaM&&_otaM.mandatory))return true;closeOta();return true}   // 更新弹窗: 下载中/必需更新时吞掉返回不关
  if($('rangeMask')&&$('rangeMask').classList.contains('on')){closeRangePicker();return true}   // #2c: 自定义时间段弹层优先于其它返回处理
  if($('modalMask').classList.contains('on')){$('modalMask').classList.remove('on');return true}
  const fp=$('filePrev');if(fp&&fp.classList.contains('on')){closeFilePreview();return true}   // 文件预览(z80): 返回=关预览, 不整 app 退后台
  const pcSheet=document.getElementById('pcSheetWrap');if(pcSheet){pcSheet.remove();return true}   // PC 会话行操作单: 返回=关操作单, 不许穿透关掉底下的 PC 视图
  if($('sheetMask').classList.contains('on')){closeSheets();return true}
  if($('modelv')&&$('modelv').classList.contains('on')){closeModelListPage();return true}
  if($('setv')&&$('setv').classList.contains('on')){setvBack();return true}
  const dv=$('drawer');if(dv&&dv.classList.contains('on')){closeDrawer();return true}
  const pc=$('pcView');if(pc&&pc.classList.contains('on')){   // #034-P1: remote view on back stack — close side first, else closeView (stay in app)
    if(pc.classList.contains('side')){pc.classList.remove('side');return true}
    if(window.PCLINK&&typeof PCLINK.closeView==='function')PCLINK.closeView();else pc.classList.remove('on');
    return true}
  return false};   // 不变量: 返回=回桌面(交还给壳 moveTaskToBack)。无弹层/抽屉时不再劫持去开抽屉; 开抽屉改由左缘右滑/顶栏菜单(变量)
function stopRun(){  // 切换会话/清空前: multi 只停焦点会话(不杀后台 run); legacy 全停
  if(multi){const id=(curConvo&&curConvo.id)||(runConvo&&runConvo.id)||activeCid;if(id&&runs.get(id)&&runs.get(id).running){bridgeAbort(id);_abortWaitCid=id;setRunning(false,id)}task=null;return}
  if(running){const id=runConvo&&runConvo.id;bridgeAbort(id);_abortWaitCid=id;setRunning(false)}task=null}   // 切换会话/清空前: 中止在飞任务, 防 poll 空引用; _abortWaitCid=id → 后端收敛前 idle poll 不复活(T7)
function runLocked(){if(!anyRunning())return false;toast(t('t_taskBusy'));return true}   // 运行中冻结突变入口的统一谓词(T1): multi 下仍冻结全局危险操作(切 LLM/清库); 新建会话另开
function stopRunClean(){  // 用户主动/被迫中止并收尾: multi 只收焦点 cid
  if(multi){const id=(curConvo&&curConvo.id)||(runConvo&&runConvo.id)||activeCid;const rr=id&&runs.get(id);if(!rr||!rr.running)return;try{bridgeAbort(id)}catch(e){}_abortWaitCid=id;if(task&&!task.done){task._fail=1;finish()}setRunning(false,id);setStatus(modelLabel(),false);return}
  if(!running)return;const id=runConvo&&runConvo.id;try{bridgeAbort(id)}catch(e){}_abortWaitCid=id;if(task&&!task.done){task._fail=1;finish()}setRunning(false);setStatus(modelLabel(),false)}   // _fail: 中止轮不算"成功完成", 不触发分享引导气泡; _abortWaitCid=id → 防 idle poll 在后端收敛前复活(T7)
function newConversation(){if(multi){/* P3b: 允许多路并存时新建空会话, 不中止后台 run */}else if(running){toast(t('t_taskBusy'));return}   // legacy 单任务: 有在飞任务时不新建
  if(multi){task=null}else stopRun();exitGoalMode();   // multi: 只解绑本视图 task, 不 bridgeAbort 后台; legacy: stopRun 全停
  startNew=true;curConvo=null;activeCid=null;deviceState={current:null,devices:deviceState.devices||[]};refreshDeviceChip();chat.innerHTML='';dropEmpty();
  closeDrawer();setHeaderTitle();syncEmpty();renderDrawer();setStatus(modelLabel(),false);updateScrollNav();inp.focus()}   // 清空 chat 后无 scroll 事件, 手动收起滚动导航
function renderMsgsInto(host,msgs,opts){opts=opts||{};   // PCLINK v2.2(#031-F3): 参数化回放体 — 主链 renderMsgs=全副作用包装零变化; pclink 传 host+noActions+detachTask ⇒ 不写 curConvo/不挂操作行/不碰主滚动与空态; _host 切换仅同步窗口, finally 必还原(异步回调外逃不到)
  const ph=_host,pr=replaying,pn=_noActs,pt=task;
  _host=host||chat;replaying=true;_noActs=!!opts.noActions;
  try{(msgs||[]).forEach(m=>{if(opts.skip&&m===opts.skip)return;
    if(m.role==='user')userBubble(m.text,m.atts,m.ts,m);
    else{newTask(m.prompt,m.model,m.ts,{el:m.el,ti:m.ti,to:m.to,cr:m.cr,cw:m.cw});task._arts=m.artifacts||[];task._citeArc=m.cites||[];try{if(m.fa)task._fail=1}catch(e){}   // 回放(D2: cites 透给 task, 同 _arts 既有范式): 产物行取存档; STEP_FOLD §2.4.3: 存档 fa → 恢复 _fail, finish 的 _fail 分支自动走中断形态(场景F, 不冒充完成态)
      const steps=(m.steps&&m.steps.length)?m.steps:(m.final?[{n:1,summary:(m.final||'').slice(0,80),text:m.final}]:[]);
      steps.forEach(setStep);
      if(m.live){if(task.state){task.state.innerHTML='';task.state.classList.add('run')}   // PCLINK 快照重渲(#031-F5): 运行中 task 不 finish(不折叠不打勾), 头=脉冲点+末步展开; 归档 msgs 永无 live 字段, 主链不受影响
        const lc=task.steps[task.steps.length-1];if(lc&&!lc.classList.contains('open')){lc.classList.add('open');renderBody(lc)}}
      else finish()}})}               // 无 step 的 turn 也渲染 final, 并清掉"正在执行"
  finally{_host=ph;replaying=pr;_noActs=pn;if(opts.detachTask)task=pt}}
function patchReplaySteps(box,steps){   // PCLINK 流式增量桥: 临时把既有远端 task 挂给 setStep，复用主管线键控更新；不重建用户行/回答容器
  if(!box)return false;const sbox=box.querySelector('.ga-card--msg');if(!sbox)return false;
  const pt=task,pr=replaying,pn=_noActs,ph=_host;
  task={box:box,sbox:sbox,steps:[].slice.call(box.querySelectorAll('.step')),state:box.querySelector('.assistState'),meta:box.querySelector('.runMeta'),done:false,msg:null};
  replaying=true;_noActs=true;_host=box.parentNode||ph;
  try{(steps||[]).forEach(setStep);return true}finally{task=pt;replaying=pr;_noActs=pn;_host=ph}}
function renderMsgs(c,skip){                                // 纯回放公共体: 只画归档数据, 不碰 running/timer/后端; skip=在飞轮的 task.msg(resumeRun 用活体重挂替代回放)
  chat.innerHTML='';dropEmpty();curConvo=c;startNew=false;
  renderMsgsInto(chat,c.msgs,{skip:skip});
  setHeaderTitle();syncEmpty();scroll(1);requestAnimationFrame(()=>scroll(1));setTimeout(()=>{scroll(1);updateScrollNav()},80)}   // 进会话即达底: 同步 scroll(1) 早于安卓异步回流→补两拍重钉(照抄切语言已验证范式), 根治"长对话进入要滑多次才到底"
function renderConvo(c){if(!multi)stopRun();else{/* P3b: 多路不因重渲杀掉其他 run; 仅解绑本视图 task 引用由调用方处理 */}renderMsgs(c);setStatus(modelLabel(),false)}   // 空闲路径(抽屉点击/启动/回滚重渲)
function previewConvo(c){const lt=task;renderMsgs(c);task=lt}   // 运行中只读预览(T3/T4): 全局 task 借出即还(JS 单线程保证回放原子), 活体 DOM 继续在 detached box 累积
function resumeRun(){if(!runConvo)return;const lt=task;renderMsgs(runConvo,lt&&lt.msg);task=lt;   // 回到运行中会话: 归档轮回放(跳过在飞轮), 重挂仍在累积的活体 box, 流式状态零丢失; 判空防竞态(点击瞬间任务恰好结束→runConvo 已清)
  if(lt&&lt.box)chat.appendChild(lt.box);stick=true;scroll(1)}
function restoreAsk(c){let j;try{const _raw=(multi&&c&&c.id&&typeof GA.pollC==='function')?GA.pollC(c.id,'0'):GA.poll(0);j=parseBridge(_raw)||{}}catch(e){return}   // P3c: multi 用 pollC(cid); 预览期错过的 ask_user 后端是持久真相
  if(j.cmd_error)bubble('sys',j.cmd_error);   // poll(0) 会消费 cmd_error, 兜底显示(与冷启一致)
  if(!j.running&&j.active_convo===c.id&&j.ask&&(j.ask.question||(j.ask.candidates&&j.ask.candidates.length)))renderAskPicker(j.ask)}
function openConvo(c){if(!c||c===curConvo){closeDrawer();return}closeDrawer();   // 判空: 调用方引用可能在任务结束竞态中变 null
  if(multi){const rr=runs.get(c.id);curConvo=c;activeCid=c.id;startNew=false;setHeaderTitle();
    if(rr&&rr.running){runConvo=c;if(rr.task)task=rr.task;resumeRun();renderDrawer();return}   // 该会话在飞: 重挂活体
    if(anyRunning()){previewConvo(c);renderDrawer();return}   // 别的会话在飞: 只读预览, 不发 /convo 不打断
    if(switchConvo(c)){renderConvo(c);readDeviceState();restoreAsk(c);if(pendingAsk&&pendingAsk.cid===c.id)renderAskPicker(pendingAsk.ask)}renderDrawer();return}
  if(running){if(c===runConvo)resumeRun();else previewConvo(c);return}   // legacy 运行中(T3)
  if(switchConvo(c)){renderConvo(c);readDeviceState();restoreAsk(c);
    if(pendingAsk&&pendingAsk.cid===c.id)renderAskPicker(pendingAsk.ask)}}   // 空闲: 切后端上下文再重渲
function clearAllConvos(){if(anyRunning()){toast(t('t_taskBusy'));return}gaConfirm(t('clearAll'),t('confirmClear'),()=>{
  try{GAT.emit('clear_convos',{n:convos.filter(c=>!c.deleted).length})}catch(e){}   // 埋点: 清空全部对话(确认后; 仅会话数, 与 clear_cache 缓存清理区分)
  try{GA.send('/clear')}catch(e){}convos=[];LS.del('convoStore');kvDel('convoStore');stopRun();newConversation();renderDrawer();toast(t('t_clearedAll'))},true)}   // /clear 清后端(chat.json+kv+会话快照+LLM日志+上下文); 前端对称删 convoStore 写入的每一处: LS.del(localStorage 快取 + kv 'ga.'前缀)+kvDel(saveConvos 经 kvSet 写的无前缀 kv) → 删除集≡写入集, 重开不再从快取读回(修"清空后重启全回来")
function convoState(c){if(multi){const rr=c&&runs.get(c.id);if(rr&&rr.running)return 'run'}else if(c===runConvo&&running)return 'run';   // 进行中: multi 跟 runs; legacy 跟 runConvo
  const m=c.msgs||[],last=m[m.length-1];
  if(!last||last.role==='user')return 'wait';                   // 空会话 / 末条是用户消息(还没回复) → 等待用户交互
  return 'done'}                                                // 末条是 assistant 回复 → 已完成
function renderDrawer(){
  const list=$('dwList'),q=($('dwSearchIn')?.value||'').trim().toLowerCase();list.innerHTML='';
  const items=convos.filter(c=>!c.deleted).filter(c=>!q||convoTitle(c).toLowerCase().includes(q));
  if(!items.length){list.innerHTML='<div class="dwEmpty">'+(q?t('noMatchConvo'):t('noConvo')+'<br>'+t('clickNew'))+'</div>';return}
  const isSysConvo=c=>{const i=convoTitle(c).indexOf(SYS_CONVO_PREFIX);return i>-1&&i<=4};                // F0.2: 仅展示层分组, 不删数据/不动生命周期; 真机标题带「⏰ 」等 emoji 前缀(idx=2), 放宽到前 4 字符内命中
  const pinned=items.filter(c=>c.pinned).reverse(), normal=items.filter(c=>!c.pinned&&(q?true:!isSysConvo(c))).reverse(),
        sysArr=q?[]:items.filter(c=>!c.pinned&&isSysConvo(c)).reverse();                                  // 搜索时不分组(直接可命中找回); 置顶的系统会话保留在置顶区(防误伤)
  const add=(arr,label)=>{if(!arr.length)return;if(label){const s=document.createElement('div');s.className='dwSec';s.textContent=label;list.appendChild(s)}
    arr.forEach(c=>{const it=el('div','dwItem'+(c===curConvo?' cur':''),list);it.tabIndex=0;it.setAttribute('role','button');   // 可 Tab 聚焦 → 配合既有 Enter/Space keydown
      const st=convoState(c),lbl=(lang==='en'?{run:'In progress',wait:'Awaiting you',done:'Completed'}:{run:'进行中',wait:'等待交互',done:'已完成'})[st];
      it.innerHTML='<span class="cst '+st+'" role="img" aria-label="'+lbl+'" title="'+lbl+'"><i></i></span><span class="t"></span>'+(c.pinned?'<span class="pinBadge" aria-hidden="true">'+ICO_PIN+'</span>':'');
      it.querySelector('.t').textContent=convoTitle(c);
      const mb=document.createElement('button');mb.className='more';mb.setAttribute('aria-label',t('sessOps'));mb.innerHTML=ICO_MORE;
      mb.onclick=e=>{e.stopPropagation();openSessMenu(c)};it.appendChild(mb);
      it.onclick=()=>openConvo(c)})};
  add(pinned,pinned.length?t('pinned'):'');add(normal,pinned.length?t('all'):'');
  if(sysArr.length){                                                                                     // F0.2: 「[通知触发上下文]」自动会话默认折叠成一行分组, 点击展开找回
    const h=document.createElement('div');h.className='dwSec dwSysHead'+(dwSysOpen?' open':'');
    h.tabIndex=0;h.setAttribute('role','button');h.setAttribute('aria-expanded',dwSysOpen?'true':'false');
    h.innerHTML='<span class="dwSysAr" aria-hidden="true">›</span><span class="dwSysT"></span>';
    h.querySelector('.dwSysT').textContent=t('sysConvos')+' ('+sysArr.length+')';
    h.onclick=()=>{dwSysOpen=!dwSysOpen;renderDrawer()};list.appendChild(h);
    if(dwSysOpen)add(sysArr,'');
  }
}
function openSessMenu(c){
  const menu=$('sessMenu');menu.innerHTML='';
  const mk=(icon,label,fn,danger)=>{const d=el('div','menuItem'+(danger?' danger':''),menu);d.innerHTML=icon+'<span>'+label+'</span>';d.onclick=()=>{closeSheets();fn()}};
  mk(ICO_EDIT,t('rename'),()=>renameSession(c));
  mk(ICO_PIN,c.pinned?t('unpin'):t('pin'),()=>{c.pinned=!c.pinned;saveConvos();renderDrawer()});
  mk(ICO_REGEN,t('regenTitle'),()=>{c.name=undefined;c.title=(c.msgs&&c.msgs.find(m=>m.role==='user')||{}).text||c.title;saveConvos();renderDrawer();setHeaderTitle();toast(t('t_resetTitle'))});
  mk(ICO_TRASH,t('delConvo'),()=>{const _rr=multi&&runs.get(c.id);if((c===runConvo&&running)||(_rr&&_rr.running)){toast(t('t_taskBusy'));return}c.deleted=true;saveConvos();   // P3d: multi 删在飞会话先拒; 删被预览的:回落
    if(c===curConvo){if(anyRunning()){resumeRun();renderDrawer()}else{stopRun();newConversation()}}else renderDrawer()},true);
  openSheet('sessSheet');
}
function renameSession(c){gaPrompt(t('convoName'),c.name||c.title||'',v=>{if(v!=null){c.name=(v||'').trim()||c.title;saveConvos();renderDrawer();setHeaderTitle()}})}

/* ── 生成文件: file_write/file_patch 内联 diff + 文件预览 + 文件面板(需求2) ── */
const _enc=s=>encodeURIComponent(s).replace(/'/g,'%27');                  // 安全进 onclick 字面量(encodeURIComponent 不转 ')
function _diffLines(oldText,newText){                                     // file_patch=定点块替换→旧块全'-'/新块全'+'(精确极简, 无需 LCS)
  const L=s=>(s==null?'':String(s)).replace(/\n$/,'').split('\n'),rows=[];
  if(oldText!=null&&oldText!=='')L(oldText).forEach(l=>rows.push(['-',l]));
  if(newText!=null&&newText!=='')L(newText).forEach(l=>rows.push(['+',l]));
  return rows;
}
function renderDiffHtml(d){
  const a=d.args||{},path=a.path||'?',base=String(path).split('/').pop();
  let all,sub;
  if(d.tool==='file_patch'){all=_diffLines(a.old_content,a.new_content);sub='file_patch';}
  else{all=_diffLines('',a.content!=null?a.content:'');sub='file_write · '+(a.mode||'overwrite');}
  const add=all.filter(r=>r[0]==='+').length,del=all.filter(r=>r[0]==='-').length;   // S4: 全量统计(在 CAP 切片前算, 否则大 diff 徽标少计)
  const CAP=60,more=all.length>CAP?all.length-CAP:0,rows=all.slice(0,CAP);
  let body=rows.map(r=>'<div class="dl '+(r[0]==='+'?'da':'dd')+'"><span class="dg">'+r[0]+'</span>'+_escd(r[1]||' ')+'</div>').join('');
  if(more)body+='<div class="dl dmore">… +'+more+' '+t('diffMore')+'</div>';
  if(!all.length)body='<div class="dl dmore">'+t('diffTapView')+'</div>';   // file_write 内容不在 args(主写法) → 无行可展示, 引导点开看全文
  const stat=(del?'<span class="dsd">-'+del+'</span>':'')+(add?'<span class="dsa">+'+add+'</span>':'');
  return '<div class="diffCard"><button class="diffHd" onclick="openFilePreview(\''+_enc(path)+'\')">'
    +fileIcon(fileKind(base),'dfic')
    +'<span class="dfn">'+_escd(base)+'</span><span class="dsub">'+_escd(sub)+'</span><span class="dstat">'+stat+'</span></button>'
    +'<div class="diffBody"><div class="diffInner">'+body+'</div></div></div>';   // diffInner=max-content 内层: 行背景随最宽行伸展 → 横向滚动右侧不留白(见 app.css .diffInner)
}
function _reescapeJson(s){                                                // 还原 get_pretty_json 的展示态: 它把字符串值内的 \n 转成裸换行→非法JSON; 在串内把裸换行/制表回转义
  let out='',inStr=false,esc=false;
  for(let i=0;i<s.length;i++){const c=s[i];
    if(esc){out+=c;esc=false;continue}
    if(c==='\\'){out+=c;esc=true;continue}
    if(c==='"'){inStr=!inStr;out+=c;continue}
    if(inStr&&c==='\n'){out+='\\n';continue}
    if(inStr&&c==='\r'){out+='\\r';continue}
    if(inStr&&c==='\t'){out+='\\t';continue}
    out+=c;}
  return out;
}
function extractFileDiffs(text){                                          // 在【原始】step 文本上把 file_write/file_patch 工具块抽出→占位符, 渲染后回填 diff 卡
  const diffs=[];
  const out=text.replace(/🛠️?\s*Tool:\s*`?(file_write|file_patch)`?\s*📥?\s*args:\s*\n`{4,}\w*\n([\s\S]*?)\n`{4,}/g,(m,tool,bd,off,whole)=>{
    let args;try{args=JSON.parse(_reescapeJson(bd))}catch(e){return m}     // get_pretty_json 破坏了 JSON → 先回转义; 仍失败则原样保留(不破坏内容)
    if(tool==='file_write'&&(args.content==null||args.content==='')){      // 内容在 <file_content> 标签里(GA 主写法, args 无 content) → 取本块之前最近一段
      const fcs=String(whole.slice(0,off)).match(/<file_content[^>]*>[\s\S]*?<\/file_content>/g);
      if(fcs){const last=fcs[fcs.length-1].match(/<file_content[^>]*>([\s\S]*?)<\/file_content>/);if(last)args.content=last[1].replace(/^\n/,'').replace(/\s+$/,'');}
    }
    const i=diffs.length;diffs.push({tool,args});return '\n\n@@GADIFF'+i+'@@\n\n';});
  return {text:out,diffs};
}
function injectDiffs(html,diffs){
  diffs.forEach((d,i)=>{html=html.replace(new RegExp('(?:<p>\\s*)?@@GADIFF'+i+'@@(?:\\s*</p>)?'),()=>renderDiffHtml(d))});
  return html;
}
/* ── 通用预览路由(v2.18): ext→channel 注册表, 与后端 _KIND_EXT 同一契约; 新格式=两表各加一行。
     字节路径不变量(I3): image/video/audio/html 走 file:// 同源直显零过桥, pdf 走原生页图, 桥上只过文本/rows/meta。
     XSS 纪律(I4): 本区 innerHTML 不经 md()/DOMPurify, 一切外来值必经 _escd(文本位)/_enc(URL/onclick 位)。 ── */
const FKIND=[
  ['image',/\.(png|jpe?g|gif|webp|bmp|svg|heic|heif)$/i],
  ['video',/\.(mp4|webm|mov|m4v|3gp|mkv)$/i],
  ['audio',/\.(mp3|wav|m4a|ogg|aac|flac|amr)$/i],
  ['html',/\.html?$/i],
  ['md',/\.(md|markdown)$/i],
  ['pdf',/\.pdf$/i],
  ['sheet',/\.(xlsx|csv|tsv)$/i],
  ['office',/\.(pptx|docx)$/i]];
function fileKind(n){const h=FKIND.find(k=>k[1].test(n||''));return h?h[0]:'text'}
const _fileUrl=rel=>'../temp/'+_enc(rel).replace(/%2F/g,'/');
const _FICO={
  image:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.6-3.6a2 2 0 0 0-2.8 0L6 21"/>',
  video:'<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m10 9 5 3-5 3z"/>',
  audio:'<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  html:'<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
  pdf:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h5"/>',
  sheet:'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/>',
  office:'<path d="M2 3h20"/><path d="M21 3v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V3"/><path d="m9 16-3 5M15 16l3 5M12 16v5"/>',
  text:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>'};
_FICO.md=_FICO.text;_FICO.other=_FICO.text;
function fileIcon(k,cls){return '<svg'+(cls?' class="'+cls+'"':'')+' viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'+(_FICO[k]||_FICO.text)+'</svg>'}
function _sheetHtml(r){const rows=r.rows||[];if(!rows.length)return '<div class="fpLoad">'+t('noPreview')+'</div>';
  const body=rows.map(rw=>'<tr>'+rw.map(c=>'<td>'+_escd(c)+'</td>').join('')+'</tr>').join('');
  return (r.sheets>1?'<div class="fpHint">'+t('sheetFirstOnly')+'</div>':'')+'<div class="fpTable"><table>'+body+'</table></div>'}
function _officeHtml(r){const secs=r.sections||[],hint='<div class="fpHint">'+t('officeHint')+'</div>';
  if(!secs.length)return hint+'<div class="fpLoad">'+t('noPreview')+'</div>';
  if(r.office==='pptx')return hint+secs.map((s,i)=>'<div class="fpSlide"><div class="fpSlideNo">'+(i+1)+'</div>'
    +(s[0]?'<div class="t1">'+_escd(s[0])+'</div>':'')+s.slice(1).map(x=>'<p>'+_escd(x)+'</p>').join('')+'</div>').join('');
  return hint+secs.map(s=>'<p class="fpPara">'+_escd(s[0]||'')+'</p>').join('')}
function _infoHtml(rel,r){const base=rel.split('/').pop();
  return '<div class="fpInfo">'+fileIcon(fileKind(base))+'<div class="nm">'+_escd(base)+'</div>'
    +((r&&r.size)?'<div class="mt">'+humanBytes(r.size)+'</div>':'')+'<div class="mt">'+t('noPreview')+'</div>'
    +'<button class="btnPrimary" onclick="openFileExternal(\''+_enc(rel)+'\')">'+t('openWith')+'</button></div>'}
const FP_POSTER='data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';   // 1px 透明 poster: 压掉低清首帧, 未播时呈纯黑卡片(Apple 风格)
const FP_RENDER={   // channel→渲染器: 对任意 kind 是总函数(I1), 未知/异常一律落 other 信息卡(I6)
  image:rel=>'<div class="fpImgWrap"><img src="'+_fileUrl(rel)+'" alt=""></div>',
  video:rel=>'<div class="fpMedia"><video class="fpVideo" controls playsinline preload="metadata" poster="'+FP_POSTER+'" src="'+_fileUrl(rel)
    +'" onerror="fpMediaFail(this,\''+_enc(rel)+'\')"></video></div>',   // poster 压掉 WebView 灰色默认占位; 播放入口=原生 controls。解码失败(如 mp4v)→整卡降级提示+系统打开
  audio:rel=>'<div class="fpPad"><audio class="fpAudio" controls preload="metadata" src="'+_fileUrl(rel)
    +'" onerror="fpMediaFail(this,\''+_enc(rel)+'\')"></audio></div>',
  html:rel=>'<iframe class="fpFrame" sandbox src="'+_fileUrl(rel)+'"></iframe>',   // 仅旧壳回退: 全 sandbox 禁脚本(主 WebView 的 GA 桥注入所有 frame, 绝不给产物脚本执行面); 新壳走 openHtmlPreview 无桥 Activity
  md:(rel,r)=>'<div class="fpMd md">'+((!window.GA_RENDER_LEGACY&&window.renderRich)?'':md(r.text||''))+'</div>',   // F1.1: 新管线时留空壳, showFilePreview 尾部经 renderRich 回填(同一出口)
  pdf:()=>'<div class="fpLoad">'+t('pdfRendering')+'</div>',
  sheet:(rel,r)=>_sheetHtml(r),
  office:(rel,r)=>_officeHtml(r),
  text:(rel,r)=>'<pre class="fpPre">'+_escd(r.text||'')+'</pre>',
  other:(rel,r)=>_infoHtml(rel,r)};
function fpMediaFail(el,enc){const rel=decodeURIComponent(enc||''),ov=$('filePrev'),body=ov&&ov.querySelector('.fpBody');   // 媒体元素报错→降级信息卡(编码不支持等)
  if(!body)return;body.innerHTML=_infoHtml(rel,{})+'<div class="fpTrunc">'+t('mediaNoCodec')+'</div>'}
function openFilePreview(enc){
  const rel=decodeURIComponent(enc||'');if(!rel)return;
  if(/(^|\/)\.\.(\/|$)/.test(rel)){toast(t('fileOpenFail'));return}   // I2: 直显通道同样锁 temp 沙盒(diff 卡路径来自原始 agent 文本, 不可信)
  const k=fileKind(rel);
  try{GAT.emit('file_preview',{kind:k})}catch(e){}   // 埋点: 仅 kind, 不含路径/内容(脱敏铁律)
  let r=null;try{if(window.GA&&GA.send)r=JSON.parse(GA.send('/files.read '+rel))}catch(e){}   // 统一存在性门禁: /files.read 对直显类只回 meta(I3 不变量), 零成本
  if(r&&!r.ok){toast(t('fileOpenFail'));return}   // 文件已被清理的陈旧 chip/列表项: 早失败一次明确提示(修: 缺文件被 onerror 误报成"编码不支持"卡+外开 not-found 双重困惑)
  if(k==='html')return openHtmlPreview(rel);   // I5(升级): html 产物走独立无桥 WebView, 脚本可跑但摸不到 GA 桥
  if(k==='image'||k==='video'||k==='audio')return showFilePreview(rel,(r&&r.ok)?r:{ok:true,kind:k,path:rel});   // 同源直显(字节走 file://); 无桥(浏览器 demo)回退直显
  if(k==='pdf')return openPdfPreview(rel);
  if(!r||!r.ok){toast(t('t_checkFail'));return}   // 非直显类必须有后端载荷(旧壳缺桥→提示)
  showFilePreview(rel,r);
}
function showFilePreview(rel,r){
  const ov=$('filePrev');if(!ov)return;const base=rel.split('/').pop(),k=(r&&r.kind)||fileKind(rel);
  let inner;try{inner=(FP_RENDER[k]||FP_RENDER.other)(rel,r||{})}catch(e){inner=_infoHtml(rel,r||{})}
  const trunc=(r&&r.truncated)?'<div class="fpTrunc">'+t(k==='sheet'?'sheetTruncated':'fileTruncated')+'</div>':'';
  const gal=(k==='video'||k==='image'||k==='audio')&&window.GA&&GA.saveToGallery   // 媒体类: 存相册后任意播放器/相册可用(系统打开对 content:// 接单少的兜底)
    ?'<button class="fpAct" onclick="saveFileToGallery(\''+_enc(rel)+'\')" aria-label="'+t('saveGallery')+'" title="'+t('saveGallery')+'">'+ICO_SAVEGAL+'</button>':'';
  ov.innerHTML='<div class="fpCard'+((k==='html'||k==='pdf')?' fpFull':'')+'"><div class="fpHd"><span class="fpName">'+_escd(base)+'</span>'+gal
    +'<button class="fpAct" onclick="openFileExternal(\''+_enc(rel)+'\')" aria-label="'+t('openWith')+'" title="'+t('openWith')+'">'+ICO_OPENEXT+'</button>'
    +'<button class="fpClose" onclick="closeFilePreview()" aria-label="close"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg></button></div>'
    +'<div class="fpBody">'+inner+trunc+'</div></div>';
  ov.classList.add('on');
  const m=ov.querySelector('.fpMd');
  if(m){if(!window.GA_RENDER_LEGACY&&window.renderRich)m.appendChild(renderRich((r&&r.text)||'',{mode:'chat',linkify:false}));   // F1.1: 预览 md 收口(legacy 本就不 linkify, 保持等价)
    else if(typeof decorateCode==='function'){decorateCode(m);wrapTables(m)}}
}
function openFileExternal(enc){const rel=decodeURIComponent(enc||'');if(!rel)return;
  if(!(window.GA&&GA.openFile)){toast(t('openWithUnavail'));return}   // 热更 webui 跑在旧壳: 桥方法缺失→提示升级, 不硬崩
  let r='err';try{r=GA.openFile(rel)}catch(e){}
  try{GAT.emit('file_open_ext',{kind:fileKind(rel),ok:r==='ok'})}catch(e){}
  if(r!=='ok')toast(r==='err:not-found'?t('fileOpenFail'):t('openWithNoApp'))}
function saveFileToGallery(enc){const rel=decodeURIComponent(enc||'');if(!rel)return;
  let r='err';try{r=GA.saveToGallery(rel)}catch(e){}
  try{GAT.emit('file_save_gallery',{kind:fileKind(rel),ok:r==='ok'})}catch(e){}
  toast(r==='ok'?t('saveGalleryDone'):t('t_checkFail'))}
let _pdfPoll=0;
function openHtmlPreview(rel){
  if(window.GA&&GA.previewHtml){let r='err';try{r=GA.previewHtml(rel)}catch(e){}
    if(r!=='ok')toast(t('fileOpenFail'));return}
  showFilePreview(rel,{ok:true,kind:'html',path:rel})}   // 旧壳(无 previewHtml 桥): 禁脚本 iframe 静态渲染兜底
function openPdfPreview(rel){
  if(!(window.GA&&GA.pdfRender))return showFilePreview(rel,{ok:true,kind:'other',path:rel});   // 旧壳无 PDF 桥→信息卡+系统打开
  showFilePreview(rel,{ok:true,kind:'pdf',path:rel});                                          // 先开占位(渲染中), 后台转页图
  let id='';try{id=GA.pdfRender(rel)}catch(e){}
  clearInterval(_pdfPoll);
  if(!id||/^err/.test(id))return _pdfBody(rel,null);
  _pdfPoll=setInterval(()=>{
    let s='';try{s=GA.pdfResult(id)}catch(e){s='err:bridge'}
    if(s==='pending')return;
    clearInterval(_pdfPoll);_pdfPoll=0;
    let j=null;if(!/^err/.test(s)){try{j=JSON.parse(s)}catch(e){}}
    _pdfBody(rel,(j&&j.ok)?j:null);
  },300);
}
function _pdfBody(rel,j){const ov=$('filePrev'),body=ov&&ov.querySelector('.fpBody');if(!body)return;   // 用户已关预览→丢弃
  if(!j){const c=ov.querySelector('.fpCard');if(c)c.classList.remove('fpFull');body.innerHTML=_infoHtml(rel,{});return}   // 渲染失败→信息卡(I6), 收回全屏高度
  body.innerHTML='<div class="fpPdf">'+j.pages.map(p=>'<img src="'+_escd(p).replace(/"/g,'&quot;')+'" loading="lazy" alt="">').join('')
    +(j.total>j.rendered?'<div class="fpTrunc">'+t('pdfPartial').replace('{n}',j.rendered).replace('{m}',j.total)+'</div>':'')+'</div>'}
function closeFilePreview(){clearInterval(_pdfPoll);_pdfPoll=0;const ov=$('filePrev');if(ov){ov.classList.remove('on');ov.innerHTML=''}}
/* ── 本轮产物行: 发送前快照 /files.list → finish 差分 → chips(落库 msg.artifacts 供回放) ── */
function _filesSnap(){try{const r=JSON.parse(GA.send('/files.list'));const m={};((r&&r.files)||[]).forEach(f=>m[f.path]=f.mtime+':'+f.size);return m}catch(e){return null}}
/* ── 正文产物超链接: 行内 code 精确命中已知产物名/路径 → 点击预览(chips 之外的第二入口; miss 静默无副作用) ── */
let _flIdx=null;   // name/path → rel 索引; 实时轮 finish 置空重建; 重名取 mtime 最新
function _fileIdx(){if(_flIdx)return _flIdx;const m=Object.create(null);   // 无原型: 防 constructor 等文件名误中原型链
  try{(JSON.parse(GA.send('/files.list')).files||[]).forEach(f=>{m[f.path]=f.path;if(!(f.name in m))m[f.name]=f.path});_flIdx=m}catch(e){}   // 失败不缓存, 下次重试
  return _flIdx||m}
function linkifyFiles(sb){const idx=_fileIdx();   // 循环外取一次: 失败态不随 code 元素数放大桥调用
  sb.querySelectorAll('code').forEach(c=>{
    if(c.closest('pre,.fdCard,a'))return;
    const rel=idx[(c.textContent||'').trim().replace(/\\/g,'/').replace(/^\.\//,'')];
    if(rel){c.classList.add('fLink');c.onclick=e=>{e.stopPropagation();openFilePreview(_enc(rel))}}})}
function linkifyArtifactAnchors(sb){const idx=_fileIdx();   // agent 常写 Markdown 链接; 相对 URL 会被 WebView 当 webui 子页导航，先按产物索引解析并接入统一预览
  sb.querySelectorAll('a[href]').forEach(a=>{
    const raw=(a.getAttribute('href')||'').trim();if(!raw||/^[a-z][a-z0-9+.-]*:/i.test(raw)||raw.startsWith('//')||raw.startsWith('#'))return;
    let key='';try{key=decodeURIComponent(raw).replace(/\\/g,'/').replace(/^(?:\.\/)+/,'').replace(/^(?:\.\.\/)*temp\//,'')}catch(e){return}
    const rel=idx[key];if(!rel)return;
    a.setAttribute('href','#');a.onclick=e=>{e.preventDefault();e.stopPropagation();openFilePreview(_enc(rel))}
  })}
function _newArtifacts(snap){if(!snap)return[];
  try{const r=JSON.parse(GA.send('/files.list'));
    return ((r&&r.files)||[]).filter(f=>snap[f.path]!==(f.mtime+':'+f.size)).slice(0,12)
      .map(f=>({path:f.path,name:f.name,kind:fileKind(f.name),size:f.size}))}catch(e){return[]}}
function renderArtifacts(arts,box){if(!arts||!arts.length||!box)return;
  const row=el('div','artRow',box);row.innerHTML='<div class="artLbl">'+t('turnArtifacts')+'</div>';
  const wrap=el('div','artChips',row);
  arts.forEach(a=>{const b=el('button','artChip',wrap);
    b.innerHTML='<span class="aIco">'+fileIcon(a.kind||fileKind(a.name))+'</span><span class="aNm">'+_escd(a.name)+'</span>';
    b.onclick=()=>openFilePreview(_enc(a.path))});
}
function openFilesPage(){setNav('filesPanel',t('genFiles'),'genFiles')}   // _setShow('filesPanel') 已驱动 renderFilesPage, 不重复(S3)
function renderFilesPage(){
  const box=$('filesList');if(!box)return;box.innerHTML='';
  let r;try{r=JSON.parse(GA.send('/files.list'))}catch(e){r=null}
  const fs=(r&&r.files)||[];
  if(!fs.length){box.innerHTML='<div class="filesEmpty">'+t('noFiles')+'</div>';return}
  fs.forEach(f=>{const row=el('button','fileRow',box);row.onclick=()=>openFilePreview(_enc(f.path));
    row.innerHTML='<span class="fIco">'+fileIcon(fileKind(f.name))+'</span><span class="fMid"><span class="fNm">'+_escd(f.name)+'</span>'
      +'<span class="fMeta">'+humanBytes(f.size)+' · '+_escd(f.path)+'</span></span>'
      +'<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>';
  });
}

/* ════════════ 记忆与技能面板: GA 的 SOP/记忆可视化(只读 + 让GA修改 + 重置出厂) ════════════ */
const _MEM_GRPS=[['global','memGrpGlobal'],['caps','memGrpCaps'],['mode','memGrpMode'],['sop','memGrpSop']];
function openMemPage(){setNav('memPanel',t('memPanelTitle'),'memPanelTitle')}
function _memT(m){const d=new Date(m*1000);const p=n=>String(n).padStart(2,'0');return (d.getMonth()+1)+'/'+d.getDate()+' '+p(d.getHours())+':'+p(d.getMinutes())}
function renderMemPage(){
  const box=$('memList');if(!box)return;box.innerHTML='';
  let r;try{r=JSON.parse(GA.send('/mem.list'))}catch(e){r=null}
  const fs=(r&&r.files)||[];
  if(!fs.length){box.innerHTML='<div class="filesEmpty">'+t('memEmpty')+'</div>';return}
  const ic='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>';
  _MEM_GRPS.forEach(g=>{const items=fs.filter(f=>f.group===g[0]);if(!items.length)return;
    el('div','secLbl',box).innerHTML='<span>'+t(g[1])+'</span>';
    const card=el('div','card',box);
    items.forEach(f=>{const row=el('button','fileRow',card);row.onclick=()=>openMemFile(f);
      row.innerHTML='<span class="fIco">'+ic+'</span><span class="fMid"><span class="fNm">'+_escd(f.name)+'</span>'
        +(f.desc?'<span class="memDesc">'+_escd(f.desc)+'</span>':'')
        +'<span class="fMeta">'+humanBytes(f.size)+' · '+_memT(f.mtime)+'</span></span>'
        +'<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>';
    });
  });
}
function openMemFile(f){
  if(!(window.GA&&GA.send)){toast(t('t_checkFail'));return}
  let r;try{r=JSON.parse(GA.send('/mem.read '+f.rel))}catch(e){r=null}
  if(!r||!r.ok){toast(t('fileOpenFail'));return}
  showFilePreview(f.rel,r);
  const ov=$('filePrev'),card=ov&&ov.querySelector('.fpCard');if(!card)return;
  const _fa=card.querySelector('.fpAct');if(_fa)_fa.remove();   // 记忆文件不在 temp 沙盒, "用其他应用打开"不适用
  if(f.rel==='capabilities.json'){try{                                     // 能力清单: 双语能力卡渲染, 解析失败保持 pre 原文(半径=该次渲染)
    const caps=(JSON.parse(r.text)||{}).capabilities,L=lang==='en'?'en':'zh',body=ov.querySelector('.fpBody');
    if(Array.isArray(caps)&&caps.length&&body)body.innerHTML=caps.map(c=>
      '<div class="capCard"><div class="capName">'+_escd((c.name&&c.name[L])||c.id||'')
      +(c.required?'<span class="capReq">'+t('memCoreBadge')+'</span>':'')+'</div>'
      +((c.why&&c.why[L])?'<div class="capWhy">'+_escd(c.why[L])+'</div>':'')
      +((c.unlock&&c.unlock[L])?'<div class="capUnlock">'+_escd(c.unlock[L])+'</div>':'')+'</div>').join('');
  }catch(e){}}
  const acts=document.createElement('div');acts.className='fpActs';        // 动作栏仅 mem 入口注入, 不动 showFilePreview 本体; DOM 闭包绑参, 文件名不进属性字符串
  const b1=document.createElement('button');b1.className='chip';b1.textContent=t('memAskGA');b1.onclick=()=>memAskGA(f.rel);acts.appendChild(b1);
  if(f.resettable){const b2=document.createElement('button');b2.className='chip chipDanger';b2.textContent=t('memReset');b2.onclick=()=>memReset(f.rel);acts.appendChild(b2)}
  card.appendChild(acts);
}
function memAskGA(rel){if(anyRunning()){toast(t('t_taskBusy'));return}          // P3d: anyRunning 冻结; 编辑经 agent 走 file_write
  closeFilePreview();closeSettings();newConversation();
  inp.value=t('memAskPrompt').replace('{f}',rel);inp.dispatchEvent(new Event('input'));inp.focus()}
function memReset(rel){if(anyRunning()){toast(t('t_taskBusy'));return}
  gaModal({title:t('memResetTitle'),msg:t('memResetMsg').replace('{f}',rel),danger:true,okText:t('memReset'),onOk:function(){
    let r;try{r=JSON.parse(GA.send('/mem.reset '+rel))}catch(e){r=null}
    if(r&&r.ok){toast(t('memResetDone'));closeFilePreview();renderMemPage()}
    else toast((r&&r.error)==='no-baseline'?t('memNoBaseline'):t('t_checkFail'))
  }})}

/* ════════════ step / 流式渲染(经验证) ════════════ */
if(window.GA_RENDER_FULL===undefined)window.GA_RENDER_FULL=false;   // F3.1 兜底开关: true=禁用键控 diff 守卫, 恢复整块重渲染旧路径(协议/700ms 轮询两侧均零改动)
function stepCard(n){const c=el('div','step live',task.sbox||task.box);   // F2.1: 步骤挂正文卡内(sbox); 旧 task 兜底原位
  c.dataset.gk=(task&&task._gen!=null?task._gen:'')+':'+n;   // F3.1 稳定键(沿用 gen+seq 复合键先例): 节点一次创建按键持有, poll 只 patch 不重建
  c.innerHTML='<div class="sh"><span class="sn">'+t('stepLabel')+' '+n+'</span><span class="ss"></span><span class="ssd"></span><span class="ar">›</span></div><div class="sb"></div>';   // STEPLABEL M1: .ssd=显示节点(E1/E2 唯一写靶); .ss 恒存内核原摘要(落库/分享真相源), 由 CSS 隐藏 ⇒ 显示与落库解耦
  c.querySelector('.sh').onclick=()=>{try{const _o=c.classList.contains('open');c._userOpen=!_o;c._userClosed=_o?1:0}catch(e){}   // STEP_FOLD §2.1.4/5: 先记用户意志再委托(spring 与原路径同源); 点开=_userOpen(前步不自动收), 点收=_userClosed(末步不再自动重开); 纯 expando 不动 DOM
    if(window.gaSpringStepToggle){gaSpringStepToggle(c,renderBody);return}c.classList.toggle('open');renderBody(c)};return c}   // M3: 收展交 spring.js(FLIP 让位+打断保速); 关态(GA_SPRING_OFF)在 helper 内走完全相同的 toggle 原路径, spring.js 缺席=此处原路径
function _sbFallback(c){try{const s=c.querySelector('.ss');const v=s?(s.textContent||'').trim():'';return(v&&v!=='…')?v:''}catch(e){return''}}   // 正文空(纯工具步/正文未拉取)时的保底: .ss 恒存内核原摘要(:1036), 好过白板
function _sbDisplay(c,body){const m=String(c&&c._text||'').match(/<summary>([\s\S]*?)(?:<\/summary>|$)/i),s=m?m[1].trim():'';   // 仅显示: 从原始 text 取完整 summary(标题字段仍可截断), 不经 cleanReply/cleanStepText
  const b=String(body==null?'':body).replace(/<summary>[\s\S]*?(?:<\/summary>|$)/gi,'').trim();return s?(b?s+'\n\n'+b:s):(b||_sbFallback(c)||'…')}
function renderBody(c){if(!c.classList.contains('open'))return;const sb=c.querySelector('.sb');
  if(c._final&&c._dupFinal){if(sb._rendered)return;if(window.GA_PACE)GA_PACE.drop(sb);   // DUPFINAL: 答案源步卡正文已抽为 .finalMsg(renderFinal), 组内复读全文=Boss 2026-08-03「展开出现重复最后一段」→ 只渲摘要+占位
    sb.className='sb sbDup';sb.textContent=_sbDisplay(c,t('sbDupFinal'));sb._rendered=true;return}
  if(c._final){if(sb._rendered)return;if(window.GA_PACE)GA_PACE.drop(sb);sb.className='sb md';   // M2 硬约束: 终态整块重渲从 c._text 全文直出 → 未释放缓冲即刻弃置, 不许残留继续打字
    const ex=extractFileDiffs(c._text||'');                                // 先在【原始】文本抽 diff(含 <file_content>), 再清洗其余(cleanReply 会删 <file_content>/工具块)
    const bt=_sbDisplay(c,_twStripText(composeFinal(cleanReply(ex.text),c._text||''),c));   // 仅展开显示追加原始完整summary；既有正文清洗/ask兜底保持不变
    if(!window.GA_RENDER_LEGACY&&window.renderRich){const _tk=window.extractThinking?extractThinking(ex.text,true):null;   // F1.3: cleanReply 之前只读提取(anchored 口径与 cleanReply 剥离一致); cleanReply 本身零改动, 存档 final 不含 thinking 不变
      sb.textContent='';sb.appendChild(renderRich(bt,{mode:'chat',diffs:ex.diffs,thinking:_tk&&_tk.blocks}))}   // F1.1: 统一管线(与 legacy 同序 md→injectDiffs→decorateCode→wrapTables→linkifyFiles)
    else{sb.innerHTML=injectDiffs(md(bt),ex.diffs);decorateCode(sb);wrapTables(sb);linkifyFiles(sb)}   // legacy 直通(GA_RENDER_LEGACY=true 回退, 保留一版)
    linkifyArtifactAnchors(sb);sb._rendered=true}   // 最终报告与复制/朗读同源清洗→所见即所复制(交叉审查 issue#1); linkify=产物第二入口; 相对链接接入产物预览
  else{sb.className='sb';
    if(!window.GA_RENDER_LEGACY&&window.renderRich){
      const _tk=window.extractThinking?extractThinking(c._text||'',false):null;   // F1.3: stripTags 之前只读提取(含流式未闭合尾块); 仅显示层, 存档/发送数据零触碰
      const lv=_sbDisplay(c,stripTags(_twStripText(cleanStepText((_tk?_tk.rest:c._text)||'…'),c)));
      const _ts=_tk?(_tk.blocks.join('')+'|'+_tk.open):'';   // thinking 结构签名: 块内容或尾块开合变化→整块重渲(折叠块非追加语义)
      if(!window.GA_RENDER_FULL&&sb._lv!=null&&sb._lvTk===_ts){   // F3.2 尾块 diff-append(感知优化, 非真流式): 快照与上帧最长公共前缀=旧文全量 → 仅新增尾巴按词淡入
        if(sb._lv===lv)return;                                    // F3.1: 文本零变化=零 DOM 变更
        if(sb._lv!=='…'&&lv.indexOf(sb._lv)===0){const _pd=lv.slice(sb._lv.length);   // 非纯追加(回改/截断/剥行口径变)→ 整块重渲兜底
          if(running&&window.GA_PACE&&GA_PACE.active())GA_PACE.feed(sb,_pd);          // M2: running 活跃步增量走 pace.js 匀速释放(缓冲+rAF 词级 append); active() 关态/缺 Segmenter 时 false 且自清残余
          else _lvAppend(sb,_pd);                                                     // 原路径原样保留: GA_PACE_OFF 或降级时 DOM 与现状一致
          sb._lv=lv;return}}
      sb._lv=lv;sb._lvTk=_ts;
      if(window.GA_PACE)GA_PACE.drop(sb);   // M2: 整块重渲即将全文重画 → 弃置该步未释放缓冲防重复
      sb.textContent='';sb.appendChild(renderRich(lv,{mode:'live',thinking:_tk&&_tk.blocks,thinkOpen:!!(_tk&&_tk.open)}))}   // F1.1: live 收口进管线(无 thinking 时纯文本等价; 主聊天不默认展开全量 stdout 红线不变); 尾块跟任务态: 流式未闭合=展开, 闭合/终态=折叠
    else{if(window.GA_PACE)GA_PACE.drop(sb);sb.textContent=_sbDisplay(c,stripTags(_twStripText(cleanStepText(c._text||'…'),c)))}}}   // M2: legacy 同样仅在显示层追加原始完整summary
const _LV_FUSE=160;   // Minis 同款熔断口径: 单拍新增超 160 词整块出, 防长输出动画卡顿
function _lvAppend(sb,delta){   // F3.2: 上一拍词 span 先并回基底文本节点(700ms 轮距 > 动画时长, 淡入必已完成)→ DOM 常驻=基底文本+本拍 spans; 新增文本仍是 renderRich live 模式语义(纯文本节点, 不经 marked)
  sb.querySelectorAll('.rrW').forEach(w=>{sb.replaceChild(document.createTextNode(w.textContent),w)});
  sb.normalize();
  const parts=delta.match(/\s*\S+/g)||[];const _tw=delta.match(/\s+$/);if(_tw)parts.push(_tw[0]);
  if(!parts.length)parts.push(delta);
  if(parts.length>_LV_FUSE){sb.appendChild(document.createTextNode(delta));return}
  const fr=document.createDocumentFragment();
  parts.forEach((w,i)=>{const s=document.createElement('span');s.className='rrW';s.textContent=w;s.style.animationDelay=Math.min(i*28,380)+'ms';fr.appendChild(s)});
  sb.appendChild(fr)}
function cleanStepText(s){if(!s)return s;   // 仅用于显示: 去核心噪声, 不改存档数据
  s=s.replace(/^[ \t]*\**[ \t]*(?:LLM Running\s*\(Turn\s*\d+\)|Turn\s*\d+)\s*\.{0,3}[ \t]*\**[ \t]*$/gim,'');   // "LLM Running (Turn N) ..." 回合分隔噪声(无意义/不好看, issue#2; \s* 容忍空格变体)
  s=s.replace(/🛠️?\s*Tool:\s*`?ask_user`?[\s\S]*?`{4,}\w*\n[\s\S]*?\n`{4,}\s*(?:`{4,}[^`]*?Waiting for your answer[\s\S]*?`{4,})?[ \t]*\n?/g,'');   // ask_user 整块(args 4 反引号 + 紧随 5 反引号 Waiting 包裹), 已由选择框替代
  s=s.replace(/`{3,}[a-z]*[ \t]*\n?[ \t]*Waiting for your answer[\s\S]*?`{3,}/g,'');   // 兜底: 包裹 Waiting 的围栏(大小写敏感, 不误伤普通含 waiting 的代码块)
  s=s.replace(/^[ \t]*Waiting for your answer ?\.{0,3}[ \t]*$/gim,'');                  // 兜底: 裸 Waiting 行
  s=s.replace(/`{3,}[a-z]*[ \t]*\n[ \t]*`{3,}/g,'');                                    // 去空代码围栏→避免渲染出空 TEXT 块(issue#7)
  return s.replace(/\n{3,}/g,'\n\n').trim()}
function stripTags(t){return(t||'').replace(/<summary>[\s\S]*?<\/summary>/g,'').replace(/<thinking>[\s\S]*?<\/thinking>/g,'').trim()}
function cleanReply(s){s=cleanStepText(s||'');                                   // 复制/朗读/最终渲染统一清洗: 去 LLM Running 引导词 + 行首独立的 thinking/summary/工具块, 只留报告正文(issue#1)
  s=s.replace(/^[ \t]*<(thinking|summary|tool_use|tool_result|file_content)>[\s\S]*?<\/\1>[ \t]*$/gim,'');   // 仅剥"行首→行尾"的独立块, 不误伤正文/行内代码里的同名标签字面量(交叉审查: GA 协议词汇即这些标签)
  return s.replace(/\n{3,}/g,'\n\n').trim()}
function _jsonNlFix(s){let o='',ins=false,esc=false;for(const ch of s){if(ins){if(esc){o+=ch;esc=false}else if(ch==='\\'){o+=ch;esc=true}else if(ch==='"'){ins=false;o+=ch}else if(ch==='\n'){o+='\\n'}else o+=ch}else{if(ch==='"')ins=true;o+=ch}}return o}   // get_pretty_json 把字符串值内的 \n 还原成真换行→多行 question 是非法 JSON; 仅转义引号内换行(不动结构空白)后可重试解析
function askFallbackMd(s){   // 末步清洗后为空的兜底: ask_user 工具块被 cleanStepText 整体删除(由选择框替代), 但选择框不入存档/重进即失 → 把 ask 的问题+候选格式化为可读正文(解析镜像 android_entry._extract_ask)
  if(!s||s.indexOf('ask_user')<0)return '';
  const seg=s.slice(s.lastIndexOf('ask_user'));
  const m=seg.match(/`{4,}\w*[ \t]*\n([\s\S]*?)\n`{4,}/);
  const cand=m?m[1]:((seg.match(/(\{[\s\S]*\})/)||[])[1]||'');
  if(!cand)return '';
  let o=null;try{o=JSON.parse(cand)}catch(e){try{o=JSON.parse(_jsonNlFix(cand))}catch(e2){}}
  if(!o||typeof o!=='object')return '';
  const q=String(o.question||'').trim(),cs=(Array.isArray(o.candidates)?o.candidates:[]).map(x=>String(x).trim()).filter(Boolean);
  if(!q&&!cs.length)return '';
  return (q?q+'\n\n':'')+cs.map(c=>'- '+c).join('\n')}
function composeFinal(cleanTxt,raw){const ak=askFallbackMd(raw||'');return ak?(cleanTxt?cleanTxt+'\n\n'+ak:ak):cleanTxt}   // 末步正文=清洗残余(如checkpoint工具块)+可读的ask提问; 渲染/复制/朗读/埋点同源
/* ════════ STEPLABEL(PLAN_STEPLABEL v1.2, 参观层): E1 去「步骤 N」+ E2 合成假摘要兜底 ════════
   红线自查: 执行层/事件层零改动(不动 *.py / poll 协议 / tool_events 契约); 只读复用 twState.evs 与 _twTitle(不碰 renderTools 本体);
   显示与落库解耦: 内核原摘要恒留 .ss.textContent(:1032/:1044 落库、slimConvo、分享海报全链读到的仍是原值), 显示值只写兄弟节点 .ssd;
   .ssd 内容不入 task.msg.*、不入 KV、不进任何发往内核的 payload(事件与步骤文本只进 UI 不回灌模型); GA_STEPLABEL_OFF=1 全短路=现状形态。 */
if(window.GA_STEPLABEL_OFF===undefined)window.GA_STEPLABEL_OFF=false;   // 开关先例: GA_STEPFOLD_OFF / GA_FINALCARD_OFF / GA_CITE_OFF / GA_HUMANIZE_OFF
/*E2-PURE-START*/   /* 纯判据(无 DOM/无全局): 证据脚本 criterion_e2.js 直接从本文件切片 eval → 断言期望值与被测实现同源(#017 ①) */
function _cjkR(s){var n=0;s=String(s||'');for(var i=0;i<s.length;i++){var c=s.charCodeAt(i);
  if((c>=0x4e00&&c<=0x9fff)||(c>=0x3400&&c<=0x4dbf)||(c>=0x3000&&c<=0x303f)||(c>=0xff00&&c<=0xffef))n++}
  return n/Math.max(1,s.length)}
function isSynthSummary(s,zh){s=String(s==null?'':s).trim();   // true=内核 _ensure_text_block 合成的假摘要(thinking 首行截断), 非真摘要
  if(s.length<8)return false;                                       // 极短不判假(空串/'…' 走 _sdEmpty 另一路)
  if(_cjkR(s)>=0.25)return false;                                   // 守卫: 中文为主 → 永不判假(仅 zh 界面有效, en 界面英文真摘要 CJK≈0 故 R2 禁用)
  if(s.length>=58&&s.length<=64&&/(\.{3}|…)$/.test(s))return true;   // R1 机器截断签名(line[:60]+'...' 经 _summary 空白折叠后 58~64), 语言无关
  if(!zh)return false;                                              // R2 仅 zh 界面启用(守卫失效时会误伤英文真摘要, PLAN §2.2 监察3)
  if(!(typeof window!=='undefined'&&window.GA_STEPLABEL_R2))return false;   /* ★ L3 安全底线(默认档): R2 整条禁用 ⇒ 判据 = 仅 R1(机器截断签名), FP 面为空。
     PLAN §2.2.2(4) 收紧阶梯执行记录(证据 evidence_f0_f4/steplabel/criterion_matrix_L{0,1,2,3}.txt, 冻结集 sha256 见 neg/SHA256SUMS):
       L0 16 个单词前缀      → NEG_SET_1 B1 桶 zh FP=15/16  FAIL
       L1 12 个强思考短语前缀 → NEG_SET_2 B1 桶 zh FP=26/26  FAIL
       L2 L1 + 句末形态附加条件 → NEG_SET_2 B1 桶 zh FP=14/26  FAIL
     两档(L1/L2)仍失败 ⇒ 按计划落预声明安全底线 L3 并升级 Boss 裁定。结论(可证伪): B1 桶的定义即「带 R2 前缀的英文真摘要」,
     任何以英文前缀为特征的 R2 变体在该桶上 FP 恒 >0 —— 冻结集协议的作用正是证伪 R2, 不是为它背书。
     代价已量化且不劣化: 真机 69 条 zh 准确率 100.00%→97.10%(FN 2 条), FN = 显示内核原文 = 现状形态; 另 76.8% 的假摘要仍由 R1 全部接住。
     ★ 若 Boss 裁定接受该已知误伤面, 只需在 app.js 之前 inline 置 window.GA_STEPLABEL_R2=1 即回到 L2 档(下方表达式即 L2 式), 无需改代码。 */
  return /^(The (user|task|current)|I need|I['’]ll|I should|Let me|Now I|So the|We need|Okay|Looking at)\b/.test(s)
      && (/:$/.test(s)||s.split(/\s+/).length>=6)
      && (/(\.{3}|…|:)$/.test(s)||!/\.$/.test(s))}                  // R2(L2 档) 英文思考叙述: 强前缀 + (冒号收尾 或 ≥6 词) + (省略号/冒号收尾 或 无句末句号)
function _sdEmpty(s){s=String(s==null?'':s).trim();return !s||s==='…'||s==='...'}   // 空摘要归并: 去 .sn 后只剩「… ›」为 Boss 明令禁止 ⇒ 一并归入需替换
function _sdNorm(s){return String(s==null?'':s).replace(/\s+/g,' ').trim()}
function _sdFinalPrefix(raw,text){   /* P0-g final 前缀守卫(W1 返工): 两处同型合成点均「先切 80、不折叠」⇒ raw 来源是正文而非内核摘要, 恒判真 —
     ① :648 老档回放 (m.final?[{n:1,summary:(m.final||'').slice(0,80),text:m.final}]:[])  ② :2053 实时报错轮 setStep({n:1,summary:(j.final||'').slice(0,80),text:j.final})
     只保留前缀式 fold(raw)===fold(text.slice(0,80)); v1.1 的第二分支 fold(text).slice(0,80) 在 final 前 80 字符含任意连续空白/换行时两侧长度必不等(实测 79 vs 80) ⇒ 永不命中, 已删。 */
  var r=_sdNorm(raw);if(!r)return false;var x=String(text==null?'':text);if(!x)return false;
  return r===_sdNorm(x.slice(0,80))}
/*E2-PURE-END*/
function _sdZh(){try{return lang!=='en'}catch(e){return true}}
function _sdToolTitle(c){   /* 兜底取「首个工具」的中文动作短语标题(只取 _twTitle().t, 一律丢弃副文 .s —— 副文回放态会退化成英文 shell 首行)。
     W2/W3 返工: 步序一律由 DOM 位置自解(与 renderTools :1907 的 cards.forEach((c,ci)=>bins[ci+1]) 同一来源), 不用 dataset.gk、不用调用方传入的 s.n
     —— gen 重建后旧代卡若仍在 box 内, gk 里的 n 与 DOM 位置会错位, 用 gk 等于重新制造「同卡文案打架」。 */
  try{                                                                           // ── P1 实时 ──
    if(!replaying&&c&&c.querySelector('.tsr')){                                  // 门1 !replaying: 回放期 twState 属另一个(可能在飞的)任务, 防串台; 门2 .tsr 存在: renderTools 无事件时会 host.remove() ⇒「头部出工具短语 ⟺ 同卡有工具行」(V14)
      var box=twState&&twState.box;
      if(box&&box.isConnected&&box.contains(c)){                                 // 门3 box 身份: 预览/多会话下 twState 可能指向别的消息体
        var cards=[].slice.call(box.querySelectorAll('.step')),N=cards.length,pos=cards.indexOf(c)+1;
        if(pos>0){var evs=(twState&&twState.evs)||[];
          for(var i=0;i<evs.length;i++){var e=evs[i];if(!e)continue;
            var tn=+e.turn||1;if(tn>N)tn=N;if(tn<1)tn=1;                         // 与 :1907 逐字符同式的 clamp: turn 超前(工具先于步文本)挂末卡, 下轮补齐自动归位
            if(tn===pos){var ti=_twTitle(e);return(ti&&ti.t)?_sdJoin(ti):null}}  // 取首个(与 P2 口径一致); 命中即定, 不再往后拾取 ⇒ 一步内文案单调稳定
        }}}}catch(e1){}
  try{var tx=String((c&&c._text)||'');                                           // P2 回放: tool_events 从不落库 ⇒ 从步文本抽首个 🛠️ 工具名, 喂同一个 _twTitle
    var m=tx.match(/🛠️?\s*Tool:\s*`?([A-Za-z_][\w.]*)`?/)||tx.match(/🛠️?\s*([A-Za-z_][\w.]*)\s*\(/);
    if(m){var ti2=_twTitle({name:m[1],input_summary:tx.slice(m.index,m.index+400)});   // TOOLDENSE: 回放取参——把工具行后 400 字喂 _twParse(regex 路径容忍非 JSON 杂讯), 文件名/问题等关键参数可复原
      if(ti2&&ti2.t)return _sdJoin(ti2)}}catch(e2){}
  return null}                                                                   // null = 本拍无更好值 ⇒ 调用方 sticky 保持旧值, 从无旧值才落 P3
function _sdJoin(ti){   // TOOLDENSE: 步头「短语 · 关键参数」——原先只取 ti.t 丢副文致整行仅 4 字(利用率低, Boss 2026-08-03); 副文 cap 40 + 剥换行, .ssd nowrap ellipsis 兜底
  var d=ti.s!=null?_twLine(String(ti.s),40):'';
  return d?String(ti.t)+' · '+d:String(ti.t)}
function applyStepDisplay(c,raw){   // §2.4 三级早退(写路径不变量: 空转拍零正则零 DOM 写, 不抵消 F3.1 keyed diff 收益)
  if(window.GA_STEPLABEL_OFF||!c)return;
  var d=c.querySelector('.ssd');if(!d)return;
  var zh=_sdZh(),tsr=c.querySelector('.tsr');
  var key=(zh?'z':'e')+' '+String(raw==null?'':raw)+' '+String((c._text||'').length)+' '+(tsr?(tsr._twSig||'1'):'');   // W3: 事件维改读 .tsr 的 _twSig(renderTools 已写好的行指纹, 只读复用不碰禁区) ⇒ O(1) 取值, 取代 v1.1 每步每拍全量扫 evs 数 evN
  if(c._sdKey===key)return;                                        // ① 空转拍: 零计算零写
  c._sdKey=key;
  var v=null;
  if(!_sdEmpty(raw)&&(_sdFinalPrefix(raw,c._text)||!isSynthSummary(raw,zh)))v=raw;   // P0/P0-g: 真摘要直显
  if(v===null)v=_sdToolTitle(c);                                   // P1/P2: 中文工具动作短语
  if(v===null)v=(c._sdText!=null?c._sdText:t('stepThinking'));     // sticky(首创拍/gen 重建拍不闪) → P3「思考」
  if(c._sdText!==v){c._sdText=v;d.textContent=v}                   // ③ 先比后写(:1028 不变量: 同值赋写也会换文本节点)
  if(!c.classList.contains('sdisp'))c.classList.add('sdisp')}      // .sdisp = E1 生效标记(CSS 隐藏 .sn/.ss); OFF 态首行 return ⇒ 永不出现
function setStep(s){if(!task)return;while(task.steps.length<s.n)task.steps.push(stepCard(task.steps.length+1));
  for(let i=0;i<s.n-1;i++){const p=task.steps[i];if(p&&!p._final){p._final=true;p.classList.remove('live');p.classList.add('done');const psb=p.querySelector('.sb');if(psb)psb._rendered=false;renderBody(p)}}   // #1: 步骤被下一步接替=已完成 → 立刻按 markdown 渲染(代码块/表格), 不再等整轮结束; 仅当前(末)步保持流式纯文本
  const c=task.steps[s.n-1],_FULL=!!window.GA_RENDER_FULL;   // F3.1 键控 diff: 摘要/文本未变的节点零 DOM 变更(textContent 同值赋写也会换文本节点→必须先比后写); GA_RENDER_FULL=旧整块路径兜底
  const _ss=c.querySelector('.ss'),_sum=s.summary||'…',_chS=_ss.textContent!==_sum,_chT=c._text!==s.text;
  if(_chS||_FULL)_ss.textContent=_sum;
  if(_chT||_FULL){c._text=s.text;c.querySelector('.sb')._rendered=false;renderBody(c)}
  try{applyStepDisplay(c,_sum)}catch(e){}   // STEPLABEL M3 单行挂点(沿用 stepFoldLive 先例): 在 .ss 写入与 c._text 赋值之后、:1032 落库之前(P2 需读本拍新 _text); 抛错=不加 .sdisp ⇒ 回落「步骤 N + 原摘要」现状形态
  if(!replaying&&task.msg&&(_chS||_chT||_FULL)){task.msg.steps=task.steps.map((x,i)=>({n:i+1,summary:x.querySelector('.ss').textContent||'',text:x._text||''}));   // 流式增量落库(节流, F3.1 后仅变化拍触发): 后台/被杀的手机控制任务也能保住已产出步骤(根治"退出重进回复变空")
    task.msg.final=cleanReply(task.steps.map(x=>x._text||'').join('\n\n'));saveConvosThrottled(task.steps.length)}
  stepFoldLive()}   // STEP_FOLD §2.1: 函数末尾单行挂点(上方既有 diff/落库逻辑零改动); 自身整体 try/catch, 抛错=现状呈现
function finish(){task.done=true;if(!replaying)_flIdx=null;   // 实时轮产物集已变→重建索引; 回放期产物不变, 置空会让长会话每轮空重建(N次同步桥调用)
  task.steps.forEach(c=>{c.classList.remove('live');c.classList.add('done');c._final=true;c.querySelector('.sb')._rendered=false;renderBody(c)});
  const c=task.steps[task.steps.length-1];if(c){c.classList.add('open');renderBody(c)}
  if(!replaying){                                             // 实时完成: 冻结用时+token, 落库供回放
    stopLive();
    const _t0=(task&&task.t0)||runStats.t0;const elMs=_t0?(Date.now()-_t0):null;   // 与 liveTick 同锚: task.t0 优先(startLive 不再重置 runStats.t0)
    const ti=runStats.tokIn, to=runStats.tokOut>1?runStats.tokOut:estTok(task.steps.map(s=>s._text||'').join('\n'));
    const cr=runStats.cacheRead||0, cw=runStats.cacheWrite||0;   // #4: 冻结本轮缓存读取/创建 token 落库, 供统计/热力图聚合
    renderTaskStats({el:elMs,ti:ti,to:to,cr:cr,cw:cw});   // R7: 详情含缓存(cr/cw 本就落库, 只是此前不显示)
    if(task.msg){task.msg.steps=task.steps.map((s,i)=>({n:i+1,summary:s.querySelector('.ss').textContent||'',text:s._text||''}));
      task.msg.final=cleanReply(task.steps.map(s=>s._text||'').join('\n\n'));   // 存清洗后的报告正文(去 LLM Running 脚手架/思考块), 不再存末步摘要(消除 final 污染)
      if(task.snap)task.msg.artifacts=_newArtifacts(task.snap);   // 成品优先: file_write 产物必出 chip(内部文件已被后端谓词滤除); 无快照(重启接续轮)不写[]防永久掩盖
      try{if(!window.GA_CITE_OFF&&!task._fail){const _cs=citeList(task).slice(0,CITE_KEEP);if(_cs.length)task.msg.cites=_cs}}catch(e){}   // D2 §3.2.3: 引用落库(tool_events 从不落库 ⇒ 不写则换会话/杀进程全丢); 中断轮不写不渲(§3.2.5 H9)
      if(task._fail)task.msg.fa=1;   // STEP_FOLD §2.4.2: 中断真相持久化(convoStore 存档 UI 侧字段, 非 poll 协议/不回灌模型); 纯数据不受 GA_STEPFOLD_OFF 控制
      task.msg.el=elMs;task.msg.ti=ti;task.msg.to=to;task.msg.cr=cr;task.msg.cw=cw;_saveN=-1;saveConvos()}
    try{   // 渲染层埋点: task_done 只证 Agent 循环结束(不证答案真写进 DOM); 此处量"屏幕实际可见字符 + 清洗后报告正文长度"→补 hanrui 报告盲区/BBS#46 待办2。task_done 数 − render_done 数 = 静默空白案例
      let _sb=null;for(let _i=task.steps.length-1;_i>=0;_i--){const _b=task.steps[_i].querySelector('.sb');if(_b&&(_b.textContent||'').trim()){_sb=_b;break}}   // 末步真实渲染体(取最后一个有可见文本的 .sb)
      const _domLen=_sb?(_sb.textContent||'').trim().length:0;                                  // 屏幕可见字符数(0=空白屏)
      const _final=composeFinal(cleanReply(task.steps.map(s=>s._text||'').join('\n\n')),(task.steps[task.steps.length-1]||{})._text||'');   // 与落库 final 同源: 清洗后报告正文; ask 兜底与 renderBody 同源→兜底命中不再误报 text_empty
      const _rp={steps:task.steps.length,bytes:_final.length,dom:_domLen,model:(task.msg&&task.msg.model)||modelLabel()||'',ms:elMs||0};   // 全为计数/型号, 不含任何回答内容(脱敏铁律)
      if(_domLen>0&&_final.length>0){GAT.emit('render_done',_rp)}
      else{_rp.reason=_final.length>0?'dom_empty':'text_empty';GAT.emit('render_error',_rp)}   // dom_empty=有正文却没渲染上屏(真"完成但空白"); text_empty=连正文都为空(常是无步骤报错)
    }catch(e){}}
  renderArtifacts(replaying?(task._arts||[]):((task.msg&&task.msg.artifacts)||[]),task.box);   // 本轮产物 chips(回放取存档, 实时取快照差分)
  try{task.steps.forEach(c=>{delete c._autoOpen;delete c._userOpen;delete c._userClosed})}catch(e){}   // STEP_FOLD §2.2.8: 运行态标记清理独立于 foldSteps 的 try(监察#3), 抛错不残留
  if(!window.GA_STEPFOLD_OFF&&task.steps.length>1){try{foldSteps(task);if(!window.GA_FINALCARD_OFF&&!task._fail)renderFinal(task)}catch(e){try{unfoldRestore(task)}catch(_e){}}}   // STEP_FOLD §2.2
  else if(!window.GA_STEPFOLD_OFF&&!window.GA_FINALCARD_OFF&&!task._fail&&task.steps.length===1){try{flatSingle(task)}catch(e){}}   // D1 §2.3 单步轮: 不折叠、不产独立 .finalMsg, 该步卡即消息体
  try{renderCites(task,replaying?(task._citeArc||[]):citeList(task))}catch(e){}   // 活体渲全量(超 CITE_SHOW 走「+N」展开), 落库仅前 CITE_KEEP 条   // D2: 宿主由 pickCiteHost 屏蔽 .finalMsg / sbox 末尾 / 中断轮无宿主三态差异: 终态唯一挂点(活体完成/回放/中断三路一次覆盖); 位于 addActions/scroll 之前(监察#5, 高度骤减后既有 scroll 即钉底); 抛错原子回退=现状呈现
  addActions();scroll()}
/* ════════ STEP_FOLD(PLAN_STEP_FOLD v1.1, 参观层): 运行中「末步自动 open/前步自动收」+ 终态「执行过程」折叠 ════════
   红线自查: 只动 classList 与新增 expando(_autoOpen/_userOpen/_userClosed/_fold), 不写 keyed diff 缓存(_text/_final/gk/_rendered/_lv/_twSig);
   容器终态专属(仅 finish 内创建, gen 重建路径 L1856 永远见不到, R2); 事件/步骤文本只进 UI 不回灌模型; GA_STEPFOLD_OFF=1 全短路(§2.9) */
function stepFoldLive(){try{   // §2.1: setStep 末尾调用; 稳态(末步已 open/前步已收)零 DOM 操作(GS1#8 MutationObserver 持平)
  if(replaying||window.GA_STEPFOLD_OFF||!task||task.done)return;
  const n=task.steps.length;if(!n)return;
  const c=task.steps[n-1];
  if(c&&!c.classList.contains('open')&&!c._userClosed){c.classList.add('open');c._autoOpen=1;renderBody(c)}   // 末步自动展开(classList 直加不走 spring, 防每拍 FLIP 风暴); 用户明确点收过(_userClosed)不再重开(R6)
  for(let i=0;i<n-1;i++){const p=task.steps[i];
    if(p&&p._autoOpen&&!p._userOpen&&p.classList.contains('open')){p.classList.remove('open');p._autoOpen=0}}   // 被接替自动收起=现状默认关态(单行头+.tsr 常显, .sb 隐藏); 用户手动展开(_userOpen)不收(R5); GA_PACE 缓冲已在接替终态化时由 renderBody L961 drop
}catch(e){}}
function foldSteps(tk){   // §2.2: 终态折叠(原子构建: detached 组装→一次插入); 调用点已判 OFF 与 steps.length>1(单步/老档守卫 R12)
  const host=tk.sbox||tk.box;if(!host||host.querySelector('.stepsFold'))return;   // 幂等: resumeRun 重挂等场景防重复
  const last=tk.steps[tk.steps.length-1];
  const fold=document.createElement('div');tk._fold=fold;fold.className='stepsFold'+(tk._fail?' sfAbort open':'');   // 中断: .sfAbort 且默认展开, 不误折不冒充完成态(场景C)
  const hd=document.createElement('div');hd.className='sfh';
  const ar=document.createElement('span');ar.className='sfar';ar.textContent='▸';   // 箭头开合走 CSS 旋转(.stepsFold.open .sfar)
  const tx=document.createElement('span');tx.className='sft';
  const _full=!tk._fail&&!window.GA_FINALCARD_OFF&&!!_finalSrc(tk);   // D1(UX_R2 §2.2): 完成轮全部步入容器(含原末步), 答案另起 .finalMsg 普通消息体; 中断轮/FINALCARD_OFF 保持 step-fold 原形态(n-1 步 + 末步留外)
  // 全空正文轮(监察#7): 无 composeFinal 非空候选 ⇒ renderFinal 恒返回 null, 若仍全收则屏上只剩「▸ 执行过程(N 步)」一行(可见性回退) ⇒ 与 renderFinal 同一挑选口径(_finalSrc 唯一决策点)判空后退回 _full=false, 末步留容器外
  tx.textContent=t(tk._fail?'stepFoldAbort':'stepFoldHead').replace('{n}',_full?tk.steps.length:tk.steps.length-1);   // i18n zh/en; textContent 注入无 XSS 面
  hd.appendChild(ar);hd.appendChild(tx);fold.appendChild(hd);
  const bd=document.createElement('div');bd.className='sfb';fold.appendChild(bd);
  for(let i=0;i<tk.steps.length-1;i++)bd.appendChild(tk.steps[i]);   // appendChild 移动非重建(R1): expando/task.steps[] 引用/.tsr/_twSig 全保, 文档序不变 → renderTools box.querySelectorAll('.step') bins 映射不变
  hd.onclick=()=>{try{const op=!fold.classList.contains('open');fold.classList.toggle('open');
    if(op&&window.gaSpring&&!gaSpring.off()){bd.classList.remove('sprPop');void bd.offsetWidth;bd.classList.add('sprPop')}   // C3: 展开入场弹簧, 只走用户点击(pclink applyFold 程序化还原不加); window.gaSpring 判在=spring.js 可缺席(真实场景守卫)
    else bd.classList.remove('sprPop')}catch(e){}};   // 收起/off 态摘类(对齐 gaSpringStepToggle 关态先例), 中途切 reduced-motion 不残留重放   // 展开后各步全文靠用户逐卡点 .sh(L959 既有路径按需渲染, 监察#4: 不做对关卡无效的批量 renderBody)
  host.insertBefore(fold,last);   // 一次性入 DOM(占住末步原位); 末步是否留容器外由 _full 决定
  if(_full&&last)bd.appendChild(last);   // D1: 末步随后一并移入(同为 appendChild 移动非重建, 引用/expando 全保)
  else if(!tk._fail&&last&&window.GA_FINALCARD_OFF){const sn=last.querySelector('.sn');if(sn){sn.textContent=t('finalAnswer');last.classList.add('sfinal')}}   /* STEPLABEL M4: 逻辑零改动, 仅补 .sfinal 类 ⇒ CSS 例外保留「最终回答」可见(E1 只去「步骤 N」)。末步答案化**只在** GA_FINALCARD_OFF 回退形态发生(=刚落地的 step-fold 原形态)。
     返工修正(监察#4): 原写法只判 !tk._fail, 导致「多步但全空正文轮」(_finalSrc 无候选 ⇒ _full=false)也把末步 .sn 改成「最终回答」——该轮压根没有答案, 冒充答案比保留「步骤 N」更差, 且使 D1「删除末步答案化」在该分支不成立(demo gen 205 实证)。
     中断轮 / 全空正文轮 一律保持「步骤 N」。该「全空正文轮」分支为计划 §2.3 场景表未列的新增分支, 已在 GU1 交付说明中申报, 断言见 demo G9/G9b/G9c。 */
  if(!replaying&&stick&&!pinned)requestAnimationFrame(()=>scroll(1))}   // R8: 仅贴底跟随态才补钉; 顶置阅读态(pinned)折叠不抢滚(stick 可能被 pin 落点近底翻回 true, 不可单独作准)
function unfoldRestore(tk){   // §2.8: foldSteps 抛错回退 — 步卡按原序移回后拆容器; 移动非重建 ⇒ expando/引用全程保留, 降级态严格=现状呈现
  const host=tk&&(tk.sbox||tk.box);if(!host)return;
  const f=(tk._fold&&(tk._fold.parentNode===host||!tk._fold.parentNode))?tk._fold:host.querySelector('.stepsFold');if(!f)return;   // 兼顾未及 insertBefore 即抛错的 detached 容器
  const last=tk.steps[tk.steps.length-1];
  const ref=(f.parentNode===host)?f:((last&&last.parentNode===host)?last:null);
  [].slice.call(f.querySelectorAll('.step')).forEach(s=>{if(ref)host.insertBefore(s,ref);else host.appendChild(s)});
  if(f.parentNode)f.remove();tk._fold=null}
/* ════════ D1 答案去卡片化(PLAN_UX_ROUND2 §2, 参观层): 终态答案=无卡边框普通消息体 .finalMsg(走 renderRich), 全部步骤进折叠组 ════════
   零冲击: composeFinal/cleanReply/_twStripText 只读复用; 不改 renderBody 本体(平行函数, 同一段调用序列);
   .finalMsg 绝不带 .step 类(否则污染 renderTools 的 box.querySelectorAll('.step') bins 映射); GA_FINALCARD_OFF=1 全短路 */
function _finalSrc(tk){   // §2.2.3 正文候选唯一决策点(与 addActions.finalText() 同一挑选口径): 「最后一个 composeFinal 非空的步卡」; foldSteps 的 _full 与 renderFinal 共用 ⇒ 二者永不失配(监察#7 全空正文轮)
  try{const s=(tk&&tk.steps)||[];
    for(let i=s.length-1;i>=0;i--){if(composeFinal(cleanReply(s[i]._text||''),s[i]._text||''))return s[i]}
  }catch(e){}
  return null}
function renderFinal(tk){   // §2.2.3: 正文实参=「最后一个 composeFinal 非空的步卡」(与 addActions.finalText() 同一挑选口径, 规避末步纯工具步白屏)
  const host=tk&&(tk.sbox||tk.box);if(!host||host.querySelector('.finalMsg'))return null;   // 幂等: resumeRun 重挂等场景防重复
  const c=_finalSrc(tk);
  if(!c)return null;
  const fm=document.createElement('div');fm.className='finalMsg sb md';   // 复用 .sb.md 全套排版(app.css:205-230)=GA 唯一「无卡消息体」形态; .sb{display:none} 由 .sb.finalMsg 显式覆盖
  fm.setAttribute('aria-label',t('finalAnswer'));
  const ex=extractFileDiffs(c._text||'');                                  // 与 renderBody L963-967 同序列(含 _twStripText, 同函数同实参)
  const bt=_twStripText(composeFinal(cleanReply(ex.text),c._text||''),c);
  if(!window.GA_RENDER_LEGACY&&window.renderRich){const _tk=window.extractThinking?extractThinking(ex.text,true):null;
    fm.appendChild(renderRich(bt,{mode:'chat',diffs:ex.diffs,thinking:_tk&&_tk.blocks}))}
  else{fm.innerHTML=injectDiffs(md(bt),ex.diffs);decorateCode(fm);wrapTables(fm);linkifyFiles(fm)}
  if(!replaying)fm.classList.add('sprPop');                                // 入场动效(§2.2.6 新增 .sb.finalMsg.sprPop 规则; 回放不放动效)
  host.appendChild(fm);host.classList.add('msgFlat');                      // 终态扁平化: 摘背景/边框/阴影, 保留 14px padding 换横向零跳变
  try{c._dupFinal=1;c.classList.remove('open');                            // DUPFINAL: 正文已抽到 .finalMsg → 源步卡收起并标记, 组内不再复读全文(重开走 renderBody 占位分支)
    const _sb=c.querySelector('.sb');if(_sb){_sb._rendered=false;_sb._lv=null;_sb.textContent='';_sb.className='sb'}}catch(_e){}
  return fm}
function flatSingle(tk){   // §2.3 单步轮(steps.length===1, 无折叠亦无独立 .finalMsg): 该步卡直接充当消息体 — 隐藏 .sh 步头 + 卡壳扁平化
  const host=tk&&(tk.sbox||tk.box);if(!host)return;
  const c=tk.steps&&tk.steps[0];if(!c)return;
  c.classList.add('step--final');host.classList.add('msgFlat')}
/* ════════ D2 引用胶囊(PLAN_UX_ROUND2 §3, 纯前端参观层): 浏览器跳事件的 url 收成消息尾部可点胶囊 ════════
   数据单向(内核→UI), 事件只进 UI 不回灌模型; 不写任何 keyed diff 缓存键, 不改 setStep/renderTools/render.js */
const CITE_SHOW=5, CITE_KEEP=5;   // 常显 5 颗(超出「+N」展开); 落库同为 5 条(§3.2.3 ≈<500B/消息)
function _citeHost(u){try{return String(u).replace(/^https?:\/\/+/i,'').split(/[\/?#]/)[0].replace(/^www\./i,'').slice(0,60)}catch(e){return ''}}
function _citeColor(h){let n=0;for(let i=0;i<h.length;i++)n=(n*31+h.charCodeAt(i))>>>0;return 'hsl('+(n%360)+' 52% 46%)'}   // host 稳定色: 纯本地计算, 零网络请求/离线一致
function citeCollect(j){   // §3.2.1 增量累积(环形 50 会挤丢早期 open_url ⇒ 不能等 finish 才捞) + 双重 gen 归属判据(防串代 R6c)
  if(window.GA_CITE_OFF)return;   // 开关唯一(监察#9): 原 GA_CITE_ALLOFF 系计划外命名漂移(全仓无定义/§5 开关表无此项, 且 renderCites 不认 ⇒ 老档仍渲, 语义不对称), 已删除并入 GA_CITE_OFF
  if(!j||!Array.isArray(j.tool_events)||!j.tool_events.length)return;
  if(!task||task.done||replaying)return;
  if(task._gen==null||String(j.gen)!==String(task._gen))return;   // 判据1 整批丢弃: 载荷代际与当前活体任务不一致(空闲 poll 终态/上一任务残留)
  if(!task._cites)task._cites=new Map();
  if(!task._citeSeen)task._citeSeen=new Set();
  j.tool_events.forEach(e=>{
    if(!e||String(e.gen)!==String(j.gen))return;                  // 判据2 逐条过滤
    const dk=String(e.gen)+':'+String(e.seq);if(task._citeSeen.has(dk))return;task._citeSeen.add(dk);   // 去重键=gen+seq 复合键(沿用参观层既有口径)
    const u=String(e.url||'').trim();
    if(!/^https?:\/\//i.test(u))return;                           // 只收 http(s): about:blank/data:/file:/chrome:// 与 droid.* 的空 url 全滤
    const k=u.split('#')[0];if(task._cites.has(k))return;         // 去重按去 fragment 的规范串; 同 host 不同 path 不合并
    const h=_citeHost(u);if(!h)return;
    const o={u:u.slice(0,300),h:h};const ti=String(e.title||'').trim();if(ti)o.t=ti.slice(0,60);   // title 现实上基本为空 → 主显 host, title 仅命中时增强
    task._cites.set(k,o)})}
function citeList(tk){try{if(!tk||!tk._cites)return [];const a=[];tk._cites.forEach(v=>a.push(v));return a}catch(e){return []}}   // Map 保插入序; forEach 而非 slice(Map 迭代器非 array-like)
function pickCiteHost(tk){   // §3.2.5 宿主唯一决策点: 常规完成→.finalMsg 末子节点; 单步/FINALCARD_OFF/STEPFOLD_OFF→sbox 末尾; 中断轮→无宿主(不写不渲)
  const host=tk&&(tk.sbox||tk.box);if(!host||tk._fail)return null;
  return host.querySelector('.finalMsg')||host}
function renderCites(tk,list){
  if(window.GA_CITE_OFF||!tk||!list||!list.length)return;
  if(tk._citeEl&&tk._citeEl.isConnected)return;                   // 幂等
  const host=pickCiteHost(tk);if(!host)return;
  const wrap=document.createElement('div');wrap.className='msgCites';
  wrap.setAttribute('role','list');wrap.setAttribute('aria-label',t('citeSources'));
  list.forEach((c,i)=>{
    const u=String(c&&c.u||'');if(!/^https?:\/\//i.test(u))return;
    const h=String(c.h||_citeHost(u)),lab=String(c.t||h);
    const sp=document.createElement('span');sp.className='citeChip'+(i>=CITE_SHOW?' citeHid':'');
    sp.setAttribute('role','link');sp.setAttribute('tabindex','0');sp.title=u;   // .title 走属性赋值(非 innerHTML), 无注入面
    const dot=document.createElement('span');dot.className='citeDot';dot.style.background=_citeColor(h);dot.textContent=(h[0]||'?').toUpperCase();   // 默认零网络请求: 本地首字母色块(离线一致, 不外泄域名)
    sp.appendChild(dot);
    if(window.GA_CITE_FAVICON){const im=document.createElement('img');im.className='citeFav';im.alt='';   // 增强开关(默认关): 开启才向 Google s2 发请求, 失败静默回落色块
      im.onerror=function(){try{im.remove()}catch(e){}};im.onload=function(){try{dot.style.display='none'}catch(e){}};
      im.src='https://www.google.com/s2/favicons?sz=32&domain='+encodeURIComponent(h);sp.insertBefore(im,dot)}
    const tx=document.createElement('span');tx.className='citeTx';tx.textContent=_twLine(lab,28);sp.appendChild(tx);   // textContent 注入: XSS 面为零(等价 _twEsc 口径)
    sp.onclick=()=>citeOpen(u);
    sp.onkeydown=(ev)=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();citeOpen(u)}};
    wrap.appendChild(sp)});
  if(!wrap.childElementCount)return;
  const hid=wrap.querySelectorAll('.citeChip.citeHid').length;
  if(hid){const more=document.createElement('span');more.className='citeChip citeMore';more.setAttribute('role','button');more.setAttribute('tabindex','0');
    more.textContent='+'+hid;
    const openAll=()=>{try{wrap.querySelectorAll('.citeHid').forEach(x=>x.classList.remove('citeHid'));more.remove()}catch(e){}};
    more.onclick=openAll;more.onkeydown=(ev)=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();openAll()}};
    wrap.appendChild(more)}
  host.appendChild(wrap);tk._citeEl=wrap}
function citeOpen(u){   // 既有外链口径: 不用 <a href>(旧壳无 WebViewClient 会劫持 file:// 主页), 走 GA.openUrl + http(s) 白名单二次校验(壳侧 MainActivity.kt:224 为第三道)
  try{if(!/^https?:\/\//i.test(String(u)))return;if(typeof GA!=='undefined'&&GA.openUrl)GA.openUrl(String(u))}catch(e){}}
let _speakBtn=null;   // 当前正在朗读的按钮: 实现"再次点=停止"切换, 不再从头重播
function _speakReset(){if(_speakBtn){_speakBtn.classList.remove('on');_speakBtn.innerHTML=ICO_SPEAK;_speakBtn.setAttribute('aria-label',t('speak'));_speakBtn=null}}
window.gaOnSpeakEnd=function(){_speakReset()};   // 原生 TTS 自然播完/出错/被停时回调, 复位朗读键
function speakStop(){try{if(typeof GA!=='undefined'&&GA.speakStop)GA.speakStop()}catch(e){}try{if(window.speechSynthesis)speechSynthesis.cancel()}catch(e){}_speakReset()}
function speakText(txt){txt=(txt||'').replace(/<[^>]+>/g,'').replace(/[#*`>_~]/g,'').trim();if(!txt)return false;
  try{if(typeof GA!=='undefined'&&GA.speak){const r=GA.speak(txt.slice(0,4000),lang);if(r==='ok'){toast(t('t_speakStart'));return true}}}catch(e){}   // 优先原生 TextToSpeech(WebView 的 speechSynthesis 多无引擎)
  try{if(window.speechSynthesis){const u=new SpeechSynthesisUtterance(txt.slice(0,2000));u.onend=u.onerror=()=>{try{gaOnSpeakEnd()}catch(e){}};speechSynthesis.cancel();speechSynthesis.speak(u);toast(t('t_speakStart'));return true}}catch(e){}
  toast(t('t_speakNo'));return false}
function addActions(){if(_noActs)return;/* PCLINK v2.2: 远程会话不挂 重跑/朗读/翻译/分享(#031-F4 跨通道) */if(!task||task._acted)return;task._acted=true;const self=task,row=el('div','msgAct',task.box);
  const finalText=()=>{const s=self.steps||[];for(let i=s.length-1;i>=0;i--){const tx=composeFinal(cleanReply(s[i]._text||''),s[i]._text||'');if(tx)return tx}return ''};   // 复制/朗读=本轮(self)最终报告(末步正文): 绑 self 不闭包全局 task→修回放后点任意轮都复制到末轮的 offset; ask 兜底与渲染同源(所见即所复制); 只取报告正文(非全部工具步)→体量小, 规避系统剪贴板长度上限
  const mk=(icon,label,fn)=>{const b=el('button',null,row);b.innerHTML=icon;b.setAttribute('aria-label',label);b.onclick=fn;return b};
  const cp=mk(ICO_COPY,t('copyReply'),()=>copyText(finalText(),()=>{cp.classList.add('ok');cp.innerHTML=ICO_OK;setTimeout(()=>{cp.classList.remove('ok');cp.innerHTML=ICO_COPY},1300)}));
  if(self.prompt)mk(ICO_REGEN,t('regenRun'),()=>retryTask(self));
  const spk=mk(ICO_SPEAK,t('speak'),function(){
    if(_speakBtn===spk){speakStop();return}                                       // 再次点同一朗读键=停止(不再从头重播)
    speakStop();                                                                  // 先停掉别处正在朗读的
    if(speakText(finalText())){_speakBtn=spk;spk.classList.add('on');spk.innerHTML=ICON_STOP;spk.setAttribute('aria-label',t('stopSpeak'))}});
  mk(ICO_TRANS,t('translate'),()=>toast(t('t_transDev')));
  const shb=mk(ICO_SHARE,t('share'),()=>{_shareHintSeen(true);openShareCard(self)});   // 分享: 非阻断, 完成后才出现; 仅用户主动点击才生成分享图(案例信息+下载二维码)
  shb.classList.add('shareBtnHi');   // A: 分享键常驻品牌绿高亮(可发现性)
  const sp=el('span','tm',row);sp.style.marginLeft='auto';sp.textContent=self.steps.length?(self.steps.length+' '+t('steps')):'';
  // B: 首次「成功」任务完成时冒一次气泡「✨生成分享图」引导, localStorage 记住不再弹。
  // ok 门槛(v2.24): 仅实时完成 + 非失败/中止(_fail) + 有步骤且有报告正文才弹——失败/报错任务不值得引导分享
  if(!_shareHintSeen()&&!replaying&&!self._fail&&self.steps.length>0&&finalText()){_showShareHint(shb,'task_done')}}
// ── 分享按钮首次引导气泡(一次性) ──
function _shareHintSeen(set){try{if(set){localStorage.setItem('ga_share_hint','1');return true}return localStorage.getItem('ga_share_hint')==='1'}catch(e){return set?true:false}}
function _showShareHint(btn,scene){
  if(!btn||$('shareHintTip'))return;
  const tip=document.createElement('div');tip.id='shareHintTip';tip.className='shareHintTip';
  tip.innerHTML='<span>'+t('shareHintTip')+'</span><i class="shArrow"></i>';
  document.body.appendChild(tip);
  const place=()=>{const r=btn.getBoundingClientRect();if(!r.width){return}
    tip.style.left=Math.max(8,Math.min(window.innerWidth-tip.offsetWidth-8, r.left+r.width/2-tip.offsetWidth/2))+'px';
    const up=r.top-tip.offsetHeight-10, flip=up<8;                                 // 上方放不下就翻到按钮下方(横向早有夹取, 纵向漏了→按钮靠顶时气泡飞出视口只剩半截)
    tip.style.top=(flip?r.bottom+10:up)+'px';tip.classList.toggle('below',flip);
    tip.querySelector('.shArrow').style.left=(r.left+r.width/2 - parseFloat(tip.style.left))+'px';};
  requestAnimationFrame(()=>{place();tip.classList.add('on')});
  try{GAT.emit('share_hint_shown',{scene:scene||'task_done'})}catch(e){}   // 曝光埋点: 引导→share_click 转化率分子来源(scene=触发场景)
  const kill=()=>{tip.classList.remove('on');setTimeout(()=>{try{tip.remove()}catch(e){}},260);_shareHintSeen(true)};
  tip.onclick=kill;setTimeout(kill,5000);   // 5s 后自动消失或点击消失(都记为已看)
}

/* ════════════ 分享卡片: 案例信息 + GA 下载二维码 (纯前端 Canvas 合成, 无第三方依赖) ════════════ */
const SHARE_URL='https://github.com/shenhao-stu/GAgent';   // 二维码指向官方下载子域(README: web/download 已迁 example.invalid)
/* 极简 QR 编码器(byte 模式, EC level M, 自动选版本 1~10, mask 0)。仅够编码一个短 URL, 不引第三方库。
   参考 QR Code ISO/IEC 18004: GF(256) RS 纠错 + 定位/校正图形 + 格式信息。 */
const QR=(function(){
  const EXP=new Array(256),LOG=new Array(256);
  for(let i=0,x=1;i<255;i++){EXP[i]=x;LOG[x]=i;x<<=1;if(x&0x100)x^=0x11d}EXP[255]=EXP[0];
  const gmul=(a,b)=>(a===0||b===0)?0:EXP[(LOG[a]+LOG[b])%255];
  // 生成多项式 g(x)=∏(x-α^i), 系数高次在前(首项=1)。多项式乘法逐次卷积。
  function rsGen(n){let g=[1];for(let i=0;i<n;i++){const ng=new Array(g.length+1).fill(0);
    for(let j=0;j<g.length;j++){ng[j]^=g[j];ng[j+1]^=gmul(g[j],EXP[i])}g=ng}return g}
  // RS 纠错码字: 对 data·x^n 除以 g(x) 取余。res 存当前余式(n 个系数, 高次在前)。
  function rsEnc(data,n){const g=rsGen(n),res=new Array(n).fill(0);
    for(let i=0;i<data.length;i++){const f=data[i]^res[0];res.shift();res.push(0);
      if(f!==0)for(let j=0;j<n;j++)res[j]^=gmul(g[j+1],f)}return res}
  // level M 容量表(byte 模式数据码字数, EC码字数/块, 块数) 版本1~10
  const CAP=[ // [ver, dataCodewords, ecPerBlock, [ [numBlocks, dataPerBlock], ... ] ]
    [1,16,10,[[1,16]]],[2,28,16,[[1,28]]],[3,44,26,[[1,44]]],[4,64,18,[[2,32]]],
    [5,86,24,[[2,43]]],[6,108,16,[[4,27]]],[7,124,18,[[4,31]]],[8,154,22,[[2,38],[2,39]]],
    [9,182,22,[[3,36],[2,37]]],[10,216,26,[[4,43],[1,44]]]];
  const ALIGN=[[],[],[6,18],[6,22],[6,26],[6,30],[6,34],[6,22,38],[6,24,42],[6,26,46],[6,28,50]];
  const FMT_M=[0x5412,0x5125,0x5e7c,0x5b4b,0x45f9,0x40ce,0x4f97,0x4aa0,0x77c4,0x72f3,0x7daa,0x789d,0x662f,0x6318,0x6c41,0x6976]; // level M, mask 0..15
  function bytes(str){const u=unescape(encodeURIComponent(str)),a=[];for(let i=0;i<u.length;i++)a.push(u.charCodeAt(i));return a}
  function build(text){
    const src=bytes(text);let V=0;for(const c of CAP){const cci=8,hdr=4+cci,total=hdr+src.length*8;if(total<=c[1]*8){V=c;break}}
    if(!V)throw new Error('qr-too-long');
    const [ver,dataCw,ec,blocks]=V;
    // 比特流: mode(0100)+count(8bit)+data+terminator+pad
    let bits=[];const push=(val,len)=>{for(let i=len-1;i>=0;i--)bits.push((val>>i)&1)};
    push(4,4);push(src.length,8);src.forEach(b=>push(b,8));
    const cap=dataCw*8;let term=Math.min(4,cap-bits.length);push(0,term);
    while(bits.length%8!==0)bits.push(0);
    const dcw=[];for(let i=0;i<bits.length;i+=8){let b=0;for(let j=0;j<8;j++)b=(b<<1)|bits[i+j];dcw.push(b)}
    const PAD=[0xec,0x11];let pi=0;while(dcw.length<dataCw)dcw.push(PAD[pi++%2]);
    // 分块 + RS
    const dBlocks=[],eBlocks=[];let off=0;
    blocks.forEach(([nb,dpb])=>{for(let k=0;k<nb;k++){const d=dcw.slice(off,off+dpb);off+=dpb;dBlocks.push(d);eBlocks.push(rsEnc(d,ec))}});
    // 交错
    const maxD=Math.max(...dBlocks.map(b=>b.length)),out=[];
    for(let i=0;i<maxD;i++)dBlocks.forEach(b=>{if(i<b.length)out.push(b[i])});
    for(let i=0;i<ec;i++)eBlocks.forEach(b=>out.push(b[i]));
    const finalBits=[];out.forEach(b=>{for(let i=7;i>=0;i--)finalBits.push((b>>i)&1)});
    return draw(ver,finalBits);
  }
  function draw(ver,data){
    const N=ver*4+17,m=[];for(let i=0;i<N;i++)m.push(new Array(N).fill(null));
    const F=(r,c,v)=>{if(r>=0&&r<N&&c>=0&&c<N)m[r][c]=v};
    const finder=(r,c)=>{for(let i=-1;i<=7;i++)for(let j=-1;j<=7;j++){const rr=r+i,cc=c+j;if(rr<0||rr>=N||cc<0||cc>=N)continue;
      const on=(i>=0&&i<=6&&(j===0||j===6))||(j>=0&&j<=6&&(i===0||i===6))||(i>=2&&i<=4&&j>=2&&j<=4);m[rr][cc]=on?1:0}};
    finder(0,0);finder(0,N-7);finder(N-7,0);
    for(let i=0;i<N;i++){if(m[6][i]===null)m[6][i]=(i%2===0)?1:0;if(m[i][6]===null)m[i][6]=(i%2===0)?1:0}   // timing
    const al=ALIGN[ver];al.forEach(r=>al.forEach(c=>{if(m[r][c]!==null)return;for(let i=-2;i<=2;i++)for(let j=-2;j<=2;j++){const on=Math.max(Math.abs(i),Math.abs(j))!==1;F(r+i,c+j,on?1:0)}}));
    F(N-8,8,1); // dark module
    // 预留格式信息位(占位, 稍后写)
    const resFmt=(r,c)=>{if(m[r][c]===null)m[r][c]=-1};
    for(let i=0;i<=8;i++){resFmt(8,i);resFmt(i,8)}for(let i=0;i<8;i++){resFmt(8,N-1-i);resFmt(N-1-i,8)}
    // 放数据(zigzag, mask 0)
    let di=0,up=true;
    for(let col=N-1;col>0;col-=2){if(col===6)col--;
      for(let t=0;t<N;t++){const row=up?N-1-t:t;
        for(let c2=0;c2<2;c2++){const cc=col-c2;if(m[row][cc]!==null)continue;
          let bit=di<data.length?data[di++]:0;if((row+cc)%2===0)bit^=1;   // mask 0: (r+c)%2==0
          m[row][cc]=bit}}up=!up}
    // 写格式信息(mask 0)
    const fmt=FMT_M[0];const fb=[];for(let i=14;i>=0;i--)fb.push((fmt>>i)&1);
    const seq1=[[8,0],[8,1],[8,2],[8,3],[8,4],[8,5],[8,7],[8,8],[7,8],[5,8],[4,8],[3,8],[2,8],[1,8],[0,8]];
    seq1.forEach(([r,c],i)=>m[r][c]=fb[i]);
    const seq2=[[N-1,8],[N-2,8],[N-3,8],[N-4,8],[N-5,8],[N-6,8],[N-7,8],[8,N-8],[8,N-7],[8,N-6],[8,N-5],[8,N-4],[8,N-3],[8,N-2],[8,N-1]];
    seq2.forEach(([r,c],i)=>m[r][c]=fb[i]);
    for(let r=0;r<N;r++)for(let c=0;c<N;c++)if(m[r][c]===-1||m[r][c]===null)m[r][c]=0;
    return m;
  }
  return {matrix:build};
})();

let _shareBusy=false;
let _shareRefineCancel=null;   // 当前预览会话的"取消在飞精修/长图"钩子(showSharePreview 内赋值, gaOnBack 分层用)
let _shareCtx=null;            // 当前预览会话的再生上下文(折叠形态切换重渲用); 单写者 showSharePreview, closeSharePreview 清空
// ── 分享图(简版/精修/长图) ──────────────────────────────────────────────────
// 变量(每次生成时读取): 视口 vw×vh(折叠形态/横竖屏决定) · 截图纵横比 shotAr(从截图像素反推, 是设备形态的唯一真相源) · 主题底色。
// 不变量(适配任何厂商/尺寸/折叠形态的根基):
//   I1 截图 = 整个 app 视口(0,0,vw,vh)——顶栏+对话+输入栏, 即"这块屏幕的完整所见";
//   I2 mock 屏纵横比 ≡ 截图纵横比(+合成状态栏), 截图恒 cover 盖满 → 结构上不存在填充带/黑下巴;
//   I3 海报画布纵横比 ≡ 预览视口纵横比 → 预览恒满屏无黑边(双折叠展开的方屏出方海报, 直板出 9:19.5);
//   I4 管线只经 GA.captureChat / GA.renderHtmlToImage(输出宽≤1440 / 画布≤4096×8192), 版式设计语言(v11)不变。
// 简版(默认·即时)=本地模板标题; 精修(✨·LLM 蒸馏标题)复用同一截图; 长图=克隆 #chat 全量对话离屏整版渲染。
function _viewAr(){return Math.max(.55,Math.min(2.6,innerHeight/Math.max(1,innerWidth)))}
function _foldSig(){return innerWidth+'x'+innerHeight}   // 折叠形态签名: 展开/合拢必然改变视口尺寸
function _shotEnv(){return {vw:innerWidth,viewAr:_viewAr(),sig:_foldSig()}}
function openShareCard(taskObj){
  if(_shareBusy)return;_shareBusy=true;
  const m=taskObj&&taskObj.msg;
  const steps=(taskObj&&taskObj.steps)||(m&&m.steps)||[];
  const nSteps=steps.length||0;
  try{GAT.emit('share_click',{steps:nSteps})}catch(e){}   // 埋点只带步数(整数), 不带任务内容
  const prompt=(taskObj&&taskObj.prompt)||(m&&m.prompt)||'';
  const final=(m&&m.final)||'';
  const base={steps:nSteps, ms:(m&&m.el)||null};
  // 蒸馏 payload(精修版才用): 关键点+成果, 内置脱敏
  const payload=JSON.stringify({prompt:String(prompt).slice(0,600),
    steps:(steps||[]).map(s=>({n:s.n,summary:(s.summary||'').slice(0,80)})).slice(0,30),
    final:cleanReply?cleanReply(final).slice(0,2000):String(final).slice(0,2000)});
  // 抓整视口真实像素 → 简版本地标题 → 渲染 poster → 预览
  _captureChatShot((shotImg,scrBg,shotAr)=>{
    if(!shotImg&&typeof GA!=='undefined'&&GA.captureChat){try{GAT.emit('share_gen_fail',{stage:'capture'})}catch(e){}}   // 截图失败(重试后仍空)→standby 降级屏, 海报仍出但无真截图; 无桥(浏览器预览)不计
    toast(t('shareGenerating'));   // 截图落定后才提示: toast 在 PixelCopy 时刻可见会被截进海报
    const env=_shotEnv();
    const info=_shareLocalInfo(prompt,steps,final,base);   // 简版: 本地模板标题(无 LLM)
    info.scrBg=_chatThemeBg()||scrBg||'#0a0a0a';   // 主题底色优先(采样可能撞气泡色): 合成状态栏底色/standby 屏用
    info.shotAr=shotAr||0;info.vw=env.vw;info.viewAr=env.viewAr;   // I2/I3: 形态变量一次采集, 渲染纯函数化
    _renderPoster(info,shotImg,(dataUrl)=>{
      _shareBusy=false;
      if(!dataUrl){try{GAT.emit('share_gen_fail',{stage:'render'})}catch(e){}toast(t('shareSaveFail'));return}   // 简版渲染失败=预览根本没打开(share_click 后静默流失点)
      // 预览: 带上 shotImg/infoS/payload/base, 供精修/长图/折叠重渲复用
      showSharePreview(dataUrl,{shotImg:shotImg,scrBg:info.scrBg,shotAr:info.shotAr,infoS:info,payload:payload,base:base,sig:env.sig,fromModel:false});
    });
  });
}
// 抓整个 app 视口真实合成帧(PixelCopy, I1): 顶栏+对话区+输入栏 = 手机屏幕完整所见(所见即所分享)。
// 曾只截 #chat 内容区并按内容底部钳高 → 截图纵横比与 mock 屏不符, 底部大片填充色("大黑下巴"根因)。
// 失败自动重试1次(400ms后): 冷启/首海报在屏时 renderer tile 高压, 单次 PixelCopy/编码可能瞬态超时。
// 重试仍失败 → cb(null)(poster 屏内走 standby 降级屏, 仍是完整海报)。
function _captureChatShot(cb){_capShotTry(1,cb)}
function _capShotTry(retryLeft,cb){
  const fail=()=>{if(retryLeft>0)setTimeout(()=>_capShotTry(retryLeft-1,cb),400);else cb(null)};
  try{
    if(typeof GA==='undefined'||!GA.captureChat){cb(null);return}   // 无桥=浏览器预览, 不重试
    // 输出宽≈1200 设备px(mock 屏最大 ~640u=1280px 的近 1:1): 多放大无视觉增益, 只会喂出巨图 →
    // 离屏软件层 tile 内存爆 + data:URL 超 2MB 导航上限 → 二次分享黑图(v2.23 根因); Kotlin 侧另有 1440 硬上限。
    const w=innerWidth, h=innerHeight;
    const scale=Math.min(2,1200/(w*(window.devicePixelRatio||1)));
    const jid=GA.captureChat(0,0,w,h,scale);
    if(!jid||String(jid).indexOf('err')===0){fail();return}
    const t0=Date.now();
    const tick=()=>{
      let rr;try{rr=GA.renderHtmlResult(jid)}catch(e){fail();return}
      if(rr==='pending'){if(Date.now()-t0>9000){fail();return}setTimeout(tick,300);return}   // 9s: tile 高压下 PNG 编码可能慢于旧 6s 上限
      if(String(rr).indexOf('data:image')===0)_shotMeta(rr,(bg,ar)=>cb(rr,bg,ar));else fail();   // err:* → 重试/降级
    };
    setTimeout(tick,300);
  }catch(e){fail()}
}
// 量截图元数据: 纵横比 ar=高/宽(mock 屏 aspect 自适应用) + 底部一行平均色(手机屏空白填充的 fallback)。
// 填充色首选 _chatThemeBg() 活页主题底色(底行采样可能撞到气泡色→缝可见), 采样只作降级。
// 失败/跨域/1.5s 超时回退 {bg:'#0a0a0a',ar:0}(Image 解码在内存压力下可能停滞, 无超时会卡死 _shareBusy)。
function _shotMeta(dataUrl,cb){
  let done=false;const fin=(c,ar)=>{if(done)return;done=true;cb(c,ar||0)};
  try{
    const im=new Image();
    im.onload=()=>{try{
      const w=im.naturalWidth,h=im.naturalHeight;if(!w||!h){fin('#0a0a0a');return}
      const ar=h/w;
      const cv=document.createElement('canvas');cv.width=w;cv.height=1;
      const g=cv.getContext('2d');g.drawImage(im,0,h-1,w,1,0,0,w,1);   // 只取最后一行
      const d=g.getImageData(0,0,w,1).data;
      let r=0,gr=0,b=0,n=0;for(let i=0;i<d.length;i+=4){r+=d[i];gr+=d[i+1];b+=d[i+2];n++}
      if(!n){fin('#0a0a0a',ar);return}
      fin('rgb('+Math.round(r/n)+','+Math.round(gr/n)+','+Math.round(b/n)+')',ar);
    }catch(e){fin('#0a0a0a')}};
    im.onerror=()=>fin('#0a0a0a');
    setTimeout(()=>fin('#0a0a0a'),1500);
    im.src=dataUrl;
  }catch(e){fin('#0a0a0a')}
}
// 活页主题底色: 从 #chat 沿祖先链取第一个不透明 backgroundColor(浅/深主题自适应); 全透明→null(退采样色)
function _chatThemeBg(){try{
  let el=chat;
  while(el&&el.nodeType===1){
    const c=getComputedStyle(el).backgroundColor;
    if(c&&c!=='transparent'&&!/^rgba\([^)]*,\s*0\s*\)$/.test(c))return c;
    el=el.parentElement}
}catch(e){}return null}
// rgb()/rgba() → #RRGGBB(供原生 eraseColor; Android Color.parseColor 只吃 #hex/命名色, 不吃 rgb())。解析失败回退主题深/浅底。
function _rgbToHex(c){
  const m=String(c||'').match(/(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
  const dk=(document.documentElement.getAttribute('data-theme')||'')==='dark'
    ||(!document.documentElement.getAttribute('data-theme')&&matchMedia('(prefers-color-scheme:dark)').matches);
  if(!m)return dk?'#000000':'#ffffff';
  return '#'+[1,2,3].map(i=>(+m[i]).toString(16).padStart(2,'0')).join('');
}
// 离屏渲染 HTML → PNG dataURL 的统一 job(海报/长图共用): 提交 → 轮询 → 终态回调。
// bg(可选 #RRGGBB): 传给原生做位图底色 eraseColor(长图深色底防"内容高度外→透明→显白"), 海报不传保持原样。
function _renderHtmlJob(html,w,h,timeout,cb,bg){
  try{
    if(typeof GA==='undefined'||!GA.renderHtmlToImage){cb(null);return}
    let jid;
    if(bg){try{jid=GA.renderHtmlToImage(html,w,h,bg)}catch(e){jid=null}}   // 新壳 4 参(带底色); 旧壳无此重载→桥返回 undefined/抛错
    if(!jid||String(jid).indexOf('err')===0)jid=GA.renderHtmlToImage(html,w,h);   // 回退 3 参(CSS 根背景已兜底), OTA 新 JS 落旧壳不炸
    if(!jid||String(jid).indexOf('err')===0){cb(null);return}
    const t0=Date.now();
    const tick=()=>{
      let rr;try{rr=GA.renderHtmlResult(jid)}catch(e){cb(null);return}
      if(rr==='pending'){if(Date.now()-t0>timeout){cb(null);return}setTimeout(tick,300);return}
      if(String(rr).indexOf('data:image')===0)cb(rr);else cb(null);
    };
    setTimeout(tick,300);
  }catch(e){cb(null)}
}
// 用 poster.html v11 版式离屏渲染海报 → PNG dataURL。真 QR 在前端算好点阵传入(离屏 WebView 无 QR 库)。
// 画布 1080×(1080·viewAr)(I3): 折叠展开的方屏出方海报, 直板出修长海报, 预览 contain 恒满屏。
function _renderPoster(info,shotImg,cb){
  if(typeof GASharePoster==='undefined'){cb(null);return}   // 模块缺失(OTA分片热推未推新模块/缓存旧index): 回退失败(cb→_shareBusy重置+提示), 不静默卡死分享
  const profile=GASharePoster.layout(info.viewAr,info.shotAr);
  _renderHtmlJob(_posterHtml(info,shotImg),profile.canvasW,profile.canvasH,9000,cb);
}
// 海报视觉层委托给纯模块 share_poster.js；app.js 只负责翻译、二维码与渲染作业。
function _posterHtml(info,shotImg){
  const clean=Object.assign({},info,{
    title:String(info.title||'').replace(/[‘’]/g,"'").replace(/[“”]/g,'"'),
    autotip:String(info.autotip||'').replace(/^全程自动\s*·\s*/,'').replace(/·/,'')
  });
  let qrUrl='';try{qrUrl=_qrDataUrl(SHARE_URL,192)}catch(e){}
  const host=String(SHARE_URL||'github.com/shenhao-stu/GAgent').replace(/^https?:\/\//,'').replace(/\/.*$/,'');
  return GASharePoster.html({
    info:clean,
    shotImg:shotImg,
    copy:{
      runTag:t('shareRunTag'),autoWord:t('shareAutoWord'),stepsWord:t('shareStepsWord'),
      hook:t('shareHook'),urlLine:t('shareUrlLine'),privacy:t('sharePrivacy')
    },
    qrDataUrl:qrUrl,host:host,now:nowHM()
  });
}
// QR 点阵 → 白底黑码 PNG dataURL(供 poster 内联 <img>; 复用 app 自研 QR.matrix)
function _qrDataUrl(url,size){
  const qm=QR.matrix(url),n=qm.length,cell=size/n;
  const cv=document.createElement('canvas');cv.width=size;cv.height=size;
  const g=cv.getContext('2d');g.fillStyle='#fff';g.fillRect(0,0,size,size);g.fillStyle='#0a0a0a';
  for(let r=0;r<n;r++)for(let c=0;c<n;c++)if(qm[r][c])g.fillRect(c*cell,r*cell,cell+.5,cell+.5);
  return cv.toDataURL('image/png');
}
// 调后端 /share.summary 异步 job, 轮询取结果; 8s 内不返回则回退(cb 收到 null)
function _shareSummarize(payload,cb){
  let done=false;const fin=(r)=>{if(done)return;done=true;cb(r)};
  try{
    const j0=JSON.parse(GA.send('/share.summary '+payload)||'{}');
    const jid=j0.job;if(!jid){fin(null);return}
    jobPoll((cont)=>{
      let r;try{r=JSON.parse(GA.send('/jobresult '+jid)||'{}')}catch(e){fin(null);return}
      if(r.pending){cont();return}
      try{fin(JSON.parse(r.result||'{}'))}catch(e){fin(null)}
    },{interval:600,timeout:60000,onTimeout:()=>fin(null)});   // 上限 60s: 对齐后端 _run_job 设计(TTL 90s/UI 轮询上限 60s); 旧 15s 短于 gpt-5.5 蒸馏经中转典型 24s+, 精修恒超时回退简版=形同虚设(真机实测后端 24s ok=true)
  }catch(e){fin(null)}
}
function _shareLocalInfo(prompt,steps,final,base){
  const clean=s=>String(s||'').replace(/<\/?(summary|thinking)>/g,'').replace(/^\**\s*|\s*\**$/g,'').replace(/\s+/g,' ').trim();
  const bucket=shareBucket(steps);
  const cat=(base.steps>=12?'heavy':(base.steps>=5?'medium':'light'));
  // 关键点: 取有信息量的步骤摘要(去重/去空), 均匀采样最多 4 条
  const sums=(steps||[]).map(s=>clean(s&&s.summary)).filter(x=>x.length>=4);
  const uniq=[];sums.forEach(s=>{if(!uniq.some(u=>u.slice(0,8)===s.slice(0,8)))uniq.push(s)});
  let pts=[];if(uniq.length<=4)pts=uniq;else{const step=(uniq.length-1)/3;for(let i=0;i<4;i++)pts.push(uniq[Math.round(i*step)])}
  pts=pts.map(s=>s.length>26?s.slice(0,25)+'…':s);
  // 最终成果: final 首个非空行(去 markdown 标记), 无 final 则用类别短语兜底
  let outcome=clean((final||'').split('\n').find(l=>clean(l).length>=4)||'');
  if(outcome.length>30)outcome=outcome.slice(0,29)+'…';
  if(!outcome)outcome=(t('shareCat')||{})[cat]||'';
  const title=(t('shareLine')||{})[bucket]||(t('shareLine')||{}).done;   // 标题仍用第一人称模板(脱敏安全)
  return {title, points:pts, outcome, autotip:(t('shareAutoTip2')||''), fromModel:false, ...base};
}
// 从 step.summary 机械匹配动作构成→选第一人称模板桶(仅用于回退标题, 不外泄文本)
function shareBucket(steps){
  const blob=((steps||[]).map(s=>s&&s.summary||'').join(' ')).toLowerCase();
  if(/搜索|查找|查询|检索|search|find|look/.test(blob))return 'search';
  if(/填写|输入|发送|提交|下单|订|回复|input|type|send|submit|order|fill/.test(blob))return 'input';
  if(/读取|查看|提取|阅读|总结|read|view|extract|summar/.test(blob))return 'read';
  if((steps||[]).length>=3)return 'act';
  return 'done';
}
// 分享预览浮层。ctx = {shotImg,scrBg,shotAr,infoS,payload,base,sig} 供精修/长图/折叠形态重渲复用。
// 三页签 [简版|✨精修|长图] 共用一套状态机: st[k]=该档缓存, 保存/转发恒作用于当前显示的 img.src。
function showSharePreview(dataUrl,ctx){
  ctx=ctx||{};
  let mask=$('shareMask');
  if(!mask){mask=document.createElement('div');mask.id='shareMask';mask.onclick=(e)=>{if(e.target===mask)closeSharePreview()};document.body.appendChild(mask);
    mask.innerHTML='<div class="shareCard"><img class="shareImg" alt=""/>'
      +'<div class="stabs"><button class="stab stab-s on" data-k="simple"></button><button class="stab stab-l" data-k="long"></button></div>'   // NOREFINE(Boss 2026-08-03): 精修页签移除, 双页签[简版|长图]; LLM 蒸馏链路(_shareSummarize)保留休眠
      +'<div class="sload"><div class="sspin"></div><div class="sloadT"></div><div class="sloadS"></div><div class="sloadC"></div></div>'
      +'<div class="shareBtns"><button class="ssave"></button><button class="sfwd"></button></div>'
      +'<button class="sclose" aria-label="close">'+ICO_X+'</button></div>';
  }
  const ep=showSharePreview._ep=(showSharePreview._ep||0)+1;   // 会话代际: 不变量=复用的 mask DOM 只许当前会话的回调写, 关闭/重开后旧回调按代际作废
  const sess=showSharePreview._sess={t0:Date.now(),acted:false,st:null};   // 埋点会话态: acted=本次预览内保存/转发成功过(关闭时不算放弃); st 稍后挂上(页签/精修状态)
  const img=mask.querySelector('.shareImg');img.src=dataUrl;
  const bs=mask.querySelector('.ssave'),bf=mask.querySelector('.sfwd');
  const tabS=mask.querySelector('.stab-s'),tabL=mask.querySelector('.stab-l');
  const load=mask.querySelector('.sload'),loadT=mask.querySelector('.sloadT'),loadS=mask.querySelector('.sloadS');
  load.classList.remove('on');tabL.disabled=false;mask.classList.remove('longview');   // 清上次会话瞬态残留
  bs.textContent=t('shareSave');bf.textContent=t('shareForward');
  bs.onclick=()=>{const d=img.src;const r=(function(){try{return GA.saveImageToGallery(d)}catch(e){return 'err'}})();
    if(r==='ok'){sess.acted=true;toast(t('shareSaved'));try{GAT.emit('share_save',{})}catch(e){}}else toast(t('shareSaveFail'))};
  bf.onclick=()=>{const d=img.src;const r=(function(){try{return GA.shareImage(d)}catch(e){return 'err'}})();
    if(r==='ok'){sess.acted=true;try{GAT.emit('share_forward',{})}catch(e){}}else toast(t('shareForwardFail'))};
  mask.querySelector('.sclose').onclick=closeSharePreview;
  const loadC=mask.querySelector('.sloadC');
  tabS.textContent=t('shareTabSimple');tabL.textContent=t('shareTabLong');
  // rep=生成尝试代际: 取消(简版页签/返回键)只作废在飞长图不关预览, 与 ep(整个预览会话代际)分层
  const st={simple:dataUrl, long:null, cur:'simple', rep:0, pending:null, pt0:0};   // NOREFINE: refined/model/fromModel 态随页签一并摘除; pending/pt0=在飞生成档位+起点(终态埋点用)
  sess.st=st;sess.cancel=(via)=>cancelPending(via);   // 埋点: closeSharePreview 读页签态 + 关闭时取消在飞生成
  const alive=(rep)=>ep===showSharePreview._ep&&rep===st.rep;   // 过期回调统一判据
  const showLoad=(tt,ss)=>{loadT.textContent=tt;loadS.textContent=ss||'';if(loadC)loadC.textContent=t('shareRefineCancelTip');load.classList.add('on')};
  const show=(k)=>{st.cur=k;img.src=st[k];
    tabS.classList.toggle('on',k==='simple');tabL.classList.toggle('on',k==='long');
    mask.classList.toggle('longview',k==='long')};   // 长图超视口: 切滚动查看模式
  const cancelPending=(via)=>{
    if(!load.classList.contains('on'))return false;
    if(via&&st.pending==='long'){try{GAT.emit('share_long_cancel',{via:via,ms:Date.now()-st.pt0})}catch(e){}}   // 用户取消在飞长图终态(via=tab/back/close); 折叠重渲静默作废(via 空)不计
    st.pending=null;
    st.rep++;load.classList.remove('on');tabL.disabled=false;   // 在飞回调按 rep 作废, 页签可重试
    return true};
  _shareRefineCancel=()=>cancelPending('back');   // gaOnBack 用: 生成中首次返回=只取消(留在预览), 再按才关(长图在飞同样适用)
  const genSimple=(rep)=>{            // 简版重渲(折叠重渲用: 标题信息复用, 只换形态变量)
    st.pending='simple';st.pt0=Date.now();
    const env=_shotEnv();
    const info=Object.assign({},ctx.infoS,{scrBg:ctx.scrBg,shotAr:ctx.shotAr,vw:env.vw,viewAr:env.viewAr});
    _renderPoster(info,ctx.shotImg,(du)=>{
      if(!alive(rep))return;
      st.pending=null;
      load.classList.remove('on');
      if(du){st.simple=du;show('simple')}else{try{GAT.emit('share_gen_fail',{stage:'rerender'})}catch(e){}toast(t('shareSaveFail'))}   // 折叠重渲失败(留旧图垫底)
    });
  };
  const genLong=(rep)=>{
    st.pending='long';st.pt0=Date.now();
    tabL.disabled=true;
    _makeLongShot((du)=>{
      if(!alive(rep))return;
      const ms=Date.now()-st.pt0;st.pending=null;
      tabL.disabled=false;load.classList.remove('on');
      if(!du){try{GAT.emit('share_long_fail',{ms:ms})}catch(e){}toast(t('shareLongFail'));return}   // 长图终态: 失败(share_long 点击后配对算成功率)
      try{GAT.emit('share_long_done',{ms:ms})}catch(e){}
      st.long=du;show('long');
    });
  };
  const setTab=(k)=>{
    if(k==='simple'&&cancelPending('tab')){   // loading 中点「简版」=取消在飞生成(恒有出口); 缓存被折叠重渲作废时就地重生
      if(st.simple)show('simple');else{showLoad(t('shareRefolding'));genSimple(++st.rep)}
      return}
    if(st.cur===k&&st[k])return;                               // 当前档且有图=无事; 缓存空(重渲失败)则点击=重试
    cancelPending('tab');                                      // 换道先作废在飞生成(rep+1), 页签禁用态一并复位
    if(st[k]){show(k);return}                                  // 已缓存: 切换即时
    if(k==='long'){
      showLoad(t('shareLongMaking'),t('shareLongSub'));
      try{GAT.emit('share_long',{})}catch(e){}
      genLong(++st.rep);
    }else{showLoad(t('shareRefolding'));genSimple(++st.rep)}   // 至此 st.simple 必空(缓存命中已提前返回)=折叠重渲后回切: 就地重生
  };
  tabS.onclick=()=>setTab('simple');
  tabL.onclick=()=>setTab('long');
  // ── 折叠形态切换(展开↔合拢)重渲: 视口签名变了 → 露底重截 → 三档缓存作废 → 当前档按新形态再生 ──
  // 体验取舍: 遮罩需短暂隐藏(PixelCopy 只能截真实合成帧), 用户刚翻折手机, 瞬见真界面是自然的。
  ctx.refold=()=>{
    cancelPending();   // 折叠重渲: 静默作废在飞生成(设备翻折非用户取消)
    const rep=++st.rep;
    ctx.sig=_foldSig();
    mask.style.display='none';
    setTimeout(()=>_captureChatShot((shotImg,scrBg,shotAr)=>{
      mask.style.display='';
      if(!alive(rep))return;
      if(shotImg){ctx.shotImg=shotImg;ctx.scrBg=_chatThemeBg()||scrBg||ctx.scrBg;ctx.shotAr=shotAr||0}
      const keep=st.cur;   // 当前档留旧图垫底: 重渲失败/被取消时不露空 src 破图
      ['simple','long'].forEach(x=>{if(x!==keep)st[x]=null});   // 其余档作废(形态已变)
      showLoad(t('shareRefolding'));
      if(st.cur==='long')genLong(rep);
      else genSimple(rep);
    }),160);   // 等遮罩消失帧真正合成上屏后再截
  };
  _shareCtx=ctx;
  show(st.cur);
  requestAnimationFrame(()=>mask.classList.add('on'))
}
// 折叠/旋转监听(模块级一次性): 预览开着且视口签名变化 → 稳定 450ms 后按新形态重渲
window.addEventListener('resize',()=>{
  const m=$('shareMask');if(!m||!m.classList.contains('on')||!_shareCtx)return;
  clearTimeout(showSharePreview._rz);
  showSharePreview._rz=setTimeout(()=>{if(_shareCtx&&_shareCtx.sig!==_foldSig()&&$('shareMask').classList.contains('on'))_shareCtx.refold()},450);
});
function closeSharePreview(){   // 代际+1: 在飞回调立即作废; 淡出后清 img.src 释放解码位图(常驻大图=tile 内存爆帮凶)
  const m=$('shareMask');if(!m)return;
  const wasOn=m.classList.contains('on');
  const ep=showSharePreview._ep=(showSharePreview._ep||0)+1;
  _shareCtx=null;_shareRefineCancel=null;
  try{const sess=showSharePreview._sess;
    if(wasOn&&sess){
      if(sess.cancel)sess.cancel('close');   // 长图在飞时关闭=取消终态(share_long_cancel via=close), 空转无害
      if(!sess.acted)GAT.emit('share_abandon',{tab:(sess.st&&sess.st.cur)||'simple',long:!!(sess.st&&sess.st.long),ms:Date.now()-sess.t0});   // 放弃埋点: 本次预览未保存/未转发就关闭(保存或转发成功过则不算放弃); long=本次生成过长图(NOREFINE 后废弃 refined 字段)
      showSharePreview._sess=null}   // 会话终结: 防重入双发
  }catch(e){}
  m.querySelectorAll('.stab').forEach(b=>b.onclick=null);   // 解除页签闭包 → 释放 st 缓存的三档大图字符串(长图可达数MB)
  m.classList.remove('on');
  setTimeout(()=>{if(ep!==showSharePreview._ep)return;const im=m.querySelector('.shareImg');if(im)im.src=FP_POSTER},320);
}
/* ── 长截图: 完整对话一张长图(所见即所得) ─────────────────────────────────────
   不变量: 长图与屏上对话同源——克隆 #chat 当前 DOM + 复用同一份样式表(document.styleSheets 序列化),
   版心宽 = #chat 当前宽(折叠形态自然带入换行); 输出受离屏渲染硬上限(4096×8192)约束,
   k = 每 CSS px 的设备 px, 内容超长时自动降 k(CSS zoom)保"全量对话"优先于分辨率。 */
function _pageCss(){
  let miss=false;
  const own=[...document.styleSheets].map(s=>{let rs;try{rs=s.cssRules}catch(e){miss=true;return ''}
    return [...rs].map(r=>r.cssText).join('\n')}).join('\n');
  if(!miss)return own;   // http 预览: CSSOM 全可读
  let base='';try{base=GA.send('/ui.css')||''}catch(e){}   // file://: <link app.css> 被 CSSOM 判跨域禁读 → 后端回读原文
  return base+'\n'+own;  // app.css 本就是首表 → 原文在前, 动态 <style> 在后, 与文档层叠序一致
}
// 长图专属样式(离屏文档与量高探针共用): 全部挂在 .ls* 类上, 注入活页量高时零污染。
// .lsChat 承接 #chat 的版心内衬(消息气泡样式本就按类命中, 克隆后自然生效)。
const _LS_CSS='.lsChat{padding:var(--sp-1) var(--sp-4) var(--sp-4)}'
 +'.lsChat .task{content-visibility:visible;contain-intrinsic-size:none}'   // 活页 .task 的 content-visibility:auto 在隐藏探针/离屏视口外只给 220px 占位 → 量高与渲染双双腰斩, 长图必须全量排版
 +'.lsChat *{animation:none!important;transition:none!important}'   /* LONGSHOT_ANIM: 离屏渲染是静态首帧——.sprPop(gaSprPop from{opacity:0} + both)/.rrW 逐词淡入等入场动画在首帧全隐形
    ⇒ 活体轮的 .finalMsg 在长图缺席(Boss 2026-08-03「长图缺最后结果」实锤根因; 回放轮不加 sprPop 故显示正常)。禁动画后元素回归自然样式(opacity:1) */
 +'.lsChat .msgAct,.lsChat .uAct,.lsChat .askCustom,.lsChat .doneNote{display:none!important}'   // 去交互纽扣(复制/分享/输入框等)
 +'.lsHd{display:flex;align-items:center;gap:9px;padding:16px 16px 10px;border-bottom:1px solid var(--line,rgba(128,128,128,.25))}'
 +'.lsHd .dot{width:10px;height:10px;border-radius:3px;background:#30D158;box-shadow:0 0 8px rgba(48,209,88,.6);flex:none}'
 +'.lsHd b{font-size:15px}.lsHd span{margin-left:auto;font-size:11px;opacity:.55;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}'
 +'.lsFt{display:flex;align-items:center;gap:12px;padding:14px 16px 18px;border-top:1px solid var(--line,rgba(128,128,128,.25))}'
 +'.lsFt .fl{flex:1;min-width:0}.lsFt .h{font-size:13.5px;font-weight:700}.lsFt .u{margin-top:4px;font-size:10.5px;opacity:.6}'
 +'.lsFt img{width:52px;height:52px;background:#fff;border-radius:8px;padding:3px;flex:none}';
function _inlineLongShotImages(cl){
  // 离屏长图是 data: HTML，没有主 WebView 的 ../temp/ 路径基准。
  // 仅将当前 GA temp 中受控、可见的少量图片内联；其他本地 file: 图仍移除，绝不开放任意路径读取。
  if(typeof GA==='undefined'||!GA.send)return;
  let count=0,total=0;
  cl.querySelectorAll('img').forEach(i=>{
    const raw=i.getAttribute('src')||'';
    if(raw.startsWith('file:')){i.remove();return}
    if(!raw.startsWith('../temp/'))return;
    const rel=raw.slice('../temp/'.length);
    if(!rel||count>=3||total>=3*1024*1024){i.replaceWith(document.createTextNode('[图片未包含在分享长图中]'));return}
    try{
      const out=JSON.parse(GA.send('/files.image_data '+rel)||'{}');
      if(!out.ok||!out.base64||!out.mime||!out.size||out.size>1024*1024||total+out.size>3*1024*1024){
        i.replaceWith(document.createTextNode('[图片未包含在分享长图中]'));return
      }
      i.src='data:'+out.mime+';base64,'+out.base64;
      count++;total+=out.size;
    }catch(e){i.replaceWith(document.createTextNode('[图片未包含在分享长图中]'))}
  });
}
function _longShotBody(){
  const cl=chat.cloneNode(true);
  cl.removeAttribute('id');cl.className='lsChat';
  _inlineLongShotImages(cl);
  const esc=s=>String(s||'').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const name=esc(curConvo?convoTitle(curConvo):'GenericAgent');
  const d=new Date(), pad=n=>(n<10?'0':'')+n, dateStr=d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());
  let qr='';try{qr=_qrDataUrl(SHARE_URL,144)}catch(e){}
  const host=String(SHARE_URL||'github.com/shenhao-stu/GAgent').replace(/^https?:\/\//,'').replace(/\/.*$/,'');
  return '<div class="lsHd"><span class="dot"></span><b>GenericAgent</b><span>'+name+' · '+dateStr+'</span></div>'
   +cl.outerHTML
   +'<div class="lsFt"><div class="fl"><div class="h">'+esc(t('shareHook'))+'</div><div class="u"><b>'+esc(host)+'</b> — '+esc(t('shareUrlLine'))+'</div></div>'
   +(qr?'<img src="'+qr+'" alt="">':'')+'</div>';
}
function _makeLongShot(cb){
  try{
    if(typeof GA==='undefined'||!GA.renderHtmlToImage){cb(null);return}
    const w=Math.max(280,chat.clientWidth);   // 版心宽=当前会话区宽 → 换行与屏上一致(折叠形态自然带入)
    const body=_longShotBody();
    // 同页隐形量高: 同一份样式表下排一遍, 高度即离屏结果高度(确定性, 无二次往返)
    const probe=document.createElement('div');
    probe.style.cssText='position:absolute;left:0;top:0;width:'+w+'px;visibility:hidden;pointer-events:none';
    probe.innerHTML='<style>'+_LS_CSS+'</style>'+body;
    document.body.appendChild(probe);
    const hCss=Math.max(200,probe.scrollHeight+24);   // +24: 度量/离屏环境亚像素差余量, 多出部分是页面底色
    probe.remove();
    const dpr=window.devicePixelRatio||2;
    const k=Math.min(dpr,8192/hCss,1440/w);           // 全量优先: 超长自动降清晰度而非截断; 宽≤1440=管线巨图红线(I4, v2.23 tile 内存爆教训)
    const dk=document.documentElement.getAttribute('data-theme')||'light';
    // 底部白边根治(v2): **zoom 从 `<html>` 移到 `<body>`**, 根元素不缩放。
    //  根因(之前 v1 未真修): Chromium 只把**未缩放的根元素**背景传播到整张画布(canvas backdrop);
    //   一旦 `<html>` 带 zoom, 其背景只画到"缩放后根盒(hCss*z)"内, 盒底到位图底之间落 WebView 缺省白底 = 深色长图底部白边。
    //  修法: `<html>` 不缩放且显式 var(--bg) → 背景铺满整张位图(与内容高度/缩放解耦); 缩放改挂 `<body>`(布局/reflow 与原先按 w 量高一致)。
    const html='<!doctype html><html data-theme="'+dk+'"><head><meta charset="utf-8"><style>'
     +_pageCss()
     +'\nhtml{background:var(--bg)}'                                                                        // 未缩放根 → 背景传播到整张画布, 消除底部白边
     +'\nbody{zoom:'+(k/dpr).toFixed(6)+';width:'+w+'px;min-height:'+hCss+'px;height:auto;margin:0;background:var(--bg);overflow:visible}'
     +_LS_CSS+'</style></head><body>'+body+'</body></html>';
    const bgHex=_rgbToHex(_chatThemeBg());   // 主题实色 → 原生位图 eraseColor 兜底(与 CSS 根背景双保险, 彻底消除底部白边)
    _renderHtmlJob(html,Math.round(w*k),Math.min(8192,Math.ceil(hCss*k)),20000,cb,bgHex);   // 长图位图大, 轮询上限放宽到 20s
  }catch(e){cb(null)}
}

/* ════════════ ask_user 单/多选框 + 完成提示音/系统消息 (issue#2 #7) ════════════ */
function playDone(){if(!soundOn)return;try{
  const Ac=window.AudioContext||window.webkitAudioContext;if(!Ac)return;
  const ac=playDone._ac||(playDone._ac=new Ac());if(ac.state==='suspended'){const p=ac.resume();if(p&&p.catch)p.catch(()=>{})}
  const now=ac.currentTime;[[660,0],[988,.12]].forEach(([f,dt])=>{   // 轻柔上行双音, 克制不刺耳
    const o=ac.createOscillator(),g=ac.createGain();o.type='sine';o.frequency.value=f;o.connect(g);g.connect(ac.destination);
    const t0=now+dt;g.gain.setValueAtTime(0,t0);g.gain.linearRampToValueAtTime(.12,t0+.02);g.gain.exponentialRampToValueAtTime(.0001,t0+.22);
    o.start(t0);o.stop(t0+.24)})}catch(e){}}
function playAsk(){if(!soundOn)return;try{   // "叮-叮"同音双击: 区别于完成的上行双音, 表示"需要你的操作"
  const Ac=window.AudioContext||window.webkitAudioContext;if(!Ac)return;
  const ac=playDone._ac||(playDone._ac=new Ac());if(ac.state==='suspended'){const p=ac.resume();if(p&&p.catch)p.catch(()=>{})}
  const now=ac.currentTime;[[880,0],[880,.17]].forEach(([f,dt])=>{
    const o=ac.createOscillator(),g=ac.createGain();o.type='sine';o.frequency.value=f;o.connect(g);g.connect(ac.destination);
    const t0=now+dt;g.gain.setValueAtTime(0,t0);g.gain.linearRampToValueAtTime(.14,t0+.02);g.gain.exponentialRampToValueAtTime(.0001,t0+.15);
    o.start(t0);o.stop(t0+.17)})}catch(e){}}
// 退到后台/锁屏时才发系统级提醒(前台有屏幕+提示音即可); ask 比 done 高一级: 振动更强 + 高优先级通知通道(issue#5)
function notifyAway(level,c){if(!document.hidden)return;
  try{if(navigator.vibrate)navigator.vibrate(level==='ask'?[0,90,70,90]:25)}catch(e){}
  try{if(typeof GA==='undefined'||!GA.notify)return;
    const cc=c||curConvo,title=t('appName'),body=(cc?convoTitle(cc).slice(0,40)+' · ':'')+(level==='ask'?t('t_needInput'):t('t_taskDone'));   // c=任务归属会话(预览别会话时通知不错标)
    if(level==='ask'){try{GA.notify(title,body,'high')}catch(e){GA.notify(title,body)}}   // 3参=高优先级通道(新APK); 旧APK无此重载→回退2参
    else GA.notify(title,body);
  }catch(e){}}
function onTaskDone(show,c){playDone();   // show=false: 正在预览别会话, doneNote 不画进当前视图(T6); 提示音/通知照常
  if(show!==false){const n=el('div','doneNote');n.innerHTML=ICO_CK+'<span></span>';n.querySelector('span').textContent=t('t_taskDone');scroll();
    if(pinned){_snDown.classList.add('done');_snDown.hidden=false;_snav.classList.add('on')}}   // C2C4(监察 F2): 顶置阅读态不抢滚, 改点亮回底钮; 点击/贴底自然清除
  notifyAway('done',c)}                                 // 完成: 轻提示音 + 普通通知(署名任务归属会话)
function onNeedInput(c){playAsk();notifyAway('ask',c)}  // 需要回答 ask_user: 醒目提示音 + 高优先级通知
let _askKey=null;
function renderAskPicker(ask){if(!ask)return;
  const key=(ask.question||'')+'|'+((ask.candidates||[]).join('|'));
  if(_askKey===key&&document.querySelector('.askBox'))return;          // 同一问题不重复渲染(防 poll/启动重入)
  if(document.querySelector('.askBox:not(.answered)'))return;          // 已有未答的选择框
  _askKey=key;
  const q=ask.question||t('askChoose'),cs=ask.candidates||[];
  const multi=/\[?\s*(?:多选|可多选|多项选择|multi(?:[-_ ]?select)?|multiple|select\s+all)\s*\]?/i.test(q);   // 与核心 _MULTI_RE 对齐(issue#3): [多选]/multi-select/select all 等都触发多选; 核心无 schema 字段, 靠问题文本推断
  const box=el('div','askBox');
  box.innerHTML='<div class="askHd"><span></span></div>'+((cs.length&&multi)?'<div class="askHint"></div>':'');   // 去掉左侧悬空小气泡, 卡片本身已表意(第一性原则, issue#2)
  box.querySelector('.askHd span').textContent=q;
  if(cs.length&&multi)box.querySelector('.askHint').textContent=t('askMulti');
  if(cs.length){const opts=el('div','askOpts',box);
    cs.forEach((c,i)=>{const o=el('button','askOpt',opts);
      o.innerHTML='<span class="ix"></span><span class="ol"></span>';
      o.querySelector('.ix').textContent=String.fromCharCode(65+(i%26));o.querySelector('.ol').textContent=c;
      o.onclick=()=>{if(box.classList.contains('answered'))return;
        if(multi)o.classList.toggle('pick');else answerAsk(box,c)}})}
  const cw=el('div','askCustom',box);
  const ipt=document.createElement('input');ipt.type='text';ipt.placeholder=t('askCustom');ipt.setAttribute('aria-label',t('askCustom'));
  const snd=document.createElement('button');snd.className='send';snd.setAttribute('aria-label',t('askSend'));snd.innerHTML=ICON_SEND;
  cw.appendChild(ipt);cw.appendChild(snd);
  const go=()=>{if(box.classList.contains('answered'))return;
    const picks=[...box.querySelectorAll('.askOpt.pick .ol')].map(e=>e.textContent);
    const ans=ipt.value.trim()||picks.join('; ');
    if(!ans){ipt.focus();toast(t('askChoose'));return}answerAsk(box,ans)};   // 空提交: 提示而非静默
  snd.onclick=go;ipt.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();go()}});
  scroll(1)}
function answerAsk(box,ans){if(box.classList.contains('answered'))return;
  box.classList.add('answered');   // 先占位标记: 使发送路径的 :not(.answered) 清理不会误删本框; 下方发送失败再回退
  let ok=false;try{ok=startTask(ans)!==false}catch(e){bubble('sys',String(e))}   // 作为新消息发送 → agent 携完整历史续跑(agentmain: full history in llmclient)
  if(!ok){box.classList.remove('answered');return}   // 运行中/无服务商/后端拒绝 → 未真正发出, 撤回标记, 选择框保持可答, 不误显"已回答"
  _askKey=null;
  box.querySelectorAll('.askOpt').forEach(o=>{o.disabled=true;if(o.querySelector('.ol').textContent===ans)o.classList.add('pick')});
  const cw=box.querySelector('.askCustom');if(cw)cw.remove();
  const d=el('div','askDone',box);d.innerHTML=ICO_CK+'<span></span>';d.querySelector('span').textContent=t('askAnswered')+'：'+ans}

/* ════════════ poll / run ════════════ */
function setStatus(t,busy){sub.textContent=t||'';sub.classList.toggle('busy',!!busy)}
function sendEnabledState(){try{const r=GA.ready();sendReady=(r==='ok'||r==='nokey')}catch(e){sendReady=false}
  return running||sendReady}   // running 时按钮是停止键必须可点; 空闲时 native ready/nokey 后可发(无 key 由后续流程引导)
function applySendEnabled(){btn.disabled=!sendEnabledState();btn.setAttribute('aria-disabled',btn.disabled?'true':'false');return !btn.disabled}
/* 故障转移实时路由(issue#3): 自动模式下把"当前实际路由到的成员"模型(含品牌 logo)写进助手消息头, 并存档→回放也显示真实模型 */
function applyRoute(r){if(!task||!task.box||!r||!r.model)return;
  const head=task.box.querySelector('.assistHead');if(!head)return;
  const label=dispModel(r.model)||r.name||'';
  const nm=head.querySelector('.assistName');if(nm&&label&&nm.textContent!==label)nm.textContent=label;
  const g=head.querySelector('.glyph'),sig=(r.model||'')+'|'+(r.type||'');
  if(g&&g._rsig!==sig){const tmp=document.createElement('div');tmp.innerHTML=modelGlyph(r.model,r.type);const ng=tmp.firstChild;if(ng){ng._rsig=sig;g.replaceWith(ng)}}
  if(task.msg&&label)task.msg.model=label;
  if(task&&!task._routed){task._routed=1;GAT.emit('auto_route',{type:r.type||'',n:(foCfg&&foCfg.llm_nos&&foCfg.llm_nos.length)||0})}}
/* ════════ 工具时间线(参观层, PLAN v3.2 §6 · 监察 #009): render() 无条件消费 tool_events ════════
   人话翻译层(A/E) + per-step 内嵌行(B, event.turn===steps[].n) + live 钉底条(C, #comp 内部) + 详情翻页(D) + 步文本 🛠️ 标题行卡级剥除(F);
   归属仍只画 event.gen===payload.gen; 终态推断在前端(running 事件+任务停 ⇒「已中断」);
   点停止后 task 本地收尾, 终态靠 2s 空闲 poll → twState.box 引用兜底, 不依赖活体 task */
let twState={gen:null,box:null,evs:[]};
function _twEsc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')}
function _twDur(e,liveLast){const t0=+e.t_start||0;if(!t0)return'';const t1=+e.t_end||0;
  if(t1)return Math.max(0,t1-t0).toFixed(1)+'s';
  return liveLast?(Math.max(0,Date.now()/1000-t0).toFixed(0)+'s'):'—'}   // 中断事件无真实耗时, 不编数字
function _twUnesc(s){try{return JSON.parse('"'+s+'"')}catch(e){return String(s).replace(/\\n/g,'\n').replace(/\\t/g,'\t').replace(/\\"/g,'"').replace(/\\\\/g,'\\')}}
function _twParse(s){                                        // 双路径解析(#009 必修 4): 300 字截断 JSON 非法是常态, parse 只是快路径
  s=String(s||'');if(!s)return{};
  try{const o=JSON.parse(s);if(o&&typeof o==='object'&&!Array.isArray(o))return o}catch(e){}
  const o={},rx=/"(type|script|desc|path|file|filename|content|question|prompt|url|cmd|stdout|status|error|message)"\s*:\s*"((?:[^"\\]|\\.)*)/g;let m;   // desc=humanize 前向预埋位(截断 JSON 场景仍可捞, PLAN_TOOLROW_HUMANIZE §2)
  while((m=rx.exec(s)))if(!(m[1] in o))o[m[1]]=_twUnesc(m[2]);   // 取已转义前缀(可能被截断)再反转义
  return o}
function _twLine(s,cap){s=String(s==null?'':s).trim();const i=s.indexOf('\n');if(i>=0)s=s.slice(0,i);cap=cap||64;return s.length>cap?s.slice(0,cap)+'…':s}
function _twBase(p){p=String(p||'');const i=Math.max(p.lastIndexOf('/'),p.lastIndexOf('\\'));return i>=0?p.slice(i+1):p}
function _twTitle(e){                                        // 人话动作行(A): {t:标题, s:副文}; 未知工具兜底=原名+首个实参值(禁止空标题)
  const a=_twParse(e.input_summary),n=e.name||'';
  try{if(e.desc&&!a.desc)a.desc=String(e.desc)}catch(_d){}   /* D3 桥接: 内核(tool_events_hook.py)把模型写的 desc 收进事件顶层并从 input_summary 剔除,
     humanize.js:53 只认 a.desc, 故此行把顶层 e.desc 补进 a —— 顶层通道不受 SUM_CAP=300 截断影响。
     !a.desc 短路保证旧内核(desc 留在 input_summary)也照常工作。此行是 D3 的唯一前端增量(humanize.js 本体零改动), 已在 INSPECTION_LOG #017 申报。 */
  if(!window.GA_HUMANIZE_OFF&&window.GA_HUMANIZE){try{const hz=GA_HUMANIZE.title(e,a);if(hz)return hz}catch(_x){}}   // H1 人话短句优先层(纯参观层); null/异常 → 原路径零变化(返工修复: 异常≠null, 必须兜住)
  if(n==='code_run'){const ty=String(a.type||'').toLowerCase();
    return{t:ty==='python'?t('twRunPy'):(ty==='sh'?t('twRunSh'):t('twRun')),s:_twLine(a.script)}}
  if(n==='file_read')return{t:t('twReadFile'),s:_twBase(a.path||a.file||a.filename)};
  if(n==='file_write')return{t:t('twWriteFile'),s:_twBase(a.path||a.file||a.filename)};
  if(n==='file_patch')return{t:t('twPatchFile'),s:_twBase(a.path||a.file||a.filename)};
  if(n==='update_working_checkpoint')return{t:t('twCkpt'),s:_twLine(a.content||a.desc||'',40)};   // TOOLDENSE: 原恒空副文 → 带进度内容头部
  if(n==='start_long_term_update')return{t:t('twLtm'),s:_twLine(a.content||a.desc||'',40)};
  if(n==='ask_user')return{t:t('twAsk'),s:_twLine(a.question||a.prompt)};
  let v='';for(const k in a){if(a[k]!=null&&typeof a[k]!=='object'){v=_twLine(a[k]);break}}
  return{t:n||'?',s:v}}
function _twResult(e){                                       // 结果人话(A/E): stdout 原文 > error 字段 > 状态词 > 原串
  if(!window.GA_HUMANIZE_OFF&&window.GA_HUMANIZE){try{const hz=GA_HUMANIZE.result(e);if(hz)return hz}catch(_x){}}   // H3 错误行短句化(类别·类型); null/异常 → 原路径(返工修复: 异常≠null, 必须兜住)
  if(e.status==='error'){let er=String(e.error||'').trim();
    if(!er||/^error\.?$/i.test(er)){const r=_twParse(e.result_summary);   // 设备内核 error 字段常为裸 "error", 真因在 stdout 的 traceback 里
      if(r.stdout!=null){const ls=String(r.stdout).trim().split('\n').map(x=>x.trim()).filter(Boolean);
        er=ls.find(x=>/^[A-Za-z_.]*(Error|Exception)\b/.test(x))||ls[ls.length-1]||''}}
    return _twLine(er||t('twFailed'),80)}
  const r=_twParse(e.result_summary);
  if(r.stdout!=null&&String(r.stdout).trim())return _twLine(r.stdout,80);
  if(typeof r.status==='string'&&r.status)return r.status;
  for(const k in r){if(r[k]!=null&&typeof r[k]!=='object')return _twLine(r[k],80)}
  return _twLine(e.result_summary,80)}
function _twStripText(s,c){                                  // F: 只剥 🛠️ 标题行/单行(args/stdout 围栏必留, #009 必修 1); 卡级标记+事件 name 白名单锚定
  if(!s||!c||!c._twStrip||!c._twNames||!c._twNames.length)return s;
  const nn='(?:'+c._twNames.map(x=>String(x).replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|')+')';
  s=s.replace(new RegExp('^[ \\t]*🛠️?\\s*Tool:\\s*`?'+nn+'`?\\s*📥?\\s*args:\\s*$','gim'),'');   // verbose 标题行
  s=s.replace(new RegExp('^[ \\t]*🛠️?\\s*'+nn+'\\([^\\n]*$','gim'),'');                          // 非 verbose 单行 🛠️ name(...)
  return s.replace(/\n{3,}/g,'\n\n')}
const _twSvg=p=>'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'+p+'</svg>';   // TOOLDENSE: 描边 SVG 图标(与 .fileRow/.chev 同风格), currentColor 随行色, 零新依赖
const _TW_ICO={
  file_read:_twSvg('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h5"/>'),
  file_write:_twSvg('<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/>'),
  file_patch:_twSvg('<circle cx="6" cy="6" r="2.2"/><circle cx="6" cy="18" r="2.2"/><path d="M6 8.2v7.6"/><path d="M15 6h5M17.5 3.5v5"/><path d="M15 18h5"/>'),
  ask_user:_twSvg('<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M8 10h.01M12 10h.01M16 10h.01"/>'),
  update_working_checkpoint:_twSvg('<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>'),
  start_long_term_update:_twSvg('<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>')};
const _TW_ICO_SH=_twSvg('<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>');
const _TW_ICO_PY=_twSvg('<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>');
const _TW_ICO_WEB=_twSvg('<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>');
const _TW_ICO_DEF=_twSvg('<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>');
function _twIcon(e){const n=e.name||'';
  if(n==='code_run')return String(_twParse(e.input_summary).type||'').toLowerCase()==='python'?_TW_ICO_PY:_TW_ICO_SH;
  if(_TW_ICO[n])return _TW_ICO[n];
  if(/browser|web|nav|url|http|search/i.test(n))return _TW_ICO_WEB;
  return _TW_ICO_DEF}
function _twRow(e,i,liveLast,run,cnt){                       /* TOOLROW_V2(Boss 2026-08-03「叉勾/红绿边框无意义, 样式丑」): 一行=[工具图标|spinner]+标题+副文+[×N]+耗时。
     状态列删除, 语义降维——成功=默认态零标记; 运行中=图标位 spinner; 错误=副文红字(.twr.err); 中断=副文灰字「已中止」。数据流/点击详情零改动 */
  const itr=e.status==='running'&&!run,ti=_twTitle(e);
  const lead=(e.status==='running'&&run)?'<span class="twspin"></span>':_twIcon(e);
  const sub=e.status==='error'?_twResult(e):(itr?t('twAborted'):ti.s);
  const sbc='twsb'+((ti.plain||itr)&&e.status!=='error'?' plain':'');   // H4: humanize 人话/中断文案去等宽(错误行由 .twr.err .twsb 覆盖字体)
  return '<div class="twr'+(e.status==='error'?' err':'')+'" data-i="'+i+'"><span class="twgi">'+lead+'</span>'
    +'<span class="twti">'+_twEsc(ti.t)+'</span><span class="'+sbc+'">'+_twEsc(sub||'')+'</span>'
    +(cnt>1?'<span class="twn">×'+cnt+'</span>':'')
    +'<span class="twdu">'+_twEsc(_twDur(e,liveLast))+'</span></div>'}
function renderTools(j){
  if(!j||!Array.isArray(j.tool_events))return;               // 旧后端无键 → 完全不动现有 UI(空载荷教训)
  const evs=j.tool_events.filter(e=>e&&String(e.gen)===String(j.gen));
  const run=!!j.running;
  let box=(task&&task.box&&task.box.isConnected)?task.box:null;
  if(!box&&twState.box&&twState.box.isConnected&&String(twState.gen)===String(j.gen))box=twState.box;   // 点停止后终态兜底
  if(!evs.length||!box){_twLiveBar(null,j);return}
  twState={gen:j.gen,box:box,evs:evs,run:run};   // run 供 _twLiveTick 判定步内 .twdu 是否按 live 递增
  const cards=[].slice.call(box.querySelectorAll('.step'));
  if(cards.length){
    const last=evs[evs.length-1],bins={};
    evs.forEach((e,i)=>{let tn=+e.turn||1;if(tn>cards.length)tn=cards.length;if(tn<1)tn=1;(bins[tn]=bins[tn]||[]).push(i)});   // turn 超前(工具先于步文本)挂末卡, 下轮补齐自动归位
    cards.forEach((c,ci)=>{
      const idxs=bins[ci+1];let host=c.querySelector('.tsr');
      if(!idxs){if(host)host.remove();return}
      if(!host){host=document.createElement('div');host.className='tsr ga-card ga-card--tool';c.insertBefore(host,c.querySelector('.sb'))}   // .sh 与 .sb 之间=折叠态常显(#009: 不得放进 .sb); F2.2: 入卡换壳
      const _he=idxs.some(i=>evs[i].status==='error'),_hr=run&&idxs.some(i=>evs[i].status==='running');   // F2.2 左缘状态色条: err > run > ok(纯视觉, 不碰数据)
      host.classList.toggle('err',_he);host.classList.toggle('run',!_he&&_hr);host.classList.toggle('ok',!_he&&!_hr);
      const names=idxs.map(i=>evs[i].name).filter(Boolean);
      if(!c._twStrip||c._twNames&&c._twNames.length!==names.length){c._twStrip=1;c._twNames=names;
        const sb=c.querySelector('.sb');if(sb){sb._rendered=false;renderBody(c)}}                       // 标记后重画正文以剥 🛠️ 标题行(仅开卡实际重算)
      // 收纳(Boss 2026-07-31 拍板方案2): 折叠态每步只常显 1 行——运行中 > (任务停后)末次错误 > 最新事件; ×N 徽章示总次数, 历史全部经点行→详情弹层 ‹ N/M › 翻页(对齐 OM Computer 面板收纳); 纯展示层, 事件数据/签名指纹/去重归属零改动
      let cur_=idxs[idxs.length-1];
      if(run){for(let k=idxs.length-1;k>=0;k--)if(evs[idxs[k]].status==='running'){cur_=idxs[k];break}}
      else for(let k=idxs.length-1;k>=0;k--)if(evs[idxs[k]].status==='error'){cur_=idxs[k];break}
      const _live=run&&evs[cur_]===last&&last.status==='running';
      let _dd=false;try{_dd=evs[cur_].status!=='error'&&c._sdText!=null&&_sdJoin(_twTitle(evs[cur_]))===c._sdText}catch(e){}   // 去重(Boss 2026-08-03 方案A 工具行让位): 步头 .ssd 与本行同文(与 STEPLABEL 完全同源的 _sdJoin(_twTitle) 比较, 零口径漂移)→行内只留图标/spinner/×N/耗时; 错误行不去重(红字副文是信息本体); 首拍 _sdText 未写靠下一拍自愈(既有先例)
      host.classList.toggle('twdedup',_dd);
      const _sig=run+''+cur_+''+idxs.map(i=>{const e=evs[i];return e.seq+':'+e.status+':'+(e.t_end||'')+':'+String(e.input_summary||'').length+':'+String(e.result_summary||'').length+':'+String(e.error||'').length}).join(',')+'|N'+evs.length+'|D'+(_dd?1:0);   // F3.1: 稳定指纹(不含 live 秒数); 截断字段长度参与→详情弹层闭包不吃陈旧快照; running 耗时改由 _twLiveTick 只改 .twdu 文本(对齐钉底 .tld)
      if(!window.GA_RENDER_FULL&&host._twSig===_sig)return;   // 该步工具条零变化 → 零 DOM 变更/零重绑(耗时秒数不进签名 → 不再每秒整刷)
      host._twSig=_sig;
      host.innerHTML=_twRow(evs[cur_],cur_,_live,run,idxs.length);   // live 行播种初始耗时文本(.twdu:empty 会隐藏空占位)
      host.querySelectorAll('.twr').forEach(r=>{r.onclick=(ev)=>{ev.stopPropagation();toolDetail(evs,+r.dataset.i,run)}})})}
  _twLiveBar(evs,j)}
let _twLiveEl=null;
function _twLiveBar(evs,j){                                  // C: 钉底条, #comp 内部首子节点(--kb 平移/--compH 追踪免费, #009 必修 3)
  const last=evs&&evs.length?evs[evs.length-1]:null;
  const show=!!(j&&j.running)&&last&&last.status==='running';
  if(!show){if(_twLiveEl){_twLiveEl.style.display='none';_twLiveEl._e=null}return}
  if(!_twLiveEl){const comp=document.getElementById('comp');if(!comp)return;
    _twLiveEl=document.createElement('div');_twLiveEl.id='twLive';
    _twLiveEl.onclick=()=>{const b=twState.box;if(!b)return;const cs=b.querySelectorAll('.step');const c=cs[cs.length-1];if(!c)return;
      try{if(!window.GA_STEPFOLD_OFF){const f=c.closest('.stepsFold');if(f&&!f.classList.contains('open'))f.classList.add('open')}}catch(e){}   // STEP_FOLD §2.5 保险丝(R10): 目标步若在收起容器内先展开再滚(终态折叠与运行态钉底条本已错峰)
      try{c.scrollIntoView({block:'center',behavior:'smooth'})}catch(e){c.scrollIntoView()}};
    comp.insertBefore(_twLiveEl,comp.firstChild)}
  const ti=_twTitle(last);
  const tis=ti.plain?_twLine(ti.s,24):ti.s;   // H4: 钉底条 cap 24 仅 humanize 命中路径生效(plain 仅 humanize 产出 → GA_HUMANIZE_OFF/未命中维持现状)
  if(_twLiveEl.style.display!=='flex')_twLiveEl.style.display='flex';
  _twLiveEl._e=last;   // 引用每拍更新(耗时计算基准), 但 DOM 只在签名变化时重写
  const _sig=ti.t+'|'+tis+'|'+(last.turn||'?')+'|'+(last.seq||'')+'|'+String(last.gen);   // F3.1: 同一事件同标题 → 不重写(耗时数字由 _twLiveTick 只改 .tld 文本)
  if(!window.GA_RENDER_FULL&&_twLiveEl._sig===_sig)return;
  _twLiveEl._sig=_sig;
  _twLiveEl.innerHTML='<span class="twspin"></span><span class="tlt">'+_twEsc(ti.t+(tis?'：'+tis:''))+'</span>'
    +'<span class="tls">'+_twEsc(t('stepLabel')+' '+(last.turn||'?')+' · ')+'<span class="tld">'+_twEsc(_twDur(last,true))+'</span></span>'}
function _twLiveTick(){   // 挂 liveTick(500ms), 不另起定时器: 钉底 .tld + 步内 running .twdu 同拍只改 textContent
  if(_twLiveEl&&_twLiveEl._e&&_twLiveEl.style.display!=='none'){const d=_twLiveEl.querySelector('.tld');if(d)d.textContent=_twDur(_twLiveEl._e,true)}
  try{if(twState&&twState.run&&twState.box&&twState.evs){const last=twState.evs[twState.evs.length-1];
    twState.box.querySelectorAll('.tsr .twr').forEach(r=>{const e=twState.evs[+r.dataset.i];if(!e||e.status!=='running')return;
      const d=r.querySelector('.twdu');if(d)d.textContent=_twDur(e,e===last)})}}catch(e){}}
/* ════════ F4 浏览器证据链(参观层, PLAN_FRONTEND_CATCHUP v1.2 §3-F4): 只消费 P4 扩展字段(phase/url/title/action/step_i/n/screenshot_id),
   老载荷(无 phase)零动作; 截图走既有产物通道(_fileUrl/openFilePreview), 不新增任何桥/工具; 事件数据只读不回写 ════════ */
const _BW_PH={navigating:['🧭','bwPhNav'],loaded:['🌐','bwPhLoaded'],acting:['👆','bwPhActing'],verifying:['🔍','bwPhVerify'],done:['✓','bwPhDone'],blocked:['🚧','bwPhBlocked'],error:['✗','bwPhError']};
const _BW_FAIL={timeout:['⏱️','bwfTimeout'],crash:['💥','bwfCrash'],notfound:['🔍','bwfNotFound'],login:['🔐','bwfLogin'],paywall:['💳','bwfPaywall'],agewall:['🔞','bwfAgeWall']};
function _bwIs(e){return !!(e&&typeof e==='object'&&e.phase!=null&&e.phase!=='')}
function _bwPh(ph){const m=_BW_PH[String(ph||'').toLowerCase()];return m?{i:m[0],l:t(m[1])}:{i:'·',l:String(ph||'')}}   // 未知 phase 兜底原文, 不阻塞
function _bwShotRel(p){p=String(p==null?'':p);const i=p.lastIndexOf('/temp/');return i<0?null:(p.slice(i+6)||null)}   // screenshot_id=既有 side-effect png 绝对路径 → temp 相对路径(产物通道契约); 无 /temp/ 段=取不到 → 降级 null
function _bwFailKind(e){                                     // F4.3 失败枚举分类: error/result_summary/url 文本启发式; 未命中回 '' 用通用失败文案
  const s=(String(e.error||'')+' '+String(e.result_summary||'')+' '+String(e.url||'')).toLowerCase();
  if(/timeout|timed[ -]?out|超时/.test(s))return'timeout';
  if(/crash|disconnect|tab closed|session closed|target closed|崩溃|连接断开/.test(s))return'crash';
  if(/not[ -]?found|no such element|unable to locate|未找到|找不到/.test(s))return'notfound';
  if(/login|log[ -]?in|sign[ -]?in|signin|authenticat|登录/.test(s))return'login';
  if(/paywall|subscri|premium|付费|会员|订阅/.test(s))return'paywall';
  if(/age[ -]?(gate|wall|verif|check|restrict)|18\+|adult only|年龄|未成年/.test(s))return'agewall';
  return''}
function _bwSection(evs,i){                                  // 详情弹层浏览器区块: 元信息行 + 失败横幅(F4.3) + 缩略图(F4.2, 上限3) + 逐跳时间线(F4.1)
  const e=evs[i];if(!_bwIs(e))return'';                      // 老载荷/非浏览器事件 → 空串零动作
  const hops=[];evs.forEach((h,k)=>{if(_bwIs(h))hops.push(k)});
  const ph=_bwPh(e.phase);
  let h='<div class="bwm"><span class="bwph '+_twEsc(String(e.phase).toLowerCase())+'">'+ph.i+' '+_twEsc(ph.l)+'</span>'
    +(e.action?'<span class="bwac">'+_twEsc(_twLine(e.action,24))+'</span>':'')
    +((+e.step_i&&+e.n)?'<span class="bwst">'+_twEsc(t('stepLabel'))+' '+(+e.step_i)+'/'+(+e.n)+'</span>':'')+'</div>';
  if(e.title||e.url)h+='<div class="bwu">'+(e.title?'<b>'+_twEsc(_twLine(e.title,48))+'</b> ':'')+(e.url?'<span>'+_twEsc(_twLine(e.url,140))+'</span>':'')+'</div>';
  const fail=e.status==='error'||/^(blocked|error)$/.test(String(e.phase).toLowerCase());
  if(fail){const fi=_BW_FAIL[_bwFailKind(e)];               // F4.3: 命中枚举给人话+图标; 未命中回通用失败; screenshot 有无均不阻塞本横幅
    h+='<div class="bwfail">'+(fi?fi[0]+' <b>'+_twEsc(t(fi[1]))+'</b>':'✗ <b>'+_twEsc(t('twFailed'))+'</b>')+'<span>'+_twEsc(_twResult(e))+'</span></div>'}
  let rels=[];hops.forEach(k=>{const r=_bwShotRel(evs[k].screenshot_id);if(r&&rels.indexOf(r)<0)rels.push(r)});
  const own=_bwShotRel(e.screenshot_id);
  rels=rels.slice(-3);                                       // 默认上限 3 张(契约); 尾 3 = 最新证据, 失败终态天然含 last_screenshot
  if(own&&rels.indexOf(own)<0)rels[rels.length-1]=own;       // 当前跳自有截图必展示
  if(rels.length)h+='<div class="bwshots">'+rels.map(r=>'<img class="bwshot'+(r===own?' cur':'')+'" alt="" src="'+_fileUrl(r)+'" data-rel="'+_twEsc(r)+'" onerror="this.style.display=\'none\'">').join('')+'</div>';   // 文件已清理 → 静默隐藏(降级=只显时间线)
  if(hops.length)h+='<div class="bwtlh">'+_twEsc(t('bwTrail'))+'</div><div class="bwtl ga-card">'
    +hops.map(k=>{const hv=evs[k],hp=_bwPh(hv.phase),he=hv.status==='error'||/^(blocked|error)$/.test(String(hv.phase).toLowerCase());
      return '<div class="bwhop'+(k===i?' cur':'')+(he?' err':'')+'" data-i="'+k+'">'
        +'<span class="bwhi">'+hp.i+'</span><span class="bwhl">'+_twEsc(hp.l)+'</span>'
        +'<span class="bwhn">'+_twEsc(_twLine(String(hv.action||hv.name||''),18))+'</span>'
        +'<span class="bwhu">'+_twEsc(_twLine(String(hv.title||'').trim()||String(hv.url||'').replace(/^https?:\/\//,''),48))+'</span>'
        +'<span class="twdu">'+_twEsc(_twDur(hv,false))+'</span></div>'}).join('')+'</div>';
  return h}
function toolDetail(evs,i,run){                              // D: 详情翻页(对齐 OM N/M); gaModal 整卡重写 ⇒ 翻页=重调自身
  if(!Array.isArray(evs)){evs=[evs];i=0}                     // 兼容单事件调用
  i=Math.max(0,Math.min(evs.length-1,+i||0));const e=evs[i];if(!e)return;
  const ti=_twTitle(e),a=_twParse(e.input_summary),r=_twParse(e.result_summary);
  const st=e.status==='running'?(run?t('twRunning'):t('twAborted')):e.status;
  const inTxt=(a.script!=null&&String(a.script))||(e.input_summary||'—');            // script 展示原文(截断件), 不是 JSON 转义串
  const outTxt=e.status==='running'?'':((r.stdout!=null&&String(r.stdout).trim())?String(r.stdout):(e.result_summary||'—'));
  const useRR=!window.GA_RENDER_LEGACY&&window.renderRich;                           // F1.2: In/Out/error 统一过 renderRich(tool)=decorateCode 全路径(高亮+复制+横滚); legacy 保旧 _twEsc pre
  const seg=(txt)=>useRR?'<div class="twdrr"></div>':('<pre>'+_twEsc(txt)+'</pre>');
  const html='<div class="twd"><div class="twmeta"><b>'+_twEsc(st)+'</b> · '+_twEsc(_twDur(e,false)||'')+(e.turn?(' · '+_twEsc(t('stepLabel')+' '+e.turn)):'')+'</div>'
    +_bwSection(evs,i)                                                               // F4: 浏览器证据链区块(非浏览器事件/老载荷=空串零动作)
    +'<div><b>'+_twEsc(t('twIn'))+'</b></div>'+seg(inTxt)
    +(outTxt?('<div><b>'+_twEsc(t('twOut'))+'</b></div>'+seg(outTxt)):'')
    +(e.error?('<div><b>error</b></div>'+seg(e.error)):'')
    +(evs.length>1?('<div class="twpgr"><button class="twpg" data-d="-1"'+(i<=0?' disabled':'')+'>‹</button><span>'+(i+1)+' / '+evs.length+'</span><button class="twpg" data-d="1"'+(i>=evs.length-1?' disabled':'')+'>›</button></div>'):'')+'</div>';
  gaModal({title:'🛠️ '+ti.t+(ti.s?'：'+_twLine(ti.s,28):''),html:html,okText:t('copy'),
    onOk:()=>copyText((e.name||'')+'\n'+t('twIn')+': '+(e.input_summary||'')+'\n'+t('twOut')+': '+(e.result_summary||''),()=>toast(t('copied')))});   // 存档/复制链路语义不变(v3.2)
  const card=$('modalCard');
  if(useRR){const ty=String(a.type||'').toLowerCase();
    const langIn=(a.script!=null)?(ty==='python'?'python':(ty==='sh'?'bash':'')):'';   // code_run 脚本给语言提示; stdout/error 留 hljs 自动检测
    const vals=[[inTxt,langIn]];if(outTxt)vals.push([outTxt,'']);if(e.error)vals.push([String(e.error),'']);
    card.querySelectorAll('.twd .twdrr').forEach((n,k)=>{if(vals[k])n.appendChild(renderRich(vals[k][0],{mode:'tool',lang:vals[k][1]}))})}
  card.querySelectorAll('.twpg').forEach(b=>{b.onclick=(ev)=>{ev.stopPropagation();toolDetail(evs,i+(+b.dataset.d),run)}});
  card.querySelectorAll('.bwhop').forEach(b=>{b.onclick=(ev)=>{ev.stopPropagation();toolDetail(evs,+b.dataset.i,run)}});                       // F4.1: 点跳行=切详情(同翻页语义)
  card.querySelectorAll('.bwshot').forEach(im=>{im.onclick=(ev)=>{ev.stopPropagation();openFilePreview(_enc(im.dataset.rel||''))}})}          // F4.2: 点缩略图=既有产物预览通道开原图
function render(j){
  if(_abortWaitCid!=null){   // T7: 用户已请求中止、等后端收敛的窗口
    const acid=String((j&&(j.active_convo||j.cid))||'');
    if(j&&j.running&&!j.notif_pending&&acid===String(_abortWaitCid)){try{bridgeAbort(_abortWaitCid)}catch(e){}return}   // abort 异步/可能丢包: 后端仍报该会话在跑 → 补刀一次并整拍短路, 绝不让"发现后台任务"分支(下方)复活它/重复补插 user 气泡
    if(!j||!j.running||acid!==String(_abortWaitCid))_abortWaitCid=null;   // 后端已停 / 焦点已切到别会话 → 解除等待, 放行正常渲染
  }
  // P3c 串台三防护之一: multi 时 payload.cid 必须对上焦点/活体 box(notif_pending 先允许进分支以切到专属会话)
  if(multi&&j&&j.cid!=null&&!j.notif_pending){
    const expect=(curConvo&&curConvo.id)||(runConvo&&runConvo.id)||activeCid;
    if(expect&&String(j.cid)!==String(expect))return;
    if(task&&task.box&&task.box._cid&&String(j.cid)!==String(task.box._cid))return;
    if(task&&task._cid&&String(j.cid)!==String(task._cid))return;
  }
  try{renderTools(j)}catch(e){}   // 工具条: 无条件消费(含空闲 poll 的终态), 失败静默不拖渲染主链
  try{citeCollect(j)}catch(e){}   // D2 §3.2.1: 引用增量累积(独立 try/catch, 不改 renderTools 本体; 归属判据在函数内)
  // 通知/闹钟触发: 后台命中时自动切换到专属会话(首次自动创建)
  if(j.notif_pending){const cid=j.notif_pending.cid,app=j.notif_pending.app||'';let c=convos.find(x=>x.id===cid);
    if(!c){c={id:cid,title:(app==='闹钟'?'⏰ ':'['+t('notif')+'] ')+app+(j.prompt?(' · '+(j.prompt||'').slice(0,40)):''),ts:Date.now(),msgs:[]};convos.push(c);saveConvos()}
    // P3d: multi 且焦点已在别会话 → 只登记 runs/徽标, 不强制劫持 UI; legacy 仍自动切
    const focusElse=multi&&curConvo&&String(curConvo.id)!==String(cid);
    if(focusElse){if(j.running){const rr=ensureRun(cid);rr.running=true;running=anyRunning();try{renderDrawer()}catch(e){}}
      else try{renderDrawer()}catch(e){}}
    else if(j.running){curConvo=c;runConvo=c;startNew=false;renderConvo(c);setHeaderTitle();closeSheets();renderDrawer()}  // 后台已在跑: 勿 /convo(会 busy), 只绑 UI
    else if(switchConvo(c)){curConvo=c;startNew=false;renderConvo(c);restoreAsk(c);setHeaderTitle();closeSheets();renderDrawer()}}
  // 空闲 UI 发现后台 call_once/notif 已 running: multi 焦点别处 → 只徽标不劫持; 否则接成前台任务视图
  if(j.running&&!running&&j.active_convo){let c=convos.find(x=>x.id===j.active_convo);
    if(!c){c={id:j.active_convo,title:(j.prompt||t('newChat')).slice(0,60),ts:Date.now(),msgs:[]};convos.push(c);saveConvos()}
    const focusElse=multi&&curConvo&&String(curConvo.id)!==String(j.active_convo);
    if(focusElse){const rr=ensureRun(j.active_convo);rr.running=true;running=anyRunning();try{renderDrawer()}catch(e){}}
    else{curConvo=c;runConvo=c;startNew=false;
    const ms=c.msgs||(c.msgs=[]);
    if(!(ms.length&&ms[ms.length-1].role==='user'&&ms[ms.length-1].text===j.prompt)&&j.prompt){const um={role:'user',text:j.prompt,ts:Date.now()};ms.push(um);if(curConvo===c)userBubble(j.prompt,null,um.ts,um)}
    newTask(j.prompt);task.snap=_filesSnap();(j.steps||[]).forEach(setStep);setRunning(true, c&&c.id);setStatus(j.status||'',true);renderDrawer();setHeaderTitle();pinReplyTop(task.box)}}
  const ownRun=!(running&&runConvo&&j.active_convo&&j.active_convo!==runConvo.id);
  if(ownRun&&!replaying&&j.running&&task&&task.done&&!task._fail&&(!j.cid||!task._cid||String(j.cid)===String(task._cid))){   // 自愈: 后端明说本会话在跑而 task 被误标 done(过期/错位拍误 finish)→ 复活, 否则 startLive 的 done 守卫把 spin/计时永久杀死而步骤照常渲染
    task.done=false;if(task.state){task.state.innerHTML='';task.state.classList.add('run')}
    runConvo=convos.find(x=>x.id===task._cid)||runConvo||curConvo;
    setRunning(true,task._cid||(curConvo&&curConvo.id))}
  if(ownRun&&task&&!replaying&&!task.done&&j.gen!=null){   // F3.1 代际键控: 首见 gen 认养(补齐既有卡键); gen 变化=后端同 task 重开新代(乱序/重入的硬边界)→ 整表重建兜底, 其余拍走键控 diff
    if(task._gen==null){task._gen=j.gen;task.steps.forEach((c,i)=>{if(c.dataset)c.dataset.gk=j.gen+':'+(i+1)})}
    else if(String(task._gen)!==String(j.gen)){
      task.steps.forEach(c=>{try{c.remove()}catch(e){}});task.steps=[];task._gen=j.gen;   // 步骤全量重建(本拍 j.steps 即刻重挂); 工具条按新 gen 过滤, 下一拍自动归位(首拍不落位次拍归位先例)
      twState={gen:null,box:null,evs:[]}}}
  if(task&&ownRun)(j.steps||[]).forEach(setStep);
  if(ownRun&&isAuto()&&j.route){applyRoute(j.route);                                                  // 助手头显示实际路由的服务商模型(品牌 logo + 型号)
    if(running)setStatus(autoLabel()+' · '+(dispModel(j.route.model)||j.route.name||''),true)}         // 顶栏副标题实时显示"当前路由到哪"
  if(ownRun&&typeof j.tok_in==='number'&&j.tok_in)runStats.tokIn=j.tok_in;     // 后端真实输入 token
  if(ownRun&&typeof j.tok_out==='number'&&j.tok_out)runStats.tokOut=j.tok_out; // 输出 token(claude 流式为 0 → liveTick 按文本估算补足)
  if(ownRun&&typeof j.cache_read==='number')runStats.cacheRead=j.cache_read;   // #4: 本轮缓存读取/创建 token(可为 0, 不加非零守卫)
  if(ownRun&&typeof j.cache_write==='number')runStats.cacheWrite=j.cache_write;
  if(ownRun&&j.cmd_error){bubble('sys',j.cmd_error);stopRunClean()}  // 切模型失败: 提示 + 干净中止复位(stopRunClean 单一真相源; 否则按钮卡停止态、"切个模型啥都没反应")
  if(!j.running&&running&&(!j.cid||!(task&&task._cid)||String(j.cid)===String(task._cid))){const wasLive=curConvo===runConvo,rc=runConvo;   // 收尾前先记归属(setRunning 会清 runConvo): 预览态下瞬时 DOM 只进运行会话视图(T6); cid 归属守卫: 别会话的 running:false 拍(legacy 后台通知/闹钟切走后端焦点)不得误 finish 本任务
    if(task&&!task.done){if(ownRun&&!task.steps.length&&j.final){setStep({n:1,summary:(j.final||'').slice(0,80),text:j.final});task._fail=1;GAT.emit('task_error',{cat:GAT.errCat(j.final),msg:GAT.errMsg(j.final),hasKey:GAT.hasKey()})}finish();GAT.emit('task_done',{ok:task.steps.length>0,steps:task.steps.length,secs:task.t0?Math.round((Date.now()-task.t0)/1000):-1})}  // 无步骤但有 final(常是报错): 显示出来, 不再"回复为空"; secs=任务时长(webui 口径, 与 agent_task_end.secs 互证)
    setRunning(false, rc&&rc.id);setStatus(modelLabel(),false);
    if(ownRun&&j.ask&&(j.ask.question||(j.ask.candidates&&j.ask.candidates.length))){if(wasLive)renderAskPicker(j.ask);else pendingAsk={cid:rc&&rc.id,ask:j.ask};if(!replaying&&!window._gaAnswering)onNeedInput(rc)}   // ask_user 退出 → 选择框(预览中不画进别会话, 存 pendingAsk 兜底——后端 ask 会被后续 /convo 切换清掉) + "需操作"提醒(issue#5)
    else if(!replaying)onTaskDone(wasLive,rc)}                                                                                    // 真完成 → 完成提示音 + 普通通知(issue#5)
  else if(!running)setStatus(j.status,j.running);   // 运行态由 liveTick 接管 header(gerund+计时); 仅非运行态用 poll 状态
  if(!running||curConvo===runConvo)scroll()}   // 预览别会话时不钉底: 700ms poll 每 tick 都会走到这, 贴底带内(stick=true)的慢滑用户会被循环拽回(与 gaOnResume 同门控)
function setRunning(r, cid){   // P3b: multi 时第二参=目标 cid; 全局 running=anyRunning(); 按钮跟焦点
  if(multi){const id=cid||(curConvo&&curConvo.id)||(runConvo&&runConvo.id)||activeCid;
    if(id){const rr=ensureRun(id);rr.running=!!r;if(r){rr.task=task;runConvo=convos.find(x=>x.id===id)||runConvo||curConvo;activeCid=id}else{if(rr.task===task)rr.task=null;if(runConvo&&runConvo.id===id){/* keep runConvo until all done */}}}
    running=anyRunning();
    if(!running)runConvo=null;
    const fr=focusRunning();
    btn.innerHTML=fr?ICON_STOP:ICON_SEND;btn.classList.toggle('stop',fr);btn.setAttribute('aria-label',fr?t('stopBtn'):t('sendBtn'));
    try{GA.keepAwake(running&&keepAwake)}catch(e){}
    if(fr)startLive();else stopLive();
    if(running&&!timer)timer=setInterval(poll,700);if(!running&&timer){clearInterval(timer);timer=null}
    applySendEnabled();updateScrollNav();return}
  running=r;if(!r)runConvo=null;   // legacy: 运行归属(T2)与 running 同生命周期, 单写者
  btn.innerHTML=r?ICON_STOP:ICON_SEND;btn.classList.toggle('stop',r);btn.setAttribute('aria-label',r?t('stopBtn'):t('sendBtn'));
  try{GA.keepAwake(r&&keepAwake)}catch(e){}   // 模型运行中且开关开 → 阻止息屏; 结束/关开关 → 清 flag 恢复系统超时
  if(r)startLive();else stopLive();
  if(r&&!timer)timer=setInterval(poll,700);if(!r&&timer){clearInterval(timer);timer=null}
  applySendEnabled();updateScrollNav()}   // 运行起止内容高度变化→刷新滚动导航显隐
function poll(){
  // P3c: multi → pollAll 摘要刷新 runs + 仅 curConvo pollC 详情; legacy → GA.poll
  if(multi){
    try{
      const rawA=bridgePollAll();
      if(rawA!=null&&rawA!==''){
        const parsed=parseBridge(rawA);
        const sessions=Array.isArray(parsed)?parsed:((parsed&&parsed.sessions)||[]);
        let badgeDirty=false;
        for(let i=0;i<sessions.length;i++){
          const s=sessions[i];if(!s||s.cid==null)continue;
          const id=String(s.cid);const rr=ensureRun(id);const was=!!rr.running;
          rr.running=!!s.running;if(typeof s.gen!=='undefined')rr.gen=s.gen;if(s.ask)rr.ask=s.ask;
          if(was!==rr.running)badgeDirty=true;
          if(was&&!rr.running&&(!curConvo||String(curConvo.id)!==id)){   // P3d: 后台结束 → toast 不切焦点; 清该 run task
            rr.task=null;
            try{const cc=convos.find(x=>String(x.id)===id);toast(t('t_bgDone')+(cc?(' · '+(cc.name||cc.title||id).slice(0,24)):''))}catch(e){}
            try{playDone()}catch(e){}
          }
        }
        running=anyRunning();
        if(running&&!timer)timer=setInterval(poll,700);if(!running&&timer){clearInterval(timer);timer=null}
        const fr=focusRunning();
        btn.innerHTML=fr?ICON_STOP:ICON_SEND;btn.classList.toggle('stop',fr);btn.setAttribute('aria-label',fr?t('stopBtn'):t('sendBtn'));
        try{GA.keepAwake(running&&keepAwake)}catch(e){}
        if(fr){if(!runStats.live)startLive()}else stopLive();   // 焦点未跑即停表摘 spin(不只 !running); startLive 边沿幂等, 禁每拍重置 t0/tok
        applySendEnabled();
        if(badgeDirty)try{renderDrawer()}catch(e){}   // P3d: 徽标状态变 → 刷抽屉
      }
    }catch(e){}
    const cid=(curConvo&&curConvo.id)||activeCid;if(!cid)return;
    const rr=ensureRun(cid);
    // 焦点 run 的私有 task 优先(N 活体 box); 否则用全局 task(本会话)
    if(rr.task&&(!task||(task._cid&&String(task._cid)!==String(cid)))){task=rr.task;runConvo=convos.find(x=>x.id===cid)||runConvo}
    else if(task&&curConvo&&String(curConvo.id)===String(cid)&&!rr.task){rr.task=task;if(task.box&&!task.box._cid)task.box._cid=cid;task._cid=cid}
    const since=task&&String((task._cid||(task.box&&task.box._cid)||cid))===String(cid)?Math.max(0,task.steps.length-1):(rr.sinceCursor||0);
    const raw=bridgePoll(cid, since);if(!raw)return;
    const j=parseBridge(raw);if(!j)return;
    if(j.error)return;   // poll2 未知 cid
    if(j.cid!=null&&String(j.cid)!==String(cid))return;   // 串台防护: 回显 cid 不符即丢
    if(task&&task.box&&task.box._cid&&j.cid!=null&&String(j.cid)!==String(task.box._cid))return;
    render(j);
    if(typeof j.nsteps==='number')rr.sinceCursor=j.nsteps;
    rr.running=!!j.running;if(!j.running){if(rr.task===task)rr.task=null}
    running=anyRunning();
    return;
  }
  const since=task?Math.max(0,task.steps.length-1):0;const raw=GA.poll(since);if(!raw)return;render(JSON.parse(raw))
}
// 空闲也低频 poll: 消费 notif_pending / 发现后台 call_once(否则只有用户发消息才轮询, 闹钟会话永远不进抽屉 UI)
if(!window._gaIdlePoll)window._gaIdlePoll=setInterval(()=>{if(!timer)try{poll()}catch(e){}},2000);
let pendingAtts=[];
/* 重试/编辑: 截断该轮(含其后所有轮)+ /rollback 真正从 LLM 上下文剔除, 而非把新输入 append 到旧上下文(issue#1) */
function retryTask(taskObj){if(replaying||!taskObj)return;if(anyRunning()){toast(t('t_taskBusy'));return}const prompt=taskObj.prompt,m=taskObj.msg;   // P3d: anyRunning 冻结截断+回滚
  try{GAT.emit('chat_action',{act:'regen'})}catch(e){}   // 头条功能(v2.6.x)埋点: 重新执行(从 assistant 气泡, 截断本轮+回滚上下文后原样重发)
  if(curConvo&&m){const idx=curConvo.msgs.indexOf(m);
    if(idx>=0){let start=idx;if(start>0&&curConvo.msgs[start-1].role==='user')start--;   // 连同对应 user 轮一起截断
      const _u=curConvo.msgs[start],_atts=(_u&&_u.role==='user'&&_u.atts)?_u.atts.slice():[];   // 重发保留该 user 轮的附件(issue#3)
      const removed=curConvo.msgs.slice(start).filter(x=>x.role==='user').length;   // 回滚 n=被删用户轮数(与后端 bh 内容锚点一一对应)
      if(!switchConvo(curConvo))return;   // 先把后端对齐到本会话(根治: 不靠 liveConvoId 猜; 跨会话/冷启/切模型都精确落到本会话 bh)。切不过去(后端忙)则整体放弃、不截断 UI → 删除集≡读写集(前后端一致), switchConvo 已 toast busy
      curConvo.msgs.length=start;saveConvos();
      if(removed>0){try{GA.send('/rollback '+removed)}catch(e){}}
      renderConvo(curConvo);pendingAtts=_atts;renderAttachRow()}}
  toast(t('t_retried'));if(prompt)startTask(prompt)}
function editMsg(m){if(replaying)return;if(anyRunning()){toast(t('t_taskBusy'));return}   // P3d
  try{GAT.emit('chat_action',{act:'edit'})}catch(e){}   // 头条功能(v2.6.x)埋点: 编辑此消息(截断该轮+回滚上下文 → 回填输入框待改后重发)
  if(curConvo&&m&&m.text!=null){const idx=curConvo.msgs.indexOf(m);
    if(idx>=0){const removed=curConvo.msgs.slice(idx).filter(x=>x.role==='user').length,text=m.text;   // 回滚 n=被删用户轮数
      if(!switchConvo(curConvo))return;   // 对齐后端到本会话(见 retryTask); 切不过去(后端忙)则放弃、不截断 UI 保前后端一致
      curConvo.msgs.length=idx;saveConvos();
      if(removed>0){try{GA.send('/rollback '+removed)}catch(e){}}
      renderConvo(curConvo);
      pendingAtts=(m.atts||[]).slice();renderAttachRow();   // 恢复该轮已上传的图片/附件(issue#3): 编辑重发不丢图
      inp.value=text;inp.dispatchEvent(new Event('input'));inp.focus();scroll(1);toast(t('t_edited'));return}}
  if(m&&m.text!=null){pendingAtts=(m.atts||[]).slice();renderAttachRow();inp.value=m.text;inp.dispatchEvent(new Event('input'));inp.focus()}}   // 兜底: 填输入框并恢复附件
/* 用户气泡「重试」: 与 editMsg 同样截断该轮+回滚, 但不进输入框, 直接把原输入重新发送(issue#4) */
function retryUserMsg(m){if(replaying||!m||m.text==null)return;if(anyRunning()){toast(t('t_taskBusy'));return}const text=m.text;   // P3d
  try{GAT.emit('chat_action',{act:'retry'})}catch(e){}   // 头条功能(v2.6.x)埋点: 用户气泡「重试」(截断该轮+回滚, 不进输入框直接原样重发)
  if(curConvo){const idx=curConvo.msgs.indexOf(m);
    if(idx>=0){const removed=curConvo.msgs.slice(idx).filter(x=>x.role==='user').length;   // 回滚 n=被删用户轮数
      if(!switchConvo(curConvo))return;   // 对齐后端到本会话(见 retryTask); 切不过去(后端忙)则放弃、不截断 UI 保前后端一致
      curConvo.msgs.length=idx;saveConvos();
      if(removed>0){try{GA.send('/rollback '+removed)}catch(e){}}
      renderConvo(curConvo)}}
  pendingAtts=(m.atts||[]).slice();renderAttachRow();   // 重试同样保留该轮附件(issue#3)
  toast(t('t_retried'));startTask(text)}
function startTask(text,override){   // override!=null: 隐藏 payload(气泡/存储只留 text 简短标签, 实际发 override) — 复用于演化融合等"显示≠payload"场景
  if(multi){const _id=(curConvo&&curConvo.id)||activeCid;if(_id&&runs.get(_id)&&runs.get(_id).running){toast(t('t_taskBusy'));return false}}   // multi: 仅拦「本会话已在飞」; 允许其它 cid 并行
  else if(running){toast(t('t_taskBusy'));return false}   // legacy 单任务不变量收口
  if(override==null&&typeof text==='string'){const lm=text.trim().match(/^\/lang\b\s*(\S*)/i);if(lm){setLang(/^en/i.test(lm[1])?'en':'zh');return false}}   // /lang=纯控制命令(切语言): 所有提交路径(发送/编辑重发/重试)的唯一咽喉, 在此拦截→不入会话存储/气泡/模型上下文/model_responses; 与设置语言开关同走 setLang(单一真相源)。trim 与 _stripLangMsgs 谓词一致
  if(!providers.length){bubble('sys',t('noProvider'));openProviders();return false}   // 无服务商: 不发后端(否则后端 0 LLM 直接回错误串), 直接引导去配置面板
  const hasOv=override!=null, atts=hasOv?[]:pendingAtts.slice();
  if(!hasOv){pendingAtts=[];renderAttachRow()}
  let payload=hasOv?override:text;
  if(!hasOv){
    if(atts.length){const refs=atts.map(a=>`[${a.name}: ${a.path}]`).join('\n');payload=refs+'\n\n'+(text||t('attView'))}
    if(goalArmed){payload=(lang==='en'?GOAL_PROMPT.en:GOAL_PROMPT.zh)+payload;goalArmed=false}   // Goal 模式: 隐式前置 SOP 提示词(气泡只显示用户目标)
  }
  if(!ensureConvo(text))return false;   // 后端在飞任务未停下(busy)→不发, 防发进未切上下文(已 toast)
  const _um={role:'user',text:text||t('attLabel'),atts,ts:Date.now()};curConvo.msgs.push(_um);
  const _ub=userBubble(text||t('attLabel'),atts,_um.ts,_um);saveConvos();   // 传 msg 引用 → 编辑/重试可定位该轮
  const _snap=_filesSnap();   // 发送前快照生成文件(mtime+size): finish 差分出本轮产物行(file_write 外的 code_run 产物也能捕获)
  const _cid=(curConvo&&curConvo.id)||activeCid;activeCid=_cid||activeCid;
  const r=bridgeSend(_cid, payload);if(r){bubble('sys',r);GAT.emit('send_blocked',{cat:GAT.errCat(r),msg:GAT.errMsg(r),hasKey:GAT.hasKey()});return false}
  GAT.emit('message_sent',{hasKey:GAT.hasKey(),atts:atts.length,voice:!!window._gaVoiceIn});window._gaVoiceIn=0;   // 语义步骤: 消息已成功发出(不含内容); voice=本条输入有语音识别贡献(voice.js 置位, 发出即清)
  document.querySelectorAll('.askBox:not(.answered)').forEach(b=>b.remove());_askKey=null;   // 新一轮已发出: 作废上一轮未答的 ask 选择框(手动发文本=对该 ask 的自由作答), 防陈旧框抑制新 picker/被迟到点击并发
  if(pendingAsk&&curConvo&&pendingAsk.cid===curConvo.id)pendingAsk=null;   // 兜底件按归属作废: 只有在 ask 归属会话内发消息才算作答/接替; 在别的会话发消息不销毁它(后端 ask 已被切换清掉, 前端副本是唯一存活渠道)
  _abortWaitCid=null;   // T7: 用户已发新一轮 → 新意图取代上一次中止等待(即便上个任务后端尚未收敛, 也让本轮正常渲染)
  newTask(text||t('attTask'));task.snap=_snap;setRunning(true,_cid);setStatus(modelLabel(),true);
  // 发送后顶置本轮: 锚=用户气泡行(问题一两行留在顶部, 回复紧随其下, ChatGPT 同款), stick=false → 流式/键盘 resize 不再追底; 要看末尾用右下「回底」钮
  pinReplyTop((_ub&&_ub.parentNode)||task.box);return true}
function submit(){if(window.GAVoice)GAVoice.stop();   // 发送/中止前先关麦克风: 录音态点发送不该让语音继续开着
  const v=inp.value.trim();if(multi?focusRunning():running){try{const _st=(task&&task.steps)?task.steps.length:0;   // 中止上下文
    GAT.emit('task_aborted',{steps:_st,elapsed_s:task&&task.t0?Math.round((Date.now()-task.t0)/1000):-1,had_output:_st>0||!!(task&&task.msg&&task.msg.final)})}catch(e){};stopRunClean();toast(t('t_stopped'));return}   // multi: 只停焦点; legacy: 全停
  if(!v&&!pendingAtts.length)return;inp.value='';inp.style.height='auto';startTask(v)}   // /lang 命令在 startTask 唯一咽喉处拦截
btn.onclick=submit;
inp.addEventListener('input',()=>{inp.style.height='auto';inp.style.height=Math.max(26,Math.min(inp.scrollHeight,140))+'px';applySendEnabled()});

/* ════════════ 附件 ════════════ */
const MAX_UPLOAD=10*1024*1024;
function openAttachSheet(){openSheet('attachSheet')}
function openHdrMore(){openSheet('hdrMoreSheet')}   // F2.3 顶栏收敛: 浏览器/悬浮窗/无障碍收进溢出菜单(收纳不删)
function pickMedia(mode){closeSheets();
  if(mode==='camera'&&typeof GA!=='undefined'&&GA.openCamera){   // 拍照直连原生相机(issue#2): 不再依赖 <input capture>/isCaptureEnabled(部分 WebView 失效→只弹相册)
    let r='err';try{r=GA.openCamera()}catch(e){}
    if(r!=='ok')toast(r==='no-camera'?t('t_noCamera'):t('t_pickFail'));
    return}                                                       // 结果经 window.gaCameraResult 异步回推
  const fi=$('fileInput');fi.removeAttribute('capture');          // 照片/文件(及旧 APK/浏览器的拍照回退): 走 onShowFileChooser
  if(mode==='camera'){fi.setAttribute('accept','image/*');fi.setAttribute('capture','environment')}
  else if(mode==='photo'){fi.setAttribute('accept','image/*')}
  else{fi.removeAttribute('accept')}
  try{fi.click()}catch(e){toast(t('t_pickFail'))}}
// 原生相机拍完回推(issue#2): path=已落盘 uploads 的绝对路径; 空=取消/失败
window.gaCameraResult=function(path){
  if(!path){toast(t('t_noCamera'));return}
  pendingAtts.push({name:'camera.jpg',path:path});renderAttachRow()};
function onFilesPicked(e){const files=[...e.target.files];e.target.value='';
  files.forEach(f=>{if(f.size>MAX_UPLOAD){toast(f.name+t('t_attTooBig'));return}
    const rd=new FileReader();rd.onerror=()=>toast(t('t_attReadFail')+f.name);
    rd.onload=()=>{const path=GA.saveUpload(f.name,rd.result);
      if(path&&!/^ERROR/.test(path)){pendingAtts.push({name:f.name,path});renderAttachRow()}else toast(t('t_attSaveFail'));};
    rd.readAsDataURL(f)})}
function renderAttachRow(){const row=$('attachRow');row.innerHTML='';pendingAtts.forEach((a,i)=>{
  const ch=el('div','fchip',row);ch.innerHTML=ICO_FILE+'<span class="fn"></span>';ch.querySelector('.fn').textContent=a.name;
  const x=document.createElement('button');x.className='x';x.setAttribute('aria-label',t('remove'));x.innerHTML=ICO_X;
  x.onclick=()=>{pendingAtts.splice(i,1);renderAttachRow()};ch.appendChild(x)});updateSendEnabled()}
function updateSendEnabled(){return applySendEnabled()}

/* ════════════ 模型 / 推理 选择 ════════════ */
function curProvider(){const a=active&&providers.find(p=>p.id===active.pid);
  if(a&&a.enabled!==false)return a;return providers.find(p=>p.enabled!==false)||providers[0]}
function provName(p){return p&&(p.label||p.name)||''}   // 显示名(可改) vs p.name(后端 /llm 键, 对 fromMk 不可改)
function dispModel(m){return (m||'').replace(/\s*\[1m\]/i,'').trim()}   // 展示用: 去掉内部 [1m](1M 上下文 beta)标记, 发送给后端的仍是原始 model
function isAuto(){return !!(active&&active.pid==='__auto__'&&providers.length)}   // 无服务商时 auto 不成立 → modelLabel 落到"未配置"而非"自动"
function autoLabel(){return t('autoFailover')}
function modelLabel(){if(!cfgLoaded)return cfgUnconfigured?t('notCfgTap'):(cfgFailed||(_bootT0&&Date.now()-_bootT0>15000))?t('cfgFailShort'):t('booting');if(isAuto())return autoLabel();const p=curProvider();if(!p)return providers.length?t('selectModel'):t('notConfigured');return dispModel((active&&active.model)||p.model)||t('selectModel')}
function refreshModelUI(){$('modelChipName').textContent=modelLabel();
  const p=isAuto()?null:curProvider();$('modelChipIcon').innerHTML=isAuto()?AUTO_GLYPH:(p?modelGlyph((active&&active.model)||p.model||'',p.type):'');
  $('effChipName').textContent=effName(curEff);
  $('effChip').classList.toggle('on',!!curEff);
  if(!running)setStatus(modelLabel(),false);setHeaderTitle()}
function ensureActiveEnabled(){if(isAuto())return;const a=active&&providers.find(p=>p.id===active.pid);
  if(!a||a.enabled===false){const e=providers.find(p=>p.enabled!==false);active=e?{pid:e.id,model:e.model}:null;LS.set('active',active)}}
function testConnection(){const tb=$('setvTest');if(tb.classList.contains('spin'))return;   // 健康检查: 异步跑一次 /models
  const cfg={name:$('pvName').value.trim(),apikey:$('pvKey').value.trim(),apibase:$('pvBase').value.trim(),proxy:$('pvProxy').value.trim()||undefined,type:provType};
  if(!cfg.apikey||!cfg.apibase){toast(t('t_fillKeyBaseFirst'));return}
  tb.classList.add('spin');toast(t('testing'));
  asyncModels(cfg,res=>{tb.classList.remove('spin');
    GAT.emit('key_test',{ok:!!res.ok,cat:res.ok?null:GAT.errCat(res.error),msg:res.ok?null:GAT.errMsg(res.error),type:cfg.type,where:'editor'}); // key 验证结果(脱敏)
    toast(res.ok?(t('t_connOk')+(res.models?res.models.length:0)):(t('t_connFail')+(res.error||'?')))})}
function openSheet(id){$('sheetMask').classList.add('on');$(id).classList.add('on')}
function closeSheets(){$('sheetMask').classList.remove('on');document.querySelectorAll('.sheet').forEach(s=>s.classList.remove('on'))}

let deviceState={current:null,devices:[]};
function deviceName(d){return (d&&(d.displayName||d.hostname||d.deviceId))||'未命名设备'}
function refreshDeviceChip(){const chip=$('deviceChip');if(!chip)return;chip.classList.toggle('on',!!deviceState.current);chip.setAttribute('aria-label',deviceState.current?deviceName(deviceState.current):'选择电脑');chip.title=chip.getAttribute('aria-label')}
function deviceConvoId(){return curConvo&&curConvo.id||''}
function readDeviceState(){const cid=deviceConvoId();try{const raw=GA.send('/pc status'+(cid?' '+cid:'')),value=JSON.parse(raw||'{}');if(value&&value.ok){deviceState={current:cid?(value.current||null):null,devices:Array.isArray(value.devices)?value.devices:[]};refreshDeviceChip();return true}toast(value&&value.error||'无法读取设备')}catch(e){toast('无法读取设备')}return false}
function deviceOption(parent,label,selected,fn){const item=el('div','opt'+(selected?' sel':''),parent);const mid=el('div','mid',item),name=el('div','nm',mid);name.textContent=label;const ck=el('span','ck',item);ck.innerHTML=ICO_CK;item.onclick=fn;return item}
function openDeviceSheet(){if(!readDeviceState())return;const list=$('deviceList');list.innerHTML='';const current=deviceState.current;deviceOption(list,'未选择设备',!current,()=>selectDevice(null));deviceState.devices.forEach(d=>deviceOption(list,deviceName(d),!!(current&&d.deviceId===current.deviceId),()=>selectDevice(d.deviceId)));openSheet('deviceSheet')}
function selectDevice(deviceId){let cid=deviceConvoId();if(!cid){const c=ensureConvo('');if(!c)return;cid=c.id}let raw,value;try{raw=GA.send(deviceId?'/pc use '+cid+' '+deviceId:'/pc off '+cid);value=JSON.parse(raw||'{}')}catch(e){toast('无法切换设备');return}if(!value||!value.ok){toast(value&&value.error||'无法切换设备');return}deviceState={current:value.current||null,devices:Array.isArray(value.devices)?value.devices:[]};refreshDeviceChip();closeSheets()}
let modelTab='all';
function refreshMkMixins(){try{const r=JSON.parse(GA.send('/config')||'{}');if(Array.isArray(r.items)){configItems=r.items;mkMixins=r.items.filter(x=>x.type==='mixin')}}catch(e){}}
function openModelSheet(){GAT.emit('view_enter',{view:'model_sheet'});closeDrawer();if(!providers.length){openProviders();return}   // 无服务商: 进设置→服务商列表(含欢迎/密钥仅本地说明), 用户点"添加服务商"进编辑器
  refreshMkMixins();modelTab='all';$('modelSearch').value='';renderModelTabs();renderModels();openSheet('modelSheet')}
function renderModelTabs(){const tabs=$('modelTabs');tabs.innerHTML='';
  const mk=(id,label)=>{const b=document.createElement('button');b.className='shTab'+(modelTab===id?' on':'');b.textContent=label;b.onclick=()=>{modelTab=id;renderModelTabs();renderModels()};tabs.appendChild(b)};
  mk('all',t('all'));mk('fav',t('fav'));providers.forEach(p=>mk(p.id,provName(p)))}
function renderModels(){const wrap=$('modelList'),q=($('modelSearch').value||'').trim().toLowerCase();wrap.innerHTML='';
  const m2m=nm=>{const p=providers.find(pp=>pp.name===nm);return p?dispModel(p.model||(p.models&&p.models[0])):nm};
  // 按 configItems(mykey.py 原始顺序) 混排渲染 mixin + provider
  let entries=[];  // {type:'mixin',opt} | {type:'model',p,m,key}
  if(modelTab==='all'||modelTab==='fav'){
    const provByName={};providers.forEach(p=>{provByName[p.name]=p});
    const rendered=new Set();
    configItems.forEach(ci=>{
      if(ci.type==='mixin'){
        if(modelTab==='fav')return;  // 收藏页不显示 mixin
        const opt={name:ci.name,label:ci.label||ci.name,members:ci.members||[],memberModels:(ci.members||[]).map(m2m)};
        if(q&&!((opt.name+' '+(opt.label||'')+' '+(opt.members||[]).join(' ')+' '+(opt.memberModels||[]).join(' ')).toLowerCase().includes(q)))return;
        entries.push({type:'mixin',opt});
      }else{
        const p=provByName[ci.name];if(!p)return;rendered.add(p.name);
        const ms=(p.models&&p.models.length?p.models:[p.model]).filter(Boolean);
        ms.forEach(m=>{const key=p.id+'::'+m;
          if(modelTab==='fav'&&!favs.includes(key))return;
          if(q&&!(m.toLowerCase().includes(q)||provName(p).toLowerCase().includes(q)))return;
          entries.push({type:'model',p,m,key})});
      }
    });
    // 补充 configItems 中没有的 provider(用户手动新增但未保存到 mykey)
    providers.forEach(p=>{if(rendered.has(p.name))return;
      const ms=(p.models&&p.models.length?p.models:[p.model]).filter(Boolean);
      ms.forEach(m=>{const key=p.id+'::'+m;
        if(modelTab==='fav'&&!favs.includes(key))return;
        if(q&&!(m.toLowerCase().includes(q)||provName(p).toLowerCase().includes(q)))return;
        entries.push({type:'model',p,m,key})});
    });
    if(modelTab==='all'&&!q&&!entries.some(e=>e.type==='mixin')&&providers.length){   // 无 mixin 块也给一个置灰 Auto 入口: 故障转移未配置/关闭→灰显可见, 点齿轮去配置(req#2)
      const _mem=foEnabledNames();
      entries.unshift({type:'mixin',opt:{name:(foCfg&&foCfg.name)||'auto',label:autoLabel(),members:_mem,memberModels:_mem.map(m2m)}})}
  }else{
    // 特定 provider tab
    const tp=providers.find(p=>p.id===modelTab);if(tp){
      const ms=(tp.models&&tp.models.length?tp.models:[tp.model]).filter(Boolean);
      ms.forEach(m=>{const key=tp.id+'::'+m;
        if(q&&!(m.toLowerCase().includes(q)||provName(tp).toLowerCase().includes(q)))return;
        entries.push({type:'model',p:tp,m,key})});
    }
  }
  if(!entries.length){wrap.innerHTML='<div class="dwEmpty">'+t('noMatchModel')+'</div>';return}
  entries.forEach(e=>{
    if(e.type==='mixin'){const opt=e.opt;const sel=isAuto()&&active.auto===opt.name;
      const usable=isFailoverOn();                                      // 未启用故障转移 → Auto 行置灰, 点齿轮去配置(需求#2)
      const o=el('div','opt'+(sel?' sel':'')+(usable?'':' off'),wrap);
      const ms=(opt.memberModels&&opt.memberModels.length?opt.memberModels:(opt.members||[]));   // 链成员的型号
      o.innerHTML=AUTO_GLYPH+'<div class="mid"><div class="nm"></div><div class="sub"></div></div>'
        +(usable&&ms.length?'<span class="foCount">'+ms.length+'</span>':'')   // 成员数 pill: 既概括链长又填满右侧, 取代过长的逐项链
        +'<button class="foCfg" aria-label="'+t('failoverCfg')+'">'+ICO_GEAR+'</button><span class="ck">'+ICO_CK+'</span>';
      o.querySelector('.nm').textContent=autoLabel();
      o.querySelector('.sub').textContent=usable?foSummary(ms):t('failoverOffHint');   // 紧凑摘要(首2型号+余量), 单行省略, 不再换行成4行
      o.querySelector('.foCfg').onclick=ev=>{ev.stopPropagation();openFailoverSheet()};
      o.onclick=()=>selectAuto(opt);
    }else{const r=e;const sel=active&&active.pid===r.p.id&&active.model===r.m;
      const o=el('div','opt'+(sel?' sel':''),wrap);
      o.innerHTML=modelGlyph(r.m,r.p.type)+`<div class="mid"><div class="nm"></div><div class="sub"></div></div>`+
        `<button class="fav${favs.includes(r.key)?' on':''}" aria-label="${t('fav')}">${ICO_HEART}</button><span class="ck">${ICO_CK}</span>`;
      o.querySelector('.nm').textContent=dispModel(r.m);m1mBadge(o.querySelector('.nm'),r.m);
      o.querySelector('.sub').textContent=provName(r.p)+' · '+(r.p.type==='claude'?'Anthropic':'OpenAI');
      o.querySelector('.fav').onclick=e=>{e.stopPropagation();const i=favs.indexOf(r.key);if(i<0)favs.push(r.key);else favs.splice(i,1);LS.set('favs',favs);renderModels()};
      o.onclick=()=>selectModel(r.p,r.m)}
  })}
function sendLlmSwitch(name,model,opts){opts=opts||{};             // 立即切换后端 LLM：先中止在飞任务，避免 /llm 排在断线流后面导致后续 busy
  if(!opts.noAbort){if(running)stopRunClean();else try{GA.abort()}catch(e){}}   // 运行中(设置页删/改服务商等仍可达): 干净收尾在飞任务防模糊窗; 空闲: 兜底 abort 清后端残留流
  const payload={name:name};if(model)payload.model=model;           // UI 选中的是「服务商+型号」；旧版只发 name 会落回 mykey 默认/旧 model，导致运行时配置看似未生效
  GA.send('/llm '+JSON.stringify(payload));applySendEnabled()}
function selectModel(p,m){if(anyRunning()){toast(t('t_taskBusy'));return}   // P3d: anyRunning 冻结切模型   // 运行中冻结模型: 完整保护在跑会话(与切会话/新建/删除同不变量), 不静默掐断在飞任务(参考 tui_v3 running_blocked)
  if(p.enabled===false){p.enabled=true;try{saveProvToMk(p)}catch(e){}}   // 选中即启用: 同步落盘 mykey.py(否则块仍 enabled:false → 被 ensureActiveEnabled/重启回退, 与 P2 停用持久层不一致)
  GAT.emit('model_switch',{type:p.type,model:(m||'').toString().slice(0,40)}); // 语义步骤: 切换模型(型号非密钥)
  active={pid:p.id,model:m};LS.set('active',active);LS.set('providers',providers);
  sendLlmSwitch(p.name,m);                                           // 立即切换: 选了就生效(先 abort 旧流)
  closeSheets();refreshModelUI();toast(t('t_modelSwitched')+m)}
function selectAuto(opt,quiet){if(anyRunning()){toast(t('t_taskBusy'));return}   // P3d   // 运行中冻结(同 selectModel): 保护在跑会话
  if(!isFailoverOn()){                                                // 未启用故障转移 → 不切到 Auto, 引导去配置页(需求#2)
    toast(t('failoverCfg'));openFailoverSheet();return}
  GAT.emit('model_switch',{type:'mixin',model:opt.name});             // 选中 mixin(故障转移链)
  active={pid:'__auto__',model:'auto',auto:opt.name};LS.set('active',active);
  sendLlmSwitch(opt.name,null);                                      // 立即切换: 选了就生效(先 abort 旧流)
  refreshModelUI();if(!quiet){closeSheets();toast(t('t_autoSwitched'))}}   // quiet: 即时保存场景, 不关表/不提示
/* 故障转移配置子表: 选/排已启用服务商的转移顺序 + 高级(重试次数/基础间隔, 默认 10 / 0.5) */
let foChain=[];
let foEnabled=false;                                                  // 故障转移总开关: 关闭时 native 切回普通模型; 启用项为 0 时自动关, 开关始终可点(允许单模型)
function foNos(cfg){return (cfg&&Array.isArray(cfg.llm_nos))?cfg.llm_nos:((cfg&&Array.isArray(cfg.members))?cfg.members:[])}  // 后端 /config 导出 mixin 用 members, UI 保存用 llm_nos
function foEnabledNames(){return foNos(foCfg).filter(n=>providers.some(p=>p.name===n&&p.enabled!==false))}   // 已启用且仍有效的转移成员(foCfg=持久化真相, 经 LS→设备kv 兜底); 之前缺失→renderModels/selectAuto 抛 ReferenceError(齿轮不显/Auto 不可点根因)
function isFailoverOn(){return !!(foCfg&&foCfg.enabled)&&foEnabledNames().length>0}                        // 故障转移是否启用: 用户在设置中显式开启且≥1 有效成员; 未启用→Auto 不可选(需求#2)
function foSummary(ms){if(!ms.length)return t('failoverCfg');const head=ms.slice(0,2).map(dispModel).join(' → ');return ms.length>2?head+' +'+(ms.length-2):head}   // 紧凑链摘要: 首2型号 + "+余量", 单行
function openFailoverSheet(){if(runLocked())return;   // 运行中冻结故障转移配置(链保存会写 mykey + 可能 sendLlmSwitch), 与 selectAuto 同不变量
  GAT.emit('view_enter',{view:'failover'});
  const en=providers.filter(p=>p.enabled!==false&&p.apikey&&p.apibase&&(p.model||(p.models&&p.models[0])));
  if(!en.length){toast(t('failoverNoProvider'));return}                // 无可用服务商: 引导先去配置
  const cur=curProvider();const ord=cur&&en.includes(cur)?[cur,...en.filter(p=>p.id!==cur.id)]:en;
  foChain=ord.map(p=>({id:p.id,name:p.name,model:(p.model||p.models[0]),type:p.type,label:provName(p),on:true}));
  const savedNos=foNos(foCfg);
  if(savedNos.length){                                               // 套用已存顺序/启用集
    foChain.sort((a,b)=>{const ia=savedNos.indexOf(a.name),ib=savedNos.indexOf(b.name);return (ia<0?99:ia)-(ib<0?99:ib)});
    foChain.forEach(it=>{if(!savedNos.includes(it.name))it.on=false})}
  $('foRetries').value=(foCfg&&foCfg.max_retries)||10;
  $('foDelay').value=(foCfg&&foCfg.base_delay!=null)?foCfg.base_delay:0.5;
  foEnabled=!!(foCfg&&foCfg.enabled)&&foChain.filter(it=>it.on).length>=1;   // 总开关初值: 取持久化的启用态(而非仅当前是否在 Auto), 这样冷开设置页也能正确回显
  renderFoChain();openSheet('failoverSheet')}
let foDragI=null;                                                     // 正在拖拽的行索引(拖拽中高亮)
function renderFoEnabled(){const sw=$('foEnabledSw');if(!sw)return;   // 渲染总开关状态: 始终可点(开启时自动全开模型, 空链由 foPersist 兜底回弹)
  sw.classList.toggle('on',foEnabled);sw.setAttribute('aria-checked',foEnabled?'true':'false');
  const ch=$('foChain');if(ch)ch.classList.toggle('foDimmed',!foEnabled)}
function renderFoChain(){const w=$('foChain');w.innerHTML='';renderFoEnabled();
  if(foChain.length<1){w.innerHTML='<div class="dwEmpty" style="padding:22px 16px">'+t('failoverNeed1')+'</div>';return}
  foChain.forEach((it,i)=>{const r=el('div','foRow'+(it.on?'':' off')+(foDragI===i?' foDrag':''),w);
    r.innerHTML=`<button class="foGrip" aria-label="${t('dragSort')}">${ICO_GRIP}</button>`+
      modelGlyph(it.model,it.type)+'<div class="mid"><div class="nm"></div><div class="sub"></div></div>'+
      `<button class="sw${it.on?' on':''}" role="switch" aria-checked="${it.on}" aria-label="${t('enable')}"></button>`;
    r.querySelector('.nm').textContent=dispModel(it.model);m1mBadge(r.querySelector('.nm'),it.model);
    r.querySelector('.sub').textContent=(it.label||it.name)+' · '+(it.type==='claude'?'Anthropic':'OpenAI');
    r.querySelector('.foGrip').addEventListener('pointerdown',e=>foDragStart(e,i));
    r.querySelector('.sw').onclick=()=>{it.on=!it.on;renderFoChain();foPersist()}})}   // 即时保存
function foDragStart(e,from){                                          // 跟手拖拽重排: 被拖行随手指位移, 相邻行让位
  e.preventDefault();
  const w=$('foChain'),rows=[...w.children],n=rows.length;
  const drag=rows[from],rects=rows.map(r=>r.getBoundingClientRect());
  const h=rects[from].height,step=n>1?rects[1].top-rects[0].top:h,startY=e.clientY;
  const vib=m=>{try{navigator.vibrate&&navigator.vibrate(m)}catch(e){}};vib(12);  // 抓起触感
  let to=from;drag.classList.add('foDrag');
  const move=ev=>{const dy=ev.clientY-startY;
    drag.style.transform='translateY('+dy+'px)';                       // 被拖行紧跟手指
    const center=rects[from].top+h/2+dy;let nt=0;
    for(let j=0;j<n;j++){if(center>rects[0].top+step*j+h/2)nt=j}
    nt=Math.max(0,Math.min(n-1,nt));
    if(nt!==to){to=nt;vib(8);rows.forEach((r,j)=>{if(r===drag)return;    // 越位轻震 + 其余行平滑让出空位
      const s=(from<to&&j>from&&j<=to)?-step:(from>to&&j>=to&&j<from)?step:0;
      r.style.transition='transform .18s';r.style.transform=s?'translateY('+s+'px)':''})}};
  const up=()=>{document.removeEventListener('pointermove',move);document.removeEventListener('pointerup',up);document.removeEventListener('pointercancel',up);
    if(to!==from){vib(10);const[it]=foChain.splice(from,1);foChain.splice(to,0,it);renderFoChain();foPersist()}else renderFoChain()};
  document.addEventListener('pointermove',move);document.addEventListener('pointerup',up);document.addEventListener('pointercancel',up)}
function foPersist(){const names=foChain.filter(it=>it.on).map(it=>it.name);   // 即时落盘: 写 mykey.py mixin 块
  if(!names.length)foEnabled=false;                                  // 0 个启用项才关闭总开关(允许单模型故障转移)
  const retries=Math.max(1,parseInt($('foRetries').value,10)||10);
  const delay=Math.max(0,parseFloat($('foDelay').value)||0.5);
  foCfg={name:'auto',enabled:foEnabled,llm_nos:names,max_retries:retries,base_delay:delay,spring_back:300};
  LS.set('foCfg',foCfg);
  GAT.emit('failover_set',{enabled:foEnabled,chain:names.length,retries,delay});
  if(foEnabled){
    // 写 mixin 到 mykey.py (变量名 mixin_config_autoauto, name:'auto')
    const payload={name:'auto',llm_nos:names,max_retries:retries,base_delay:delay,spring_back:300};
    const r=GA.send('/provider.save '+JSON.stringify(payload));
    if(r&&/error|错误|失败|invalid/i.test(r)){toast(t('t_fetchFail')+r)}
  }else foDisableNative();
  if(foEnabled){
    if(isAuto())sendLlmSwitch('auto',null,{noAbort:true});            // 启用/重排: 当前在 Auto → llm_core 立即采用刚写回的 mixin_config_auto
  }else if(isAuto()){                                                  // 关闭故障转移且当前在 Auto: mixin 已删 → 切到具体已启用服务商(否则 /llm auto 落到已删 mixin = 未找到 LLM)
    const p=curProvider();
    if(p){active={pid:p.id,model:p.model||(p.models&&p.models[0])};LS.set('active',active);sendLlmSwitch(p.name,active.model)}
  }
  renderModels();renderFoEnabled();refreshModelUI()}
function foDisableNative(){
  GA.send('/provider.delete '+JSON.stringify({name:'auto'}));         // 从 mykey.py 删除 auto mixin
}
function toggleFailover(){
  if(!foEnabled)foChain.forEach(it=>it.on=true);                     // 开启: 默认全开(避免空链; 0 项由 foPersist 兜底关回)
  foEnabled=!foEnabled;foPersist()}
let foPersistTimer=null;
function foPersistDebounced(){clearTimeout(foPersistTimer);foPersistTimer=setTimeout(foPersist,500)}   // 输入框防抖
function foRestoreDefaults(){$('foRetries').value=10;$('foDelay').value=0.5;foPersist();toast(t('restoreDefaults'))}   // 高级选项恢复默认
function openEffSheet(){const wrap=$('effList');wrap.innerHTML='';
  EFFS.forEach(e=>{const o=el('div','opt'+(curEff===e.v?' sel':''),wrap);
    o.innerHTML=`<div class="mid"><div class="nm"></div><div class="sub"></div></div><span class="ck">${ICO_CK}</span>`;
    o.querySelector('.nm').textContent=t(e.k);o.querySelector('.sub').textContent=t(e.k+'_d');o.onclick=()=>selectEff(e.v)});
  openSheet('effSheet')}
function selectEff(v){if(anyRunning()){toast(t('t_taskBusy'));return}   // P3d   // 运行中冻结推理强度: saveProvToMk 会触发后端 reload_mykeys, 不应扰动在飞任务
  curEff=v;LS.set('eff',v);const p=curProvider();if(p){p.reasoning=v||undefined;LS.set('providers',providers);saveProvToMk(p)}
  closeSheets();refreshModelUI();toast(t('t_effSet')+effName(v))}

/* 快捷指令 (/goal /hive /conductor): 提示注入 → 选中后填入输入框, 用户补内容再发(手机端单进程: hive/conductor 适配为单 agent 串行编排) */
/* Goal 模式(issue#2): SOP 提示词对用户不可见(发送时隐式前置), 开启时输入框流光特效; hive/conductor 暂移除 */
const GOAL_PROMPT={
  zh:'请进入 Goal 模式：先读 memory/goal_mode_sop.md，按其在 temp/goal_state.json 记录目标与预算后持续自驱推进，期间用 update_working_checkpoint 记录进度，预算用尽再交付。注意节制临时文件与内存占用，不要堆积无用产物。\n\n用户目标：',
  en:'Enter Goal mode: read memory/goal_mode_sop.md, record the goal & budget in temp/goal_state.json, then self-drive continuously, logging progress via update_working_checkpoint, delivering when the budget is spent. Keep temp files & memory usage lean — do not pile up junk artifacts.\n\nGoal: '};
let goalMode=false, goalArmed=false;
function toggleGoalMode(){goalMode=!goalMode;goalArmed=goalMode;
  const cap=$('comp').querySelector('.cap');if(cap)cap.classList.toggle('goalActive',goalMode);
  const gb=$('cmdBtn');if(gb){gb.classList.toggle('on',goalMode);gb.setAttribute('aria-pressed',goalMode?'true':'false')}
  inp.setAttribute('placeholder',goalMode?t('goalPh'):t('composerPh'));
  if(goalMode)inp.focus();toast(goalMode?t('goalOn'):t('goalOff'))}
function exitGoalMode(){if(!goalMode)return;goalMode=goalArmed=false;
  const cap=$('comp').querySelector('.cap');if(cap)cap.classList.remove('goalActive');
  const gb=$('cmdBtn');if(gb){gb.classList.remove('on');gb.setAttribute('aria-pressed','false')}
  inp.setAttribute('placeholder',t('composerPh'))}

/* 用户头像模板选择 (issue#6) */
function openAvatarSheet(){const g=$('avGrid');g.innerHTML='';
  const up=el('div','avCell avUp',g);up.innerHTML=ICO_IMGADD;up.setAttribute('role','button');up.setAttribute('aria-label',t('avatarUpload'));
  up.onclick=()=>{const fi=$('avatarFile');if(fi)fi.click()};                                   // 上传自定义头像图片
  if(userAv&&(userAv.indexOf('img:')===0||userAv.indexOf('file:')===0)){const c=el('div','avCell sel',g);c.innerHTML=userAvatarInner();
    c.setAttribute('role','button');c.setAttribute('aria-label',t('myAvatar'))}                // 已上传图(含旧 'file:' 兼容): 置顶且选中
  AV_PRESETS.forEach(av=>{const c=el('div','avCell'+(av===userAv?' sel':''),g);
    c.innerHTML=av==='person'?AV_PERSON:'<span class="em">'+av+'</span>';c.setAttribute('role','button');c.setAttribute('aria-label',av==='person'?t('myAvatar'):av);
    c.onclick=()=>{closeSheets();setUserAvatar(av,{sync:true})}});   // 单一真相源: 写本地+刷新所有展示+同步远程库
  openSheet('avatarSheet')}
// 头像上传(#4): 选图 → 圆形裁剪器(拖动+缩放) → 导出 200px jpeg → userAv='img:'+dataURL(经 LS→设备kv 持久); userAvatarInner 渲染 <img>
// 选图→圆形裁剪 公共入口(设置页头像 + 注册"完善资料"头像复用): onDone(dataURL)=裁剪结果; 不传=存本地用户头像。
function cropImageFile(file,onDone){if(!file)return;
  const rd=new FileReader();rd.onerror=()=>toast(t('t_attReadFail')+(file.name||''));
  rd.onload=()=>{closeSheets();openAvatarCrop(rd.result,onDone)};
  rd.readAsDataURL(file)}
function onAvatarPicked(e){cropImageFile(e.target.files&&e.target.files[0])}   // 设置页: 不传 onDone → 存本地用户头像(value 由 closeCrop 清)
function refreshAvatarRow(){const inner=userAvatarInner();
  const v=$('avatarVal');if(v)v.innerHTML=inner;                  // 旧设置行(已移除)兼容: 存在才写
  const dv=$('dwAvatar');if(dv)dv.innerHTML=inner;                // 抽屉头像
  const up=$('userPageAvatar');if(up)up.innerHTML=inner;          // 账户页顶部大头像随改动即时刷新
  const dn=$('dwUserName');if(dn)dn.textContent=userDisplayName()}
/* 头像单一真相源(issue#1 v2.4): 写本地(userAv+LS, 失败回滚)→刷新展示→可选 PUT 远程库同步。
   token 形态: 'person'(默认)|emoji|'img:'+dataURL|'file:'(旧兼容)。后端 avatar 列存裸图(dataURL/URL)或 token, _normAvatarToken 归一。 */
function _avatarBackendRep(token){return token.indexOf('img:')===0?token.slice(4):token}   // 图片存裸 dataURL(兼容历史注册写入); 预设/emoji 存 token 原样
function _normAvatarToken(v){if(!v)return '';
  if(v.indexOf('img:')===0||v.indexOf('file:')===0)return v;            // 已是 token
  if(v.indexOf('data:')===0||v.indexOf('http')===0)return 'img:'+v;     // 历史裸图 → token
  return v}                                                            // 预设/emoji 原样

function setUserAvatar(token,opts){opts=opts||{};const prev=userAv;userAv=token;   // 写本地+持久(失败回滚, 不与渲染分叉)
  if(!LS.set('userAvatar',token)){userAv=prev;toast(t('t_attSaveFail'));return false}
  refreshAvatarRow();if(curConvo&&!running)renderConvo(curConvo);                 // 刷新设置/抽屉/账户页头像 + 已有气泡
  return true}
// 后端头像(登录回填/注册上传)落本地展示: 仅当本地未自定义图片头像时(尊重本地选择), 不回写后端。
function hydrateAvatarFromBackend(av){const tok=_normAvatarToken(av);if(!tok)return;
  const cur=LS.get('userAvatar','person');
  if(cur&&cur!=='person')return;   // 本地已自定义(图片/预设/emoji)=该设备单一真相源, 不被后端旧值回灌(修复离线改预设头像下次启动被静默回退); 仅默认 person 时采纳后端(新设备登录回填)
  setUserAvatar(tok,{sync:false})}
/* 圆形头像裁剪器: 拖动平移 + 滑杆缩放, 圆形选框圈定 → 导出 200px jpeg。鲁棒: 失败回滚/取消可重选/图始终盖满选框。 */
let crop=null,cropDone=null;   // cropDone(dataURL): 非空时 confirmCrop 回调它(注册页捕获 dataURL→PUT 后端); 空=存本地用户头像(设置页)
function openAvatarCrop(src,onDone){cropDone=onDone||null;const img=$('cropImg');
  const show=()=>{const stage=$('cropStage'),S=stage.clientWidth||260;
    crop={natW:img.naturalWidth||1,natH:img.naturalHeight||1,S,z:1,tx:0,ty:0};
    const zr=$('cropZoom');if(zr)zr.value=1;cropLayout();$('cropMask').classList.add('on')};
  img.onload=show;img.onerror=()=>{toast(t('t_pickFail'));closeCrop()};
  if(img.getAttribute('src')===src){show();return}          // 同图重选: src 不变→onload 不再触发, 直接复用已解码位图弹框(根治"裁剪框不弹")
  img.removeAttribute('src');img.src=src;                    // 先清再设, 保证换图必触发 onload
  if(img.complete&&img.naturalWidth)show()}                  // 已同步解码(缓存命中)兜底: 不空等 onload
function _cropBase(){return crop.S/Math.min(crop.natW,crop.natH)}        // z=1 短边铺满选框(cover)
function cropLayout(){if(!crop)return;const sc=_cropBase()*crop.z,dw=crop.natW*sc,dh=crop.natH*sc;
  const mx=Math.max(0,(dw-crop.S)/2),my=Math.max(0,(dh-crop.S)/2);
  crop.tx=Math.max(-mx,Math.min(mx,crop.tx));crop.ty=Math.max(-my,Math.min(my,crop.ty));   // 夹紧: 图始终盖满选框, 不露黑边
  const img=$('cropImg');img.style.width=dw+'px';img.style.height=dh+'px';
  img.style.left=((crop.S-dw)/2+crop.tx)+'px';img.style.top=((crop.S-dh)/2+crop.ty)+'px'}
function cropZoomTo(v){if(!crop)return;crop.z=Math.max(1,Math.min(3,+v||1));cropLayout()}
function cropZoomAt(nz,cx,cy){if(!crop)return;nz=Math.max(1,Math.min(3,nz||1));   // #3 以手势中心(cx,cy, stage 坐标)为锚缩放: 保持锚点下的图像点不动(双指捏合自然手感, 苹果/安卓通用范式)
  const sc0=_cropBase()*crop.z,sc1=_cropBase()*nz,dw0=crop.natW*sc0,dh0=crop.natH*sc0,dw1=crop.natW*sc1,dh1=crop.natH*sc1;
  const left0=(crop.S-dw0)/2+crop.tx,top0=(crop.S-dh0)/2+crop.ty;            // 缩放前图左上(stage 坐标)
  crop.tx=(cx-(cx-left0)*dw1/dw0)-(crop.S-dw1)/2;crop.ty=(cy-(cy-top0)*dh1/dh0)-(crop.S-dh1)/2;   // 反解新 tx/ty 使锚点不漂移
  crop.z=nz;const zr=$('cropZoom');if(zr)zr.value=nz;cropLayout()}            // 同步滑杆 + cropLayout 夹紧(图始终盖满选框)
function confirmCrop(){if(!crop){closeCrop();return}
  const OUT=200,sc=_cropBase()*crop.z,dw=crop.natW*sc,dh=crop.natH*sc;
  const left=(crop.S-dw)/2+crop.tx,top=(crop.S-dh)/2+crop.ty;
  const sx=(-left)/sc,sy=(-top)/sc,sw=crop.S/sc,sh=crop.S/sc;    // 选框(0..S)反映射回原图像素
  let url;try{const cv=document.createElement('canvas');cv.width=cv.height=OUT;const cx=cv.getContext('2d');
    cx.drawImage($('cropImg'),sx,sy,sw,sh,0,0,OUT,OUT);url=cv.toDataURL('image/jpeg',0.82)}
  catch(e){closeCrop();toast(t('t_pickFail'));return}
  if(cropDone){const cb=cropDone;closeCrop();cb(url);return}   // 注册页等: 把裁剪结果(dataURL)交回调(PUT 后端 avatar), 不写本地用户头像
  closeCrop();if(setUserAvatar('img:'+url,{sync:true}))toast(t('t_avatarSet'))}   // 单一真相源: 写本地(失败回滚)+刷新+同步远程库
function closeCrop(){$('cropMask').classList.remove('on');crop=null;cropDone=null;const ci=$('cropImg');if(ci)ci.removeAttribute('src');const fi=$('avatarFile');if(fi)fi.value=''}   // 清 cropImg.src: 否则重选同图时 src 不变→<img>load 不再触发, 裁剪框不弹(Monitor major); 同时释放解码位图
(function bindCrop(){const stage=$('cropStage');if(!stage)return;let lx=0,ly=0,drag=false,pinching=false,pd0=0,pz0=1;   // #3: 单指拖动平移 + 双指捏合缩放(锚定手势中心)
  const dist=(a,b)=>Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY);
  const down=e=>{if(!crop)return;
    if(e.touches&&e.touches.length>=2){pinching=true;drag=false;pd0=dist(e.touches[0],e.touches[1])||1;pz0=crop.z;e.preventDefault();return}   // 双指: 记捏合起始间距/缩放
    pinching=false;drag=true;const p=e.touches?e.touches[0]:e;lx=p.clientX;ly=p.clientY;e.preventDefault()};
  const move=e=>{if(!crop)return;
    if(pinching&&e.touches&&e.touches.length>=2){const a=e.touches[0],b=e.touches[1],r=stage.getBoundingClientRect();
      cropZoomAt(pz0*dist(a,b)/pd0,(a.clientX+b.clientX)/2-r.left,(a.clientY+b.clientY)/2-r.top);e.preventDefault();return}   // 缩放比例 = 当前间距/起始间距, 锚定双指中点
    if(!drag)return;const p=e.touches?e.touches[0]:e;crop.tx+=p.clientX-lx;crop.ty+=p.clientY-ly;lx=p.clientX;ly=p.clientY;cropLayout();e.preventDefault()};
  const up=e=>{const n=e.touches?e.touches.length:0;
    if(n>=2){pinching=true;drag=false;pd0=dist(e.touches[0],e.touches[1])||1;pz0=crop.z;return}   // 仍≥2指(如 3→2 指): 重设捏合基线 → 不跳变
    if(n===1){pinching=false;drag=true;lx=e.touches[0].clientX;ly=e.touches[0].clientY;return}     // 回到单指: 切平移, 重锚起点(防跳)
    drag=false;pinching=false};
  stage.addEventListener('touchstart',down,{passive:false});stage.addEventListener('touchmove',move,{passive:false});stage.addEventListener('touchend',up);stage.addEventListener('touchcancel',up);
  stage.addEventListener('mousedown',down);window.addEventListener('mousemove',move);window.addEventListener('mouseup',up)})();

/* ════════════ 服务商配置(多服务商) ════════════ */
let provType='oai', editingId=null;
function providerPayload(p,selectedModel){const model=selectedModel||(active&&active.pid===p.id&&active.model)||p.model||(p.models&&p.models[0]);
  const cfg={name:p.name,apikey:p.apikey,apibase:p.apibase,model,models:p.models||[],type:p.type};
  if(p.enabled===false)cfg.enabled=false;                                                // I6: 停用态落 mykey.py 块(单一真相源); 启用=不写该键(缺省即启用, 块干净) → 关闭保存不再被 /config 回弹
  if(p.label&&p.label!==p.name)cfg.label=p.label;                                        // 自定义显示名同落 mykey 块(同 I6); 与 name 相同不写键(受管字段, 缺失即删残留行) → 改名不再被 /config 回弹
  if(p.proxy)cfg.proxy=p.proxy;
  if(p.type==='oai'){if(p.api_mode)cfg.api_mode=p.api_mode}else{cfg.thinking_type='adaptive';if(p.fake_cc)cfg.fake_cc_system_prompt=true}
  if(p.reasoning||curEff)cfg.reasoning_effort=p.reasoning||curEff;
  if(p.max_tokens)cfg.max_tokens=+p.max_tokens;
  if(p.user_agent)cfg.user_agent=p.user_agent;                                           // 高级设置直传后端(白名单已含; 后端把 connect→timeout 迁移到 llmcore 真读的键)
  if(p.max_retries!=null&&p.max_retries!=='')cfg.max_retries=+p.max_retries;
  if(p.read_timeout!=null&&p.read_timeout!=='')cfg.read_timeout=+p.read_timeout;
  if(p.timeout!=null&&p.timeout!=='')cfg.timeout=+p.timeout;
  return cfg}
function saveProvToMk(p,selectedModel){return GA.send('/provider.save '+JSON.stringify(providerPayload(p,selectedModel)))}
function delProvFromMk(name){return GA.send('/provider.delete '+JSON.stringify({name}))}
/* ════════════ 设置(kelivo 分组首页 + 子页栈式导航) ════════════ */
const SET_PANELS=['homePanel','userForm','provListPanel','provEditPanel','dataPanel','statsPanel','filesPanel','memPanel','updatePanel','a11yPersistPanel','ganetPanel','ganetSetupPanel','ganetDevicePanel'];
let setStack=[];   // [{panel,title}] 导航栈: 栈顶=当前页, 返回逐级 pop, 见底关设置(变量收敛在此处, 半径小)
function _setShow(panel,title){
  SET_PANELS.forEach(id=>{const e=$(id);if(e)e.style.display=(id===panel)?'block':'none'});
  $('setvTitle').textContent=title||'';
  const isEdit=panel==='provEditPanel';
  $('provSaveBar').style.display=isEdit?'flex':'none';$('setvTest').style.display=isEdit?'flex':'none';
  const sr=$('setvRules');if(sr)sr.style.display=(panel==='planPanel'||panel==='pointsDetailPanel')?'inline-flex':'none';   // 右上角「积分规则」入口(仅套餐/明细页)
  if(!isEdit)$('setvBrand').style.display='none';
  if(panel==='homePanel')refreshHome();
  
  else if(panel==='ganetPanel')setTimeout(refreshGanetPage,0);
  else if(panel==='provListPanel'){editingId=null;$('welcome').style.display=providers.length?'none':'block';renderProvList()}
  else if(panel==='dataPanel')setTimeout(refreshStorage,20);
  else if(panel==='filesPanel')renderFilesPage();
  else if(panel==='memPanel')renderMemPage();
  else if(panel==='updatePanel')renderUpdatePage();
  else if(panel==='statsPanel')renderStats();
  
  
  
  else if(panel==='datasetPanel')resetDatasetForm();
  else if(panel==='a11yPersistPanel')renderA11yPersistPage();
}
function setNav(panel,title,key){setStack.push({panel,title,key});_setShow(panel,title)}   // key=可选 i18n 键, 切语言时据此重译标题
function setvBack(){if(setStack.length>1){setStack.pop();const top=setStack[setStack.length-1];_setShow(top.panel,top.title);return}closeSettings()}
function closeSettings(){setStack=[];$('setv').classList.remove('on');$('setv').setAttribute('aria-hidden','true')}
function openSettings(){GAT.emit('view_enter',{view:'settings'});closeDrawer();setStack=[{panel:'homePanel',title:t('settings'),key:'settings'}];_setShow('homePanel',t('settings'));
  $('setv').classList.add('on');$('setv').setAttribute('aria-hidden','false');}

/* ---- APK 工厂额度(设置页行): 登录态实时读取, 失败/未登录回退静态文案; 尽力而为不阻塞设置页 ---- */
   // 与 apk_factory.py DEFAULT_BASES 同源
let _apkQuotaBusy=false;


function openGanetPage(){setNav('ganetPanel',t('grpGanet'),'grpGanet')}
function formatGanetCode(el){
  const s=(el.value||'').replace(/\D/g,'').slice(0,6);
  el.value=s.length>3?s.slice(0,3)+' '+s.slice(3):s;
}
function openGanetSetupHelp(){setNav('ganetSetupPanel',t('ganetSetupTitle'),'ganetSetupTitle')}
function _ganetRenderDevices(data){
  const box=$('ganetDeviceList');if(!box)return;const devs=(data&&data.devices)||[];
  box.innerHTML=devs.length?devs.map(d=>'<button class="row rowBtn ganetDevice" data-id="'+_escd(d.deviceId||'')+'" data-name="'+_escd(d.displayName||d.model||'Computer')+'" data-model="'+_escd(d.model||'Computer')+'"><span class="k">'+_escd(d.displayName||d.model||'Computer')+'</span><svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg></button>').join(''):'<div class="row"><span class="k">'+_escd(t('ganetNone'))+'</span></div>';
  box.querySelectorAll('.ganetDevice').forEach(b=>b.onclick=()=>openGanetDevice(b.dataset.id,b.dataset.name,b.dataset.model));
  const hv=$('ganetHomeVal');if(hv)hv.textContent=devs.length?String(devs.length):t('ganetAdd');
}
function refreshGanetPage(){
  try{const r=JSON.parse(GA.send('/ganet.devices')||'{}');_ganetRenderDevices(r)}catch(e){_ganetRenderDevices({devices:[]})}
}
function ganetConnectionLabel(result){
  if(result&&result.ok&&result.state==='reachable')return '可连接';
  if(result&&result.state==='disconnected')return '未连接';
  return '连接异常';
}
function checkGanetDevice(id,conn){
  conn.innerHTML='<span class="spinDot"></span>正在检查';
  let start;try{start=JSON.parse(GA.send('/ganet.status '+id)||'{}')}catch(e){conn.textContent='检查失败';return}
  if(!start.job){conn.textContent=ganetConnectionLabel(start);return}
  let tries=0;const tick=()=>{let job;try{job=JSON.parse(GA.send('/jobresult '+start.job)||'{}')}catch(e){conn.textContent='检查失败';return}
    if(job.pending){if(++tries>150){conn.textContent='检查超时';return}setTimeout(tick,400);return}
    let result;try{result=JSON.parse(job.result||'{}')}catch(e){result={ok:false,state:'error'}}
    conn.textContent=ganetConnectionLabel(result);if(result&&result.error)conn.title=String(result.error)};
  setTimeout(tick,250)
}
function openGanetDevice(id,name,model){
  $('ganetDetailModel').textContent=(name&&model&&name!==model)?name+' · '+model:(name||model||'Computer');const btn=$('ganetRemoveBtn'),conn=$('ganetDetailConnection');btn.onclick=()=>removeGanetDevice(id,name);conn.textContent='正在检查';
  setNav('ganetDevicePanel',t('ganetDeviceDetails'),'ganetDeviceDetails');setTimeout(()=>checkGanetDevice(id,conn),0)
}
function removeGanetDevice(id,name){
  gaConfirm('解除配对？',name+' 会从当前手机的已配对电脑中移除。以后如需再次使用，需要重新配对。',()=>{try{const r=JSON.parse(GA.send('/ganet.remove '+id)||'{}');if(!r.ok)throw new Error(r.error||'解除配对失败');const box=$('ganetDeviceList'),row=box&&box.querySelector('[data-id="'+CSS.escape(id)+'"]');if(row)row.remove();if(box&&!box.querySelector('.ganetDevice'))_ganetRenderDevices({devices:[]});setvBack();setTimeout(refreshGanetPage,0)}catch(e){toast(String(e))}},true)
}
function setGanetPairProgress(message,busy){const st=$('ganetPairStatus');if(!st)return;st.classList.toggle('ganetPairBusy',!!busy);st.textContent=message}
function scanGanetPair(){const pairButton=$('ganetPairBtn');if(pairButton)pairButton.disabled=true;setGanetPairProgress('正在打开相机',true);try{GA.scanGanetQr()}catch(e){if(pairButton)pairButton.disabled=false;setGanetPairProgress(String(e),false)}}
window.gaGanetScanResult=function(job){const pairButton=$('ganetPairBtn');if(!job){if(pairButton)pairButton.disabled=false;setGanetPairProgress('已取消扫描',false);return}setGanetPairProgress('正在安全验证电脑',true);const tick=()=>{let r={};try{r=JSON.parse(GA.ganetQrStatus(job)||'{}')}catch(e){};const terminal=['approved','cancelled','rejected','expired','security_failed'].includes(r.state);setGanetPairProgress(r.message||(terminal?'配对已结束':'正在安全验证电脑'),!terminal);if(terminal){if(pairButton)pairButton.disabled=false;if(r.state==='approved')refreshGanetPage();return}setTimeout(tick,700)};tick()}
function userDisplayName(){return t('me')}




function openProviders(){refreshProvidersFromLlmc();if(!setStack.length)openSettings();setNav('provListPanel',t('providersModels'),'providersModels')}

function openDataPage(){setNav('dataPanel',t('storageSpace'),'storageSpace')}
function openStatsPage(){GAT.emit('view_enter',{view:'stats'});setNav('statsPanel',t('stats'),'stats')}

function refreshHome(){
  const sw=$('swSound');if(sw){sw.classList.toggle('on',soundOn);sw.setAttribute('aria-checked',soundOn?'true':'false')}
  const swK=$('swKeepAwake');if(swK){swK.classList.toggle('on',keepAwake);swK.setAttribute('aria-checked',keepAwake?'true':'false')}
  const swTh=$('swShowThinking');if(swTh){swTh.classList.toggle('on',showThinking);swTh.setAttribute('aria-checked',showThinking?'true':'false')}   // F1.3 开关同步
  try{if(window.GA&&GA.floatAlwaysOn){const nv=!!GA.floatAlwaysOn();if(nv!==floatAlwaysOn){floatAlwaysOn=nv;LS.set('floatAlwaysOn',nv)}}}catch(e){}   // 常开真值=原生 SP∧权限(读桥, 仿 a11yOn); kv 镜像可分叉(授权往返时 WebView 未载/登录切命名空间), 旧壳无桥保持镜像
  const swFA=$('swFloatAlways');if(swFA){swFA.classList.toggle('on',floatAlwaysOn);swFA.setAttribute('aria-checked',floatAlwaysOn?'true':'false')}
  try{refreshA11y()}catch(e){}   // 无障碍行值含持久化态(设置首页打开/切语言时重读原生真值)
  refreshAvatarRow();refreshProxyVal();refreshAppVersion();_reflectUpdateBadge();refreshThemeVal();refreshEvoBadge();
  const pc=$('provCountVal');if(pc)pc.textContent=providers.length?(providers.length+t('count')):t('addProvider');
  const r=$('opacityRange');if(r)r.value=Math.round(floatOpacity*100);
  const ov=$('opacityVal');if(ov)ov.textContent=Math.round(floatOpacity*100)+'%';
                               // 切语言等重渲路径同步刷新额度行(JS 填充值, 不带 data-i18n)
  setTimeout(refreshStorage,20)}
/* 统计子页(#2): 范围筛选 + 聊天热力图(每格可点看当日明细) + 总览 + 按模型消耗, 纯本机聚合, 不上报、不额外存储 */
let customRange=LS.get('customRange',null);          // #2c: 自定义统计时间段 [startMs,endMs] | null
let statRange=LS.get('statRange','range_all');if(statRange==='range_custom'&&!customRange)statRange='range_all';
let heatMode=LS.get('heatMode','rolling'), _heatAgg=null;   // #2: 热力图窗口 'rolling'(最近一年, 默认) | <年份数字>(该日历年, 当前年裁到今天→无未来空白); _heatAgg=全量聚合缓存(切窗重渲不重算)
const STAT_RANGES=[{k:'range_all',d:0},{k:'range_30d',d:30},{k:'range_90d',d:90}];
function _dayKey(ts){const d=new Date(ts);return d.getFullYear()+'-'+(d.getMonth()+1)+'-'+d.getDate()}
function _startOfDay(ts){const d=new Date(ts);return new Date(d.getFullYear(),d.getMonth(),d.getDate()).getTime()}
function statsAgg(startTs,endTs){endTs=endTs==null?Infinity:endTs;const live=convos.filter(c=>!c.deleted);   // #2c/#4: 可选上界 endTs(自定义时间段); 同时聚合 缓存读取 cr / 缓存创建 cw
  const byDay=new Map(),byModel=new Map(),cset=new Set();let msgs=0,ti=0,to=0,steps=0,cr=0,cw=0,minTs=0;
  live.forEach(c=>(c.msgs||[]).forEach(m=>{const ts=m.ts||c.ts||0;if(ts<startTs||ts>endTs)return;
    if(!minTs||ts<minTs)minTs=ts;
    msgs++;cset.add(c.id);const dk=_dayKey(ts),dd=byDay.get(dk)||{n:0,ti:0,to:0,steps:0,cr:0,cw:0};dd.n++;
    if(m.role==='assistant'){const a=m.ti||0,b=m.to||0,rc=m.cr||0,wc=m.cw||0,st=(m.steps&&m.steps.length)||0;
      ti+=a;to+=b;cr+=rc;cw+=wc;steps+=st;dd.ti+=a;dd.to+=b;dd.cr+=rc;dd.cw+=wc;dd.steps+=st;
      const mdl=dispModel(m.model);if(mdl){const mm=byModel.get(mdl)||{n:0,ti:0,to:0,steps:0};mm.n++;mm.ti+=a;mm.to+=b;mm.steps+=st;byModel.set(mdl,mm)}}   // 「按模型消耗」只统计有真实模型名的回合; 无 model 的回合(中途中止/报错/旧数据)不再凑成幻影"未填模型"桶(总 token/步数仍计入上方汇总, 仅不参与逐模型拆分)
    byDay.set(dk,dd)}));
  return {convos:cset.size,msgs,ti,to,steps,cr,cw,byDay,byModel,minTs}}
function _hitRate(cr,ti){return ti>0?Math.round(cr/ti*100)+'%':'—'}   // #4: 缓存命中率=缓存读取/总输入 token(tok_in 已含 cache_read → 比值=输入中来自缓存的占比)
function _heatBounds(){const maxY=new Date().getFullYear();const dataMin=(_heatAgg&&_heatAgg.minTs)?new Date(_heatAgg.minTs).getFullYear():maxY;return [Math.min(dataMin,maxY-2), maxY]}   // #4 [可选最早年, 当前年]: 即使仅当年数据也至少回溯到前年 → 年份下拉恒有 ≥3 项(rolling+过去年), 不再退化为静态标签; 用户可选历史年份(空年=空网格, 同 GitHub 贡献图)
function renderStats(){_heatAgg=statsAgg(0);                                  // 面板打开: 全量聚合一次, 缓存供切窗复用
  const [minY,maxY]=_heatBounds();
  if(heatMode!=='rolling'&&(heatMode<minY||heatMode>maxY))heatMode='rolling';  // 陈旧年份越界 → 回退"最近一年"
  renderYearSel(minY,maxY);renderHeatmap(_heatAgg.byDay,heatMode);renderStatRange()}
function selectHeatMode(m){GAT.emit('stats_heat_mode',{rolling:m==='rolling',year:m==='rolling'?0:(+m||0)});heatMode=m;LS.set('heatMode',m);closeSheets();     // 切窗: 只重渲热力图+选择器, 不动总览/按模型(与范围筛选解耦)
  const [minY,maxY]=_heatBounds();
  renderYearSel(minY,maxY);renderHeatmap((_heatAgg||{byDay:new Map()}).byDay,heatMode)}
function _heatModeLabel(m){return m==='rolling'?t('heatRolling'):String(m)}
function renderYearSel(minY,maxY){const w=$('heatYearSel');if(!w)return;
  w.innerHTML='';   // #2b: Apple 风下拉(pill + 底部弹层)取代步进器; 默认"最近一年", 可下拉选具体过去年份
  const opts=[{v:'rolling',label:t('heatRolling')}];
  for(let y=maxY-1;y>=minY;y--)opts.push({v:y,label:String(y)});   // 过去整年(当前年已被"最近一年"覆盖, 不重复列入)
  const btn=el('button','heatYearPick',w);
  btn.innerHTML='<span class="hyText"></span><svg class="hyChev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>';
  btn.querySelector('.hyText').textContent=_heatModeLabel(heatMode);
  btn.setAttribute('aria-haspopup','listbox');btn.setAttribute('aria-label',t('heatRangeTitle')+': '+_heatModeLabel(heatMode));   // Monitor#4: 标签含当前选中值; 弹层标为真 listbox(见 openHeatYearSheet)
  if(opts.length<=1){btn.classList.add('solo');btn.disabled=true}            // 仅一年数据 → 无可下拉项, 退化为静态范围标签
  else btn.onclick=()=>openHeatYearSheet(opts)}
function openHeatYearSheet(opts){const w=$('heatYearList');if(!w)return;w.innerHTML='';w.setAttribute('role','listbox');
  opts.forEach(o=>{const sel=String(heatMode)===String(o.v),it=el('div','opt'+(sel?' sel':''),w);
    it.setAttribute('role','option');it.setAttribute('aria-selected',sel?'true':'false');
    it.innerHTML='<div class="mid"><div class="nm"></div></div><span class="ck">'+ICO_CK+'</span>';
    it.querySelector('.nm').textContent=o.label;it.onclick=()=>selectHeatMode(o.v)});
  openSheet('heatYearSheet')}
function renderStatRange(){   // 范围切换: 只重渲染筛选条+总览+按模型, 不碰热力图(保留其滚动位置/不重建, N1)
  let startTs,endTs=Infinity;
  if(statRange==='range_custom'&&customRange){startTs=_startOfDay(customRange[0]);endTs=_startOfDay(customRange[1])+864e5-1}   // 自定义: [起日 00:00, 止日 23:59:59]
  else{const sr=STAT_RANGES.find(r=>r.k===statRange)||STAT_RANGES[0];startTs=sr.d?_startOfDay(Date.now()-sr.d*864e5):0}
  const A=statsAgg(startTs,endTs);
  const rg=$('statRanges');if(rg){rg.innerHTML='';
    STAT_RANGES.forEach(r=>{const b=el('button','statRange'+(r.k===statRange?' on':''),rg);
      b.textContent=t(r.k);b.onclick=()=>{statRange=r.k;LS.set('statRange',r.k);GAT.emit('stats_range',{type:r.k});renderStatRange()}});
    const cb=el('button','statRange statRangeCustom'+(statRange==='range_custom'?' on':''),rg);   // #2c: 自定义时间段(kelivo 风月历选择)
    cb.textContent=(statRange==='range_custom'&&customRange)?_fmtRange(customRange):t('range_custom');
    cb.onclick=()=>openRangePicker()}
  const g=$('statGrid');if(g){g.innerHTML='';
    [[A.convos,'statConvos'],[A.msgs,'statMsgs'],[humanTok(A.ti),'statTokIn'],[humanTok(A.to),'statTokOut'],[A.steps,'statSteps'],
     [humanTok(A.cr),'statCacheRead'],[humanTok(A.cw),'statCacheWrite'],[_hitRate(A.cr,A.ti),'statCacheHit']].forEach(a=>{   // #4: 增 缓存读取/缓存创建/缓存命中率
      const c=el('div','statCard',g);c.innerHTML='<div class="statNum"></div><div class="statLbl"></div>';   // Apple 风: 数字优先 + 标签, 去彩色图标块
      c.querySelector('.statNum').textContent=a[0];c.querySelector('.statLbl').textContent=t(a[1])})}
  const ms=$('modelStats');if(ms){ms.innerHTML='';
    const arr=[...A.byModel.entries()].sort((x,y)=>(y[1].ti+y[1].to)-(x[1].ti+x[1].to));
    if(!arr.length)ms.innerHTML='<div class="statEmpty">'+t('noData')+'</div>';
    else arr.forEach(([name,v])=>{const r=el('div','mstRow',ms);
      r.innerHTML=modelGlyph(name)+'<div class="mmid"><div class="nm"></div><div class="sub"></div></div><div class="val"></div>';
      r.querySelector('.nm').textContent=name;
      r.querySelector('.sub').textContent=v.n+t('unitMsgs')+' · '+v.steps+' '+t('steps');
      r.querySelector('.val').innerHTML='↑'+humanTok(v.ti)+'<br>↓'+humanTok(v.to)})}}
const HEAT_DOW={zh:['一','','三','','五','',''],en:['Mon','','Wed','','Fri','','']};
const MON_EN=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function _heatLvl(n){return !n?0:n>=7?4:n>=4?3:n>=2?2:1}
function renderHeatmap(byDay,mode){const grid=$('heatGrid'),mon=$('heatMonths'),dows=$('heatDows'),lg=$('heatLgCells');if(!grid)return;
  grid.innerHTML='';mon.innerHTML='';dows.innerHTML='';if(lg)lg.innerHTML='';
  const inner=grid.closest('.heatInner');if(inner)inner.style.setProperty('--heat-gutter',(lang==='en'?28:16)+'px');   // #3: 周标签栏宽度随语言(Mon/Wed/Fri 比 一三五 宽)→ 不再贴住方块
  (HEAT_DOW[lang]||HEAT_DOW.zh).forEach(s=>{const e=document.createElement('span');e.textContent=s;dows.appendChild(e)});
  const oneDay=864e5,half=432e5,today=_startOfDay(Date.now());   // half=12h 垫: 按本地午夜重锚每格, 消除 DST 漂移
  let winStart,winEnd;   // #2: 时间窗. rolling=过去≈53周(回溯今天, 无未来); 具体年=1/1→min(12/31,今天)(当前年裁到今天→根治"右滑未来空白区域")
  if(mode==='rolling'){winEnd=today;winStart=_startOfDay(today-364*oneDay)}
  else{const y=+mode;winStart=_startOfDay(new Date(y,0,1).getTime());winEnd=Math.min(_startOfDay(new Date(y,11,31).getTime()),today)}
  let start=_startOfDay(winStart-((new Date(winStart).getDay()+6)%7)*oneDay+half);   // 回退到含 winStart 那周的周一(列=周)
  let cur=start,curMonth=-1,curW=0;const seg=[];
  for(;cur<=winEnd;cur=_startOfDay(cur+7*oneDay+half)){const wm=new Date(cur).getMonth();
    if(wm!==curMonth){if(curMonth>=0)seg.push({m:curMonth,w:curW});curMonth=wm;curW=0}curW++;
    for(let d=0;d<7;d++){const day=_startOfDay(cur+d*oneDay+half),cell=el('button','heatCell',grid);
      if(day<winStart||day>winEnd){cell.style.visibility='hidden';continue}   // 窗外(含本周未来日) → 占位隐藏保列对齐; 因 winEnd≤今天, 右端永不出现整列未来空白
      if(day===today)cell.classList.add('today');
      const ds=new Date(day),dstr=ds.getFullYear()+'-'+(ds.getMonth()+1)+'-'+ds.getDate();
      const info=byDay.get(dstr),n=info?info.n:0,lv=_heatLvl(n);if(lv)cell.classList.add('l'+lv);
      cell.setAttribute('aria-label',dstr+' · '+n+t('unitMsgs'));
      cell.onclick=()=>{grid.querySelectorAll('.heatCell.sel').forEach(x=>x.classList.remove('sel'));cell.classList.add('sel');showDayDetail(dstr,info)}}}
  if(curMonth>=0)seg.push({m:curMonth,w:curW});
  seg.forEach((s,i)=>{const e=document.createElement('span');e.style.width=(s.w*14-(i===seg.length-1?3:0))+'px';if(s.w>=2)e.textContent=lang==='en'?MON_EN[s.m]:(s.m+1)+'月';mon.appendChild(e)});   // 月份段宽=周数×14px(格距), 末段减末列尾隙 3px → 月份行宽=网格宽(末列精确对齐)
  if(lg)['','l1','l2','l3','l4'].forEach(c=>{const i=document.createElement('i');i.className='heatCell'+(c?' '+c:'');lg.appendChild(i)});
  const hs=$('heatScroll');if(hs)hs.scrollLeft=(mode==='rolling'||(+mode)>=new Date().getFullYear())?hs.scrollWidth:0}   // 滚动定位(Monitor#1修): rolling/当前年→最右(近期活动, 无未来列); 选具体过去年→0(年初/1月, 浏览历史年从头看)
function showDayDetail(dstr,info){const n=info?info.n:0,ti=info?info.ti:0,to=info?info.to:0,steps=info?info.steps:0,cr=info?info.cr:0,cw=info?info.cw:0;
  const row=(k,v)=>'<div class="ddRow"><span class="ddK">'+k+'</span><span class="ddV">'+v+'</span></div>';   // #4: 当日明细=干净的 标签/值 行(替代纯文本块 → 不再与背景卡片视觉重叠)
  gaModal({title:dstr,noCancel:true,okText:t('ok'),
    html:row(t('statMsgs'),n)+row(t('statTokIn'),humanTok(ti))+row(t('statTokOut'),humanTok(to))
        +row(t('statCacheRead'),humanTok(cr))+row(t('statCacheWrite'),humanTok(cw))+row(t('statCacheHit'),_hitRate(cr,ti))
        +row(t('statSteps'),steps)})}
/* #2c 自定义统计时间段: kelivo 风月历选择器(开始/结束字段 + 月历, 周一为列首, 不可选未来) */
const CAL_DOW={zh:['一','二','三','四','五','六','日'],en:['Mo','Tu','We','Th','Fr','Sa','Su']};
let _cr={start:0,end:0,active:'start',view:null};
function _ymd(ts){const d=new Date(ts);return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
function _fmtRange(r){const a=new Date(r[0]),b=new Date(r[1]),cy=new Date().getFullYear();   // 同今年→M/D; 跨年/非今年→Y/M/D
  const wy=a.getFullYear()!==b.getFullYear()||a.getFullYear()!==cy,f=d=>(wy?d.getFullYear()+'/':'')+(d.getMonth()+1)+'/'+d.getDate();
  return f(a)+'–'+f(b)}
function openRangePicker(){const today=_startOfDay(Date.now());
  const s=customRange?_startOfDay(customRange[0]):_startOfDay(today-29*864e5),e=customRange?_startOfDay(customRange[1]):today;
  _cr={start:s,end:e,active:'start',view:new Date(new Date(s).getFullYear(),new Date(s).getMonth(),1)};
  renderRangePicker();$('rangeMask').classList.add('on')}
function closeRangePicker(){$('rangeMask').classList.remove('on')}
function rangeSetActive(which){_cr.active=which;const d=new Date(which==='start'?_cr.start:_cr.end);_cr.view=new Date(d.getFullYear(),d.getMonth(),1);renderRangePicker()}
function rangeMonth(delta){const v=_cr.view;_cr.view=new Date(v.getFullYear(),v.getMonth()+delta,1);renderRangeCal()}
function rangePick(dayTs){if(_cr.active==='start'){_cr.start=dayTs;if(_cr.start>_cr.end)_cr.end=_cr.start;_cr.active='end'}   // 选起→自动切到选止; 始终保持 start≤end
  else{_cr.end=dayTs;if(_cr.end<_cr.start)_cr.start=_cr.end}renderRangePicker()}
function renderRangePicker(){if(!$('rangeMask'))return;
  $('rfStartVal').textContent=_ymd(_cr.start);$('rfEndVal').textContent=_ymd(_cr.end);
  $('rfStart').classList.toggle('on',_cr.active==='start');$('rfStart').setAttribute('aria-pressed',_cr.active==='start');
  $('rfEnd').classList.toggle('on',_cr.active==='end');$('rfEnd').setAttribute('aria-pressed',_cr.active==='end');   // Monitor#6: 两态字段暴露 pressed 态
  renderRangeCal()}
function renderRangeCal(){const mon=$('calMon'),grid=$('calGrid'),dows=$('calDows');if(!grid)return;
  const v=_cr.view,y=v.getFullYear(),m=v.getMonth(),today=_startOfDay(Date.now()),now=new Date();
  mon.textContent=y+'-'+String(m+1).padStart(2,'0');
  dows.innerHTML='';(CAL_DOW[lang]||CAL_DOW.zh).forEach(s=>{const e=document.createElement('span');e.textContent=s;dows.appendChild(e)});
  const cn=$('calNext');if(cn)cn.disabled=(y>now.getFullYear()||(y===now.getFullYear()&&m>=now.getMonth()));   // 不可翻到未来月
  grid.innerHTML='';
  const first=new Date(y,m,1),lead=(first.getDay()+6)%7,startCell=_startOfDay(first.getTime()-lead*864e5);   // 周一为列首
  for(let i=0;i<42;i++){const day=_startOfDay(startCell+i*864e5),dd=new Date(day),out=dd.getMonth()!==m,cell=el('button','calCell',grid);cell.textContent=dd.getDate();
    cell.setAttribute('aria-label',_ymd(day));   // Monitor#3: 每格带完整日期可达标签(对齐热力图同款)
    if(out){cell.classList.add('out');cell.disabled=true}   // Monitor#7: 邻月日非交互(用 ‹ › 翻月)→ 免"低对比却可点"困惑
    if(day>today){cell.classList.add('dis');cell.disabled=true}
    if(day===today)cell.classList.add('today');
    const sel=(day===_cr.start||day===_cr.end);
    if(sel)cell.classList.add('sel');else if(day>_cr.start&&day<_cr.end)cell.classList.add('inr');
    cell.setAttribute('aria-pressed',sel?'true':'false');
    if(!cell.disabled)cell.onclick=()=>rangePick(day)}}
function applyRangePicker(){customRange=[_cr.start,_cr.end];LS.set('customRange',customRange);
  GAT.emit('stats_range',{type:'range_custom',days:Math.round((_cr.end-_cr.start)/864e5)+1});
  statRange='range_custom';LS.set('statRange',statRange);closeRangePicker();renderStatRange()}
/* 颜色模式: system=由 GA.isDark()(权威系统夜间)解析后显式置 data-theme / light / dark */
const THEMES=[{v:'system',k:'themeSystem'},{v:'light',k:'themeLight'},{v:'dark',k:'themeDark'}];
function _sysDark(){try{if(window.GA&&GA.isDark)return !!GA.isDark()}catch(e){}try{return matchMedia('(prefers-color-scheme:dark)').matches}catch(e){}return false}
function applyTheme(){const v=theme==='light'?'light':theme==='dark'?'dark':(_sysDark()?'dark':'light');   // 跟随系统: 用 GA.isDark()(权威系统夜间)显式置 data-theme, 不靠 WebView prefers(部分 OEM 不准)
  document.documentElement.setAttribute('data-theme',v);
  if(typeof FX!=='undefined'&&FX.alive&&emptyEl){FX.destroy();FX.mount(emptyEl)}   // 重挂刷新 --fxRip 等已读入 JS 的主题令牌(canvas 色值不吃 CSS 变量热切)
  const m=document.querySelector('meta[name=theme-color]');if(m)m.setAttribute('content',v==='dark'?'#0a0a0a':'#ffffff')}
function themeLabel(){return t((THEMES.find(x=>x.v===theme)||THEMES[0]).k)}
function refreshThemeVal(){const e=$('themeVal');if(e)e.textContent=themeLabel()}
function openThemeSheet(){const w=$('themeList');w.innerHTML='';
  THEMES.forEach(o=>{const it=el('div','opt'+(theme===o.v?' sel':''),w);
    it.innerHTML='<div class="mid"><div class="nm"></div></div><span class="ck">'+ICO_CK+'</span>';
    it.querySelector('.nm').textContent=t(o.k);
    it.onclick=()=>{theme=o.v;LS.set('theme',o.v);applyTheme();refreshThemeVal();closeSheets();if(curConvo&&!running)renderConvo(curConvo)}});
  openSheet('themeSheet')}
function onOpacityInput(v){floatOpacity=Math.max(0.3,Math.min(1,(+v||90)/100));LS.set('floatOpacity',floatOpacity);
  const ov=$('opacityVal');if(ov)ov.textContent=Math.round(floatOpacity*100)+'%';
  try{GA.setFloatOpacity&&GA.setFloatOpacity(String(floatOpacity))}catch(e){}}
function toggleLang(){setLang(lang==='zh'?'en':'zh')}
function refreshProxyVal(){const e=$('globalProxyVal');if(e){e.textContent=globalProxy||t('proxyUnset');e.style.color=globalProxy?'var(--txt)':''}}
function refreshAppVersion(){const e=$('appVerVal');if(!e)return;   // APK 版本号(来自原生 GA.appVersion 桥, 浏览器预览无桥→显示 —)
  let v=null;try{v=JSON.parse((window.GA&&GA.appVersion&&GA.appVersion())||'null')}catch(_e){}
  e.textContent=(v&&v.name)?('v'+v.name+(v.code?' ('+v.code+')':'')):'—'}
/* 关于: 官网 / GitHub 外链(无 WebViewClient → 必走原生 GA.openUrl 经系统浏览器, 否则会劫持 file:// 页) */
function openWebsite(){try{GA.openUrl&&GA.openUrl('https://github.com/shenhao-stu/GAgent')}catch(e){}}
/* ── 演化融合(issue#1): 把热更新前备份的本地自演化改动, 3-way 合并回当前官方版 ── */
function evoFileCount(st){return st?(st.files!=null?st.files:(st.latest&&st.latest.count)||0):0}   // 唯一计数源=后端 files(全备份去重, 与聚合融合范围一致); 旧后端无 files 退回最新 zip 计数
function refreshEvoBadge(){const e=$('evoBakVal');if(!e)return;e.textContent='';
  if(!(window.GA&&GA.send))return;
  try{const n=evoFileCount(JSON.parse(GA.send('/evo.status')));
    if(n)e.textContent=n+' '+t('evoBak1')}catch(_e){}}
function evoMergeFlow(){   // 演化融合(LLM, v2.3): 确认模型 → 跳转对话 → 发隐藏 /update 式 prompt, 智能体逐文件三路智能合并并透明叙述
  if(!(window.GA&&GA.send)){toast(t('t_checkFail'));return}
  let st;try{st=JSON.parse(GA.send('/evo.status'))}catch(e){st=null}
  const n=evoFileCount(st);
  if(!n){toast(t('evoNoBackup'));return}
  const bks=(st&&st.backups)||[],oldVer=(bks[bks.length-1]||{}).oldVer;   // backups 按 ts 降序 → 末位=最旧, 与聚合融合的 base 来源一致
  const esc=_escd;
  const p=curProvider&&curProvider(),mdl=modelLabel();
  const glyph=isAuto()?AUTO_GLYPH:modelGlyph((active&&active.model)||(p&&p.model)||'',p&&p.type);
  const pv=p?provName(p)||'':'',sub=(!isAuto()&&pv&&pv!==mdl)?esc(pv):'';   // 服务商名作副标(区别于型号); 与型号同名或 auto 时省略
  const desc=esc(t('evoFuseDesc').replace('%v',oldVer||'?').replace('%n',n));
  const chev='<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>';
  const html='<p class="evoDesc">'+desc+'</p>'+
    '<div class="evoLbl">'+esc(t('evoUseModel'))+'</div>'+
    '<button class="evoPick" onclick="evoSwitchModel()" aria-label="'+esc(t('evoSwitchModel'))+'">'+glyph+
      '<span class="epMid"><span class="epNm">'+esc(mdl||t('evoModelNone'))+'</span>'+
        (sub?'<span class="epSub">'+sub+'</span>':'')+'</span>'+
      '<span class="epGo">'+esc(t('evoSwitchModel'))+chev+'</span></button>';
  gaModal({title:t('evoMerge'),html,okText:t('evoStart'),onOk:evoFuseStart});
}
function evoSwitchModel(){$('modalMask').classList.remove('on');openModelSheet();}   // 关确认 → 开模型选择; 选好后用户再点「演化融合」即用新模型
function evoFuseStart(){   // 取隐藏 prompt(后端 evo_prepare 抽备份三路素材) → 回对话页 → 新会话发出(气泡只显示简短标签)
  toast(t('evoMerging'));
  setTimeout(()=>{                                  // 让 toast 先渲染; /evo.fuseprompt 同步抽 zip
    let r;try{r=JSON.parse(GA.send('/evo.fuseprompt'))}catch(e){r=null}
    if(!r||!r.ok){toast((r&&r.error==='no-backup')?t('evoNoBackup'):t('evoFail'));return}
    closeSettings();startNew=true;
    if(!startTask(t('evoMsgLabel'),r.prompt))startNew=false;   // busy/无服务商致发送失败 → 复位 startNew
  },30);
}
function openGithub(){try{GA.openUrl&&GA.openUrl('https://github.com/shenhao-stu/GAgent')}catch(e){}}
/* ── 应用内热更新(OTA) ─────────────────────────────────────────────────────────────────
   机制在原生 Updater(取清单 latest.json / 下载 / 校验 sha256 / 拉起安装器); 此处只做策略+UI。
   不变量: 清单 versionCode 高于本机即提示; 配置天然保留(同签名→Android 原地升级, /data 不动)。*/
let _otaM=null,_otaPoll=null;
function _appCode(){try{return(JSON.parse((window.GA&&GA.appVersion&&GA.appVersion())||'null')||{}).code|0}catch(e){return 0}}
function _appName(){try{return(JSON.parse((window.GA&&GA.appVersion&&GA.appVersion())||'null')||{}).name||''}catch(e){return ''}}
function _otaFetch(){try{const r=GA.otaManifest&&GA.otaManifest();if(!r)return null;const m=JSON.parse(r);return m||null}catch(e){return null}}
function _reflectUpdateBadge(){   // 持久反映"有可用更新"(关于行 + 应用更新页两处徽标; 跳过的版本不再提示)
  const av=LS.get('ota.availCode',0),cur=_appCode(),skip=LS.get('ota.skip',0),show=(av>cur&&av!==skip)?'':'none';
  ['updateBadge','updBadge2'].forEach(id=>{const b=$(id);if(b)b.style.display=show});}
function openUpdatePage(){setNav('updatePanel',t('appUpdate'),'appUpdate')}   // 集中入口: 检查更新(热更新) + 演化融合, 各带说明
function _updateSource(){try{return JSON.parse(GA.appVersion())||{}}catch(e){return {}}}
function renderUpdatePage(){
  const avInfo=_updateSource(), external=avInfo.updatesConfigured===false;
  const row=$('swOtaBeta');if(row)row.closest('.row').style.display=external?'none':'';
  const label=$('rowDoUpdate').querySelector('.k');if(label)label.textContent=external?(lang==='en'?'Releases & downloads':'发布与下载'):t('checkUpdate');
  const hint=$('updatePanel').querySelector('[data-i18n=updHint]');if(hint&&external)hint.textContent=lang==='en'?'Automatic updates are not configured. Visit this app’s GitHub Releases page to check for available downloads. A package with the same identity and signing certificate retains data.':'尚未配置自动更新。请前往本应用的 GitHub Releases 页面查看可用下载；安装同包名、同签名版本可保留数据。';
  const v=$('updCurVer');if(v){let av=null;try{av=JSON.parse((window.GA&&GA.appVersion&&GA.appVersion())||'null')}catch(e){}
    let s=(av&&av.name)?('v'+av.name+(av.code?' ('+av.code+')':'')):'—';
    if(av&&av.channel==='beta')s+=' · '+t('otaChannelBeta');
    v.textContent=s}
  const sw=$('swOtaBeta');if(sw){   // 同步测试通道开关(有效 channel, 含构建戳/设置覆盖)
    let on=false;try{const c=JSON.parse((window.GA&&GA.otaChannel&&GA.otaChannel())||'{}');on=c.channel==='beta'}catch(e){}
    sw.classList.toggle('on',on);sw.setAttribute('aria-checked',on?'true':'false')}
  refreshEvoBadge();_reflectUpdateBadge();}
function toggleOtaBeta(btn){   // 设置覆盖 OTA 通道: on→beta / off→official(显式写 official, 避免 beta 构建戳包关不掉)
  if(!(window.GA&&GA.otaSetChannel))return;
  const want=!(btn&&btn.classList.contains('on'));
  let ok=false;try{const r=JSON.parse(GA.otaSetChannel(want?'beta':'official')||'{}');ok=!!r.ok}catch(e){}
  if(!ok){toast(t('otaChSetFail'));return}
  if(btn){btn.classList.toggle('on',want);btn.setAttribute('aria-checked',want?'true':'false')}
  try{GAT.emit('ota_channel_set',{chan:want?'beta':'official'})}catch(e){}   // 谁在用测试通道(beta 人群规模/流失的分母)
  LS.set('ota.availCode',0);_reflectUpdateBadge();   // 切通道后清徽标, 下次检查再算
  toast(t(want?'otaChannelBeta':'otaChannelOfficial'));
}
function _otaStopPoll(){if(_otaPoll)_otaPoll.stop();_otaPoll=null}
function checkUpdate(manual){
  const source=_updateSource();if(source.updatesConfigured===false){if(manual)GA.openUrl((source.repositoryUrl||'https://github.com/shenhao-stu/GAgent')+'/releases');return}
  if(!(window.GA&&GA.otaManifest)){if(manual)toast(t('t_checkFail'));return}   // 浏览器预览/旧壳无桥
  if(manual)toast(t('t_checking'));
  setTimeout(()=>{                                  // otaManifest 同步阻塞网络(原生后台线程)→ 让 toast 先渲染
    const m=_otaFetch();LS.set('ota.lastCheck',Date.now());
    if(!m){if(manual)toast(t('t_checkFail'));return}
    if(m.error){if(manual){let bc=false;try{bc=JSON.parse((window.GA&&GA.otaChannel&&GA.otaChannel())||'{}').channel==='beta'}catch(e){}toast(t(bc&&/http 404/.test(''+m.error)?'otaClosed':'t_checkFail'))}return}
    if(m.closed){LS.set('ota.availCode',0);_reflectUpdateBadge();if(manual)toast(t('otaClosed'));return}   // beta 通道关闭: 不弹窗、不清零以外逻辑
    _otaM=m;_absorbHeroChips(m);const cur=_appCode(),latest=+m.versionCode||0,has=latest>cur;
    LS.set('ota.availCode',has?latest:0);_reflectUpdateBadge();
    GAT.emit('update_check',{manual:!!manual,has:has,latest:latest,cur:cur,channel:m.channel||''});
    if(has){if(manual||latest!==LS.get('ota.skip',0))showOtaDialog(m,cur)}
    else if(manual){if(latest>0&&latest<cur)toast(t('t_aheadOfChannel'));else toast(t('t_upToDate'))}
  },manual?40:0);
}
function maybeAutoCheck(){try{if(Date.now()-LS.get('ota.lastCheck',0)<216e5)return}catch(e){}checkUpdate(false)}   // 启动节流自动检查(6h)
function showOtaDialog(m,cur){
  $('otaTitle').textContent=t('otaFound');
  $('otaVerLine').textContent='v'+(m.versionName||'?')+'  ·  build '+(m.versionCode||'?');
  const meta=$('otaMeta');meta.innerHTML='';
  const row=(k,v)=>{if(!v)return;const d=el('div','otaMetaRow',meta);d.innerHTML='<span class="omK"></span><span class="omV"></span>';d.querySelector('.omK').textContent=k;d.querySelector('.omV').textContent=v};
  row(t('otaCurrent'),'v'+(_appName()||'?')+' ('+cur+')');
  row(t('otaLatest'),'v'+(m.versionName||'?')+' ('+(m.versionCode||'?')+')');
  row(t('otaSize'),m.size?humanBytes(m.size):'');
  const notes=lang==='en'?(m.notes_en||m.notes||m.notes_zh||''):(m.notes||m.notes_zh||m.notes_en||'');
  const nx=$('otaNotes');
  if(!window.GA_RENDER_LEGACY&&window.renderRich){nx.textContent='';if(notes)nx.appendChild(renderRich(String(notes),{mode:'chat',linkify:false}))}   // F1.1: OTA notes 收口(新增 decorateCode/wrapTables, 与正文同款)
  else nx.innerHTML=notes?md(String(notes)):'';
  $('otaProg').style.display='none';$('otaBarFill').style.width='0%';$('otaPct').textContent='0%';
  _renderOtaBtns(m,'prompt');$('otaMask').classList.add('on');
  setTimeout(()=>{try{$('otaBtns').querySelector('.otaPrimary').focus()}catch(e){}},60);   // a11y: 打开后焦点落到主按钮
}
function _renderOtaBtns(m,st){
  const box=$('otaBtns');box.innerHTML='';
  const primary=(label,on,dis)=>{const b=el('button','otaPrimary',box);b.textContent=label;if(dis)b.disabled=true;else b.onclick=on;return b};
  if(st==='downloading'){primary(t('otaDownloading'),null,true);return}
  if(st==='ready'){primary(t('otaInstall'),_otaInstall);return}
  primary(t('otaUpdateNow'),()=>startOtaDownload(m));                       // prompt 态
  if(!m.mandatory){const sub=el('div','otaSubBtns',box);
    const later=el('button','otaGhost',sub);later.textContent=t('otaLater');later.onclick=closeOta;
    const skip=el('button','otaGhost',sub);skip.textContent=t('otaSkip');
    skip.onclick=()=>{LS.set('ota.skip',+m.versionCode||0);_reflectUpdateBadge();closeOta()}}
}
function startOtaDownload(m){
  if(!(window.GA&&GA.otaDownload)||!m.url){toast(t('otaDownloadFail'));return}
  GAT.emit('update_download',{latest:+m.versionCode||0,channel:m.channel||''});   // OTA 漏斗: 点了"立即更新"(与 update_result 配对算成功率); channel=official/beta 双通道分开算
  $('otaProg').style.display='';_renderOtaBtns(m,'downloading');
  let r='';try{r=GA.otaDownload(String(m.url),String(m.sha256||''))}catch(e){}
  let started=false;try{started=!JSON.parse(r||'{}').error}catch(e){}   // 仅 {ok} 才进轮询; 同步拒绝/抛错/空返回都视为失败(不挂假进度条)
  if(!started){GAT.emit('update_result',{ok:false,stage:'download',error:'start-fail',channel:m.channel||''});toast(t('otaDownloadFail'));$('otaProg').style.display='none';_renderOtaBtns(m,'prompt');return}
  _otaStopPoll();
  _otaPoll=jobPoll((cont,stop)=>{
    let p={};try{p=JSON.parse((GA.otaProgress&&GA.otaProgress())||'{}')}catch(e){}
    const pct=Math.max(0,Math.min(100,+p.pct||0));$('otaBarFill').style.width=pct+'%';
    $('otaPct').textContent=p.state==='verifying'?t('otaVerifying'):pct+'%';
    if(p.state==='ready'){stop();GAT.emit('update_result',{ok:true,stage:'download',latest:+m.versionCode||0,channel:m.channel||''});$('otaBarFill').style.width='100%';$('otaPct').textContent='100%';_renderOtaBtns(m,'ready');toast(t('otaReady'));_otaInstall()}
    else if(p.state==='error'){stop();GAT.emit('update_result',{ok:false,stage:'download',error:String(p.error||'').slice(0,64),channel:m.channel||''});$('otaProg').style.display='none';_renderOtaBtns(m,'prompt');toast(t('otaDownloadFail')+(p.error?'：'+p.error:''))}
    else cont();
  },{interval:500});
}
function _otaInstall(){let r='';try{r=(GA.otaInstall&&GA.otaInstall())||''}catch(e){}
  let _e='';try{_e=JSON.parse(r||'{}').error||''}catch(e){}
  GAT.emit('update_result',{ok:!_e,stage:'install',error:_e?String(_e).slice(0,64):undefined,channel:(_otaM&&_otaM.channel)||''});   // 安装器拉起结果; 真装完由下次启动的 app_version 变化佐证
  if(_e==='need-unknown-sources')toast(t('otaUnknownSrc'))}
function closeOta(){_otaStopPoll();$('otaMask').classList.remove('on')}
function editGlobalProxy(){gaModal({title:t('proxy'),msg:t('proxyPrompt'),input:'http://127.0.0.1:10809',value:globalProxy||'',okText:t('save'),onOk:v=>{
  globalProxy=(v||'').trim();LS.set('proxy',globalProxy);
  try{GA.send('/proxy '+(globalProxy||'clear'))}catch(e){}refreshProxyVal();toast(globalProxy?t('t_proxyUpdated'):t('t_proxyCleared'))}})}
function detectProxy(){const b=$('proxyDetectBtn');if(b&&b._busy)return;if(b)b._busy=true;toast(t('t_detecting'));
  setTimeout(()=>{let res={};try{res=JSON.parse(GA.send('/detectproxy')||'{}')}catch(e){}
    if(b)b._busy=false;const px=res.proxy||'';
    if(px){globalProxy=px;LS.set('proxy',px);try{GA.send('/proxy '+px)}catch(e){}refreshProxyVal();toast(t('t_proxyDetected')+px)}
    else toast(t('t_proxyNone'))},40)}
function humanBytes(n){n=+n||0;return n>=1073741824?(n/1073741824).toFixed(1)+' GB':n>=1048576?(n/1048576).toFixed(1)+' MB':n>=1024?(n/1024).toFixed(0)+' KB':n+' B'}
/* 分类存储(#3): 后端 /storageinfo 返回 cats[{key,size,count}] + clearable; 前端堆叠条 + 分色清单 + 行可点详情 */
const STORE_CATS={chats:{c:'#30D158',ico:ICO_STAT_CHAT},assistant:{c:'#0A84FF',ico:STORE_ICO.bot},
  images:{c:'#BF5AF2',ico:STORE_ICO.img},files:{c:'#FF9F0A',ico:ICO_FILE},cache:{c:'#FF453A',ico:STORE_ICO.cube},
  evobak:{c:'#64D2FF',ico:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 8v13H3V8"/><path d="M1 3h22v5H1z"/><line x1="10" y1="12" x2="14" y2="12"/></svg>'},
  updcache:{c:'#FFD60A',ico:STORE_ICO.cube},
  system:{c:'#5E5CE6',ico:STORE_ICO.cube},logs:{c:'#8E8E93',ico:STORE_ICO.doc}};
function refreshStorage(){let info={};try{info=JSON.parse(GA.send('/storageinfo')||'{}')}catch(e){}
  const cats=info.cats||[],used=info.used!=null?info.used:cats.reduce((s,c)=>s+(c.size||0),0);
  const uh=$('stUsageHome');if(uh)uh.textContent=info.used!=null?humanBytes(used):'';   // 设置首页"存储空间"值
  const num=$('storeUsedNum');if(!num)return;                                           // 仅存储子页存在时渲染详情
  num.textContent=humanBytes(used);
  const an=$('storeAppNum');if(an)an.textContent=humanBytes(info.app_used);              // 应用运行时占用(只读, 不计入"我的数据")
  const bar=$('storeBar'),nz=cats.filter(c=>c.size>0);bar.innerHTML='';bar.style.background='';
  if(nz.length)nz.forEach(c=>{const s=document.createElement('div');s.className='seg';s.style.flexGrow=c.size;s.style.flexBasis='0';s.style.background=(STORE_CATS[c.key]||{}).c||'var(--mut)';bar.appendChild(s)});
  else bar.style.background='var(--surface3)';
  const lg=$('storeLegend');lg.innerHTML='';nz.forEach(c=>{const s=el('div','storeLg',lg);s.innerHTML='<i></i><span></span>';
    s.querySelector('i').style.background=(STORE_CATS[c.key]||{}).c;s.querySelector('span').textContent=t('cat_'+c.key)});
  const cl=$('storeClearable');if(cl)cl.textContent=info.clearable?(t('storeClearable')+humanBytes(info.clearable)):'';
  const list=$('storeCats');list.innerHTML='';
  cats.forEach(c=>{const r=el('button','catRow',list);
    r.innerHTML='<span class="catIco"></span><div class="cmid"><div class="cnm"></div><div class="csz"></div></div><svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>';
    const meta=STORE_CATS[c.key]||{},ico=r.querySelector('.catIco');ico.style.background=meta.c||'var(--mut)';ico.innerHTML=meta.ico||'';
    r.querySelector('.cnm').textContent=t('cat_'+c.key);
    r.querySelector('.csz').textContent=humanBytes(c.size)+' · '+(c.count||0)+t('unitFiles');
    r.onclick=()=>showCatDetail(c)})}
function showCatDetail(c){const msg=t('cat_'+c.key+'_d')+'\n\n'+humanBytes(c.size)+' · '+(c.count||0)+t('unitFiles');
  if(c.key==='cache'&&c.size>0)gaModal({title:t('cat_cache'),msg,okText:t('clearCache'),onOk:doClearCache});
  else if(c.key==='evobak'&&c.size>0)gaModal({title:t('cat_evobak'),msg,danger:true,okText:t('clearBackups'),onOk:doClearBackups});
  else if(c.key==='updcache'&&c.size>0)gaModal({title:t('cat_updcache'),msg,okText:t('clearUpdCache'),onOk:clearUpdCache});
  else gaModal({title:t('cat_'+c.key),msg,noCancel:true,okText:t('ok')})}
function doClearCache(){if(runLocked())return;   // 运行中冻结: agent cwd=temp, /cleartemp 会删掉在飞任务正在生成的产物
  let before=0;try{before=(JSON.parse(GA.send('/storageinfo')||'{}').clearable)||0}catch(e){}
  toast(t('t_clearing'));setTimeout(()=>{try{GA.send('/cleartemp')}catch(e){}GAT.emit('clear_cache',{freed:before});toast(t('t_cacheCleared')+humanBytes(before));refreshStorage()},40)}
function doClearBackups(){let before=0;try{before=((JSON.parse(GA.send('/storageinfo')||'{}').cats||[]).find(c=>c.key==='evobak')||{}).size||0}catch(e){}
  toast(t('t_clearing'));setTimeout(()=>{try{GA.send('/evo.clearbackups')}catch(e){}toast(t('t_backupsCleared')+(before?' '+humanBytes(before):''));refreshStorage();refreshEvoBadge()},40)}
window.clearUpdCache=function(){try{GA.send('/clearupdcache')}catch(e){}setTimeout(refreshStorage,50)}   // 清理热更/OTA 下载残留的安装包缓存(应用运行时占用的一部分)
function toggleSound(e){soundOn=e.classList.toggle('on');e.setAttribute('aria-checked',soundOn?'true':'false');LS.set('soundDone',soundOn);if(soundOn)playDone()}
function toggleKeepAwake(e){keepAwake=e.classList.toggle('on');e.setAttribute('aria-checked',keepAwake?'true':'false');LS.set('keepAwake',keepAwake);try{GA.keepAwake(keepAwake&&running)}catch(e){}}   // 关时若正运行 → 立即清 flag; 开时若正运行 → 立即保持亮屏
function toggleShowThinking(e){showThinking=e.classList.toggle('on');e.setAttribute('aria-checked',showThinking?'true':'false');LS.set('showThinking',showThinking);window.GA_THINKING_ON=showThinking;   // F1.3: 只影响后续渲染(已上屏卡片下次 renderBody 生效), 不触碰存档/发送数据
  try{document.querySelectorAll('.rrThink').forEach(d=>{d.style.display=showThinking?'':'none'})}catch(e){}   // 已上屏块即时显隐(免整页重渲)
  if(showThinking)try{document.querySelectorAll('.step').forEach(c=>{   // 开→ON 补渲: 关着渲染过的 final 卡没生成 .rrThink, 命中 thinking 的置脏重画(仅显示层)
    if(!c._final)return;const sb=c.querySelector('.sb');if(!sb||!sb._rendered||sb.querySelector('.rrThink'))return;
    const _tk=window.extractThinking?extractThinking(c._text||'',true):null;
    if(_tk&&_tk.blocks.length){sb._rendered=false;renderBody(c)}})}catch(e){}}
// 原生 onResume 回推: 检测到常开开着但悬浮窗权限已被撤 → 原生已把真值源(SharedPreferences)落 false 并停服务,
// 前端据此把 UI/LS 同步为关, 消除"开关显示开实则功能死"的假态(单一真值源=原生 SP, 前端只镜像)。
window.gaOnFloatAlways=function(on){ floatAlwaysOn=!!on; LS.set('floatAlwaysOn',floatAlwaysOn);
  const swFA=$('swFloatAlways'); if(swFA){swFA.classList.toggle('on',floatAlwaysOn);swFA.setAttribute('aria-checked',floatAlwaysOn?'true':'false');}
  try{refreshFloat()}catch(e){} };                                                // onResume 回推即重算菜单状态+红点: 授权往返/服务被杀后回前台立刻如实呈现
// 悬浮窗权限引导(原生 toFloat/setFloatAlwaysOn 检出无权限时回调): 先弹说明再跳授权页, 替代裸跳系统页
//   (v4.5 数据: 208 台被拒、46% 再未成功)。「去开启」→ GA.requestOverlayPerm 落往返意图, 用户返回后由原生
//   float_perm_result 闭环并自动接续原动作(button=进悬浮窗 / always_on=补落开关)。埋点: float_perm_guide{choice,from}。
window.gaFloatPermGuide=function(from){from=(from==='always_on')?'always_on':'button';
  gaModal({title:t('floatGuideTitle'),msg:t('floatGuideBody'),okText:t('floatGuideGo'),cancelText:t('floatGuideLater'),
    onOk:()=>{GAT.emit('float_perm_guide',{choice:'go',from:from});try{GA.requestOverlayPerm(from)}catch(e){}},
    onCancel:()=>{GAT.emit('float_perm_guide',{choice:'later',from:from})}});
};
function toggleFloatAlways(e){   // 悬浮窗常开: 开→请求悬浮窗权限并常驻悬浮球; 关→收起。原生 setFloatAlwaysOn 返回实际生效态(权限未授→原生跳授权页并返回 false, 此处回滚开关)
  const want=e.classList.toggle('on');e.setAttribute('aria-checked',want?'true':'false');
  let ok=want;
  try{ const r=GA.setFloatAlwaysOn(want); if(r===false||r==='false')ok=false; }catch(err){ ok=want; }   // 桥缺失(旧包/浏览器 demo)→乐观保留 UI 态
  if(ok!==want){ e.classList.toggle('on',ok);e.setAttribute('aria-checked',ok?'true':'false'); }   // 权限被拒 → 回滚为关
  floatAlwaysOn=ok;LS.set('floatAlwaysOn',floatAlwaysOn);
  try{setTimeout(refreshFloat,300)}catch(e){}                                     // 服务起停是异步的, 略等再读 running(立即读必读到旧值)
}
let _swipeOpen=null;
function closeSwipe(row){if(!row)return;const inner=row.querySelector('.provRowInner'),del=row.querySelector('.provDel');
  if(inner)inner.style.transform='';if(del){del.style.transform='';del.style.opacity=''}row.classList.remove('swiped');if(_swipeOpen===row)_swipeOpen=null}
function renderProvList(){const wrap=$('provList');wrap.innerHTML='';_swipeOpen=null;
  if(!providers.length){wrap.innerHTML='<div class="dwEmpty" style="padding:14px">'+t('noProviderYet')+'</div>';return}
  if(providers.some(p=>p.managed))try{syncPlanModels()}catch(e){}   // 有受管套餐才值得联网
  providers.forEach(p=>{const row=el('div','provRow',wrap);
    
    const del=el('button','provDel',row);del.textContent=t('del');del.setAttribute('aria-label',t('del')+' '+provName(p));
    const inner=el('div','provRowInner',row);
    inner.innerHTML=provGlyph(p)+'<div class="mid"><div class="nm"></div><div class="sub"></div></div><span class="dot'+(p.enabled===false?' off':'')+'"></span>';
    inner.querySelector('.nm').textContent=provName(p);
    inner.querySelector('.sub').textContent=(p.models&&p.models.length?p.models.join(', '):p.model)||t('noModels');
    del.onclick=ev=>{ev.stopPropagation();closeSwipe(row);                                  // 二次确认(危险红按钮)后才真删
      gaConfirm(t('deleteProvider'),t('confirmDelProv').replace('%s',provName(p)),()=>removeProvider(p),true)};
    bindSwipeDelete(row,inner,()=>editProvider(p.id))})}
// 左滑露出删除(iOS/Material 惯例); 阈值过半吸附打开, 否则回弹; 同时仅一行打开; 滑动后不误触发点击进编辑。
function bindSwipeDelete(row,inner,onTap){const REVEAL=88;const del=row.querySelector('.provDel');
  let x0=0,y0=0,dx=0,drag=false,decided=false,horiz=false,moved=false;
  const reveal=p=>{if(!del)return;p=Math.max(0,Math.min(1,p));del.style.opacity=p.toFixed(2);del.style.transform='scale('+(0.7+0.3*p).toFixed(3)+')'};   // 内嵌药丸: 随手势缩放+淡入; p=0 全隐(不透红边), p=1 弹出
  inner.addEventListener('pointerdown',e=>{x0=e.clientX;y0=e.clientY;dx=(_swipeOpen===row)?-REVEAL:0;drag=true;decided=false;horiz=false;moved=false;inner.style.transition='none';if(del)del.style.transition='none'});
  inner.addEventListener('pointermove',e=>{if(!drag)return;const mx=e.clientX-x0,my=e.clientY-y0;
    if(Math.abs(mx)>4||Math.abs(my)>4)moved=true;
    if(!decided&&(Math.abs(mx)>8||Math.abs(my)>8)){decided=true;horiz=Math.abs(mx)>Math.abs(my)}
    if(!horiz)return;e.preventDefault();
    const base=(_swipeOpen===row)?-REVEAL:0;dx=Math.max(-REVEAL,Math.min(0,base+mx));
    inner.style.transform='translateX('+dx+'px)';if(dx<0)row.classList.add('swiped');reveal(-dx/REVEAL)});   // 滑动一开始即直角拼接, 杜绝拖动中露红错位
  const settle=open=>{inner.style.transition='';if(del)del.style.transition='';                       // 放手→交回 CSS 平滑过渡(吸附)
    if(open){if(_swipeOpen&&_swipeOpen!==row)closeSwipe(_swipeOpen);_swipeOpen=row;row.classList.add('swiped');
      inner.style.transform='translateX(-'+REVEAL+'px)';reveal(1);try{navigator.vibrate&&navigator.vibrate(11)}catch(e){}}   // 吸附打开 + 轻触感
    else closeSwipe(row)};
  const end=()=>{if(!drag)return;drag=false;if(horiz)settle(dx<-REVEAL*0.4)};                          // 过 40% 即吸附打开, 更跟手
  inner.addEventListener('pointerup',end);inner.addEventListener('pointercancel',end);
  inner.addEventListener('click',e=>{if(moved&&horiz){e.preventDefault();e.stopPropagation();return}   // 刚滑过→吞掉点击
    if(_swipeOpen===row){closeSwipe(row);return}                                                       // 已打开→点收起
    onTap()})}
function editProvider(id){GAT.emit('view_enter',{view:'provider_edit',edit:!!id});editingId=id;const p=id?providers.find(x=>x.id===id):null;
  editing=p?JSON.parse(JSON.stringify(p)):{id:uid(),type:'oai',name:'',apikey:'',apibase:'',proxy:'',models:[],enabled:true};  // 深拷贝: 子页编辑不直接改 providers[]
  if(!setStack.length)openSettings();                       // onboarding 直达: 先确保设置已开(栈含 home), 返回键可逐级回退
  setNav('provEditPanel',p?(provName(p)||t('editProvider')):t('addProvider'));
  $('provDelBtn').style.display=p?'block':'none';
  $('setvBrand').innerHTML=provGlyph(p||{type:provType});$('setvBrand').style.display='flex';
  provType=p?p.type:'oai';setProvType(provType);
  $('pvName').value=p?provName(p):'';$('pvKey').value=p?p.apikey||'':'';$('pvKey').type='password';$('pvEye').style.color='';
  $('pvBase').value=p?p.apibase||'':'';$('pvProxy').value=p?p.proxy||'':'';$('pvMaxTok').value=p?(p.max_tokens||''):'';
  $('pvModel').value=editing.model||(editing.models&&editing.models[0])||'';
  $('pvMaxRetries').value=p&&p.max_retries!=null?p.max_retries:'';$('pvReadTimeout').value=p&&p.read_timeout!=null?p.read_timeout:'';
  $('pvConnTimeout').value=p&&p.timeout!=null?p.timeout:'';$('pvUA').value=p?uaToVer(p.user_agent):'';   // 高级设置回显(需求#1)
  $('pvEnable').classList.toggle('on',p?p.enabled!==false:true);$('pvEnable').setAttribute('aria-checked',(p?p.enabled!==false:true));
  $('pvResp').classList.toggle('on',!!(p&&p.api_mode==='responses'));$('pvFakeCC').classList.toggle('on',p?!!p.fake_cc:false);   // 新建默认开启透传CC(命中 getoken GA 指纹; 仅 claude 生效)
  updateModelCount();updateUARow();
  $('setv').classList.add('on');$('setv').setAttribute('aria-hidden','false')}
function uaToVer(ua){const m=/claude-cli\/([0-9][0-9.]*)/.exec(ua||'');return m?m[1]:''}                 // 'claude-cli/2.1.85 (external, cli)' → '2.1.85'
function verToUA(v){v=(v||'').trim();return v?('claude-cli/'+v+' (external, cli)'):''}                    // 版本号 → 透传 CC 的完整 UA(llmcore native_ua 同款格式)
function updateUARow(){const r=$('rowUA');if(r)r.style.display=(provType==='claude'&&$('pvFakeCC').classList.contains('on'))?'block':'none'}   // UA 高级项仅在 claude + 透传CC 开启时出现(需求#1)
function setProvType(t){provType=t;document.querySelectorAll('#pvSeg button').forEach(b=>b.classList.toggle('on',b.dataset.t===t));
  if($('setvBrand').style.display!=='none')$('setvBrand').innerHTML=provGlyph({type:t,name:$('pvName').value.trim(),model:(editing&&editing.model)||''});
  const oai=t==='oai';$('rowResp').style.display=oai?'flex':'none';$('rowFakeCC').style.display=oai?'none':'flex';
  $('pvName').placeholder=oai?'gpt-native':'claude-native';$('pvBase').placeholder=oai?'https://api.openai.com/v1':'https://api.anthropic.com';updateUARow()}
function toggleSw(e){const on=e.classList.toggle('on');e.setAttribute('aria-checked',on?'true':'false')}
function toggleEye(){const i=$('pvKey'),on=i.type==='password';i.type=on?'text':'password';$('pvEye').style.color=on?'var(--acc)':''}
function saveProvider(){if(runLocked())return;const v=id=>$(id).value.trim();
  const disp=v('pvName')||(provType==='claude'?'claude-native':'gpt-native');   // 显示名(label)
  const apikey=v('pvKey'),apibase=v('pvBase');
  if(!apikey||!apibase){toast(t('t_fillKeyBase'));return}
  if(!v('pvModel')){toast(t('t_fillModel'));$('pvModel').focus();$('pvModel').scrollIntoView({block:'center'});return}
  readModelDraft();
  const isMk=!!(editing&&editing.fromMk);
  const backendName=isMk?editing.name:disp;                       // fromMk: 后端 /llm 键不可改; 否则跟随显示名
  if(providers.some(p=>p.name===backendName&&p.id!==editingId)){toast(t('t_nameExists'));return}
  const mtRaw=v('pvMaxTok');if(mtRaw&&!/^\d+$/.test(mtRaw)){toast(t('t_maxTokNum'));return}
  for(const _id of ['pvMaxRetries','pvReadTimeout','pvConnTimeout']){const _x=v(_id);if(_x&&!/^\d+$/.test(_x)){toast(t('t_maxTokNum'));return}}   // 高级数值项仅允许数字(需求#1)
  const _uav=v('pvUA');if(provType==='claude'&&$('pvFakeCC').classList.contains('on')&&_uav&&!/^[0-9]+(\.[0-9]+)*$/.test(_uav)){toast(t('uaVerBad'));return}   // UA 仅接受版本号(如 2.1.85)
  let models=(editing&&editing.models)||[];      // 模型来自子页管理(非逗号输入)
  let commitStrip=null;                          // favs/active 的持久化迁移延迟到后端保存成功后(失败路径不落 LS, 防状态分叉)
  if(provType!=='claude'&&models.some(is1m)){    // [1m] 语义仅属 Anthropic 型: 切到 OAI 保存时剥后缀(否则字面 'x[1m]' 直发上游 400 且无入口摘除)
    const strip=m=>m.replace(/\s*\[1m\]$/i,'');
    models=[...new Set(models.map(strip))];
    if(editing){if(editing.model)editing.model=strip(editing.model);   // editing 是编辑期深拷贝草稿, 改它不落盘
      commitStrip=()=>{const pre=editing.id+'::';
        favs=[...new Set(favs.map(k=>k.startsWith(pre)?pre+strip(k.slice(pre.length)):k))];LS.set('favs',favs);
        if(active&&active.pid===editing.id&&active.model){active={...active,model:strip(active.model)};LS.set('active',active)}}}}
  const p={id:editingId||(editing&&editing.id)||uid(),type:provType,name:backendName,label:disp,fromMk:isMk||undefined,   // 类型一律取当前分段值(fromMk 只 pin name 不 pin 类型); 后端按 type 迁移块 var 名(协议类⟺var名)
    apikey,apibase,proxy:v('pvProxy')||undefined,
    model:(editing&&editing.model)||models[0],models,
    enabled:$('pvEnable').classList.contains('on'),api_mode:(provType==='oai'&&$('pvResp').classList.contains('on'))?'responses':undefined,
    fake_cc:provType==='claude'&&$('pvFakeCC').classList.contains('on'),max_tokens:mtRaw?+mtRaw:undefined};
  const _num=id=>{const x=v(id);return x?+x:undefined};                                  // 高级设置(需求#1): 重试次数 / 读取·连接超时 / 透传 UA 版本
  p.max_retries=_num('pvMaxRetries');p.read_timeout=_num('pvReadTimeout');p.timeout=_num('pvConnTimeout');
  if(provType==='claude'&&$('pvFakeCC').classList.contains('on')){const _ua=verToUA(v('pvUA'));if(_ua)p.user_agent=_ua}
  // Persist the draft first; a rejected write must not change selected/usable providers.
  const r=saveProvToMk(p,p.model);
  if(r&&/error|错误|失败|invalid/i.test(r)){toast(t('t_fetchFail')+r);GAT.emit('provider_save_failed',{cat:GAT.errCat(r),msg:GAT.errMsg(r),type:provType});return}
  if(editingId){const i=providers.findIndex(x=>x.id===editingId);providers[i]=p}else providers.push(p);
  LS.set('providers',providers);
  if(!active||active.pid===p.id||!providers.find(x=>x.id===active.pid)){active={pid:p.id,model:p.model};LS.set('active',active)}
  ensureActiveEnabled();
  if(editing&&!isMk&&editing.name&&editing.name!==backendName){try{delProvFromMk(editing.name)}catch(e){}}   // 用户自建服务商改名: 删旧 name 块, 否则孤儿块下次 /config 回读成重复服务商
  if(commitStrip)commitStrip();                  // 后端已确认保存 → 才迁移 favs/active(剥 [1m])
  syncFromBackend();                             // 写后回读 /config(同 delete 路径): 唯一成功点清 cfgLoaded/cfgUnconfigured/cfgFailed 三态, 根治首配后 chip 卡「未配置模型」(#252)
  $('pvKey').value='';applySendEnabled();refreshModelUI();setvBack();
  if(!convos.length)setStatus(modelLabel(),false);
  GAT.emit('provider_saved',{type:p.type,hasModels:!!(models&&models.length)}); // key 配置完成
  toast(t('t_saved')+disp+(models.length?'':t('t_savedFetch')))}
function deleteProviderCur(){if(!editingId)return;const old=providers.find(p=>p.id===editingId);if(!old)return;
  gaConfirm(t('deleteProvider'),t('confirmDelProv').replace('%s',provName(old)),()=>{if(removeProvider(old)){setvBack();toast(t('t_deleted'))}},true)}   // 危险操作二次确认(与左滑删除一致; 删除键已移到底部右侧更易误触)
// 删一个服务商: 写 mykey.py(连带从 Auto 链剔除) → 从 /config 重建 → 必要时切走被删的活跃模型。返回是否成功。
function removeProvider(p){if(anyRunning()){toast(t('t_taskBusy'));return false}   // P3d   // 单一真相源守卫: 运行中不删服务商(否则活跃服务商删除会经 sendLlmSwitch→stopRunClean 静默掐断在飞任务, 违反全仓不变量); 三处入口(左滑/底部删/删最后模型)统一在此拦, 与 selectModel/openConvo 等一致
  const wasActive=active&&active.pid===p.id;
  if(p.name){const r=delProvFromMk(p.name);if(r&&/error|错误|失败|invalid/i.test(r)){toast(t('t_fetchFail')+r);return false}}
  syncFromBackend();                                                  // 唯一读源 /config: providers/Auto 链/active 一并刷新
  if(active&&active.pid==='__auto__'){                                  // 当前在 Auto: 删后按链是否仍有效决定路由(删除同样走 重写mixin→llm_core→渲染)
    if(isFailoverOn())sendLlmSwitch('auto',null,{noAbort:true});        // 链仍≥1 成员 → llm_core 重建修复后的故障转移链(实时生效)
    else{const np=curProvider();active=np?{pid:np.id,model:np.model||(np.models&&np.models[0])}:null;LS.set('active',active);if(np)sendLlmSwitch(np.name,active.model)}   // 链已空 → 退回具体模型, 不留悬空 Auto
  }else if(wasActive&&active){const np=curProvider();if(np)sendLlmSwitch(np.name,active.model)}   // 删的是当前具体服务商 → 切到存活服务商
  return true}

/* ════════════ 模型列表子页 (获取 /v1/models · 增删 · 收藏 · 默认) ════════════ */
let editing=null;
function inferGroup(id){const s=id.toLowerCase();
  if(/(gpt|^o\d|codex|chatgpt|openai)/.test(s))return 'OpenAI';
  if(/claude/.test(s))return 'Claude'; if(/gemini|gemma/.test(s))return 'Gemini';
  if(/grok/.test(s))return 'Grok'; if(/deepseek/.test(s))return 'DeepSeek';
  if(/(qwen|qwq|tongyi)/.test(s))return 'Qwen'; if(/glm|zhipu/.test(s))return 'GLM';
  if(/(kimi|moonshot)/.test(s))return 'Kimi'; if(/minimax|abab/.test(s))return 'MiniMax';
  if(/mimo|xiaomi/.test(s))return 'Xiaomi'; if(/step/.test(s))return 'Step';
  if(/longcat/.test(s))return 'LongCat'; if(/doubao|豆包/.test(s))return 'Doubao'; if(/hunyuan|混元/.test(s))return 'Hunyuan';
  if(/ernie|wenxin|文心/.test(s))return 'ERNIE'; if(/spark|星火|讯飞|iflytek/.test(s))return 'Spark'; if(/baichuan|百川/.test(s))return 'Baichuan';
  if(/cohere|command|aya\b/.test(s))return 'Cohere'; if(/\byi[- ]|\b0?1[ -]?ai\b|零一万物/.test(s))return 'Yi';
  if(/mistral|mixtral|codestral/.test(s))return 'Mistral'; if(/llama|meta-/.test(s))return 'Llama';
  if(/embed/.test(s))return '嵌入'; return '其他'}
function isReasoning(id){return /(think|reason|o1-|o3|o4|-r\b|\br1\b|deepseek-r|qwq)/i.test(id)}
function readModelDraft(){if(!editing)return;
  const model=$('pvModel').value.trim();editing.model=model;
  if(model&&!(editing.models||[]).includes(model))editing.models=[...(editing.models||[]),model]}
function updateModelCount(){const n=(editing&&editing.models||[]).length;$('pvModelCount').textContent=n+t('count');
  const ready=!!($('pvKey').value.trim()&&$('pvBase').value.trim());
  $('rowModels').classList.toggle('dim',!n&&!ready);
  const rf=$('rowFetch');if(rf)rf.classList.toggle('dim',!ready)}   // 填好 Key+Base 即可获取(无需先保存, issue#1)
function fetchModelsInEditor(){if(!editing)return;   // 直接用表单当前值获取并打开列表页, 立即拉取
  const disp=$('pvName').value.trim()||(provType==='claude'?'claude-native':'gpt-native');
  editing.label=disp;if(!editing.fromMk)editing.name=disp;
  editing.apikey=$('pvKey').value.trim();editing.apibase=$('pvBase').value.trim();editing.proxy=$('pvProxy').value.trim();editing.type=provType;
  if(!editing.apikey||!editing.apibase){toast(t('t_fillKeyBaseFirst'));return}
  openModelListPage();fetchModels()}
function openModelListPage(){
  if(!editing)return;
  readModelDraft();
  const disp=$('pvName').value.trim()||(provType==='claude'?'claude-native':'gpt-native');   // 与 saveProvider 同一空值兜底, 杜绝 name/label 分叉
  editing.label=disp; if(!editing.fromMk)editing.name=disp;
  editing.apikey=$('pvKey').value.trim();
  editing.apibase=$('pvBase').value.trim(); editing.proxy=$('pvProxy').value.trim(); editing.type=provType;
  if(!editing.apikey||!editing.apibase){toast(t('t_fillKeyBaseFirst'));return}
  $('mlFetch').classList.remove('spin');                       // 清掉上一个服务商遗留的转圈, 否则会卡住本页的获取
  $('mlTitle').textContent=provName(editing)||t('models'); $('mlSearch').value=''; renderModelList();
  $('modelv').classList.add('on'); $('modelv').setAttribute('aria-hidden','false')}
function closeModelListPage(){$('modelv').classList.remove('on');$('modelv').setAttribute('aria-hidden','true');$('pvModel').value=editing&&editing.model||'';updateModelCount()}
function persistEditing(){updateModelCount();    // 模型增删=即时保存(仅提交模型/名称, 不含未保存的表单字段→杜绝半改泄漏)
  if(editingId){const i=providers.findIndex(x=>x.id===editingId);
    if(i>=0){providers[i].models=editing.models.slice();providers[i].model=editing.model;
      providers[i].label=editing.label;if(!providers[i].fromMk)providers[i].name=editing.name}
    const r=saveProvToMk(providers[i]);
    if(r&&/error|错误|失败|invalid/i.test(r)){                          // 后端拒绝(mykey.py 写入回滚): 不能让 LS/草稿领先真相源——否则模型"已加上"但重启即消失, 且下一次保存又撞同一错(#获取失败 复现根因之一)
      toast(t('t_fetchFail')+r);GAT.emit('provider_save_failed',{cat:GAT.errCat(r),msg:GAT.errMsg(r),type:providers[i].type});
      syncFromBackend();const p=providers.find(x=>x.id===editingId);
      if(p){editing.models=(p.models||[]).slice();editing.model=p.model;updateModelCount()}
      return}
    LS.set('providers',providers);refreshModelUI()}}
function renderModelList(){const body=$('mlBody');const q=$('mlSearch').value.trim().toLowerCase();
  const ms=(editing.models||[]).filter(id=>!q||id.toLowerCase().includes(q));
  if(!ms.length){body.innerHTML='<div class="mlhint">'+(editing.models&&editing.models.length?t('noMatchModel'):t('mlEmpty'))+'</div>';return}
  const groups={};ms.forEach(id=>{const g=inferGroup(id);(groups[g]=groups[g]||[]).push(id)});
  body.innerHTML='';Object.keys(groups).sort().forEach(g=>{
    el('div','mgroup',body).textContent=(g==='嵌入'?t('grpEmbed'):g==='其他'?t('grpOther'):g)+' · '+groups[g].length;
    groups[g].forEach(id=>{const isDef=editing.model===id, key=editing.id+'::'+id, isFav=favs.includes(key);
      const row=el('div','mrow'+(isDef?' def':''),body);
      row.innerHTML=modelGlyph(id,editing.type)+'<span class="mck">'+ICO_CK+'</span><div class="mmid"><div class="mname"></div><div class="mid"></div></div>'+
        (isReasoning(id)?'<span class="mtag rsn">'+t('reasoning')+'</span>':'')+
        (((editingId&&(providers.find(x=>x.id===editingId)||editing).type||editing.type)==='claude')?'<button class="mact m1mBtn'+(is1m(id)?' on':'')+'" aria-label="1M context">1M</button>':'')+   // 1M 开关仅 Anthropic 型; 已保存服务商以磁盘真值判型(防类型未保存时把 [1m] 写进 oai 块)
        '<button class="mact fav'+(isFav?' on':'')+'" aria-label="'+t('fav')+'">'+ICO_HEART+'</button>'+
        '<button class="mact del" aria-label="del">'+ICO_TRASH+'</button>';
      row.querySelector('.mname').textContent=dispModel(id);row.querySelector('.mid').textContent=isDef?t('curDefault'):dispModel(id);
      const b1=row.querySelector('.m1mBtn');if(b1)b1.onclick=e=>{e.stopPropagation();toggle1m(id)};
      row.querySelector('.fav').onclick=e=>{e.stopPropagation();const i=favs.indexOf(key);if(i<0)favs.push(key);else favs.splice(i,1);LS.set('favs',favs);renderModelList()};
      row.querySelector('.del').onclick=e=>{e.stopPropagation();delModel(id)};
      row.onclick=()=>setDefaultModel(id)})})}
function asyncModels(cfg,onResult){            // 异步取模型(获取列表/测试连接): 立即返回, 后台轮询 → UI 不冻, spin 能转
  let resp;try{resp=JSON.parse(GA.send('/models '+JSON.stringify(cfg))||'{}')}catch(e){return onResult({ok:false,error:'bridge'})}
  if(!resp.job){return onResult(resp)}        // 兼容直接返回(老/demo)
  jobPoll((cont)=>{
    let j;try{j=JSON.parse(GA.send('/jobresult '+resp.job)||'{}')}catch(e){return onResult({ok:false,error:'bridge'})}
    if(j.pending){cont();return}
    let res;try{res=JSON.parse(j.result||'{}')}catch(e){res={ok:false,error:'parse'}}
    onResult(res)
  },{interval:400,delay:250,maxTries:150,onTimeout:()=>onResult({ok:false,error:'timeout'})})}
function fetchModels(){if(runLocked())return;
  if($('mlFetch').classList.contains('spin'))return;      // 防连点
  const target=editing;                                   // 快照: 拉取期间用户若切到别的服务商, 结果不能写错对象
  const cfg={name:editing.name,apikey:editing.apikey,apibase:editing.apibase,proxy:editing.proxy||undefined,type:editing.type};
  $('mlFetch').classList.add('spin');
  $('mlBody').innerHTML='<div class="mlhint"><span class="spinDot"></span>'+t('loading')+'</div>';   // 懒加载占位, 让等待可见
  asyncModels(cfg,res=>{
    if(editing!==target)return;                           // 已切换/关闭: 丢弃这次结果(不污染当前对象, 不动 DOM)
    $('mlFetch').classList.remove('spin');
    GAT.emit('key_test',{ok:!!res.ok,cat:res.ok?null:GAT.errCat(res.error),msg:res.ok?null:GAT.errMsg(res.error),type:cfg.type,where:'fetchModels'}); // key 验证结果(脱敏)
    if(!res.ok){renderModelList();toast(t('t_fetchFail')+(res.error||'?'));return}
    const base=m=>m.replace(/\s*\[1m\]$/i,'');
    // 获取是「只增不减」的(手工加的模型不能被一次拉取抹掉)。但这也意味着上游抖一次吐出脏项,
    // 该项就永久留在 mykey 里、再点获取也清不掉。故每次成功拉取顺带清一次通配项:
    // 含 * 或 ? 的 id 是路由匹配规则不是模型(py 侧 _callable_model_id 同源判据), 删它不会误伤任何真实配置。
    const kept=(target.models||[]).filter(m=>!/[*?]/.test(base(m)));
    const dropped=(target.models||[]).length-kept.length;
    const had=new Set(kept.map(base));const add=(res.models||[]).filter(m=>!had.has(base(m)));   // 按基名去重: 已开 1M 的模型重拉不回流裸名副本
    target.models=kept.concat(add);
    if(!target.model&&target.models.length)target.model=target.models[0];
    if(target.model&&/[*?]/.test(base(target.model)))target.model=target.models[0]||undefined;   // 选中项本身就是通配时一并纠正
    persistEditing();renderModelList();
    toast((add.length?(t('t_added')+add.length+t('t_addedModels')):(t('t_latest')+target.models.length+t('t_modelsTotal')))
      +(dropped?t('t_dropGlob')+dropped:''))})}
function addModelManual(){if(runLocked())return;const inp=$('mlAddInput'),id=inp.value.trim();if(!id)return;
  editing.models=editing.models||[];if(editing.models.includes(id)){toast(t('t_exists'));return}
  editing.models.push(id);if(!editing.model)editing.model=id;inp.value='';persistEditing();renderModelList()}
function delModel(id){if(runLocked())return;
  if(editingId&&(editing.models||[]).filter(m=>m!==id).length===0){   // 删最后一个模型=删整个服务商: 空壳服务商无意义; 无名块(如 glm)还会按 'model' 字段复活, 必须整块删(req#3)
    const p=providers.find(x=>x.id===editingId);
    if(p){gaConfirm(t('deleteProvider'),t('confirmDelLastModel'),()=>{closeModelListPage();if(removeProvider(p)){setvBack();toast(t('t_deleted'))}},true);return}
  }
  editing.models=(editing.models||[]).filter(m=>m!==id);
  if(editing.model===id)editing.model=editing.models[0]||undefined;
  if(editingId&&active&&active.pid===editing.id&&active.model===id){active=editing.model?{pid:editing.id,model:editing.model}:null;LS.set('active',active)}  // 删的是当前活跃模型→同步 active
  const fi=favs.indexOf(editing.id+'::'+id);if(fi>=0){favs.splice(fi,1);LS.set('favs',favs)}
  persistEditing();renderModelList()}
function setDefaultModel(id){if(runLocked())return;editing.model=id;
  if(editingId&&active&&active.pid===editing.id){active={pid:editing.id,model:id};LS.set('active',active)}
  persistEditing();renderModelList();toast(t('t_defaultModel')+id)}
/* 1M 上下文 = model id 尾缀 [1m](桌面同约定, llmcore 发送时剥后缀+context-1m beta 头)。唯一写入点=此开关; 展示一律 dispModel+徽章。 */
function is1m(id){return /\[1m\]$/i.test(id||'')}
function m1mBadge(nmEl,id){if(!is1m(id)||!nmEl)return;const s=document.createElement('span');s.className='mtag m1m';s.textContent='1M';nmEl.appendChild(s)}
function toggle1m(id){if(runLocked())return;const to=is1m(id)?id.replace(/\s*\[1m\]$/i,''):id+'[1m]';
  const ms=editing.models||[];
  editing.models=ms.includes(to)?ms.filter(m=>m!==id):ms.map(m=>m===id?to:m);   // 两态并存(重拉裸名等)→合并为目标态, 否则双向 t_exists 死锁
  if(editing.model===id)editing.model=to;                             // 默认模型/活跃模型/收藏 key 同步迁移(与 delModel 同套账)
  if(editingId&&active&&active.pid===editing.id&&active.model===id){active={pid:editing.id,model:to};LS.set('active',active)}
  const fi=favs.indexOf(editing.id+'::'+id);if(fi>=0){favs[fi]=editing.id+'::'+to;favs=[...new Set(favs)];LS.set('favs',favs)}   // 去重: 目标键已收藏时合并, 防重复键致心形关不掉
  persistEditing();renderModelList()}

/* keyboard for non-button interactive (drawer items) */
document.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.classList&&(e.target.classList.contains('dwItem')||e.target.classList.contains('dwSysHead'))){e.preventDefault();e.target.click()}});   // dwSysHead 同享键盘激活(F0.2 分组头可 Tab+Enter/Space 展开)

/* 首启从设备 mykey 自动填充服务商(密钥仅本地, 不进 git); 名称与 mykey 一致 → /llm 可直接切原生配置 */
const SEED_VER=5;                                                 // 改 seed 策略时 +1, 触发旧 mk 服务商迁移
function maybeSeedProviders(){
  const userAdded=providers.filter(p=>!p.fromMk);
  const allMk=providers.length>0&&userAdded.length===0;
  const need=!providers.length||(allMk&&LS.get('seedVer',0)<SEED_VER);   // 空 / 旧的全 mk 列表 → 迁移重 seed
  if(!need)return false;
  try{const res=JSON.parse(GA.send('/config')||'{}');
    if(res.ok&&Array.isArray(res.items)){configItems=res.items;mkMixins=res.items.filter(x=>x.type==='mixin');
    const resProv=res.items.filter(x=>x.type!=='mixin');
    if(resProv.length){
      const picked=resProv; const LBL={};
      const prevByName={};providers.forEach(x=>{if(x.name)prevByName[x.name]=x});   // 重 seed 时保留用户已获取的模型/默认(防"保存后回退", issue#6)
      providers=picked.map(p=>{const pv=prevByName[p.name];
        const models=(pv&&pv.models&&pv.models.length>(p.models||[]).length)?pv.models.slice():(p.models||[]);
        return {...p,fromMk:true,label:LBL[p.name]||(pv&&pv.label)||p.label||p.name,models,model:(pv&&pv.model)||p.model||models[0],fake_cc:!!p.fake_cc};   // claude 默认透传CC
      }).concat(userAdded);  // 保留用户手动加的; 替换旧 mk 列表(但合并已存模型)
      LS.set('providers',providers);LS.set('seedVer',SEED_VER);
      favs=favs.filter(k=>providers.some(p=>k.indexOf(p.id+'::')===0));LS.set('favs',favs);
      const f=providers.find(p=>p.enabled!==false)||providers[0];
      active={pid:f.id,model:f.model||(f.models&&f.models[0])};LS.set('active',active);refreshModelUI();return true}}
  }catch(e){}
  return false}
// 从 /config 重新载入 provider：唯一读源为后端 llmcore(mykey.py)。
// localStorage 中旧 providers 只允许作为写后临时缓存，不参与启动/打开设置页的最终显示。
function refreshProvidersFromLlmc(){
  try{const res=JSON.parse(GA.send('/config')||'{}');
    if(!res.ok||!Array.isArray(res.items)){_lastCfgErr=(res&&res.error)||'config not ok';_lastCfgErrCat=(res&&res.errcat)||'';return false;}
    cfgLoaded=true;cfgFailed=false;cfgUnconfigured=false;   // 成功载入 ⇒ 三态归位(唯一成功点, 含写后 syncFromBackend 路径)
    configItems=res.items;
    const resProv=res.items.filter(x=>x.type!=='mixin');
    const prevByName={};providers.forEach(p=>{if(p.name)prevByName[p.name]=p});
    const LBL={};
    providers=resProv.map(p=>{const pv=prevByName[p.name]||{};const models=Array.isArray(p.models)?p.models.slice():[];
      const model=(p.model&&models.includes(p.model))?p.model:((pv.model&&models.includes(pv.model))?pv.model:models[0]);
      return {...p,fromMk:true,label:p.label||LBL[p.name]||p.name,models,model,fake_cc:p.type==='claude'?(p.fake_cc!==undefined?p.fake_cc:true):p.fake_cc};
    });
    mkMixins=res.items.filter(x=>x.type==='mixin');
    favs=favs.filter(k=>providers.some(p=>k.indexOf(p.id+'::')===0));LS.set('favs',favs);
    if(active){
      if(active.pid==='__auto__'){
        const an=active.auto||'auto';
        const hasAuto=(foCfg&&foCfg.name===an)||mkMixins.some(m=>m.name===an);
        if(!hasAuto)active=null;                                      // auto 不是普通 provider; 成员删减后降级为未选
      }else{const cur=providers.find(p=>p.id===active.pid)||providers.find(p=>prevByName[p.name]&&prevByName[p.name].id===active.pid);
        if(!cur||(active.model&&cur.models&&cur.models.length&&!cur.models.includes(active.model)))active=null}
    }
    if(!active){const f=providers.find(p=>p.enabled!==false)||providers[0];active=f?{pid:f.id,model:f.model||(f.models&&f.models[0])}:null}
    LS.set('active',active);LS.set('providers',providers);
    refreshModelUI();return true}
  catch(e){_lastCfgErr=String((e&&e.message)||e||'config parse error');_lastCfgErrCat='';return false}}

/* /config 失败兜底: 退避重试 + 可见错误态出口, 绝不让 UI 永久停在不可操作的「启动中…」。
   与 modelLabel 超时降级联动, 只维护 cfgFailed 单一错误态; 抽屉/设置/服务商入口本就不受此影响, 保持可用。 */
const _CFG_RETRY_MS=[1000,2000,4000,8000];   // 退避序列(共 4 次), 覆盖引擎冷启慢/一过性卡顿
function _scheduleCfgRetry(n){
  if(cfgLoaded)return;
  if(_lastCfgErrCat==='unconfigured'){_enterCfgUnconfigured();return}   // 未配置≠故障: 不烧重试也不进错误态(#244 96%误报根治)
  if(n>=_CFG_RETRY_MS.length){_enterCfgFail(n);return}
  _cfgRetryTimer=setTimeout(function(){
    if(cfgLoaded)return;
    if(refreshProvidersFromLlmc())_recoverFromCfgFail();
    else _scheduleCfgRetry(n+1);
  },_CFG_RETRY_MS[n]);
}
function _enterCfgUnconfigured(){   // 未配置态(mykey 不存在): 状态栏引导去配置, 点击直跳服务商列表; 绝不发 cfg_load_fail
  cfgUnconfigured=true;cfgFailed=false;   // 单一态互斥: 重试路径中途转未配置时清错误态
  if(_cfgRetryTimer){clearTimeout(_cfgRetryTimer);_cfgRetryTimer=null}
  setStatus(t('notCfgTap'),false);
  const chip=$('modelChipName');if(chip)chip.textContent=t('notCfgTap');
  GAT.emit('cfg_unconfigured',{});
}
function _enterCfgFail(retries){   // 重试用尽: 进入可点击重试的错误态 + 上报失败原因(脱敏)
  cfgFailed=true;
  setStatus(t('cfgFail'),false);
  const chip=$('modelChipName');if(chip)chip.textContent=t('cfgFailShort');
  let cat='other';try{cat=GAT.errCat(_lastCfgErr)}catch(e){}
  GAT.emit('cfg_load_fail',{retries:retries,cat:cat,err:(GAT.errMsg&&GAT.errMsg(_lastCfgErr))||''});
}
function _recoverFromCfgFail(){   // /config 终于成功: 复位错误态并补齐正常启动后续(默认选模型 + 刷新状态/模型 UI)
  cfgFailed=false;cfgUnconfigured=false;
  if(_cfgRetryTimer){clearTimeout(_cfgRetryTimer);_cfgRetryTimer=null}
  try{if(!LS.get('active',null)&&providers.length){const p=providers[0];selectModel(p,p.model||(p.models&&p.models[0])||'')}}catch(e){}
  setStatus(modelLabel(),false);refreshModelUI();
}
function retryCfg(){   // 用户点击状态栏「点此重试」: 立即重试一次, 成功即恢复, 失败回错误态(等用户再点)
  if(cfgLoaded)return;
  if(_cfgRetryTimer){clearTimeout(_cfgRetryTimer);_cfgRetryTimer=null}
  setStatus(t('booting'),true);
  if(refreshProvidersFromLlmc())_recoverFromCfgFail();
  else if(_lastCfgErrCat==='unconfigured')_enterCfgUnconfigured();
  else _enterCfgFail(-1);
}
// 写后统一回读重渲: mykey.py(经 /provider.save|delete 改) → /config → 重建 providers/链 → 重渲开着的视图。
// 单一读源, 与"写"解耦: 调用方只管改 mykey.py, 渲染都走这里(req#5)。
function syncFromBackend(){refreshProvidersFromLlmc();
  if(foCfg&&Array.isArray(foCfg.llm_nos)){const valid=foCfg.llm_nos.filter(n=>providers.some(p=>p.name===n));   // 被删服务商从 foCfg 链一并剔除→前端缓存不与后端链分叉(req#5 单一真相)
    if(valid.length!==foCfg.llm_nos.length){foCfg=Object.assign({},foCfg,{llm_nos:valid});LS.set('foCfg',foCfg)}}
  if($('modelSheet')&&$('modelSheet').classList.contains('on'))renderModels();   // 模型表开着→Auto 链/服务商实时跟随(req#3)
  const pl=$('provListPanel');if(pl&&pl.style.display!=='none')renderProvList()}   // 该面板用 inline display 切换(非 .on class)→滑删后列表实时刷新

/* ───────── analytics (脱敏埋点; 仅上报状态/类别, 绝不上报明文 key/token/baseURL) ───────── */
var GAT=(function(){
  // 错误类事件同时落本地诊断日志(功能1): 供用户主动上传时一并带走; 与埋点(短事件)互补, 日志留完整报错原文(已脱敏)。
  var LOG_EVENTS={render_error:1,task_error:1,cfg_load_fail:1,send_blocked:1,provider_save_failed:1,voice_fail:1,app_crash:1};
  function emit(event,props){try{if(window.GA&&GA.track)GA.track(JSON.stringify({event:event,props:props||{}}))}catch(e){}
    try{if(LOG_EVENTS[event]&&window.GA&&GA.logError){var p=props||{};GA.logError(event,(p.cat?('['+p.cat+'] '):'')+(p.msg||p.reason||p.error||p.err||''))}}catch(e){}}   // p.err: cfg_load_fail 把报错原文放在 err 字段, 不接则镜像日志正文为空(#244 最需要的那条)
  function hasKey(){try{return !!(providers&&providers.some(function(p){return p.apikey&&p.enabled!==false}))}catch(e){return false}}
  function provCount(){try{return (providers||[]).length}catch(e){return 0}}
  function errCat(msg){msg=(msg||'').toString().toLowerCase();
    if(/401|unauthor|invalid.*key|api[_\s-]?key|认证|鉴权|无效.*key|api key/.test(msg))return 'auth_key';
    if(/403|forbidden|permission|quota|额度|余额|insufficient|欠费/.test(msg))return 'quota_perm';
    if(/404|not found|model.*not|不存在|无此模型/.test(msg))return 'model_notfound';
    if(/429|rate[_\s-]?limit|频繁|too many/.test(msg))return 'rate_limit';
    if(/timeout|timed out|超时|network|连接|connection|unreachable|dns|无法访问|代理/.test(msg))return 'network';
    if(/5\d\d|server error|internal|bad gateway|502|503/.test(msg))return 'server';
    return 'other'}
  // 报错原文(供定位用): 先抹掉夹带的密钥/令牌片段, 再压空白截断到 300。
  function errMsg(msg){msg=(msg||'').toString();
    msg=msg.replace(/sk-[A-Za-z0-9_\-]{6,}/g,'sk-***')
           .replace(/(Bearer\s+)[A-Za-z0-9._\-]+/gi,'$1***')
           .replace(/((?:api[_-]?key|key|token|secret|password|authorization)["'\s]*[=:]\s*["']?)[^\s,;"']+/gi,'$1***')
           .replace(/[A-Za-z0-9_\-]{32,}/g,'***');   // 任何超长疑似密钥串
    msg=msg.replace(/\s+/g,' ').trim();return msg?msg.slice(0,300):null}
  return {emit:emit,hasKey:hasKey,provCount:provCount,errCat:errCat,errMsg:errMsg}
})();
// WebUI 未捕获 JS 错误 → 落本地诊断日志(不上报埋点, 避免噪声; 仅供用户主动上传日志时带走定位)。
window.addEventListener('error',function(e){try{if(window.GA&&GA.logError){var m=(e&&e.message)||'';var src=(e&&e.filename)?(' @'+String(e.filename).split('/').pop()+':'+(e.lineno||0)):'';GA.logError('js_error',(GAT.errMsg&&GAT.errMsg(m)||m)+src)}}catch(x){}});
window.addEventListener('unhandledrejection',function(e){try{if(window.GA&&GA.logError){var r=(e&&e.reason);var m=(r&&(r.message||r.toString&&r.toString()))||String(r||'');GA.logError('js_reject',(GAT.errMsg&&GAT.errMsg(m))||m)}}catch(x){}});

/* ───────── 通用操作日志: 记录每一步用户操作并上报首尔 ─────────
   脱敏铁律: 只记元素身份(data-track / id / 标签+短文本)与粗粒度视图; 输入框仅记类型, 绝不取 value。 */
(function(){
  function curView(){try{
    var s=document.getElementById('setv');
    if(s&&s.classList.contains('on')){var e=document.getElementById('provEditPanel');return (e&&e.style.display!=='none')?'provider_edit':'providers';}
    var d=document.getElementById('drawer');if(d&&d.classList.contains('on'))return 'drawer';
    return 'chat';
  }catch(e){return ''}}
  function desc(el){
    if(!el||!el.tagName)return null;
    var dt=el.getAttribute&&el.getAttribute('data-track');if(dt)return dt.toString().slice(0,40);
    var tag=(el.tagName||'').toLowerCase();
    if(tag==='input'||tag==='textarea')return tag+(el.type?(':'+el.type):'');   // 仅类型, 不取值
    var id=el.id?('#'+el.id):'';
    var lbl='';if(tag==='button'||tag==='a'||tag==='label')lbl=(el.textContent||'').trim().replace(/\s+/g,' ').slice(0,24);
    if(!lbl){var al=el.getAttribute&&el.getAttribute('aria-label');if(al)lbl=al.toString().trim().slice(0,24);} // 图标按钮兜底
    var s=(tag+id+(lbl?(' '+lbl):'')).trim();return s?s.slice(0,40):null;
  }
  function nearest(el){var n=el,h=0;while(n&&h<5){var t=(n.tagName||'').toLowerCase();
    if((n.getAttribute&&n.getAttribute('data-track'))||n.id||t==='button'||t==='a'||t==='input'||t==='textarea'||t==='select'||t==='label')return n;
    n=n.parentElement;h++}return el}
  var last=0,lastKey='';
  function log(ev,kind){try{
    var now=Date.now();var d=desc(nearest(ev.target));if(!d)return;
    var k=kind+'|'+d;if(now-last<80&&k===lastKey)return;last=now;lastKey=k;   // 去抖: 同操作 80ms 内合成事件不重复
    var p={target:d,view:curView()};if(kind!=='click')p.kind=kind;
    GAT.emit('ui_action',p);
  }catch(e){}}
  window.addEventListener('click',function(e){log(e,'click')},true);          // 捕获阶段, 每次点击操作
  window.addEventListener('change',function(e){log(e,'change')},true);         // 下拉/勾选/输入提交(仅记类型)
})();

/* ════════════ boot ════════════ */
/* ════════════ 无障碍权限提示(三层: 顶栏状态图标 / 设置行红点 / 齿轮红点) ════════════
   无障碍是 GA 操作其他 app 的核心权限, 单靠模型运行时反馈太弱。分层提示(可关注、不打扰):
   ① 顶栏琥珀状态图标(#a11yStat): 未开启时显示, 轻点弹引导层(说明+去开启)。
   ② 设置「通用」组无障碍行(#a11yRow): 行首红点 + 值「未开启/已开启」。
   ③ 抽屉齿轮红点(#gearDot): 无障碍未开启 或 无线调试未连接, 任一不满足即显示(refreshGearDot 单一真相源)。
   状态来源: GA.a11yEnabled()(原生读 Settings.Secure); 用户从系统设置返回时 MainActivity.onResume→gaOnA11y() 回推刷新。*/
function a11yOn(){try{return !!GA.a11yEnabled()}catch(e){return true}}  // 桥缺失(异常)时视为已开, 不误报
function refreshGearDot(){const gd=$('gearDot');if(gd)gd.hidden=a11yOn()&&adbOn()}   // 齿轮红点单一真相源: refreshA11y/refreshAdb 都只调它, 谁后刷新都收敛到同一结果
/* 悬浮窗三元组(perm 授权 / always 用户意图 / running 球真在屏上)。原桥 floatAlwaysOn() 只答 perm∧always,
   把"用户开了"当成"球在跑", 于是撤权、上屏失败、服务被杀都表现为"开关是开的却没球"且无处可见。
   floatState 直读原生三元组; 桥缺失(旧壳/热更时序)时按"无待办"降级, 与 a11yOn 的不误报惯例一致。*/
// 桥缺失(旧壳 + webui 热更, deploy.sh hotui 是常规动作)时返回 unknown: 既不能报"在跑"(假信息),
// 也不能按 running:false 算待办——那会让老壳红点恒亮且用户无论如何都消不掉。unknown 一律退出判断,
// 与 a11yOn 桥异常视为已开的"不误报"惯例同向。
function floatState(){try{return JSON.parse(GA.floatState())}catch(e){return{unknown:true,perm:true,always:false,running:false,err:''}}}
function floatPending(f){f=f||floatState();return !f.unknown&&(!f.perm||!f.running)}   // 待处理 = 悬浮窗此刻没在为你工作(没授权 / 没开 / 开了却没上屏); 开启常驻即消除, 红点有明确的下一步
function refreshHdrDot(){const d=$('hdrMoreDot');if(d)d.hidden=a11yOn()&&!floatPending()}   // 溢出红点单一真相源: 菜单内任一待处理项即亮(无障碍未开 ∪ 悬浮窗未就绪)
function refreshFloat(){                                                          // 菜单「悬浮窗」项的状态副标 + 红点收敛(gaOnFloatAlways/refreshHome/onResume 都到这里)
  const f=floatState(),v=$('floatStat');
  if(v){const k=f.unknown?'':(!f.perm?'floatStOff':(f.running?'floatStOn':(f.always?'floatStStuck':'floatStReady')));   // 每个态都说得出下一步, 红点才有归属; 桥缺失则整条不出(宁可不说, 不可说错)
    v.textContent=k?t(k):'';v.className='menuVal '+(k==='floatStOn'?'a11yValOn':(k?'a11yValOff':''))}
  refreshHdrDot();
}
function refreshA11y(){                                                            // 唯一收敛点: 顶栏图标/红点/行值/子页(gaOnA11y/refreshHome/开关变更都到这里)
  const on=a11yOn();
  const st=$('a11yStat');if(st)st.hidden=on;                                      // 溢出菜单内状态行(F2.3 由顶栏收进 hdrMoreSheet, id/显隐逻辑不变): 仅未开启时显示
  refreshFloat();                                                                 // 顺带收敛悬浮窗态(内含 refreshHdrDot): 溢出红点两个来源必须同刷, 否则后刷者覆盖前者
  const dot=$('a11yDot');if(dot)dot.hidden=on;                                    // 设置行红点
  refreshGearDot();
  const ap=apStatus(),persist=!!(ap&&ap.hasWriteSecure&&ap.persistEnabled);       // 旧壳桥缺失(ap=null) → 退化为纯开/关两态
  const v=$('a11yVal');if(v){v.textContent=t(on?(persist?'a11yOnPersist':'a11yOn'):'a11yOff');v.className=on?'a11yValOn':'a11yValOff'}
  const p=$('a11yPersistPanel');if(p&&p.style.display!=='none')renderA11yPersistPage();
}
window.a11yStatTap=function(){openA11yPersistPage()};                              // 顶栏琥珀项 → 权限枢纽页(状态+主 CTA+自动保持一站式), 替代旧「说明弹窗+裸跳系统页」
window.gaOnA11y=function(on){try{refreshA11y()}catch(e){}};                        // 原生 onResume 回推; 忽略入参, 统一以 refreshA11y 重读为准
window.openA11ySettings=function(){try{GA.openA11ySettings()}catch(e){}};          // 横幅/设置行/弹窗共用: 跳系统无障碍设置页
/* ════════════ 无线调试自连(app 内自连 ADB, 补无障碍之外的 shell 能力, 结构仿上方无障碍三层) ════════════
   状态来源: GA.adbSelfStatus()(原生读 adb_wifi_enabled + AdbController); 用户从开发者选项返回时 onResume→gaOnAdb() 回推刷新。
   真正的配对/连接由 agent 侧经 droid.adb_pair/adb_connect 完成(bus 已有) — UI 只负责引导 + 状态展示 + 深链, 不自己实现 SPAKE2。*/
function adbOn(){try{return !!JSON.parse(GA.adbSelfStatus()).connected}catch(e){return true}}  // 桥缺失/解析异常时视为已连, 不误报
function refreshAdb(){
  const on=adbOn();
  const dot=$('adbDot');if(dot)dot.hidden=on;                                    // 设置行红点(结构仿 a11yDot): 仅未连接时显示
  refreshGearDot();
  const v=$('adbVal');if(v){v.textContent=t(on?'adbOn':'adbOff');v.className=on?'a11yValOn':'a11yValOff'}
}
window.gaOpenConvo=function(cid){           // 原生 per-cid 通知点击：冷热启动共用，精确切到该会话
  cid=cid==null?'':String(cid);if(!cid)return false;
  const c=convos.find(x=>String(x.id)===cid);if(!c)return false;
  if(c!==curConvo)openConvo(c);return true;
};
window.gaFloatAnswer=function(ans,cid){      // Float ask panel answer bridge；cid 可选，旧单参调用兼容
  ans=String(ans);cid=cid==null?'':String(cid);   // 悬浮面板回答恒为纯文本: 不 JSON.parse(数字/true/null/数组会被误解型)
  if(multi&&cid){const c=convos.find(x=>String(x.id)===cid);if(c&&c!==curConvo)openConvo(c)}   // 把回答送回 ask 所属会话，不能误投当前预览会话
  if(running){window._gaAnswering=1;try{poll()}catch(e){}finally{window._gaAnswering=0}}   // F3: 后台定时器节流 → 本地 running 滞后; 先经既有 poll() 同步一拍(前台同一状态机)。_gaAnswering 门: 这一拍的 finish 不重发"需操作"通知(答题当刻已由原生 notifyTaskEnd 提示过)
  startTask(ans);
};
window.gaOnAdb=function(){try{refreshAdb()}catch(e){}};                            // 原生 onResume 回推; 无参, JS 侧自己重读 adbSelfStatus, 单一真值源
/* 点设置行「无线调试自连」→ 不再弹模态/深链系统页(旧版=开屏打扰), 而是回对话页开一个干净新会话,
   把引导 prompt 预填进输入框(复用编辑重发的填充范式), 用户选模型后自行发送 → GA 走 adb_self_setup SOP
   (droid.adb_pair/adb_connect)协助完成。守单会话不变量: 在飞任务不打断, 仅提示。 */
window.startAdbAssist=function(promptKey){                                        // promptKey 可选: 无障碍页入口传 apAdbAssistPrompt(带配对后回程指引), 默认通用引导
  if(anyRunning()){toast(t('t_taskBusy'));return}   // P3d                                       // 单会话不变量: 在飞任务不打断(同 newConversation/selectModel 守卫)
  closeSettings();newConversation();                                              // 回对话页 + 干净新会话(内部复位空态并 focus, 不 /clear 上一会话)
  inp.value=t(promptKey||'adbAssistPrompt');inp.dispatchEvent(new Event('input'));inp.focus();  // 预填不发送: input 监听只自增高+applySendEnabled, 唯一发送口是 btn.onclick=submit
};
/* ════════════ 无障碍持久化(v2.29 机制 / v2.33 引导重构): WRITE_SECURE_SETTINGS 静默回写, 免 force-stop 后手动重开+10s 倒计时 ════════════
   真值源全在原生(SP 开关 + 系统 secure setting + 权限本身), 前端零缓存零 LS, 每次渲染重读 GA.a11yPersistStatus()。
   页面 = 英雄卡(服务状态+主 CTA) + 保护卡「自动保持开启」+ 折叠高级(电脑 adb)/保活。
   不变量①每态至多一个填充主 CTA: 未开启(已授权→英雄卡「立即恢复」/ 未授权→英雄卡「去开启」);
   已开启未授权→保护卡按钮升为主 CTA(此时它是页面唯一待办)。②授权路径恒可达: 未授权时无论
   selfAdbOn 与否都有按钮(一键开启 / 开始设置→复用 startAdbAssist 无线调试引导), 电脑 adb 恒为折叠兜底。
   旧壳(webui 热更早于 APK)桥缺失 → 服务态退回老桥 a11yOn, 保护卡显示「更新应用后可用」。*/
function apGrantFallback(){let p='io.github.shenhaostu.gagent';try{p=JSON.parse(GA.appVersion()).packageName||p}catch(e){}return 'adb shell pm grant '+p+' android.permission.WRITE_SECURE_SETTINGS'}
function apStatus(){try{return JSON.parse(GA.a11yPersistStatus())}catch(e){return null}}
window.openA11yPersistPage=function(){if(!setStack.length)openSettings();setNav('a11yPersistPanel',t('a11yPerm'),'a11yPerm')};   // 顶栏入口无设置上下文 → 先进设置(返回链自然)
function renderA11yPersistPage(){
  const hero=$('apHeroBody'),card=$('apProtCard'),wrap=$('apProtWrap');if(!hero||!card||!wrap)return;
  const advOpen=!!(wrap.querySelector('details.apFold')||{}).open;   // onResume 等高频重渲染不吞用户展开的「高级」折叠(电脑授权流程天然多次切走切回)
  const st=apStatus();
  const on=st?!!st.a11yOn:a11yOn(),perm=!!(st&&st.hasWriteSecure),en=!!(st&&st.persistEnabled),prot=perm&&en;
  const btn=(id,k,fill)=>'<button id="'+id+'" class="'+(fill?'btnPrimary apPriBtn':'apOutlineBtn')+'">'+_escd(t(k))+'</button>';
  const ico='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="4" r="2" fill="currentColor" stroke="none"/><path d="M4.5 9.5C9 8 15 8 19.5 9.5"/><path d="M12 8v5"/><path d="M8.5 21 12 13.5 15.5 21"/></svg>';
  hero.innerHTML='<div class="apHeroIco '+(on?'ok':'warn')+'">'+ico+'</div>'
    +'<div class="apHeroT">'+_escd(t(on?(prot?'a11yOnPersist':'apStateOnT'):'apStateOffT'))+'</div>'
    +'<div class="apHeroS">'+_escd(t(on?(prot?'apStateProtS':(st?'apStateOnNoProtS':'apStateOnS')):(perm?'apStateOffHealS':'apStateOffS')))+'</div>'
    +(on?'':'<div class="apHeroAct">'+(perm?btn('apHealBtn','apHealNow',1):btn('apGoBtn','apGoEnable',1))+'</div>'
      +(perm?'<button id="apManualBtn" class="apGhostBtn">'+_escd(t('apManualOpen'))+'</button>':''));   // 立即恢复失败时的手动兜底; 未授权态主 CTA 本身就是去系统设置
  const hb=$('apHealBtn');if(hb)hb.onclick=apHealNow;
  const go=$('apGoBtn');if(go)go.onclick=()=>openA11ySettings();
  const mb=$('apManualBtn');if(mb)mb.onclick=()=>openA11ySettings();
  if(!st){card.innerHTML='<p class="hint apCardHint">'+_escd(t('openWithUnavail'))+'</p>';wrap.innerHTML=''}
  else if(perm){   // 已授权: 单开关行(真值渲染, 不留镜像态), 授权细节不再打扰
    card.innerHTML='<div class="row"><span class="k">'+_escd(t('apProtLbl'))+'</span><span class="v">'
      +'<button class="sw'+(en?' on':'')+'" id="swA11yPersist" role="switch" aria-checked="'+(en?'true':'false')+'" aria-label="'+_escd(t('apProtLbl'))+'" onclick="toggleA11yPersist(this)"></button></span></div>';
    wrap.innerHTML='<p class="hint">'+_escd(t(en?'apProtOnHint':'apProtOffHint'))+'</p>'}
  else{
    card.innerHTML='<div class="row"><span class="k">'+_escd(t('apProtLbl'))+'</span><span class="v"><span class="a11yValOff">'+_escd(t('apProtUnset'))+'</span></span></div>'
      +'<div class="apProtBody"><p class="apProtWhy">'+_escd(t('apWhy'))+'</p>'
      +(st.selfAdbOn?btn('apGrantBtn','apGrantSelf',on)   // 自连就绪→一键开启; 服务未开时降为线框(英雄卡「去开启」保持唯一主 CTA)
        :btn('apSetupBtn','apSetup',on)+'<p class="hint apHintTight">'+_escd(t('apSetupHint'))+'</p>')
      +'</div>';
    wrap.innerHTML='<details class="apFold"'+(advOpen?' open':'')+'><summary>'+_escd(t('apAdvPc'))+'</summary>'
      +'<div class="card apAdvCard"><code class="apCmd">'+_escd(st.grantCmd||apGrantFallback())+'</code>'
      +'<button id="apCopyBtn" class="otaGhost apCopyBtn">'+_escd(t('apCopyCmd'))+'</button>'
      +'<p class="hint apHintTight">'+_escd(t('apCmdHint'))+'</p></div></details>';
    const gb=$('apGrantBtn');if(gb){gb.onclick=apGrantSelfAdb;
      if(_apGrantBusy){gb.disabled=true;gb.textContent=t('apGranting')}}   // 45s 授权轮询中重渲染(onResume/切语言)不抹 busy 视觉, 否则再点被防重入静默吞
    const sb=$('apSetupBtn');if(sb)sb.onclick=()=>startAdbAssist('apAdbAssistPrompt');
    const cp=$('apCopyBtn');if(cp)cp.onclick=()=>copyText((st.grantCmd||apGrantFallback()),()=>toast(t('copied')))}
}
window.toggleA11yPersist=function(e){                 // 真值源=原生 SP(不落 LS); v2.33 起开关仅在已授权(perm)态渲染
  const want=e.classList.toggle('on');e.setAttribute('aria-checked',want?'true':'false');
  try{GA.setA11yPersist(want)}catch(err){             // 极端桥异常兜底(全文件桥调用统一防御风格): 回滚开关并提示更新
    e.classList.toggle('on',!want);e.setAttribute('aria-checked',!want?'true':'false');toast(t('openWithUnavail'));return}
  GAT.emit('a11y_persist_toggle',{on:want});
  refreshA11y();
};
function apHealNow(){
  let ok=false;try{ok=GA.a11yReEnableNow()===true}catch(e){}
  toast(t(ok?'apHealed':'apHealFail'));
  refreshA11y();                                      // 成功→顶栏琥珀图标/红点/行值/本页一并收敛(refreshA11y=唯一收敛点)
}
let _apGrantBusy=false;
function apGrantSelfAdb(){
  if(_apGrantBusy)return;
  if(anyRunning()){toast(t('t_taskBusy'));return}   // P3d 同款守卫: agent 在飞可能正占 adb 通道(原生 shell @Synchronized 串行), 锁排队时间不计入其 20s 超时
  let id;try{id=GA.a11yGrantViaSelfAdb()}catch(e){toast(t('apGrantFail'));return}
  if(!id||/^err:/.test(String(id))){toast(t('apGrantFail'));return}
  _apGrantBusy=true;
  const gb=$('apGrantBtn');if(gb){gb.disabled=true;gb.textContent=t('apGranting')}
  const fin=r=>{_apGrantBusy=false;
    if(r==='ok')toast(t('apGrantOk'));
    else toast(t('apGrantFail')+(String(r).indexOf('err:')===0?'：'+String(r).slice(4,84).split('。')[0]:''));   // 详情按句界截断: 原生错误串首句面向用户可行动, 尾句是 agent 词汇(droid.adb_connect 等)不外漏
    refreshA11y()};                                   // 成功: 权限行→已授予, 开关→开(原生已置), 主操作区收敛为就绪态
  jobPoll((cont)=>{
    let r;try{r=GA.a11yGrantResult(id)}catch(e){r='err:bridge'}
    if(r==='pending'){cont();return}
    fin(r);
  },{interval:500,delay:0,maxTries:90,onTimeout:()=>{_apGrantBusy=false;toast(t('apGrantSlow'));refreshA11y()}});   // 45s 只够无争用原生流(重连最坏~82s, 锁排队无上界)→超时不判死刑: 中性提示+复位按钮, 原生任务续跑, 真实终态由下次渲染收敛
}
window.apOpenSys=function(which){let ok=false;try{ok=GA.openAppSysSettings(which)===true}catch(e){}if(!ok)toast(t('openWithUnavail'))};
(function boot(){applyTheme();const r=GA.ready();
  if(!_bootT0)_bootT0=Date.now();   // 首次进入 boot 记时, 供 modelLabel 超时降级
  if(r!=='ok'&&r!=='nokey'){   // I4: 仅引擎真就绪(ok/nokey)才装载会话; ""(启动中)/Py.boot 异常(ERR:前缀)退避重试, 绝不在未就绪态跑会话恢复+写回(临时失忆固化根因)
    if((r||'').indexOf('ERR:')===0&&++_bootErrTries>30){setStatus(t('cfgFailShort'),true);try{bubble('sys',r.slice(4))}catch(e){}return}   // 确定性失败重试~12s仍不就绪→暴露错误(可诊断), 不无限静默转圈; ""(仍启动中)不计数继续等
    setStatus(t('booting'),true);return setTimeout(boot,400)}
  try{const _hs=$('hdrsub');if(_hs&&!_hs._retryWired){_hs._retryWired=1;_hs.addEventListener('click',function(ev){if(cfgUnconfigured&&!cfgLoaded){ev.stopPropagation();ev.preventDefault();openProviders()}else if(cfgFailed){ev.stopPropagation();ev.preventDefault();retryCfg()}})}}catch(e){}   // 错误态下点状态栏=重试(拦截冒泡, 不触发选择模型); 正常态放行到 #hdrtitle
  if(!hasPrivacyConsent())return showPrivacyConsent(boot);
  applySendEnabled();applyI18n();
  userAv=LS.get('userAvatar','person');foCfg=LS.get('foCfg',null);   // 模块初读(行206/210)早于 GA 就绪→只拿到默认; GA 就绪后从设备 kv 重读, 头像与故障转移配置方能跨重启持久
  active=LS.get('active',null);favs=LS.get('favs',[]);sessMeta=LS.get('sessMeta',{});curEff=LS.get('eff','');   // 同因: 模型选择/收藏/会话元/推理档在模块初读(行317)时 Py 未就绪(kv 返回"引擎未就绪"→回退可能已丢的 localStorage)→拿默认。必须在 refreshProvidersFromLlmc 之前从 kv 重读, 否则它见 active=null 会改选首个服务商并覆盖持久值→丢失已选模型(P0-2 根因)
  refreshAvatarRow();
  try{GA.setFloatOpacity&&GA.setFloatOpacity(String(floatOpacity))}catch(e){}   // 把已存透明度同步到原生(重装/启动恢复)
  const _kvc=kvGet('convoStore');   // 权威会话源=设备文件 kv(localStorage 仅启动快取); 顺带剥离历史 /lang 噪声
  if(_kvc===KV_CORRUPT){_recoverCorruptConvos()}                       // 主存截断损坏: 隔离取证→快取抢救→放行(不静默当空覆盖)
  else if(Array.isArray(_kvc)){convos=_stripLangMsgs(_kvc);_convoAuthLoaded=true}   // 权威读成功→放行写回
  else{_convoAuthLoaded=true}                                          // undefined=主存确为空(新装/游客首用): 合法空, 放行写回
  if(!LS.get('emptyMsgMig0',false)){LS.set('emptyMsgMig0',true);   // 一次性: 折叠历史里成串的空 assistant 回合(老版遗留的空气泡/重复气泡)
    let mch=false;convos.forEach(c=>{if(!c.msgs)return;const n=c.msgs.length;c.msgs=c.msgs.filter(m=>!isEmptyAssistant(m));if(c.msgs.length!==n)mch=true});
    if(mch)try{saveConvos()}catch(e){}}
  if(!LS.get('proxyMig0',false)){LS.set('proxyMig0',true);   // 一次性: 清除自动识别遗留的本地死代理(getoken 直连可达; 用户可再在设置里手填), 修复"获取失败 ProxyError"(issue#6)
    if(/127\.0\.0\.1|localhost/i.test(globalProxy||'')){globalProxy='';LS.set('proxy','');try{GA.send('/proxy clear')}catch(e){}}}
  const _noSel=!LS.get('active',null);                       // 记录刷新前是否"从未显式选过模型"
  if(!refreshProvidersFromLlmc())_scheduleCfgRetry(0);       // 启动时从 /config(llmcore→mykey.py) 权威覆盖 provider; 失败→退避重试, 全败进可点重试的错误态(不阻塞后续 boot)
  // 补领必须放在 providers 真正加载**之后**: 领取不能只挂在「登录成功」这一个事件上, 那样只覆盖新注册
  // 的人, **存量已登录用户**(登录早于本功能上线)永远走不到那条回调, 服务商列表里会一直没有 GA Plan。
  // 判据用"本机还没有受管块"而非"是否登录过", 已有块的人一次也不会多调; 服务端三道闸 + reused 幂等
  // 使万一重复也无副作用。
  
  if(_noSel&&providers.length){                                // 首次/未选过模型 → 默认选第一个
    try{const p=providers[0];selectModel(p,p.model||(p.models&&p.models[0])||'')}catch(e){}}
  else if(!_noSel){                                             // 已有选择 → 启动时同步到后端(选择即切换,无延迟apply)
    const a=LS.get('active',null);if(a){
      if(a.pid==='__auto__'){try{sendLlmSwitch(a.auto||'auto',null,{noAbort:true})}catch(e){}}
      else{const p=providers.find(x=>x.id===a.pid);if(p){try{sendLlmSwitch(p.name,a.model,{noAbort:true})}catch(e){}}}}}
  try{const _a=(typeof getAuth==='function')?getAuth():null,_ok=!!(_a&&_a.token&&(!_a.exp||Date.now()<_a.exp));   // boot 校正埋点账号态: 修 token 过期未显式登出留下的脏 user_id
    if(typeof GA!=='undefined'){if(_ok&&_a.userId!=null&&GA.setUser)GA.setUser(String(_a.userId));else if(!_ok&&GA.clearUser)GA.clearUser();}}catch(e){}
  let _li={};try{_li=JSON.parse((window.GA&&GA.launchInfo&&GA.launchInfo())||'{}')}catch(e){}   // src=唤起来源(launcher|float|notif_*), notif=通知总开关(回访钩子可触达面基线)
  GAT.emit('app_open',{ready:r,hasKey:GAT.hasKey(),providers:GAT.provCount(),authed:false,src:_li.src||'?',notif:!!_li.notif}); // 漏斗起点: 启动即知是否已配置/已登录/从哪唤起
  try{GA.send('/lang '+lang)}catch(e){}                        // 同步 UI 语言到后端(状态行文案)
  if(globalProxy)GA.send('/proxy '+globalProxy);              // 同步全局代理到后端(重装后恢复)
  if(r==='nokey'&&!providers.length){setStatus(cfgUnconfigured?t('notCfgTap'):t('noProvider'),false);GAT.emit('onboarding_shown',{reason:'nokey'});openProviders()}   // 首启无 key: 落到服务商列表; 未配置态保住「点此配置」文案不被覆盖(与 model chip 一致)
  else{
    if(r!=='ok'&&r!=='nokey')bubble('sys',r);
    setStatus(modelLabel(),false);
    const j=JSON.parse(GA.poll(0)||'{}');
    if(!convos.length&&j.hist&&j.hist.length){          // 首启无本地会话: 用 Python 归档重建为历史会话
      const c={id:uid(),title:(j.hist[0].prompt||t('newChat')).slice(0,60),ts:Date.now(),msgs:[]};
      j.hist.forEach(h=>{c.msgs.push({role:'user',text:h.prompt||'-'});
        c.msgs.push({role:'assistant',prompt:h.prompt,steps:h.steps||[],final:h.final})});
      convos.push(c);saveConvos()}
    const live=convos.filter(c=>!c.deleted);
    if(!j.running&&j.hist&&j.hist.length){                       // 冷启对账(根治「UI 显 N 步、实际更多步」): 任务在悬浮窗模式下 WebView 被销毁、后台跑到完成 → 会话增量节流落库截断在中途, 而后端 _hist 有完整步骤。逐条按【归属会话 id】对账(后端每条 _hist 已标 convo, 随 chat.json 持久、跨进程被杀仍在)→ 彻底弃用脆弱 prompt 启发(payload 经 goal/附件/override 变换后 ≠ 气泡 raw text, 长多步任务必漏=旧修了个寂寞)
      const seen=new Set();let _ch=false;
      for(let k=j.hist.length-1;k>=0;k--){const h=j.hist[k];   // 从最新往旧: 每会话只由它【最新一条】_hist 对账其末条 assistant, seen 去重防旧条目覆盖同会话的新回合(不变量: 一会话末轮只补一次)
        let tgt=h.convo?live.find(c=>c.id===h.convo):null;     // 首选: 后端持久标记的归属会话 id(精确、跨进程存活、与长度/prompt 无关)
        if(!tgt&&k===j.hist.length-1){                          // 兜底(仅最末条, 仅老数据无 convo 字段时): 内存 active_convo → 末以 prompt 前缀近似(均为升级前遗留条目的退路, 新条目不会走到)
          if(j.active_convo)tgt=live.find(c=>c.id===j.active_convo);
          if(!tgt){const hp=(h.prompt||'').slice(0,400);tgt=live.find(c=>{const ms=c.msgs||[],m=ms[ms.length-1];return m&&m.role==='assistant'&&(m.prompt||'').slice(0,400)===hp})}}
        if(!tgt||seen.has(tgt.id))continue;seen.add(tgt.id);
        const ms=tgt.msgs||[],m=ms[ms.length-1],hs=(h.steps&&h.steps.length)||0;
        const mlen=(m&&m.steps&&m.steps.length)||0;
        const fuller=hs>mlen||(hs&&hs===mlen&&((h.steps[hs-1].text||'').length>(((m.steps||[])[mlen-1]||{}).text||'').length));   // 步数更多 或 同步数但末步文本更长(旧 STEP_CAP=1000 截断把 ask/报告切掉)→ 用后端完整记录补全
        if(m&&m.role==='assistant'&&fuller){   // 仅当后端记录更全才补(不覆盖已完整会话、绝不缩短)
          m.steps=(h.steps||[]).map(s=>({n:s.n,summary:s.summary,text:s.text}));m.final=h.final||m.final;_ch=true}}
      if(_ch)saveConvos();
    }
    let liveC=live.length?live[live.length-1]:null;
    // P3d: multi 冷启先 pollAll 重建 N 路 runs 徽标; 焦点只接一个 live 详情
    let multiSess=[];if(multi){try{const rawA=bridgePollAll();if(rawA){const parsed=parseBridge(rawA);multiSess=Array.isArray(parsed)?parsed:((parsed&&parsed.sessions)||[]);
      for(let i=0;i<multiSess.length;i++){const s=multiSess[i];if(!s||s.cid==null)continue;const id=String(s.cid);const rr=ensureRun(id);rr.running=!!s.running;if(typeof s.gen!=='undefined')rr.gen=s.gen;if(s.ask)rr.ask=s.ask}
      running=anyRunning()}}catch(e){}}
    if(j.running&&j.active_convo){const m=live.find(c=>c.id===j.active_convo);if(m)liveC=m}   // 运行中接续: 精确定位后端 _active_convo
    else if(multi&&multiSess.length){const pref=multiSess.find(s=>s&&s.running);if(pref){const m=live.find(c=>String(c.id)===String(pref.cid));if(m)liveC=m}}
    if(j.running&&liveC&&liveC.msgs){let ms=liveC.msgs;   // 运行中: 末尾「同 prompt」assistant 回合交给实时渲染
      while(ms.length&&ms[ms.length-1].role==='assistant'&&(ms[ms.length-1].prompt||'')===(j.prompt||''))ms.pop()}
    if(liveC){if(j.running||(multi&&ensureRun(liveC.id)&&ensureRun(liveC.id).running)){try{if(multi&&typeof GA.sendC==='function'){/* bind via focus */}else GA.send('/convo.bind '+liveC.id)}catch(e){}}else switchConvo(liveC);renderConvo(liveC)} else{curConvo=null;startNew=true;syncEmpty()}
    const coldRun=j.running||(multi&&liveC&&ensureRun(liveC.id)&&ensureRun(liveC.id).running);
    if(coldRun&&liveC){curConvo=liveC;ensureConvo(j.prompt||'');const ms=curConvo.msgs,lm=ms[ms.length-1];   // 跨重启接续
      if(!(lm&&lm.role==='user'&&lm.text===(j.prompt||''))&&j.prompt){const um={role:'user',text:j.prompt,ts:Date.now()};ms.push(um);userBubble(j.prompt,null,um.ts,um)}
      newTask(j.prompt||'');task.snap=_filesSnap();(j.steps||[]).forEach(setStep);setRunning(true, liveC.id);setStatus(j.status,true);pinReplyTop(task.box);
      if(multi){const rr=ensureRun(liveC.id);rr.task=task;rr.running=true;if(task.box)task.box._cid=liveC.id;task._cid=liveC.id}}
    if(j.cmd_error)bubble('sys',j.cmd_error);
    if(!j.running&&j.ask&&(j.ask.question||(j.ask.candidates&&j.ask.candidates.length))){
      if(!j.active_convo||(liveC&&j.active_convo===liveC.id))renderAskPicker(j.ask);
      else pendingAsk={cid:j.active_convo,ask:j.ask}}
    renderDrawer();scroll(1)}
  if(_li.cid)try{window.gaOpenConvo(_li.cid)}catch(e){}   // 冷启动通知目标最后覆盖自动续接焦点；不存在/已删会话则保持原焦点
  readDeviceState();
  refreshModelUI();
  try{refreshA11y()}catch(e){}                      // 无障碍: 首帧刷新横幅/红点/状态
  try{refreshAdb()}catch(e){}                       // 无线调试自连: 首帧刷新设置行状态
  try{setTimeout(maybeAutoCheck,3000)}catch(e){}   // 启动后台检查更新(节流 6h): 有非跳过新版才弹窗
})();
