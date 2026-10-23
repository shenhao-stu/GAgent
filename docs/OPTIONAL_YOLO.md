# 可选 Android UI 检测模型 / Optional Android UI detector

默认 APK 的本地视觉模型包含 PaddleOCR；YOLO 不自动下载，也没有付费解锁开关。YOLO 能为无文字图标、输入框和弹窗补充候选框，但不能保证每个按钮都识别正确，操作后仍需观察确认。

PaddleOCR is bundled. YOLO is a separate optional model, with no paid unlock or automatic download. The optional detector adds boxes for icons, inputs and dialogs; verify the resulting screen after every action.

## At a glance / 先看这一张表

| Component / 组件 | Role / 作用 | Setup / 配置 |
| --- | --- | --- |
| OCR | Reads visible text / 识别文字 | Bundled / 已内置 |
| YOLO | Locates UI classes such as icons and inputs / 定位图标、输入框等控件 | User-installed compatible ONNX / 用户安装兼容 ONNX |
| Vision model | Interprets an image or checks a semantic question / 看图理解与核验 | Configure the [vision adapter](CONFIGURATION.md#models) / 配置视觉适配器 |

**Enable:** acquire a trusted compatible ONNX → verify its digest → install at the
exact private path below → restart → run a fresh detection. File presence enables
the optional detector; no separate settings toggle is required. Renaming a `.pt`
file to `.onnx` does not convert it. No model-provider key is used for local YOLO inference.

**开启顺序：**取得可信、兼容的 ONNX → 校验摘要 → 放到下方指定位置 → 重启 → 核对实际检测。
文件存在后由视觉管线按需加载，不需要额外开关；把 `.pt` 改名不能代替导出。

## 1. 来源与许可 / Source and licensing

- 模型 / Model: [yasirfaizahmed/android_ui_detection_yolov8](https://huggingface.co/yasirfaizahmed/android_ui_detection_yolov8), YOLOv8 Nano, 21 Android UI classes.
- 固定来源版本 / Pinned source revision: `f692e68a3d7c92d51b5e94bba2fc13196a280e18`.
- 模型卡标注 Apache-2.0；旧 ONNX 导出元数据标注 Ultralytics / AGPL-3.0。此差异尚未由权利方澄清。GAgent 框架的 Apache-2.0 不会覆盖第三方模型；使用、修改和再分发须遵守适用模型条款，商业授权须另行取得，不能把本说明视作已取得授权。
- The model card says Apache-2.0, while the previous ONNX export embeds Ultralytics / AGPL-3.0 metadata. These conflicting notices remain unresolved. The framework license does not relicense model weights; obtain the applicable rights separately before redistribution.
- [Ultralytics licensing](https://www.ultralytics.com/license), [ONNX export documentation](https://docs.ultralytics.com/modes/export/).

## 2. 自行下载、导出 / Download and export yourself

在独立桌面 Python 环境安装你已接受条款的 Ultralytics 导出工具，下载固定版本的 [best.pt](https://huggingface.co/yasirfaizahmed/android_ui_detection_yolov8/resolve/f692e68a3d7c92d51b5e94bba2fc13196a280e18/best.pt)。不要把 `.pt` 直接放进 APK。

In an isolated desktop Python environment, obtain the export tools under their applicable terms and download the pinned `best.pt` above. The APK requires ONNX, not PyTorch weights.

```python
from ultralytics import YOLO
YOLO("best.pt").export(format="onnx", imgsz=640, dynamic=True,
                       nms=True, opset=19, half=False, simplify=True)
```

输出契约必须是 float32 RGB `[1,3,H,W]`，输出 `[1,300,6]`，每行 `x1,y1,x2,y2,confidence,class_id`，包含 NMS，21 类顺序见 `ui_detect_lite.NAMES`。不同导出器版本可能产生不兼容图；先验证，不直接替换线上模型。上述命令是复现配方，本次并未重新运行桌面导出。

Required contract: float32 RGB `[1,3,H,W]`, NMS output `[1,300,6]` with `x1,y1,x2,y2,confidence,class_id`, and the 21 classes in `ui_detect_lite.NAMES` order. Exporter versions may differ; validate compatibility first. The recipe was not re-exported in this release.

## 3. 安装到自己的手机 / Install on your phone

将兼容的 ONNX 重命名为 `ui_detect_yolo.onnx`，记录其 SHA-256，并通过 USB/系统文件选择放到手机 Download 目录。让 GAgent 在本机执行以下代码（把摘要替换为你实际核验的值），或 debug 安装使用 `adb shell run-as` 写入相同私有路径。无需官方账号、订阅或密钥。

Rename a compatible ONNX file to `ui_detect_yolo.onnx`, record its SHA-256, and transfer it to Downloads. With file access granted, run the following inside your own GAgent. No official account, subscription, or key is required.

```python
from pathlib import Path
import hashlib, shutil, droid
src = Path('/sdcard/Download/ui_detect_yolo.onnx')
expected = 'REPLACE_WITH_YOUR_VERIFIED_SHA256'
assert hashlib.sha256(src.read_bytes()).hexdigest() == expected
out = Path(droid.BUNDLE) / 'models/ui_detect_yolo.onnx'
if out.exists():
    raise FileExistsError('Back up the existing model before replacing it')
shutil.copyfile(src, out)
print({'installed': out.exists(), 'bytes': out.stat().st_size})
```

实际目标为当前安装的私有目录 `files/ga/models/ui_detect_v1/models/ui_detect_yolo.onnx`。
正式版与 debug 的目录独立；装进一个版本不会自动让另一个版本生效。
已有模型先备份再替换。此安装步骤不需要 root；无法读取 Download 时先检查文件访问授权。

The target is the current app's private `files/ga/models/ui_detect_v1/models/ui_detect_yolo.onnx`.
Release and debug installations are independent. Back up an existing detector
before replacement. Root is not required; resolve file-access permission if Downloads cannot be read.

## 4. 验证与停用 / Verify and disable

重启 GAgent 后运行 `print(droid.look(cache=False))`。`droid.ping()['loaded']` 应包含 `ui_detect_yolo.onnx`，检测项应有 `Icon`/`TextButton` 等类别。不要仅凭文件存在宣称模型工作。

Restart GAgent, then run `print(droid.look(cache=False))`. Confirm the detector appears in `droid.ping()['loaded']` and that actual predictions contain UI classes such as `Icon` or `TextButton`.

删除这个可选文件并重启即可退回 OCR。模型安装仅作用于 App 私有数据，不会加入 Git 源码历史或默认发布包。
Delete the optional file and restart to return to OCR. Device installation does not add the model to Git history or default release artifacts.


可直接对 GAgent 说：

> 我已将兼容的 ui_detect_yolo.onnx 放进 Download。先核验我提供的 SHA-256，
> 确认现有模型不会被覆盖，再安装到当前应用的模型目录。不要输出私人文件。
> 重启后在设置页运行一次不缓存的检测，确认模型加载及输出类别。

You can ask GAgent to perform the verified copy and a fresh detection on your own
Settings screen. Do not test it by sending a message or making a purchase.

| Symptom / 现象 | Check / 检查 |
| --- | --- |
| Only OCR output / 只有文字框 | Correct package/private path, model filename and restart; some screens genuinely have no eligible non-text detections / 核对安装身份、路径、文件名与重启，也可能该页没有可用图标框 |
| ONNX load/output error / 加载或形状错误 | Export contract, opset/runtime compatibility, NMS output and class order / 检查导出契约、版本、NMS 与类别顺序 |
| File permission denied / 无权读取 | Use an allowed shared-file location or grant the needed file access / 使用获准目录并授权 |
| Boxes are wrong after rotation / 旋转后位置不对 | Re-observe the current screen and geometry; do not reuse old coordinates / 重新观察，不复用旧坐标 |
| Vision still unavailable / 仍不能看图问答 | YOLO is local detection, not a multimodal provider; configure the visual adapter separately / YOLO 不替代看图模型配置 |

The desktop export recipe is documented, not newly executed in this documentation
update. A compatible detector was present in the earlier Pixel run; see its
[validation limits](VALIDATION.md). No bundled-weight redistribution is implied.
