<div align="center">
  <img src="docs/assets/gagent-logo.png" width="128" height="128" alt="GAgent — an open G loop with a blue action point">
  <h1>GAgent: A Self-Evolving Agent in Your Pocket</h1>
  <p><strong>See your screen. Use your tools. Remember what works.</strong></p>
  <p>🧠 GenericAgent core · 👁️ Local vision · 📱 Self-ADB · 🌐 Connected devices</p>
  <p><a href="README.zh-CN.md">简体中文</a> · <a href="#start">Quick start</a> · <a href="docs/CONFIGURATION.md">Enable capabilities</a> · <a href="docs/README.md">Docs</a></p>
  <p><a href="https://gaagent.ai/">Website</a> · <a href="https://app.gaagent.ai/">GA Mobile APK</a> · <a href="https://github.com/lsdefine/GenericAgent">GenericAgent</a> · <a href="https://androidbench.gaagent.ai/">AndroidBench</a></p>
</div>

[Apache-2.0](LICENSE) · Android 11+ for visual phone use · arm64-v8a · [Development since June 13, 2026](docs/HISTORY.md)

**GAgent brings GenericAgent's minimal, self-evolving autonomous-agent design to Android.**
Give it a goal: it can observe the screen, write and execute Python, work with files
and websites, connect to your computer, and turn verified experience into reusable
procedures. The agent and tools run on your phone; you choose the model endpoint.
Everyday use needs no PC or USB.

<a id="start"></a>
## 🚀 Install → configure → run

**You need:** an **arm64 Android 11+ phone**, internet access, and your own model
provider's **API URL, key and model ID**. Python and the phone tools are inside the
APK. No computer, root, Shizuku, Docker or separate Python installation is needed
for ordinary use.

1. **📦 Get the open-source APK.** Download **GAgent-release.apk** and `SHA256SUMS`
   from the latest [prerelease](https://github.com/shenhao-stu/GAgent/releases) (no
   sign-in needed) and check the hash. Newer builds are CI artifacts from
   [Android builds](https://github.com/shenhao-stu/GAgent/actions/workflows/android.yml?query=branch%3Amain)
   (sign in, pick a green **main** run, extract **GAgent-android-…**). [Download, checksums and installation →](docs/GETTING_STARTED.md#download)
2. **🔑 Add your model.** Open **Settings → Providers & Models → Add provider**.
   Select the matching protocol and enter the URL, key and **Default model ID**;
   tap **Save**. Fetching a model list is optional. Leave Proxy empty unless needed.
3. **📱 Enable phone use.** Open **Settings → Accessibility** and enable GAgent in
   Android's settings. Turn on **Always-on floating window** and allow overlay
   access to keep task progress visible. [Permission walkthrough →](docs/GETTING_STARTED.md#permissions)
4. **✅ Check one task.** First send “Reply OK”; then try “Open Settings without
   changing anything.” For image understanding, use the [vision setup prompt](docs/CONFIGURATION.md#models),
   then ask it to describe that screen. Text, tool use and vision are separate checks.

**Prefer your agent to handle setup?** Paste this into **GenericAgent, Codex or Claude Code**:

```text
Help me install and configure the open-source GAgent using this guide:
https://github.com/shenhao-stu/GAgent/blob/main/docs/INSTALL_WITH_AGENT.md
Inspect my OS, existing tools and chosen Android device. Prefer a verified APK;
resolve only the dependencies needed for that path. Preserve existing apps/data,
keep credentials out of chat/logs, and guide me through manual Android permissions.
Verify text, a harmless tool action and vision separately; report anything untested.
```

[📖 Step-by-step installation](docs/GETTING_STARTED.md) · [🤖 Agent setup guide](docs/INSTALL_WITH_AGENT.md) ·
[🔧 Build from source](docs/BUILD.md) · [🩺 Troubleshooting](docs/TROUBLESHOOTING.md)

> **Open-source preview.** Releases are prereleases, not a stable channel; CI
> artifacts require GitHub sign-in and expire after 14 days. Preserve existing apps and data: release
> (`io.github.shenhaostu.gagent`) and debug (`io.github.shenhaostu.gagent.debug`) have
> separate identities. [app.gaagent.ai](https://app.gaagent.ai/) distributes the
> separate official mobile edition. [Native dependency migration](docs/DEPENDENCY_SECURITY.md)
> and broader device acceptance remain open.

The foundation is [GenericAgent's **~3K-line seed core**](https://github.com/lsdefine/GenericAgent):
a compact execution loop, a small tool vocabulary and layered memory. Android
capabilities sit around that core. The figure describes the upstream seed, **not
the entire APK or Android codebase**. [Core, memory and counting scope →](docs/CORE_AND_MEMORY.md)

## ✨ What GAgent brings together

| Capability | What you can do |
| --- | --- |
| 🧠 **Memory that becomes a tool** | Keep a small index, recall relevant facts and procedures on demand, and reuse verified solutions across sessions. |
| 👁️ **Local OCR + YOLOv8n** | Read text and locate 21 classes of Android UI controls locally; ask an image-capable model when semantic understanding is needed. Locally built APKs bundle the detector; repository builds install it from the [guide](docs/OPTIONAL_YOLO.md). |
| 📱 **Self-ADB, without a Shizuku app** | Pair with Android's own wireless debugging to gain authorized shell capabilities. Ordinary GUI use needs accessibility, not ADB; advanced setup stays explicit. |
| 🪟 **Offscreen apps and web tasks** | Move supported apps to a virtual display, or run a separate background WebView. App virtual displays require self-ADB and device verification. |
| 🌐 **A browser that keeps your session** | Sign in yourself, then let the task browser reuse the stored cookies. It uses Android WebView, with no separate desktop-browser binary to install. |
| 🔗 **PC Link / P2P / GAnet** | Connect a phone to paired computers and authorized peers for cross-device work. Compatible peer software, services and your credentials are required. |
| 🎙️ **Step Voice streaming input** | Speak a task and review the transcript. The client supports the Step ASR streaming path through a configured compatible WSS service. |
| 🛠️ **APK Factory** | Describe a small app, generate its project, then submit, track and fetch its APK through your configured build service. Templates and clients are included. |

**Local tools are ready to configure; hosted integrations are opt-in.** PC Link has no default relay: enter the relay you run or are authorized to use, or tap the explicit public GenericAgent relay preset and review its note, then scan the computer QR to pair. Voice and APK Factory do not include service credentials or build workers. [All setup steps](docs/CONFIGURATION.md) · [Component boundaries](docs/OFFICIAL_MODULES.md)

## 🧠 A small core, useful memory, less repeated context

GAgent carries the **same GenericAgent lineage and core architecture**, with
Android adapters for device operations. Its memory loop is straightforward:

**Observe → act → verify → save the useful procedure → recall it when needed.**

- **Recall selectively.** A short memory index points to facts, procedures and
  scripts; the full library need not be inserted into every model request.
- **Keep working state compact.** Checkpoints, short summaries and context trimming
  preserve relevant progress while reducing repeated history.
- **Grow capabilities through use.** Verified procedures and local Python tools can
  become part of the next task. Review learned material; a failed attempt is not a fact.

This is how GAgent pursues token efficiency. Actual token use depends on the model,
task, screenshots and retries. Measure those inputs on your own tasks. [Implementation and measurement](docs/CORE_AND_MEMORY.md)

## 🧪 Practical things to try

| Try asking | Setup / recorded result |
| --- | --- |
| “Find videos on my topic, sort by most played, and list titles and creators.” | Simple-sort passes and a later Meizu timeout are recorded; combined date/duration filters remained partial. |
| “Read the driving time and distance; don't start navigation.” | Recorded Amap route readback passed with matching history available. |
| “Browse McDonald's in WeChat using GUI only; stop before submitting and at any login.” | Reached meal selection and phone login; no confirmed cart, checkout or payment. |
| “Use my signed-in website in the background and save a summary.” | Recipe: sign in through GAgent's browser; verify session reuse and saved output. |
| “Read a test folder on my paired computer and summarize its filenames.” | Recipe: configured PC Link and an authorized peer; start read-only. |
| “Make me a study timer app with a task list and local history.” | Recipe: generate/review the project, configure APK Factory, then test the returned APK. |

Recipes are examples, not new test results. See [cases and evidence](docs/CASES.md)
and [AndroidBench](https://androidbench.gaagent.ai/). [Physical validation](docs/VALIDATION.md)
covers Pixel 10 and MEIZU 21 on Android 16, including failed and blocked trials;
foldables and other OEMs still need their own acceptance.

## 🗺️ Roadmap & News

| Date · UTC+8 | Milestone |
| --- | --- |
| **2026-10-23** | Apache-2.0 source preview; opt-in services, visual-only WeChat, network/overlay/geometry fixes and public setup guides |
| **2026-08-06 → 08-13** | PC Link/P2P client and recorded GAnet integration |
| **2026-07-15 → 07-18** | Scheduling and native notification triggers |
| **2026-06-27 → 07-03** | Local-change preservation, self-ADB, browser control and virtual-display adapters |
| **2026-06-24** | Android-specific YOLOv8n with 21 UI classes replaces the earlier detector |
| **2026-06-16** | Streaming voice input |
| **2026-06-13** | Earliest verifiable Android implementation and same-day build/device report |

The June record comes from the private predecessor, not a public-launch claim.
[History and source references](docs/HISTORY.md) · [Changelog](CHANGELOG.md)

Next: 🔧 supported native dependencies · 📐 fold/unfold and more OEMs ·
🎯 reliable filter/rank verification · 🔌 easier scoped-service onboarding.
[Roadmap and acceptance criteria](docs/ROADMAP.md)

## 🤝 Build with us

[Build](docs/BUILD.md) · [Architecture](docs/ARCHITECTURE.md) · [Development](docs/DEVELOPMENT.md) · [Testing](docs/TESTING.md) · [Contributing](CONTRIBUTING.md) · [PR checklist](.github/PULL_REQUEST_TEMPLATE.md)

Keep the core small, make variable inputs explicit, preserve invariants in testable
functions, and isolate device/network effects. English and Chinese contributions
are welcome. Model requests may include task text, screenshots and tool output;
generated code uses your granted capabilities. [Security and data flows](SECURITY.md)

## 📄 License & lineage

Project-owned code: [Apache-2.0](LICENSE). Built on **Liang Jiaqing and contributors'
GenericAgent / GAndroid**; attribution remains in [NOTICE](NOTICE).
[Third-party libraries, fonts and models](THIRD_PARTY.md) retain their own terms.
YOLO weights are gitignored: locally built APKs bundle them, while repository and CI builds install the detector separately (license notice in the guide). iOS and ESP32 development remain separate.

[Website](https://gaagent.ai/) · [GA Mobile](https://app.gaagent.ai/) · [GenericAgent](https://github.com/lsdefine/GenericAgent) · [AndroidBench](https://androidbench.gaagent.ai/) · [Logo](docs/assets/README.md)

Settings → Local icon detection now imports and validates a user-supplied compatible ONNX model without a provider key, and can test a real screenshot. Optional detector weights remain separately supplied; see [setup](docs/OPTIONAL_YOLO.md).
