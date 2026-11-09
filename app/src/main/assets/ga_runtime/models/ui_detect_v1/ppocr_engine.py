# -*- coding: utf-8 -*-
"""
PP-OCR 纯ONNX推理引擎 (det + cls + rec)
依赖: onnxruntime, opencv-python(numpy)。无 rapidocr / paddle / torch / PIL / pyclipper / shapely。
逐步镜像 rapidocr_onnxruntime 默认流程, 输出与其等价。
易移植设计: 所有步骤为显式 numpy/cv2 基本操作, 注释标注每步张量形状。
用法:
    from ppocr_engine import PPOCR
    ocr = PPOCR()                       # 模型在 ./models/
    results = ocr(cv2.imread(path))     # BGR ndarray
    # results: [ (box 4x2 int, text:str, score:float), ... ]
"""
import math
import os

import cv2
import numpy as np
import onnxruntime as ort

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

# ---------------- 默认参数 (= rapidocr config.yaml) ----------------
MAX_SIDE_LEN = 1280      # det 输入最长边上限(手机截图 1080x2424 → 570x1280): 文字检测在此分辩率足够, 像素量比 2000 少 2.4 倍;
                         # rec 切片从**原图**取(见 __call__), 不受这里的缩放影响 → 小字识别精度不掉。r28 实测 淘宝闪购首页 74 行: 11.8s → 见 look_bench
MIN_SIDE_LEN = 30        # 整图最短边下限
DET_LIMIT_SIDE = 736     # det: 最短边目标 (limit_type=min)
DET_THRESH = 0.3         # det: 概率图二值化阈值
DET_BOX_THRESH = 0.5     # det: 框平均得分阈值
DET_UNCLIP_RATIO = 1.6   # det: 框外扩系数
DET_USE_DILATION = True  # det: 二值图 2x2 膨胀
DET_MAX_CANDIDATES = 1000
CLS_SHAPE = (3, 48, 192) # cls 输入 CHW
CLS_THRESH = 0.9         # cls: 180度置信阈值
CLS_BATCH = 16
REC_SHAPE = (3, 48, 320) # rec 输入 CHW
REC_BATCH = 16           # Logical grouping controls padding; keep stable for recognition parity.
REC_MICROBATCH = 8       # Split inference only, retaining each parent's padded width.
REC_WORKERS = 4          # Phone-validated with microbatch=8; no cache required for speedup.
MIN_TEXT_H = 10          # det 框在原图上高度 < 10px 的文字肉眼不可读、rec 也认不出 → 直接丢, 省 crop+rec
TEXT_SCORE = 0.5         # 最终文本得分过滤


def _session(name):
    so = ort.SessionOptions()
    so.log_severity_level = 4
    so.enable_cpu_mem_arena = False
    return ort.InferenceSession(os.path.join(_DIR, name), so,
                                providers=["CPUExecutionProvider"])


# ======================= Det: DBNet =======================
class TextDetector:
    def __init__(self):
        self.sess = _session("ch_PP-OCRv4_det_infer.onnx")
        self.iname = self.sess.get_inputs()[0].name

    def __call__(self, img):
        """img: BGR HxWx3 → boxes: Nx4x2 float (原图坐标, TL TR BR BL)"""
        src_h, src_w = img.shape[:2]
        # --- 预处理: 最短边缩放到>=736, 且边长取整到32倍数 ---
        h, w = src_h, src_w
        ratio = float(DET_LIMIT_SIDE) / min(h, w) if min(h, w) < DET_LIMIT_SIDE else 1.0
        resize_h = max(int(round(int(h * ratio) / 32) * 32), 32)
        resize_w = max(int(round(int(w * ratio) / 32) * 32), 32)
        resized = cv2.resize(img, (resize_w, resize_h))
        # 归一化 (x/255 - 0.5)/0.5, HWC→CHW→NCHW float32
        x = (resized.astype(np.float32) / 255.0 - 0.5) / 0.5
        x = x.transpose(2, 0, 1)[None]
        # --- 推理: 输出 (1,1,resize_h,resize_w) 概率图 ---
        pred = self.sess.run(None, {self.iname: x})[0][0, 0]
        # --- 后处理: DB ---
        mask = (pred > DET_THRESH).astype(np.uint8)
        if DET_USE_DILATION:
            mask = cv2.dilate(mask, np.ones((2, 2), np.uint8))
        boxes = self._boxes_from_bitmap(pred, mask, src_w, src_h)
        return boxes

    def _boxes_from_bitmap(self, pred, mask, dest_w, dest_h):
        height, width = mask.shape
        outs = cv2.findContours(mask * 255, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        contours = outs[0] if len(outs) == 2 else outs[1]
        boxes = []
        for contour in contours[: DET_MAX_CANDIDATES]:
            pts, sside = self._mini_box(contour)
            if sside < 3:
                continue
            score = self._box_score_fast(pred, pts)
            if score < DET_BOX_THRESH:
                continue
            pts = self._unclip(pts)           # 外扩
            pts, sside = self._mini_box(pts.reshape(-1, 1, 2).astype(np.float32))
            if sside < 5:
                continue
            # 映射回原图坐标
            pts[:, 0] = np.clip(np.round(pts[:, 0] / width * dest_w), 0, dest_w)
            pts[:, 1] = np.clip(np.round(pts[:, 1] / height * dest_h), 0, dest_h)
            boxes.append(pts.astype(np.float32))
        return boxes

    @staticmethod
    def _mini_box(contour):
        """最小外接矩形, 顶点排序为 TL TR BR BL; 返回(4x2, 短边长)"""
        rect = cv2.minAreaRect(contour)      # ((cx,cy),(w,h),angle)
        points = sorted(cv2.boxPoints(rect), key=lambda p: p[0])  # 按x排序
        if points[1][1] > points[0][1]:
            i1, i4 = 0, 1
        else:
            i1, i4 = 1, 0
        if points[3][1] > points[2][1]:
            i2, i3 = 2, 3
        else:
            i2, i3 = 3, 2
        box = np.array([points[i1], points[i2], points[i3], points[i4]], dtype=np.float32)
        return box, min(rect[1])

    @staticmethod
    def _box_score_fast(pred, pts):
        """框内概率均值 (fillPoly掩码)"""
        h, w = pred.shape
        xmin = np.clip(int(np.floor(pts[:, 0].min())), 0, w - 1)
        xmax = np.clip(int(np.ceil(pts[:, 0].max())), 0, w - 1)
        ymin = np.clip(int(np.floor(pts[:, 1].min())), 0, h - 1)
        ymax = np.clip(int(np.ceil(pts[:, 1].max())), 0, h - 1)
        m = np.zeros((ymax - ymin + 1, xmax - xmin + 1), dtype=np.uint8)
        shifted = pts.copy()
        shifted[:, 0] -= xmin
        shifted[:, 1] -= ymin
        cv2.fillPoly(m, shifted.reshape(1, -1, 2).astype(np.int32), 1)
        return cv2.mean(pred[ymin:ymax + 1, xmin:xmax + 1], m)[0]

    @staticmethod
    def _unclip(pts):
        """外扩距离 d = 面积*unclip_ratio/周长 (Vatti偏移的矩形解析等价, 免pyclipper)
        对最小外接矩形: 四边各外推d → 中心不变, 宽高各+2d, 角度不变"""
        # shoelace 面积 & 周长
        x, y = pts[:, 0], pts[:, 1]
        area = abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0
        length = np.sum(np.sqrt(np.sum(np.diff(np.vstack([pts, pts[:1]]), axis=0) ** 2, axis=1)))
        if length < 1e-6:
            return pts
        d = area * DET_UNCLIP_RATIO / length
        (cx, cy), (w, h), ang = cv2.minAreaRect(pts)
        return cv2.boxPoints(((cx, cy), (w + 2 * d, h + 2 * d), ang))


# ======================= Cls: 方向分类 =======================
class TextClassifier:
    def __init__(self):
        self.sess = _session("ch_ppocr_mobile_v2.0_cls_infer.onnx")
        self.iname = self.sess.get_inputs()[0].name

    def __call__(self, crops):
        """crops: list[BGR ndarray] → 原地旋转180度修正, 返回crops"""
        for beg in range(0, len(crops), CLS_BATCH):
            batch = crops[beg:beg + CLS_BATCH]
            x = np.stack([self._resize_norm(c) for c in batch])
            prob = self.sess.run(None, {self.iname: x})[0]  # (N,2) softmax已含
            for i, p in enumerate(prob):
                idx = int(np.argmax(p))      # 0='0', 1='180'
                if idx == 1 and p[idx] > CLS_THRESH:
                    crops[beg + i] = cv2.rotate(crops[beg + i], cv2.ROTATE_180)
        return crops

    @staticmethod
    def _resize_norm(img):
        c, ih, iw = CLS_SHAPE
        h, w = img.shape[:2]
        rw = min(int(math.ceil(ih * w / float(h))), iw)
        r = cv2.resize(img, (rw, ih)).astype(np.float32)
        r = (r.transpose(2, 0, 1) / 255.0 - 0.5) / 0.5
        pad = np.zeros(CLS_SHAPE, dtype=np.float32)
        pad[:, :, :rw] = r
        return pad


# ======================= Rec: CTC识别 =======================
class TextRecognizer:
    def __init__(self, compact=True, cache_bytes=16 * 1024 * 1024):
        from collections import OrderedDict
        from threading import Lock
        # Exact normalized batch bytes, scoped to this model instance. No stale coordinates.
        self._cache = OrderedDict()
        self._cache_lock = Lock()
        self._cache_limit = max(0, int(cache_bytes))
        self._cache_size = 0
        compact_name = "ch_PP-OCRv4_rec_compact.onnx"
        self.compact = compact and os.path.isfile(os.path.join(_DIR, compact_name))
        self.sess = _session(compact_name if self.compact else "ch_PP-OCRv4_rec_infer.onnx")
        self.iname = self.sess.get_inputs()[0].name
        # 字典: blank + 6623字 + 空格 (rec_keys.txt 提取自onnx metadata)
        with open(os.path.join(_DIR, "rec_keys.txt"), encoding="utf-8") as f:
            self.character = ["blank"] + f.read().splitlines() + [" "]

    def __call__(self, crops):
        """crops: list[BGR] → [(text, score), ...] 顺序与输入一致。
        batch 按宽高比排序(同 batch 宽度接近, 少 pad); batch 之间用 REC_WORKERS 路并发发往总线——ORT 每次 Run 只吃部分核,
        两路并发实测 7.55s→5.7s(73 行), 3-4 路无更多收益(r28 淘宝闪购首页)。"""
        n = len(crops)
        results = [None] * n
        if n == 0:
            return results
        ratios = [c.shape[1] / float(c.shape[0]) for c in crops]
        order = np.argsort(np.array(ratios))
        c, ih, iw = REC_SHAPE
        # Preserve parent padding: recomputing widths per microbatch changes CTC results.
        batches = []
        for beg in range(0, n, REC_BATCH):
            parent = order[beg:beg + REC_BATCH]
            width = max(iw / float(ih), *(ratios[i] for i in parent))
            for offset in range(0, len(parent), REC_MICROBATCH):
                batches.append((parent[offset:offset + REC_MICROBATCH], width))

        def run_batch(batch):
            idxs, max_wh = batch
            x = np.stack([self._resize_norm(crops[i], max_wh) for i in idxs])
            key = (x.shape, x.tobytes()) if self._cache_limit and x.nbytes <= self._cache_limit else None
            decoded = None
            if key is not None:
                with self._cache_lock:
                    decoded = self._cache.get(key)
                    if decoded is not None:
                        self._cache.move_to_end(key)
            if decoded is None:
                outputs = self.sess.run(None, {self.iname: x})
                if self.compact:
                    ids, scores = outputs
                    decoded = tuple(self._ctc_decode_top1(idx, prob) for idx, prob in zip(ids, scores))
                else:
                    decoded = tuple(self._ctc_decode(p) for p in outputs[0])
                if key is not None:
                    with self._cache_lock:
                        if key not in self._cache:
                            self._cache[key] = decoded
                            self._cache_size += len(key[1])
                            while self._cache_size > self._cache_limit:
                                old_key, _ = self._cache.popitem(last=False)
                                self._cache_size -= len(old_key[1])
            for i, result in zip(idxs, decoded):
                results[i] = result

        if len(batches) <= 1 or REC_WORKERS <= 1:
            for b in batches:
                run_batch(b)
        else:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=REC_WORKERS) as ex:
                list(ex.map(run_batch, batches))   # list() 让异常在此抛出
        return results

    @staticmethod
    def _resize_norm(img, max_wh_ratio):
        c, ih, _ = REC_SHAPE
        tw = int(ih * max_wh_ratio)          # 本batch目标宽
        h, w = img.shape[:2]
        rw = min(int(math.ceil(ih * w / float(h))), tw)
        r = cv2.resize(img, (rw, ih)).astype(np.float32)
        r = (r.transpose(2, 0, 1) / 255.0 - 0.5) / 0.5
        pad = np.zeros((c, ih, tw), dtype=np.float32)
        pad[:, :, :rw] = r
        return pad

    def _ctc_decode(self, pred):
        """pred: (T, num_classes) → (text, mean_prob); 去重相邻+去blank(0)"""
        return self._ctc_decode_top1(pred.argmax(axis=1), pred.max(axis=1))

    def _ctc_decode_top1(self, idx, prob):
        """Same CTC decoding for local probabilities and compact ORT outputs."""
        keep = np.ones(len(idx), dtype=bool)
        keep[1:] = idx[1:] != idx[:-1]       # 去相邻重复
        keep &= idx != 0                     # 去blank
        text = "".join(self.character[i] for i in idx[keep])
        conf = prob[keep]
        return text, float(conf.mean()) if len(conf) else 0.0


# ======================= 总管线 =======================
class PPOCR:
    def __init__(self, use_cls=True):
        self.det = TextDetector()
        self.cls = TextClassifier() if use_cls else None
        self.rec = TextRecognizer()

    def recognize(self, img):
        crops = [img]
        if self.cls:
            crops = self.cls(crops)
        return self.rec(crops)[0]

    def region(self, img):
        h, w = img.shape[:2]
        side = DET_LIMIT_SIDE
        pb, pr = max(0, side - h), max(0, side - w)
        padded = cv2.copyMakeBorder(
            img, 0, pb, 0, pr, cv2.BORDER_CONSTANT, value=(0, 0, 0)
        )
        rows = self(padded)
        return [
            (box, text, score)
            for box, text, score in rows
            if float(box[:, 0].mean()) < w and float(box[:, 1].mean()) < h
        ]

    def __call__(self, img):
        """img: BGR ndarray → [(box 4x2 int(原图坐标), text, score), ...]"""
        src = img
        src_h, src_w = img.shape[:2]
        # --- 整图尺寸规整 (与rapidocr一致): 最长边<=MAX_SIDE_LEN(只用于 det), 最短边>=30 ---
        rh = rw = 1.0
        h, w = img.shape[:2]
        if max(h, w) > MAX_SIDE_LEN:
            img, rh, rw = self._resize32(img, float(MAX_SIDE_LEN) / max(h, w))
        h, w = img.shape[:2]
        if min(h, w) < MIN_SIDE_LEN:
            img, rh2, rw2 = self._resize32(img, float(MIN_SIDE_LEN) / min(h, w))
            rh, rw = rh * rh2, rw * rw2
        # --- det (缩放图) ---
        boxes = self.det(img)
        if not boxes:
            return []
        boxes = self._sort_boxes(boxes)
        # --- crop: 框映射回**原图**再切(透视校正; 高/宽>=1.5 视为竖排转90) → det 降分辩率不影响 rec 精度 ---
        src_boxes = [np.stack([np.clip(b[:, 0] * rw, 0, src_w), np.clip(b[:, 1] * rh, 0, src_h)], axis=1) for b in boxes]
        keep = [i for i, b in enumerate(src_boxes) if (b[:, 1].max() - b[:, 1].min()) >= MIN_TEXT_H]
        boxes = [boxes[i] for i in keep]; src_boxes = [src_boxes[i] for i in keep]
        if not boxes:
            return []
        crops = [self._rotate_crop(src, b) for b in src_boxes]
        # --- cls 方向修正 ---
        if self.cls:
            crops = self.cls(crops)
        # --- rec ---
        rec_res = self.rec(crops)
        # --- 过滤 + 坐标还原到原图 ---
        out = []
        for box, (text, score) in zip(boxes, rec_res):
            if score < TEXT_SCORE:
                continue
            box = box.copy()
            box[:, 0] = np.clip(box[:, 0] * rw, 0, src_w)
            box[:, 1] = np.clip(box[:, 1] * rh, 0, src_h)
            out.append((box.round().astype(int), text, score))
        return out

    @staticmethod
    def _resize32(img, ratio):
        h, w = img.shape[:2]
        nh = int(round(int(h * ratio) / 32) * 32)
        nw = int(round(int(w * ratio) / 32) * 32)
        img = cv2.resize(img, (nw, nh))
        return img, h / nh, w / nw   # 返回还原系数

    @staticmethod
    def _sort_boxes(boxes):
        """自上而下,同行(y差<10)自左而右"""
        boxes = sorted(boxes, key=lambda b: (b[0][1], b[0][0]))
        for i in range(len(boxes) - 1):
            for j in range(i, -1, -1):
                if abs(boxes[j + 1][0][1] - boxes[j][0][1]) < 10 and \
                        boxes[j + 1][0][0] < boxes[j][0][0]:
                    boxes[j], boxes[j + 1] = boxes[j + 1], boxes[j]
                else:
                    break
        return boxes

    @staticmethod
    def _rotate_crop(img, pts):
        w = int(max(np.linalg.norm(pts[0] - pts[1]), np.linalg.norm(pts[2] - pts[3])))
        h = int(max(np.linalg.norm(pts[0] - pts[3]), np.linalg.norm(pts[1] - pts[2])))
        dst = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
        M = cv2.getPerspectiveTransform(pts.astype(np.float32), dst)
        crop = cv2.warpPerspective(img, M, (w, h),
                                   borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_CUBIC)
        if h * 1.0 / max(w, 1) >= 1.5:
            crop = np.rot90(crop)
        return crop


if __name__ == "__main__":
    import sys, time
    ocr = PPOCR()
    t = time.time()
    res = ocr(cv2.imread(sys.argv[1] if len(sys.argv) > 1 else "../cmp_phone.png"))
    print("elapsed %.2fs, %d lines" % (time.time() - t, len(res)))
    for box, text, score in res:
        print(box[0].tolist(), box[2].tolist(), round(score, 3), text)
