# 手机使用电脑 SOP

触发词：连电脑 / 连我的电脑 / 在电脑上执行 / 电脑上的文件 / 远程到电脑。

通过手机本地 `code_run` 调用 `ganet` 使用已配对电脑；手机本地的 `code_run`、`file_read`、`file_patch`、`file_write` 操作的是手机，不是电脑。不要自行调用系统 `ssh` 或 Paramiko，也不要向用户索取 token、私钥或二维码内容。

## 调用电脑能力

一般用户会在会话 ui 界面选好要连接的设备。电脑能力统一先查询、再调用：

```python
import ganet

# 当前已配对电脑提供什么正式能力与参数。
tools = ganet.device_tool_catalog()

# 读取电脑文件。
ganet.call_device_tool("file_read", {
    "path": "电脑上的文件路径",
    "start": 1,
    "count": 200,
})
```

`ganet.call_device_tool` 会自动完成正确调用。不要自行建立电脑连接或绕过该接口；不要把文件内容放进工具参数。

文件在手机与当前会话选择的电脑之间传输时，使用 `file_transfer`：

```python
# 手机附件或手机路径 → 电脑；电脑相对路径基于其原子工具工作目录 temp/
ganet.call_device_tool("file_transfer", {
    "action": "upload",
    "local_path": "手机源路径",
    "remote_path": "电脑目标路径",
})

# 电脑 → 手机聊天文件产物；省略 local_path 时保存到手机产物目录
ganet.call_device_tool("file_transfer", {
    "action": "download",
    "remote_path": "电脑源路径",
})
```

文件传输采用流式方式，默认不覆盖同名目标。只有用户明确要求覆盖时才传 `"overwrite": True`。成功结果包含传输大小及可用于复验的元数据；下载结果的 `artifactPath` 对应手机聊天中的文件产物。

## 设备
ganet 连接失败，用户要求查看、切换或停止连接电脑时，可使用下列接口连接和切换：

```python
# 查看已配对电脑和当前会话选择
computers = ganet.list_devices()
selected = ganet.current_device()

# 为当前会话选择一台电脑；传设备名或 deviceId
computer = ganet.bind_device("我的电脑")

# 选择“不连接设备”
ganet.unbind_device()
```

设备名称相同时，使用 `deviceId`。

### 选择规则

- 读取文件：`file_read`。
- 局部修改：先 `file_read` 获取最新内容，再 `file_patch`；匹配失败后重新读取，不要猜。
- 创建或整体改写：`file_write`。覆盖已有文件前先确认内容和用户意图。
- 在电脑运行代码或系统命令：`code_run`；优先 Python，Windows 系统操作才用 PowerShell。
- 操作电脑浏览器：先读取电脑的 `../memory/tmwebdriver_sop.md`，使用 `web_scan` / `web_execute_js`；不要用 `code_run` 启动浏览器 GUI。
- 当完成一项需要用户视觉验收的电脑桌面任务，或需要用户查看当前电脑桌面时，调用 `computer_screenshot`，参数为 `{}`。它截取当前交互桌面的完整可见画面，不是网页 DOM 或后台窗口截图。
  - 展示某个目标窗口：先使该窗口在电脑桌面可见且位于前台，再调用截图；不要在截图后才聚焦。
  - 展示浏览器页面：先用 `web_execute_js` 对目标 tab 调用 CDP `Page.bringToFront`，确认该 tab 已处于前台，再调用 `computer_screenshot`。不要用 `Page.captureScreenshot`、Base64 或 `code_run` 自行截屏代替该工具。
  - 成功结果的 `markdown` 字段是手机本地图片引用；在最终回复中原样引用该字段。

### 电脑专项 SOP

电脑原子工具的相对路径基准是电脑项目的 `temp/`，不是项目根目录。需要电脑端专项规则时，读取相邻的 `../memory/`：

```python
info = ganet.call_device_tool("file_read", {
    "path": "../memory/<相关_sop>.md",
    "start": 1,
    "count": 300,
})
```

常用入口：

```text
../memory/computer_use.md       电脑桌面操作
../memory/tmwebdriver_sop.md    电脑真实浏览器操作
../memory/ljqCtrl_sop.md        Windows/macOS 键鼠与截图
../memory/vision_sop.md         电脑视觉辅助
```

只在任务相关时读取对应 SOP，不要一次读取全部。

## 执行与安全

- 路径或环境未知时，先用只读原子工具确认；不要根据手机本地路径推断电脑路径。
- 工具返回成功后按任务复验：文件修改后重新读取，进程或系统操作后检查实际状态。不能仅因命令已发送就报告完成。
- 失败时读取错误并调整；不要无信息重复同一调用。
- 删除或覆盖数据、安装软件、修改服务/防火墙/SSH、结束进程、发送或发布内容等高影响操作，先取得用户明确确认。
- 浏览器中的发送、发布、购买、删除或提交表单等外部行为，先取得用户明确确认。
- 不读取、输出或传输 SSH 私钥、GAuth token、二维码内容。
- 不通过远程命令批准配对、修改设备授权或移除设备。
- 不自动接受电脑身份变化；一台电脑的连接或命令失败不得影响其他已配对设备。

## 没有已配对电脑

告诉用户：

1. 在电脑启动 GenericAgent（确保已更新到最新版本）。
2. 对电脑 GA 发送：`阅读 ../memory/ganet_pc_setup_sop.md，帮我配置 GAnet。`
3. 配置过程中电脑会自动打开「GAnet 用户中心」页面；未登录时在该页面登录与手机相同的 GA 账号。
4. 配置完成后，在 GAnet 用户中心打开“我的设备”，点击“添加设备”。
5. 在手机打开“设置 → 设备互联 → 扫描二维码”。
6. 手机显示“已验证，等待电脑确认”后，在电脑确认手机型号。

二维码内容不得发送到聊天中。

## 连接失败

先读取错误；同一错误不要盲目重复调用。可能是以下错误导致：

1. **电脑未开机或处于休眠**：请用户检查目标电脑已开机、已解锁且未休眠；恢复后再重试。手机无法代替用户唤醒或检查电脑电源状态。
2. **电脑环境发生变化、GAnet 掉登录或电脑端已解除配对**：请用户在电脑打开「GAnet 用户中心 → 我的设备」（双击 GAnet 组件目录的 `ganet.cmd` 可打开），确认目标电脑仍在设备列表中并检查环境状态。必要时，让电脑 GA 执行“阅读 ../memory/ganet_pc_setup_sop.md，帮我配置 GAnet。”完成环境排查与恢复；恢复后重试，不要直接把 SSH 错误归因为手机密钥问题。
3. **确认电脑端配对记录已不存在，或 SSH 公钥被明确拒绝**：停止重试；在电脑的“我的设备”重新添加设备，再让手机扫码并在电脑确认。不要修改 SSH 密码认证策略。
4. **电脑身份验证失败**：停止连接并告诉用户电脑身份发生变化；不得自动接受新的 SSH host key。仅在用户确认电脑重装或身份变化后，重新扫码配对。
