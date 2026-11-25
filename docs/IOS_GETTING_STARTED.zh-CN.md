# GAgent iOS 版（IOSAgent）完整上手指南与使用规范

[English](IOS_GETTING_STARTED.md) · [iOS 架构说明](../ios/README.md) · [隐私政策](../PRIVACY.md)

本文档面向 iOS 用户与开发者，详细说明如何从零完成 **ESP32-S3 蓝牙键鼠固件烧录、Xcode 真机签名安装、HTTPS 模型配置、四步手机控制向导与一键指针校准**，以及日常使用中的安全接管规范。

---

## 1. 硬件与环境准备

| 项目 | 要求与建议 |
| --- | --- |
| **iPhone** | 系统版本 **iOS 17.0+**（推荐 **iOS 18+**，中文与中英混排 Vision OCR 识别率显著更佳；**iOS 26+** 支持切到其他 App 后的系统级持续运行） |
| **Mac 电脑** | macOS 14+（Apple Silicon 或 Intel），已安装 **Xcode 16+** 及命令行工具 |
| **ESP32-S3 开发板** | 任意带原生 USB（TinyUSB）且具备 8MB Flash / OPI PSRAM 的 **ESP32-S3** 开发板（如 **ESP32-S3-DevKitC-1 N8R8**，常见售价约 ¥20–¥35）。*注：不支持无原生 USB HID 的老款 ESP32 或 ESP32-C3* |
| **ESP32 供电** | 日常使用时插在任意 5V 手机充电头、桌面排插 USB 口或充电宝即可，**iPhone 全程无线连接，无需插任何数据线** |
| **Apple 账号** | 付费 Apple Developer 账号（支持完整灵动岛实时活动 + 1 年有效证书）**或** 免费个人 Apple ID（支持 `WITHOUT_WIDGETS=1` 模式，每 7 天重签一次，数据保留） |
| **模型 API Key** | 支持 OpenAI Chat Completions（`/v1/chat/completions`）、OpenAI Responses（`/v1/responses`）或 Anthropic Messages（`/v1/messages`）协议的 **HTTPS** 接口；手机 GUI 操作强烈推荐使用带**视觉看图能力**的模型 |

---

## 2. 第一步：烧录 ESP32-S3 蓝牙键鼠固件（仅首次需要）

仓库 [`ios/firmware/hid_bridge/`](../ios/firmware/hid_bridge/) 提供纯 MIT 协议的精简蓝牙/USB 键鼠桥接固件，零 Wi-Fi 热点、零 GPL 组件，烧录一次即可长期使用。

1. **在 Mac 上安装编译工具链与 `xcodegen`：**
   ```bash
   brew install arduino-cli xcodegen
   ```
2. **安装 ESP32 3.3.x 板级支持包与 `NimBLE-Arduino` 蓝牙库：**
   ```bash
   arduino-cli core update-index
   arduino-cli core install esp32:esp32@3.3.0
   arduino-cli lib install "NimBLE-Arduino"
   ```
   *（任意 `esp32:esp32` 3.3.x 版本均可兼容。）*
3. **用带数据传输功能的 USB-C 线将 ESP32-S3 连接到 Mac**（若开发板上有 `USB` 和 `UART` 两个口，推荐插 `USB` 口），在仓库根目录执行：
   ```bash
   bash ios/firmware/flash.sh
   ```
   - 仅验证编译不烧录：`bash ios/firmware/flash.sh --build-only`
   - 若电脑连接了多个串口设备，可显式指定端口：`bash ios/firmware/flash.sh /dev/cu.usbmodemXXXX`

看到上传完成提示后，即可将 ESP32-S3 拔下并插到手机附近的充电头或充电宝上保持通电。

---

## 3. 第二步：在 iPhone 上编译、签名并安装 GAgent

1. **开启 iPhone 开发者模式：**
   - 用数据线将 iPhone 连接 Mac 并解锁（首次连接点击「信任此电脑」）。
   - 打开 **iPhone「设置 → 隐私与安全性 → 开发者模式」**，开启开关并按提示重启手机确认。
2. **登录 Xcode 并查看你的 Team ID：**
   - 打开 **Xcode → Settings → Accounts**，登录你的 Apple ID。
   - 付费开发者团队可直接看到 10 位 **Team ID**；若使用免费个人账号未直接显示，可在终端运行：
     ```bash
     security find-identity -v -p codesigning
     ```
     输出中 `"Apple Development: ... (XXXXXXXXXX)"` 括号内的 10 位字符即为 `APPLE_TEAM_ID`。
3. **在仓库根目录运行一键真机部署脚本：**
   ```bash
   APPLE_TEAM_ID=你的10位TEAM_ID bash ios/deploy_device.sh
   ```
   该脚本首次运行会自动拉取 BeeWare Python 3.13 框架与内置 UNIX shell 组件到 `ios/Vendor/` 与 `ios/Resources/`，自动暂存签名引擎、生成工程、签名编译并安装拉起 GAgent。

   > **💡 免费个人 Apple ID（Personal Team）必读：**
   > Apple 限制免费个人账号每周最多注册 **3 个 App ID**。完整版包含主应用、ReplayKit 广播扩展、灵动岛组件共 3 个 Target；若免费账号已占用名额导致签名报错，请加上 `WITHOUT_WIDGETS=1` 跳过灵动岛 Widget 扩展：
   > ```bash
   > WITHOUT_WIDGETS=1 APPLE_TEAM_ID=你的10位TEAM_ID bash ios/deploy_device.sh
   > ```
   > `WITHOUT_WIDGETS=1` 下屏幕广播、蓝牙点击、应用内状态条和系统通知完全可用。免费签名约 7 天到期后，重新插线执行同一条命令即可原地覆盖重签，**历史对话、记忆与模型配置不会丢失**。
4. **首次信任开发者证书（免费个人账号）：**
   - 安装后打开 **iPhone「设置 → 通用 → VPN 与设备管理」**，在「开发者 App」下点击你的 Apple ID 并选择 **「信任」**。

---

## 4. 第三步：配置 HTTPS 模型服务商与代理

1. 打开 GAgent，点击侧边栏或右上角进入 **「设置 → 服务商与模型 → 添加服务商」**。
2. 选择接口类型（OpenAI 兼容或 Anthropic Claude），填写：
   - **名称**：自定义名称（如 `OpenAI`、`Claude`、`DeepSeek`、`OpenRouter`）
   - **API Base 地址**：**必须以 `https://` 开头**（为保障凭据安全，iOS 策略层拒绝明文 `http://` 以及 URL 中内嵌 `user:pass@` 或 `?key=` 的地址）
   - **API Key**：保存在本机应用私有沙盒 `mykey.py` 中，不上传任何第三方
   - **默认模型 ID**：如 `gpt-4.1`、`claude-sonnet-4-20250514`、`gemini-2.5-pro`、`qwen-vl-max` 等（执行跨 App 视觉点击任务强烈建议选择支持图片输入的模型）
3. 点击 **「测试连接」**（可选）后点击 **「保存」**。
4. **本机代理 / VPN 一键识别（可选）：** 如果你在 iPhone 上使用本地代理工具访问海外模型，可在 **「设置 → 设备与连接 → 本机代理」** 打开开关，GAgent 会自动检测系统代理隧道并在连通后启用。
5. **数据共享知情同意：** 首次向新配置的服务商发送请求时，GAgent 会弹出隐私披露卡片，说明发送给该模型接口的数据范围（对话文本、任务引用的文件片段及手机操作时的屏幕画面/OCR 文本），点击 **「同意并继续」** 即可生效，后续可随时在「设置 → 存储与数据」撤回授权。

---

## 5. 第四步：配对 ESP32-S3、开启辅助触控、共享屏幕与自动校准

进入 GAgent **「设置 → 设备与连接 → iPhone 操作」**：

1. **开启顶部总开关「允许 GAgent 操作」。**
2. **步骤 1 · 连接 ESP32：**
   - 确认 ESP32-S3 已通电且靠近手机。
   - 点击 **「查找附近设备」**，在列表中点击 **`ESP32 Agent XXXX`**，并在系统弹出的蓝牙配对提示中点击 **「配对」**（建立加密绑定通道）。
3. **步骤 2 · 启用无线键鼠：**
   - 点击页内 **「打开系统设置」**，依次进入 **「辅助功能 → 触控 → 辅助触控（AssistiveTouch）」并将其开启**。
     > **⚠️ 关键说明：** iOS 系统规定，只有开启「辅助触控（AssistiveTouch）」后，外接蓝牙鼠标才能在屏幕上显示光标并执行点击！仅在系统蓝牙里配对成功但未开辅助触控时，点击不会生效。
   - 进入 **「系统设置 → 蓝牙」**，确认 **`ESP32 Agent XXXX`** 状态为 **「已连接」**（若下方「其他设备」出现同名键鼠项，点击完成配对）。
4. **步骤 3 · 屏幕共享：**
   - 点击步骤 3 卡片内的 **屏幕广播按钮**，确认选中 **GAgent**，点击 **「开始直播」**。
   - 等待 1–2 秒，顶部状态栏/灵动岛出现红色广播标识，步骤 3 显示绿色对勾（`正在共享 · 按需截图`）。
5. **步骤 4 · 校准指针：**
   - **保持 GAgent 停留在前台，校准期间（约 8 秒）请勿触摸屏幕。**
   - 点击 **「开始自动校准」**：屏幕会弹出白色网格校准板，GAgent 自动将光标归零至左上角、在多个基准点自动点击并读取真实落点，拟合双轴线性映射并执行独立验证点击。误差 `≤ 1.5%` 即自动通过并持久化保存（只要不修改系统鼠标跟踪速度或更换板子，后续无需重复校准）。

点击右上角 **「完成」** 返回对话页，即可开始让 GAgent 操作手机！

---

## 6. 日常使用规范与安全准则（Guidelines）

### 三步快速验收
1. 发送 `请回复 OK` —— 验证模型接口与授权状态。
2. 发送 `用 code_run 计算前 10 个斐波那契数` —— 验证本机嵌入式 Python 3.13 执行环境。
3. 发送 `打开 iPhone 系统设置，看一眼当前连接的 Wi-Fi 名称后告诉我，不要修改任何开关` —— 验证 ReplayKit 按需截屏、Apple Vision OCR 与蓝牙自动校准点击。

### 灵动岛、切后台运行与就地回答
- 在 **「iPhone 操作 → 运行与预览」** 中可开启 **「切换 App 后继续」**（需 iOS 26+ 系统支持），让 GAgent 切到目标 App 后继续执行多步操作。
- 任务执行期间，灵动岛与锁屏实时活动会展示当前步骤；当智能体调用 `ask_user` 向你确认选项时，可直接在灵动岛/通知横幅上点击候选按钮或输入回复。

### 人工接管（Takeover）与安全红线
- **敏感操作务必本人完成：** 涉及 **付款输入密码、Apple Pay 确认、账号密码、短信验证码 / 2FA、系统权限授权、删除重要数据或公开发布内容** 时，GAgent 会主动暂停并请求你接管（你也可以随时点击灵动岛或界面的「暂停/接管」）。由你本人操作完成后，再点击「继续任务」交回控制权。
- **随时一键急停：** 无论何时，点击 GAgent 底栏的 **「停止任务」**、灵动岛上的停止按钮，或在系统控制中心关闭屏幕广播，都会立即中断任务队列、向 ESP32-S3 发送硬件 `release` 释放所有按键，并作废旧画面引用。
- **锁屏说明：** iOS 系统在锁屏时会自动终止 ReplayKit 屏幕广播，因此执行手机界面操作期间请保持手机处于解锁亮屏状态（可在系统设置中适当调长自动锁定时间）。

---

## 7. 可选进阶：连接电脑（PC Link）

如果你想在 iPhone 上远程查看并操控电脑上的 [GenericAgent](https://github.com/lsdefine/GenericAgent)：

1. 在电脑端启动 GenericAgent Hub：
   ```bash
   python3 ios/pc_link/run_hub.py /path/to/GenericAgent/frontends/hub.py
   ```
2. 在 iPhone GAgent **「设置 → 可选组件」** 中填写你自建或获授权的 WebSocket 中继地址（或阅读说明后启用公共中继预设）。
3. 在 **「设置 → 设备与连接 → PC 互联」** 中扫描电脑终端显示的二维码完成配对，之后即可在顶部导航一键切换 **「本机」** 与 **「电脑」** 会话。

---

## 8. 常见问题排查（FAQ）

| 现象 | 解决方法 |
| --- | --- |
| **校准提示「点击未到达屏幕 / Clicks are not reaching the screen」** | 检查 **iPhone「设置 → 辅助功能 → 触控 → 辅助触控」** 是否已开启，且「设置 → 蓝牙」中 `ESP32 Agent XXXX` 是否显示「已连接」。 |
| **点击位置出现固定偏移** | 检查是否调整过「辅助功能 → 指针控制」中的跟踪速度或屏幕显示缩放；重新进入「iPhone 操作 → 步骤 4」点击「重新校准」即可恢复精度。 |
| **重刷 ESP32 固件后蓝牙连不上** | 板端重新烧录清空绑定信息后，需进 **iPhone「设置 → 蓝牙」** 点击 `ESP32 Agent XXXX` 右侧 `(i)` 选择 **「忽略此设备」**，并在 GAgent「设备选项与关于」点击「忘记此板子」后重新扫描配对。 |
| **提示「Start sharing the screen with GAgent」** | 手机锁屏或手动关闭广播后 ReplayKit 会停止；重新在「iPhone 操作 → 步骤 3」（或控制中心长按录屏按钮选择 GAgent）开启屏幕直播即可。 |
| **免费 Apple ID 编译报 App ID 数量超限** | 使用 `WITHOUT_WIDGETS=1 APPLE_TEAM_ID=... bash ios/deploy_device.sh` 跳过第三个 Widget Target 即可正常编译安装。 |
