# -*- coding: utf-8 -*-
"""
UI元素检测 特种版 v2 (纯ONNX: Android专调 YOLOv8n 21类语义检测 + PP-OCR 全图文字 + 空间匹配)
依赖: onnxruntime, opencv-python(numpy)。无 ultralytics / torch / PIL / rapidocr。
检测器: yasirfaizahmed/android_ui_detection_yolov8 (YOLOv8n, 21 Android UI 类),
        导出 ONNX(内置NMS, 输出(1,300,6)=[x1,y1,x2,y2,conf,cls], 动态输入, opset19), ~12.6MB。
        实效 License = AGPL-3.0(继承 Ultralytics YOLOv8, 见 MODEL_NOTICE.txt); 与被替换的旧 OmniParser 同级。
用法:
    from ui_detect_lite import detect
    elements = detect("screenshot.png")   # 或 BGR ndarray
返回: [{'bbox':[x1,y1,x2,y2], 'type':'icon'|'text', 'label':str|None, 'cls':str, 'confidence':float}]
  - type: 'text'(文字类: Text/TextButton/CheckedTextView) | 'icon'(其余控件/图标/图片)
  - cls : 21 类语义标签(Icon/Image/EditText/Switch/CheckBox/Toolbar/Bottom_Navigation/Card/...), 即便无文字也有语义
  - label: 框内 OCR 文字; 无文字时图标/控件回退为 cls 语义名, 文字类回退 None(不造假文本)
不变量: 输出坐标恒为整屏物理像素(letterbox 已还原); type∈{'icon','text'}; cls∈NAMES; bbox 满足 x2>x1,y2>y1。
"""
import os

import cv2
import numpy as np
import onnxruntime as ort

from ppocr_engine import PPOCR

_DIR = os.path.dirname(os.path.abspath(__file__))
YOLO_MODEL = os.path.join(_DIR, "models", "ui_detect_yolo.onnx")
YOLO_SIZE = 640   # 最长边=模型训练分辨率; 真机实测(Meizu21/ORT-android) 640≈165ms/35框 vs 960≈310ms/44框
                  # → 取 640 平衡延迟/召回(召回仍远超旧版 20框)。模型动态输入, 调大此值可换更高召回。
NMS_CONF_FLOOR = 0.25   # 导出时内置 NMS 烘焙的 conf 下限: 模型不输出低于此分的框。
                        # 故 detect(conf=) 只能向上过滤(conf>此值更严), 低于此值无效(不会召回更多)。

# yasirfaizahmed/android_ui_detection_yolov8 的 21 类 (顺序即模型 cls 索引, 勿改)
NAMES = [
    "BackgroundImage", "Bottom_Navigation", "Card", "CheckBox", "Checkbox",
    "CheckedTextView", "Drawer", "EditText", "Icon", "Image", "Map", "Modal",
    "Multi_Tab", "PageIndicator", "Remember", "Spinner", "Switch", "Text",
    "TextButton", "Toolbar", "UpperTaskBar",
]
TEXT_CLASSES = {"Text", "TextButton", "CheckedTextView"}

# 推理引擎按路径缓存(纯转发到 APK 总线; 一次建会话即可复用, 省去每帧重复 /onnx/info 往返)。
# 接受模块级状态: 显著降低每次 detect 的固定开销, 不改变输出(同模型同会话)。
_SESSIONS = {}
_PPOCR = None


def _session(path):
    sess = _SESSIONS.get(path)
    if sess is None:
        sess = _SESSIONS[path] = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    return sess


def _ocr_engine():
    global _PPOCR
    if _PPOCR is None:
        _PPOCR = PPOCR(use_cls=False)   # 手机截图不存在 180° 倒置文字: 跳过方向分类器 = 少一整轮 batch 往返(r28: 74 行文字省 ~1.5s)
    return _PPOCR


def _letterbox(img):
    """ultralytics rect letterbox: 等比缩放到<=YOLO_SIZE, pad 到 32 倍数填充 114。
    返回 (NCHW float32 输入, 还原系数 r, 左 pad, 上 pad)。"""
    h, w = img.shape[:2]
    r = min(YOLO_SIZE / w, YOLO_SIZE / h)
    nw, nh = round(w * r), round(h * r)
    im = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    dw, dh = (YOLO_SIZE - nw) % 32 / 2, (YOLO_SIZE - nh) % 32 / 2
    top, bot = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    im = cv2.copyMakeBorder(im, top, bot, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))
    x = np.ascontiguousarray(im[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0)
    return x, r, left, top


def _yolo(img, conf):
    """YOLO ONNX(内置NMS, 输出(1,300,6)) → [[x1,y1,x2,y2,conf,cls],...] 还原到原图坐标。"""
    x, r, left, top = _letterbox(img)
    import detector_models
    model = str(detector_models.model_path())
    if not os.path.isfile(model):
        return []
    sess = _session(model)
    out = sess.run(None, {sess.get_inputs()[0].name: x})[0][0]  # (300,6)
    return _restore(out, conf, r, left, top, img.shape[1], img.shape[0])


def _restore(rows, conf, r, left, top, w, h):
    """模型空间框 → 原图像素: 去 letterbox, 夹到图内, 丢弃夹后退化的框(大框常越过边缘)。"""
    boxes = []
    for x1, y1, x2, y2, c, cls in rows:
        if c < conf:
            continue
        x1, x2 = (min(max((v - left) / r, 0.0), w) for v in (x1, x2))
        y1, y2 = (min(max((v - top) / r, 0.0), h) for v in (y1, y2))
        if x2 > x1 and y2 > y1:
            boxes.append([x1, y1, x2, y2, float(c), int(cls)])
    return boxes


def _cls_name(cls):
    return NAMES[cls] if 0 <= cls < len(NAMES) else "Icon"


def _containment(a, b):
    """交集面积 / b面积 (b 被 a 包含的比例)。"""
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / area_b if area_b > 0 else 0


def detect(image, conf=0.25, contain_thresh=0.5):
    """image: 路径 或 BGR ndarray → 元素列表(YOLO 21类 + 全图OCR 空间匹配)。
    conf: 仅向上过滤(见 NMS_CONF_FLOOR, 低于地板无效)。
    contain_thresh: OCR 文字框被 YOLO 框包含到此比例即归属该框(取其文本作 label)。"""
    img = cv2.imread(image) if isinstance(image, str) else image
    assert img is not None, "image load failed"

    yolo_boxes = _yolo(img, conf)
    # 全图 OCR: 4点box → 轴对齐bbox
    ocr_items = []
    for box, text, score in _ocr_engine()(img):
        xs, ys = box[:, 0], box[:, 1]
        ocr_items.append([int(xs.min()), int(ys.min()),
                          int(xs.max()), int(ys.max()), text, float(score)])

    h, w = img.shape[:2]
    img_area = float(h * w) or 1.0
    elements, matched = [], set()
    for x1, y1, x2, y2, c, cls in yolo_boxes:
        name = _cls_name(cls)
        box_area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        label = None
        # 巨框(>50%屏: 背景图/弹窗/抽屉)不抢 OCR 标签, 避免吞掉某一条文字
        if box_area < 0.5 * img_area:
            for i, (ox1, oy1, ox2, oy2, text, oc) in enumerate(ocr_items):
                if i in matched:
                    continue
                if _containment([x1, y1, x2, y2], [ox1, oy1, ox2, oy2]) > contain_thresh:
                    label = text
                    matched.add(i)
                    break
        # 无文字: 文字类→None(不可造假文本), 其余控件→回退控件语义(Switch/EditText/Icon...)
        if label is None and name not in TEXT_CLASSES:
            label = name
        elements.append({'bbox': [x1, y1, x2, y2],
                         'type': 'text' if name in TEXT_CLASSES else 'icon',
                         'label': label, 'cls': name, 'confidence': c})
    # 未被任何控件框吸收的 OCR 文字 → 独立 text 元素
    for i, (ox1, oy1, ox2, oy2, text, oc) in enumerate(ocr_items):
        if i not in matched:
            elements.append({'bbox': [ox1, oy1, ox2, oy2], 'type': 'text',
                             'label': text, 'cls': 'Text', 'confidence': oc})
    return elements


def visualize(image, elements, output_path):
    img = cv2.imread(image) if isinstance(image, str) else image.copy()
    for el in elements:
        x1, y1, x2, y2 = [int(v) for v in el['bbox']]
        color = (0, 0, 255) if el['type'] == 'icon' else (255, 0, 0)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        tag = el.get('cls', '')
        if tag:
            cv2.putText(img, tag[:10], (x1, max(12, y1 - 3)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
    cv2.imwrite(output_path, img)


if __name__ == "__main__":
    import sys, time, json
    t = time.time()
    els = detect(sys.argv[1] if len(sys.argv) > 1 else "../cmp_phone.png")
    print("elapsed %.2fs, %d elements" % (time.time() - t, len(els)))
    for e in els[:50]:
        print(json.dumps(e, ensure_ascii=False, default=float))
