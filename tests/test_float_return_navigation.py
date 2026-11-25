"""Float return must route the displayed session through the existing launch contract."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "app/src/main/java/com/ljq/ga"
APP = ROOT / "app/src/main/assets/ga_runtime/webui/app.js"


def test_long_press_passes_displayed_session_and_reuses_activity():
    source = (JAVA / "FloatService.kt").read_text(encoding="utf-8")
    body = source.split("private fun backToApp() {", 1)[1].split("\n    }", 1)[0]
    assert '.putExtra("convo_cid", last?.optString("cid").orEmpty())' in body
    for flag in ("NEW_TASK", "SINGLE_TOP", "REORDER_TO_FRONT"):
        assert "Intent.FLAG_ACTIVITY_" + flag in body
    assert body.index("startActivity(") < body.index("stopSelf()")


def test_target_is_consumed_on_both_cold_and_warm_launch():
    source = (JAVA / "MainActivity.kt").read_text(encoding="utf-8")
    assert source.count('launchCid = intent?.getStringExtra("convo_cid").orEmpty()') == 2
    assert 'webCallbacks.raw("window.gaOpenConvo&&gaOpenConvo($jsCid)")' in source
    app = APP.read_text(encoding="utf-8")
    assert "window.gaOpenConvo(_li.cid)" in app
    assert app.index("window.gaOpenConvo(_li.cid)") > app.index("let liveC=")


def test_existing_js_router_selects_exact_target_and_ignores_missing_session():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required for WebView router behavior test")
    app = APP.read_text(encoding="utf-8")
    router = app.split("window.gaOpenConvo=function(cid){", 1)[1].split("\n};", 1)[0]
    script = """
const assert = require('node:assert/strict');
const window = {}, convos = [{id:'previous'}, {id:'float-target'}, {id:42}];
let curConvo = convos[0], opened = [];
function openConvo(c) { opened.push(c.id); curConvo = c; }
""" + "window.gaOpenConvo = function(cid){" + router + "\n};" + """
assert.equal(window.gaOpenConvo('float-target'), true);
assert.equal(curConvo, convos[1]);
assert.equal(window.gaOpenConvo('float-target'), true);
assert.deepEqual(opened, ['float-target']);
for (const id of ['', null, undefined, 'deleted']) {
    assert.equal(window.gaOpenConvo(id), false);
    assert.equal(curConvo, convos[1]);
}
assert.equal(window.gaOpenConvo('42'), true);
assert.equal(curConvo, convos[2]);
console.log('exact target, same target, missing target, numeric ID: passed');
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
