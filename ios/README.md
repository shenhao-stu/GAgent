# GAgent for iOS (`ios/`)

GAgent for iOS (**IOSAgent**) runs the GenericAgent Python core directly inside an iOS app (`WKWebView` + embedded CPython 3.13), paired with **Apple ReplayKit Screen Broadcast** for on-demand screen observation, **Apple Vision** for local bilingual OCR, and a pure-MIT **ESP32-S3 BLE/USB HID bridge** for hardware-level mouse and keyboard actions.

- User setup guide (English): [../docs/IOS_GETTING_STARTED.md](../docs/IOS_GETTING_STARTED.md)
- 用户完整上手指南（中文）：[../docs/IOS_GETTING_STARTED.zh-CN.md](../docs/IOS_GETTING_STARTED.zh-CN.md)

---

## 1. First-Principles Architecture

iOS isolates apps from inspecting other apps' UI hierarchies or injecting synthetic touch events. Rather than relying on private APIs, developer-disk tunnels, or desktop tethering, IOSAgent decomposes phone autonomy into orthogonal, auditable primitives:

1. **Signed On-Device Engine (`ios/deps/stage_runtime.py`, `ios/GAgent/PyRuntime.swift`)**
   - Embeds BeeWare `Python-Apple-support` (CPython 3.13) and executes the immutable `gacore` bundle inside the app process.
   - `ios_policy.py` enforces strict separation between immutable signed code (`Bundle.main/gacore`) and writable user workspace (`Application Support/ga/{temp,memory,uploads}`). `mykey.py` is parsed as AST literals only — never `import`ed or `exec`ed.
2. **Minimal Atomic Toolset (9 Tools Total)**
   - Local workspace & memory: `code_run`, `file_read`, `file_write`, `file_patch`, `ask_user`, `start_long_term_update`.
   - Device & cross-device:
     - `screen`: requests a fresh frame from the `GAgentBroadcast` ReplayKit extension over authenticated local Mach/Keychain IPC (`ReplayCapture`), runs on-device `Vision` OCR (`zh-Hans` + `en-US`), numbers text elements (Set-of-Mark), and issues a cryptographic/generational `frame_id`.
     - `hid`: sends calibrated relative-mouse gestures (`move`, `click`, `flick`, `press`, `release`, `scroll`) and keyboard actions (`type`, `key`, `stage_text`) over encrypted, bonded BLE GATT (`6e400001-a9e8-4b1b-9c39-6d6f8a3c0000`) to the ESP32-S3 HID bridge.
     - `pc_link`: optional WebSocket client to a user-paired desktop GenericAgent Hub (`ios/pc_link/`).
3. **1-Tap Auto-Calibration (`BoardKit/App/AutoCalibrator.swift`, `TouchCalibration.swift`)**
   - iOS applies non-linear pointer acceleration based on report step size. `Pointer.swift` moves one axis at a time with matched report tails, while `AutoCalibrator` clicks known mouse distances on a foreground `TouchProbe` overlay, fits per-axis least-squares lines, and verifies an independent check tap within `±1.5%` screen tolerance.
4. **Presence Surface (`ios/Presence/`)**
   - Displays live task steps, `ask_user` quick-reply choices, takeover/resume actions, and an emergency Stop button across the Dynamic Island, Lock Screen Live Activity, notifications, and in-app strip.

---

## 2. Directory Layout

| Path | Responsibility |
| --- | --- |
| `GAgent/` | App lifecycle (`GAgentApp.swift`), synchronous `WKUIDelegate` JS bridge (`ios_bridge.js`), `NativeKit`, CPython C bridge (`python_bridge.{h,m}`), UNIX shell dlopen bridge (`ShellBridge.m`), `BoardSetupView.swift`, `VoiceInput.swift` |
| `BoardKit/` | CoreBluetooth GATT client (`BoardLink`, `BoardCommands`), relative pointer & gesture kinematics (`Pointer`, `HIDService`), ReplayKit `ScreenService` + `Vision` OCR (`ScreenElements`), `AutoCalibrator`, `PhoneTakeover` (MIT, derived from ESP32 iPhone Agent) |
| `BoardKitTests/` | Unit & OCR fixture tests for `BoardKit` (`xcodebuild test -scheme BoardKitTests`) |
| `ReplayCapture/` & `ReplayCaptureHost/` & `BroadcastUpload/` | Authenticated IPC wire protocol and ReplayKit Broadcast Upload Extension (`GAgentBroadcast`) |
| `Presence/` | Standalone Swift Package (`PresenceCore`) + WidgetKit Live Activity / Dynamic Island extension + web strip |
| `firmware/` | Pure-MIT ESP32-S3 BLE/USB HID firmware (`hid_bridge/`) + `flash.sh` + host C/C++ ASan/UBSan unit tests (`firmware/tests/`) |
| `deps/` | On-demand dependency fetchers (`get_python.sh`, `get_shell.sh`), PEP 730 `.fwork` dylib signer (`process_dylibs.sh`), signed runtime stager (`stage_runtime.py`), and `signed-host.patch` |
| `py/` | `bootstrap_ios.py` (engine entrypoint) and `presence_snapshot.py` (read-only session state projector) |
| `pc_link/` | Desktop GenericAgent Hub launcher (`run_hub.py`) and optional `/model_settings` adapter (`pc_model_settings.py`) |
| `tests/` | Offline Python & Node/Playwright test suites verifying the staged signed runtime, bridge contract, security policy, and iOS WebUI |

---

## 3. Developer Commands

### Run Host Verification Suites (No Physical iPhone Required)

```bash
# 1. Source secret & endpoint audit
python3 tools/audit_source.py

# 2. ESP32-S3 HID firmware C/C++ host tests (ASan + UBSan)
make -C ios/firmware/tests && make -C ios/firmware/tests clean

# 3. Presence Swift Package + Python snapshot + WebUI strip tests
bash ios/Presence/test.sh

# 4. Signed iOS Python runtime, policy, and JS bridge contract suites
python3 ios/tests/run_all.py

# 5. iOS WebUI Node unit tests
for f in ios/tests/test_*.js; do node "$f"; done

# 6. Generate Xcode projects & run BoardKitTests on iOS Simulator
cd ios
xcodegen generate
xcodebuild test -project GAgent.xcodeproj -scheme BoardKitTests \
  -destination 'platform=iOS Simulator,name=iPhone 16' CODE_SIGNING_ALLOWED=NO
```

### Deploy to a Physical iPhone

```bash
# Full build (App + ReplayKit Broadcast Extension + Dynamic Island Presence Widget)
APPLE_TEAM_ID=YOUR_TEAM_ID bash ios/deploy_device.sh

# Free Personal Team build (skips the extra Widget extension if hitting the 3-App-ID weekly limit)
WITHOUT_WIDGETS=1 APPLE_TEAM_ID=YOUR_TEAM_ID bash ios/deploy_device.sh
```

`deploy_device.sh` automatically downloads BeeWare CPython 3.13 + `ios_system` into `ios/Vendor/` and `ios/Resources/` on first run, stages `Resources/gacore` via `deps/stage_runtime.py`, generates `GAgentWithPresence.xcodeproj`, signs with Xcode Automatic Signing, installs via `xcrun devicectl`, and launches the app.
