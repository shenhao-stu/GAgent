"""One-tap proxy detection on iOS only accepts listeners that complete an HTTP CONNECT."""
import socket
import sys
import threading
import unittest
from unittest.mock import patch

import signed_runtime
import android_entry


def serve(reply):
    """A loopback listener that answers every connection with `reply` (None closes without a byte)."""
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(8)

    def loop():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.recv(256)
                    if reply:
                        conn.sendall(reply)
                except OSError:
                    pass
    threading.Thread(target=loop, daemon=True).start()
    return server, server.getsockname()[1]


class ProxyDetectTests(unittest.TestCase):
    def setUp(self):
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.close()

    def listener(self, reply):
        server, port = serve(reply)
        self.servers.append(server)
        return port

    def test_only_a_completed_connect_counts(self):
        proxy = self.listener(b'HTTP/1.1 200 Connection Established\r\n\r\n')
        socks = self.listener(b'\x05\xff')
        silent = self.listener(None)
        web = self.listener(b'HTTP/1.1 405 Method Not Allowed\r\n\r\n')
        self.assertTrue(android_entry._answers_http_connect(proxy))
        for port in (socks, silent, web):
            self.assertFalse(android_entry._answers_http_connect(port), port)

    def test_ios_skips_open_ports_that_are_not_http_proxies(self):
        socks, proxy = self.listener(b'\x05\xff'), self.listener(b'HTTP/1.0 200 OK\r\n\r\n')
        with patch.object(android_entry, '_PROXY_PORTS', (socks, proxy)), patch.object(sys, 'platform', 'ios'):
            self.assertEqual(android_entry._detect_proxy(), f'http://127.0.0.1:{proxy}')
        with patch.object(android_entry, '_PROXY_PORTS', (socks,)), patch.object(sys, 'platform', 'ios'):
            self.assertEqual(android_entry._detect_proxy(), '')

    def test_system_proxy_hint_is_verified_before_the_port_table(self):
        """iOS reads the system proxy natively (Shadowrocket HTTP mode publishes 127.0.0.1:1082); the hint is
        accepted only when it completes CONNECT, otherwise the port table decides."""
        proxy, socks = self.listener(b'HTTP/1.1 200 OK\r\n\r\n'), self.listener(b'\x05\xff')
        with patch.object(android_entry, '_PROXY_PORTS', ()), patch.object(sys, 'platform', 'ios'):
            self.assertEqual(android_entry._detect_proxy(f'http://127.0.0.1:{proxy}'), f'http://127.0.0.1:{proxy}')
            self.assertEqual(android_entry._detect_proxy(f'http://127.0.0.1:{socks}'), '')
            self.assertEqual(android_entry._detect_proxy('http://127.0.0.1:1'), '', 'a closed port is not a proxy')
            self.assertEqual(android_entry._detect_proxy('socks5://127.0.0.1:%d' % proxy), '', 'only http(s) URLs')
        with patch.object(android_entry, '_PROXY_PORTS', (proxy,)), patch.object(sys, 'platform', 'ios'):
            self.assertEqual(android_entry._detect_proxy('garbage'), f'http://127.0.0.1:{proxy}')
        self.assertEqual(android_entry._cmd_detectproxy(f'/detectproxy http://127.0.0.1:{proxy}'),
                         '{"proxy": "http://127.0.0.1:%d"}' % proxy)
        self.assertTrue(any(match('/detectproxy http://127.0.0.1:1') for match, fn in android_entry._CMDS
                            if fn is android_entry._cmd_detectproxy), 'the command accepts an argument')

    def test_android_keeps_the_connectivity_probe(self):
        socks = self.listener(b'\x05\xff')
        with patch.object(android_entry, '_PROXY_PORTS', (socks,)), patch.object(sys, 'platform', 'linux'):
            self.assertEqual(android_entry._detect_proxy(), f'http://127.0.0.1:{socks}')


if __name__ == '__main__':
    unittest.main()
