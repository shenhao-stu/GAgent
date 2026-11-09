# sense 场景与原子能力图谱 SOP — 真实世界交互跨端协同的可拓展底座

> 本文是 sense 子系统的**顶层设计单一真相源**: 把"真实世界交互 × 跨端记忆"拆成高价值场景, 再把场景解耦成可复用的原子能力, 并标注每个原子在四层里的落点与安卓兼容边界。
> 目的有二: ① 让 agent 面对新需求时先查"要哪些原子"而不是从零设计; ② 让后续动态拓展有章可循——**加一个原子必须四层同步, 缺一层就静默半残**(见 §4)。
> 采集/回忆/隐私的执行细则在 `sense_sop.md` / `sense_recall_sop.md` / `sense_privacy_sop.md`; 本文只管"场景→原子→落点"的映射, 不重复那边的话术。

## 0. 一句话产品定位(占位与竞品空档)

**纯手机、零新硬件、传感器融合(谁/在哪/何时/说了什么)、隐私优先(音频默认不出设备, 重计算在用户自己的 PC)的真实世界记忆。** wearable 阵营(Limitless→Meta、Bee→Amazon、Omi)要买设备且多被收编; 桌面阵营(Recall/Screenpipe/Granola)只看数字世界。手机天生带 GPS+BLE+日历+运动状态, 能回答"和谁、在哪、什么场合", 不只是"说了什么"——这是可独占的象限。

## 1. 高价值场景清单(按上线 ROI 排序)

| 顺位 | 场景 | 一句话 | 需要的原子(§3 编号) | 成熟度 |
|---|---|---|---|---|
| 1 | **闪念胶囊** | 磁贴/桌面一点 10-60s 语音便签, 端侧转文字入时间线, PC 夜间归档抽待办 | A14, A1, A7, A12, A11 | 骨架齐(A14 已补) |
| 2 | **会议全息纪要 + 承诺追踪** | 开录会议(音频+位置+同场者+日历)→ PC 转写+说话人分离 → "上周二在 Y 和 X 聊了什么、他答应了什么" | A1, A2, A5, A6, A8, A9, A11, A12, A13 | 旗舰, 80% |
| 3 | **地点触发情境回忆** | 到常访地点后手机主动想起"上次来这和谁谈了什么、你还欠他什么" | A3, A10, A11, 通知卡片 | 缺 A3 |
| 4 | **无音频自动日记 + 日终简报** | 全天 stay-point+运动+日历(不碰麦), PC 生成一天叙事 + 明日备战 | A2(全天), A4, A6, A10, A12, A13, A16 | 缺 A4/全天/A16(A16 已补) |
| 5 | **停车/行踪回忆** | 驾车→步行 transition 自动落停车点; "我把车停哪了" | A4, A2(single-fix), A11 | 缺 A4 |
| 后置 | **人脉记忆(声纹)** | BLE 同场 + 声纹 + 参会人建 person 实体, 再见面给出历史 | A5, A9, A10, A11, consent | 技术就绪, 法务/enroll UI 待建 |

**旗舰演示脚本(对外爆点)**: 开会时手机一点开录 → 回家路上手机把音频+GPS+同场者推到自己的 PC → 睡前问 PC 版 GA "上周三下午在客户那儿, 我跟王总具体聊了哪几条报价、我答应了什么" → GA 凭时间+地点+人硬过滤命中原话与承诺, 并对没录到的时段显式说"这段没有记录"。

## 2. 分层与降级(为什么这套 SOP 能适配尽量多安卓系统)

```
L3 SOP(memory/*.md)      产品判断与话术: 何时开、怎么告知、能不能答
L2 组合(sense.py 末段)    固定原子序列: snapshot / meeting_wrap / recall / daily_digest
L1 原子(sense.py)         统一形状 + 落时间线 + 时空人过滤; 桥命令 /sense.*
L0 原生(SenseService.kt)  从系统真取信号; 机型/版本/GMS/ROM 差异全部吸收成 granted/caps/degraded_to
```

**唯一跨版本不变量**: 上层永远只读三个字段——`sources.*.state` / `caps.*`(拿不拿得到)、`degraded_to`(换了哪条更差的路)。**绝不在 L1/L2/L3 里判 Android 版本或厂商**。新增原子必须延续这条: 拿不到就如实降级, 绝不抛异常、绝不谎报达标。

## 3. 原子能力并集表(去重后 16 项 + 落点 + 安卓边界)

> 落点列 = [L0 Bus 路由 | L1 sense.py | SOP]。"—"= 该层不涉及(如纯 PC 侧)。⚠ = 当前未实现/受限, 拓展时优先补。

| # | 原子 | 作用 | 落点 | 安卓 API / 兼容边界 |
|---|---|---|---|---|
| A1 | 分段录音会话 | 长会话切段落盘, 静音/被抢/写失败→gap | `/sense/session`+`/sense/mic` \| `_h_session/_h_mic` \| §3 | AudioRecord + FGS microphone; 11+后台需FGS type, 12+状态栏指示灯, 14+后台禁启, 15禁开机启 |
| A2 | 被动定位+stay-point | 低功耗轨迹→驻留点 | `/sense/loc` \| `_h_loc` \| §3 | LocationManager 自带 fused(免GMS); 全天需 ACCESS_BACKGROUND_LOCATION(30+跳设置页, **当前显式不申请**⚠) |
| A3 | ⚠ Geofencing | 进出地点触发 | 未实现(`watch.caps.geofence=unsupported`) | GeofencingClient(需 play-services-location, 本仓未引)或 LocationManager.addProximityAlert(平台自带, 可作免GMS落点); 后台启FGS(location)官方豁免 |
| A4 | ⚠ 运动状态识别 | 静止/步行/驾车 transition; 停车 | `/sense/motion`(仅瞬时, 无 transition 订阅) \| `_h_motion` \| §3 | 现为加速度方差启发式(零权限兜底); 升级 ActivityRecognition Transition API 需 ACTIVITY_RECOGNITION(已声明); transition 事件享后台启FGS豁免 |
| A5 | BLE/WiFi 邻近 | co-presence 指纹 | `/sense/near` \| `_h_near` \| §3 | BluetoothLeScanner(12+ BLUETOOTH_SCAN neverForLocation); 8.1+熄屏丢无过滤扫描; WiFi 9+严格节流只读当前连接 |
| A6 | 日历交叉引用 | 会议标题/参会人锚定 | `/sense/cal` \| `_h_cal` \| §3 | CalendarContract(READ_CALENDAR); 全版本稳 |
| A7 | 端侧 VAD+ASR | 闪念即时转写 | (登记走 `_h_asr`; 端侧引擎 onnxruntime 已在依赖) \| §3 | sherpa-onnx/onnxruntime JNI; 纯NDK无版本风险; 低端机用int8。**手机端只登记不跑流式**(实测ANR), 转写在PC |
| A8 | PC 端 ASR+diarization | 高质量转写+说话人分离 | — \| — \| PC 侧 | whisper/FunASR + pyannote; 走 `/sense.sync` 回写 |
| A9 | ⚠ 声纹注册+匹配 | speaker ID→实名 peer | 未实现(peer 靠 BLE/日历) | sherpa-onnx speaker-id 端侧可跑; **生物特征, 需显式 enroll+被采集人同意**, 法务门槛高, 后置 |
| A10 | 实体解析 place/peer | stay-point→POI; 设备/声纹→person | `/sense/place`+`/sense/peer` \| `_h_place/_h_peer` \| §3 | 应用层; POI 语义化(LLM 补类别)建议在 PC 侧, 参考 stay-point→POI 管线(93%+ acc) |
| A11 | 情景记忆库+语义召回 | time+place+person 过滤+检索 | `/sense/query` \| `_h_query`+`recall()` \| `sense_recall_sop` | 应用层; 建议向多信号检索(语义+关键词+实体+时间)与层级摘要(clip→hour→day)收敛; 用 LongMemEval/EgoLifeQA 式题库做召回回归 |
| A12 | LLM 抽取 | 摘要/待办/commitment/日记 | — \| `daily_digest()` 备料 \| 上层一次调用 | PC 端 LLM 主力; 手机小模型兜底 |
| A13 | 跨设备同步 | phone→PC 推; PC→phone 回写 | `/sense/sync` \| `_h_sync` \| §6 | pclink 通道 + 断点续传; 14+ dataSync FGS 6h 上限→大文件分片或 user-initiated transfer |
| **A14** | **无感开录面** | <1.5s 从意图到开录 | 磁贴 `SenseTileService`+快捷方式 `shortcuts.xml`+透明 `SenseQuickActivity` \| — \| §3+无感开录段 | **已补(r14)**。QS Tile startActivityAndCollapse(34+需PendingIntent) / 静态shortcut; mic-FGS须可见Activity起, 后台豁免启不动mic |
| A15 | ⚠ 使用情境(可选) | app 使用/亮屏节律入日记 | 未接入 | UsageStatsManager(PACKAGE_USAGE_STATS 特殊访问)/NotificationListenerService(GA 已有 NotifService); 国产ROM上NLS不稳, 默认关 |
| **A16** | **OEM 保活自检** | 探测被杀风险+ROM 定制引导 | `/sense/keepalive` \| `_h_keepalive` \| §3+§7 | **已补(r14)**。isIgnoringBatteryOptimizations + isBackgroundRestricted + Build.MANUFACTURER 分支引导; 长时采集前必查 |

**明确不做(手机端)**: MediaProjection 连续录屏——A14+每次会话须用户同意+单app限制+常驻指示, "手机版 Recall"政策不可行; 屏幕记忆放 PC 侧。

## 4. 如何动态拓展一个新原子(N+1 配方)

加原子是四层协同, **顺序固定, 缺层即半残**:

1. **L0(SenseService.kt)**: 加 `fun <atom>(ctx, b): JSONObject`, 全程 `runCatching`, 拿不到回 `granted:false`/`degraded_to`, **绝不抛**; 需前台服务的才起 SenseService, 拉取式(如 keepalive/motion)直接返回。
2. **BusServer.kt**: `routes` 加 `"/sense/<atom>" to { s, _ -> senseJson { Sense.<atom>(adbCtx(), senseBody(s)) } }`; `HELP` 加一行契约(入参/出参/不变量)。
3. **L1(sense.py)**: 加 `_h_<atom>(v, a)`——先校验 verb(未知回 `_err('unknown_verb', want=[...])`, fail-closed), 再 `_l0('/sense/<atom>', ...)` 透传并归一形状; 注册进 `_SUBS`。
4. **L3(sense_sop.md §3 表)**: 加一行速查(关键入参 + 关键出参与不变量); 若涉及新的产品判断/话术, 在对应 SOP 补; 本文 §3 原子表同步加行(含安卓边界)。

**自检**: 加完后 grep 该 atom 名, 必须在 `BusServer routes`、`BusServer HELP`、`Sense.<atom>`、`sense.py _h_<atom>`、`_SUBS`、`sense_sop.md §3`、本文 §3 —— 七处齐全才算完整; 只在部分层出现 = 调用方会拿到 `unknown_cmd`(L1 未注册)或 `404`(L0 未路由), 静默半残。这条自检就是"方便后续动态拓展"的护栏。

## 5. 红线(拓展时不可破)

1. 默认关闭、显式开启: 任何新原子若涉及采集, 必须挂在用户显式动作后, 不得开机/安装自启。
2. 版本/ROM 差异只吸收在 L0: L1/L2/L3 出现 `Build.VERSION`/`MANUFACTURER` 判断即违规。
3. 出错退向更少: 采得更少、留得更短、传得更少; 静默故障产出显式 gap 而非丢弃。
4. 音频默认不出设备; consent 未授予的同场者原文连 PC 都不上(只上存在性)。
5. 数据只落 `GA_DIR/temp/.sense/` 与 `temp/sense_export_*.jsonl`, 绝不写进 gacore 树(Evolution 会清)。
