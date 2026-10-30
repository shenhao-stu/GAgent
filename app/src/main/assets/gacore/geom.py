# -*- coding: utf-8 -*-
"""geom: 屏幕坐标的唯一换算权威 + 本机实测的系统 UI 锚带。

为什么单独一个模块(而不是各处各算): 坐标单位曾经散在四处——gui_act 的 point 要
0-1000、look()/dump()/find()/tap() 用像素、SOP 文本写百分数、tap_rel 又是 0-1000——
区分它们只靠 ga_android._norm_pt 里那句「任一轴 >1000 就当像素」。在 1200x2670 上
这句话对上/左大半个屏幕恒错, 而且**不报错**: 实测放大镜像素 (996,215) 被当成归一化,
点成 (1195,574), 偏 199px 右、359px 下, 模型只看到 diff=0, 于是反复重点。搜索框/
放大镜/标题行全在这片区域里, 所以「点不到搜索框」是这类故障的必然结果, 不是偶发。

本模块只提供事实, 不替调用方判别单位:
- to_px / to_norm: 精确 round + 夹取, 端点是 dim-1 而不是 dim。旧实现
  int(x/1000*w) 在 x=1000 时产出 w, 被 _gesture_screen 与 ScreenGeometry.requirePoint
  当越界拒掉, 整个轮次白废(既有单测还把 (1200,2670) 当正确期望, 等于把 bug 固化)。
- BANDS: 本机实测的系统 UI 区域, 按**比例**记录。比例与分辨率无关, 换机仍可用;
  注释里的像素值是 1200x2670 上的实测值, 仅供核对。

锚带描述的是**系统 UI**(状态栏/标题行/底部导航)的几何, 不是任何 App 的控件位置,
因此不触碰「无 per-app 硬编码」红线; App 特有的位置仍只能来自当帧观测。
"""
NORM = 1000          # 归一化域上限: 0-1000, 左上原点, x 右 y 下

# 本机 1200x2670 实测(screencap 逐像素扫描暗像素与图标边缘), 取整后按比例记录。
# 小数是比例, 注释是 1200x2670 上的像素值。
BANDS = {
    # 状态栏: 时间/电量文字与图标实测落在 y 53..91
    'status':  (0.000, 0.000, 1.000, 0.040),      # y 0..106
    # 标题/工具栏行: 微信主页放大镜/+ 实测 y 190..244; 各 App 的标题行都在这条带里
    'title':   (0.000, 0.055, 1.000, 0.120),      # y 146..320
    # 内容区: 列表/表单/正文
    'content': (0.000, 0.120, 1.000, 0.880),      # y 320..2349
    # 底部导航/tab 栏: 微信底栏实测 y 2406..2526, 其下是系统手势条
    'navbar':  (0.000, 0.880, 1.000, 1.000),      # y 2349..2669
}


def _dim(v, who):
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ValueError('%s must be a positive int, got %r' % (who, v))
    if v <= 0:
        raise ValueError('%s must be a positive int, got %r' % (who, v))
    return v


def _coord(v, who):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError('%s must be a number, got %r' % (who, v))
    return float(v)


def to_px(rx, ry, w, h):
    """0-1000 归一化 → 当前屏幕像素 (round + 夹取)。

    跨度取 dim-1: 归一化 1000 必须落在最后一像素。旧实现 int(x/1000*w) 产出 dim,
    被 _gesture_screen 与 ScreenGeometry.requirePoint 当越界拒掉, 整个轮次白废
    (既有单测还把 (1200,2670) 当正确期望, 等于把 bug 固化)。dim-1 跨度是
    [0,1000]→[0,dim-1] 的双射, 不需要夹取也能落在屏内; 夹取只兜 VLM 估算溢出。
    to_norm 用同一跨度, 两者互为逆运算(整数取舍内)。"""
    w, h = _dim(w, 'w'), _dim(h, 'h')
    rx, ry = _coord(rx, 'rx'), _coord(ry, 'ry')
    x = int(round(rx / NORM * (w - 1)))
    y = int(round(ry / NORM * (h - 1)))
    return max(0, min(w - 1, x)), max(0, min(h - 1, y))


def to_norm(x, y, w, h):
    """像素 → 0-1000 归一化 (round + 夹取)。与 to_px 互为逆运算(整数取舍内一致)。"""
    w, h = _dim(w, 'w'), _dim(h, 'h')
    x, y = _coord(x, 'x'), _coord(y, 'y')
    return (max(0, min(NORM, int(round(x / (w - 1) * NORM)))) if w > 1 else 0,
            max(0, min(NORM, int(round(y / (h - 1) * NORM)))) if h > 1 else 0)


def band(name, w, h):
    """锚带名 → 当前屏幕的像素矩形 (x1, y1, x2, y2); 未知名抛错并列出可用名。"""
    if name not in BANDS:
        raise ValueError('unknown band %r, choose from: %s' % (name, '/'.join(sorted(BANDS))))
    w, h = _dim(w, 'w'), _dim(h, 'h')
    rx1, ry1, rx2, ry2 = BANDS[name]
    x1, y1 = to_px(rx1 * NORM, ry1 * NORM, w, h)
    x2, y2 = to_px(rx2 * NORM, ry2 * NORM, w, h)
    return x1, y1, x2, y2

def band_norm(name):
    """锚带名 → 0-1000 矩形; 直接当 ask_vision 的 roi / look 的 roi 用(与全系统坐标契约一致)。"""
    if name not in BANDS:
        raise ValueError('unknown band %r, choose from: %s' % (name, '/'.join(sorted(BANDS))))
    rx1, ry1, rx2, ry2 = BANDS[name]
    return (int(round(rx1 * NORM)), int(round(ry1 * NORM)),
            int(round(rx2 * NORM)), int(round(ry2 * NORM)))


def in_band(name, x, y, w, h, pad=0):
    """像素点是否落在锚带内(可带像素容差)。给"这个坐标像不像在标题行"一个客观判据,
    替代模型用状态栏文字位置猜图标——那种猜法在真机上直接点偏。"""
    x1, y1, x2, y2 = band(name, w, h)
    return (x1 - pad) <= x <= (x2 + pad) and (y1 - pad) <= y <= (y2 + pad)
