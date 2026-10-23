## Problem and result / 问题与结果

<!-- Describe the trigger and before/after behavior. Link an issue if relevant.
说明触发条件、修改前后行为；有相关 Issue 时链接。 -->

## Boundary and invariants / 边界与不变量

<!-- What inputs can vary? What must remain true? Why does this module own the change?
明确变量、不变量和职责归属。核心、协议或依赖变更需说明必要性。 -->

## Validation / 验证

<!-- List commands and observed results. For GUI changes include device/OS, commit,
orientation, initial state and final-state evidence. Mark untested/blocked items.
列实际命令和结果；GUI 变更记录设备、系统、方向、初态和结果证据；未测/阻塞明确标注。 -->

## Risks and compatibility / 风险与兼容

<!-- Cover migration, user-data preservation, rollback and limitations when relevant.
涉及迁移、用户数据、回退或兼容性时说明；不适用可写 N/A。 -->

## Review checklist / 审查清单

- [ ] The change has one coherent purpose; unrelated edits are excluded. / 改动职责聚焦。
- [ ] Relevant checks and their actual outcomes are recorded above. / 已记录真实验证结果。
- [ ] Documentation and English/Chinese user-facing text match the behavior. / 文档与中英文文案一致。
- [ ] No credentials, personal data or private runtime artifacts are included. / 未包含秘密或个人运行数据。
- [ ] Dependency/model provenance and licenses are updated, or unchanged. / 依赖与模型来源许可已更新或未变。
- [ ] New cases/news cite evidence and identify examples, observed outcomes and dates accurately, or are not applicable. / 新案例与节点有依据，区分示例、实测与日期，或不适用。
