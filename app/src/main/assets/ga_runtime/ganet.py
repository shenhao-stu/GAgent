"""Self-hosted mesh pairing and SSH with pinned host keys."""
import hashlib
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import ganet_pairing_protocol as pairing_protocol
import service_config
import bus_auth
from service_http import open_request

BUS = bus_auth.BUS_URL

SSH_LOCAL_PORT = 2222         # 手机本地转发端口 → 已配对电脑的登记 SSH 端口
# 电脑地址不再写死：由 /provision/devices 按 uid 动态发现（多设备支持，见设计 §7-F）。

GA_DIR = os.path.dirname(os.path.abspath(__file__))
_SSH_DIR = os.path.join(GA_DIR, "ssh")
_KEY_PATH = os.path.join(_SSH_DIR, "id_ed25519")
# 会话级设备绑定：{convoId: hostname}。会话 id 由 android_entry 写在 kv/ga.active_convo。
# 每条会话各自绑一台电脑，互不干扰；用户经 /pc 命令管理（见 pc_use_sop.md）。
_BIND_PATH = os.path.join(GA_DIR, "kv", "ga.pc_bind.json")
_ACTIVE_CONVO_PATH = os.path.join(GA_DIR, "kv", "ga.active_convo")
_DEVICE_PATH = os.path.join(GA_DIR, "kv", "ga.device.json")
_ANDROID_DEVICE_PATH = os.path.join(GA_DIR, "kv", "ga.android_device.json")
_COMPUTERS_PATH = os.path.join(GA_DIR, "kv", "ga.paired_computers.json")
DEFAULT_SSH_PORT = 48222
PC_TOOL_PROTOCOL = 1
PC_TOOL_MAX_RESPONSE = 256 * 1024
PC_SCREENSHOT_MAX_BYTES = 5 * 1024 * 1024
PC_TOOL_COMMAND = "~/.genericagent/ganet/atomic-bridge"
PC_TOOL_COMMAND_WINDOWS = 'cmd.exe /d /s /c ""%USERPROFILE%\\.genericagent\\ganet\\atomic-bridge.cmd""'
_CONNECT_LOCK = threading.Lock()


def _forward_log(event, **fields):
    """Emit timing-only forwarding diagnostics without sensitive connection data."""
    try:
        detail = " ".join("%s=%s" % (key, value) for key, value in fields.items())
        print("GA_FORWARD %s %s" % (event, detail), file=sys.stderr, flush=True)
    except Exception:
        pass


# ---------------- HTTP 小工具 ----------------

def _post(url, body=None, token=None, timeout=150):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    for name, value in bus_auth.headers(url).items():
        req.add_header(name, value)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with open_request(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _get(url, token=None, timeout=30):
    req = urllib.request.Request(url, method="GET")
    for name, value in bus_auth.headers(url).items():
        req.add_header(name, value)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with open_request(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _normalize_pair_code(code):
    normalized = "".join(c for c in (code or "") if c.isdigit())
    if len(normalized) != 6:
        raise ValueError("设备码应为 6 位，例如 483 271")
    return normalized


# ---------------- 凭据：自动读登录态 ----------------



# ---------------- 手动登录（可选，dev/调试用）----------------
# App 正常登录由 webui/auth.js 走正式 GAuth；这里保持同一认证域。






# ---------------- 一次性 SSH 密钥 ----------------

def _ensure_keypair():
    """生成/复用一对 ed25519 密钥，返回 OpenSSH 单行公钥字符串。

    当前私钥保存在 Android app 私有目录；接真机前仍需迁移到 Keystore-backed 存储。
    """
    os.makedirs(_SSH_DIR, exist_ok=True)
    if not os.path.exists(_KEY_PATH):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
        priv = ed25519.Ed25519PrivateKey.generate()
        pem = priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with open(_KEY_PATH, "wb") as f:
            f.write(pem)
        os.chmod(_KEY_PATH, 0o600)
        pub = priv.public_key().public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        ) + b" ga-phone\n"
        with open(_KEY_PATH + ".pub", "wb") as f:
            f.write(pub)
    with open(_KEY_PATH + ".pub", encoding="utf-8") as f:
        return f.read().strip()


# ---------------- 电脑公钥配对 ----------------

def _android_model():
    try:
        with open(_ANDROID_DEVICE_PATH, encoding="utf-8") as f:
            native = json.load(f)
        manufacturer = str(native.get("manufacturer") or "").strip()
        model = str(native.get("model") or "").strip()
        if manufacturer and model and manufacturer.lower() not in model.lower():
            return manufacturer + " " + model
        if model:
            return model
    except Exception:
        pass
    return os.environ.get("GA_PHONE_MODEL") or "Android phone"


def local_device():
    try:
        with open(_DEVICE_PATH, encoding="utf-8") as f:
            value = json.load(f)
        if isinstance(value, dict) and str(value.get("deviceId", "")).startswith("dev_"):
            model = _android_model()
            if value.get("model") != model:
                value["model"] = model
                with open(_DEVICE_PATH, "w", encoding="utf-8") as f:
                    json.dump(value, f, ensure_ascii=False)
            return value
    except Exception:
        pass
    value = {"deviceId": "dev_" + uuid.uuid4().hex,
             "displayName": os.environ.get("GA_PHONE_NAME") or "Android phone",
             "platform": "android", "model": _android_model()}
    os.makedirs(os.path.dirname(_DEVICE_PATH), exist_ok=True)
    with open(_DEVICE_PATH, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False)
    return value


def _load_computers():
    try:
        with open(_COMPUTERS_PATH, encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save_computer(computer):
    devices = _load_computers()
    devices[computer["deviceId"]] = computer
    os.makedirs(os.path.dirname(_COMPUTERS_PATH), exist_ok=True)
    tmp = _COMPUTERS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(devices, f, ensure_ascii=False)
    os.replace(tmp, _COMPUTERS_PATH)


_QR_JOBS = {}
_QR_LOCK = threading.Lock()
_QR_TERMINAL = frozenset(("approved", "cancelled", "rejected", "expired", "security_failed"))
_QR_RELAY_TIMEOUT = 8
_QR_RETRY_DELAY = 0.75


def _qr_relay_get(session_id, token):
    """Read transient relay state; timeouts are retried until the QR expires."""
    return _get(service_config.get_service('ganet')['url'] + "/provision/pairings/relay/" + session_id,
                token=token, timeout=_QR_RELAY_TIMEOUT)


def _qr_retryable(exc):
    if isinstance(exc, (TimeoutError, urllib.error.URLError)):
        return True
    return "timed out" in str(exc).lower() or "timeout" in str(exc).lower()


def _qr_relay_get_until(session_id, token, expires_at):
    while int(time.time()) < expires_at:
        try:
            return _qr_relay_get(session_id, token)
        except Exception as exc:
            if not _qr_retryable(exc):
                raise
            time.sleep(_QR_RETRY_DELAY)
    raise RuntimeError("二维码有效期内未能连接设备互联服务")




def _qr_pair_worker(job_id, qr_value, token):
    secret = None
    try:
        qr = pairing_protocol.parse_qr_payload(qr_value)
        secret = qr["secret"]
        if qr["expiresAt"] <= int(time.time()):
            raise RuntimeError("二维码已过期")
        session_id = qr["sessionId"]
        relay = _qr_relay_get_until(session_id, token, qr["expiresAt"])
        pc = pairing_protocol.verify_envelope(relay.get("pcHello"), "pcHello", secret)
        if pc["sessionId"] != session_id or pc["expiresAt"] != qr["expiresAt"] \
                or pc["ownerId"] != _owner_id_from_login(token):
            raise RuntimeError("电脑身份验证失败")
        device = local_device()
        message = {"protocol": pairing_protocol.PROTOCOL, "suite": pairing_protocol.SUITE,
                   "sessionId": session_id, "ownerId": pc["ownerId"], "role": "phone",
                   "pcHelloHash": pairing_protocol.envelope_hash(relay["pcHello"]),
                   "computerDeviceId": pc["computerDeviceId"], "pcNonce": pc["pcNonce"],
                   "phoneDeviceId": device["deviceId"], "displayName": device["displayName"],
                   "platform": device["platform"], "model": device["model"],
                   "publicKey": _ensure_keypair(),
                   "phoneNonce": pairing_protocol.b64u_encode(secrets.token_bytes(16)),
                   "expiresAt": qr["expiresAt"]}
        phone_hello = pairing_protocol.envelope("phoneHello", message, secret)
        _post(service_config.get_service('ganet')['url'] + "/provision/pairings/relay/" + session_id + "/phone",
              {"phoneHello": phone_hello}, token=token, timeout=30)
        with _QR_LOCK:
            _QR_JOBS[job_id].update(state="phone_verified", message="已验证，等待电脑确认")
        while int(time.time()) < qr["expiresAt"]:
            try:
                relay = _qr_relay_get(session_id, token)
            except Exception as exc:
                if _qr_retryable(exc):
                    with _QR_LOCK:
                        _QR_JOBS[job_id].update(
                            state="phone_verified", message="网络波动，正在继续等待电脑确认")
                    time.sleep(_QR_RETRY_DELAY)
                    continue
                raise
            if relay.get("result"):
                result = pairing_protocol.verify_envelope(relay["result"], "result", secret)
                if result["phoneHelloHash"] != pairing_protocol.envelope_hash(phone_hello) \
                        or result["computerDeviceId"] != pc["computerDeviceId"] \
                        or result["phoneDeviceId"] != device["deviceId"] \
                        or result["expiresAt"] != qr["expiresAt"]:
                    raise RuntimeError("电脑最终结果验证失败")
                if result["state"] == "approved":
                    computer = {"deviceId": pc["computerDeviceId"],
                                "displayName": pc["displayName"], "platform": pc["platform"],
                                "model": pc["model"], "hostname": None, "ip": pc["tailnetIp"],
                                "sshUsername": pc["sshUsername"], "sshPort": pc["sshPort"],
                                "sshHostKey": pc["sshHostKey"], "kind": "computer",
                                "pairingState": "paired", "pairedAt": int(time.time())}
                    _save_computer(computer)
                    final = "approved"; message_text = "配对完成"
                elif result["state"] == "cancelled":
                    final = "cancelled"; message_text = "电脑已取消"
                else:
                    final = "rejected"; message_text = "电脑拒绝了本次配对"
                with _QR_LOCK:
                    _QR_JOBS[job_id] = {"state": final, "message": message_text}
                return
            time.sleep(0.75)
        raise RuntimeError("二维码已过期")
    except Exception as exc:
        text = str(exc)
        state = "expired" if "过期" in text else "security_failed"
        with _QR_LOCK:
            _QR_JOBS[job_id] = {"state": state, "message": text[:160]}
    finally:
        secret = None


def start_qr_pairing(qr_value, token=None):
    """Native-only entry: QR secret is passed directly here, never through WebUI JS."""
    if token is None:
        token = read_token()
    job_id = "pair_" + secrets.token_hex(12)
    with _QR_LOCK:
        _QR_JOBS[job_id] = {"state": "phone_verifying", "message": "正在安全验证电脑"}
    threading.Thread(target=_qr_pair_worker, args=(job_id, qr_value, token), daemon=True).start()
    return job_id


def qr_pairing_status(job_id):
    with _QR_LOCK:
        value = dict(_QR_JOBS.get(job_id) or {"state": "security_failed", "message": "配对任务不存在"})
        if value.get("state") in _QR_TERMINAL:
            _QR_JOBS.pop(job_id, None)
        return value


def pair_computer(code, device_name=None, token=None):
    """输入电脑 `/ganet pair` 显示的短码，提交本手机的 Ed25519 公钥。

    设备码只在内存中使用，不写文件/聊天记录；私钥始终留在 app 私有目录。
    """
    if token is None:
        token = read_token()
    public_key = _ensure_keypair()
    device = local_device()
    body = {
        "confirmationCode": _normalize_pair_code(code),
        "publicKey": public_key,
        "deviceId": device["deviceId"],
        "deviceName": (device_name or device["displayName"])[:80],
        "platform": device["platform"],
        "model": device["model"],
    }
    resp = _post(service_config.get_service('ganet')['url'] + "/provision/pairings/claim", body, token=token, timeout=30)
    if not resp.get("ok"):
        raise RuntimeError("配对失败：%s" % resp)
    computer = {
        "deviceId": resp.get("computerDeviceId"),
        "pairingId": resp.get("pairingId"),
        "displayName": resp.get("displayName") or resp.get("meshHostname"),
        "model": resp.get("model") or "Computer",
        "hostname": resp.get("meshHostname"),
        "ip": resp.get("tailnetIp"),
        "sshUsername": resp.get("sshUsername"),
        "sshPort": resp.get("sshPort") or DEFAULT_SSH_PORT,
        "sshHostKey": resp.get("sshHostKey"),
        "kind": "computer",
        "pairingState": "pending",
        "pairedAt": None,
    }
    if not str(computer.get("deviceId") or "").startswith("dev_") or not computer.get("ip"):
        raise RuntimeError("配对服务未返回完整的电脑连接信息")
    _save_computer(computer)
    _DEV_CACHE["at"], _DEV_CACHE["devs"] = 0.0, None
    return {"ok": True, "device": computer, "message": "公钥已提交，等待电脑确认"}


# ---------------- provision：私有网络入网授权 ----------------

def provision(token):
    """凭 JWT 换 preauthkey（入网用）。"""
    resp = _post(service_config.get_service('ganet')['url'] + "/provision/tailscale", token=token)
    if not resp.get("ok"):
        raise RuntimeError("provision failed: %s" % resp)
    return resp


# ---------------- 多设备：发现 + 会话级绑定 ----------------
# 只把 computer 作为 SSH 目标；手机记录用于设备管理，不会成为被连接端。

# /provision/devices 有按 uid 限流（30 次/时）。一次 run() 链路上 _resolve_device、
# current_device 等会多次要设备表，不缓存的话几轮对话就把额度打穿（实测 429）。
# 设备表变化频度极低（enroll/掉线），进程内 TTL 缓存 60s 足够新鲜且一次会话只耗 1 次额度。
_DEV_CACHE = {"at": 0.0, "devs": None}
_DEV_TTL = 60.0


def pairing_status(pairing_id, token=None):
    """Return the server pairing state and synchronize the local computer record."""
    if token is None:
        token = read_token()
    devices = _load_computers()
    computer = next((d for d in devices.values() if d.get("pairingId") == pairing_id), None)
    if not computer:
        raise RuntimeError("未找到本机配对记录")
    state = _get(service_config.get_service('ganet')['url'] + "/provision/pairings/" + pairing_id, token=token)
    status = state.get("state") or "pending"
    if status == "consumed":
        computer["pairingState"] = "paired"
        computer["pairedAt"] = int(time.time())
        computer.pop("pairingId", None)
        _save_computer(computer)
        _DEV_CACHE["at"], _DEV_CACHE["devs"] = 0.0, None
    elif status in ("cancelled", "expired"):
        remove_computer(computer["deviceId"])
        _DEV_CACHE["at"], _DEV_CACHE["devs"] = 0.0, None
    return {"ok": True, "state": status, "device": computer}


def _refresh_pairing(computer, token):
    if computer.get("pairingState") != "pending" or not computer.get("pairingId"):
        return computer
    try:
        pairing_status(computer["pairingId"], token)
    except Exception:
        pass
    return _load_computers().get(computer["deviceId"], computer)


def computer_status(device_id, verify=False):
    """Return one paired computer's real connection status.

    ``verify=True`` performs the same pinned-host-key and phone-key SSH handshake
    used by actual PC tools. A local forward alone is not proof that the computer
    is usable, so only a successful handshake is reported as ``reachable``.
    """
    computer = _load_computers().get(device_id)
    if not computer or computer.get("pairingState") != "paired":
        raise RuntimeError("未找到已配对电脑")
    expected = "%s:%s" % (computer.get("ip"), computer.get("sshPort") or DEFAULT_SSH_PORT)
    if verify:
        client = None
        try:
            client = connect(device=device_id)
            return {"ok": True, "state": "reachable", "connected": True}
        except Exception as exc:
            message = str(exc)
            state = ("disconnected" if
                     ("已在电脑端登出" in message or "当前不在网" in message)
                     else "unreachable")
            return {"ok": True, "state": state, "connected": False,
                    "error": message[:240]}
        finally:
            if client is not None:
                client.close()
    try:
        bridge = status()
    except Exception:
        return {"ok": True, "state": "disconnected", "connected": False}
    if not _forward_matches(bridge, expected):
        return {"ok": True, "state": "disconnected", "connected": False}
    return {"ok": True, "state": "forward_ready", "connected": False}


def remove_computer(device_id):
    devices = _load_computers()
    if device_id not in devices:
        return False
    devices.pop(device_id, None)
    tmp = _COMPUTERS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(devices, f, ensure_ascii=False)
    os.replace(tmp, _COMPUTERS_PATH)
    store = _bind_store()
    changed = False
    for cid, bound in list(store.items()):
        if bound == device_id:
            store.pop(cid, None)
            changed = True
    if changed:
        _bind_save(store)
    return True


def list_devices(token=None, fresh=False):
    """List computers paired with this phone; the server is not a device directory."""
    computers = _load_computers()
    if computers and token is None:
        token = read_token()
    devs = [_refresh_pairing(d, token) for d in computers.values()]
    devs = [d for d in devs if d.get("pairingState") == "paired"]
    _DEV_CACHE["at"] = time.time()
    _DEV_CACHE["devs"] = devs
    return devs


def _active_convo():
    """当前会话 id（android_entry 落在 kv/ga.active_convo）；无则 None（走单机兜底）。"""
    try:
        with open(_ACTIVE_CONVO_PATH, encoding="utf-8") as f:
            return f.read().strip() or None
    except Exception:
        return None


def _bind_store():
    try:
        with open(_BIND_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _bind_save(store):
    os.makedirs(os.path.dirname(_BIND_PATH), exist_ok=True)
    with open(_BIND_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False)


def bind_device(identifier, token=None, convo_id=None):
    """Bind a computer's immutable deviceId to a conversation."""
    if token is None:
        token = read_token()
    devs = list_devices(token)
    match = next((d for d in devs if identifier in
                  (d.get("deviceId"), d.get("hostname"), d.get("displayName"))), None)
    if not match:
        raise RuntimeError("设备 %r 不在账号名下：%s" %
                           (identifier, [d.get("displayName") or d.get("hostname") for d in devs]))
    device_id = match.get("deviceId")
    if not isinstance(device_id, str) or not device_id.startswith("dev_"):
        raise RuntimeError("该电脑使用旧登记格式；请在电脑上重新登录 GA 以完成迁移")
    cid = convo_id or _active_convo() or "_default"
    store = _bind_store()
    store[cid] = device_id
    _bind_save(store)
    return match


# 兼容旧名（早期文档用过 use_device）
use_device = bind_device


def unbind_device(convo_id=None):
    """Clear one conversation's device selection."""
    cid = convo_id or _active_convo() or "_default"
    store = _bind_store()
    if store.pop(cid, None) is not None:
        _bind_save(store)
    return True


def current_device(token=None, convo_id=None):
    """Return one conversation's explicitly selected computer, if any."""
    devs = list_devices(token)
    cid = convo_id or _active_convo() or "_default"
    stored = _bind_store().get(cid)
    if stored:
        d = next((x for x in devs if x.get("deviceId") == stored), None)
        if d:
            return d
        # One-time compatibility for old hostname bindings; immediately rewrite them
        # to the immutable identity so hostname changes cannot retarget a session.
        d = next((x for x in devs if stored in (x.get("hostname"), x.get("displayName"))), None)
        if d and str(d.get("deviceId", "")).startswith("dev_"):
            store = _bind_store()
            store[cid] = d["deviceId"]
            _bind_save(store)
            return d
    return None


def _resolve_device(token, convo_id=None, identifier=None):
    """Locate an explicitly named computer or a conversation's selected one."""
    devs = list_devices(token)
    if not devs:
        raise RuntimeError("当前账号没有已配对电脑。请在电脑打开 GAnet 用户中心 → 我的设备 → 添加设备，再用手机扫描二维码配对。")
    if identifier:
        d = next((item for item in devs if identifier in
                  (item.get("deviceId"), item.get("hostname"), item.get("displayName"))), None)
        if d is None:
            raise RuntimeError("未找到已配对电脑 %r" % identifier)
    else:
        d = current_device(token, convo_id=convo_id)
    if d is None:
        raise RuntimeError("当前会话未选择电脑。请点击聊天框的设备按钮选择一台已配对电脑；如需配对，请在电脑打开 GAnet 用户中心 → 我的设备 → 添加设备。")
    if d.get("expired"):    # 电脑端 GA 登出会退网吊销 node key（#21）——给用户明确的恢复动作
        raise RuntimeError("电脑 %r 已在电脑端登出。让用户在那台电脑的 GAnet 用户中心重新登录 GA 即可恢复直连"
                           % (d.get("displayName") or d.get("hostname")))
    if not d.get("ip"):
        raise RuntimeError("设备 %r 当前不在网（未入网/已注销；在电脑的 GAnet 用户中心登录 GA 可自动入网）"
                           % (d.get("displayName") or d.get("hostname")))
    return d


# ---------------- 入网 ----------------

def join(token=None, pc=None, remote_port=DEFAULT_SSH_PORT, local_port=SSH_LOCAL_PORT,
         hostname=None, enroll=False):
    """Restore the persistent phone node, provisioning only its first enrollment."""
    if token is None:
        token = read_token()
    if pc is None:
        pc = _resolve_device(token)["ip"]
    body = {
        "controlUrl": service_config.get_service("ganet")["url"],
        "hostname": hostname or "ga-phone",
        "forwardPort": local_port,
        "remoteAddr": "%s:%s" % (pc, remote_port),
    }
    if enroll:
        prov = provision(token)
        body.update({"controlUrl": prov["controlUrl"],
                     "authKey": prov["preauthkey"],
                     "hostname": hostname or ("ga-phone-%s" % prov.get("uid", "x"))})
    return _post(BUS + "/net/join", body)


def set_forward(pc, remote_port=DEFAULT_SSH_PORT, local_port=SSH_LOCAL_PORT):
    return _post(BUS + "/net/forward", {
        "forwardPort": local_port,
        "remoteAddr": "%s:%s" % (pc, remote_port),
    })


def status():
    with open_request(urllib.request.Request(BUS + "/net/status", headers=bus_auth.headers(BUS)), timeout=10) as r:
        return json.loads(r.read().decode())


def down():
    return _post(BUS + "/net/down")


def dial_test(remote_addr, timeout=20):
    """Verify that the live tsnet node can reach one tailnet TCP endpoint."""
    value = _get(BUS + "/net/dialtest?addr=" + urllib.parse.quote(remote_addr, safe=""),
                 timeout=timeout)
    return str(value.get("err") or "")


def _forward_matches(state, remote_addr):
    try:
        return bool(state.get("running") and state.get("remoteAddr") == remote_addr
                    and int(state.get("forwardPort") or 0) == SSH_LOCAL_PORT)
    except (AttributeError, TypeError, ValueError):
        return False


def _ensure_forward(token, target, remote_port):
    """Reuse a healthy forward, or replace stale/mismatched tsnet state atomically."""
    expected_remote = "%s:%s" % (target["ip"], remote_port)
    started = time.monotonic()
    with _CONNECT_LOCK:
        lock_ms = int((time.monotonic() - started) * 1000)
        try:
            state = status()
        except Exception as exc:
            _forward_log("forward_status_failed", ms=int((time.monotonic() - started) * 1000),
                         error=type(exc).__name__)
            state = {"running": False}
        if _forward_matches(state, expected_remote):
            _forward_log("forward_reused", lockMs=lock_ms,
                         totalMs=int((time.monotonic() - started) * 1000))
            return state
        if state.get("running"):
            forward_started = time.monotonic()
            state = set_forward(target["ip"], remote_port=remote_port)
            _forward_log("forward_updated", lockMs=lock_ms,
                         forwardMs=int((time.monotonic() - forward_started) * 1000),
                         totalMs=int((time.monotonic() - started) * 1000))
        else:
            join_started = time.monotonic()
            try:
                state = join(token, pc=target["ip"], remote_port=remote_port)
                restored = True
            except urllib.error.HTTPError as exc:
                restored = False
                if exc.code != 500:
                    raise
                detail = exc.read(4096).decode("utf-8", "replace")
                if "ganet_state_missing" not in detail:
                    raise
                state = join(token, pc=target["ip"], remote_port=remote_port, enroll=True)
            _forward_log("forward_joined", lockMs=lock_ms, restored=restored,
                         joinMs=int((time.monotonic() - join_started) * 1000),
                         totalMs=int((time.monotonic() - started) * 1000))
        return state


# ---------------- 高层：透明 SSH ----------------

def _pinned_host_key_policy(expected):
    """Verify the enrolled PC host key for the local mesh forward; never TOFU."""
    import paramiko
    if not isinstance(expected, str) or not expected.startswith("ssh-ed25519 "):
        raise RuntimeError("电脑未登记可验证的 SSH host key；请在该电脑重新登录 GA")
    expected_key = expected.split()[1]

    class _Pin(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            if key.get_name() != "ssh-ed25519" or key.get_base64() != expected_key:
                raise paramiko.SSHException("电脑 SSH host key 不匹配；已拒绝连接")

    return _Pin()


def _computer_platform(target):
    platform = str(target.get("platform") or "").lower()
    if platform in ("windows", "linux", "macos"):
        return platform
    model = str(target.get("model") or "").lower()
    if "windows" in model:
        return "windows"
    if "mac" in model:
        return "macos"
    if "linux" in model:
        return "linux"
    return ""


def _ssh_error_detail(exc):
    detail = str(exc).strip()
    return detail or type(exc).__name__


def _is_terminal_ssh_error(exc, paramiko):
    terminal_types = tuple(
        cls for cls in (
            getattr(paramiko, "AuthenticationException", None),
            getattr(paramiko, "BadHostKeyException", None),
            getattr(paramiko, "PasswordRequiredException", None),
        ) if isinstance(cls, type)
    )
    return isinstance(exc, terminal_types) or "host key 不匹配" in str(exc)


def _diagnose_transport_failure(remote_addr, ssh_error):
    """Return the failing GAnet layer behind a localhost SSH symptom."""
    try:
        mesh_error = dial_test(remote_addr)
    except Exception as exc:
        return "GAnet 本地转发连接失败，且私网诊断不可用：%s（原始 SSH 错误：%s）" % (
            _ssh_error_detail(exc), _ssh_error_detail(ssh_error))
    if mesh_error:
        return "GAnet 私网无法连接电脑：%s（SSH 仅报告：%s）" % (
            mesh_error, _ssh_error_detail(ssh_error))
    return "电脑私网端口可达，但 SSH 握手失败：%s" % _ssh_error_detail(ssh_error)


def connect(token=None, device=None, convo_id=None):
    """Return an SSH client for a selected paired computer.

    ``device`` may be a device ID, display name, or mesh hostname; bindings persist
    only the immutable device ID.
    """
    import paramiko
    if token is None:
        token = read_token()

    # 1) 定位目标设备（device 显式指定时仅临时选用，不改变会话绑定）
    target = _resolve_device(token, convo_id=convo_id, identifier=device)

    # 2) Reuse only a reachable forward; stale ephemeral nodes are re-enrolled.
    try:
        remote_port = int(target.get("sshPort") or DEFAULT_SSH_PORT)
    except (TypeError, ValueError):
        raise RuntimeError("电脑上报的 SSH 端口无效；请在该电脑重新配置 GAnet")
    if not 1024 <= remote_port <= 65535:
        raise RuntimeError("电脑上报的 SSH 端口无效；请在该电脑重新配置 GAnet")
    _ensure_forward(token, target, remote_port)

    # 3) Use the persistent phone key installed by PC-local pairing, and pin the
    # computer SSH host key supplied by its enrollment record.
    key = paramiko.Ed25519Key.from_private_key_file(_KEY_PATH)
    username = target.get("sshUsername")
    if not username:
        raise RuntimeError("电脑尚未上报 SSH 用户名；请在该电脑重新配置 GAnet")
    def open_client():
        client = paramiko.SSHClient()
        try:
            client.set_missing_host_key_policy(_pinned_host_key_policy(target.get("sshHostKey")))
            client.connect("127.0.0.1", port=SSH_LOCAL_PORT, username=username,
                           pkey=key, look_for_keys=False, allow_agent=False, timeout=30,
                           banner_timeout=15, auth_timeout=20,
                           disabled_algorithms={
                               'ciphers': ['aes128-cbc', 'aes192-cbc', 'aes256-cbc', '3des-cbc',
                                           'chacha20-poly1305@openssh.com'],
                               'macs': ['hmac-sha1', 'hmac-sha1-96', 'hmac-md5', 'hmac-md5-96'],
                               'keys': ['ssh-rsa'], 'pubkeys': ['ssh-rsa'],
                           })
            return client
        except Exception:
            client.close()
            raise

    remote_addr = "%s:%s" % (target["ip"], remote_port)
    try:
        return open_client()
    except (paramiko.SSHException, OSError) as first_error:
        if _is_terminal_ssh_error(first_error, paramiko):
            raise
        diagnosis = _diagnose_transport_failure(remote_addr, first_error)
        if not diagnosis.startswith("电脑私网端口可达"):
            raise RuntimeError(diagnosis) from first_error
        # Refresh only the forwarding target. A failed SSH handshake must never
        # tear down or re-enroll the persistent phone node.
        with _CONNECT_LOCK:
            set_forward(target["ip"], remote_port=remote_port)
        try:
            return open_client()
        except (paramiko.SSHException, OSError) as retry_error:
            if _is_terminal_ssh_error(retry_error, paramiko):
                raise
            raise RuntimeError(
                _diagnose_transport_failure(remote_addr, retry_error)
            ) from retry_error


def _bridge_check(client, target, timeout=30):
    """Return the desktop bridge environment used to resolve relative SFTP paths."""
    platform = _computer_platform(target)
    if not platform:
        raise RuntimeError("电脑平台信息缺失；请重新配对该电脑")
    command = (PC_TOOL_COMMAND_WINDOWS + " --check"
               if platform == "windows" else PC_TOOL_COMMAND + " --check")
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read(PC_TOOL_MAX_RESPONSE + 1)
    if len(output) > PC_TOOL_MAX_RESPONSE:
        raise RuntimeError("电脑环境信息内容过大")
    if stdout.channel.recv_exit_status() != 0:
        detail = _decode_ssh_output(stderr.read(8193), platform=platform).strip()
        raise RuntimeError("电脑环境信息读取失败" + (("：" + detail[:300]) if detail else ""))
    try:
        value = json.loads(output.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("电脑环境信息无效") from exc
    if not isinstance(value, dict) or value.get("ok") is not True \
            or value.get("protocol") != PC_TOOL_PROTOCOL \
            or not isinstance(value.get("toolCwd"), str) or not value["toolCwd"]:
        raise RuntimeError("电脑环境信息无效")
    return value


def _remote_sftp_path(path, tool_cwd, platform):
    """Resolve a user path like the desktop atomic tools, then use SFTP separators."""
    value = str(path or "").strip()
    if not value:
        raise ValueError("电脑文件路径不能为空")
    windows_absolute = bool(re.match(r"^[A-Za-z]:[\\/]", value))
    if not windows_absolute and not value.startswith("/"):
        value = str(tool_cwd).rstrip("\\/") + "/" + value
    value = value.replace("\\", "/")
    if platform == "windows" and re.match(r"^[A-Za-z]:/", value):
        value = "/" + value
    return value


def _local_transfer_path(path, *, download=False):
    value = str(path or "").strip()
    if value:
        return os.path.abspath(value if os.path.isabs(value) else os.path.join(GA_DIR, "temp", value))
    if download:
        raise ValueError("手机保存路径不能为空")
    raise ValueError("手机文件路径不能为空")


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _sftp_exists(sftp, path):
    try:
        sftp.stat(path)
        return True
    except (IOError, OSError):
        return False


def _sftp_commit(sftp, temporary, destination, overwrite):
    if _sftp_exists(sftp, destination):
        if not overwrite:
            raise FileExistsError("电脑目标文件已存在")
        try:
            sftp.posix_rename(temporary, destination)
            return
        except (AttributeError, IOError, OSError):
            sftp.remove(destination)
    sftp.rename(temporary, destination)


def _put_file(local_path, remote_path=None, overwrite=False, token=None, device=None,
              convo_id=None):
    """Stream one phone file to the paired computer through pinned-key SFTP."""
    if token is None:
        token = read_token()
    source = _local_transfer_path(local_path)
    if not os.path.isfile(source):
        raise FileNotFoundError("手机文件不存在或不是普通文件")
    target = _resolve_device(token, convo_id=convo_id, identifier=device)
    client = connect(token=token, device=device, convo_id=convo_id)
    sftp = None
    temporary = None
    try:
        environment = _bridge_check(client, target)
        destination = _remote_sftp_path(remote_path or os.path.basename(source),
                                        environment["toolCwd"], _computer_platform(target))
        parent = destination.rsplit("/", 1)[0]
        sftp = client.open_sftp()
        if parent and not _sftp_exists(sftp, parent):
            raise FileNotFoundError("电脑目标目录不存在")
        temporary = destination + ".ga-transfer-" + secrets.token_hex(8) + ".part"
        sftp.put(source, temporary, confirm=True)
        _sftp_commit(sftp, temporary, destination, bool(overwrite))
        temporary = None
        size = os.path.getsize(source)
        return {"direction": "to_computer", "name": os.path.basename(destination),
                "size": size, "sha256": _sha256_file(source),
                "phonePath": source, "computerPath": destination}
    finally:
        if sftp is not None:
            if temporary is not None:
                try:
                    sftp.remove(temporary)
                except Exception:
                    pass
            sftp.close()
        client.close()


def _get_file(remote_path, local_path=None, overwrite=False, token=None, device=None,
              convo_id=None):
    """Stream one computer file into the phone artifact directory."""
    if token is None:
        token = read_token()
    target = _resolve_device(token, convo_id=convo_id, identifier=device)
    client = connect(token=token, device=device, convo_id=convo_id)
    sftp = None
    temporary = None
    try:
        environment = _bridge_check(client, target)
        source = _remote_sftp_path(remote_path, environment["toolCwd"],
                                   _computer_platform(target))
        name = os.path.basename(source.rstrip("/")) or "download"
        destination = _local_transfer_path(local_path or os.path.join("computer_downloads", name),
                                           download=True)
        if os.path.exists(destination) and not overwrite:
            raise FileExistsError("手机目标文件已存在")
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        sftp = client.open_sftp()
        source_info = sftp.stat(source)
        temporary = destination + ".ga-transfer-" + secrets.token_hex(8) + ".part"
        sftp.get(source, temporary)
        if os.path.getsize(temporary) != int(source_info.st_size):
            raise RuntimeError("文件传输不完整")
        os.replace(temporary, destination)
        temporary = None
        relative = os.path.relpath(destination, os.path.join(GA_DIR, "temp")).replace("\\", "/")
        return {"direction": "from_computer", "name": os.path.basename(destination),
                "size": os.path.getsize(destination), "sha256": _sha256_file(destination),
                "computerPath": source, "phonePath": destination,
                "artifactPath": relative}
    finally:
        if temporary is not None:
            try:
                os.remove(temporary)
            except FileNotFoundError:
                pass
        if sftp is not None:
            sftp.close()
        client.close()


def _pc_catalog_response(token=None, timeout=30, device=None):
    """Read the paired computer's complete capability response once."""
    if token is None:
        token = read_token()
    if device:
        bind_device(device, token)
    target = _resolve_device(token)
    client = connect(token)
    try:
        platform = _computer_platform(target)
        if not platform:
            raise RuntimeError("电脑平台信息缺失；请重新配对该电脑")
        command = (PC_TOOL_COMMAND_WINDOWS + " --catalog"
                   if platform == "windows" else PC_TOOL_COMMAND + " --catalog")
        _, stdout, _ = client.exec_command(command, timeout=timeout)
        output = stdout.read(PC_TOOL_MAX_RESPONSE + 1)
        if len(output) > PC_TOOL_MAX_RESPONSE:
            raise RuntimeError("电脑工具描述内容过大")
        if stdout.channel.recv_exit_status() != 0:
            raise RuntimeError("电脑工具描述读取失败")
        value = json.loads(output.decode("utf-8"))
        if not isinstance(value, dict) or value.get("ok") is not True \
                or value.get("protocol") != PC_TOOL_PROTOCOL or not isinstance(value.get("tools"), list):
            raise RuntimeError("电脑工具描述无效")
        return value
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("电脑工具描述无效") from exc
    finally:
        client.close()


def device_tool_catalog(token=None, timeout=30, device=None):
    """Return the paired computer's agent-facing capability contract.

    Dispatch channels are intentionally absent: callers name a capability and
    ``call_device_tool`` selects the correct local implementation.
    """
    value = _pc_catalog_response(token=token, timeout=timeout, device=device)
    capabilities = value.get("capabilities")
    if capabilities is None:
        return list(value["tools"])
    allowed = {"name", "description", "parameters", "operations"}
    if not isinstance(capabilities, list) or not all(
            isinstance(item, dict) and isinstance(item.get("name"), str)
            and set(item).issubset(allowed) for item in capabilities):
        raise RuntimeError("电脑能力目录无效")
    return capabilities


def _save_pc_screenshot(header, image):
    if not isinstance(header, dict) or header.get("contentType") != "image/jpeg":
        raise RuntimeError("电脑截图格式无效")
    length = header.get("contentLength")
    digest = header.get("sha256")
    if not isinstance(length, int) or not 0 < length <= PC_SCREENSHOT_MAX_BYTES \
            or length != len(image) or not isinstance(digest, str) \
            or len(digest) != 64 or hashlib.sha256(image).hexdigest() != digest.lower() \
            or not image.startswith(b"\xff\xd8\xff"):
        raise RuntimeError("电脑截图内容校验失败")
    for field in ("width", "height", "sessionId"):
        if not isinstance(header.get(field), int) or header[field] <= 0:
            raise RuntimeError("电脑截图元数据无效")
    root = os.path.join(GA_DIR, "temp", "computer_screenshots")
    os.makedirs(root, exist_ok=True)
    name = "pc_screenshot_" + secrets.token_hex(12) + ".jpg"
    relative_path = "computer_screenshots/" + name
    final_path = os.path.join(root, name)
    temp_path = final_path + ".tmp"
    try:
        with open(temp_path, "wb") as f:
            f.write(image)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, final_path)
    finally:
        try:
            os.remove(temp_path)
        except FileNotFoundError:
            pass
    markdown = "![电脑桌面](../temp/%s)" % relative_path
    return {"ok": True, "path": relative_path, "width": header["width"], "height": header["height"],
            "markdown": markdown,
            "instruction": "请在最终回复中原样引用 markdown 字段，以展示当前电脑桌面截图。"}


def _recv_exact(channel, size):
    chunks = []
    remaining = size
    while remaining:
        chunk = channel.recv(min(65536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_header(channel):
    chunks = []
    total = 0
    while total <= 16 * 1024:
        chunk = channel.recv(1)
        if not chunk:
            break
        if chunk == b"\n":
            return b"".join(chunks)
        chunks.append(chunk)
        total += 1
    raise RuntimeError("电脑截图响应头无效")


def _call_pc_screenshot(arguments, token, target, timeout):
    if arguments:
        raise ValueError("电脑截图工具暂不接受参数")
    request_id = "req_" + secrets.token_hex(16)
    raw = json.dumps({"protocol": PC_TOOL_PROTOCOL, "requestId": request_id,
                      "tool": "computer_screenshot", "arguments": {}},
                     separators=(",", ":")).encode("utf-8")
    client = connect(token)
    try:
        platform = _computer_platform(target)
        if platform not in ("windows", "macos"):
            raise RuntimeError("电脑截图目前仅支持 Windows 与 macOS")
        command = (PC_TOOL_COMMAND_WINDOWS if platform == "windows" else PC_TOOL_COMMAND) + " --screenshot"
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        stdin.write(raw)
        stdin.channel.shutdown_write()
        channel = stdout.channel
        header_raw = _recv_header(channel)
        if not header_raw:
            raise RuntimeError("电脑截图响应头无效")
        try:
            header = json.loads(header_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("电脑截图响应头无效") from exc
        if not isinstance(header, dict) or header.get("protocol") != PC_TOOL_PROTOCOL \
                or header.get("requestId") != request_id:
            raise RuntimeError("电脑截图返回上下文不匹配")
        if header.get("ok") is not True:
            raise RuntimeError(str(header.get("error") or "电脑截图失败")[:500])
        length = header.get("contentLength")
        if not isinstance(length, int) or not 0 < length <= PC_SCREENSHOT_MAX_BYTES:
            raise RuntimeError("电脑截图大小无效")
        image = _recv_exact(channel, length)
        if len(image) != length:
            raise RuntimeError("电脑截图传输不完整")
        if channel.recv_ready() and channel.recv(1):
            raise RuntimeError("电脑截图响应包含多余内容")
        if channel.recv_exit_status() != 0:
            detail = _decode_ssh_output(stderr.read(8193), platform=platform).strip()
            raise RuntimeError("电脑截图入口执行失败" + (("：" + detail[:300]) if detail else ""))
        return _save_pc_screenshot(header, image)
    finally:
        client.close()


def call_device_tool(name, arguments, token=None, timeout=60, device=None, convo_id=None):
    """Call one advertised paired-computer capability through its selected transport."""
    if not isinstance(name, str) or not isinstance(arguments, dict):
        raise ValueError("电脑能力名称和参数必须有效")
    if name in ("code_run", "file_read", "file_patch", "file_write",
                "web_scan", "web_execute_js", "computer_screenshot"):
        if convo_id is not None:
            raise ValueError("bridge 电脑工具不接受 conversationId")
        return _call_pc_tool(name, arguments, token=token, timeout=timeout, device=device)
    if name == "file_transfer":
        action = arguments.get("action")
        allowed = {
            "upload": {"action", "local_path", "remote_path", "overwrite"},
            "download": {"action", "remote_path", "local_path", "overwrite"},
        }
        if action not in allowed or set(arguments) - allowed[action]:
            raise ValueError("文件传输参数无效")
        if action == "upload":
            if not isinstance(arguments.get("local_path"), str):
                raise ValueError("上传需要 local_path")
            return _put_file(arguments["local_path"], arguments.get("remote_path"),
                             bool(arguments.get("overwrite")), token, device, convo_id)
        if not isinstance(arguments.get("remote_path"), str):
            raise ValueError("下载需要 remote_path")
        return _get_file(arguments["remote_path"], arguments.get("local_path"),
                         bool(arguments.get("overwrite")), token, device, convo_id)
    raise ValueError("不支持的电脑能力")


def _call_pc_tool(tool, arguments, token=None, timeout=60, device=None):
    """Call one computer GA atomic tool through the paired SSH connection."""
    if tool not in ("code_run", "file_read", "file_patch", "file_write",
                    "web_scan", "web_execute_js", "computer_screenshot"):
        raise ValueError("不支持的电脑工具")
    if not isinstance(arguments, dict):
        raise ValueError("电脑工具参数必须是对象")
    if token is None:
        token = read_token()
    if device:
        bind_device(device, token)
    target = _resolve_device(token)
    if tool == "computer_screenshot":
        return _call_pc_screenshot(arguments, token, target, timeout)
    request_id = "req_" + secrets.token_hex(16)
    request = {"protocol": PC_TOOL_PROTOCOL, "requestId": request_id,
               "tool": tool, "arguments": arguments}
    raw = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > 256 * 1024:
        raise ValueError("电脑工具请求内容过大")
    client = connect(token)
    try:
        platform = _computer_platform(target)
        if not platform:
            raise RuntimeError("电脑平台信息缺失；请重新配对该电脑")
        command = PC_TOOL_COMMAND_WINDOWS if platform == "windows" else PC_TOOL_COMMAND
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        stdin.write(raw)
        stdin.channel.shutdown_write()
        output = stdout.read(PC_TOOL_MAX_RESPONSE + 1)
        error = stderr.read(8193)
        if len(output) > PC_TOOL_MAX_RESPONSE:
            raise RuntimeError("电脑工具返回内容过大")
        status = stdout.channel.recv_exit_status()
        if status != 0 and not output:
            detail = _decode_ssh_output(error, platform=platform).strip()
            raise RuntimeError("电脑工具入口执行失败" + (("：" + detail[:300]) if detail else ""))
        try:
            response = json.loads(output.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("电脑工具入口返回无效结果") from exc
        if not isinstance(response, dict) or response.get("protocol") != PC_TOOL_PROTOCOL \
                or response.get("requestId") != request_id:
            raise RuntimeError("电脑工具返回上下文不匹配")
        if response.get("ok") is not True:
            raise RuntimeError(str(response.get("error") or "电脑工具执行失败")[:500])
        return response.get("result")
    finally:
        client.close()


def _decode_ssh_output(data, platform=None):
    """Decode remote process bytes without silently discarding invalid data."""
    if not data:
        return ""
    candidates = ["utf-8-sig"]
    if str(platform or "").lower() == "windows":
        candidates.append("gb18030")
    for encoding in candidates:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    return data.decode("utf-8", "replace")


def read_token():
    return service_config.get_service('ganet')['token']

def _owner_id_from_login(token):
    config = service_config.get_service('ganet')
    if config['token'] != token:
        raise ValueError('Mesh credentials changed; retry pairing')
    return config['owner_id']
