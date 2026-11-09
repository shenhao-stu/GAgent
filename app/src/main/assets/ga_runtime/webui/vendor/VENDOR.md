# Vendored WebUI libraries

无包管理器；所有库为 drop-in 文件，随 APK 分发，升级后重建 APK。
升级时需手动重新下载并更新此表 + 排查安全公告（DOMPurify / marked / highlight.js）。

| 文件 | 库 | 版本 | 许可证 | 源 |
|---|---|---|---|---|
| ../marked.min.js | marked | 15.0.7 | MIT | https://github.com/markedjs/marked |
| purify.min.js | DOMPurify | 3.4.17 | Apache-2.0 / MPL-2.0 | https://github.com/cure53/DOMPurify |
| highlight.min.js | highlight.js (common build) | 11.10.0 | BSD-3-Clause | https://github.com/highlightjs/highlight.js |

代码移植溯源（仅 MIT/Apache/BSD/ISC/MPL）：
- 代码块复制按钮+语言标签：参考 NextChat (MIT) 的标记模式，独立重写。
- hljs 主题：基于 highlight.js BSD-3 token class，配色由本仓 M3 令牌派生，独立编写。

设计仅模仿（不可复制源码/素材）：kelivo (AGPL-3.0)、Open WebUI、Cherry Studio。
