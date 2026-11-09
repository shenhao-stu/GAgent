# -*- coding: utf-8 -*-
"""Client for an explicitly configured, self-hosted APK build service."""
import io
import os
import json
import time
import zipfile
import hashlib

import requests
import service_config

_DIR = os.path.dirname(os.path.abspath(__file__))
_CFG_PATH = os.path.join(_DIR, "apk_factory.json")   # {base_urls:[...], token:"..."} 可选覆盖
_DL_DIR = os.path.join(_DIR, "temp", "apk_factory")

DEFAULT_BASES = []








def _pick_base():
    """按连通性探测选路：首个 /healthz 通的 base。全不通则回第一个（让上层报清晰错误）。"""
    for b in _bases():
        try:
            if requests.get(b + "/healthz", timeout=6).status_code < 500:
                return b
        except requests.RequestException:
            continue
    return _bases()[0]


def zip_project(project_dir):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(project_dir):
            for fn in sorted(files):
                fp = os.path.join(root, fn)
                z.write(fp, os.path.relpath(fp, project_dir))
    return buf.getvalue()


def _content_key(project_dir):
    """由工程内容(路径+字节)算稳定幂等键：同一份工程重复提交 → 命中原 job(不 409/不双扣)，
    改了代码 → 新键 → 新构建。消除「agent 多次调 build_and_fetch 撞 already_active」摩擦。"""
    h = hashlib.sha256()
    for root, _dirs, files in os.walk(project_dir):
        for fn in sorted(files):
            fp = os.path.join(root, fn)
            h.update(os.path.relpath(fp, project_dir).replace(os.sep, "/").encode())
            try:
                h.update(open(fp, "rb").read())
            except OSError:
                pass
    return "c-" + h.hexdigest()[:24]


def _read_meta(project_dir):
    """从工程 app/build.gradle 读 applicationId + versionCode（工程是版本号真相源，GA 不用手工同步）。"""
    import glob
    pkg, vc = None, None
    for gp in glob.glob(os.path.join(project_dir, "**", "build.gradle"), recursive=True) + \
              glob.glob(os.path.join(project_dir, "**", "build.gradle.kts"), recursive=True):
        try:
            t = open(gp, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        import re
        m = re.search(r"applicationId\s*=?\s*['\"]([^'\"]+)['\"]", t)
        v = re.search(r"versionCode\s*=?\s*(\d+)", t)
        if m and not pkg:
            pkg = m.group(1)
        if v and not vc:
            vc = int(v.group(1))
    return pkg, vc


def submit(project_dir, package=None, version_code=None, label="", base=None, token=None, idempotency_key=None):
    """上传工程，返回 {job_id, state, base, idempotency_key}。package/version_code 省略则从工程读。同 key 重发返回原 job。"""
    mp, mv = _read_meta(project_dir)
    package = package or mp
    version_code = version_code if version_code is not None else (mv or 1)
    if not package:
        raise RuntimeError("工程缺 applicationId，无法确定包名")
    token = token or _token()
    if not token:
        raise RuntimeError("缺少身份令牌：请先登录（gauth）或配置 apk_factory.json token")
    base = base or _pick_base()
    zbytes = zip_project(project_dir)
    # 内容稳定键：同一在途构建的弱网重发=幂等命中不双扣；终态后重提由服务端开新 job（一次编译=一次额度）
    key = idempotency_key or _content_key(project_dir)
    data = {"idempotency_key": key, "package": package, "version_code": str(version_code),
            "label": label, "device_id": _cfg().get("device_id", "ga")}
    r = requests.post(base + "/v1/apk/builds", headers={"Authorization": "Bearer " + token},
                      data=data, files={"project": ("project.zip", zbytes, "application/zip")}, timeout=120, allow_redirects=False)
    if r.status_code >= 300:
        raise RuntimeError("提交失败 %d: %s" % (r.status_code, _err(r)))
    j = r.json()
    return {"job_id": j["job_id"], "state": j["state"], "base": base, "idempotency_key": key}


def quota(base=None, token=None):
    """查询当前账号编译额度：{tier, unlimited, used_today, daily_limit, remaining_today}。"""
    token = token or _token()
    base = base or _pick_base()
    r = requests.get(base + "/v1/apk/quota", headers={"Authorization": "Bearer " + token}, timeout=15, allow_redirects=False)
    if r.status_code >= 300:
        raise RuntimeError("额度查询失败 %d: %s" % (r.status_code, _err(r)))
    return r.json()


def status(job_id, base, token=None):
    token = token or _token()
    r = requests.get(base + "/v1/apk/builds/" + job_id,
                     headers={"Authorization": "Bearer " + token}, timeout=30, allow_redirects=False)
    if r.status_code >= 300:
        raise RuntimeError("查询失败 %d: %s" % (r.status_code, _err(r)))
    return r.json()


def poll(job_id, base, token=None, timeout_s=600, on_update=None):
    """轮询至终态。抖动退避 5s→30s。返回终态 status dict。"""
    token = token or _token()
    delay, waited = 5, 0
    while waited < timeout_s:
        s = status(job_id, base, token)
        if on_update:
            on_update(s)
        if s["state"] in ("SUCCEEDED", "FAILED", "CANCELED", "EXPIRED"):
            return s
        time.sleep(delay)
        waited += delay
        delay = min(30, delay + 5)
    raise TimeoutError("构建轮询超时")


def download(job_id, base, download_url, dest=None, token=None, retries=3):
    """下载已签名 APK 到设备（相对 url 拼 base，Range 续传，网络抖动自动重试）。返回本地路径。
    编译成功后额度已消耗——下载失败绝不重新 build：产物 24h 内可用 status(job_id, base) 补发链接免费重取。"""
    os.makedirs(_DL_DIR, exist_ok=True)
    dest = dest or os.path.join(_DL_DIR, job_id + ".apk")
    last = None
    for attempt in range(retries):
        headers = {}
        mode = "wb"
        if os.path.exists(dest):  # 断点续传
            headers["Range"] = "bytes=%d-" % os.path.getsize(dest)
            mode = "ab"
        try:
            r = requests.get(base + download_url, headers=headers, stream=True, timeout=120, allow_redirects=False)
            if r.status_code in (200, 206):
                with open(dest, mode) as f:
                    for chunk in r.iter_content(1 << 16):
                        f.write(chunk)
                return dest
            last = "HTTP %d" % r.status_code
        except requests.RequestException as e:
            last = type(e).__name__
        time.sleep(2 * (attempt + 1))
    raise RuntimeError("下载失败(%s) job=%s —— 产物已编好且额度已计，勿重新 build；"
                       "用 F.status('%s', '%s') 取新下载链接后 F.download 重取" % (last, job_id, job_id, base))


def build_and_fetch(project_dir, package=None, version_code=None, label="", on_update=None):
    """一站式：上传→轮询→下载。package/version_code 省略则自动从工程读。
    返回 {job_id, state, apk_path, sha256, size, quota}（quota=本次编译后剩余额度, 告知用户）。
    失败抛异常带诊断(含关键编译错误行)。"""
    token = _token()
    sub = submit(project_dir, package, version_code, label, token=token)
    q = {}
    try:
        q = quota(sub["base"], token)
        if on_update:
            on_update({"state": "QUOTA", "quota": q})
    except (RuntimeError, requests.RequestException):
        pass                                  # 额度展示尽力而为，不阻断构建
    fin = poll(sub["job_id"], sub["base"], token=token, on_update=on_update)
    if fin["state"] != "SUCCEEDED":
        raise RuntimeError("构建未成功: %s / %s\n%s" % (
            fin["state"], fin.get("reason"), (fin.get("error_tail") or "")[-1200:]))
    apk = download(fin["job_id"], sub["base"], fin["download"], token=token)
    got = _sha256(apk)
    if got != fin.get("sha256"):                # 续传残片污染 → 删净重下一次，仍不符才报（绝不重新 build）
        os.remove(apk)
        apk = download(fin["job_id"], sub["base"], fin["download"], token=token)
        got = _sha256(apk)
    if got != fin.get("sha256"):
        raise RuntimeError("下载 sha256 不匹配（%s != %s）job=%s —— 产物已编好且额度已计，"
                           "勿重新 build；用 F.status 取链接重试下载" % (got, fin.get("sha256"), fin["job_id"]))
    return {"job_id": fin["job_id"], "state": "SUCCEEDED", "apk_path": apk,
            "sha256": fin["sha256"], "size": fin.get("size"), "quota": q}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _err(r):
    try:
        return r.json().get("error", r.text[:200])
    except ValueError:
        return r.text[:200]


def _cfg():
    config = service_config.get_service('apk')
    return {'base_urls': [config['url']], 'token': config['token']}

def _bases():
    return _cfg()['base_urls']

def _token():
    return _cfg()['token']
