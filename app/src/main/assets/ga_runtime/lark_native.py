# -*- coding: utf-8 -*-
"""lark_native: 飞书全接口端内客户端(去 PC 化) —— 纯 requests 直调 open.feishu.cn/open-apis/*。

定位: 不装 lark-cli/Node/companion host, **不需要 ADB/无线调试**(纯端内 requests; 飞书任务永不走 ADB)。
窄腰 = api(method, path, params, payload, as_user): 任何开放平台 REST 端点一个入口全覆盖
(IM/Base/Wiki/Doc/...; 端点配方见 memory/lark_sop.md)。

两种身份:
- bot(tenant_access_token): 仅需 app_id+app_secret, 免登录; 看不到用户私有资源。api(...) 默认走 bot。
- user(user_access_token, 标准 OAuth 授权码流): 用户点授权页一次即得, 可读写用户私有资源(个人文档/云空间/日历)。
  流程 = user_auth_url() 生成授权链接(发聊天里让用户点) → 用户浏览器登录+授权 → 本地 127.0.0.1:3000 一次性回调抓 code
       → user_wait() 换 token(自动续期); 兜底 user_code_from_url(粘贴回跳URL)。api(..., as_user=True) 用 user 身份。

凭证(红线): 不硬编码。落盘/读取只走本模块 _load/_save, 物理路径 = 本模块同级 channels/lark.json
    (设备上 = GA 数据目录 files/ga/channels/lark.json; 运行时创建, 不入 APK assets/Evolution/日志/BBS)。
    app_secret / access_token / refresh_token 只在此文件与进程内存, 绝不进返回值/报错文本(仅 code/msg)/日志/对话。

一次性配置: 用户在 open.feishu.cn 建"企业自建应用"拿 App ID+App Secret → save_creds(id, secret);
    并在应用"安全设置"里把重定向 URL 加上 http://localhost:3000/callback(用户 OAuth 需要)。详见 lark_sop.md。
"""
import http.server
import json
import os
import secrets
import threading
import time
import urllib.parse

import requests

_DIR = os.path.dirname(os.path.abspath(__file__))
_OPEN = "https://open.feishu.cn/open-apis"
_ACCOUNTS = "https://accounts.feishu.cn/open-apis"
_CRED = os.path.join(_DIR, "channels", "lark.json")   # 运行时写入, 不入库
# OAuth 端点(单一真源: authorize 与 exchange 共用 _REDIRECT, 免除"注册值漂移"这类错配):
_AUTHZ = _ACCOUNTS + "/authen/v1/authorize"           # 用户授权页(响应 code)
_TOKEN = _OPEN + "/authen/v2/oauth/token"             # OAuth2 令牌端点(授权码/刷新共用)
_REDIRECT = "http://localhost:3000/callback"          # 须在开放平台"安全设置"注册(lark-mcp 默认值, PC 端配过的应用已有)
_CB_PORT = 3000

_tok = {"v": None, "exp": 0.0}                          # 进程内 tenant(bot) token 缓存
_STALE_BOT = (99991663, 99991661)                       # bot token 失效/过期 → 强刷重试一次
_STALE_USER = (99991668, 99991677)                      # user token 失效 → 强刷重试一次(精确码待真机核验)
_lock = threading.Lock()                                # user token 刷新串行化
_auth = {"state": None, "code": None, "httpd": None}    # 进程内授权会话(state 另落盘于 pending, 防进程死)


def _json(r, path):
    """非 JSON 响应(网关5xx HTML/运营商拦截页)转带上下文的报错, 不让裸 JSONDecodeError 穿透。"""
    try:
        return r.json()
    except ValueError:
        raise RuntimeError("%s HTTP %s 非JSON响应(网关/拦截页?): %.120s" % (path, r.status_code, r.text))


def _load():
    """读凭证存储(dict); 缺失返回空 dict。"""
    if not os.path.exists(_CRED):
        return {}
    with open(_CRED, encoding="utf-8") as f:
        return json.load(f)


def _save(obj):
    """原子写(tmp+os.replace): 防并发/崩溃留下半截 JSON。模块自己 makedirs, 调用方绝不拼相对路径。"""
    os.makedirs(os.path.dirname(_CRED), exist_ok=True)
    tmp = _CRED + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, _CRED)


def save_creds(app_id, app_secret):
    """落盘飞书凭证。换应用(app_id/secret 变)时作废旧 user token —— user token 是 per-app 的, 留着会用错身份。"""
    obj = _load()
    changed = obj.get("app_id") != app_id or obj.get("app_secret") != app_secret
    obj["app_id"] = app_id
    obj["app_secret"] = app_secret
    if changed:
        obj.pop("user", None)
        obj.pop("pending", None)
    _save(obj)
    _tok["v"] = None
    _tok["exp"] = 0.0
    return _CRED


def _creds():
    """读设备本地凭证; 缺失显式报错引导用户配置(不猜/不兜底默认值)。"""
    obj = _load()
    if not obj.get("app_id") or not obj.get("app_secret"):
        raise RuntimeError(
            "飞书凭证未配置: 先调 lark_native.save_creds(app_id, app_secret) "
            "(从飞书开放平台自建应用凭证页取; 只存本机 " + _CRED + ", 不进对话/日志)")
    return obj["app_id"], obj["app_secret"]


def tenant_token(force=False):
    """自建应用 tenant_access_token(bot 身份免登录, 仅需 app_id+app_secret)。缓存到过期前 60s。"""
    now = time.time()
    if not force and _tok["v"] and now < _tok["exp"]:
        return _tok["v"]
    app_id, app_secret = _creds()
    r = requests.post(_OPEN + "/auth/v3/tenant_access_token/internal",
                      json={"app_id": app_id, "app_secret": app_secret}, timeout=30)
    j = _json(r, "/auth/v3/tenant_access_token/internal")
    if j.get("code") != 0:
        raise RuntimeError("tenant_access_token 失败 code=%s msg=%s" % (j.get("code"), j.get("msg")))
    _tok["v"] = j["tenant_access_token"]
    _tok["exp"] = now + int(j.get("expire", 7200)) - 60
    return _tok["v"]


# ---------------- 用户身份 OAuth(user_access_token, 标准授权码流; 无需公网/无需 ADB) ----------------

def user_auth_url(scope="offline_access", timeout_s=300):
    """生成用户授权 URL 并起一次性本地回调监听(127.0.0.1:3000)。
    把返回的 URL 作为**可点链接发给用户**; 用户浏览器登录+授权后自动回跳被本地监听捕获 code。之后调 user_wait()。
    scope: 空格分隔; offline_access 换取 refresh_token(否则约 2h 需重新授权)。其余 scope 须在应用"权限管理"已开通。"""
    app_id, _ = _creds()
    state = secrets.token_urlsafe(16)
    obj = _load()
    obj["pending"] = {"state": state}   # 落盘: 进程被杀后 user_code_from_url 兜底仍可校验 state(飞书 code 服务端 ~5min 过期, 无需客户端 TTL)
    _save(obj)
    _auth["state"] = state
    _auth["code"] = None
    _start_listener(timeout_s)
    q = urllib.parse.urlencode({"client_id": app_id, "redirect_uri": _REDIRECT,
                                "response_type": "code", "scope": scope, "state": state})
    return _AUTHZ + "?" + q


def _start_listener(timeout_s):
    """一次性 loopback 回调监听。只接受 GET /callback 且 state 匹配的请求(防设备内其它 app 注入)。拿到 code 或超时即自关。"""
    _stop_listener()

    class _H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(u.query)
            code = (qs.get("code") or [None])[0]
            st = (qs.get("state") or [None])[0]
            ok = bool(code and st and st == _auth.get("state"))   # state 校验: 防注入/CSRF
            if ok:
                _auth["code"] = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "授权完成，请返回 GAgent。" if ok else "state 校验失败，请回 GAgent 重新发起授权。"
            self.wfile.write(("<html><body style='font:16px sans-serif;text-align:center;padding:3em'>%s</body></html>" % msg).encode("utf-8"))

        def log_message(self, *a):
            pass

    try:
        httpd = http.server.HTTPServer(("127.0.0.1", _CB_PORT), _H)   # HTTPServer.allow_reuse_address=1: TIME_WAIT 内可重启
    except OSError as e:
        raise RuntimeError("本地回调端口 %d 被占用/绑定失败(%s): 该端口须与开放平台注册的 redirect_uri(%s)一致; "
                           "关掉占用它的程序或重启 app 后重试" % (_CB_PORT, e, _REDIRECT))
    httpd.timeout = 1
    _auth["httpd"] = httpd

    def run():
        deadline = time.time() + timeout_s
        while _auth.get("httpd") is httpd and time.time() < deadline and not _auth.get("code"):
            try:
                httpd.handle_request()   # 单次, 1s 超时后回来复检条件
            except Exception:
                break
        try:
            httpd.server_close()
        except Exception:
            pass
        if _auth.get("httpd") is httpd:
            _auth["httpd"] = None

    threading.Thread(target=run, daemon=True).start()


def _stop_listener():
    httpd = _auth.get("httpd")
    _auth["httpd"] = None
    if httpd:
        try:
            httpd.server_close()   # 立即解绑端口, 使下次 user_auth_url 能重绑
        except Exception:
            pass


def user_wait(timeout_s=40):
    """轮询本地回调捕获的 code 并换 user_access_token。默认 40s(< code_run 默认 60s, 防线程无法强杀 + stdout 被劫持)。
    未拿到 code 会报错; 用户完成授权后**可再调 user_wait() 续等**, 或复制回跳 URL 调 user_code_from_url(url) 兜底。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _auth.get("code"):
            return _exchange(_auth["code"])
        time.sleep(1)
    raise RuntimeError(
        "等待授权超时(%ds): 用户完成授权后可再调 user_wait() 续等; 或让用户复制授权后浏览器回跳的完整地址"
        "(飞书 App 内 webview 无地址栏时点右上 ··· → 在浏览器中打开/复制链接), 调 user_code_from_url(url) 兜底" % timeout_s)


def user_code_from_url(url):
    """兜底: 从用户粘贴的回跳 URL(含 ?code=&state=)解析并换 token。state 对落盘的 pending 值校验(进程死后仍有效)。"""
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    code = (qs.get("code") or [None])[0]
    st = (qs.get("state") or [None])[0]
    if not code:
        raise RuntimeError("URL 中无 code: 请粘贴授权后浏览器回跳的完整地址(形如 %s?code=...&state=...)" % _REDIRECT)
    pending = _load().get("pending") or {}
    if not st or st != pending.get("state"):
        raise RuntimeError("state 不匹配(授权会话已过期或非本次): 请重新调 user_auth_url() 发起授权")
    return _exchange(code)


def _exchange(code):
    """授权码换 user token(+refresh)并落盘, 清 pending, 返回 me()。"""
    app_id, app_secret = _creds()
    r = requests.post(_TOKEN, json={"grant_type": "authorization_code", "client_id": app_id,
                                    "client_secret": app_secret, "code": code, "redirect_uri": _REDIRECT}, timeout=30)
    j = _json(r, "/authen/v2/oauth/token")
    if not j.get("access_token"):
        raise RuntimeError("换取 user token 失败 code=%s msg=%s" % (j.get("code"), j.get("msg") or j.get("error")))
    _persist_user(j)
    obj = _load()
    obj.pop("pending", None)   # 用掉即清
    _save(obj)
    _auth["code"] = None
    _stop_listener()
    return me()


def _persist_user(j):
    """原子落盘 user token; refresh_token 单次可用, 刷新时须先落新的再返回(见 user_token)。"""
    now = time.time()
    obj = _load()
    u = obj.get("user") or {}
    u["access_token"] = j["access_token"]
    u["expires_at"] = now + int(j.get("expires_in", 7200)) - 60
    if j.get("refresh_token"):
        u["refresh_token"] = j["refresh_token"]
        u["refresh_expires_at"] = now + int(j.get("refresh_token_expires_in", 30 * 24 * 3600)) - 60
    obj["user"] = u
    _save(obj)


def user_token(force=False):
    """保证返回 ≥60s 有效的 user_access_token; 过期用 refresh_token 续(串行化, 原子落新单次 token 后再返回)。
    无 user 授权 / refresh 失效 → 报错引导 user_auth_url()。"""
    with _lock:
        u = _load().get("user") or {}
        if not force and u.get("access_token") and time.time() < u.get("expires_at", 0):
            return u["access_token"]
        rt = u.get("refresh_token")
        if not rt or time.time() >= u.get("refresh_expires_at", 0):
            raise RuntimeError("用户身份未授权或已过期: 调 user_auth_url() 生成链接发用户授权, 再 user_wait()")
        app_id, app_secret = _creds()
        r = requests.post(_TOKEN, json={"grant_type": "refresh_token", "client_id": app_id,
                                        "client_secret": app_secret, "refresh_token": rt}, timeout=30)
        j = _json(r, "/authen/v2/oauth/token(refresh)")
        if not j.get("access_token"):
            raise RuntimeError("刷新 user token 失败(需重新授权 user_auth_url) code=%s msg=%s"
                               % (j.get("code"), j.get("msg") or j.get("error")))
        _persist_user(j)   # 先原子落新的单次 refresh_token, 再返回, 避免崩溃丢失续期链
        return j["access_token"]


# ---------------- 通用入口 ----------------

def api(method, path, params=None, payload=None, as_user=False):
    """唯一通用入口。path 相对 open-apis, 如 '/im/v1/messages'; payload=JSON body(dict)。
    as_user=True 用 user_access_token(个人私有资源), 否则用 bot tenant_access_token。身份由 as_user 唯一决定, 绝不静默回退到另一身份。
    code==0 返回 data(旧式端点载荷挂顶层非 data, 如 /bot/v3/info, 此时回退返回整个响应体)。token 失效自动强刷同身份重试一次。"""
    def once():
        tok = user_token() if as_user else tenant_token()
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        r = requests.request(method, _OPEN + path, params=params, data=body,
                             headers={"Authorization": "Bearer " + tok,
                                      "Content-Type": "application/json; charset=utf-8"},
                             timeout=30)
        return _json(r, path)
    j = once()
    if j.get("code") in (_STALE_USER if as_user else _STALE_BOT):
        (user_token if as_user else tenant_token)(force=True)
        j = once()
    if j.get("code") != 0:
        raise RuntimeError("%s code=%s msg=%s" % (path, j.get("code"), j.get("msg")))
    if "data" in j:
        return j["data"]
    return {k: v for k, v in j.items() if k not in ("code", "msg")}


def bot_info():
    """bot 连通验证: 返回 {app_name, open_id, ...} ⟺ 凭证与链路通。"""
    return api("GET", "/bot/v3/info").get("bot", {})


def me():
    """user 身份连通验证: 返回 {name, open_id, ...} ⟺ user token 有效。bot_info 的用户身份对应物。"""
    return api("GET", "/authen/v1/user_info", as_user=True)


def send_text(receive_id, text, receive_id_type="open_id"):
    """发纯文本消息。receive_id_type ∈ {open_id, user_id, union_id, email, chat_id}。
    危险动作(发消息给他人): 调用方须先过 [VERIFY] 人确认(见 SOP 红线)。"""
    d = api("POST", "/im/v1/messages", params={"receive_id_type": receive_id_type},
            payload={"receive_id": receive_id, "msg_type": "text",
                     "content": json.dumps({"text": str(text)}, ensure_ascii=False)})
    return d.get("message_id", "")
