# -*- coding: utf-8 -*-
"""droid.paste L2 区域化 OCR + 空间分区回归测试(离线, mock 总线)。
场景取材 2026-07-10 微信发消息真机事故日志: 键盘剪贴板提示条显示剪贴板全文,
旧版全屏 OCR 匹配 → hit=True 假阳性 → agent 误信已上屏。"""
import sys
import time
import types
from pathlib import Path

import numpy as np
import pytest

GACORE = Path(__file__).resolve().parents[2] / "app" / "src" / "main" / "assets" / "ga_runtime"
sys.path.insert(0, str(GACORE))
import droid  # noqa: E402

TEXT = "gpt5.6和grok正式上线了"
W, H = 1080, 2340
REAL_NUMPY_IMAGE = np.zeros((H, W, 3), dtype=np.uint8)


class _Img:
    shape = (H, W, 3)


@pytest.fixture(autouse=True)
def _node_permission(monkeypatch):
    """Exercise optional tree-based verification in an ordinary app unless a test overrides it."""
    monkeypatch.setattr(droid, "SAFE_MODE", False)
    monkeypatch.setattr(droid, "_get", lambda path, **kw: {"visual_only": False})


def test_safe_mode_does_not_inspect_nodes_or_claim_paste_success(monkeypatch):
    monkeypatch.setattr(droid, "SAFE_MODE", True)
    monkeypatch.setattr(droid, "_get", lambda *a, **kw: pytest.fail("unexpected bus read"))
    actions = []
    monkeypatch.setattr(droid, "_act", lambda **kw: actions.append(kw))
    assert droid.dump(full=True) == []
    result = droid.paste(TEXT)
    assert result["needs_gui_paste"] and result["uncertain"] and not result["hit"]
    assert actions == [{"op": "clipboard", "text": TEXT}]


def _box(l, t, r, b):
    return [[l, t], [r, t], [r, b], [l, b]]


def _region_fake(rows):
    """按几何过滤 full-image 坐标 fixture 行, 模拟 _ocr_region 的区域扫描语义。"""
    def fake(img, x1, y1, x2, y2):
        out = []
        for box, s, sc in rows:
            cx = sum(p[0] for p in box) / len(box); cy = sum(p[1] for p in box) / len(box)
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                out.append(([[int(px), int(py)] for px, py in box], s, float(sc)))
        return out
    return fake


def _run_paste(monkeypatch, nodes, ocr_rows, text=TEXT):
    edits = [
        [int(v) for v in n["b"].split(",")]
        for n in nodes if n.get("edit") and n.get("b")
    ]
    recognized = next(
        ((s, sc) for box, s, sc in ocr_rows
         if any(l <= sum(p[0] for p in box) / len(box) <= r
                and t <= sum(p[1] for p in box) / len(box) <= b
                for l, t, r, b in edits)),
        ("", 0.0),
    )
    monkeypatch.setattr(droid, "_act", lambda **kw: {"ok": 1})
    monkeypatch.setattr(droid, "dump", lambda full=False: nodes)
    monkeypatch.setattr(droid, "shot", lambda: REAL_NUMPY_IMAGE)
    monkeypatch.setattr(droid, "ocr_text", lambda img: recognized)
    monkeypatch.setattr(droid, "_ocr_region", _region_fake(ocr_rows))
    return droid.paste(text)


# 事故现场帧(真机取材): 微信 adjustPan 下 app 窗口底恒=屏高(1570 不可用), 键盘候选区靠"来自剪贴板"标签锚定;
# 输入框在键盘上方(y≈1500), 提示条"来自剪贴板"标签 + 全文气泡在其下方键盘候选区(y≈1580+)。
WECHAT_NODES = [
    {"b": "0,0,%d,%d" % (W, H), "l": 0},                    # 微信 adjustPan: 窗口根底界=屏高(故不能靠它定键盘)
    {"b": "150,1470,850,1540", "edit": 1, "t": "", "l": 5}, # 输入框(微信 a11y 不透出文本)
    {"b": "0,130,%d,1440" % W, "l": 2},                     # 聊天列表容器
]
CLIP_LABEL = (_box(19, 1578, 213, 1622), "来自剪贴板", 0.99)
CLIP_BUBBLE = (_box(51, 1650, 616, 1715), TEXT, 0.99)
WECHAT_EDITS = [[150, 1470, 850, 1540]]


def test_paste_rejects_empty_text_before_action(monkeypatch):
    monkeypatch.setattr(
        droid, "_act",
        lambda **kw: (_ for _ in ()).throw(AssertionError("must not dispatch")),
    )
    with pytest.raises(ValueError, match="empty"):
        droid.paste("")


def test_reviewer_fix_verification_uses_full_dump_once(monkeypatch):
    calls = {"dump": [], "region": 0}
    monkeypatch.setattr(droid, "_act", lambda **kw: {"ok": 1})
    def fake_dump(full=False):
        calls["dump"].append(full)
        return WECHAT_NODES
    monkeypatch.setattr(droid, "dump", fake_dump)
    monkeypatch.setattr(droid, "shot", lambda: REAL_NUMPY_IMAGE)
    monkeypatch.setattr(droid, "ocr_text", lambda img: (TEXT, .99))
    monkeypatch.setattr(
        droid, "_ocr_region",
        lambda *a: calls.__setitem__("region", calls["region"] + 1) or [],
    )
    ret = droid.paste(TEXT)
    assert ret["hit"] is True
    assert ret["verify"] == "recognize"
    assert calls == {"dump": [True], "region": 0}


def test_paste_only_runs_detector_after_recognition_miss(monkeypatch):
    calls = {"region": 0}
    monkeypatch.setattr(droid, "_act", lambda **kw: {"ok": 1})
    monkeypatch.setattr(droid, "dump", lambda full=False: WECHAT_NODES)
    monkeypatch.setattr(droid, "shot", lambda: REAL_NUMPY_IMAGE)
    monkeypatch.setattr(droid, "ocr_text", lambda img: ("other", .99))
    monkeypatch.setattr(
        droid, "_ocr_region",
        lambda *a: calls.__setitem__("region", calls["region"] + 1)
        or [CLIP_LABEL, CLIP_BUBBLE],
    )
    ret = droid.paste(TEXT)
    assert ret["hit"] is False
    assert ret["ime_hint"]["text"] == TEXT
    assert calls["region"] == 1


def test_label_only_evidence_is_not_clickable_content(monkeypatch):
    monkeypatch.setattr(droid, "_act", lambda **kw: {"ok": 1})
    monkeypatch.setattr(droid, "dump", lambda full=False: WECHAT_NODES)
    monkeypatch.setattr(droid, "shot", lambda: REAL_NUMPY_IMAGE)
    monkeypatch.setattr(droid, "ocr_text", lambda img: ("other", .99))
    monkeypatch.setattr(droid, "_ocr_region", lambda *a: [CLIP_LABEL])
    ret = droid.paste(TEXT)
    assert ret["hit"] is False
    assert ret["ime_label"]["text"] == "来自剪贴板"
    assert "ime_hint" not in ret
    assert "标签" in ret["hint"]


def test_reviewer_fix_verification_shot_error_is_bounded_uncertainty(monkeypatch):
    monkeypatch.setattr(
        droid, "_act", lambda **kw: {"ok": 1, "action_id": "kept"}
    )
    monkeypatch.setattr(droid, "dump", lambda full=False: [])
    monkeypatch.setattr(
        droid, "shot",
        lambda: (_ for _ in ()).throw(
            RuntimeError("super-secret-token " + "x" * 500)
        ),
    )
    ret = droid.paste(TEXT)
    assert ret["action_id"] == "kept"
    assert ret["hit"] is False
    assert ret["uncertain"] is True
    assert ret["verify"] == "unavailable"
    assert 0 < len(ret["error"]) <= 160
    assert "super-secret-token" not in ret["error"]
    assert "接管" in ret["hint"]


def test_reviewer_fix_verification_ocr_text_error_is_uncertain(monkeypatch):
    monkeypatch.setattr(droid, "_act", lambda **kw: {"ok": 1})
    monkeypatch.setattr(droid, "dump", lambda full=False: WECHAT_NODES)
    monkeypatch.setattr(droid, "shot", lambda: REAL_NUMPY_IMAGE)
    monkeypatch.setattr(
        droid, "ocr_text",
        lambda img: (_ for _ in ()).throw(RuntimeError("recognizer failed")),
    )
    monkeypatch.setattr(droid, "_ocr_region", lambda *a: [])
    ret = droid.paste(TEXT)
    assert ret["hit"] is False
    assert ret["uncertain"] is True
    assert ret["verify"] == "unavailable"
    assert "ocr_text" in ret["error"]


def test_reviewer_fix_verification_region_error_is_uncertain(monkeypatch):
    monkeypatch.setattr(droid, "_act", lambda **kw: {"ok": 1})
    monkeypatch.setattr(droid, "dump", lambda full=False: WECHAT_NODES)
    monkeypatch.setattr(droid, "shot", lambda: REAL_NUMPY_IMAGE)
    monkeypatch.setattr(droid, "ocr_text", lambda img: ("other", .99))
    monkeypatch.setattr(
        droid, "_ocr_region",
        lambda *a: (_ for _ in ()).throw(RuntimeError("detector failed")),
    )
    ret = droid.paste(TEXT)
    assert ret["hit"] is False
    assert ret["uncertain"] is True
    assert ret["verify"] == "unavailable"
    assert "ocr_region" in ret["error"]


def test_reviewer_fix_verification_error_keeps_ime_hint(monkeypatch):
    monkeypatch.setattr(droid, "_act", lambda **kw: {"ok": 1})
    monkeypatch.setattr(droid, "dump", lambda full=False: WECHAT_NODES)
    monkeypatch.setattr(droid, "shot", lambda: REAL_NUMPY_IMAGE)
    monkeypatch.setattr(
        droid, "ocr_text",
        lambda img: (_ for _ in ()).throw(RuntimeError("recognizer failed")),
    )
    monkeypatch.setattr(
        droid, "_ocr_region", lambda *a: [CLIP_LABEL, CLIP_BUBBLE]
    )
    ret = droid.paste(TEXT)
    assert ret["hit"] is False
    assert ret["uncertain"] is True
    assert ret["verify"] == "unavailable"
    assert ret["ime_hint"]["text"] == TEXT
    assert "ime_hint" in ret["hint"]


def test_reviewer_fix_verification_clamps_edit_crop(monkeypatch):
    img = np.zeros((20, 30, 3), dtype=np.uint8)
    nodes = [{"b": "-10,-5,40,25", "edit": 1, "t": ""}]
    seen = {}
    monkeypatch.setattr(droid, "_act", lambda **kw: {"ok": 1})
    monkeypatch.setattr(droid, "dump", lambda full=False: nodes)
    monkeypatch.setattr(droid, "shot", lambda: img)
    def recognize(crop):
        seen["shape"] = crop.shape
        seen["size"] = crop.size
        return TEXT, .99
    monkeypatch.setattr(droid, "ocr_text", recognize)
    ret = droid.paste(TEXT)
    assert ret["hit"] is True
    assert seen == {"shape": (20, 30, 3), "size": 20 * 30 * 3}


def test_reviewer_fix_verification_preserves_action_errors(monkeypatch):
    monkeypatch.setattr(
        droid, "_act",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("action failed")),
    )
    with pytest.raises(RuntimeError, match="action failed"):
        droid.paste(TEXT)


def test_reviewer_fix_verification_preserves_baseexception(monkeypatch):
    class Cancelled(BaseException):
        pass

    monkeypatch.setattr(droid, "_act", lambda **kw: {"ok": 1})
    monkeypatch.setattr(droid, "dump", lambda full=False: [])
    monkeypatch.setattr(
        droid, "shot", lambda: (_ for _ in ()).throw(Cancelled())
    )
    with pytest.raises(Cancelled):
        droid.paste(TEXT)


def test_short_expected_text_requires_exact_match():
    assert droid._match("ok", "broken") is False
    assert droid._match("ok", "ok") is True


def test_clipboard_label_is_not_returned_as_clickable_hint():
    rows = [(CLIP_LABEL[0], "来自剪贴板", .99)]
    out = droid._classify_paste_rows(TEXT, rows, WECHAT_EDITS, H)
    assert out["hit"] is False
    assert "ime_hint" not in out
    assert out["ime_label"]["text"] == "来自剪贴板"


def test_clipboard_content_is_clickable_hint():
    rows = [(CLIP_LABEL[0], "来自剪贴板", .99),
            (CLIP_BUBBLE[0], TEXT, .99)]
    out = droid._classify_paste_rows(TEXT, rows, WECHAT_EDITS, H)
    assert out["hit"] is False
    assert out["ime_hint"]["text"] == TEXT


def test_reviewer_fix_clipboard_label_predicate_is_conservative():
    for label in ("来自剪贴板", " 来自 剪贴板 ： ",
                  "From clipboard", "  fRoM   ClIpBoArD: "):
        assert droid._is_clipboard_label(label) is True
    assert droid._is_clipboard_label("来自北京") is False
    assert droid._is_clipboard_label("From clipboard history") is False


def test_reviewer_fix_known_clipboard_labels_anchor_content_hint():
    for label in ("来自剪贴板", "  fRoM   ClIpBoArD: "):
        rows = [(CLIP_LABEL[0], label, .99), CLIP_BUBBLE]
        out = droid._classify_paste_rows(TEXT, rows, WECHAT_EDITS, H)
        assert out["hit"] is False
        assert out["ime_label"]["text"] == label
        assert out["ime_hint"]["text"] == TEXT


def test_reviewer_fix_ordinary_lai_zi_content_is_edit_hit_not_label():
    text = "来自北京的消息"
    rows = [(_box(160, 1475, 700, 1535), text, .99)]
    out = droid._classify_paste_rows(text, rows, WECHAT_EDITS, H)
    assert out["hit"] is True
    assert "ime_label" not in out
    assert "ime_hint" not in out


def test_reviewer_fix_unrelated_lai_zi_row_cannot_anchor_ime_hint():
    rows = [(_box(19, 1578, 213, 1622), "来自北京", .99),
            CLIP_BUBBLE]
    out = droid._classify_paste_rows(TEXT, rows, WECHAT_EDITS, H)
    assert out["hit"] is False
    assert "ime_label" not in out
    assert "ime_hint" not in out


def test_reviewer_fix_match_outside_edit_without_label_is_not_evidence():
    out = droid._classify_paste_rows(
        TEXT, [CLIP_BUBBLE], WECHAT_EDITS, H
    )
    assert out["ocr"][0]["hit"] is True
    assert out["hit"] is False
    assert "ime_label" not in out
    assert "ime_hint" not in out


def test_ocr_text_uses_shared_engine_recognizer(monkeypatch):
    img = object()
    engine = types.SimpleNamespace(recognize=lambda value: ("recognized", .97)
                                   if value is img else ("wrong", 0.0))
    monkeypatch.setattr(droid, "_ocr_engine", lambda: engine)
    assert droid.ocr_text(img) == ("recognized", .97)


def test_ppocr_recognize_runs_single_crop_without_detection():
    droid._bundle()
    from ppocr_engine import PPOCR

    img = object()
    seen = {}
    engine = object.__new__(PPOCR)

    def classify(crops):
        seen["classified"] = list(crops)
        return crops

    def recognize(crops):
        seen["recognized"] = list(crops)
        return [("crop text", .95)]

    engine.cls = classify
    engine.rec = recognize
    assert engine.recognize(img) == ("crop text", .95)
    assert seen == {"classified": [img], "recognized": [img]}


def test_ppocr_region_pads_and_drops_rows_from_padding():
    import numpy as np

    droid._bundle()
    from ppocr_engine import PPOCR

    class RegionPPOCR(PPOCR):
        def __init__(self):
            self.seen_shape = None

        def __call__(self, img):
            self.seen_shape = img.shape
            return [
                (np.array(_box(10, 10, 60, 40)), "inside", .9),
                (np.array(_box(10, 700, 60, 730)), "padding", .9),
            ]

    engine = RegionPPOCR()
    rows = engine.region(np.zeros((100, 200, 3), dtype=np.uint8))
    assert engine.seen_shape == (736, 736, 3)
    assert [row[1] for row in rows] == ["inside"]


def test_clipboard_bar_is_ime_hint_not_hit(monkeypatch):
    """提示条全文命中必须归 ime_hint 而非 hit(事故根因): 靠'来自剪贴板'标签锚定键盘区, 不依赖 a11y 窗口底。"""
    ret = _run_paste(monkeypatch, WECHAT_NODES, [CLIP_LABEL, CLIP_BUBBLE])
    assert ret["hit"] is False
    assert ret["ime_hint"]["text"] == TEXT                  # tap 目标=内容气泡而非"来自"标签
    assert "ime_hint" in ret["hint"]


def test_text_inside_edit_box_is_hit(monkeypatch):
    """文本真上屏(编辑框识别命中)立即返回，不再运行文本检测。"""
    inbox = (_box(160, 1475, 700, 1535), TEXT, 0.99)
    ret = _run_paste(monkeypatch, WECHAT_NODES, [inbox, CLIP_LABEL, CLIP_BUBBLE])
    assert ret["hit"] is True and ret["verify"] == "recognize"


def test_chat_bubble_echo_is_not_hit(monkeypatch):
    """正文区回显同文(历史消息气泡/搜索联想)不在扫描带内, 不算上屏。"""
    echo = (_box(200, 900, 800, 960), TEXT, 0.99)
    ret = _run_paste(monkeypatch, WECHAT_NODES, [echo])
    assert ret["hit"] is False and "①" in ret["hint"]


def test_no_edit_body_match_is_uncertain_not_hit(monkeypatch):
    """a11y 无可编辑框时，正文同文只能诊断，不能确认已上屏。"""
    nodes = [{"b": "0,0,%d,%d" % (W, 1570), "l": 0}]
    body = (_box(160, 800, 700, 860), TEXT, 0.99)
    ret = _run_paste(monkeypatch, nodes, [body])
    assert ret["hit"] is False
    assert ret["uncertain"] is True
    assert "未定位到输入框" in ret["hint"]


def test_dump_exception_remains_uncertain_not_confirmation(monkeypatch):
    body = (_box(160, 800, 700, 860), TEXT, 0.99)
    monkeypatch.setattr(droid, "_act", lambda **kw: {"ok": 1})
    monkeypatch.setattr(
        droid, "dump",
        lambda full=False: (_ for _ in ()).throw(RuntimeError("dump failed")),
    )
    monkeypatch.setattr(droid, "shot", lambda: REAL_NUMPY_IMAGE)
    monkeypatch.setattr(droid, "_ocr_region", _region_fake([body]))
    ret = droid.paste(TEXT)
    assert ret["hit"] is False
    assert ret["uncertain"] is True
    assert "读取失败" in ret["hint"]


def test_keyboard_closed_no_hit(monkeypatch):
    """键盘收起(无提示条)且文本全屏未命中 → hit=False + 恢复路径提示。"""
    nodes = [{"b": "0,0,%d,%d" % (W, H), "l": 0},
             {"b": "150,2100,850,2200", "edit": 1, "t": "", "l": 5}]
    ret = _run_paste(monkeypatch, nodes, [(_box(50, 50, 200, 90), "03:30", 0.9)])
    assert ret["hit"] is False and "长按输入框" in ret["hint"]


def test_clip_label_anchors_kb_top_over_adjustpan(monkeypatch):
    """真机契约: 微信 adjustPan 下 a11y 窗口底=屏高不可用, 全文气泡命中仍靠'来自'标签锚定归 ime_hint。"""
    ret = _run_paste(monkeypatch, WECHAT_NODES, [CLIP_LABEL, CLIP_BUBBLE])
    assert ret["hit"] is False and ret["ime_hint"]["text"] == TEXT


def test_dump_text_short_circuits_before_ocr(monkeypatch):
    """L1: dump 读到输入框文本 → 直接 hit, 绝不触发慢速 OCR。"""
    nodes = [{"b": "150,1500,850,1570", "edit": 1, "t": TEXT + "|", "l": 5}]
    monkeypatch.setattr(droid, "_act", lambda **kw: {"ok": 1})
    monkeypatch.setattr(droid, "dump", lambda full=False: nodes)
    monkeypatch.setattr(droid, "shot", lambda: (_ for _ in ()).throw(AssertionError("不应截图")))
    ret = droid.paste(TEXT)
    assert ret["hit"] is True and ret["verify"] == "dump"


def test_paste_verify_false_returns_action_without_verification(monkeypatch):
    monkeypatch.setattr(droid, "_act", lambda **kw: {"ok": 1, "action": "sent"})
    monkeypatch.setattr(
        droid, "dump",
        lambda full=False: (_ for _ in ()).throw(AssertionError("must not verify")),
    )
    assert droid.paste(TEXT, verify=False) == {"action": "sent"}


def test_ga_float_echo_filtered(monkeypatch):
    """GA 悬浮窗自述(如 'S32·\"gpt5.6...\"已输入')复述粘贴文案, 编辑框外不得计入命中。"""
    float_echo = (_box(30, 800, 900, 860), "S32·" + TEXT, 0.9)
    ret = _run_paste(monkeypatch, [{"b": "0,0,%d,1570" % W, "l": 0}], [float_echo])
    assert ret["hit"] is False


def test_s_prefix_inside_edit_box_still_hit(monkeypatch):
    """用户真要粘贴 'S32·…' 这类文本: 命中落在编辑框条带内时免疫回显过滤。"""
    t = "S32·" + TEXT
    inbox = (_box(160, 1478, 700, 1532), t, 0.99)
    ret = _run_paste(monkeypatch, WECHAT_NODES, [inbox], text=t)
    assert ret["hit"] is True


def test_ocr_region_delegates_padding_filtering_and_offsets(monkeypatch):
    """_ocr_region 只裁剪/偏移，padding 与幻影框过滤统一委托 PPOCR.region。"""
    img = np.zeros((H, W, 3), dtype=np.uint8)
    seen = {}
    def region(crop):
        seen["shape"] = crop.shape
        return [(_box(10, 10, 60, 40), "in", 0.9)]
    monkeypatch.setattr(
        droid, "_ocr_engine", lambda: types.SimpleNamespace(region=region)
    )
    rows = droid._ocr_region(img, 100, 1470, 800, 1540)
    assert seen["shape"] == (70, 700, 3)
    assert [r[1] for r in rows] == ["in"]
    assert rows[0][0][0] == [110, 1480]


def test_scroll_ignores_status_and_navigation_noise():
    before = np.zeros((H, W, 3), np.uint8)
    after = before.copy()
    after[:120] = 255
    after[2200:] = 255
    roi = (0, 120, W, 2200)
    assert droid._pixel_change_pct(before, after, roi) == 0


def test_scroll_verdict_requires_stable_pixel_change():
    assert droid._scroll_verdict(0, 20, 18) == "pixel"
    assert droid._scroll_verdict(0, 20, .2) == "none"


def test_scroll_text_evidence_requires_real_nodes():
    assert droid._text_change_ratio(["A"], ["B"]) is None
    assert droid._scroll_verdict(.5, None, None) == "text"


def test_scroll_dynamic_text_noise_is_not_evidence():
    before = ["A%d" % i for i in range(10)]
    after = ["B0"] + before[1:]
    ratio = droid._text_change_ratio(before, after)
    assert ratio == pytest.approx(.1)
    assert droid._scroll_verdict(ratio, 0, None) == "none"


def test_scroll_no_observation_is_uncertain(monkeypatch):
    monkeypatch.setattr(droid, "ping", lambda: {"w": W, "h": H, "pkg": "x"})
    monkeypatch.setattr(
        droid,
        "dump",
        lambda: (_ for _ in ()).throw(
            RuntimeError("super-secret-token " + "x" * 500)
        ),
    )
    monkeypatch.setattr(
        droid, "shot",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("shot")),
    )
    monkeypatch.setattr(droid, "swipe", lambda *a, **kw: {"ok": 1})
    ret = droid.scroll("up", settle=0)
    assert ret["scrolled"] is False
    assert ret["evidence"] == "none"
    assert ret["uncertain"] is True
    assert 0 < len(ret["error"]) <= 160
    assert "super-secret-token" not in ret["error"]
    assert "观察" in ret["hint"]


def test_scroll_verify_false_never_claims_success(monkeypatch):
    monkeypatch.setattr(droid, "ping", lambda: {"w": W, "h": H, "pkg": "x"})
    monkeypatch.setattr(droid, "swipe", lambda *a, **kw: {"ok": 1})
    ret = droid.scroll("up", verify=False)
    assert ret == {"ok": 1, "performed": True, "verified": False,
                   "finger_direction": "up", "view_direction": "down"}


def test_scroll_base_exception_propagates(monkeypatch):
    class Stop(BaseException):
        pass
    monkeypatch.setattr(droid, "ping", lambda: {"w": W, "h": H, "pkg": "x"})
    monkeypatch.setattr(
        droid, "dump", lambda: (_ for _ in ()).throw(Stop())
    )
    with pytest.raises(Stop):
        droid.scroll("up")


def test_scroll_ignores_legacy_package_and_requires_visual_change(monkeypatch):
    calls = []
    def status():
        calls.append(1)
        return {"w": W, "h": H, "pkg": "stale.launcher"}
    image = np.zeros((240, 120, 3), np.uint8)
    monkeypatch.setattr(droid, "ping", status)
    monkeypatch.setattr(droid, "dump", lambda: [])
    monkeypatch.setattr(droid, "shot", lambda **kw: image.copy())
    monkeypatch.setattr(droid, "swipe", lambda *a, **kw: {"ok": 1})
    ret = droid.scroll("up", settle=0)
    assert ret["scrolled"] is False
    assert ret["evidence"] == "none"
    assert not ({"pkg", "pkg_before", "fg"} & ret.keys())
    assert len(calls) == 1


@pytest.mark.parametrize(("times", "expected"), [(0, 1), (650, 10)])
def test_scroll_times_guard_is_preserved(monkeypatch, times, expected):
    calls = []
    monkeypatch.setattr(droid, "ping", lambda: {"w": W, "h": H, "pkg": "x"})
    monkeypatch.setattr(
        droid, "swipe",
        lambda *a, **kw: calls.append((a, kw)) or {"ok": 1},
    )
    ret = droid.scroll("up", times=times, verify=False, settle=0)
    assert len(calls) == expected
    assert ret["performed"] is True


def _scroll_px_case(monkeypatch, img_seq):
    """text 恒不变 + 指定截图序列 → scroll 判定结果。"""
    A = np.zeros((240, 120, 3), np.uint8)
    B = A.copy()
    B[60:170] = 200
    imgs = iter([{"A": A, "B": B}[c] for c in img_seq])
    same = [{"t": "A%d" % i} for i in range(10)]
    monkeypatch.setattr(droid, "dump", lambda: list(same))
    monkeypatch.setattr(droid, "ping", lambda: {"w": W, "h": H, "pkg": "x"})
    monkeypatch.setattr(droid, "swipe", lambda *a, **kw: {"ok": 1})
    monkeypatch.setattr(droid, "shot", lambda **kw: next(imgs))
    return droid.scroll("up", settle=0.0)


def test_scroll_pixel_beats_stale_a11y(monkeypatch):
    """真机契约(Flyme设置/WebView): a11y 树滞后文本恒判没变, 像素持续偏离 → 真滚 scrolled=True。"""
    ret = _scroll_px_case(monkeypatch, "ABB")     # before=A, 滚后稳定在 B
    assert ret["scrolled"] is True
    assert ret["evidence"] == "pixel"
    assert "uncertain" not in ret


def test_scroll_bounce_at_edge_not_scrolled(monkeypatch):
    """真机契约(到顶回弹): 像素短暂偏离后归位 → 不算滚动 scrolled=False。"""
    ret = _scroll_px_case(monkeypatch, "ABA")     # 回弹: 偏离 B 后回到 A
    assert ret["scrolled"] is False
    assert ret["evidence"] == "none"
    assert "uncertain" not in ret


def test_scroll_stable_shot_failure_is_uncertain(monkeypatch):
    A = np.zeros((240, 120, 3), np.uint8)
    B = A.copy()
    B[60:170] = 200
    frames = iter([A, B, RuntimeError("FLAG_SECURE")])
    same = [{"t": "A%d" % i} for i in range(10)]

    def fake_shot(**kw):
        frame = next(frames)
        if isinstance(frame, Exception):
            raise frame
        return frame

    monkeypatch.setattr(droid, "dump", lambda: list(same))
    monkeypatch.setattr(
        droid, "ping", lambda: {"w": W, "h": H, "pkg": "pkg.same"}
    )
    monkeypatch.setattr(droid, "shot", fake_shot)
    monkeypatch.setattr(droid, "swipe", lambda *a, **kw: {"ok": 1})
    ret = droid.scroll("up", settle=0)
    assert ret["scrolled"] is False
    assert ret["evidence"] == "none"
    assert ret["uncertain"] is True
    assert "观察" in ret["hint"]


def test_scroll_samples_geometry_once_and_stable_pixels(monkeypatch):
    A = np.zeros((240, 120, 3), np.uint8)
    B = A.copy()
    B[60:170] = 200
    same = [{"t": "A%d" % i} for i in range(10)]
    state = {"shots": 0, "pings": 0}

    def fake_shot(**kw):
        state["shots"] += 1
        return A if state["shots"] == 1 else B

    def fake_ping():
        state["pings"] += 1
        pkg = "pkg.after" if state["shots"] >= 3 else "pkg.before"
        return {"w": W, "h": H, "pkg": pkg}

    monkeypatch.setattr(droid, "dump", lambda: list(same))
    monkeypatch.setattr(droid, "ping", fake_ping)
    monkeypatch.setattr(droid, "shot", fake_shot)
    monkeypatch.setattr(droid, "swipe", lambda *a, **kw: {"ok": 1})
    ret = droid.scroll("up", settle=0)
    assert state == {"shots": 3, "pings": 1}
    assert ret["scrolled"] is True
    assert ret["evidence"] == "pixel"
    assert "pkg" not in ret and "pkg_before" not in ret


def test_scroll_without_package_uses_stable_pixel_evidence(monkeypatch):
    A = np.zeros((240, 120, 3), np.uint8)
    B = A.copy()
    B[60:170] = 200
    frames = iter([A, B, B])
    same = [{"t": "A%d" % i} for i in range(10)]
    monkeypatch.setattr(droid, "dump", lambda: list(same))
    monkeypatch.setattr(droid, "ping", lambda: {"w": W, "h": H})
    monkeypatch.setattr(droid, "shot", lambda **kw: next(frames))
    monkeypatch.setattr(droid, "swipe", lambda *a, **kw: {"ok": 1})
    ret = droid.scroll("up", settle=0)
    assert ret["scrolled"] is True
    assert ret["evidence"] == "pixel"
    assert "pkg" not in ret


def test_scroll_geometry_ping_failure_does_not_swipe(monkeypatch):
    calls = []
    monkeypatch.setattr(
        droid, "ping",
        lambda: (_ for _ in ()).throw(RuntimeError("ping failed")),
    )
    monkeypatch.setattr(
        droid, "swipe",
        lambda *a, **kw: calls.append((a, kw)) or {"ok": 1},
    )
    with pytest.raises(RuntimeError, match="geometry"):
        droid.scroll("up", verify=False, settle=0)
    assert calls == []


@pytest.mark.parametrize(
    "geometry",
    [
        {"pkg": "x"},
        {"w": 0, "h": H, "pkg": "x"},
        {"w": W, "h": -1, "pkg": "x"},
    ],
)
def test_scroll_invalid_geometry_does_not_swipe(monkeypatch, geometry):
    calls = []
    monkeypatch.setattr(droid, "ping", lambda: geometry)
    monkeypatch.setattr(
        droid, "swipe",
        lambda *a, **kw: calls.append((a, kw)) or {"ok": 1},
    )
    with pytest.raises(RuntimeError, match="geometry"):
        droid.scroll("up", verify=False, settle=0)
    assert calls == []


def test_scroll_shot_retries_known_code3_once(monkeypatch):
    import cv2
    import time

    image = np.full((8, 12, 3), 128, dtype=np.uint8)
    encoded = cv2.imencode('.png', image)[1].tobytes()
    calls, sleeps = [], []

    def fake_get(path, **kw):
        assert path == '/a11y/shot'
        calls.append(kw)
        if len(calls) == 1:
            raise RuntimeError("java.lang.RuntimeException: takeScreenshot failed code=3")
        return encoded

    monkeypatch.setattr(droid, "_get", fake_get)
    monkeypatch.setattr(time, "sleep", lambda sec: sleeps.append(sec))
    assert np.array_equal(droid._scroll_shot(), image)
    assert calls == [{"q": 45}, {"q": 45}]
    assert sleeps == [.35]


def test_scroll_shot_does_not_retry_nontransient_error(monkeypatch):
    import time

    calls, sleeps = [], []

    def fake_shot(**kw):
        calls.append(kw)
        raise RuntimeError("FLAG_SECURE")

    monkeypatch.setattr(droid, "shot", fake_shot)
    monkeypatch.setattr(time, "sleep", lambda sec: sleeps.append(sec))
    assert droid._scroll_shot() is None
    assert calls == [{"q": 45}]
    assert sleeps == []


def test_scroll_shot_base_exception_propagates(monkeypatch):
    class Stop(BaseException):
        pass

    monkeypatch.setattr(
        droid, "shot", lambda **kw: (_ for _ in ()).throw(Stop())
    )
    with pytest.raises(Stop):
        droid._scroll_shot()


# ── scroll 证据窗形态变化(旋转/折叠): 显式 uncertain, 绝不把树剧变误读成滚动 ──

def test_scroll_shape_change_suppresses_false_text_movement(monkeypatch):
    portrait = np.zeros((240, 120, 3), np.uint8)
    landscape = np.zeros((120, 240, 3), np.uint8)
    frames = iter([portrait, landscape])
    dumps = iter([
        [{"t": "A%d" % i} for i in range(10)],
        [{"t": "B%d" % i} for i in range(10)],   # 旋转后树剧变: text_ratio=1.0 假"滚动"
    ])
    monkeypatch.setattr(droid, "ping", lambda: {"w": W, "h": H, "pkg": "pkg.same"})
    monkeypatch.setattr(droid, "dump", lambda: next(dumps))
    monkeypatch.setattr(droid, "shot", lambda **kw: next(frames))
    monkeypatch.setattr(droid, "swipe", lambda *a, **kw: {"ok": 1})
    ret = droid.scroll("up", settle=0)
    assert ret["scrolled"] is False
    assert ret["evidence"] == "none"
    assert ret["uncertain"] is True
    assert "旋转/折叠" in ret["hint"]
    assert "ShapeChanged" in ret["error"]


def test_scroll_stable_window_shape_change_is_uncertain(monkeypatch):
    A = np.zeros((240, 120, 3), np.uint8)
    B = A.copy()
    B[60:170] = 200
    landscape = np.zeros((120, 240, 3), np.uint8)
    frames = iter([A, B, landscape])             # 稳态复核帧才旋转
    same = [{"t": "A%d" % i} for i in range(10)]
    monkeypatch.setattr(droid, "ping", lambda: {"w": W, "h": H, "pkg": "pkg.same"})
    monkeypatch.setattr(droid, "dump", lambda: list(same))
    monkeypatch.setattr(droid, "shot", lambda **kw: next(frames))
    monkeypatch.setattr(droid, "swipe", lambda *a, **kw: {"ok": 1})
    ret = droid.scroll("up", settle=0)
    assert ret["scrolled"] is False
    assert ret["uncertain"] is True
    assert "旋转/折叠" in ret["hint"]


def test_shape_changed_helper_ignores_missing_frames():
    A = np.zeros((240, 120, 3), np.uint8)
    L = np.zeros((120, 240, 3), np.uint8)
    assert droid._shape_changed(None, L) is False
    assert droid._shape_changed(A, None, None) is False
    assert droid._shape_changed(A, A.copy(), None) is False
    assert droid._shape_changed(A, A.copy(), L) is True
    assert droid._shape_changed(A, L, None) is True


# ── 敏感 App(微信)dump 门控: 强制 SOP/wechat-yolo「只走视觉路径」红线 ──
# 事故取材 2026-07-10 微信会话: paste(verify=True) 内部无条件 dump(full=True) 抓 a11y 整树
# (封号元凶), 一次会话跑了 9+ 次而 agent 无感。敏感前台必须跳过 dump, 只走 shot()+OCR。

def _track_dump(monkeypatch, fg):
    called = {"dump": 0}

    def _dump(full=False):
        called["dump"] += 1
        return []

    monkeypatch.setattr(droid, "_get", lambda path, **kw: {"visual_only": fg != "com.android.settings"})
    monkeypatch.setattr(droid, "dump", _dump)
    return called


def test_paste_skips_a11y_dump_on_sensitive_foreground(monkeypatch):
    called = _track_dump(monkeypatch, "com.tencent.mm")
    monkeypatch.setattr(droid, "_act", lambda **kw: {"ok": 1})
    monkeypatch.setattr(droid, "shot", lambda: REAL_NUMPY_IMAGE)
    monkeypatch.setattr(droid, "ocr_text", lambda img: ("", 0.0))
    monkeypatch.setattr(droid, "_ocr_region", lambda img, x1, y1, x2, y2: [])
    out = droid.paste(TEXT)
    assert called["dump"] == 0                 # 红线: 微信前台零 a11y 树读取
    assert out["hit"] is False
    assert out["uncertain"] is True            # 无 edit 框视觉路径 → 不确定, 不谎报上屏


def test_paste_uses_a11y_dump_on_normal_foreground(monkeypatch):
    called = _track_dump(monkeypatch, "com.android.settings")
    monkeypatch.setattr(droid, "_act", lambda **kw: {"ok": 1})
    monkeypatch.setattr(droid, "shot", lambda: REAL_NUMPY_IMAGE)
    monkeypatch.setattr(droid, "ocr_text", lambda img: ("", 0.0))
    monkeypatch.setattr(droid, "_ocr_region", lambda img, x1, y1, x2, y2: [])
    droid.paste(TEXT)
    assert called["dump"] == 1                 # 普通 App: dump 快路径不变


def test_scroll_skips_a11y_dump_on_sensitive_foreground(monkeypatch):
    called = _track_dump(monkeypatch, "com.tencent.mm")
    monkeypatch.setattr(
        droid, "ping", lambda: {"w": W, "h": H, "pkg": "com.tencent.mm"}
    )
    monkeypatch.setattr(droid, "swipe", lambda *a, **k: {"ok": 1})
    monkeypatch.setattr(droid, "_scroll_shot", lambda: REAL_NUMPY_IMAGE)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    droid.scroll("up", settle=0)
    assert called["dump"] == 0                 # 微信滚动只用像素证据, 零 a11y 树读取


def test_scroll_uses_a11y_dump_on_normal_foreground(monkeypatch):
    called = _track_dump(monkeypatch, "com.android.settings")
    monkeypatch.setattr(
        droid, "ping", lambda: {"w": W, "h": H, "pkg": "com.android.settings"}
    )
    monkeypatch.setattr(droid, "swipe", lambda *a, **k: {"ok": 1})
    monkeypatch.setattr(droid, "_scroll_shot", lambda: REAL_NUMPY_IMAGE)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    droid.scroll("up", settle=0)
    assert called["dump"] == 2                 # 普通 App: 前后各一次文本对比 dump


# Device status never reports a guessed app identity.
def test_ping_strips_legacy_identity(monkeypatch):
    monkeypatch.setattr(droid, "_get", lambda *a, **kw: {"pkg": "stale", "fg": "stale", "a11y": True, "w": W, "h": H})
    assert droid.ping() == {"a11y": True, "w": W, "h": H}
    assert not any(hasattr(droid, n) for n in ("_fg", "_wait_fg", "_resolve_fg"))


def test_missing_node_permission_fails_closed(monkeypatch):
    monkeypatch.setattr(droid, "_get", lambda *a, **kw: {})
    assert droid._visual_only() is True
    monkeypatch.setattr(droid, "_get", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("offline")))
    assert droid._visual_only() is True


def test_launch_does_not_poll_or_claim_foreground(monkeypatch):
    monkeypatch.setattr(droid, "_act", lambda **kw: {"ok": True})
    monkeypatch.setattr(droid, "ping", lambda: pytest.fail("launch must not query foreground"))
    ret = droid.launch("com.android.settings", wait=0)
    assert ret["request_sent"] is True
    assert ret["opened"] is None
    assert not any(k in ret for k in ("ok", "fg", "pkg"))


@pytest.mark.parametrize("ack", [{"ok": 0}, {}, None, {"ok": 1, "error": "blocked"}])
def test_launch_rejects_unconfirmed_request(monkeypatch, ack):
    monkeypatch.setattr(droid, "_act", lambda **kw: ack)
    with pytest.raises(RuntimeError, match="启动请求未获确认"):
        droid.launch("com.android.settings", wait=0)


def test_launch_preserves_transport_failure(monkeypatch):
    def fail(**kw):
        raise RuntimeError("offline")
    monkeypatch.setattr(droid, "_act", fail)
    with pytest.raises(RuntimeError, match="offline"):
        droid.launch("com.android.settings", wait=0)


def test_safe_mode_does_not_request_node_permission(monkeypatch):
    monkeypatch.setattr(droid, "SAFE_MODE", True)
    monkeypatch.setattr(droid, "_get", lambda *a, **kw: pytest.fail("safe mode must not read nodes"))
    assert droid._visual_only() is True
