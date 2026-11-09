# -*- coding: utf-8 -*-
"""sense — 真实世界感知/跨端协同的 L1 原子 + L2 组合(桥命令 `/sense.*`; agent 侧 `import sense` 直接调)

窄腰: 任何来源的信号先变成一条 observation 落进同一条时间线, 再由 /sense.query 用「时空+人」硬过滤取回。
分层: L3 SOP(memory/*.md) → L2 组合(本文件末段) → L1 本文件 → L0 原生(Kotlin, Bus `/sense/*`)。
降级只发生在 L0 内部与本文件存储层: 上层只看 `degraded_to` / `caps` / `storage` 三个字段, 对 Android 版本、
GMS 有无、厂商 ROM 零感知 —— 这是同一份 SOP 能适配尽可能多安卓系统的唯一实现方式。

隐私红线(写进代码而不是文档): 默认不采集(必须显式 /sense.session start); 默认 uplink=text_only(音频不出设备);
默认保留期短; 读不到配置一律退向「采得更少、留得更短、传得更少」; 静默故障产出显式 gap 而不是丢弃(假数据比
没数据危险得多); consent 未授予的同场者在检索层就不返回原文, 同场者没标注的原话按会话级同场者从严判定(标注
缺失落在保护侧); purge 在 PC 不可达/表达不出选择集时如实返回 cascaded:false, 绝不退化成全清。

── 子命令(返回 JSON 字符串; 失败统一 {"ok":0,"error":"<code>",...}; 未知子命令/动词就地失败, 绝不进 agent) ──
 /sense.session start|stop|status {"sources":["mic","loc","near"],"label":"周会","sid":".."}
     → {ok,sid,started_at,label,sources:{mic:{state:"on|off|denied|silenced|unsupported"},..},degraded_to,storage}
     不变量: 单个 source 拿不到不导致 session 失败(部分可用是常态); L0 不可达时不写覆盖窗 —— 没采集就不能有覆盖。
 /sense.mic status|seg|probe {"sid":".."}      seg=把 L0 已落盘的分片登记进时间线(有效→audio.seg+blob, 无效→audio.gap)
     → {ok,n,sid,ingested:[blob_id],gaps:[{from,to,reason}],state,degraded_to}   sid 省略=L0 解析出的当前/最近一次会话
 /sense.loc fix|watch|status {"mode":"stay|move|once","max_stale_ms":120000}
     → {ok,fix:{lat,lon,acc_m,ts,provider,stale_ms}|null,granted,provider,place_id,degraded_to}  fix:null 仍 ok:1
 /sense.near scan {"ms":8000}   → {ok,ts,wifi:{bssid_h},ble:[{h,rssi,stable}],paired:[..],peers:[peer_id],caps,degraded_to}
 /sense.cal range {"from":<ms>,"to":<ms>,"limit":20} → {ok,granted,n,events:[{id,title,start,end,loc,attendees,peer_ids}]}
 /sense.motion now|range {"from":..,"to":..}   → {ok,state,conf,src,since} | {ok,n,items:[..]}
 /sense.asr seg|status|result   本轮手机端不做实时流式转写(whisper.cpp 安卓实测延迟累积到 ANR), 只做登记/查询/回写:
     seg {"blob":"blob_..","engine":"pc|cloud|ondevice|auto","lang":"zh"} → {ok,queued,blob,engine}
     status {"limit":50} → {ok,counts:{pending,done,failed},pending:[{blob,ts,dur_ms,bytes,engine}]}
     result {"blob":"..","segs":[{"t0":0,"t1":3200,"text":"..","spk":"s0","conf":0.9}],"engine":"pc"} → {ok,n,ids}
     result {"blob":"..","ok":false,"reason":".."} → 标 failed 并写一条 audio.gap, 让「为什么没有原文」可解释
 /sense.log {<obs>} | [{<obs>},..]  → {ok,ids,dedup,storage}   任何来源的唯一写入口(WebUI/agent/PC 回写共用)
 /sense.query {"from":<ms>,"to":<ms>,"near":{"lat":..,"lon":..,"radius_m":300}|{"place":"plc_.."},
               "with":["peer_.."],"kinds":["asr.text"],"q":"报价","as_of":<ms>,"limit":50,"order":"ts|-ts"}
     → {ok,n,total,items:[<obs>],filters_applied,evidence:{n_hits,span_ms,span_covered_ms,coverage_ratio,
        gaps:[{from,to,reason:"not_capturing|source_off|silenced|in_call|service_gone|purged|.."}],l0?},abstain_hint}
     gaps 把「没在采集」与「没发生」显式分开: 拒答能力下沉到数据层, 不靠 prompt 自律。覆盖按源判定 ——
     只开了定位的会话不给录音类问题作证(source_off), 否则「零命中+满覆盖」会被答成「你没聊过这事」。
     开着的会话窗只在 L0 当场确认「还在跑」时才算覆盖到此刻; 问不到 L0 就只认有真实数据佐证的那段, 并带上
     evidence.l0(=bus_unavailable/l0_timeout/..) —— 「窗开着」不等于「真在采」, 存疑一律退向拒答。
 /sense.place list|stays|name|resolve {"from":..,"to":..} | {"place_id":"plc_..","name":"公司"} | {"lat":..,"lon":..}
     → {ok,places:[{id,name,named_by,centroid,r_m,anchor,n_visits,first_ts,last_ts}]} | {ok,place_id,dist_m,conf}
 /sense.peer list|name|merge|resolve {"peer_id":..,"name":"老王","consent":"none|self|granted"} |
     {"from":"peer_a","into":"peer_b"} | {"signals":{"ble_h":[..],"cal_attendee":"..","spk":"s0"},"stable":true}
     → {ok,peers:[{id,name,consent,signals,n_meets,first_ts,last_ts}]} | {ok,peer_id,created}
 /sense.sync push|status|pull {"max_bytes":524288,"kinds":[..],"dry_run":false,"since":<ms>}
     → {ok,pushed,bytes,pending,held_consent,cursor,pc:{reachable,endpoint,status}}  幂等(obs id 稳定)+断点续传,
     失败绝不丢本地数据; consent 未授予的同场者只上行存在性(held_consent 计数), 授予后由 /sense.peer name 重排队重推
     pull 只补本机没有的行(pulled/kept_local/redacted_skipped): PC 上那份可能是被 consent 遮挡过的空壳,
     以它为准回灌就是用空壳覆盖原文, 而且补不回来 —— 同步成功同样不许丢本地数据。
 /sense.blob list|put|get|upload|purge {"id":"blob_..","path":"..","force":false,"older_than_days":7}
     → {ok,blobs:[{id,kind,ts,dur_ms,bytes,uploaded,asr,expires_at}],quota:{used_mb,cap_mb}}
     upload 默认被 policy.uplink=text_only 挡住: 音频出设备必须是一次显式动作(force=true), 并留一条 blob.uplink 审计
 /sense.watch add|list|del|set-enabled {"id":"w1","on":{"type":"kind","kind":"asr.text","match":"报价"},
     "task":"<prompt>","cooldown_ms":3600000,"quiet_hours":[23,7]} → {ok,running,rule_count,rules,caps}
     只管 kind 触发(写入时就地判定, 零后台开销); 纯时间触发用 droid.alarm_set, 通知触发用 /notif-trigger, 不重复造。
 /sense.policy get|set {"uplink":"text_only","retain_audio_days":3,"loc_mode":"stay",..}
     → {ok,policy,effective_from,source:"kv|default"}   真机免发版调参的抓手(等价 `/kv.set ga.sense.policy {..}`)
 /sense.data count|export|purge  三者共用与 query 同形状的 selector —— 删之前必须能精确预览删什么
     count  → {ok,n,bytes,blobs,span,confirm:"tok_.."}
     export {"fmt":"jsonl|md"} → {ok,path,n}            产物走用户可见路径 temp/sense_export_*.jsonl
     purge  {"confirm":"tok_..","cascade_pc":true} → {ok,deleted:{obs,blobs},pc:{cascaded,deleted,reason?},receipt,..}
     confirm token 只能来自本次 count 且与 selector 绑定(防「查 A 删 B」); purge 真删文件, 并写 purge.mark 墓碑,
     使「这段时间的数据被删过」在 query 的 gaps 里永远可见(墓碑/覆盖窗不进 count/purge 的选择集, 否则「删完
     复核 n==0」永远不成立; 要清它们得显式 kinds 点名)。级联给 PC 的永远是本机这次真删掉的那批 id, 只有
     「一个选择键都没给」才是全清 —— 表达不了就 cascaded:false + reason, 绝不退化成 all。PC 不可达 →
     cascaded:false + 挂队列, 下次 /sense.sync push|status 真去补删(purge_queue_flushed / purge_queue)。

── agent 侧(code_run 里 `import sense`; L2 组合只管「哪几个原子按什么顺序」, 判断与话术留在 L3 SOP) ──
 sense.log(obs) / sense.query(**selector) / sense.status() / sense.ingest(json)  —— L1 原子的 Python 直调
 sense.snapshot(label='')          此刻处境: 位置+同场信号+运动+前后 1h 日历(可选顺手记一条 note.user)
 sense.meeting_wrap(sid)           会议收尾: 停会话→收分片→登记待转写→借日历补参与者→推 PC
 sense.recall(q, frm, to, near, with_, kinds)  回忆: 硬过滤→证据充分性→{answerable, items, gaps, hint}
 sense.daily_digest(day_ts)        一天分层压缩: 按地点/同场者分桶 + 保留缺口(不调 LLM, 交给上层一次调用)

L0 契约(Kotlin 实现, 本模块只消费; 任何失败一律降级成 {granted:false, degraded_to:"bus_unavailable"}, 绝不抛给上层):
  GET  /sense/loc?mode=stay|move|once  GET /sense/near  GET /sense/cal?from&to  GET /sense/motion
  POST /sense/session {action,sources,label}   POST /sense/mic {action:"segments",sid}
  POST /sense/perm {action,kinds,wait_ms}(按需授权, 由 session start 内部驱动)  POST /sense/keepalive {action}(A16 保活自检)

── 加一个原子要动的地方(唯一权威清单; 缺任一处 = 静默半残, 场景图谱见 memory/sense_scenarios_sop.md §4) ──
  1) L0  SenseService.kt: object Sense 加 fun <atom>(ctx,b), 先校验 action(unknown_action), 全程 runCatching, 回统一 ok()/degraded_to;
  2) L0  BusServer.kt **两处**: ROUTE_DOCS 一行契约(即 HELP) + routes 一条 senseJson{ Sense.<atom>(...) };
  3) L1  本文件 **三处**: _h_<atom>(v,a)(verb 白名单→_err('unknown_verb')) + 注册进 _SUBS + 更新上面这段契约列表;
  4) L3  memory/sense_sop.md §3 表加一行(入参+出参不变量); memory/sense_scenarios_sop.md §3 原子表加一行(含安卓边界);
  android_entry.py 无需改 —— /sense.* 整族由单条转发覆盖(见其 :2561)。

存储: GA_DIR/temp/.sense/(非官方文件路径 —— Evolution.pruneRemoved 只清「baseline 里有而新包没有」的文件, 不碰这里)。
  sqlite3 不可用/建库失败 → 自动落 append-only JSONL, 读写路径全在降级态可用, status 里标 storage=jsonl。
  ⚠已知风险: `/cleartemp` 会整体删 temp/ 下非会话文件, 本模块靠 kv 里的 ga.sense.stat 在重建后补一条 purge.mark
  墓碑(reason=cleared), 保证「数据没了」这件事仍以缺口的形式被看见, 而不是变成沉默的失忆。
"""
import hashlib
import json
import math
import os
import re
import threading
import time

GA_DIR = os.environ.get('GA_DIR') or os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(GA_DIR, 'temp', '.sense')          # 内部数据: `.` 前缀不进「生成的文件」产物列表
BLOBS = os.path.join(DIR, 'blobs')
DB = os.path.join(DIR, 'tl.db')
OUT = os.path.join(GA_DIR, 'temp')                    # 导出/回执: 用户可见路径, 与内部 .sense/ 分开

# 默认值的方向就是产品红线: 采得更少、留得更短、传得更少。kv 读不到/解析失败时原样退回这一份。
POLICY = {'uplink': 'text_only', 'retain_audio_days': 3, 'retain_text_days': 365, 'loc_mode': 'stay',
          # vad_rms=0 即不做能量门控: 门控错杀是「静默丢帧」, 缺口都留不下, 比多存一段更危险(键名与 L0 一致)
          'seg_ms': 300000, 'vad_rms': 0, 'near_period_ms': 600000, 'peers_allow': ['peer_self'],
          # near_period_ms/quiet_* 本轮只存不生效(无周期扫描与静默判定的执行体): 保留键位以免热更改名, 但
          # SOP 里必须标明未生效 —— 把没实现的开关说成隐私保护, 比没有这个开关更伤信任。
          'quiet_apps': [], 'quiet_places': [], 'stay_r_m': 80, 'stay_min_ms': 300000,
          'abstain_min_cov': 0.999, 'sync_max_bytes': 524288, 'blob_cap_mb': 512}
_ENUM = {'uplink': ('text_only', 'text_and_audio'), 'loc_mode': ('stay', 'move', 'off')}
_LIM = {'retain_audio_days': (0, 90), 'retain_text_days': (1, 3650), 'seg_ms': (30000, 900000), 'vad_rms': (0, 8000),
        'near_period_ms': (60000, 3600000), 'sync_max_bytes': (16384, 524288), 'blob_cap_mb': (16, 4096),
        'stay_r_m': (20, 2000), 'stay_min_ms': (60000, 7200000)}

_COLS = ('id', 'ts', 'ts_end', 'ts_ingest', 'tz_off', 'kind', 'source', 'sid', 'place_id', 'peers',
         'lat', 'lon', 'acc_m', 'text', 'meta', 'blob_ref', 'conf', 'valid', 'synced')
_ECOLS = ('id', 'type', 'name', 'fp', 'lat', 'lon', 'r_m', 'n', 'first_ts', 'last_ts', 'meta', 'created_ts')
_BCOLS = ('id', 'path', 'bytes', 'sha256', 'kind', 'ts', 'dur_ms', 'asr', 'synced', 'expires_at', 'meta')
_TBL = {'obs': _COLS, 'entity': _ECOLS, 'blob': _BCOLS}
_META_KINDS = ('session.win', 'purge.mark')           # 覆盖窗与墓碑: 只喂 evidence, 不当内容返回
_TOMB_KIND = 'purge.mark'                             # 唯一会「自己命中自己」的 kind(区间就是刚删掉的那段), 删除口径只排除它

_DDL = """
CREATE TABLE IF NOT EXISTS obs(id TEXT PRIMARY KEY, ts INTEGER, ts_end INTEGER, ts_ingest INTEGER, tz_off INTEGER,
 kind TEXT, source TEXT, sid TEXT, place_id TEXT, peers TEXT, lat REAL, lon REAL, acc_m REAL, text TEXT,
 meta TEXT, blob_ref TEXT, conf REAL, valid INTEGER, synced INTEGER);
CREATE INDEX IF NOT EXISTS obs_ts ON obs(ts);
CREATE INDEX IF NOT EXISTS obs_kt ON obs(kind, ts);
CREATE INDEX IF NOT EXISTS obs_geo ON obs(lat, lon);
CREATE INDEX IF NOT EXISTS obs_sy ON obs(synced, ts);
CREATE TABLE IF NOT EXISTS entity(id TEXT PRIMARY KEY, type TEXT, name TEXT, fp TEXT, lat REAL, lon REAL,
 r_m REAL, n INTEGER, first_ts INTEGER, last_ts INTEGER, meta TEXT, created_ts INTEGER);
CREATE INDEX IF NOT EXISTS ent_fp ON entity(type, fp);
CREATE TABLE IF NOT EXISTS blob(id TEXT PRIMARY KEY, path TEXT, bytes INTEGER, sha256 TEXT, kind TEXT,
 ts INTEGER, dur_ms INTEGER, asr TEXT, synced INTEGER, expires_at INTEGER, meta TEXT);
CREATE INDEX IF NOT EXISTS blob_ts ON blob(ts);
"""

_lk = threading.RLock()
_S = {'db': None, 'mode': 'db', 'rtree': False, 'err': '', 'wiped': False, 'stat': 0, 'l0_down': 0}

# ── 小工具(纯函数) ────────────────────────────────────────────────────────────
def _now(): return int(time.time() * 1000)
def _s(v): return str(v)[:64] if v else ''
def _day(ts): return time.strftime('%Y%m%d', time.localtime(ts / 1000.0))
def _h(*parts): return hashlib.sha256('|'.join([str(p) for p in parts]).encode('utf-8')).hexdigest()[:20]

def _tzoff():
    lt = time.localtime()
    return int(-(time.altzone if (time.daylight and lt.tm_isdst) else time.timezone) // 60)

def _i(v, d=0):
    try: return int(v)
    except Exception: return d

def _f(v, d=None):
    try: return d if v is None else float(v)          # 缺值走默认(不是 None): 调用方给了 d 就是要 d, 否则夹紧/半径全成 None 崩在下游
    except Exception: return d

def _dist_m(la1, lo1, la2, lo2):
    p = math.pi / 180.0
    a = math.sin((la2 - la1) * p / 2) ** 2 + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2
    return 2 * 6371000.0 * math.asin(min(1.0, math.sqrt(a)))

def _bbox(lat, lon, r_m):
    """圆的外接矩形: 给 SQL 做可索引粗筛, 精确半径由 _match 复核(索引只许放大召回, 不许决定语义)。"""
    dla, dlo = r_m / 111320.0, r_m / max(1.0, 111320.0 * math.cos(lat * math.pi / 180.0))
    return (lat - dla, lat + dla, lon - dlo, lon + dlo)

def _err(code, **kw):
    kw['ok'] = 0
    kw['error'] = code
    return kw

# ── kv(与 android_entry._kv_path 同槽位: 用户可用 /kv.set 直接调参, 不必发版) ──
def _kv_path(k):
    d = os.path.join(GA_DIR, 'kv')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, re.sub(r'[^A-Za-z0-9._-]', '_', k)[:64] + '.json')

def _kv_get(k, d=''):
    try:
        with open(_kv_path(k), encoding='utf-8') as f: return f.read()
    except Exception: return d

def _kv_put(k, text):
    try:
        p = _kv_path(k)
        tmp = '%s.%d.tmp' % (p, os.getpid())
        with open(tmp, 'w', encoding='utf-8') as f: f.write(text)
        os.replace(tmp, p)                            # 原子替换: 写途中被杀要么完整旧值要么完整新值
        return True
    except Exception: return False

def _kv_obj(k, d):
    try: v = json.loads(_kv_get(k, '') or 'null')
    except Exception: v = None
    return v if isinstance(v, type(d)) else d

def _clamp(k, v):
    if k in _ENUM:
        return v if v in _ENUM[k] else POLICY[k]
    if k in _LIM:
        n = _i(v, None)
        return POLICY[k] if n is None else max(_LIM[k][0], min(_LIM[k][1], n))
    if isinstance(POLICY[k], list):
        return [str(x)[:64] for x in v][:64] if isinstance(v, list) else POLICY[k]
    if isinstance(POLICY[k], float):
        x = _f(v, None)
        return POLICY[k] if x is None else max(0.0, min(1.0, x))
    return POLICY[k]

def _policy():
    """出错时不猜: 逐键校验, 单个键非法只把该键退回保守默认, 不因一个坏键放弃整份策略。"""
    p = dict(POLICY)
    got = _kv_obj('ga.sense.policy', {})
    for k in got:
        if k in POLICY:
            p[k] = _clamp(k, got[k])
    return p

# ── 存储层(唯一副作用集中处; sqlite → JSONL 双模, 语义由同一份纯函数 _match 决定) ──
def _mkdir():
    for d in (DIR, BLOBS, OUT):
        try: os.makedirs(d, exist_ok=True)
        except Exception: pass

def _db():
    """取连接并自愈。库文件被 `/cleartemp` 整体删掉后旧连接仍指向已 unlink 的 inode(写进去=悄悄丢),
    所以每次先确认文件还在——静默故障必须被发现并记成缺口, 不能装作还在工作。"""
    with _lk:
        c = _S['db']
        if c is not None:
            if os.path.exists(DB): return c
            try: c.close()
            except Exception: pass
            _S['db'], _S['wiped'] = None, True
        if _S['mode'] == 'jsonl': return None
        try:
            import sqlite3
            _mkdir()
            c = sqlite3.connect(DB, check_same_thread=False, timeout=8)
            c.executescript(_DDL)
            try:
                c.execute('PRAGMA journal_mode=WAL')
                c.execute('CREATE VIRTUAL TABLE IF NOT EXISTS obs_rt USING rtree(rid,minLat,maxLat,minLon,maxLon)')
                # 开库即对账重建: 上次跑在无索引态(或索引被弃用)时写入的行不在表里, 而 IF NOT EXISTS 会造出一张
                # 空表看起来「可用」—— 半满索引会让 near 查询静默漏行, 比没索引危险得多。
                if c.execute('SELECT (SELECT count(*) FROM obs WHERE lat IS NOT NULL)-(SELECT count(*) FROM obs_rt)').fetchone()[0]:
                    c.execute('INSERT OR REPLACE INTO obs_rt SELECT rowid,lat,lat,lon,lon FROM obs WHERE lat IS NOT NULL')
                _S['rtree'] = True
            except Exception:
                _S['rtree'] = False                   # 无 R*Tree 模块 → 退 bbox 列 + (lat,lon) 普通索引, 结果形状不变
            c.commit()
            _S['db'] = c
        except Exception as e:
            _S['mode'], _S['err'] = 'jsonl', str(e)[:120]
            return None
        if _S['wiped']:
            _S['wiped'] = False
            _tomb_cleared()
        return _S['db']

def _jpath(t, ts=None):
    return os.path.join(DIR, ('tl-%s.jsonl' % _day(ts if ts else _now())) if t == 'obs' else (t + '.jsonl'))

def _jappend(t, rows):
    _mkdir()
    by = {}
    for r in rows:
        by.setdefault(_jpath(t, r.get('ts')), []).append(r)
    for p, rs in by.items():
        with open(p, 'a', encoding='utf-8') as f:
            for r in rs:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')

def _jread(t, frm=None, to=None):
    """JSONL 降级态读: 同 id 后写覆盖先写(与 DB 的 INSERT OR REPLACE 同语义)。"""
    out = {}
    try: names = sorted(os.listdir(DIR))
    except Exception: return []
    d0, d1 = (_day(frm) if frm else ''), (_day(to) if to else '~')
    for n in names:
        if t == 'obs':
            if not (n.startswith('tl-') and n.endswith('.jsonl')): continue
            if (d0 and n[3:-6] < d0) or (d1 != '~' and n[3:-6] > d1): continue   # 文件名即日期分区: 范围外整文件跳过
        elif n != os.path.basename(_jpath(t)):
            continue
        try:
            with open(os.path.join(DIR, n), encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        r = json.loads(line)
                        out[r.get('id')] = r
        except Exception:
            continue                                  # 单文件损坏不拖垮整次读取(其余数据仍可用)
    return list(out.values())

def _put_t(t, rows):
    """写入路径永不失败: DB 不可用即落 JSONL。返回写入条数。"""
    rows = [r for r in rows if r]
    if not rows:
        return 0
    if t == 'obs' and [r for r in rows if r.get('kind') in _PEER_KINDS or r.get('kind') == 'session.win']:
        _S['pcache'] = {}                             # 同场者/会话窗一变, _ses_peers 的缓存立刻作废: 缓存过期=漏人=放行
    cols = _TBL[t]
    c = _db()
    with _lk:
        if c is not None:
            try:
                c.executemany('INSERT OR REPLACE INTO %s(%s) VALUES(%s)' % (t, ','.join(cols), ','.join(['?'] * len(cols))),
                              [tuple(r.get(k) for k in cols) for r in rows])
                c.commit()
                if t == 'obs':
                    _rt_put([r for r in rows if r.get('lat') is not None])
                _stat_touch(rows if t == 'obs' else [])
                return len(rows)
            except Exception as e:
                _S['err'] = str(e)[:120]              # DB 出问题就地转 JSONL: 宁可慢, 不可丢
                _S['mode'] = 'jsonl'
                _S['db'] = None
        try:
            _jappend(t, rows)
            _stat_touch(rows if t == 'obs' else [])
            return len(rows)
        except Exception as e:
            _S['err'] = str(e)[:120]
            return 0

def _rt_put(rows):
    """R*Tree 只是加速器: 任何失败立即整体弃用(并删表), 绝不留「半满索引」——查询会漏行, 比没索引危险。"""
    if not rows or not _S['rtree']:
        return
    c = _S['db']
    try:
        c.executemany('INSERT OR REPLACE INTO obs_rt(rid,minLat,maxLat,minLon,maxLon) '
                      'SELECT rowid,?,?,?,? FROM obs WHERE id=?',
                      [(r['lat'], r['lat'], r['lon'], r['lon'], r['id']) for r in rows])
        c.commit()
    except Exception:
        _S['rtree'] = False
        try:
            c.execute('DROP TABLE IF EXISTS obs_rt')
            c.commit()
        except Exception:
            pass

def _stat_touch(rows):
    """记「我们确实有过 A..B 的数据」到 kv(限频 1h): temp/ 被清后靠它补墓碑, 让失忆以缺口形式可见。"""
    if not rows or _now() - _S['stat'] < 3600000:
        return
    _S['stat'] = _now()
    st = _kv_obj('ga.sense.stat', {})
    ts = [r['ts'] for r in rows]
    st['first_ts'] = min([x for x in [st.get('first_ts')] + ts if x])
    st['last_ts'] = max([x for x in [st.get('last_ts'), max(ts)] if x])
    _kv_put('ga.sense.stat', json.dumps(st))

def _tomb_cleared():
    st = _kv_obj('ga.sense.stat', {})
    if st.get('first_ts') and st.get('last_ts'):
        _put_t('obs', [_norm({'id': 'obs_cleared_%d' % st['last_ts'], 'kind': 'purge.mark', 'ts': st['first_ts'],
                              'ts_end': st['last_ts'], 'source': 'phone', 'valid': False,
                              'payload': {'reason': 'cleared', 'note': 'temp/ 被清理, 该区间数据已不存在'}})])

def _all_t(t):
    c = _db()
    if c is None:
        return _jread(t)
    try:
        with _lk:
            cur = c.execute('SELECT %s FROM %s' % (','.join(_TBL[t]), t))
            return [dict(zip(_TBL[t], row)) for row in cur.fetchall()]
    except Exception:
        return _jread(t)

def _del_t(t, ids):
    """真删(不是标记删除)。JSONL 态用整文件重写实现: 慢但确定。"""
    ids = list(ids)
    if not ids:
        return 0
    _S['pcache'] = {}                                 # 与 _put_t 同理: 行一增删就可能改变同场者集合, 缓存不许比数据旧
    c = _db()
    with _lk:
        if c is not None:
            try:
                for i in range(0, len(ids), 400):
                    ck = ids[i:i + 400]
                    q = ','.join(['?'] * len(ck))
                    if t == 'obs' and _S['rtree']:
                        c.execute('DELETE FROM obs_rt WHERE rid IN (SELECT rowid FROM obs WHERE id IN (%s))' % q, ck)
                    c.execute('DELETE FROM %s WHERE id IN (%s)' % (t, q), ck)
                c.commit()
                return len(ids)
            except Exception as e:
                _S['err'] = str(e)[:120]
                return 0
        drop = set(ids)
        keep = [r for r in _jread(t) if r.get('id') not in drop]
        own = (lambda n: n.startswith('tl-') and n.endswith('.jsonl')) if t == 'obs' else \
              (lambda n: n == os.path.basename(_jpath(t)))
        try:
            for n in os.listdir(DIR):                 # 整分区重写: 慢但确定, 降级态也必须是真删而不是标记删
                if own(n):
                    os.remove(os.path.join(DIR, n))
            _jappend(t, keep)
        except Exception as e:
            _S['err'] = str(e)[:120]
            return 0
        return len(ids)

def _put_obs_new(rows):
    """只新增, 绝不覆盖已存在的 id。给「外部副本回流」这类路径用: 远端那份可能是本机上行时被 consent
    遮挡过的空壳, 覆盖回来就是不可逆销毁, 且没有第二份可补。「不覆盖」必须是这条路径的形状, 不能靠调用方自觉。
    返回真正新增的行(调用方据此报数, 免得把「本机已有、原样保住」说成「拉回来了」)。"""
    rows = [r for r in rows if r]
    have = set([x['id'] for x in _scan({'ids': [r['id'] for r in rows], 'include_invalid': True})]) if rows else set()
    new = [r for r in rows if r['id'] not in have]
    _put_t('obs', new)
    return new

# ── observation 信封 ─────────────────────────────────────────────────────────
def _peers_str(v):
    ps = sorted(set([_s(x) for x in v if x])) if isinstance(v, (list, tuple)) else ([_s(v)] if v else [])
    return (',' + ','.join(ps) + ',') if ps else ''

def _norm(o):
    """任意来源的一条观测 → 统一信封(DB-ready)。id 由内容派生 ⇒ 重放/断点续传/多入口写天然幂等。
    三个时间戳分开(发生/结束/入库)是三个独立系统的共同教训: 只留一个, 「某个时间段」的查询一定算错。"""
    m = o.get('payload') if isinstance(o.get('payload'), dict) else (o.get('meta') if isinstance(o.get('meta'), dict) else {})
    g = o.get('geo') if isinstance(o.get('geo'), dict) else {}
    ts = _i(o.get('ts_start', o.get('ts', o.get('t0'))), _now())
    mj = json.dumps(m, ensure_ascii=False, sort_keys=True)
    if len(mj) > 16000:
        mj = json.dumps({'_truncated': len(mj)})      # 截断 JSON 会变成非法 JSON, 宁可只留一个可解释的标记
    r = {'ts': ts, 'ts_end': max(ts, _i(o.get('ts_end', o.get('t1')), ts)), 'ts_ingest': _i(o.get('ts_ingest'), _now()),
         'tz_off': _i(o.get('tz_off'), _tzoff()), 'kind': str(o.get('kind') or 'note.user')[:40],
         'source': str(o.get('source') or 'phone')[:16], 'sid': _s(o.get('sid')), 'place_id': _s(o.get('place_id')),
         'peers': _peers_str(o.get('peers') or o.get('peer_ids') or []),
         'lat': _f(g.get('lat', o.get('lat'))), 'lon': _f(g.get('lon', o.get('lon'))),
         'acc_m': _f(g.get('acc_m', o.get('acc_m'))), 'text': str(o.get('text') or m.get('text') or '')[:8000],
         'meta': mj, 'blob_ref': _s(o.get('blob_ref') or o.get('blob')), 'conf': _f(o.get('conf'), 1.0),
         'valid': 0 if o.get('valid') is False else 1, 'synced': _i(o.get('synced'), 0)}
    r['id'] = _s(o.get('id')) or 'obs_' + _h(r['kind'], r['ts'], r['source'], r['text'], r['meta'], r['blob_ref'])
    return r

def _meta(r):
    try:
        m = json.loads(r.get('meta') or '{}')
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}

_PEER_KINDS = ('near.scan', 'cal.event')              # 唯二真的记下了「当时有谁在场」的 kind
_CONTENT_KINDS = ('asr.text', 'audio.seg', 'note.user')   # 承载原话的 kind: 同场者没标注时必须按未授权处理

def _peers_at(sid, t0, t1, slack=None):
    """这段时间的同场者 = 该时窗(±near 扫描周期容差)内 near.scan / cal.event 记到的 peer 并集。
    near 是周期扫描, 不给容差就会因为「这一分片正好没扫」而漏人 —— 漏人=放行, 只能往「多算一个人」偏。
    别的会话的扫描不算数; 没标 sid 的扫描算数(采集层常在会话外扫, 排除它等于把人漏掉)。"""
    slack = _policy()['near_period_ms'] if slack is None else slack
    ps = set()
    for r in _scan({'from': _i(t0) - slack, 'to': _i(t1) + slack, 'kinds': list(_PEER_KINDS), 'include_invalid': True}):
        if sid and r.get('sid') and r['sid'] != sid:
            continue
        ps.update([p for p in (r.get('peers') or '').split(',') if p])
    return sorted(ps)

def _ses_peers(sid):
    """会话级同场者(检索层兜底判据): 有覆盖窗就用窗的时段, 没有就用该 sid 全部行的时段。
    结果缓存到下一次 near/cal/session 写入为止 —— 每行都回表扫一遍会让一次 query 退化成 O(行数×表)。"""
    c = _S.setdefault('pcache', {})
    if sid not in c:
        w = _by_id('obs_ses_' + sid)
        rows = [] if w else _scan({'sid': sid, 'include_invalid': True})
        t0 = w['ts'] if w else min([r['ts'] for r in rows] or [_now()])
        t1 = (_now() if _meta(w).get('open') else w['ts_end']) if w else max([r['ts_end'] for r in rows] or [t0])
        c[sid] = _peers_at(sid, t0, t1)
    return c[sid]

def _consent_ok(r, allow):
    """allow=None = 调用方不做 consent 过滤(内部路径)。同场者只要有一个没授权, 这条就只留存在性。
    空 peers 不等于「当时没别人」: audio.seg 落行时采集层可能没标, asr.text 又继承自它。所以承载原话的
    kind 在没标注时回会话再问一次同场者, 问到未授权的人就按未授权处理 —— 标注缺失必须落到保护侧。
    机主自己的记录(无 sid 的手记 / peer_self)不受影响: 没有任何同场证据时照常放行。"""
    if allow is None:
        return True
    ps = [p for p in (r.get('peers') or '').split(',') if p]
    if ps:
        return set(ps).issubset(allow)
    if r.get('kind') in _CONTENT_KINDS and r.get('sid'):
        return set(_ses_peers(r['sid'])).issubset(allow)
    return True

def _out(r, allow=None):
    """行 → 对外 observation。consent 过滤在这里(检索层)做: 模型听得懂 ≠ 会保护, 不能指望 LLM 自律。
    只清 text 是清不干净的: payload 常另存一份原文(note.user 就是), blob_ref 更是直接指向原始音频 ——
    留任何一条都等于把「只回存在性」这句话作废, 所以三者同清。"""
    ps = [p for p in (r.get('peers') or '').split(',') if p]
    red = '' if _consent_ok(r, allow) else 'peer_consent'
    d = {'id': r.get('id'), 'sid': r.get('sid') or None, 'kind': r.get('kind'), 'source': r.get('source'),
         'ts_start': r.get('ts'), 'ts_end': r.get('ts_end'), 'ts_ingest': r.get('ts_ingest'), 'tz_off': r.get('tz_off'),
         'geo': ({'lat': r.get('lat'), 'lon': r.get('lon'), 'acc_m': r.get('acc_m')} if r.get('lat') is not None else None),
         'place_id': r.get('place_id') or None, 'peers': ps, 'conf': r.get('conf'), 'valid': bool(r.get('valid')),
         'text': '' if red else (r.get('text') or ''), 'payload': {} if red else _meta(r),
         'blob_ref': None if red else (r.get('blob_ref') or None)}
    if red:
        d['redacted'] = red
    return d

# ── selector: query / data 共用同一形状(删之前必须能精确预览删什么) ─────────────
_SEL_KEYS = ('from', 'to', 'as_of', 'kinds', 'sid', 'with', 'q', 'ids', 'near', 'unsynced')

def _sel_given(a):
    """调用方到底给没给选择器 —— 「删这一部分」与「删全部」的分界线, 也是 confirm token 的绑定面。
    必须列全 _prep 认识的每一个键: 漏一个, 那个维度上就既没绑定也会被当成「没给选择器」。"""
    return [k for k in _SEL_KEYS if a.get(k) not in (None, '', [], {}, False)]

def _prep(a):
    """外部 selector → 内部形状(一次解析, 之后 _match 保持纯函数)。"""
    s = {'from': _i(a.get('from'), None) if a.get('from') is not None else None,
         'to': _i(a.get('to'), None) if a.get('to') is not None else None,
         'as_of': _i(a.get('as_of'), None) if a.get('as_of') else None,
         'kinds': [str(k)[:40] for k in a.get('kinds') or []] or None,
         'sid': _s(a.get('sid')) or None, 'with': [_s(p) for p in a.get('with') or [] if p] or None,
         'q': (str(a.get('q')).lower() if a.get('q') else None), 'ids': list(a.get('ids') or []) or None,
         'include_invalid': bool(a.get('include_invalid')), 'unsynced': bool(a.get('unsynced')),
         'near': None, '_bbox': None, '_places': None}
    n = a.get('near') if isinstance(a.get('near'), dict) else None
    if n:
        if n.get('place'):
            s['near'] = {'place': _s(n['place'])}
            s['_places'] = [s['near']['place']]
        elif n.get('lat') is not None and n.get('lon') is not None:
            r_m = _f(n.get('radius_m', n.get('r_m')), 300.0) or 300.0
            s['near'] = {'lat': _f(n['lat']), 'lon': _f(n['lon']), 'radius_m': r_m}
            s['_bbox'] = _bbox(s['near']['lat'], s['near']['lon'], r_m)
            s['_places'] = [p['id'] for p in _all_t('entity')      # 无坐标的文本行靠 place 落进圈内, 否则「某地聊了什么」永远查不到
                            if p.get('type') == 'place' and p.get('lat') is not None
                            and _dist_m(s['near']['lat'], s['near']['lon'], p['lat'], p['lon']) <= r_m + (p.get('r_m') or 0)]
    return s

def _match(r, s):
    """硬过滤的唯一语义来源(DB 与 JSONL 两条路径共用): SQL 只做粗筛, 降级态不会悄悄换一套规则。"""
    if s.get('from') is not None and r['ts_end'] < s['from']:
        return False
    if s.get('to') is not None and r['ts'] > s['to']:
        return False
    if s.get('as_of') and r['ts_ingest'] > s['as_of']:
        return False
    if s.get('kinds') and r['kind'] not in s['kinds']:
        return False
    if s.get('sid') and r['sid'] != s['sid']:
        return False
    if s.get('ids') and r['id'] not in s['ids']:
        return False
    if s.get('with') and not all((',' + p + ',') in (r['peers'] or '') for p in s['with']):
        return False                                   # with 取 AND: 「和张三李四一起」比 OR 精确, 且可预期
    if s.get('q') and s['q'] not in ((r['text'] or '') + (r['meta'] or '')).lower():
        return False
    if s.get('near') and not _near_hit(r, s):
        return False
    if s.get('unsynced') and r.get('synced'):
        return False
    if not s.get('include_invalid') and not r['valid']:
        return False
    return True

def _near_hit(r, s):
    n = s['near']
    if r.get('place_id') and r['place_id'] in (s.get('_places') or []):
        return True
    if 'lat' not in n or r.get('lat') is None:
        return False
    return _dist_m(n['lat'], n['lon'], r['lat'], r['lon']) <= n['radius_m']

def _sql(s):
    w, ar = ['1=1'], []
    if s.get('from') is not None:
        w.append('ts_end>=?')
        ar.append(s['from'])
    if s.get('to') is not None:
        w.append('ts<=?')
        ar.append(s['to'])
    if s.get('as_of'):
        w.append('ts_ingest<=?')
        ar.append(s['as_of'])
    if s.get('kinds'):
        w.append('kind IN (%s)' % ','.join(['?'] * len(s['kinds'])))
        ar += list(s['kinds'])
    if s.get('sid'):
        w.append('sid=?')
        ar.append(s['sid'])
    if s.get('ids'):
        w.append('id IN (%s)' % ','.join(['?'] * len(s['ids'])))
        ar += list(s['ids'])                          # 幂等判重在写入热路径上, 必须走主键而不是全表扫
    if s.get('unsynced'):
        w.append('synced=0')                          # 走 obs_sy 索引: 同步是热路径, 不能每轮全表扫
    if not s.get('include_invalid'):
        w.append('valid=1')
    bb, pl = s.get('_bbox'), (s.get('_places') or [])
    if bb or pl:
        parts = []
        if bb:
            parts.append('obs.rowid IN (SELECT rid FROM obs_rt WHERE maxLat>=? AND minLat<=? AND maxLon>=? AND minLon<=?)'
                         if _S['rtree'] else '(lat>=? AND lat<=? AND lon>=? AND lon<=?)')
            ar += [bb[0], bb[1], bb[2], bb[3]]
        if pl:
            parts.append('place_id IN (%s)' % ','.join(['?'] * len(pl)))
            ar += pl
        w.append('(%s)' % ' OR '.join(parts))
    return ' AND '.join(w), ar

def _scan(a, cap=0, prepped=False):
    s = a if prepped else _prep(a)
    c = _db()
    rows = []
    if c is not None:
        try:
            where, ar = _sql(s)
            lim = (' LIMIT %d' % (cap * 4 + 200)) if cap else ''   # 过取: 精确半径/子串还要再筛一轮
            with _lk:
                cur = c.execute('SELECT %s FROM obs WHERE %s ORDER BY ts DESC%s' % (','.join(_COLS), where, lim), ar)
                rows = [dict(zip(_COLS, x)) for x in cur.fetchall()]
        except Exception as e:
            _S['err'] = str(e)[:120]
            rows = _jread('obs', s.get('from'), s.get('to'))
    else:
        rows = _jread('obs', s.get('from'), s.get('to'))
    rows = [r for r in rows if _match(r, s)]
    rows.sort(key=lambda r: r['ts'], reverse=True)
    return rows[:cap] if cap else rows

def _by_id(oid):
    r = _scan({'ids': [oid], 'include_invalid': True}, cap=1)
    return r[0] if r else None

# ── 证据与缺口: 把「没在采集」和「没发生」分开, 拒答能力下沉到数据层 ──────────
def _merge(iv):
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out

def _minus(iv, cut):
    """区间差(纯函数)。被静音/被抢麦的那几分钟, 服务确实在跑但拿不到东西 —— 算成「已覆盖」就等于用
    在场证明冒充证据, 是本设计最不能犯的错。"""
    out = []
    for a, b in iv:
        segs = [(a, b)]
        for c, d in cut:
            segs = [x for s in segs for x in ((s[0], min(s[1], c)), (max(s[0], d), s[1])) if x[0] < x[1]]
        out += segs
    return out

_SRC_OF = {'asr.text': 'mic', 'audio.seg': 'mic', 'audio.gap': 'mic', 'loc.fix': 'loc', 'near.scan': 'near'}

def _needs(kinds):
    """问的是哪几类内容 ⇒ 当时得有哪几个源真的开着。没点名 kinds = 问「那段发生了什么」, 不设要求。"""
    return sorted(set([_SRC_OF[k] for k in (kinds or []) if k in _SRC_OF]))

def _ses_close(live):
    """L0 是「会话是否还在跑」的唯一真值(服务被 OEM/任务管理器停掉时 L1 无从自知)。把幻影窗闭到最后一条真实
    数据, 其后如实成 not_capturing —— 窗一直开着 = 覆盖率永远 1.0, 「没录到」会被答成「没发生」。"""
    n = 0
    for r in _scan({'kinds': ['session.win'], 'include_invalid': True}):
        m = _meta(r)
        if not m.get('open') or (r['sid'] and r['sid'] == live):
            continue
        m['open'], m['closed_by'] = 0, 'no_service'
        end = max([r['ts']] + [x['ts_end'] for x in (_scan({'sid': r['sid'], 'include_invalid': True}) if r['sid'] else [])
                               if x['id'] != r['id']])
        _put_t('obs', [_norm({'id': r['id'], 'kind': 'session.win', 'sid': r['sid'], 'ts': r['ts'],
                              'ts_end': end, 'payload': m})])
        n += 1
    return n

def _data_end(r):
    """一个开着的窗在「L0 说不上话」时最多能算到哪: 最后一条属于它的真实数据(与 _ses_close 同口径)。
    窗开着不等于真在采 —— 服务被杀/进程被冻的窗会一直开着, 拿它按 _now() 计就是用在场证明冒充证据。"""
    ts = [x['ts_end'] for x in (_scan({'sid': r['sid'], 'include_invalid': True}) if r['sid'] else []) if x['id'] != r['id']]
    return min(_now(), max([r['ts']] + ts))

def _cover(frm, to, need=()):
    """采集覆盖窗 = session.win 行(只有 L0 确认起了会话才会写, 所以它是真覆盖而不是自称覆盖)。
    返回 (覆盖, 开着会话但所问的源没开, L0 探针结论)。只开了定位的会话不能替录音作证 —— 拿它当覆盖,
    「零命中」就会被说成「没聊过」。窗里没记 sources(旧行/从 PC 拉回的行)一律按「不能作证」处理。"""
    # 扫描不设 from 下界: 开着的窗 ts_end 恒等于起点(_norm 的 max(ts,ts)), 设了下界就会把「正在录的这一场」
    # 整个滤掉, 于是活会话期间凡 from>会话起点的查询覆盖率恒为 0。区间裁剪交给下面的取交, 语义不变。
    sel = {'to': to, 'kinds': ['session.win'], 'include_invalid': True}
    rows = _scan(sel)
    l0 = ''
    if [r for r in rows if _meta(r).get('open')]:      # 有开着的窗才问 L0(冷路径), 顺手把幻影窗收敛掉
        # force: 这是每次回忆才走一次的冷路径, 不该吃总线静默期 —— 冷却里直接拿降级形状会让下面按「问不到」处理,
        # 而那 20 秒里真会话的覆盖会被算成没采到(反向的假缺口)。
        st = _l0('/sense/session', body={'action': 'status'}, force=True)
        l0 = 'live' if st.get('ok') else (st.get('degraded_to') or 'l0_error')
        if st.get('ok') and _ses_close(_s(st.get('sid'))):
            rows = _scan(sel)
    iv, off = [], []
    for r in rows:
        m = _meta(r)
        # 三种窗三种口径: 已闭合按落盘的 ts_end; L0 确认还在跑的开窗算到此刻(L0 是"是否在采"的唯一真值);
        # 问不到 L0 的开窗只认有真实数据佐证的那段 —— 存疑时退向拒答, 而不是替一台可能早就没在采的机器作证。
        end = r['ts_end'] if not m.get('open') else (_now() if l0 == 'live' else _data_end(r))
        a, b = max(frm, r['ts']), min(to, end)
        src = m.get('sources') or {}
        if b > a:
            (iv if all((src.get(x) or {}).get('state') == 'on' for x in need) else off).append((a, b))
    return _merge(iv), _merge(off), l0

def _gap(a, b, off):
    """会话开着但这个源没开(只开了定位却问录音) → source_off; 压根没在采 → not_capturing。对用户的说法不同。"""
    return {'from': a, 'to': b, 'reason': 'source_off' if any(x < b and a < y for x, y in off) else 'not_capturing'}

def _evidence(s, rows):
    frm, to = s.get('from'), s.get('to')
    if frm is None or to is None:
        ts = [r['ts'] for r in rows] + [r['ts_end'] for r in rows]
        frm = frm if frm is not None else (min(ts) if ts else _now() - 86400000)
        to = to if to is not None else (max(ts) if ts else _now())
    span = max(1, to - frm)
    cov, off, l0 = _cover(frm, to, _needs(s.get('kinds')))
    gaps, cur = [], frm
    for a, b in cov:
        if a > cur:
            gaps.append(_gap(cur, a, off))
        cur = max(cur, b)
    if cur < to:
        gaps.append(_gap(cur, to, off))
    bad = []
    for r in _scan({'from': frm, 'to': to, 'include_invalid': True}):   # 只按时间范围取: 缺口是「这段时间的事实」, 与内容过滤无关
        if not r['valid']:                            # 静音/被抢麦/通话/配额/已删: 保留为显式缺口而不是丢弃
            gaps.append({'from': r['ts'], 'to': r['ts_end'],
                         'reason': _meta(r).get('reason') or ('purged' if r['kind'] == 'purge.mark' else 'invalid')})
            bad.append((max(frm, r['ts']), min(to, r['ts_end'])))
    covered = sum([b - a for a, b in _minus(cov, _merge(bad))])
    ratio = round(min(1.0, covered / float(span)), 4)
    gaps.sort(key=lambda g: g['from'])
    ev = {'n_hits': len(rows), 'span_ms': span, 'span_covered_ms': covered, 'coverage_ratio': ratio,
          'gaps': gaps[:24], 'gaps_truncated': len(gaps) > 24}
    if l0 and l0 != 'live':
        ev['l0'] = l0                                 # 有窗开着却问不到 L0:「说不准那段到底在不在采」必须对上层可见
    return ev, ratio

# ── L0(Kotlin/Bus) 与 PC(pclink) 出口: 失败一律降级, 绝不抛到上层 ─────────────
_L0_COOLDOWN = 20000                                  # 总线不通时的静默期: 每次 droid._base() 都要 ping 一轮(实测 ~2s),
                                                      # 采集是高频循环, 逐次重探等于持续耗电还拖慢每条命令; 冷却内直接给降级形状。
def _l0(path, params=None, body=None, timeout=10, force=False):
    """复用 droid 的端口发现与连接池(bus_port.txt 缺失时它会回退默认端口并验活), 不另起一套。"""
    down = {'ok': 0, 'granted': False, 'degraded_to': 'bus_unavailable'}
    if not force and _now() - _S['l0_down'] < _L0_COOLDOWN:
        return dict(down, cached=1)
    try:
        import droid
        url = droid._base() + path
        r = (droid._SESSION.post(url, json=body, timeout=timeout) if body is not None
             else droid._SESSION.get(url, params=params or {}, timeout=timeout))
        d = r.json()
        _S['l0_down'] = 0
        if isinstance(d, dict) and d.get('ok'):
            return d
        return {'ok': 0, 'granted': False, 'degraded_to': 'l0_error', 'detail': str(d)[:120]}
    except Exception as e:
        # 读超时 ≠ 总线死亡: near 按契约就能睡满 10s, 一次慢答让全部端点静默 20 秒, 等于拿一次慢答伪造一台坏机器
        # (用户随后那句「开始记录」会在一个字节都没发的情况下被回成 unsupported)。只有连不上才算总线下线。
        slow = 'ReadTimeout' in type(e).__name__
        if not slow:
            _S['l0_down'] = _now()
        return dict(down, degraded_to=('l0_timeout' if slow else 'bus_unavailable'), detail=str(e)[:120])

def _pc(path, obj, method='POST'):
    """走已有 PC 互联通道。未配对/未连接一律当「PC 不可达」(不是错误); 不连就不发, 免得撞 _api 超时把 socket 弄断。"""
    try:
        import pclink
        st = json.loads(pclink.handle('/pclink.status') or '{}')
        if not (st.get('paired') and st.get('connected')):
            return None
        body = json.dumps(obj, separators=(',', ':'), ensure_ascii=False)
        if method == 'GET':                           # hub 的检索是 GET ?sel=<json>; pclink 按空格切 'METHOD 目标 [body]', 故整串转义
            from urllib.parse import quote
            cmd = '/pclink.api GET %s?sel=%s' % (path, quote(body))
        else:
            cmd = '/pclink.api POST %s %s' % (path, body)
        r = json.loads(pclink.handle(cmd) or '{}')
        return r if isinstance(r, dict) else None
    except Exception:
        return None

def _dev():
    d = _kv_get('ga.sense.dev', '')
    if not d:
        d = 'dev_' + _h(GA_DIR, _now())
        _kv_put('ga.sense.dev', d)
    return d

# ── entity(place / peer 共用一张表: 同一个模式的两个实例) ─────────────────────
def _ent(t, eid=None, fp=None):
    for e in _all_t('entity'):
        if e.get('type') == t and ((eid and e['id'] == eid) or (fp and e.get('fp') == fp)):
            return e
    return None

def _ent_put(e):
    _put_t('entity', [e])
    return e

_VISIT_GAP = 1800000                                  # 隔多久再见到才算「又一次」

def _ent_touch(e, ts):
    # n 是场次不是采样次数: 静止时每次轮询都 +1, n_visits/n_meets 就成了假话(「上个月见了张三 300 次」)
    if not e.get('n') or ts - (e.get('last_ts') or 0) > _VISIT_GAP:
        e['n'] = (e.get('n') or 0) + 1
    e['first_ts'] = min([x for x in [e.get('first_ts'), ts] if x])
    e['last_ts'] = max([x for x in [e.get('last_ts'), ts] if x])
    return _ent_put(e)

def _ent_new(t, fp, ts, **kw):
    e = {'id': ('plc_' if t == 'place' else 'peer_') + _h(t, fp), 'type': t, 'name': '', 'fp': fp,
         'lat': kw.get('lat'), 'lon': kw.get('lon'), 'r_m': kw.get('r_m'), 'n': 0, 'first_ts': ts,
         'last_ts': ts, 'meta': json.dumps(kw.get('meta') or {}, ensure_ascii=False), 'created_ts': ts}
    return _ent_put(e)

def _ent_out(e):
    m = _meta(e)
    d = {'id': e['id'], 'name': e.get('name') or None, 'n': e.get('n') or 0,
         'first_ts': e.get('first_ts'), 'last_ts': e.get('last_ts'), 'meta': m}
    if e.get('type') == 'place':
        d.update({'named_by': 'user' if e.get('name') else ('auto' if m.get('auto_name') else 'none'),
                  'centroid': ({'lat': e['lat'], 'lon': e['lon']} if e.get('lat') is not None else None),
                  'r_m': e.get('r_m'), 'anchor': m.get('anchor') or ('geo' if e.get('lat') is not None else 'wifi_h'),
                  'n_visits': e.get('n') or 0})
    else:
        d.update({'consent': m.get('consent') or 'none', 'signals': m.get('signals') or {}, 'n_meets': e.get('n') or 0})
    return d

def _place_for(lat, lon, wifi_h='', ts=None):
    """坐标/WiFi 指纹 → 稳定地点实体。无任何定位权限时 place 由 wifi 指纹定义(零定位权限即可用, 隐私最温和)。"""
    ts = ts or _now()
    pol = _policy()
    if lat is not None and lon is not None:
        best, bd = None, None
        for e in _all_t('entity'):
            if e.get('type') == 'place' and e.get('lat') is not None:
                d = _dist_m(lat, lon, e['lat'], e['lon'])
                if d <= max(pol['stay_r_m'], e.get('r_m') or 0) and (bd is None or d < bd):
                    best, bd = e, d
        if best is None:
            best = _ent_new('place', 'geo:%.5f,%.5f' % (lat, lon), ts, lat=lat, lon=lon, r_m=pol['stay_r_m'],
                            meta={'anchor': 'geo'})
        return _ent_touch(best, ts)['id'], (bd if bd is not None else 0.0)
    if wifi_h:
        e = _ent('place', fp='wifi:' + wifi_h) or _ent_new('place', 'wifi:' + wifi_h, ts, meta={'anchor': 'wifi_h'})
        return _ent_touch(e, ts)['id'], None
    return '', None

def _peer_for(kind, val, ts=None, stable=True):
    """只有稳定信号(已配对设备/日历参与者/用户标注)才建实体: A12+ MAC 随机化让随机 BLE 跨天不可比,
    据此建实体等于每天造一堆假人——降级成「认不出是谁」反而是更诚实也更隐私的形态。"""
    if not val or not stable:
        return ''
    e = _ent('peer', fp='%s:%s' % (kind, val)) or _ent_new('peer', '%s:%s' % (kind, val), ts or _now(),
                                                           meta={'consent': 'none', 'signals': {kind: [val]}})
    return _ent_touch(e, ts or _now())['id']

def _allow_set():
    """可返回原文的 peer 集合 = policy.peers_allow ∪ consent 明确为 self/granted 的实体。"""
    al = set(_policy()['peers_allow'])
    for e in _all_t('entity'):
        if e.get('type') == 'peer' and _meta(e).get('consent') in ('self', 'granted'):
            al.add(e['id'])
    return al

# ── blob ─────────────────────────────────────────────────────────────────────
def _blob_put(path, kind, ts, dur_ms=0, meta=None):
    """L0 每次回全量分片 ⇒ 重复登记是常态, 所以这里只能是「补登」: id 由 path+ts 派生必然撞上旧行, 重建整行
    会把 asr/synced/sha256 抹回初值 —— 已转写的分片被重新排队白转一遍, /sense.asr status 的计数跟着回退。
    文件已不在且本来就没这行 → 不建行(返回 None): 保留期删掉的分片不该以指向空文件的僵尸行复活。"""
    _mkdir()
    try:
        n = os.path.getsize(path)
    except Exception:
        n = 0
    bid = 'blob_' + _h(path, ts)
    old = _blob(bid) or {}
    if not n and not old and not os.path.isfile(path):
        return None
    pol = _policy()
    m = _meta(old)
    m.update(meta or {})
    b = {'id': bid, 'path': path, 'bytes': n or _i(old.get('bytes')), 'sha256': old.get('sha256') or '', 'kind': kind,
         'ts': ts, 'dur_ms': _i(dur_ms) or _i(old.get('dur_ms')), 'asr': old.get('asr') or '',
         'synced': _i(old.get('synced')), 'expires_at': ts + pol['retain_audio_days'] * 86400000,
         'meta': json.dumps(m, ensure_ascii=False)}
    _put_t('blob', [b])
    return b

def _blob(bid):
    for b in _all_t('blob'):
        if b['id'] == bid:
            return b
    return None

def _blob_out(b):
    return {'id': b['id'], 'kind': b.get('kind'), 'ts': b.get('ts'), 'dur_ms': b.get('dur_ms'),
            'bytes': b.get('bytes'), 'uploaded': bool(b.get('synced')), 'asr': b.get('asr') or 'none',
            'expires_at': b.get('expires_at'), 'path': b.get('path')}

def _unlink(paths):
    k = 0
    for p in paths:
        try:
            if p and os.path.isfile(p):
                os.remove(p)
                k += 1
        except Exception:
            pass
    return k

# ── 子命令 ───────────────────────────────────────────────────────────────────
def _h_session(v, a):
    if v not in ('start', 'stop', 'status'):
        return _err('unknown_verb', verb=v, want=['start', 'stop', 'status'])
    pol = _policy()
    # force: start/stop 是用户当次的显式动作, 每次只发一次请求, 「高频循环省电」的冷却理由不成立 ——
    # 被静默期挡住等于一个字节都没发就回「这台机器不支持采集」, 用户那次「开始记录」就白点了。
    r = _l0('/sense/session', body={'action': v, 'sources': a.get('sources') or ['mic'],
                                    'label': str(a.get('label') or '')[:64], 'sid': _s(a.get('sid')),
                                    # 采集参数由 kv 下发(免发版调参); L0 侧再夹一次区间, 两头都不信任对方的数
                                    'policy': {'seg_ms': pol['seg_ms'], 'vad_rms': pol['vad_rms'],
                                               'max_bytes': pol['blob_cap_mb'] * 1048576}},
            force=v in ('start', 'stop'))
    sid = _s(r.get('sid')) or _s(a.get('sid'))
    src = r.get('sources') if isinstance(r.get('sources'), dict) else {}
    dg = r.get('degraded_to') or ''
    if r.get('ok'):
        _ses_close(_s(r.get('sid')))                  # L0 说没在跑就闭窗: 服务被杀后窗还开着 = 假覆盖
    if not r.get('ok'):                               # 形状恒定: L0 不可达也给齐 mic/loc/near 三键(上层按键直取, 少一键就是一处崩)
        # 「试过了不行」与「冷却期内压根没试」要分得开, 否则排障时会去查一条完全健康的总线
        src = dict([(k, {'state': 'unsupported', 'reason': 'bus_cooldown' if r.get('cached') else dg})
                    for k in ('mic', 'loc', 'near')])
    elif v == 'start' and sid:                        # 只有 L0 确认起了会话才写覆盖窗: 没采集就不能有覆盖(假覆盖=假证据)
        _put_t('obs', [_norm({'id': 'obs_ses_' + sid, 'kind': 'session.win', 'sid': sid, 'ts': _i(r.get('started_at'), _now()),
                              'payload': {'open': 1, 'label': str(a.get('label') or '')[:64], 'sources': src}})])
    elif v == 'stop' and sid:
        old = _by_id('obs_ses_' + sid)
        if old:
            m = _meta(old)
            m['open'] = 0
            _put_t('obs', [_norm({'id': old['id'], 'kind': 'session.win', 'sid': sid, 'ts': old['ts'],
                                  'ts_end': _now(), 'payload': m})])
    return {'ok': 1, 'sid': sid or None, 'started_at': _i(r.get('started_at'), 0), 'label': str(a.get('label') or ''),
            # 没有会话就没有"已运行多久"。started_at 缺省成 0 时旧写法算出的是整个纪元, 真机上报成了
            # 56000 年 —— 一个明显假的数字比缺字段更糟, 因为上层会照着答。
            'sources': src, 'uptime_ms': (max(0, _now() - _i(r.get('started_at'), 0)) if _i(r.get('started_at'), 0) else 0), 'degraded_to': dg,
            'storage': _S['mode'], 'indicator': r.get('indicator') or {}}

def _h_mic(v, a):
    if v in ('status', 'probe'):                      # 麦克风状态是 session 的一个 source, 不另设 L0 端点(少一个契约就少一处漂移)
        r = _l0('/sense/session', body={'action': 'status', 'sid': _s(a.get('sid'))}, force=(v == 'probe'))
        mic = (r.get('sources') or {}).get('mic') if isinstance(r.get('sources'), dict) else None
        st = (mic or {}).get('state') or ('unknown' if not r.get('ok') else 'off')
        d = {'ok': 1, 'state': st, 'silenced': st == 'silenced', 'degraded_to': r.get('degraded_to') or ''}
        if v == 'probe':
            d['l0'] = bool(r.get('ok'))
            return d
        d['asr_pending'] = len([b for b in _all_t('blob') if b.get('kind') == 'audio' and b.get('asr') == 'pending'])
        d['rate'] = 16000
        return d
    if v != 'seg':
        return _err('unknown_verb', verb=v, want=['status', 'seg', 'probe'])
    r = _l0('/sense/mic', body={'action': 'segments', 'sid': _s(a.get('sid')), 'max_ms': _i(a.get('max_ms'), _policy()['seg_ms'])})
    if not r.get('ok'):
        return {'ok': 1, 'n': 0, 'ingested': [], 'gaps': [], 'degraded_to': r.get('degraded_to') or 'l0_error'}
    # sid 省略是 L0 的一等公民契约(=当前/最近一次会话), 它已解析好并逐条盖在分片上。丢掉它, 这一整场就以
    # sid='' 落库: sid 检索命中 0、会话窗塌成 0 长度, 明明录了却报「那段没在采集」。
    sid, rows, ing, gaps = _s(a.get('sid')) or _s(r.get('sid')), [], [], []
    for sg in (r.get('segments') or []):
        t0, t1 = _i(sg.get('from')), _i(sg.get('to'))
        s1 = _s(sg.get('sid')) or sid
        if sg.get('valid') is False or not sg.get('path'):
            g = {'from': t0, 'to': t1, 'reason': str(sg.get('reason') or 'unknown')[:40]}
            gaps.append(g)
            rows.append(_norm({'kind': 'audio.gap', 'sid': s1, 'ts': t0, 'ts_end': t1, 'valid': False, 'payload': g}))
            continue
        b = _blob_put(sg['path'], 'audio', t0, t1 - t0, {'sid': s1, 'codec': sg.get('codec') or ''})
        if not b:                                     # 文件已被保留期清掉: 如实成缺口, 不造一条指向空文件的行
            g = {'from': t0, 'to': t1, 'reason': 'blob_missing'}
            gaps.append(g)
            rows.append(_norm({'kind': 'audio.gap', 'sid': s1, 'ts': t0, 'ts_end': t1, 'valid': False, 'payload': g}))
            continue
        ing.append(b['id'])
        # peers 必须在这里标: asr.text 只会继承分片的同场者, 源头恒空就等于 consent 硬过滤对原话完全失效
        rows.append(_norm({'kind': 'audio.seg', 'sid': s1, 'ts': t0, 'ts_end': t1, 'blob_ref': b['id'],
                           'peers': _peers_at(s1, t0, t1),
                           'payload': {'bytes': b['bytes'], 'codec': sg.get('codec') or '', 'vad': sg.get('vad') or {}}}))
    _put_t('obs', rows)
    _watch_eval(rows)
    return {'ok': 1, 'n': len(rows), 'sid': sid or None, 'ingested': ing, 'gaps': gaps, 'degraded_to': ''}

def _h_loc(v, a):
    pol = _policy()
    if v == 'status':                                 # 只读本地视图: status 不该顺手打开传感器
        last = _scan({'kinds': ['loc.fix']}, cap=1)
        return {'ok': 1, 'mode': pol['loc_mode'], 'last': (_out(last[0]) if last else None), 'storage': _S['mode']}
    if v not in ('fix', 'watch'):
        return _err('unknown_verb', verb=v, want=['fix', 'watch', 'status'])
    mode = str(a.get('mode') or ('once' if v == 'fix' else pol['loc_mode']))
    if mode not in ('stay', 'move', 'once', 'off'):
        mode = 'once'
    # 客户端超时必须大于 L0 的最大阻塞时长, 否则慢答会被当成失败(定位等一次 fix 本来就慢); 键名/上下界与 L0 契约对齐
    tmo = min(max(_i(a.get('timeout_ms'), 8000), 500), 30000)
    r = _l0('/sense/loc', params={'mode': mode, 'timeout_ms': tmo}, timeout=tmo / 1000.0 + 5)
    fx = r.get('fix') if isinstance(r.get('fix'), dict) else None
    out = {'ok': 1, 'fix': None, 'granted': bool(r.get('granted')), 'provider': r.get('provider') or 'none',
           'mode': mode, 'place_id': None, 'degraded_to': r.get('degraded_to') or ('bus_unavailable' if not r.get('ok') else '')}
    if not fx:
        return out                                    # fix:null 仍 ok:1 ——「没拿到位置」是已知状态, 不是错误
    ts = _i(fx.get('ts'), _now())
    stale = max(0, _now() - ts)
    lat, lon = _f(fx.get('lat')), _f(fx.get('lon'))
    if lat is None or lon is None:
        return out                                    # 给了 fix 却没坐标: 当没拿到, 不往时间线塞一条没有坐标的「定位」
    pid, _d = _place_for(lat, lon, '', ts)
    # id 只认「这一次真实定位」(时刻+来源): stale_ms 每次调用都变, 落进派生 id 会让同一个缓存点被反复
    # 拉取时在时间线上变成 N 条 loc.fix —— 默认 loc_mode=stay 只吃缓存点, 那正是最常走的路径。
    row = _norm({'id': 'obs_loc_' + _h(ts, r.get('provider') or ''), 'kind': 'loc.fix', 'ts': ts,
                 'sid': _s(a.get('sid')), 'place_id': pid,
                 'geo': {'lat': lat, 'lon': lon, 'acc_m': _f(fx.get('acc_m'))},
                 'payload': {'provider': r.get('provider') or '', 'stale_ms': stale, 'mode': mode}})
    _put_t('obs', [row])
    out['fix'] = {'lat': lat, 'lon': lon, 'acc_m': _f(fx.get('acc_m')), 'ts': ts,
                  'provider': r.get('provider') or '', 'stale_ms': stale,
                  'valid': stale <= _i(a.get('max_stale_ms'), 120000)}
    out['place_id'] = pid or None
    return out

def _h_near(v, a):
    if v not in ('', 'scan'):
        return _err('unknown_verb', verb=v, want=['scan'])
    ms = min(max(_i(a.get('ms'), 8000), 500), 10000)   # 端侧先夹到 L0 契约内(SenseService 的 coerceIn 同界),
    r = _l0('/sense/near', params={'ms': ms}, timeout=ms / 1000.0 + 5)   # 再给足超时: 扫描睡满 ms 才回, 卡着不动是正常的
    ts = _now()
    wifi = r.get('wifi') if isinstance(r.get('wifi'), dict) else None
    wh = _s((wifi or {}).get('bssid_hash') or (wifi or {}).get('h'))
    ble = [{'h': _s(x.get('hash') or x.get('h')), 'rssi': _i(x.get('rssi'), 0), 'stable': bool(x.get('stable'))}
           for x in (r.get('ble') or []) if isinstance(x, dict)]
    paired = [{'h': _s(x.get('hash') or x.get('h')), 'name': str(x.get('name') or '')[:40], 'stable': True}
              for x in (r.get('paired') or []) if isinstance(x, dict)]
    peers = [p for p in [_peer_for('ble', x['h'], ts, True) for x in ble if x['stable']] +
             [_peer_for('bt', x['h'], ts, True) for x in paired] if p]
    pid, _d = _place_for(None, None, wh, ts) if wh else ('', None)
    row = _norm({'kind': 'near.scan', 'ts': ts, 'sid': _s(a.get('sid')), 'place_id': pid, 'peers': peers,
                 'payload': {'wifi': {'bssid_h': wh} if wh else None, 'ble': ble, 'paired': paired,
                             'caps': r.get('caps') or {}}})
    if r.get('ok'):
        _put_t('obs', [row])
    return {'ok': 1, 'ts': ts, 'wifi': ({'bssid_h': wh} if wh else None), 'ble': ble, 'paired': paired,
            'peers': peers, 'place_id': pid or None, 'granted': bool(r.get('granted')),
            'caps': r.get('caps') or {}, 'degraded_to': r.get('degraded_to') or ''}

def _h_cal(v, a):
    if v not in ('', 'range'):
        return _err('unknown_verb', verb=v, want=['range'])
    frm, to = _i(a.get('from'), _now() - 86400000), _i(a.get('to'), _now() + 86400000)
    lim = max(1, min(_i(a.get('limit'), 50), 200))     # limit 必须下传: L0 自己也截断(默认 50), 不传就永远只回 50 条
    r = _l0('/sense/cal', params={'from': frm, 'to': to, 'limit': lim})
    if not r.get('ok'):
        return {'ok': 1, 'granted': False, 'n': 0, 'events': [], 'degraded_to': r.get('degraded_to') or 'l0_error'}
    evs, rows = [], []
    for e in (r.get('events') or [])[:lim]:
        att = [x for x in (e.get('attendees') or []) if isinstance(x, dict)]
        pids = [p for p in [_peer_for('cal', _s(x.get('email_h') or x.get('name')), _i(e.get('start'), _now())) for x in att] if p]
        d = {'id': _s(e.get('id')), 'title': str(e.get('title') or '')[:200], 'start': _i(e.get('start')),
             'end': _i(e.get('end')), 'loc': str(e.get('location') or e.get('loc') or '')[:120],
             'attendees': [{'name': str(x.get('name') or '')[:40], 'email_h': _s(x.get('email_h'))} for x in att],
             'peer_ids': pids}
        evs.append(d)
        rows.append(_norm({'id': 'obs_cal_' + _h(d['id'], d['start']), 'kind': 'cal.event', 'ts': d['start'],
                           'ts_end': d['end'] or d['start'], 'peers': pids, 'text': d['title'], 'payload': d}))
    _put_t('obs', rows)
    return {'ok': 1, 'granted': True, 'n': len(evs), 'events': evs, 'degraded_to': ''}

def _h_motion(v, a):
    if v == 'range':
        rows = _scan({'from': _i(a.get('from'), _now() - 86400000), 'to': _i(a.get('to'), _now()), 'kinds': ['motion.state']})
        return {'ok': 1, 'n': len(rows), 'items': [_out(r) for r in rows[:_i(a.get('limit'), 200)]]}
    if v not in ('', 'now'):
        return _err('unknown_verb', verb=v, want=['now', 'range'])
    r = _l0('/sense/motion')
    st = str(r.get('state') or 'unknown')
    conf = _f(r.get('confidence'), None)
    conf = (conf / 100.0 if conf and conf > 1 else conf) or 0.0
    out = {'ok': 1, 'state': st, 'conf': conf, 'src': r.get('src') or ('none' if not r.get('ok') else ''),
           'granted': bool(r.get('granted')), 'degraded_to': r.get('degraded_to') or ''}
    if r.get('ok') and st != 'unknown':
        last = _scan({'kinds': ['motion.state'], 'from': _now() - 600000}, cap=1)
        if not last or _meta(last[0]).get('state') != st:   # 同状态 10 分钟内不重复落行: 时间线要的是状态切换, 不是心跳
            _put_t('obs', [_norm({'kind': 'motion.state', 'ts': _now(), 'text': st,
                                  'payload': {'state': st, 'conf': conf, 'src': r.get('src') or ''}})])
    return out

def _h_asr(v, a):
    if v == 'status':
        bs = [b for b in _all_t('blob') if b.get('kind') == 'audio']
        cnt = {'pending': 0, 'done': 0, 'failed': 0}
        for b in bs:
            if b.get('asr') in cnt:
                cnt[b['asr']] += 1
        pend = sorted([b for b in bs if b.get('asr') == 'pending'], key=lambda x: x.get('ts') or 0)
        return {'ok': 1, 'counts': cnt, 'pending': [_blob_out(b) for b in pend[:_i(a.get('limit'), 50)]],
                'engines': {'ondevice': False, 'cloud': False, 'pc': True},
                'note': 'phone-side streaming ASR is out of scope; register + write back only'}
    if v == 'seg':
        b = _blob(_s(a.get('blob')))
        if not b:
            return _err('no_blob', blob=_s(a.get('blob')))
        eng = str(a.get('engine') or 'pc')
        if b.get('asr') == 'done' and not a.get('force'):   # L0 每次回全量分片, 重复登记不能把已转写的打回待办(转写会被白做一遍)
            return {'ok': 1, 'queued': 0, 'blob': b['id'], 'engine': eng, 'state': 'done'}
        m = _meta(b)
        m.update({'engine': eng, 'lang': str(a.get('lang') or 'zh')[:8]})
        b['asr'] = 'pending'
        b['meta'] = json.dumps(m, ensure_ascii=False)
        _put_t('blob', [b])
        return {'ok': 1, 'queued': 1, 'blob': b['id'], 'engine': eng}
    if v != 'result':
        return _err('unknown_verb', verb=v, want=['seg', 'status', 'result'])
    b = _blob(_s(a.get('blob')))
    if not b:
        return _err('no_blob', blob=_s(a.get('blob')))
    seg = [r for r in _scan({'kinds': ['audio.seg'], 'from': b['ts'] - 1, 'to': b['ts'] + 1, 'include_invalid': True})
           if r.get('blob_ref') == b['id']]
    src = seg[0] if seg else None                     # 转写文本继承分片的会话/地点/同场者: 上下文丢了就无法做时空+人的硬过滤
    if a.get('ok') is False:
        b['asr'] = 'failed'
        _put_t('blob', [b])
        _put_t('obs', [_norm({'kind': 'audio.gap', 'ts': b['ts'], 'ts_end': b['ts'] + (b.get('dur_ms') or 0),
                              'blob_ref': b['id'], 'valid': False,
                              'payload': {'reason': str(a.get('reason') or 'asr_failed')[:40]}})])
        return {'ok': 1, 'n': 0, 'ids': [], 'state': 'failed'}
    # 分片行找不到(被删/旧行)或它自己没标同场者时, 回时间窗再算一次: 继承链断在哪一环都会让原话失去 consent 保护
    ssid = (src or {}).get('sid') or _s(_meta(b).get('sid'))
    speers = [p for p in ((src or {}).get('peers') or '').split(',') if p] or _peers_at(ssid, b['ts'], b['ts'] + _i(b.get('dur_ms')))
    rows = []
    for sg in (a.get('segs') or []):
        t0 = b['ts'] + _i(sg.get('t0'))
        rows.append(_norm({'kind': 'asr.text', 'ts': t0, 'ts_end': b['ts'] + _i(sg.get('t1'), _i(sg.get('t0'))),
                           'sid': ssid, 'place_id': (src or {}).get('place_id') or '', 'peers': speers,
                           'blob_ref': b['id'], 'text': str(sg.get('text') or ''), 'conf': _f(sg.get('conf'), 1.0),
                           'source': str(a.get('source') or 'pc')[:16],
                           'payload': {'spk': sg.get('spk'), 'engine': str(a.get('engine') or 'pc')}}))
    n = _put_t('obs', rows)
    b['asr'] = 'done'
    _put_t('blob', [b])
    _watch_eval(rows)
    return {'ok': 1, 'n': n, 'ids': [r['id'] for r in rows], 'state': 'done'}

def _h_log(v, a):
    if v:
        return _err('unknown_verb', verb=v, want=['<obs json>'])
    items = a if isinstance(a, list) else [a]
    rows = [_norm(x) for x in items if isinstance(x, dict)]
    if not rows:
        return _err('bad_obs')
    have = set([r['id'] for r in _scan({'ids': [r['id'] for r in rows], 'include_invalid': True})])
    n = _put_t('obs', rows)
    _watch_eval(rows)
    return {'ok': 1, 'n': n, 'ids': [r['id'] for r in rows], 'dedup': len(have), 'storage': _S['mode']}

def _h_query(v, a):
    if v not in ('', 'run'):
        return _err('unknown_verb', verb=v, want=['<selector json>'])
    s = _prep(a)
    rows = _scan(s, prepped=True)
    allow = _allow_set()
    if s.get('q'):
        # 按内容搜索时, 未授权同场者的行连「命中」都不给: 只清原文挡不住逐词试探(q='报价' 命中即确认了对方说过它),
        # 那等于把 consent 过滤降级成一次一比特的问答。存在性仍可用时间/地点/人查到, 那才是「只保留存在性」。
        rows = [r for r in rows if _consent_ok(r, allow)]
    ev, ratio = _evidence(s, rows)
    kw = s.get('kinds') or []
    items = [r for r in rows if r['kind'] not in _META_KINDS or r['kind'] in kw]   # 覆盖窗/墓碑只喂 evidence, 显式点名才当内容
    if str(a.get('order') or '') == 'ts':
        items = sorted(items, key=lambda r: r['ts'])   # 默认 -ts(新→旧, _scan 已排); order:"ts" 表示正序
    lim = max(1, min(_i(a.get('limit'), 50), 500))
    return {'ok': 1, 'n': min(len(items), lim), 'total': len(items), 'items': [_out(r, allow) for r in items[:lim]],
            'filters_applied': {'from': s['from'], 'to': s['to'], 'near': s['near'], 'with': s['with'],
                                'kinds': s['kinds'], 'q': a.get('q') or None, 'as_of': s['as_of']},
            # 拒答判据只看覆盖率: 覆盖满而零命中 = 「那段时间确实没发生」, 是可以答的; 覆盖不满才是「我不知道」
            'evidence': ev, 'abstain_hint': bool(ratio < _policy()['abstain_min_cov']),
            'storage': _S['mode']}

def _h_place(v, a):
    ps = [e for e in _all_t('entity') if e.get('type') == 'place']
    if v in ('', 'list'):
        ps.sort(key=lambda e: e.get('last_ts') or 0, reverse=True)
        return {'ok': 1, 'n': len(ps), 'places': [_ent_out(e) for e in ps[:_i(a.get('limit'), 100)]]}
    if v == 'name':
        e = _ent('place', eid=_s(a.get('place_id')))
        if not e:
            return _err('no_place', place_id=_s(a.get('place_id')))
        e['name'] = str(a.get('name') or '')[:40]
        return {'ok': 1, 'place': _ent_out(_ent_put(e))}
    if v == 'resolve':
        lat, lon = _f(a.get('lat')), _f(a.get('lon'))
        if lat is None or lon is None:
            e = _ent('place', fp='wifi:' + _s(a.get('wifi_h')))
            return {'ok': 1, 'place_id': (e['id'] if e else None), 'dist_m': None, 'conf': 1.0 if e else 0.0}
        best, bd = None, None
        for e in ps:
            if e.get('lat') is not None:
                d = _dist_m(lat, lon, e['lat'], e['lon'])
                if bd is None or d < bd:
                    best, bd = e, d
        ok = best is not None and bd <= max(_policy()['stay_r_m'], best.get('r_m') or 0)
        return {'ok': 1, 'place_id': (best['id'] if ok else None), 'dist_m': (round(bd, 1) if bd is not None else None),
                'conf': round(max(0.0, 1.0 - (bd or 0) / 500.0), 2) if ok else 0.0}
    if v != 'stays':
        return _err('unknown_verb', verb=v, want=['list', 'stays', 'name', 'resolve'])
    pol = _policy()
    fixes = sorted(_scan({'from': _i(a.get('from'), _now() - 86400000), 'to': _i(a.get('to'), _now()),
                          'kinds': ['loc.fix']}), key=lambda r: r['ts'])
    stays = _stays([(r['ts'], r['lat'], r['lon']) for r in fixes if r.get('lat') is not None],
                   _f(a.get('r_m'), pol['stay_r_m']), _i(a.get('min_ms'), pol['stay_min_ms']))
    out = []
    for t0, t1, lat, lon, n in stays:
        pid, _d = _place_for(lat, lon, '', t0)
        out.append({'from': t0, 'to': t1, 'centroid': {'lat': round(lat, 6), 'lon': round(lon, 6)},
                    'n_fix': n, 'place_id': pid or None})
    return {'ok': 1, 'n': len(out), 'stays': out}

def _stays(pts, r_m, min_ms):
    """纯函数: 有序 (ts,lat,lon) → 停留段 [(t0,t1,lat,lon,n)]。连续点落在半径 r 内且驻留 > T 即一次停留。"""
    out, cur = [], []

    def flush():
        if len(cur) >= 2 and cur[-1][0] - cur[0][0] >= min_ms:
            out.append((cur[0][0], cur[-1][0], sum([p[1] for p in cur]) / len(cur), sum([p[2] for p in cur]) / len(cur), len(cur)))
    for p in pts:
        if cur:
            cla = sum([x[1] for x in cur]) / len(cur)
            clo = sum([x[2] for x in cur]) / len(cur)
            if _dist_m(cla, clo, p[1], p[2]) > r_m:
                flush()
                cur = []
        cur.append(p)
    flush()
    return out

def _h_peer(v, a):
    ps = [e for e in _all_t('entity') if e.get('type') == 'peer']
    if v in ('', 'list'):
        ps.sort(key=lambda e: e.get('last_ts') or 0, reverse=True)
        return {'ok': 1, 'n': len(ps), 'peers': [_ent_out(e) for e in ps[:_i(a.get('limit'), 200)]]}
    if v == 'name':
        e = _ent('peer', eid=_s(a.get('peer_id')))
        if not e:
            return _err('no_peer', peer_id=_s(a.get('peer_id')))
        m = _meta(e)
        if a.get('name') is not None:
            e['name'] = str(a.get('name') or '')[:40]
        if a.get('consent') in ('none', 'self', 'granted'):
            m['consent'] = a['consent']               # consent 是检索层硬过滤依据, 只能由用户显式动作改
        e['meta'] = json.dumps(m, ensure_ascii=False)
        _ent_put(e)                                   # 先把 consent 落库, 下面的放行集才是改之后的口径
        rearm = []
        if a.get('consent') in ('self', 'granted'):
            # 之前只把存在性推给 PC 的行(synced=2): 同意之后重新排队上行, 否则这次同意等于没生效。判据是
            # 「当初被扣留、现在按新 consent 能出原文」—— 不能只找 peers 里写了这个 id 的行: 采集层没标全人、
            # 靠会话级同场者才被扣下的那些行, 用 with 一条也找不回来。
            # 反向(收回同意)推不回来, 只能靠 purge —— 这一点由 sense_privacy_sop 明写给用户, 不在这里假装能撤。
            allow = _allow_set()
            rearm = [dict(x, synced=0) for x in _scan({'include_invalid': True})
                     if x.get('synced') == 2 and _consent_ok(x, allow)]
            _put_t('obs', rearm)
        return {'ok': 1, 'peer': _ent_out(e), 'resync': len(rearm)}
    if v == 'merge':
        src, dst = _ent('peer', eid=_s(a.get('from'))), _ent('peer', eid=_s(a.get('into')))
        if not src or not dst or src['id'] == dst['id']:
            return _err('bad_merge', **{'from': _s(a.get('from')), 'into': _s(a.get('into'))})
        rows = [r for r in _scan({'with': [src['id']], 'include_invalid': True})]
        for r in rows:
            r['peers'] = _peers_str([p for p in r['peers'].split(',') if p and p != src['id']] + [dst['id']])
        _put_t('obs', rows)
        ms, md = _meta(src), _meta(dst)
        sig = md.get('signals') or {}
        for k, vs in (ms.get('signals') or {}).items():
            sig[k] = sorted(set(list(sig.get(k) or []) + list(vs)))
        md['signals'] = sig
        dst['meta'] = json.dumps(md, ensure_ascii=False)
        dst['n'] = (dst.get('n') or 0) + (src.get('n') or 0)
        _ent_put(dst)
        _del_t('entity', [src['id']])
        return {'ok': 1, 'peer': _ent_out(dst), 'moved': len(rows)}
    if v != 'resolve':
        return _err('unknown_verb', verb=v, want=['list', 'name', 'merge', 'resolve'])
    sg = a.get('signals') if isinstance(a.get('signals'), dict) else {}
    stable = a.get('stable') is not False
    for k, val in (('cal', sg.get('cal_attendee')), ('bt', sg.get('bt_h')), ('spk', sg.get('spk'))):
        if val:
            had = bool(_ent('peer', fp='%s:%s' % (k, _s(val))))
            pid = _peer_for(k, _s(val), _now(), stable)
            if pid:
                return {'ok': 1, 'peer_id': pid, 'created': not had, 'signal': k}
    for h in (sg.get('ble_h') or []):
        e = _ent('peer', fp='ble:' + _s(h))
        if e:
            return {'ok': 1, 'peer_id': e['id'], 'created': False, 'signal': 'ble'}
    return {'ok': 1, 'peer_id': None, 'created': False, 'reason': 'no_stable_signal'}

_PCQ_CHUNK = 400                                      # 一次级联最多带这么多 id: pclink 传的是整串 JSON 命令行

def _purge_body(ids, wipe=False):
    """级联删除的请求体, 只有两种合法形状: 按 id 删, 或调用方显式说的全清。
    按 id 是唯一不会歧义的形状 —— 选择器在两端的口径差(near 半径键名、q 匹配到整条 JSON、PC 不认 sid/ids)
    只会让 PC 删多或删少, 而 id 就是本机刚刚真删掉的那一批, 两侧删的必然是同一个集合。
    绝不允许「selector 表达不了就退化成 all:1」: 那是把「删这一场会」静默升级成「抹掉整个档案库」。"""
    return {'all': 1} if wipe else ({'selector': {'ids': list(ids)}} if ids else None)

def _pc_why(r):
    return 'pc_unreachable' if r is None else str(r.get('code') or r.get('error') or 'pc_rejected')[:60]

def _pc_purge(ids, wipe=False):
    """级联删除的唯一出口。返回 (成功, PC 已删条数, 原因, 未删的 id)。分批发, 任一批没成就整体算没成 ——
    回一个删了一半的 cascaded:true, 比回 false 更伤: 隐私 SOP 会照着它对用户说「已删干净」。"""
    if wipe:
        r = _pc('/api/sense/purge', _purge_body([], True))
        return (bool(r and r.get('ok')), _i((r or {}).get('deleted')), _pc_why(r), [])
    ids = list(ids)
    if not ids:
        return (False, 0, 'no_ids', [])
    n = 0
    for i in range(0, len(ids), _PCQ_CHUNK):
        r = _pc('/api/sense/purge', _purge_body(ids[i:i + _PCQ_CHUNK]))
        if not (r and r.get('ok')):
            return (False, n, _pc_why(r), ids[i:])
        n += _i(r.get('deleted'))
    return (True, n, '', [])

def _pcq_drain():
    """purge 时 PC 不可达会挂队列。不排干净, 「已排队等 PC 上线」就只是句好听的话 —— 删除承诺必须真兑现,
    所以每次同步顺手补删; 删不掉的留在队列里继续可见, 不悄悄丢。"""
    q = _kv_obj('ga.sense.pcq', [])
    if not q:
        return 0
    left, done = [], 0
    for x in q:
        ids, wipe = list(x.get('ids') or []), bool(x.get('all'))
        if not (ids or wipe):
            continue                                  # 老格式(只存 selector)的条目: 旧代码会把它当 all:1 全清, 迁移时宁可丢弃也不照旧
        ok, _n, _w, rest = _pc_purge(ids, wipe)
        if ok:
            done += 1
        else:
            left.append(dict(x, ids=rest))            # 只留还没删掉的那部分: 重试不该把已删的再算一遍
    if len(left) != len(q):
        _kv_put('ga.sense.pcq', json.dumps(left, ensure_ascii=False))
    return done

def _h_sync(v, a):
    pol = _policy()
    cur = _kv_obj('ga.sense.cursor', {})
    if v == 'status':
        flushed = _pcq_drain()                         # 查状态先补删: 用户看到的欠账必须是此刻的真值
        pend = len(_scan({'unsynced': True, 'include_invalid': True}))
        try:
            import pclink
            st = json.loads(pclink.handle('/pclink.status') or '{}')
        except Exception:
            st = {}
        return {'ok': 1, 'pending': pend, 'cursor': cur, 'storage': _S['mode'], 'purge_queue_flushed': flushed,
                'purge_queue': len(_kv_obj('ga.sense.pcq', [])),   # 还欠 PC 几笔删除: 说了排队就得看得见
                'pc': {'reachable': bool(st.get('connected')), 'paired': bool(st.get('paired')),
                       'endpoint': '/api/sense/ingest'}}
    if v == 'pull':
        since = _i(a.get('since'), _i(cur.get('pull'), 0))
        # PC 侧只有 GET /api/sense/query(与本机 selector 同形), 没有 pull 端点 —— 拉回就是「按时间反查自己的档案」
        r = _pc('/api/sense/query', {'from': since, 'limit': 200}, method='GET')
        if not r or not r.get('ok'):
            return {'ok': 1, 'pulled': 0, 'pc': {'reachable': bool(r)}, 'cursor': cur}
        items = [x for x in (r.get('items') or []) if isinstance(x, dict)]
        # pull 是「补本机没有的行」, 不是「以 PC 为准镜像回来」: PC 上那份是本机上行时被 consent 遮挡过的
        # 空壳(text/payload/blob_ref 全空, id 却与本地同一行), 回灌就是用空壳覆盖原文, 而且没有第二份可补。
        # redacted 的一律不收(它按定义就是本机自己上去的存在性), 其余交给 _put_obs_new 保证不覆盖已有行。
        rows = [_norm(dict(x, source=str(x.get('source') or 'pc'), synced=1)) for x in items if not x.get('redacted')]
        new = _put_obs_new(rows)                       # 从 PC 拉回的直接标 synced: 否则下一轮又推回去, 形成乒乓
        cur['pull'] = max([_i(x.get('ts_start')) for x in items] + [since])   # PC 按 ts 升序返回, 故最大事件时刻即断点
        _kv_put('ga.sense.cursor', json.dumps(cur))
        return {'ok': 1, 'pulled': len(new), 'kept_local': len(rows) - len(new), 'redacted_skipped': len(items) - len(rows),
                'cursor': cur, 'pc': {'reachable': True}}
    if v not in ('', 'push'):
        return _err('unknown_verb', verb=v, want=['push', 'status', 'pull'])
    flushed = _pcq_drain()    # 删除承诺先于新数据上行, 且没有待推数据时也要补删 —— 用户删完就再没同步过是常态
    cap = min(_i(a.get('max_bytes'), pol['sync_max_bytes']), 524288)   # 512KB 硬顶: HTTPExporter 8MB + base64 涨 33%,
    sel = {'kinds': a.get('kinds') or None, 'unsynced': True, 'include_invalid': True}  # 且 _api 超时会 _drop 整条 socket
    todo = sorted(_scan(sel), key=lambda r: r['ts'])                   # → 贴着上限走 = 造重连风暴, 故按时间预算切批
    allow = _allow_set()      # consent 必须在出设备之前过滤: PC 侧没有 peer 表, 代不了我们把关, 上去了也收不回
    batch, size, held = [], 0, 0
    for r in todo:
        o = _out(r, allow)
        b = len(json.dumps(o, ensure_ascii=False).encode('utf-8')) + 2
        if batch and size + b > cap:
            break
        batch.append(r)
        size += b
        held += 1 if o.get('redacted') else 0
    if a.get('dry_run'):
        return {'ok': 1, 'pushed': 0, 'bytes': size, 'pending': len(todo), 'batch': len(batch),
                'held_consent': held, 'dry_run': True}
    if not batch:
        return {'ok': 1, 'pushed': 0, 'bytes': 0, 'pending': 0, 'cursor': cur, 'purge_queue_flushed': flushed,
                'pc': {'endpoint': '/api/sense/ingest'}}
    out = [_out(x, allow) for x in batch]
    r = _pc('/api/sense/ingest', {'items': out, 'cursor': _s(cur.get('pc'))})
    took = _i((r or {}).get('accepted'), 0) + _i((r or {}).get('dup'), 0)   # dup=PC 早就有了, 与新收下等价
    if not r or not r.get('ok') or took < len(batch):
        # 只认逐条回执: 字段名一旦对不上, PC 会回 ok:1/accepted:0, 光看 ok 就会把根本没落盘的一批标成已同步(静默丢档)。
        # 不足额一律整批不标: PC 按 obs.id 幂等去重, 重推零副作用, 比猜哪几条丢了安全。
        return {'ok': 1, 'pushed': 0, 'bytes': 0, 'pending': len(todo), 'queued': len(todo), 'cursor': cur,
                'pc': {'reachable': bool(r), 'endpoint': '/api/sense/ingest',
                       'status': (r or {}).get('error') or (r and 'partial_%d/%d' % (took, len(batch))) or 'unreachable'}}
    for x, o in zip(batch, out):
        # 只有 PC 确认后才标已同步: 同步失败绝不丢本地数据。2 = 只上行了存在性, consent 改判后要重推带原文的版本
        x['synced'] = 2 if o.get('redacted') else 1
    _put_t('obs', batch)
    cur['push'] = batch[-1]['ts']
    cur['id'] = batch[-1]['id']
    cur['pc'] = _s(r.get('next_cursor'))               # PC 的不透明游标: 原样回带, 端侧不解释它的含义
    _kv_put('ga.sense.cursor', json.dumps(cur))
    return {'ok': 1, 'pushed': len(batch), 'bytes': size, 'pending': len(todo) - len(batch), 'cursor': cur,
            'held_consent': held, 'purge_queue_flushed': flushed,
            'pc': {'reachable': True, 'endpoint': '/api/sense/ingest', 'ver': _i(r.get('ver'), 1)}}

def _h_blob(v, a):
    bs = _all_t('blob')
    pol = _policy()
    used = sum([b.get('bytes') or 0 for b in bs])
    quota = {'used_mb': round(used / 1048576.0, 2), 'cap_mb': pol['blob_cap_mb']}
    if v in ('', 'list'):
        since = _i(a.get('since'), 0)
        sel = sorted([b for b in bs if (b.get('ts') or 0) >= since], key=lambda b: b.get('ts') or 0, reverse=True)
        return {'ok': 1, 'n': len(sel), 'blobs': [_blob_out(b) for b in sel[:_i(a.get('limit'), 100)]], 'quota': quota}
    if v == 'put':
        p = str(a.get('path') or '')
        if not p or not os.path.isfile(p):
            return _err('no_file', path=p[:120])
        b = _blob_put(p, str(a.get('kind') or 'audio'), _i(a.get('ts'), _now()), _i(a.get('dur_ms')), a.get('meta') or {})
        return {'ok': 1, 'blob': _blob_out(b), 'quota': quota} if b else _err('no_file', path=p[:120])
    if v == 'get':
        b = _blob(_s(a.get('id')))
        return {'ok': 1, 'blob': _blob_out(b)} if b else _err('no_blob', id=_s(a.get('id')))
    if v == 'purge':
        days = _i(a.get('older_than_days'), pol['retain_audio_days'])
        cut = _now() - days * 86400000
        old = [b for b in bs if (b.get('ts') or 0) < cut]
        k = _unlink([b.get('path') for b in old])
        _del_t('blob', [b['id'] for b in old])
        if old:                                        # 「为什么没有原文」必须可解释, 不能静默消失
            _put_t('obs', [_norm({'kind': 'audio.gap', 'ts': min([b['ts'] for b in old]),
                                  'ts_end': max([b['ts'] + (b.get('dur_ms') or 0) for b in old]), 'valid': False,
                                  'payload': {'reason': 'retention', 'days': days, 'n': len(old)}})])
        return {'ok': 1, 'deleted': len(old), 'files': k, 'quota': quota}
    if v != 'upload':
        return _err('unknown_verb', verb=v, want=['list', 'put', 'get', 'upload', 'purge'])
    b = _blob(_s(a.get('id')))
    if not b:
        return _err('no_blob', id=_s(a.get('id')))
    if pol['uplink'] != 'text_and_audio' and not a.get('force'):
        return _err('uplink_blocked', policy=pol['uplink'], hint='音频出设备必须是显式动作: force=true 或改 policy.uplink')
    import base64
    ck = min(_i(a.get('chunk_bytes'), 262144), 262144)
    seq, sent, done = _i(a.get('seq'), 0), 0, False
    try:
        total = (os.path.getsize(b['path']) + ck - 1) // ck
        with open(b['path'], 'rb') as f:
            f.seek(seq * ck)
            for _ in range(8):                         # 每次命令最多 8 片(≈2MB): 有界工作量, 断点由 next_seq 续
                data = f.read(ck)
                if not data:
                    done = True
                    break
                r = _pc('/api/sense/blob', {'dev': _dev(), 'id': b['id'], 'seq': seq, 'total': total,
                                            'b64': base64.b64encode(data).decode('ascii'),
                                            'sha256': hashlib.sha256(data).hexdigest()})
                if not r or not r.get('ok'):
                    return {'ok': 1, 'uploaded': False, 'sent': sent, 'next_seq': seq,
                            'pc': {'reachable': bool(r)}, 'quota': quota}
                seq += 1
                sent += len(data)
    except Exception as e:
        return _err('io', detail=str(e)[:120])
    if done:
        b['synced'] = 1
        _put_t('blob', [b])
    _put_t('obs', [_norm({'kind': 'blob.uplink', 'ts': _now(), 'blob_ref': b['id'],
                          'payload': {'bytes': sent, 'done': done, 'forced': bool(a.get('force'))}})])
    return {'ok': 1, 'uploaded': done, 'sent': sent, 'next_seq': (None if done else seq), 'quota': quota}

def _watch_rules():
    r = _kv_obj('ga.sense.watch', [])
    return r if isinstance(r, list) else []

def _watch_save(rs):
    _kv_put('ga.sense.watch', json.dumps(rs, ensure_ascii=False))

def _watch_eval(rows):
    """kind 触发: 写入时就地判定(零后台开销)。geofence/near 需要常驻定位, 由采集会话或 L0 驱动, 这里如实标 caps。"""
    rules = _watch_rules()
    live = [r for r in rules if r.get('enabled', True) and (r.get('on') or {}).get('type') == 'kind']
    if not live or not rows:
        return
    now, hits, dirty = _now(), [], False
    hr = time.localtime(now / 1000.0).tm_hour
    for rl in live:                                   # rl 是 rules 里的同一个对象: 改 last_ts 后整表回写, 不做集合重组(重组过就丢过规则)
        on = rl.get('on') or {}
        q = str(on.get('match') or '')
        hit = [r for r in rows if r['kind'] == on.get('kind') and (not q or q in (r.get('text') or ''))]
        if not hit:
            continue
        qh = rl.get('quiet_hours') or []
        quiet = len(qh) == 2 and ((qh[0] <= hr < qh[1]) if qh[0] < qh[1] else (hr >= qh[0] or hr < qh[1]))
        cd = now - _i(rl.get('last_ts'), 0) < _i(rl.get('cooldown_ms'), 3600000)
        why = 'quiet_hours' if quiet else ('cooldown' if cd else '')
        fired = False
        if not why:
            try:
                import droid
                droid.alarm_set('sense_' + str(rl.get('id')), now + 5000, 0, str(rl.get('task') or ''))
                fired = True
            except Exception:
                why = 'bus_unavailable'               # 触发不了也要留痕: 静默不执行比不配置更难排查
            rl['last_ts'] = now
            dirty = True
        hits.append(_norm({'kind': 'watch.hit', 'ts': now, 'text': str(rl.get('id')),
                           'payload': {'rule': rl.get('id'), 'fired': fired, 'reason': why, 'n': len(hit),
                                       'obs': [r['id'] for r in hit[:5]]}}))
    if dirty:
        _watch_save(rules)
    if hits:
        _put_t('obs', hits)

def _h_watch(v, a):
    rs = _watch_rules()
    # 本轮只有 kind 触发有执行体(写入时就地判定); geofence/near 需要常驻定位驱动, 没有就如实标 unsupported
    # ——「规则存下了」不等于「会触发」, 把没实现说成降级运行是最容易骗到自己人的那种谎。
    caps = {'kind': 'ok', 'geofence': 'unsupported', 'near': 'unsupported'}
    if v in ('', 'list'):
        return {'ok': 1, 'running': True, 'rule_count': len(rs), 'rules': rs, 'caps': caps}
    if v == 'add':
        rid = _s(a.get('id')) or 'w_' + _h(_now())
        on = a.get('on') if isinstance(a.get('on'), dict) else {}
        if on.get('type') not in ('kind', 'geofence', 'near'):
            return _err('bad_rule', want=['kind', 'geofence', 'near'])
        rl = {'id': rid, 'on': on, 'task': str(a.get('task') or '')[:2000], 'enabled': True,
              'cooldown_ms': _i(a.get('cooldown_ms'), 3600000), 'quiet_hours': a.get('quiet_hours') or [], 'last_ts': 0}
        rs = [r for r in rs if r.get('id') != rid] + [rl]
        _watch_save(rs)
        return {'ok': 1, 'running': True, 'rule_count': len(rs), 'rules': rs, 'caps': caps}
    if v == 'del':
        rid = _s(a.get('id'))
        rs2 = [r for r in rs if r.get('id') != rid]
        _watch_save(rs2)
        return {'ok': 1, 'running': True, 'rule_count': len(rs2), 'deleted': len(rs) - len(rs2), 'caps': caps}
    if v != 'set-enabled':
        return _err('unknown_verb', verb=v, want=['add', 'list', 'del', 'set-enabled'])
    rid, en = _s(a.get('id')), bool(a.get('enabled'))
    for r in rs:
        if r.get('id') == rid:
            r['enabled'] = en
    _watch_save(rs)
    return {'ok': 1, 'running': True, 'rule_count': len(rs), 'rules': rs, 'caps': caps}

def _h_policy(v, a):
    if v in ('', 'get'):
        return {'ok': 1, 'policy': _policy(), 'defaults': POLICY, 'effective_from': _now(),
                'source': 'kv' if _kv_get('ga.sense.policy', '') else 'default'}
    if v != 'set':
        return _err('unknown_verb', verb=v, want=['get', 'set'])
    cur = _kv_obj('ga.sense.policy', {})
    bad = [k for k in a if k not in POLICY]
    for k in a:
        if k in POLICY:
            cur[k] = _clamp(k, a[k])                  # 逐键校验+夹紧: 非法值退回保守默认而不是原样落盘
    _kv_put('ga.sense.policy', json.dumps(cur, ensure_ascii=False))
    return {'ok': 1, 'policy': _policy(), 'ignored': bad, 'effective_from': _now(), 'source': 'kv'}

def _sel_key(a):
    """confirm token 与 selector 的绑定(防「查 A 删 B」): 绑定面就是全部选择键 —— 漏掉哪个键,
    「count 全量拿 token → purge {那个键}」就在那个维度上通用, 两步确认等于没做。"""
    return _h(json.dumps({k: a.get(k) for k in _SEL_KEYS}, sort_keys=True, ensure_ascii=False, default=str))

def _h_data(v, a):
    if v not in ('count', 'export', 'purge'):
        return _err('unknown_verb', verb=v, want=['count', 'export', 'purge'])
    s = _prep(dict(a, include_invalid=True))
    kw = s.get('kinds') or []
    # 墓碑的区间正是刚被删的那段, 不排除它就会自己命中同一个 selector —— 「删完复核 n==0」永远不成立,
    # 每轮还把上一个墓碑删掉再写一个新的。只排除墓碑, 不排除覆盖窗: 窗里存着用户自己起的 label(「和老王谈判」),
    # 跟着 _h_query 的展示规则一起排掉, 就成了「删掉那场会之后标题还留在库里」—— 删除承诺当场破功。
    rows = [r for r in _scan(s, prepped=True) if r['kind'] != _TOMB_KIND or _TOMB_KIND in kw]
    ids = [r['id'] for r in rows]
    brefs = set([r['blob_ref'] for r in rows if r.get('blob_ref')])
    blobs = [b for b in _all_t('blob') if b['id'] in brefs]
    nbytes = sum([len(r.get('text') or '') + len(r.get('meta') or '') for r in rows]) + sum([b.get('bytes') or 0 for b in blobs])
    span = {'from': min([r['ts'] for r in rows]) if rows else None, 'to': max([r['ts_end'] for r in rows]) if rows else None}
    if v == 'count':
        tok = 'tok_' + _h(_sel_key(a), _now())
        toks = _kv_obj('ga.sense.confirm', {})
        toks[tok] = {'sel': _sel_key(a), 'n': len(rows), 'exp': _now() + 600000}
        toks = dict(sorted(toks.items(), key=lambda kv: kv[1].get('exp', 0), reverse=True)[:5])
        _kv_put('ga.sense.confirm', json.dumps(toks))
        return {'ok': 1, 'n': len(rows), 'bytes': nbytes, 'blobs': len(blobs), 'span': span, 'confirm': tok}
    if v == 'export':
        _mkdir()
        fmt = 'md' if str(a.get('fmt') or '') == 'md' else 'jsonl'
        p = os.path.join(OUT, 'sense_export_%s.%s' % (time.strftime('%Y%m%d_%H%M%S'), fmt))
        allow = _allow_set()
        with open(p, 'w', encoding='utf-8') as f:
            for r in sorted(rows, key=lambda x: x['ts']):
                o = _out(r, allow)
                f.write(json.dumps(o, ensure_ascii=False) + '\n' if fmt == 'jsonl' else
                        '- %s [%s] %s\n' % (time.strftime('%Y-%m-%d %H:%M', time.localtime(r['ts'] / 1000.0)),
                                            r['kind'], (o.get('text') or json.dumps(o.get('payload'), ensure_ascii=False))[:400]))
        return {'ok': 1, 'path': p, 'n': len(rows), 'fmt': fmt}
    toks = _kv_obj('ga.sense.confirm', {})
    t = toks.get(_s(a.get('confirm')))
    if not t or t.get('exp', 0) < _now() or t.get('sel') != _sel_key(a):
        return _err('bad_confirm', hint='先 /sense.data count {同一 selector} 取 confirm token(10 分钟内有效)')
    files = _unlink([b.get('path') for b in blobs])
    _del_t('blob', [b['id'] for b in blobs])
    n = _del_t('obs', ids)
    if span['from']:                                   # 墓碑: 「这段时间的数据被删过」必须在 query 的 gaps 里永远可见
        _put_t('obs', [_norm({'id': 'obs_purge_' + _h(span['from'], span['to'], _now()), 'kind': 'purge.mark',
                              'ts': span['from'], 'ts_end': span['to'], 'valid': False,
                              'payload': {'reason': 'purged', 'n': n, 'blobs': len(blobs)}})])
    toks.pop(_s(a.get('confirm')), None)
    _kv_put('ga.sense.confirm', json.dumps(toks))
    pc = {'cascaded': False, 'deleted': 0}
    if a.get('cascade_pc') is not False:
        # 级联的选择集 = 本机这次真删掉的那批 id; 只有「调用方一个选择键都没给」才是用户要的全清。
        # 表达不出来就拒绝级联并如实说明(cascaded:false + reason), 绝不猜 —— 猜的方向永远是删多。
        wipe = not _sel_given(a)
        ok, dn, why, rest = _pc_purge(ids, wipe)
        if ok:
            pc = {'cascaded': True, 'deleted': dn}
        elif why == 'no_ids':
            pc['reason'] = 'nothing_to_cascade'        # 本地一条都没删, PC 上也就没有对应 id 可删: 没必要挂队列
        else:                                          # PC 不可达/拒收就如实说没删干净, 并挂队列; 假装删干净会让整条隐私叙事失效
            q = _kv_obj('ga.sense.pcq', [])[-19:] + [{'ts': _now(), 'ids': rest, 'all': 1 if wipe else 0}]
            _kv_put('ga.sense.pcq', json.dumps(q, ensure_ascii=False))
            pc.update({'deleted': dn, 'reason': why, 'pending': len(q)})
    else:
        pc['reason'] = 'cascade_off'                   # 回执要分得清「没删成」与「调用方没让删」
    rcp = {'id': 'rcp_' + _h(_now(), n), 'ts': _now(), 'selector': {k: a.get(k) for k in _SEL_KEYS if a.get(k) is not None},
           'deleted': {'obs': n, 'blobs': len(blobs), 'files': files}, 'pc': pc, 'storage': _S['mode']}
    rp = os.path.join(OUT, 'sense_receipt_%s.json' % time.strftime('%Y%m%d_%H%M%S'))
    try:
        _mkdir()
        with open(rp, 'w', encoding='utf-8') as f:
            json.dump(rcp, f, ensure_ascii=False, indent=1)
    except Exception:
        rp = ''
    return {'ok': 1, 'deleted': {'obs': n, 'blobs': len(blobs), 'files': files}, 'pc': pc,
            'receipt': rcp['id'], 'receipt_path': rp}

def _h_perm(v, a):
    """按需授权透传 L0(status|request|settings)。日常采集不必直呼——session start 会就地申请;
    仅当需要单独查/引导某权限(如 blocked 后深链设置页)时用。未知 verb 就地失败(fail-closed)。"""
    if v not in ('', 'status', 'request', 'settings'):
        return _err('unknown_verb', verb=v, want=['status', 'request', 'settings'])
    body = dict(a or {})
    body['action'] = v or 'status'
    r = _l0('/sense/perm', body=body)
    return r if isinstance(r, dict) else {'ok': 0, 'error': 'bus_unavailable', 'degraded_to': 'bus_unavailable'}

def _h_keepalive(v, a):
    """保活自检(A16)透传 L0: 长时/全天采集前查 needs_setup, true 就先按 vendor_hint 引导用户加白名单。
    settings 拉起系统页(须 GA 前台); 连不上总线时如实回降级形状, 不谎报「已达标」。"""
    if v not in ('', 'status', 'settings'):
        return _err('unknown_verb', verb=v, want=['status', 'settings'])
    r = _l0('/sense/keepalive', body={'action': v or 'status'})
    if not r.get('ok'):
        # 失败恒带 error(模块契约, 见文件头 §失败统一形状); 同时给出 needs_setup/vendor_hint 让上层仍能引导。
        return {'ok': 0, 'error': r.get('degraded_to') or 'bus_unavailable', 'needs_setup': True,
                'degraded_to': r.get('degraded_to') or 'bus_unavailable',
                'vendor_hint': '无法自检(采集服务未就绪), 长时采集前请手动确认 GA 已加电池白名单'}
    return {'ok': 1, 'needs_setup': bool(r.get('needs_setup')), 'ignoring_batt': bool(r.get('ignoring_batt')),
            'bg_restricted': bool(r.get('bg_restricted')), 'manufacturer': r.get('manufacturer') or '',
            'vendor_hint': r.get('vendor_hint') or '', 'opened': bool(r.get('opened')), 'degraded_to': ''}

_SUBS = {'session': _h_session, 'mic': _h_mic, 'loc': _h_loc, 'near': _h_near, 'cal': _h_cal, 'motion': _h_motion,
         'asr': _h_asr, 'log': _h_log, 'query': _h_query, 'place': _h_place, 'peer': _h_peer, 'sync': _h_sync,
         'blob': _h_blob, 'watch': _h_watch, 'policy': _h_policy, 'data': _h_data,
         'perm': _h_perm, 'keepalive': _h_keepalive}

def _arg(rest):
    """'start {json}' → ('start', {..}); '{json}'/'[json]' → ('', obj); '' → ('', {})"""
    rest = (rest or '').strip()
    if not rest:
        return '', {}
    if rest[0] in '{[':
        return '', json.loads(rest)
    p = rest.split(None, 1)
    return p[0], (json.loads(p[1].strip()) if len(p) > 1 and p[1].strip() else {})

def handle(text):
    """同步入口(android_entry 后台 job 线程调用)。text 形如 '/sense.query {"from":..}'。
    末尾就地失败是硬约束: 未知子命令若落到 _send_for 的 put_task 会被当 prompt 起真实 LLM 任务烧积分
    (宿主命令不应发往模型)。"""
    try:
        cmd = (text or '')[len('/sense.'):].strip()
        p = cmd.split(None, 1)
        name = p[0] if p else ''
        fn = _SUBS.get(name)
        if fn is None:
            return json.dumps({'ok': 0, 'error': 'unknown_cmd', 'cmd': '/sense.' + name[:32],
                               'subs': sorted(_SUBS.keys())}, ensure_ascii=False)
        try:
            verb, arg = _arg(p[1] if len(p) > 1 else '')
        except Exception:
            return json.dumps({'ok': 0, 'error': 'bad_json', 'cmd': '/sense.' + name}, ensure_ascii=False)
        if not isinstance(arg, dict) and name != 'log':   # 只有 log 收数组; 其余非对象入参说明调用方拼错了, 就地失败别猜
            return json.dumps({'ok': 0, 'error': 'bad_args', 'cmd': '/sense.' + name}, ensure_ascii=False)
        return json.dumps(fn(verb, arg), ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({'ok': 0, 'error': str(e)[:200] or type(e).__name__}, ensure_ascii=False)

# ── 直呼入口(不过命令表, 采集热路径零开销) ───────────────────────────────────
def ingest(payload):
    """收一整串 JSON(单条或数组)写时间线。L0 按「只写不推」纪律把分片落 segs.jsonl 由 /sense.mic seg 拉,
    故 Kotlin 侧不走这里; 留给 WebUI/外部注入与将来的原生直呼(届时在 android_entry 加一行 sense_ingest 转发即可)。"""
    try:
        return handle('/sense.log ' + (payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)))
    except Exception as e:
        return json.dumps({'ok': 0, 'error': str(e)[:200]}, ensure_ascii=False)

def log(obs):
    return json.loads(handle('/sense.log ' + json.dumps(obs, ensure_ascii=False)))

def query(**sel):
    return json.loads(handle('/sense.query ' + json.dumps(sel, ensure_ascii=False)))

def status():
    return {'storage': _S['mode'], 'rtree': _S['rtree'], 'err': _S['err'], 'dir': DIR, 'policy': _policy()}

# ── L2 组合层: 只含「哪几个原子按什么顺序」, 不含产品决策(判断与话术在 L3 SOP) ──
def _call(cmd, arg=None):
    return json.loads(handle(cmd + ((' ' + json.dumps(arg, ensure_ascii=False)) if arg is not None else '')))

def snapshot(label=''):
    """此刻的处境快照: 位置 + 同场信号 + 运动 + 前后 1h 日历。用于「我现在在哪、旁边有谁」。"""
    now = _now()
    loc = _call('/sense.loc fix', {'mode': 'once'})
    near = _call('/sense.near scan', {'ms': 6000})
    mot = _call('/sense.motion now')
    cal = _call('/sense.cal range', {'from': now - 3600000, 'to': now + 3600000, 'limit': 5})
    if label:
        log({'kind': 'note.user', 'ts': now, 'text': label, 'place_id': loc.get('place_id') or '',
             'peers': near.get('peers') or []})
    return {'ts': now, 'place_id': loc.get('place_id'), 'fix': loc.get('fix'), 'peers': near.get('peers') or [],
            'motion': mot.get('state'), 'events': cal.get('events') or [],
            'degraded': [x for x in [loc.get('degraded_to'), near.get('degraded_to'), mot.get('degraded_to')] if x]}

def meeting_wrap(sid, cal_slack_ms=1800000):
    """会议收尾: 停会话 → 收分片 → 登记待转写 → 借日历补元数据与参与者 → 推 PC。"""
    ses = _call('/sense.session stop', {'sid': sid})
    seg = _call('/sense.mic seg', {'sid': sid})
    for b in seg.get('ingested') or []:
        _call('/sense.asr seg', {'blob': b, 'engine': 'pc'})
    win = _by_id('obs_ses_' + sid) or {}
    cal = _call('/sense.cal range', {'from': (win.get('ts') or _now()) - cal_slack_ms,
                                     'to': (win.get('ts_end') or _now()) + cal_slack_ms, 'limit': 5})
    peers = sorted(set([p for e in (cal.get('events') or []) for p in (e.get('peer_ids') or [])]))
    push = _call('/sense.sync push', {})
    return {'sid': sid, 'session': ses, 'segments': len(seg.get('ingested') or []), 'gaps': seg.get('gaps') or [],
            'events': cal.get('events') or [], 'peers': peers, 'pushed': push.get('pushed', 0),
            'pending': push.get('pending', 0)}

def recall(q='', frm=None, to=None, near=None, with_=None, kinds=None, limit=50):
    """回忆: 先时空+人硬过滤再看内容, 最后由证据充分性决定「能不能答」——拒答判据来自数据层, 不是 prompt。"""
    now = _now()
    sel = {'from': _i(frm, now - 86400000), 'to': _i(to, now), 'q': q or None, 'near': near,
           'with': with_ or None, 'kinds': kinds or None, 'limit': limit}
    r = _call('/sense.query', dict([(k, v) for k, v in sel.items() if v is not None]))
    ev = r.get('evidence') or {}
    return {'answerable': not r.get('abstain_hint') and bool(r.get('items')),
            'items': r.get('items') or [], 'n': r.get('total', 0), 'gaps': ev.get('gaps') or [],
            'coverage_ratio': ev.get('coverage_ratio'), 'storage': r.get('storage'),
            'hint': ('无证据: 先说明缺口再问用户, 不要编' if r.get('abstain_hint') else '')}

def daily_digest(day_ts=None, limit=400):
    """一天的分层压缩: 按地点/同场者分桶 + 保留缺口, 交给上层做一次 LLM 摘要(本函数不调 LLM)。"""
    t = day_ts or _now()
    lt = time.localtime(t / 1000.0)
    d0 = int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)) * 1000)
    r = _call('/sense.query', {'from': d0, 'to': d0 + 86400000, 'limit': limit})
    buckets = {}
    for it in r.get('items') or []:
        k = it.get('place_id') or 'unknown'
        b = buckets.setdefault(k, {'place_id': it.get('place_id'), 'n': 0, 'peers': set(), 'texts': []})
        b['n'] += 1
        b['peers'].update(it.get('peers') or [])
        if it.get('text'):
            b['texts'].append(it['text'][:200])
    for b in buckets.values():
        b['peers'] = sorted(b['peers'])
        b['texts'] = b['texts'][:40]
    return {'day': time.strftime('%Y-%m-%d', lt), 'from': d0, 'to': d0 + 86400000, 'n': r.get('total', 0),
            'buckets': list(buckets.values()), 'evidence': r.get('evidence') or {}, 'abstain_hint': r.get('abstain_hint')}
