---
app: 支付宝
aliases: [alipay, 付款码, 扫一扫, 转账, 余额]
pkg: com.eg.android.AlipayGphone
intent: [打开付款码, 扫码, 转账, 查余额]
verified: false
verified_at:
evidence:
confidence: 0.4
---
- 首页顶部搜索框 + 右上角「+」(扫一扫/收付款/付款码都在这个面板里)。**待核**: 同类布局在其它 App 上验证过, 支付宝本身未实测。
- 付款码属于敏感操作: 动手前先把「要做什么」告诉用户(`ask_user`), 别自己点过去。
