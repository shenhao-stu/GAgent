"""browser_events 插件 —— F4/P4 浏览器证据链后端: 给 tool_events 叠加浏览器/手机操作「跳」事件。

架构契约(PLAN_FRONTEND_CATCHUP v1.2 F4 / VISITABLE 红线):
  执行层文件零改动: 本插件在 import 时对 webcdp/droid 的既有咽喉函数做**观察性包装**
    (同 run_guard 对 threading.Thread 的包装先例), 只记事件、绝不改变被包装函数的行为/返回/异常。
  不新增任何暴露给模型的工具; screenshot_id 只引用工具实现内**既有 side-effect 截图**
    (webcdp.web_shot / open_url(shot=True) / droid.shot(path) 落在 files/ga/temp 的产物路径),
    没有真实落盘点时置 None(json 序列化为 null, 宁缺毋假)。
  事件只进 poll→UI 通道, 绝不回灌模型上下文; 与 tool_events_hook 共用 gen/seq 计数器
    (前端按 gen+seq 复合键去重, 两插件的事件必须在同一 seq 空间)与环形上限 50。
  只增字段: 跳事件在 v3 基础字段(gen/seq/id/name/status/turn/t_start/t_end/
    input_summary/result_summary/error)之上叠加 phase/url/title/action/step_i/n/screenshot_id;
    既有 code_run 等事件的字段一个不动, 旧前端忽略未知字段/多出的行。
  会话归属: 优先 patches.current_sess()(TLS); code_run 的 _run 子线程无 TLS 绑定,
    经本插件对 threading.Thread 的构造期捕获把父线程归属**只读传递**给子线程
    (插件私有 TLS, 不写 patches._tls, 不影响 abort/取消语义; 与 run_guard 令牌继承同款思路)。
  写入纪律: 除 screenshot_id 允许 None(json null)外全部纯 str/int/float; 全部写操作持 sess.lock。
  失败静默: 任何记录失败都不得影响被包装函数(埋点绝不拖垮执行层)。
"""
import threading
import time
import weakref

from kernel_adapter import patches
from plugins.tool_events_hook import _text, NAME_CAP, SUM_CAP, trim

URL_CAP = 300

# ---------- 会话归属: TLS 优先 + 线程构造期只读继承(code_run _run 子线程场景) ----------
_tls = threading.local()


def _install_thread_inheritance():
    """threading.Thread 构造期捕获父线程归属 sess(weakref), run() 期间放进插件私有 TLS。
    只服务本插件的事件归属查询, 不触碰 patches 的绑定/取消链路; 幂等。"""
    if getattr(threading.Thread, '_ga_bwev', False):
        return
    _Base = threading.Thread

    class _BwThread(_Base):
        _ga_bwev = True

        def __init__(self, *a, **k):
            # 用捕获的原始基类显式初始化, 不用零参 super() —— 同 run_guard._GuardedThread:
            # paramiko.Transport 等第三方类在补丁前捕获原始 Thread, 其 __init__ 显式调
            # threading.Thread.__init__(self) 会命中本包装类, 此时 self 并非 _BwThread
            # 实例, 零参 super() 抛 "super(type, obj): obj must be an instance..."。
            _Base.__init__(self, *a, **k)
            s = _sess()
            try:
                self._ga_bw_sess = weakref.ref(s) if s is not None else None
            except TypeError:
                self._ga_bw_sess = (lambda _s=s: _s)

        def run(self):
            ref = getattr(self, '_ga_bw_sess', None)
            if ref is not None:
                _tls.sess_ref = ref
            try:
                _Base.run(self)
            finally:
                try:
                    del _tls.sess_ref
                except Exception:
                    pass

    threading.Thread = _BwThread


def _sess():
    s = patches.current_sess()
    if s is not None:
        return s
    ref = getattr(_tls, 'sess_ref', None)
    if ref is None:
        return None
    try:
        s = ref()
    except Exception:
        return None
    if s is None or getattr(s, 'retired', False):
        return None
    return s


# ---------- 跳事件读写(与 tool_events_hook 共用 gen/seq 空间) ----------
_depth = threading.local()   # 重入护栏: open_url 内部的 web_open/web_shot 不再各记一跳


def _pick_url(args, kwargs, take_first_pos):
    u = kwargs.get('url')
    if u is None and take_first_pos and args:
        u = args[0]
    return _text(u, URL_CAP) if isinstance(u, str) else ''


def _arg(v):
    """图像数组只记形状: 看图入口的首参是整屏像素, 不能把数组文本塞进摘要。"""
    shape = getattr(v, 'shape', None)
    if shape is not None and hasattr(v, 'dtype'):
        try:
            return 'ndarray%s' % (list(shape),)
        except Exception:
            return 'ndarray'
    return v


def _open_event(label, action, phase, args, kwargs, url_from_args):
    sess = _sess()
    if sess is None:
        return None
    try:
        arg_summary = {}
        for i, v in enumerate(args):
            arg_summary['a%d' % i] = _arg(v)
        for k, v in kwargs.items():
            if not str(k).startswith('_'):
                arg_summary[k] = _arg(v)
        with sess.lock:
            st = sess.state
            gen = int(st.get('gen', 0) or 0)
            evs = st.setdefault('tool_events', [])
            if st.get('_tool_gen') != gen:      # 同 tool_events_hook 的换代回收(通常 code_run 的 tool_before 已做过)
                del evs[:]
                st['_tool_gen'] = gen
                st['_tool_seq'] = 0
            st['_tool_seq'] = int(st.get('_tool_seq', 0) or 0) + 1
            # 浏览器跳步计数(按 gen 重置); n=当前 gen 已知总跳数, 追加新跳时同步刷旧跳的 n(均为本插件自有字段)
            if st.get('_bw_gen') != gen:
                st['_bw_gen'] = gen
                st['_bw_i'] = 0
            st['_bw_i'] = int(st.get('_bw_i', 0) or 0) + 1
            step_i = st['_bw_i']
            for e in evs:
                if e.get('gen') == gen and 'step_i' in e:
                    e['n'] = step_i
            turn = 0
            for e in reversed(evs):             # 归属到当前在跑的宿主工具(code_run)的 turn
                if e.get('status') == 'running' and 'step_i' not in e:
                    turn = int(e.get('turn', 0) or 0)
                    break
            ev = {
                'gen': gen,
                'seq': st['_tool_seq'],
                'id': '',
                'name': _text(label, NAME_CAP),
                'status': 'running',
                'turn': turn,
                't_start': round(time.time(), 3),
                't_end': 0,
                'input_summary': _text(arg_summary, SUM_CAP),
                'result_summary': '',
                'error': '',
                # ---- F4 扩展字段(只增) ----
                'phase': phase,
                'url': _pick_url(args, kwargs, url_from_args),
                'title': '',
                'action': action,
                'step_i': step_i,
                'n': step_i,
                'screenshot_id': None,          # 唯一允许的 None(json null): 无既有截图落盘即缺省, 宁缺毋假
            }
            evs.append(ev)
            trim(evs)
            return (weakref.ref(sess), gen, ev['seq'])
    except Exception:
        return None


def _shot_ref(action, ret):
    """既有 side-effect 截图的引用: 只认工具自身返回的 png 路径, 不主动截图。"""
    try:
        if isinstance(ret, str) and ret.endswith('.png'):
            return _text(ret, URL_CAP)
        if isinstance(ret, dict):
            p = ret.get('shot')
            if isinstance(p, str) and p.endswith('.png'):
                return _text(p, URL_CAP)
    except Exception:
        pass
    return None


def _close_event(rec, action, ret, err):
    if rec is None:
        return
    try:
        sref, gen, seq = rec
        sess = sref()
        if sess is None or getattr(sess, 'retired', False):
            return
        with sess.lock:
            ev = None
            for e in reversed(sess.state.get('tool_events') or []):
                if e.get('gen') == gen and e.get('seq') == seq:
                    ev = e
                    break
            if ev is None or ev.get('status') != 'running':
                return
            ev['t_end'] = round(time.time(), 3)
            is_err = err is not None or (isinstance(ret, dict)
                                         and str(ret.get('status', '')).lower() == 'error')
            if action == 'vision' and isinstance(ret, str):
                ev['out_len'] = len(ret)             # 看图回答长度: 与耗时一起判断生成成本
                is_err = is_err or ret.startswith('Error:')   # 模板以 'Error: ...' 返回失败而非抛异常
            if is_err:
                ev['status'] = 'error'
                ev['phase'] = 'error'
                ev['error'] = _text(err if err is not None
                                    else (ret.get('error') or ret.get('msg') or 'error'), SUM_CAP)
            else:
                ev['status'] = 'done'
                ev['phase'] = 'loaded' if ev.get('phase') == 'navigating' else 'done'
            if isinstance(ret, list) and action in _LIST_ACTIONS:
                ev['result_summary'] = _text('n=%d %s' % (len(ret), _text(ret[:3], SUM_CAP)), SUM_CAP)
            elif isinstance(ret, (dict, list, str, int, float, bool)) or ret is None:
                ev['result_summary'] = _text(ret if ret is not None else '', SUM_CAP)
            else:
                ev['result_summary'] = type(ret).__name__      # ndarray 等大对象只记类型名
            if isinstance(ret, dict):
                if isinstance(ret.get('url'), str) and ret['url']:
                    ev['url'] = _text(ret['url'], URL_CAP)
                if isinstance(ret.get('title'), str) and ret['title']:
                    ev['title'] = _text(ret['title'], URL_CAP)
            sid = _shot_ref(action, ret)
            if sid:
                ev['screenshot_id'] = sid
    except Exception:
        pass


_LIST_ACTIONS = ('look',)   # 检测列表: 摘要记条数+前 3 项


# ---------- 观察性包装 ----------
def _wrap(mod, fname, action, phase, url_from_args=False):
    orig = getattr(mod, fname, None)
    if orig is None or getattr(orig, '_ga_bwev', False):
        return
    label = '%s.%s' % (mod.__name__, fname)

    def wrapper(*args, **kwargs):
        d = int(getattr(_depth, 'v', 0) or 0)
        _depth.v = d + 1
        rec = None
        if d == 0:
            rec = _open_event(label, action, phase, args, kwargs, url_from_args)
        try:
            ret = orig(*args, **kwargs)
        except BaseException as e:
            _depth.v = d
            _close_event(rec, action, None, e)
            raise
        _depth.v = d
        _close_event(rec, action, ret, None)
        return ret

    wrapper._ga_bwev = True
    wrapper.__name__ = getattr(orig, '__name__', fname)
    wrapper.__doc__ = getattr(orig, '__doc__', None)
    wrapper.__wrapped__ = orig
    setattr(mod, fname, wrapper)


def _install():
    _install_thread_inheritance()
    try:
        import webcdp
        _wrap(webcdp, 'connect', 'connect', 'navigating')
        _wrap(webcdp, 'open_url', 'navigate', 'navigating', url_from_args=True)
        _wrap(webcdp, 'web_open', 'navigate', 'navigating', url_from_args=True)
        _wrap(webcdp, 'web_click', 'click', 'acting')
        _wrap(webcdp, 'web_type', 'type', 'acting')
        _wrap(webcdp, 'web_scan', 'scan', 'verifying')
        _wrap(webcdp, 'web_eval', 'eval', 'verifying')
        _wrap(webcdp, 'web_shot', 'screenshot', 'verifying')
    except Exception:
        pass
    try:
        import droid
        _wrap(droid, 'launch', 'launch', 'acting')
        _wrap(droid, 'tap', 'tap', 'acting')
        _wrap(droid, 'swipe', 'swipe', 'acting')
        _wrap(droid, 'scroll', 'scroll', 'acting')
        _wrap(droid, 'key', 'key', 'acting')
        _wrap(droid, 'back', 'back', 'acting')
        _wrap(droid, 'paste', 'paste', 'acting')
        _wrap(droid, 'shot', 'screenshot', 'verifying')
        # 观察侧也记一跳: OCR 检测与看图问答原先不在 tool_events 中, 长 code_run 无法区分等待、检测与远端视觉。
        # 只包耗时的观察; dump/find 便宜且常在轮询循环里, 记录会挤满环形缓冲。嵌套调用(如 look 内的 shot)由 _depth 只记外层。
        _wrap(droid, 'tap_text', 'tap', 'acting')
        _wrap(droid, 'scroll_view', 'scroll', 'acting')
        _wrap(droid, 'look', 'look', 'verifying')
        _wrap(droid, 'ask_vision', 'vision', 'verifying')
    except Exception:
        pass


_install()
