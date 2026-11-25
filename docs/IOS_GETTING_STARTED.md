# GAgent for iOS — Getting Started & User Guidelines

[简体中文](IOS_GETTING_STARTED.zh-CN.md) · [iOS Architecture](../ios/README.md) · [Privacy Policy](../PRIVACY.md)

This guide walks you through setting up **GAgent for iOS (IOSAgent)** from scratch: flashing the ~$5 ESP32-S3 Bluetooth HID dongle, building and signing the app onto your iPhone with Xcode, configuring an HTTPS model provider, completing the 4-step iPhone Control setup, and using GAgent safely in daily tasks.

---

## 1. Prerequisites

| Item | Requirement |
| --- | --- |
| **iPhone** | iOS 17.0 or later (**iOS 18+** recommended for improved bilingual Chinese/English Vision OCR; **iOS 26+** enables system background task continuation when switching apps) |
| **Mac** | macOS 14+ (Apple Silicon or Intel) with **Xcode 16+** and Command Line Tools installed |
| **ESP32-S3 Board** | Any **ESP32-S3** development board with native USB (`USB-OTG` / TinyUSB) and 8 MB Flash / OPI PSRAM (e.g., **ESP32-S3-DevKitC-1 N8R8** or SuperMini ESP32-S3, ~$4–$6). Standard ESP32 / ESP32-C3 boards without TinyUSB HID support are **not** compatible with `flash.sh` defaults |
| **Power for ESP32-S3** | Any 5V USB wall charger, computer port, or portable power bank (the iPhone itself stays completely wireless) |
| **Apple Developer Account** | Paid Apple Developer Program ($99/yr, full Dynamic Island Live Activities + 1-year signing) **or** a free Apple ID Personal Team (`WITHOUT_WIDGETS=1`, ~7-day signing) |
| **Model API Key** | Any OpenAI-compatible (`/v1/chat/completions` or `/v1/responses`) or Anthropic-compatible (`/v1/messages`) **HTTPS** API endpoint; a **vision-capable model** is strongly recommended for GUI automation |

---

## 2. Step 1 — Flash the ESP32-S3 BLE HID Firmware

The firmware in [`ios/firmware/hid_bridge/`](../ios/firmware/hid_bridge/) is pure MIT-licensed C/C++ code that turns an ESP32-S3 into a composite **Bluetooth LE Mouse + Keyboard + Consumer Control** peripheral and an encrypted BLE GATT control service (`ESP32 Agent XXXX`).

1. **Install `arduino-cli` and `xcodegen` on your Mac:**
   ```bash
   brew install arduino-cli xcodegen
   ```
2. **Install the ESP32 3.3.x core and `NimBLE-Arduino` library:**
   ```bash
   arduino-cli core update-index
   arduino-cli core install esp32:esp32@3.3.0
   arduino-cli lib install "NimBLE-Arduino"
   ```
   *(Any `esp32:esp32` 3.3.x release works.)*
3. **Connect the ESP32-S3 to your Mac via a data-capable USB-C cable** (if your board has two USB-C ports labeled `USB` and `UART`, either works; the native `USB` port is recommended) and run:
   ```bash
   bash ios/firmware/flash.sh
   ```
   - To compile without flashing (for verifying toolchain setup): `bash ios/firmware/flash.sh --build-only`
   - If multiple serial devices are connected, pass the port explicitly: `bash ios/firmware/flash.sh /dev/cu.usbmodemXXXX`

Once flashing finishes, unplug the ESP32-S3 from your Mac if desired and plug it into any 5V USB power source near your iPhone.

---

## 3. Step 2 — Build, Sign & Install GAgent on Your iPhone

1. **Enable Developer Mode on your iPhone:**
   - Connect your iPhone to your Mac via USB and unlock it (tap **Trust This Computer** if prompted).
   - Open **iPhone Settings → Privacy & Security → Developer Mode**, turn it **ON**, restart the iPhone, and confirm when prompted.
2. **Sign in to Xcode & find your Team ID:**
   - Open **Xcode → Settings → Accounts** and sign in with your Apple ID.
   - Paid Developer teams show a 10-character **Team ID** (e.g., `AB12CD34EF`). If you are using a free Personal Team and do not see the 10-character ID directly, run:
     ```bash
     security find-identity -v -p codesigning
     ```
     The 10-character code in parentheses at the end of `"Apple Development: ... (XXXXXXXXXX)"` is your `APPLE_TEAM_ID` (or open `ios/GAgent.xcodeproj` once in Xcode → Signing & Capabilities → select your Personal Team and inspect `DEVELOPMENT_TEAM`).
3. **Run the one-command deployment script from the repository root:**
   ```bash
   APPLE_TEAM_ID=YOUR_TEAM_ID bash ios/deploy_device.sh
   ```
   **Using a Free Apple ID (Personal Team)?**
   Apple limits free Personal Teams to **3 newly registered App IDs per 7 days**. Full GAgent builds 3 targets (`GAgent`, `GAgentBroadcast`, and `GAgentPresence`). If Xcode reports a provisioning limit on the 3rd target, build without the extra WidgetKit extension:
   ```bash
   WITHOUT_WIDGETS=1 APPLE_TEAM_ID=YOUR_TEAM_ID bash ios/deploy_device.sh
   ```
   *(With `WITHOUT_WIDGETS=1`, ReplayKit screen capture, ESP32-S3 control, notifications, and the in-app status strip all work identically; only the Dynamic Island / Lock Screen widget extension is omitted. When a free certificate expires after 7 days, re-running the same command re-signs in place without deleting your conversations or settings.)*
4. **Trust your Developer Certificate (first install on Free Personal Team):**
   - On your iPhone, open **Settings → General → VPN & Device Management**, tap your Apple ID under **Developer App**, and tap **Trust**.

---

## 4. Step 3 — Configure Your Model Provider

1. Launch **GAgent** on your iPhone and open **Settings (gear icon) → Providers & Models → Add Provider**.
2. Choose the protocol matching your service:
   - **OpenAI Chat Completions** (`oai`, `/v1/chat/completions`)
   - **OpenAI Responses** (`oai`, API mode `responses`, `/v1/responses`)
   - **Anthropic Messages** (`claude`, `/v1/messages`)
3. Enter:
   - **Name**: e.g., `OpenAI`, `Anthropic`, `OpenRouter`, `DeepSeek`
   - **API Base URL**: **must start with `https://`** (plain `http://` or URLs containing embedded `user:pass@` or `?key=` query secrets are rejected by `ios_policy.py` for security)
   - **API Key**: stored locally inside your app sandbox (`mykey.py`)
   - **Default Model ID**: pick a vision-capable model (e.g., `gpt-4.1`, `claude-sonnet-4-20250514`, `gemini-2.5-pro`, `qwen-vl-max`) if you want GAgent to visually inspect icons and layouts beyond OCR text.
4. Tap **Test Connection** (optional) and **Save**.
5. **Local Proxy / VPN (Optional):** If you run a local proxy/VPN tunnel on your iPhone (such as Shadowrocket, Surge, Stash, or Clash), open **Settings → Devices & Connections** and toggle **Local Proxy** — GAgent inspects `CFNetworkCopySystemProxySettings()` and probes connectivity before routing model traffic through it.
6. **Data-Sharing Consent:** On your first prompt to a newly configured provider, GAgent displays a clear disclosure of what leaves the device (prompts, selected file excerpts, and screen frames/OCR during phone tasks). Tap **Agree** to authorize that provider; you can revoke consent anytime in **Settings → Storage & Data**.

---

## 5. Step 4 — Pair ESP32-S3, Enable AssistiveTouch, Share Screen & Calibrate

Open **Settings → iPhone Control (`iPhone 操作`)** in GAgent:

1. **Toggle ON “Allow GAgent to operate” (`允许 GAgent 操作`)** at the top of the sheet.
2. **Card 1 — Connect ESP32 (`连接 ESP32`):**
   - Ensure your ESP32-S3 is powered on nearby.
   - Tap **Scan Nearby Devices** (`查找附近设备`) and select **`ESP32 Agent XXXX`**. When iOS asks to pair over Bluetooth, tap **Pair** (this establishes LE Secure Connections bonding on the encrypted GATT channel).
3. **Card 2 — Enable Wireless Mouse & Keyboard (`启用无线键鼠`):**
   - Tap **Open System Settings** (or open iPhone **Settings** manually).
   - Go to **Accessibility → Touch → AssistiveTouch** and turn **AssistiveTouch ON**.
     > **Why is AssistiveTouch mandatory?** iOS only renders and dispatches Bluetooth mouse clicks when AssistiveTouch is enabled. Pairing the Bluetooth device alone is not enough!
   - Go to **Settings → Bluetooth** and verify **`ESP32 Agent XXXX`** shows **Connected** (if another entry appears under Other Devices for the HID profile, tap it to pair).
   - *(Recommended)* Under **Accessibility → Pointer Control**, keep standard pointer speed; if you ever change pointer tracking speed later, re-run Step 4 calibration once.
4. **Card 3 — Screen Sharing (`屏幕共享`):**
   - Tap the **Screen Broadcast button** inside Card 3, select **GAgent** (if not preselected), and tap **Start Broadcast** (`开始直播`).
   - Wait 1–2 seconds until the red broadcast indicator appears in your status bar / Dynamic Island and Card 3 shows a green checkmark (`正在共享 · 按需截图`).
5. **Card 4 — Calibrate Pointer (`校准指针`):**
   - Keep GAgent open in the foreground and **do not touch the screen** for ~8 seconds.
   - Tap **Start Auto Calibration** (`开始自动校准`).
   - A white calibration grid appears; GAgent homes the cursor to the top-left corner, clicks rough diagonal stops and 5 corner/center targets, fits per-axis linear mappings, and performs an independent verification click. Once verified (`偏差 ±0.x%`, `≤ 1.5%`), calibration is saved persistently for this board.

Tap **Done (`完成`)** at the top-right to return to chat!

---

## 6. Everyday Usage, Takeover & Safety Guidelines

### Verification Smoke Test
1. Send `Reply OK` — verifies model connectivity and consent.
2. Send `Use code_run to compute the first 10 Fibonacci numbers` — verifies the embedded CPython 3.13 sandbox.
3. Send `Open iPhone Settings, check the current Wi-Fi network name, and do not change any switch` — verifies ReplayKit `screen` capture, Vision OCR, and calibrated `hid` gestures.

### Dynamic Island, Lock Screen & Background Runs
- Keep **Continue After Switching Apps** (`切换 App 后继续`, iOS 26+) enabled in **iPhone Control → Run & Preview** so GAgent can keep operating while another app is in the foreground.
- On Dynamic Island devices (when built with default `project.presence.yml`), GAgent displays the current step on the island and Lock Screen. When the agent calls `ask_user`, tap the notification or Live Activity to pick an option or type your answer in place.

### Human Takeover & Sensitive Boundaries
- **Always handle sensitive steps yourself:** GAgent's system prompt and runtime guidelines instruct it never to submit payments, passwords, 2FA/SMS codes, biometric prompts, or destructive confirmations. Whenever a task reaches login or checkout, GAgent pauses and requests takeover (or you can tap **Pause / Take Over** yourself). Complete the step on your iPhone, then tap **Resume** (`继续任务`).
- **Emergency Stop:** Tap **Stop Task** (`停止任务`) in GAgent, on the Dynamic Island, or stop Screen Broadcast from Control Center at any moment. GAgent immediately halts queued BLE commands, releases any pressed mouse button or key on the ESP32-S3, and invalidates previous screen observations.

---

## 7. Optional: Connect to Your Computer (PC Link)

To control or collaborate with a desktop [GenericAgent](https://github.com/lsdefine/GenericAgent) instance from your iPhone:

1. Start your desktop GenericAgent Hub:
   ```bash
   python3 ios/pc_link/run_hub.py /path/to/GenericAgent/frontends/hub.py
   ```
2. In GAgent on iPhone, open **Settings → Optional Modules (`可选组件`)** to configure your WebSocket relay URL (or explicitly enable the public GenericAgent relay preset after reviewing its notice).
3. Open **Settings → Devices & Connections → PC Link**, scan the QR code shown by your desktop Hub (or enter the pairing code manually), and switch between **This iPhone (`本机`)** and **Computer (`电脑`)** anytime from the top bar.

---

## 8. Troubleshooting

| Symptom | Fix |
| --- | --- |
| **Calibration says “Clicks are not reaching the screen”** | Confirm **Settings → Accessibility → Touch → AssistiveTouch** is **ON**, and `ESP32 Agent XXXX` is **Connected** in **Settings → Bluetooth**. |
| **Pointer clicks slightly off target** | Did you change **Pointer Control → Tracking Speed** or screen zoom? Open **Settings → iPhone Control → Step 4 → Recalibrate**. |
| **`ESP32 Agent` fails to reconnect after re-flashing firmware** | Re-flashing with bond wipe changes the board's keys. In iPhone **Settings → Bluetooth**, tap `(i)` next to `ESP32 Agent XXXX` → **Forget This Device**, tap **Forget This Board** in GAgent's **Device Options & About**, and pair again. |
| **Xcode fails signing `GAgentPresence` on a free Apple ID** | Run `WITHOUT_WIDGETS=1 APPLE_TEAM_ID=YOUR_TEAM_ID bash ios/deploy_device.sh` to stay within Apple's 3-App-ID weekly Personal Team limit. |
| **Screen observation says “Start sharing the screen with GAgent”** | iOS stops ReplayKit broadcasts when the screen locks. Unlock the iPhone and tap the Broadcast button in **Settings → iPhone Control → Step 3** (or Control Center → long-press Screen Recording → GAgent). |
