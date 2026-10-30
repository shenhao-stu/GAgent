---
app: 系统设置
aliases: [settings, 设置, 无障碍, 悬浮窗, 无线调试, 开发者选项, 电池优化]
pkg: com.android.settings
intent: [开无障碍, 开悬浮窗权限, 开无线调试, 关电池优化]
verified: true
verified_at: 2026-10-30
evidence: PermissionCoordinator 同口径 + 本机实测路径
confidence: 0.7
---
- 设置首页顶部有搜索框: 直接 `target='无障碍'` / `target='悬浮窗'` / `target='无线调试'` 搜进去, 比逐层点快得多。
- 二级页里点**开关文案**那一行(`target='使用无障碍'`), 别点行标题(有时只是展开)。
- 品牌差异: 小米/红米悬浮窗权限在「应用设置 → 应用管理 → 本应用 → 权限 → 显示悬浮窗」, 部分 ROM 在「特殊权限」里。**抓不到就 ask_user 让用户手动点**, 别在一个二级页里试 5 次。
