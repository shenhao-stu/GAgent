# Hybrid phone agent spec / 混合式手机 Agent 规格

[Documentation index](README.md) · [Architecture](ARCHITECTURE.md) ·
[Roadmap](ROADMAP.md) · [Validation](VALIDATION.md) ·
[Core & memory](CORE_AND_MEMORY.md) ·
[Empowerment addendum / 赋能增补](SPEC-EMPOWERMENT.md)

## Status of this document / 文档性质

This is a **design specification**, not a capability claim. It is split in two:

- **Part 2 (AS-IS)** records what current `main` source actually implements, with
  file and line references. Every statement there is traceable to code or to a
  dated validation record.
- **Parts 3–8 (TO-BE)** describe target architecture, routing policy, metrics and
  phased acceptance. Nothing in those parts is shipped. A phase becomes a
  capability claim only when its acceptance evidence in Part 8 exists and is
  linked from [VALIDATION.md](VALIDATION.md).

本文是设计规格，不是能力声明。第二部分是当前源码的既成事实（带文件行号），
第三至八部分是目标设计，尚未实现；某个阶段只有在第八部分的验收证据存在、
并在 VALIDATION.md 留档之后，才能被称为已实现能力。

Nothing here authorizes changes to repository visibility, live services,
credentials or a device owner's accounts.

---

## 1. Problem statement / 问题陈述

**Observable trigger.** On an app whose UI tree is unavailable — obfuscated or
encrypted builds, self-drawn WebView pages, virtualized node lists — a task as
small as "open Tencent News and read the first three headlines" takes about one
minute. The measured cost split is dominated by model responses, then by tool
responses.

**Expected outcome.** The same底座 (base) covers ordinary apps, tree-less apps,
self-drawn pages, virtualized lists, landscape/portrait games and short-video
feeds, and picks the **cheapest channel that still produces sufficient
evidence** for the current step — not a fixed "vision first" or "tree first"
order. Speed and quality are both first-class; neither is traded silently.

**Root cause identified in Part 2.** The bottleneck is not the screenshot, the
diff or the tool round-trip. It is that a read-only task is decomposed into many
turns of a *general* ReAct loop, and every turn makes the model re-observe,
re-reason, emit code and re-verify from a full re-sent prompt.

问题不是截图、diff 或工具慢，而是简单任务也被拆成多轮通用 ReAct，每轮都让模型
重新观察、推理、生成代码和验证，且每轮重发全量历史。

---

## 2. AS-IS review / 现状审查

Source references are against `main` at the time of writing. Line numbers move;
the named symbols do not.

### 2.1 Execution architecture: one general loop / 执行架构

The whole runtime is a single generic ReAct loop plus a code executor:

| Component | Location | Role |
| --- | --- | --- |
| `agent_runner_loop` | `app/src/main/assets/gacore/agent_loop.py:42` | Turn loop: call model → dispatch tools → collect `next_prompt` → repeat. `max_turns` defaults to 40; `agentmain.py:253` passes 80 |
| `BaseHandler.dispatch` | `agent_loop.py:18` | Resolves a tool name to `do_<name>` on the handler |
| `GenericAgentHandler` | `app/src/main/assets/gacore/ga_android.py:201` | Tool implementations |
| `ToolClient.chat` | `app/src/main/assets/gacore/llmcore.py:832` | Text-protocol client (tools serialized into the prompt) |
| `NativeToolClient.chat` | `llmcore.py:1086` | Native tool-call client |

**The tool surface is seven tools, and none of them is a phone action:**

`code_run`, `file_read`, `file_patch`, `file_write`,
`update_working_checkpoint`, `ask_user`, `start_long_term_update`
(`app/src/main/assets/gacore/assets/tools_schema.json`).

Every phone operation — `droid.tap`, `droid.look`, `droid.scroll`,
`sense.*`, `webcdp.*`, `ganet.*` — is reached by the model **writing Python
inside `code_run`** (`ga_android.py:221`). There is no structured action space,
no action schema validation, and no recorded-and-replayable trace. One physical
action therefore costs at minimum: model emits code → in-process `exec` →
result formatting → model reads result → next turn.

**Consequence.** Latency scales with *turns*, and turns scale with how much the
model has to re-derive. A task that a human performs in three gestures currently
costs a model round-trip per gesture plus verification round-trips.

### 2.2 Model layer: where the time goes / 模型层耗时构成

| Mechanism | Location | Effect on latency / cost |
| --- | --- | --- |
| History re-sent every turn | `agent_loop.py:104`, `llmcore.py:615` | The loop rebuilds `messages` as *one* new user message plus tool results; the accumulated history lives in `BaseSession.history` and is re-serialized on every call |
| Prompt flattening | `llmcore.py:880` `_build_protocol_prompt` | All prior turns are concatenated into a single `user` string, so turn *N* carries the sum of turns 1..N-1 |
| History compression | `llmcore.py:46` `compress_history_tags` | Every 5 turns (`cut_msg_interval`) older `<thinking>`/`<tool_use>`/`<tool_result>` blocks are truncated to 800 chars |
| Context trim | `llmcore.py:103` `trim_messages_history` | Cap is `context_win * 3` characters, target 60%; oldest user messages are popped once exceeded |
| Tool-schema dedup | `llmcore.py:874` | When `last_tools` is unchanged the full tools JSON collapses to one line — already a real saving on the text-protocol path |
| Thinking off | `llmcore.py:469` | `payload["enable_thinking"] = False`, added 2026-10-25. **Global to `chat_completions` mode**, not scoped to the endpoint that needed it |
| Effort clamping | `llmcore.py:415` `_effort_window`, `llmcore.py:433` `_clamp_effort` | Per-model legal window for `reasoning_effort`; never emits a tier the model would reject. Good single source of truth |
| Retry backoff | `llmcore.py:368` `_stream_with_retry` | `max_retries` defaults to 4, backoff 0.5s → 30s, `time.sleep` **inside the generator** — blocks the streaming consumer |
| Read timeout | `llmcore.py:585` | 40s streaming / 240s non-streaming |
| Prompt caching | `llmcore.py:355`, `llmcore.py:667` | `cache_control` ephemeral stamped on the last two user messages; `responses` mode uses a process-level `prompt_cache_key` (`llmcore.py:4`) |
| Provider failover | `llmcore.py:1031` `MixinSession._raw_ask` | Rotates sessions on error; a fully exhausted round sleeps up to 30s before retrying |
| Tool-call parsing | `llmcore.py:944` `_parse_text_tool_calls` | On malformed JSON the **entire batch is rejected and nothing executes** — a deliberate no-partial-execution invariant |

**Dated measurements on record** (not re-measured here):

| Fact | Value | Source |
| --- | --- | --- |
| Thinking off, single round | 12.2s → 4.8s | commit `e1ac8d5`, `step_plan` endpoint |
| Thinking off, full chain | 88s → 42s | commit `e1ac8d5` |
| Local GLM-5.3-flash transfer, 3 text + 2 synthetic image requests | 1.385–2.806s | [VALIDATION.md](VALIDATION.md), 2026-10-23, Pixel 10 / Android 16 |
| Overlay restore, background→Home→app→Home | 483 / 649 ms | [VALIDATION.md](VALIDATION.md), 2026-10-23 |
| Core four files | 2,161 physical lines | [CORE_AND_MEMORY.md](CORE_AND_MEMORY.md), 2026-10-23 |

The 88s→42s result is the strongest evidence available: **model output volume,
not tooling, was the dominant term.** Any design that reduces turns or output
tokens per task attacks the real bottleneck; one that only speeds up gestures
does not.

### 2.3 Perception channels actually present / 已有感知通道

| Entry point | Returns | Cache |
| --- | --- | --- |
| `droid.dump(full)` `droid.py:307` | Accessibility nodes `[{t,d,x,y,b,cls,click,edit,range,sel}]` | none; sensitive or unresolved foreground yields `[]` (`droid.py:147,313,315`) |
| `droid.look(conf,roi,cache)` `droid.py:514` | Elements with center x/y, label, class | `_LOOK_CACHE` `droid.py:506`, key = 36×80 grayscale thumbnail + roi, hit when thumbnail differs < 0.3% |
| `droid.ui_detect(img)` `droid.py:1202` | 21-class YOLO boxes + OCR text | ORT session cached per model path |
| `droid.ocr` / `droid.ocr_text` `droid.py:1223,1228` | 4-point boxes + text + score | PPOCR singleton |
| `droid.ask_vision` `droid.py:563` | Text | none; empty response raises (`droid.py:571`) |
| `droid.ui_snapshot` `droid.py:411` | Single-window snapshot + fingerprint + blockers | none |
| `droid.shot(path,q)` `droid.py:1112` | BGR ndarray | none; two consecutive black frames raise (`_black_check` `droid.py:1091`) |
| `webcdp.web_scan` `webcdp.py:524` | DOM interactive elements with viewport bbox | none |
| `jev_ui.tap_target` / `click_text` `jev_ui.py:216` | Target resolution from candidates | none |

`look()` is the one perception path that already avoids a model round-trip for
localization, and it is the foundation any fast channel must build on.

**Known gap in the `look()` cache key:** it does not include package name or
rotation (`droid.py:543`). A cached lookup can therefore be served after the
foreground app or orientation changed. This is a correctness defect in a cache
that a fast path would depend on, and it is cheap to fix.

### 2.4 Execution channels actually present / 已有执行通道

| Entry point | Transport | Settle / verification |
| --- | --- | --- |
| `droid.tap` `droid.py:391` | `/a11y/act` → `dispatchGesture`, 100 ms stroke | `sleep 1.0` then a screenshot; `expected_screen` pre-check |
| `droid.swipe` `droid.py:441` | same, `dur` default 300 | `sleep 0.6`; endpoints clamped into the safe band by `swipePoint` |
| `droid.scroll_view` / `droid.scroll` `droid.py:640,649` | repeated `swipe(verify=False)` | 0.5s per segment; center = `w/2, h/2`. `scroll_view` takes a browse direction and is the recommended name; `scroll` keeps the legacy finger direction |
| `droid.tap_rel` `droid.py:492` | delegates to `tap` | `rx/1000*(w-1)` against the current frame's `screen()` |
| `droid.paste` `droid.py:910` | clipboard + `ACTION_PASTE` | `selectAll` first; verified against edit-node text, then region OCR |
| `droid.key` `droid.py:1069` | `ACTION_IME_ENTER` (API 30+) | ENTER only |
| `droid.launch` `droid.py:1070` | shell `am start --windowingMode 1` preferred | `_wait_fg` polls every 0.05s up to 1.0s |
| `back`/`home`/`notifications`/`panel` `droid.py:1085` | `performGlobalAction`; panel is a gesture from `y=3` | none |
| `droid.adb_shell` `droid.py:1252` | self-ADB shell, gated by `_gate_injection` `droid.py:255` | none |
| `vd_*` `vdisplay.py:174` | `input -d <vid> swipe/text/keyevent` | `vd_tap` is a same-point swipe (comment: `input tap` deadlocks with libadb) |
| `webcdp.web_click` / `web_type` `webcdp.py:547,561` | CDP `Input.dispatch*` | none |

**Scope boundary that must not move.** `webcdp` connects only to GAgent's own
WebView / task browser; connecting to a system browser or another app's WebView
is out of scope (`webcdp.py:19`). No node-tree access, internal API or
target-app CDP is permitted for third-party apps — the visual route stays the
only route for them.

### 2.5 Verification already implemented / 已有验证机制

| Check | Location | Rule |
| --- | --- | --- |
| Pixel diff | `droid.py:352` `_img_diff_str` | Grayscale `absdiff > 12`; `pct < 0.05%` hints "tapped nothing / did not scroll" |
| Scroll verdict | `droid.py:612` `_scroll_verdict` | `text_ratio > 0.30` **or** `pixel > 1.5%`, both confirmed twice; evidence window `roi=(0, max(48, 5%h), w, min(h-60, 94%h))` |
| Shape change | `droid.py:607` `_shape_changed` | Screenshot geometry change → `uncertain` |
| Text change ratio | `droid.py:587` | Used for scroll and paste verdicts |
| Paste verification | `droid.py:880` `_ocr_region`, `droid.py:846` `_classify_paste_rows` | Edit-node text match, else region OCR; any failed observation → `uncertain=True` (`droid.py:906`) |
| Foreground change | `droid.py:769` | Package change mid-scroll → `uncertain` |

`uncertain` is a first-class outcome, not an error. That is the right shape: a
fast path must be able to say "I cannot prove this worked" and escalate rather
than guess.

### 2.6 Memory and SOP: not executable / 记忆与规程不可执行

| Layer | File | Written by | Read by |
| --- | --- | --- | --- |
| L0 meta-procedure | `memory/memory_management_sop.md` | `file_patch` `ga_android.py:128` | `do_start_long_term_update` `ga_android.py:412` |
| L1 index | `memory/global_mem_insight.txt` (generated at first run) | `agentmain.py:32` | injected into the system prompt `agentmain.py:102`, refreshed every 10 turns `ga_android.py:462` |
| L2 facts | `memory/global_mem.txt` | `agentmain.py:30` | same |
| L3 procedures | 26 `memory/*.md` SOPs + `modes_index.md` | `file_patch` | LLM via `file_read` `ga_android.py:302` |
| L4 raw sessions | `memory/L4_raw_sessions/` | — | **documented only; the directory does not exist in the repository** |

**Finding: SOPs are natural-language markdown with no interpreter and no
executor.** The only executor is the LLM itself: read the markdown, then call
`droid`/`sense`/`webcdp` inside `code_run`. The single structured execution body
is the L2 composition in `sense.py:1757`, whose own docstring states it only
fixes *which* atoms run *in what order* and leaves judgement and phrasing to the
L3 SOP. `_mem_meta` (`android_entry.py:1744`) parses SOP tables for the WebUI
panel only; it drives no routing.

**Recall.** No embeddings, no vector store — a repository-wide search for
`embed|vector|cosine|faiss` under `gacore/` returns nothing. Recall is: L1 index
resident in context (keyword → SOP filename) + `file_read(keyword=)` substring
location (`ga_android.py:155`) + a `difflib` similarity > 0.3 "Did you mean"
suggestion (`ga_android.py:180`).

**Recall correctness is verified for `sense` only.** `sense._evidence`
(`sense.py:722`) emits `coverage_ratio`, `gaps[]` and `abstain_hint`, separating
"not collected" from "did not happen"; `recall()` (`sense.py:1786`) returns
`answerable` on that basis. SOP recall has no behavioural verification — only
substring assertions over the markdown in
`apk_factory/tests/test_phone_use_policy.py`.

This is the single largest structural gap for the requested scenarios: **there
is no recorded, replayable, verified trace anywhere in the system.** Everything
is re-derived by the model on every run.

### 2.7 Capability matrix / 能力矩阵

From `memory/capabilities.json` (13 entries) cross-checked against source:

| Capability | Probe | Code |
| --- | --- | --- |
| accessibility | `droid.ping().get('a11y')` | implemented |
| asset_scan | `len(droid.pkgs())>0` | implemented |
| vendor_assistant | `vendor_bridge.discover` | implemented |
| wireless_adb | `droid.adb_status()` | implemented |
| vision | `droid.ui_detect` / `droid.ocr` | implemented; YOLO weights are not distributed by default ([OPTIONAL_YOLO.md](OPTIONAL_YOLO.md)) |
| sense_mic_bg / sense_location / sense_nearby / sense_calendar | `perm:*` or `perm:*\|sense.handle(...)` | partial: handlers exist (`sense.py:1713`), `perm:*` is a string |
| overlay / record_audio / install_unknown | `ui:*` / `perm:*` | **no code**; `onboarding_sop.md` states these are confirmed by the user replying |

Also documented but not code-backed: the L3 "type key by key" fallback in
`phone_use.md` §3 has no API (`droid.py:38` states there is no per-key typing);
`appfn_*` requires Android 16+ with self-ADB connected (`droid.py:1311`).

### 2.8 Test baseline / 测试基线

`pytest.ini` collects `tests` and `apk_factory/tests`, about 268 cases, none
requiring a real device or a production model key. Four `tools/` scripts add 81
cases outside collection and are run explicitly by CI.

Modules with **zero** unit coverage: `sense.py`, `webcdp.py`, `ganet.py`,
`ganet_pairing_protocol.py`, `ga_android.py`, `evolution.py`, `scaffold.py`,
`apk_factory.py`, `lark_native.py`, `vendor_bridge.py`, `plugins/` hooks.
`llmcore` is covered only at the tool-call parsing layer and `agentmain` at one
method.

Documentation drift found: [ARCHITECTURE.md](ARCHITECTURE.md) contains no
mention of `memory`, `SOP`, `sense` or `evolution` — it omits the largest
Python-side subsystem (26 SOP files plus 1,816 lines of `sense.py`).

---

## 3. Scene matrix / 场景矩阵

Each scene is defined by **what evidence is obtainable**, not by app name. The
router in Part 5 selects a channel from this row; no row may hardcode a package,
a device size, an orientation or an OEM layout.

| # | Scene / 场景 | Obtainable evidence / 可获得的证据 | Primary channel | Verification | Known risk / 风险 |
| --- | --- | --- | --- | --- | --- |
| S1 | Ordinary app, UI tree available | Full a11y node list with bounds, class, clickable | Tree + `look()` | node-state diff + pixel diff | stale tree after animation |
| S2 | Obfuscated / encrypted app, no tree | Screenshot only; `dump()` returns `[]` | `look()` (YOLO+OCR) → ask_vision only on residual ambiguity | pixel/text diff, `uncertain` on failure | visual false positives; see measured error rates in `phone_use.md` §0.5 |
| S3 | Self-drawn WebView page | Screenshot; DOM unreachable unless it is GAgent's own WebView | `look()`; `webcdp` **only** for GAgent's own WebView | text diff within ROI | CDP scope violation if applied to a third-party app |
| S4 | Virtualized / recycled node list | Partial node list; bounds present but content churns | `look()` + scroll-verdict evidence window | `_scroll_verdict` two-confirmation rule | recycled nodes report stale bounds |
| S5 | Landscape game | Screenshot; no actionable nodes | `look()` for HUD/text, relative gestures for the rest | pixel diff only; no node-state proof | no semantic ground truth; must stay `uncertain`-aware |
| S6 | Portrait game | same as S5 | same as S5 | same as S5 | same as S5 |
| S7 | Short-video feed | Screenshot; vertical swipe changes whole frame | relative swipe + pixel diff | `_scroll_verdict` | preload/buffer makes frame diff ambiguous |
| S8 | Text entry into a protected/IME field | Edit node may be absent or unreadable | `paste` + edit-node verification, region OCR fallback | `_classify_paste_rows` → `ime_hint`/`ime_label` | silent no-op input; must surface `uncertain` |
| S9 | Cross-app task (launch → act → return) | Package name from `ping()` | `launch` + `_wait_fg` | foreground-package assertion | IME window counted as foreground was a real defect, fixed in `5a5cbd7` |
| S10 | Rotated / folded state | `ScreenGeometry(w,h,rot)` | any | gesture-time geometry re-check | `capture()` already refuses on rotation change (`droid.py:384`) |

**Scene S5/S6/S7 have no semantic ground truth at all.** For these the spec
requires an explicit confidence field on every action and forbids reporting
success from a pixel diff alone. A game action that cannot be verified is
reported as unverified, not as done.

---

## 4. Target architecture / 目标架构

### 4.1 Layered channels, cheapest sufficient first / 分层通道

```text
                 ┌─ L0  Task Router            (pure function, no model)
user goal ───────┼─ L1  Recipe Executor        (replay + re-locate + re-verify, 0 model calls)
                 ├─ L2  Local Reactive Controller (local perception + deterministic policy)
                 ├─ L3  Grounded GUI Actor      (one small specialized model, one step)
                 └─ L4  General Agent           (today's ReAct + code_run, unchanged)
                              │
                     Action Executor (existing droid/vd_*/webcdp surface)
                              │
                     Outcome Verifier (existing diff/verdict functions)
                              │
              evidence sufficient? ──no──► escalate one layer, never silently retry
                              │
                             yes
```

The existing general loop is **kept as L4, not replaced**. L4 is the correct
tool for genuinely novel tasks; it is the wrong tool for the third repetition of
a known task. Every layer above it is an optimisation that must be able to hand
a task back down.

### 4.2 L1 Recipe Executor / 轨迹回放执行器

This is the component that removes model calls from repeat tasks, and it does
not exist today (Part 2.6).

A recipe is a **structured JSON trace**, not prose:

```json
{
  "recipe_id": "news.read_top3",
  "scene": "S3",
  "recorded_at": "2026-10-25T00:00:00Z",
  "app_hint": {"package": null, "match": "title_contains", "value": "新闻"},
  "steps": [
    {
      "intent": "open the app",
      "locator": {"kind": "text", "value": "腾讯新闻", "channel": "look"},
      "action": {"kind": "tap"},
      "expected": {"kind": "foreground_is", "value": "com.tencent.news"},
      "on_fail": "escalate"
    },
    {
      "intent": "read the first headline",
      "locator": {"kind": "roi", "value": [0, 0.08, 1.0, 0.35], "channel": "ocr"},
      "action": {"kind": "observe"},
      "expected": {"kind": "min_lines", "value": 3},
      "on_fail": "escalate"
    }
  ]
}
```

**Replay semantics — the invariant that keeps this honest:**

1. A step stores an **intent plus a locator**, never a coordinate. Coordinates
   are re-resolved against the current observation on every replay.
2. `expected` is checked by the **existing** verifier functions
   (`_scroll_verdict`, `_img_diff_str`, foreground assertion). No new verifier
   is invented for replay.
3. **Any** failed expectation escalates immediately to the next layer. There is
   no in-recipe retry loop that could repeat an action whose outcome is unknown.
4. A recipe that escalates twice in one run is marked unstable and is not
   offered by the router until re-recorded.

Rules 1 and 3 are what separate this from a brittle coordinate script. Rule 1
satisfies the standing constraint against app-specific coordinate workarounds;
rule 3 satisfies the constraint against retry loops with unknown outcomes.

### 4.3 L2 Local Reactive Controller / 本地反应式控制器

Deterministic policy over local perception, no large model:

- **Candidate selection, not coordinate generation.** Local `look()` already
  returns labelled boxes. When the goal maps onto text candidates, the
  controller picks a candidate id; it never emits a coordinate.
- **Scroll-until-found.** Uses the existing evidence window and
  two-confirmation rule; stops on target text, on `uncertain`, or on a step
  budget.
- **Confidence gate.** If the best candidate score is below a per-scene
  threshold, escalate to L3 rather than act.

This layer is where "open the app and read three headlines" can complete with
**zero** large-model calls, which is the concrete answer to the reported
bottleneck.

### 4.4 L3 Grounded GUI Actor / 专用定位模型

One small model, one step, structured output only: given a cropped observation
and a natural-language intent, return a candidate box or an explicit
`not_found`. It replaces "ask a general VLM to reason about the whole screen and
emit code" with "ask a small model where the thing is".

Constraints: it must run on-device or on a pinned endpoint, must return
structured output, and must be swappable — the interface is
`locate(observation, intent) -> candidates | not_found`, nothing more.

### 4.5 Action Executor and Outcome Verifier / 执行与验证

Unchanged from Part 2.4 and 2.5. The new layers are **callers** of the existing
surface; they add no second execution path and no second verification rule. This
keeps the change radius at the routing boundary, which is the stated preference
for this repository.

### 4.6 Required instrumentation before any optimisation / 先插桩再优化

There is currently **no persisted per-turn timing or token measurement**. The
88s→42s figure came from a manual single-endpoint experiment, not from
instrumentation. Before Phases 1–4 land, record per task:

- wall time per turn, split into model-wait / tool-exec / verify-wait
- input and output tokens per turn, and the re-sent history size
- layer chosen, escalations, and which verifier produced the final verdict

Without this, later "optimisations" cannot be distinguished from noise, and the
acceptance numbers in Part 8 are unfalsifiable.

---

## 5. Routing policy / 路由策略

The router is a **pure function**. No network, no filesystem, no clock, no
Android effect — all of those arrive as explicit arguments. This makes it unit
testable without a device, which is the only way routing policy can be trusted.

```python
def route(task: TaskText,
          observation: Observation,
          caps: CapabilitySet,
          budget: LatencyBudget) -> RouteDecision
```

### 5.1 Decision order / 决策顺序

Evaluated top to bottom; the first match wins. Every branch names the scene row
from Part 3 it serves.

| Order | Condition | Layer | Rationale |
| --- | --- | --- | --- |
| 1 | A stable recipe exists for this task **and** its scene row matches the current observation | L1 | Zero model calls; verification is the existing verifier |
| 2 | Goal maps onto local text candidates and best score ≥ scene threshold | L2 | Localization already solved by `look()`; no coordinate generation |
| 3 | Observation is obtainable but ambiguous, and budget allows one grounded call | L3 | One small structured call beats one general reasoning turn |
| 4 | No recipe, no confident local candidate, or budget exhausted | L4 | General loop is the correct fallback for novel tasks |
| 5 | Observation unobtainable **and** no vision configured | stop with an actionable error | Never act blind; `9c71fe8` already established this pattern for vision |

### 5.2 Latency budget / 时延预算

Each layer declares a budget in **model calls**, not seconds, because model wait
is the measured dominant term:

| Layer | Model calls per step | Escalation trigger |
| --- | --- | --- |
| L1 | 0 | any `expected` failure, or two escalations in one run |
| L2 | 0 | confidence below threshold, or step budget exhausted |
| L3 | 1 | `not_found`, or malformed output |
| L4 | unbounded, existing `max_turns` | unchanged |

A budget is a **hard** gate: when it is exhausted the router must escalate or
stop, never silently continue on a cheaper but insufficient channel.

### 5.3 Router invariants / 路由不变量

1. The router never selects a layer whose required evidence is absent from
   `observation`. Choosing a tree-based channel with `dump() == []` is a bug,
   not a fallback.
2. The router never selects L1 for a task whose recipe scene row disagrees with
   the current observation.
3. Escalation is always **upward by exactly one layer**, and the escalation
   reason is recorded. There is no L4→L1 shortcut mid-task.
4. The router is deterministic: identical inputs produce an identical decision.
   No randomness, no time-of-day behaviour, no provider-dependent branching.

---

## 6. Invariants and red lines / 不变量与红线

These carry over from the repository's standing constraints and are binding on
every phase below.

**Geometry and state**
- A gesture must never reuse coordinates from an incompatible observation.
  Rotation may change width and height; a 180° rotation changes neither and
  already fails loudly (`droid.py:384`).
- Re-observe and re-verify after every action. `uncertain` is a legitimate
  terminal outcome for a step.
- No hardcoded device size, orientation, OEM layout or app-specific workaround
  for a general interface defect.

**Third-party app access**
- WeChat and comparable apps stay on the **visual-only** route. No node-tree
  access, no internal API, no target-app CDP.
- `webcdp` may connect only to GAgent's own WebView.

**Execution safety**
- A malformed tool-call batch executes **nothing**
  (`llmcore.py:944`). Preserve this.
- No retry loop that can repeat an action whose outcome is unknown.
- Sensitive or unresolved foreground yields an empty node list by design
  (`droid.py:151`); do not "fix" this by weakening the gate.

**Evidence discipline**
- A screenshot or a model's own claim is not evidence of task success. The
  verifier decides.
- Documentation must not promote a plan to a capability claim. A phase is done
  when its Part 8 evidence exists and is dated.

---

## 7. Metrics / 性能与质量指标

Two families, measured from the Part 4.6 instrumentation. Targets are stated as
directions with a measurement method, not as promised numbers, because no
baseline exists yet.

### 7.1 Speed / 速度

| Metric | Definition | Why this one |
| --- | --- | --- |
| Model calls per task | Count of model round-trips, by layer | Directly attacks the measured dominant term |
| Output tokens per task | Sum of completion tokens | The 88s→42s result shows output volume drives wait |
| Re-sent history size per turn | Characters serialized into the prompt at turn *N* | Exposes the flattening cost in `llmcore.py:880` |
| P50 / P95 end-to-end | Wall time, split model / tool / verify | Separates the three contributors instead of one opaque number |
| Escalation count | L1→L2→L3→L4 transitions per task | Detects a router that escalates constantly, i.e. a useless fast path |

### 7.2 Quality / 质量

| Metric | Definition | Notes |
| --- | --- | --- |
| Terminal-state correctness | Independent check of the final screen against the goal | Must not be the acting model's self-assessment |
| Verified-action rate | Actions with a positive verifier verdict / total | `uncertain` counts as unverified, never as success |
| Silent-failure rate | Actions reported done with no positive verdict | Target: zero. This is the metric that matters most |
| False-positive rate on tree-less scenes | Wrong target acted on / actions on S2–S4 | Compare against the recorded error bands in `phone_use.md` §0.5 |
| Recipe stability | Recipes completing without escalation / total replays | A recipe that escalates twice is marked unstable |

### 7.3 Explicit non-goals for measurement / 不追求的指标

Do not optimize gestures-per-second, screenshot compression, or diff algorithm
cost. Part 2.2 shows those are not the dominant term; spending effort there
would be optimizing the wrong layer.

---

## 8. Phased acceptance / 分阶段验收

Each phase is independently shippable and independently verifiable. A phase may
not begin until the previous phase's evidence is linked from
[VALIDATION.md](VALIDATION.md).

### Phase 0 — Instrumentation / 可观测性

**Work.** Persist per-turn model-wait, tool-exec, verify-wait, input/output
tokens, re-sent history size, chosen layer and escalation reasons.

**Acceptance.**
- A recorded run of one known task produces the full metric set of Part 7.1.
- The recording itself adds no model calls and no device operations.
- `pytest -q` still passes; no existing test is modified to accommodate it.

**Blocking.** Nothing in Phases 1–4 may start before this lands, because its
numbers are the only way to tell a real improvement from noise.

### Phase 1 — Recipe record and replay (L1) / 轨迹记录与回放

**Work.** Recipe schema as in Part 4.2; a recorder that captures a successful L4
run into that schema; an executor that replays with re-location and the existing
verifiers; the two-escalations → unstable rule.

**Acceptance.**
- A recorded task replays with **zero** model calls on the same initial state.
- A deliberately altered initial state (different first item, rotated device)
  causes escalation, not a wrong action — this is the test that proves
  coordinates are not being replayed.
- `uncertain` from any verifier escalates rather than being swallowed.
- New unit tests cover: schema validation, locator re-resolution, escalation on
  failed expectation, unstable marking. Pure functions, no device.

### Phase 2 — Local reactive controller (L2) / 本地反应式控制器

**Work.** Candidate selection over `look()` output, scroll-until-found with the
existing evidence window, per-scene confidence thresholds.

**Acceptance.**
- The reference read-only task (open an app, read the first three items)
  completes with zero large-model calls on scenes S1–S4.
- Below-threshold confidence escalates to L3 in a test with a synthetic
  low-score fixture.
- The `look()` cache-key defect from Part 2.3 (missing package name and
  rotation) is fixed and covered by a test, since L2 depends on that cache.

### Phase 3 — Router and budgets / 路由与预算

**Work.** `route()` as a pure function per Part 5; wire L1/L2/L3/L4 behind it;
enforce the hard model-call budgets.

**Acceptance.**
- `route()` is fully unit-tested from synthetic `Observation`/`CapabilitySet`
  fixtures — no device, no network, no clock.
- All four router invariants in Part 5.3 have a named failing case.
- A scene mismatch between recipe and observation routes to L4, demonstrated by
  test.
- End-to-end P50 improves over the Phase 0 baseline on at least the S1–S4
  scenes, with the before/after numbers recorded.

### Phase 4 — Grounded GUI actor (L3) / 专用定位模型

**Work.** `locate(observation, intent) -> candidates | not_found`, on-device or
pinned endpoint, structured output only.

**Acceptance.**
- Interface is swappable: a stub implementation passes the same tests as the
  real one.
- Malformed or empty output escalates; it never becomes a guessed coordinate.
- Runs without a shared privileged key, and without new dependencies beyond
  what the runtime already packages.
- Measured false-positive rate on S2–S4 is recorded against the bands in
  `phone_use.md` §0.5.

### Documentation and consistency gate (every phase) / 文档一致性门禁

- [README.md](../README.md) and [README.zh-CN.md](../README.zh-CN.md) stay
  consistent for capabilities and limitations.
- [ARCHITECTURE.md](ARCHITECTURE.md) is updated to include `memory`, `sense` and
  `evolution`, which it currently omits (Part 2.8).
- Translated UI strings and HTML fallback text stay consistent.
- No new dependency is added to make a phase pass.

---

## 9. Explicit non-goals / 明确不做

- **No rewrite of the general loop.** L4 stays as-is; the work is entirely at
  the routing boundary.
- **No second execution or verification path.** New layers call the existing
  `droid`/`vd_*`/`webcdp` surface and the existing verifiers.
- **No node-tree, internal-API or target-app CDP access** for third-party apps.
- **No device-size, orientation, OEM or per-app hardcoding.**
- **No embedding or vector store** for SOP recall in these phases. The L1 index
  plus `file_read` keyword location is sufficient for the scenes named here;
  adding retrieval infrastructure before it is needed would be speculative.
- **No artificial tests for prose.** Phases that only change documentation need
  factual, link and formatting review, not invented behavior tests.
- **No live model calls or device operations as a test prerequisite.** Device
  acceptance that needs owner participation is reported as untested or blocked
  until it is actually run.
