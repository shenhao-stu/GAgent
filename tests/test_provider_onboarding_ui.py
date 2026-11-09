"""First-run provider setup through the shipped UI, without a model-list API."""
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

WEB = Path(__file__).parents[1] / 'app/src/main/assets/ga_runtime/webui'


@pytest.mark.parametrize('language,protocol,width,height', [
    ('zh', 'oai', 390, 844), ('en', 'claude', 844, 390),
    ('zh', 'oai', 320, 700),
])
def test_manual_model_survives_reload_and_failed_edit(language, protocol, width, height):
    errors, outgoing = [], []
    with sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': width, 'height': height}, locale=language)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('http**://**', lambda route: (outgoing.append(route.request.url), route.abort()))
        page.add_init_script('''
          window.commands=[];
          const read=()=>JSON.parse(localStorage.getItem('fixture.providers')||'[]');
          window.GA=new Proxy({
            ready:()=>read().length?'ok':'nokey', poll:()=> '{}', isDark:()=>false,
            appVersion:()=> '{"name":"test","code":1}',
            send:(command)=>{
              commands.push(command.split(' ')[0]);
              if(command==='/config')return JSON.stringify({ok:true,items:read()});
              if(command.startsWith('/provider.save ')){
                if(window.failSave)return 'error: fixture write failed';
                const p=JSON.parse(command.slice(15)), items=read().filter(x=>x.name!==p.name);
                items.push({...p,id:'mk_'+p.name});
                localStorage.setItem('fixture.providers',JSON.stringify(items));return 'ok';
              }
              if(command.startsWith('/kv.get '))return localStorage.getItem('fixture.kv.'+command.slice(8))||'';
              if(command.startsWith('/kv.set ')){
                const rest=command.slice(8),i=rest.indexOf(' ');
                localStorage.setItem('fixture.kv.'+rest.slice(0,i),rest.slice(i+1));return 'ok';
              }
              return '{}';
            }
          },{get:(target,key)=>target[key]||(()=> '{}')});
        ''')
        page.goto((WEB / 'index.html').as_uri())
        page.locator('.pcAgree').click()
        page.get_by_role('button', name='添加服务商' if language == 'zh' else 'Add provider', exact=True).click()
        page.locator(f'#pvSeg button[data-t={protocol}]').click()
        page.locator('#pvName').fill('Example provider')
        page.locator('#pvKey').fill('fixture-credential')
        page.locator('#pvBase').fill('https://model.example.test/v1')
        page.locator('#saveBtn').click()
        expect(page.locator('#pvModel')).to_be_focused()
        assert page.locator('#pvModel').evaluate('''e=>{
          const r=e.getBoundingClientRect();
          return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===e;
        }'''), 'Validation must reveal the input above the fixed Save bar'
        assert '/provider.save' not in page.evaluate('commands')
        page.locator('#pvModel').fill('fixture-model')
        page.evaluate('window.failSave=true')
        page.locator('#saveBtn').click()
        assert page.evaluate('providers.length') == 0
        expect(page.locator('#pvModel')).to_have_value('fixture-model')
        page.evaluate('window.failSave=false')
        page.locator('#saveBtn').click()
        expect(page.locator('#provListPanel')).to_be_visible()
        expect(page.locator('#modelChipName')).to_have_text('fixture-model')
        assert '/models' not in page.evaluate('commands')

        page.reload()
        expect(page.locator('#modelChipName')).to_have_text('fixture-model')
        page.evaluate('openProviders()')
        page.locator('.provRowInner').click()
        expect(page.locator('#pvModel')).to_have_value('fixture-model')
        page.locator('#pvModel').fill('fixture-new-model')
        page.evaluate('window.failSave=true')
        page.locator('#saveBtn').click()
        assert page.evaluate('providers[0].model') == 'fixture-model'
        expect(page.locator('#modelChipName')).to_have_text('fixture-model')
        expect(page.locator('#pvModel')).to_have_value('fixture-new-model')
        page.evaluate('window.failSave=false')
        page.locator('#saveBtn').click()
        expect(page.locator('#modelChipName')).to_have_text('fixture-new-model')
        page.reload()
        expect(page.locator('#modelChipName')).to_have_text('fixture-new-model')
        assert not errors
        assert not outgoing
        browser.close()
