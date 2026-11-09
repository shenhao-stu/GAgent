"""Real DOM events against the voice controller; native bridge is a bounded fixture."""
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

VOICE = Path(__file__).parents[1] / 'app/src/main/assets/ga_runtime/webui/voice.js'


@pytest.fixture
def page():
    with sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.set_content('<textarea id="in"></textarea><button id="voiceBtn">Voice</button>'
                         '<textarea id="other"></textarea><button id="otherBtn">PC voice</button>'
                         '<button id="send">Send</button><div id="toast"></div>')
        page.evaluate('''() => {
          window.I18N={en:{},zh:{}}; window.t=k=>I18N.en[k]||k;
          window.toast=s=>document.getElementById('toast').textContent=s;
          window.calls=[];window.modelReady=true;window.nextError='';window.result={done:false};window.id=0;
          window.GA={
            offAsrStatus:()=>JSON.stringify({modelReady,dlState:'idle'}),
            offAsrDownload:()=>{calls.push(['download']);return '{"ok":true}'},
            offAsrStart:()=>{calls.push(['start']);return JSON.stringify(nextError?{ok:false,error:nextError}:{ok:true,id:++id})},
            offAsrPoll:i=>{calls.push(['poll',i]);return JSON.stringify(result)},
            offAsrStop:i=>{calls.push(['stop',i]);return '{"ok":true}'},
            offAsrCancel:i=>{calls.push(['cancel',i]);return '{"ok":true}'}
          };
        }''')
        page.add_script_tag(path=str(VOICE))
        page.evaluate("window.otherVoice=GAVoice.bind(document.getElementById('otherBtn'),{input:'other'})")
        yield page
        assert not errors
        browser.close()


def hold(page, button='#voiceBtn'):
    page.locator(button).dispatch_event('pointerdown', {'pointerId': 1, 'clientY': 300, 'button': 0})
    page.wait_for_function('calls.some(c=>c[0]==="start")')
    page.wait_for_timeout(320)


def release(page, button='#voiceBtn'):
    page.locator(button).dispatch_event('pointerup', {'pointerId': 1, 'clientY': 300})


def test_release_appends_to_current_draft_without_sending(page):
    page.locator('#in').fill('Before')
    hold(page)
    page.locator('#in').fill('Edited while recording')
    release(page)
    page.evaluate("result={done:true,text:'你好 hello'}")
    expect(page.locator('#in')).to_have_value('Edited while recording 你好 hello')
    assert page.evaluate('calls.some(c=>c[0]==="stop")')
    assert not page.evaluate('GAVoice.active()')


@pytest.mark.parametrize('cancel', ['short', 'slide', 'pointercancel', 'lostpointercapture', 'pagehide'])
def test_cancel_never_inserts_late_transcript(page, cancel):
    page.locator('#in').fill('Keep my draft')
    if cancel == 'short':
        page.locator('#voiceBtn').dispatch_event('pointerdown', {'pointerId': 1, 'clientY': 300})
    else:
        hold(page)
    if cancel == 'slide':
        page.locator('#voiceBtn').dispatch_event('pointermove', {'pointerId': 1, 'clientY': 200})
    if cancel in ('short', 'slide'):
        release(page)
    elif cancel == 'pagehide':
        page.evaluate("dispatchEvent(new Event('pagehide'))")
    else:
        page.locator('#voiceBtn').dispatch_event(cancel, {'pointerId': 1})
    page.evaluate("result={done:true,text:'must not appear'}")
    page.wait_for_timeout(400)
    expect(page.locator('#in')).to_have_value('Keep my draft')
    assert not page.evaluate('GAVoice.active()')


def test_other_composer_does_not_receive_old_owner_result(page):
    hold(page)
    page.evaluate('GAVoice.toggle(otherVoice)')
    page.wait_for_function('id===2')
    assert page.evaluate('calls.some(c=>c[0]==="cancel"&&c[1]===1)')
    page.evaluate("GAVoice.toggle(otherVoice);result={done:true,text:'PC only'}")
    expect(page.locator('#other')).to_have_value('PC only')
    expect(page.locator('#in')).to_have_value('')


def test_first_use_downloads_model_without_starting_microphone(page):
    page.evaluate('modelReady=false')
    page.locator('#voiceBtn').click()
    expect(page.locator('#toast')).to_contain_text('Downloading')
    assert page.evaluate('calls') == [['download']]
    page.evaluate('modelReady=true')
    expect(page.locator('#toast')).to_contain_text('ready')


def test_permission_denial_keeps_draft_and_allows_retry(page):
    page.locator('#in').fill('Untouched')
    page.evaluate("nextError='no_mic_permission'")
    hold(page)
    release(page)
    expect(page.locator('#toast')).to_contain_text('microphone access')
    expect(page.locator('#in')).to_have_value('Untouched')
    page.evaluate("nextError='';calls=[]")
    hold(page)
    release(page)
    page.evaluate("result={done:true,text:'Retry worked'}")
    expect(page.locator('#in')).to_have_value('Untouched Retry worked')


@pytest.mark.parametrize('event', ['pointercancel', 'lostpointercapture'])
def test_unrelated_pointer_cancel_does_not_cancel_the_active_recording(page, event):
    hold(page)
    page.locator('#voiceBtn').dispatch_event(event, {'pointerId': 99})
    assert page.evaluate('GAVoice.active()')
    assert not page.evaluate('calls.some(c=>c[0]==="cancel")')
    page.locator('#voiceBtn').dispatch_event(event, {'pointerId': 1})
    assert not page.evaluate('GAVoice.active()')
    assert page.evaluate('calls.some(c=>c[0]==="cancel"&&c[1]===1)')
