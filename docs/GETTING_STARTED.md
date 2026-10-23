# Get started / 开始使用

[Documentation](README.md) · [Troubleshooting](TROUBLESHOOTING.md)

## 1. Choose a device and build / 选择设备与安装包

Use an arm64-v8a Android 11 / API 30+ phone for screenshot-based phone use.
The app declares minSdk 24, but its accessibility screenshot path explicitly
requires API 30+. Current physical validation covers Pixel 10 / Android 16;
other OEMs, real foldables and 16 KB page-size configurations need separate tests.

截图工作流要求 arm64-v8a、Android 11 / API 30+；最低可安装版本不等于完整功能支持。
当前仅有 Pixel 10 / Android 16 实机证据，详见[验收范围](VALIDATION.md)。

Obtain an APK from this repository's release or CI artifact, or follow
[Build](BUILD.md). Check its SOURCE_COMMIT, SHA-256 and signing certificate.
An unsigned release APK must be signed before installation.

| Package / 包 | Identity / 应用 ID | Data / 数据 |
| --- | --- | --- |
| Release | `io.github.shenhaostu.gagent` | Separate app-private directory / 独立私有目录 |
| Debug | `io.github.shenhaostu.gagent.debug` | Separate from release / 与正式版分离 |

The earlier app is a different installation. Updates require the same application
ID and compatible signing identity. Keep any existing app and its data when
trying another variant. Do not uninstall an app or clear its data to resolve a
signature error without first arranging an explicit backup and migration.

旧版、开源正式版和调试版是不同安装身份。尝试新包时保留原数据；签名错误应核对制品来源，
不要直接卸载。只有 APK 升级成功，不代表数据迁移已经被验证。

## 2. Configure a model / 配置模型

Open **Settings → Providers & Models** and add the endpoint, credential and model
issued by your provider. Choose the matching protocol; an Anthropic-compatible
URL is not interchangeable with an OpenAI-compatible URL. Enter a model manually
if the provider does not expose a usable model list.

在「设置 → 服务商与模型」添加接口、密钥与模型，协议要与服务商相符。
服务商不提供模型目录时，可手动添加模型。

Validate three separate capabilities:

1. **Text:** a short request returns a response.
2. **Tools:** a harmless task actually invokes a tool and consumes its result.
3. **Vision:** a synthetic image is interpreted correctly by the configured visual adapter.

文本成功不能证明工具或图像可用。视觉能力还涉及
[`vision_api.template.py`](../app/src/main/assets/gacore/memory/vision_api.template.py)
与用户生成的 `memory/vision_api.py`；更换模型配置时检查该引用。
支持 Anthropic 原生工具调用的服务商可复用已有原生适配器，旧配置迁移见[网络指南](NETWORK.md)。

Keep the provider proxy empty unless needed. If used, it must be reachable from
the phone. `127.0.0.1` means the phone itself, not the development computer.
Normal use does not require USB, wireless ADB or `adb reverse`.
Credentials are sent to the selected service for authentication; screenshots and
tool output may also leave the device as part of model requests.

## 3. Grant capabilities as needed / 按需授权

| Capability / 能力 | Used for / 用途 |
| --- | --- |
| Accessibility / 无障碍 | Device observation and gestures, including the API 30+ screenshot path / 设备观察、手势与截图 |
| Display over other apps / 悬浮窗 | Task status while another app is visible / 在其他应用上显示任务状态 |
| Notifications / 通知 | Task and foreground-service visibility, subject to Android version / 任务与前台服务通知 |
| Microphone / 麦克风 | Voice input when used / 使用语音输入时 |
| Files / 文件 | Tools that read or write shared storage / 读写共享存储 |
| Camera / 相机 | In-app pairing-code scanning / 应用内扫描配对码 |
| Optional sensing permissions / 可选感知权限 | Enabled sensing features, such as location or calendar access / 已启用的定位、日历等感知能力 |

This table explains capabilities, not a request to enable every permission.
Wireless ADB and optional server modules have their own setup; neither is needed
to begin with the ordinary screenshot/gesture route.

不必一次开启全部权限。先配置当前任务需要的能力，后台异常再核查系统限制。
不要通过关闭证书校验解决联网问题。

## 4. Run a small, observable task / 先做可观察的小任务

Try “Open Settings and describe the visible screen without changing any settings.”
Check that the intended app opened, the screen description matches, and the task
can be stopped. Move GAgent to the background during a harmless task to check its
overlay. Enable **Always-on floating window** if you want it retained in apps
whose visual-only policy otherwise hides it.

可先让它“打开设置，描述画面，不修改设置”。检查实际画面，并试用停止按钮。
任务切后台时检查浮窗；需要在微信等应用持续显示时开启“悬浮窗常开”。

For WeChat, use screenshots, OCR, optional YOLO, visual questions and gestures.
Do not substitute node-tree reads or internal app APIs for the GUI route.
A login screen, payment confirmation or system restriction is a boundary to
handle deliberately, not evidence that the task has completed.

## 5. Add optional modules later / 再接入可选组件

**Settings → Optional modules** configures PC Link/P2P, GAnet, voice and APK
building. These are client integrations, not installers for the server components.
GA Plan is configured as a normal model provider. Review
[protocol and credential requirements](OFFICIAL_MODULES.md) before enabling them.

默认无需可选服务。先验收基本模型与设备路径，再逐项接入；客户端配置成功不代表服务端部署通过。
YOLO 的独立安装与许可见[可选检测模型](OPTIONAL_YOLO.md)。

## First-run evidence / 首次验收记录

Record the app version/commit, package variant, Android version, device model,
orientation, enabled capabilities and text/tool/image outcomes. Do not include
keys, full provider configuration, personal screenshots or account details in an
issue. [Troubleshooting](TROUBLESHOOTING.md) explains what to collect for a failure.
