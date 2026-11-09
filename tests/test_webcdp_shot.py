"""Foreground browser screenshots on Android WebView, and open_url when only the screenshot fails."""
import base64
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/ga_runtime'
sys.path.insert(0, str(CORE))
import webcdp


def test_screenshot_asks_for_the_surface(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(webcdp, '_call', lambda m, p=None, timeout=15: calls.append((m, p)) or {'data': base64.b64encode(b'png').decode()})
    path = webcdp.web_shot(str(tmp_path / 's.png'))
    # Without fromSurface the WebView waits for a new frame and a static page times out (MEIZU 21, WebView 155).
    assert calls == [('Page.captureScreenshot', {'format': 'png', 'fromSurface': True})]
    assert Path(path).read_bytes() == b'png'


def test_open_url_keeps_the_page_when_the_screenshot_fails(monkeypatch):
    monkeypatch.setattr(webcdp, 'ensure_fg', lambda: None)
    monkeypatch.setattr(webcdp, 'connect', lambda **k: None)
    monkeypatch.setattr(webcdp, 'web_open', lambda url, wait_load=10: {'url': url, 'readyState': 'complete'})

    def timed_out(path=None, timeout=20):
        raise RuntimeError("devtools 连接已断开(已自动清理, 请重新 connect()): TimeoutError('timed out')")
    monkeypatch.setattr(webcdp, 'web_shot', timed_out)
    res = webcdp.open_url('https://example.com')
    assert res['readyState'] == 'complete' and res['where'] == 'foreground'
    assert res['shot'] is None and 'timed out' in res['shot_error']
