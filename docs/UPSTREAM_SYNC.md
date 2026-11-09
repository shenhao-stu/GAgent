# Android synchronization — 2026-11-09 / Android 同步记录

This update adapts the GAndroid main snapshot `eae6e54` into GAgent's own main
history. Private Git history, hosted credentials, billing services, telemetry and
account data are not imported. The open-source application keeps its own package
identity and optional service configuration.

本次把上游功能适配到开源宿主，未合并私有 Git 历史；保留独立包名、用户模型配置、
本地总线鉴权、可选组件开关和数据隐私边界。

## Scope / 范围

- PC Link: multi-hub discovery, encoded session routing, hub selection, reconnect
  grace, foreground recovery and serialized pair/unpair cleanup. An explicitly
  selected offline hub fails without sending to another computer. Responses stay
  bound to the current socket, including the legacy one-to-one path.
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
- Streaming voice remains the explicitly configured open-source service adapter;
  the hosted offline-ASR package is not included in this synchronization.

## Public repository controls / 公网仓库防护

CI pins external Actions and the secret scanner to immutable revisions, uses a
read-only workflow token and removes checkout credentials. Release signing material
is available only on main/tag builds, never PR or feature-branch builds. The source
and APK audit covers nested runtime build directories and rejects linked content;
full Git history is scanned with redacted results. These checks cannot prove that
arbitrary data contains no secrets.

Service HTTP requests and voice WebSockets reject redirects. PC Link has no
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
