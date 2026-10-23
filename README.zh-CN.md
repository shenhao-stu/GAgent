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

底座源自 [GenericAgent 的 **约 3K 行种子内核**](https://github.com/lsdefine/GenericAgent)：
精简执行循环、少量工具原语与分层记忆。Android 能力围绕内核扩展。
这个数字描述上游种子内核，**不包含整个 APK、Android 设备层和 WebUI**。
[内核、记忆与统计口径 →](docs/CORE_AND_MEMORY.md)

> **开源预览 · 2.33.3 / 136。** 测试本仓库源码请使用[本仓库 Actions 构建](https://github.com/shenhao-stu/GAgent/actions/workflows/android.yml)。
> [app.gaagent.ai](https://app.gaagent.ai/) 是独立的官方手机版分发渠道。
> [原生依赖迁移](docs/DEPENDENCY_SECURITY.md)与更广泛的设备验收仍是稳定 APK 发布前的待办。

## ✨ GAgent 把这些能力放到一起

| 能力 | 能做什么 |
| --- | --- |
| 🧠 **让记忆成为工具** | 小索引定位相关事实、规程与脚本，跨会话复用已经验证的解决方法。 |
| 👁️ **本地 OCR + 可选 YOLOv8n** | 在手机上识别文字与 21 类 Android UI 控件；需要理解画面语义时再调用已配置的视觉模型。[YOLO 安装指南](docs/OPTIONAL_YOLO.md)。 |
| 📱 **Self-ADB，无需额外 Shizuku App** | 通过手机自身的无线调试配对，取得用户授权的 shell 能力。普通 GUI 操作只需无障碍；高级调试权限按需开启。 |
| 🪟 **App 离屏与网页后台操作** | 支持的 App 可放入虚拟屏，网页可运行在独立后台 WebView。App 虚拟屏需要 self-ADB，并按设备验收。 |
| 🌐 **可保留登录态的内置浏览器** | 你先完成登录，任务浏览器复用已保存的 Cookie。基于 Android WebView，无需另装桌面浏览器内核。 |
| 🔗 **PC Link / P2P / GAnet** | 从手机连接已配对电脑和授权节点，组合跨设备工作流；需兼容的对端软件、服务及自己的凭据。 |
| 🎙️ **Step Voice 流式语音输入** | 说出任务，核对转写后发送。通过配置的兼容 WSS 服务接入 Step ASR 流式路径。 |
| 🛠️ **APK 工厂：做出你想要的 App** | 用自然语言描述小应用，生成工程，再通过已配置的构建服务提交、查询和下载 APK；仓库保留模板与客户端。 |

**本地工具直接配置，可选服务主动接入。** PC Link、语音和 APK 工厂不附带服务端密钥、
构建工作节点或自动注册权限。[完整开启步骤](docs/CONFIGURATION.md) · [组件与服务端边界](docs/OFFICIAL_MODULES.md)

## 🧠 小内核，长记忆，减少重复 Token

GAgent 与 GenericAgent **同源、沿用同一套内核架构**，在设备边界适配 Android：

**观察 → 执行 → 验证 → 沉淀有用方法 → 下次按需召回。**

- **按需读取：**极简索引指向事实、规程和脚本，不把整个记忆库塞进每一轮请求。
- **保留关键进度：**工作检查点、短摘要和上下文裁剪减少重复历史，保持当前任务信息可用。
- **在使用中生长：**验证过的规程和本地 Python 工具可以被下一次任务复用；学习材料仍需审阅，失败尝试不自动成为事实。

Token 效率来自这些具体机制。实际消耗取决于模型、任务、截图与重试，
不承诺固定节省倍数，也不把其他环境的成绩当作安卓对比结果。
[实现与测量口径](docs/CORE_AND_MEMORY.md)

## 🆚 与 DeepSeek 安卓移植的设计差异

“DeepSeek Harness 安卓版”包含多个**社区实现**。下面按 **2026-10-23** 核对的两个具体项目对照，
不把它们合称为一个官方 Android 产品。

| 设计维度 | GAgent | DeepSeek 安卓实现举例 |
| --- | --- | --- |
| 智能体底座 | GenericAgent；内嵌 Python 与原生设备适配 | dsh/Node.js；[dphmoblie](https://github.com/dphmoblie/deepseek-harness-android) 使用 Ubuntu/PRoot，[Soodok](https://github.com/Soodok/Deepseek-Harness-Local-Android) 使用原生 bionic |
| 高级设备 shell | 内置 self-ADB 配对，不依赖额外 Shizuku App | 两个被比较项目均提供可选 Shizuku 接入 |
| 屏幕理解 | OCR + 可选 Android YOLO + 视觉模型；微信固定走纯视觉 | Soodok 也记录了 OCR/图标识别回退，视觉操作并非 GAgent 独有 |
| 后台任务 | 共享 Cookie 的 WebView 与 self-ADB 虚拟屏适配 | dphmoblie 也有经 Shizuku 驱动的实验性虚拟屏 |

GAgent 的重点是 **小型 Python 内核、可复用记忆、本地感知、跨设备与应用构建工作流的组合**。
这是架构对照，没有用不同设备的数据证明速度、内存或成功率领先。
[固定版本来源与能力细节 →](docs/COMPARISON.md)

<a id="start"></a>
## 🚀 从一个有用的小任务开始

1. **安装：**使用 arm64-v8a、Android 11 / API 30+ 手机，获取核验后的
   [本仓库构建](https://github.com/shenhao-stu/GAgent/actions/workflows/android.yml)，或[自行构建](docs/BUILD.md)。
   Manifest 的 API 24 最低安装版本不等于完整截图支持。
2. **配置模型：**「设置 → 服务商与模型」，填写自己的接口、密钥、模型及匹配协议。
   分别验证文本、工具调用和看图能力。
3. **开启手机操作：**授予无障碍与悬浮窗权限；需要跨 App 看进度时开启「悬浮窗常开」。
4. **试一试：**“打开设置，描述当前画面，不修改任何设置。”核对观察结果，并试用停止按钮。

正式版：`io.github.shenhaostu.gagent`；调试版：`io.github.shenhaostu.gagent.debug`。
两者可与旧应用共存，数据独立。保留现有安装，升级前先核对签名差异。
[首次使用](docs/GETTING_STARTED.md) · [模型、视觉与所有可选功能](docs/CONFIGURATION.md)

## 🧪 可以这样用

| 试着说 | 条件 / 已有记录 |
| --- | --- |
| “在 B 站搜索指定主题，按播放多排序，列出标题与 UP 主。” | 既有简单排序任务通过；日期与时长组合筛选仍部分完成。 |
| “查一下驾车时间和距离，不启动导航。” | 高德路线读回通过，当时存在匹配的历史路线。 |
| “纯 GUI 浏览微信麦当劳小程序，到提交订单前停止，遇登录也停下。” | 完成选餐，停在手机号登录；未确认加购、结算或付款。 |
| “在后台浏览我已登录的网站，把结果保存成摘要。” | 示例配方：先在内置浏览器登录，核验会话复用与实际文件。 |
| “读取已配对电脑的测试目录，总结文件名。” | 示例配方：配置 PC Link 和授权对端，先做只读任务。 |
| “帮我做一个学习计时器 App，带任务清单和本地历史。” | 示例配方：生成并审阅工程，接入 APK 工厂，再实测返回的安装包。 |

示例配方不计入实测成绩。详见[案例与证据](docs/CASES.md)及 [AndroidBench](https://androidbench.gaagent.ai/)。
当前实机证据覆盖 Pixel 10 / Android 16，折叠屏和其他 OEM 仍需各自验收。

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
YOLO 权重可选安装、默认不捆绑；iOS 与 ESP32 开发独立维护。

[官网](https://gaagent.ai/) · [GA 手机版](https://app.gaagent.ai/) · [GenericAgent](https://github.com/lsdefine/GenericAgent) · [AndroidBench](https://androidbench.gaagent.ai/) · [Logo](docs/assets/README.md)
