import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect
WEB=Path(__file__).parents[1]/'app/src/main/assets/gacore/webui'


@pytest.mark.parametrize('language',['en','zh'])
def test_local_settings_import_and_update_actions(language):
    with sync_playwright() as engine:
        browser=engine.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page=browser.new_page(locale=language)
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.add_init_script('''
        window.opened=[];window.commands=[];window.kv={};
        window.GA=new Proxy({ready:()=> 'nokey',poll:()=> '{}',isDark:()=>false,
          appVersion:()=>JSON.stringify({name:'test',code:138,packageName:'io.github.shenhaostu.gagent.debug',updatesConfigured:false,repositoryUrl:'https://github.com/shenhao-stu/GAgent'}),
          openUrl:url=>opened.push(url),saveUpload:()=>'/fixture/uploads/model.onnx',
          send:cmd=>{commands.push(cmd);
            if(cmd==='/config')return '{"ok":true,"items":[]}';
            if(cmd==='/detector.status')return '{"ok":true,"installed":false}';
            if(cmd.startsWith('/detector.install ')||cmd==='/detector.test')return '{"job":"42"}';
            if(cmd==='/jobresult 42')return JSON.stringify({pending:false,result:JSON.stringify({ok:true,installed:true,icons:7,text:4,width:1008,height:2244,elapsed_ms:500})});
            if(cmd.startsWith('/kv.get '))return kv[cmd.slice(8)]||'';
            if(cmd.startsWith('/kv.set ')){const r=cmd.slice(8),i=r.indexOf(' ');kv[r.slice(0,i)]=r.slice(i+1);return 'ok'}
            return '{}';}
        },{get:(t,k)=>t[k]||(()=> '{}')});
        ''')
        page.goto((WEB/'index.html').as_uri());page.locator('.pcAgree').click()
        expect(page.locator('#provListPanel')).to_be_visible()
        assert page.locator('[onclick="doLogout()"]').count()==0
        assert page.evaluate("setUserAvatar('person',{sync:false})") is True
        assert 'gagent.debug' in page.evaluate('apGrantFallback()')
        page.evaluate('openSettings();openUpdatePage();renderUpdatePage()')
        assert not page.locator('#swOtaBeta').is_visible()
        page.locator('#rowDoUpdate').click()
        assert page.evaluate('opened')==['https://github.com/shenhao-stu/GAgent/releases']
        page.evaluate('openSettings();openDetector()')
        modal=page.locator('#detectorDialog')
        modal.locator('input').set_input_files({'name':'model.onnx','mimeType':'application/octet-stream','buffer':b'fixture graph'})
        expect(modal.locator('#detectorState')).to_contain_text('7')
        modal.get_by_role('button',name='Test current screen' if language=='en' else '检测当前屏幕',exact=True).click()
        expect(modal.locator('#detectorState')).to_contain_text('1008×2244')
        assert '/detector.test' in page.evaluate('commands')
        assert not errors
        browser.close()
