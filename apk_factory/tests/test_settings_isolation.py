"""Settings fault boundaries against production navigation/functions and real DOM.
Services are stubbed: this tests failure containment, not native/network success.
"""
import os
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / 'app/src/main/assets/ga_runtime/webui'


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright
    # Runtime apk_factory.py can shadow the package during combined suites.
    import runpy
    _func_body = runpy.run_path(str(Path(__file__).with_name('test_pclink_scroll_contract.py')))['_func_body']

    src = (WEB / 'app.js').read_text(encoding='utf-8')
    funcs = {'_settingsBlock': 'id,render', '_setShow': 'panel,title',
             'setNav': 'panel,title,key', 'setvBack': '', 'closeSettings': '',
             'openSettings': '', 'refreshHome': '', '_setEnter':'panel,dir'}
    code = '\n'.join('function %s(%s){%s}' % (n, args, _func_body(src, n))
                     for n, args in funcs.items())
    panels = re.search(r'const SET_PANELS=\[[^;]+;', src).group(0)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"))
        p = browser.new_page()
        errors = []
        p.on('pageerror', lambda e: errors.append(str(e)))
        # Actual markup, no app bootstrap/native bridges or external requests.
        html = (WEB / 'index.html').read_text(encoding='utf-8')
        html = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', html)
        html = re.sub(r'<link\b[^>]*>', '', html)
        p.set_content(html)
        p.evaluate('''() => {
          window.$=id=>document.getElementById(id);window.t=k=>k;
          window.failures={};window.calls=[];
          window.closeDrawer=()=>{window.drawerClosed=true};
          window.GAT={emit(){if(failures.telemetry)throw Error('telemetry')}};
          for(const name of ['refreshA11y','refreshAvatarRow','refreshProxyVal',
             'refreshAppVersion','_reflectUpdateBadge','refreshThemeVal',
             'renderAuthSummary','refreshEvoBadge','refreshApkQuota','refreshStorage',
             'renderUserPage','refreshGanetPage','renderProvList','renderFilesPage',
             'renderMemPage','renderUpdatePage','renderStats','renderPlan',
             'renderPointsDetail','renderPointsRules','resetDatasetForm',
             'resetFeedbackForm','renderA11yPersistPage']){
            window[name]=()=>{calls.push(name);if(failures[name])throw Error('test secret must not be logged')};
          }
          Object.assign(window,{soundOn:true,keepAwake:false,showThinking:true,
            floatAlwaysOn:false,safeMode:false,contribPrompts:false,
            floatOpacity:0.5,providers:[],editingId:null,LS:{set(){}}});
        }''')
        p.add_script_tag(content=panels + "\nlet setStack=[],_setAnim=null;const _setBody=()=>$('setv').querySelector('.setbody');\n" + code)
        yield p, errors
        browser.close()


@pytest.mark.parametrize('name,target', [
    ('refreshA11y', 'a11yVal'), ('refreshAvatarRow', 'dwAvatar'),
    ('refreshProxyVal', 'globalProxyVal'), ('refreshAppVersion', 'appVerVal'),
    ('_reflectUpdateBadge', 'updateBadge'), ('refreshThemeVal', 'themeVal'),
    ('refreshEvoBadge', 'evoBakVal'),
    ('refreshStorage', 'stUsageHome'),
])
def test_home_failure_is_local_and_recovers(page, name, target):
    p, errors = page
    p.evaluate('(name)=>{failures[name]=true;openSettings()}', name)
    p.wait_for_timeout(60)
    assert p.locator('#setv').evaluate("e=>e.classList.contains('on')")
    assert p.locator('#setv').get_attribute('aria-hidden') == 'false'
    assert p.locator('#homePanel').evaluate("e=>e.style.display") == 'block'
    assert p.locator('#setErr_' + target).count() == 1
    assert p.locator('#setErr_homePanel').count() == 0
    assert p.evaluate("calls.includes('refreshEvoBadge') && calls.includes('refreshStorage')")
    # The model list remains reachable even when an unrelated home block fails.
    p.evaluate("setNav('provListPanel','Models')")
    assert p.evaluate("calls.includes('renderProvList')")
    p.evaluate('failures={};setvBack()')
    p.wait_for_timeout(60)
    assert p.locator('#setErr_' + target).count() == 0
    p.evaluate('setvBack()')
    assert p.locator('#setv').get_attribute('aria-hidden') == 'true'
    assert not errors


@pytest.mark.parametrize('panel,renderer', [
    ('provListPanel', 'renderProvList'),
    ('ganetPanel', 'refreshGanetPage'), ('dataPanel', 'refreshStorage'),
    ('filesPanel', 'renderFilesPage'), ('memPanel', 'renderMemPage'),
    ('updatePanel', 'renderUpdatePage'), ('statsPanel', 'renderStats'),
    ('a11yPersistPanel', 'renderA11yPersistPage'),
])
def test_subpage_failure_preserves_navigation(page, panel, renderer):
    p, errors = page
    p.evaluate('openSettings()')
    p.wait_for_timeout(50)
    p.evaluate('([panel,renderer])=>{failures[renderer]=true;setNav(panel,panel)}', [panel, renderer])
    p.wait_for_timeout(60)
    assert p.locator('#setErr_' + panel).count() == 1
    p.evaluate('failures={};setvBack()')
    assert p.locator('#homePanel').evaluate("e=>e.style.display") == 'block'
    p.evaluate('(panel)=>setNav(panel,panel)', panel)
    p.wait_for_timeout(60)
    assert p.locator('#setErr_' + panel).count() == 0
    assert not errors


def test_promise_rejection_and_stale_result(page):
    p, errors = page
    p.evaluate("openSettings();renderStats=()=>Promise.reject(Error('async'));setNav('statsPanel','User')")
    p.wait_for_timeout(50)
    assert p.locator('#setErr_statsPanel').count() == 1
    p.evaluate('''() => {
      _settingsBlock('statsPanel',()=>new Promise((ok,fail)=>window.lateFail=fail));
      _settingsBlock('statsPanel',()=>{});
      lateFail(Error('stale'));
    }''')
    p.wait_for_timeout(50)
    assert p.locator('#setErr_statsPanel').count() == 0
    assert not errors


def test_multiple_failures_still_allow_model_navigation(page):
    p, errors = page
    p.evaluate('''() => {
      failures.refreshThemeVal=true;failures.refreshEvoBadge=true;
      failures.refreshProxyVal=true;
      refreshAppVersion=()=>{window.visibleDuringRefresh=$('setv').classList.contains('on')};
      openSettings();
    }''')
    assert p.evaluate('visibleDuringRefresh')
    assert p.locator('[id^="setErr_"]').count() == 3
    p.evaluate("setNav('provListPanel','Models')")
    assert p.evaluate("calls.includes('renderProvList')")
    assert not errors


def test_missing_optional_node_does_not_break_boundary(page):
    p, errors = page
    p.evaluate("$('appVerVal').remove();failures.refreshAppVersion=true;openSettings()")
    assert p.locator('#setv').get_attribute('aria-hidden') == 'false'
    assert p.evaluate("calls.includes('refreshEvoBadge')")
    assert not errors


def test_telemetry_cannot_block_opening(page):
    p, errors = page
    p.evaluate('failures.telemetry=true;openSettings()')
    assert p.locator('#setv').get_attribute('aria-hidden') == 'false'
    assert not errors
