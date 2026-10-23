# Changelog / 变更记录

Entries describe repository candidates, not an assertion that every version was
publicly released. Exact artifacts and acceptance belong to their release records.

本页记录源码候选的变化，不表示各版本均已公开；制品与验收以对应发布记录为准。

## Unreleased / 未发布变更

- Fix virtual-display adapter import: load `os` before reading the installation's
  package identity; cover default and debug identities without device access.
- Present the public source preview with a sourced DeepSeek Android comparison,
  scoped core-size claims, memory/token guidance and optional workflow setup.

- Add the GAgent logo, redesigned bilingual landing pages, ecosystem/download
  navigation, practical case guides and evidence-linked development milestones.
- Add a complete capability setup matrix and importable service-profile example;
  clarify YOLO installation, visual-model setup and independent verification.
- Permit reviewed public website navigation in source docs while retaining
  credential, runtime-endpoint and APK/archive checks; add focused regressions.
- Rewrite English and Chinese READMEs around actual capabilities, setup and limits.
- Add first-run, development, testing, troubleshooting, validation and release guides.
- Define contribution/review requirements, bilingual PR and issue templates,
  project decisions and community conduct.
- Correct provider-settings copy: keys are stored locally and sent to the chosen
  provider for authentication.
- Document unresolved native dependencies, physical-device coverage and optional
  module/YOLO licensing boundaries without treating them as completed work.

## 2.33.3 / 136 — 2026-10-23 candidate

- Honor provider proxy configuration in visual requests and expose one lazy
  `droid.ask_vision` entry.
- Request correction for malformed text tool calls instead of silently ending;
  reject malformed mixed batches without partial execution.
- Observe active system panels correctly and expose slider bounds/current values.
- Validate visual detector arguments and clarify GUI selection/clipboard feedback.
- Bind gestures to explicit observed display geometry; reject stale or
  out-of-bounds coordinates, including same-size 180° rotation.
- Restore task overlays when the app moves to the background, honor always-on
  in visual-only apps and constrain overlay placement after display changes.

See [Validation](docs/VALIDATION.md): the representative task sample still has
partial and blocked outcomes. Real foldable/OEM coverage and native dependency
migration remain open.

## Earlier extraction / 早期剥离

The initial repository combined Android beta 2.33.0 / 133 with later PC Link
changes, starting a clean source history at 2.33.1 / 134. The 2.33.2 / 135 candidate
established the visual-only WeChat policy and optional detector guidance.
Mandatory commercial/account flows, bundled service authority and source
encryption were removed from this distribution; original attribution and necessary
Kotlin device code remain. See [Feature scope](docs/FEATURE_SCOPE.md) and
[Extraction review](docs/REVIEW.md).
