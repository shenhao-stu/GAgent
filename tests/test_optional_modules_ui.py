import json
import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

WEB = Path(__file__).parents[1] / 'app/src/main/assets/ga_runtime/webui'


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_profile_import_requires_save_and_provider_remains_available(language):
    errors, outgoing = [], []
    with sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 390, 'height': 844}, locale=language)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('http**://**', lambda route: (outgoing.append(route.request.url), route.abort()))
        page.add_init_script('''
          window.savedProfiles=[]; window.kv={};
          const services={voice:{url:'wss://voice.example.com/asr',has_token:true}};
          window.GA=new Proxy({
            ready:()=> 'ok', poll:()=> '{}', isDark:()=>false,
            appVersion:()=> '{"name":"2.33.1","code":134}',
            send:(command)=>{
              if(command==='/config')return '{"ok":true,"items":[]}';
              if(command==='/integrations.get')return JSON.stringify(services);
              if(command.startsWith('/integrations.save ')){
                savedProfiles.push(JSON.parse(command.slice(19)));return '{"ok":true}';
              }
              if(command.startsWith('/kv.get '))return kv[command.slice(8)]||'';
              if(command.startsWith('/kv.set ')){const rest=command.slice(8),i=rest.indexOf(' ');kv[rest.slice(0,i)]=rest.slice(i+1);return 'ok'}
              return '{}';
            }
          },{get:(target,key)=>target[key]||(()=> '{}')});
        ''')
        page.goto((WEB / 'index.html').as_uri())
        page.locator('.pcAgree').click()
        page.evaluate('openSettings();openIntegrations()')
        card = page.locator('#integrationsPanel')
        expect(card).to_be_visible()
        assert card.locator('input[type=password]').evaluate_all('(xs)=>xs.every(x=>!x.value)')
        profile = {'schema': 1, 'integrations': {'voice': {'url': 'wss://speech.example.com/asr', 'token': 'sample-user-token', 'model': 'asr'}}}
        card.locator('input[type=file]').set_input_files({'name':'connection.json','mimeType':'application/json','buffer':json.dumps(profile).encode()})
        expect(card.locator('input[type=password][placeholder]')).to_have_value('sample-user-token')
        assert page.evaluate('savedProfiles.length') == 0
        card.get_by_role('button', name='保存' if language == 'zh' else 'Save', exact=True).click()
        assert page.evaluate('savedProfiles[0].voice') == profile['integrations']['voice']
        page.evaluate('openIntegrations()')
        page.get_by_role('button', name='模型服务商' if language == 'zh' else 'Model provider', exact=True).click()
        assert page.locator('#provListPanel').is_visible()
        assert not errors
        assert not outgoing
        browser.close()


# WCAG 1.4.3 for readable text, including ::placeholder of empty fields: composite every ancestor background,
# skip inactive controls (.dim / disabled; WCAG exempts inactive components).
LOW_CONTRAST_JS = r'''(sel)=>{
  const root=document.querySelector(sel);if(!root)return [{missing:sel}];
  const parse=s=>{const m=s.match(/rgba?\(([^)]+)\)/);if(!m)return null;const p=m[1].split(/[ ,\/]+/).filter(Boolean).map(Number);return [p[0],p[1],p[2],p.length>3?p[3]:1]};
  const blend=(t,b)=>[0,1,2].map(i=>t[i]*t[3]+b[i]*(1-t[3])).concat(1);
  const lum=c=>{const f=v=>{v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)};return .2126*f(c[0])+.7152*f(c[1])+.0722*f(c[2])};
  const ratio=(a,b)=>{const x=lum(a),y=lum(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)};
  const low=[];
  for(const node of [root,...root.querySelectorAll('*')]){
    if(!node.getClientRects().length||node.closest('.dim,[disabled],[aria-disabled=true]'))continue;
    const style=getComputedStyle(node);if(style.visibility!=='visible')continue;
    const field=(node.tagName==='INPUT'&&['text','password','url','search','email','tel'].includes(node.type))||node.tagName==='TEXTAREA';
    let text=field?node.value:[...node.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent).join('').trim();
    const ph=field&&!text&&!!node.placeholder;if(ph)text='placeholder:'+node.placeholder;   // empty field shows its placeholder instead
    if(!text)continue;
    let bg=[255,255,255,1],alpha=1;const chain=[];for(let e=node;e;e=e.parentElement)chain.unshift(e);
    for(const e of chain){const s=getComputedStyle(e),b=parse(s.backgroundColor);alpha*=+s.opacity;if(b&&b[3]>0)bg=blend(b,bg)}
    const ps=ph?getComputedStyle(node,'::placeholder'):style,fg=parse(ps.color);fg[3]*=alpha*(ph?+ps.opacity:1);
    const size=parseFloat(style.fontSize),large=size>=24||(size>=18.66&&+style.fontWeight>=700);
    const r=ratio(blend(fg,bg),bg);if(r<(large?3:4.5))low.push(text.slice(0,24)+' '+r.toFixed(2));
  }
  return low;
}'''


@pytest.mark.parametrize('dark', [False, True])
def test_optional_module_settings_text_is_readable_in_both_themes(dark):
    errors = []
    with sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 390, 'height': 844}, locale='zh',
                                color_scheme='dark' if dark else 'light')
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('http**://**', lambda route: route.abort())
        page.add_init_script('''
          window.kv={};
          const services={voice:{url:'wss://voice.example.com/asr',has_token:true,model:'asr'},ganet:{url:'https://mesh.example.com',owner_id:'7',has_token:true}};
          window.GA=new Proxy({ready:()=> 'ok', poll:()=> '{}', isDark:()=>%s,
            send:(c)=>c==='/integrations.get'?JSON.stringify(services):c==='/config'?'{"ok":true,"items":[]}':
              c.startsWith('/integrations.save ')?'{"ok":false,"error":"voice requires a wss URL without embedded credentials"}':
              c.startsWith('/kv.get ')?'':'{}'
          },{get:(t,k)=>t[k]||(()=> '{}')});
        ''' % ('true' if dark else 'false'))
        page.goto((WEB / 'index.html').as_uri())
        page.locator('.pcAgree').click()
        assert page.evaluate(LOW_CONTRAST_JS, '#in') == [], dark   # chat composer placeholder
        for opener, selector in [('openSettings()', '#homePanel'),
                                 ('openIntegrations()', '#integrationsPanel'),
                                 ('openGanetPage()', '#ganetPanel'),
                                 ("setNav('ganetSetupPanel','')", '#ganetSetupPanel'),
                                 # one configured provider so the model subtitle row is rendered
                                 ("openProviders();providers=[{id:'t',name:'GLM',model:'glm-test',models:['glm-test']}];"
                                  "renderProvList()", '#provListPanel .provRow .sub'),
                                 ('PCLINK.openView()', '#pcView')]:
            page.evaluate(opener)
            page.wait_for_timeout(350)
            assert page.evaluate(LOW_CONTRAST_JS, selector) == [], (opener, dark)
        page.evaluate('PCLINK.closeView();openIntegrations()')
        page.locator('#integrationsPanel').get_by_role('button', name='保存', exact=True).click()
        expect(page.locator('#integrationsPanel .intErr')).to_contain_text('wss URL')
        page.wait_for_function('!_setAnim')  # contrast is measured after navigation fades in
        assert page.evaluate(LOW_CONTRAST_JS, '#integrationsPanel') == []
        assert page.locator('#integrationsPanel .intChip.on').count() == 2
        assert not errors
        browser.close()


def test_unconfigured_pclink_opens_its_relay_fields_and_save_refreshes_status():
    errors = []
    with sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 390, 'height': 640}, locale='en')
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('http**://**', lambda route: route.abort())
        page.add_init_script('''
          window.services={}; window.statusCalls=0;
          window.GA=new Proxy({ready:()=> 'ok', poll:()=> '{}', isDark:()=>false,
            send:(c)=>{
              if(c==='/integrations.get')return JSON.stringify(services);
              if(c==='/config')return '{"ok":true,"items":[]}';
              if(c.startsWith('/integrations.save ')){const p=JSON.parse(c.slice(19)).pclink;
                if(p&&p.url)services.pclink={url:p.url,has_token:!!p.token};return '{"ok":true}'}
              if(c==='/pclink.status'||c==='/pclink.resume'){statusCalls++;
                return JSON.stringify({ok:1,configured:!!services.pclink,paired:false,connected:false})}
              return c.startsWith('/kv.get ')?'':'{}'}
          },{get:(t,k)=>t[k]||(()=> '{}')});
        ''')
        page.goto((WEB / 'index.html').as_uri())
        page.locator('.pcAgree').click()
        page.evaluate('openSettings()')
        expect(page.locator('#pcLinkV')).to_contain_text('Optional modules')
        page.locator('#pcLinkRow').click()
        panel = page.locator('#integrationsPanel')
        expect(panel).to_be_visible()
        assert 'build-provided' not in panel.inner_text()
        url = page.locator('#int_pclink_url')
        expect(url).to_be_in_viewport()
        url.fill('wss://relay.example.com/ws')
        page.locator('#int_pclink_token').fill('synthetic-user-credential')
        before = page.evaluate('statusCalls')
        panel.get_by_role('button', name='Save', exact=True).click()
        expect(page.locator('#pcLinkV')).to_have_text('Not linked')
        assert page.evaluate('statusCalls') > before
        assert not errors
        browser.close()


def test_unconfigured_voice_opens_settings_without_requesting_microphone():
    errors = []
    with sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 390, 'height': 844}, locale='en')
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('http**://**', lambda route: route.abort())
        page.add_init_script('''
          window.micRequests=0;
          navigator.mediaDevices.getUserMedia=async()=>{micRequests++;throw Error('not expected')};
          window.GA=new Proxy({ready:()=> 'ok', poll:()=> '{}', isDark:()=>false,
            sttStart:()=> '{"ok":false,"error":"voice_not_configured"}', sttSend:()=> '{}', sttPoll:()=> '{}', sttStop:()=> '{}',
            send:(c)=>c==='/integrations.get'?'{}':c==='/config'?'{"ok":true,"items":[]}':c.startsWith('/kv.get ')?'':'{}'
          },{get:(t,k)=>t[k]||(()=> '{}')});
        ''')
        page.goto((WEB / 'index.html').as_uri())
        page.locator('.pcAgree').click()
        page.locator('#voiceBtn').click()
        expect(page.locator('#integrationsPanel')).to_be_visible()
        expect(page.locator('#int_voice_url')).to_be_in_viewport()
        expect(page.locator('#toast')).to_contain_text('Optional modules')
        assert page.evaluate('micRequests') == 0
        page.evaluate('closeSettings();PCLINK.openView()')   # the PC view (above settings) has its own voice key
        expect(page.locator('#setv')).not_to_have_class(re.compile(r'(^|\s)on(\s|$)'))
        page.locator('#pcVoiceBtn').click()                 # voice start is asynchronous (waits two frames)
        expect(page.locator('#pcView')).not_to_have_class(re.compile(r'(^|\s)on(\s|$)'))
        expect(page.locator('#setv')).to_have_class(re.compile(r'(^|\s)on(\s|$)'))
        expect(page.locator('#int_voice_url')).to_be_in_viewport()
        assert page.evaluate('micRequests') == 0
        assert not errors
        browser.close()


def test_public_relay_preset_fills_the_form_only_after_confirmation():
    relay = 'wss://p2p.' + 'gaagent' + '.ai/ws'
    with sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 390, 'height': 844}, locale='en')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('http**://**', lambda route: route.abort())
        page.add_init_script('''
          window.saved=[];
          window.GA=new Proxy({ready:()=> 'ok', poll:()=> '{}', isDark:()=>false,
            send:(c)=>{if(c.startsWith('/integrations.save '))saved.push(JSON.parse(c.slice(19)));
              return c==='/integrations.get'?'{}':c==='/config'?'{"ok":true,"items":[]}':c.startsWith('/kv.get ')?'':'{"ok":true}'}
          },{get:(t,k)=>t[k]||(()=> '{}')});
        ''')
        page.goto((WEB / 'index.html').as_uri())
        page.locator('.pcAgree').click()
        page.evaluate("openIntegrations('pclink')")
        page.locator('.intPreset').click()
        expect(page.locator('#modalMask.on')).to_contain_text('not a password')
        page.locator('#modalMask .cancel').click()
        expect(page.locator('#int_pclink_url')).to_have_value('')
        page.locator('.intPreset').click()
        page.locator('#modalMask .ok').click()
        expect(page.locator('#int_pclink_url')).to_have_value(relay)
        assert len(page.locator('#int_pclink_token').input_value()) > 20
        assert page.evaluate('saved.length') == 0                      # nothing is saved by the button itself
        page.locator('#integrationsPanel').get_by_role('button', name='Save', exact=True).click()
        assert page.evaluate('saved[0].pclink.url') == relay
        assert not errors
        browser.close()
