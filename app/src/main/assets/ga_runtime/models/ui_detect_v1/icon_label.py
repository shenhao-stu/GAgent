# -*- coding: utf-8 -*-
"""常见符号图标命名(放大镜/加号/叉/返回/菜单), 补 YOLO 'Icon' 框无文字时的语义。
纯 numpy/cv2: 前景掩膜 → 48x48 归一化 → 与模板特征余弦匹配。无神经网络, 每屏约 0.02-0.04s(真机)。
模板在首次调用时用 cv2 画几何线条生成(无外部图标素材/无模板文件), 每类覆盖几种线宽和比例。
circle/check/chevron-right/arrow-right 是干扰类, 只用于拉开差距, 不会作为结果输出。"""
import cv2
import numpy as np

# 模板名 → 输出名; 不在表里的模板名(干扰类)命中时视为未知
LABELS = {'search': 'search', 'plus': 'plus', 'close': 'close', 'menu': 'menu', 'back': 'back'}
THRESHOLD = 0.90   # 最高相似度下限
MARGIN = 0.045     # 与第二名(不同模板名)的最小差距
PAD = 6            # 裁剪外扩: YOLO 框常贴边甚至切掉图标笔画, 2px 时微信放大镜贴边被当边框删掉
MIN_SIDE, MAX_SIDE = 8, 160


def feature(rgb):
    """RGB 裁剪 → 2304 维单位向量; 无可用前景返回 None。"""
    if rgb.size == 0:
        return None
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    bg = int(np.argmax(np.bincount(g.ravel(), minlength=256)))   # 主背景色(比边框中位数稳)
    delta = np.abs(g.astype(np.float32) - bg)
    if delta.max() < 15:
        return None
    mask = (delta > max(10, float(np.percentile(delta[delta > 0], 90)) * .35)).astype(np.uint8)
    _, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
    h, w = mask.shape
    for i, (x, y, cw, ch, area) in enumerate(stats[1:], 1):
        touches = x == 0 or y == 0 or x + cw == w or y + ch == h
        if area < 3 or (touches and (cw > w * .8 or ch > h * .8 or area < 12)):   # 碎点/外框/背景块
            mask[lab == i] = 0
    ys, xs = np.where(mask)
    if len(xs) < 5:
        return None
    mask = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = mask.shape
    scale = 40 / max(h, w)
    norm = cv2.resize(mask.astype(np.float32), (max(1, round(w * scale)), max(1, round(h * scale))))
    out = np.zeros((48, 48), np.float32)
    y, x = (48 - norm.shape[0]) // 2, (48 - norm.shape[1]) // 2
    out[y:y + norm.shape[0], x:x + norm.shape[1]] = norm
    out = cv2.GaussianBlur(out, (5, 5), 1.0).ravel()
    return out / (np.linalg.norm(out) + 1e-8)


def _shapes(t):
    """线宽 t 下各模板的绘制函数(64x64 画布, 1=前景)。"""
    L = lambda c, a, b: cv2.line(c, a, b, 1, t, cv2.LINE_AA)
    C = lambda c, o, r: cv2.circle(c, o, r, 1, t, cv2.LINE_AA)
    P = lambda c, pts: cv2.polylines(c, [np.array(pts, np.int32)], False, 1, t, cv2.LINE_AA)
    out = {}
    for r, h in ((17, 13), (19, 10), (15, 16)):     # 放大镜: 圈大小/柄长, 柄朝右下或左下
        k = r * .7
        out.setdefault('search', []).append(lambda c, r=r, h=h, k=k: (C(c, (26, 26), r), L(c, (round(26 + k), round(26 + k)), (round(26 + k + h), round(26 + k + h)))))
        out['search'].append(lambda c, r=r, h=h, k=k: (C(c, (38, 26), r), L(c, (round(38 - k), round(26 + k)), (round(38 - k - h), round(26 + k + h)))))
    out['plus'] = [lambda c: (L(c, (32, 10), (32, 54)), L(c, (10, 32), (54, 32))),
                   lambda c: (C(c, (32, 32), 26), L(c, (32, 18), (32, 46)), L(c, (18, 32), (46, 32)))]
    out['close'] = [lambda c: (L(c, (12, 12), (52, 52)), L(c, (52, 12), (12, 52))),
                    lambda c: (C(c, (32, 32), 26), L(c, (22, 22), (42, 42)), L(c, (42, 22), (22, 42)))]
    out['menu'] = [lambda c, g=g: [L(c, (10, y), (54, y)) for y in (32 - g, 32, 32 + g)] for g in (10, 14, 18)]   # 三横线, 行距由紧到松
    out['back'] = [lambda c: P(c, [(42, 10), (20, 32), (42, 54)]),
                   lambda c: (L(c, (12, 32), (52, 32)), P(c, [(30, 14), (12, 32), (30, 50)]))]
    out['chevron-right'] = [lambda c: P(c, [(22, 10), (44, 32), (22, 54)])]
    out['arrow-right'] = [lambda c: (L(c, (12, 32), (52, 32)), P(c, [(34, 14), (52, 32), (34, 50)]))]
    out['check'] = [lambda c: P(c, [(10, 34), (26, 50), (54, 16)])]
    out['circle'] = [lambda c: C(c, (32, 32), 24)]
    return out


_BANK = None


def _bank():
    global _BANK
    if _BANK is None:
        names, feats = [], []
        for t in (2, 3, 4, 6):
            for name, fns in _shapes(t).items():
                for fn in fns:
                    c = np.zeros((64, 64), np.uint8)
                    fn(c)
                    f = feature(np.repeat(255 - c[..., None] * 255, 3, axis=2))   # 白底黑线
                    if f is not None:
                        names.append(name)
                        feats.append(f)
        names = np.array(names)
        _BANK = (np.stack(feats), [(n, np.flatnonzero(names == n)) for n in sorted(set(names.tolist()))])
    return _BANK


def classify(rgb):
    """RGB 裁剪 → (名字|None, 相似度, 与第二名差距)。"""
    f = feature(rgb)
    if f is None:
        return None, 0.0, 0.0
    mat, groups = _bank()
    sc = mat @ f
    rk = sorted(((float(sc[ix].max()), n) for n, ix in groups), reverse=True)
    s, name = rk[0]
    gap = s - rk[1][0]
    ok = s >= THRESHOLD and gap >= MARGIN
    return (LABELS.get(name) if ok else None), round(s, 4), round(gap, 4)


def name_box(img_bgr, bbox):
    """整图 BGR + 框 → 图标名或 None。尺寸/长宽比明显不像单个符号的框直接跳过。"""
    x1, y1, x2, y2 = [int(v) for v in bbox]
    w, h = x2 - x1, y2 - y1
    if min(w, h) < MIN_SIDE or max(w, h) > MAX_SIDE or not .3 < w / max(h, 1) < 3.3:
        return None
    H, W = img_bgr.shape[:2]
    crop = img_bgr[max(0, y1 - PAD):min(H, y2 + PAD), max(0, x1 - PAD):min(W, x2 + PAD)]
    return classify(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))[0]
