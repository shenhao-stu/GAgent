"""run_metrics —— 一次任务的每 turn 运行指标: 记录、聚合、落盘(docs/SPEC.md Part 4.6 / Phase 0)。

职责边界(遵循本仓"纯函数做决策, I/O 留边界"的约定):
  - 纯函数: 判定字段白名单提取、判定函数归因、分位、汇总、JSONL 渲染。
  - 显式副作用: 只有 append_jsonl()/prune_oldest() 碰文件系统; RunRecorder 的时钟与写入口可注入。
  - 只观察: 写入失败静默——观测绝不影响 agent 主循环或手机操作。
  - 隐私: 不写屏幕内容、坐标、账号数据; 判定只取布尔/短枚举白名单字段。

字段口径:
  model_wait_s  本轮 llm_before→llm_after 的墙钟(verbose 路径含流式消费时间)
  tool_exec_s   本轮各工具 tool_before→tool_after 之和(含后验)
  verify_wait_s  上一段"动作已下发"到工具调用结束的时间; 未派发过动作的工具不计(落 null, ≠0)
                → action_s = tool_exec_s - verify_wait_s
  in_tok/out_tok 同一轮只有一次模型请求, 但一次请求分多事件上报(Claude: message_start
                的占位 output + message_delta 的终值) → 取最大值避免重复计
  resend_chars  本轮请求往返完成后 BaseSession.history 的序列化字符数(含本轮 user+assistant),
                即下一轮实际重发量的基线。不是本轮请求发出时的体量——那个时刻没有 hook 可达。
线程: RunRecorder 自带锁; 后验累加器跨线程(见下), recorder 由调用方按线程隔离。
"""
import json
import os
import threading
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Optional

SCHEMA_VERSION = 1
DEFAULT_KEEP = 20                       # 落盘目录保留最近的运行记录文件数(沿用 _persist_convo 限量先例)
LAYER_TODAY = 'L4'                      # 当前只有通用 ReAct 一层; Phase 3 路由器落地后由路由决策填入

# 判定白名单: 这些键由既有判定函数产出(_img_diff_str/_scroll_verdict/_classify_paste_rows),
# 值为布尔或短枚举, 可安全落盘; 其余工具结果一律不记录。
# 今天手机动作都在 code_run 的 stdout 里, 工具结果不带这些键 → 记入 tools_no_verdict;
# 结构化动作空间落地后同一段代码直接开始产出判定与判定来源。
VERDICT_KEYS = ('verified', 'uncertain', 'scrolled', 'evidence', 'performed', 'hit',
                'expect_verified')

# 判定函数归因表: (工具名, 见到的白名单键) → 既有判定函数名。归不出返回 None, 不猜。
# gui_act 是多路复用器: 它按 action 分别调 droid.tap/swipe/paste, 判定仍由那些既有函数产出,
# 所以归因到同一行(不归它 = 结构化动作通道的判定全部无法解释来源)。
_VERIFIER_TABLE = (
    (('tap', 'tap_rel', 'swipe', 'gui_act'), ('diff_pct',), '_img_diff_str'),
    (('scroll', 'scroll_view'), ('evidence',), '_scroll_verdict'),
    (('paste', 'gui_act'), ('hit',), '_classify_paste_rows'),
)

# 判定汇总的五个互斥桶(穷尽 tool_records)。优先级 uncertain > verified > negative >
# pixel > none: uncertain 必须压过一切——观察不可用不等于"没成功", 更不是成功,
# 也不能被同时出现的 hit=True 盖回去(旧实现只给 negative 排了 uncertain, verified 会双记,
# 四桶相加越过 tools_total, 把 tools_no_verdict 算成负数)。


def _is_success(verdict: dict) -> bool:
    return bool(verdict.get('hit') or verdict.get('scrolled')
                or verdict.get('verified') is True
                or verdict.get('expect_verified') is True)


def _is_negative(verdict: dict) -> bool:
    # expect_verified=False 只是"本地没读到期望文字"的软提示, 不是动作失败:
    # 长句期望几乎必然读不到。它只有在同时带有 verified=False 时才由后者计负。
    return (verdict.get('hit') is False or verdict.get('verified') is False
            or verdict.get('scrolled') is False
            or verdict.get('evidence') == 'none')


def _has_pixel_evidence(verdict: dict) -> bool:
    """只有像素变化率、没有布尔判定的记录。
    diff_pct 是 extract_verdict 从 'diff: 12.5% ...' 解析出的判定键(归因 _img_diff_str),
    但它两头都证不了: 屏幕变了≠任务推进(故不算 verified), 列表已在端点也几乎不变
    (故不算 negative)。单列一桶, 既不虚高成功率, 也不该算"无判定"。
    真机实证: 46 轮微信任务里 16 次 gui_act 只带 diff_pct, 旧实现把它们算进
    tools_no_verdict, 令 tools_no_verdict=42/45、verified-action rate 显示 0%。"""
    v = verdict.get('diff_pct')
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def classify_verdict(verdict: dict) -> str:
    """tool_record 判定分桶(五选一, 互斥且穷尽)。"""
    if not isinstance(verdict, dict):
        return 'none'
    if verdict.get('uncertain') is True:
        return 'uncertain'
    if _is_success(verdict):
        return 'verified'
    if _is_negative(verdict):
        return 'negative'
    if _has_pixel_evidence(verdict):
        return 'pixel'
    return 'none'


def diff_pct(value) -> Optional[float]:
    """'diff: 1.234% bbox=[...]' → 1.234; 取不到返回 None(只留像素变化率, 不留坐标)。"""
    if not isinstance(value, str) or '%' not in value:
        return None
    try:
        return float(value.split('%', 1)[0].rsplit(' ', 1)[-1])
    except (TypeError, ValueError):
        return None


def extract_verdict(data) -> dict:
    """从工具结果里取判定证据(白名单); 非 dict 或无线索返回 {}。
    gui_act 的结果是 json.dumps 出的字符串——结构化动作通道的判定全走这里。
    不解析字符串, 所有 gui_act 调用都会落进 tools_no_verdict 桶, hit/uncertain 永远不计。"""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (TypeError, ValueError):
            return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for k in VERDICT_KEYS:
        v = data.get(k)
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, str) and len(v) <= 40:
            out[k] = v
    pct = diff_pct(data.get('diff'))
    if pct is not None:
        out['diff_pct'] = pct
    return out


def attrib_verifier(tool_name: str, verdict: dict) -> Optional[str]:
    """判定证据 → 既有判定函数名。证据不足或工具不识别时返回 None(不猜)。"""
    if not verdict:
        return None
    name = (tool_name or '').rsplit('.', 1)[-1]
    keys = set(verdict)
    for tools, needs, fn in _VERIFIER_TABLE:
        if name in tools and keys & set(needs):
            return fn
    return None


def percentile(values, p) -> Optional[float]:
    """线性插值分位(0..100); 空序列返回 None。"""
    xs = sorted(float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool))
    if not xs:
        return None
    if len(xs) == 1:
        return round(xs[0], 3)
    k = (len(xs) - 1) * (p / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 3)


@dataclass
class ToolRecord:
    name: str
    exec_s: float
    verify_s: Optional[float]
    verdict: dict = field(default_factory=dict)
    verifier: Optional[str] = None

    def to_dict(self) -> dict:
        return {'name': self.name, 'exec_s': round(self.exec_s, 3),
                'verify_s': None if self.verify_s is None else round(self.verify_s, 3),
                'verdict': self.verdict, 'verifier': self.verifier}


@dataclass
class TurnRecord:
    turn: int
    layer: str
    t_start: float
    model_wait_s: float = 0.0
    tool_exec_s: float = 0.0
    verify_wait_s: float = 0.0
    in_tok: int = 0
    out_tok: int = 0
    resend_chars: Optional[int] = None
    escalations: list = field(default_factory=list)
    tool_records: list = field(default_factory=list)
    def to_dict(self) -> dict:
        return {'type': 'turn', 'v': SCHEMA_VERSION, 'turn': self.turn, 'layer': self.layer,
                't_start': self.t_start, 'model_wait_s': round(self.model_wait_s, 3),
                'tool_exec_s': round(self.tool_exec_s, 3), 'verify_wait_s': round(self.verify_wait_s, 3),
                'in_tok': self.in_tok, 'out_tok': self.out_tok, 'resend_chars': self.resend_chars,
                'n_tools': len(self.tool_records), 'tools': [r.name for r in self.tool_records],
                'tool_records': [r.to_dict() for r in self.tool_records],
                'escalations': list(self.escalations)}


@dataclass
class RunRecord:
    run_id: str
    gen: int
    started_at: float
    layer: str = LAYER_TODAY
    turns: list = field(default_factory=list)
    end_reason: str = ''
    ended_at: float = 0.0


def summarize(run: RunRecord) -> dict:
    """一次运行的总量与分位(SPEC Part 7.1); 不含任何屏幕内容。"""
    turns = run.turns
    model = [t.model_wait_s for t in turns]
    end_to_end = [t.model_wait_s + t.tool_exec_s for t in turns]
    recs = [r for t in turns for r in t.tool_records]
    buckets = {'verified': 0, 'uncertain': 0, 'negative': 0, 'pixel': 0, 'none': 0}
    for r in recs:
        buckets[classify_verdict(r.verdict)] += 1
    return {
        'type': 'run_summary', 'v': SCHEMA_VERSION, 'run_id': run.run_id, 'gen': run.gen,
        'layer': run.layer, 'started_at': run.started_at, 'ended_at': run.ended_at,
        'end_reason': run.end_reason, 'turns': len(turns),
        # 每轮一次 client.chat; 供应商侧重试/故障转移不计入额外一次
        'model_calls': len(turns),
        'model_wait_s': round(sum(model), 3),
        'tool_exec_s': round(sum(t.tool_exec_s for t in turns), 3),
        'verify_wait_s': round(sum(t.verify_wait_s for t in turns), 3),
        'in_tok': sum(t.in_tok for t in turns), 'out_tok': sum(t.out_tok for t in turns),
        'resend_chars_last': turns[-1].resend_chars if turns else None,
        'p50_turn_s': percentile(end_to_end, 50), 'p95_turn_s': percentile(end_to_end, 95),
        'p50_model_wait_s': percentile(model, 50), 'p95_model_wait_s': percentile(model, 95),
        'escalations': sum(len(t.escalations) for t in turns),
        # Part 7.2 verified-action rate 的分子。五桶互斥且穷尽 tool_records:
        #   uncertain 记"未验证", 绝不是成功, 且压过同时出现的 hit=True;
        #   pixel = 只有 diff_pct(屏幕变了, 但证不出成功也证不出失败), 单列不虚高成功率;
        #   no_verdict = 真无判定键, 只该是 code_run/file_read 这类非动作工具——
        #   它才是 SPEC silent-failure rate 的候选, 别把像素证据混进来。
        'tools_total': len(recs),
        'tools_verified': buckets['verified'],
        'tools_uncertain': buckets['uncertain'],
        'tools_negative': buckets['negative'],
        'tools_pixel_evidence': buckets['pixel'],
        'tools_no_verdict': buckets['none'],
    }


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def recovered_summary(run_id: str, turns) -> Optional[dict]:
    """从已落盘的 turn 行重建一次运行的汇总(用户中止/线程死亡, agent_after 没跑)。

    为什么需要: 每个任务跑在独立线程, RunRecorder 存在线程局部; 下一个任务的
    agent_before 在另一条线程, 读不到旧 recorder, 只能按文件补写。文件里 turn 行
    已经包含轮数/耗时/token/判定, 足够重建真实汇总, 不必留只有 run_id 的 stub。

    ended_at 只能取「最后一轮 t_start + model_wait + tool_exec」——真实暂停可能
    发生在下一轮模型调用中, 所以标 ended_at_estimated=True, 不冒充精确值。
    没有任何 turn 行时返回 None, 调用方保留诚实的 stub(unfinished_summary)。
    """
    dicts = [t for t in (turns or []) if isinstance(t, dict) and t.get('type') == 'turn']
    if not dicts:
        return None
    objs = []
    for t in dicts:
        recs = []
        for r in (t.get('tool_records') or []):
            if isinstance(r, dict):
                recs.append(SimpleNamespace(
                    verdict=r.get('verdict') if isinstance(r.get('verdict'), dict) else {}))
        objs.append(SimpleNamespace(
            model_wait_s=_num(t.get('model_wait_s')), tool_exec_s=_num(t.get('tool_exec_s')),
            verify_wait_s=_num(t.get('verify_wait_s')),
            in_tok=int(_num(t.get('in_tok'))), out_tok=int(_num(t.get('out_tok'))),
            resend_chars=t.get('resend_chars'),
            escalations=list(t.get('escalations') or []), tool_records=recs))
    first = dicts[0]
    started_at = _num(first.get('t_start'))
    ended_at = max((_num(t.get('t_start')) + o.model_wait_s + o.tool_exec_s
                    for t, o in zip(dicts, objs)), default=started_at)
    run = RunRecord(run_id=str(run_id), gen=0,
                    layer=first.get('layer') or LAYER_TODAY,
                    started_at=started_at, turns=objs,
                    end_reason='unfinished', ended_at=ended_at)
    summary = summarize(run)
    summary.update(recovered=True, ended_at_estimated=True, summary_source='turn_rows')
    return summary


def unfinished_summary(run_id: str) -> dict:
    """运行被中止/异常弃掉时的补写汇总(调用方按文件复查发现没有汇总行才写)。

    只有 run_id 与 end_reason 是确定的; 轮数/耗时/token 一律不猜——填 0 会被读成
    "没有耗时", 填 null 又和"取不到"混不开。所以只写能证明的两件事, 并用 recovered
    标明这是补写而非运行自己落下的,  Reader 不至于把 stub 当成真实汇总。"""
    return {'type': 'run_summary', 'v': SCHEMA_VERSION, 'run_id': str(run_id),
            'end_reason': 'unfinished', 'recovered': True}


def jsonl_line(obj) -> str:
    """单行 JSON(ensure_ascii=False); default=str 兜底——坏类型只毁自己这一行, 不毒死整条通道。"""
    return json.dumps(obj, ensure_ascii=False, default=str)


def append_jsonl(path: str, lines) -> bool:
    """追加写 JSONL(本模块唯一的文件写入口); 失败返回 False 而不抛。"""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, 'a', encoding='utf-8') as f:
            for line in lines:
                f.write(str(line).rstrip('\n') + '\n')
        return True
    except Exception:
        return False


def prune_oldest(directory: str, prefix: str, keep: int = DEFAULT_KEEP) -> int:
    """只保留最近的 keep 个 <prefix>*.jsonl, 返回删除条数(防 temp 无限增长)。"""
    try:
        names = sorted((n for n in os.listdir(directory)
                        if n.startswith(prefix) and n.endswith('.jsonl')),
                       key=lambda n: os.path.getmtime(os.path.join(directory, n)))
        drop = names[:-keep] if keep > 0 else names
        removed = 0
        for n in drop:
            try:
                os.remove(os.path.join(directory, n))
                removed += 1
            except Exception:
                pass
        return removed
    except Exception:
        return 0


# ---------- 动作后验计时(跨线程; droid._act 打点, 插件在 tool_after 结算) ----------
# 打点发生在 code_run 的子线程(ga_android.do_code_run 起 Thread), 结算发生在 agent 循环线程
# —— 线程本地累加器会把真实路径上的后验整段丢成 0(真机实测), 所以用模块级累加器 + 锁。
# 一个 agent 同一时刻只有一个工具调用在飞(循环线程阻塞等 code_run 返回), 串行场景归属正确;
# 多会话并行时两段后验会落进同一累加器, 归属不再精确(已知限制)。
_VERIFY_LOCK = threading.Lock()
_VERIFY = {'t0': None, 'total': 0.0}


def mark_action_dispatched():
    """droid._act() 派发成功后调用: 记录"动作已下发"时刻。
    同一段内上一次未结算的标记先入账——code_run 里连续多个动作由此正确切分。
    绝不抛异常: 手势已经发出, 观测失败不能把它变成失败。"""
    try:
        now = time.time()
        with _VERIFY_LOCK:
            t0 = _VERIFY['t0']
            if t0 is not None:
                _VERIFY['total'] += max(0.0, now - t0)
            _VERIFY['t0'] = now
    except Exception:
        pass          # 手势已发出; 观测失败绝不能把它变成失败


def take_verify_seconds() -> Optional[float]:
    """结算并取走累计的"动作后验"秒数; 期间没有派发过动作返回 None。"""
    with _VERIFY_LOCK:
        t0, total = _VERIFY['t0'], _VERIFY['total']
        _VERIFY['t0'] = None
        _VERIFY['total'] = 0.0
    if t0 is None:
        return None
    return round(total + max(0.0, time.time() - t0), 3)


def reset_verify_accumulator():
    """丢弃未结算的后验计时(新任务开局调: 上一轮被中止时可能有僵尸线程还在打点)。"""
    with _VERIFY_LOCK:
        _VERIFY['t0'] = None
        _VERIFY['total'] = 0.0


class RunRecorder:
    """一次任务(agent_runner_loop 一轮)的指标收集器。

    时钟与写入口注入 → 单测无需真实时间/文件。循环线程调用; 内部加锁。
    sink 形如 sink(list[str]) —— 每行一个 JSON 对象, 由插件负责真正落盘。
    """

    def __init__(self, run_id: str, gen: int = 0, layer: str = LAYER_TODAY,
                 clock=time.time, sink=None):
        self.run = RunRecord(run_id=run_id, gen=gen, layer=layer, started_at=round(clock(), 3))
        self._clock = clock
        self._sink = sink if sink is not None else (lambda lines: None)
        self._lock = threading.Lock()
        self._turn: Optional[TurnRecord] = None
        self._t_llm = None
        self._t_tool = None
        self._tok = [0, 0]

    def _emit(self, lines):
        try:
            self._sink(lines)
        except Exception:
            pass          # 观测失败不影响主循环

    # ---- 生命周期 ----
    def start_turn(self, turn: int):
        with self._lock:
            self._turn = TurnRecord(turn=turn, layer=self.run.layer,
                                    t_start=round(self._clock(), 3))
            self._t_llm = self._t_tool = None

    def end_turn(self):
        """把本轮指标交给 sink(一行 JSON); 无进行中的轮次则空转。"""
        with self._lock:
            turn, self._turn = self._turn, None
            self._t_llm = self._t_tool = None
        if turn is not None:
            self.run.turns.append(turn)
            self._emit([jsonl_line(turn.to_dict())])

    def end_run(self, end_reason: str = ''):
        with self._lock:
            self.run.end_reason = str(end_reason or '')
            self.run.ended_at = round(self._clock(), 3)
            turn, self._turn = self._turn, None
        if turn is not None:      # 循环被 break 时最后一轮可能没走 turn_after
            self.run.turns.append(turn)
            self._emit([jsonl_line(turn.to_dict())])
        self._emit([jsonl_line(summarize(self.run))])

    # ---- 计量 ----
    def llm_start(self):
        with self._lock:
            self._t_llm = self._clock()

    def llm_end(self):
        with self._lock:
            t0, self._t_llm = self._t_llm, None
            if self._turn is not None and t0 is not None:
                self._turn.model_wait_s += max(0.0, self._clock() - t0)
                self._turn.in_tok = self._tok[0]
                self._turn.out_tok = self._tok[1]
            self._tok = [0, 0]

    def note_tokens(self, in_tok: int, out_tok: int):
        """llmcore 用量观察者回调。同一轮一次请求分多事件上报 → 取最大值避免重复计。"""
        with self._lock:
            self._tok[0] = max(self._tok[0], int(in_tok or 0))
            self._tok[1] = max(self._tok[1], int(out_tok or 0))

    def set_resend_chars(self, n: int):
        with self._lock:
            if self._turn is not None:
                self._turn.resend_chars = int(n or 0)

    def tool_start(self):
        with self._lock:
            self._t_tool = self._clock()

    def tool_end(self, name: str, data, verify_s: Optional[float]):
        verdict = extract_verdict(data)
        with self._lock:
            t0, self._t_tool = self._t_tool, None
            exec_s = max(0.0, self._clock() - t0) if t0 is not None else 0.0
            if self._turn is not None:
                self._turn.tool_exec_s += exec_s
                if verify_s is not None:
                    self._turn.verify_wait_s += verify_s
                self._turn.tool_records.append(
                    ToolRecord(name=name, exec_s=exec_s, verify_s=verify_s,
                               verdict=verdict, verifier=attrib_verifier(name, verdict)))

    def add_escalation(self, reason: str):
        with self._lock:
            if self._turn is not None:
                self._turn.escalations.append(str(reason)[:80])
