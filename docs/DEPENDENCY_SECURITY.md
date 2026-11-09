# Dependency review / 依赖安全边界

This revision migrates the embedded runtime to supported CPython 3.13 and builds
Android native wheels from SHA-256-pinned source distributions. APK builds and
source scans alone are insufficient: check the packaged inventory and the
separate on-device native acceptance results before treating a candidate as ready.

本轮迁移至 CPython 3.13，并从固定哈希源码构建 Android 原生轮子。声明的版本、
构建通过、真机可运行是三类证据；实际结果见 [Validation](VALIDATION.md)。

| Component | Declared change | Verification boundary |
|---|---|---|
| Python / Chaquopy | 3.10 → 3.13; Chaquopy 17.2.0 | APK inventory and device interpreter version; upstream Python 3.10 is end-of-life |
| OpenSSL | 3.5.9 LTS in Python and newly built cryptography | Check both the packaged shared library and cryptography's linked runtime |
| cryptography | 42.0.8 → 50.0.2 | Native AES-GCM and X25519 round trips; do not substitute desktop tests |
| Paramiko | 2.12.0 → 5.1.0 | Native key/signature tests; retain host-key pinning and disabled legacy SSH algorithms |
| PyNaCl / bcrypt / cffi | 1.6.2 / 5.0.0 / 2.1.1; libffi 3.8.0 | Android signature/password-hash checks; source versions alone do not identify bundled C libraries |
| NumPy / OpenCV | 1.26.2 / 4.5.1 → 2.5.4 / 5.0.0.93 | Actual arm64 numerical, image and OCR checks; NumPy uses internal BLAS/LAPACK fallback |
| ONNX Runtime / sherpa | 1.31.1 / 2.0.1 | OCR and local speech inference on the target device; model download terms are separate |
| Conscrypt | 2.5.2 → 2.9.0 | Native TLS 1.3 initialization and cipher check; wireless pairing still needs device acceptance |
| certifi | 2026.10.23, including bundled Lark and generated CA assets | Native TLS uses Android's trust store independently |
| Go mesh | Go 1.27.3 with the prior pinned modules | Prior scan flagged deprecated OpenPGP outside the inspected import graph; re-audit if mesh imports change |
| aiohttp family | Existing patched portable wheels retained | Pure Python paths trade some performance for compatibility |
| DOMPurify | 3.4.17 retained | Keep HTML sanitization and privileged WebView separation |

`tools/native-sources.json` records downloaded native source digests. The reusable
native workflow builds its dependencies for each revision or restores a scoped
cache; Android builds consume artifacts from that same workflow run, never a
permanent URL to an expiring artifact. Native build hooks adapt compiler paths,
linking and target ABI information; no runtime security check is disabled.

OpenCV excludes WebP, TIFF, Jasper, OpenEXR, AVIF, OpenJPEG, FFmpeg and downloaded
Unicode fonts. Build inventory and linked library inspection must agree with these
flags. Generated artifacts redact upstream build-user paths before APK hashing.
Voice models use fixed public HTTPS sources, bounded downloads and SHA-256
verification; [model provenance](OFFLINE_VOICE.md) does not claim a code license
also licenses weights.

No client can enforce a server's billing or quotas. Keep credentials out of source,
use server-side authorization, and test service integrations separately. These
controls and version upgrades are not a vulnerability-free certification.

Sources: [Chaquopy release notes](https://chaquo.com/chaquopy/doc/current/changelog.html),
[Python support status](https://devguide.python.org/versions/),
[cibuildwheel Android](https://cibuildwheel.pypa.io/en/stable/platforms/#android),
[OpenSSL releases](https://openssl-library.org/source/),
[NumPy cross compilation](https://numpy.org/doc/stable/building/cross_compilation.html),
[Go report](https://pkg.go.dev/vuln/GO-2026-5932).
