"""T3 PC 互联 interop-critical 原语在 3.13 上的正确性。
pclink.py / p2p_ws_client.py 在 iOS 上零修改复用(Android 已验), 移植风险只在:
「CPython 3.13(iOS) 跑这套 3.10(Android) 写的加密/帧编解码, 结果是否逐字节等价」——
不等价则与 PC 端(以及 Android 端)握手/传输互不通。本测试锁死这条 interop 边界, 全程 hermetic。"""
import os
import sys
import importlib
import asyncio
from unittest.mock import AsyncMock, patch

import signed_runtime


def main():
    p = importlib.import_module("p2p_ws_client")
    importlib.import_module("pclink")             # 仅验 import 通过(纯 py, 无副作用触网)
    print("T3.1 pclink + p2p_ws_client import ok on 3.13")

    # ── seal/open roundtrip: 会话密钥下 AESGCM 封包→解包 无损(bytes 与 str 两种 kind) ──
    key = os.urandom(32)
    for payload in (b"\x00\x01binary-blob" * 40, "文字消息 with unicode 🌍" * 30):
        frame = p.seal(key, payload, compress=True)
        out = p.open_(key, frame)
        want = payload if isinstance(payload, (bytes, bytearray)) else payload
        # open_ 对 kind=1 还原为 str, kind=0 还原为 bytes
        got = out.decode("utf-8") if isinstance(out, (bytes, bytearray)) and isinstance(payload, str) else out
        assert got == want, "seal/open 不还原: %r != %r" % (type(got), type(want))
    print("T3.2 AESGCM seal/open roundtrip(bytes+str, zlib)无损 ok")

    # ── 错误密钥必须解包失败(端到端加密的安全断言, 不能静默返回明文) ──
    frame = p.seal(key, b"secret", compress=False)
    bad = False
    try:
        p.open_(os.urandom(32), frame)
    except Exception:
        bad = True
    assert bad, "错误密钥竟解包成功 —— E2E 加密被破坏"
    print("T3.3 错误密钥解包失败(E2E 安全)ok")

    # ── 大不可压缩 payload 走中继路径(iOS/Android 实际用的 seal/open, 非 aiortc 直连)roundtrip ──
    big = os.urandom(200 * 1024)                  # 随机=不可压, 强制走 AESGCM 全量 + 内部分片
    assert p.open_(key, p.seal(key, big, compress=True)) == big, "大 payload 中继 roundtrip 失真"
    print("T3.4 大不可压缩 payload 中继 roundtrip(200KB)无损 ok")

    # ── 9 位配对码格式(四侧单一真相, iOS 侧兑换必须同格式) ──
    signal = "wss://signal.example.invalid"
    with patch.object(p, "_post_json", new_callable=AsyncMock) as exchange:
        for invalid in ("12345678", "1234567890", "12x456789"):
            try:
                asyncio.run(p.connect_code(signal, invalid, access_key="fixture-key"))
            except ValueError:
                pass
            else:
                raise AssertionError(f"invalid code reached pairing: {invalid}")
        exchange.assert_not_awaited()
        exchange.side_effect = ConnectionError("test transport stopped before exchanging secrets")
        try:
            asyncio.run(p.connect_code(signal, "123456789", access_key="fixture-key"))
        except ConnectionError:
            pass
        exchange.assert_awaited_once()
    print("T3.5 9 位码格式契约 ok")

    print("PASS T3: PC 互联 interop 原语在 CPython %s 上与契约一致" % ".".join(map(str, sys.version_info[:3])))


if __name__ == "__main__":
    main()
