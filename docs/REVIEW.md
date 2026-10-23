# Extraction review / 剥离审查

This file records the initial extraction boundary. It is not the latest device
acceptance record; see [Validation](VALIDATION.md) for the dated 2.33.3 snapshot
and [Contributing](../CONTRIBUTING.md) for current PR review requirements.

本页保留初始剥离审查的范围；当前实机证据和贡献审查要求分别见上述文档。

Scope: Android beta 2.33.0 / 133 plus later PC Link changes from the former main,
released as candidate 2.33.1 / 134. A fresh Git repository excludes private history.
This is the implementation author's review, not an independent security audit.

Changes remove bundled service authority, mandatory account/payment UI, telemetry,
prompt collection, source-encryption keys and the old release identity. Official
services remain optional through explicit adapters. Root signing authority is not
transferred to clients. The old AGPL-derived YOLO weights are excluded.

Review follows cohesive modules, local reasoning, pure transformations and explicit
invariants. Provider transformations and service validation are separate modules.
Local bus authorization, strict voice TLS, external navigation restrictions and
atomic configuration writes close concrete exposure paths found during extraction.

Verification is recorded by each CI run: source and archive audit, full-history
secret scan, Python regressions, JavaScript parsing, Kotlin unit tests, both Android
build variants and APK audit. A failed or pending workflow is not release approval.
Real-device automation, microphone behavior and all third-party service deployments
require their own acceptance tests. No device test is implied by a successful build.

Known review limits: inherited runtime/WebUI modules are still large; native Android
Python wheel availability constrains upgrades. CI credentials and upstream binary
dependencies are separate trust boundaries. Source scans cannot prove arbitrary
free text contains no sensitive information. Repository visibility remains an
owner decision after reviewing these results and the dependency inventory.

See [dependency findings](DEPENDENCY_SECURITY.md) for the remaining native-library
version findings and scoped mitigations. They remain stable APK release gates.
The owner authorized publishing this source preview; that decision does not
reclassify the unresolved findings as fixed.
