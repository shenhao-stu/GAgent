# GAgent & DeepSeek Android ports / 设计对照

[README](../README.md) · [Core & memory](CORE_AND_MEMORY.md) · [Capability setup](CONFIGURATION.md)

Reviewed **2026-10-23**. “DeepSeek Harness Android” names several community ports,
not one official Android product. This comparison uses the published documentation
of two specific revisions. We did not install or benchmark these ports on the Pixel.

核对日期为 **2026-10-23**。以下比较具体社区项目，不代表 DeepSeek 官方 Android 产品，
也不是同机性能或成功率测试。上游变更后请重新核对。

## Sources / 固定版本来源

- **D:** [dphmoblie/deepseek-harness-android, `da8843a`](https://github.com/dphmoblie/deepseek-harness-android/blob/da8843a72fcee611f0fbc2b01360aa27b31c02c2/README.en.md).
- **S:** [Soodok/Deepseek-Harness-Local-Android, `2e9edb3`](https://github.com/Soodok/Deepseek-Harness-Local-Android/blob/2e9edb3738937320664033fb302dee5dded3bf12/README.md).
- **G:** this repository's linked implementations and [configuration guide](CONFIGURATION.md).

## Architecture / 架构选择

| Dimension / 维度 | GAgent | Reviewed DeepSeek ports / 已核对移植 |
| --- | --- | --- |
| Runtime / 运行时 | Embedded Python, GenericAgent loop and native Android adapters / 内嵌 Python 与设备适配 | **D:** dsh/Node.js in Ubuntu/PRoot. **S:** native bionic Node.js; no PRoot/Ubuntu or installed Termux app required. |
| Device shell / 设备 shell | Direct wireless-debugging self-pairing; no separate Shizuku installation / 直接无线调试自连 | **D/S:** optional Shizuku. Ordinary operation does not require it; do not describe it as mandatory for every task. |
| Visual interaction / 视觉交互 | Local OCR, optional 21-class Android YOLO, configured vision and gestures / OCR、可选 YOLO 与模型视觉 | **S:** documents accessibility plus OCR/icon fallback and frame-difference handling. Visual interaction is shared territory. |
| Offscreen apps / App 离屏 | Self-ADB virtual-display adapter; experimental and device-dependent / 实验性虚拟屏 | **D:** also documents experimental virtual screens with Shizuku/AI Shell. |
| Voice / 语音 | Configurable Step ASR streaming input / 可配置流式语音输入 | **S:** documents voice input too. A named client path is not evidence of exclusive voice support. |

These choices do not establish that Python is always faster than Node.js or that
Shizuku is inherently expensive. “Lightweight” here describes GAgent's reuse of
Android WebView, a compact seed loop and optional local detection—not a measured
RAM, battery, APK-size or latency advantage over these projects.

“轻量”描述具体设计：复用系统 WebView、小循环与可选本地检测。
没有同机测量时，不据此宣称内存、功耗、包体、速度或成功率优胜。

## What GAgent combines / GAgent 的组合重点

| Capability / 能力 | Implementation and setup / 实现与开启 |
| --- | --- |
| 🧠 Reusable memory / 可复用记忆 | [Layered memory](CORE_AND_MEMORY.md): small index, selective recall, working checkpoints and saved procedures. |
| 👁️ Local screen candidates / 本地视觉候选 | [YOLO guide](OPTIONAL_YOLO.md): OCR is bundled; Android YOLO weights are optional. Local boxes help locate controls; semantics and state verification remain necessary. |
| 📱 Self-ADB / 无线调试自连 | [Pairing SOP](../app/src/main/assets/gacore/memory/adb_self_setup.md): explicit Android authorization and persisted pairing identity. Ordinary GUI operation does not need ADB. |
| 🌐 Browser sessions / 浏览器登录态 | [BrowserActivity](../app/src/main/java/com/ljq/ga/BrowserActivity.kt), [task browser](../app/src/main/java/com/ljq/ga/AgentBrowserActivity.kt) and [offscreen SOP](../app/src/main/assets/gacore/memory/offscreen_sop.md): shared Android WebView cookies; manual login, task use and background web work. Expired sessions still require login. |
| 🪟 App virtual displays / App 虚拟屏 | [vdisplay.py](../app/src/main/assets/gacore/vdisplay.py): probe, create, observe, input and stop through self-ADB. Secure pages and unsupported apps/ROMs may refuse capture or launch. It is not locked-screen automation. |
| 🔗 PC Link / P2P / GAnet | [pclink.py](../app/src/main/assets/gacore/pclink.py), [ganet.py](../app/src/main/assets/gacore/ganet.py): clients for paired peers and authorized mesh workflows. Compatible remote services and peer software are required. |
| 🎙️ Step Voice | [VoiceClient.kt](../app/src/main/java/com/ljq/ga/VoiceClient.kt): PCM16, 16 kHz mono over a compatible WSS relay; default model `step-asr-1.1-stream`. This is streaming speech input, not a claim of a complete duplex voice assistant. |
| 🛠️ APK Factory / APK 工厂 | [apk_factory.py](../app/src/main/assets/gacore/apk_factory.py) and [workflow](../app/src/main/assets/gacore/memory/apk_factory_sop.md): generate a project, submit it, track the build and retrieve the APK. Workers, quotas and signing authority stay in your configured service. |

This table explains GAgent's scope. It does not imply that an unlisted feature is
absent from every competing port. Optional service clients are included; production
credentials and server deployments are not. See [component boundaries](OFFICIAL_MODULES.md).

上表强调 GAgent 的能力组合，不把对方文档未提到的能力直接判定为不存在。
可选服务需要用户主动配置；“客户端已保留”与“服务已部署并验收”分别判断。
