# offscreen_sop — 离屏模式速查(关键点+坑点)

「离屏」是两条不同链路, 先分清(路由与词义对照见 phone_use.md, 本文不复制):
- **网页离屏** = `webcdp.open_url(url, background=True)`: 离屏 WebView, 不遮对话页。仅当用户明确说「后台/别占屏/不打扰」才用; 没说后台一律 L1 前台任务浏览器。
- **App 离屏** = `import vdisplay`(docstring=完整 SOP): 第三方 App 跑在虚拟屏。前置=self-adb 已连(memory/adb_self_setup.md)。

## 网页离屏(webcdp L2)
- 只驱动 GA 自建哨兵 tab(白名单 fail-closed); 失败显式 raise→按 phone_use.md 降级, ⚠禁 role='raw'(会连系统 Chrome)。
- 与前台/登录 WebView 共享 cookie, 登录态自动复用; 截图用 web_shot(离屏页默认持续光栅化, v2.19 已修)。

## App 离屏(vdisplay)生命周期
- 开工先 `vd_status()`; alive=True=上一会话遗留活屏, 先 `vd_shot()` 认清现状再决定复用/重启, 勿假设在主页。
- 收工必 `vd_stop()`(关持有流=确定性回收; 遗留屏会把下一会话 resume 到旧页面, 诱发多轮误诊)。
- 虚拟屏模式下主屏 tap/launch/home=破坏用户意图; 仅 vd 明确不可用且已告知用户才降级前台。
- launch 后 fg 未变≠失败: app 可能被 resume 到遗留虚拟屏, 看 `vd_status()`/`dumpsys activity` 的 display 归属再诊断。

## 三条执行面怎么选(先选面, 再选动作)
- **主屏 GUI(droid/A11y)**: 默认面, 用户能看见; 截图/点击/A11y 都归默认屏。
- **App 离屏(vdisplay)**: 截图=虚拟屏帧(vd_shot), 输入=`input -d <vid>`(vd_tap/vd_swipe/vd_key), 二者同属该屏; ⚠droid.shot/look/tap/A11y 只看/只点主屏, 离屏期间禁混用。
- **网页离屏(webcdp background)**: 只适用于网页任务, 复用内置浏览器登录态; 不能操作第三方 App。
- 诚实边界: 离屏不是"所有 App 都能后台跑"。FLAG_SECURE 黑帧、ROM/App 拒绝非默认屏(被落回主屏会撤回报错)、中文输入只能深链、
  锁屏/熄屏后虚拟屏内 App 是否继续运行因 ROM 而异(未验证前不得承诺)。

## 守护规则(代码已强制)
- 目标 App 正在主屏前台(用户在用)时 `vd_start` 直接拒绝: 真机取证 `am start --display` 会把该 App 整条 task 从用户屏幕搬走。
- 坐标按虚拟屏尺寸(`vd_status()['size']`, 默认 1080x1920)校验, 越界(常见于沿用主屏截图坐标)直接 ValueError, 不注入。
- `vd_shot` 只交付属于当前 helper 且晚于最近一次 vd 输入的帧(动作无画面变化时 settle 后交付当前帧); helper 已死直接报错, 不回旧图。

## 坑点(细则=vdisplay docstring, 设备端唯一细则源, 勿凭印象)
- `vd_text` 仅 ASCII 可靠; 中文一律 app scheme 深链 `am start --display <vid> -a android.intent.action.VIEW -d '<scheme>://…'`(URL 编码), 失效再退 vd_tap。
- FLAG_SECURE App 在虚拟屏同样黑帧; droid.shot/vd_shot 拿黑帧按报错提示降级, 勿盲目重截。
- vd_shot 无帧/超时: 走 `screencap -d <SF物理id>` 落文件直读, 勿 base64 走文本 bus(大帧超时)。
