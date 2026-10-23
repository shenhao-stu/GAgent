# Contributing to GAgent

[简体中文](CONTRIBUTING.zh-CN.md) · [Development](docs/DEVELOPMENT.md) · [Testing](docs/TESTING.md)

We welcome reproducible bug reports, documentation, translations, tests and focused
implementation changes. English and Chinese are both accepted. For a substantial
protocol, dependency or architecture change, discuss the problem and proposed
boundary in an issue before committing to a large implementation. Small fixes can
go directly to a PR.

## Start with the problem

Describe the observable trigger and expected outcome. Identify the owning module,
the inputs that may vary and the invariant that must hold. For example: rotation
may change width and height, but a gesture must not reuse coordinates from an
incompatible observation.

Check existing interfaces before adding a new one. Prefer device, provider or
service adapters when the GA planning loop does not need to change. Keep one
responsibility per PR; avoid unrelated renames, formatting and dependency upgrades.

## Development workflow

1. Start from current `main` and use a focused branch.
2. Follow [Build](docs/BUILD.md) and the [source map](docs/DEVELOPMENT.md).
3. For a reproducible behavioral bug, capture a failing case before the fix.
4. Implement the smallest coherent change, with effects at explicit boundaries.
5. Select checks from [Testing](docs/TESTING.md), then inspect the whole diff.
6. Update affected guides and both READMEs when capability or compatibility changes.
7. Submit using the [PR template](.github/PULL_REQUEST_TEMPLATE.md).

Do not clear app data, connect to production accounts or run paid/device operations
as an automatic test prerequisite. Use synthetic fixtures. If a device test needs
owner participation, report it as untested or blocked until it is actually run.

## What a PR needs

- A title describing the resulting behavior; a prefix such as `fix(android):`,
  `docs:` or `test:` can help scanning.
- The concrete problem, before/after behavior and why this boundary owns the fix.
- Variable inputs and preserved invariants, including compatibility and data ownership.
- Exact validation commands and results; distinguish passed, failed, blocked and untested.
- Material risks, migration or rollback implications, and remaining limitations.

A screenshot or model answer alone is not sufficient evidence of task success.
For GUI changes include device/OS, app commit, orientation, initial state and
observable outcome. Distinguish warm state and manual assistance.
Do not attach private conversations, provider files, keys or unredacted logs.

## Review principles

Reviewers should be able to reason about a change locally. Favor high cohesion,
stable dependency direction, composable interfaces and a small change radius.
Parsing, validation, geometry and policy should usually be pure functions;
network, filesystem, clocks and Android effects should be explicit.

Encode important constraints in interfaces or validation instead of relying on
comments. Reject stale session/device/credential state before side effects.
Error handling should match the failure's reach: stop a potentially misdirected
operation, while keeping low-impact diagnostics from obscuring the primary path.

Avoid speculative abstractions, app-specific patches for a general interface defect,
and retry loops that can repeat an action whose outcome is unknown. Existing large
modules are not a reason to rewrite the entire runtime in an unrelated PR.

## Merge requirements

Maintainers review behavior, scope and evidence. Both Android workflow jobs,
`verify` and `build`, must pass for the proposed commit before merging a normal
code change. A pending or cancelled run is not a pass. Relevant device acceptance
is additional evidence, not a substitute for CI.

Dependency, model or vendored-file changes also need provenance, license notices,
packaged-runtime review and the affected compatibility checks. Service integrations
must remain opt-in, work without shared privileged keys and preserve TLS and
credential-origin boundaries. Security-sensitive changes should receive an
independent review where a qualified reviewer is available; do not label the
author's self-review as independent.

These are review requirements. Repository branch-protection settings are a separate
configuration; this document does not claim they are already enforced by GitHub.
An exception must be explicit, scoped and recorded, never described as a passed check.

## Documentation, conduct and licensing

Keep examples executable or clearly mark incomplete sketches. Link to one canonical
recipe instead of copying it into many pages. Do not claim a roadmap item is shipped.
A docs-only change needs factual, link and formatting review, not invented behavior
tests.

For README cases and news, distinguish a reusable example from an observed run.
Link the tested revision, conditions and outcome; keep partial and blocked results
visible. Date milestones from reviewed history and distinguish implementation,
release and public-launch dates. Download links must identify their distribution.

Follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report vulnerabilities through
[SECURITY.md](SECURITY.md), not ordinary bug reports. Submit only material you have
the right to contribute under the project's [Apache-2.0 license](LICENSE), and
preserve the separate terms in [THIRD_PARTY.md](THIRD_PARTY.md).
