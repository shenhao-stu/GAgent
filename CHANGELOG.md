# Changelog / 变更记录

Entries describe repository candidates, not an assertion that every version was
publicly released. Exact artifacts and acceptance belong to their release records.

本页记录源码候选的变化，不表示各版本均已公开；制品与验收以对应发布记录为准。

## Unreleased / 未发布变更

## 2.34.0 / 143 — 2026-11-09 (source candidate / 源码候选)

- Sync upstream `db40dc6`: portrait PC scanner, clear failed scan callbacks, reject
  ambiguous or offline selected-PC routing, close group connections before forgetting
  a room, and keep cancellation bound to the initiating pointer.
  同步竖屏扫码及失败提示，阻止任务误发到其他电脑；取消动作绑定原手势。
- Replace standalone streaming voice settings with on-device Chinese/English
  hold-to-talk. Download a hash-verified model once, release to append to the draft,
  slide up or leave the foreground to cancel; never send automatically.
  使用离线中英文语音，删除独立在线语音配置；转写追加草稿，上滑或切后台取消。
  Native foreground/session synchronization also rejects delayed background starts.
  原生层同步前台状态与录音会话，拒绝迟到的后台启动。
- Upgrade CPython/Chaquopy, cryptography/OpenSSL, Paramiko, NumPy/OpenCV,
  inference and TLS dependencies. Build arm64 Python extensions from pinned source;
  check target linkage and update OpenCV's bundled libpng/zlib security fixes.
  升级原生依赖，固定源码校验值，校验 Android 链接并修复图像编解码依赖。
- Compact default memory and update untouched defaults during upgrades while
  preserving user edits. Keep GA's core unchanged and document edition differences.
  精简默认记忆，升级保留用户修改；核心不变，明确开闭源适配差异。
- Block nested content in the privileged WebView and fall back to plain text when
  sanitization fails. Retain explicit authenticated service configuration and WSS.
  限制特权页面嵌套内容，清理失败显示纯文本，保留服务鉴权与 WSS 边界。

OpenCV now includes the image-processing/OCR subset, not every desktop module.
See [native/voice acceptance and remaining limits](docs/VALIDATION.md#v2340).
OpenCV 为图像处理/OCR 子集；真机结果与剩余限制见验收记录。

## 2.33.9 / 142 — 2026-11-09 (source update / 源码更新)

- Adapt the latest upstream multi-computer PC Link, routing/reconnect, UI and device
  fixes while preserving OSS endpoint and authorization boundaries. Remove GA Plan,
  commercial account/billing bridges and hosted telemetry. See
  [the synchronization record](docs/UPSTREAM_SYNC.md).
  同步多电脑 PC Link、重连、界面和设备修复，保留开源鉴权边界；删除商业计费账户路径。

## 2.33.8 / 141 — 2026-10-25 (open-source prerelease / 开源预发布)

- Web tool: the foreground browser's screenshot no longer times out on Android WebView,
  so `open_url` works on the first try (on a MEIZU 21 every web task used to lose about
  45 s and two failed calls); a failed screenshot no longer discards an opened page.
  前台浏览器截图不再超时，网页任务不再先失败两次。
- Privacy: images in model replies are not fetched from the network (a prompt-injected
  reply could carry chat text in an image URL), and the quick-record activity is no
  longer exported, so other apps cannot make GAgent start the microphone. The launcher
  shortcuts now target this app. 回复中的远程图片不再自动加载；其他 App 不能再让 GAgent 开麦；
  桌面快捷方式改为指向本应用。
- A finished task posts one notification instead of two; idle shows “待命/Idle” instead
  of “idle”; “1 step” instead of “1 steps”; the placeholder translate button is hidden.
  完成只发一条通知；待命状态本地化；单数步数；隐藏未实现的翻译键。

## 2.33.7 / 140 — 2026-10-25 (open-source prerelease / 开源预发布)

- A task whose last model call failed (for example HTTP 429 when a provider quota runs
  out) is reported as “Error” on the floating capsule, in the task status and in the
  chat's end-of-task divider (“Task failed”), not as a green “Done”.
  末轮模型请求失败（如额度用尽返回 429）的任务在浮窗、状态和会话结尾都显示“出错”，不再显示绿色完成。
- Wireless ADB: when the phone no longer trusts GAgent's key, `droid.adb_connect()` now
  says re-pairing is needed instead of “wireless debugging may be off”, and Settings
  shows “Re-pair needed” as soon as it opens. 手机撤销信任时自连报错改为明确提示重新配对；
  设置页打开即刷新“需重新配对”状态。

## 2.33.6 / 139 — 2026-10-25 (open-source prerelease / 开源预发布)

- PC Link offers an explicit **Use the public GenericAgent relay** preset in Optional
  modules. It fills the form only after you confirm its note (the access value is the
  one already public in the GenericAgent desktop client and is not a password) and is
  used only after Save; there is still no default. PC Link 新增需确认的公共中继预设，不是默认值。
- Reasoning-effort and provider changes now reach every open conversation instead of
  only the first one. 推理强度等服务商变更会同步到所有会话。
- A task that ends by asking you shows “Reply needed” on the floating capsule instead
  of a green “Done”. 以提问结束的任务，浮窗显示“需要你回复”而不是绿色完成。
- Wireless ADB shows “Re-pair needed” when the phone no longer trusts GAgent's key.
  手机撤销无线调试信任后显示“需重新配对”。
- Troubleshooting explains that some OEMs turn accessibility off after a force stop
  and how to restore it automatically. 说明部分厂商强制停止后会关闭无障碍及自动恢复方法。

- PC Link no longer ships a build-injected relay default. CI stops writing
  `pclink_defaults.json`, the APK audit rejects that asset, and runtime ignores a
  stale copy from older builds; configure your own relay URL and credential in
  Optional modules. PC Link 不再在构建中注入默认中继凭据：CI 不写入、APK 审计拒绝该文件、
  运行时忽略旧版残留，请在可选组件填写自己的中继地址与凭据。
  Optional modules no longer claim a blank PC Link URL restores a default; an
  unconfigured PC Link tap opens its relay fields. 可选组件页去掉“清空恢复默认”的旧说明。
- System back closes only the topmost layer, ordered by the layers' own stacking:
  dialogs and the detector close before the page beneath, stacked sheets step back
  one level, and back on the first-run consent leaves the app instead of dismissing
  it (which left a blank window). Settings sub-pages open at the top and restore the
  parent position on back, with an interruptible enter that is instant under reduced
  motion; fading scrims no longer swallow taps. Scrims use one theme token (darker in
  dark mode) and a re-opened lower sheet is drawn on top. 系统返回只关最上层；首启同意页不再被返回关掉；
  设置子页还原父页位置，遵守减少动态效果；遮罩改用主题色值，暗色更深。
- PC Link reconnects that finish after unlinking, or during a new pairing, are
  discarded, and unlinking during a pending pairing cancels it, so an unpaired phone
  does not reconnect. 解除配对后或新配对期间迟到的重连会被丢弃，配对进行中解除会先取消配对。
- Choosing the default reasoning effort removes a previously saved level instead of
  keeping it while the UI shows the default. 推理强度切回默认时会真正清除已保存的档位。
- Streaming voice checks its configuration before asking for the microphone and
  opens the voice settings when unset. 语音未配置时不再先申请麦克风。
- A local bus start failure no longer stops the app from opening, and crash capture
  starts first. 本机总线启动失败不再导致应用打不开。
- Detector boxes are clipped to the observed screen. Main-model requests and
  observation hops record timing for slow-task attribution (observe-only).
  检测框限制在屏幕内；记录主模型请求与观察步骤耗时（只观察，不改行为）。

- The floating capsule and task-end notification no longer report a user-stopped
  or failed task as "✔ Done": the core now exposes an `end` reason
  (`done`/`stopped`/`error`) and the capsule shows "■ 已停止" (no alert) or a red
  "⚠ 出错". 悬浮胶囊不再把用户中止或出错的任务显示为「完成」。
- Rebuild optional-module settings (PC Link, mesh, GAnet, streaming voice, APK
  build service) as a themed settings page with labelled fields, status chips and
  inline errors; settings secondary text now meets WCAG AA in light and dark.
  可选组件设置改为统一主题的设置子页；设置页次要文字在浅/暗色下满足对比度要求。
- Configured provider rows show their model names in readable secondary text.
  服务商列表中的模型名改用可读的次要文字颜色。
- Placeholder hints (chat composer, drawer search, optional-module `wss://`
  examples and the saved-token hint) now meet WCAG AA; the contrast test checks
  `::placeholder` of empty fields. 输入框占位提示在浅/暗色下达到对比度要求。
- The floating capsule's transparency preference now fades only the capsule
  body; status text stays opaque (white with a dark halo when the body is too
  transparent), so "✔ 完成" stays readable at 30%. 悬浮胶囊透明度只淡化底色，文字保持可读，偏好值不变。
- Exclude GAgent's own overlay windows from `droid.shot()` frames so OCR, the UI
  detector and vision models no longer read the status capsule's text.
  截图抹平 GA 自身悬浮窗区域，避免 OCR/视觉模型读到自己的状态文字。
- Virtual display: refuse to move a task the user has in the foreground, reject
  points outside the display, require frames newer than the last input and write
  a trailing frame after motion stops (frame metadata includes size and PID).
  离屏虚拟屏：拒绝抢占用户前台同一 App、坐标越界拒绝、帧须新于最近输入并补尾帧。
- Agent guidance uses view-direction `scroll_view()` consistently and warns that
  `back()` may leave the page instead of closing an in-page drawer.
- Destroy the previous chat WebView when the system theme, locale or font size
  recreates the main screen, so stale pages stop polling in the background.
  系统深浅色等配置变更重建主界面时销毁旧 WebView，避免旧页面继续后台轮询。
- Document why YOLO weights stay user-installed and the permissive alternatives
  for a bundled detector. 说明 YOLO 不内置的原因及可再分发的替代路线。

- Fix virtual-display adapter import: load `os` before reading the installation's
  package identity; cover default and debug identities without device access.
- Present the public source preview with a sourced DeepSeek Android comparison,
  scoped core-size claims, memory/token guidance and optional workflow setup.

- Add the GAgent logo, redesigned bilingual landing pages, ecosystem/download
  navigation, practical case guides and evidence-linked development milestones.
- Add a complete capability setup matrix and importable service-profile example;
  clarify YOLO installation, visual-model setup and independent verification.
- Permit reviewed public website navigation in source docs while retaining
  credential, runtime-endpoint and APK/archive checks; add focused regressions.
- Rewrite English and Chinese READMEs around actual capabilities, setup and limits.
- Add first-run, development, testing, troubleshooting, validation and release guides.
- Define contribution/review requirements, bilingual PR and issue templates,
  project decisions and community conduct.
- Correct provider-settings copy: keys are stored locally and sent to the chosen
  provider for authentication.
- Document unresolved native dependencies, physical-device coverage and optional
  module/YOLO licensing boundaries without treating them as completed work.

## 2.33.3 / 136 — 2026-10-23 candidate

- Honor provider proxy configuration in visual requests and expose one lazy
  `droid.ask_vision` entry.
- Request correction for malformed text tool calls instead of silently ending;
  reject malformed mixed batches without partial execution.
- Observe active system panels correctly and expose slider bounds/current values.
- Validate visual detector arguments and clarify GUI selection/clipboard feedback.
- Bind gestures to explicit observed display geometry; reject stale or
  out-of-bounds coordinates, including same-size 180° rotation.
- Restore task overlays when the app moves to the background, honor always-on
  in visual-only apps and constrain overlay placement after display changes.

See [Validation](docs/VALIDATION.md): the representative task sample still has
partial and blocked outcomes. Real foldable/OEM coverage and native dependency
migration remain open.

## Earlier extraction / 早期剥离

The initial repository combined Android beta 2.33.0 / 133 with later PC Link
changes, starting a clean source history at 2.33.1 / 134. The 2.33.2 / 135 candidate
established the visual-only WeChat policy and optional detector guidance.
Mandatory commercial/account flows, bundled service authority and source
encryption were removed from this distribution; original attribution and necessary
Kotlin device code remain. See [Feature scope](docs/FEATURE_SCOPE.md) and
[Extraction review](docs/REVIEW.md).
