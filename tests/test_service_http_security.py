"""Credential requests never follow redirects or reveal signed pairing URLs."""
import asyncio
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import urllib.error

import pytest

RUNTIME = Path(__file__).parents[1] / 'app/src/main/assets/ga_runtime'
sys.path[:0] = [str(RUNTIME)]


def test_mesh_redirect_never_sends_authorization_to_another_origin():
    import ganet
    received = []

    class Target(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.headers.get('Authorization'))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{}')

        def log_message(self, *args):
            pass

    target = ThreadingHTTPServer(('127.0.0.1', 0), Target)

    class Source(Target):
        def do_GET(self):
            self.send_response(302)
            self.send_header('Location', 'http://127.0.0.1:%s/stolen' % target.server_port)
            self.end_headers()

    source = ThreadingHTTPServer(('127.0.0.1', 0), Source)
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (target, source)]
    for thread in threads:
        thread.start()
    try:
        with pytest.raises(urllib.error.HTTPError):
            ganet._get('http://127.0.0.1:%s/redirect' % source.server_port, 'synthetic-token', timeout=2)
        assert received == []
    finally:
        for server, thread in zip((target, source), threads):
            server.shutdown()
            server.server_close()
            thread.join(2)


@pytest.mark.parametrize('http_error', [False, True])
def test_pairing_errors_do_not_expose_urls_or_response_bodies(monkeypatch, http_error):
    import p2p_ws_client as p2p
    url = 'https://relay.example/code/use?code=123456789&sig=private-signature'
    error = (urllib.error.HTTPError(url, 403, 'Forbidden', {}, io.BytesIO(url.encode()))
             if http_error else OSError(url))
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(p2p._direct_opener, 'open', fail)
    with pytest.raises(ConnectionError) as caught:
        asyncio.run(p2p._post_json(url))
    assert '123456789' not in str(caught.value)
    assert 'private-signature' not in str(caught.value)


@pytest.mark.parametrize('url', ['ws://relay.example/ws', 'wss://user:pw@relay.example/ws',
                               'wss://relay.example/ws?token=private'])
def test_short_code_rejects_unsafe_relay_before_network(url):
    import p2p_ws_client as p2p
    with pytest.raises(ValueError):
        p2p.code_url(url, 'code/use')


def test_websocket_signaling_does_not_follow_redirects():
    import p2p_ws_client as p2p
    received = []

    class Redirect(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def do_GET(self):
            if self.path.startswith('/original'):
                self.send_response(302)
                self.send_header('Location', '/unexpected?sig=synthetic-signature')
            else:
                received.append(self.path)
                self.send_response(403)
            self.send_header('Content-Length', '0')
            self.end_headers()
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    async def scenario():
        connect = getattr(p2p, '_SignalConnect', p2p.websockets.connect)
        with pytest.raises(p2p.websockets.exceptions.InvalidStatus):
            await connect('ws://127.0.0.1:%s/original?sig=synthetic-signature' % server.server_port,
                          proxy=None, open_timeout=2)
    try:
        asyncio.run(scenario())
        assert received == []
    finally:
        server.shutdown(); server.server_close(); thread.join(2)
