# Core & memory / 内核与记忆

[README](../README.md) · [Architecture](ARCHITECTURE.md) · [Development](DEVELOPMENT.md)

## What “~3K lines” means / 约 3K 行的口径

[GenericAgent](https://github.com/lsdefine/GenericAgent) describes its starting
framework as a **~3K-line seed core**: a compact agent loop, a small set of tools
and a memory system that can accumulate reusable procedures. GAgent carries this
lineage and architecture into Android. It is an adapted descendant, not a claim
of byte-for-byte equivalence with today's upstream main.

“约 3K 行”来自上游对种子框架的描述。GAgent 沿用其内核架构并适配 Android，
不将上游的数字当成整个 APK、所有工具或当前仓库的代码总量。

For a reproducible local reference, these four files contain **2,161 physical
lines** on 2026-10-23, including comments and blank lines:

| File | Physical lines | Role / 职责 |
| --- | ---: | --- |
| [agent_loop.py](../app/src/main/assets/gacore/agent_loop.py) | 133 | Observe/tool/response loop / 执行循环 |
| [agentmain.py](../app/src/main/assets/gacore/agentmain.py) | 399 | Tool dispatch and execution support / 工具调度与执行 |
| [llmcore.py](../app/src/main/assets/gacore/llmcore.py) | 1,134 | Model protocols and history handling / 模型协议与历史处理 |
| [ga_android.py](../app/src/main/assets/gacore/ga_android.py) | 495 | Android agent policy and memory integration / Android 策略与记忆接入 |

~~~sh
wc -l app/src/main/assets/gacore/{agent_loop,agentmain,llmcore,ga_android}.py
~~~

This is a named-file count, **not a complete dependency or core inventory**.
It excludes other Python adapters, Android/Kotlin, WebUI, libraries, model weights
and build tooling. Changes may alter these counts; use the command at your checkout.
The small loop explains the design; the complete application still needs its platform.

这些数字只统计列出的四个文件，不能用来宣称全功能应用只有 2,161 行。
Android 层承担生命周期、权限、取屏、输入与后台工作；保留清晰边界比压低总行数更重要。

## Remember the method, recall the relevant part / 沉淀方法，按需召回

The bundled [memory SOP](../app/src/main/assets/gacore/memory/memory_management_sop.md)
organizes knowledge in layers:

| Layer | Content / 内容 | How it helps / 用途 |
| --- | --- | --- |
| L1 | Small index, with a target of at most 30 lines / 不超过约 30 行的入口索引 | Locate relevant material without loading the whole library / 定位而非全量注入 |
| L2 | Facts and environment references / 事实与环境索引 | Reuse established context; verify facts that can change / 复用事实，复核时效 |
| L3 | Procedures and executable scripts / 规程与脚本 | Reuse a tested method instead of rediscovering each step / 复用验证过的方法 |
| L4 | Raw sessions and evidence / 原始会话与证据 | Retrieve detail when a summary is insufficient / 按需追溯原始依据 |

Working-memory checkpoints and selective folding live in `ga_android.py`;
history-tag compression and trimming live in `llmcore.py`. Context limits depend
on the selected configuration and model. There is no universal fixed token cap.
Local text changes also have [asset-update preservation](FEATURE_SCOPE.md), which
is best-effort merging rather than a guarantee that every edit survives an upgrade.

工作检查点保存当前状态，分层记忆保存可复用知识；它们各有用途。
规程必须区分已验证事实、失败尝试与待办。自我进化是方法和工具的积累，
不意味着模型权重在线训练，也不意味着可以未经授权扩大权限。

## How to measure token efficiency / 如何测量 Token 效率

GAgent reduces repeated context through selective retrieval, compact progress
and reusable tools. A saved procedure can avoid repeated exploration, but its
benefit depends on task quality, model behavior, image inputs and retries.

For a fair experiment, fix the task, device/app state, model/protocol and tool
configuration. Compare fresh versus reused memory; record provider-reported input,
output and cached tokens, wall time, retries and independently verified completion.
Keep failed and blocked runs. Report missing token counters as missing, not zero.

公平比较需固定任务、设备与初始状态、模型、协议和工具；分别记录首次探索与记忆复用。
Token、耗时与完成质量一起看，不能靠减少观察来制造低开销。
上游桌面成绩不能直接转作 Android 成绩；当前[验收](VALIDATION.md)没有证明固定节省倍数。

## Variables and invariants / 变量与不变量

Models, screen dimensions, orientation, permissions, account state and service
endpoints vary. Keep parsing, coordinate validation and policy decisions separate
from device/network effects. A fresh observation, explicit authorization, correct
coordinate space and verified outcome remain invariants across those changes.

模型、屏幕、权限、登录态和网络是变量；新鲜观察、明确授权、坐标一致与结果核验是不变量。
变化应落在设备和协议适配层，保留内核的少量通用工具与执行循环。
