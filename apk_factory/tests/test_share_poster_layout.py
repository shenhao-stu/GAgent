# -*- coding: utf-8 -*-
"""Share-poster layout contracts executed against the shipped JS module."""
import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
WEBUI = ROOT / "app" / "src" / "main" / "assets" / "ga_runtime" / "webui"
MODULE = WEBUI / "share_poster.js"
INDEX = WEBUI / "index.html"
APP_JS = WEBUI / "app.js"
APP_CSS = WEBUI / "app.css"


def _layouts(*pairs):
    script = (
        "const p=require(" + json.dumps(str(MODULE)) + ");"
        "const xs=" + json.dumps(pairs) + ";"
        "console.log(JSON.stringify(xs.map(x=>p.layout(x[0],x[1]))));"
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def _poster_html(view_ar, shot_ar):
    script = (
        "const p=require(" + json.dumps(str(MODULE)) + ");"
        f"const info={{viewAr:{view_ar},shotAr:{shot_ar},vw:1600,"
        "title:'我让 GA 替我跑完了一个任务',steps:8,ms:123000,"
        "autotip:'我只说了一句话',scrBg:'#111214'};"
        "const out=p.html({info,shotImg:'data:image/png;base64,AA',"
        "copy:{runTag:'真实运行 · 未剪辑',autoWord:'全程自动',"
        "stepsWord:'步',hook:'你也有想让 AI 替你干的活？',"
        "urlLine:'扫码把 GA 装进手机',privacy:'任务过程 · 已保密'},"
        "qrDataUrl:'data:image/png;base64,QR',host:'example.invalid',now:'09:41'});"
        "console.log(JSON.stringify(out));"
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def test_index_loads_share_module_before_app():
    text = INDEX.read_text(encoding="utf-8")
    assert text.index('src="share_poster.js"') < text.index('src="app.js"')


def test_layout_selects_profiles_and_preserves_canvas_ratio():
    ratios = [2.167, 1.25, 1.0, .75, .625, .55]
    layouts = _layouts(*[(ratio, ratio) for ratio in ratios])
    assert [item["mode"] for item in layouts] == [
        "portrait", "book", "book", "wide", "wide", "wide"
    ]
    for ratio, item in zip(ratios, layouts):
        assert item["canvasH"] / item["canvasW"] == pytest.approx(ratio, abs=1 / 1080)
        assert item["canvasAr"] == pytest.approx(ratio)


def test_profile_thresholds_are_exact():
    wide, book, portrait = _layouts((.8499, 1), (.85, 1), (1.35, 1))
    assert wide["mode"] == "wide"
    assert book["mode"] == "book"
    assert portrait["mode"] == "portrait"


def test_pura_x_max_uses_true_16_by_10_wide_profile():
    pura = _layouts((10 / 16, 10 / 16))[0]
    assert pura["mode"] == "wide"
    assert pura["canvasAr"] == pytest.approx(.625)
    assert pura["canvasH"] == 675


def test_layout_values_are_finite_bounded_and_ordered():
    layouts = _layouts((2.167, 2.167), (1, 1), (.625, .625))
    for item in layouts:
        assert item["canvasW"] == 1080
        assert 594 <= item["canvasH"] <= 2808
        assert 250 <= item["deviceWidth"] <= 460
        assert 4 <= item["framePad"] <= 10
        assert 12 <= item["frameRadius"] <= 36
        assert 8 <= item["screenRadius"] < item["frameRadius"]
        assert 24 <= item["titleSize"] <= 40
        assert 2 <= item["titleLines"] <= 3
        assert 76 <= item["qrSize"] <= 92


def test_invalid_ratios_have_deterministic_finite_fallback():
    script = (
        "const p=require(" + json.dumps(str(MODULE)) + ");"
        "const xs=[[0,0],[null,null],['bad',Infinity],[NaN,-1]];"
        "console.log(JSON.stringify(xs.map(x=>p.layout(x[0],x[1]))));"
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    layouts = json.loads(result.stdout)
    assert len({(x["mode"], x["canvasW"], x["canvasH"]) for x in layouts}) == 1
    assert layouts[0]["mode"] == "portrait"


@pytest.mark.parametrize(
    ("ratio", "mode"),
    [(2.167, "portrait"), (1.0, "book"), (.625, "wide")],
)
def test_html_uses_profile_class_and_finite_tokens(ratio, mode):
    html = _poster_html(ratio, ratio)
    assert f'class="poster poster--{mode}"' in html
    assert "NaN" not in html
    assert "undefined" not in html
    assert ".poster{--u:2px" not in html
    assert "--device-w:" in html
    assert "--frame-radius:" in html


def test_wide_html_uses_two_column_editorial_grid():
    wide = _poster_html(.625, .625)
    portrait = _poster_html(2.167, 2.167)
    assert "grid-template-areas:&quot;mast mast&quot;" not in wide
    assert "grid-template-rows:auto minmax(0,1fr) auto" in wide
    assert 'grid-template-areas:"mast mast" "copy hero" "foot hero"' in wide
    assert 'grid-template-areas:"mast" "copy" "hero" "foot"' in portrait


def test_trifold_band_uses_dense_tokens_and_pura_keeps_flagship():
    trifold, pura, wide = _layouts((.55, .55), (.625, .625), (.75, .75))
    assert trifold["dense"] is True
    assert trifold["titleSize"] == 24
    assert trifold["qrSize"] == 64
    assert pura["dense"] is False
    assert pura["titleSize"] == 28
    assert pura["qrSize"] == 76
    assert wide["dense"] is False
    assert 'class="poster poster--wide poster--dense"' in _poster_html(.55, .55)
    assert 'class="poster poster--wide"' in _poster_html(.75, .75)


def test_wide_meta_is_factual_only_and_meta_overflow_is_elided():
    wide = _poster_html(.625, .625)
    portrait = _poster_html(2.167, 2.167)
    assert "我只说了一句话" not in wide
    assert "我只说了一句话" in portrait
    for html in (wide, portrait):
        assert "text-overflow:ellipsis" in html


def test_device_stage_is_uncropped_and_has_no_toy_frame_artifacts():
    html = _poster_html(.625, .625)
    assert "object-fit:contain" in html
    assert "class=\"halo\"" not in html
    assert "phW=270" not in html
    assert "border-radius:calc(40" not in html
    assert html.count("box-shadow:") == 1


def test_pura_html_keeps_qr_and_device_as_primary_artifact():
    html = _poster_html(.625, .625)
    assert 'class="qr"' in html
    assert 'data:image/png;base64,QR' in html
    assert 'class="deviceStage"' in html
    assert 'class="device"' in html


def test_model_copy_is_html_escaped_before_rendering():
    script = (
        "const p=require(" + json.dumps(str(MODULE)) + ");"
        "const out=p.html({info:{viewAr:1,shotAr:1,vw:1000,"
        "title:'<img src=x onerror=alert(1)> GA',autotip:'<script>x</script>'},"
        "shotImg:'data:image/png;base64,AA',copy:{hook:'<b>hook</b>'},"
        "host:'example.invalid',now:'09:41'});console.log(JSON.stringify(out));"
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    html = json.loads(result.stdout)
    assert '<img src=x onerror=alert(1)>' not in html
    assert "<script>x</script>" not in html
    assert "<b>hook</b>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_app_delegates_layout_and_html_to_share_module():
    text = APP_JS.read_text(encoding="utf-8")
    assert "GASharePoster.layout(info.viewAr,info.shotAr)" in text
    assert "GASharePoster.html({" in text
    assert "profile.canvasW,profile.canvasH" in text


def test_app_preserves_real_wide_viewport_ratio():
    text = APP_JS.read_text(encoding="utf-8")
    assert "Math.max(.55,Math.min(2.6" in text
    assert "Math.max(.85,Math.min(2.6" not in text


def test_old_inline_poster_renderer_is_removed():
    text = APP_JS.read_text(encoding="utf-8")
    assert "function _statusBarSvg" not in text
    assert "function _isDarkBg" not in text
    assert "class=\"halo\"" not in text
    assert "const phW=270" not in text


def test_upstream_capture_and_refold_state_machine_remain():
    text = APP_JS.read_text(encoding="utf-8")
    for token in (
        "GA.captureChat(0,0,w,h,scale)",
        "ctx.refold=()=>",
        "const alive=(rep)=>",
        "genLong(++st.rep)",
        "GA.shareImage(d)",
    ):
        assert token in text


def test_share_preview_uses_paper_mat_not_black_gutters():
    css = APP_CSS.read_text(encoding="utf-8")
    assert "#shareMask{position:fixed;inset:0;background:#0a0a0a" not in css
    assert "--share-mat:#E7E5DE" in css
    assert "background:var(--share-mat)" in css
    assert "object-fit:contain" in css


def test_share_preview_controls_keep_48px_touch_targets():
    css = APP_CSS.read_text(encoding="utf-8")
    assert "#shareMask .sclose" in css and "width:48px;height:48px" in css
    assert "#shareMask .stab" in css and "min-height:48px" in css
    assert "#shareMask .shareBtns button" in css and "min-height:48px" in css


def test_longview_and_safe_area_contracts_remain():
    css = APP_CSS.read_text(encoding="utf-8")
    for token in (
        "#shareMask.longview .shareCard",
        "#shareMask.longview .shareImg",
        "env(safe-area-inset-top)",
        "env(safe-area-inset-bottom)",
    ):
        assert token in css


def _html_with_ms(ms):
    script = (
        "const p=require(" + json.dumps(str(MODULE)) + ");"
        f"const info={{viewAr:2.0,shotAr:2.0,vw:1600,title:'T',steps:8,ms:{ms},"
        "autotip:'我只说了一句话',scrBg:'#111214'};"
        "const out=p.html({info,shotImg:'data:image/png;base64,AA',"
        "copy:{runTag:'R',autoWord:'全程自动',stepsWord:'步',hook:'H',urlLine:'U',privacy:'P'},"
        "qrDataUrl:'',host:'example.invalid',now:'09:41'});"
        "console.log(out);"
    )
    return subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def test_duration_is_factual_across_ranges():
    # 亚秒时长不谎报 "00:00"(不渲染该项), 正常 MM:SS, ≥1h 进位为 H:MM:SS 而非假封顶 99:xx
    assert "00:00" not in _html_with_ms(400)
    assert "02:03" in _html_with_ms(123000)
    long_html = _html_with_ms(6000000)      # 100 分钟
    assert "1:40:00" in long_html
    assert "99:" not in long_html


def test_render_poster_guards_against_missing_module():
    # 模块缺失(OTA 分片热推未推新模块)时分享回退失败而非静默卡死 _shareBusy
    src = APP_JS.read_text(encoding="utf-8")
    assert "typeof GASharePoster==='undefined'" in src
