# Development guide / 开发指南

[Architecture](ARCHITECTURE.md) · [Build](BUILD.md) · [Testing](TESTING.md) · [Contributing](../CONTRIBUTING.md)

## Find the owner of a change / 先确定职责归属

| Change / 修改目标 | First place to inspect / 首查位置 |
| --- | --- |
| Provider configuration or protocol selection | app/src/main/assets/gacore/provider_config.py, llmcore.py and existing provider adapters |
| Tool/session lifecycle | app/src/main/assets/gacore/android_entry.py, kernel_adapter/ |
| Phone observation or gesture | app/src/main/assets/gacore/droid.py; BusA11yService.kt, ScreenGeometry.kt |
| Overlay or background transition | MainActivity.kt, PermissionCoordinator.kt, OverlayPolicy.kt, FloatService.kt |
| Local device authentication | bus_auth.py, LocalBusAuth.kt |
| Optional service configuration | service_config.py; the owning client such as pclink.py or ganet.py |
| UI and translations | app/src/main/assets/gacore/webui/; assets/i18n.js |
| Runtime instructions | app/src/main/assets/gacore/memory/ |
| Packaged dependencies and notices | app/build.gradle, tsbridge/, tools/, third_party/ |
| Build and release verification | .github/workflows/android.yml |

Python paths without a prefix above are under `app/src/main/assets/gacore/`;
Kotlin paths are under `app/src/main/java/com/ljq/ga/`.

## Make the smallest coherent change / 做最小且完整的修改

1. Reproduce the behavior and separate transport, observation, tool protocol and
   task reasoning failures.
2. Write down the variable inputs and the invariant that failed.
3. Find the existing owning boundary; reuse its public entry point.
4. For a behavioral bug, make a focused test fail, then fix the cause.
5. Run the relevant checks and update documentation for changed behavior.

先明确“什么变了、什么不应变”，再改代码。不要通过扩大超时、循环重试或为每个 App 增加
硬编码分支，掩盖错误的坐标、协议、会话归属或完成判定。

A model answering incorrectly is not automatically a transport or runtime defect.
Preserve the original query and final-state evidence. If a tool contract is unclear,
improve its boundary and instructions before changing the planning loop.

## Phone tools / 手机工具

Use the existing `droid` facade. This harmless observation can run inside the
configured phone runtime:

~~~python
import droid

frame = droid.capture()
print(frame["screen"])  # Width, height and rotation for this observation.
~~~

For a gesture, derive the target from that frame and pass its `screen` value to
`tap` or `swipe`. See [Screen geometry](SCREEN_GEOMETRY.md) for the contract.
A scalar detector confidence belongs in `look(conf=...)`; a question about an
image belongs in `ask_vision(image, prompt)`.

Do not assume a phone resolution, orientation, density or fixed status-bar height.
On rotation, fold resize, keyboard appearance or navigation, observe again.
A dispatch acknowledgement is not a task outcome. Keep WeChat on the visual-only
route; accessibility gestures do not authorize reading its node tree.

不要把某一台 Pixel 的成功坐标写成通用逻辑。坐标转换与边界校验保持纯函数，
Android 层只负责读取当前状态、校验和派发。完成后核对真实结果。

## Optional integrations / 可选服务扩展

Use `service_config.py` for endpoint validation and explicit configuration.
Network calls belong in the client, not a parser or import side effect. A disabled
module must remain usable as “not configured” without requiring a hosted login.
Changing origin must not silently preserve credentials for the old origin.

Keep privileged vendor keys and issuance logic on a server. Client profiles are
data, not downloadable executable extensions. If a compatible server is absent,
document that limitation; do not add a shared default credential.

接入一个服务需要客户端协议、鉴权和失败行为的明确契约，不等于把服务端业务并入 GA 核心。
见[官方组件](OFFICIAL_MODULES.md)。

## Runtime assets and user data / 运行资产与用户数据

`AssetUnpacker.kt` refreshes bundled assets when the installed version/update
stamp changes. The WebUI directory is replaced. Files shipped by the APK can
overwrite their runtime copies; a changed file on a test phone is not a source
change and is not automatically included in the next build.

User-created files such as `mykey.py` and `memory/vision_api.py` are not bundled
credentials. Preserve them deliberately. The evolution backup is best-effort and
does not replace a user-controlled backup. A migration must state exactly which
files change and prove unrelated configuration survives.

升级会刷新随 APK 提供的资源，不要把整个 memory 目录都视为不会覆盖。
个人配置、会话、截图、日志和设备上演化出的代码不是提交材料；需要测试时使用合成样例。
禁止把生产配置复制进测试夹具。

## UI and documentation / 界面与文档

Keep English and Chinese strings consistent, including fallback text in HTML.
State the actual data flow: locally stored provider keys are still sent for
authentication. A masked field is not proof that a key is inaccessible on a
compromised device.

Update both READMEs when capabilities or limitations change. Put detailed recipes
in a guide and link them instead of duplicating commands across many pages.
Code, dependency manifests and CI are the sources of truth for technical claims.

## Before review / 提交审查前

Use [Testing](TESTING.md) to select checks. Include the trigger, before/after
behavior, evidence, compatibility impact and remaining uncertainty in the PR.
Avoid unrelated formatting, mass renames and dependency upgrades. A broad refactor
needs a concrete problem and migration path, not only a style preference.
