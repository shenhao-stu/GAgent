<div align="center">
  <img src="docs/assets/gagent-logo.png" width="128" height="128" alt="GAgent：开放的 G 循环与蓝色行动节点">
  <h1>GAgent</h1>
  <p><strong>让智能体住进你的手机。</strong></p>
  <p>Python 工具 · 视觉操作 · 记忆复用 · 自选模型</p>
  <p><a href="README.md">English</a> · <a href="#start">快速开始</a> · <a href="docs/CONFIGURATION.md">开启功能</a> · <a href="docs/README.md">开发文档</a></p>
  <p><a href="https://gaagent.ai/">官网</a> · <a href="https://app.gaagent.ai/">GA 手机版 APK</a> · <a href="https://github.com/lsdefine/GenericAgent">GenericAgent</a> · <a href="https://androidbench.gaagent.ai/">AndroidBench</a></p>
</div>

[Apache-2.0](LICENSE) · 视觉操作要求 Android 11+ · arm64-v8a · [最早 Android 记录：2026-06-13](docs/HISTORY.md)

GAgent 将 [GenericAgent](https://github.com/lsdefine/GenericAgent) 的执行循环带到 Android。
给出任务后，它观察屏幕、调用工具、验证结果，并可保留有用的操作方法。
Python、文件与记忆运行在手机上，推理由你配置的模型接口提供；日常使用不依赖电脑或 USB。

> **公开前的私有候选 · 2.33.3 / 136。** 公开时间由所有者决定。
> 要使用本仓库源码对应的版本，请获取**本仓库构建**。GA 手机版下载站属于另一分发渠道，
> [渠道说明及旧地址 apk.gaagent.ai](docs/ECOSYSTEM.md)列出了区别。

## 核心能力

| 观察 | 执行 | 复用 |
| --- | --- | --- |
| 截图、内置 OCR、可选 YOLO、已配置的视觉模型 | Python 工具和 Android 原生手势、文件、浏览器、设备适配 | 会话、本地记忆、可复用规程，以及可选的电脑与服务连接 |

主循环聚焦规划与执行；屏幕几何、权限、模型协议和远程服务各有明确边界。
[查看架构 →](docs/ARCHITECTURE.md)

<a id="cases"></a>
## 实操案例

先从能直接核验结果的小任务开始。下表来自已记录的开发验收；
[案例指南](docs/CASES.md)提供可复用指令、前置条件和检查方法。

| 任务 | 实际结果 | 证据 |
| --- | --- | --- |
| 调整系统亮度 | 读回亮度与模式，测试后恢复原设置 | [通过](docs/CASES.md#settings) |
| B 站搜索视频 | 核对“播放多”选中态及标题、UP；复杂组合筛选仍部分完成 | [通过 / 部分完成](docs/CASES.md#video-search) |
| 高德查询路线 | 读回时间和距离，未启动导航；利用了匹配的历史路线 | [通过，暖态](docs/CASES.md#route) |
| 微信麦当劳小程序 | 纯 GUI 选好套餐，停在手机号登录；未结算、下单或付款 | [部分完成 / 登录边界](docs/CASES.md#wechat) |

还可以尝试[本地文件与电脑协作示例](docs/CASES.md#recipes)。更多公开过程见
[AndroidBench 案例](https://androidbench.gaagent.ai/#traces) 与 [评测方法](https://androidbench.gaagent.ai/#method)。
各研究的设备、模型与协议独立记录，不作为所有 GAgent 版本的统一成绩。

<a id="start"></a>
## 快速开始

1. **安装：**使用 arm64-v8a、Android 11 / API 30+ 手机，从本仓库
   [Actions](https://github.com/shenhao-stu/GAgent/actions/workflows/android.yml) 或
   [Releases](https://github.com/shenhao-stu/GAgent/releases)获取核验后的 APK，或[自行构建](docs/BUILD.md)。
   私有制品需要仓库权限；Manifest 的 API 24 最低安装版本不等于完整截图支持。
2. **配置模型：**在「设置 → 服务商与模型」填写服务地址、自己的密钥与模型，选择匹配协议。
   分别验证文本、工具和图像能力，见[模型与视觉配置](docs/CONFIGURATION.md#models)。
3. **开启手机操作：**授予无障碍与悬浮窗权限；需要跨应用持续显示进度时开启「悬浮窗常开」。
   其他权限按工具需要授权。
4. **做一个小任务：**“打开设置，描述当前画面，不修改任何设置。”核对真实画面，并试用停止按钮。

正式版包名 `io.github.shenhaostu.gagent`，调试版为 `io.github.shenhaostu.gagent.debug`。
两者数据独立，均可与旧应用共存。保留现有数据；签名不匹配时先核对和安排迁移，不直接卸载。
[首次使用指南](docs/GETTING_STARTED.md) · [排障指南](docs/TROUBLESHOOTING.md)

<a id="capabilities"></a>
## 开启你需要的功能

| 能力 | 开启方式 |
| --- | --- |
| 对话、工具、记忆、本地文件 | 配置支持工具的模型；访问共享文件时授权 |
| 手机 GUI 与 OCR | 开启无障碍、悬浮窗；OCR 已内置 |
| 看图问答 | 为本地视觉适配器配置支持图像的服务商，用合成图片自测 |
| YOLO 图标检测 | 按模型许可安装兼容 ONNX，重启并验证实际检测，见[完整步骤](docs/OPTIONAL_YOLO.md) |
| 语音 / PC Link / GAnet / APK 构建 | 「设置 → 可选组件」，填写兼容服务地址和自己的限定权限凭据 |
| GA Plan | 作为普通模型服务商接入，填写自己的用户密钥 |
| 定时任务、通知、飞书、感知、无线 ADB、虚拟屏、Jev | 按[功能清单](docs/CONFIGURATION.md)逐项配置，前置条件与限制各不相同 |

没有统一的“全部解锁”开关。框架无需强制托管登录或购买套餐；可选客户端不等于服务端安装器，
交付给客户端的秘密也不能保证无法提取。
[完整配置指南](docs/CONFIGURATION.md) · [官方组件与权限边界](docs/OFFICIAL_MODULES.md)

<a id="roadmap-news"></a>
## Roadmap & News

最早可核验的 Android 实现日期为 **2026 年 6 月 13 日**：私有前身已包含 Python 智能体、
设备桥接与视觉管线，当日 README 记录了构建及真机检查。这是开发沿革，**不是公开开源日期**。

| 日期 · UTC+8 | 重要节点 |
| --- | --- |
| **2026-10-23** | 整理 Apache-2.0 私有开源候选；组件改为主动接入；微信纯 GUI、网络/浮窗/旋转修复与有限 Pixel 验收 |
| **2026-08-06 → 08-13** | PC Link/P2P 客户端与 GAnet 集成记录 |
| **2026-07-15 → 07-18** | 定时唤起任务与原生通知触发自动化 |
| **2026-06-27 → 07-03** | 本地修改保留、无线 ADB、内置浏览器控制与虚拟屏适配 |
| **2026-06-24** | 将旧检测器替换为 Android 专用 YOLOv8n，识别 21 类 UI 控件 |
| **2026-06-16** | 流式语音输入 |
| **2026-06-13** | Android 实现及当日构建、真机验证记录 |

[历史节点与源码依据](docs/HISTORY.md) · [变更记录](CHANGELOG.md)

后续重点：

- **发布准备：**迁移受支持的 Python/原生依赖，明确模型再分发权利，完善制品来源记录。
- **跨设备能力：**真实折叠/展开、更多厂商系统、16 KB 页大小与后台生命周期验收。
- **任务可靠性：**加强筛选/排序结果核验、可重复对照测试和限定权限的组件接入。

[路线图与验收条件 →](docs/ROADMAP.md)

## 开发、贡献与验证

[构建](docs/BUILD.md) · [架构](docs/ARCHITECTURE.md) · [开发](docs/DEVELOPMENT.md) · [测试](docs/TESTING.md) · [贡献](CONTRIBUTING.zh-CN.md) · [PR 要求](.github/PULL_REQUEST_TEMPLATE.md)

保持高内聚，明确变化的输入，用小而可测的函数维护不变量，隔离网络、文件与 Android 副作用。
能由适配层解决的问题优先不改变 GA 主循环，欢迎中英文贡献。

当前实机证据覆盖 **Pixel 10 / Android 16**。点击成功不等于任务完成，旋转测试不代表全部折叠屏或 OEM 均兼容。
详见[验收记录](docs/VALIDATION.md)和[依赖待办](docs/DEPENDENCY_SECURITY.md)。
任务文本、截图和工具结果可能发送给所选模型；生成代码使用你授予的能力执行，框架不是恶意代码沙箱。
[安全与数据流](SECURITY.md)。

## 许可证与来源

项目自有代码采用 [Apache-2.0](LICENSE)。GAgent 源自 **Liang Jiaqing 及贡献者**的
GenericAgent / GAndroid，署名保留于 [NOTICE](NOTICE)。[第三方库、模型和字体](THIRD_PARTY.md)沿用各自条款。
YOLO 权重可选安装、默认不捆绑。本仓库分发 Android，iOS 与 ESP32 开发仍独立维护。

[官网](https://gaagent.ai/) · [上游框架](https://github.com/lsdefine/GenericAgent) · [生态与下载渠道](docs/ECOSYSTEM.md) · [Logo](docs/assets/README.md)

旧 APK 地址：[apk.gaagent.ai](https://apk.gaagent.ai/)（2026-10-23 检查为 HTTP 404，当前下载站见上方入口）。
