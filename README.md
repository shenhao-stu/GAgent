<div align="center">
  <img src="docs/assets/gagent-logo.png" width="128" height="128" alt="GAgent — an open G loop with a blue action point">
  <h1>GAgent</h1>
  <p><strong>An agent that lives on your phone.</strong></p>
  <p>Python tools · visual phone use · reusable memory · your choice of model</p>
  <p><a href="README.zh-CN.md">简体中文</a> · <a href="#start">Quick start</a> · <a href="docs/CONFIGURATION.md">Enable capabilities</a> · <a href="docs/README.md">Docs</a></p>
  <p><a href="https://gaagent.ai/">Website</a> · <a href="https://app.gaagent.ai/">GA Mobile APK</a> · <a href="https://github.com/lsdefine/GenericAgent">GenericAgent</a> · <a href="https://androidbench.gaagent.ai/">AndroidBench</a></p>
</div>

[Apache-2.0](LICENSE) · Android 11+ for visual phone use · arm64-v8a · [Android lineage: June 13, 2026](docs/HISTORY.md)

GAgent brings the [GenericAgent](https://github.com/lsdefine/GenericAgent) execution
loop to Android. Ask for a task; it observes the screen, runs tools, checks the
result and can retain useful procedures. Python, files and memory run on the
phone. Inference uses your configured model endpoint. Everyday use needs no PC or USB.

> **Private pre-publication candidate · 2.33.3 / 136.** Public launch remains an
> owner decision. Use **this repository's builds** for this source. The GA Mobile
> download portal is a separate distribution; see the
> [download channel guide](docs/ECOSYSTEM.md).

## What makes it useful

| Observe | Act | Reuse |
| --- | --- | --- |
| Screenshots, bundled OCR, optional YOLO and a configured vision model | Python tools and native Android gestures, files, browser and device adapters | Conversations, local memory, reusable procedures and optional computer/service connections |

The planning loop stays small in responsibility. Device geometry, permissions,
provider protocols and remote services belong at explicit boundaries.
[Architecture →](docs/ARCHITECTURE.md)

<a id="cases"></a>
## Practical cases

Start with a visible, bounded result. These are summaries of recorded development
runs; the [case guide](docs/CASES.md) gives reusable prompts, setup and verification.

| Task | What happened | Evidence |
| --- | --- | --- |
| Adjust system brightness | Setting and mode read back; original settings restored after testing | [Passed](docs/CASES.md#settings) |
| Find videos on Bilibili | “Most played” selection and title/creator verified; complex combined filters remained partial | [Passed / partial](docs/CASES.md#video-search) |
| Read a route in Amap | Duration and distance read back without starting navigation; matching history helped | [Passed, warm state](docs/CASES.md#route) |
| Browse McDonald's in WeChat | Pure GUI reached a selected meal and the phone-login boundary; no checkout, order or payment | [Partial / login boundary](docs/CASES.md#wechat) |

Also try [local file workflows and computer handoff](docs/CASES.md#recipes).
Explore the broader [AndroidBench cases](https://androidbench.gaagent.ai/#traces)
and [methodology](https://androidbench.gaagent.ai/#method). Those studies have their
own devices, models and protocols; they are not a score for every GAgent build.

<a id="start"></a>
## Quick start

1. **Install.** Use an arm64-v8a Android 11 / API 30+ device. Get a verified APK from
   this repository's [Actions](https://github.com/shenhao-stu/GAgent/actions/workflows/android.yml)
   or [Releases](https://github.com/shenhao-stu/GAgent/releases), or [build it](docs/BUILD.md).
   Private artifacts require repository access. The manifest's API 24 minimum does
   not provide the full screenshot workflow on older Android versions.
2. **Connect your model.** Open **Settings → Providers & Models**. Add the provider's
   URL, your key and model; choose the matching protocol. Check text, tool calls
   and images separately. [Model and vision setup](docs/CONFIGURATION.md#models).
3. **Enable phone use.** Grant accessibility and overlay access. Turn on
   **Always-on floating window** if you want progress visible across apps.
   Grant other permissions when their tools need them.
4. **Try a small task.** “Open Settings and describe the current screen without
   changing anything.” Confirm the actual screen and test the stop control.

Release: `io.github.shenhaostu.gagent` · Debug: `io.github.shenhaostu.gagent.debug`.
They have separate data and coexist with the earlier app. Preserve existing data;
a signature mismatch needs an explicit migration, not an automatic uninstall.
[First-run guide](docs/GETTING_STARTED.md) · [Troubleshooting](docs/TROUBLESHOOTING.md)

<a id="capabilities"></a>
## Enable the capabilities you need

| Capability | How to enable it |
| --- | --- |
| Text, tools, memory, local files | Configure a tool-capable model; allow shared-file access when needed |
| Phone GUI + OCR | Accessibility + overlay permissions; OCR is bundled |
| Vision questions | Configure the local vision adapter with an image-capable provider; test a synthetic image |
| YOLO icon detection | Install a compatible ONNX under its model terms, restart, verify actual detections; [step-by-step](docs/OPTIONAL_YOLO.md) |
| Voice / PC Link / GAnet / APK builder | **Settings → Optional modules**; supply a compatible server and your own scoped credentials |
| GA Plan | Add it as a normal model provider with your own issued key |
| Scheduling, notifications, Feishu, sensing, wireless ADB, virtual displays, Jev | Follow the [capability checklist](docs/CONFIGURATION.md); prerequisites and limits differ |

There is no universal “enable everything” switch. The framework needs no mandatory
hosted login or subscription. Optional clients do not install their servers, and
client-held secrets cannot be made unextractable.
[Full configuration](docs/CONFIGURATION.md) · [Official modules](docs/OFFICIAL_MODULES.md)

<a id="roadmap-news"></a>
## Roadmap & News

The earliest verifiable Android implementation is **June 13, 2026**: the private
predecessor already contained the Python agent, device bridge and vision pipeline;
its same-day README recorded build and real-device checks. This is development
provenance, not the date of a public open-source launch.

| Date · UTC+8 | Milestone |
| --- | --- |
| **2026-10-23** | Private Apache-2.0 extraction; opt-in services; visual-only WeChat, network/overlay/rotation fixes and bounded Pixel acceptance |
| **2026-08-06 → 08-13** | PC Link/P2P client and recorded GAnet integration |
| **2026-07-15 → 07-18** | Scheduled agent tasks and native notification-triggered automation |
| **2026-06-27 → 07-03** | Local-change preservation, wireless ADB, in-app browser control and virtual-display adapters |
| **2026-06-24** | Android-specific YOLOv8n detector with 21 UI classes replaces the earlier detector |
| **2026-06-16** | Streaming voice input |
| **2026-06-13** | Android implementation and same-day build/device validation record |

[Milestones and source references](docs/HISTORY.md) · [Changelog](CHANGELOG.md)

Next priorities:

- **Release readiness:** supported Python/native dependencies, model redistribution rights and durable artifact provenance.
- **Device breadth:** real fold/unfold transitions, more OEMs, 16 KB page-size validation and background lifecycle tests.
- **Task reliability:** better filter/rank verification, repeatable comparisons and scoped optional-service onboarding.

[Roadmap and acceptance criteria →](docs/ROADMAP.md)

## Develop, contribute, verify

[Build](docs/BUILD.md) · [Architecture](docs/ARCHITECTURE.md) · [Development](docs/DEVELOPMENT.md) · [Testing](docs/TESTING.md) · [Contributing](CONTRIBUTING.md) · [PR requirements](.github/PULL_REQUEST_TEMPLATE.md)

Keep changes cohesive. Make variable inputs explicit, preserve invariants in small
testable functions, and isolate network/files/Android effects. Prefer adapter fixes
when the GA loop does not need to change. English and Chinese contributions are welcome.

Current physical evidence is **Pixel 10 / Android 16**. A successful tap is not task
completion; rotation tests do not prove every foldable or OEM works. See
[validation](docs/VALIDATION.md) and [open dependency findings](docs/DEPENDENCY_SECURITY.md).
Model requests can send task content, screenshots and tool output to your endpoint.
Generated code acts with your granted capabilities; this is not a hostile-code sandbox.
[Security and data flows](SECURITY.md).

## License & lineage

Project-owned code: [Apache-2.0](LICENSE). GAgent derives from **Liang Jiaqing and
contributors' GenericAgent / GAndroid**; attribution is retained in [NOTICE](NOTICE).
[Third-party libraries, models and fonts](THIRD_PARTY.md) keep their own terms.
YOLO weights are optional and not bundled. This repository distributes Android;
iOS and ESP32 development remain separate.

[Website](https://gaagent.ai/) · [Upstream framework](https://github.com/lsdefine/GenericAgent) · [Ecosystem & download channels](docs/ECOSYSTEM.md) · [Logo](docs/assets/README.md)
