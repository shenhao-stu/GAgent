# Install and run GAgent / 安装与首次使用

[Docs](README.md) · [Let your agent help / 让 Agent 帮你安装](INSTALL_WITH_AGENT.md) · [All capabilities / 开启功能](CONFIGURATION.md) · [Troubleshooting / 排障](TROUBLESHOOTING.md)

Start with the APK, one model and a small task. The APK includes Python and the
phone tools; you do **not** need a development environment on the phone or computer.
YOLO, self-ADB, PC Link, voice and APK Factory can be added later.

先装 APK、配一个模型、跑通一个小任务。手机和电脑均无需为普通使用安装 Python、Java、
Gradle、Docker 或 Shizuku。YOLO、self-ADB、跨设备服务、语音和 APK 工厂按需接入。

## Before you begin / 准备

- **Phone:** arm64-v8a, Android 11 / API 30+ for screenshots and GUI use. The manifest
  permits API 24, but that does not provide the full screenshot workflow.
- **Model:** a provider-issued API base URL, your own key, exact model ID and matching
  OpenAI-compatible or Anthropic-compatible protocol. Phone tasks need tool use;
  semantic image understanding also needs an image-capable provider.
- **Network:** the phone must reach the provider independently. Keep Proxy empty
  unless needed; `127.0.0.1` on the phone is **the phone**, not your computer.

准备 arm64、Android 11+ 手机与自己的模型配置。确认手机能独立访问接口。
普通使用无需 USB、无线 ADB 或 `adb reverse`。当前有限实机证据包括 Pixel 10 与魅族 21 / Android 16；
更多 OEM、折叠屏和 16 KB 页大小配置仍需单独验收，见[范围](VALIDATION.md)。

<a id="download"></a>
## 1. Download and install / 下载与安装

This is an **open-source preview**. The quickest download is the latest
[prerelease](https://github.com/shenhao-stu/GAgent/releases) (no sign-in): take
**GAgent-release.apk** and `SHA256SUMS`, check the hash, then continue at step 5.
For a newer commit, use its Actions build below. Do not substitute an old draft or a
different distribution just because its app name looks the same. See [channels](ECOSYSTEM.md).

当前为**开源预览**。最快的方式是从最新[预发布版](https://github.com/shenhao-stu/GAgent/releases)
下载 **GAgent-release.apk** 与 `SHA256SUMS`（无需登录），核对哈希后从第 5 步继续；需要更新的提交时用下面的
Actions 构建。不要把旧草稿或同名的其他分发包当成本仓库最新版。[原生依赖迁移](DEPENDENCY_SECURITY.md)仍是稳定发布前的待办。

1. Sign in to GitHub and open [Android builds on main](https://github.com/shenhao-stu/GAgent/actions/workflows/android.yml?query=branch%3Amain).
2. Open the run for the commit you want. Both **verify** and **build** must be green
   for that same commit; a running or failed check is not a pass.
3. Under **Artifacts**, download **GAgent-android-<commit>** and extract the ZIP.
   Artifacts expire after **14 days**. If no current artifact is available, use
   [Build](BUILD.md); do not silently switch to an unverified download.
4. Match `SOURCE_COMMIT` to that run's commit. Check the APK against `SHA256SUMS`;
   `SIGNATURES.txt` records CI's signing verification. [Agent-assisted verification](INSTALL_WITH_AGENT.md#artifact)
   includes commands. A checksum detects a changed download; trust also depends on
   the repository and signing identity.
5. Transfer **GAgent-release.apk** to the phone if downloaded on a computer. Open it
   from the phone's Files app, allow **Install unknown apps** for that installer if
   prompted, then install. Android labels vary by vendor. Open GAgent and review
   its first-run privacy notice.

中文步骤：登录 GitHub → main 对应记录的两个任务全绿 → 下载底部制品 → 解压、核对提交与摘要 →
在手机「文件」中点开 **GAgent-release.apk** → 按系统提示允许该来源安装 → 打开 GAgent。
GitHub 制品下载需要登录，见[GitHub 官方说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts)。

| File / 文件 | Use / 用途 |
| --- | --- |
| `GAgent-release.apk` | Signed release variant; use this for ordinary preview testing / 已签名正式变体，通常选它 |
| `GAgent-debug.apk` | Separate debuggable variant for development / 独立调试变体，供开发排障 |
| `GAgent-release-unsigned.apk` | Unsigned build, **not installable as-is**; follow [Build](BUILD.md) for signing / 未签名，不能直接安装 |

Release ID: `io.github.shenhaostu.gagent`; debug ID:
`io.github.shenhaostu.gagent.debug`. These can coexist with the earlier app and keep
separate data. Updates need the **same package ID and compatible signing identity**.
On a signature mismatch, keep the installed app and obtain a matching package;
do not uninstall or clear data as an automatic fix. A successful APK upgrade does
not prove a separate data migration was performed.

旧版、开源正式包与调试包数据独立。签名不匹配先核对来源，保留原安装和数据；不要默认卸载重装。

**Use one active phone controller.** Each installation has its own floating-window
setting. If two edge handles appear, open the unused installation and turn off
**Settings → Always-on floating window** there. Keep its app and data; switching
controllers does not require uninstalling it or revoking its permissions.

**同一时间使用一个手机控制器。** 两版都有独立的悬浮窗开关；若边缘出现两个浮条，
进入暂不使用的那一版，在「设置」关闭「悬浮窗常开」。保留安装和数据，无需卸载或撤销权限。

## 2. Configure a model / 配置模型

Open **Settings → Providers & Models → Add provider**:

| Field / 字段 | Enter / 填写 |
| --- | --- |
| Protocol / 协议 | Match your provider's API, not the model brand / 按接口协议选择，不按模型品牌猜测 |
| Name / 名称 | A label you can recognize / 便于区分的名称 |
| API Key | Your own key, entered locally / 在本机输入自己的密钥 |
| API Base URL | The API endpoint from the provider, not its website / 服务商提供的接口地址，不填官网 |
| Default model ID / 默认模型 ID | Exact model name; then **Save** / 完整模型名，填好即可**保存** |
| Proxy / 代理 | Leave empty unless required and reachable from the phone / 无需求留空，否则必须由手机可达 |

**Fetching a model list is optional.** Some working endpoints do not support the
model-list API. A failed fetch or connection test is not proof that chat is broken:
enter a known model ID, save, and send a short message. Keep advanced options at
their defaults unless the provider requires them. Credentials authenticate to
your selected service; task text, screenshots and tool output may also be sent.

「设置 → 服务商与模型 → 添加服务商」直接填写模型 ID 即可，不必等待获取列表。
列表接口失败时用已知模型名保存，再发短消息测试。进阶选项先保持默认。

<a id="permissions"></a>
## 3. Enable phone control / 开启手机操作

1. Open **Settings → Accessibility** in GAgent, then **Enable** or **Enable
   accessibility manually**. In Android's accessibility settings, select the
   **GAgent OSS** (release) or **GAgent OSS Debug** and enable its service; return to GAgent and confirm
   it reports enabled. If Android blocks a sideloaded app with *Restricted
   settings*, review the app's origin and Android's on-screen instructions. The
   user must make that trust decision; an agent should not bypass it.
2. Enable **Settings → Always-on floating window**. Follow the prompt to allow
   **Display over other apps**, then return and check the switch is on.
3. Allow task notifications when requested. The current preview may also open
   the all-files settings page on launch. You can return without granting it for
   text chat and basic screenshot/gesture tasks. Microphone access is requested
   when voice capture needs it. Grant camera, shared-file or sensing access when
   you need it; if
   voice reports a permission denial, enable Microphone in Android app permissions.

「设置 → 无障碍权限 → 去开启／手动开启无障碍」进入系统页，为**本次安装的 GAgent**授权后返回；
再开「悬浮窗常开」，按引导授予「显示在其他应用上」。遇 Android「受限设置」先核实安装来源，
由你本人按照系统提示决定是否允许。系统列表中选择 **GAgent OSS**（调试版为 **GAgent OSS Debug**），
避免与原有闭源版混淆。通知用于显示任务状态；当前预览首启可能提前打开「所有文件访问」，
纯文本与基础截图/手势可先返回。麦克风在语音采集需要时申请；若已永久拒绝，到系统应用权限开启。

On Meizu / Flyme, the accessibility shortcut can first open **Auxiliary features**;
scroll to **Accessibility → Downloaded apps → GAgent OSS**. Labels vary across ROMs.
魅族 Flyme 可能先进入「辅助功能」总页：向下找到「无障碍 → 已下载的应用 → GAgent OSS」。

Wireless debugging and accessibility auto-keep are advanced options. You can begin
with manually enabled accessibility; self-ADB is not a prerequisite for ordinary
screenshots and gestures. If the system later stops background work, use the
app's accessibility keep-alive guide and [Troubleshooting](TROUBLESHOOTING.md).

先手动开通无障碍即可，不必先配置无线调试、持久化或任何可选服务。

<a id="acceptance"></a>
## 4. Verify the first task / 首次验收

| Check / 检查 | Task and observable result / 任务与验收 |
| --- | --- |
| Text / 文本 | “Reply OK.” A response arrives from the selected model / “请回复 OK”，确认所选模型响应 |
| Tools / 工具 | “Open Settings; do not change anything.” Confirm Settings actually opens / “打开设置，不修改任何设置”，核对手机画面 |
| Vision / 看图 | Use the [vision setup prompt](CONFIGURATION.md#models), test a synthetic image, then describe the Settings screen / 先配置视觉并用合成图自测，再描述设置页 |
| Background / 后台 | During a harmless task, press Home; check the overlay and stop control / 无害任务中回桌面，检查浮窗与停止按钮 |
| Independent network / 独立网络 | Repeat without any computer proxy or USB reverse tunnel; when convenient, unplug and repeat / 不用电脑代理或 USB 转发重试，方便时再拔线验收 |

**Selecting the chat model does not create the vision adapter.** The [configuration
guide](CONFIGURATION.md#models) explains how GAgent can generate
`memory/vision_api.py` using an existing image-capable provider, without copying
keys into chat. OCR works locally; optional YOLO is not a substitute for semantic
image understanding.

主模型保存成功不等于看图已配置。按指南让 GAgent 生成视觉适配器；不需要为开始使用先下载 YOLO。
微信坚持截图、OCR、可选检测与手势的纯 GUI 路径。遇登录、订单提交或付款按用户授权边界停下。

Record version/commit, package variant, Android/device, orientation and each result.
Mark a missing physical unplug or model/image check **untested**, rather than
inferring it from another check. Exclude keys and personal screenshots from issues.

## 5. Add capabilities when you need them / 按需扩展

[YOLO](OPTIONAL_YOLO.md) · [Self-ADB, browser and offscreen](CONFIGURATION.md) ·
[PC Link, voice and APK Factory](OFFICIAL_MODULES.md) · [Practical cases](CASES.md)

**Settings → Optional modules** configures clients for compatible services. It
does not deploy servers or supply shared keys. Model access uses a normal provider
configuration. Enable one module, verify its smallest useful action, then continue.

「设置 → 可选组件」用于连接兼容服务，不会自动部署服务端或发放共享密钥。
先跑通基础流程，再逐项扩展；开启步骤与核验入口见[功能清单](CONFIGURATION.md)。
