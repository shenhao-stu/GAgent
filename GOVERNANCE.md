# Project decisions / 项目治理

GAgent is maintained through this repository. Maintainers review contributions;
the repository owner controls access, signing authority, releases and visibility.
The repository is an open-source preview. Source publication and stable APK
releases are separate owner decisions; a successful build alone does not establish
production readiness. See the remaining [dependency work](docs/DEPENDENCY_SECURITY.md).

维护者通过本仓库审查贡献；所有者管理访问、签名、发布与公开时间。
合并代码和构建 APK 不等于公开仓库。

## Decisions / 决策方式

Small, reversible changes can be proposed directly as a focused PR. Changes to
protocols, persistent data, core architecture, dependencies or default permissions
should first explain the problem, alternatives, invariants and migration cost in
an issue or design note. Review evidence and simplicity take precedence over
the number of features or layers added.

小改动直接 PR；跨边界改动先说明问题、替代方案、不变量与迁移代价。
用证据和整体复杂度评估方案，不以新增功能或抽象层数量评价质量。

[Contributing](CONTRIBUTING.md) defines review requirements.
[Releasing](docs/RELEASING.md) defines artifact and publication checks.
These documents do not claim that a GitHub ruleset or a multi-reviewer team has
already been configured. Review authority follows actual repository permissions.

## Scope / 项目范围

The Android framework and opt-in client protocols are the shared scope.
Separately operated services have their own credentials, deployment and licensing.
Publishing framework code does not grant access to those services or transfer
their signing authority.

Engineering priorities are tracked in the [Roadmap](docs/ROADMAP.md).
Plans carry no implied delivery date. Record consequential decisions in issues,
PRs or linked documentation so later contributors can understand the tradeoff.
