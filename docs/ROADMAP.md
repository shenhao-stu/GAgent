# Roadmap / 工程路线图

[News & completed milestones / 已完成节点](HISTORY.md) · [Current setup / 当前配置](CONFIGURATION.md)

This is a list of open work and acceptance criteria, not a delivery schedule.
Completed behavior belongs in release notes and validation records. Discuss a
substantial proposal in an issue and link its evidence when completed.

The Android implementation is traceable to June 13, 2026; the dated history is
separate from this list of future work. Current source has the local runtime,
visual phone tools, memory and optional clients. Cross-device certification,
complete native migration and automatic service onboarding are not marked done.

这里列待办和验收条件，不承诺时间，也不把计划写成已发布功能。

| Priority / 优先级 | Work / 工作 | Completion evidence / 完成依据 |
| --- | --- | --- |
| Public-release gate | Move to a supported Python/native-wheel set; resolve remaining dependency findings | Packaged library inventory, reachability review, both builds and real-device compatibility; see DEPENDENCY_SECURITY.md |
| Device compatibility | Verify 16 KB page size, additional OEMs and real fold/unfold transitions | Named physical devices/configurations, repeatable screen/gesture/overlay tests and explicit unsupported cases |
| Task reliability | Improve observation-to-action and final-state verification | Fixed-query comparisons with initial state, model/protocol, failed attempts and manual assistance recorded |
| GUI semantics | Resolve demonstrated filtering, product-type and ranking errors | Correct selected state and independent result evidence, without app-specific coordinate scripts |
| Optional services | Define and validate compatible service/credential protocols | Disabled-by-default behavior, scoped/revocable credentials, server-side authorization and deployment acceptance |
| Detector distribution | Resolve model provenance/licensing before any bundled YOLO redistribution | Rights and source/export contract recorded; OCR-only fallback remains usable |
| Core maintainability | Extract coherent boundaries from large inherited modules when justified | Smaller change radius, explicit invariants and preserved behavior; no wrapper-only refactor |
| Release evidence | Improve durable artifact provenance and repeatable acceptance | Source/CI/APK/signature correspondence and verified download metadata |

No roadmap item authorizes a change to repository visibility, live services,
credentials or a device owner's accounts. The framework can be open while
privileged service authority stays on separately controlled servers.

公开框架不要求交付服务商根密钥。新组件能否接入，应由协议、权限和验收证据决定，
不能以混淆或客户端加密替代服务端授权。

Current boundaries are in [Architecture](ARCHITECTURE.md), prior outcomes in
[Validation](VALIDATION.md), and release decisions in [Releasing](RELEASING.md).
