"""recipe: L1 Recipe Executor（SPEC Phase 1）——结构化轨迹的校验、回放与录制。

四条不变量（SPEC §4.2，各有测试锁定）：
1. 步骤只存 intent + locator，**永不存坐标**——校验层把坐标字段当非法输入拒绝，
   回放每次按当前观测重新解析（结构性保证，不靠自觉）。
2. `expected` 由既有验证函数判定（`_scroll_verdict` / `_img_diff_str` / 前台断言），
   本模块不新造验证器，只做编排。
3. 任何 expected 失败立即向上一层升级，配方内无重试循环。
4. 单次运行升级两次的配方标记 unstable，路由器不再提供，直到重新录制。

回放零模型调用：observe/act 由调用方注入（droid 侧接 dump/look/tap/swipe），
纯函数核心可在无设备、无网络、无模型下单测。
"""
import hashlib
import json
import re
from collections import deque
from pathlib import Path
from dataclasses import dataclass, field

RECIPE_VERSION = 1
LOCATOR_KINDS = frozenset({"text", "desc", "cls", "roi", "relative", "any"})
ACTION_KINDS = frozenset({"tap", "swipe", "paste", "key", "launch", "back", "home", "wait", "observe"})
EXPECTED_KINDS = frozenset({"foreground_is", "diff_at_least", "diff_at_most",
                            "min_nodes", "text_appears", "text_in_roi"})
# 不变量 1 的结构保证: 步骤里出现这些键=有人存了坐标, 一律非法
_COORD_FIELDS = frozenset({"x", "y", "point", "point2", "coordinate", "coords", "px", "py"})


class RecipeError(ValueError):
    """配方不合法（schema/版本/存坐标）。调用方据此拒绝加载或升级。"""


@dataclass
class Step:
    intent: str
    locator: dict
    action: dict
    expected: dict
    on_fail: str = "escalate"


@dataclass
class Recipe:
    recipe_id: str
    scene: str
    app_hint: dict
    steps: list
    recorded_at: str = ""
    version: int = RECIPE_VERSION
    fragile: bool = False          # 含 relative 兜底定位器: 页面一变就可能要升级


def _reject_coordinates(step, where):
    for key, value in step.items():
        if key in _COORD_FIELDS:
            raise RecipeError("step %s 含坐标字段 %r——配方只存 locator, 坐标必须回放时重新解析" % (where, key))
        if isinstance(value, dict):
            _reject_coordinates(value, where)


def _validate_step(obj, idx):
    if not isinstance(obj, dict):
        raise RecipeError("step %d 不是对象" % idx)
    for key in ("intent", "locator", "action", "expected"):
        if key not in obj:
            raise RecipeError("step %d 缺 %r" % (idx, key))
    _reject_coordinates(obj, idx)
    intent = obj["intent"]
    if not isinstance(intent, str) or not intent.strip():
        raise RecipeError("step %d intent 必须是非空字符串" % idx)
    locator = obj["locator"]
    if not isinstance(locator, dict) or locator.get("kind") not in LOCATOR_KINDS:
        raise RecipeError("step %d locator.kind 必须是 %s" % (idx, sorted(LOCATOR_KINDS)))
    if locator.get("kind") != "any" and "value" not in locator:
        raise RecipeError("step %d locator 缺 value" % idx)
    action = obj["action"]
    if not isinstance(action, dict) or action.get("kind") not in ACTION_KINDS:
        raise RecipeError("step %d action.kind 必须是 %s" % (idx, sorted(ACTION_KINDS)))
    expected = obj["expected"]
    if not isinstance(expected, dict) or expected.get("kind") not in EXPECTED_KINDS:
        raise RecipeError("step %d expected.kind 必须是 %s" % (idx, sorted(EXPECTED_KINDS)))
    if "value" not in expected:
        raise RecipeError("step %d expected 缺 value" % idx)
    on_fail = obj.get("on_fail", "escalate")
    if on_fail != "escalate":
        raise RecipeError("step %d on_fail 只支持 escalate(不变量 3: 配方内无重试)" % idx)
    return Step(intent=intent, locator=locator, action=action, expected=expected, on_fail=on_fail)


def validate_recipe(obj):
    """严格校验并归一化。任何不合法抛 RecipeError——调用方不得加载半截配方。"""
    if not isinstance(obj, dict):
        raise RecipeError("recipe 必须是对象")
    version = obj.get("version", RECIPE_VERSION)
    if version != RECIPE_VERSION:
        raise RecipeError("recipe version %r 不受支持(当前 %d)" % (version, RECIPE_VERSION))
    for key in ("recipe_id", "scene", "app_hint", "steps"):
        if key not in obj:
            raise RecipeError("recipe 缺 %r" % key)
    if not isinstance(obj["recipe_id"], str) or not obj["recipe_id"].strip():
        raise RecipeError("recipe_id 必须是非空字符串")
    if not isinstance(obj["scene"], str) or not obj["scene"].strip():
        raise RecipeError("scene 必须是非空字符串")
    if not isinstance(obj["app_hint"], dict):
        raise RecipeError("app_hint 必须是对象")
    steps = obj["steps"]
    if not isinstance(steps, list) or not steps:
        raise RecipeError("steps 必须是非空数组")
    return Recipe(
        recipe_id=obj["recipe_id"],
        scene=obj["scene"],
        app_hint=obj["app_hint"],
        steps=[_validate_step(s, i) for i, s in enumerate(steps)],
        recorded_at=str(obj.get("recorded_at", "")),
        version=version,
    )


def recipe_to_dict(recipe):
    """Recipe → 可 JSON 序列化 dict（落盘/传输用；坐标仍被 _reject_coordinates 挡住）。"""
    return {
        "recipe_id": recipe.recipe_id,
        "scene": recipe.scene,
        "app_hint": recipe.app_hint,
        "steps": [{"intent": s.intent, "locator": s.locator, "action": s.action,
                   "expected": s.expected, "on_fail": s.on_fail} for s in recipe.steps],
        "recorded_at": recipe.recorded_at,
        "version": recipe.version,
        "fragile": recipe.fragile,
    }


# ---------------- R2: locator 解析与 expected 判定 ----------------

def _bbox_pixels(bbox, screen):
    """bbox → 像素 4 元组; 认 dump 的 "l,t,r,b" 字符串与 look 的 [x1,y1,x2,y2] 列表。"""
    if isinstance(bbox, str):
        parts = bbox.split(",")
        if len(parts) != 4:
            return (None, None, None, None)
        try:
            return tuple(int(v) for v in parts)
        except Exception:
            return (None, None, None, None)
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            return tuple(int(v) for v in bbox)
        except Exception:
            return (None, None, None, None)
    return (None, None, None, None)


def _candidates(observation):
    """当前观测 → 统一候选列表。dump 节点优先(精确)，look 检测兜底(视觉)。"""
    screen = observation.get("screen") or (0, 0)
    out = []
    for n in observation.get("nodes") or []:
        point = (n.get("x"), n.get("y"))
        if point[0] is None or point[1] is None:
            x1, y1, x2, y2 = _bbox_pixels(n.get("b"), screen)
            point = ((x1 + x2) // 2, (y1 + y2) // 2) if None not in (x1, y1, x2, y2) else (None, None)
        out.append({"point": point, "bbox": _bbox_pixels(n.get("b"), screen),
                    "text": n.get("t") or "", "desc": n.get("d") or "",
                    "cls": n.get("cls") or "", "source": "node"})
    for d in observation.get("detections") or []:
        out.append({"point": (d.get("x"), d.get("y")), "bbox": _bbox_pixels(d.get("bbox"), screen),
                    "text": d.get("label") or "", "desc": "", "cls": d.get("cls") or "",
                    "source": "detection"})
    return out


def _in_roi(bbox, roi, screen):
    if not roi or len(roi) != 4 or None in bbox:
        return False
    w, h = screen if screen and screen[0] and screen[1] else (0, 0)
    if not w:
        return False
    rx1, ry1, rx2, ry2 = roi[0] / 1000.0 * w, roi[1] / 1000.0 * h, roi[2] / 1000.0 * w, roi[3] / 1000.0 * h
    cx, cy = (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0
    return rx1 <= cx <= rx2 and ry1 <= cy <= ry2


def resolve_locator(observation, locator, unique=True):
    """locator → 当前观测上的具体目标；0 命中一律 None（不猜，交升级）。
    unique=True（动作步）：>1 命中=歧义，返回 None 交升级——绝不猜一个点。
    unique=False（观测步）：>1 命中返回区域摘要（读区域不需要唯一目标）。
    relative 是最后一级（canvas 类目标），总是解析。"""
    kind = locator.get("kind")
    if kind not in LOCATOR_KINDS:
        raise RecipeError("unknown locator kind %r" % kind)
    screen = observation.get("screen") or (0, 0)
    if kind == "any":
        return {"point": None, "bbox": None, "source": "any", "label": ""}
    if kind == "relative":
        rx, ry = (list(locator["value"]) + [0, 0])[:2]
        w, h = screen if screen and screen[0] else (0, 0)
        return {"point": (int(rx / 1000.0 * w), int(ry / 1000.0 * h)),
                "bbox": None, "source": "relative", "label": ""}
    cands = _candidates(observation)
    if kind == "text":
        want = str(locator["value"])
        hits = [c for c in cands if want in (c["text"] or "")]
    elif kind == "desc":
        want = str(locator["value"])
        hits = [c for c in cands if want in (c["desc"] or "")]
    elif kind == "cls":
        want = str(locator["value"])
        hits = [c for c in cands if (c["cls"] or "") == want]
    elif kind == "roi":
        hits = [c for c in cands if _in_roi(c["bbox"], locator["value"], screen)]
        if "text" in locator:
            want = str(locator["text"])
            hits = [c for c in hits if want in (c["text"] or "")]
    else:
        hits = []
    if len(hits) != 1:
        node_hits = [c for c in hits if c["source"] == "node"]
        if node_hits:                    # 多源命中时优先精确源(dump 节点), 再判唯一
            hits = node_hits
    if len(hits) != 1:
        if not unique and hits:
            xs = [c["bbox"] for c in hits if None not in c["bbox"]]
            box = [min(b[0] for b in xs), min(b[1] for b in xs),
                   max(b[2] for b in xs), max(b[3] for b in xs)] if xs else None
            return {"point": None, "bbox": box, "source": "region",
                    "label": "", "matches": len(hits)}
        return None                      # 0=没找到; unique 时 >1=歧义——都不猜
    hit = hits[0]
    if hit["point"][0] is None or hit["point"][1] is None:
        return None
    return {"point": (int(hit["point"][0]), int(hit["point"][1])),
            "bbox": list(hit["bbox"]) if None not in hit["bbox"] else None,
            "source": hit["source"], "label": hit["text"] or hit["desc"]}


def check_expected(expected, outcome):
    """expected 判定。数据来自既有验证函数产出；缺数据返回 None（uncertain，一律升级）。"""
    kind = expected.get("kind")
    if kind == "foreground_is":
        pkg = outcome.get("pkg")
        return None if not pkg else (pkg == expected["value"])
    if kind in ("diff_at_least", "diff_at_most"):
        pct = outcome.get("diff_pct")
        if pct is None:
            return None
        return pct >= expected["value"] if kind == "diff_at_least" else pct <= expected["value"]
    if kind == "min_nodes":
        nodes = outcome.get("nodes")
        return None if nodes is None else len(nodes) >= expected["value"]
    if kind == "text_appears":
        nodes = outcome.get("nodes")
        if nodes is None:
            return None
        want = str(expected["value"])
        return any(want in (n.get("t") or n.get("d") or n.get("label") or "") for n in nodes)
    if kind == "text_in_roi":
        nodes = outcome.get("nodes")
        if nodes is None:
            return None
        screen = outcome.get("screen") or (0, 0)
        want, roi = str(expected["value"]), expected.get("roi") or []
        for n in nodes:
            if want not in (n.get("t") or n.get("d") or n.get("label") or ""):
                continue
            if _in_roi(_bbox_pixels(n.get("b"), screen), roi, screen):
                return True
        return False
    raise RecipeError("unknown expected kind %r" % kind)


# ---------------- R3: 回放引擎（零模型调用） ----------------

@dataclass
class ReplayResult:
    status: str                 # completed | escalated
    steps_done: int
    escalated_at: object = None
    reason: object = None       # locator_miss | expected_failed | uncertain
    evidence: dict = field(default_factory=dict)
    model_calls: int = 0        # 结构性地为 0: 引擎没有任何 LLM 路径
    observation: dict = field(default_factory=dict)   # 末步观测摘要: 读取类任务据此直接回答, 无需再 dump


# 需要「动作后状态」才能判定的 expected 种类——只有这些才触发动作后二次观测
_STATE_EXPECTED = frozenset({"min_nodes", "text_appears", "text_in_roi"})


def _evidence(outcome):
    """升级证据只带判定必需的字段，不把整个观测倒进结果。"""
    ev = {}
    for k in ("diff_pct", "pkg"):
        if k in outcome:
            ev[k] = outcome[k]
    if isinstance(outcome.get("nodes"), list):
        ev["node_count"] = len(outcome["nodes"])
    return ev


def _state_view(obs):
    return {k: obs.get(k) for k in ("nodes", "detections", "screen", "pkg") if k in obs}


def _obs_summary(obs):
    """观测摘要: 只带文本类内容(读取类任务靠它直接回答), 不带整树。"""
    items = []
    for n in (obs.get("nodes") or []):
        txt = n.get("t") or n.get("d") or ""
        if txt.strip():
            items.append(txt.strip())
    for d in (obs.get("detections") or []):
        txt = d.get("label") or ""
        if txt.strip():
            items.append(txt.strip())
    return {"texts": items[:60], "pkg": obs.get("pkg"), "screen": obs.get("screen")}


def replay(recipe, observe, act):
    """回放配方。observe() -> 观测 dict；act(action, resolved) -> 动作产出 dict。
    不变量 3：第一个失败即结束，配方内无重试。uncertain 与 False 同样升级，不当成功。"""
    last_obs = {}
    for i, step in enumerate(recipe.steps):
        obs = observe()
        last_obs = obs
        resolved = resolve_locator(obs, step.locator, unique=step.action.get("kind") != "observe")
        if resolved is None:
            return ReplayResult("escalated", i, escalated_at=i, reason="locator_miss",
                                evidence={"locator": step.locator})
        if step.action.get("kind") == "observe":
            outcome = _state_view(obs)              # observe 步: 解析时的那次观测即后验, 不重复观测
        else:
            outcome = dict(act(step.action, resolved) or {})
        verdict = check_expected(step.expected, outcome)
        if verdict is None and step.expected["kind"] in _STATE_EXPECTED \
                and step.action.get("kind") != "observe":
            outcome.update(_state_view(observe()))  # 动作后状态: 只在判定真需要时二次观测
            verdict = check_expected(step.expected, outcome)
        if verdict is not True:
            return ReplayResult("escalated", i, escalated_at=i,
                                reason="uncertain" if verdict is None else "expected_failed",
                                evidence={"expected": step.expected, "outcome": _evidence(outcome)},
                                observation=_obs_summary(last_obs))
    return ReplayResult("completed", len(recipe.steps), observation=_obs_summary(last_obs))


# ---------------- R4: 录制器（trace → recipe，零模型调用） ----------------

_MAX_STEPS = 24


def _node_at(obs, point):
    """动作点落在哪个节点/检测上——locator 推导的唯一依据；找不到返回 None。"""
    if not point or point[0] is None or point[1] is None:
        return None
    screen = obs.get("screen") or (0, 0)
    for n in obs.get("nodes") or []:
        x1, y1, x2, y2 = _bbox_pixels(n.get("b"), screen)
        if None in (x1, y1, x2, y2):
            continue
        if x1 <= point[0] <= x2 and y1 <= point[1] <= y2:
            return n
    for d in obs.get("detections") or []:
        bbox = d.get("bbox") or []
        if len(bbox) == 4 and bbox[0] <= point[0] <= bbox[2] and bbox[1] <= point[1] <= bbox[3]:
            return d
    return None


def _locator_for_point(obs, point):
    """点 → locator：所在节点的 text/desc；解析不到退 relative(并置 fragile)。"""
    node = _node_at(obs, point)
    if node is not None:
        text = node.get("t") or ""
        desc = node.get("d") or node.get("label") or ""
        if text.strip():
            return {"kind": "text", "value": text.strip()}
        if desc.strip():
            return {"kind": "desc", "value": desc.strip()}
    screen = obs.get("screen") or (0, 0)
    if screen and screen[0] and screen[1]:
        rx, ry = int(point[0] * 1000.0 / screen[0]), int(point[1] * 1000.0 / screen[1])
        return {"kind": "relative", "value": [rx, ry]}
    return {"kind": "any"}


def _expected_from_result(kind, result, args=None):
    """expected 全部来自该动作已有的验证产出，不新造判定。"""
    if kind == "paste" and result.get("hit"):
        # paste 的原文只在 trace 的 args.value 里(outcome 不含), 单独取
        return {"kind": "text_appears",
                "value": str((args or {}).get("value") or result.get("text") or "")}
    pct = result.get("diff_pct")
    if pct is None:
        return {"kind": "diff_at_least", "value": 1.5}
    if pct <= 0.05:
        return {"kind": "diff_at_most", "value": 0.05}
    return {"kind": "diff_at_least", "value": max(round(pct / 2.0, 2), 0.1)}


def _dir_from_points(p1, p2):
    """(起点, 终点) → 手指移动方向; 与 scroll() 的 direction 同口径。推不出返回 None。
    与 droid._finger_direction 同源: 本模块必须在无设备/无 droid 的环境下单测,
    所以各留一份, 不跨模块 import。"""
    if not p1 or not p2 or None in p1[:2] or None in p2[:2]:
        return None
    dx, dy = float(p2[0]) - float(p1[0]), float(p2[1]) - float(p1[1])
    if abs(dx) < 1 and abs(dy) < 1:
        return None
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "down" if dy > 0 else "up"


def _app_slug(app):
    """App 名 → 配方 id 片段。中文名经 [^0-9A-Za-z_.-] 替换会塌缩成同一个 '_',
    不同 App 的配方落同路径互相覆盖(评审实证: 腾讯新闻/美团/高德全落 recipe._.json)。
    替换后只剩分隔符时退回稳定哈希: 可区分、可复现、不引入新依赖。"""
    s = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(app)).strip("._-")
    if not s:
        s = "app_" + hashlib.md5(str(app).encode("utf-8")).hexdigest()[:8]
    return s


def trace_to_recipe(trace, task_hint):
    """设备操作痕迹 → 配方。trace 是 droid 侧记录的结构化操作(非模型代码)，故零模型调用。"""
    if not trace:
        raise RecipeError("empty trace: 没有可录制的操作")
    steps, fragile, app_pkg = [], False, None
    for op in trace:
        kind = op.get("kind")
        # 前置 reset 操作(home/back)不进配方: 它是环境归位而非任务意图,
        # 录进去会让「从桌面回放再按 home 无变化」必然升级(真机实证)。
        if kind in ("home", "back") and not steps:
            continue
        args = op.get("args") or {}
        result = op.get("result") or {}
        obs = op.get("obs") or {}
        if kind == "wait":
            continue                      # 等待不进入配方: 回放时各步 verify 自然覆盖时序
        if kind == "launch":
            app_pkg = args.get("pkg") or result.get("pkg") or ""
            steps.append(Step("打开 App", {"kind": "any"}, {"kind": "launch", "pkg": app_pkg},
                              {"kind": "foreground_is", "value": app_pkg}))
            continue
        if kind in ("look", "dump"):
            nodes = obs.get("nodes") or []
            dets = obs.get("detections") or []
            n = len([x for x in nodes if (x.get("t") or x.get("d") or "").strip()])
            n += len([x for x in dets if (x.get("label") or "").strip()])
            # 观测步期望「页面有内容」而非「和录制时一样多」: 信息流节点数天然波动,
            # 录多少就期望多少会把回放变成一次性脚本(真机实证: 录 58 节点, 重放时 48 → 误升级)。
            # 取录制值与一个小天花板的较小者: 页面确实有实质内容即通过, 内容被清空才升级。
            steps.append(Step("读取当前页", {"kind": "roi", "value": [0, 100, 1000, 900]},
                              {"kind": "observe"}, {"kind": "min_nodes", "value": max(1, min(n, 5))}))
            continue
        if kind == "scroll":
            steps.append(Step("滚动列表", {"kind": "roi", "value": [0, 100, 1000, 900]},
                              {"kind": "swipe", "direction": args.get("direction", "up")},
                              {"kind": "diff_at_least", "value": 1.5}))
            continue
        if kind in ("tap", "swipe", "paste"):
            if kind == "paste":
                # 只录"已验证上屏"的输入。hit 缺失/False(未上屏、被循环守卫拦下、验证不可用)
                # 录进去, 回放要么 paste('') 直接抛 ValueError, 要么 text_appears 永不成立——必然升级。
                if result.get("hit") is not True:
                    continue
                text = str(args.get("value") or result.get("text") or "")
                if not text:
                    continue                      # 无原文可回放
            if kind == "tap":
                point = (args.get("x"), args.get("y"))
            elif kind == "swipe":
                point = (args.get("x1"), args.get("y1"))
            else:
                point = (args.get("x"), args.get("y")) if args.get("x") is not None else None
            locator = _locator_for_point(obs, point) if point else {"kind": "any"}
            if locator["kind"] == "relative":
                fragile = True
            action = {"kind": kind}
            if kind == "paste":
                action["value"] = text
            if kind == "swipe":
                # direction 是手指方向(与 scroll() 同口径); 老 trace 没有该键时按坐标推, 不猜默认值
                action["direction"] = args.get("direction") or _dir_from_points(
                    (args.get("x1"), args.get("y1")), (args.get("x2"), args.get("y2"))) or "up"
            steps.append(Step("执行 %s" % kind, locator, action,
                              _expected_from_result(kind, result, args)))
            continue
        if kind in ("back", "home"):
            steps.append(Step("返回" if kind == "back" else "回桌面", {"kind": "any"},
                              {"kind": kind}, {"kind": "diff_at_least", "value": 1.5}))
            continue
        # 其余操作(key 等)不进配方: 回放不需要复刻每一次按键
    if not steps:
        raise RecipeError("trace 里没有可录制的操作(全是 wait?)")
    if len(steps) > _MAX_STEPS:
        steps, fragile = steps[:_MAX_STEPS], True
    app = str((task_hint or {}).get("app") or app_pkg or "app")
    rid = str((task_hint or {}).get("id") or ("recipe." + _app_slug(app)))
    return Recipe(recipe_id=rid, scene=str((task_hint or {}).get("scene") or "S1"),
                  app_hint={"package": app_pkg or "", "match": "title_contains", "value": app},
                  steps=steps, recorded_at=str((task_hint or {}).get("recorded_at") or ""),
                  fragile=fragile)


# ---------------- R5a: 存储与稳定性 ----------------

class RecipeStore:
    """memory/recipes/ 下的配方存储。

    - 坏文件/半截 schema = 不存在（严格校验，不降级加载）；
    - 单任务内升级满 UNSTABLE_AFTER 次 → unstable，对 load/match 均不可见，直到重新录制覆盖；
    - 匹配只用 app_hint 的 package / title 值，确定性、无模型、无向量。
    """

    UNSTABLE_AFTER = 2

    def __init__(self, root):
        self.root = Path(root)
        self._esc = None

    def _path(self, recipe_id):
        return self.root / ("%s.json" % recipe_id)

    def _esc_path(self):
        return self.root / "_escalations.json"

    def _load_esc(self):
        if self._esc is None:
            self._esc = {}
            try:
                self._esc = json.loads(self._esc_path().read_text(encoding="utf-8"))
            except Exception:
                self._esc = {}
            if not isinstance(self._esc, dict):
                self._esc = {}
        return self._esc

    def _persist_esc(self):
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self._esc_path().write_text(json.dumps(self._load_esc(), ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass                            # 记账失败不阻断回放; 代价是稳定性升级可能延迟一个任务

    def save(self, r):
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(r.recipe_id).write_text(
            json.dumps(recipe_to_dict(r), ensure_ascii=False, indent=1), encoding="utf-8")
        self._load_esc().pop(r.recipe_id, None)   # 重新录制即重置升级计数
        self._persist_esc()

    def load(self, recipe_id):
        if self.is_unstable(recipe_id):
            return None                     # unstable 对上层不可见, 直到重录
        p = self._path(recipe_id)
        if not p.is_file():
            return None
        try:
            return validate_recipe(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            return None                     # 坏文件=不存在, 不半截加载

    def list(self):
        out = []
        try:
            files = sorted(self.root.glob("*.json"))
        except Exception:
            return out
        for p in files:
            if p.name.startswith("_"):
                continue
            try:
                out.append(validate_recipe(json.loads(p.read_text(encoding="utf-8"))))
            except Exception:
                continue
        return out

    def match(self, hint):
        """按包名或 App 名确定性匹配; 跳过 unstable。多命中取第一个(确定性顺序)。"""
        hint = hint or {}
        pkg = str(hint.get("pkg") or "")
        app = str(hint.get("app") or "")
        for r in self.list():
            if self.is_unstable(r.recipe_id):
                continue
            ah = r.app_hint or {}
            if pkg and ah.get("package") == pkg:
                return r
            val = str(ah.get("value") or "")
            if app and val and (app in val or val in app):
                return r
        return None

    def record_escalation(self, recipe_id):
        esc = self._load_esc()
        esc[recipe_id] = int(esc.get(recipe_id, 0)) + 1
        self._persist_esc()

    def escalations(self, recipe_id):
        return int(self._load_esc().get(recipe_id, 0))

    def is_unstable(self, recipe_id):
        return self.escalations(recipe_id) >= self.UNSTABLE_AFTER
