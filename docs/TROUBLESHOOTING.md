# Troubleshooting / 排障

[Get started](GETTING_STARTED.md) · [Networking](NETWORK.md) · [Report a bug](../CONTRIBUTING.md)

Start by separating **transport**, **device observation**, **tool protocol** and
**task reasoning**. Preserve the original error and current state. Do not clear
app data, change several settings at once or repeat a possibly completed action.

先区分联网、设备观察、工具协议和任务理解四类问题；保留错误与当前状态，
不要通过清库或重复未知结果的动作来“试一试”。

## Model timeout or failed image request / 模型超时或图像请求失败

1. Check the exact installed package in the phone VPN's inclusion/exclusion list.
   Debug and release have different IDs.
2. Test a short text request and a synthetic image independently.
3. If a provider proxy is configured, verify its listener on the phone.
   A localhost address on the phone is not the development computer.
4. Check protocol, model capabilities and the existing visual adapter reference.
5. Keep TLS verification enabled and record the actual error category and time.

A lost USB/ADB control connection is not itself an API timeout. A network success
does not prove the model selected the correct GUI action. See [NETWORK.md](NETWORK.md)
for provider proxy and native-tool migration details.

## Overlay disappears / 悬浮窗消失

Check “display over other apps,” the task's running/waiting state and the
**always-on** preference. A live task should restore the overlay on background
transition when permission is granted. Always-on takes precedence over the
visual-only app auto-hide policy; when it is off, that auto-hide behavior remains.

先确认权限、任务是否仍运行、是否开启常开，再复测“任务运行 → Home → 回到 GA → Home”。
记录它是在普通桌面还是目标应用消失。仅看 Activity 不可见，不能判断服务已经停止。

If it still fails, report the source/version, OS/device, orientation, permission
and preference state, whether the task continued and the exact transition.
OEM background restrictions are a possible factor, not a diagnosis without evidence.

## Screenshot or coordinates fail / 截图或坐标失败

The current screenshot path requires API 30+ and an active accessibility service.
A protected surface can also reject screenshot capture. Do not bypass protected
content restrictions.

After rotation, resizing, a keyboard, dialog or navigation change, capture a new
observation. Do not scale old coordinates to “repair” a stale target.
Fresh `capture()` metadata can be passed to gestures; matching geometry is
necessary but not sufficient to prove the UI content is unchanged.
See [SCREEN_GEOMETRY.md](SCREEN_GEOMETRY.md).

## Wrong visual API or missing detections / 视觉入口误用或没有检测结果

- `look(conf=...)` accepts a numeric detector confidence, not a natural-language question.
- `ask_vision(image, prompt)` uses the configured visual adapter.
- OCR is bundled; YOLO is optional and not downloaded automatically.
- A model file's presence is not proof it loaded or predicted correctly.
- In WeChat, an unavailable node tree is intentional; use the visual-only path.

错误应指向明确的接口契约，不要靠猜测模块名、读取微信树或绕过策略来恢复。
可选模型的格式与安装验收见[OPTIONAL_YOLO.md](OPTIONAL_YOLO.md)。

## Tool ran, task is still wrong / 工具成功但任务不正确

Inspect the resulting selection, sort indicator, numbered rank or other state.
A tap acknowledgement, low price on one card or one matching date does not prove
that a filter was applied. Preserve the original query and distinguish partial
completion from success. Do not retry a send, purchase or other mutation before
checking whether it already happened.

## Install/update fails / 安装或升级失败

Check architecture, package ID, versionCode and signing certificate. The declared
API minimum does not guarantee every native dependency works on the device.
Do not assume 16 KB page-size compatibility without checking the actual package
and runtime. An unsigned release needs signing.

签名不匹配时保留原应用和数据，使用同一身份的更新包，或明确规划独立安装/迁移。
不要以卸载作为默认修复。

Bundled files refresh during startup after an update; wait for startup to finish
before comparing runtime hashes. User-generated visual adapters may need an
explicit migration and are not replaced by copying a new template alone.

## Optional module does not connect / 可选组件无法连接

The settings page configures a client; it does not deploy the server.
Confirm protocol, endpoint and scoped credentials against the deployed service.
A legacy relay requiring a shared application secret is not automatically
compatible with this distribution. Never “fix” it by embedding that secret in
the APK. See [OFFICIAL_MODULES.md](OFFICIAL_MODULES.md).

## Useful report / 有效报告

Include version/commit and variant, device/OS, initial state, minimal steps,
expected/actual result, and a short redacted error. Include protocol and model
when relevant, but not API keys or a full provider file. Screenshots should be
cropped/redacted before sharing; private chats, addresses and login screens do not
belong in public issues. Suspected vulnerabilities follow [SECURITY.md](../SECURITY.md).
