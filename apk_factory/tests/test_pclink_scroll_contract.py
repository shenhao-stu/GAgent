# -*- coding: utf-8 -*-
"""Static regression tests for PC Link scroll lifecycle semantics.

The 2026-08-26 regression merged peer switches, first/new task placement and
same-task streaming into one bottom-follow transaction.  That leaked read mode
between peers and skipped the established "new reply starts at viewport top"
behavior.  These assertions keep the three cases separate.
"""
import re
from pathlib import Path


WEBUI = Path(__file__).resolve().parents[2] / "app" / "src" / "main" / "assets" / "ga_runtime" / "webui"
PCLINK_JS = WEBUI / "pclink.js"
APP_CSS = WEBUI / "app.css"


def _src():
    return PCLINK_JS.read_text(encoding="utf-8")


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


def _compact(text):
    return re.sub(r"\s+", "", text)


def test_peer_switch_resets_scroll_mode_and_cancels_old_transactions():
    body = _compact(_func_body(_src(), "setPeer"))
    assert "b._pcPinSeq=(b._pcPinSeq||0)+1" in body
    assert "b._pcStick=true" in body
    assert "b._pcUserScroll=false" in body
    assert body.index("b._pcPinSeq=") < body.index("skel(b)")


def test_new_task_pins_top_without_running_bottom_settlement_afterwards():
    src = _src()
    pin = _compact(_func_body(src, "pcPinTaskTop"))
    assert "constseq=(box._pcPinSeq||0)+1;box._pcPinSeq=seq" in pin
    assert "box._pcUserScroll=false;box._pcStick=false" in pin
    assert "alignTop(box,el,6)" in pin
    assert "box._pcPinSeq" in pin

    paint = _compact(_func_body(src, "paint"))
    branch = re.search(r"if\(grew&&lastW\)\{([^}]*)\}", paint)
    assert branch, "new task must have an explicit placement branch"
    assert "pcPinTaskTop(box,lastW);done();return" in branch.group(1)
    assert "settleScroll" not in branch.group(1)
    assert paint.count("pcPinTaskTop(box,lastW)") == 2, "both whole-list replacement and append must pin the newest task"


def test_same_task_streaming_keeps_scroll_transaction_and_close_cancels_it():
    src = _src()
    paint = _compact(_func_body(src, "paint"))
    assert "constsettleScroll=pcScrollTxn(box)" in paint
    assert "patchLiveTask(w,tk)" in paint
    assert "pcFitTail(box,existing[tasks.length-1]);finish()" in paint

    txn = _compact(_func_body(src, "pcScrollTxn"))
    assert "if(!follow){box.scrollTop=top;pcSyncDown(box);return}" in txn

    fit = _compact(_func_body(src, "pcFitTail"))
    assert "box._pcStick!==false" in fit
    assert "--pcTail','0px'" in fit

    close = _compact(_func_body(src, "closeView"))
    assert "box._pcPinSeq=(box._pcPinSeq||0)+1" in close


def test_explicit_bottom_navigation_drops_alignment_tail():
    src = _compact(_src())
    assert "dn.onclick=()=>{box._pcStick=true;box._pcPinSeq++;box.style.setProperty('--pcTail','0px');box.scrollTop=box.scrollHeight}" in src


def test_tail_spacer_is_part_of_pc_message_padding_only():
    css = _compact(APP_CSS.read_text(encoding="utf-8"))
    assert "#pcMsgs{flex:1;overflow-y:auto;padding:var(--sp-4)var(--sp-4)calc(var(--sp-4)+var(--pcTail,0px));" in css
