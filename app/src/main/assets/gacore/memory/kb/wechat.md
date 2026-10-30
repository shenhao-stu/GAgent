---
app: 微信
aliases: [wechat, com.tencent.mm, 小程序, 搜一搜, 发现页, 朋友圈, 聊天]
pkg: com.tencent.mm
intent: [搜小程序, 打开小程序, 找公众号, 看朋友圈, 发表情]
verified: true
verified_at: 2026-10-30
evidence: run 1793268615 (search_app 一步成功, 41s/6 轮收工) / run 1793324693
confidence: 0.95
---
- **搜东西/进小程序**: `gui_act action=search_app value='关键词'` 一步做完。返回里的 `results` 就是这一帧的结果行(设备像素, 按 y 排序), 要哪行就 `target=<那一行的文字>`。
- 手动兜底才用放大镜: 微信主页**标题行右侧**的放大镜(先 `look(roi='title')` 找最右的图标), 别背像素坐标。
- 底栏四个 tab: 微信 / 通讯录 / 发现 / 我。朋友圈在 **发现 → 第一条**; 扫一扫、收付款在右上角 **+** 的面板里。
- 微信是敏感 App: `dump_state` 永远返回空树(`droid_dump_blank`), 只能靠截图/OCR/target; `droid.find()` 在微信里必然是空的。
