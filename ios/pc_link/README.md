# PC Link on iOS

iOS uses the same Group / HubUnion WebSocket protocol as Android: QR/manual pairing, automatic reconnection, computer selection, independent GA sessions, streaming replies, model selection, interruption, and local pin/archive/search controls. A selected `peer@hub` never silently falls back to another hub.

Run an existing desktop Hub with its installed Python environment:

```sh
python3 ios/pc_link/run_hub.py /path/to/GenericAgent/frontends/hub.py
```

An optional `--package-dir` points to existing, ABI-compatible `site-packages`.

Checks: `ios/tests/test_pc_hub_routing.py`, `ios/tests/test_pclink_browser.cjs`, and the shared `apk_factory/tests/test_pclink_*.py` suites.

## State ownership

- `selectionGen` belongs to user navigation; normal message polling cannot cancel create/send receipts.
- `gen` belongs to rendered message revisions and rejects stale message/segment results.
- During session creation, polling cannot auto-select another peer. Every destination keeps its full `peer@hub` identity; independent phone sessions keep separate pin/archive state.

## Computer model controls

The WebUI provides hold-to-talk dictation and an index-based `/llms` / `/llm` channel picker, and optionally uses `/model_settings` when supported by the desktop Hub for structured profiles and reasoning effort. A Hub without `/model_settings` keeps its existing channel picker and computer-configured reasoning.

The optional desktop adapter is `pc_model_settings.py`. To add it to a matching GenericAgent checkout, review and apply `model-settings-hub.patch` (`git apply --check` first), copy `pc_model_settings.py` to `frontends/pc_model_settings.py`, and restart the Hub.

Only computer-configured profile names are offered. Secret URLs, API keys, and local histories never leave the computer through this endpoint. Changes apply only to the current GA session, never `mykey.py`.
