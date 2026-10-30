# GAgent 赋能 Spec：混合式手机 Agent 增强设计（增补篇）

> 定位：本文是 `docs/SPEC.md`（五层混合架构 L0-L4）的**增补与实施细化**，不替换、不改动其红线。
> 输入：① GAgent 源码三层分析（Kotlin 总线 / Python 核 / 文档测试）② 2026-10-26 真机适配验证（StepOS PZ261A / Android 16 / SM8845 / 16GB）③ 外部研究：mobile-agent 源码级分析、GELab-Zero-4B（Step-GUI Edge）、V-Droid（MobiCom 2026）、豆包手机 M153 逆向、UI-TARS/OmniParser/FastVLM 等论文调研。
> 姊妹文档：《GUI-Agent成熟实现调研.md》《mobile-agent-GUI实现分析.md》《豆包手机实现调研.md》《Amoo-ADB-GUI方案.md》《Amoo-端侧GUI方案.md》（均在 E:\project\daiyimo\）。
> 状态：设计完成，待用户对第八节决策点（D1-D8）拍板后进入实施。

> **2026-10-26 实施记录（第一轮）**：W4 关闭（前提被推翻，见 §1.2）、W5 与 W3 已实现并真机验证（commit f357556 / 3fc9709 / 0544dbf / 1c52a08，52 个新测试，全套 448 passed / 38 failed+5 errors 均为预存 Playwright/GBK 环境问题）。agent 面对契约已同步（memory/phone_use.md §0.5-7 循环守卫）。执行台账与全部 Ruling：`.superpowers/sdd/GAgent赋能Spec/progress.md`。其余工作项（W1/W2/W6-W10、P0 验证项）与 D1-D8 决策点状态不变。

---

## 1. 实机适配基线（2026-10-26 实测，全部可复现）

设备上跑的是 2.33.3-debug（仓库已到 2.33.8），无障碍已绑定，capabilities=161（读窗口+手势+截图），事件订阅 3 类窗口事件。

### 1.1 已验证（passed）

| 项 | 结果 | 对 spec 的意义 |
|---|---|---|
| 总线 API | 端口转发后全端点可用：`/ping`（pkg/rot/w/h 真值）、`/a11y/dump?full=1`、`/a11y/shot?q=`、`/a11y/act`（tap/swipe/paste/key/launch/back/home/pkgs）、`/onnx/info+run`、`/adb/*`、`/web/*`、`/notifications` | 设备层无需新建，spec 全部增强都落在 L1-L4 调用侧 |
| 截图延迟 | GAgent 界面 142ms/290KB；王者荣耀 110ms/172KB（JPEG q80） | 与豆包手机 250KB/帧同量级；视觉通道每步成本 ~0.15s，可接受 |
| 游戏（王者荣耀 SurfaceView） | dump 仅 1 节点（"Game view"）；**截图正常出图**；`/ping` 正确报 rot=1、2670×1200 | S5/S6 场景确认"树不可用但视觉可用"；旋转由 ping 真值处理 |
| 微信（visual-only） | `dump()` 返回 `[]`（策略置空，非树真空） | S2 红线在本机生效；但**空数组丢失了"树真空 vs 策略置空"的区分**——spec 要求 ping/dump 增加降级原因码 |
| 设置页（高信息对照） | 47 节点 / 16 文本 / 13 可点 | S1 场景锚点 |
| 中文输入 | `paste`（剪贴板+ACTION_PASTE）中文完整上屏，草稿可清 | 与 ADB 路线 `input text` 中文 NPE 对比，端侧 paste 是正解 |
| 端侧 ONNX | PP-OCR det 模型经 `/onnx/info` 加载成功，`/ping.loaded` 出现该路径 | L2/L3 的端侧推理通道已通 |
| Shizuku 通道 | `/adb/status` 报 `shizuku=true` | StepOS 全屏启动的第二通道就绪 |

### 1.2 已验证的缺口（failed / 需修）

| 项 | 结果 | 归属 |
|---|---|---|
| `pkgs` 模糊匹配 | ~~只搜包名不搜中文名~~ **前提被推翻（2026-10-26 更正）**：首次实测用 curl 传中文被 Git Bash 编码破坏出现假阴性；改用 Python 显式 UTF-8 后「王者/微信/设置」全部唯一命中——label 匹配自初始框架提交即存在（BusA11yService.kt:431） | W4 关闭，无代码变更 |
| self-ADB | 无线调试未开 → `/adb/shell` 报"无法建立自连"；`vd_*`（虚拟屏/离屏 App）因此**当前整链不可用**；叠加 StepOS 虚拟屏放 Activity 必崩 system_server 的历史结论，本机执行通道**只走 a11y 前台路线** | 适配结论 A1 |
| YOLO 权重 | 设备未装 → `look()` 实际退化为**纯 OCR**，S2/S4/S5 的控件级定位只剩 ask_vision | W1（P0 验证项） |
| dump 降级不可观测 | 微信 `[]` 与"树真空"同形，L0 路由器无法区分"策略置空/FLAG_SECURE/真真空" | W5 |

### 1.3 未验证（untested / blocked）

- **FLAG_SECURE 页面**：本机无银行类 App 可测；Kotlin 已有"登录浏览器前台显式报错"分支，真机行为待测（P0-V2）。
- **YOLO 端侧延迟**：HF 只有 best.pt 无 ONNX，需按 `docs/OPTIONAL_YOLO.md` 配方导出后实测 SM8845（参照：魅族 21 上 640 输入 165ms/35 框、首跑 5009ms 含加载）（P0-V1）。
- **无障碍崩溃恢复**：用户历史日志有一次"视觉识别超时→服务崩溃→按 SOP 手动恢复"；A11yPersist 的写回机制存在，但崩溃根因（vision 超时）未定位（P0-V3）。

---

## 2. 研究发现 → 分层增强映射（总表）

| # | 研究发现（来源） | 增强点 | 落入层 | 触碰红线？ |
|---|---|---|---|---|
| F1 | GELab-Zero-4B-preview：AndroidWorld 75.86%（超 UI-TARS-1.5 的 64.2%），Apache-2.0，GGUF Q4 仅 2.2GB，`locate` 式结构化输出；其工程基建（状态压缩/动作执行/包名推断）与 GAgent 的 droid 同构 | L3 的**具体模型选型**（SPEC 4.4 只定义了接口没定模型） | L3 | 否 |
| F2 | V-Droid（MobiCom 2026）：LLM 当验证器不当生成器；**离散动作空间+prefill-only**；4.3s/步、比现有 agent 快 6.1× | ① L2/L3 用"候选编号选择"替代坐标生成 ② 终态验证器机制 | L2/L3 + 横切 | 半条（见 D3） |
| F3 | mobile-agent：ActionOutcome 三层账（DISPATCHED/SETTLED/REJECTED + screenshot_exactly_same + foreground_identity_changed）；**三档防循环**（提示→改写→执行边界拒绝）；40px 等价；有界恢复阶梯；长列表扫描豁免 | ① 动作结算账本结构化 ② **防循环/停滞检测**（GAgent 现状只有轮数告警） | 横切（L1-L4 共用） | 否（检测+有界恢复是对"无未知结果重试"的加强） |
| F4 | mobile-agent/GELab：prompt 缓存靠**稳定消息前缀**；GAgent 现状 `llmcore.py:880` 把历史拍成单条 user 字符串，每轮全量重发（SPEC 2.2 已测：88s→42s 证明输出量主导） | L4 时延优化：稳定前缀+动态尾部（provider adapter 层） | L4 适配器 | 否（不改循环，改消息构造） |
| F5 | 豆包手机：7 个离散指令、3-5s/步云端往返（要避免的速度）、**拒绝操作清单+金融类主动限制**、虚拟屏后台执行 | ① 动作空间收敛验证 ② **风控策略代码化**（GAgent 现状是 SOP 散文约束） | 横切 | 半条（见 D4） |
| F6 | FastVLM（TTFT 85×）、ShowUI-2B（UI 引导 token 选择）、骁龙 NPU 实测（编码器 20-45×、decode 仅 1.18×） | L3 端侧部署的效率手法与**预期管理**（decode 是瓶颈） | L3 | 否 |
| F7 | ScopeMem（冻结 VLM+修订记忆追平专用模型）、LearnGUI（经验学习） | 轨迹经验检索（L4 raw sessions 已落盘但无检索层） | L1/L3 之间 | 否（先用 difflib，不引向量库） |
| F8 | GELab `local_state_compress_server.py`：10 步一压状态压缩 | 长任务上下文管理（GAgent 已有 compress_history_tags，补**轨迹状态机式压缩**） | L1/L4 | 否 |
| F9 | SPA-Bench（ICLR25 Spotlight，中英+7 指标含资源消耗）、AndroidDaily（3146 静态+235 端到端） | 评测 harness（SPEC 7 有指标无外部基准） | 横切 | 否 |
| F10 | OmniParser 两阶段（检测+描述，ScreenSpotPro 39.5%）vs 当前 YOLOv8n（无指标） | 检测器备选与自训路线（a11y dump 即免费标注源——OPTIONAL_YOLO.md 方案 C 已写明） | L2 | 否 |

---

## 3. 分层增强详设

### 3.1 L0 Router：把"场景判据"机械化

SPEC 5.1 的决策顺序不变，补三个机械化判据（全部纯函数）：

1. **降级原因码**（W5）：`Observation` 增加 `degraded: {reason: "policy_blank"|"secure_window"|"tree_empty"|"vision_timeout", source}`。`dump()==[]` 时必须能区分"微信策略置空"（走视觉）与"FLAG_SECURE"（停手报错）与"真真空"（走视觉）。这是路由器不变式 1（不选证据缺失通道）的前提。
2. **低信息闸门**（W2）：树节点数 < K 或可点=0 → 判 S2-S7，直接路由 L2 视觉候选，不再浪费一轮 L4。K 按场景表配置（S1 阈值 vs S5 阈值不同），纯函数+合成 fixture 可测。
3. **中文应用名解析**（W4）：`pkgs` 增补 label 匹配（NFKC+casefold+去空白唯一命中），未命中再落 LLM 消歧（GELab 三级 fallback 的最轻量版）。这是通用接口缺陷修复，不是 per-app 补丁。

### 3.2 L1 Recipe Executor：状态压缩 + 稳定标记

- 沿用 SPEC 4.2 schema（intent+locator 不存坐标、既有 verifier、失败即升级、两次升级标 unstable）——**不变**。
- 增补 F8：recipe 执行时每 10 步做一次轨迹状态压缩（保留最近 10 步滑窗 + 里程碑摘要），防长 recipe 上下文膨胀。压缩函数纯函数化（输入步骤列表，输出折叠摘要），可单测。
- 增补 F3 的 collection 豁免：滚动类 recipe 步骤若每步都产出新证据（`_scroll_verdict` 通过），不计入循环检测——防把"长列表有效扫描"误杀。

### 3.3 L2 Local Reactive Controller：候选选择 + SoM 编号

- 沿用 SPEC 4.3（候选 id 选择、scroll-until-found、置信门限）——**不变**。
- 增补 F2 的**离散动作空间**：L2 输出结构化为 `{action: TAP_CANDIDATE|SWIPE_DIR|TYPE_TEXT|OBSERVE|ESCALATE, candidate_id?, dir?, text?}`，与豆包 7 指令、GELab/UI-TARS 动作空间对齐；坐标永远由端侧从候选框解析，**任何层都不生成原始坐标**（与现有 `tap_rel` 禁令一致，是其强化）。
- 增补 **SoM 编号图**（W6）：`look()` 输出候选后，端侧在截图上画编号框（红/蓝双色，参考 mobile-agent 的标注实现），仅用于 L3/L4 的视觉输入与人工核验；编号→bbox 映射表随请求传递。**标注图不进 L2**（L2 只用结构化候选）。
- 前置修复（SPEC Phase 2 验收已列）：`look()` 缓存键补 `package + rotation`（`droid.py:543`）。

### 3.4 L3 Grounded GUI Actor：GELab-Zero-4B 落地（核心增强）

SPEC 4.4 定义接口 `locate(observation, intent) -> candidates | not_found`，未定模型。选型：

| 候选 | 许可 | 体积 | 证据 | 结论 |
|---|---|---|---|---|
| **GELab-Zero-4B-preview**（推荐） | Apache-2.0（权重+代码） | BF16 8.9GB / **GGUF Q4 2.2GB** | AndroidWorld 75.86%、AndroidDaily 静态 73.4%（UI-TARS-1.5 47.0%）；**设备同源**（stepos-gui-agent 的开放版） | ✅ 首选。且其 repo 自带 ADB 执行器/状态压缩/包名推断，与 droid 层可互校 |
| ShowUI-2B | MIT | ~4GB | ScreenSpot-Pro 仅 7.7（最难基准弱） | 备选 |
| OS-Atlas-4B | 见仓库 | ~8GB | grounding 基础模型，可微调 | 自训路线基座 |
| 云端 pinned endpoint（阶跃 Step-GUI API） | 服务条款 | 0 | 官方口径同上 | 过渡/对照 |

**部署形态（D2 待拍板）**：
- 形态 A（推荐先做）：PC/局域网推理端点，`locate()` 走 HTTP。零端侧成本、可随时换模型；手机侧只传截图+意图，回传候选编号。**注意**：这会在截图出设备——与微信 visual-only 的隐私姿态冲突，需按 App 分级（敏感 App 禁用形态 A，降级 L2 OCR-only + ask_vision 已有通道）。
- 形态 B（产品化）：端侧 GGUF Q4 经 llama.cpp（Chaquopy 原生库）或 ExecuTorch/QNN。SM8845 + 16GB 内存可行；**预期管理**：骁龙实测 decode NPU 仅 1.18×，4B Q4 端侧 decode ~5-15 tok/s → 单步 3-8s，比形态 A 慢、比 L4 快。且需动构建链（`build_pure_wheels.py` + gradle 原生库步骤）——这是 D2 的核心代价。

**接口契约**（遵循 SPEC 4.4 可换性要求）：
```python
def locate(observation: Observation, intent: str) -> list[Candidate] | NOT_FOUND
# Candidate: {id, bbox(物理像素), label, cls, score, source: "yolo"|"ocr"|"a11y"|"vlm"}
# 约束：结构化输出；malformed/empty → NOT_FOUND（升级，永不猜坐标）；
#       同一 stub 实现必须通过与真实模型相同的测试（SPEC Phase 4 验收原句）
```

**与现有 `look()` 的关系**：L3 是 `look()` 的语义增强——`look()` 给候选框，L3 在候选+裁切片上做"是/不是这个"的判定（F2 的 verifier 用法），而不是重新全场定位。这保住了 L2 的零模型调用性质。

### 3.5 L4 General Agent：两处适配器级增强（不改循环）

1. **多模态观察工具化**（D6）：现状主 LLM 看不到截图（`phone_use.md:43` 明示；llmcore 有 image block 能力但无人构造）。**不建议**给 L4 开截图通道（触碰"VLM 坐标禁令"红线且推翻既有安全姿态）；改为把 `look()` 候选表 + SoM 编号图作为 `code_run` 内的**结构化观察结果**注入（已经是现状），L3 才消费图像。如未来要开，须先修订红线——列为 D6。
2. **Prompt 稳定前缀**（W7，F4）：`llmcore.py:880` 的 prompt 扁平化每轮全量重发。优化：系统提示+工具 schema+任务目标组成稳定前缀（Claude 侧已打 `persistent`/`ephemeral` 缓存标记，问题是前缀本身不稳定）；动态尾部 = 最近 N 步 + 当前观察。**验收必须带 Phase 0 指标的 before/after**（re-sent history size、P50/P95、output tokens），无数据不回滚不合并。

### 3.6 横切一：动作结算账本 + 三档防循环（W3，F3）

现状：tap/swipe/paste/scroll 已有像素 diff + uncertain（强项），但**无重复动作检测、无全局停滞检测**。

新增（全部在 droid 执行边界与 agent_loop hook 上实现，不新增执行路径）：
1. **ActionOutcome 账本**：每个动作记录 `{action, params, dispatched_at, settled: {screenshot_exactly_same, foreground_changed, diff_pct, verdict, uncertain}}`——前三个字段 GAgent 已在算，缺的是**结构化落账**供循环检测消费。
2. **等价判定**：同类型 + 坐标欧氏距离 ≤40px（0-1000 归一化域，≈本机 48px）；TYPE 比 value+point；滑动比起终点。纯函数。
3. **三档干预**：
   - 提示级：等价动作 ×5 / ABAB 序列 / 5 步内 TYPE×4 / 界面粘滞（4 步每步截图全一致且动作 ≥3 种）→ 注入 hint 文案（带 ABCD 强制选项，mobile-agent 实测有效）；
   - 改写级：连续 3 次等价 TAP 且截图全一致 → WAIT(1s)→BACK→HOME→**ABORT**；连续 2 次等价 TEXT 无变化 → 重聚焦 → 重试 → **ABORT**（私有 marker 从账本计数，不引新状态机）；
   - 拒绝级：最近 5 步全部 SETTLED + 截图全一致 + 动作等价 → **拒绝下发**，`REJECTED` 入账；屏幕一变或换动作自动解除。
4. **豁免**：滚动类动作只要有新证据（`_scroll_verdict` 通过）不计等价——与 SPEC 2.5 既有滚动判定衔接，不新造规则。
5. **边界符合性**：所有恢复步骤都带 expected 检查、全部有界、以 ABORT 收尾——这是对 SPEC 红线"无未知结果重试"的**加强**而非违反。

### 3.7 横切二：风控策略引擎（W8，F5）

现状：微信 visual-only + `_gate_injection` + 7 天冷却 + SOP 散文（约束账本/登录墙/风控信号表）——方向正确，但**判定全在模型自觉**。

新增代码级策略层（纯函数策略表 + 执行边界强制）：
- **应用分级表**（用户可配）：`financial`（支付/银行/证券）→ 禁注入+ASK_USER；`social_login`（微信/QQ 登录页）→ 视觉只读+ASK_USER；`risk_watch`（风控信号命中过的 App）→ 降频+截图留证。豆包的教训：其因无此机制被 155 款 App 抵制后被迫加"拒绝操作清单"。
- **动作分级**：读操作放行；写操作（paste/launch/install_apk/adb_shell）过分级表；不可逆操作（下单/发送/删除）一律 ASK_USER。
- **登录墙即停**：检测登录页（现有 dump/look 判据）→ 停手 + ASK_USER，不自动登录（与 SOP 红线一致，升级为代码强制）。
- 落地约束：策略表数据驱动、默认保守、每条例外须在 VALIDATION.md 留档；**不得变成 per-app 坐标补丁**。

### 3.8 横切三：轨迹经验检索（W9，F7）

现状：L4 raw sessions 目录不存在（SPEC 2.6 自承）、SOP 检索只有 L1 触发词 + `file_read` 子串 + difflib>0.3 提示。

增补（不引向量库，守 SPEC 非目标）：
- L4 成功轨迹落盘（recipe recorder 的副产品，Phase 1 已有 recorder——一次建设两用）；
- 检索：任务文本 vs 轨迹元数据（app/scene/intent 序列）的 difflib 相似度 > 阈值 → 提示"相似任务曾这样完成"，注入 anchor prompt；
- L1 recipe 的 `unstable` 标记与轨迹检索联动：不稳定 recipe 不推荐。

---

## 4. 工作项与验收（W1-W9 + P0 验证项）

> 沿用 SPEC 纪律：纯函数、合成 fixture、无设备无网络无时钟；验收口径 passed/partial/failed/blocked/untested 分开；某阶段只有 VALIDATION.md 留档后才可称已实现。Phase 0 已落地，下列工作项从 Phase 1 起排。

### P0 验证项（实机适配，先于任何代码合并）

| # | 内容 | 方法 | 出口 |
|---|---|---|---|
| V1 | YOLO 端侧实测 | 按 OPTIONAL_YOLO.md 导出 onnx → 设置页导入 → "检测当前屏幕"记录 图标数/文字数/尺寸/耗时（魅族参照：5/24/1080×2340/首跑 5009ms） | SM8845 延迟数据入 VALIDATION.md；失败则 W1 转 OmniParser 评估 |
| V2 | FLAG_SECURE 行为 | 找/装一个 FLAG_SECURE 页面（或银行 WebView 登录页）测 `/a11y/shot` 与 dump | 确认"显式报错而非黑图"分支在真机成立 |
| V3 | 无障碍崩溃根因 | 复现用户历史日志中的"视觉识别超时→服务崩溃"；查 ask_vision 超时与服务生命周期 | 有根因则有修复+测试；无根因记 blocked |

### W 系列（按 SPEC Phase 对齐）

| # | 工作项 | 落入 | 依赖 | 验收（摘要） |
|---|---|---|---|---|
| W1 | 检测器补齐与评测 | L2 | V1 | `look()` 在本机 S2/S5 场景产出控件级候选；误报率对照 phone_use.md §0.5 误差带记录。**默认不换 OmniParser**（决策规则见 D5）：先调参（YOLO_SIZE 640→960 换召回），再混合 caption，自训是长期路线 |
| W2 | 低信息闸门机械化 | L0 | — | `route()` 单测：树<阈值 → L2；策略置空/FLAG_SECURE/真真空三路分流各有命名用例 |
| W3 | 动作账本+三档防循环 | 横切 | Phase 0 指标 | **✅ 已实现（3fc9709/0544dbf/1c52a08）+ 真机验证**：等价×5 提示、TAP 恢复阶梯 WAIT→BACK→HOME→ABORT、swipe 第 5 次拒绝、滚动豁免、ABORT 有界；真机（PC 侧 gacore+adb forward）连续 tap 1-2 派发 / 3→WAIT / 4→BACK / 5→HOME / 6-7→ABORT，连续 swipe 第 5 次 rejected，真实行跳转（diff 20.137%）后 hint 清除 |
| W4 | pkgs 中文应用名匹配 | L0 | — | **✅ 关闭（无代码）**：label 匹配一直存在，初版"缺口"是 curl/GBK 编码假阴性（见 §1.2）；NFKC 硬化按仓库纪律留待复现失败 |
| W5 | dump 降级原因码 | L0 | — | **✅ 已实现（f357556）**：`dump_state()` 返回 `{nodes, degraded, pkg}`，reason ∈ sensitive_blank/unresolved_fg/tree_empty；`dump()` 委派保持 list 契约；`_track` 事件名不变（指标对齐）。纯 Python 增量化（blanking 所有者是 droid.py，无需改 Kotlin） |
| W6 | SoM 编号图 | L2/L3 | W1 | 编号→bbox 映射正确（旋转/横屏用例）；标注图不进 L2；标注失败降级原图不报错 |
| W7 | prompt 稳定前缀 | L4 适配器 | Phase 0 | re-sent history size 与 P50/P95 before/after 记录；无改善则回滚（不 merge） |
| W8 | 风控策略引擎 | 横切 | — | 策略表单测（分级/动作/登录墙即停）；微信既有行为零回归；条例外留档 |
| W9 | 轨迹检索 | L1 | Phase 1 recorder | 相似任务召回命中率记录；不引新依赖；无向量库 |

### 与 SPEC Phase 的关系

- **Phase 1（recipe）**：W8 的风控表可作为 recipe 的 `on_fail` 策略来源；W9 依赖 recorder。
- **Phase 2（L2）**：W1/W2/W6 是 L2 的感知地基，先于 L2 验收。
- **Phase 3（router）**：W2/W4/W5 是路由判据，W3 的账本供路由器读 escalations。
- **Phase 4（L3）**：F1 模型选型+D2 部署形态是 Phase 4 的前置决策。

---

## 5. 评测方案（W10，F9）

1. **外部基准接入**：SPA-Bench 框架（即插即用、已集成 10+ agent、中英任务、7 指标含资源消耗）作为横向对标；AndroidDaily 子集（中国生活场景，与 GAgent 的 app_cards 重合度高）作为回归集。
2. **自有场景集**：SPEC 的 S1-S10 每场景 ≥3 题，其中本机已验证锚点：S1=设置、S2=微信（visual-only）、S5=王者荣耀（横屏游戏）、S8=中文输入（paste 通道）。
3. **指标**：沿用 SPEC 7.1/7.2，补两项——**每步模型调用数按层分布**（验证 L1/L2 零调用占比）、**风控触发次数**（ASK_USER/停手/冷却）。
4. **对照基线**：同机跑 GAgent 现状（L4-only）vs 增强版；豆包/DSH 的 3-5s/步作为外部参照点（非同机，仅方向参考）。
5. 纪律：评测不等于已实现；数字入 VALIDATION.md 带日期与 commit。

---

## 6. 风险与红线符合性自查

| SPEC 红线 | 本 spec 是否符合 | 说明 |
|---|---|---|
| 不重写 L4 通用循环 | ✅ | W7 只改 llmcore 消息构造（provider adapter）；不开 L4 截图通道 |
| 不建第二执行/验证路径 | ✅ | 全部增强调用既有 droid/look/verifier；SoM 是观察呈现不是新执行 |
| 第三方 App 不走节点树/内部 API/CDP | ✅ | 微信 visual-only 不动；W8 是加强 |
| webcdp 只连自己的 WebView | ✅ | 不涉及 |
| 无设备尺寸/方向/OEM/per-app 硬编码 | ✅ | W4 是通用匹配缺陷修复；策略表按应用分级不按坐标 |
| 不引 embedding/向量库 | ✅ | W9 用 difflib；明确列为非目标 |
| 无未知结果重试 | ✅ | W3 的恢复阶梯每步带 expected、有界、ABORT 收尾——是加强 |
| 敏感前台空树是设计 | ✅ | W5 只是给空树加原因码，不放宽 gate |
| 文档不把计划写成能力 | ✅ | 本文档所有未实施项均标 W/P0 编号 |

**新增风险**：
- L3 出图（形态 A）与视觉-only 隐私姿态冲突 → 按 App 分级禁用（D2 附带决策）。
- W8 策略表可能过度限制 → 默认保守 + 可配置 + 每条例外留档。
- W7 若破坏既有缓存命中 → before/after 数据不过即回滚。

---

## 7. 实施顺序建议

```
P0 验证（V1/V2/V3，1-2 天，可并行）
  → W4 + W5（路由判据，小而易测）
  → W3（防循环，横切地基）
  → W1 + W6（视觉通道补齐）
  → Phase 1 recipe + W9（经验沉淀）
  → Phase 2 L2（依赖 W1/W2/W6）
  → W7（时延优化，数据说话）
  → Phase 3 router + Phase 4 L3（依赖 D1/D2 决策）
  → W8（风控引擎，可与 Phase 3 并行）
  → W10 评测收口
```

---

## 8. 待用户决策点（D1-D8）

| # | 决策 | 选项 | 我的建议 |
|---|---|---|---|
| D1 | L3 模型 | A. GELab-Zero-4B-preview（Apache-2.0，设备同源） B. ShowUI-2B C. OS-Atlas-4B 自训 D. 云端 pinned endpoint | **A**，D 作对照基线 |
| D2 | L3 部署形态 | A. PC/局域网 HTTP 端点（快、零端侧成本、截图出设备→敏感 App 禁用） B. 端侧 GGUF Q4（产品化、需动构建链、3-8s/步） C. 两者（A 先行 B 后续） | **C**：A 先行验证效果，B 作为产品化阶段 |
| D3 | 语义 verifier（终态断言）是否引入 | A. 引入（V-Droid 式，触碰"无第二验证路径"红线，需修订红线措辞为"verifier 是既有 verifier 的编排者+一个受控新规则"） B. 不引入，终态只用既有像素/文本证据 | **A**，但写成"受控单点新规则"并单独留档——SPEC 7.2 的 terminal-state correctness 指标本来就没有满足机制 |
| D4 | 风控策略代码化 | A. 代码级策略表（豆包教训） B. 维持 SOP 散文 C. 混合（代码管分级，SOP 管流程） | **C** |
| D5 | YOLO 权重路线 | A. 维持用户自装 B. 自训宽松许可检测器（a11y dump 免费标注，OPTIONAL_YOLO 方案 C） C. 全盘换 OmniParser D. 混合（YOLO 框 + 仅 top-K 候选跑 caption） | **V1 实测后定**；默认不换——GAgent 自己就是从 OmniParser 迁到 YOLOv8n 的（ui_detect_lite.py:7），且 OmniParser 是桌面/服务器定位（Florence caption ~GB 级、通用屏训练、英文描述、ScreenSpotPro 39.5% 是桌面域成绩不可外推安卓）。顺序：调参（YOLO_SIZE 640→960）→ D 混合 → C 仅在“要默认内置”时评估（许可干净但体量代价大）→ B 是长期唯一能进默认包且保持端侧友好的路（a11y dump=免费标注源） |
| D6 | 主 LLM 多模态化 | A. 维持禁令（L3 才见图） B. 开 L4 截图通道 | **A**（红线不动；如业务需要再单独立项修订） |
| D7 | 轨迹检索深度 | A. difflib 元数据匹配（无新依赖） B. 上向量库（违反现非目标） | **A** |
| D8 | 评测基线 | A. SPA-Bench 接入 B. 自建 C 用例集 C. 两者 | **C** |

---

## 9. 诚实声明

- 本文所有"已验证"均为 2026-10-26 在 StepOS PZ261A 真机上的实测，可复现；"未验证"项已明确标注，不冒充通过。
- 外部性能数字（GELab-Zero 75.86% 等）均为**官方口径或论文自述**，未在本机复测。
- W 系列工作项均未开始编码；本文是设计，不是能力声明（与 SPEC 文档性质一致）。

---

## 3.7 自绘/canvas 页面加速（S5-S7 通用机制，2026-10-26）

> 触发实证：羊了个羊一局 652s/18 轮（未完成）。慢因四层：导航段无配方（125.7s）、
> 游戏段每步 1-2 次云端 ask_vision 且全屏 320 万像素+长 prompt（单次 25-50s）、
> 无机械验证（每步再付一次 VLM 验证）、vision 超时拖垮 a11y。
> **以下机制全部场景通用，不针对具体 App/游戏。**

| # | 机制 | 做法 | 收益 |
|---|---|---|---|
| 1 | ROI 注意力 | 首次进 canvas 页：VLM 看强降插图（max_pixels≈300K）只问"可交互区域边界(百分比)"；ROI 记 checkpoint，之后所有 ask_vision 带 `roi=[x1,y1,x2,y2]`(0-1000) 只送局部 | 像素量降 3-6 倍，单次 25-50s → 8-15s |
| 2 | Exemplar 指纹识别 | 重复视觉元素（牌堆/卡牌/图标墙/列表项）网格化后每格算局部指纹（颜色直方图+感知哈希，本地 ms）；VLM 只命名一次 exemplar，之后"哪些格相同/第X格是什么"全部本地回答 | 棋盘类页面每步 VLM 调用 → 0 |
| 3 | 机械优先的 canvas 验证 | canvas 上 tap 后：整屏 diff + 落点周边区域 diff（本地 ms）；区域明显变化⇒点中，无需 VLM 验证 | 每步省 1 次 VLM（~35s） |
| 4 | 增量提问 | 本地保存上次结构化观测，VLM 只被问"什么变了" | prompt 变短、输出变短 |
| 5 | 配方自动录制 | 导航段自动归配方（L1 收尾） | 固定路径 0 模型调用 |
| 6 | VLM 超时熔断 | `ask_vision` 单次上限 30s + 连续 2 次失败熔断 120s，静默期内直接拒 | 不再烧超时、不再拖垮 a11y |

**覆盖映射**：羊了个羊=1+2+3+5（652s→~20s）；王者荣耀/小程序自绘/混淆 App=1+3+4（VLM 仍在但每次快 3 倍）；短视频流=1+3；普通 App 不变（a11y+配方）。

**实施顺序**：P1=机制1+6（已落地：`ask_vision(roi=,max_pixels=,timeout=)` + 熔断 + conftest 状态重置）→ P2=机制3+4 → P3=机制2 → P4=机制5。

**保留 VLM 的场景**：全新元素命名、隐藏信息推理、复杂语义判断——且都从"全屏长 prompt"变为"裁剪+短问"。
