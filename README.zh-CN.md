# GAgent

**运行在 Android 手机上的 Python 智能体框架，连接原生设备工具和你选择的模型服务。**

[English](README.md) · [开始使用](docs/GETTING_STARTED.md) · [文档导航](docs/README.md) · [参与贡献](CONTRIBUTING.zh-CN.md)

GAgent 将一个请求推进为“观察、调用工具、验证结果”的循环。Python 运行时、会话、文件和记忆保存在手机上；模型推理由你配置的接口提供，截图和必要的工具结果可能发送给该服务。日常手机操作不需要电脑或 USB 连接。

> **项目状态：**公开前的私有候选，Android 基线为 2.33.3 / 136。
> 已验证范围见[验收记录](docs/VALIDATION.md)，尚未解决的原生依赖问题见
> [依赖安全](docs/DEPENDENCY_SECURITY.md)。仓库可见性和公开时间由所有者决定。

## 可以用它做什么

| 能力 | 实现方式 |
| --- | --- |
| 操作手机 | 观察当前画面、定位目标、执行动作、核验结果。普通应用可使用无障碍工具；微信使用截图、OCR、可选视觉检测与手势，不读取其节点树。 |
| 本地工具与记忆 | 运行 Python 工具、处理文件、保存会话状态和复用设备上的操作说明。 |
| 选择模型 | 自行配置服务地址、密钥与模型。现有适配器支持多种协议；服务商支持时可使用原生工具调用。 |
| 视觉定位 | 默认包含 PaddleOCR；兼容 YOLO 权重可由用户按适用许可自行安装。 |
| 可选连接 | 在兼容服务已部署的前提下，接入 PC Link/P2P、GAnet、流式语音或 APK 构建服务。 |

框架不要求购买套餐或登录托管账号。GA Plan 可以作为普通模型服务商接入。
本仓库不包含这些组件的完整服务端、生产凭据或商业支付流程，边界详见
[功能去留清单](docs/FEATURE_SCOPE.md)和[官方组件方案](docs/OFFICIAL_MODULES.md)。

## 在手机上开始

1. 截图与手势工作流请使用 **Android 11 / API 30 及以上的 arm64-v8a 手机**。
   Manifest 的最低安装版本为 API 24，但这不表示旧版本支持完整截图能力。
2. [自行构建 APK](docs/BUILD.md)，或从本仓库
   [Actions](https://github.com/shenhao-stu/GAgent/actions/workflows/android.yml)、
   [Releases](https://github.com/shenhao-stu/GAgent/releases)获取已提供并核验的制品。
   私有制品需要仓库访问权限。
3. 在「设置 → 服务商与模型」填写自己的接口、凭据和模型，分别检查文本、工具调用和图像能力。
4. 手机操作需要无障碍与悬浮窗权限；麦克风、文件等能力按实际使用需要授权。
5. 先试一个小任务，例如“打开设置，描述当前画面，不修改任何设置”，确认结果后再尝试长任务。

[首次使用指南](docs/GETTING_STARTED.md)说明安装身份、权限和模型配置；
接口超时或浮窗消失时，先看[排障指南](docs/TROUBLESHOOTING.md)。

| 构建类型 | 应用 ID |
| --- | --- |
| Release | `io.github.shenhaostu.gagent` |
| Debug | `io.github.shenhaostu.gagent.debug` |

两个类型有独立数据目录，也能与旧应用共存。密钥、账号和会话不会静默迁移。
本地签名包不一定能覆盖维护者签名的安装包，不要通过清除数据解决签名不匹配。

## 使用边界

- **本地运行不等于离线推理。** 凭据保存在应用私有存储，调用时用于向所选服务认证；
  任务文本、图片和工具输出可能随请求发送。
- **框架不是沙箱。** 生成的 Python 和设备动作可以在已授予权限内影响真实文件、应用和账号。
- **支持范围以证据为准。** 当前实机验收覆盖 Pixel 10 / Android 16。
  旋转与边界检查不能代替所有折叠屏、厂商系统、外接屏及 16 KB 页大小设备的验收。
- **完成任务需要结果证据。** 接口成功或点击被系统接受，不代表排序、购买流程等多步任务已经完成。
- **可选模型有独立条款。** 默认不捆绑或自动下载 YOLO，见[安装与许可](docs/OPTIONAL_YOLO.md)。

本分发停用了自动托管遥测和提问收集。[安全说明](SECURITY.md)列出了数据流、报告方式与信任边界。

## 开发与贡献

设计原则是把变化集中在明确边界，将不变量落实为小而可测的函数。
能在设备或服务适配层解决的问题，优先不改变智能体主循环。

| 目标 | 入口 |
| --- | --- |
| 构建、签名 Android 包 | [构建指南](docs/BUILD.md) |
| 理解运行过程和扩展位置 | [架构](docs/ARCHITECTURE.md)、[开发指南](docs/DEVELOPMENT.md) |
| 修复问题并选择验证范围 | [测试指南](docs/TESTING.md) |
| 提建议、提交 PR | [贡献指南](CONTRIBUTING.zh-CN.md) |
| 核对证据、准备发布 | [验收记录](docs/VALIDATION.md)、[发布指南](docs/RELEASING.md) |
| 了解当前优先事项 | [路线图](docs/ROADMAP.md) |

欢迎中英文贡献。一个 PR 聚焦一个行为变化，提供可复现证据，并保留第三方署名。
[PR 模板](.github/PULL_REQUEST_TEMPLATE.md)列出了必要审查信息。

## 许可证与来源

项目自有代码采用 [Apache-2.0](LICENSE)。GAgent 源自 **Liang Jiaqing 及贡献者**
的 GenericAgent / GAndroid，原作者署名保留于 [NOTICE](NOTICE)。

第三方库、模型和字体沿用各自许可，见 [THIRD_PARTY.md](THIRD_PARTY.md)。
项目许可证不授予私有服务凭据、服务商标或独立模型权重的权利。
本仓库分发 Android 工程；iOS 与 ESP32 开发仍独立维护。
