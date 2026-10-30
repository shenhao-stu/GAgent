# Architecture / 架构

[Documentation](README.md) · [Development](DEVELOPMENT.md)

GAgent runs the agent and tools on Android; the configured model endpoint supplies
inference. Kotlin owns platform capabilities, Python owns sessions and tool
orchestration, and the local WebUI presents intent and results. Optional service
adapters connect to separately operated servers.

Kotlin 负责平台能力，Python 负责会话与工具编排，本地 WebUI 展示意图和结果，
模型接口提供推理；可选组件的服务端是独立部署边界。

~~~mermaid
flowchart LR
    U["User / 用户"] --> W["Local WebUI"]
    W --> K["Kotlin bridge"]
    K --> P["Python sessions and tools"]
    P <--> M["Configured model endpoint"]
    P --> D["Device adapter"]
    D --> B["Authenticated loopback bus"]
    B --> A["Android capabilities"]
    P --> S["Optional service adapters"]
    S --> R["Configured remote services"]
    A --> D
    P --> W
~~~

The diagram describes responsibility and data flow, not a sandbox boundary.
Generated Python has real app capabilities. Remote content and model output are
untrusted inputs even when displayed inside a trusted application.

图中是职责与数据流，不是沙箱。网页、模型输出和外部工具结果都可能是不可信输入。

## A task's path / 一次任务经过哪里

1. The WebUI submits an explicit command through the Android bridge.
2. `android_entry.py` routes it to the appropriate conversation lifecycle.
3. The session invokes the configured provider and dispatches tool work.
4. Device tools use `droid.py` and the authenticated local bus; optional clients
   use their configured network endpoints.
5. Observations return to the initiating session. A tool result is evidence for
   the next step, not automatically a success verdict.

Unknown bridge commands must not become model prompts. Retired sessions must not
accept work. A response from a previous operation must not update a newer one.

未知桥接命令不能隐式变成模型请求；已退休会话不能接新工作；旧连接结果不能写进新一代状态。

## Boundaries / 模块边界

Paths below are relative to `app/src/main/assets/gacore/`, except Kotlin files,
which live under `app/src/main/java/com/ljq/ga/`.

| Boundary / 边界 | Responsibility / 职责 | Invariant / 不变量 |
| --- | --- | --- |
| provider_config.py | Provider parsing and transformations | Preserve unrelated configuration and caller-owned inputs |
| service_config.py | Pure integration validation, explicit persistence | Unconfigured modules do not request a service; URL changes do not reuse old credentials |
| android_entry.py | Command dispatch and conversation lifecycle | Commands and output stay associated with the correct live session |
| kernel_adapter/patches.py | Runtime/thread association | Usage and output belong to the initiating session |
| droid.py / ScreenGeometry.kt | Device observations and gesture geometry | Coordinates are valid for the observed display; reject stale or out-of-bounds gestures |
| bus_auth.py / LocalBusAuth.kt | Local capability transport | The random capability goes only to the exact authenticated loopback origin |
| PermissionCoordinator.kt / OverlayPolicy.kt / FloatService.kt | Permission, lifecycle and overlay placement | Respect the user's always-on preference and keep the handle within display bounds |
| VoiceClient.kt | Streaming voice transport | TLS validation remains enabled; stale connection generations cannot publish results |
| pclink.py / ganet.py | Pairing and remote-device clients | Explicit endpoints and peer identity, without bundled server authority |
| memory/*.md + global_mem*.txt | L0–L3 memory and SOP store | SOP files are prose with no executor; the model is the only interpreter, and L1 is a seeded index the device evolves |
| sense.py | Local evidence collection with coverage reporting | `_evidence` separates "not collected" from "did not happen"; `recall()` may abstain |
| evolution.py | Three-way merge of self-evolution backups | Conflicts surface for review; no silent overwrite |
| agent_loop.py + plugins/*_hook.py | Turn loop and observation hooks | Hooks observe only; a plugin failure never stops the loop |
| run_metrics.py + plugins/run_metrics_hook.py | Per-turn run metrics for the SPEC phases | Observation only: no model calls, no device operations, and a failed write never affects the task |

## Variables and invariants / 变量与不变量

A **variable** is something the environment or user may change. An **invariant**
is a property that must remain true across those changes.

| Variables / 可变输入 | Invariant / 应保持的性质 |
| --- | --- |
| Provider, model, protocol, proxy | Credentials remain bound to the intended endpoint; text/tool/image capabilities are checked separately |
| Conversation, thread, cancellation, reconnect | Results cannot cross session or connection ownership |
| Width, height, rotation, fold layout, keyboard, system bars | Observe the current UI; validate geometry before dispatch; verify the resulting state |
| Optional module endpoint and token | No implicit enrollment or server authority; configuration changes invalidate incompatible saved credentials |
| Android version, permissions, app lifecycle | Capabilities fail explicitly when unavailable; background state is not inferred only from the activity being visible |
| Detection backend and resize/crop transform | Convert detections back to the observed physical display coordinates |

Geometry cannot detect every content change. A keyboard or dialog can move a
target without changing width or height. Capture-to-tap is not atomic. See the
[screen contract](SCREEN_GEOMETRY.md) before changing gestures.

坐标保护不能证明页面内容没变；相同宽高下也可能出现键盘或弹窗。尺寸相同不等于仍可点击旧目标。

## Functional core, explicit effects / 纯函数与副作用

Prefer `input → validated decision` functions for parsing, geometry, selection
policy and state transitions. Android callbacks, network requests, file writes
and clocks perform effects at the boundary. Pass their results into the decision
function instead of reading hidden global state inside it.

Do not create a framework or wrapper for every function. Reuse a coherent existing
entry point, keep dependency direction stable and reject invalid inputs where they
enter. Let failures stop operations when continuing could act on the wrong device,
session or endpoint; do not hide such failures behind a generic success fallback.

解析、几何和策略优先纯函数；I/O 留在边界。追求整体简单，不把“函数式”变成新增一层包装的理由。
失败处理按影响范围设计：可能影响错误目标的失败应中止，不能静默伪装成功。

## Extension rule / 扩展规则

A new provider should normally extend provider adaptation; a phone behavior should
normally extend the device adapter; an optional service belongs in an opt-in
client. Change the agent loop only when a reproduced invariant failure cannot be
resolved at the owning boundary. Supply the failing behavior and a focused
regression test before expanding core scope.

The inherited runtime and WebUI still contain large modules. These boundaries
describe current seams and intended direction, not a claim of complete
architectural purity. [Development](DEVELOPMENT.md) maps common changes to files.
