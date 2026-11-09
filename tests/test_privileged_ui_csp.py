"""Chat rejects remote frames and sanitizes untrusted HTML before native bridging."""
from html.parser import HTMLParser
import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


class Policy(HTMLParser):
    value = ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('http-equiv', '').lower() == 'content-security-policy':
            self.value = attrs['content']


@pytest.mark.parametrize('source', ['remote', 'data'])
def test_subframes_cannot_execute_with_native_bridge(source):
    policy = Policy()
    policy.feed((Path(__file__).parents[1] / 'app/src/main/assets/ga_runtime/webui/index.html').read_text())
    child = '<script>GA.call()</script>'
    with sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page()
        invoked = []
        page.on('console', lambda msg: invoked.append(msg.text) if msg.text == 'bridge-invoked' else None)
        # Android addJavascriptInterface injects into every frame, not just the top document.
        page.add_init_script("globalThis.GA={call:()=>console.log('bridge-invoked')}")
        page.route('**/*', lambda route: route.fulfill(content_type='text/html', body=(
            '<meta http-equiv="Content-Security-Policy" content="' + policy.value + '">'
            if route.request.url == 'https://ui.invalid/' else child)))
        page.goto('https://ui.invalid/')
        page.evaluate('''({source, child}) => {
          window.blocked=[];
          addEventListener('securitypolicyviolation', e=>blocked.push(e.effectiveDirective));
          const frame=document.createElement('iframe');
          frame.src=source==='data'?'data:text/html,'+encodeURIComponent(child):'https://child.invalid/';
          document.body.append(frame);
        }''', {'source': source, 'child': child})
        page.wait_for_function("blocked.includes('frame-src')", timeout=2000)
        assert not invoked
        browser.close()


@pytest.mark.parametrize('sanitizer', ['ready', 'missing', 'failed'])
def test_model_html_cannot_create_frames_or_invoke_bridge(sanitizer):
    web = Path(__file__).parents[1] / 'app/src/main/assets/ga_runtime/webui'
    with sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page()
        page.route('http**://**', lambda route: route.abort())
        page.add_init_script('''
          window.invoked=0;
          window.GA=new Proxy({ready:()=> 'ok',poll:()=> '{}',isDark:()=>false,
            call:()=>invoked++,send:()=> '{}'}, {get:(t,k)=>t[k]||(()=> '{}')});
        ''')
        page.goto((web / 'index.html').as_uri())
        if sanitizer == 'missing':
            page.evaluate('window.DOMPurify=undefined')
        elif sanitizer == 'failed':
            page.evaluate("() => {DOMPurify.sanitize=()=>{throw Error('synthetic failure')}}")
        page.evaluate('''() => {
          const root=document.createElement('div');root.id='untrusted-output';
          root.append(renderRich('<iframe srcdoc="<script>GA.call()<\\/script>"></iframe>'+
            '<img src="data:image/png,invalid" onerror="GA.call()">'+
            '<a href="javascript:GA.call()">link</a><p>ordinary text</p>',{mode:'chat'}));
          document.body.append(root);
        }''')
        root = page.locator('#untrusted-output')
        assert 'ordinary text' in root.inner_text()
        assert root.locator('iframe,object,embed,[onerror],[srcdoc],[href^="javascript:"]').count() == 0
        page.wait_for_timeout(150)
        assert page.evaluate('invoked') == 0
        browser.close()
