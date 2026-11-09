/* ═══════════ spring.js — M3 弹簧动效（纯参观层, PLAN_MOTION_CADENCE §3-S3） ═══════════
   闭式解阻尼谐振子（wobble 思路自实现, 按自有代码维护）+ WWDC23 双参 facade:
     mass=1; stiffness=(2π/duration)²; damping=(1−bounce)·4π/duration
   欠阻尼 x(t)=e^(−βt)(x0·cos(ωd t)+((v0+β·x0)/ωd)·sin(ωd t)); 临界/过阻尼分支齐备; 带初速度项。
   retarget 保速: 中途重新调用 gaSpring 时从「当前采样位置+当前速度」重建解析解 → 打断动画速度连续不跳变。
   硬约束: 只写 transform(translate3d/scale)/opacity, 合成器路径; 事件数据零触碰(五禁自查: 纯视觉层)。
   开关: window.GA_SPRING_OFF=true → 全部入口直落终态(与无本文件时的 CSS 回退等价); prefers-reduced-motion 同路径。
   单一 rAF 环消费全部活跃元素(与 pace.js 同款先例, 不动 .rrW/gaWordIn — M2 交接坑④)。 */
(function(){
'use strict';
if(window.gaSpring)return;                                   // 幂等: 热推重复注入零动作

/* ---------- 闭式解核心 ---------- */
function makeSolver(stiff,damp,mass,x0,v0){                  // 返回 t(秒)→[位移x, 速度v]; 位移=相对目标
  var b=damp/(2*mass), w0=Math.sqrt(stiff/mass);
  if(b<w0-1e-9){                                             // 欠阻尼(bounce>0)
    var wd=Math.sqrt(w0*w0-b*b), A=x0, B=(v0+b*x0)/wd;
    return function(t){var e=Math.exp(-b*t),co=Math.cos(wd*t),si=Math.sin(wd*t);
      return [e*(A*co+B*si), e*((B*wd-b*A)*co-(A*wd+b*B)*si)]}}
  if(b<w0+1e-9){                                             // 临界阻尼(bounce=0)
    var C=v0+b*x0;
    return function(t){var e=Math.exp(-b*t);
      return [e*(x0+C*t), e*(C-b*(x0+C*t))]}}
  var q=Math.sqrt(b*b-w0*w0), r1=-b+q, r2=-b-q,              // 过阻尼(bounce<0)
      c1=(v0-r2*x0)/(r1-r2), c2=x0-c1;
  return function(t){var e1=Math.exp(r1*t),e2=Math.exp(r2*t);
    return [c1*e1+c2*e2, c1*r1*e1+c2*r2*e2]}}
function cfg(opts){                                          // WWDC23 双参 → 物理参数(mass=1)
  var dur=(opts&&+opts.duration>0)?+opts.duration:.5,
      bo=(opts&&opts.bounce!=null)?+opts.bounce:.15;
  return {k:Math.pow(2*Math.PI/dur,2), c:(1-bo)*4*Math.PI/dur}}

/* ---------- 元素状态 + 单 rAF 环 ---------- */
var OK={x:1,y:1,scale:1,opacity:1};                          // 白名单: 只允许合成器属性(transform 分量 + opacity)
var EPS={x:.15,y:.15,scale:.0015,opacity:.0015},
    VEPS={x:2,y:2,scale:.02,opacity:.02};                    // 收敛阈值(位移/速度 每秒)
var S=(typeof WeakMap!=='undefined')?new WeakMap():null;
var ACTIVE=[],rafId=0;                                       // Set 语义用数组实现(旧 WebView 兜底)
var _rm=null;try{_rm=matchMedia('(prefers-reduced-motion: reduce)')}catch(e){}
function off(){return !!window.GA_SPRING_OFF||!S||!!(_rm&&_rm.matches)}
function mkSt(){return {p:{},cb:null,hadTr:false}}
function num(v){return Math.round(v*1e4)/1e4}
function apply(el,st){
  var p=st.p,tr='';
  if(p.x||p.y)tr='translate3d('+num(p.x?p.x.cur:0)+'px,'+num(p.y?p.y.cur:0)+'px,0)';
  if(p.scale)tr+=(tr?' ':'')+'scale('+num(p.scale.cur)+')';
  if(tr||st.hadTr){el.style.transform=tr;st.hadTr=!!tr}
  if(p.opacity)el.style.opacity=num(Math.max(0,Math.min(1,p.opacity.cur)))}
function tick(now){
  rafId=0;
  for(var i=ACTIVE.length-1;i>=0;i--){
    var el=ACTIVE[i],st=S.get(el);
    if(!st){ACTIVE.splice(i,1);continue}
    var done=true;
    for(var k in st.p){var p=st.p[k];if(!p.solver)continue;
      var r=p.solver((now-p.t0)/1000);
      p.cur=p.target+r[0];p.vel=r[1];
      if(Math.abs(r[0])<(EPS[k]||.002)&&Math.abs(r[1])<(VEPS[k]||.02)){p.cur=p.target;p.vel=0;p.solver=null}
      else done=false}
    apply(el,st);
    if(done){ACTIVE.splice(i,1);var cb=st.cb;st.cb=null;if(cb)try{cb()}catch(e){}}}
  if(ACTIVE.length)rafId=requestAnimationFrame(tick)}

/* ---------- 公共 API: gaSpring(el, props, {duration,bounce,from,jump,onDone}) ----------
   props: 目标值 {x,y(px), scale, opacity}; from: 仅该属性未在动时设初值(入场);
   jump: 无条件强设当前位置但保留速度(FLIP 反演位); onDone: 全部属性收敛后回调(被更新调用替换即作废)。 */
function gaSpring(el,props,opts){
  if(!el||!el.style||!props)return;
  opts=opts||{};
  if(off()){                                                 // 关态/降级: 直落终态(等价 CSS 回退终点), 不产生中间帧
    if(S){var st0=S.get(el);if(st0){for(var q in st0.p)st0.p[q].solver=null;st0.cb=null}}
    var tr2='',hasT=false;
    for(var k0 in props){if(!OK[k0])continue;
      if(k0==='opacity')el.style.opacity=String(props[k0]);
      else{hasT=true}}
    if(hasT){var xx=props.x||0,yy=props.y||0,ss=(props.scale==null?1:props.scale);
      el.style.transform=((xx||yy)?'translate3d('+xx+'px,'+yy+'px,0) ':'')+(props.scale!=null?'scale('+ss+')':'');}
    if(opts.onDone)try{opts.onDone()}catch(e){}
    return}
  var pc=cfg(opts),st=S.get(el);
  if(!st){st=mkSt();S.set(el,st)}
  var now=performance.now();
  for(var key in props){
    if(!OK[key])continue;
    var target=+props[key],p=st.p[key];
    if(!p)p=st.p[key]={cur:(key==='scale'||key==='opacity')?1:0,vel:0,target:target,solver:null,t0:now};
    var live=!!p.solver;
    if(opts.jump&&opts.jump[key]!=null)p.cur=+opts.jump[key];            // FLIP: 强设位置, 速度保留 → 打断保速
    else if(!live&&opts.from&&opts.from[key]!=null)p.cur=+opts.from[key];// 入场初值: 在动时忽略(retarget 保位保速)
    p.target=target;
    p.solver=makeSolver(pc.k,pc.c,1,p.cur-target,p.vel);
    p.t0=now}
  st.cb=opts.onDone||null;
  apply(el,st);
  if(ACTIVE.indexOf(el)<0)ACTIVE.push(el);
  if(!rafId)rafId=requestAnimationFrame(tick)}
gaSpring.stop=function(el){if(!S)return;var st=S.get(el);if(st){for(var k in st.p)st.p[k].solver=null;st.cb=null}};
gaSpring.clear=function(el){gaSpring.stop(el);if(S)S.delete(el);      // 收敛后交还 CSS 控制权(内联样式清空)
  if(el&&el.style){el.style.transform='';el.style.opacity='';el.style.transition=''}};
gaSpring.get=function(el,k){if(!S)return null;var st=S.get(el);return (st&&st.p[k])?st.p[k].cur:null};
gaSpring.off=off;

/* ---------- 接入点 1: 步骤卡收展 + 列表让位 FLIP ----------
   开: 同步 class 切换(布局立即到位, 逻辑态=classList 单一真相) + .sb 一次性入场走 CSS linear() 烘焙曲线(app.css .sprPop);
   关: 立即收起; 两侧都对后续兄弟做 FLIP——旧视觉位(含在途 transform)→新布局位 jump 反演 + 弹簧归零 → 中途反向打断速度连续。 */
function flipSibs(c){
  var out=[],n=c,depth=0;
  while(n&&depth<3&&out.length<14){                          // 向上 3 层收集后续兄弟(步骤/产物行/后续消息)
    var s=n.nextElementSibling;
    while(s&&out.length<14){out.push(s);s=s.nextElementSibling}
    n=n.parentElement;depth++}
  return out}
function flipMove(sibs,before){
  for(var i=0;i<sibs.length;i++){
    var s=sibs[i],curY=gaSpring.get(s,'y')||0,
        d=before[i]-(s.getBoundingClientRect().top-curY);   // 旧视觉位 − 新布局位(剔除在途 transform)
    if(Math.abs(d)<.5&&!curY)continue;
    (function(sEl){gaSpring(sEl,{y:0},{duration:.5,bounce:.18,jump:{y:d},
      onDone:function(){gaSpring.clear(sEl)}})})(s)}}
window.gaSpringStepToggle=function(c,render){
  var sb=c.querySelector('.sb');
  if(off()||!sb){c.classList.toggle('open');render(c);return}   // 关态: 与原 onclick 完全同路径
  var opening=!c.classList.contains('open'),
      sibs=flipSibs(c),before=[],i;
  for(i=0;i<sibs.length;i++)before[i]=sibs[i].getBoundingClientRect().top;
  if(opening){
    c.classList.add('open');render(c);
    sb.classList.remove('sprPop');void sb.offsetWidth;sb.classList.add('sprPop')}  // 一次性入场(CSS linear() 烘焙, 重触发需回流复位)
  else{
    c.classList.remove('open');
    sb.classList.remove('sprPop');gaSpring.clear(sb)}
  flipMove(sibs,before)};

/* ---------- 接入点 2: 详情弹层(gaModal 卡片)出入场 ----------
   mask 明暗仍走既有 CSS .2s(回退零改动); 卡片被弹簧接管期间禁其 CSS transition 防对打, 收敛后 clear 交还。 */
window.gaSpringModalOpen=function(card){
  if(off()||!card)return;                                    // 关态: 不碰内联样式, CSS scale(.94)→none 原过渡生效
  card.style.transition='none';
  gaSpring(card,{scale:1,opacity:1},{duration:.42,bounce:.28,from:{scale:.92,opacity:.55},
    onDone:function(){gaSpring.clear(card)}})};
window.gaSpringModalClose=function(mask,card){
  mask.classList.remove('on');                               // 语义与原 close 完全一致(mask CSS 渐隐)
  if(off()||!card){gaSpring.clear(card);return}
  card.style.transition='none';
  gaSpring(card,{scale:.94},{duration:.3,bounce:0,
    onDone:function(){gaSpring.clear(card)}})};

window.gaSpring=gaSpring;
gaSpring._test={makeSolver:makeSolver,cfg:cfg};              // node 单测口(纯函数)
})();
