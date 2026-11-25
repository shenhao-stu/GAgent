/* ════════════ iOS GA 桥 (WKUserScript atDocumentStart 注入, 先于 app.js 的 typeof GA 检测) ════════════
   只暴露 iOS 原生实现和共享的引擎方法；WebUI 按平台和桥能力选择入口。
   通道 = window.prompt() 拦截(WKUIDelegate.runJavaScriptTextInputPanel)。
   engine→PyRuntime; native→NativeKit。 */
(function(){
  'use strict';
  if(window.GA) return;
  document.documentElement?.classList.add('iosApp');
  const SENTINEL = '\u0001GABRIDGE';

  function rpc(kind, fn, args){
    try{ return window.prompt(SENTINEL, JSON.stringify({fn: fn, kind: kind, args: args || []})); }
    catch(e){ return null; }
  }
  const eng    = (fn) => (...a) => { const r = rpc('engine', fn, a); return r === null ? '引擎未就绪' : r; };
  const engQ   = (fn) => (...a) => rpc('engine', fn, a);
  const nat    = (fn) => (...a) => { const r = rpc('native', fn, a); return r === null ? '' : r; };
  const natV   = (fn) => (...a) => { rpc('native', fn, a); };
  window.GA = {
    platform: 'ios',

    /* ── 引擎协议 (嵌入式 CPython) ── */
    selectModel: eng('select_model'), phoneTakeover: eng('phone_takeover'),
    ready:   eng('ready'),   send:  eng('send'),   abort: () => { rpc('engine', 'abort', []); },
    poll:    engQ('poll'),   pollC: (cid, since) => engQ('poll2')(cid, since), pollAll: engQ('poll_all'),
    sendC:   (cid, t) => eng('send2')(cid, t),   abortC: (cid) => { rpc('engine', 'abort2', [cid]); },
    caps:    () => { const r = rpc('engine', 'caps', []); return r === null ? '{}' : r; },

    /* ── 原生实现 (Swift NativeKit) ── */
    isDark:        () => rpc('native', 'isDark', []) === 'true',
    appVersion:    nat('appVersion'),   launchInfo: nat('launchInfo'),
    boardSetup:    natV('boardSetup'), boardStatus: nat('boardStatus'),
    offAsrStatus: () => nat('offAsrStatus')(document.documentElement.lang),
    offAsrStart: nat('offAsrStart'), offAsrPoll: nat('offAsrPoll'),
    offAsrStop: nat('offAsrStop'), offAsrCancel: nat('offAsrCancel'),
    networkProxy:  nat('networkProxy'),
    openUrl:       natV('openUrl'),
    notify:        natV('notify'),      speak: nat('speak'), speakStop: natV('speakStop'),
    keepAwake:     natV('keepAwake'),   track: natV('track'),
    setUser:       natV('setUser'),     clearUser: natV('clearUser'), logError: natV('logError'),
    saveUpload:    nat('saveUpload'),   openFile: nat('openFile'), previewFile: nat('previewFile'),
    saveToGallery: nat('saveToGallery'), saveImageToGallery: nat('saveImageToGallery'),
    shareImage:    nat('shareImage'),   scanQr: nat('scanQr'),
    previewHtml:   nat('previewHtml'),  openAppSysSettings: (w) => rpc('native', 'openAppSysSettings', [w]) === 'true',
    promptContribute: natV('promptContribute'),

    /* ── 诊断通道 (未启用时返回空字符串) ── */
    logsUpload:    nat('logsUpload'),   feedbackSubmit: nat('feedbackSubmit'), diagResult: nat('diagResult'),
  };
})();
