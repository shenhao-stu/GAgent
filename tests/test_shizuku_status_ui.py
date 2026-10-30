"""从 Shizuku 管理器授权后返回 GA, 状态行/红点必须刷新。

真机回归(2026-10-27): 用户在 Shizuku 管理器里授权 GA 后切回, 状态仍显示未授权,
且红点不亮。根因是 resume 只推 a11y/adb, 没推 Shizuku; 页面没有重新读状态。
"""
from playwright.sync_api import sync_playwright

from test_motion_navigation_ui import open_page


def test_resume_refreshes_shizuku_status_and_dot():
    with sync_playwright() as engine:
        browser, page, errors = open_page(engine)
        got = page.evaluate('''()=>{
          GA.shizukuStatus=()=>JSON.stringify({installed:true,ready:false});
          refreshShizuku();
          const off=[document.getElementById('szDot').hidden,
                     document.getElementById('szVal').textContent];
          GA.shizukuStatus=()=>JSON.stringify({installed:true,ready:true});
          gaOnResume();
          const on=[document.getElementById('szDot').hidden,
                    document.getElementById('szVal').textContent];
          return {off,on};
        }''')
        assert got['off'][0] is False            # 未授权: 红点可见
        assert got['off'][1] in ('未授权', 'Not authorized')
        assert got['on'][0] is True              # 已就绪: 红点隐藏
        assert got['on'][1] in ('已就绪', 'Ready')
        assert not errors
        browser.close()
