# Dependency review / 依赖安全边界

This is an open-source preview. Source publication does not resolve the native
findings below. The supported Python/native-wheel migration remains a **stable
APK release gate**; CI artifacts are development builds, not a security certification.
本版为开源预览；源码公开不代表依赖问题已修复。受支持的 Python/原生依赖迁移仍是
**稳定 APK 发布门槛**。以下发现与限定条件继续保留，构建和密钥扫描不能替代修复。

| Dependency | Change / observation | Remaining boundary |
| --- | --- | --- |
| CPython / OpenSSL | Chaquopy17.1.0 supplies CPython3.10.22 and OpenSSL3.5.9; CI verifies the packaged native library | Replaces the initial candidate's actual OpenSSL3.0.5. Python3.10 reached upstream end of life on2026-10-01; a supported Python/native-wheel migration remains a stable APK release gate |
| Go mesh | Go1.27.3; x/net0.60, x/crypto0.57, x/text0.42, compress1.18.7 | Module scan only flags deprecated OpenPGP (GO-2026-5932); the inspected dependency graph does not import it |
| DOMPurify | 3.4.17 | WebView still executes model-rendering code, so keep sanitization and bridge separation |
| certifi | 2026.10.19 in runtime and bundled Lark dependencies; also replaces Chaquopy's default CA asset before its integrity hashes are calculated | Android-native TLS uses the device/provider trust store separately |
| aiohttp | 3.14.5; patched multidict/yarl/frozenlist/propcache portable wheels | Pure Python paths trade some performance for Android compatibility |
| cryptography | 3.4.8→42.0.8, the available Python3.10 Android wheel | CVE-2026-26007 (SECT), 34073/69248/69249 (X.509 verification) remain version findings. Project adapters use X25519/Ed25519/AES-GCM, not SECT or this X.509 verifier; this is scoped reachability analysis, not a patched library |
| Paramiko | Android wheel constraints retain2.12.0 | CVE-2023-48795 and2026-44405 mitigated in the application's SSH connection by disabling CBC/ChaCha20 and SHA1/RSA-SHA1 algorithms, with pinned host identity. The library itself is not fully upgraded |
| PyNaCl | Android wheel1.5.0 | CVE-2025-69277 concerns libsodium point validation. No project adapter calls crypto_core_ed25519_is_valid_point; the vulnerable dependency still needs a native upgrade |
| OpenCV | Android wheel4.5.1.48 | Its Chaquopy recipe explicitly disables WebP/TIFF/Jasper/OpenEXR, so the PyPI wheel libwebp finding is not directly transferable. The old native dependency set still needs a supported replacement |

OpenSSL findings attached to desktop cryptography wheels do not identify the
OpenSSL version in a separately built Chaquopy wheel. The Android cryptography
extension dynamically depends on the `_chaquopy` compatibility stubs, which forward
to the current `_python` OpenSSL libraries. Its old build-time version string is
not the dynamically loaded library. CI checks the actual native runtime as well.
The desktop regression environment uses cryptography50.0.2 and cannot substitute
for testing the Android binary. Generated Python artifacts replace public upstream
build-user paths with equal-length anonymous strings before packaging.

稳定 APK 发布前仍需完成受支持的 Android 原生依赖迁移及真机验收。配置默认关闭、禁用易损算法
或未走到特定 API，都是限定条件下的风险收敛，不能宣传为依赖已经全部打补丁。

Sources: [Go report](https://pkg.go.dev/vuln/GO-2026-5932),
[Chaquopy release notes](https://chaquo.com/chaquopy/doc/current/changelog.html),
[OpenSSL supported releases](https://openssl-library.org/source/),
[CPython support status](https://devguide.python.org/versions/),
[Chaquopy OpenCV recipe](https://github.com/chaquo/chaquopy/tree/master/server/pypi/packages/opencv-python),
[cryptography SECT](https://github.com/advisories/GHSA-r6ph-v2qm-q3c2),
[cryptography name constraints](https://github.com/advisories/GHSA-m959-cc7f-wv43),
[Paramiko Terrapin](https://github.com/advisories/GHSA-45x7-px36-x8w8),
[libsodium point validation](https://github.com/advisories/GHSA-mrfv-m5wm-5w6w).
