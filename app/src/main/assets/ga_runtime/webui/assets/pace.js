/* pace.js — M2 流式 pacing: 缓冲 + 自适应匀速释放 (PLAN_MOTION_CADENCE §3-S2, 纯参观层)
   管线: app.js live 步骤 diff 增量 → feed() 入缓冲 → 单一 rAF 消费环按自适应速率(throttleBasic 思路:
   近 2s 到达速率 + 缓冲偏差纠偏, 基线 ~4-6ms/字符)词级 append 进 DOM(.rrW 复用现有 CSS 淡入, 释放节奏即交错)。
   词切分: Intl.Segmenter('zh',{granularity:'word'}); 缺失(Chromium<87)时整体自动回退原整块路径
   (与 GA_PACE_OFF 同路径, §3-S2 特性检测), 调试可用 GA_PACE_FORCE_CHAR=true 强制字符级继续 pacing。
   硬约束(§3-S2): 终态/abort/完成立即出全量 —— app.js 侧终态整块重渲前 drop()(全文即刻直出),
   stopLive 时 flushAll()(缓冲即刻落 DOM), 禁止「已停止还在打字」。
   开关: window.GA_PACE_OFF=true 一键关闭, feed 决策点实时生效, 关闭瞬间残余缓冲自动 flush。
   契约: 只 append 不重排(append-only); 只消费 app.js 传入的显示文本, 不碰数据层/不回灌模型。
   可测性: 纯函数 splitTokens/calcRate 经 GA_PACE._test 暴露(node 可单测, 不依赖 DOM)。 */
(function(){
'use strict';
var CFG={winMs:2000,     // 到达速率回看窗
         baseCps:200,    // 无到达样本时基线释放速率 5ms/字符(4-6ms 中值)
         minCps:60,      // 尾水最低速率(流停后残余不悬挂)
         maxCps:2000,    // 追赶上限(防缓冲无界)
         tgtRatio:0.35,tgtMin:8,tgtMax:60,  // 目标缓冲 ≈0.35s 到达量, 夹在 8-60 字符(§2 目标缓冲思路)
         catchupS:0.8,   // 缓冲偏差在 ~0.8s 内纠平
         carryCap:40,    // 单帧预算上限(帧率抖动不成块)
         mergeMs:450,    // 淡入(300ms)完成后词 span 并回文本节点, DOM 常驻有界
         fuseChars:4000, // 熔断: 超长增量整块直出(对齐 app.js _LV_FUSE 思路)
         maxDt:64};      // 帧间隔封顶(后台恢复不倾泻)
var seg=null;
try{if(typeof Intl!=='undefined'&&Intl.Segmenter)seg=new Intl.Segmenter('zh',{granularity:'word'})}catch(e){seg=null}

/* ── 纯函数区(可单测) ── */
function splitTokens(s){                     // 文本 → 释放单元数组(join 后与原文逐字节相等)
  s=String(s==null?'':s);if(!s)return[];
  if(seg){var out=[],pend='';
    for(var it=seg.segment(s)[Symbol.iterator](),n=it.next();!n.done;n=it.next()){
      var w=n.value.segment;if(!w)continue;
      if(!w.trim()){if(out.length)out[out.length-1]+=w;else pend+=w;continue}  // 空白粘前词(中文无空白, 西文空格随词走)
      out.push(pend+w);pend=''}
    if(pend)out.push(pend);
    return out}
  return Array.from(s)}                      // 无 Segmenter(仅 FORCE_CHAR 调试路径): 字符级(Array.from 保代理对)
function calcRate(arr,now,bufChars){         // [{t,n}]近2s到达 + 当前缓冲 → 释放速率 chars/sec
  var tot=0;
  for(var i=0;i<arr.length;i++)if(now-arr[i].t<=CFG.winMs)tot+=arr[i].n;
  var ar=tot*1000/CFG.winMs;                 // 固定 2s 窗均值(throttleBasic 回看口径)
  var base=ar>0?ar:CFG.baseCps;
  var tgt=Math.min(CFG.tgtMax,Math.max(CFG.tgtMin,base*CFG.tgtRatio));
  var r=base+(bufChars-tgt)/CFG.catchupS;    // 缓冲高于目标加速追平, 低于目标减速续流
  return Math.min(CFG.maxCps,Math.max(CFG.minCps,r))}

/* ── 调度器(单一 rAF 消费环, 单例) ── */
var streams=new Map(),rafId=0,lastT=0,relChars=0,relSpans=0;   // el(.sb) → 流状态
function _st(el){var s=streams.get(el);if(!s){s={buf:[],chars:0,arr:[],spans:[],carry:0};streams.set(el,s)}return s}
function _enabled(){return !window.GA_PACE_OFF&&(!!seg||!!window.GA_PACE_FORCE_CHAR)}
function active(){                           // app.js feed 决策点: 关态/缺 Segmenter → false(走原 _lvAppend 路径, DOM 同现状)
  if(_enabled())return true;
  if(streams.size)flushAll();                // 运行中被关闭: 残余缓冲立即出, 不留孤儿
  return false}
function _mergeOld(s,el,now){                // 淡入完成的词 span 并回文本节点(DOM 有界; 动画中的不动防跳变)
  var k=0;while(k<s.spans.length&&now-s.spans[k]._pt>CFG.mergeMs)k++;
  if(!k)return;
  for(var i=0;i<k;i++){var sp=s.spans[i];try{if(sp.parentNode)sp.parentNode.replaceChild(document.createTextNode(sp.textContent),sp)}catch(e){}}
  s.spans.splice(0,k);try{el.normalize()}catch(e){}}
function _flushEl(el,s){                     // 立即释放: span 全并回 + 残余缓冲一次性 append(纯文本, 与 renderRich live 语义一致)
  for(var i=0;i<s.spans.length;i++){var sp=s.spans[i];try{if(sp.parentNode)sp.parentNode.replaceChild(document.createTextNode(sp.textContent),sp)}catch(e){}}
  s.spans=[];
  if(s.chars){relChars+=s.chars;try{el.appendChild(document.createTextNode(s.buf.join('')))}catch(e){}}
  s.buf=[];s.chars=0;s.carry=0;try{el.normalize()}catch(e){}}
function _loop(){if(!rafId)rafId=requestAnimationFrame(_frame)}
function _frame(now){
  rafId=0;
  var dt=lastT?Math.min(CFG.maxDt,now-lastT):16;lastT=now;
  var more=false;
  streams.forEach(function(s,el){
    if(!el.isConnected){streams.delete(el);return}          // 步骤卡被重建移除: 丢流
    _mergeOld(s,el,now);
    if(!s.chars){if(s.spans.length)more=true;else streams.delete(el);return}   // 只剩动画中 span: 等并回后自然停环
    s.carry+=calcRate(s.arr,now,s.chars)*dt/1000;
    var frag=null;
    while(s.buf.length&&s.buf[0].length<=s.carry){
      var w=s.buf.shift();s.carry-=w.length;s.chars-=w.length;relChars+=w.length;relSpans++;
      var sp=document.createElement('span');sp.className='rrW';sp.textContent=w;sp._pt=now;
      if(!frag)frag=document.createDocumentFragment();frag.appendChild(sp);s.spans.push(sp)}
    if(frag)try{el.appendChild(frag)}catch(e){}
    if(!s.buf.length)s.carry=0;else if(s.carry>CFG.carryCap)s.carry=CFG.carryCap;
    more=true});
  if(more)_loop();else lastT=0}

/* ── 对 app.js 的接口 ── */
function feed(el,delta){                     // running 活跃步文本增量入缓冲(app.js 已保证 delta 为纯追加尾巴)
  delta=String(delta==null?'':delta);if(!el||!delta)return;
  var s=_st(el),now=(typeof performance!=='undefined'&&performance.now)?performance.now():Date.now();
  var toks=splitTokens(delta);
  for(var i=0;i<toks.length;i++)s.buf.push(toks[i]);
  s.chars+=delta.length;
  s.arr.push({t:now,n:delta.length});
  while(s.arr.length&&now-s.arr[0].t>CFG.winMs)s.arr.shift();
  if(s.chars>CFG.fuseChars){_flushEl(el,s);return}          // 熔断: 巨块不动画
  _loop()}
function flush(el){var s=streams.get(el);if(s){_flushEl(el,s);streams.delete(el)}}
function flushAll(){streams.forEach(function(s,el){_flushEl(el,s)});streams.clear()}   // 硬约束出口: 终态/abort 即刻清空
function drop(el){streams.delete(el)}        // 整块重渲前弃置(全文即将整体重画, 防重复)
function stats(){var b=0,sp=0;streams.forEach(function(s){b+=s.chars;sp+=s.spans.length});
  return{on:_enabled(),seg:!!seg,streams:streams.size,buffered:b,liveSpans:sp,relChars:relChars,relSpans:relSpans}}
window.GA_PACE={active:active,feed:feed,flush:flush,flushAll:flushAll,drop:drop,stats:stats,
  _test:{splitTokens:splitTokens,calcRate:calcRate,CFG:CFG}};
})();
