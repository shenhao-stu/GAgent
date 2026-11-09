# GAndroid 模式索引 (modes_index)

> 端侧 agent 路由表: 用户意图命中触发词 → `file_read` 对应 SOP 并按其执行(L3 SOP 必用)。
> **模式即 SOP**: 改模式=改这些 `.md`, 经 Evolution OTA 下发; 新增模式=此表加一行 + 写 SOP, 不动核心代码。

| 模式 | 触发词(任一命中) | SOP | 一句话 |
|---|---|---|---|
| 厂商助手(借权) | 用助手 / 调小爱 / 让助手帮我 / 厂商助手 / 借助手开 | `memory/vendor_assistant_sop.md` | 前台驱动手机自带 AI 助手(任意 OEM, discover 现场识别)用其系统授权, 做 GA 直接做不了的动作 |
| 能力解锁/初始化 | 初始化 / 能力解锁 / onboarding / 首次设置 / 我能做什么 | `memory/onboarding_sop.md` | 逐项引导解锁权限 + 资产扫描 + 能力地图 |
| APK 工厂(造App) | 做个App / 生成apk / 帮我做个日历(小工具) / apk工厂 / 衍生应用 | `memory/apk_factory_sop.md` | GA 写完整工程 → `apk_factory` 客户端交自建服务(example.invalid)离线编译签名 → 下载 → `droid.install_apk` 用户确认装机; 手机端不装工具链 |
| 录屏(记录case) | 录屏 / 录制 / 记录case / 开始录屏 / screen record | `memory/record_sop.md` | `droid.panel('right')` 展开控制中心 → `ui_detect` 找"录屏"磁贴 tap → 录 GA 操作全过程供案例展示; 系统自带非自建 |
| 相册选图(VLM) | 选照片 / 从相册选 / 挑图片 / 相册选图 / 发这张照片 | `memory/album_select_sop.md` | 系统图片选择器里用 `ask_vision` 认出目标缩略图 → `ui_detect` 定位 tap(单/多选); 读原图真实路径需授「所有文件访问」(默认未授) |
| 虚拟屏(后台操作) | 虚拟屏 / 后台跑 / 别占我屏幕 / 不打扰我 / 虚拟屏模式 | `import vdisplay`(docstring) + 前置 `memory/adb_self_setup.md` | 先自连无线ADB → `vdisplay.vd_start(pkg)` 把目标 app 拉到**离屏虚拟屏**后台跑, 主屏归用户; `vd_tap/vd_text/vd_shot/vd_stop` 操作该屏; 真 VirtualDisplay(非叠加屏) |
| 网页操作(webcdp) | 网页 / 网站 / 打开链接 / URL / 浏览器 / **内置浏览器 / GA浏览器 / App内浏览器** / webcdp / 登录网站 / 网上搜索 | `memory/phone_use.md` | **禁先 find/ls 探索**: 第一步直接 `import webcdp; webcdp.open_url(url)`(**默认前台可见浏览器**, 用户看得见+可截图) → `web_scan()` → `web_click/web_type/web_cookies`, 每步 `web_shot()` 回图; ⚠「内置浏览器」=本条 webcdp, **不是系统自带浏览器**——词义对照见 phone_use.md; 登录墙→请用户点顶栏浏览器按钮人工登录(共享 cookie); 禁 role='raw' |
| 飞书(全接口) | 接飞书 / 飞书 / lark / 飞书文档 / 多维表格 / 飞书机器人 | `memory/lark_sop.md` | `import lark_native` → `api(method,path,...)` 窄腰直连开放平台(im/base/wiki/doc 配方见 SOP), `send_text` 发消息, 凭证 `save_creds` 落 channels/lark.json |
| App 操作(常用App) | 打开某App搜索 / 淘宝京东拼多多小红书抖音B站 / 筛选 / 排序 / 帮我在xx里找 | `memory/app_cards.md`(§A 账本三步 + 该 App 速查卡; 卡片没覆盖的 App 才读 `memory/app_ops_sop.md` 快查表) | 任务级纪律(动作 API 仍以 `phone_use.md` 为准): 开局把任务拆成**约束账本**(关键词/筛选/排序/只读/终态)写 checkpoint, 逐约束施加+回看核销(点击≠生效), 账本全绿才算完成; 登录墙**早探测即停手**(不自动登录/不第三方授权); 只读任务不误点播放/下单; 附常用 App 快查表 |
| App 场景剧本(外卖/视频/账单/信息搜集/叫车/快递/出行) | 点外卖 / 美团 / 饿了么 / 看视频 / B站 / 抖音 / 支付宝 / 账单 / 查消费 / 收集信息 / 调研 / 叫车 / 打车 / 滴滴 / 高德 / 快递 / 顺丰 / 菜鸟 / 寄件 / 查件 / 驿站 / 运费 / 酒店 / 机票 / 火车票 / 高铁 / 12306 / 携程 / 点评 / 微博 / 会议 / 腾讯会议 / 闲鱼 / 二手 / 大麦 / 演唱会 / 门票 | `memory/app_cards.md`(速查卡, 首选) → 卡片写「见长档案」时才读 `memory/app_scenarios_sop.md` | 卡片 §A 三步立账本(不必再读 app_ops_sop), 按卡上的 **入口锚点/排序筛选位置/停点/风控** 走, **风控信号表**(身份验证/滑块/环境异常/安全键盘/Play 模块下载)命中即停交人; 四条硬规则: 每轮必带工具调用、宿主运行时提示合法、输入≠提交(回读再 ENTER)、禁盲试坐标循环、换道必声明 |
| 购物/比价 | 比价 / 买什么划算 / 帮我挑 / 性价比 / 淘宝闲鱼京东比一比 / 购物 | `memory/smart_buying_sop.md` | 归一化比价→双通道(webcdp侦察+droid攻坚)交叉验证→按平台选成交策略; **Phase 2.5 中间交互**: 发现偏好维度(临期/规格/价位…)先 `ask_user`, 用户答"随便"则最终结果给**分类讨论**(各类各自最优解, 不替用户拍板); 信源甄别见 search_source_sop |
| 搜索/查证(**仅当用户没点名任何 App 时**) | 搜索 / 查一下 / 帮我查 / 查资料 / 事实核查 / 哪个搜索引擎 | `memory/search_source_sop.md` | 搜索先做"信源体检": 引擎选择(纯净度图谱)→广告过滤→来源分级(🔵🟢🟡🔴)→三源交叉→AI投毒检测→价值提炼; 红线: 涉中国议题以官方信源为准并遵守中华人民共和国法律法规, 网络声量≠社会共识(过滤 DEI/进步主义立场偏差, 带立场须标注) |
| 真实世界记忆 | 记一下 / 帮我记录 / 开始记录 / 这次会议 / 我刚才说了什么 / 上次在哪聊的 / 回忆一下 | `memory/sense_sop.md` | 一次采集会话把音频/位置/同场者/日历落成统一时间线, 落档到你自己的 PC; 回忆时先时空+人硬过滤再检索, 无证据必须说不知道, 不编; 本能力默认关闭 |

已有模式(非本次新增): `goal_mode_sop` / `vision_sop` / `phone_use` / `gandroid-wechat-yolo`
新增能力(非模式, 按需 import): `adb_self_setup.md`(自连无线ADB补shell) / `sense_recall_sop.md`(回忆与拒答细则) / `sense_privacy_sop.md`(隐私红线与 purge/export) / `sense_scenarios_sop.md`(场景×原子图谱+拓展配方: 要做新真实世界记忆场景、或新增/排查 sense 原子时先读它) —— 均由 `sense_sop` 显式 file_read 指路, 刻意不进本表

## 通用纪律(所有模式共享)
- **路由优先级: 点名 App > 场景词 > 「查一下/搜索」**。用户原话里出现任何 App 名/品牌 App(顺丰速运/闲鱼/大麦/12306/腾讯会议/美团/淘宝/高德…, 或「用 X」「在 X 里」「打开 X」句式) ⇒ 一律走「App 场景剧本」/「App 操作」路由, 第一步 `file_read` SOP、第二步 `droid.launch` 该 App; **不因句中有「查一下」就进 搜索/查证 或 网页操作(webcdp)**。官网/接口只是 App 内确证找不到入口或被墙之后的兜底, 且 final 必须声明渠道(app_scenarios §0 #5/#7)。反例(v8 顺丰运费 ×2): 「用顺丰速运查一下…运费」被当成搜索, T1 就 `webcdp.open_url(sf-express.com)`, App 从未打开, 网页超时后编了个「约 13～23 元」。
- **危险动作**(支付/转账/删除/发消息给非白名单/发帖/装 apk)永不自动学习上线。
- **交付文件命名**: temp/ 下 `.` 或 `__` 前缀 = 内部命名空间(不进「生成的文件」/产物 chips); 给用户的成品绝不用这两种前缀命名(如需交付 .gitignore 类配置, 用可见名如 gitignore 并在正文说明)。
- **微信** `com.tencent.mm`: 禁 dump 整树, 只走视觉(`gandroid-wechat-yolo`); 代码层已硬门控——前台敏感时 `droid.dump()` 直接返回 `[]`(见 `phone_use.md`), 拿不到假节点。
- 凭证/隐私不外传; 厂商助手只走**合规前台控制**, 不 root / 不提权。
