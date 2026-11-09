# -*- coding: utf-8 -*-
"""webcdp — CDP 驱动内置/系统浏览器, 复用其登录态 (files/ga/webcdp.py)

背后连的是安卓自带的 Chrome DevTools 抽象命名空间 socket(非本 App 起的进程), 拿到的是
用户真实浏览器/WebView 的已登录 DOM+Cookie, 免去 code_run+截图OCR 猜坐标。用法:
    import webcdp
    webcdp.connect()                      # 探测本机 devtools socket 并建连, 返回 {target,url,title}
    webcdp.web_open('https://x.com')      # Page.navigate + 等 load
    els = webcdp.web_scan()               # 可见可交互元素 [{tag,role,text,href,type,bbox}]
    webcdp.web_click(els[0]['bbox'][:2])  # (x,y) 走 CDP 合成鼠标事件; 传 CSS selector 则走 JS click
    webcdp.web_type('hello')              # 当前焦点元素输入; sel=显式定位输入框
    cookies = webcdp.web_cookies('example.com')
    img = webcdp.web_shot()               # 存 png, 返回路径
    webcdp.close()

浏览器三级路由(open_url 默认走 L1 前台): L1 role='fg'=前台任务浏览器 AgentBrowserActivity(用户可见+可截图+可CDP,
绝大多数"用浏览器…"任务走这条); L2 role='browser'=离屏虚拟屏(用户明确说"后台"才走); L3=droid.launch 系统浏览器+视觉兜底。
role='fg'/'browser' 各只绑自己的 data: 哨兵 tab(_whitelist_tab: fg=ga-task / browser=ga-automation, 硬白名单),
不变量#3: 永不误绑用户可见登录浏览器 BrowserActivity——那里有用户人工登录的隐私会话(FLAG_SECURE 保护, 且无哨兵结构上连不到)。
role='raw' 老行为 target 优先级: chrome_devtools_remote(系统Chrome前台暴露) >
webview_devtools_remote_<本进程pid>(GA 自身 WebView, 同域必通) > content_shell_devtools_remote >
/proc/net/unix 扫到的其它 *devtools_remote*。传具体名字可强指定目标。
握手不发 Origin 头(suppress_origin): Chromium111+ 带 Origin 会拒握手(gandroid_v28 实测教训)。
不依赖第三方包: 手写最小 WebSocket 客户端(握手+文本帧掩码/长度编解码), 仅用标准库。
全部候选连接失败 → connect() 显式 raise; 本模块不做兜底, 由调用者回退 droid.shot()+ui_detect。
"""
import base64
import hashlib
import json
import os
import socket
import struct
import time
import urllib.error
import urllib.parse

import bus_auth
from service_http import open_request


def _track_path(kind):
    """路径埋点(任务级聚合 + 每任务首次 webcdp 建连补一条 agent_web_path 便于单看网页路径漏斗)。
    惰性 import + 全吞异常: PC 侧调试无 plugins 包也不报错; 只报类别枚举, 无 URL/域名(脱敏铁律)。"""
    try:
        from plugins.analytics_hook import record_path, _emit, _STATE
        first_web = not any(k.startswith('web_') for k in (_STATE.get('paths') or {}))
        record_path(kind)
        if first_web:
            _emit('agent_web_path', {'role': kind})
    except Exception:
        pass
import urllib.request

import run_guard   # 僵尸线程护栏: code_run 超时/被停后, 后台线程经 CDP 持续点击/输入/导航登录态网页 → 在 _call/ensure 被拒

_CHAT_MARK = "webui/index.html"   # 对话页 tab 的 url 特征; webcdp 只驱动 url 不含它的 tab(不变量#2)
_AUTO_MARK = "ga-automation"      # 离屏自动化 WebView(WebController.AUTO_HOME)首载哨兵页 url 标记(role='browser' 白名单锚点)
_FG_MARK = "ga-task"              # 前台任务浏览器(AgentBrowserActivity)首载哨兵页 url 标记(role='fg' 白名单锚点; 与登录浏览器结构区分)
_DIR = os.path.dirname(os.path.abspath(__file__))
_TIMEOUT = 15  # 所有网络调用的默认超时(秒), 避免卡死 agent
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_SCAN_JS = """(() => {
  const sel = 'a,button,input,textarea,select,[role],[onclick],[tabindex]';
  const out = [];
  document.querySelectorAll(sel).forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') return;
    const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0, 80);
    out.push({tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || '', text: text,
              href: el.getAttribute('href') || '', type: el.getAttribute('type') || '',
              bbox: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]});
  });
  return out.slice(0, 200);
})()"""

_conn = None  # 单例连接(显式命名, 唯一可变全局状态); None=未连接


class _Buf:
    """socket 读缓冲: 按需 recv 攒够 n 字节/直到分隔符, 超预算 deadline 显式报错。"""

    def __init__(self, sock):
        self.sock = sock
        self.data = b""

    def take(self, n, deadline):
        while len(self.data) < n:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("devtools socket read timeout")
            self.sock.settimeout(remaining)
            chunk = self.sock.recv(max(4096, n - len(self.data)))
            if not chunk:
                raise ConnectionError("devtools socket closed")
            self.data += chunk
        out, self.data = self.data[:n], self.data[n:]
        return out

    def take_until(self, sep, deadline):
        while sep not in self.data:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("devtools socket read timeout")
            self.sock.settimeout(remaining)
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("devtools socket closed")
            self.data += chunk
        idx = self.data.index(sep) + len(sep)
        out, self.data = self.data[:idx], self.data[idx:]
        return out


class _Conn:
    """一个 devtools socket + 一条已握手 WebSocket 的会话态。role 记录建连路径(browser/raw), 供缓存复用校验。"""

    def __init__(self, name, sock, buf, tab, role="browser"):
        self.name, self.sock, self.buf, self.tab, self.role = name, sock, buf, tab, role
        self.msg_id = 0

    def call(self, method, params=None, timeout=_TIMEOUT):
        self.msg_id += 1
        mid = self.msg_id
        _send_frame(self.sock, 0x1, json.dumps({"id": mid, "method": method, "params": params or {}}).encode())
        deadline = time.monotonic() + timeout
        while True:
            opcode, payload = _recv_message(self.buf, deadline)
            if opcode == 0x8:
                raise ConnectionError("devtools ws closed: %r" % payload[:200])
            if opcode in (0x9, 0xA) or opcode != 0x1:
                continue  # ping/pong/非文本帧: 忽略继续等真正响应
            try:
                msg = json.loads(payload.decode("utf-8"))
            except Exception:
                continue
            if msg.get("id") != mid:
                continue  # 其它 target 的事件通知, 非本次调用的响应, 丢弃继续等
            if "error" in msg:
                raise RuntimeError("CDP %s error: %s" % (method, msg["error"]))
            return msg.get("result", {})


def _connect_abstract(name, timeout):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(b"\0" + name.encode())
    return sock


def _send_frame(sock, opcode, payload):
    """客户端→服务端帧必须掩码(RFC6455)。"""
    b0 = 0x80 | (opcode & 0x0F)
    n = len(payload)
    if n < 126:
        hdr = bytes([b0, 0x80 | n])
    elif n < 65536:
        hdr = bytes([b0, 0x80 | 126]) + struct.pack("!H", n)
    else:
        hdr = bytes([b0, 0x80 | 127]) + struct.pack("!Q", n)
    mask = os.urandom(4)
    masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    sock.sendall(hdr + mask + masked)


def _recv_frame(buf, deadline):
    hdr = buf.take(2, deadline)
    b0, b1 = hdr[0], hdr[1]
    fin, opcode = bool(b0 & 0x80), b0 & 0x0F
    masked, n = bool(b1 & 0x80), b1 & 0x7F
    if n == 126:
        n = struct.unpack("!H", buf.take(2, deadline))[0]
    elif n == 127:
        n = struct.unpack("!Q", buf.take(8, deadline))[0]
    mask = buf.take(4, deadline) if masked else None
    payload = buf.take(n, deadline)
    if masked:
        payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    return fin, opcode, payload


def _recv_message(buf, deadline):
    """聚合延续帧(CDP 实测通常单帧, 仍兜底处理), 返回 (opcode, 完整payload)。"""
    parts, msg_opcode = [], None
    while True:
        fin, opcode, payload = _recv_frame(buf, deadline)
        if opcode != 0x0:
            msg_opcode = opcode
        parts.append(payload)
        if fin:
            return msg_opcode, b"".join(parts)


def _candidates():
    """目标 socket 名候选(优先级见 module docstring); /proc/net/unix 扫描失败静默忽略(仍有前3个硬编码兜底)。"""
    pid = os.getpid()
    names = ["chrome_devtools_remote", "webview_devtools_remote_%d" % pid, "content_shell_devtools_remote"]
    try:
        with open("/proc/net/unix", encoding="utf-8", errors="ignore") as f:
            for line in f:
                i = line.rfind("@")
                if i < 0:
                    continue
                name = line[i + 1:].strip()
                if "devtools_remote" in name and name not in names:
                    names.append(name)
    except Exception:
        pass
    return names


def _own_socket():
    return "webview_devtools_remote_%d" % os.getpid()


def _pick_tab(tabs, browser):
    """不变量#2(永不误导航对话页)对**全部 role 无条件生效**: 恒排除含对话页标记的 tab(旧版仅 browser=True 才排,
    raw 路径 Chrome socket 不可达时会落到自身 pid socket 误导航对话页——已修)。
    本函数只服务显式 target/raw 高级路径; role='browser'/'fg' 默认走 _whitelist_tab 硬白名单(各自 mark)。"""
    pages = [t for t in tabs if t.get("webSocketDebuggerUrl") and _CHAT_MARK not in (t.get("url") or "")]
    return next((t for t in pages if t.get("type") == "page"), None) or (pages[0] if pages else None)


_PIN_PATH = os.path.join(_DIR, "temp", ".webcdp_pin.txt")        # role='browser' 离屏自动化 tab id; 点前缀=内部命名空间(不进用户产物面)
_FG_PIN_PATH = os.path.join(_DIR, "temp", ".webcdp_fg_pin.txt")  # role='fg' 前台任务浏览器 tab id(与离屏分开, 否则两 tab 互相覆盖 pin); 旧名迁移统一在 android_entry 启动时做


def _read_pin(path=_PIN_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _write_pin(tab_id, path=_PIN_PATH):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(tab_id)
    except Exception:
        pass   # pin 只是加速/加固缓存, 写失败下次仍可经 ensure_url/哨兵识别


def _whitelist_tab(tabs, ensure_url, mark, pin_path):
    """role='browser'(离屏)与 'fg'(前台)共用的硬白名单识别(不变量#3, fail-closed) —— 唯一差异是 mark 哨兵与 pin 存档。
    只绑自动化/任务浏览器自己的 tab, 身份三选一: ① 钉住的 tab id(导航后仍稳定) ② ensure 权威 url 唯一匹配
    ③ 建页 data: 哨兵(mark; 真实网页可经 pushState 伪造 http url 里的标记串, data: 伪造不了)。
    全部识别不了 → None → connect raise, 绝不退化成"随便挑一个非对话页 tab"(会误绑用户可见登录浏览器读隐私)。"""
    pages = [t for t in tabs if t.get("webSocketDebuggerUrl") and _CHAT_MARK not in (t.get("url") or "")]
    pin = _read_pin(pin_path)
    hit = next((t for t in pages if pin and t.get("id") == pin), None)
    if hit is None and ensure_url and ensure_url != "about:blank":   # about:blank 是任何新开 tab 的泛型 url, 不构成身份
        matches = [t for t in pages if (t.get("url") or "") == ensure_url]
        hit = matches[0] if len(matches) == 1 else None
    if hit is None:
        hit = next((t for t in pages if (t.get("url") or "").startswith("data:") and mark in (t.get("url") or "")), None)
    if hit is not None and hit.get("id"):
        _write_pin(hit["id"], pin_path)
    return hit


def _bus_port(timeout=3):
    """总线端口。bus_port.txt 缺失 ≠ 服务未启动(与 droid._base 同一契约): 回退默认 18765 并 ping 验活(校验 ver 字段);
    验活失败给精准诊断——总线组件未监听=重启 App 恢复, 与 agent 是否运行无关。"""
    try:
        with open(os.path.join(_DIR, "bus_port.txt")) as f:
            return f.read().strip()
    except OSError:
        try:
            with open_request(urllib.request.Request("http://127.0.0.1:18765/ping", headers=bus_auth.headers("http://127.0.0.1:18765/ping")), timeout=timeout) as r:
                if "ver" in json.loads(r.read().decode("utf-8")):
                    return "18765"
        except Exception:
            pass
        raise RuntimeError("APK 内设备总线未监听(bus_port.txt 缺失且 18765 ping 不通): 重启 App 即恢复; "
                           "与 agent/会话是否运行无关, 勿引导用户找『启动核心服务』按钮。") from None


def ensure(timeout=_TIMEOUT):
    """经 GA 总线让 App 幂等建/复用离屏浏览器 WebView(不遮挡对话页), 返回 {ok,title,url,viewport}。
    仅 role='browser'(后台离屏)路径需要; 失败(总线未起/无 Context)显式 raise, 由调用者据错退纯视觉。"""
    run_guard.check()   # 僵尸线程护栏: 已取消则不再建离屏 WebView
    port = _bus_port()
    with open_request(urllib.request.Request("http://127.0.0.1:%s/web/ensure" % port, headers=bus_auth.headers("http://127.0.0.1:%s/web/ensure" % port)), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ensure_fg(timeout=_TIMEOUT):
    """经 GA 总线拉起/复用「前台任务浏览器」(AgentBrowserActivity: 用户可见 + 可截图 + CDP 可驱动),
    返回 {ok,url,...}。role='fg'(默认前台)路径用; 失败显式 raise, 由调用者退离屏或 droid+视觉。"""
    run_guard.check()
    port = _bus_port()
    try:
        with open_request(urllib.request.Request("http://127.0.0.1:%s/web/ensure_fg" % port, headers=bus_auth.headers("http://127.0.0.1:%s/web/ensure_fg" % port)), timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:   # 旧 APK 无此端点(python 资产热更快于 APK): 给可诊断报错+活路, 别裸抛泛 404
            raise RuntimeError("GA APK 过旧: 无 /web/ensure_fg 前台浏览器端点。改用 open_url(url, background=True) "
                               "走离屏, 或升级 APK(部署顺序: APK 先于 python 资产)") from None
        raise


def _list_tabs(name, timeout):
    sock = _connect_abstract(name, timeout)
    try:
        deadline = time.monotonic() + timeout
        sock.sendall(b"GET /json HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        buf = _Buf(sock)
        head = buf.take_until(b"\r\n\r\n", deadline)
        status_line = head.split(b"\r\n", 1)[0]
        if b" 200 " not in status_line:
            raise RuntimeError("bad /json status: %s" % status_line)
        cl = None
        for line in head.split(b"\r\n")[1:]:
            if line.lower().startswith(b"content-length:"):
                cl = int(line.split(b":", 1)[1].strip())
                break
        if cl is not None:
            body = buf.take(cl, deadline)
        else:  # 无 Content-Length: 读到连接关闭(已请求 Connection: close)
            body = buf.data
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                sock.settimeout(remaining)
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    break
                if not chunk:
                    break
                body += chunk
        return json.loads(body.decode("utf-8"))
    finally:
        sock.close()


def _ws_handshake(name, ws_url, timeout):
    parts = urllib.parse.urlsplit(ws_url)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    sock = _connect_abstract(name, timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    req = ("GET %s HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
           "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n") % (path, key)
    # 刻意不发 Origin 头: Chromium111+ 带 Origin 会拒握手(gandroid_v28 实测)
    sock.sendall(req.encode())
    deadline = time.monotonic() + timeout
    buf = _Buf(sock)
    head = buf.take_until(b"\r\n\r\n", deadline)
    status_line = head.split(b"\r\n", 1)[0]
    if b" 101 " not in status_line:
        sock.close()
        raise RuntimeError("ws handshake rejected: %s" % status_line)
    expect = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
    accept = None
    for line in head.split(b"\r\n")[1:]:
        if line.lower().startswith(b"sec-websocket-accept:"):
            accept = line.split(b":", 1)[1].strip().decode()
            break
    if accept != expect:
        sock.close()
        raise RuntimeError("ws accept mismatch (got %r)" % accept)
    return sock, buf


def connect(target="auto", timeout=_TIMEOUT, force=False, role="browser"):
    """建连并缓存单例(缓存复用必须同 role, 防信任级混用)。
    role='fg'(前台任务浏览器, open_url 默认): ensure_fg() 拉起 AgentBrowserActivity(用户可见+可截图)→ _whitelist_tab 硬白名单只绑 ga-task 哨兵 tab。
    role='browser'(离屏后台): ensure() 建离屏 WebView → _whitelist_tab 硬白名单只绑 ga-automation 哨兵 tab(不遮挡对话页)。
    两者都守不变量#2(永不导航对话页)/#3(永不绑用户登录浏览器, 隐私)。
    role='raw': 老行为(按 _candidates 优先级, 可连系统 Chrome), 供高级用途, 无不变量#3保护。
    target 传具体 socket 名可强指定(同 raw 信任级)。全部失败 → 显式 raise(调用者退 droid.shot()+ui_detect)。返回 {target,url,title}。"""
    global _conn
    if _conn is not None:
        if not force and _conn.role == role:   # 缓存复用必须同 role: raw 建的连接绝不冒充 browser 白名单路径(不变量#3)
            _track_path({"fg": "web_fg", "browser": "web_bg"}.get(_conn.role, "web_raw"))   # 缓存命中也是 connect 成功出口: 跨任务复用连接时本任务的 web 归属不丢
            return {"target": _conn.name, "url": _conn.tab.get("url"), "title": _conn.tab.get("title")}
        close()
    if role == "browser" and target == "auto":
        return _connect_browser(timeout)
    if role == "fg" and target == "auto":
        return _connect_fg(timeout)
    candidates = [target] if target != "auto" else _candidates()
    errors = []
    for name in candidates:
        try:
            tabs = _list_tabs(name, timeout)
            tab = _pick_tab(tabs, role == "browser")
            if tab is None:
                raise RuntimeError("no inspectable tab")
            sock, buf = _ws_handshake(name, tab["webSocketDebuggerUrl"], timeout)
        except Exception as e:
            errors.append("%s: %s" % (name, e))
            continue
        _conn = _Conn(name, sock, buf, tab, "raw")   # 显式 target 同 raw 信任级
        _track_path("web_raw")
        return {"target": name, "url": tab.get("url"), "title": tab.get("title")}
    raise RuntimeError("no usable devtools socket, tried %s (%s); fallback to droid.shot()+ui_detect" % (candidates, "; ".join(errors)))


def _connect_browser(timeout):
    """role='browser' 默认路径: ensure() 幂等建离屏 WebView → 短轮询(target 注册滞后于 ensure 返回)
    _whitelist_tab(ga-automation 哨兵)唯一识别自动化 tab → 握手。识别失败 fail-closed raise, 绝不降级乱绑。"""
    global _conn
    info = ensure(timeout)
    name = _own_socket()
    deadline = time.monotonic() + 3
    tab, last_err = None, ""
    while tab is None and time.monotonic() < deadline:
        try:
            tab = _whitelist_tab(_list_tabs(name, timeout), info.get("url") or "", _AUTO_MARK, _PIN_PATH)
        except Exception as e:
            last_err = str(e)
        if tab is None:
            time.sleep(0.3)
    if tab is None:
        raise RuntimeError("webcdp: 无法唯一识别离屏自动化tab(不变量#3 fail-closed, 不误绑可见登录浏览器)%s; "
                           "回退 droid.shot()+ui_detect" % ("; last=" + last_err if last_err else ""))
    sock, buf = _ws_handshake(name, tab["webSocketDebuggerUrl"], timeout)
    _conn = _Conn(name, sock, buf, tab, "browser")
    _track_path("web_bg")
    return {"target": name, "url": tab.get("url"), "title": tab.get("title")}


def _connect_fg(timeout):
    """role='fg' 前台路径: ensure_fg() 拉起可见任务浏览器 → 短轮询 _whitelist_tab(ga-task 哨兵)唯一识别 → 握手。
    Activity 冷启比离屏久, 轮询放宽到 5s。识别失败 fail-closed raise, 由调用者退离屏/droid+视觉。"""
    global _conn
    info = ensure_fg(timeout)
    if not info.get("ok"):   # 前台浏览器未就绪(GA 不在前台被系统 BAL 拦后台启动 / 无悬浮窗权限): 快失败, 不再盲轮询 5s
        raise RuntimeError("前台任务浏览器未能就绪(可能 GA 不在前台被拦截后台启动, 或无悬浮窗权限): "
                           "改用 open_url(url, background=True) 走离屏, 或让 GA 回到前台再试")
    name = _own_socket()
    deadline = time.monotonic() + 5
    tab, last_err = None, ""
    while tab is None and time.monotonic() < deadline:
        try:
            tab = _whitelist_tab(_list_tabs(name, timeout), info.get("url") or "", _FG_MARK, _FG_PIN_PATH)
        except Exception as e:
            last_err = str(e)
        if tab is None:
            time.sleep(0.3)
    if tab is None:
        raise RuntimeError("webcdp: 无法识别前台任务浏览器 tab(fail-closed, 不误绑登录浏览器/对话页); "
                           "回退离屏 open_url(background=True) 或 droid.shot()+ui_detect%s"
                           % ("; last=" + last_err if last_err else ""))
    sock, buf = _ws_handshake(name, tab["webSocketDebuggerUrl"], timeout)
    _conn = _Conn(name, sock, buf, tab, "fg")
    _track_path("web_fg")
    return {"target": name, "url": tab.get("url"), "title": tab.get("title")}


def close():
    global _conn
    if _conn is not None:
        try:
            _conn.sock.close()
        except Exception:
            pass
        _conn = None


def _call(method, params=None, timeout=_TIMEOUT):
    run_guard.check()   # CDP 副作用唯一漏斗(navigate/eval/click/type/shot) → 僵尸线程护栏: 已取消则抛 RunCancelled 自毁
    if _conn is None:
        raise RuntimeError("webcdp 未连接: 先调用 connect()")
    try:
        return _conn.call(method, params, timeout)
    except OSError as e:  # 断线: 清空单例自愈(下次调用会重连), 本次仍显式报错
        close()
        raise RuntimeError("devtools 连接已断开(已自动清理, 请重新 connect()): %r" % (e,)) from e


def web_open(url, wait_load=10, timeout=_TIMEOUT):
    """Page.navigate 到 url, 轮询 document.readyState 至多 wait_load 秒。"""
    _call("Page.enable", timeout=timeout)
    _call("Page.navigate", {"url": url}, timeout=timeout)
    deadline = time.monotonic() + wait_load
    state = ""
    while time.monotonic() < deadline:
        try:
            state = web_eval("document.readyState", timeout=3)
        except Exception:
            state = ""
        if state == "complete":
            break
        time.sleep(0.3)
    return {"url": url, "readyState": state}


def web_eval(js, timeout=_TIMEOUT):
    """Runtime.evaluate(returnByValue, awaitPromise), 返回 JS 值; JS 抛错/reject → raise。"""
    res = _call("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True}, timeout=timeout)
    exc = res.get("exceptionDetails")
    if exc:
        desc = (exc.get("exception") or {}).get("description") or exc.get("text") or str(exc)
        raise RuntimeError("web_eval JS 异常: %s" % desc)
    return res.get("result", {}).get("value")


def web_cookies(domain=None, timeout=_TIMEOUT):
    """Network.getAllCookies; domain 给出则按子串过滤。"""
    cookies = _call("Network.getAllCookies", timeout=timeout).get("cookies", [])
    if domain:
        cookies = [c for c in cookies if domain in (c.get("domain") or "")]
    return cookies


def web_shot(path=None, timeout=20):
    """Page.captureScreenshot → 存 png, 返回路径(backdrop-filter 等破图由调用者自行处理)。"""
    # fromSurface 必须显式给: Android WebView(MEIZU 21 / WebView 155 实测)缺省时一直等新帧, 静态页 20s 超时; 显式 True 0.4s 返回
    res = _call("Page.captureScreenshot", {"format": "png", "fromSurface": True}, timeout=timeout)
    data = base64.b64decode(res["data"])
    if path is None:
        path = os.path.join(_DIR, "temp", "webcdp_%d.png" % int(time.time() * 1000))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def web_scan(timeout=_TIMEOUT):
    """可见可交互元素简化列表(纯 JS 端提取, 仿 simphtml 思想) [{tag,role,text,href,type,bbox:[x,y,w,h]}]。"""
    return web_eval(_SCAN_JS, timeout=timeout)


def open_url(url, wait_load=10, shot=True, background=False):
    """一步到位打开网页并 CDP 驱动。**默认前台可见**(background=False): 走 AgentBrowserActivity —
    用户看得见 GA 在操作、可截图、可 CDP,是绝大多数"用浏览器…"任务应走的路。
    background=True 才用离屏虚拟屏(用户明确说"后台/别占屏/不打扰"时); 两条都不可用(CDP 建连失败/站点反 WebView)
    再由调用者退 L3 = droid.launch(系统浏览器包)+droid 视觉操作。
    返回 {url, readyState, where, shot}(shot=files/ga/temp 下 png 路径, agent 引用即在对话页内联渲染)。"""
    if background:
        connect(role="browser")
    else:
        ensure_fg()           # 每次都把前台浏览器带到前台(兑现 L1 可见性; connect 缓存命中时也生效, 旧实例被切后台会前移)
        connect(role="fg")
    res = web_open(url, wait_load=wait_load)
    res["where"] = "background" if background else "foreground"
    if shot:
        try:
            res["shot"] = web_shot(timeout=8)
        except RuntimeError as e:   # 页面已打开: 截图失败只记在结果里, 不让整次 open_url 报错(否则 agent 会重复打开同一页)
            res["shot"] = None
            res["shot_error"] = str(e)
    return res


def web_click(sel_or_xy, timeout=_TIMEOUT):
    """str → CSS selector, 走 JS querySelector+click(对纯前端监听足够)。
    (x,y) → 视口坐标, 走 CDP Input.dispatchMouseEvent 三事件(moved→pressed→released, isTrusted=true)。"""
    if isinstance(sel_or_xy, str):
        js = "(() => { const el = document.querySelector(%s); if (!el) return false; el.scrollIntoView({block:'center'}); el.click(); return true; })()" % json.dumps(sel_or_xy)
        if not web_eval(js, timeout=timeout):
            raise RuntimeError("web_click: 未找到元素 %r" % sel_or_xy)
        return {"ok": True, "via": "js"}
    x, y = sel_or_xy
    for typ in ("mouseMoved", "mousePressed", "mouseReleased"):
        _call("Input.dispatchMouseEvent", {"type": typ, "x": float(x), "y": float(y), "button": "left", "clickCount": 1}, timeout=timeout)
    return {"ok": True, "via": "cdp", "x": x, "y": y}


def web_type(text, sel=None, timeout=_TIMEOUT):
    """优先 JS 设值(触发 React 受控输入用原生 setter)+dispatch input/change; sel 省略=当前焦点元素。
    JS 路径无目标元素(el为空) → 兜底 CDP Input.dispatchKeyEvent 逐字符发给当前已有焦点。"""
    target = "document.activeElement" if sel is None else "document.querySelector(%s)" % json.dumps(sel)
    js = (
        "(() => { const el = %s; if (!el) return false; el.focus && el.focus();"
        " if ('value' in el) { const d = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value');"
        " if (d && d.set) d.set.call(el, %s); else el.value = %s;"
        " el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }"
        " else { document.execCommand('insertText', false, %s); }"
        " return true; })()"
    ) % (target, json.dumps(text), json.dumps(text), json.dumps(text))
    if web_eval(js, timeout=timeout):
        return {"ok": True, "via": "js"}
    for ch in text:
        _call("Input.dispatchKeyEvent", {"type": "char", "text": ch}, timeout=timeout)
    return {"ok": True, "via": "cdp"}
