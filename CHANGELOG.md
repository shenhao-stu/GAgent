# Changelog / 变更记录

Entries describe repository candidates, not an assertion that every version was
publicly released. Exact artifacts and acceptance belong to their release records.

本页记录源码候选的变化，不表示各版本均已公开；制品与验收以对应发布记录为准。

## Unreleased / 未发布变更

- tests: 降级契约用例不再因为环境没装 onnxruntime 就在收集期报错(CI 曾 `ModuleNotFoundError: No module named 'onnxruntime'` 打断整个 pytest) / degrade tests stub onnxruntime when absent
- 解耦审核修整: 历史剪枝归会话侧, 猴补不再抄签名, 关闭/roi 的事实不再被丢
  / decoupling review: history pruning belongs to the session, monkey patches stop copying signatures, close/roi facts are no longer dropped
  - `ga_android._drop_stale_frame_history()` 不再自己遍历并改写 `parent.history`(会话消息库, 属主是
    `llmcore.BaseSession`), 改成调用新增的 `BaseSession.drop_stale_images()`(内部 `age_image_blocks(history, keep=0)`);
    旧写法漏了 `image_url` 块, 占位文字也和 `IMAGE_PLACEHOLDER` 不一致 —— 一处策略只能有一份实现。
  - 第一帧的标志改成**拿到 b64 之后**才清: 此前 shot 一抛错, "第一步必附图"静默失效而旧图已被剪掉(不可回滚)。
  - `kernel_adapter/patches.py` 的 `_stream_with_retry` 改 `(*args, **kwargs)` 原样转发(payload 从 args[3]/kw 取):
    抄全签名正是上一轮 `takes 5 positional arguments but 6 were given` 让每个模型请求立刻失败的成因。
  - `close_dialog` 的 `still_there`(关完再 OCR 核验)现在会随 `gui_act close` 回到模型; 胶囊改道那条 close 也补上
    `expect_text`, 与主分支一致(此前那条路仍可能把 10% 的卡片抖动当"关上了")。
  - `_close_icon_ok`: 拉丁标签上限 12 → 3 —— 真机 15:30:02 被误点的正是 OCR 读出的正文 `TEXT`。
  - `_roi_box`: `800,150,950,250`(无括号)也接受; 夹到零宽/零高时返回 None 让调用方回退全屏, 不静默裁空条。
  - 测试: `tests/test_first_frame.py`(截图失败不清标志 + 剪枝走会话)、`tests/test_dialog_close.py`(拉丁正文不是叉)、
    `tests/test_observe.py`(roi 数字框)、`tests/test_soft_failures.py`(still_there 回到模型)、`tests/test_empty_stream_fallback.py`(猴补原样转发)。
- droid/ga_android: 任务第一帧必附图 + 旧截图不再冒充"现在" + roi 接受 0-1000 数字框
  / first turn always attaches a live frame, stale screenshots are dropped, roi accepts a 0-1000 box
  - 真机 15:29/15:34 两次任务第一轮 prompt 里一张图都没有(前台是桌面, auto 模式只在视觉型页面附图),
    而同一会话历史还带着上一个任务的截图和"今日密码弹窗已打开、密码 0600/…"的结论 → 模型在桌面上
    连按 close/back, 把整个小程序退掉, 用户看到"路径完全不对"。
  - `ga_android.GenericAgentHandler._task_frame_pending`(任务边界置 True): `turn_content_blocks()` 在
    auto 模式下**第一步例外附图**, 提示前置"任务刚开始(第 1 步): 这是此刻的真实屏幕 … 上一个任务/上一轮
    的截图、坐标、『已经打开了什么页面』的结论一律作废" + `当前前台: <pkg>`; 用完置 False(第二步起回落原判据)。
  - `_drop_stale_frame_history()`: 任务第一步顺手摘掉历史里的 image 块(保留文字, 纯图消息补一句占位),
    既防"把上一任务的画面当成现在", 也省 token(一帧约 1.4k)。`/vision off` 时一帧不发、历史也不动。
  - `droid.close_dialog(..., allow_back=None)`: 给了 bbox 的弹层关闭**不许按系统返回**(自绘小程序里
    "返回"=退出整个小程序), 只能点文字按钮或图标叉; 新增 `droid.ui_back(..., allow_system=True)`,
    目标像弹层(`弹窗/弹层/对话框/窗口`)时 ga_android 传 False。
  - `_CLOSE_TEXTS` 里的单字符改用 `_is_close_text()` 全等判定(旧 `any(k in t)` 会把 OCR 出来的 "TEXT" 当叉)。
  - `droid._roi_box()`: roi 现在也吃 `"[800, 150, 950, 250]"` 这种 0-1000 数字框(真机 15:41 模型就是这么传的,
    旧代码 `ValueError: unknown roi …` 让整轮观测作废); 非字符串仍保持原比例/像素语义。
  - 新增 `tests/test_first_frame.py`(5 条) + `tests/test_observe.py` 两条 + close/back 回归断言若干。
- droid/ga_android: 关弹层不再把弹窗正文当叉点 + 关闭判据按百分比 + 单字 target="X" 软失败
  / droid+ga_android: dialog close can no longer pick body text as the ×, close threshold is real percent, single-letter target="X" is refused
  - 真机 15:08/15:11 三次会话同一条路打转: 模型 `tap target="X"` 命中了底栏 (361,2366); 之后 `gui_act close`
    把弹窗里「航天基地」卡片(位置恰在弹层 bbox 右上方)当图标叉点了下去, 直接进了航天基地详情,
    又因卡片轮播抖 10.037% 被判成"关上了" —— 于是"点了今日密码却进了航天基地", 再往后「制造推荐」
    也穿透到弹窗后面的卡片, 最后退出小程序。
  - `droid._DIFF_CLOSED_PCT = 20.0`: `_pct_from_diff` 返回的是百分数(10.037 表示 10.037%), 旧判据 `pct >= 0.2`
    等于 0.2%, 任何抖动都算关成功; 现在按钮/图标/系统返回三处统一走 `_closed_ok(pct, expect_text)`,
    要求变化 >= 20% 且(给了关键字时)该关键字已从屏上消失, 失败结果新增 `still_there`。
  - `droid._close_icon_ok(label)` 准入: 空标签、命中 `_CLOSE_TEXTS`、或不含中文(CJK)的标签才当叉;
    「航天基地」这类弹窗正文即便位置正好在右上方也一律不点。
  - `ga_android._close_expect_text(args)`: 从 `target`/`expect` 剥掉「关闭窗口/弹窗/按钮/×」等词, 得到
    这一层的名字(如 `关闭今日密码弹窗` → `今日密码`), close 时交给 `close_dialog(expect_text=…)` 核验。
  - 单字 target(×/✕/╳/✖/x) 改成 SoftFail(`zone:'close_icon'`), 提示改用 `{"action":"close"}` 关这一层、
    `{"action":"exit_miniapp"}` 离开小程序; 正常文字里的 x(如 `Xbox`)不受影响。
  - 测试: `tests/test_dialog_close.py::CloseRegressionTest` 3 条 + `tests/test_soft_failures.py::CloseIconTargetSoftResultTest`
    2 条 + `tests/test_ui_back.py` 补「系统返回后只抖 12% 不算退层成功」反例。
- llmcore: 空流现场诊断(stream_diag) + 把网关塞在 SSE 里的 error 事件如实抛出
  / llmcore: empty-stream diagnostics dump + surface gateway error events carried inside SSE
  - 取证(PC 直连同一 key/端点): 1.7MB / 16 图 / 并发 5 / 两个模型全部正常, 排除配置与网络;
    但 HTTP 200 的流确实可能只回 `role` + `finish_reason` + `usage` 三块而零正文 —— 这时旧代码一律
    报 `ConnectionError: empty response`, 把"模型这一回合没吐字"和"网络一个字节没回"混成同一条红字。
  - 现在空流会往 `temp/stream_diag_<ts>.json` 落现场(`raw_lines`/`saw_done`/首行/Content-Type/
    请求体形状, 图片只留长度, 最多 20 份), 报错文案也带上 `raw_lines`/`saw_done`, 便于事后判定是哪一类。
  - `_parse_openai_sse` 遇到 `data: {"error": ...}`(网关把错误包成事件)现在会 yield `!!!Error: <msg>`,
    不再被静默忽略然后误报成"空流"。
  - 修 `kernel_adapter/patches.py:patch_llm_timing` 的猴补签名(补 `json_fn=None` 并转发): 否则真机上第一个模型
    请求就 `TypeError: ... takes 5 positional arguments but 6 were given`, 任务 6 秒即结束。
- llmcore: 空流(HTTP 200 零 chunk)自动改非流式重取 + 中间重试不再刷红字
  / llmcore: empty-stream auto-retry via non-stream fallback + silent intermediate retries
  - 真机取证(2026-10-30, StepFun `step_plan` + `step-3.7-flash`): `files/ga/chat.json` 20 条历史任务里 4 条
    以 `!!!Error: ConnectionError: empty response` 收尾, 且都死在开局第 2 回合左右 —— 用户看到的就是
    "刚开始执行就报一堆 error"; 失败那次 `model_responses_*.txt` 只有 `=== Prompt ===` 没有 `=== Response ===`,
    即上游 200 但一个 chunk 都没回。
  - `_stream_with_retry(sess, url, headers, payload, parse_fn, json_fn=None)`: 命中空流时先用同一 payload
    (`stream=False`, 摘掉 `stream_options`) 走非流式再要一次, 拿到正文就直接继续本轮, 不再报错; 三个调用点
    (`_openai_stream` 与两处 Claude `raw_ask`) 都补了 `json_fn`。
  - 中间重试不再 `yield err`(真机一轮空流会连着重试好几次, 连出好几行红字), 只打 `[LLM Retry]` 到 stdout;
    次数用尽才在正文里放一条, 并附中文说明"上游这一回合一个字都没回…不是任务做错了, 过一会儿重发或换模型"。
  - 新增 `tests/test_empty_stream_fallback.py`(3 条): 兜底改非流式并继续、全失败只有一条红字且带恢复提示、
    普通 `Timeout` 行为不变。
- amoo(StepOS 语音助手) 接单通道: 新增 AppFunctions 服务 + 分享接单 + 结果回推 amoo
  / amoo (StepOS voice assistant) task intake: AppFunctions service + share-target intake + result push-back
  - 真机机制实测: 装/更新包即触发 `AbilityInstallerWatcher: handleAppUpdated` → `refreshAndUpload` →
    `AtomicAbilityRepository: syncPackage: package=io.github.shenhaostu.gagent.debug tools=4` →
    `BM25Index: rebuild: docs=378` / `ToolSearchEngine: Index rebuilt: 378 tools` —— 第三方 AppFunctions
    **装包即入本地目录, 不需要云端审核**; 但 `JetpackToolConverter` 生成的 `ToolItem(... hasAbilityId=false)`,
    而 amoo 的 `ability.search` 只吐云端已发布项, 所以模型看不见这些工具(实测 4 次 search 全空, 说出来是
    "本机没有能自动操作其他 App 界面的工具")。故自动派活这一步被 amoo 云端目录卡住, 端侧另开两条通道。
  - 通道① AppFunctions(`com.ljq.ga.amoo.GaAppFunctionService`, 函数 `capabilities`/`startTask`/`taskStatus`/
    `cancelTask`, amoo 侧工具名 `debug_start_task` 等 = 包名末段 + 方法名下划线): 直调实测
    `{"ok":true,"state":"accepted","taskId":"amoomvugk7g3"}` → running(第5/7步, 前台 `AppBrandUI00`) → done 8 步;
    `StepOSFreeze: [BLOCK_FREEZE] … FLAG_USING_SERVICE … perceivableUnfreeze true` 证明 amoo 挂后台时 GA 不被冻。
  - 通道② 分享接单(A 路线, 完全端侧): `MainActivity` 认 `ACTION_SEND`+`text/plain` → `AmooBridge.taskFromShare`
    → `takeAmooTask` → `AmooBridge.dispatch`(`send2`, 多会话关闭时自动降级 `send`) → 起跑; 实测 15 步跑完。
  - 结果回推: `AmooBridge.watchAndReport` 每 6s 轮询 `status(taskId)`, `state=done` 后 `cleanFinal` 剥掉转写壳
    (只留最后一回合的人话, 去掉 `**LLM Running`/工具 JSON/碎词) → `ACTION_SEND` 到 amoo `ShareActivity` 预填输入框
    (实测 amoo 不会自动发送, 由用户点一下); 报告长度 1200→214 字符。
  - 编译门: `compileSdk 34 → 36`(android.app.appfunctions.* 只在 API36) + `android.suppressUnsupportedCompileSdk=36`
    (AGP 8.1.4 未声明支持 36); 元数据由 `tools/gen_amoo_functions.py` 手写生成 `app/src/main/assets/amoo/app_functions.xml`
    与 `app_functions_v2.xml`(不走 KSP), schema 用 AOSP 的 `app_functions_schema.xsd`。
- gacore: 参数/命中类失败不再渲染成 `[Error]`, 改成带现场事实的软失败结果(用户反馈"刚开始执行就报一堆 error")
  / parameter and hit-test failures are no longer rendered as `[Error]`; they return an actionable soft result
  - 真机普查(2026-10-29~30, 22 次会话): 45 条 `[Error]` 里 target 未命中 14、多选 6、三单位二选一 5、状态栏 4、附图越界 2、其它 12, 真正的设备故障只有 2 条(无障碍未开); 全部集中在 t3-t14, 正是用户说的"开头那一段"。
  - 新增 `SoftFail(ValueError)` / `SoftMiss(LookupError)`, 由 `_do_gui_act` 兜底转成 `{"ok": false, "soft": true, ...}` 的普通 `StepOutcome`: 仍是失败, 但不是红字, 模型同一轮就能按提示改对。
  - `target` 没命中时回这一屏的近似候选 `near`(`t`/`point`/`ratio`); 只差空格/标点/一个字且 ratio >= 0.85、领先次名 >= 0.15 时直接命中并回 `fuzzy` —— 真机 14 条 miss 里大半是这种写法差异。
  - 坐标守卫(三单位互斥/缺位置/形状/像素越界/状态栏/附图越界)改 `SoftFail` 并带 `screen`、`rel_suggestion`、单位说明; 附图坐标越界但落在屏幕内时按设备像素用掉, 并在结果的 `zone_hint` 里说明。
  - 新增 `tests/test_soft_failures.py`; `tests/test_img_point.py`、`tests/test_structured_action.py`、`tests/test_dialog_close.py`、`tests/test_layer_and_retry.py` 的旧契约随之更新。
- gacore: 小程序「总控胶囊」不再被当关闭键 —— 胶囊区坐标一律拒点，改成 `close` / `exit_miniapp`
  / the mini-program capsule (share + close keys) is no longer tapped as if it were a close button;
  any coordinate inside it is now refused and redirected to `close` or `exit_miniapp`
  - 用户实测口径：小程序右上角是总控胶囊，并排两个键 —— 左=分享/更多，右=关闭（退出小程序），
    **非必要不要点**。三次真机记录都点到左边那个键（10:06 `[906,205]`、10:26 `[895,206]`×5、
    10:52 `[890,200]`），每次 diff 都是 85.850%~85.867%（分享面板开→关→开），而真正要关的
    今日密码弹窗一直没关掉。
  - 上一版"第一次照点 + `zone_hint`"仍会点开分享面板（10:52:17 就是它），本轮改成一步都不点：
    有"离开小程序"意图 → `droid.exit_miniapp()` 只点胶囊右侧那个键；有"关掉这一层"意图 →
    改道 `droid.close_dialog(bbox=最近一次画面变化范围)`；其它意图直接拒绝并说明该用哪个动作。
  - `droid.miniapp_capsule()` 用 YOLO 在标题带右侧（`x >= 0.72*W`）认框：最右=关闭、其左邻=分享，
    只用来点"关闭"，分享键永不点击（`exit_miniapp` 返回里 `more` 只作信息）。
  - `close_dialog()` 补图标兜底：真机 10:51:34 `action=close` 返回 `ok:false`，因为 canvas 弹窗
    的 × 是画出来的、OCR 读不到文字。现在在弹层范围（最近一次 diff 的 bbox）内用 YOLO 找
    "右上方的图标框"并逐个点验，标题带（y<10%）依旧不碰。
  - 新增 `gui_act {"action":"exit_miniapp"}`（两份 schema 的 enum 与说明同步、契约测试映射
    `'exit_miniapp': 'exit_miniapp'`），并补 `tests/test_dialog_close.py` 的
    `CapsuleTest` / `CloseDialogIconTest` / 胶囊闸门三条用例。
- gacore: 标题栏右侧那三个点（⋯）不再被当成关闭键 —— 同一处重复点击会被拒或被改成 `close`
  / the mini-program title-bar ⋯ (share/more) is no longer treated as a close button; a repeat tap
  there is refused or turned into `close`
  - 真机 2026-10-30 10:26: 同一个点 `[895,206]` 连点 5 次（每次 diff 85.850% = 分享面板开→关→开），
    `expect` 全是"关闭今日密码弹窗"。上一版只在"target 没命中且退回坐标"时拦，模型这次直接给坐标，
    拦不住。
  - `_share_trap` 现在对所有落点在标题带右侧（x>55%）的点击生效：第一次照点但结果里带
    `zone_hint`；同一处（±40px）第二下起，带「关闭/关掉/退出/返回/取消」意图就**替你改成
    `droid.close_dialog(bbox=最近一次画面变化范围)`**（结果带 `redirect: title_band_close`），
    其它意图直接拒绝并给出正确做法。
  - `obs_note` 增加第 ④ 条：要关掉这一层用 `gui_act {"action":"close"}`，不用给坐标 ——
    这段话每轮都在，比 schema/SOP 更靠前。

- gacore: 关弹层改成一条原语 `gui_act action=close`，并且不再允许"文字没找到 → 点模型目测的坐标"
  / dismissal is now a primitive (`gui_act action=close`) and a missed target can no longer fall
  back to a guessed coordinate in the title bar
  - 真机 2026-10-30 10:06（三角洲「今日密码」）：关闭控件是 canvas 里的图标型 ×，OCR 读不出文字；
    模型把 `target='关闭按钮（X）'` 当文字找 → `target_miss` → 退回它目测的 `(906,205)`，
    那正是小程序**标题栏右上角的分享/更多** → 一下点开分享面板，之后 6 轮都在关分享、找返回，
    真正的下一步「特勤处 → 制作推荐」一次都没走到。
  - `droid.close_dialog(bbox=None)`：全屏 OCR 只认「关闭窗口/关闭/取消/我知道了/×」这类按钮文字
    （长句不算），有 bbox 时只在这块范围里选并按"离弹层右上角最近"排序，没有 bbox 时标题带
    (y<10%) 一律不碰 —— 那是分享/更多；点一个核验一个，全都点不动才退系统返回。
  - `_do_gui_act` 新增 `close` 分支（结果带 `via: button|system`、`text`、`point`、`tried`），
    并把最近一次画面变化的 bbox 记下来当弹层作用域；两份 schema 的 action 枚举同步。
  - 新增 `_share_trap(x, y)`：`target` 没命中又退回坐标、而坐标落在标题栏右侧（x>55%）时**直接拒绝**
    并提示改用 `close` / `target` / `img_point`，不再"帮忙"点一下。
  - 知识卡与 SOP 同步：小程序标题栏右角是分享/更多、今日密码弹窗自带图标型关闭窗口、关弹层用 `close`。

- Task-start knowledge is now retrieved **into the anchor prompt** instead of being read by the model:
  `gacore/kb.py` scores `memory/kb/*.md` cards (front-matter + body) with a deterministic lexical
  ranker -- Chinese character bigrams (no jieba), BM25(k1=1.2, b=0.75), field weights
  (app/aliases x3, intent x2, body x1), confidence (verified 1.0 / pending 0.5) and a +5 bonus for the
  foreground package -- and `_kb_block()` injects the top 1-3 cards (<=1200 chars) on the first two
  turns plus once per app switch, never repeating a card. Evidence: every real session opened with two
  `file_read` calls (phone_use.md 318 lines served 60, app_cards.md 133 lines served 60) costing ~4s and
  often returning the wrong section; and the 09:45 delta-force run tapped the mini-program's title-bar
  share icon because nothing in context said where 查看今日密码 lives. Retrieval runs before the model
  speaks, so it costs no extra tool turn (a turn is 5-6s). Hot switch: `/kv.set ga.kbmode off`.
  `tools/kb_eval.py` pins recall@1/@3, the injection budget and the no-leak property on real task texts.
  任务开头的知识现在**检索进锚点**，而不是让模型自己去读：`gacore/kb.py` 用确定性词法打分
  （中文字符 bigram，不引 jieba；BM25 k1=1.2/b=0.75；字段权重 app/别名 x3、意图 x2、正文 x1；
  置信度 verified 1.0 / 待核 0.5；前台包名 +5）给 `memory/kb/*.md` 的卡片排序，`_kb_block()` 在前两轮
  以及每次换 App 时注入前 1-3 张（<=1200 字符），同一张卡不重复。依据：真机每个任务都先两次
  `file_read`（phone_use.md 318 行只给 60 行、app_cards.md 133 行只给 60 行）≈4s 且常拿到无关段落；
  09:45 的三角洲会话连标题栏右上角的分享都点开了，原因是上下文里没有任何一句说「查看今日密码」在哪。
  检索发生在模型说话之前，所以不额外花工具轮（一轮 5-6s）。热开关：`/kv.set ga.kbmode off`。
  `tools/kb_eval.py` 用真机任务原文把 recall@1/@3、注入预算与「无关查询零注入」钉住。

- `back` now means "go up one level", not "press the system back key": in mini-programs,
  self-drawn canvases and H5 pages the system back key is swallowed by the page, so pressing it
  changes nothing -- which is exactly how the 2026-10-30 09:15 session got stuck (the next task
  entry was one level up, and the only exits were the on-screen "返回/关闭" buttons).
  `droid.ui_back()` looks at the current frame first: OCR finds an on-screen 返回/关闭/取消/退出/×
  in the title band (falling back to the left-most title-bar icon when there is no text), taps it,
  and verifies the change; only when no such button exists -- or tapping it changes nothing -- does
  it fall back to the system back key. `gui_act action=back` routes through it and reports
  `via: button|system` plus the button text/point, so the model can tell "the page has no way back"
  from "I pressed the wrong thing".
  另外新增设置项「结束任务后返回桌面」(设置 → 通用设置 → 悬浮窗常开 下面): 开启后任务真正结束
  (done/error)时把设备退回桌面, 免得跑完还停在别人的 App 里。开关真值存原生
  `SharedPreferences("ga").home_after_task`(读桥 `GA.homeAfterTask()`), `GA.goHome()` 用 HOME
  intent(不需要悬浮窗/无障碍权限)。ask_user 那种"等你回话"的停点不触发——那是还要继续的任务。
  `back` 现在等于"回退一层"，而不是"按系统返回键"：小程序、自绘 canvas、H5 页面会把系统返回键
  吃掉，按了等于没按——2026-10-30 09:15 的会话就是这么卡住的（后续任务入口在上一级，唯一的出口
  是屏幕上那个「返回/关闭」按钮）。`droid.ui_back()` 先看当帧：OCR 在标题带里找「返回/关闭/取消/
  退出/×」（没有文字时退回标题栏最左边的图标），点它并核验画面变化；只有在屏上真没有这类按钮、
  或点了没反应时，才退回系统返回键。`gui_act action=back` 走这条路径，并回报
  `via: button|system` 与按钮文字/坐标，模型因此能区分"这页没有退路"和"我点错了东西"。

- Levels, stuck loops and entry knowledge: the 2026-10-30 09:15 session showed the trap
  a per-tap diff cannot see -- after reading "today's password" the next task entry was on
  the *parent* page, so the model kept tapping "cancel"/"close" inside the dialog layer; six
  taps in a row reported the same `diff: 85.850%` (same bbox), because the screen just
  alternated between two frames. Every diff said "changed", the agent never moved. Three
  things now come from the screen itself instead of from `diff`: (1) `droid.frame_digest()`
  fingerprints the frame already in hand, and when the last actions only ever visit ≤2
  distinct frames the result carries `layer_hint` telling the agent the target is one level
  **up** -- use `back`/the title-bar arrow/close the dialog instead of trying another pixel
  on this layer; (2) a tap that changes nothing is retried inside the same call, either on
  the next `target` candidate (`auto_retry.kind=target_alternate`) or on the
  image-to-screen converted point (`img_scale`), instead of spending another 5-6s round;
  (3) a missing `target` now answers with "not on this screen -- it is probably one level
  up, go back first" rather than "take a fresh observe". Entry knowledge also stops costing
  a turn: `memory/app_index.md` (where mini-programs / Moments / stickers / scan live, with
  unverified entries marked) is injected as `[KB]` on the first two turns only, and the L1
  insight now points at it before telling anyone to read a card.
  层级、原地打转与入口知识：2026-10-30 09:15 的会话暴露了 diff 看不见的陷阱——读完"今日密码"
  后，后续任务入口在**上一级**页面，模型却一直在弹窗层点"取消/关闭"；连续 6 次点击报的都是
  同一个 `diff: 85.850%`（连 bbox 都一样），因为画面只是在两帧之间来回切。每个 diff 都说"变了"，
  agent 一步没走。现在三件事改由画面本身判断，而不是 diff：① `droid.frame_digest()` 给手上的帧
  算指纹，最近几次动作只在 ≤2 个画面之间来回时，结果里带 `layer_hint` 告诉它目标在**上一级**——
  用 `back`/标题栏返回箭头/关掉弹窗，而不是在这一层再换一个像素；② 点空的 tap 在同一次调用里
  重试（换下一个 `target` 候选 `auto_retry.kind=target_alternate`，或换成"图坐标→设备像素"
  `img_scale`），不再白花 5–6s 一轮；③ `target` 找不到时的答复改成"这一层没有，它更可能在上一级，
  先回退"，而不是"再 observe 一次"。入口知识也不再花一轮：`memory/app_index.md`（小程序/朋友圈/
  表情包/扫一扫在哪，未实测的条目标「待核」）只在任务开头两轮以 `[KB]` 注入，L1 提示也改成先看它
  再决定要不要读卡片。

- Search results and target ambiguity: `gui_act action=search_app` now returns the
  rows it can read on this frame (`results: [{t,x,y}]`, device pixels) with the
  keyword, so "where is the first result" is an observation instead of a guess.
  Measured on device: the fast sessions typed the keyword, tapped a text target, and
  finished in 8 turns; the slow ones spent up to 24 turns re-guessing pixel positions
  with `diff` 0.010%/0.000% because they only had a 647x1440 image to measure on.
  Text targets also stop failing on ambiguity: same-name candidates are ranked
  (exact match first, then topmost) and one is used, with the rejected candidates and
  their `index` returned in the same result so `target_index` can correct it without
  another round trip; `target` alongside `point`/`rel` is now a label instead of a
  `ValueError`; and `search_app` accepts `value` / `query` / `target` / `text`.
  搜索结果与 target 歧义：`gui_act action=search_app` 现在把这一帧能读到的结果行
  （`results: [{t,x,y}]`，设备像素）随关键词一起带回——"第一条结果在哪"从猜变成读。真机
  实测：快的会话输入关键词、点文字目标，8 轮收工；慢的会话花 24 轮反复猜像素位置，
  `diff` 0.010%/0.000%，因为它手里只有一张 647×1440 的图可量。文字目标也不再因同名多解
  报错：候选按「完全相等 → 从上到下」排序后选一个，落选清单连同 `index` 在同一份结果里
  返回，`target_index` 不必多跑一轮；`target` 与 `point`/`rel` 同时给时当标注而不是
  `ValueError`；`search_app` 接受 `value` / `query` / `target` / `text` 四种写法。
- Coordinates: the screenshot attached to each turn is a *scaled* image (long side
  1440), but `point` means device pixels. The caption used to say "give `gui_act`
  `point` in this image's pixels", so the model did exactly that: on a 1200x2670
  screen with a 647x1440 image every tap landed at 1/1.86 of the intended position
  (up and left), and anything below image row 1440 — the bottom 46% of the screen —
  was unreachable. That is why `search_app` worked (no coordinates involved) and the
  self-drawn page right after the search "drifted badly". There is now a third named
  unit, `img_point` / `img_point1` / `img_point2` (pixels on the attached image), and
  the conversion to device pixels happens in `_resolve_point`; `point`, `rel` and
  `img_point` stay mutually exclusive so nothing is guessed from magnitudes. The
  per-turn image size is recorded with the turn (and cleared when no image is
  attached) because it is the conversion basis. A tap that changes nothing now also
  asks the question out loud (`coord_hint`: those pixels fit inside the attached
  image — did you measure them on it?), instead of only saying "small change".
  坐标：每轮附的截图是缩放过的（长边 1440），而 `point` 是设备像素。旧提示词说"按这张
  图的像素给 point"，模型照做——1200×2670 的屏幕配 647×1440 的图，每次点击都落在目标
  位置的 1/1.86 处（偏左偏上），图第 1440 行以下（屏幕下 46%）点不到。所以 `search_app`
  这类不给坐标的步骤很顺，搜索之后的自绘页面"漂得很厉害"。现在有第三个具名单位
  `img_point`（附图上的像素），换算在 `_resolve_point` 里做；`point`/`rel`/`img_point`
  三者互斥，仍然不从数值大小猜单位。附图尺寸随那一轮记录，没有附图时清空。"点了没变"时
  还会多问一句（`coord_hint`：这几个坐标落在附图尺寸内，是不是从图上量的）。
- Vision: whether a turn may carry a screenshot is now decided by a capability bit
  (`supports_images`) instead of a hard-coded list of class names. The old check
  compared `type(backend).__name__` against three names, which silently skipped
  `NativeOAISession` — the class the device actually runs — because its conversion
  path (`_msgs_claude2oai`) turns image blocks into `image_url` perfectly well; the
  exemption it was given ("it stringifies every message into the prompt") describes
  `ToolClient`/`BaseSession.ask`, not it. The cost was invisible: in a real 25-turn
  session not a single image ever reached the model (0 occurrences of the image
  caption, 0 image blocks in the transcript) while `obs_note` told the model
  "screenshot attached" 8 times, so it kept hunting coordinates blind. `obs_note` and
  `turn_content_blocks` now share one predicate, and the text-protocol case says the
  truth ("this session cannot receive images") instead of lying.
  看图与否改由能力位 `supports_images` 决定，不再比对类名白名单：旧判据漏掉了真机
  实际在跑的 `NativeOAISession`（它的转换路径完全能带图，被排除的理由描述的其实是
  `ToolClient`/`BaseSession.ask`）。代价是隐形的——真机 25 轮会话一帧图都没发出去，
  而 `obs_note` 还说了 8 次"截图已附"。现在两处共用一个谓词，文本协议会话如实告知。
- Search: `gui_act action='search_app'` performs "open the app → tap its search entry
  → type the keyword → read it back" as one step with a per-step verdict. The entry
  anchor is a 0-1000 relative coordinate (resolution independent); nothing in the
  business flow is hard-coded. In the real session the model spent a `see` call
  (16.3s) to rediscover the magnifier position that `phone_use.md` had already
  recorded (returned rx=830, ry=79 — the documented value). `recipe_list()` also
  advertises the builtin entry path now, and tolerates a missing `memory/recipes/`
  directory instead of always returning an empty list.
  `gui_act action='search_app'` 把"打开 App→点搜索入口→输入关键词→回读"做成一步，
  每步都有判据。入口锚点是 0-1000 相对坐标（与分辨率无关），业务页坐标一个都不写死。
  真机里模型为了让视觉重新发现文档里早写好的放大镜位置，花了一次 16.3s 的 see。
- Actions: an action now counts as "proved" only by evidence about *that* action.
  `launch` requires the foreground to be the requested package (it used to accept any
  non-empty foreground, so a failed launch looked successful and skipped
  `wait_stable`); the post-action frame is tagged with its package and is never
  reused across apps; and a large screen change (diff ≥ 30%) re-takes a frame after a
  short settle instead of reusing the pending one, which is a transition frame.
  动作核验改成"只认这个动作自己的证据"：launch 要求前台确实是要拉起的包；动作后验帧
  带包名，跨 App 不复用；大跳变（≥30%）重新截一帧而不是复用过渡帧。
- Observability: read-only tools (`see`/`ocr`/`observe`) now write to the phone
  ledger, and repeating the same channel on an unchanged screen raises `[OBS-GUARD]`.
  The ledger only ever recorded actions, so a session that burned 11 `see` calls
  (164s) circling the same screen was invisible to both `[LOOP-GUARD]` and the
  every-7-turns strategy warning. `see` keeps the cheaper gates first (cache hit,
  once-per-turn) and this one last, so a cached answer is never turned into a refusal.
  只读工具（see/ocr/observe）开始记入账本，同屏同通道重复会给出 `[OBS-GUARD]`；
  see 保留"缓存命中→每轮一次"这两档在前，本档在最后，避免把已有答案变成拒绝。
- Anchor prompt: the original task statement is re-injected every turn as `[GOAL]`,
  with `[DONE]` milestones and the last `[UNMET]` expectation. A real run drifted from
  "look at the ladder inside the deck" to "find the ladder" before it had even entered
  the deck, because `<history>` only keeps the last 30 lines (older lines fold into
  summaries) and nothing restated the goal. Turns that made GUI actions without a
  verifiable result also can no longer end silently — the model must call
  `finish_task` (done/blocked) or `ask_user` instead of stopping with a checkpoint
  note, which is how a 25-turn run ended with the user receiving nothing.
  锚点每轮重注原始任务（`[GOAL]`+`[DONE]`+`[UNMET]`）；有 GUI 动作但没有可核验结果的
  轮次不再允许静默退出，必须 `finish_task`(done/blocked) 或 `ask_user`。
- Structured actions: `gui_act` now accepts pixel coordinates as well as 0-1000
  normalized ones — any value over 1000 can only be a pixel, since the normalized
  ceiling is exactly 1000, so the reading is unambiguous. A real 46-turn session
  wasted 7 whole turns on `ValueError: point must be 0-1000 normalized, got
  [752, 2512]` — half of every error in 145 tool results, and the single largest
  failure source. The cause was a contract contradiction: the schema told the
  model the point "must come from the current observation (dump bounds or
  look() box)", but both report pixels while the tool demanded 0-1000, so
  following the instruction guaranteed the error. The schema and `phone_use.md`
  §0.2 now state the conversion (`rx = round(x * 1000 / screen_w)`) and say that
  raw dump/look coordinates are accepted too.
  结构化动作现在同时收像素与 0-1000 归一化坐标（>1000 只可能是像素，无歧义）。
  真机 46 轮会话有 7 个轮次整个废在坐标单位报错上，占 145 个 tool_result 里全部
  错误的一半，是最大的单一失败源。根因是契约矛盾：schema 让模型"point 取自 dump
  bounds 或 look() box"，而那两处给的是像素，与 0-1000 的要求自相矛盾。schema 与
  phone_use.md §0.2 现在写明换算公式，并说明原始 dump/look 坐标也可直接传入。
- Structured actions: `phone_use.md` §1 now documents `ocr(img)` — it needs the
  image argument, and a bare `droid.ocr()` raises `TypeError: missing 1 required
  positional argument: 'img'` (observed on a real device). §0.1 already told the
  model to use `droid.ocr()`, but only `ocr_text` was documented.
  §1 补齐 `ocr(img)` 文档：它必须传图片参数，裸调会 TypeError（真机中过）。
- Latency: `BaseSession.history` is now capped by message count
  (`max_history_msgs`, default 20) before the size-based trim runs. Every turn
  re-sends the whole history, so an uncapped count makes per-turn cost grow
  linearly and total time quadratically: a real 19-turn run went from 829 to
  50017 re-sent characters (60x) and `model_wait` from 3.1s to 32.5s, and the
  user cancelled it for being too slow. The size cap (`context_win * 3`, up to
  90k characters) was never reached, because compression only shrinks each
  message, not the number of them. The head (task description) and the most
  recent turns are kept; older turns are covered by the working memory the anchor
  prompt injects each turn.
  每轮重发全部历史，条数不封顶则单轮成本线性涨、总时间平方涨。真机 19 轮 resend
  829→50017 字符（60x）、model_wait 3.1s→32.5s，用户因太慢取消。体积上限高达 9 万
  字符根本等不到——压缩只压单条长度，压不掉条数。保留首条与最近轮次。
- Diagnostics: an aborted or failed run now gets a backfilled
  `end_reason='unfinished'` summary. `agent_after` is not in a `finally`, so it
  never fires when the loop raises, and the previous backfill read the recorder
  from thread-local storage — but each task runs on its own thread, so the dead
  task's recorder was unreachable and the backfill could never run. Five
  consecutive aborted runs left no summary at all on a real device. The backfill
  now re-checks the previous run's file, which works across threads and
  processes, and the regression test drives the next task on a real second
  thread — the original single-threaded test could not catch this.
  中止/异常时 agent_after 不触发；原补写读线程局部的 recorder，而每个任务独立线程，
  上个任务的 recorder 谁也读不到，真机连续 5 次中止全无汇总行。改为按文件复查，
  跨线程/跨进程都生效；回归测试改用真实第二线程复现。
- Diagnostics: each session now appends a per-turn run record to
  `temp/model_responses/sessions/metrics_<id>.jsonl` — model wait, tool execution and
  post-action verification time, input/output tokens, re-sent history size, and the
  verifier that produced each verdict, plus a run summary with P50/P95 and five mutually
  exclusive verdict counters. Recording is observation only: it adds no model calls and no
  device operations, and a failed write never affects the task. The structured action
  channel (`gui_act`) made tool-level verdicts attributable: `extract_verdict` now parses
  its JSON-string result and `attrib_verifier` maps it back to the existing droid verifier
  (`_img_diff_str` / `_scroll_verdict` / `_classify_paste_rows`). `layer` is still the
  single existing `L4` with no router behind it.
  每个会话追加一份按 turn 的记录：模型等待、工具执行与动作后验耗时、输入输出 token、
  重发历史大小与每轮判定来源，附 P50/P95 与五个互斥的判定计数器。只观察，不增加模型调用与
  设备操作，写盘失败不影响任务。结构化动作通道（gui_act）落地后工具级判定已可归因：
  `extract_verdict` 解析它的 JSON 字符串结果，`attrib_verifier` 归回 droid 侧既有判定函数。
  `layer` 仍只有现存的 L4，背后还没有路由器。
- Run metrics: the verdict counters are now five mutually exclusive buckets —
  `tools_verified`, `tools_uncertain`, `tools_negative`, `tools_pixel_evidence`,
  `tools_no_verdict` — with precedence `uncertain > verified > negative > pixel > none`.
  A record carrying only `diff_pct` used to fall through every boolean test and land in
  `tools_no_verdict`, which reported 42/45 "no verdict" and a 0% verified-action rate for a
  real 46-turn run in which 16 `gui_act` actions had pixel evidence. Those records now go to
  `tools_pixel_evidence`: a changed screen proves neither success nor failure, so it is
  neither counted as success nor as a silent failure. Precedence also fixes a latent
  double count — `{'hit': True, 'uncertain': True}` was tallied as both verified and
  uncertain, pushing the sum past `tools_total` and driving `tools_no_verdict` negative.
  判定计数器改为五个互斥桶，优先级 uncertain > verified > negative > pixel > none。
  只带 `diff_pct` 的记录原先穿透所有布尔判定落进 `tools_no_verdict`，导致真机 46 轮运行
  报出 42/45"无判定"、verified-action rate 显示 0%（其中 16 次 gui_act 其实有像素证据）。
  这类记录现在进 `tools_pixel_evidence`：屏幕变了证不出成功也证不出失败，既不算成功也不算
  静默失败。优先级同时修掉一处潜在双记——`{'hit': True, 'uncertain': True}` 曾同时计入
  verified 与 uncertain，使五桶相加越过 `tools_total`、把 `tools_no_verdict` 算成负数。
- Device observation: `droid.dump_state()` returns `{nodes, degraded, pkg}` so an empty
  tree can be told apart from a policy blank (sensitive app) and an unresolved foreground;
  `dump()` delegates to it and keeps its list contract, and the `droid_dump_blank` metric
  event is unchanged. SPEC W5.
  树观测带降级原因码：`dump_state()` 区分策略置空/前台未解析/真空树；`dump()` 契约不变。
- Loop guard (SPEC W3): a process-wide action ledger (`phone_ledger`) records verified
  tap/swipe/paste/scroll outcomes; the execution boundary substitutes bounded recoveries
  (tap: WAIT→BACK→HOME→ABORT; input: REFOCUS→RETRY→ABORT), refuses repeated no-effect
  actions from the fifth equivalent attempt, and each turn injects a `[LOOP-GUARD]` hint
  when equivalence or a stuck screen is detected. Only verified facts are recorded;
  productive scrolls and screen changes reset the counters. The ledger is cleared at every
  task boundary, recovery is skipped under a policy-sensitive foreground, and "no
  observable change" uses the same ≤0.05% band as the existing miss hint.
  循环守卫：动作账本 + 三档干预（提示/改写/拒绝），全部有界；只落已验证事实；任务边界清账。

## 2.33.8 / 141 — 2026-10-25 (open-source prerelease / 开源预发布)

- Web tool: the foreground browser's screenshot no longer times out on Android WebView,
  so `open_url` works on the first try (on a MEIZU 21 every web task used to lose about
  45 s and two failed calls); a failed screenshot no longer discards an opened page.
  前台浏览器截图不再超时，网页任务不再先失败两次。
- Privacy: images in model replies are not fetched from the network (a prompt-injected
  reply could carry chat text in an image URL), and the quick-record activity is no
  longer exported, so other apps cannot make GAgent start the microphone. The launcher
  shortcuts now target this app. 回复中的远程图片不再自动加载；其他 App 不能再让 GAgent 开麦；
  桌面快捷方式改为指向本应用。
- A finished task posts one notification instead of two; idle shows “待命/Idle” instead
  of “idle”; “1 step” instead of “1 steps”; the placeholder translate button is hidden.
  完成只发一条通知；待命状态本地化；单数步数；隐藏未实现的翻译键。

## 2.33.7 / 140 — 2026-10-25 (open-source prerelease / 开源预发布)

- A task whose last model call failed (for example HTTP 429 when a provider quota runs
  out) is reported as “Error” on the floating capsule, in the task status and in the
  chat's end-of-task divider (“Task failed”), not as a green “Done”.
  末轮模型请求失败（如额度用尽返回 429）的任务在浮窗、状态和会话结尾都显示“出错”，不再显示绿色完成。
- Wireless ADB: when the phone no longer trusts GAgent's key, `droid.adb_connect()` now
  says re-pairing is needed instead of “wireless debugging may be off”, and Settings
  shows “Re-pair needed” as soon as it opens. 手机撤销信任时自连报错改为明确提示重新配对；
  设置页打开即刷新“需重新配对”状态。

## 2.33.6 / 139 — 2026-10-25 (open-source prerelease / 开源预发布)

- PC Link offers an explicit **Use the public GenericAgent relay** preset in Optional
  modules. It fills the form only after you confirm its note (the access value is the
  one already public in the GenericAgent desktop client and is not a password) and is
  used only after Save; there is still no default. PC Link 新增需确认的公共中继预设，不是默认值。
- Reasoning-effort and provider changes now reach every open conversation instead of
  only the first one. 推理强度等服务商变更会同步到所有会话。
- A task that ends by asking you shows “Reply needed” on the floating capsule instead
  of a green “Done”. 以提问结束的任务，浮窗显示“需要你回复”而不是绿色完成。
- Wireless ADB shows “Re-pair needed” when the phone no longer trusts GAgent's key.
  手机撤销无线调试信任后显示“需重新配对”。
- Troubleshooting explains that some OEMs turn accessibility off after a force stop
  and how to restore it automatically. 说明部分厂商强制停止后会关闭无障碍及自动恢复方法。

- PC Link no longer ships a build-injected relay default. CI stops writing
  `pclink_defaults.json`, the APK audit rejects that asset, and runtime ignores a
  stale copy from older builds; configure your own relay URL and credential in
  Optional modules. PC Link 不再在构建中注入默认中继凭据：CI 不写入、APK 审计拒绝该文件、
  运行时忽略旧版残留，请在可选组件填写自己的中继地址与凭据。
  Optional modules no longer claim a blank PC Link URL restores a default; an
  unconfigured PC Link tap opens its relay fields. 可选组件页去掉“清空恢复默认”的旧说明。
- System back closes only the topmost layer, ordered by the layers' own stacking:
  dialogs and the detector close before the page beneath, stacked sheets step back
  one level, and back on the first-run consent leaves the app instead of dismissing
  it (which left a blank window). Settings sub-pages open at the top and restore the
  parent position on back, with an interruptible enter that is instant under reduced
  motion; fading scrims no longer swallow taps. Scrims use one theme token (darker in
  dark mode) and a re-opened lower sheet is drawn on top. 系统返回只关最上层；首启同意页不再被返回关掉；
  设置子页还原父页位置，遵守减少动态效果；遮罩改用主题色值，暗色更深。
- PC Link reconnects that finish after unlinking, or during a new pairing, are
  discarded, and unlinking during a pending pairing cancels it, so an unpaired phone
  does not reconnect. 解除配对后或新配对期间迟到的重连会被丢弃，配对进行中解除会先取消配对。
- Choosing the default reasoning effort removes a previously saved level instead of
  keeping it while the UI shows the default. 推理强度切回默认时会真正清除已保存的档位。
- Streaming voice checks its configuration before asking for the microphone and
  opens the voice settings when unset. 语音未配置时不再先申请麦克风。
- A local bus start failure no longer stops the app from opening, and crash capture
  starts first. 本机总线启动失败不再导致应用打不开。
- Detector boxes are clipped to the observed screen. Main-model requests and
  observation hops record timing for slow-task attribution (observe-only).
  检测框限制在屏幕内；记录主模型请求与观察步骤耗时（只观察，不改行为）。

- The floating capsule and task-end notification no longer report a user-stopped
  or failed task as "✔ Done": the core now exposes an `end` reason
  (`done`/`stopped`/`error`) and the capsule shows "■ 已停止" (no alert) or a red
  "⚠ 出错". 悬浮胶囊不再把用户中止或出错的任务显示为「完成」。
- Rebuild optional-module settings (PC Link, mesh, GAnet, streaming voice, APK
  build service) as a themed settings page with labelled fields, status chips and
  inline errors; settings secondary text now meets WCAG AA in light and dark.
  可选组件设置改为统一主题的设置子页；设置页次要文字在浅/暗色下满足对比度要求。
- Configured provider rows show their model names in readable secondary text.
  服务商列表中的模型名改用可读的次要文字颜色。
- Placeholder hints (chat composer, drawer search, optional-module `wss://`
  examples and the saved-token hint) now meet WCAG AA; the contrast test checks
  `::placeholder` of empty fields. 输入框占位提示在浅/暗色下达到对比度要求。
- The floating capsule's transparency preference now fades only the capsule
  body; status text stays opaque (white with a dark halo when the body is too
  transparent), so "✔ 完成" stays readable at 30%. 悬浮胶囊透明度只淡化底色，文字保持可读，偏好值不变。
- Exclude GAgent's own overlay windows from `droid.shot()` frames so OCR, the UI
  detector and vision models no longer read the status capsule's text.
  截图抹平 GA 自身悬浮窗区域，避免 OCR/视觉模型读到自己的状态文字。
- Virtual display: refuse to move a task the user has in the foreground, reject
  points outside the display, require frames newer than the last input and write
  a trailing frame after motion stops (frame metadata includes size and PID).
  离屏虚拟屏：拒绝抢占用户前台同一 App、坐标越界拒绝、帧须新于最近输入并补尾帧。
- Agent guidance uses view-direction `scroll_view()` consistently and warns that
  `back()` may leave the page instead of closing an in-page drawer.
- Destroy the previous chat WebView when the system theme, locale or font size
  recreates the main screen, so stale pages stop polling in the background.
  系统深浅色等配置变更重建主界面时销毁旧 WebView，避免旧页面继续后台轮询。
- Document why YOLO weights stay user-installed and the permissive alternatives
  for a bundled detector. 说明 YOLO 不内置的原因及可再分发的替代路线。

- Fix virtual-display adapter import: load `os` before reading the installation's
  package identity; cover default and debug identities without device access.
- Present the public source preview with a sourced DeepSeek Android comparison,
  scoped core-size claims, memory/token guidance and optional workflow setup.

- Add the GAgent logo, redesigned bilingual landing pages, ecosystem/download
  navigation, practical case guides and evidence-linked development milestones.
- Add a complete capability setup matrix and importable service-profile example;
  clarify YOLO installation, visual-model setup and independent verification.
- Permit reviewed public website navigation in source docs while retaining
  credential, runtime-endpoint and APK/archive checks; add focused regressions.
- Rewrite English and Chinese READMEs around actual capabilities, setup and limits.
- Add first-run, development, testing, troubleshooting, validation and release guides.
- Define contribution/review requirements, bilingual PR and issue templates,
  project decisions and community conduct.
- Correct provider-settings copy: keys are stored locally and sent to the chosen
  provider for authentication.
- Document unresolved native dependencies, physical-device coverage and optional
  module/YOLO licensing boundaries without treating them as completed work.

## 2.33.3 / 136 — 2026-10-23 candidate

- Honor provider proxy configuration in visual requests and expose one lazy
  `droid.ask_vision` entry.
- Request correction for malformed text tool calls instead of silently ending;
  reject malformed mixed batches without partial execution.
- Observe active system panels correctly and expose slider bounds/current values.
- Validate visual detector arguments and clarify GUI selection/clipboard feedback.
- Bind gestures to explicit observed display geometry; reject stale or
  out-of-bounds coordinates, including same-size 180° rotation.
- Restore task overlays when the app moves to the background, honor always-on
  in visual-only apps and constrain overlay placement after display changes.

See [Validation](docs/VALIDATION.md): the representative task sample still has
partial and blocked outcomes. Real foldable/OEM coverage and native dependency
migration remain open.

## Earlier extraction / 早期剥离

The initial repository combined Android beta 2.33.0 / 133 with later PC Link
changes, starting a clean source history at 2.33.1 / 134. The 2.33.2 / 135 candidate
established the visual-only WeChat policy and optional detector guidance.
Mandatory commercial/account flows, bundled service authority and source
encryption were removed from this distribution; original attribution and necessary
Kotlin device code remain. See [Feature scope](docs/FEATURE_SCOPE.md) and
[Extraction review](docs/REVIEW.md).
