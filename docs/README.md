# Documentation / 文档导航

Start with the path that matches your task. English and Chinese READMEs describe
the same supported scope; deeper guides keep API names and commands unchanged.
按任务选择入口。中英文 README 的能力与限制保持一致，命令和 API 名称不翻译。

| Audience / 读者 | Reading path / 阅读顺序 |
| --- | --- |
| First-time user / 首次使用 | [Get started / 开始使用](GETTING_STARTED.md) → [Enable capabilities / 开启功能](CONFIGURATION.md) → [Practical cases / 实操案例](CASES.md) |
| Agent-assisted setup / 让 Agent 帮你安装 | [Install with GenericAgent, Codex or Claude Code](INSTALL_WITH_AGENT.md) → [First-run checks / 首次验收](GETTING_STARTED.md#acceptance) |
| Contributor / 开发者 | [Build / 构建](BUILD.md) → [Architecture / 架构](ARCHITECTURE.md) → [Development / 开发](DEVELOPMENT.md) → [Testing / 测试](TESTING.md) |
| PR author or reviewer / PR 作者与审查者 | [Contributing](../CONTRIBUTING.md) / [中文贡献指南](../CONTRIBUTING.zh-CN.md) → [PR template / 模板](../.github/PULL_REQUEST_TEMPLATE.md) |
| Maintainer / 维护者 | [Validation / 验收](VALIDATION.md) → [Dependency security / 依赖安全](DEPENDENCY_SECURITY.md) → [Releasing / 发布](RELEASING.md) |

## Specific topics / 专题

- [Core size, memory and token measurement / 内核规模、记忆与 Token 统计](CORE_AND_MEMORY.md)
- [DeepSeek Android comparison and pinned sources / DeepSeek 安卓对照与固定来源](COMPARISON.md)
- [Ecosystem and download channels / 生态与下载渠道](ECOSYSTEM.md)
- [News and dated development milestones / 新闻与开发节点](HISTORY.md)
- [Troubleshooting / 排障](TROUBLESHOOTING.md)
- [Phone-side networking / 手机模型网络](NETWORK.md)
- [Screen geometry and overlay invariants / 屏幕与悬浮窗不变量](SCREEN_GEOMETRY.md)
- [Optional YOLO installation and licensing / YOLO 安装与许可](OPTIONAL_YOLO.md)
- [Official modules and credential boundaries / 官方组件与密钥边界](OFFICIAL_MODULES.md)
- [Retained, removed and excluded features / 功能范围](FEATURE_SCOPE.md)
- [Extraction review and its limits / 剥离审查与局限](REVIEW.md)
- [Hybrid phone agent spec / 混合式手机 Agent 规格](SPEC.md)
- [Empowerment addendum: research findings, device adaptation and work items / 赋能增补：研究发现、真机适配与工作项](SPEC-EMPOWERMENT.md)
- [Engineering priorities / 工程路线图](ROADMAP.md)
- [Security reporting and data flows / 安全报告与数据流](../SECURITY.md)
- [Third-party notices / 第三方声明](../THIRD_PARTY.md)
- [Project decisions / 项目治理](../GOVERNANCE.md) and [community conduct / 社区行为](../CODE_OF_CONDUCT.md)
- [Changes / 变更记录](../CHANGELOG.md)
- [Logo and usage / 标识与使用](assets/README.md)

## Documentation contract / 文档约定

Build pins come from the workflow and dependency manifests, behavior from source
and tests, and acceptance claims from a dated run with an identified commit.
A roadmap item is not an implemented feature. If these disagree, fix the document
or implementation and record the evidence; do not silently promote a plan to a claim.

构建版本以工作流和依赖文件为准，行为以源码和测试为准，验收结论须有日期和提交标识。
计划不等于已实现。更改用户可见能力时同步相关指南；修改 README 的能力或限制时同步另一语言。
