# Feature scope / 功能去留清单

Reviewed on 2026-10-23; 2.33.3 / 136 candidate builds on the 2.33.2 GUI policy. Exact build and device results are recorded in release notes.
This describes the open-source preview. “Removed” means removed from this
distribution; the original projects remain intact.

核对日期：2026-10-23，应用源码基线同上。本仓库作为开源预览提供。
下文的“剥离”指从本次分发中移除，不代表删除原项目或停止现有服务。

## Kotlin decision / Kotlin 决定

The owner confirmed that Android APKs and the necessary Kotlin device layer stay.
Kotlin currently provides application startup, the Python bridge, accessibility,
screenshots, overlays, microphone access and background work. Removing it without
a replacement would remove those capabilities. Native source and unit tests live
under app/src/main/java and app/src/test/java. This retained layer is not a claim
that every inherited module is already minimal.

保留 Android APK 和必要的 Kotlin 设备层，源码与测试以当前目录为准。
源码加密已经移除；设备适配层继续保留。
HTTPS/WSS、P2P 传输加密和设备总线鉴权继续保留，它们承担通信和访问安全。
现有原生层仍有大模块，本次没有宣称已经完成全部精简。

## Removed or disabled / 已剥离或停用

| Capability / 能力 | Current result / 当前结果 | Evidence / 证据 |
| --- | --- | --- |
| Mandatory hosted login, plans, payment, orders, credits and redemption entry / 强制托管登录、套餐支付、订单积分和领取入口 | Removed from the app; users configure a model provider themselves / 已从应用剥离，改为用户自行配置模型服务商 | `PlanActivity.kt`, `DeepLinkActivity.kt`, `webui/auth.js` absent; [provider configuration](../app/src/main/assets/gacore/provider_config.py) |
| Source encryption / 源码加密 | NativeKey, native key store and client decryption removed; assets copied as readable files / 删除 NativeKey、原生密钥与客户端解密链，资源按可读文件装载 | [AssetUnpacker.kt](../app/src/main/java/com/ljq/ga/AssetUnpacker.kt), [bootstrap.py](../app/src/main/python/bootstrap.py) |
| Hosted telemetry, prompt contribution, remote diagnostics and feedback submission / 托管遥测、提问捐赠、远端诊断和反馈上传 | Collection/upload disabled; compatibility no-ops and bounded local diagnostics remain / 停用收集上传，保留兼容空实现和有界本地诊断 | [Analytics.kt](../app/src/main/java/com/ljq/ga/Analytics.kt), [Diag.kt](../app/src/main/java/com/ljq/ga/Diag.kt) |
| Embedded service authority / 内置服务权限 | No default shared P2P credential, vendor speech key or client-side root signer / 移除默认共享 P2P 凭据、供应商语音密钥和客户端根签发权限 | [Official modules](OFFICIAL_MODULES.md) |
| Old update channels / 旧版自动更新通道 | Old manifests disabled; download/install primitives remain; releases are obtained from this repository / 旧清单地址停用，下载与安装基础能力保留，从本仓库获取版本 | [Endpoints.kt](../app/src/main/java/com/ljq/ga/Endpoints.kt), [Updater.kt](../app/src/main/java/com/ljq/ga/Updater.kt) |
| Bundled YOLO icon detector / 内置 YOLO 图标检测模型 | Weight excluded by default; users may install a compatible model under its applicable terms; OCR still runs / 默认不分发权重，用户可按适用许可自行安装，OCR 保留 | [Model notice](../app/src/main/assets/gacore/models/ui_detect_v1/MODEL_NOTICE.txt), [detector fallback](../app/src/main/assets/gacore/models/ui_detect_v1/ui_detect_lite.py) |
| Old release identity and private material / 旧发布身份与私有资料 | Old signing key, production configuration, account data and old Git history excluded; new app ID and signing identity / 不分发旧签名、生产配置、账号资料或旧 Git 历史，使用新应用与签名身份 | [Build](BUILD.md), [review](REVIEW.md) |

## Outside this repository / 未纳入此次仓库

| Implementation / 实现 | What is distributed instead / 本次保留的接入方式 |
| --- | --- |
| GA Plan commerce, billing and the complete GA2api gateway / GA Plan 商业与计费系统、完整 GA2api 网关 | Normal model-provider interface with a user-issued API key / 普通模型服务商接口，由用户填写自己的 API Key |
| P2P relay operations and credential issuance / P2P 中继运营与凭据签发服务 | PC Link / P2P client and explicit WSS configuration / 客户端与显式 WSS 配置 |
| GAnet identity issuer and mesh control plane / GAnet 身份签发与组网控制面 | Pairing, mesh and SSH clients / 配对、组网与 SSH 客户端 |
| Hosted voice relay and vendor credentials / 托管语音代理及供应商凭据 | Streaming voice client / 流式语音客户端 |
| APK factory workers, quotas and signer service / APK 工厂构建工作节点、额度与签名服务 | Project scaffold/template, submission, polling and download client / 工程模板、提交、轮询和下载客户端 |
| Production deployment, administration and commercial web pages / 生产部署、运维管理与商业网页 | No production environment or privileged credentials / 不携带生产环境与管理凭据 |
| iOS and ESP32 work / iOS 与 ESP32 工程 | Maintained separately; not deleted and not part of this Android export / 继续在原项目维护，没有删除，也未并入此次 Android 分发 |

Exclusion here is not a permanent decision to keep every service implementation
closed. A service's code can be published without publishing its production keys.
Separate server-component releases need their own scope, licensing, deployment
instructions and acceptance checks. This client repository does not deploy them.

这里的“未纳入”不代表所有服务端代码都必须闭源。服务源码可以公开，生产密钥必须独立保管。
P2P、GAnet、语音代理和构建服务若继续作为独立开源组件发布，需要分别确定范围、许可证、
部署说明与验收；本仓库目前没有提供它们的一键服务端部署。

## Retained / 继续保留

| Capability / 能力 | Source / 主要源码 | Conditions / 条件 |
| --- | --- | --- |
| Agent planning, tools and code execution / 智能体规划、工具调用与代码执行 | `agent_loop.py`, `agentmain.py`, `llmcore.py`, `ga_android.py` | User-selected model/provider; execution has real effects / 用户配置模型，执行具有真实副作用 |
| Bilingual UI, sessions, streaming, memory and file tools / 中英文界面、会话、流式输出、记忆和文件工具 | `webui/`, `android_entry.py`, `memory/` | Existing local workflows remain / 保留本地工作流 |
| Android startup and embedded Python / Android 启动与内嵌 Python | `App.kt`, `MainActivity.kt`, `Py.kt`, `bootstrap.py` | APK retains its native adapter / 仍依赖原生设备适配 |
| Accessibility, gestures, screenshots, clipboard, overlays and wireless ADB / 无障碍、手势、截图、剪贴板、悬浮窗与无线 ADB | `BusA11yService.kt`, `BusServer.kt`, `FloatService.kt`, `AdbController.kt`, `droid.py` | Permissions and Android-version restrictions apply / 受授权与系统版本限制 |
| Browser automation, login browser and HTML preview / 浏览器自动化、登录浏览器与 HTML 预览 | `AgentBrowserActivity.kt`, `BrowserActivity.kt`, `HtmlPreviewActivity.kt`, `webcdp.py` | Authentication requires the user's own sessions / 登录态由用户提供 |
| Local text OCR / 本地文字 OCR | `models/ui_detect_v1/ppocr_engine.py` and PaddleOCR weights | Does not replace the excluded icon detector / 不等同于被排除的图标检测模型 |
| Scheduled tasks and notification rules / 定时任务与通知规则 | `AlarmSched.kt`, `NativeNotifTrigger.kt`, `NotifService.kt` | User configuration, permissions and background policy / 依赖用户配置、授权与系统后台策略 |
| Sensing and recording / 感知与记录 | `SenseService.kt`, `SenseQuickActivity.kt`, `SenseTileService.kt`, `sense.py` | Explicit activation and permissions; no blanket device validation / 需主动开启与授权，尚未完成真机全面验收 |
| Virtual-display and vendor-assistant adapters / 虚拟屏与厂商助手适配 | `VdHelper.kt`, `vdisplay.py`, `vendor_bridge.py` | Requires compatible devices/setup / 依赖兼容设备与配置 |
| Feishu tools and bot runtime / 飞书工具与机器人运行时 | `lark_native.py`, `fsbot/` | User supplies app credentials and grants permissions / 用户提供应用凭据与权限 |
| Local modification backup and merge / 本地自修改备份与融合 | `Evolution.kt`, `evolution.py` | Tracks local text changes during asset updates / 在资源更新时跟踪本地文本改动 |
| PC Link, GAnet, voice and APK-builder clients / PC Link、GAnet、语音与 APK 构建客户端 | `pclink.py`, `ganet.py`, `VoiceClient.kt`, `apk_factory.py`, `service_config.py` | Optional, disabled until configured, require compatible services / 默认未接入，需配置兼容服务 |
| Build, signing integration, source scans and license notices / 构建、签名接入、源码扫描与许可证声明 | `.github/workflows/android.yml`, `tools/`, `THIRD_PARTY.md` | Signing secrets stay outside Git / 签名秘密不进入 Git |

Python and WebUI paths in this table are under `app/src/main/assets/gacore/`;
Kotlin application paths are under `app/src/main/java/com/ljq/ga/`.

## Unresolved / 尚未确定或验收

- **Server release scope / 服务端开源范围：** the separate P2P, GAnet, voice and
  builder implementations have not been packaged for open-source distribution.
  Their absence does not mean the client features were deleted.
  这些服务尚未整理为可独立发布的开源组件；客户端能力仍保留，服务端后续发布范围待定。
- **Official onboarding / 官方接入闭环：** automatic login, token renewal and a new
  per-user issuer are not implemented. Legacy shared-key relays require migration;
  a settings screen alone does not establish safe authorization.
  官方自动登录、令牌续签和新逐用户签发器尚未实现；旧共享密钥中继仍需迁移，配置页不等于安全授权闭环。
- **Model redistribution / 模型再分发：** optional YOLO installation is documented in
  [OPTIONAL_YOLO.md](OPTIONAL_YOLO.md). The upstream model-card and export notices
  conflict; no new redistribution license is claimed.
  已提供自行下载和安装说明；模型卡与旧导出声明不一致，未宣称已取得新的再分发授权。
- **Device acceptance / 真机验收：** source retention, successful compilation and
  desktop regressions do not prove microphone, background jobs, screenshots,
  wireless ADB, virtual displays or third-party integrations work on every device.
  麦克风、后台任务、截图、无线 ADB、虚拟屏及外部服务接入仍需真机验收，不能由编译结果替代。
- **Dependency support / 依赖支持：** Python 3.10 and some Android-native wheels
  still require migration. See [dependency findings](DEPENDENCY_SECURITY.md).
  Python 3.10 和部分 Android 原生依赖仍需迁移，详见依赖审查文档。
- **Further decomposition / 后续解耦：** provider and service configuration are
  separated, but the inherited runtime, WebUI and native modules still include
  large files. This is not a completed architectural rewrite.
  已分离模型与组件配置，继承的运行时、WebUI 和原生层仍有大文件，尚未完成全部架构重构。

2.33.2 removes the fixed WeChat action budget while retaining screenshot-only
observation, visible GUI input, and stopping on observed account security challenges.
GLM tool arguments and vision text parsing are corrected. See release notes for
the exact build and device acceptance evidence.

2.33.2 去除微信固定操作预算，保留纯视觉观察、可见 GUI 输入与出现账号安全验证时停止。
修复 GLM 工具参数和视觉文本解析；具体构建与真机结果以发布说明为准。
