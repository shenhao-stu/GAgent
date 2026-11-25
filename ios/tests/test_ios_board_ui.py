"""Exercise the real PC toolbar and iOS settings bridge in Chromium."""
import re
from pathlib import Path

import pytest
from signed_runtime import HOST

ROOT = Path(__file__).resolve().parents[2]
WEB = HOST / "webui"


@pytest.fixture
def page():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser.new_page(viewport={"width": 390, "height": 844})
        browser.close()


def test_ios_quick_actions_keep_screenshot_and_fill_draft(page):
    source = (WEB / "pclink.js").read_text()
    view = source[source.index("function ensureView(){"):source.index("\nfunction bgPoll(){")]
    icons = [re.search(r"const %s=.*?;\n" % name, text).group(0) for name, text in
             (("IOS_COMPOSE_ICON", (WEB / "ios_ui.js").read_text()), ("SVG_PHONE", source))]
    page.set_content('<meta name="viewport" content="width=device-width,initial-scale=1">')
    page.add_style_tag(content=(WEB / "app.css").read_text())
    page.add_script_tag(content="".join(icons) + """
        const IS_IOS=true;
        const t=key=>({pcNewComputer:'新建电脑会话',newChat:'新对话',iosSwitchPhone:'切换到本机对话',iosThisPhone:'本机'})[key]||key;
        window.GA={platform:'ios',appVersion:()=>'{"name":"0.9","code":2610230048}'};
        const GA=window.GA;
        let pcVoice=null, peerRun=false;
        const syncFab=()=>{},scheduleVisible=()=>{},closeSwipe=()=>{},updatePcSend=()=>{},bindPCVoice=()=>{};
        function applyI18n(){document.querySelectorAll('[data-i18n]').forEach(e=>{
          e.textContent=({pcQcCont:'继续',pcQcProg:'现在进展如何？',pcQcShot:'截个图',pcQcSum:'总结一下结果'})[e.dataset.i18n]||e.dataset.i18n;
        })}
    """ + view + "ensureView().classList.add('on');")
    chips = page.locator(".pcChip")
    assert chips.all_text_contents() == ["继续", "现在进展如何？", "截个图", "总结一下结果"]
    page.locator('[data-i18n="pcQcShot"]').click()
    assert page.locator("#pcIn").input_value() == "截个图"
    assert page.locator(".pcVerChip").count() == 0
    create = page.get_by_role("button", name="新建电脑会话", exact=True)
    assert create.inner_text() == "" and create.locator("svg").count() == 1
    local = page.get_by_role("button", name="切换到本机对话", exact=True)
    assert local.inner_text() == "本机"
    assert local.evaluate("e => e.nextElementSibling.id") == "pcNewBtn"


def test_ios_settings_show_version_and_board_entry(page):
    page.set_content((WEB / "index.html").read_text())
    page.evaluate("""() => {
      window.calls=[];
      window.prompt=(_,args)=>{const call=JSON.parse(args);calls.push(call);
        return call.fn==='appVersion'?'{"name":"0.9","code":2610230048}':'ok'};
    }""")
    page.add_script_tag(content=(ROOT / "ios/GAgent/ios_bridge.js").read_text())
    page.add_script_tag(content=(WEB / "ios_settings.js").read_text())
    page.evaluate("""() => {
        window.$ = id => document.getElementById(id);
        window.isIOSClient = () => true;
        window.iosConfigureSettingsChrome = () => {};
        initIOSSettings();
    }""")
    assert "0.9" in page.locator("#iosAppVersion").inner_text()
    assert "2610230048" in page.locator("#iosAppVersion").inner_text()
    page.locator("#iosBoardSetup").evaluate("e=>e.click()")
    assert page.evaluate("calls.some(c=>c.kind==='native' && c.fn==='boardSetup')")
    assert page.locator("#userPanel").count() == 0
