# Ecosystem & download channels / 生态与下载渠道

[README](../README.md) · [中文首页](../README.zh-CN.md) · [Build](BUILD.md)

These projects share a lineage, but their packages, licenses and validation records
are distinct. Choose a channel by what you want to use.
这些项目有共同来源，但安装身份、许可证和验收记录不同。

| Entry / 入口 | Purpose / 用途 | How it relates to this repository / 与本仓库的关系 |
| --- | --- | --- |
| [gaagent.ai](https://gaagent.ai/) | GenericAgent website, framework and ecosystem / 官网与生态入口 | Overview and links; not an APK built from this repository / 总览入口，不是本仓库制品 |
| [lsdefine/GenericAgent](https://github.com/lsdefine/GenericAgent) | Upstream agent framework / 上游智能体框架 | Source lineage; upstream's own license and desktop setup apply / 来源项目，沿用其自身许可与桌面安装方法 |
| [app.gaagent.ai](https://app.gaagent.ai/) | Current GA Mobile download portal / 当前 GA 手机版下载站 | Separately distributed app; preserve it when trying this repository's package / 独立分发，试用本仓库时保留原安装 |
| [androidbench.gaagent.ai](https://androidbench.gaagent.ai/) | Real-device evaluation, task catalog and case traces / 真机评测、任务与案例轨迹 | Research evidence with its own protocols; not a universal version score / 按各研究协议解读，不等于所有版本的成绩 |
| [GAgent Actions](https://github.com/shenhao-stu/GAgent/actions/workflows/android.yml) / [Releases](https://github.com/shenhao-stu/GAgent/releases) | Builds of this repository / 本仓库构建 | Use development artifacts or build locally; GitHub sign-in may be needed to download Actions artifacts / 使用开发制品或自行构建，Actions 制品下载可能需要 GitHub 登录 |

The open-source release application ID is `io.github.shenhaostu.gagent`; debug adds
`.debug`. Do not assume a portal APK is an update for either one. Check source
commit, package ID, signing certificate and SHA-256 before upgrading.

开源正式版与调试版包名不同，也与旧版独立。下载站上的包不自动等于本仓库构建；升级前核对
源码提交、包名、签名和摘要。维护者应在下载地址迁移后同步更新本页及中英文 README。

The AndroidBench [cases](https://androidbench.gaagent.ai/#traces),
[paired navigation study](https://androidbench.gaagent.ai/#jev-study) and
[methodology](https://androidbench.gaagent.ai/#method) explain different research
conditions. The bounded Pixel snapshot for this extraction is in
[Validation](VALIDATION.md). Keep those evidence sets separate.

本仓库提供开源预览。源码公开、开发构建、草稿发布与稳定 APK 分发分别管理。
