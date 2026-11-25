"""Draw the handoff strip and the two settings rows inside the real chat page, check what is really visible
(and that what the strip stands in for is really gone), and save screenshots.

    <python with playwright> ios/Presence/Tests/shots_strip.py [out_dir]      default out: ios/Presence/build/strip

The page is the shipping web UI served as it is, with its own browser-preview bridge switched to the iOS
layout. The script is added the way WebSurface.swift adds it: style and words first, then presence.js, then
configure() and render(). What the page sends to the native side is collected in window.__posted.
"""
import functools
import http.server
import json
import re
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parents[1]
WEB = HERE.parents[1] / 'app/src/main/assets/ga_runtime/webui'
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / 'build/strip'
LABELS = {'takeOver': '我来操作', 'handBack': '交还给 GAgent', 'handingBack': '正在交还…', 'end': '结束', 'released': '键鼠已松开'}
STATES = {
    'running': {'phase': 'acting', 'running': True, 'status': '正在操作', 'now': '点击「去结算」'},
    'asking': {'phase': 'asking', 'running': False, 'status': '需要你决定', 'now': '从哪一家下单？'},
    'paused': {'phase': 'paused', 'running': False, 'status': '你在操作', 'now': ''},
    'done': {'phase': 'done', 'running': False, 'status': '已完成', 'now': '已下单'},
}
BUTTONS = {'running': 1, 'asking': 0, 'paused': 2, 'done': 0}     # what must actually be on screen
SHOWN = "(q => [...document.querySelectorAll(q)].filter(e => e.getClientRects().length).length)"
ROWS = "[...document.querySelectorAll('.gpSetting')]"
NATIVE = "window.__posted=[];window.webkit={messageHandlers:{gaPresence:{postMessage:m=>window.__posted.push(m)}}};"


def words():
    """The rows' labels as PresenceCopy.swift has them: {'zh': {...}, 'en': {...}}."""
    copy = (HERE / 'Core/PresenceCopy.swift').read_text(encoding='utf-8')
    found = re.findall(r'"(gaPresence\w+)": t\("([^"]+)", "([^"]+)"\)', copy)
    assert len(found) == 2, found
    return {'zh': {key: zh for key, zh, _ in found}, 'en': {key: en for key, _, en in found}}


def settings(page, theme, labels):
    """Both rows sit in the general settings card after the sound row, in the page's language, and report taps."""
    page.evaluate("setLang('zh')")
    page.evaluate('openSettings()')
    page.wait_for_timeout(700)
    page.evaluate('GAPresence.configure({live:true,lockDetail:true})')
    rows = page.evaluate(ROWS + ".map(r => ({text: r.querySelector('.k').textContent, on: r.querySelector('.sw').classList.contains('on'),"
                         " shown: r.getClientRects().length > 0}))")
    assert [row['text'] for row in rows] == list(labels['zh'].values()), rows
    assert all(row['on'] and row['shown'] for row in rows), rows
    assert page.evaluate("(rows => rows[0].previousElementSibling.contains(document.getElementById('swSound'))"
                         " && rows[1].previousElementSibling === rows[0])(" + ROWS + ")"), 'right after the sound row'
    page.evaluate(ROWS + "[0].scrollIntoView({block:'center'})")
    page.wait_for_timeout(200)
    page.screenshot(path=str(OUT / f'settings-{theme}.png'))
    page.evaluate(ROWS + "[0].querySelector('.sw').click()")
    assert page.evaluate('window.__posted.filter(m => m.setting)') == [{'setting': 'live', 'value': False}]
    assert page.evaluate(ROWS + "[1].querySelector('.sw').disabled")
    page.wait_for_timeout(200)
    page.screenshot(path=str(OUT / f'settings-{theme}-off.png'))
    page.evaluate("setLang('en')")
    assert page.evaluate(ROWS + ".map(r => r.querySelector('.k').textContent)") == list(labels['en'].values())
    page.evaluate("setLang('zh')")
    page.evaluate('closeSettings()')
    page.wait_for_timeout(500)
# The preview bridge appears when the page finds no GA. Mark the one it creates as the iOS client, let it
# report the data-sharing disclosure as accepted, so the chat is what is on screen.
IOS = """Object.defineProperty(window,'GA',{configurable:true,get(){},set(bridge){
  const send=bridge.send;bridge.platform='ios';
  bridge.send=cmd=>cmd==='/ios.consent.status'?'{"ok":true,"pcAccepted":true,"accepted":true,"needsRefresh":false,"receivers":[]}':send(cmd);
  Object.defineProperty(window,'GA',{value:bridge,writable:true,configurable:true})}});"""


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(WEB)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    labels = words()
    setup = {'css': (HERE / 'Web/presence.css').read_text(encoding='utf-8'), 'words': labels}
    add = NATIVE + 'window.__gaPresence=' + json.dumps(setup) + ';\n' + (HERE / 'Web/presence.js').read_text(encoding='utf-8')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for theme in ('light', 'dark'):
            page = browser.new_page(viewport={'width': 430, 'height': 932}, device_scale_factor=2, color_scheme=theme)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.add_init_script(IOS)
            page.goto(f'http://127.0.0.1:{server.server_address[1]}/index.html')
            page.wait_for_selector('#comp')
            page.wait_for_function("typeof setLang==='function' && typeof openSettings==='function' && typeof openConvo==='function'")
            page.add_style_tag(content='.authOverlay{display:none!important}')   # the sign-in sheet covers the chat
            page.evaluate(add)
            assert page.evaluate('!!window.GAPresence'), 'the strip was not added'
            assert page.evaluate('window.__posted') == [{'ready': True}]
            settings(page, theme, labels)
            # A card opened while the computer destination is visible must reveal its local task.
            page.evaluate("convos.push({id:'presence-review-target', title:'卡片任务', ts:Date.now(), msgs:[]}); GAIOS.navigate('computer')")
            page.wait_for_function("document.body.dataset.iosPage==='computer'")
            assert page.evaluate("GAPresence.openConversation('presence-review-target')")
            page.wait_for_function("document.body.dataset.iosPage==='assistant' && !document.getElementById('app').inert"
                                   " && curConvo.id==='presence-review-target'")
            # The strip is the open conversation's; the page's own live line sits in the same place.
            cid = 'demo'
            page.evaluate("curConvo = {id: 'demo', msgs: []}")   # the page sets this when a task starts
            page.evaluate("(() => { const line = document.createElement('div'); line.id = 'twLive'; line.style.display = 'flex';"
                          " line.textContent = 'screen：点击「去结算」'; const comp = document.getElementById('comp');"
                          " comp.insertBefore(line, comp.firstChild) })()")
            for name, state in STATES.items():
                page.evaluate('s => GAPresence.render(s)', {'cid': cid, 'labels': LABELS, **state})
                page.wait_for_timeout(250)
                visible = page.evaluate(SHOWN + "('#gaPresence button')")
                assert visible == BUTTONS[name], (name, 'visible buttons', visible)
                stands_in = name in ('running', 'paused')
                assert page.evaluate(SHOWN + "('#gaPresence')") == stands_in, name
                assert page.evaluate(SHOWN + "('#twLive')") == (not stands_in), (name, 'one line for the tool at work')
                if stands_in:
                    box = page.evaluate("(() => { const r = document.getElementById('gaPresence').getBoundingClientRect();"
                                        " return [r.left, r.right, r.height, innerWidth] })()")
                    assert box[0] >= 0 and box[1] <= box[3] and box[2] >= 44, (name, box)
            for name in ('running', 'paused'):
                page.evaluate('s => GAPresence.render(s)', {'cid': cid, 'labels': LABELS, **STATES[name]})
                page.wait_for_timeout(250)
                page.screenshot(path=str(OUT / f'strip-{theme}-{name}.png'), clip={'x': 0, 'y': 560, 'width': 430, 'height': 372})
            # Narrow screens and a reduced viewport (keyboard-sized): the handoff controls and composer
            # must stay reachable. Hit-test actual DOM paint order, not just the existence of the controls.
            for width, height in ((320, 568), (375, 420), (430, 500)):
                page.set_viewport_size({'width': width, 'height': height})
                for name in ('running', 'paused'):
                    page.evaluate('s => GAPresence.render(s)', {'cid': cid, 'labels': LABELS, **STATES[name]})
                    page.wait_for_timeout(250)
                    reachable = page.evaluate("""() => [...document.querySelectorAll('#gaPresence button, #in')]
                        .filter(e => e.getClientRects().length).map(e => {
                            const r=e.getBoundingClientRect(), hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
                            return {label:e.textContent||e.id, visible:r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight,
                                    reachable:!!hit&&(hit===e||e.contains(hit)), hit:hit&&(hit.id||hit.className||hit.tagName)};
                        })""")
                    if not all(item['visible'] and item['reachable'] for item in reachable):
                        page.screenshot(path=str(OUT / 'layout-failure.png'))
                    assert all(item['visible'] and item['reachable'] for item in reachable), (theme, width, height, name, reachable)
                page.screenshot(path=str(OUT / f'strip-{theme}-{width}x{height}.png'))
            page.set_viewport_size({'width': 430, 'height': 932})
            page.evaluate('s => GAPresence.render(s)', {'cid': 'another-conversation', 'labels': LABELS, **STATES['running']})
            assert page.evaluate(SHOWN + "('#gaPresence')") == 0, 'a task elsewhere is not this chat\'s'
            page.evaluate('GAPresence.render(null)')
            page.evaluate('curConvo = null')
            assert page.evaluate("document.getElementById('gaPresence').hidden")
            assert page.evaluate(SHOWN + "('#twLive')") == 1
            print(theme, 'ok; page errors:', errors[:3])
            page.close()
        browser.close()
    server.shutdown()
    print('written to', OUT)


if __name__ == '__main__':
    main()
