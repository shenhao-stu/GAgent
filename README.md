# GAgent

**A Python agent runtime on your Android phone, with native device tools and your choice of model provider.**

[简体中文](README.zh-CN.md) · [Get started](docs/GETTING_STARTED.md) · [Documentation](docs/README.md) · [Contribute](CONTRIBUTING.md)

GAgent turns a request into a loop of observation, tool use and verification. The
Python runtime, conversations, files and memory live on the phone. Model inference
runs at the endpoint you configure; screenshots and relevant tool results may be
sent there. Normal phone operation does not require a computer or USB connection.

> **Project status:** private pre-publication candidate. The Android baseline is
> 2.33.3 / 136. Real-device coverage and unresolved native dependency work are
> documented in [Validation](docs/VALIDATION.md) and
> [Dependency security](docs/DEPENDENCY_SECURITY.md). Repository visibility and
> public release timing remain owner decisions.

## What you can build with it

| Capability | How it works |
| --- | --- |
| Phone use | Observe the current screen, locate a target, act and check the result. Accessibility supports ordinary app tools; WeChat uses screenshots, OCR, optional visual detection and gestures without reading its node tree. |
| Local tools and memory | Run Python tools, work with files, retain conversation state and reuse instructions on the device. |
| Model choice | Configure your own provider URL, key and models. Existing adapters support multiple protocols, including native tool calls where the provider supports them. |
| Visual grounding | PaddleOCR is bundled. Compatible YOLO weights are an optional user installation, with a separate licensing review. |
| Optional connections | Configure PC Link/P2P, GAnet, streaming voice or an APK build service when a compatible server is available. |

There is no mandatory hosted account or subscription for the framework. GA Plan
can be used through a normal model-provider configuration. Server implementations,
production credentials and commercial payment flows are outside this repository.
See the [feature scope](docs/FEATURE_SCOPE.md) and
[official module boundaries](docs/OFFICIAL_MODULES.md).

## Start on a phone

1. Use an **arm64-v8a device with Android 11 / API 30 or newer** for the screenshot
   and gesture workflow. The manifest permits API 24+, but that does not mean full
   screenshot support on those older versions.
2. [Build an APK](docs/BUILD.md), or obtain a verified artifact from this
   repository's [Actions](https://github.com/shenhao-stu/GAgent/actions/workflows/android.yml)
   or [Releases](https://github.com/shenhao-stu/GAgent/releases) when available.
   Private artifacts require repository access.
3. Open **Settings → Providers & Models** and enter your own provider endpoint,
   credential and model. Check text, tool use and image support separately.
4. Grant accessibility and overlay permissions for phone use; grant microphone,
   files and other capabilities only when you use the corresponding tools.
5. Start with a small task such as “Open Settings and describe the visible screen
   without changing any settings.” Inspect the result before trying a longer task.

The [first-run guide](docs/GETTING_STARTED.md) covers installation identities,
permissions, model setup and a short acceptance checklist. For timeouts or a
missing overlay, start with [Troubleshooting](docs/TROUBLESHOOTING.md).

| Variant | Application ID |
| --- | --- |
| Release | `io.github.shenhaostu.gagent` |
| Debug | `io.github.shenhaostu.gagent.debug` |

These variants have separate data directories and coexist with the earlier app.
Keys, accounts and conversations are not silently migrated. A locally signed build
may not upgrade a maintainer-signed installation; do not clear data to work around
a signature mismatch.

## Know the boundaries

- **On-device execution is not offline inference.** Provider credentials are
  stored in app-private storage and sent to the selected service for authentication.
  Model requests may contain task text, images and tool output.
- **This is not a sandbox.** Generated Python and device actions can affect real
  files, applications and accounts within the permissions you grant.
- **Device support is evidence-based.** Current physical acceptance covers
  Pixel 10 / Android 16. Rotation and bounds checks do not establish compatibility
  with every foldable, OEM, external display or 16 KB page-size device.
- **Task completion requires evidence.** A successful API call or accepted tap is
  not proof that a sort, purchase flow or other multi-step task succeeded.
- **Optional models have their own terms.** YOLO weights are not bundled or
  automatically downloaded. See [installation and licensing](docs/OPTIONAL_YOLO.md).

Automatic hosted telemetry and prompt collection are disabled in this distribution.
Review [Security](SECURITY.md) for data flows, reporting and trust boundaries.

## Develop and contribute

The core design rule is to keep changing inputs at clear boundaries and encode
stable invariants in small, testable functions. Prefer device or service adapter
changes when the agent loop does not need to change.

| I want to… | Start here |
| --- | --- |
| Build and sign Android packages | [Build](docs/BUILD.md) |
| Understand the runtime and extension points | [Architecture](docs/ARCHITECTURE.md), [Development](docs/DEVELOPMENT.md) |
| Fix a bug and choose the right checks | [Testing](docs/TESTING.md) |
| Propose a change or submit a PR | [Contributing](CONTRIBUTING.md) |
| Review evidence or prepare a release | [Validation](docs/VALIDATION.md), [Releasing](docs/RELEASING.md) |
| Find current engineering priorities | [Roadmap](docs/ROADMAP.md) |

Contributions in English or Chinese are welcome. Keep a PR focused on one
behavioral change, include reproducible evidence and preserve third-party notices.
The [PR template](.github/PULL_REQUEST_TEMPLATE.md) lists the expected review
information.

## License and attribution

Project-owned code is licensed under [Apache-2.0](LICENSE). GAgent derives from
GenericAgent / GAndroid by **Liang Jiaqing and contributors**, whose notices are
retained in [NOTICE](NOTICE).

Libraries, model files and fonts retain their respective licenses; see
[THIRD_PARTY.md](THIRD_PARTY.md). The project license does not grant rights to
private service credentials, service trademarks or separately licensed weights.
This repository distributes Android; iOS and ESP32 work remains separate.
