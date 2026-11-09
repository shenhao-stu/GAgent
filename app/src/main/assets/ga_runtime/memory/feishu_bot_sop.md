# 飞书机器人 SOP (feishu_bot) — 端内双向机器人一键启停

> 触发: 启动飞书机器人 / 开启飞书机器人 / 飞书机器人 / 停止飞书机器人 / 飞书机器人状态 / start feishu bot。
> 定位: 让 GA 在**手机本机**跑一个飞书双向机器人(WS 长连接收发消息 + 用 GA 智能体回复)。零 PC、零 adb、零联网装依赖(依赖随包)。
> 与「飞书全接口(lark_sop)」的关系: 那个是**主动调**开放平台 API(发消息/读文档); 本 SOP 是**被动收**飞书消息并自动回。两者**共用同一份凭证** channels/lark.json。

## 一次性前提(用户侧)
1. 在 open.feishu.cn 建「企业自建应用」，拿 **App ID(cli_…)** + **App Secret**。
2. 开放平台「事件订阅」选 **长连接** 方式；订阅事件 **接收消息 im.message.receive_v1**。
3. 「权限管理」开 IM 收发消息权限并**发布版本**。
4. 在 GA「设置 → 飞书机器人」填 App ID / App Secret（也可让用户报给你，你走下方控制命令写入）。

## 端内控制(正典入口: fsbot.fsbot_ctl, 零核心耦合)
```python
import fsbot.fsbot_ctl as ctl
ctl.status()   # {running, ready, deps_ready, configured, config_path}
ctl.start()    # 首次自动: 解压依赖(site-packages) + 打 pyaes 解密补丁 + 起长连接线程; 返回 {success,message}
ctl.stop()     # 停长连接; 可再 start()
```
- **首启较慢**: 第一次 start 要解压随包依赖(lark-oapi 等)到 files/ga/fsbot/site-packages/, 数秒到十几秒, 之后秒起。
- **缺凭证**: start 返回「未配置 App ID/Secret」→ 引导用户去设置面板填, 或用下方命令写入。
- **写凭证**(等价于设置面板保存): 通过 UI 桥命令(前端已封装), 或直接:
```python
import lark_native
lark_native.save_creds("cli_...", "<app_secret>")   # 原子写 channels/lark.json, 不回显 secret
```

## 智能体回复
- 机器人收到私聊/群 @ 消息 → 交给一个**独立的 GA 智能体实例**(与手机上正在看的对话隔离)执行并回复。
- 支持文本/图片/文件; 群里需 @机器人; 指令 /help /stop /status /clear。
- 需要设备已配好 LLM 服务商(设置→服务商与模型), 否则智能体无法回复。

## 红线
- App Secret 只落 channels/lark.json，**绝不** print/回显/进日志/进 BBS/进对话。
- 机器人常驻耗电: 不用时 stop; 「开机自动启动」默认关。

## 收事件已落地(对比旧「未实现」声明)
- 旧 lark_sop 曾声明「收事件(长连接)未进 gacore」; 本 SOP 即其落地: lark-oapi 依赖随包 + pyaes 补丁自动化 + fsbot_ctl 常驻线程。无需再升级 Chaquopy 或手动 pip。
