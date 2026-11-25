# Third-party components

The Apache-2.0 license covers project-owned code. Third-party notices and license
terms continue to apply. Exact dependency versions are in `app/build.gradle`,
`tsbridge/go.mod`, `tsbridge/go.sum`, `ios/deps/get_python.sh`, `ios/deps/get_shell.sh`,
the bundled archive and the build output.

## Android & Shared WebUI Components

| Component | License / distribution choice | Source |
| --- | --- | --- |
| CPython / Chaquopy | PSF / MIT | [CPython](https://github.com/python/cpython), [Chaquopy](https://github.com/chaquo/chaquopy) |
| OpenSSL 3.5.9 | Apache-2.0 | [OpenSSL](https://github.com/openssl/openssl/tree/openssl-3.5.9); supplied by the Chaquopy CPython runtime |
| Kotlin / AndroidX / OkHttp / Conscrypt | Apache-2.0 | [Kotlin](https://github.com/JetBrains/kotlin), [AndroidX](https://android.googlesource.com/platform/frameworks/support/), [OkHttp](https://github.com/square/okhttp), [Conscrypt](https://github.com/google/conscrypt) |
| NanoHTTPD | BSD-3-Clause | [NanoHTTPD](https://github.com/NanoHttpd/nanohttpd) |
| sherpa-onnx | Apache-2.0; static dependencies retain their notices; model terms separate | [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), [voice model provenance](docs/OFFLINE_VOICE.md) |
| libffi / OpenSSL | MIT / Apache-2.0 | Fixed sources in `tools/native-sources.json`; linked into cffi / cryptography |
| ONNX Runtime | MIT | [ONNX Runtime](https://github.com/microsoft/onnxruntime) |
| LibADB Android | Apache-2.0 option; auxiliary BSD/MIT notices retained | [LibADB 3.1.1](https://github.com/MuntashirAkon/libadb-android/tree/3.1.1) |
| sun-security-android | GPL-2.0 with Classpath exception; unmodified library (Android only) | [Exact 1.1 source](https://github.com/MuntashirAkon/sun-security-android/tree/c933659431310bf19a6f5e3166bf7a271d280d3a) |
| ZXing Android Embedded | Apache-2.0 | [ZXing Embedded](https://github.com/journeyapps/zxing-android-embedded) |
| Tailscale / tsnet | BSD-3-Clause; transitive Go modules retain their licenses (Android optional mesh) | [Tailscale 1.100.0](https://github.com/tailscale/tailscale/tree/v1.100.0) |
| PaddleOCR PP-OCR models and dictionary | Apache-2.0 | [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) |
| marked | MIT | [marked](https://github.com/markedjs/marked) |
| DOMPurify | Apache-2.0 option | [DOMPurify 3.4.17](https://github.com/cure53/DOMPurify/tree/3.4.17) |
| highlight.js | BSD-3-Clause | [highlight.js](https://github.com/highlightjs/highlight.js) |
| KaTeX and mhchem | MIT; included fonts retain upstream notices | [KaTeX](https://github.com/KaTeX/KaTeX) |
| requests / beautifulsoup4 / PyYAML | Apache-2.0 / MIT / MIT | PyPI packages of the same name |
| NumPy / OpenCV | BSD-3-Clause / Apache-2.0; Android-native build dependencies retain separate notices | [NumPy](https://github.com/numpy/numpy), [OpenCV](https://github.com/opencv/opencv), [Chaquopy recipes](https://github.com/chaquo/chaquopy/tree/master/server/pypi/packages) |
| OpenCV libpng / zlib overrides | PNG Reference Library License / zlib; unmodified upstream C sources with OpenCV's CMake adapters | Fixed archives and hashes in `tools/native-sources.json`; separate license texts in `third_party/licenses/` |
| cryptography / cffi / bcrypt / PyNaCl | Apache-2.0 or BSD / MIT / Apache-2.0 / Apache-2.0 | Hash-pinned source distributions; Android wheels built with cibuildwheel |
| Paramiko | LGPL-2.1 (Android only) | [Paramiko](https://github.com/paramiko/paramiko); unmodified Python source wheel in `third_party/`, also embedded in the APK |
| aiohttp / multidict / yarl / frozenlist / propcache | Apache-2.0 | [aio-libs](https://github.com/aio-libs); portable source builds |
| websocket-client / websockets | Apache-2.0 / BSD-3-Clause | Respective PyPI distributions |
| certifi | MPL-2.0 | [certifi](https://github.com/certifi/python-certifi); CA bundle is public trust data |
| lark-oapi | MIT | [Lark SDK](https://github.com/larksuite/oapi-sdk-python) |
| Bundled Lark dependencies | Each upstream license; source retained in `fsbot/deps/site_packages.tgz` | anyio, exceptiongroup, h11, httpcore, httpx, idna, pyaes, requests-toolbelt, sniffio, websockets, certifi |

## iOS App & ESP32-S3 Firmware Components

| Component | License / distribution choice | Source |
| --- | --- | --- |
| ESP32 iPhone Agent (`ios/BoardKit/`, `ios/firmware/`) | MIT | [esp32-iphone-agent](https://github.com/onehumanbeing/esp32-iphone-agent) by Henry Yuan (`ios/BoardKit/LICENSE`, `ios/firmware/LICENSE`); pure MIT BLE/USB HID bridge only (all GPL AirPlay components excluded) |
| BeeWare Python-Apple-support (CPython 3.13 for iOS) | PSF / MIT / BSD / Apache-2.0 | [Python-Apple-support](https://github.com/beeware/Python-Apple-support); fetched on demand by `ios/deps/get_python.sh` |
| mobile-forge iOS wheels (`cryptography`, `cffi`, `pycparser`) | Apache-2.0 or BSD / MIT / BSD-3-Clause | [mobile-forge](https://anaconda.org/beeware/); fetched on demand by `ios/deps/get_python.sh` |
| rubicon-objc | BSD-3-Clause | [rubicon-objc](https://github.com/beeware/rubicon-objc); pure-Python Objective-C bridge for iOS `code_run` |
| ios_system & UNIX shell applets (`dash`, `shell`, `files`, `text`, `awk`) | BSD-3-Clause / BSD | [ios_system](https://github.com/holzschuh/ios_system); fetched on demand by `ios/deps/get_shell.sh` and loaded dynamically for local workspace commands |
| NimBLE-Arduino & Arduino-ESP32 core | Apache-2.0 / LGPL-2.1 | [NimBLE-Arduino](https://github.com/h2zero/NimBLE-Arduino), [arduino-esp32](https://github.com/espressif/arduino-esp32); used when compiling `ios/firmware/hid_bridge` with `arduino-cli` |
| Apple System Frameworks (`ReplayKit`, `Vision`, `CoreBluetooth`, `ActivityKit`, `Speech`, `WebKit`) | Apple SDK License | Supplied by iOS / Xcode |

License texts for directly vendored components are in `third_party/licenses/`,
`ios/BoardKit/LICENSE`, and `ios/firmware/LICENSE`.
The Android build embeds notices and source archives in APK assets under
`third_party/`; mesh licenses are collected from the resolved Go module sources.
`third_party/provenance.json` records retrieved package sources and checksums.
The sun-security source archive is included separately for corresponding-source
availability; the Classpath exception applies only as stated in the upstream file
headers. Do not remove upstream notices when rebuilding dependencies.
The Paramiko source wheel contains its unmodified Python modules (Android only;
excluded from iOS builds). To replace that library on Android, change the dependency
in `app/build.gradle`, rebuild and sign with your own key.

Generated Chaquopy assets replace upstream build-user path strings with equal-length
anonymous build paths and update the public CA bundle before asset hashing and APK
signing. These are packaging changes to third-party artifacts, not upstream releases.

All YOLO-derived detector weights and GPL AirPlay receiver sources are excluded.
Supplying or distributing another detector model requires a separate license review.
Service branding and private server implementations are not granted by the project
source license.

The compact PP-OCRv4 recognition graph (Android) is a derived output graph of the
bundled PaddleOCR model, with unchanged recognition weights and Apache-2.0 attribution.
See its bundled MODEL_NOTICE and `tests/test_compact_ocr.py`.
