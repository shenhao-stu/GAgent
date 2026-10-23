# Validation snapshot / 验收快照

**Date:** 2026-10-23

**Android baseline:** 2.33.3 / 136

**Open-source device-build commit:** `6c4683a1a36ccc7b3b9a121099b81ef2d1d75422`

This is a bounded engineering record, not a certification or overall accuracy
claim. Later commits need checks appropriate to their changes; they do not
automatically inherit complete device acceptance from this snapshot.

本页记录一次有边界的验收，不代表所有设备、模型或任务均通过。后续提交需按变化补充证据。

## Automated build / 自动构建

[Android CI run 39930370841](https://github.com/shenhao-stu/GAgent/actions/runs/39930370841)
passed source/archive and history scans, Python/UI regressions, Kotlin tests,
both APK builds and packaged-content checks. Actions artifact retention is limited; a release must preserve its
reviewed source and artifact metadata separately.

The focused Python regressions passed in both development trees. Geometry and
overlay decisions also have Kotlin unit coverage. These checks are not an
independent security audit; native dependency limitations remain in
[Dependency security](DEPENDENCY_SECURITY.md).

## Physical device / 实机

Device: Pixel 10, Android 16, default display. The tested OSS installation was
the debug variant, upgraded without clearing data. It had a separately installed
optional detector; task results therefore do not establish identical behavior for
an OCR-only fresh installation.

测试设备保留了用户自行安装的可选检测模型；不能把这组任务结果直接当成默认无 YOLO 包的效果。

| Check / 项目 | Observed result / 实际结果 |
| --- | --- |
| Phone-local GLM-5.3-flash transport | 3 text + 2 synthetic-image requests passed; 1.385–2.806 seconds, including droid.ask_vision |
| Background task → Home → app → Home | Overlay restored in both background transitions: 483 / 649 ms |
| WeChat with always-on enabled | Overlay remained visible through the nofloat launch path; no WeChat node-tree reads |
| Rotation 0° / 90° / 180° / 270° | Screenshot and display geometry agreed; stale and out-of-bounds coordinates were rejected |
| Fresh portrait/landscape gesture | Own-app input focused and keyboard appeared; no text submitted |
| Settings preservation | Rotation settings restored after testing; no ADB reverse transport used |

An earlier network probe observed a transient SSL EOF that recovered. A phone-local
proxy was configured for the tested provider. This does not establish stability
on every network. An actual ADB disconnection during a task did not stop the phone
session; the exact physical unplug interval was not measured.

此前出现过一次恢复后的 SSL EOF。无 USB 代理和一次断连继续运行，不等于所有网络均无超时。

## Representative task sample / 代表性任务

Eight original queries across six task families were attempted during candidate
iteration, with the same GLM model but evolving adapters/instructions. App history
was retained, so repeated runs were warm. The final overlay/geometry commit did
not receive a new full run of all eight queries.

| Task family / 任务 | Last attempt / 最后一次结果 | Limitation / 说明 |
| --- | --- | --- |
| System settings L1 | Passed | Verified final setting; restored original state |
| System settings L2 | Passed | Verified mode and value; restored original state |
| Bilibili L1 | Passed | GUI sort selection verified; filter drawer left open |
| Bilibili L2 | Partial | Date range broadened; combined duration selection not established |
| Used-goods search | Partial | Price ordering not established; accessory mistaken for the complete product |
| Meeting app | Blocked | Existing login expired; no login or meeting join |
| Route query | Passed | Route read back; matching history provided a warm-state advantage |
| Trending list | Partial | Pinned item confused with numbered rank |

Result: **4 passed, 3 partial, 1 blocked**. This is not a randomized A/B comparison,
a full benchmark, or evidence that a different historical model/version regressed.
Uninstrumented token fields must not be interpreted as zero use.

结果为4通过、3部分完成、1阻塞。保留失败，按实际状态而不是模型自述计分；
不同日期和模型的历史记录不能直接证明版本退化。

A separate WeChat mini-program task reached the phone-login boundary. Login was
deferred by the device owner; checkout, order submission and payment were not
completed. No full shopping-flow success is claimed.

## Not established / 尚未证明

- Physical foldable behavior, other OEMs, external displays and 16 KB page-size coverage.
- Correct complex filtering or ranking across arbitrary third-party apps.
- Production acceptance of every optional service, microphone path or server deployment.
- Complete native dependency remediation or an independent security audit.
- Equivalent task results with every model, protocol, network or OCR-only installation.

Follow [Testing](TESTING.md) for new evidence and [Roadmap](ROADMAP.md) for the
remaining engineering priorities. Personal device traces and screenshots are not
distributed in this repository.
