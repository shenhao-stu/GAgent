"""Use production rowSheet/CSS to check long model menus on mobile viewports."""
import os
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / 'app/src/main/assets/ga_runtime/webui'


@pytest.mark.parametrize('peer', ['pc', 'phone-123'])
@pytest.mark.parametrize('height', [360, 800])
@pytest.mark.parametrize('count', [2, 80])
def test_pc_models_scroll_and_select(height, count, peer):
    pw = pytest.importorskip('playwright.sync_api')
    src = (WEB / 'pclink.js').read_text(encoding='utf-8')
    row_sheet = src[src.index('function rowSheet('):src.index('function bindLongPress(')]
    with pw.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"))
        page = browser.new_page(viewport={'width': 390, 'height': height}, has_touch=True)
        page.set_content('<meta name="viewport" content="width=device-width,initial-scale=1">')
        page.add_style_tag(content=(WEB / 'app.css').read_text(encoding='utf-8'))
        page.add_script_tag(content='''
          const IC_RESTORE='',IC_PIN_OFF='',IC_PIN='',IC_ARCH='';
          const metaOf=()=>({}),t=x=>x,track=()=>{},toast=()=>{},pollNow=()=>{};
          let selected=null,curPeer='phone-123',confirmClose=null,closed=false;
          const gaConfirm=(title,msg,cb)=>{confirmClose=cb},setPeer=p=>{curPeer=p};
          function api(method,path,body,cb){
            if(method==='GET')cb({items:Array.from({length:COUNT},(_,i)=>'Model '+i),cur:COUNT-1});
            else {selected=body.no;closed=body.text==='/exit';cb({})}
          }
        '''.replace('COUNT', str(count)) + row_sheet)
        def open_menu():
            page.evaluate("name=>rowSheet({name,title:'Session',caps:['llm']})", peer)
            page.wait_for_timeout(300)
        open_menu()
        sheet = page.locator('.pcSheet')
        bounds = sheet.bounding_box()
        assert bounds['y'] >= 0
        assert bounds['y'] + bounds['height'] <= height
        menu = page.locator('.pcSheetLlm')
        heading = menu.locator('.pcSheetSub')
        assert heading.evaluate('(e)=>getComputedStyle(e).fontSize') == '15px'
        assert heading.evaluate('(e)=>getComputedStyle(e).paddingLeft') == '18px'
        assert heading.evaluate('(e)=>getComputedStyle(e).fontWeight') == '640'
        if count > 2:
            assert menu.evaluate('(e)=>e.scrollHeight>e.clientHeight')
            assert menu.evaluate('(e)=>getComputedStyle(e).overflowY') == 'auto'
        # Click both ends without changing model ordering/index mapping.
        page.locator('.pcSheetLlm button').first.click()
        assert page.evaluate('selected') == 0
        page.wait_for_timeout(200)
        open_menu()
        cancel_top = page.locator('.pcSheetCancel').bounding_box()['y']
        menu.evaluate('(e)=>{e.scrollTop=e.scrollHeight}')
        assert abs(page.locator('.pcSheetCancel').bounding_box()['y'] - cancel_top) < 1
        page.locator('.pcSheetLlm button').last.click()
        assert page.evaluate('selected') == count - 1
        page.wait_for_timeout(200)
        open_menu()
        close_button = page.get_by_text('pcClose', exact=True)
        assert close_button.count() == (1 if peer.startswith('phone-') else 0)
        if close_button.count():
            close_button.click()
            assert page.evaluate('closed') is False
            page.evaluate('confirmClose()')
            assert page.evaluate('closed && curPeer===null')
        browser.close()
