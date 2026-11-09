# APK 设计指南 (apk_design_guide) — 工厂出的 App 要好看

> 蒸馏自 mobile-android-design(Material Design 3) + mobile-ios-design(Apple HIG) 两个 skill，
> 适配工厂可编译边界(View 体系 + material:1.12.0，无 Compose)。写 UI 前读一遍，逐条对着做。

## 三原则(两大设计体系的交集)
- **清晰**: 内容第一，装饰克制——少色、留白、层级分明；一屏只讲一件事。
- **一致**: 全 App 同一套颜色/字号/圆角/间距 token，同类元素长一样。
- **深度**: 用 elevation/阴影/圆角表达层级(卡片浮于背景)，不用花哨边框。

## 硬规矩(违反=不合格)
| 项 | 规矩 |
|---|---|
| 主题 | `Theme.Material3.DayNight.*`(material 依赖自带)——自动深色模式 |
| 颜色 | 只用主题属性(`?attr/colorPrimary`/`colorSurface`/`colorOnSurface`…)，不硬编码 `#RRGGBB` 正文色；品牌色可自定但明暗两套 |
| 字号 | sp 单位；层级 = 22-28(标题)/16(正文)/12-14(辅助)，辅助文字用 60% 透明度而非灰色硬编码 |
| 间距 | 8dp 网格(8/16/24)；屏幕边距 16dp 起；相关元素近、无关元素远 |
| 触控 | 可点目标 ≥48dp(HIG 44pt 同源)；水波纹反馈(`?attr/selectableItemBackground`) |
| 圆角 | 统一 token: 卡片 12-16dp、按钮 8-12dp 或全圆；不要一屏三种圆角 |
| 图标 | Vector drawable(24dp 网格)；不缩放位图当图标 |
| 无障碍 | 图像/图标按钮给 `contentDescription`；正文对比度 ≥4.5:1 |

## 好看加分项
- 空状态: 列表为空给一句引导文案+图标，不留白屏。
- 状态设计: pressed/disabled/selected 有视觉差(M3 state layer)。
- 渐变/大字头图: 顶部 hero 区渐变(`GradientDrawable`)+大号数字/日期是低成本高级感(参考 examples/calendar)。
- 深色模式实测: 明暗各截一屏看对比度，别只测浅色。

## 更新来源
```
npx skills add https://github.com/wshobson/agents --skill mobile-android-design
npx skills add https://github.com/wshobson/agents --skill mobile-ios-design
```
