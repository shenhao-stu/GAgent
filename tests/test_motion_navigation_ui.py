"""System back closes only the topmost open layer; transitions stay interruptible and leave no residue."""
import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

WEB = Path(__file__).parents[1] / 'app/src/main/assets/ga_runtime/webui'
STUB = '''
  window.GA=new Proxy({ready:()=> 'ok', poll:()=> '{}', isDark:()=>false,
    send:(c)=>c==='/integrations.get'?'{}':c==='/config'?'{"ok":true,"items":[]}':
      c==='/detector.status'?'{"ok":true,"installed":false,"bytes":0}':c.startsWith('/kv.get ')?'':'{}'
  },{get:(t,k)=>t[k]||(()=> '{}')});
'''
# Which registered layer (if any) receives a tap at the viewport centre.
HIT = '''()=>{const e=document.elementFromPoint(innerWidth/2,innerHeight/2);
  const l=e&&e.closest('#setv,#modelv,#sheetMask,.sheet,#mask,#drawer,#modalMask,#detectorDialog,#pcSheetWrap');return l?(l.id||l.className):''}'''
PANEL_ANIMATIONS = "document.getAnimations().filter(a=>a.effect&&a.effect.target&&/Panel$/.test(a.effect.target.id)).length"


def open_page(engine, *, reduced=False, agree=True):
    browser = engine.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
    page = browser.new_page(viewport={'width': 390, 'height': 844}, locale='en',
                            reduced_motion='reduce' if reduced else 'no-preference')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('http**://**', lambda route: route.abort())
    page.add_init_script(STUB)
    page.goto((WEB / 'index.html').as_uri())
    if agree:
        page.locator('.pcAgree').click()
    return browser, page, errors


def test_pick_back_is_topmost_open_layer():
    with sync_playwright() as engine:
        browser, page, errors = open_page(engine)
        pick = page.evaluate('''()=>[
          gaPickBack([{id:'a',z:60,seq:0,open:true},{id:'b',z:125,seq:1,open:true},{id:'c',z:200,seq:2,open:false}]).id,
          gaPickBack([{id:'a',z:70,seq:0,open:true},{id:'b',z:70,seq:1,open:true}]).id,
          gaPickBack([{id:'a',z:70,seq:0,open:false}])]''')
        assert pick == ['b', 'b', None]
        assert not errors
        browser.close()


def test_back_on_first_run_consent_returns_to_system_and_keeps_consent():
    with sync_playwright() as engine:
        browser, page, errors = open_page(engine, agree=False)
        page.locator('#modalMask.on .pcAgree').wait_for(state='visible', timeout=2000)   # entrance animation: sample after it starts
        assert page.evaluate('gaOnBack()') is False
        assert page.locator('#modalMask.on .pcAgree').is_visible()
        page.locator('.pcAgree').click()
        assert page.evaluate('gaOnBack()') is False   # nothing open after boot: back leaves the app
        assert not errors
        browser.close()


@pytest.mark.parametrize('reduced', [False, True])
def test_rapid_back_steps_down_one_layer_at_a_time(reduced):
    with sync_playwright() as engine:
        browser, page, errors = open_page(engine, reduced=reduced)
        page.evaluate("openSettings();setNav('dataPanel','Data');openSheet('modelSheet');openSheet('failoverSheet')")
        assert page.evaluate('[gaOnBack(),gaOnBack()]') == [True, True]
        assert page.evaluate("[...document.querySelectorAll('.sheet.on')].length") == 0
        assert page.evaluate('setStack.map(x=>x.panel)') == ['homePanel', 'dataPanel']
        page.evaluate("openDetector()")
        page.evaluate("openDetector()")
        assert page.locator('#detectorDialog').count() == 1
        assert page.evaluate('gaOnBack()') is True
        assert page.locator('#detectorDialog').count() == 0
        assert page.evaluate('setStack.map(x=>x.panel)') == ['homePanel', 'dataPanel']
        assert page.evaluate('[gaOnBack(),gaOnBack(),gaOnBack()]') == [True, True, False]
        assert page.evaluate(HIT) == ''             # settings is still sliding out, yet taps reach the page beneath
        page.wait_for_timeout(450)
        assert page.evaluate(HIT) == ''
        assert page.evaluate(PANEL_ANIMATIONS) == 0
        assert not errors
        browser.close()


def test_failover_back_button_returns_to_model_sheet():
    with sync_playwright() as engine:
        browser, page, errors = open_page(engine)
        page.evaluate("openSheet('modelSheet');openSheet('failoverSheet')")
        page.locator('#failoverSheet .foBack').click()
        assert page.evaluate("[...document.querySelectorAll('.sheet.on')].map(s=>s.id)") == ['modelSheet']
        page.locator('#sheetMask').click(position={'x': 20, 'y': 20})
        assert page.evaluate("[...document.querySelectorAll('.sheet.on')].length") == 0
        assert not errors
        browser.close()


def test_settings_restores_parent_scroll_and_never_opens_hidden_drawer():
    with sync_playwright() as engine:
        browser, page, errors = open_page(engine, reduced=True)
        page.set_viewport_size({'width': 390, 'height': 420})
        page.evaluate("openSettings()")
        body = "document.querySelector('#setv .setbody')"
        page.evaluate(f"{body}.scrollTop=180")
        start = page.evaluate(f"{body}.scrollTop")
        assert start > 0
        page.evaluate("setNav('dataPanel','Data')")
        assert page.evaluate(f"{body}.scrollTop") == 0
        page.evaluate('gaOnBack()')
        assert page.evaluate(f"{body}.scrollTop") == start
        assert page.evaluate('document.getAnimations().filter(a=>a.playState==="running"&&a.effect&&a.effect.target&&/Panel$/.test(a.effect.target.id)).length') == 0
        page.evaluate("closeSettings();PCLINK.openView()")
        assert page.evaluate('gaPanelOpen()') is True   # edge swipe must not open a drawer beneath the PC view
        assert page.evaluate('gaOnBack()') is True
        assert page.evaluate("document.getElementById('drawer').classList.contains('on')") is False
        assert not errors
        browser.close()


def test_interrupted_settings_navigation_settles_on_the_last_request():
    with sync_playwright() as engine:
        browser, page, errors = open_page(engine)
        page.evaluate("openSettings()")
        page.wait_for_timeout(80)
        page.evaluate("closeSettings()")
        page.wait_for_timeout(40)
        page.evaluate("openSettings();setNav('dataPanel','Data')")
        page.wait_for_timeout(60)
        page.evaluate("gaOnBack();setNav('statsPanel','Stats')")
        page.wait_for_timeout(500)
        assert page.evaluate('setStack.map(x=>x.panel)') == ['homePanel', 'statsPanel']
        shown = page.evaluate("['homePanel','dataPanel','statsPanel'].filter(id=>getComputedStyle(document.getElementById(id)).display!=='none')")
        assert shown == ['statsPanel']
        assert page.evaluate("getComputedStyle(document.getElementById('setv')).transform") in ('none', 'matrix(1, 0, 0, 1, 0, 0)')
        assert page.evaluate(PANEL_ANIMATIONS) == 0   # interrupted enters were cancelled; the last one finished without fill
        assert not errors
        browser.close()


def test_reopened_lower_sheet_is_drawn_on_top():
    with sync_playwright() as engine:
        browser, page, errors = open_page(engine)
        page.evaluate("openSheet('themeSheet');openSheet('modelSheet');openSheet('themeSheet')")
        z = page.evaluate("['themeSheet','modelSheet'].map(id=>+getComputedStyle(document.getElementById(id)).zIndex)")
        assert z[0] > z[1]
        page.evaluate('gaOnBack()')
        assert page.evaluate("[...document.querySelectorAll('.sheet.on')].map(s=>s.id)") == ['modelSheet']
        assert not errors
        browser.close()
