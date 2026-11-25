<div align="center">
  <img src="docs/assets/gagent-logo.png" width="128" height="128" alt="GAgent：开放的 G 循环与蓝色行动节点">
  <h1>GAgent: 住进手机、持续进化的自主智能体</h1>
  <p><strong>看懂屏幕，调用工具，把成功经验留给下一次任务。</strong></p>
  <p>🧠 GenericAgent 内核 · 🤖 Android &amp; iOS 双端 · 👁️ 本地视觉 · 🖱️ ESP32-S3 蓝牙键鼠 · 🌐 跨设备协作</p>
  <p><a href="README.md">English</a> · <a href="#start">Android 快速开始</a> · <a href="#ios-start">iOS 快速开始</a> · <a href="docs/IOS_GETTING_STARTED.zh-CN.md">iOS 使用指南</a> · <a href="docs/CONFIGURATION.md">开启功能</a> · <a href="docs/README.md">开发文档</a></p>
  <p><a href="https://gaagent.ai/">官网</a> · <a href="https://app.gaagent.ai/">GA 手机版 APK</a> · <a href="https://github.com/lsdefine/GenericAgent">GenericAgent</a> · <a href="https://androidbench.gaagent.ai/">AndroidBench</a></p>
</div>

[Apache-2.0](LICENSE) · Android 11+ (`arm64-v8a`) &amp; iOS 17+ (`arm64` + ESP32-S3 BLE HID) · [隐私说明](PRIVACY.md) · [开发记录始于 2026-06-13](docs/HISTORY.md)

**GAgent 将 GenericAgent 极简、可自我进化的自主 Agent 设计同时带到 Android 与 iOS。**
给出目标，它可以观察屏幕、在本机编写并执行 Python、处理本地文件、通过 PC Link 连接电脑，再把经过验证的方法沉淀为可复用规程。智能体循环与工具运行在手机本地，模型接口由你自主配置。

<a id="start"></a>
## 🤖 Android：安装 → 配置 → 开始使用

**准备三样东西：arm64、Android 11+ 手机，网络，以及模型服务商的 API 地址、密钥和模型 ID。**
APK 已内置 Python 与手机工具。日常使用无需电脑、root、Shizuku、Docker 或另装 Python。

1. **📦 下载开源 APK。** 从最新[预发布版](https://github.com/shenhao-stu/GAgent/releases)下载
   **GAgent-release.apk** 与 `SHA256SUMS`（无需登录）并核对哈希。更新的构建在
   [Android 构建页](https://github.com/shenhao-stu/GAgent/actions/workflows/android.yml?query=branch%3Amain)
   （登录 GitHub，选 main 上全绿的记录，解压 **GAgent-android-…**）。
   [下载、校验与安装详解 →](docs/GETTING_STARTED.md#download)
2. **🔑 配置模型。**「设置 → 服务商与模型 → 添加服务商」，选择匹配协议，填写 API 地址、
   密钥和 **默认模型 ID**，保存即可；**不必先获取模型列表**。没有代理需求就留空。
3. **📱 开启手机操作。**「设置 → 无障碍权限」，在 Android 设置中启用 GAgent；
   开启「悬浮窗常开」并允许显示在其他应用上，便于跨 App 查看进度。
   [权限操作指南 →](docs/GETTING_STARTED.md#permissions)
4. **✅ 验收小任务。** 先发“请回复 OK”，再发“打开设置，不修改任何设置”。
   如需看图理解，先执行[视觉配置提示词](docs/CONFIGURATION.md#models)，再让它描述当前画面。
   文本、工具调用和视觉要分别验证。

**想让 Agent 帮你装好 Android 版？** 将下面一段交给 **GenericAgent / Codex / Claude Code**：

```text
请按照这份指南帮我安装、配置开源 GAgent：
https://github.com/shenhao-stu/GAgent/blob/main/docs/INSTALL_WITH_AGENT.md
先检查我的系统、现有工具和选定的 Android 手机，优先使用核验过的 APK，
只解决当前安装路径所需的环境依赖。保留现有应用和数据，不在聊天或日志中输出密钥，
引导我完成必须手动授予的系统权限。分别验收文本、无害工具操作和看图能力，
明确报告通过、失败与未测试项。
```

[📖 Android 完整安装指南](docs/GETTING_STARTED.md) · [🤖 Agent 安装指南](docs/INSTALL_WITH_AGENT.md) ·
[🔧 Android 源码构建](docs/BUILD.md) · [🩺 常见问题](docs/TROUBLESHOOTING.md)

<a id="ios-start"></a>
## 🍎 iOS（IOSAgent）：烧录固件 → 签名安装 → 配对校准 → 开始使用

由于 iOS 系统沙盒禁止普通 App 截取其他应用画面或注入全局触控，**GAgent iOS 版**从第一性原理出发，采用 **本机嵌入式 CPython 3.13 + Apple ReplayKit 屏幕广播按需取帧 + Apple Vision 本地 OCR + 纯 MIT 协议 ESP32-S3 蓝牙键鼠桥接板**（约 20–35 元人民币开发板，仅需充电头或充电宝供电，日常使用手机无需插线，零越狱、零私有 API）。

### 极简原子工具集（第一性原理裁剪）

GAgent iOS 版剔除所有冗余与不常用组件，仅保留 **9 个最小原子工具**：
- **6 个本机核心工具**：`code_run`（内置 CPython 3.13、`rubicon-objc` 与本机 UNIX shell 工具集）、`file_read`、`file_write`、`file_patch`、`ask_user`、`start_long_term_update`
- **3 个设备与跨端原语**：
  - `screen`：ReplayKit 按需取图 + Apple Vision 本地双语 OCR + Set-of-Mark 元素编号 + `frame_id` 画面新鲜度强校验
  - `hid`：经加密 BLE GATT 驱动 ESP32-S3 执行键鼠手势（`tap`、`double_tap`、`long_press`、`swipe`、`drag`、`type`、`key`、`scroll`、`button`、`stage_text`、`status`、`stop`）
  - `pc_link`：可选通过二维码或手动地址配对桌面端 GenericAgent Hub

### iOS 快速上手四步法

**准备工作：** 一台 **iOS 17+ 的 iPhone**（推荐 iOS 18+ 以获得最佳中英混合 OCR 效果；iOS 26+ 支持系统级切后台持续运行）、一台装有 **Xcode 16+** 与 `xcodegen`（`brew install xcodegen`）的 **Mac**、一块 **ESP32-S3 开发板**（推荐 N8R8，如 ESP32-S3-DevKitC-1），以及你自己的 **HTTPS 模型 API Key**。

1. **⚡ 烧录 ESP32-S3 蓝牙键鼠固件（仅首次需要）。** 安装 `arduino-cli`、`esp32:esp32`（3.3.x）核心及 `NimBLE-Arduino` 库，用数据线将 ESP32-S3 插到 Mac 的 USB/UART 口，执行：
   ```bash
   bash ios/firmware/flash.sh
   ```
   烧录完成后，ESP32-S3 只需插在任意 5V 充电器或充电宝上保持供电即可。
2. **📲 编译签名并安装到 iPhone。** 在 iPhone 上开启「开发者模式」并用 USB 连接 Mac，在 **Xcode → Settings → Accounts** 查看你的 Team ID，执行一键部署脚本：
   ```bash
   APPLE_TEAM_ID=你的TEAM_ID bash ios/deploy_device.sh
   ```
   > **免费个人 Apple ID（Personal Team）提示：** 免费个人开发者账号每周最多注册 3 个 App ID。若因灵动岛 Widget 扩展超出配额报错，可加上 `WITHOUT_WIDGETS=1` 构建精简签名包：`WITHOUT_WIDGETS=1 APPLE_TEAM_ID=你的TEAM_ID bash ios/deploy_device.sh`（免费证书约 7 天过期，过期后重跑同一命令即可原地重签，应用内对话与配置完整保留）。
3. **🔑 配置 HTTPS 模型服务商。** 打开 GAgent **「设置 → 服务商与模型 → 添加服务商」**，填写 `https://` 开头的 API 地址、API Key 和默认模型 ID（GUI 手机操作强烈推荐具备视觉能力的模型，如 GPT-4.1、Claude Sonnet、Gemini、Qwen-VL 等），点击保存，并在首次发送任务时确认该服务商的数据共享授权。若手机开启了本地代理/VPN，可在「设置 → 设备与连接」一键开启本机代理检测。
4. **🖱️ 完成「iPhone 操作」四步向导。** 打开 **「设置 → iPhone 操作」**，先开启顶部的 **「允许 GAgent 操作」**，再按顺序完成 4 张引导卡片：
   - **第 1 步 · 连接 ESP32：** 在页内扫描并点击 `ESP32 Agent XXXX`，自动完成加密 BLE 配对。
   - **第 2 步 · 启用无线键鼠：** 打开 **iPhone「系统设置 → 辅助功能 → 触控 → 辅助触控（AssistiveTouch）」并开启**（iOS 要求开启辅助触控后蓝牙鼠标才能点击屏幕），再在「系统设置 → 蓝牙」中配对 `ESP32 Agent XXXX`。
   - **第 3 步 · 屏幕共享：** 点击页内系统广播按钮开始共享当前 iPhone 屏幕（按需取帧，静止画面不额外耗电）。
   - **第 4 步 · 校准指针：** 保持 GAgent 在前台且不要触碰屏幕，点击 **「开始自动校准」**。应用会像 3D 打印机自动调平一样完成多点打点拟合与独立校验（误差 ≤ 1.5% 自动保存）。

### iOS 使用规范与安全准则（Guidelines）

- **灵动岛、锁屏实时活动与就地回答：** 任务切到其他 App 执行时，灵动岛与锁屏卡片会实时显示当前步骤；遇到 `ask_user` 提问时，可直接在通知或实时活动上点击选项或输入回答，无需频繁切回主界面。
- **敏感操作人工接管（Takeover）：** 凡涉及 **支付确认、密码输入、短信/2FA 验证码、Face ID 授权、系统权限弹窗或不可逆删除**，请务必点击灵动岛或界面上的「暂停/接管」，由本人亲自完成后再交回继续执行。
- **硬件级随时急停（Stop）：** 在 GAgent 内、灵动岛上点击「停止任务」，或在控制中心关闭屏幕广播，都会立即取消当前动作、作废旧 `frame_id` 截图证明，并向 ESP32-S3 发送带外 `release` 指令释放所有按键。
- **纯本地沙盒与 HTTPS 边界：** iOS 端 `mykey.py` 仅按静态字面量解析、绝不作为动态代码执行；模型请求强制校验证书的 HTTPS 且禁止重定向；`code_run` 与文件读写严格限制在沙盒 `temp/`、`memory/`、`uploads/` 目录内。

[📘 iOS 完整图文级上手指南](docs/IOS_GETTING_STARTED.zh-CN.md) · [🏗️ iOS 架构与工程说明](ios/README.md) · [🔒 隐私政策](PRIVACY.md)

---

> **开源预览。** Releases 中是预发布版，不是稳定渠道；CI 制品需登录 GitHub 下载，保留 14 天。
> 保留已有安装与数据：正式包 `io.github.shenhaostu.gagent`、调试包
> `io.github.shenhaostu.gagent.debug` 使用独立身份。
> [app.gaagent.ai](https://app.gaagent.ai/) 为独立的官方手机版渠道。
> [原生依赖迁移](docs/DEPENDENCY_SECURITY.md)与更多设备验收仍在推进。

底座源自 [GenericAgent 的 **约 3K 行种子内核**](https://github.com/lsdefine/GenericAgent)：
精简执行循环、少量工具原语与分层记忆。Android 与 iOS 能力围绕同一内核扩展。
[内核、记忆与统计口径 →](docs/CORE_AND_MEMORY.md)

## ✨ GAgent 把这些能力放到一起

| 能力 | 能做什么 |
| --- | --- |
| 🧠 **让记忆成为工具** | 小索引定位相关事实、规程与脚本，在 Android 与 iOS 上跨会话复用已验证的解决方法。 |
| 🍎 **iOS ReplayKit + ESP32-S3 蓝牙键鼠** | 本机 ReplayKit 按需截图 + Apple Vision 双语 OCR + 自动校准的蓝牙相对指针手势，零越狱、零私有 API、纯 MIT 固件。 |
| 👁️ **Android 本地 OCR + 可选 YOLOv8n** | 在 Android 手机上识别文字与 21 类 UI 控件；需要理解画面语义时再调用视觉模型。[YOLO 安装指南](docs/OPTIONAL_YOLO.md)。 |
| 📱 **Android Self-ADB，无需 Shizuku** | 通过手机自身的无线调试配对取得授权 shell 能力；普通 GUI 操作只需无障碍。 |
| 🪟 **Android App 离屏与网页后台操作** | 支持的 App 可放入虚拟屏，网页可运行在独立后台 WebView。 |
| 🔗 **PC Link 跨端协同** | 从 Android 或 iPhone 配对桌面 GenericAgent Hub，跨设备发起会话、切换模型、流式查看输出。 |
| 🎙️ **端侧离线语音输入** | 按住说话、松开转写、上滑取消：iOS 使用系统本地 `SFSpeechRecognizer`，Android 使用 `sherpa-onnx`。 |
| 🛠️ **APK 工厂（Android）** | 用自然语言描述小应用，生成工程并通过已配置的构建服务打包 APK。 |

**本地工具直接配置，可选服务主动接入。** PC Link 没有默认中继：填写你自建或获授权使用的中继，或点击需确认的 GenericAgent 公共中继预设并阅读说明，再扫码配对电脑。[完整开启步骤](docs/CONFIGURATION.md) · [组件与服务端边界](docs/OFFICIAL_MODULES.md)

## 🧠 小内核，长记忆，减少重复 Token

GAgent 与 GenericAgent **同源、沿用同一套内核架构**，在设备边界分别适配 Android 与 iOS：

**观察 → 执行 → 验证 → 沉淀有用方法 → 下次按需召回。**

- **按需读取：**极简索引指向事实、规程和脚本，不把整个记忆库塞进每一轮请求。
- **保留关键进度：**工作检查点、短摘要和上下文裁剪减少重复历史，保持当前任务信息可用。
- **在使用中生长：**验证过的规程和本地 Python 工具可以被下一次任务复用；学习材料仍需审阅，失败尝试不自动成为事实。

[实现与测量口径](docs/CORE_AND_MEMORY.md)

## 🧪 可以这样用

| 试着说 | 条件 / 已有记录 |
| --- | --- |
| “在 B 站搜索指定主题，按播放多排序，列出标题与 UP 主。” | 保留简单排序通过及后续魅族超时记录；日期与时长组合筛选仍部分完成。 |
| “查一下驾车时间和距离，不启动导航。” | 高德路线读回通过，当时存在匹配的历史路线。 |
| “纯 GUI 浏览微信麦当劳小程序，到提交订单前停止，遇登录也停下。” | 完成选餐，停在手机号登录；未确认加购、结算或付款。 |
| “在我的 iPhone 上打开系统设置，查看当前 Wi-Fi 与蓝牙状态，不修改任何开关。” | 验收 iOS ReplayKit 读屏 + ESP32-S3 自动校准点击与返回。 |
| “读取已配对电脑的测试目录，总结文件名。” | 示例配方：配置 PC Link 和授权对端，先做只读任务。 |

详见[案例与证据](docs/CASES.md)、[iOS 上手指南](docs/IOS_GETTING_STARTED.zh-CN.md)及 [AndroidBench](https://androidbench.gaagent.ai/)。

## 🗺️ Roadmap & News

| 日期 · UTC+8 | 重要节点 |
| --- | --- |
| **2026-11-25** | 正式开源 **IOSAgent**（`ios/`）：ReplayKit + Apple Vision 本地 OCR、纯 MIT 协议 ESP32-S3 BLE HID 固件、一键自动指针校准、灵动岛/锁屏实时活动状态界面，并合并 `main` 最新修复 |
| **2026-10-23** | Apache-2.0 Android 源码预览；组件主动接入、微信纯 GUI、网络/浮窗/几何修复与公开配置指南 |
| **2026-08-06 → 08-13** | PC Link/P2P 客户端与 GAnet 集成记录 |
| **2026-07-15 → 07-18** | 定时任务与原生通知触发 |
| **2026-06-27 → 07-03** | 本地修改保留、self-ADB、浏览器控制与虚拟屏适配 |
| **2026-06-24** | 换用 Android 专用 YOLOv8n，识别 21 类 UI 控件 |
| **2026-06-16** | 流式语音输入 |
| **2026-06-13** | 最早可核验的 Android 实现及当日构建、真机验证记录 |

[历史与提交依据](docs/HISTORY.md) · [变更记录](CHANGELOG.md) · [路线图](docs/ROADMAP.md)

## 🤝 一起建设

[Android 构建](docs/BUILD.md) · [iOS 构建与架构](ios/README.md) · [架构](docs/ARCHITECTURE.md) · [开发](docs/DEVELOPMENT.md) · [测试](docs/TESTING.md) · [贡献](CONTRIBUTING.zh-CN.md) · [PR 清单](.github/PULL_REQUEST_TEMPLATE.md)

保持内核精简，明确可变输入，用可测函数维护不变量，隔离设备与网络副作用；欢迎中英文贡献。[安全说明](SECURITY.md) · [隐私政策](PRIVACY.md)

## 📄 许可证与来源

项目自有代码采用 [Apache-2.0](LICENSE)。源自 **Liang Jiaqing 及贡献者**的 GenericAgent / GAndroid；iOS `BoardKit` 与 ESP32-S3 蓝牙键鼠固件（`ios/BoardKit/`、`ios/firmware/`）衍生自 **Henry Yuan** 的 [ESP32 iPhone Agent](https://github.com/onehumanbeing/esp32-iphone-agent)（MIT 许可证）。
署名保留于 [NOTICE](NOTICE)、[ios/BoardKit/NOTICE](ios/BoardKit/NOTICE) 与 [ios/firmware/NOTICE](ios/firmware/NOTICE)。[第三方库、字体与模型](THIRD_PARTY.md)沿用各自条款。仓库不含任何 GPL AirPlay 组件与 YOLO 检测权重。

[官网](https://gaagent.ai/) · [GA 手机版](https://app.gaagent.ai/) · [GenericAgent](https://github.com/lsdefine/GenericAgent) · [AndroidBench](https://androidbench.gaagent.ai/) · [Logo](docs/assets/README.md)
