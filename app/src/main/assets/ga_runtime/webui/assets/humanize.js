/* humanize.js — 工具行「人话短句」参观层 (PLAN_TOOLROW_HUMANIZE v1.1 H1-H3)
   纯函数模块: 事件对象 → {t:标题, s:副文, plain:是否人话短句} 或 null(null=回退 app.js 原路径, 行为零变化; app.js 调用侧另有 try/catch, 本模块任何异常同样落回原路径)
   开关: window.GA_HUMANIZE_OFF 为真时 app.js 侧整体旁路, 本文件零调用; 删除本 script 标签同效
   优先级链(副文): a.desc(前向预埋, 今天恒空) > 脚本首注释行 > 语义词典(附录A) > 原始命令首行兜底(等宽, 口径B 允许英文)
   红线: 只读消费 tool_events; 不碰 schema/事件层/执行层; 无 DOM/无状态; 文案全走 i18n t(), 由 app.js 侧 _twEsc 统一转义 */
(function(){
'use strict';
function T(k){try{return typeof t==='function'?t(k):k}catch(e){return k}}
function cap(s,n){s=String(s==null?'':s).trim();var i=s.indexOf('\n');if(i>=0)s=s.slice(0,i);return s.length>n?s.slice(0,n)+'…':s}   // 行内 cap: 人话 40 / 兜底原文 30 (H4)
var TOOL_T={file_read:'twReadFile',file_write:'twWriteFile',file_patch:'twPatchFile',update_working_checkpoint:'twCkpt',start_long_term_update:'twLtm',ask_user:'twAsk'};   // 非 code_run 直映现有 i18n 标题词表(H1)
/* ── 附录A 语义词典: 1-20 按优先级顺序匹配(动作类优先); 's'=对归一化 input_summary 前 300 字, 'l'=对脚本首个非注释行 ── */
var DICT=[
  ['s',/droid\.(tap|click|swipe|scroll|drag|long)|input (tap|swipe)/,'hzTap'],
  ['s',/droid\.(shot|screenshot|snap)|screencap/,'hzShot'],
  ['s',/droid\.(text|key|back|home|paste)|input (text|keyevent)/,'hzKey'],
  ['s',/droid\.(dump|ui_detect)|uiautomator/,'hzDump'],
  ['s',/droid\.ocr/,'hzOcr'],
  ['s',/droid\.launch|droid\._fg|am start|monkey -p/,'hzLaunch'],
  ['s',/droid\.(ping|adb_status|adb_connect)/,'hzPing'],
  ['s',/droid\.adb_shell/,'hzAdb'],
  ['s',/droid\.pkgs|pm list/,'hzPkgs'],
  ['s',/droid\.(get_notifications|notif_)/,'hzNotif'],
  ['s',/getprop|dumpsys|settings (get|put)/,'hzSys'],
  ['s',/curl |wget |requests\.|urllib|nslookup/,'hzNet'],
  ['s',/pip3? install/,'hzPip'],
  ['l',/^(ls|find|du|df|stat|tree)\b/,'hzLs'],
  ['l',/^(cat|head|tail|grep|wc|sed|awk)\b/,'hzCat'],
  ['l',/^(cp|mv|rm|mkdir|touch|chmod)\b/,'hzMv'],
  ['s',/echo .*>|tee |cat <</,'hzRedir'],
  ['s',/\b(ps|pgrep|pidof|top|kill)\b/,'hzPs'],
  ['s',/import droid/,'hzDroid'],
  ['s',/inspect|help\(|dir\(|__doc__/,'hzProbe']];
function firstCode(sc){                                      // 脚本首个非注释非空行(兜底副文原料; 跳过 shebang/#/// /docstring 块)
  var ls=String(sc||'').split('\n');
  for(var i=0;i<ls.length;i++){var l=ls[i].trim();
    if(!l||/^#!/.test(l)||/^#/.test(l)||/^\/\//.test(l))continue;
    var m=l.match(/^("""|''')/);
    if(m){var q=m[1];
      if(l.length>3&&l.indexOf(q,3)>=0)continue;             // 单行 docstring
      for(i++;i<ls.length;i++)if(ls[i].indexOf(q)>=0)break;  // 跳过多行 docstring 块
      continue}
    return l}
  return ''}
function commentDesc(sc){                                    // 首注释行提取(实测命中≈0.04%, 仅低成本前向兼容保留, §1 诚实声明)
  var l=String(sc||'').split('\n').map(function(x){return x.trim()}).filter(Boolean)[0]||'',m;
  if(/^#!/.test(l))return'';
  if((m=l.match(/^#\s*(.+)/)))return m[1];
  if((m=l.match(/^\/\/\s*(.+)/)))return m[1];
  if((m=l.match(/^(?:"""|''')\s*(.+?)\s*(?:"""|''')?\s*$/)))return m[1];
  return''}
function title(e,a){                                         // → {t,s,plain} | null; a=app.js 已 _twParse 的入参对象
  a=a||{};var n=(e&&e.name)||'';
  var desc=a.desc!=null?String(a.desc).trim():'';
  if(n!=='code_run'){
    if(!desc)return null;                                    // 非 code_run 无 desc → 原路径(标题本就是 i18n 中文, 副文=文件名/问题原文)
    return{t:TOOL_T[n]?T(TOOL_T[n]):(n||'?'),s:cap(desc,40),plain:true}}
  var ty=String(a.type||'').toLowerCase();
  var tk=ty==='python'?'twRunPy':(ty==='sh'?'twRunSh':'twRun');
  if(desc)return{t:T(tk),s:cap(desc,40),plain:true};         // 优先级 1: desc 预埋(今天恒空, 未来后端加字段自动生效)
  var cd=commentDesc(a.script);
  if(cd)return{t:T(tk),s:cap(cd,40),plain:true};             // 优先级 2: 首注释行
  var sum=String((e&&e.input_summary)||'').slice(0,300),fl=firstCode(a.script);
  for(var i=0;i<DICT.length;i++){var d=DICT[i];
    if(d[0]==='l'?d[1].test(fl):d[1].test(sum))return{t:T(tk),s:T(d[2]),plain:true}}   // 优先级 3: 语义词典(观感主力)
  return{t:T(tk),s:cap(fl||String(a.script||''),30)}}        // 兜底: 中文标题 + 原始命令前 30 字(无 plain → 等宽, 口径B 不计违例)
function result(e){                                          // 错误行短句化(H3): {类别短语} · {错误类型}; 非 error 态 → null 走原路径
  if(!e||e.status!=='error')return null;
  var n=e.name||'';
  var catK=n==='code_run'?'twErrCode':(/^file_/.test(n)?'twErrFile':'twErrRun');
  var r=(typeof _twParse==='function')?_twParse(e.result_summary):{};
  var all=String(e.error||'')+'\n'+String(r.stdout!=null?r.stdout:'');
  var ls=all.split('\n').map(function(x){return x.trim()}).filter(Boolean);
  for(var i=0;i<ls.length;i++){var m=ls[i].match(/^([A-Za-z_.]*(?:Error|Exception))\b/);   // 复用现状 traceback 扫描口径, 只取冒号前裸类型名
    if(m)return T(catK)+' · '+m[1]}
  if(/command not found/i.test(all))return T('twErrExit')+' · '+T('twErrNotFound');
  if(/permission denied/i.test(all))return T('twErrExit')+' · '+T('twErrPerm');
  var mx=all.match(/exit(?: code| status)?[ :=]+(\d+)/i)||all.match(/returncode[ :=]+(\d+)/i);
  if(mx&&mx[1]!=='0')return T('twErrExit')+' · exit '+mx[1];
  if(/timed?[ -]?out|timeout/i.test(all))return T('twErrTimeout')+' · Timeout';
  return T(catK)}                                            // 提取不到类型 → 纯类别短语, 绝不把整段英文塞进行内(V2)
window.GA_HUMANIZE={title:title,result:result};
})();
