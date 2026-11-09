"""fsbot.bootstrap — 端内一键就位飞书机器人运行环境(替代旧版 4 补丁 / install.py)。

单一职责: 把随包的纯 Python 依赖解压到 GA_DIR/fsbot/site-packages/, 并把 lark_oapi 的
解密器(依赖 pycryptodome, Chaquopy 装不了 C 扩展)替换成纯 Python 的 pyaes 实现。
全部幂等: 已就位则秒回, 供 fsbot_ctl.start() 每次调用而无副作用。

设计不变量:
- 依赖随包(deps/site_packages.tgz), 不联网, 不需要 PC/adb —— 这是相对旧版的"无感"核心。
- 只写 GA_DIR/fsbot/ 子树, 不碰 gacore 其它文件, 变化半径为零。
- 失败半径大(缺依赖→机器人跑不起来)→ 显式抛错; 半径为零的(重复解压)→ 静默跳过。
"""
import os
import sys
import tarfile

FSBOT_DIR = os.path.dirname(os.path.abspath(__file__))
SP_DIR = os.path.join(FSBOT_DIR, "site-packages")
DEPS_TGZ = os.path.join(FSBOT_DIR, "deps", "site_packages.tgz")
_MARKER = os.path.join(SP_DIR, "lark_oapi", "__init__.py")
_DECRYPTOR = os.path.join(SP_DIR, "lark_oapi", "core", "utils", "decryptor.py")

# pyaes 版 AES-CBC 解密: lark_oapi 事件回调/长连接解密用, 替换 pycryptodome(无 C 扩展)。
_PATCHED_DECRYPTOR = '''# Patched for GA (Chaquopy) — pycryptodome → pyaes (GA fsbot bootstrap)
import pyaes


def _aes_cbc_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    aes = pyaes.AES(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(ciphertext), 16):
        block = ciphertext[i:i + 16]
        dec = bytearray(aes.decrypt(block))
        for j in range(len(dec)):
            dec[j] ^= prev[j]
        out.extend(dec)
        prev = block
    pad = out[-1]
    if 0 < pad <= 16:
        return bytes(out[:-pad])
    return bytes(out)


def decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    return _aes_cbc_decrypt(ciphertext, key, iv)
'''
_PATCH_TAG = "GA fsbot bootstrap"


def _extract_deps():
    """解压依赖到 site-packages/(幂等: lark_oapi 已在则跳过)。tgz 顶层即 site-packages/。"""
    if os.path.isfile(_MARKER):
        return
    if not os.path.isfile(DEPS_TGZ):
        raise RuntimeError("缺少依赖包: " + DEPS_TGZ)
    with tarfile.open(DEPS_TGZ, "r:gz") as tar:
        tar.extractall(FSBOT_DIR)   # tgz 内含 site-packages/ 顶层目录 → 落到 FSBOT_DIR/site-packages/
    if not os.path.isfile(_MARKER):
        raise RuntimeError("依赖解压后仍缺 lark_oapi: " + _MARKER)


def _patch_decryptor():
    """把 lark_oapi 解密器换成 pyaes 版(幂等: 已含补丁标记则跳过)。"""
    if not os.path.isfile(_DECRYPTOR):
        raise RuntimeError("缺少待补丁文件: " + _DECRYPTOR)
    try:
        cur = open(_DECRYPTOR, encoding="utf-8").read()
    except Exception:
        cur = ""
    if _PATCH_TAG in cur:
        return
    open(_DECRYPTOR, "w", encoding="utf-8").write(_PATCHED_DECRYPTOR)


def ensure(add_to_path=True):
    """就位 + 可选注入 sys.path。返回 site-packages 路径。供 fsbot_ctl.start 首步调用。"""
    os.makedirs(SP_DIR, exist_ok=True)
    _extract_deps()
    _patch_decryptor()
    if add_to_path and SP_DIR not in sys.path:
        sys.path.insert(0, SP_DIR)
    return SP_DIR


def status():
    """轻量就位状态(不解压)。供 UI 展示 '依赖是否已安装'。"""
    return {
        "deps_ready": os.path.isfile(_MARKER),
        "patched": os.path.isfile(_DECRYPTOR) and _PATCH_TAG in _read(_DECRYPTOR),
        "bundle_present": os.path.isfile(DEPS_TGZ),
    }


def _read(p):
    try:
        return open(p, encoding="utf-8").read()
    except Exception:
        return ""
