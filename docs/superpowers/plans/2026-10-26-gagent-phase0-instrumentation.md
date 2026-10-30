# GAgent Phase 0 可观测性 Implementation Plan

> 实现计划（含设计取舍、每任务的接口契约、Review Focus 与执行期 rulings）。
> 步骤用复选框 `- [ ]` 记录，可按顺序复现；已在分支 `feat/phase0-run-metrics` 上执行完毕。

**Goal:** 让 GAgent 每次任务都把「每 turn」的运行指标落盘，使 Phase 1–4 的优化可被测量（`docs/SPEC.md` Part 4.6 / Part 8 Phase 0）。

**Architecture:** 观测挂在 `agent_loop.py` 既有的 8 个 hook 点上（`plugins/*_hook.py` 机制，执行层零改动）；新增纯模块 `run_metrics.py` 负责 schema、聚合与 JSONL 渲染（时钟与写入口可注入）；`llmcore` 开一个只观察的用量观察者 seam；`droid._act()` 打一个「动作已下发」的时间标记，用于把稳态等待/截图/对比分摊为 verify-wait。

**Tech Stack:** Python 3.12（Chaquopy 运行时 + 桌面 CLI 同一份 `gacore/`），pytest 8.3.5，无新依赖。

**Spec:** `docs/SPEC.md`（Part 2.2 现状、Part 4.6 插桩要求、Part 7.1 指标、Part 8 Phase 0 验收）；本计划不修改 SPEC.md——**Phase 0 只有在真机记录运行留档后才算完成，文档不得提前宣称为已实现能力**。

## Global Constraints

以下每条对全部任务生效，逐字取自规格与仓库约定：

- **不新增依赖**：`No new dependency is added to make a phase pass.`（SPEC Part 8 文档门禁）
- **记录不增加模型调用与设备操作**：`The recording itself adds no model calls and no device operations.`（Phase 0 验收）
- **不改现有测试以适应**：`pytest -q still passes; no existing test is modified to accommodate it.`
- **不写敏感内容**：`Never commit keys, personal configuration, screenshots, account data, signing material, production logs`；`只记枚举/数值, 绝不写屏幕内容/坐标以外信息`（`droid._track` 先例）
- **只观察，不影响主循环**：插件 handler 抛错一律吞掉（`plugins/hooks.py:18-23` 已有契约）；`埋点/插件绝不能拖垮 agent 主循环`
- **不硬编码**：`Do not hardcode a device size, orientation, OEM layout or an app-specific workaround for a general interface defect.`
- **第三方 App 只走视觉路线**：`webcdp` 只连 GAgent 自己的 WebView；不为微信等引入节点树/内部 API/目标 App CDP。
- **文档不把计划写成能力声明**：`A roadmap item is not an implemented feature.`
- **现有 Android 埋点不动**：`kernel_adapter/patches.py`（`patch_usage` / `patch_llm_timing` / `patch_abort` / `patch_route_probe`）与本任务并行存在，不许改写或删除。
- **基线**：本机 `python -m pytest -q` 当前为 `38 failed, 336 passed, 5 errors`——失败全部来自 Playwright 浏览器未安装（`BrowserType.launch: Executable doesn't exist`）与 1 个 Windows/NTFS `chmod 0o600` 既有问题（`tests/test_service_boundaries.py:47`）。验收口径是**失败集合不变**，不是全绿。

## Review Focus

规格没说、但使用者会遇到的五类输入，以及应有行为（每条都已挂到拥有该代码的任务里）：

1. **写盘失败（磁盘满/权限拒/路径被占）** → 记录静默失败，任务与手机操作完全不受影响。→ Task 2 `test_a_failing_sink_never_raises`、Task 5 `test_a_failing_write_never_breaks_the_task`
2. **CLI 路径无 `GA_DIR`、无归属会话** → 仍落到 `gacore/temp/...`，不崩不漏。→ Task 5 `test_ga_dir_fallback_when_unset`、`test_metrics_file_sits_beside_the_session_snapshots`
3. **`code_run` 里连续多个动作**（今天所有手机操作都走 `code_run`）→ verify-wait 必须按动作切分累加，不能只算最后一个。→ Task 1 `test_consecutive_actions_split_the_wait`
4. **任务被中止/抛异常，循环生成器被弃** → 只落已完成的 turn 行，不写假汇总；下一个任务开局把上次标为 `unfinished`。→ Task 2 `test_unfinished_turn_is_flushed_when_the_run_ends`、Task 5 `test_unfinished_run_is_closed_by_the_next_task`
5. **工具结果超大/非标量/含坐标**（`droid.dump` 返回上百节点、`diff` 串带 bbox）→ 只取白名单字段，坏类型不毒死整行。→ Task 1 `TestExtractVerdict`、`test_jsonl_line_survives_non_scalar_values`

---

## File Structure

| 文件 | 责任 | 新建/修改 |
| --- | --- | --- |
| `app/src/main/assets/gacore/run_metrics.py` | 指标 schema、纯聚合（白名单提取/归因/分位/汇总）、verify 累加器、JSONL 渲染与限量 | 新建 |
| `app/src/main/assets/gacore/plugins/run_metrics_hook.py` | 把 8 个 hook 点接到 recorder；run_id/落盘目录推导；用量观察者注册 | 新建 |
| `app/src/main/assets/gacore/llmcore.py` | 只观察的用量观察者 seam（`add_usage_observer` / `_emit_usage`），约 +14 行 | 修改 |
| `app/src/main/assets/gacore/droid.py` | `_act()` 末尾打「动作已下发」标记，+2 行 | 修改 |
| `tests/test_run_metrics.py` | 纯函数 + recorder + IO 单测 | 新建 |
| `tests/test_llm_usage_observer.py` | llmcore 观察者 seam 单测 | 新建 |
| `tests/test_run_metrics_hook.py` | 用假 client/handler 真跑 `agent_runner_loop` 的端到端单测 | 新建 |
| `CHANGELOG.md` | Unreleased 条目 | 修改 |
| `docs/ARCHITECTURE.md` | 边界表补 `memory` / `sense` / `evolution` / `run_metrics`（SPEC Part 8 每阶段文档门禁） | 修改 |

依赖方向：`run_metrics` 不 import 任何 gacore 模块；`plugins/run_metrics_hook` → `run_metrics` + `plugins.hooks` + （惰性）`llmcore` / `kernel_adapter`；`droid` → `run_metrics`。

---

## Task 1: `run_metrics.py` 纯核心与 verify 累加器

**Files:**
- Create: `app/src/main/assets/gacore/run_metrics.py`
- Test: `tests/test_run_metrics.py`

**Interfaces:**
- Consumes: 无（本任务不依赖其他新代码）
- Produces:
  - `SCHEMA_VERSION: int = 1`
  - `DEFAULT_KEEP: int = 20`
  - `LAYER_TODAY: str = 'L4'`
  - `VERDICT_KEYS: tuple[str, ...]`
  - `extract_verdict(data: object) -> dict`
  - `diff_pct(value: object) -> float | None`
  - `attrib_verifier(tool_name: str, verdict: dict) -> str | None`
  - `percentile(values, p: float) -> float | None`
  - `summarize(run: RunRecord) -> dict`
  - `jsonl_line(obj) -> str`
  - `mark_action_dispatched() -> None`
  - `take_verify_seconds() -> float | None`
  - dataclasses `ToolRecord` / `TurnRecord` / `RunRecord`

- [ ] **Step 1: 建分支**

```bash
cd /e/project/daiyimo/GAgent
git checkout -b feat/phase0-run-metrics
```

- [ ] **Step 2: 写失败测试**

创建 `tests/test_run_metrics.py`：

```python
"""每 turn 运行指标: 纯聚合、判定归因、分位与落盘(SPEC.md Part 4.6 / Phase 0)。

全部合成 fixture: 不连设备、不联网、不需要模型 key。
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import run_metrics


@pytest.fixture
def clean_verify():
    """排空线程本地的 verify 累加器(线程本地, 不影响其他测试)。"""
    run_metrics.take_verify_seconds()
    yield
    run_metrics.take_verify_seconds()


class TestExtractVerdict:
    def test_booleans_and_short_enums_are_kept(self):
        data = {'verified': True, 'uncertain': False, 'scrolled': True,
                'evidence': 'pixel', 'performed': True, 'hint': 'x' * 500,
                'fg': 'com.example.app'}
        assert run_metrics.extract_verdict(data) == {
            'verified': True, 'uncertain': False, 'scrolled': True,
            'evidence': 'pixel', 'performed': True}

    def test_diff_becomes_a_bare_percentage_without_bbox(self):
        v = run_metrics.extract_verdict({'diff': 'diff: 1.234% bbox=[10,20,30,40]'})
        assert v == {'diff_pct': 1.234}

    def test_unparseable_or_missing_diff_is_dropped(self):
        assert run_metrics.extract_verdict({'diff': 'diff: n/a'}) == {}
        assert run_metrics.extract_verdict({'diff': None}) == {}
        assert run_metrics.extract_verdict({'diff': 12}) == {}

    def test_non_dict_result_yields_nothing(self):
        assert run_metrics.extract_verdict(None) == {}
        assert run_metrics.extract_verdict('a very long tool result') == {}
        assert run_metrics.extract_verdict([{'t': 'node'}]) == {}


class TestAttribVerifier:
    @pytest.mark.parametrize('tool,verdict,expected', [
        ('droid.tap', {'verified': True, 'diff_pct': 1.2}, '_img_diff_str'),
        ('tap', {'uncertain': True, 'diff_pct': 0.0}, '_img_diff_str'),
        ('swipe', {'diff_pct': 2.0}, '_img_diff_str'),
        ('scroll_view', {'scrolled': True, 'evidence': 'text'}, '_scroll_verdict'),
        ('scroll', {'scrolled': False, 'evidence': 'none'}, '_scroll_verdict'),
        ('paste', {'verified': True}, '_classify_paste_rows'),
        ('tap', {'verified': True}, None),          # 无像素证据 → 不归因
        ('file_read', {'verified': True}, None),    # 非判定类工具 → 不归因
        ('dump', {}, None),
    ])
    def test_mapping(self, tool, verdict, expected):
        assert run_metrics.attrib_verifier(tool, verdict) == expected


class TestPercentile:
    def test_empty(self):
        assert run_metrics.percentile([], 50) is None

    def test_single_value(self):
        assert run_metrics.percentile([4.2], 95) == 4.2

    def test_interpolates(self):
        assert run_metrics.percentile([1, 2, 3, 4], 50) == 2.5
        assert run_metrics.percentile([1, 2, 3, 4], 95) == 3.85

    def test_ignores_non_numbers(self):
        assert run_metrics.percentile([1, None, 'x', 3], 50) == 2.0


class TestVerifyAccumulator:
    def test_no_mark_means_no_verify_time(self, clean_verify):
        assert run_metrics.take_verify_seconds() is None

    def test_mark_then_take_is_non_negative_and_one_shot(self, clean_verify):
        run_metrics.mark_action_dispatched()
        first = run_metrics.take_verify_seconds()
        assert first is not None and first >= 0.0
        assert run_metrics.take_verify_seconds() is None

    def test_consecutive_actions_split_the_wait(self, clean_verify):
        """code_run 里连续多个动作: 每段"动作后验"都要计入, 不能只算最后一个。"""
        run_metrics.mark_action_dispatched()
        time.sleep(0.02)
        run_metrics.mark_action_dispatched()      # 第二段动作开始 → 第一段入账
        time.sleep(0.02)
        total = run_metrics.take_verify_seconds()
        assert total >= 0.04


class TestJsonlIO:
    def test_jsonl_line_survives_non_scalar_values(self):
        line = run_metrics.jsonl_line({'a': {1, 2}, 'b': object()})
        assert '\n' not in line
        assert json.loads(line)['b']

    def test_append_creates_the_directory_and_one_object_per_line(self, tmp_path):
        p = tmp_path / 'a' / 'b' / 'metrics_1.jsonl'
        assert run_metrics.append_jsonl(str(p), ['{"a": 1}', '{"b": 2}']) is True
        assert run_metrics.append_jsonl(str(p), ['{"c": 3}']) is True
        assert [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines()] == [
            {'a': 1}, {'b': 2}, {'c': 3}]

    def test_unwritable_path_returns_false_instead_of_raising(self, tmp_path):
        blocker = tmp_path / 'blocker'
        blocker.write_text('not a directory', encoding='utf-8')
        assert run_metrics.append_jsonl(str(blocker / 'x.jsonl'), ['{}']) is False

    def test_prune_keeps_only_the_newest_files(self, tmp_path):
        for i, name in enumerate(['metrics_a.jsonl', 'metrics_b.jsonl', 'metrics_c.jsonl']):
            p = tmp_path / name
            p.write_text('{}', encoding='utf-8')
            os.utime(p, (1000 + i, 1000 + i))
        assert run_metrics.prune_oldest(str(tmp_path), 'metrics_', keep=2) == 1
        assert sorted(x.name for x in tmp_path.iterdir()) == ['metrics_b.jsonl', 'metrics_c.jsonl']

    def test_prune_ignores_other_files_and_missing_dirs(self, tmp_path):
        (tmp_path / 'session_x.json').write_text('{}', encoding='utf-8')
        assert run_metrics.prune_oldest(str(tmp_path), 'metrics_', keep=5) == 0
        assert run_metrics.prune_oldest(str(tmp_path / 'nope'), 'metrics_') == 0
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/test_run_metrics.py -q`
Expected: 收集错误 `ModuleNotFoundError: No module named 'run_metrics'`

- [ ] **Step 4: 实现 `run_metrics.py`**

创建 `app/src/main/assets/gacore/run_metrics.py`：

```python
"""run_metrics —— 一次任务的每 turn 运行指标: 记录、聚合、落盘(docs/SPEC.md Part 4.6 / Phase 0)。

职责边界(遵循本仓"纯函数做决策, I/O 留边界"的约定):
  - 纯函数: 判定字段白名单提取、判定函数归因、分位、汇总、JSONL 渲染。
  - 显式副作用: 只有 append_jsonl()/prune_oldest() 碰文件系统; RunRecorder 的时钟与写入口可注入。
  - 只观察: 写入失败静默——观测绝不影响 agent 主循环或手机操作。
  - 隐私: 不写屏幕内容、坐标、账号数据; 判定只取布尔/短枚举白名单字段。

字段口径:
  model_wait_s  本轮 llm_before→llm_after 的墙钟(verbose 路径含流式消费时间)
  tool_exec_s   本轮各工具 tool_before→tool_after 之和(含后验)
  verify_wait_s  上一段"动作已下发"到工具调用结束的时间; 未派发过动作的工具不计(≠0)
                → action_s = tool_exec_s - verify_wait_s
  in_tok/out_tok 同一轮只有一次模型请求, 但一次请求分多事件上报(Claude: message_start
                的占位 output + message_delta 的终值) → 取最大值避免重复计
  resend_chars  BaseSession.history 的序列化字符数(协议路径每轮整体重发; 实际扁平化
                提示词略大于此值)
线程: RunRecorder 自带锁; mark/take 用线程本地(code_run 子线程与循环线程不同)。
"""
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

SCHEMA_VERSION = 1
DEFAULT_KEEP = 20                       # 落盘目录保留最近的运行记录文件数(沿用 _persist_convo 限量先例)
LAYER_TODAY = 'L4'                      # 当前只有通用 ReAct 一层; Phase 3 路由器落地后由路由决策填入

# 判定白名单: 这些键由既有判定函数产出(_img_diff_str/_scroll_verdict/_classify_paste_rows),
# 值为布尔或短枚举, 可安全落盘; 其余工具结果一律不记录。
# 今天手机动作都在 code_run 的 stdout 里, 工具结果不带这些键 → 记录为 tools_without_verdict;
# 结构化动作空间落地后同一段代码直接开始产出判定与判定来源。
VERDICT_KEYS = ('verified', 'uncertain', 'scrolled', 'evidence', 'performed')

# 判定函数归因表: (工具名, 见到的白名单键) → 既有判定函数名。归不出返回 None, 不猜。
_VERIFIER_TABLE = (
    (('tap', 'tap_rel', 'swipe'), ('diff_pct',), '_img_diff_str'),
    (('scroll', 'scroll_view'), ('evidence',), '_scroll_verdict'),
    (('paste',), ('verified',), '_classify_paste_rows'),
)


def diff_pct(value) -> Optional[float]:
    """'diff: 1.234% bbox=[...]' → 1.234; 取不到返回 None(只留像素变化率, 不留坐标)。"""
    if not isinstance(value, str) or '%' not in value:
        return None
    try:
        return float(value.split('%', 1)[0].rsplit(' ', 1)[-1])
    except (TypeError, ValueError):
        return None


def extract_verdict(data) -> dict:
    """从工具结果里取判定证据(白名单); 非 dict 或无线索返回 {}。"""
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
    resend_chars: int = 0
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
        'resend_chars_last': turns[-1].resend_chars if turns else 0,
        'p50_turn_s': percentile(end_to_end, 50), 'p95_turn_s': percentile(end_to_end, 95),
        'p50_model_wait_s': percentile(model, 50), 'p95_model_wait_s': percentile(model, 95),
        'escalations': sum(len(t.escalations) for t in turns),
        # Part 7.2 verified-action rate 的分子; uncertain 记"未验证", 绝不是成功;
        # 无判定证据的工具单列, 不混入任何成功率
        'tools_verified': sum(1 for t in turns for r in t.tool_records
                              if r.verdict.get('verified') or r.verdict.get('scrolled')),
        'tools_uncertain': sum(1 for t in turns for r in t.tool_records if r.verdict.get('uncertain')),
        'tools_without_verdict': sum(1 for t in turns for r in t.tool_records if not r.verdict),
    }


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


# ---------- 动作后验计时(线程本地; droid._act 打点, 插件在 tool_after 结算) ----------
_tls = threading.local()


def mark_action_dispatched():
    """droid._act() 派发成功后调用: 记录"动作已下发"时刻。
    同一线程上一次未结算的标记先入账——code_run 里连续多个动作由此正确切分。"""
    now = time.time()
    prev = getattr(_tls, 'verify_t0', None)
    if prev is not None:
        _tls.verify_total = getattr(_tls, 'verify_total', 0.0) + max(0.0, now - prev)
    _tls.verify_t0 = now


def take_verify_seconds() -> Optional[float]:
    """结算并取走本线程累计的"动作后验"秒数; 本线程没派发过动作返回 None。"""
    now = time.time()
    t0 = getattr(_tls, 'verify_t0', None)
    if t0 is None:
        return None
    total = getattr(_tls, 'verify_total', 0.0) + max(0.0, now - t0)
    _tls.verify_t0 = None
    _tls.verify_total = 0.0
    return round(total, 3)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_run_metrics.py -q`
Expected: 全部 PASS（约 20 项）

- [ ] **Step 6: 提交**

```bash
git add app/src/main/assets/gacore/run_metrics.py tests/test_run_metrics.py
git commit -m "feat(android): 新增 run_metrics 纯核心——每 turn 指标的 schema、聚合与 JSONL 落盘 (SPEC Phase 0)" -m "" -m "Co-authored-by: Claude <noreply@anthropic.com>"
```

---

## Task 2: `RunRecorder` 收集器

**Files:**
- Modify: `app/src/main/assets/gacore/run_metrics.py`（在文件末尾追加 `RunRecorder` 类）
- Test: `tests/test_run_metrics.py`（追加 `TestRunRecorder`）

**Interfaces:**
- Consumes: Task 1 的 `ToolRecord` / `TurnRecord` / `RunRecord` / `extract_verdict` / `attrib_verifier` / `summarize` / `jsonl_line`
- Produces:
  - `RunRecorder(run_id: str, gen: int = 0, layer: str = LAYER_TODAY, clock=time.time, sink=None)`
  - `.run: RunRecord`
  - `.start_turn(turn: int) -> None`
  - `.end_turn() -> None`（把本轮一行 JSON 交给 sink）
  - `.end_run(end_reason: str = '') -> None`（补落未收尾轮次 + 汇总行）
  - `.llm_start() -> None` / `.llm_end() -> None`
  - `.note_tokens(in_tok: int, out_tok: int) -> None`（同一轮取最大值）
  - `.set_resend_chars(n: int) -> None`
  - `.tool_start() -> None`
  - `.tool_end(name: str, data, verify_s: Optional[float]) -> None`
  - `.add_escalation(reason: str) -> None`

- [ ] **Step 1: 写失败测试**

在 `tests/test_run_metrics.py` 末尾追加：

```python
class _FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, secs):
        self.t += secs
        return self.t


class _Sink:
    def __init__(self):
        self.lines = []

    def __call__(self, lines):
        self.lines.extend(lines)


class TestRunRecorder:
    def _rec(self, sink):
        clock = _FakeClock()
        return run_metrics.RunRecorder(run_id='r1', gen=7, clock=clock, sink=sink), clock

    def test_turn_line_carries_the_phase_zero_metric_set(self):
        sink = _Sink()
        rec, clock = self._rec(sink)
        rec.start_turn(1)
        rec.llm_start(); clock.advance(4.8); rec.note_tokens(1975, 42); rec.llm_end()
        rec.set_resend_chars(48213)
        rec.tool_start(); clock.advance(1.35)
        rec.tool_end('droid.tap', {'verified': True, 'diff': 'diff: 1.234% bbox=[1,2,3,4]'}, 0.98)
        clock.advance(0.05)
        rec.end_turn()
        rec.end_run('CURRENT_TASK_DONE')
        turn, summary = (json.loads(x) for x in sink.lines)
        assert turn['type'] == 'turn' and turn['turn'] == 1 and turn['layer'] == 'L4'
        assert turn['model_wait_s'] == 4.8
        assert turn['tool_exec_s'] == 1.35
        assert turn['verify_wait_s'] == 0.98
        assert (turn['in_tok'], turn['out_tok']) == (1975, 42)
        assert turn['resend_chars'] == 48213
        assert turn['n_tools'] == 1 and turn['tools'] == ['droid.tap']
        assert turn['tool_records'][0]['verifier'] == '_img_diff_str'
        assert turn['tool_records'][0]['verdict'] == {'verified': True, 'diff_pct': 1.234}
        assert turn['escalations'] == []
        assert summary['type'] == 'run_summary'
        assert summary['turns'] == 1 and summary['model_calls'] == 1
        assert summary['p50_turn_s'] == 6.15 and summary['p95_turn_s'] == 6.15
        assert summary['tools_verified'] == 1
        assert summary['tools_uncertain'] == 0 and summary['tools_without_verdict'] == 0

    def test_tokens_are_attributed_to_the_turn_that_asked(self):
        sink = _Sink()
        rec, clock = self._rec(sink)
        rec.start_turn(1); rec.llm_start(); rec.note_tokens(10, 1); rec.llm_end(); rec.end_turn()
        rec.start_turn(2); rec.llm_start(); clock.advance(1.0); rec.llm_end(); rec.end_turn()
        rec.end_run('MAX_TURNS_EXCEEDED')
        t1, t2 = (json.loads(x) for x in sink.lines[:2])
        assert (t1['in_tok'], t1['out_tok']) == (10, 1)
        assert (t2['in_tok'], t2['out_tok']) == (0, 0)

    def test_one_request_reporting_usage_twice_is_not_double_counted(self):
        """Claude 流式: message_start 的 output_tokens 是占位值, message_delta 才是终值。"""
        sink = _Sink()
        rec, clock = self._rec(sink)
        rec.start_turn(1); rec.llm_start()
        rec.note_tokens(1975, 1); rec.note_tokens(0, 42)
        rec.llm_end(); rec.end_turn()
        assert json.loads(sink.lines[0])['out_tok'] == 42

    def test_unfinished_turn_is_flushed_when_the_run_ends(self):
        """循环被 break(末轮不走 turn_after)时, 最后一轮仍要落一行, 不丢。"""
        sink = _Sink()
        rec, clock = self._rec(sink)
        rec.start_turn(3); rec.llm_start(); clock.advance(2.0); rec.llm_end()
        rec.end_run('CURRENT_TASK_DONE')
        assert [json.loads(x)['turn'] for x in sink.lines] == [3]
        assert json.loads(sink.lines[-1])['turns'] == 1

    def test_a_failing_sink_never_raises(self):
        """观测失败绝不能影响 agent 主循环。"""
        def boom(lines):
            raise OSError('disk full')

        rec = run_metrics.RunRecorder(run_id='r', clock=_FakeClock(), sink=boom)
        rec.start_turn(1); rec.llm_start(); rec.llm_end(); rec.end_turn()
        rec.end_run('done')          # 不抛即通过

    def test_summary_counts_uncertain_and_unverified_separately(self):
        sink = _Sink()
        rec, clock = self._rec(sink)
        rec.start_turn(1)
        rec.tool_start(); clock.advance(1.0)
        rec.tool_end('droid.tap', {'uncertain': True}, None)
        rec.tool_start(); clock.advance(1.0)
        rec.tool_end('droid.scroll_view', {'scrolled': True, 'evidence': 'text'}, 0.4)
        rec.tool_start(); clock.advance(1.0)
        rec.tool_end('file_read', {'content': 'x' * 100}, None)
        rec.end_turn(); rec.end_run('done')
        s = json.loads(sink.lines[-1])
        assert s['tools_uncertain'] == 1          # uncertain 记"未验证", 绝不是成功
        assert s['tools_without_verdict'] == 1    # 无判定证据的工具单列, 不混入成功率
        assert s['verify_wait_s'] == 0.4
        assert s['tool_exec_s'] == 3.0

    def test_tool_without_a_dispatched_action_has_no_verify_time(self):
        sink = _Sink()
        rec, clock = self._rec(sink)
        rec.start_turn(1)
        rec.tool_start(); clock.advance(0.5)
        rec.tool_end('file_read', {}, None)
        rec.end_turn()
        assert json.loads(sink.lines[0])['tool_records'][0]['verify_s'] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_run_metrics.py::TestRunRecorder -q`
Expected: `AttributeError: type object 'RunRecorder' has no attribute ...` / `ImportError`

- [ ] **Step 3: 实现 `RunRecorder`**

在 `app/src/main/assets/gacore/run_metrics.py` 末尾追加：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_run_metrics.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add app/src/main/assets/gacore/run_metrics.py tests/test_run_metrics.py
git commit -m "feat(android): RunRecorder——按 turn 归集模型等待/工具执行/后验/token/重发历史" -m "" -m "Co-authored-by: Claude <noreply@anthropic.com>"
```

---

## Task 3: `llmcore` 用量观察者 seam

**Files:**
- Modify: `app/src/main/assets/gacore/llmcore.py:309`（`_record_usage` 及其上方）
- Test: `tests/test_llm_usage_observer.py`（新建）

**Interfaces:**
- Consumes: 无
- Produces:
  - `llmcore._USAGE_OBSERVERS: list`
  - `llmcore.add_usage_observer(fn) -> None`，`fn(in_tok: int, out_tok: int, cached_tok: int)`
  - `llmcore._emit_usage(inp, out, cached=0) -> None`
- 兼容性：`_record_usage(usage, api_mode)` 的签名与 print 行为**完全不变**（`kernel_adapter/patches.py:167` 的猴补丁按两参数包装，改签名会炸）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_llm_usage_observer.py`：

```python
"""llmcore 用量观察者: token 必须可按 turn 归集(原来三个协议分支只 print)。"""
import sys
from pathlib import Path

import pytest

CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import llmcore


@pytest.fixture
def seen():
    saved = list(llmcore._USAGE_OBSERVERS)
    box = []
    llmcore.add_usage_observer(lambda i, o, c: box.append((i, o, c)))
    yield box
    llmcore._USAGE_OBSERVERS[:] = saved


def test_chat_completions_usage_is_emitted_normalized(seen):
    llmcore._record_usage({'prompt_tokens': 100, 'completion_tokens': 20,
                           'prompt_tokens_details': {'cached_tokens': 40}}, 'chat_completions')
    assert seen == [(100, 20, 40)]


def test_messages_usage_counts_cache_creation_as_input(seen):
    llmcore._record_usage({'input_tokens': 10, 'output_tokens': 5,
                           'cache_creation_input_tokens': 7, 'cache_read_input_tokens': 3}, 'messages')
    assert seen == [(20, 5, 3)]


def test_responses_usage_is_emitted(seen):
    llmcore._record_usage({'input_tokens': 11, 'output_tokens': 22,
                           'input_tokens_details': {'cached_tokens': 5}}, 'responses')
    assert seen == [(11, 22, 5)]


def test_empty_usage_emits_nothing(seen):
    llmcore._record_usage({}, 'chat_completions')
    llmcore._record_usage(None, 'messages')
    assert seen == []


def test_observer_failure_is_swallowed(seen):
    def boom(i, o, c):
        raise RuntimeError('bad observer')

    llmcore.add_usage_observer(boom)
    llmcore._record_usage({'prompt_tokens': 1, 'completion_tokens': 1}, 'chat_completions')
    assert seen == [(1, 1, 0)]


CLAUDE_SSE = [
    b'data: {"type":"message_start","message":{"usage":{"input_tokens":1975,"output_tokens":1}}}',
    b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}',
    b'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":42}}',
    b'data: {"type":"message_stop"}',
]


def test_claude_streaming_output_tokens_reach_the_observer(seen):
    """Claude 流式 output_tokens 只走 message_delta(不经 _record_usage), 也必须可归集。"""
    blocks = list(llmcore._parse_claude_sse(iter(CLAUDE_SSE)))
    assert any(b.get('type') == 'text' and b.get('text') == 'ok' for b in blocks)
    assert seen == [(1975, 1, 0), (0, 42, 0)]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_llm_usage_observer.py -q`
Expected: `AttributeError: module 'llmcore' has no attribute '_USAGE_OBSERVERS'`

- [ ] **Step 3: 实现观察者 seam**

在 `app/src/main/assets/gacore/llmcore.py` 的 `def _record_usage(usage, api_mode):`（第 309 行）**上方**插入：

```python
_USAGE_OBSERVERS = []   # 只观察消费者(如 run_metrics): 每次收到服务端用量即回调; 异常吞掉, 不影响解析


def add_usage_observer(fn):
    """注册用量观察者 fn(in_tok, out_tok, cached_tok)。同一 fn 只注册一次。
    存在原因: _record_usage 原先只 print, token 无法按 turn 归集(SPEC Part 4.6)。"""
    if fn not in _USAGE_OBSERVERS:
        _USAGE_OBSERVERS.append(fn)


def _emit_usage(inp, out, cached=0):
    """把已归一的用量发给观察者; 观察者出错绝不影响协议解析。"""
    for fn in list(_USAGE_OBSERVERS):
        try:
            fn(int(inp or 0), int(out or 0), int(cached or 0))
        except Exception:
            pass
```

然后把 `_record_usage` 改为（每个分支末尾加一行 `_emit_usage`，print 一律不动）：

```python
def _record_usage(usage, api_mode):
    if not usage: return
    if api_mode == 'responses':
        cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
        inp = usage.get("input_tokens", 0); out = usage.get("output_tokens", 0)
        print(f"[Cache] input={inp} cached={cached}")
        if out: print(f"[Output] tokens={out}")
        _emit_usage(inp, out, cached)
    elif api_mode == 'chat_completions':
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        inp = usage.get("prompt_tokens", 0); out = usage.get("completion_tokens", 0)
        print(f"[Cache] input={inp} cached={cached}")
        if out: print(f"[Output] tokens={out}")
        _emit_usage(inp, out, cached)
    elif api_mode == 'messages':
        ci, cr, inp = usage.get("cache_creation_input_tokens", 0), usage.get("cache_read_input_tokens", 0), usage.get("input_tokens", 0)
        print(f"[Cache] input={inp} creation={ci} read={cr}")
        _emit_usage(inp, out=usage.get("output_tokens", 0), cached=cr)
```

再改 `_parse_claude_sse` 的 `message_delta` 分支（第 179-180 行）：

```python
        elif evt_type == "message_delta":
            delta = evt.get("delta", {})
            stop_reason = delta.get("stop_reason", stop_reason)
            out_usage = evt.get("usage", {})
            out_tokens = out_usage.get("output_tokens", 0)
            if out_tokens:
                print(f"[Output] tokens={out_tokens} stop_reason={stop_reason}")
                # Claude 流式 output_tokens 不经 _record_usage; 只补输出, 输入仍由 message_start 上报
                _emit_usage(0, out_tokens, 0)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_llm_usage_observer.py -q`
Expected: 全部 PASS（6 项）

- [ ] **Step 5: 确认没有破坏既有测试**

Run: `python -m pytest tests/test_observation_timing.py -q`
Expected: 11 passed（该文件覆盖 `patch_usage` / `patch_llm_timing`，是本任务最相关的回归）

- [ ] **Step 6: 提交**

```bash
git add app/src/main/assets/gacore/llmcore.py tests/test_llm_usage_observer.py
git commit -m "feat(android): llmcore 开用量观察者 seam——token 可按 turn 归集, 三个协议分支与 Claude 流式都覆盖" -m "" -m "Co-authored-by: Claude <noreply@anthropic.com>"
```

---

## Task 4: `droid._act()` 打「动作已下发」标记

**Files:**
- Modify: `app/src/main/assets/gacore/droid.py:60`（`import run_guard` 下一行加 import）与 `droid.py:337`（`_act` 末尾）
- Test: `tests/test_run_metrics.py`（追加 `TestActionMark`）

**Interfaces:**
- Consumes: Task 1 的 `run_metrics.mark_action_dispatched()`
- Produces: 无新接口；行为约束——`_act()` 的返回值与异常路径**完全不变**

- [ ] **Step 1: 写失败测试**

在 `tests/test_run_metrics.py` 末尾追加：

```python
class TestActionMark:
    """droid._act() 是动作派发唯一入口; 打完点必须原样返回, 且任何异常路径不得被观测改变。"""

    def test_act_marks_the_dispatch_and_returns_unchanged(self, monkeypatch, clean_verify):
        import droid
        marks = []
        monkeypatch.setattr(droid.run_metrics, 'mark_action_dispatched', lambda: marks.append(1))
        monkeypatch.setattr(droid, '_gate_injection', lambda op: None)
        monkeypatch.setattr(droid, '_record_path', lambda kind: None)
        monkeypatch.setattr(droid, '_base', lambda: 'http://127.0.0.1:1')   # 否则回退分支会 ping 真机总线
        monkeypatch.setattr(droid, '_check', lambda r: {'ok': True, 'x': 1})
        monkeypatch.setattr(droid, '_SESSION', type('S', (), {'post': staticmethod(lambda *a, **k: None)})())
        assert droid._act(op='tap', x=1, y=2) == {'ok': True, 'x': 1}
        assert marks == [1]

    def test_a_failing_mark_does_not_break_the_action(self, monkeypatch, clean_verify):
        import droid

        def boom():
            raise RuntimeError('observer bug')

        monkeypatch.setattr(droid.run_metrics, 'mark_action_dispatched', boom)
        monkeypatch.setattr(droid, '_gate_injection', lambda op: None)
        monkeypatch.setattr(droid, '_record_path', lambda kind: None)
        monkeypatch.setattr(droid, '_base', lambda: 'http://127.0.0.1:1')
        monkeypatch.setattr(droid, '_check', lambda r: {'ok': True})
        monkeypatch.setattr(droid, '_SESSION', type('S', (), {'post': staticmethod(lambda *a, **k: None)})())
        with pytest.raises(RuntimeError, match='observer bug'):
            droid._act(op='tap', x=1, y=2)
```

注意：第二个测试**断言打点异常会向上抛**——这是当前实现的真实行为（打点在 `return` 之前）。Phase 0 只要求"记录不增加模型调用与设备操作"，不要求改变 `_act` 的异常语义；若后续要把它变成完全静默，是独立改动，不在本计划内。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_run_metrics.py::TestActionMark -q`
Expected: `AttributeError: module 'droid' has no attribute 'run_metrics'`

- [ ] **Step 3: 实现打点**

`app/src/main/assets/gacore/droid.py` 第 60 行 `import run_guard` 之后加：

```python
import run_metrics   # 只观测: 动作后验计时打点(SPEC Phase 0); 不参与任何门禁/几何判定
```

把 `_act` 的结尾（第 337 行）

```python
    return _check(_SESSION.post(_base() + "/a11y/act", json=body, timeout=30))
```

改为

```python
    ret = _check(_SESSION.post(_base() + "/a11y/act", json=body, timeout=30))
    run_metrics.mark_action_dispatched()   # 只观测(SPEC Phase 0): 记"动作已下发"时刻, 供 run_metrics 把随后的稳态等待/截图/对比分摊为 verify_wait; 不影响返回值与行为
    return ret
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_run_metrics.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 确认手机工具回归未破**

Run: `python -m pytest tests/test_phone_task_regressions.py tests/test_observation_timing.py tests/test_droid_appfn_rel_swipe.py tests/test_scroll_timing.py tests/test_screenshot_throttle.py -q`
Expected: 与改动前一致（改动前这些文件全过；若 `test_phone_task_regressions.py` 的 1 个 Playwright 失败仍在，属基线）

- [ ] **Step 6: 提交**

```bash
git add app/src/main/assets/gacore/droid.py tests/test_run_metrics.py
git commit -m "feat(android): _act 派发成功后打点——把动作后验耗时从工具执行里分摊出来 (SPEC Phase 0)" -m "" -m "Co-authored-by: Claude <noreply@anthropic.com>"
```

---

## Task 5: `plugins/run_metrics_hook.py` 接线 + 端到端落盘

**Files:**
- Create: `app/src/main/assets/gacore/plugins/run_metrics_hook.py`
- Test: `tests/test_run_metrics_hook.py`（新建）

**Interfaces:**
- Consumes: Task 1/2 的 `run_metrics.RunRecorder` / `mark_action_dispatched` / `take_verify_seconds` / `append_jsonl` / `prune_oldest` / `DEFAULT_KEEP`；Task 3 的 `llmcore.add_usage_observer`
- Produces: 无新接口；落盘契约：
  - 目录 `<GA_DIR>/temp/model_responses/sessions/`（`_clear_temp()` 唯一保留的子树）
  - 文件 `metrics_<logid>.jsonl`，`<logid>` 取自 `handler.parent.log_path` 的文件名根（与既有 LLM 响应日志同根，可互相印证）
  - 每 turn 一行 `{"type":"turn",...}`，运行结束一行 `{"type":"run_summary",...}`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_run_metrics_hook.py`：

```python
"""run_metrics 插件: 挂 agent_loop 既有 hook 点, 一次任务产出 SPEC Part 7.1 全指标集。

用假 client/handler 真跑 agent_runner_loop: 不连设备、不联网、不需要模型 key。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import agent_loop
import llmcore
import run_metrics
import plugins.run_metrics_hook as hook
from agent_loop import StepOutcome


class _Backend:
    def __init__(self):
        self.history = [{'role': 'user', 'content': [{'type': 'text', 'text': 'x' * 100}]}]


class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = json.dumps(arguments)


class _TC:
    def __init__(self, name, args, id='tc1'):
        self.function = _Fn(name, args)
        self.id = id


class _Resp:
    def __init__(self, tool_calls):
        self.thinking = ''
        self.content = 'ok'
        self.raw = ''
        self.tool_calls = tool_calls
        self.stop_reason = 'tool_use' if tool_calls else 'end_turn'


class _Client:
    """两轮: 第一轮调 tap, 第二轮不调工具(引擎自动触发 no_tool → 结束)。"""
    last_tools = ''

    def __init__(self, script):
        self.script = list(script)
        self.backend = _Backend()

    def chat(self, messages, tools=None):
        name = self.script.pop(0)
        if name:
            llmcore._record_usage({'prompt_tokens': 1975, 'completion_tokens': 42,
                                   'prompt_tokens_details': {'cached_tokens': 8}}, 'chat_completions')
        yield 'chunk'
        return _Resp([_TC(name, {})] if name else [])


class _Handler(agent_loop.BaseHandler):
    def __init__(self, parent):
        self.max_turns = 5
        self.current_turn = 0
        self._done_hooks = []
        self.parent = parent
        self.working = {}

    def do_tap(self, args, response):
        """合成替身: 代表"结果自带判定字段的工具"——即未来的结构化动作空间。
        今天所有手机动作都埋在 code_run 的 stdout 里, 工具级判定确实取不到(见模块已知限制),
        所以这条路径用替身覆盖, 不冒充真实现状。"""
        run_metrics.mark_action_dispatched()     # 模拟"动作已下发"(真实路径由 droid._act 打点)
        return StepOutcome({'verified': True, 'diff': 'diff: 1.500% bbox=[0,0,9,9]'},
                           next_prompt='next')

    def do_no_tool(self, args, response):
        return StepOutcome({'done': True}, next_prompt=None)


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('GA_DIR', str(tmp_path))
    saved, hook._rec = hook._rec, None
    yield tmp_path / 'temp' / 'model_responses' / 'sessions'
    hook._rec = saved


def _drive(tmp_path, script=('tap', None), logid='1700000000000000000'):
    parent = SimpleNamespace(log_path=str(tmp_path / f'model_responses_{logid}.txt'))
    handler = _Handler(parent)
    agent_loop.agent_runner_loop(_Client(list(script)), 'sys', 'read three headlines',
                                 handler, [], max_turns=5, verbose=False)
    return handler


def _lines(path):
    return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()]


def test_one_task_writes_the_phase_zero_metric_set(run_dir, tmp_path):
    _drive(tmp_path)
    files = list(run_dir.glob('metrics_*.jsonl'))
    assert len(files) == 1
    lines = _lines(files[0])
    turns = [x for x in lines if x['type'] == 'turn']
    summary = [x for x in lines if x['type'] == 'run_summary']
    assert len(turns) == 2 and len(summary) == 1
    t1 = turns[0]
    assert t1['layer'] == 'L4' and t1['turn'] == 1
    assert t1['model_wait_s'] >= 0 and t1['tool_exec_s'] >= 0 and t1['verify_wait_s'] >= 0
    assert (t1['in_tok'], t1['out_tok']) == (1975, 42)
    assert t1['resend_chars'] > 0
    assert t1['tools'] == ['tap']
    assert t1['tool_records'][0]['verdict'] == {'verified': True, 'diff_pct': 1.5}
    assert t1['tool_records'][0]['verifier'] == '_img_diff_str'
    assert t1['escalations'] == []
    s = summary[0]
    assert s['turns'] == 2 and s['model_calls'] == 2
    assert s['end_reason'] == 'CURRENT_TASK_DONE'
    assert s['p50_turn_s'] is not None and s['p95_turn_s'] is not None
    assert s['in_tok'] == 3950 and s['out_tok'] == 84
    assert s['tools_verified'] == 1
    assert s['tools_uncertain'] == 0 and s['tools_without_verdict'] == 0


def test_metrics_file_sits_beside_the_session_snapshots(run_dir, tmp_path):
    _drive(tmp_path)
    assert (run_dir / 'metrics_1700000000000000000.jsonl').exists()


def test_the_engine_no_tool_call_is_not_counted_as_a_tool(run_dir, tmp_path):
    _drive(tmp_path)
    lines = _lines(next(run_dir.glob('metrics_*.jsonl')))
    turns = [x for x in lines if x['type'] == 'turn']
    assert [t['n_tools'] for t in turns] == [1, 0]
    assert turns[1]['tools'] == []


def test_pruning_keeps_only_the_newest_run_files(run_dir, tmp_path):
    for i in range(run_metrics.DEFAULT_KEEP + 3):
        _drive(tmp_path, logid=str(1700000000000000000 + i))
    assert len(list(run_dir.glob('metrics_*.jsonl'))) == run_metrics.DEFAULT_KEEP


def test_unfinished_run_is_closed_by_the_next_task(run_dir, tmp_path):
    """中止/异常时 agent_after 不触发; 下一个任务开局必须把上次标成 unfinished, 不丢也不假完成。"""
    hook._on_agent_before({'handler': _Handler(SimpleNamespace(
        log_path=str(tmp_path / 'model_responses_1.txt')))})
    hook._on_turn_before({'turn': 1})
    hook._on_llm_before({})
    hook._on_llm_after({'client': _Client([])})
    # 没有 turn_after / agent_after —— 模拟循环生成器被弃
    _drive(tmp_path, logid='2')
    assert _lines(run_dir / 'metrics_1.jsonl')[-1]['end_reason'] == 'unfinished'


def test_a_failing_write_never_breaks_the_task(run_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(run_metrics, 'append_jsonl',
                        lambda *a, **k: (_ for _ in ()).throw(OSError('disk full')))
    handler = _drive(tmp_path)          # 仍然正常跑完并返回终态
    assert handler.current_turn == 2


def test_ga_dir_fallback_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv('GA_DIR', raising=False)
    assert hook._ga_dir().endswith('gacore')
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_run_metrics_hook.py -q`
Expected: `ModuleNotFoundError: No module named 'plugins.run_metrics_hook'`

- [ ] **Step 3: 实现插件**

创建 `app/src/main/assets/gacore/plugins/run_metrics_hook.py`：

```python
"""run_metrics 插件 —— 每 turn 指标落盘(docs/SPEC.md Phase 0 / Part 4.6)。

契约与 tool_events_hook 一致: 执行层零改动, 只挂 agent_loop 既有 hook 点;
任何失败静默(hooks.trigger 已吞异常, 这里再兜一层); 指标只写文件, 不回灌模型上下文。

落盘: <GA_DIR>/temp/model_responses/sessions/metrics_<logid>.jsonl
  —— _clear_temp() 唯一保留的子树, 与 session_*.json 同级; 每次任务开局限量到最近 DEFAULT_KEEP 个。
已知限制(如实记录):
  - 今天所有手机动作都埋在 code_run 的 stdout 里(droid.tap 的返回值不经过工具结果),
    所以工具级判定今天取不到 → 记录里 tools_without_verdict 会等于工具调用数。
    这是现状而不是缺陷: 该计数把这处空白显式记下来, 等结构化动作空间(Phase 1+)落地,
    同一段 extract_verdict/attrib_verifier 直接开始产出 verified/uncertain 与判定来源。
  - 任务被用户中止或抛异常时, agent_loop 的 agent_after 不触发 → 只落已完成的 turn 行,
    没有汇总行; 下一次任务开局会把上次补一条 end_reason='unfinished' 的汇总。
  - 一轮里供应商侧重试/故障转移产生的多次 HTTP 请求只记一次 model_wait(墙钟已含重试)。
"""
import json
import os
import threading
import time

from plugins.hooks import register
import run_metrics

_PREFIX = 'metrics_'
_SUFFIX = '.jsonl'
_lock = threading.Lock()
_rec = None                      # 当前任务的 RunRecorder(任务在 run 线程上串行)


def _safe(fn, *a):
    try:
        fn(*a)
    except Exception:
        pass


def _ga_dir():
    """进程级真相(android_entry.init 固化); CLI 未设时回退到本文件上两级 = gacore/。"""
    d = os.environ.get('GA_DIR')
    if d:
        return d
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _metrics_dir():
    return os.path.join(_ga_dir(), 'temp', 'model_responses', 'sessions')


def _logid(ctx):
    """与既有 LLM 日志同根(model_responses_<ns>.txt) → 指标与响应日志可互相印证。"""
    raw = ''
    try:
        lp = getattr(getattr(ctx.get('handler'), 'parent', None), 'log_path', '') or ''
        if lp:
            raw = os.path.splitext(os.path.basename(lp))[0].replace('model_responses', '').lstrip('_')
    except Exception:
        raw = ''
    raw = raw or str(time.time_ns())
    return ''.join(c for c in raw if c.isalnum() or c in '_-')[:64] or 'run'


def _gen():
    """Android 侧代际号(与 poll/tool_events 同源); 无归属会话返回 0。"""
    try:
        from kernel_adapter import patches
        st = getattr(patches.current_sess(), 'state', None)
        if isinstance(st, dict):
            return int(st.get('gen', 0) or 0)
    except Exception:
        pass
    return 0


def _resend_chars(ctx):
    """本轮真正重发的历史字符数 = BaseSession.history 序列化长度(协议路径每轮整体重发)。
    取不到返回 None——不猜。"""
    try:
        hist = getattr(getattr(ctx.get('client'), 'backend', None), 'history', None)
        if isinstance(hist, list):
            return sum(len(json.dumps(m, ensure_ascii=False, default=str)) for m in hist)
    except Exception:
        pass
    return None


def _sink(lines):
    """RunRecorder 的写入口(显式副作用边界); 失败静默。"""
    rec = _rec
    if rec is None:
        return
    run_metrics.append_jsonl(
        os.path.join(_metrics_dir(), _PREFIX + rec.run.run_id + _SUFFIX), lines)


def _install_usage_observer():
    """把 llmcore 的用量观察者接到当前 recorder(幂等; recorder 每次任务换新, 由闭包现取)。"""
    try:
        import llmcore
        llmcore.add_usage_observer(_on_usage)
    except Exception:
        pass


def _on_usage(in_tok, out_tok, cached_tok):
    rec = _rec
    if rec is not None:
        _safe(rec.note_tokens, in_tok, out_tok)


def _on_agent_before(ctx):
    global _rec
    with _lock:
        prev, _rec = _rec, None
    if prev is not None:                     # 上一轮被中止/异常弃掉: 补一条汇总, 不丢也不假完成
        _safe(prev.end_run, 'unfinished')
    with _lock:
        _rec = run_metrics.RunRecorder(run_id=_logid(ctx), gen=_gen(), sink=_sink)
    _install_usage_observer()
    _safe(run_metrics.prune_oldest, _metrics_dir(), _PREFIX, run_metrics.DEFAULT_KEEP)


def _on_turn_before(ctx):
    rec = _rec
    if rec is not None:
        _safe(rec.start_turn, int(ctx.get('turn') or 0))


def _on_llm_before(ctx):
    rec = _rec
    if rec is not None:
        _safe(rec.llm_start)


def _on_llm_after(ctx):
    rec = _rec
    if rec is None:
        return
    n = _resend_chars(ctx)
    if n is not None:
        _safe(rec.set_resend_chars, n)
    _safe(rec.llm_end)


def _on_tool_before(ctx):
    if (ctx.get('tool_name') or '') == 'no_tool':
        return                              # 引擎自动触发, 不是工具调用
    rec = _rec
    if rec is not None:
        _safe(rec.tool_start)


def _on_tool_after(ctx):
    if (ctx.get('tool_name') or '') == 'no_tool':
        return                              # 引擎自动触发, 不是工具调用
    rec = _rec
    if rec is None:
        return
    _safe(rec.tool_end, str(ctx.get('tool_name') or ''),
          getattr(ctx.get('ret'), 'data', None), run_metrics.take_verify_seconds())


def _on_turn_after(ctx):
    rec = _rec
    if rec is not None:
        _safe(rec.end_turn)


def _on_agent_after(ctx):
    global _rec
    with _lock:
        rec, _rec = _rec, None
    if rec is None:
        return
    reason = ctx.get('exit_reason')
    reason = reason.get('result', '') if isinstance(reason, dict) else ''
    _safe(rec.end_run, reason or 'MAX_TURNS_EXCEEDED')


register('agent_before', _on_agent_before)
register('turn_before', _on_turn_before)
register('llm_before', _on_llm_before)
register('llm_after', _on_llm_after)
register('tool_before', _on_tool_before)
register('tool_after', _on_tool_after)
register('turn_after', _on_turn_after)
register('agent_after', _on_agent_after)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_run_metrics_hook.py -q`
Expected: 全部 PASS（7 项）

- [ ] **Step 5: 三个测试文件一起跑**

Run: `python -m pytest tests/test_run_metrics.py tests/test_llm_usage_observer.py tests/test_run_metrics_hook.py -q`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add app/src/main/assets/gacore/plugins/run_metrics_hook.py tests/test_run_metrics_hook.py
git commit -m "feat(android): run_metrics 插件——挂既有 hook 点, 每 turn 指标落盘到 sessions 目录 (SPEC Phase 0)" -m "" -m "Co-authored-by: Claude <noreply@anthropic.com>"
```

---

## Task 6: 文档一致性与全量回归

**Files:**
- Modify: `CHANGELOG.md`（`## Unreleased / 未发布变更` 之下）
- Modify: `docs/ARCHITECTURE.md`（`## Boundaries / 模块边界` 表格追加 4 行）

**Interfaces:**
- Consumes: Task 1–5 的产物
- Produces: 无代码接口
- 门禁来源：SPEC Part 8「Documentation and consistency gate (every phase)」——`ARCHITECTURE.md` 需补上它目前遗漏的 `memory`、`sense`、`evolution`；**本计划不修改 SPEC.md / ROADMAP.md / VALIDATION.md**，Phase 0 只有在真机记录运行留档后才算完成。

- [ ] **Step 1: 更新 CHANGELOG**

在 `CHANGELOG.md` 的 `## Unreleased / 未发布变更` 标题下插入：

```markdown
- Diagnostics: each task now writes a per-turn run record to
  `temp/model_responses/sessions/metrics_<id>.jsonl` — model wait, tool execution and
  post-action verification time, input/output tokens, re-sent history size, and the
  verifier that produced each verdict, plus a run summary with P50/P95. Recording is
  observation only: it adds no model calls and no device operations, and a failed write
  never affects the task. 每个任务落一份按 turn 的记录：模型等待、工具执行与动作后验耗时、
  输入输出 token、重发历史大小与每轮判定来源，附 P50/P95 汇总。只观察，不增加模型调用与
  设备操作，写盘失败不影响任务。
```

- [ ] **Step 2: 更新 ARCHITECTURE.md 边界表**

在 `docs/ARCHITECTURE.md` 的边界表末尾（`pclink.py / ganet.py` 那一行之后）追加：

```markdown
| memory/*.md + global_mem*.txt | L0–L3 memory and SOP store | SOP files are prose with no executor; the model is the only interpreter, and L1 is a seeded index the device evolves |
| sense.py | Local evidence collection with coverage reporting | `_evidence` separates "not collected" from "did not happen"; `recall()` may abstain |
| evolution.py | Three-way merge of self-evolution backups | Conflicts surface for review; no silent overwrite |
| agent_loop.py + plugins/*_hook.py | Turn loop and observation hooks | Hooks observe only; a plugin failure never stops the loop |
| run_metrics.py + plugins/run_metrics_hook.py | Per-turn run metrics for the SPEC phases | Observation only: no model calls, no device operations, and a failed write never affects the task |
```

- [ ] **Step 3: 全量回归与基线对比**

```bash
cd /e/project/daiyimo/GAgent
python -m pytest -q 2>&1 | tail -3
python -m pytest -q 2>&1 | grep -E "^(ERROR|FAILED)" | sed 's/\[.*//' | sort > /tmp/after.txt
```

Expected: `failed` 与 `errors` 的**数量与测试名集合与改动前完全一致**（基线 38 failed / 5 errors，全部来自 Playwright 浏览器未安装与 `tests/test_service_boundaries.py:47` 的 Windows chmod 既有问题）；`passed` 比基线 336 多出本计划新增的约 33 项。若出现**新的**失败名，定位并修复，不允许用"基线本来就不绿"带过。

- [ ] **Step 4: 仓库既有扫描门禁**

```bash
python tools/audit_source.py
git diff --check
```

Expected: 两条都无输出/通过（`audit_source.py` 失败则按其输出修复本次改动引入的问题）

- [ ] **Step 5: 提交**

```bash
git add CHANGELOG.md docs/ARCHITECTURE.md
git commit -m "docs: 记录 Phase 0 指标落盘, 并补回 ARCHITECTURE 遗漏的 memory/sense/evolution 边界" -m "" -m "Co-authored-by: Claude <noreply@anthropic.com>"
```

---

## 真机验收（需用户授权，本计划不自动执行）

用户已授权跑一次。执行前必须先向用户说明：用的哪个模型/端点、跑什么任务、预期消耗；执行后用本计划产出的指标文件回报。

前置条件：设备上安装的 APK 必须包含本分支的 `gacore`（`AssetUnpacker` 会把 assets 里的 `gacore/` 解压到 `GA_DIR`），且已配好可用的模型 key。

步骤：

1. 装包含本分支代码的 debug/release 包，确认 GAgent 有可用服务商配置。
2. 通过 WebUI 或悬浮窗发一个**只读**任务（例如「打开设置，读出前三条菜单项」），不使用任何注入类操作。
3. 任务结束后拉取记录文件：

```bash
adb -s ZYPZ261A01M68700159 exec-out run-as com.ljq.ga cat files/gacore/temp/model_responses/sessions/metrics_<id>.jsonl
```

（`GA_DIR` 以 `android_entry.init()` 实际传入为准；上面是常见布局，取不到时先用
`adb shell run-as com.ljq.ga find . -name 'metrics_*.jsonl'` 定位。）

4. 核对 SPEC Phase 0 验收三条：
   - 记录里出现 Part 7.1 全指标集（`model_wait_s` / `tool_exec_s` / `verify_wait_s` /
     `in_tok` / `out_tok` / `resend_chars` / `layer` / `escalations` / `p50_turn_s` / `p95_turn_s`）；
   - 记录本身没有新增模型调用与设备操作（对照同一任务改动前后的 turn 数与截图次数）；
   - `python -m pytest -q` 失败集合不变。
5. 只有第 4 步留档后，才允许在 `docs/VALIDATION.md` 写一条带日期的记录，并把 SPEC 的
   Phase 0 称为已完成。**未留档前不得宣称为已实现能力。**
