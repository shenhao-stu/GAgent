# News & development history / 新闻与开发沿革

[Roadmap](ROADMAP.md) · [Changelog](../CHANGELOG.md) · [Validation](VALIDATION.md)

## Earliest verifiable Android implementation / 最早可核验的 Android 实现

**2026-06-13, UTC+8.** The predecessor's initial commit `f684f6c` already contains
`ga_android.py`, the Python agent loop, the Android capability bus, accessibility,
screenshots, a floating service and an ONNX/OCR pipeline. The same-day README
update `270a59e` records a working debug APK, Gradle and real-device validation,
Android-adapted Python/shell tools and persistent conversations.

**2026 年 6 月 13 日（UTC+8）**是目前检索到的最早 Android 实现记录。
当日代码已包含 Python 智能体、设备总线、无障碍、截图、浮窗及 ONNX/OCR 管线；
随后更新的 README 记录了 debug APK、Gradle 与真机验证、Android 工具执行和会话持久化。

The initial README still described an earlier chat-only limitation; the code and
its later same-day documentation are the stronger evidence for that day's state.
This review did not recreate the 2026-06 build environment or rerun those device
checks. It establishes recorded implementation history, not independent historical
certification, a public launch date, or priority over another project.

初始 README 还保留较早的“仅对话”描述，不能忽略同日源码与后续文档的更新。
本轮核对历史而未重建当时环境，不把旧验收记录说成今天重新验证，也不据此宣称行业首创。

## Selected milestones / 重要里程碑

Dates below use recorded commit time converted to UTC+8. “Implemented” describes
the predecessor at that time; current availability and setup are listed separately.

| Date / 日期 | Recorded development / 已记录开发 | Source reference / 提交依据 | Current open-source boundary / 当前边界 |
| --- | --- | --- | --- |
| 2026-06-13 | Android agent, native bridge, screenshot/vision pipeline; same-day build/device report / Android 实现与当日验证记录 | `f684f6c`, `270a59e` | Python runtime and native device layer retained / 保留运行时与设备层 |
| 2026-06-14 | APK CI and richer model/provider/session UI / APK CI、多模型与会话界面 | `dd7a168`, `0da6182` | Current build recipe and user-supplied providers / 当前构建与自选服务商 |
| 2026-06-16 | Streaming voice input / 流式语音输入 | `6dfbf67` | Optional voice client; own compatible service required / 语音客户端保留，服务需自行接入 |
| 2026-06-24 | Android-specific YOLOv8n, 21 UI classes, replacing the earlier detector / 换用 Android 专用 21 类检测器 | `b039f1b` | OCR bundled; YOLO installed separately under applicable terms / OCR 内置，YOLO 独立安装 |
| 2026-06-27 | Local modification preservation across asset updates and conversation continuity / 资源更新中的本地修改保留与续聊 | `732c8ca` | Best-effort local evolution/merge; not a guarantee to preserve every edited bundled file / 保留机制，不保证所有资源改动无损 |
| 2026-07-03 | Wireless ADB, browser control and virtual-display adapters / 无线 ADB、浏览器控制与虚拟屏 | `837eb84` | Device-dependent optional setup / 按设备配置与验收 |
| 2026-07-15 / 07-18 | Scheduled tasks and native notification triggers / 定时任务与通知触发 | `f502043`, `bd033d4` | User-created rules and Android permissions required / 需用户规则与系统权限 |
| 2026-08-06 / 08-13 | PC Link/P2P client and recorded GAnet integration / 电脑互联与组网客户端 | `68c6311`, `9203ec1` | Optional clients; no bundled service authority / 可选接入，不附带服务端权限 |
| 2026-10-23 | Clean Apache-2.0 extraction, explicit module configuration, visual-only WeChat and Pixel network/overlay/geometry acceptance / 开源预览与有限 Pixel 验收 | [Device-build baseline](https://github.com/shenhao-stu/GAgent/commit/6c4683a1a36ccc7b3b9a121099b81ef2d1d75422) | Source preview; native dependency and cross-device work remains open / 源码预览，依赖与跨设备待办保留 |

GAnet's `9203ec1` has an author date of July 20 and a recorded commit date of
August 13. We use the latter rather than implying a July release. The same rule
keeps rebased/imported history from silently becoming a release claim.

GAnet 该提交的作者日期为 7 月 20 日、提交记录日期为 8 月 13 日；本页使用后者，
不将作者日期推断为上线日期。

## Provenance and publication / 依据与公开

Pre-extraction references above were reviewed in the private **GAndroid** history.
Those short hashes identify predecessor commits and may not resolve in this clean
repository. We publish selected dates and feature summaries, not old private Git
history, configurations, account data or service implementations.

`shenhao-stu/GAgent` starts a separate sanitized history. The owner authorized
source publication on 2026-10-23. Android's earlier implementation, private
repository creation, source publication and APK releases are separate events.
The preview retains the [documented dependency and device limits](ROADMAP.md).

历史摘要经私有 GAndroid 记录核对，旧提交不必存在于本仓库。
所有者于 2026-10-23 授权源码公开；旧实现、私库创建、源码公开与 APK 分发分别记录。
本页不公开旧仓库历史或敏感资料，也不将预览版称为稳定 APK。
