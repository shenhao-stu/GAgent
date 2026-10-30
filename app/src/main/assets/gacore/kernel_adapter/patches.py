import threading
import weakref

# 全局 fallback（无归属线程 / 未 bind 时）
_ACTIVE_RESPS = weakref.WeakSet()
_ROUTE = {'cur': None}   # {'name','model','type'} 或 None; 仅 mixin(自动故障转移)运行时被探针写入
_UNATTR_USAGE = {'tok_in': 0, 'tok_out': 0, 'cache_read': 0, 'cache_write': 0}

# TLS：当前线程归属的 _Sess；run 线程启动包装器 + 非 run LLM 显式 bind(__util)
_tls = threading.local()
# thread-ident → weakref(Sess) 兜底（线程池复用 / TLS 丢失时）
_TID_REG = {}
_TID_LOCK = threading.Lock()


class _Aborted(Exception):
    def __str__(self): return '⏹ 已中止 (aborted)'


def bind_sess(sess):
    """把当前线程绑定到 sess；sess=None 解绑。run 线程入口与 __util LLM 调用点必须调。"""
    if sess is None:
        try: delattr(_tls, 'sess')
        except Exception: pass
        tid = threading.get_ident()
        with _TID_LOCK: _TID_REG.pop(tid, None)
        return
    _tls.sess = sess
    tid = threading.get_ident()
    with _TID_LOCK:
        try: _TID_REG[tid] = weakref.ref(sess)
        except TypeError:
            # 测试替身不可 weakref 时退化为强引用 lambda
            _TID_REG[tid] = (lambda s=sess: s)


def current_sess():
    """当前线程归属 sess；无归属返回 None（绝不误落到焦点）。"""
    s = getattr(_tls, 'sess', None)
    if s is not None and not getattr(s, 'retired', False):
        return s
    tid = threading.get_ident()
    with _TID_LOCK:
        wr = _TID_REG.get(tid)
    if wr is None: return None
    try: s = wr() if callable(wr) else wr
    except Exception: s = None
    if s is None or getattr(s, 'retired', False):
        with _TID_LOCK: _TID_REG.pop(tid, None)
        return None
    _tls.sess = s
    return s


def _sess_resps(sess):
    """per-sess 在飞响应 WeakSet；无 sess 用全局。"""
    if sess is None: return _ACTIVE_RESPS
    rs = getattr(sess, '_active_resps', None)
    if rs is None:
        rs = weakref.WeakSet()
        try: sess._active_resps = rs
        except Exception: return _ACTIVE_RESPS
    return rs


def _cancel_now():
    """只看当前归属 sess 的 stop_sig；无归属绝不误杀（回 False）。"""
    s = current_sess()
    if s is not None:
        a = getattr(s, 'agent', None)
        return bool(a and getattr(a, 'stop_sig', False))
    return False


def _cancel_for(sess):
    if sess is None: return _cancel_now()
    a = getattr(sess, 'agent', None)
    return bool(a and getattr(a, 'stop_sig', False))


def _wrap_iter_lines(r, sess=None, rec=None):
    orig = getattr(r, 'iter_lines', None)
    if orig is None or getattr(orig, '_ga_wrapped', False): return
    # 捕获登记时的 sess，避免迭代时 TLS 漂移
    owner = sess if sess is not None else current_sess()
    def wrapped(*a, **k):
        it = orig(*a, **k)
        while True:
            if _cancel_for(owner):
                try: r.close()
                except Exception: pass
                raise _Aborted()
            try: line = next(it)
            except StopIteration: return
            except Exception:
                if _cancel_for(owner): raise _Aborted()   # close() 唤醒的读异常 → 归一为中止(_stream_with_retry 的 except Exception: 不重试)
                raise
            if rec is not None: _llmt_line(rec, line)
            yield line
    wrapped._ga_wrapped = True
    try: r.iter_lines = wrapped
    except Exception: pass


class _ReqProxy:
    """只替换 llmcore 命名空间里的 requests: post 登记在飞响应并注入中止检查, 其余属性透传(不动全局 requests)。"""
    def __getattr__(self, n):
        import requests; return getattr(requests, n)
    def post(self, *a, **k):
        if _cancel_now(): raise _Aborted()           # 已中止: 不再发起新请求 → 快速跳出重试/故障转移
        rec = getattr(_tls, 'llmt', None)
        if rec is not None: rec['attempts'] += 1
        import requests; r = requests.post(*a, **k)
        sess = current_sess()
        try:
            _sess_resps(sess).add(r)                 # 先登记: 「停止」靠它关掉在飞 SSE, 不受计时影响
            _wrap_iter_lines(r, sess, rec)
        except Exception: pass
        if rec is not None: _llmt_sent(rec, r)
        return r


class _TimeProxy:
    """只替换 llmcore 命名空间里的 time: sleep 分片可中断(中止时立即返回 → 跳过重试/故障转移的退避等待), 其余透传。"""
    def __getattr__(self, n):
        import time; return getattr(time, n)
    def sleep(self, secs):
        import time
        try: secs = float(secs)
        except Exception: return time.sleep(secs)
        slept = 0.0
        while slept < secs:
            if _cancel_now(): return                  # 中止: 立即返回, 跳过剩余退避(不 raise, 让上层自然走到下一次 cancel 检查)
            d = min(0.1, secs - slept); time.sleep(d); slept += d


def patch_session_proxy():
    """胶水级猴补丁(不改 llmcore.py 本体): 给 llmcore.BaseSession 注入"代理兜底 + 移动网络连接超时兜底"。
    根因: 手机挂 VPN 时直连 DNS 解析不了任何主机(直连=HTTP 000),
    必须走本地 HTTP 代理(127.0.0.1:10809, CONNECT 实测可达)。
    但 mykey.py 里的渠道都没填 proxy → BaseSession.proxies=None → requests.post(proxies=None)
    本应回退 HTTP(S)_PROXY env, 实测在 Chaquopy 下不稳→直连→NameResolutionError→max_retries 重试→
    UI 一直"思考中"不出结果。这里在 __init__ 后把 env 代理显式写进 self.proxies, 彻底走代理。"""
    import os
    try:
        import llmcore
        if getattr(llmcore.BaseSession, '_ga_proxy_patched', False): return
        _orig = llmcore.BaseSession.__init__
        def _init(self, cfg):
            _orig(self, cfg)
            if cfg.get('timeout') is None:                             # 移动网络 TLS 握手常 >5s(无线电唤醒/蜂窝抖动/CF 边缘), 桌面默认 connect=5 手机上误杀;
                self.connect_timeout = max(self.connect_timeout, 15)   # urllib3 对握手期停滞报 "Read timed out. (read timeout=5)"(读的是 connect 值)→桌面无此症, 表象极具误导
            if getattr(self, 'proxies', None) is None:
                base = getattr(self, 'api_base', '') or ''
                host = base.split('://', 1)[-1].split('/', 1)[0].split(':', 1)[0].lower()
                if host in ('127.0.0.1', 'localhost', '::1') or host.startswith('127.'):
                    return                       # 本地回环端点(in-APK bus / kiro 127.0.0.1:8765)绝不走代理(显式 proxies dict 不认 NO_PROXY)
                penv = (os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
                        or os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy') or '')
                if penv: self.proxies = {'http': penv, 'https': penv}
        llmcore.BaseSession.__init__ = _init
        llmcore.BaseSession._ga_proxy_patched = True
    except Exception:
        pass


def patch_usage():
    """胶水级猴补丁(不改 llmcore.py): 包住 llmcore._record_usage, 把每次 LLM 用量累加到
    当前归属 sess.state（有 TLS）或全局 _state/_UNATTR_USAGE（无归属），供 poll/poll2 上报。
    注: claude 流式 output_tokens 不经此函数(走 SSE delta), 那部分由前端按文本长度估算补足。"""
    import android_entry as _ae
    try:
        import llmcore
        # 旗标记录"哪个模块实例"包的: android_entry 被清缓存重导入后, 新实例必须重绑(旧闭包写旧 _state=用量冻结/中止失效)
        if getattr(llmcore, '_ga_usage_patched', None) is _ae: return
        _orig = getattr(llmcore, '_ga_usage_orig', None) or llmcore._record_usage
        def _wrap(usage, api_mode):
            try:
                if usage:
                    cr = cw = 0                                     # 缓存读取 / 缓存创建(写)token; 仅 messages(Claude) 有 creation 概念, OAI 只有 cached
                    if api_mode == 'messages':
                        cw = usage.get('cache_creation_input_tokens', 0) or 0
                        cr = usage.get('cache_read_input_tokens', 0) or 0
                        inp = (usage.get('input_tokens', 0) or 0) + cw + cr
                        out = usage.get('output_tokens', 0) or 0
                    elif api_mode == 'responses':
                        cr = (usage.get('input_tokens_details') or {}).get('cached_tokens', 0) or 0
                        inp = usage.get('input_tokens', 0) or 0; out = usage.get('output_tokens', 0) or 0
                    else:
                        cr = (usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0) or 0
                        inp = usage.get('prompt_tokens', 0) or 0; out = usage.get('completion_tokens', 0) or 0
                    s = current_sess()
                    if s is not None and isinstance(getattr(s, 'state', None), dict):
                        lock = getattr(s, 'lock', None) or _ae._lock
                        with lock:
                            st = s.state
                            st['tok_in'] = st.get('tok_in', 0) + inp
                            st['tok_out'] = st.get('tok_out', 0) + out
                            st['cache_read'] = st.get('cache_read', 0) + cr
                            st['cache_write'] = st.get('cache_write', 0) + cw
                    else:
                        with _ae._lock:
                            _UNATTR_USAGE['tok_in'] += inp
                            _UNATTR_USAGE['tok_out'] += out
                            _UNATTR_USAGE['cache_read'] += cr
                            _UNATTR_USAGE['cache_write'] += cw
                            _ae._state['tok_in'] = _ae._state.get('tok_in', 0) + inp
                            _ae._state['tok_out'] = _ae._state.get('tok_out', 0) + out
                            _ae._state['cache_read'] = _ae._state.get('cache_read', 0) + cr
                            _ae._state['cache_write'] = _ae._state.get('cache_write', 0) + cw
            except Exception: pass
            return _orig(usage, api_mode)
        llmcore._ga_usage_orig = _orig
        llmcore._record_usage = _wrap
        llmcore._ga_usage_patched = _ae
    except Exception:
        pass


# ---------- 主模型请求计时(只观察, 不改请求/重试/返回) ----------
_LLMT_CAP = 40
# 首 token 分类(Anthropic / Chat Completions / Responses SSE); 值为 null 或空串的占位字段不算
_LLMT_MARKS = None


def _llmt_marks():
    global _LLMT_MARKS
    if _LLMT_MARKS is None:
        import re
        _LLMT_MARKS = (
            (re.compile(rb'"thinking_delta"|"(?:reasoning_content|reasoning)"\s*:\s*"[^"]|reasoning[a-z_]*\.delta'), 'think'),
            (re.compile(rb'"input_json_delta"|"type"\s*:\s*"tool_use"|"tool_calls"\s*:\s*\[|function_call[a-z_]*\.delta'), 'tool'),
            (re.compile(rb'"text_delta"|output_text\.delta|"content"\s*:\s*"[^"]'), 'text'),
        )
    return _LLMT_MARKS


def _llmt_dt(rec):
    import time
    return round(time.time() - rec['t_req'], 2)


def _llmt_open(payload):
    """每次 _stream_with_retry 一条记录, 时间点相对 t_req(秒)。无归属会话不记。上下文规模在发出后从请求体量, 不在请求路径上重复序列化。"""
    import time
    s = current_sess()
    st = getattr(s, 'state', None) if s is not None else None
    if not isinstance(st, dict) or not isinstance(payload, dict): return None
    msgs = payload.get('messages') or payload.get('input') or []
    rec = {'gen': int(st.get('gen', 0) or 0), 'i': 0, 't_req': round(time.time(), 3),
           'model': str(payload.get('model') or '')[:60], 'n_msgs': len(msgs) if isinstance(msgs, list) else 0,
           'body_bytes': 0, 'n_img': 0,
           'attempts': 0, 'http': 0, 'errors': 0, 'last_error': '',
           'hdr': None, 'first': None, 'think': None, 'text': None, 'tool': None, 'end': None,
           'in_tok': 0, 'out_tok': 0, 'cache_read': 0}
    lock = getattr(s, 'lock', None)
    try:
        if lock is not None: lock.acquire()
        lst = st.get('llm')
        if not isinstance(lst, list): lst = st['llm'] = []
        lst[:] = [x for x in lst if x.get('gen') == rec['gen']][-(_LLMT_CAP - 1):]
        rec['i'] = (lst[-1]['i'] + 1) if lst else 1
        lst.append(rec)
    finally:
        if lock is not None: lock.release()
    return rec


def _llmt_sent(rec, r):
    """响应头到达: 记首包时间、HTTP 码, 并从已发送的请求体量上下文规模(bytes.count 为 C 级扫描)。"""
    try:
        if rec['hdr'] is None: rec['hdr'] = _llmt_dt(rec)
        rec['http'] = int(getattr(r, 'status_code', 0) or 0)
        body = getattr(getattr(r, 'request', None), 'body', None) or b''
        if isinstance(body, str): body = body.encode('utf-8', 'replace')
        rec['body_bytes'] = max(rec['body_bytes'], len(body))
        rec['n_img'] = max(rec['n_img'], body.count(b'"type": "image"') + body.count(b'"image_url"'))
    except Exception:
        pass


def _llmt_line(rec, line):
    """SSE 行打点: 首个 data 行/首个推理/首个可见文字/首个工具调用 + 用量。字节匹配, 不解码正文。"""
    try:
        if not line: return
        b = line if isinstance(line, bytes) else str(line).encode('utf-8', 'replace')
        if not b.startswith(b'data:'): return
        if rec['first'] is None: rec['first'] = _llmt_dt(rec)
        for rx, key in _llmt_marks():
            if rec[key] is None and rx.search(b): rec[key] = _llmt_dt(rec)
        if b'"usage"' in b and b'"usage":null' not in b:
            import json
            evt = json.loads(b[5:].decode('utf-8', 'replace').strip())
            u = evt.get('usage') or (evt.get('message') or {}).get('usage') or {}
            inp = (u.get('input_tokens') or u.get('prompt_tokens') or 0) + (u.get('cache_read_input_tokens') or 0) + (u.get('cache_creation_input_tokens') or 0)
            out = u.get('output_tokens') or u.get('completion_tokens') or 0
            cr = u.get('cache_read_input_tokens') or ((u.get('prompt_tokens_details') or {}).get('cached_tokens')) or 0
            if inp: rec['in_tok'] = max(rec['in_tok'], int(inp))
            if out: rec['out_tok'] = max(rec['out_tok'], int(out))
            if cr: rec['cache_read'] = max(rec['cache_read'], int(cr))
    except Exception:
        pass


def patch_llm_timing():
    """胶水猴补丁(不改 llmcore): 包 _stream_with_retry, 给每次主模型请求记 发出→响应头→首个 SSE→推理/文字/工具首 token→结束,
    以及发出时的上下文字符数、图片数、重试/报错与服务端用量; 写入当前归属 sess.state['llm'] → poll.llm。
    只观察: 原样转发 chunk/返回值/异常, 记录失败静默。"""
    import android_entry as _ae
    import llmcore
    if getattr(llmcore, '_ga_llmt_patched', None) is _ae: return
    orig = getattr(llmcore, '_ga_llmt_orig', None) or llmcore._stream_with_retry
    def _stream_with_retry(*args, **kwargs):
        # payload 是第 4 个位置参数(_stream_with_retry(sess, url, headers, payload, parse_fn, json_fn=None));
        # 这里只按位置/kw 取自己要看的那一个, 其余原样转发 —— 抄全签名就会在改签名时把每个请求打成 TypeError。
        payload = args[3] if len(args) > 3 else (kwargs.get('payload') or {})
        try: rec = _llmt_open(payload)
        except Exception: rec = None
        g = orig(*args, **kwargs)
        try:
            while True:
                prev, _tls.llmt = getattr(_tls, 'llmt', None), rec   # 只在推进内层生成器时归属本记录: 弃用的生成器不会吞下后续请求
                try: chunk = next(g)
                except StopIteration as e: return e.value
                finally: _tls.llmt = prev
                if rec is not None and isinstance(chunk, str) and chunk.lstrip().startswith(('!!!Error', '[!!!')):
                    rec['errors'] += 1; rec['last_error'] = chunk.strip()[:120]
                yield chunk
        finally:
            try: g.close()
            except Exception: pass
            if rec is not None:
                try: rec['end'] = _llmt_dt(rec)
                except Exception: pass
    _stream_with_retry.__wrapped__ = orig
    llmcore._ga_llmt_orig = orig
    llmcore._stream_with_retry = _stream_with_retry
    llmcore._ga_llmt_patched = _ae


def patch_llm_reload():
    """胶水猴补丁(不改 agentmain): /llm 在 agent 自己的线程里先丢弃缓存的会话表, 再交给内核处理。
    内核按 mykey 的 mtime 只报一次 changed, 多个会话中只有第一个会重建; 丢弃后 load_llm_sessions 必按当前配置重建
    (历史经 self.llmclient 保留)。放在 agent 线程内执行, 不与正在处理上一条命令的 worker 竞争。"""
    import re
    import android_entry as _ae
    from agentmain import GenericAgent
    if getattr(GenericAgent, '_ga_llm_reload_patched', None) is _ae: return
    orig = getattr(GenericAgent, '_ga_llm_reload_orig', None) or GenericAgent._handle_slash_cmd
    def _handle_slash_cmd(self, raw_query, display_queue):
        if isinstance(raw_query, str) and re.match(r'/llm\s+\S', raw_query.strip()):
            self.__dict__.pop('llmclients', None)
        return orig(self, raw_query, display_queue)
    GenericAgent._ga_llm_reload_orig = orig
    GenericAgent._handle_slash_cmd = _handle_slash_cmd
    GenericAgent._ga_llm_reload_patched = _ae


def patch_abort():
    import android_entry as _ae
    import llmcore
    if getattr(llmcore, '_ga_abort_patched', None) is _ae: return   # 同 patch_usage: 按模块实例重绑
    llmcore.requests = _ReqProxy()                       # 包 post: 登记在飞响应 + 中止前不再发请求(代理类属新实例, 闭包自动指新 _ACTIVE_RESPS)
    llmcore.time = _TimeProxy()                          # 包 sleep: 中止时跳过退避(故障转移/重试不再卡几秒)
    llmcore._ga_abort_patched = _ae


def abort_streams(sess=None):
    """只关本会话 SSE；sess=None 时关全局 + 当前 TLS 归属（兼容旧 abort()）。"""
    bags = []
    if sess is not None:
        bags.append(_sess_resps(sess))
    else:
        bags.append(_ACTIVE_RESPS)
        s = current_sess()
        if s is not None:
            bags.append(_sess_resps(s))
    seen = set()
    for bag in bags:
        for r in list(bag):
            rid = id(r)
            if rid in seen: continue
            seen.add(rid)
            try: r.close()
            except Exception: pass


def set_route(llm_sess):
    """路由探针：写到当前归属 _Sess.route；无归属写全局 _ROUTE。"""
    import android_entry as _ae
    try:
        cls = llm_sess.__class__.__name__
        r = {'name': getattr(llm_sess, 'name', '') or '',
             'model': getattr(llm_sess, 'model', '') or '',
             'type': 'claude' if 'Claude' in cls else 'oai'}
        s = current_sess()
        if s is not None:
            s.route = r
            # 焦点会话同步全局，保 legacy poll.route
            try:
                fs = _ae._focus_sess()
                if fs is s or fs is None:
                    with _ae._lock: _ROUTE['cur'] = r
            except Exception:
                with _ae._lock: _ROUTE['cur'] = r
        else:
            with _ae._lock: _ROUTE['cur'] = r          # 与 send()/poll() 同锁(其余共享态一致), 虽 GIL 下单赋值已原子
    except Exception: pass


def patch_route_probe():
    """胶水猴补丁(不改 llmcore): 包 MixinSession 各成员的 raw_ask, 一被调用即记录当前路由成员 → poll.route。
    单服务商(非 mixin)不触发; 任务开始时清空 _ROUTE → UI 仅在故障转移运行时显示实际成员。"""
    import android_entry as _ae
    import llmcore
    Mix = getattr(llmcore, 'MixinSession', None)
    if Mix is None or getattr(Mix, '_ga_route_patched', None) is _ae: return   # 按模块实例重绑(同 patch_usage)
    orig_init = getattr(Mix, '_ga_route_orig_init', None) or Mix.__init__
    def __init__(self, all_sessions, cfg):
        orig_init(self, all_sessions, cfg)
        def wrap(s, fn):
            def g(*a, **k): set_route(s); return fn(*a, **k)
            return g
        try: self._orig_raw_asks = [wrap(self._sessions[i], fn) for i, fn in enumerate(self._orig_raw_asks)]
        except Exception: pass
    __init__.__doc__ = getattr(orig_init, '__doc__', None)
    Mix._ga_route_orig_init = orig_init
    Mix.__init__ = __init__
    Mix._ga_route_patched = _ae
