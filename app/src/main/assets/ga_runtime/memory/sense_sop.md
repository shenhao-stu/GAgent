# 真实世界记忆 SOP (sense) — 采集→落档→回忆全链路; 默认关闭, 无证据不作答

> 触发见 `modes_index`。把「音频/位置/同场者/日历/运动」采成一条统一时间线, 落档到用户**自己的 PC**; 回忆时先时空+人硬过滤再检索。
> **本能力默认关闭**: 没有正在跑的 session 就是没在采集。只有用户本轮显式要求才 `session start`——「看起来该记一下」不是开启理由。
> 两份细则由本文指路, 用时 `file_read`: 回忆与拒答 → `memory/sense_recall_sop.md`; 隐私/告知话术/purge → `memory/sense_privacy_sop.md`。

## 何时用
- 用户说「记一下/开始记录/这次会议帮我记」→ 走本文 §2 采集会话。
- 用户问「上周三下午在公司和老王聊了什么/上个月见了张三几次/我常去那家店都干嘛」→ **不用开采集**, 直接读 `sense_recall_sop` 走回忆。
- 用户问「你都存了我什么/删掉昨天下午的记录/导出我的数据」→ 读 `sense_privacy_sop` 走治理。
- 不属于本模式: 纯屏幕操作(`phone_use`)、纯语音输入(前台麦克风)、通知规则(`notif_trigger_sop`)。

## 0. 三条不可协商
1. **默认关闭 · 显式开启**: 每次采集都要用户当次明确要求; 采集期指示(系统麦克风指示 + 带「停止记录」的常驻通知)不可隐藏, 也不要尝试隐藏(悬浮窗当前不参与指示, 别说它会变红)。
2. **无证据不作答**: 回忆只认 `/sense.query` 的 `evidence`。「没采到」≠「没发生」, 说反了就是编。
3. **出错退向更少**: 形状不认识/读不到策略时, 一律按「采得更少、留得更短、传得更少」处置(默认 `uplink=text_only`, 音频不出设备)。

## 1. 唯一调用方式
`sense` 已在 PATH(禁加虚假前缀)。`handle()` 收桥命令字符串、回 JSON 字符串; 子命令是位置参数, 参数体是**一个** JSON:

```python
import json, time, sense
def S(cmd, **kw):                        # 全篇示例都用它; kw 为空就不带参数体
    return json.loads(sense.handle(cmd + (' ' + json.dumps(kw, ensure_ascii=False) if kw else '')))

S('/sense.session status')
S('/sense.query', **{'from': t0, 'to': t1, 'kinds': ['asr.text'], 'q': '报价'})   # from 是 Python 关键字, 只能这么传
```

- 成功 `{'ok':1, ...}`; 失败恒有 `{'ok':0,'error':'<code>'}`(其余键随 code 走, 如 `unknown_verb` 带 `verb`/`want`)。
- code_run 里直调 `sense.handle()` **同步返回终态**(WebUI 桥路径才回 `{'job':...}`), 不必轮询。
- `error=='unknown_cmd'` = 本机 APK 还没有这条子命令(SOP 可热更、原生要发版)。**立刻停手并告诉用户**; 禁止改名重试——未知桥命令会被当成 prompt 起真实 LLM 任务烧积分。
- 三个 L2 组合(只是原子的固定序列, 出错就按 §2/§3 自己走原子): `sense.meeting_wrap(sid)` / `sense.daily_digest(day)` / `sense.recall(q)`。

## 2. 一次采集会话(主线)
开始前 30 秒的两件事: ①确认用户本轮明确要开; ②有第三方在场则先按 `sense_privacy_sop` 的告知话术让用户念一遍。二者缺一不开。

```python
# ① 开: sources 只列真正需要的; 只要 loc/near 就别带 mic(采集面小一个数量级, 也没有 bystander 问题)
r = S('/sense.session start', sources=['mic', 'loc', 'near'], label='周会')   # 采集参数不在这里传, 在 /sense.policy
sid = r['sid']
on  = [k for k, v in r['sources'].items() if v['state'] == 'on']
bad = {k: (v['state'], v.get('reason', '')) for k, v in r['sources'].items() if v['state'] != 'on'}
# 立刻如实播报: 「在录音+位置, 蓝牙没开所以同场者这次记不到」。别把 bad 咽下去, 用户以为在录才是最坏结果。

# ② 中途: 用户问起或每隔几分钟看一次; 状态会变(被抢麦/被系统静音/服务被用户在任务管理器停掉)
st = S('/sense.session status')          # state 变 silenced/denied → 当场告诉用户, 别等结束才说

# ③ 用户口述要点 → 写成 note.user, 与录音同轴可查
now = int(time.time() * 1000)
S('/sense.log', **{'sid': sid, 'kind': 'note.user', 'source': 'user',
                   'ts_start': now, 'ts_end': now, 'payload': {'text': '老王答应周五给报价'}})
# id/ts_ingest/tz_off/conf/valid 由写入层补全, 不要自己造; 幂等靠 id 派生, 重复写不会多出一行。

# ④ 停 + 落档(stop 之后必须 wrap, 否则数据停在原始态)
S('/sense.session stop', sid=sid)
w = sense.meeting_wrap(sid)              # = asr 批处理 → 日历继承元数据 → peer 归并 → sync.push
```

`meeting_wrap` 不可用时的等价原子序列(逐步做, 每步失败只影响该步):

```python
for b in S('/sense.blob list', since=t0)['blobs']:
    S('/sense.asr seg', blob=b['id'], engine='auto', lang='zh')      # engine=auto 由 L1 选云/端侧/留给 PC
ev = S('/sense.cal range', **{'from': t0, 'to': t1, 'limit': 20})['events']
# 有时间重叠的日历事件 → 直接继承 title/loc/attendees, 这是零推断的元数据, 优先于从音频里猜
S('/sense.sync push', max_bytes=524288)   # 推的就是「本地还没推成功的」, 不用给游标; 批按时间预算切, 别贴 8MB 上限走
```

收尾给用户的回执只说事实: 采了多久、几段转写、**几处缺口及原因**、已同步 N 条 / 待同步 M 条。

## 3. 原子速查(参数体字段名以本表为准)

| 命令 | 关键入参 | 关键出参与不变量 |
|---|---|---|
| `/sense.session` start, stop, status | `sources[] label` / `sid` | `sid`, `sources.{mic,loc,near}.state`(on, off, denied, silenced, unsupported); **单源拿不到不导致 session 失败**; `sources` 里可以带 `cal`/`motion`——它们不是常驻源(status 不报), 只是让 start 顺带把这两项的权限一并申请 |
| `/sense.mic` status, seg, probe | `sid`(省略=当前/最近一次会话) | status: `state silenced asr_pending`; seg: `n sid ingested[blob_id] gaps[{from,to,reason}]`(把已落盘的分片登记进时间线; 静音期与写盘失败期自动成 `audio.gap`, 分片的 `bytes` 是磁盘真实长度; 回参 `sid` 告诉你这批分片归到了哪场会话) |
| `/sense.loc` fix, watch, status | `mode max_stale_ms` | `fix{lat,lon,acc_m,ts,provider,stale_ms,valid}` 或 null, `granted`, `place_id`, `degraded_to`; **fix 为 null 时仍是 `ok:1`** |
| `/sense.near` scan | `ms` | `ble[{h,rssi,stable}]`, `wifi.bssid_h`, `paired[]`, `peers[]`, `caps`; `stable:false` 只在**本次会话内**可比对, 跨天匹配一定错 |
| `/sense.cal` range | `from to limit` | `granted`, `events[{title,start,end,loc,attendees}]`; 未授权是 `granted:false, events:[]`, 不是错误 |
| `/sense.motion` now, range | `from to limit` | `state`(still, walking, vehicle, unknown), `conf`, `src`; 也是定位的省电门控 |
| `/sense.asr` seg, status, result | `blob engine lang` / `segs[]` | seg: `queued`(只登记待转写, 手机端不跑流式 ASR); status: `counts{pending,done,failed}`; 转写文本由 PC 用 `result` 写回, `spk` 是**会话内**编号, 不是人 |
| `/sense.log` | 一条或一批 Observation | `ids[]`; 幂等 |
| `/sense.query` | `from to near with[] kinds[] q as_of limit order` | `items[]`, `evidence{n_hits,span_covered_ms,gaps[]}`, `abstain_hint` |
| `/sense.place` list, stays, name, resolve | `place_id name` / `lat lon` | `places[{id,name,named_by,centroid,anchor,n_visits}]`; 无匹配回 `place_id:null` 而非报错 |
| `/sense.peer` list, name, merge, resolve | `peer_id name consent` / `signals` | `peers[{id,name,consent,signals,n_meets}]`; `peer_self` 是机主保留 id |
| `/sense.sync` push, status, pull | `kinds max_bytes dry_run` / `since`(仅 pull) | `pushed cursor pending held_consent pc.reachable`; 同步失败**永不删本地**; `held_consent`>0 = 那几条只上行了存在性(同场者未同意), 授予同意后自动补推; pull 只补本机没有的行(`kept_local`/`redacted_skipped` 是被保住的本机原文, 不是失败) |
| `/sense.blob` list, put, get, upload, purge | `id force chunk_bytes older_than_days` | `blobs[{id,dur_ms,uploaded,expires_at}]`, `quota`; 默认不上传, 上传须 `force` 或改 policy |
| `/sense.watch` add, list, del, set-enabled | `id on task cooldown_ms quiet_hours` | `rules[]`, `caps.geofence`; 纯时间触发用 `droid.alarm_set`, 通知触发用 `notif_trigger`, 别在这里重造 |
| `/sense.policy` get, set | 见 `sense_privacy_sop` | `policy`, `source`(kv 或 default) |
| `/sense.perm` status, request, settings | `kinds[] wait_ms` | 采集类 dangerous 权限的按需查/申请; 日常不必直呼(session start 会就地申请), 仅在需单独引导某权限(blocked 后深链设置页)时用; `request` 只在 GA 前台弹框 |
| `/sense.keepalive` status, settings | `action` | `ignoring_batt bg_restricted needs_setup manufacturer vendor_hint opened`; 长时/全天采集前查一次——`needs_setup:true` 就先按 `vendor_hint`(按 ROM 定制)引导用户加电池白名单, 否则国产 ROM 杀后台会让采集静默中断。`settings` 拉起电池豁免请求/应用详情页(须 GA 前台) |
| `/sense.data` count, export, purge | selector 与 query 同形 + `confirm` | count 出 `confirm` token; purge 出 `receipt` 与 `pc.cascaded` |

**无感开录三通道(A14, 都落到「起一个 mic 会话」)**: ① 下拉快捷设置磁贴「GA 记一下」(合规天花板, 一划一点 ~1.5s); ② 桌面长按 GA 图标 →「记一下/停止记录」; ③ GA 内 `/sense.session start`。三者都最终经透明 `SenseQuickActivity` 满足「mic FGS 须由可见 Activity 起」(A34 铁律)——**后台任何豁免都启不动 mic**, 所以不存在「息屏自动开录」, 别对用户这么承诺。磁贴/快捷方式只开 `mic` 单源(采集面最小); 要 loc/near 多源仍走 GA 内显式 start。

## 4. 降级与失败(这一节决定 SOP 能不能通用)
**永远不要自己判断 Android 版本、有没有 GMS、什么厂商 ROM。** 机型差异已被原生层吸收成两个字段, 只读这两个:
- `caps.*` / `sources.*.state` = 本机此刻**拿不拿得到**;
- `degraded_to` = 换了哪条更差的路(如 `near_fingerprint`)——照常用, 但对用户说清精度降了。

判读规则:
- `ok:1` 但 `fix:null` / `ble:[]` / `granted:false` = **已知状态不是错误**: 不重试、不换命令, 换一种证据(没有位置就用 near/cal, 没有日历就用 place/peer)。
- `degraded_to` 分得清「试过了不行」与「压根没试」: `bus_unavailable`=连不上采集服务; `l0_timeout`=这一条太慢(总线本身没问题, 可以直接再来一次或把 `ms` 调小); 源的 `reason: bus_cooldown`=上一次连不上, 这次在静默期内没发请求(用户显式的 `session start/stop` 不受静默期影响, 一定是真发过)。
- `ok:0` 才是真错误: 看 `error`。`unknown_cmd` 立刻停手(见 §1)。
- 单源 `denied`/`unsupported` 不停整个 session; 部分可用是常态。
- 源 `denied` = **没授权, 不是坏了**: `session start` 已经就地弹过一次系统授权框(只有 GA 在前台才弹得出来, 且只在 start 这个用户显式动作上弹)。请用户点允许后**再 start 一次**——中途授权不会让正在跑的会话把那个源接上。用户若之前选过「不再询问」, 系统不再弹框, 只能引导去 设置 > 应用 > GenericAgent > 权限 手动开。
- 发现「用户以为在录、其实没录到」(silenced / 通话中 / 配额打满 / 写不进磁盘) → 必须补写一条 `audio.gap`(`valid:false` + `reason`)。**缺口是数据, 不是可以省略的坏消息**; 假数据比没数据危险得多。
- 连续失败 3 次不再重试, 改为如实报告 + 请用户处置(权限/蓝牙/省电策略)。

## 5. 什么时候问用户(一次只问一件)
1. 用户没明说要记 → 不开; 说了「记一下」但没说范围 → 问一句就开, 别追问三轮。
2. 有第三方在场 → 先给告知话术, 用户念完再 start(`sense_privacy_sop`)。
3. `/sense.place resolve` 回 `place_id:null`(新地点) → 事后问一次名字 → `/sense.place name`。
4. 出现新说话人/新同场设备 → 事后问一次「这是谁」并同时确定 consent 档 → `/sense.peer name`。**不问就没有名字, 绝不自动猜真名。**
5. 回忆时时间表达式有歧义、或候选人重名 → 问(细则见 `sense_recall_sop`)。
6. `purge` 预览之后必须问(两步确认, 见 `sense_privacy_sop`)。

采集进行中把打扰压到最低: 能事后一次性问清的, 绝不在会中打断。

## 6. 落档与跨端
- 结构化小数据(转写文本/位置/同场者/日历)走 `/sense.sync push` 到用户自己的 PC; 音频等大对象走 `/sense.blob`, **默认不出设备**, 只有 PC 侧明确要回听某段才 `upload`。consent 未授予的同场者的原文**连 PC 都不上**(只上存在性), 见 `sense_privacy_sop` §4。
- `pc.reachable:false` → 本地队列堆积并定期重试, 如实显示「已存本地 N 条待同步」; **永不因为同步失败丢弃本地数据**。
- 手机与 PC 实现同一个 query 契约: 同一句问话手机离线也能答, 只是召回面更小——**召回面小要说出来**, 不能当成完整答案。

## 7. 红线
- 采集数据只落 `GA_DIR/temp/.sense/`(内部) 与 `temp/sense_export_*.jsonl`(交付给用户); **绝不写进 gacore 树内**——Evolution 会把「官方包里没有的文件」从存量设备清掉。
- 不 root、不提权、不绕平台指示。开机后自动续录做不到(A14 起 microphone 前台服务禁止由开机广播启动), 且**重启后不会有任何提示**(没有开机接收器), 要用户自己回 GA / 磁贴 / 桌面快捷方式再开一次——别承诺「重启后点一下通知就接着录」。
- 部分国产 ROM 会杀后台, 长时采集存在中断风险, 但**可以靠 `/sense.keepalive` 前置引导把风险压下来**: 长时/全天采集前先 `keepalive status`, `needs_setup:true` 就按 `vendor_hint` 引导用户加电池白名单+开自启动(各家路径不同, 文案已按 `manufacturer` 定制)。这一步做过与否, 直接决定全天场景的成败——别跳过。中断后仍按 `caps`/gap 归因到**具体哪一项**, 别笼统说「录音失败」。会话被杀后下一次 `/sense.session status|start` 会把覆盖窗闭到最后一条真实数据, 之后那段在回忆里就是显式缺口——**这是特性: 宁可说没录到, 不可拿在场证明冒充证据**。
- 地理围栏**本轮没实现**(`/sense.watch` 的 `caps.geofence` 恒为 `unsupported`, 规则存得下但不会触发), 一律不承诺到达提醒; 平台本身也只有约 2 分钟量级响应, 就算做了也不是分钟级。
- 在能力真正跑通之前, 不对用户或对外承诺任何隐私能力。
