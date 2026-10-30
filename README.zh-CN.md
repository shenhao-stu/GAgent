<div align="center">
  <img src="docs/assets/gagent-logo.png" width="128" height="128" alt="GAgent：开放的 G 循环与蓝色行动节点">
  <h1>GAgent: 住进手机、持续进化的自主智能体</h1>
  <p><strong>看懂屏幕，调用工具，把成功经验留给下一次任务。</strong></p>
  <p>🧠 GenericAgent 内核 · 👁️ 本地视觉 · 📱 Self-ADB · 🌐 跨设备协作</p>
  <p><a href="README.md">English</a> · <a href="#start">快速开始</a> · <a href="docs/CONFIGURATION.md">开启功能</a> · <a href="docs/README.md">开发文档</a></p>
  <p><a href="https://gaagent.ai/">官网</a> · <a href="https://app.gaagent.ai/">GA 手机版 APK</a> · <a href="https://github.com/lsdefine/GenericAgent">GenericAgent</a> · <a href="https://androidbench.gaagent.ai/">AndroidBench</a></p>
</div>

[Apache-2.0](LICENSE) · 视觉操作要求 Android 11+ · arm64-v8a · [Android 开发记录始于 2026-06-13](docs/HISTORY.md)

**GAgent 将 GenericAgent 极简、可自我进化的自主 Agent 设计带到 Android。**
给出目标，它可以观察屏幕、编写并执行 Python、处理文件和网页、连接电脑，
再把经过验证的方法沉淀为可复用规程。智能体与工具运行在手机上，模型接口由你选择；日常使用无需电脑或 USB。

<a id="start"></a>
## 🚀 安装 → 配置 → 开始使用

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

**想让 Agent 帮你装好？** 将下面一段交给 **GenericAgent / Codex / Claude Code**：

```text
请按照这份指南帮我安装、配置开源 GAgent：
https://github.com/shenhao-stu/GAgent/blob/main/docs/INSTALL_WITH_AGENT.md
先检查我的系统、现有工具和选定的 Android 手机，优先使用核验过的 APK，
只解决当前安装路径所需的环境依赖。保留现有应用和数据，不在聊天或日志中输出密钥，
引导我完成必须手动授予的系统权限。分别验收文本、无害工具操作和看图能力，
明确报告通过、失败与未测试项。
```

[📖 完整安装指南](docs/GETTING_STARTED.md) · [🤖 Agent 安装指南](docs/INSTALL_WITH_AGENT.md) ·
[🔧 源码构建](docs/BUILD.md) · [🩺 常见问题](docs/TROUBLESHOOTING.md)

> **开源预览。** Releases 中是预发布版，不是稳定渠道；CI 制品需登录 GitHub 下载，保留 14 天。
> 保留已有安装与数据：正式包 `io.github.shenhaostu.gagent`、调试包
> `io.github.shenhaostu.gagent.debug` 使用独立身份。
> [app.gaagent.ai](https://app.gaagent.ai/) 为独立的官方手机版渠道。
> [原生依赖迁移](docs/DEPENDENCY_SECURITY.md)与更多设备验收仍在推进。

底座源自 [GenericAgent 的 **约 3K 行种子内核**](https://github.com/lsdefine/GenericAgent)：
精简执行循环、少量工具原语与分层记忆。Android 能力围绕内核扩展。
这个数字描述上游种子内核，**不包含整个 APK、Android 设备层和 WebUI**。
[内核、记忆与统计口径 →](docs/CORE_AND_MEMORY.md)

## ✨ GAgent 把这些能力放到一起

| 能力 | 能做什么 |
| --- | --- |
| 🧠 **让记忆成为工具** | 小索引定位相关事实、规程与脚本，跨会话复用已经验证的解决方法。 |
| 👁️ **本地 OCR + YOLOv8n** | 在手机上识别文字与 21 类 Android UI 控件；需要理解画面语义时再调用已配置的视觉模型。本机构建的 APK 默认内置该检测器；仓库与 CI 构建按[安装指南](docs/OPTIONAL_YOLO.md)单独安装。 |
| 📱 **Self-ADB，无需额外 Shizuku App** | 通过手机自身的无线调试配对，取得用户授权的 shell 能力。普通 GUI 操作只需无障碍；高级调试权限按需开启。 |
| 🪟 **App 离屏与网页后台操作** | 支持的 App 可放入虚拟屏，网页可运行在独立后台 WebView。App 虚拟屏需要 self-ADB，并按设备验收。 |
| 🌐 **可保留登录态的内置浏览器** | 你先完成登录，任务浏览器复用已保存的 Cookie。基于 Android WebView，无需另装桌面浏览器内核。 |
| 🔗 **PC Link / P2P / GAnet** | 从手机连接已配对电脑和授权节点，组合跨设备工作流；需兼容的对端软件、服务及自己的凭据。 |
| 🎙️ **Step Voice 流式语音输入** | 说出任务，核对转写后发送。通过配置的兼容 WSS 服务接入 Step ASR 流式路径。 |
| 🛠️ **APK 工厂：做出你想要的 App** | 用自然语言描述小应用，生成工程，再通过已配置的构建服务提交、查询和下载 APK；仓库保留模板与客户端。 |

**本地工具直接配置，可选服务主动接入。** PC Link 没有默认中继：填写你自建或获授权使用的中继，或点击需确认的 GenericAgent 公共中继预设并阅读说明，再扫码配对电脑。语音和 APK 工厂不附带服务凭据或构建节点。[完整开启步骤](docs/CONFIGURATION.md) · [组件与服务端边界](docs/OFFICIAL_MODULES.md)

## 🧠 小内核，长记忆，减少重复 Token

GAgent 与 GenericAgent **同源、沿用同一套内核架构**，在设备边界适配 Android：

**观察 → 执行 → 验证 → 沉淀有用方法 → 下次按需召回。**

- **按需读取：**极简索引指向事实、规程和脚本，不把整个记忆库塞进每一轮请求。
- **保留关键进度：**工作检查点、短摘要和上下文裁剪减少重复历史，保持当前任务信息可用。
- **在使用中生长：**验证过的规程和本地 Python 工具可以被下一次任务复用；学习材料仍需审阅，失败尝试不自动成为事实。

Token 效率来自这些具体机制。实际消耗取决于模型、任务、截图与重试，
可以按自己的任务记录这些输入，评估实际开销。
[实现与测量口径](docs/CORE_AND_MEMORY.md)

## 🧪 可以这样用

| 试着说 | 条件 / 已有记录 |
| --- | --- |
| “在 B 站搜索指定主题，按播放多排序，列出标题与 UP 主。” | 保留简单排序通过及后续魅族超时记录；日期与时长组合筛选仍部分完成。 |
| “查一下驾车时间和距离，不启动导航。” | 高德路线读回通过，当时存在匹配的历史路线。 |
| “纯 GUI 浏览微信麦当劳小程序，到提交订单前停止，遇登录也停下。” | 完成选餐，停在手机号登录；未确认加购、结算或付款。 |
| “在后台浏览我已登录的网站，把结果保存成摘要。” | 示例配方：先在内置浏览器登录，核验会话复用与实际文件。 |
| “读取已配对电脑的测试目录，总结文件名。” | 示例配方：配置 PC Link 和授权对端，先做只读任务。 |
| “帮我做一个学习计时器 App，带任务清单和本地历史。” | 示例配方：生成并审阅工程，接入 APK 工厂，再实测返回的安装包。 |

示例配方不计入实测成绩。详见[案例与证据](docs/CASES.md)及 [AndroidBench](https://androidbench.gaagent.ai/)。
[实机验收记录](docs/VALIDATION.md)覆盖 Pixel 10 和魅族 21 / Android 16，包含失败与阻塞结果；
折叠屏和其他 OEM 仍需各自验收。

## 🗺️ Roadmap & News

| 日期 · UTC+8 | 重要节点 |
| --- | --- |
| **2026-10-23** | Apache-2.0 源码预览；组件主动接入、微信纯 GUI、网络/浮窗/几何修复与公开配置指南 |
| **2026-08-06 → 08-13** | PC Link/P2P 客户端与 GAnet 集成记录 |
| **2026-07-15 → 07-18** | 定时任务与原生通知触发 |
| **2026-06-27 → 07-03** | 本地修改保留、self-ADB、浏览器控制与虚拟屏适配 |
| **2026-06-24** | 换用 Android 专用 YOLOv8n，识别 21 类 UI 控件 |
| **2026-06-16** | 流式语音输入 |
| **2026-06-13** | 最早可核验的 Android 实现及当日构建、真机验证记录 |

六月记录来自私有前身，不是公开开源日期。[历史与提交依据](docs/HISTORY.md) · [变更记录](CHANGELOG.md)

接下来：🔧 受支持的原生依赖 · 📐 真实折叠/展开与更多 OEM · 🎯 筛选/排序正确性 · 🔌 更便捷的限定权限组件接入。
[路线图与验收条件](docs/ROADMAP.md)

## 🤝 一起建设

[构建](docs/BUILD.md) · [架构](docs/ARCHITECTURE.md) · [开发](docs/DEVELOPMENT.md) · [测试](docs/TESTING.md) · [贡献](CONTRIBUTING.zh-CN.md) · [PR 清单](.github/PULL_REQUEST_TEMPLATE.md)

保持内核精简，明确可变输入，用可测函数维护不变量，隔离设备与网络副作用；欢迎中英文贡献。
模型请求可能包含任务、截图和工具结果，生成代码使用你授予的能力执行。[安全与数据流](SECURITY.md)

## 📄 许可证与来源

项目自有代码采用 [Apache-2.0](LICENSE)。源自 **Liang Jiaqing 及贡献者**的 GenericAgent / GAndroid，
署名保留于 [NOTICE](NOTICE)。[第三方库、字体与模型](THIRD_PARTY.md)沿用各自条款。
YOLO 权重按 .gitignore 规则不进仓库：本机构建的 APK 默认内置，仓库与 CI 构建按指南单独安装（许可说明见指南）。iOS 与 ESP32 开发独立维护。

[官网](https://gaagent.ai/) · [GA 手机版](https://app.gaagent.ai/) · [GenericAgent](https://github.com/lsdefine/GenericAgent) · [AndroidBench](https://androidbench.gaagent.ai/) · [Logo](docs/assets/README.md)

设置中的「本地图标识别」可导入并验证用户提供的兼容 ONNX 模型，无需模型 API Key，并可检测实际屏幕。可选检测权重仍需单独提供，见[开启指南](docs/OPTIONAL_YOLO.md)。
