# Testing and evidence / 测试与证据

[Build](BUILD.md) · [Contributing](../CONTRIBUTING.md) · [Validation](VALIDATION.md)

Test behavior and fragile boundaries. A bug fix should have a failing regression
when a deterministic test is practical. Documentation and copy changes need
consistency and link checks, not artificial tests that restate the new text.

测试真实行为与易损边界。可确定复现的行为修复应先失败后通过；低影响文字修改不用制造镜像测试。
以下是检查选择指南，不代表每个 PR 都需要连接真实账号或设备。

## Select checks by change / 按变化选择验证

| Change / 变化 | Relevant evidence / 对应证据 |
| --- | --- |
| Documentation | Links and examples resolve; English/Chinese scope agrees; git diff --check; source audit |
| Provider or session behavior | Existing provider/config/session tools and focused Python regression |
| Optional module config | tests/test_service_boundaries.py, test_pclink_credentials.py, test_optional_modules_ui.py |
| Phone tool protocol | tests/test_phone_task_regressions.py and relevant existing tool tests |
| Screen or overlay behavior | tests/test_screen_geometry.py, Kotlin unit tests, affected real-device scenario |
| WebUI | Browser regression tests, JavaScript syntax, both languages and relevant viewport |
| Dependency or packaging | Source/archive scan, both APK audits, runtime inventory, license/provenance update |
| Signing, storage or upgrade | Same-identity upgrade acceptance and evidence that existing data is preserved |

## Local automated checks / 本地自动检查

Prepare the isolated environment and browser from [Build](BUILD.md).

~~~sh
git diff --check
python tools/audit_source.py
python -m pytest -q
python tools/test_mykey_writer.py
python tools/test_provider_selection.py
python tools/test_jev_ui.py
python tools/test_sess_registry.py
find app/src/main/assets/gacore/webui -name '*.js' -print0 | xargs -0 -n1 node --check
~~~

The `tools/test_*.py` commands above are explicit CI steps; do not assume
`pytest` alone covers them. Browser tests use Playwright and synthetic state.
The existing checks do not require a production model key.

Kotlin tests run with the Android toolchain. Prepare the mesh AAR and portable
wheels from [Build](BUILD.md) first; Android compilation consumes those inputs:

~~~sh
gradle :app:testDebugUnitTest --no-daemon
~~~

For a complete build, create the AAR and portable wheels first, then follow
[Build](BUILD.md). CI also scans every Git commit with redacted gitleaks and audits
the APKs; a local source scan alone is not the entire security gate.

## Device acceptance / 真机验收

Use a selected test device with the owner's permission. Preserve app data and
system settings. Test one active controller at a time. Do not run a destructive
reset script or automatically retry an action after its outcome becomes unknown.

| Scenario / 场景 | Evidence to record / 记录内容 |
| --- | --- |
| Text, tool and image request | Protocol, success/failure, elapsed time; no credentials or personal payloads |
| Background task → Home → app → Home | Task remains live, overlay state, permission and always-on setting |
| 0°, 90°, 180°, 270° rotation | Screenshot dimensions, rotation, stale-coordinate rejection, valid fresh gesture |
| Resize, keyboard or dialog | Fresh observation and target verification; identical dimensions alone are insufficient |
| Permission denied/revoked | Explicit capability error; no silent success |
| Upgrade | Package ID, source commit, certificate, installed APK digest and retained configuration |
| Cancellation or reconnect | No stale-session result or duplicate external action |

WeChat acceptance uses screenshots, visual tools and gestures only. Any test-only
CDP connection is limited to GAgent's own WebView, never a target app. Stop before
messages, purchases, account changes or other real-world effects unless the test's
owner has explicitly authorized them.

手机测试不能把 ADB 断连误记成模型超时，也不能把无 reverse 当作已实测拔线。
UI 布局可能受登录状态、历史记录、通知和语言影响，这些都需要记录。

## Report outcomes honestly / 结果口径

- Record the exact query, model/protocol, app/source version and initial state.
- Separate **passed**, **partial**, **failed** and **blocked** outcomes.
- Preserve failed attempts; a model's final answer is not independent verification.
- Distinguish cold and warm app state and disclose manual assistance.
- Record actual usage when available; an uninstrumented zero is not zero consumption.
- Keep private screenshots and traces out of Git; publish only minimized, redacted evidence.
- State what was not tested, including devices and services outside the run.

Historical runs with different models or dates cannot establish a version
regression. A small sample is not a benchmark-wide accuracy estimate. The current
evidence and open limits are in [Validation](VALIDATION.md).
