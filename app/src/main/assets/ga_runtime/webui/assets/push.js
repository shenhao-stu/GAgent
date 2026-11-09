/* push.js — M1 nudge 推送通道 JS 侧(参观层, PLAN_MOTION_CADENCE §3-S1)。
 *
 * 通道: Kotlin addWebMessageListener("GAPush") 注入 window.GAPush →
 *   本文件启动即 postMessage 握手(Kotlin 借此拿到 JavaScriptReplyProxy; 页面重建后旧 proxy
 *   静默作废, 重新加载本文件 = 天然重握手) → Kotlin 50ms 合并批后 proxy.postMessage("nudge")。
 *   降级链: 无 GAPush(WebView 不支持) → Kotlin 走 evaluateJavascript 调 window.gaPushNudge;
 *   两者都不通 → 什么都不发生, 现有 700ms/2s 心跳轮询维持现状(功能零损失)。
 *
 * nudge 不丢弃(r2): poll 进行中/距上次 <50ms 到达的 nudge 标记脏 + trailing-edge 补拍,
 *   杜绝 burst 尾事件(webcdp.* 高频后宿主 tool_after 收尾)被丢弃式去抖跳过、只能等心跳。
 *
 * 渲染路径拆分(监察 r2 关键修正):
 *   ① 工具事件行 → nudge 后立即 readonly poll(负 since, 不消费 ask/cmd_error/notif_pending)
 *      + renderTools(j) 即时落 DOM(只 append/更新工具行局部, 不触碰活跃步文本节点) —— 承载 ≤150ms 门;
 *   ② live 步骤文本 → 本文件绝不重渲(数据由现有 700ms 节拍 poll 照常取), 护 680ms 词级渐入(M2 pace.js 才接管);
 *   ③ 终态/任务启停边界(readonly 探测到 j.running 与 UI 不一致) → 调现有全局 poll() 走全量路径
 *      (正确消费 ask/cmd_error/notif_pending + 全量渲染 flip), 不自造第二条渲染链。
 *
 * 心跳纪律: 本文件不动任何定时器 —— 运行态 700ms / 空闲态 2s 现状不变(§3-S1 载荷论证口径)。
 * 开关: window.GA_PUSH_OFF = true → 收到 nudge 一律无操作(纯现状轮询)。
 * 依赖(app.js 顶层绑定, 裸标识符访问): running/multi/curConvo/activeCid/focusRunning/renderTools/poll;
 *   全部 typeof 守卫, app.js 变更/未加载时本文件静默退化为无操作。
 */
(function () {
  'use strict';
  var MIN_GAP = 50;                 // 与 Kotlin 合并批同窗宽: 50ms 内重复 nudge 合并为一次补拍
  var RO_SINCE = -999999;           // readonly poll: 负 since 不消费任何一次性字段, steps 切片为空(轻载荷)
  var _last = 0;                    // 上次 nudge poll 时刻
  var _busy = false;                // nudge poll 进行中(桥同步, 防御性保留)
  var _dirty = false;               // 窗口内有被合并的 nudge → trailing-edge 必补拍
  var _trail = null;                // 补拍定时器句柄
  var _stat = { nudges: 0, polls: 0, full: 0 };   // 载荷申报计数(GM1 证据, 只读暴露)

  function _off() { try { return !!window.GA_PUSH_OFF; } catch (e) { return false; } }

  function _focusCid() {            // multi 时的焦点 cid(与 app.js poll 同源规则); legacy 返回 null
    try {
      if (typeof multi !== 'undefined' && multi) {
        var c = (typeof curConvo !== 'undefined' && curConvo && curConvo.id) ? curConvo.id
              : (typeof activeCid !== 'undefined' && activeCid ? activeCid : null);
        return c ? String(c) : null;
      }
    } catch (e) {}
    return null;
  }

  function _uiRunning() {           // UI 视角的运行态(multi 看焦点会话)
    try {
      if (typeof multi !== 'undefined' && multi && typeof focusRunning === 'function') return !!focusRunning();
      return (typeof running !== 'undefined') && !!running;
    } catch (e) { return false; }
  }

  function _fullPoll() {            // 边界拍: 复用现有全量 poll(消费语义/渲染主链全在 app.js, 单一真相源)
    _stat.full++;
    try { if (typeof poll === 'function') poll(); } catch (e) {}
  }

  function _probe() {               // 一次 nudge poll: readonly 取数 → 工具行即时渲染 / 边界转全量
    _stat.polls++;
    var cid = _focusCid(), raw = null;
    try {
      if (cid && typeof GA !== 'undefined' && typeof GA.pollC === 'function') raw = GA.pollC(cid, String(RO_SINCE));
      else if (typeof GA !== 'undefined' && typeof GA.poll === 'function') raw = GA.poll(RO_SINCE);
    } catch (e) { return; }
    if (raw == null || raw === '') return;
    var j; try { j = (typeof raw === 'object') ? raw : JSON.parse(raw); } catch (e) { return; }
    if (!j || j.error) return;
    if (cid && j.cid != null && String(j.cid) !== cid) return;   // 串台防护(与 render() 同款)
    var ui = _uiRunning();
    if (!!j.running !== ui) { _fullPoll(); return; }             // 终态 flip / 后台任务冒头: 走现有全量路径
    try { if (typeof renderTools === 'function') renderTools(j); } catch (e) {}   // 工具行局部即时落 DOM(≤150ms 门)
  }

  function _run() {
    _busy = true; _last = Date.now();
    try { _probe(); } catch (e) {}
    _busy = false;
    if (_dirty && !_trail) _trail = setTimeout(_onTrail, MIN_GAP);   // 拍中又有 nudge → 尾拍兜底
  }

  function _onTrail() {             // trailing-edge 补拍: 窗口结束后把被合并的 nudge 补上, 绝不丢弃
    _trail = null;
    if (!_dirty) return;
    if (_busy || Date.now() - _last < MIN_GAP) { _trail = setTimeout(_onTrail, MIN_GAP); return; }
    _dirty = false;
    _run();
  }

  function _kick() {                // nudge 入口(GAPush onmessage / evaluateJavascript 兜底共用)
    if (_off()) return;
    _stat.nudges++;
    var gap = Date.now() - _last;
    if (_busy || gap < MIN_GAP) {
      _dirty = true;
      if (!_trail) _trail = setTimeout(_onTrail, Math.max(15, MIN_GAP - gap));
      return;
    }
    _run();
  }

  // ── 通道就位 ──
  window.gaPushNudge = _kick;       // 降级链第二级: Kotlin evaluateJavascript 直调
  window.gaPushStat = function () { return JSON.parse(JSON.stringify(_stat)); };   // GM1 载荷计数取证用(只读快照)

  var _bound = false;
  function _handshake() {           // 启动即握手; GAPush 缺失(不支持/未注册)时静默作废
    try {
      var ch = window.GAPush;
      if (!ch || typeof ch.postMessage !== 'function') return false;
      if (!_bound) {
        _bound = true;
        var ok = false;
        try { if (typeof ch.addEventListener === 'function') { ch.addEventListener('message', _kick); ok = true; } } catch (e) {}
        if (!ok) try { ch.onmessage = _kick; } catch (e) {}
      }
      ch.postMessage('ga_push_hello');   // Kotlin 侧: 任何页内消息都刷新最新 replyProxy(页面重建重握手)
      return true;
    } catch (e) { return false; }
  }
  if (!_handshake()) {              // 注入对象理论上 documentStart 即有; 少量重试兜时序竞位
    var _n = 0, _hsT = setInterval(function () { if (_handshake() || ++_n >= 5) clearInterval(_hsT); }, 1000);
  }
})();
