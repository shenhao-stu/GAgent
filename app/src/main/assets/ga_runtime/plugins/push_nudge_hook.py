"""push_nudge 插件 —— M1 推送通道内核侧(PLAN_MOTION_CADENCE §3-S1): 拉改推的「失效通知」信号源。

架构契约(红线映射见 PLAN_MOTION_CADENCE §5):
  推的是「有新东西」的信号, 不是数据本身 —— JS 收到 nudge 后仍走现有 poll 取数,
    poll 是唯一数据源(gen+seq 契约不动), 本插件不读不写任何事件/状态数据。
  事件层纯插件: 挂 agent_loop 现成钩子 tool_before/tool_after + llm_after/agent_after
    (后两者覆盖非工具型更新: 每 turn 步骤文本 / 最终回答 / 正常完成路径的 running→false 终态;
     abort 与后端异常路径 agent_after 不触发 —— 如实登记, 终态靠前端 ≤700ms 心跳兜底, §6)。
  跳事件触发面(r2): code_run 期间 webcdp.*/droid.* 不走 agent_loop 钩子, 本插件对其咽喉函数做
    **第二层观察性包装**(先例: browser_events_hook._wrap) —— 包装体只调 nudge() 发信号,
    不读不写事件数据、不改参数/返回值/异常; webcdp/droid 源文件零改动, 现有插件零改动。
  回调注册: Kotlin 经 getModule('plugins.push_nudge_hook').callAttr('set_nudge_callback', cb)
    直达本模块(不动 android_entry); cb 为 Java Runnable(设备)或 Python callable(测试)。
    回调未注册(沙箱/桌面无 Kotlin)或调用抛异常 → 一律静默无操作, 绝不拖垮执行层。
  线程: nudge() 在会话/工具线程触发; Kotlin 侧回调体只投递主线程 Handler, 不做任何 UI 操作。
  五禁自查: 不改 max_steps / 不加 confirm / 信号不回写规划 / 不暴露新工具 / 信号只进 UI 通道。
"""
import threading
import time

from plugins.hooks import register

_lock = threading.Lock()
_cb = None            # 已注册回调(0 参可调用); None = 未注册 → nudge() 无操作


def set_nudge_callback(fn):
    """Kotlin(Py.boot 后 + poll 桥旁懒重试)注册推送回调; 传 None 注销。
    接受: Python callable(测试/沙箱) 或带 .run 的对象(Java Runnable 经 Chaquopy 代理)。"""
    global _cb
    cb = None
    try:
        if fn is not None:
            if callable(fn):
                cb = fn
            else:
                run = getattr(fn, 'run', None)      # Java Runnable 代理: 调 .run()
                if run is not None:
                    cb = run
    except Exception:
        cb = None
    with _lock:
        _cb = cb
    return _cb is not None


def has_callback():
    """Kotlin 懒重试探针(bootstrap 自愈重导入本模块 → _cb 丢失, 据此重注册)。"""
    return _cb is not None


def nudge(*_a, **_k):
    """发一次「有新东西」信号。未注册/异常一律静默(埋点绝不拖垮执行层); 吞掉一切入参。"""
    cb = _cb
    if cb is None:
        return
    try:
        cb()
    except Exception:
        pass


def _on_hook(ctx):
    nudge()


def _on_agent_after(ctx):
    """终态信号: 立即 1 发 + 事件锚定的延迟补发(0.25s/0.6s 各 1 次, 一次性 Timer 非周期轮询)。
    原因(§6 空拍): agent_after 在会话线程触发, 而 running→False 由 _drain 线程稍后写入
    (queue 消费 + flush 阈值, 实测滞后可达 ~300ms+) —— 只发瞬时 nudge 会拍到 running 仍 True
    的空拍, 终态只能等 700ms 心跳(实测最坏 ~1s, 劣于基线); 延迟补发把正常完成路径的
    终态可见压回 ~300ms 级。abort/后端异常路径本钩子不触发, 仍靠心跳兜底(如实登记)。
    注: 不能用 threading.Timer —— browser_events_hook 已把 threading.Thread 换成 _BwThread,
    Timer(原生 Thread 子类)构造会触发 super(type,obj) TypeError; 直接构造 threading.Thread 无此问题。"""
    nudge()
    try:
        def _late():
            for d in (0.25, 0.35):        # 累计 0.25s / 0.6s 两次补发
                time.sleep(d)
                nudge()
        th = threading.Thread(target=_late, daemon=True)
        th.start()
    except Exception:
        pass


register('tool_before', _on_hook)     # 工具行 running 即时可见(agent_loop L22)
register('tool_after', _on_hook)      # 工具行终态即时可见(agent_loop L24)
register('llm_after', _on_hook)       # 每 turn 步骤文本/最终回答落地(agent_loop L67)
register('agent_after', _on_agent_after)   # 正常完成路径 running→false 终态(agent_loop L106)


# ---------- 跳事件触发面: webcdp/droid 咽喉函数第二层观察性包装 ----------
_MARK = '_ga_push_nudge'              # 幂等标记(自有命名, 不与 browser_events_hook._ga_bwev 冲突)


def _wrap(mod, fname):
    """在(可能已被 browser_events_hook 包装过的)函数外再套一层: 起止各发一次 nudge。
    行为透明: 参数原样透传、返回值/异常原样透出; 只发信号, 不碰事件数据。"""
    try:
        orig = getattr(mod, fname, None)
        if orig is None or getattr(orig, _MARK, False):
            return

        def wrapper(*args, **kwargs):
            nudge()                   # 起: browser_events_hook._open_event 紧随其后 append 事件,
            try:                      #    50ms 合并批 + JS trailing-edge 补拍保证拍到(§6 空拍应对)
                return orig(*args, **kwargs)
            finally:
                nudge()               # 止: 事件已 _close_event 收尾(含异常路径), 立即可见

        setattr(wrapper, _MARK, True)
        wrapper.__name__ = getattr(orig, '__name__', fname)
        wrapper.__doc__ = getattr(orig, '__doc__', None)
        wrapper.__wrapped__ = orig
        setattr(mod, fname, wrapper)
    except Exception:
        pass


def _install():
    """与 browser_events_hook._install 同一份咽喉清单(它记事件, 我发信号)。
    无 webcdp/droid 的环境(沙箱/桌面)静默跳过 —— import 本模块必须零副作用成功。"""
    try:
        import webcdp
        for f in ('connect', 'open_url', 'web_open', 'web_click',
                  'web_type', 'web_scan', 'web_eval', 'web_shot'):
            _wrap(webcdp, f)
    except Exception:
        pass
    try:
        import droid
        for f in ('launch', 'tap', 'swipe', 'scroll',
                  'key', 'back', 'paste', 'shot'):
            _wrap(droid, f)
    except Exception:
        pass


_install()
