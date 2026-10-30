# Validation snapshot / 验收快照

Latest update: [2.33.8 follow-up, 2026-10-25](#v2338).

**Initial Pixel snapshot:** 2026-10-23

**Android baseline:** 2.33.3 / 136

**Initial Pixel device-build commit:** `6c4683a1a36ccc7b3b9a121099b81ef2d1d75422`

This is a bounded engineering record, not a certification or overall accuracy
claim. Later commits need checks appropriate to their changes; they do not
automatically inherit complete device acceptance from this snapshot.

本页记录一次有边界的验收，不代表所有设备、模型或任务均通过。后续提交需按变化补充证据。

## Automated build / 自动构建

[Android CI run 39930370841](https://github.com/shenhao-stu/GAgent/actions/runs/39930370841)
passed source/archive and history scans, Python/UI regressions, Kotlin tests,
both APK builds and packaged-content checks. Actions artifact retention is limited; a release must preserve its
reviewed source and artifact metadata separately.

The focused Python regressions passed in both development trees. Geometry and
overlay decisions also have Kotlin unit coverage. These checks are not an
independent security audit; native dependency limitations remain in
[Dependency security](DEPENDENCY_SECURITY.md).

## Physical device / 实机

Device: Pixel 10, Android 16, default display. The tested OSS installation was
the debug variant, upgraded without clearing data. It had a separately installed
optional detector; task results therefore do not establish identical behavior for
an OCR-only fresh installation.

测试设备保留了用户自行安装的可选检测模型；不能把这组任务结果直接当成默认无 YOLO 包的效果。

| Check / 项目 | Observed result / 实际结果 |
| --- | --- |
| Phone-local GLM-5.3-flash transport | 3 text + 2 synthetic-image requests passed; 1.385–2.806 seconds, including droid.ask_vision |
| Background task → Home → app → Home | Overlay restored in both background transitions: 483 / 649 ms |
| WeChat with always-on enabled | Overlay remained visible through the nofloat launch path; no WeChat node-tree reads |
| Rotation 0° / 90° / 180° / 270° | Screenshot and display geometry agreed; stale and out-of-bounds coordinates were rejected |
| Fresh portrait/landscape gesture | Own-app input focused and keyboard appeared; no text submitted |
| Settings preservation | Rotation settings restored after testing; no ADB reverse transport used |
| Loop guard ladder (2026-10-26, `3fc9709`..`1c52a08`) | Repeated identical taps on a static screen: attempts 1–2 dispatched, 3/4/5 substituted by the guard with WAIT/BACK/HOME, 6–7 returned `aborted` without dispatch; repeated identical swipes were refused from attempt 5 with `repeated_no_effect`; a productive tap (diff 20.137%) cleared the guard. Driven from a PC-side gacore over the bus with `adb forward` |
| `dump_state()` degradation codes (2026-10-26, `f357556`) | Launcher tree: 13 nodes, `degraded=None`. WeChat: 0 nodes with `degraded={'reason':'sensitive_blank'}` while `dump()` still returned `[]` (contract unchanged). Game (SurfaceView): 1 non-interactive node, so `tree_empty` does not fire — low-information detection must use `clickable_count==0`/node-count thresholds, not emptiness alone |
| Sensitive-app guard posture (2026-10-26, review fixes) | With WeChat foreground, repeated failed pastes record `uncertain` and never start the input ladder; the tap ladder no longer substitutes BACK/HOME under a policy-sensitive foreground |

An earlier network probe observed a transient SSL EOF that recovered. A phone-local
proxy was configured for the tested provider. This does not establish stability
on every network. An actual ADB disconnection during a task did not stop the phone
session; the exact physical unplug interval was not measured.

此前出现过一次恢复后的 SSL EOF。无 USB 代理和一次断连继续运行，不等于所有网络均无超时。

## Representative task sample / 代表性任务

Eight original queries across six task families were attempted during candidate
iteration, with the same GLM model but evolving adapters/instructions. App history
was retained, so repeated runs were warm. The final overlay/geometry commit did
not receive a new full run of all eight queries.

| Task family / 任务 | Last attempt / 最后一次结果 | Limitation / 说明 |
| --- | --- | --- |
| System settings L1 | Passed | Verified final setting; restored original state |
| System settings L2 | Passed | Verified mode and value; restored original state |
| Bilibili L1 | Passed | GUI sort selection verified; filter drawer left open |
| Bilibili L2 | Partial | Date range broadened; combined duration selection not established |
| Used-goods search | Partial | Price ordering not established; accessory mistaken for the complete product |
| Meeting app | Blocked | Existing login expired; no login or meeting join |
| Route query | Passed | Route read back; matching history provided a warm-state advantage |
| Trending list | Partial | Pinned item confused with numbered rank |

Result: **4 passed, 3 partial, 1 blocked**. This is not a randomized A/B comparison,
a full benchmark, or evidence that a different historical model/version regressed.
Uninstrumented token fields must not be interpreted as zero use.

结果为4通过、3部分完成、1阻塞。保留失败，按实际状态而不是模型自述计分；
不同日期和模型的历史记录不能直接证明版本退化。

A separate WeChat mini-program task reached the phone-login boundary. Login was
deferred by the device owner; checkout, order submission and payment were not
completed. No full shopping-flow success is claimed.

## Meizu fresh-install follow-up / 魅族首次安装补充

**Date:** 2026-10-24. MEIZU 21, Android 16 / API 36, arm64, 1080 × 2340,
portrait. Release APK installed fresh at `4b33fb4`, then upgraded to `960edb1`
without clearing data; the separate closed-source package was preserved.
[CI for `960edb1`](https://github.com/shenhao-stu/GAgent/actions/runs/39996863082)
passed both jobs. Downloaded artifact hashes and inventories matched its source
and CI reports. No optional YOLO model, vision adapter or self-ADB was configured.

| Check / 项目 | Observed result / 实际结果 |
| --- | --- |
| Model setup / 模型配置 | Exact model ID saved without model discovery; GLM-5.3-flash, Anthropic protocol, proxy field empty |
| Text request / 文字请求 | Exact requested reply; UI duration 5 seconds |
| Upgrade / 覆盖升级 | Model, conversations and accessibility authorization retained; distinct GAgent OSS label visible |
| Unconfigured mesh / 未配置组网 | Initial startup error reproduced at 4b33fb4; not observed after 960edb1 upgrade |
| Background GUI / 后台 GUI | Settings launch, gestures and visible task overlay observed |
| Original navigation / 原始导航 | Did not reach the display page; stopped after 13 completed steps / 4:49 |
| Guided visual retry / 指引后视觉重试 | Screenshot/OCR with explicit small, slower gestures reached “显示和亮度”; independently checked by screenshot; 9 UI steps / 5:50 |
| Networking / 网络 | No ADB reverse or computer proxy configured; physical USB unplug not tested |

The successful retry used an explicit diagnostic prompt and warm Settings state.
It proves that this route can reach the page, **not fluent default navigation or
benchmark-wide accuracy**. The slower gestures moved through the list in smaller
increments; the earlier failure is retained. System settings were not changed.
Some initial permission state changed between observations, so this is not an
entirely unassisted setup. Microphone access was denied; voice was not tested.

魅族新装已跑通模型配置、文字回复和基本设备控制；保留原闭源版及数据。
原始导航失败，加入截图/OCR和小幅慢滑指引后到达目标，但耗时5分50秒，不能称为流畅。
这是带诊断指引、保留页面状态的重试，不是完整 benchmark。通知与文件权限部分状态可能有
机主协助；未实测物理拔线、语音、折叠屏或横屏。任务运行期间仅用被动截图观察，
UIAutomator 抑制无障碍的干扰另见 [Testing](TESTING.md#passive-observation)。

<a id="meizu-gui-regression"></a>

## Meizu GUI and overlay regression / 魅族 GUI 与浮窗回归

**Date:** 2026-10-24. MEIZU 21 / Android 16, portrait, GLM-5.3-flash
through the Anthropic-compatible endpoint. The release APK from `dd49e39`
matched its [passing CI artifact](https://github.com/shenhao-stu/GAgent/actions/runs/40029121947);
installed bytes and runtime guide/tool hashes were checked. The GA planning core
was unchanged. Changes belong to foreground identity, capture, gesture handling,
visual responses and the Android tool guide.

Each trial used a fresh conversation and an unchanged query. Accounts, search
history and unrelated agent memory were retained. Selected target processes
were stopped before the final trials; no data was cleared. Earlier compact-guide
trials used the `809f6c4` APK with exact `62679db` / `cb2fd3e` guide assets,
backups and hash checks. Their Bilibili run retained its page/search state and
restored an official App guide after an earlier failure had written incorrect
filter advice. The vision adapter was configured during iteration. No optional
YOLO detector or self-ADB was added; the provider proxy was empty and there was
no ADB reverse transport. These are host-observed completion intervals, not
statistically established speedups or a cold-start A/B experiment.

| Check / 项目 | Observed result / 实际结果 |
| --- | --- |
| Display-page navigation / 显示页 | `dd49e39`: **81–90 s, 8 turns**, passed; one recovered tuple/dictionary misuse. Same original query: baseline `c5f1bf7` 180–188 s; earlier compact-guide trial 37–46 s; `8e692d9` repeat 203–212 s after wrong-direction scrolling and a wrong-page detour. The fastest trial did not establish stable latency |
| Sound-page navigation / 声音页 | `dd49e39`: **54–63 s, 7 turns**, passed with no tool errors. The preceding `8e692d9` run took 45–54 s with one recovered package-list shape error; the earlier compact-guide run exceeded 240 s and exposed the overlay collision |
| Battery-page navigation / 电池页 | `5a254ff`: 144–153 s, 9 turns, passed. Control center was already open; the agent recovered through its visible Settings entry |
| Bilibili `v9_video_L1` | Latest `8e692d9` repeat: **partial, exceeded 240 s / 13 turns**. Sort selection was visually confirmed, but Back left the results page and caused a repeat search. An earlier compact-guide run passed in 208–217 s / 11 turns; its title was visually truncated and its extra claim of backgrounding the App was wrong. Earlier timeouts and a 583–592 s web fallback remain failed App trials |
| Idlefish / 闲鱼 `v9_used_L1` | `5a254ff`: blocked by login; no login or purchase |
| Meeting / 腾讯会议 `v9_meet_L1` | `5a254ff`: blocked by expired login; no login or meeting join |
| Two floating handles / 双浮窗 | Each retained App owned one: closed-source and OSS. Turned off the closed App's own always-on setting; one OSS overlay remained at Home, during tasks and after completion. Both installs, data and permissions preserved |

A separate native defect let an injected swipe drag GAgent's expanded capsule
while the Settings list stayed still. The capsule's movement produced 8.483%
pixel change, falsely counted as progress. Candidates `d8c9fab` and `0c1190b`
passed CI but failed physical collision checks; those failures are retained.
The fix keeps the overlay visible, temporarily passes gesture input through it,
waits for compositor commit where supported, then restores touch handling.
Overlapping gestures use leases so an older cancellation cannot unlock a newer gesture.

On the exact `8e692d9` APK, three normal-path top-boundary swipes left the capsule
stationary and returned `scrolled=False`; another swipe moved Settings while the
capsule stayed in place. Flags and opacity returned to their prior values, and a
manual click changed the capsule's display mode. No extra pre-held lease or
preparation delay was used. The final `dd49e39` keeps that native implementation
and adds `scroll_view`, which expresses the desired browsing direction while
preserving the legacy `scroll` finger-direction contract. Older Android and
software-rendering fallbacks were not physically exercised on this device.

The final local suite passed **267 tests and 10 subtests**; CI also passed Kotlin
tests and both APK builds. Seven literal prose-matching checks were retired during
guide cleanup; runtime guards for visual-only input, unresolved foregrounds,
clipboard verification and geometry remain. This is author verification, not
an independent security audit or a full AndroidDailyBench score.

显示页、声音页的标题由截图独立核验，未修改设置。最快一次不能代表稳定体验：B站复测仍超时，
闲鱼和腾讯会议受登录状态阻塞，均未算通过。双浮窗来自两个独立安装的 App，已关闭闭源版
的常驻浮窗；另一个“手势拖动自身浮窗”的缺陷在 Android 层修复。新滚动接口按浏览方向表达
意图，保留旧接口兼容，不包含机型、任务或固定坐标特例。

This remains a small engineering sample. Model direction/shape mistakes, stale
node choices and popup navigation still caused detours; floating status text can
also appear in OCR candidates. Broadly fluent operation is not established.
Physical unplug, landscape/foldables on this Meizu, voice and optional services
were not tested. Private screenshots/traces are not published; uninstrumented
zero token fields do not mean zero usage.

## 2026-10-25 integration candidate / 集成候选

MEIZU 21, Android 16, portrait 1080×2340, GLM-5.3-flash (Anthropic protocol), the
original queries, a fresh conversation per run, the target app force-stopped, a
fixed 240 s budget including model wait. Success requires `end=done` within budget,
no pending question, no settings change, and a checked answer: the device's real
page title for display/sound; for Bilibili the most-played order, full first title
and uploader checked against an independent on-device reading. Valid runs are all
reported. One batch was discarded because the app's accessibility service had been
turned off during another executor's device window (every task stopped to ask for
it), and one vision check was discarded because the model wrote a result without
running code. Arms are successive builds/settings, not single-variable trials;
three runs per task on one phone and one network.

在 MEIZU 21 上用原始指令、每轮新对话、目标 App 冷启动、240 秒固定预算（含模型等待）逐轮记录。
有效轮次全部列出；作废 1 个批次（另一执行者使用设备期间无障碍被关闭）和 1 次模型未执行代码就写出结果的看图核验。
各组是逐步叠加的构建与设置，不是单变量试验；每项 3 轮、单机单网络，不是基准成绩。

| Arm / 组 | display | sound | Bilibili |
| --- | --- | --- | --- |
| main 7bc0340 | 3/3, median 90.4 s | 3/3, median 76.1 s | 0/3 (all 240 s) |
| integration build with observe-only timing | 3/3, 92.2 s | 3/3, 61.5 s | 0/3 |
| + migrated `vision_api.py` without extended thinking | 3/3, 86.7 s | 3/3, 95.3 s | 1/3 |
| + reasoning effort `low` (composer setting) | 3/3, 40.3 s | 3/3, 56.9 s | 2/3; one failed run opened and played the video |
| + imported YOLO; effort still `low` in the saved provider* | 3/3, 47.0 s | 3/3, 54.0 s | 2/3 |

\* The composer showed “default”, but the saved provider kept `low` (reasoning
appeared in 1 of 85 requests, as in the `low` arm). The editor now removes the
level when “default” is chosen. YOLO's own effect is therefore not separated here.

- With default effort the main model reasoned on most turns (visible reasoning
  before text in 39/62 and 44/73 requests; first byte median about 7 s, 90th
  percentile 21–26 s, maximum 77 s). Vision calls inside tasks took 27.5–53.8 s
  before the template change and 6.6–13.9 s after it. On a synthetic image and a
  real screenshot, one measurement each changed from 44.2 s and 11.0 s to 2.0 s
  and 2.6 s with correct answers; the device's `vision_api.py` was migrated with a
  backup and its configuration names preserved.
- Bilibili timeouts combine model time with the app's own GUI: a self-drawn filter
  drawer absent from the node tree, back leaving the results page, and no confirm
  control. One `low`-effort run opened and played the first video. No
  app-specific workaround was added.
- Reasoning effort `low` is a user choice, not a default here: faster in these
  runs, but one run violated “do not play”.
- Original AndroidDaily items `v9_used_L1` and `v9_meet_L1` stopped at the apps'
  login pages and asked the user; recorded as blocked, not passed.
- The optional YOLO export imported through Settings, passed on-device validation
  and detected 5 icons and 24 text items in 5009 ms on its first run.
- The WebView back handler that the hardware Back calls closed one layer per press
  across 18 settings/sheet/dialog screens in in-page dark and light themes; the
  hardware Back key itself closed the detector before settings (one press needed a
  retry). The voice and PC Link setup guides opened their own fields without asking
  for the microphone. Landscape and the keyboard kept the focused field visible.
- Observed issues: a task that ends by asking the user shows the green “done”
  capsule; the capsule can cover a field label on GAgent's own pages; the phone's
  Wi-Fi dropped requests twice (`Errno 101`) and recovered.
- Model behavior to watch: GLM sometimes issued `code_run` without code and once
  wrote a fabricated execution result without calling a tool; judge runs by the
  recorded tool events, not by the reply text.

Not established in this round / 本轮未证明: App self-ADB offscreen (the phone required
re-pairing, a user step), optical QR pairing (needs a user-run relay and a PC QR), a
fresh install (the ROM requires on-device confirmation for new USB installs), the
overlay error state, YOLO's effect at default effort, foldables and other OEMs.
本轮未证明：App 自连 ADB 离屏（需用户重新配对）、光学扫码配对（需用户自建中继与电脑二维码）、
全新安装（系统要求在手机上确认 USB 安装）、浮窗出错态、默认推理强度下 YOLO 的单独效果、折叠屏与其他厂商。
结果摘要：display/sound 各组均 3/3；B站从 0/3 到 1/3（看图关推理）再到 2/3（推理强度 low，其中 1 次失败播放了视频）。

<a id="v2338"></a>
## 2.33.8 follow-up / 2.33.8 补充

Same MEIZU 21 (Android 16, WebView 155.0.8059.43). First the published 2.33.7 was
exercised end to end, then the release build of the fixes was installed over it
(same signature, data kept) and each fix was checked once.
同一台 MEIZU 21：先对已发布的 2.33.7 做整体回归，再覆盖安装修复后的 release 包逐项单次复核。

- Web tool: on 2.33.7 every web task's `open_url` timed out twice (about 21 s each)
  before the model fell back; the screenshot call waited for a new frame. With the fix
  `open_url` succeeded on the first call in 1.8 s and returned a screenshot.
  网页工具：2.33.7 每次先超时两次；修复后首次调用 1.8 s 成功并带截图。
- In the chat WebView a remote image in rendered Markdown raised an `img-src`
  violation and was not fetched; a local data image still rendered.
  回复中的远程图片被策略拦截未请求，本地图片照常显示。
- Starting the quick-record activity from outside the app (adb shell) is refused
  (“not exported”); the launcher shortcuts are now published for this package.
  外部无法再启动快捷录音入口；桌面快捷方式已正常发布。
- A task finished in the background produced one notification instead of two; after a
  restart the header and capsule show “待命”; the reply actions no longer include the
  placeholder translate button. 后台完成只发一条通知；重启后显示“待命”；不再显示未实现的翻译键。
- Also exercised without changes: a read-only Settings task (correct title, brightness
  unchanged), stopping a running task, language switching, settings pages, the
  composer sheets, copy, read-aloud and the share card.
  其余回归项（只读设置任务、停止、语言切换、设置页、输入框弹层、复制、朗读、分享图）正常。

Not established / 未证明: App self-ADB offscreen (needs the user to re-pair), optical
QR pairing in this app, a fresh install, foldables and other OEMs.
本次未证明：App 自连 ADB 离屏（需用户重新配对）、本 App 光学扫码配对、全新安装、折叠屏与其他厂商。

<a id="v2337"></a>
## 2.33.7 follow-up / 2.33.7 补充

Same MEIZU 21, release builds of the merged fixes installed over the existing app
(same signature, data kept), GLM-5.3-flash. Single checks, not trials.
同一台 MEIZU 21，覆盖安装合入后的 release 包（同签名、保留数据）；每项单次检查，不是成功率测试。

- Failed tasks: one task that hit HTTP 429 (provider quota) and one that could not
  reach the network through an unreachable proxy both showed “Error” on the capsule,
  “Error · N steps” in the status, a red cross on the reply header and a “Task
  failed” divider. The cross was still there after a cold start.
  额度用尽（429）和代理不可达两种失败都显示“出错”，冷启动后回复头 ✕ 保持。
- Reasoning effort: in a conversation created while effort was default, choosing
  “low” applied to its next task and choosing “default” cleared it again, without
  restarting the app. 推理强度在既有会话的下一次任务即生效，无需重启。
- A task that ended by asking showed “Reply needed · tap to answer” on the capsule
  until it was answered, then “Done”. 以提问结束时浮窗显示“需要你回复”，回答后变完成。
- Wireless ADB after the phone revoked GAgent's key (adbd answered with
  `CERTIFICATE_UNKNOWN`): `droid.adb_connect()` now says re-pairing is needed
  (it previously said wireless debugging might be off), and Settings shows
  “Re-pair needed” as soon as it opens. 手机撤销信任后，自连报错明确要求重新配对，设置页打开即显示“需重新配对”。

Not established / 未证明: App self-ADB offscreen (needs the user to re-pair),
optical QR pairing in this app, a fresh install, foldables and other OEMs.
本次未证明：App 自连 ADB 离屏（需用户重新配对）、本 App 光学扫码配对、全新安装、折叠屏与其他厂商。

## Not established / 尚未证明

- Physical foldable behavior, broader OEM coverage, external displays and 16 KB page-size coverage.
- Correct complex filtering or ranking across arbitrary third-party apps.
- Production acceptance of every optional service, microphone path or server deployment.
- Complete native dependency remediation or an independent security audit.
- Equivalent task results with every model, protocol, network or OCR-only installation.

Follow [Testing](TESTING.md) for new evidence and [Roadmap](ROADMAP.md) for the
remaining engineering priorities. Personal device traces and screenshots are not
distributed in this repository.
