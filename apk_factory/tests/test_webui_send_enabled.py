# -*- coding: utf-8 -*-
"""Static regression tests for the WebView send button enablement contract.

The Meizu WebView regression was: native GA.ready() already returned "ok", but the
send button stayed disabled because the prompt input handler only resized the box.
These tests keep the small JS abstraction from regressing back into scattered
``btn.disabled`` writes.
"""
import re
from pathlib import Path


APP_JS = Path(__file__).resolve().parents[2] / "app" / "src" / "main" / "assets" / "ga_runtime" / "webui" / "app.js"


def _src():
    return APP_JS.read_text(encoding="utf-8")


def _func_body(src, name):
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", src)
    assert m, "missing function %s" % name
    i = m.end()
    depth = 1
    j = i
    while j < len(src) and depth:
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
        j += 1
    assert depth == 0, "unterminated function %s" % name
    return src[i:j - 1]


def test_send_enabled_has_single_ready_gate():
    src = _src()
    assert "let sendReady=false" in src
    body = _func_body(src, "sendEnabledState")
    assert "GA.ready()" in body
    assert "sendReady=(r==='ok'||r==='nokey')" in body.replace(" ", "")
    assert "sendReady=false" in body.replace(" ", "")
    assert "returnrunning||sendReady" in body.replace(" ", "")

    apply_body = _func_body(src, "applySendEnabled")
    compact = apply_body.replace(" ", "")
    assert "btn.disabled=!sendEnabledState()" in compact
    assert "aria-disabled" in apply_body
    assert "return!btn.disabled" in compact


def test_prompt_input_recomputes_send_enabled_after_resize():
    src = _src()
    assert re.search(
        r"inp\.addEventListener\('input',\s*\(\)\s*=>\s*\{[^}]*inp\.style\.height[^}]*applySendEnabled\(\)",
        src,
        re.S,
    ), "prompt input must resize and then recompute send enabled state"


def test_running_attachments_model_and_boot_all_use_gate():
    src = _src()
    assert "function updateSendEnabled(){return applySendEnabled()}" in src
    switch = _func_body(src, "switchBackendModel")
    assert switch.index("GA.selectModel(") < switch.index("applySendEnabled()")
    assert "applySendEnabled();applyI18n()" in src

    set_running = _func_body(src, "setRunning")
    assert "applySendEnabled()" in set_running

    render_attach = _func_body(src, "renderAttachRow")
    assert "updateSendEnabled()" in render_attach


def test_no_global_send_button_force_enable_remains():
    src = _src()
    assert "btn.disabled=false" not in src
    assert src.count("btn.disabled=") == 2, "only the send gate and unrelated year range dropdown may assign disabled"
