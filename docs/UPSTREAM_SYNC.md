# Android synchronization — 2026-11-09 / Android 同步记录

This update adapts the GAndroid main snapshot `db40dc6` into GAgent's own main
history. Private Git history, hosted credentials, billing services, telemetry and
account data are not imported. The open-source application keeps its own package
identity and optional service configuration.

本次把上游功能适配到开源宿主，未合并私有 Git 历史；保留独立包名、用户模型配置、
本地总线鉴权、可选组件开关和数据隐私边界。

## Edition differences / 两个版本的差异

| Area / 范围 | Open-source adaptation / 开源适配 |
| --- | --- |
| GA core | Seven tracked core files match the reference byte for byte; Android wiring stays in adapters / 7 个核心文件逐字节一致 |
| PC Link | Latest multi-computer, response ownership and reconnect fixes retained; explicit WSS configuration replaces official endpoint rewriting / 保留最新多电脑与响应归属修复，显式配置安全端点 |
| GAnet | Generic pairing and device transport retained; credentials and ownership are user-configured / 保留配对和设备传输，用户自行配置凭据 |
| Voice | Native offline hold-to-talk reused; independent streaming settings and transport removed; system TTS retained / 复用离线按住说话，删除独立在线配置，保留系统朗读 |
| Accounts and billing | GA Plan, commercial account bridges and managed quota synchronization removed; ordinary model providers remain / 删除商业账户计费路径，保留通用模型配置 |
| Device tools | Upstream tools retained with OSS geometry, frame freshness, local authorization and revoked-ADB-pairing safeguards / 保留设备能力及开源版边界修复 |
| Memory | Short defaults and focused references; upgrades preserve user edits / 精简默认记忆，升级保留用户改动 |
| Privacy and rendering | Hosted telemetry disabled; local capability tokens, separate HTML preview and fail-closed sanitization retained / 禁用托管遥测，隔离 HTML 预览，清理失败时显示纯文本 |
| Native dependencies | Rebuilt Android wheels and updated inference/TLS libraries; actual artifact and device evidence required / 重建原生依赖，以实包和真机结果验收 |

Source equality and adaptation review establish where behavior is implemented;
they do not prove every feature works on every device or network.

## Scope / 范围

- PC Link: portrait scanner with explicit close, launch-failure callback cleanup,
  multi-hub discovery, encoded session routing, hub selection, reconnect
  grace, foreground recovery and serialized pair/unpair cleanup. An explicitly
  selected offline hub fails without sending to another computer. Responses stay
  bound to the current socket, including the legacy one-to-one path. A named group
  destination cannot fall back to a legacy computer; ambiguous multiple-computer
  requests require explicit selection, including during reconnection.
- Optional PC Link configuration still requires an explicit WSS endpoint and
  credential. Group membership tracks credential changes and unpairing. Signed
  short-code and WebSocket requests reject redirects; errors omit signed URLs.
- Runtime: `ga_runtime/gacore/` contains the unmodified synchronized core;
  `kernel_adapter/` owns Android workspace/execution wiring. See the
  [core hashes](upstream-core.json). Process-global Python execution is serialized;
  hung tasks cannot overlap a new worker's cwd/stdout state.
- UI: incremental steps, bounded persistence, last-view restoration, independent
  settings failure boundaries and floating-window docking. Provider configuration
  remains explicit and configuration reload failures roll back disk/cache state.
- Device tools: visual observation by default, compact OCR results, bounded OCR
  caching and microbatching. Geometry, screenshot retry, frame ownership and input
  freshness safeguards from the open-source edition are retained. Offscreen launch
  does not guess foreground identity or force-stop apps; verify the observed result.
- GA Plan, billing/account commerce UI, managed-plan synchronization and prompt
  contribution toggles are removed. Generic provider access remains. Retired bridge
  commands fail locally instead of becoming model requests.
- Voice input now reuses the native offline recognizer and hold/cancel interaction.
  The independent streaming configuration and transport are removed. Public model
  downloads are HTTPS-only and hash-pinned; recognition audio stays on the phone.
- Default memory is reduced to a short index and task references. Upgrades replace
  untouched defaults and preserve user edits; baselines come from packaged assets.

## Public repository controls / 公网仓库防护

CI pins external Actions and the secret scanner to immutable revisions, uses a
read-only workflow token and removes checkout credentials. Release signing material
is available only on main/tag builds, never PR or feature-branch builds. The source
and APK audit covers nested runtime build directories and rejects linked content;
full Git history is scanned with redacted results. These checks cannot prove that
arbitrary data contains no secrets.

Credential-bearing service HTTP requests reject redirects. Offline model downloads
carry no credentials, remain on HTTPS and verify pinned hashes. PC Link has no
embedded signing authority and unconfigured services do not make requests.
This client does not implement server-side quota or billing enforcement.

## Evidence and limits / 验证与局限

Behavioral tests cover routing/connection ownership, cleanup races, revoked
configuration, redirect credential leaks, parser/unlink failure handling, settings
isolation, core execution and OCR equivalence. CI builds both Android variants,
runs native unit tests, audits APK contents and records source/checksums.
See the associated PR and successful main CI for observed results. Source tests
and compilation do not establish cross-network or physical-camera acceptance.
Existing native dependency findings remain tracked in [Dependency security](DEPENDENCY_SECURITY.md).
