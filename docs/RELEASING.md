# Release guide / 发布指南

[Build](BUILD.md) · [Testing](TESTING.md) · [Security](../SECURITY.md)

A release binds **source commit → verified build → signed artifact → published
metadata**. Every link must refer to the same artifact. Building, merging,
creating a draft and making a repository public are distinct actions.

发布必须把源码、构建、签名制品与元数据绑定到同一份产物。仓库公开由所有者单独决定，
不能随构建或合并自动发生。

## 1. Define the candidate / 确定候选

- Select an exact reviewed commit and record the intended versionCode/versionName.
- Review [feature scope](FEATURE_SCOPE.md), [dependency findings](DEPENDENCY_SECURITY.md)
  and [validation limits](VALIDATION.md). Resolve or explicitly classify open items.
- Update the changelog and bilingual release notes with behavior, compatibility,
  migration and remaining limitations.
- Decide whether the result is a private draft, prerelease or stable release.
  Do not claim a public launch while the repository remains private.

For this project, source is published as a preview by the owner's decision.
The supported Python/native-wheel migration remains an open **stable APK release
gate**. Publishing source does not mark those findings fixed or publish draft
releases. Optional YOLO redistribution needs its own resolved rights; a user-download
guide is not permission to bundle weights.

## 2. Build and verify the same commit / 验证同一提交

Use the existing workflow. Inspect both `verify` and `build`, including source
and history scans, Python/UI tests, Kotlin tests and both APK audits.

~~~sh
gh run list --workflow android.yml --branch main
~~~

Select the run by its exact commit, not just its position in the list. Download
its artifact through GitHub or `gh run download` with the selected run ID.
Compare SOURCE_COMMIT, SHA256SUMS, each inventory and the signing certificate.
An inventory is not a complete SBOM or an independent vulnerability audit.

Do not rebuild after acceptance and assume the bytes are identical. If source,
toolchain, packaging or signing changes, identify the new artifact and rerun the
affected checks. The build recipe is pinned in parts; bit-for-bit reproducibility
has not been established.

## 3. Verify device and upgrade behavior / 设备与升级验收

Use the intended signed variant on a selected test device. Preserve data.
At minimum, validate the changed behavior and startup/configuration after update.
For device changes, include background lifecycle and relevant rotation/resize
cases from [Testing](TESTING.md).

Record the installed APK digest, package ID, certificate, OS/device and result.
Distinguish debug validation from release validation. If a complete task stops at
login or another user boundary, record it as blocked or partial rather than passed.

## 4. Prepare a reviewable draft / 准备可审查草稿

Create the tag only for the selected commit. Prepare a **draft** release with:

- Explicitly selected APKs, identifying debug, signed release or unsigned release.
- SHA256SUMS and SOURCE_COMMIT for those exact bytes.
- Package inventories and certificate information.
- English and Chinese notes, tested scope and known limitations.
- Updated third-party notices and any corresponding source required for distribution.

Never upload a whole workspace or private runtime backup. Keep signing keys,
passwords, service configuration and personal traces out of artifacts.
Do not silently replace a published versioned APK with different bytes.
A corrected artifact needs a clearly identified new release.

草稿可供核验，不等于获准公开。制品清单应逐项选择，不能打包整份工作目录。
版本化文件一旦发布，不应在原地址悄悄换成另一份内容。

## 5. Publish and verify delivery / 发布与交付核验

The owner decides repository visibility and publication. Before public launch,
confirm a usable private security-reporting channel and review access, Actions
permissions, secret handling and third-party rights. This guide does not change
those settings automatically.

After an authorized publication, verify the release/tag, metadata and downloaded
APK hash. If a separate website or updater is used, give it one publication owner:
publish the canonical release first, then synchronize it. A periodic synchronizer
can otherwise restore an older release over a manual website change.

Use immutable, versioned APK URLs in update manifests. Check mutable aliases
separately and invalidate only their changed cache entries when necessary.
A successful upload is not proof that users receive the intended bytes.

## 6. Recovery / 回退

Keep prior signed artifacts and reviewed metadata available. Prefer a corrective
release with a higher versionCode when Android will not accept a downgrade.
Do not use uninstall or data clearing as an automatic rollback.

If a key leaks, revoke it at the authority that issued it; deleting a file or
rewriting Git history does not revoke credentials. Follow the security reporting
and communication path before redistributing affected artifacts.
