# iOS 平台适配层：配置嵌入式 Python 的证书路径并记录依赖诊断，其余委托 android_entry。
# 本地动态代码边界由 ga_android 和 ios_policy 统一处理。
import sys

_INITED = False   # bootstrap_ios 在 init 成功后盖章(模块重导入自愈判据, 同 Android bootstrap)


def _patch_ios_ssl():
    """嵌入式 CPython 的 OpenSSL 在 iOS 读不到系统根证书(BeeWare #119) ⇒ pclink 的 wss 信令/短码 https
    证书验证必失败(requests 自带 certifi 没事, 但 websockets/urlopen 那条没人喂)。指到 certifi 的 PEM。"""
    try:
        import os, certifi
        os.environ.setdefault('SSL_CERT_FILE', certifi.where())
        os.environ.setdefault('SSL_CERT_DIR', os.path.dirname(certifi.where()))
    except Exception:
        pass   # 无 certifi 也不拦 boot; 真机 wss 若失败按此线索排查


def _ios_diag(ga_dir):
    """真机可用性自检 → GA_DIR/ios_diag.txt + stdout(Xcode console 可见)。
    覆盖 PEP 730 后处理(process_dylibs.sh)的 C 扩展与 pclink 依赖链;
    任一 FAIL 都不拦 boot, 只留证据 —— 排障从盲猜变成看一个文件。"""
    import time
    lines = [time.strftime("UTC %Y-%m-%dT%H:%M:%SZ", time.gmtime()), "layout ga_runtime/gacore"]
    for m in ('ssl', 'sqlite3', 'zlib', 'hashlib', 'cryptography', 'websockets', 'p2p_ws_client'):
        try:
            __import__(m); lines.append('ok   ' + m)
        except Exception as e:
            lines.append('FAIL %s: %r' % (m, e))
    txt = '\n'.join(lines)
    print('[ios_diag]\n' + txt, flush=True)   # 嵌入式 stdout 块缓冲, 不 flush 则 devicectl console 看不到
    try:
        import os
        with open(os.path.join(ga_dir, 'ios_diag.txt'), 'w') as f:
            f.write(txt + '\n')
    except Exception:
        pass


def init(ga_dir):
    # ga_dir contains user data and legacy scripts, never importable application code.
    if sys.platform == 'ios':
        _patch_ios_ssl()
        _ios_diag(ga_dir)
    import android_entry
    r = android_entry.init(ga_dir, ios_host=True)
    android_entry._INITED = True   # 顺手盖章(镜像 Android bootstrap): 供 C9 自愈判据识别引擎已 init
    return r


def __getattr__(name):
    import android_entry
    return getattr(android_entry, name)


def model_diagnostics(cid):
    import json
    from kernel_adapter.ios_transport import diagnostics
    import android_entry as entry
    with entry._reg_lock:
        session = next((s for s in entry._REG.values() if entry._pub_cid(s.cid) == cid and not s.retired), None)
    thread = getattr(getattr(session, 'run_thread', None), 'ident', None)
    return json.dumps(diagnostics(thread) if thread is not None else [])


def phone_takeover(cid, action, token=''):
    import json
    import board_bridge
    import android_entry as entry
    from kernel_adapter.ios_host import abort_drivers
    from kernel_adapter.ios_takeover import perform
    with entry._reg_lock:
        session = next((s for s in entry._REG.values() if entry._pub_cid(s.cid) == cid and not s.retired), None)
    def abort():
        entry.abort2(cid)
        abort_drivers()
    return json.dumps(perform(session, action, token, native=board_bridge.takeover, abort=abort), ensure_ascii=False)


def iphone_abort():
    import android_entry as entry
    from kernel_adapter.ios_host import abort_drivers
    with entry._reg_lock:
        paused = [(entry._pub_cid(s.cid), s._phone_pause_token) for s in entry._REG.values()
                  if not s.retired and getattr(s, '_phone_pause_token', None)]
    for cid, token in paused:
        phone_takeover(cid, 'cancel', token)
    return abort_drivers()
