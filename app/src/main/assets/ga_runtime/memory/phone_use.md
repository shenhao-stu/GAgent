# phone_use

相关: droid.py docstring(接口真相源) | app_cards.md(各App速查) | 遇到再读: app_scenarios_sop.md vision_sop.md offscreen_sop.md

## 0. 节奏
首次进入尚未观察的界面，先观察再决定。
明确操作后，可以同次调用执行动作并观察新状态；下一轮根据这份观察继续操作并观察。
观察时一并获取下一步操作所需的信息；需要点击时，同时取得目标位置。
一步一验: `print(droid.tap(x,y))` —— tap 已内置等待+前后截图 diff, **勿再 sleep**; diff≈0 立即停下诊断, 禁盲目重试
不预测关键词筛候选, 看实际输出/坐标/上下文判断; 同一路径失败 2 次换路径
终态即 final: 回读到状态证据(新气泡/settings get/订单页)才算完成, 动作返回 ok 或 UI 文案不算

## 1. 工具(按优先级降级)
用户指定 App/浏览器/Python 时按指定通道。先满足结果/状态/权限：账号状态、本机状态或外部写需要相应权限；无状态查询选交互轮次最少的等价通道，同轮次优先已装 App。
`pkgs()` 只证明存在可启动候选；pkgs() 发现不消耗这一次探测。对候选只探测一次，该探测=launch + 一次初始状态/能力检查。不可用再降级，不自动安装。Python 仅用于不需要手机 UI 的操作，不得绕过 droid。
默认安全模式走视觉路径，所有 App 均不读取控件树。

| 工具 | 时机 | 限制 |
|---|---|---|
| ping | 检查设备与服务状态时 | a11y、屏幕尺寸与旋转；不提供前台包名 |
| 1 dump / find / tap_text | 控件树可用时首选 | 敏感App(微信等, 见 droid.SENSITIVE_APPS)恒返回 [], 勿重试; 游戏/内嵌WebView 常为空壳 |
| 2 look(roi=) | dump 不可用 | shot+ui_detect+OCR 一步, 坐标=整屏物理像素直接 tap; roi: top/upper/middle/lower/bottom |
| 3 ask_vision(droid.shot(),"一个具体问题") | 按需自主选用; 遇异常(diff≈0/结果不符预期/look 读不懂)立即用, 不先猜或重试 | 一次只问一件事、要短答; look 已读出的不再问 |

动作只走 droid: tap/swipe/paste/scroll/key('ENTER')/back/home/launch/pkgs; 禁 shell am/input
用户点名 App 就走 App, 不算网页任务; 用户说"后台/别占屏/虚拟屏"→ App 用 vdisplay, 网页用 open_url(background=True)(读 offscreen_sop), 此后禁碰主屏
网页: `webcdp.open_url(url)` 前台内置浏览器(默认; "内置/GA浏览器"=它, 不是系统浏览器); 两条都 raise 或用户点名 Chrome 等才 droid.launch 视觉操作; 禁 role='raw'
登录墙/验证码: 请用户点对话页顶栏浏览器按钮自行登录, GA 永不代填、永不截图它; 完成后 web_cookies(域名) 验证

## 2. 输入
paste 是追加; 覆盖用 `paste(text, replace=True)`, 不支持则点框内 ✕ / 长按全选
hit=True=已确认上屏；hit=False, uncertain=True=未知，先看当帧输入框。ime_label 仅是元数据；只有 ime_hint 可点击，点击后再确认文本。verify=False 永远不能证明输入成功。
长按 = `swipe(x,y,x,y,dur=800)`; 键盘/表情面板弹着时先收起再长按
key() 只有 ENTER; 发送键位置随键盘漂移, 每次从当帧定位

## 3. 微信(只走视觉)
paste 只放剪贴板(needs_gui_paste)→ `look(roi='lower')` 点键盘上方剪贴板提示条中段(别点右端✕); 无条则长按输入框点"粘贴"
找人: 搜索后点带头像的联系人条目, 「搜索网络结果」以下是搜一搜, 别点; 列表看不到名字就搜索, 不凭位置点
**进会话先核对顶部标题=目标**, 再输入; 发送后见标题正确+新气泡才完成
launch 后弹分身/打开方式选择框: 按本机记忆选, 无记忆问用户

## 4. 坑
坑1-弹窗/遮罩: 只操作最上层, 不点遮罩后正文; 不用 back() 猜关弹窗(可能退出小程序)
坑2-坐标: 只用当帧坐标, 禁写死/复用旧坐标; 状态栏附近点击前重新观察(通知横幅劫持)
坑3-快捷设置面板: 用完 `droid.dismiss_shade()`, 残留会吞掉所有 tap
坑4-滚动: direction 是手指移动方向：`scroll('up', times=1)` 看下方内容，`scroll('down', times=1)` 看上方内容；scroll() 自己负责文本/像素证据。times>1 仅用于明确遍历。
坑5-风控: 验证码、登录失效、账号异常、安全验证、设备证明、实名或支付授权立即停，交用户。不自动重试，不切换输入法，不使用 ADB 文本注入，不转交厂商助手，不自动登录。不得使用随机抖动、拟人化或隐藏自动化。
外部提交按「探测 → 单一动作 → 条件等待 → 验证 → 下一步」。目标上下文、唯一载荷和输入确认齐备后只提交一次；用输入框清空及精确的新气泡/状态核验。同一路径第二次失败先诊断。

## 5. 提问
用户指令即授权, 直接执行, 不可逆动作只执行一次并核验
提问只能用 ask_user, 整个任务尽量一次; 可默认的(当前位置/现在/经济型)不问, final 里声明
多约束任务(排序/筛选)每条回读确认生效, 未生效在 final 逐条标注
