"""Pairing input and failed unlink responses must preserve their actual meaning."""
import json
import shutil
import subprocess

import pytest

from .test_pclink_reconnect import CORE
from .test_pclink_scroll_contract import _func_body


def _run(functions, script):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for JS behavior tests')
    source = (CORE / 'webui/pclink.js').read_text(encoding='utf-8')
    code = '\n'.join('function %s(%s){%s}' % (name, args, _func_body(source, name))
                     for name, args in functions.items())
    result = subprocess.run([node, '-e', code + '\n' + script],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('payload,expected', [
    ('ga-pclink:v1:123456789', '123456789'),
    (' GA-PCLINK:V1:123456789 ', '123456789'),
    ('123456789', '123456789'),
    ('123 456 789', '123456789'),
    ('123-456-789', '123456789'),
    ('ga-pclink:v1:12345678', None),
    ('ga-pclink:v2:12345678', None),
    ('ga-pclink:v2:123456789', None),
    ('https://example.invalid/123456789', None),
    ('arbitrary text 123456789', None),
    ('12345678', None),
    ('1234567890', None),
])
def test_pairing_payload_does_not_extract_codes_from_unrelated_content(payload, expected):
    script = 'require("assert").strictEqual(parsePairPayload(%s), %s)' % (
        json.dumps(payload), json.dumps(expected))
    _run({'parsePairPayload': 'raw'}, script)


@pytest.mark.parametrize('error,expired', [
    ('short-code server rejected request: 410 code expired', True),
    ('short-code server rejected request: 503 unavailable', False),
    ('short-code server unreachable (TimeoutError: timed out)', False),
])
def test_expired_pairing_code_requests_a_fresh_code_without_marking_connected(error, expired):
    script = r'''
const assert=require('assert');
let paired=false,connected=false,notices=[];
const t=k=>k,toast=s=>notices.push(s),track=()=>{};
const renderRow=()=>assert.fail('failed pairing must not update connected UI');
const showFab=renderRow;
const call=(command,callback)=>callback({ok:0,error:ERROR});
doPair('123456789','qr');
assert.equal(paired,false);assert.equal(connected,false);
assert.equal(notices.length,2);
assert.equal(notices[1].includes('pcCodeExpired'),EXPIRED);
if(EXPIRED)assert(!notices[1].includes('short-code'));
'''.replace('ERROR', json.dumps(error)).replace('EXPIRED', json.dumps(expired))
    _run({'doPair': 'code,via'}, script)


@pytest.mark.parametrize('response,success', [
    ({'ok': 1, 'paired': False, 'connected': False}, True),
    ({'ok': 0, 'error': 'timeout'}, False),
    ({'ok': 0, 'error': 'bridge'}, False),
    ({}, False),
    (None, False),
])
def test_unlink_updates_state_only_after_success(response, success):
    script = r'''
const assert=require('assert');
let configError='',paired=true,connected=true,notices=[],events=[],rendered=0,fabUpdates=0;
const t=k=>k,toast=s=>notices.push(s),track=e=>events.push(e);
const renderRow=()=>rendered++,showFab=()=>fabUpdates++;
const gaConfirm=(title,message,accept)=>accept();
const call=(command,callback)=>{assert.equal(command,'/pclink.unpair');callback(RESPONSE)};
onRowTap();
assert.equal(paired,!SUCCESS);assert.equal(connected,!SUCCESS);
assert.equal(rendered,Number(SUCCESS));assert.equal(fabUpdates,Number(SUCCESS));
assert.deepEqual(events,SUCCESS?['pclink_unpair']:[]);
assert.equal(notices.length,1);
if(SUCCESS)assert.equal(notices[0],'pcUnpair');
else assert(notices[0].startsWith('pcUnpairFail'));
'''.replace('RESPONSE', json.dumps(response)).replace('SUCCESS', json.dumps(success))
    _run({'onRowTap': ''}, script)


@pytest.mark.parametrize('result', ['no-camera', 'err:camera unavailable'])
def test_failed_scanner_launch_reports_error_and_removes_callback(result):
    script = r'''
const assert=require('assert');
const notices=[],window={},t=k=>k,toast=s=>notices.push(s);
const GA={scanQr:()=>RESULT};
startScan();
assert.equal(window.gaQrResult,undefined);
assert.equal(notices.length,1);
assert.equal(notices[0],RESULT==='no-camera'?'pcScanNoCam':'pcPairFail'+RESULT);
'''.replace('RESULT', json.dumps(result))
    _run({'startScan': ''}, script)


@pytest.mark.parametrize('result', ['ok', 'need-perm'])
def test_scanner_waits_for_native_result_and_pairs_only_once(result):
    script = r'''
const assert=require('assert');
const notices=[],pairs=[],window={},t=k=>k,toast=s=>notices.push(s);
const GA={scanQr:()=>RESULT},doPair=(code,via)=>pairs.push([code,via]);
startScan();
assert.equal(typeof window.gaQrResult,'function');
assert.equal(pairs.length,0);
window.gaQrResult('ga-pclink:v1:123456789');
assert.deepEqual(pairs,[['123456789','qr']]);
assert.equal(window.gaQrResult,undefined);
'''.replace('RESULT', json.dumps(result))
    _run({'parsePairPayload': 'raw', 'startScan': ''}, script)
