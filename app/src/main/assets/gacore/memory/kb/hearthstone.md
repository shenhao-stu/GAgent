---
app: 炉石传说小程序
aliases: [炉石, hearthstone, 套牌, 传说, 排行榜, 卡组代码]
pkg: com.tencent.mm
intent: [看套牌排行榜, 复制卡组代码, 炉石传说小程序]
verified: false
verified_at: 2026-10-30
evidence: run 1793322875 (卡在"套牌"底部导航, 连点 3 次 diff 0.3-0.5%)
confidence: 0.5
---
- 进小程序: `search_app value='炉石传说'` → `target='炉石传说 小程序'`。
- 底部导航(首页/套牌/…)用 `target='套牌'`; 同名文字多时返回里的 `target.alternatives` 就是落选清单, 同轮用 `target_index` 纠正, 不要重发同一坐标。
- 精确文字(牌表、卡组代码)用 `code_run` 里的 `ocr()` 或 `gui_act` 的 `target`; `observe` 在 canvas 页拿不到结构。
- 排行榜一般在「套牌 → 传说」二级页; 进不去先确认是不是停在弹层(分享/活动), 关掉再点。
