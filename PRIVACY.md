# Privacy Policy

GAgent is an open-source mobile agent runtime for Android and iOS. The project does not operate a mandatory cloud service, collect analytics or telemetry, or upload your conversations, screenshots, API keys, or files to any project-operated server.

## 1. Local-First Storage

- Conversations, generated files, memory notes (`memory/`), temporary workspaces (`temp/`), pointer calibration (`BoardKit/calibration.json`), and provider configurations (`mykey.py`) are stored locally inside the app's private sandbox on your device.
- No account registration is required to use GAgent.

## 2. User-Configured Model Providers

- Model requests are sent **only** to the API endpoints (`apibase`) that you explicitly configure in Settings (OpenAI Chat Completions, OpenAI Responses, or Anthropic Messages over HTTPS).
- On iOS, outbound model requests require HTTPS with valid TLS certificates (`verify=True`, `allow_redirects=False`) and explicit per-provider data-sharing consent before any prompt, file excerpt, or screen image/OCR text leaves the device.
- When you send a task or run a phone-control turn, your prompt, conversation context, and (when visual observation is active) captured screen frames or on-device OCR text are transmitted directly to your chosen model provider under that provider's own privacy terms.

## 3. Screen Observation & Hardware Input

- **iOS**: Screen frames are captured on demand only while you actively run an iOS ReplayKit Screen Broadcast session (`GAgentBroadcast`) and keep phone-control authorization enabled. On-device OCR runs locally via Apple's `Vision` framework. Pointer and keyboard actions are sent locally over encrypted Bluetooth Low Energy to your paired ESP32-S3 HID bridge.
- **Android**: Screen observation and gestures run locally through Android Accessibility Service (or user-granted Shizuku/ADB shell permissions) only when enabled by you.
- Sensitive steps such as payments, passwords, 2FA codes, biometric prompts, and system permission dialogs must be completed by you personally using the takeover / pause controls.

## 4. Optional Microphone, Camera, Photos & PC Link

- **Hold-to-Talk Dictation**: On iOS, hold-to-talk speech recognition uses Apple's on-device `SFSpeechRecognizer` (`requiresOnDeviceRecognition = true`); audio is not uploaded by GAgent. On Android, offline ASR uses local `sherpa-onnx` models on the device.
- **Camera & Photos**: Used only when you attach an image, scan a pairing QR code, or explicitly save/share an output image.
- **PC Link**: Only connects to a desktop GenericAgent Hub or relay URL that you explicitly pair via QR code or manual configuration.

## 5. Deleting Data & Revoking Consent

- You can revoke data-sharing consent, disable phone-control consent, unpair your ESP32-S3 board or PC Link hub, clear temporary screen captures, or delete conversations and provider keys at any time inside Settings, or remove all local state by uninstalling the app.
