/* render.js — F1.1 统一富文本渲染管线（webui 参观层，无构建链，<script> 直引且置于 app.js 之前）
   唯一出口: window.renderRich(text, opt) -> DocumentFragment
     opt.mode : 'chat' 正文 markdown（sanitize→marked→[injectDiffs]→decorateCode→wrapTables→[linkifyFiles]）
                'tool' 工具 stdout/args 原文（不经 marked，包 pre>code 走 decorateCode: 复制+hljs+横滚）
                'live' 流式纯文本（现状等价 textContent；F3 diff-append 在此模式扩展）
     opt.diffs   : extractFileDiffs 产物（仅 chat），经 injectDiffs 回填 diff 卡
     opt.linkify : 仅 chat；false 时跳过 linkifyFiles（文件预览/OTA notes 等非产物入口）
     opt.lang    : 仅 tool；language-xxx 提示（缺省由 hljs 自动检测）
   依赖纪律: sanitize/marked/decorateCode/wrapTables/linkifyFiles/injectDiffs 均在 app.js（运行时晚绑定引用，
   本文件先于 app.js 加载但 renderRich 只在 app.js 就绪后被调用）；DOMPurify/marked/highlight 已 vendored，无 CDN。
   开关: window.GA_RENDER_LEGACY=true 时各出口回退旧路径（本文件不被调用，保留一版）。
   挂点: window.GA_RENDER_HOOKS.katex(F1.4)/.thinking(F1.3) —— fn(rootEl, opt) 就地增强。
   F1.3: extractThinking(s,anchored) 在调用处于 cleanReply/stripTags 之前只读提取 thinking 内容
         （cleanReply 剥离逻辑零改动，thinking 仅进 UI 折叠块，不进存档/不回灌模型——契约不变）；
         opt.thinking=[...]、opt.thinkOpen(live 尾块跟任务态展开)；window.GA_THINKING_ON===false 时整体不渲染（设置页开关）。
   F1.4: KaTeX 懒加载（对齐 ensureHljs 模式，vendor/katex/ 离线 876KB 含 fonts，无 CDN）——
         仅 chat 模式且文本含 $...$/$$...$$ 定界时加载 js+css+mhchem；渲染失败降级保留原文。 */
(function(){
'use strict';
if(window.GA_RENDER_LEGACY===undefined)window.GA_RENDER_LEGACY=false;
if(!window.GA_RENDER_HOOKS)window.GA_RENDER_HOOKS={katex:null,thinking:null};

/* ── F1.3 thinking 提取（只读，不改动 cleanReply/stripTags 的剥离行为）──
   anchored=true : 镜像 cleanReply 的“行首→行尾独立块”口径（final 路径），rest 原样返回不改。
   anchored=false: 镜像 stripTags 的“任意位置闭合块”口径 + 流式未闭合尾块（live 路径），
                   rest 为剥除后的显示文本（未闭合尾块现状会裸露在 live 正文，剥进折叠块属显示层收口）。 */
function extractThinking(s,anchored){
  s=s==null?'':String(s);const blocks=[];let open=false,rest=s;
  if(anchored){
    s.replace(/^[ \t]*<thinking>([\s\S]*?)<\/thinking>[ \t]*$/gim,function(_,b){const v=(b||'').trim();if(v)blocks.push(v);return ''});
  }else{
    rest=s.replace(/<thinking>([\s\S]*?)<\/thinking>/gi,function(_,b){const v=(b||'').trim();if(v)blocks.push(v);return ''});
    rest=rest.replace(/<thinking>([\s\S]*)$/i,function(_,b){const v=(b||'').trim();if(v){blocks.push(v);open=true}return ''});
  }
  return {rest:rest,blocks:blocks,open:open}}
window.extractThinking=extractThinking;

function _i18n(k,fb){try{if(typeof window.t==='function'){const v=window.t(k);if(v&&v!==k)return v}}catch(e){}return fb}

function _thinkHook(root,opt){   // F1.3 默认实现: opt.thinking → 折叠灰蓝块置顶（默认折叠; live 尾块 thinkOpen 时展开）
  if(window.GA_THINKING_ON===false)return;
  const bs=opt&&opt.thinking;if(!bs||!bs.length)return;
  for(let i=bs.length-1;i>=0;i--){
    const d=document.createElement('details');d.className='rrThink ga-card ga-card--thinking';   // F2.1 thinking 入卡(视觉换壳, 提取/折叠逻辑零改动)
    if(opt.thinkOpen&&i===bs.length-1)d.open=true;
    const sm=document.createElement('summary');sm.textContent=_i18n('thinkingLabel','思考过程');d.appendChild(sm);
    const body=document.createElement('div');body.className='rrThinkBody';body.textContent=bs[i];d.appendChild(body);
    root.insertBefore(d,root.firstChild)}}

/* ── F1.4 KaTeX 懒加载 + 定界渲染 ── */
let _katexP=null;
function ensureKatex(){if(window.katex)return Promise.resolve(window.katex);
  if(!_katexP)_katexP=new Promise(function(r){
    const l=document.createElement('link');l.rel='stylesheet';l.href='vendor/katex/katex.min.css';document.head.appendChild(l);
    const s=document.createElement('script');s.src='vendor/katex/katex.min.js';
    s.onload=function(){const m=document.createElement('script');m.src='vendor/katex/mhchem.min.js';   // mhchem 扩展一并（注册进 katex）
      m.onload=m.onerror=function(){r(window.katex||null)};document.head.appendChild(m)};
    s.onerror=function(){r(null)};document.head.appendChild(s)});
  return _katexP}
window.ensureKatex=ensureKatex;

const _MATH_RE=/\$\$([\s\S]+?)\$\$|(?<![\\$\w])\$(?!\s)((?:\\.|[^$\n])+?)(?<![\s\\])\$(?!\d)|\\\[([\s\S]+?)\\\]|\\\(((?:\\[^()]|[^\\\n])+?)\\\)/g;   // display 优先; inline 排除 \$ 转义/词粘连/$5 价格样式; 追加 \[..\] display 与 \(..\) inline 定界（code/pre 跳过口径不变, 渲染失败仍降级原文）
function _hasMathDelim(s){return s.indexOf('$')>-1||s.indexOf('\\(')>-1||s.indexOf('\\[')>-1}   // 定界预检: $ 或 \( \[ 任一命中才走正则/资源加载
function _mathifyText(tn,kx){   // 单文本节点: 命中定界→katex.renderToString 替换; 渲染抛错→保留原文（降级）
  const s=tn.nodeValue||'';if(!_hasMathDelim(s))return;
  _MATH_RE.lastIndex=0;let m,last=0,out=null;
  while((m=_MATH_RE.exec(s))){
    const disp=m[1]!=null||m[3]!=null,tex=m[1]!=null?m[1]:m[2]!=null?m[2]:m[3]!=null?m[3]:m[4];let html=null;
    try{html=kx.renderToString(tex,{displayMode:disp,throwOnError:true,strict:false})}catch(e){html=null}
    if(html==null)continue;   // 失败: 该段原文原样保留
    if(!out)out=document.createDocumentFragment();
    if(m.index>last)out.appendChild(document.createTextNode(s.slice(last,m.index)));
    const sp=document.createElement('span');sp.className=disp?'rrMath rrMathD':'rrMath';sp.innerHTML=html;out.appendChild(sp);
    last=m.index+m[0].length}
  if(!out)return;
  if(last<s.length)out.appendChild(document.createTextNode(s.slice(last)));
  if(tn.parentNode)tn.parentNode.replaceChild(out,tn)}
function _mathifyTree(node,kx){
  if(node.nodeType===3){_mathifyText(node,kx);return}
  if(node.nodeType!==1)return;
  const tag=node.tagName;
  if(tag==='CODE'||tag==='PRE'||tag==='SCRIPT'||tag==='STYLE'||tag==='TEXTAREA'||tag==='A')return;   // 代码/围栏内 $ 不当公式
  if(node.classList&&(node.classList.contains('katex')||node.classList.contains('rrMath')))return;
  const kids=[];for(let c=node.firstChild;c;c=c.nextSibling)kids.push(c);
  for(let i=0;i<kids.length;i++)_mathifyTree(kids[i],kx)}
function _mathText(node){   // 检测用文本: 与 _mathifyTree 同一跳过口径(code/pre 等内的 $ 不算定界, 免误触资源加载)
  if(node.nodeType===3)return node.nodeValue||'';
  if(node.nodeType!==1)return '';
  const tag=node.tagName;
  if(tag==='CODE'||tag==='PRE'||tag==='SCRIPT'||tag==='STYLE'||tag==='TEXTAREA'||tag==='A')return '';
  if(node.classList&&(node.classList.contains('katex')||node.classList.contains('rrMath')))return '';
  let s='';for(let c=node.firstChild;c;c=c.nextSibling)s+=_mathText(c);return s}
function _katexHook(root,opt){   // F1.4 默认实现: 仅 chat；无定界零成本返回（不触发资源加载）
  if((opt&&opt.mode||'chat')!=='chat')return;
  if(!_hasMathDelim(root.textContent||''))return;
  const txt=_mathText(root);if(!_hasMathDelim(txt))return;
  _MATH_RE.lastIndex=0;if(!_MATH_RE.test(txt))return;
  const tops=[];for(let c=root.firstChild;c;c=c.nextSibling)tops.push(c);   // 持节点引用: 异步加载完成时节点已被移入真实 DOM, 引用仍有效（同 decorateCode/hljs 模式）
  ensureKatex().then(function(kx){if(!kx)return;
    for(let i=0;i<tops.length;i++){try{_mathifyTree(tops[i],kx)}catch(e){}}})}

if(!window.GA_RENDER_HOOKS.thinking)window.GA_RENDER_HOOKS.thinking=_thinkHook;
if(!window.GA_RENDER_HOOKS.katex)window.GA_RENDER_HOOKS.katex=_katexHook;

function _protectTexDelims(s){   // marked 把 \( \) \[ \] 当 markdown 转义剥反斜杠 → 非代码段先加倍(\\() 令 marked 还原字面 \( 供 katex 定界; 围栏/行内码段跳过(其内 \( 本就字面保留)
  if(s.indexOf('\\(')<0&&s.indexOf('\\[')<0)return s;
  return s.split(/(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`+[^`\n]*`+)/).map(function(seg,i){
    return i%2?seg:seg.replace(/\\([()\[\]])/g,'\\\\$1')}).join('')}
function _mdHtml(text){   // 单一 sanitize 口径: 复用 app.js md()=marked+DOMPurify; 未载/异常降级纯文本
  try{if(typeof window.md==='function')return window.md(_protectTexDelims(text==null?'':String(text)))}catch(e){}
  const d=document.createElement('div');d.textContent=text==null?'':String(text);return d.innerHTML}

function renderRich(text,opt){
  opt=opt||{};const mode=opt.mode||'chat';
  const frag=document.createDocumentFragment();
  if(mode==='live'){
    const H0=window.GA_RENDER_HOOKS;
    if(opt.thinking&&opt.thinking.length&&H0&&typeof H0.thinking==='function'&&window.GA_THINKING_ON!==false){
      const r0=document.createElement('div');r0.appendChild(document.createTextNode(text==null?'':String(text)));
      try{H0.thinking(r0,opt)}catch(e){}   // F1.3: live 折叠块置于文本前（尾块跟任务态 thinkOpen 展开）
      while(r0.firstChild)frag.appendChild(r0.firstChild);return frag}
    frag.appendChild(document.createTextNode(text==null?'':String(text)));return frag}   // 无 thinking: 纯 TextNode 现状等价
  const root=document.createElement('div');
  if(mode==='tool'){   // F1.2: 工具输出原文非 markdown, 不经 marked(防 stdout 被富文本重排/丢空白), textContent 注入天然免 XSS
    const pre=document.createElement('pre'),code=document.createElement('code');
    pre.className='rrPre';
    if(opt.lang)code.className='language-'+opt.lang;
    code.textContent=text==null?'':String(text);
    pre.appendChild(code);root.appendChild(pre)}
  else{
    let h=_mdHtml(text);
    if(opt.diffs&&opt.diffs.length&&typeof window.injectDiffs==='function'){try{h=window.injectDiffs(h,opt.diffs)}catch(e){}}
    root.innerHTML=h}
  try{if(typeof window.decorateCode==='function')window.decorateCode(root)}catch(e){}
  if(mode==='chat'){
    try{if(typeof window.wrapTables==='function')window.wrapTables(root)}catch(e){}
    if(opt.linkify!==false){try{if(typeof window.linkifyFiles==='function')window.linkifyFiles(root)}catch(e){}}}
  const H=window.GA_RENDER_HOOKS;
  if(H&&typeof H.katex==='function'){try{H.katex(root,opt)}catch(e){}}       // F1.4 挂点: 检测 $...$/$$ 定界后懒加载 KaTeX
  if(H&&typeof H.thinking==='function'){try{H.thinking(root,opt)}catch(e){}} // F1.3 挂点: thinking 折叠块
  while(root.firstChild)frag.appendChild(root.firstChild);
  return frag}
window.renderRich=renderRich;
})();
