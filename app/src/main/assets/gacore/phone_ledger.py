"""phone_ledger: 动作账本与三档防循环（SPEC 赋能 W3）。

设计来源与边界:
- 机械后验三层账来自 mobile-agent 的 ActionOutcome(DISPATCHED/SETTLED/REJECTED + screenshot_exactly_same
  + foreground_identity_changed): runtime 只提供事实, 不替模型下成败结论。
- 三档干预: 提示级(repetition_hint/guard_hint, 进 anchor prompt) → 改写级(click_recovery/type_recovery,
  在执行边界把动作换成 WAIT/BACK/HOME/REFOCUS/RETRY) → 拒绝级(reject_reason, 不下发)。
- 所有恢复有界并以 ABORT 收尾; 解除条件只有「屏幕变了」或「换动作」——不维护额外循环状态机。
- 滚动豁免: 每步产出新证据(diff 明显/截图在变)的滑动不计循环, 避免把长列表有效扫描误杀。

铁律(对应 SPEC 红线「无未知结果重试」的加强): 判定只消费已结算记录(outcome.verdict 已知),
uncertain 永远不算数; 恢复执行后由下一轮观察重新判定, 恢复动作本身不落等价账。
"""
from collections import deque
from dataclasses import dataclass, field

EQUIV_TOLERANCE = 40          # 0-1000 归一化域欧氏距离容差(≈1080p 43px; 本机 1200 宽≈48px)
EXACT_PCT = 0.05              # "无可观察变化"带: 与 droid 既有 miss 阈值(pct<0.05)同口径。
                              # 状态栏时钟跳字≈0.009%、JPEG 量化噪声都落在带内→算无效果;
                              # 像素全等会让改写/拒绝两档在有时钟/动画的页面上永不触发(评审 I1)。
REPETITION_WINDOW = 5         # 等价动作计数窗口
REPETITION_THRESHOLD = 5      # 窗口内等价动作 ≥5 → 提示
TYPE_WINDOW = 5
TYPE_THRESHOLD = 4            # 窗口内 TYPE(paste) ≥4 → 提示
STUCK_WINDOW = 4              # 界面粘滞: 最近 N 步每步截图逐次一致
STUCK_MIN_KINDS = 3           # 且动作类型 ≥3 种(排除「就是同一个东西点不动」的单动作场景)
REJECT_WINDOW = 5             # 拒绝级: 最近 N 步全部 settled+逐次一致+互相等价
EVIDENCE_PCT = 1.5            # diff 超过此比例=产出新证据(有效滚动/页面真变): 循环计数重置(长列表豁免)
CLICK_THRESHOLD = 3           # 恢复阶梯起点: 连续等价无效点击
TYPE_RECOVERY_THRESHOLD = 2   # 连续等价无效输入
CLICK_LADDER = ("WAIT", "BACK", "HOME", "ABORT")
TYPE_LADDER = ("REFOCUS", "RETRY", "ABORT")
OBS_WINDOW = 4                # 只读观察的连续窗口(see/ocr/observe 都算)
OBS_REPEAT_THRESHOLD = 2      # 同屏 + 同通道连续 N 次 → 提示换通道/换动作
OBS_KINDS = frozenset({"see", "ocr", "observe", "look"})
_POINT_KINDS = frozenset({"tap", "longpress"})
_PATH_KINDS = frozenset({"swipe"})
_VALUE_KINDS = frozenset({"paste", "scroll"})   # scroll 比方向(value), 端点由安全滚动自算
INPUT_KINDS = frozenset({"paste"})              # 仅真输入(提示/恢复阶梯专用; scroll 是值类但不是输入)


@dataclass
class ActionRecord:
    """一次已尝试的动作 + 结算事实。outcome 由执行层(droid)在验证后填入, 缺省=未结算(不计入任何判定)。"""
    kind: str
    point: tuple = ()
    point2: tuple = ()
    value: str = ""
    screen: tuple = ()                      # 记录时物理屏 (w, h): 等价判定按各自屏幕归一化
    outcome: dict = field(default_factory=dict)

    @property
    def settled(self):
        return self.outcome.get("verdict") in ("settled", "rejected", "recovered", "aborted")

    @property
    def exact_same(self):
        return bool(self.outcome.get("screenshot_exactly_same"))


@dataclass
class Observation:
    """一次只读观察(see/ocr/observe/look)。

    账本以前只记动作, 于是"在 OCR/视觉之间来回打转"对 [LOOP-GUARD] 和 turn%7 的 [DANGER]
    完全不可见 —— 真机 25 轮里 11 次 see(合计 164s)一次都没被拦。
    digest=屏幕摘要: 相同即画面没动, 再问一遍不会得到新信息。"""
    kind: str
    digest: object = None
    detail: str = ""


def _norm(point, screen):
    if not point or len(point) < 2 or not screen or len(screen) < 2 or not screen[0] or not screen[1]:
        return None
    return (point[0] * 1000.0 / screen[0], point[1] * 1000.0 / screen[1])


def _close(a, b, tol):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 <= tol


def equivalent(a, b, tol=EQUIV_TOLERANCE):
    """同类型 + 关键参数等价。坐标用欧氏距离而非网格量化: 边界点不会被切到不同格子误判。"""
    if a.kind != b.kind:
        return False
    if a.kind in _POINT_KINDS:
        pa, pb = _norm(a.point, a.screen), _norm(b.point, b.screen)
        if pa is None or pb is None:
            return tuple(a.point) == tuple(b.point)
        return _close(pa, pb, tol)
    if a.kind in _PATH_KINDS:
        pa, pb = _norm(a.point, a.screen), _norm(b.point, b.screen)
        qa, qb = _norm(a.point2, a.screen), _norm(b.point2, b.screen)
        if None in (pa, pb, qa, qb):
            return (tuple(a.point), tuple(a.point2)) == (tuple(b.point), tuple(b.point2))
        return _close(pa, pb, tol) and _close(qa, qb, tol)
    if a.kind in _VALUE_KINDS:
        if a.value != b.value:
            return False
        if a.point and b.point:
            pa, pb = _norm(a.point, a.screen), _norm(b.point, b.screen)
            if pa is not None and pb is not None:
                return _close(pa, pb, tol)
        return True
    return a.value == b.value          # key/back/home/launch: 类型+值相同即等价


def _settled_tail(records, kind=None):
    """末尾连续的同类型已结算片段(遇到未结算/异类型/有新证据即断)。"""
    tail = []
    for r in reversed(records):
        if not r.settled:
            break
        if kind is not None and r.kind != kind:
            break
        if r.outcome.get("evidence_new") or (r.outcome.get("diff_pct") or 0) > EVIDENCE_PCT:
            break                        # 产出新证据(有效滚动/明显变化)→ 循环计数重置
        tail.append(r)
    tail.reverse()
    return tail


def _equivalent_count(records, kind=None):
    tail = _settled_tail(records, kind)
    if not tail:
        return 0, []
    last = tail[-1]
    n = 0
    for r in reversed(tail):
        if equivalent(r, last):
            n += 1
        else:
            break
    return n, tail


def _abab_period(records):
    """ABAB/ABCABC 策略循环; 序列内动作不完全互相等价(那是单动作重复, 另一规则管)。"""
    for period in (2, 3):
        seq = [r for r in records[-period * 2:] if r.settled]
        if len(seq) < period * 2:
            continue
        if all(equivalent(seq[i], seq[i + period]) for i in range(period)):
            if not all(equivalent(seq[0], seq[i]) for i in range(1, period)):
                return period
    return None


def repetition_hint(records):
    """提示级信号 → 注入 prompt 的文案; 无信号返回 None。证据强度决定措辞(有逐次一致=断言无效果, 否则只要求核对)。"""
    window = [r for r in records[-REPETITION_WINDOW:] if r.settled]
    n, tail = _equivalent_count(records)
    if n >= REPETITION_THRESHOLD:
        strong = tail[-REPETITION_THRESHOLD:] and all(r.exact_same for r in tail[-REPETITION_THRESHOLD:])
        if strong:
            return (f"最近 {n} 次动作互为等价且前后截图逐次无可观察变化，说明该动作没有产生可观察效果。"
                    "请先比较动作前后截图，换一个目标或策略，不要原样重发。")
        return ("检测到最近多次动作互为等价。请先比较动作前后截图核对上一步是否生效，"
                "不能仅根据动作意图判断它是否生效；若无变化请切换策略。")
    period = _abab_period(records)
    if period:
        return (f"检测到 {['', '两', '三'][period]} 步一循环的策略循环(如 A→B→A→B)。"
                "请检查是否在同一两个状态间反复；不得在没有新证据时再次从该序列开头进入。")
    if len(window) >= TYPE_WINDOW:
        # 只数没有产出新证据的输入: 多字段填表(每个字段都成功上屏)不是循环,
        # 提示只针对"输入了但没确认生效"的连续动作。
        types = sum(1 for r in window if r.kind in INPUT_KINDS and not r.outcome.get("evidence_new"))
        if types >= TYPE_THRESHOLD:
            return ("最近多步都在做文本输入。请先核对目标字段是否已显示等长文本或掩码，"
                    "确认输入是否真正生效，再决定是否继续输入。")
    stuck = [r for r in records[-STUCK_WINDOW:] if r.settled]
    if len(stuck) >= STUCK_WINDOW and len({r.kind for r in stuck}) >= STUCK_MIN_KINDS \
            and all(r.exact_same for r in stuck):
        return ("最近多步动作类型不同但前后截图逐次完全一致，界面可能被遮挡、焦点错误或处于不可操作状态。"
                "请先观察当前截图确认真实状态，再决定下一步。")
    return None


def reject_reason(records, pending=None):
    """拒绝级: 最近 REJECT_WINDOW 步全部已结算 + 截图逐次一致 + 互相等价 → 不下发。
    pending=待发动作: 它将是第 REJECT_WINDOW 次等价(只要求已结算部分有强证据, 待发动作无证据可验)。"""
    settled = [r for r in records[-REJECT_WINDOW:] if r.settled]
    if pending is not None:
        if not settled or not equivalent(settled[-1], pending):
            return None
        need = REJECT_WINDOW - 1
    else:
        need = REJECT_WINDOW
    window = settled[-need:]
    if len(window) < need:
        return None
    if not all(r.exact_same for r in window):
        return None
    if not all(equivalent(window[0], r) for r in window[1:]):
        return None
    return "repeated_no_effect"


def _ladder(records, kind, threshold, ladder, pending=None):
    """恢复阶梯: 末尾连续等价无效动作达到 threshold 即启动。
    pending=待发动作(无证据, 不参与断尾): 次数按已结算部分算, pending 与末尾等价时+1;
    强证据只看已结算部分(逐次一致)。"""
    base = records[:-1] if pending is not None else records
    n, tail = _equivalent_count(base, kind)
    if pending is not None:
        if not tail or not equivalent(tail[-1], pending):
            return None
        n += 1
    if n < threshold:
        return None
    need = threshold - 1 if pending is not None else threshold
    evidence = tail[-need:] if need else []
    if not all(r.exact_same for r in evidence):
        return None                      # 强证据门槛: 已结算部分逐次一致
    idx = min(n - threshold, len(ladder) - 1)
    return ladder[idx]


def click_recovery(records, pending=None, kind="tap"):
    """改写级(点击): 连续等价无效点击 → WAIT→BACK→HOME→ABORT(有界)。
    kind 默认 'tap'; tap/longpress 同走点击阶梯——长按若漏了它,
    在同一位置反复无效长按永远不拦(评审实证: 硬编码 'tap' 使 _settled_tail 一开头就断)。"""
    return _ladder(records, kind, CLICK_THRESHOLD, CLICK_LADDER, pending)


def type_recovery(records, pending=None):
    """改写级(输入): 连续等价无效输入 → REFOCUS→RETRY→ABORT(有界)。"""
    return _ladder(records, "paste", TYPE_RECOVERY_THRESHOLD, TYPE_LADDER, pending)


def observation_hint(observations, window=OBS_WINDOW):
    """同屏同通道反复只读观察 → 提示文案; 无信号返回 None(digest 未知时不猜)。"""
    if not observations:
        return None
    tail = list(observations)[-window:]
    last = tail[-1]
    if last.digest is None:
        return None
    same = 1
    for o in reversed(tail[:-1]):
        if o.digest != last.digest or o.kind != last.kind:
            break
        same += 1
    if same < OBS_REPEAT_THRESHOLD:
        return None
    return ("[OBS-GUARD] 同一屏已经用 %s 观察了 %d 次(%s), 画面没有变化: 再问一次不会得到新信息。"
            "要么换通道(定位→obs/rel, 精确文字→ocr), 要么用动作推进; 已有答案就直接 finish_task。确需再敲一次同一屏, 传 force=true。"
            % (last.kind, same, (last.detail or "")[:40]))


def guard_hint(records):
    """喂给 anchor prompt 的循环守卫文案(提示级); 无信号 None。"""
    hint = repetition_hint(records)
    if not hint:
        return None
    return f"[LOOP-GUARD] {hint}"


class Ledger:
    """进程内动作账本(有界环形)。droid 落账, guard_hint/reject/recovery 读取; 不落盘、不做 I/O。"""

    def __init__(self, limit=64, obs_limit=16):
        self.records = deque(maxlen=limit)
        self.observations = deque(maxlen=obs_limit)   # 只读观察(see/ocr/observe)另一本账

    def append(self, record):
        self.records.append(record)
        return record

    def recent(self, n=10):
        return list(self.records)[-n:]

    def clear(self):
        self.records.clear()
        self.observations.clear()   # 任务边界: 上个任务的观察不能算进本任务的空转判定

    def hint(self):
        parts = [h for h in (guard_hint(list(self.records)),
                             observation_hint(list(self.observations))) if h]
        return chr(10).join(parts) if parts else None

    def note_observation(self, kind, digest=None, detail=""):
        """只读观察落账(see/ocr/observe/look)。返回提示文案(该换通道时), 无信号 None。"""
        if str(kind) not in OBS_KINDS:
            return None
        self.observations.append(Observation(kind=str(kind), digest=digest, detail=str(detail or "")))
        return observation_hint(list(self.observations))


# 进程级共享账本: droid(执行边界落账/守卫)与 ga_android(每轮提示注入)共用同一实例,
# 两侧都只 import 本纯函数模块, 不互相依赖(ga_android 保持设备无关)。
ACTIVE = Ledger()
