"""App-level HTTP proxy selection for iOS model traffic."""

import time
from urllib.parse import urlsplit

from ios_policy import data_root

PROBE_URL = 'https://www.apple.com/library/test/success.html'


def _proxy_url(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme == 'http' and parsed.hostname and parsed.port
                and parsed.username is None and parsed.password is None
                and parsed.path in ('', '/') and not parsed.query and not parsed.fragment):
            return 'http://' + parsed.netloc
    except (TypeError, ValueError):
        pass
    return ''


def configured_proxy():
    try:
        return _proxy_url((data_root() / 'proxy.txt').read_text(encoding='utf-8').strip())
    except (OSError, ValueError):
        return ''


def request_proxies(url):
    host = urlsplit(url).hostname or ''
    proxy = '' if host in ('localhost', '::1') or host.startswith('127.') else configured_proxy()
    # Empty entries deliberately override environment or OS proxy discovery in requests.
    return {'http': proxy, 'https': proxy, 'all': ''}


def probe(hint, ports):
    """Check real TLS connectivity. This operation never changes routing."""
    import requests

    candidates = dict.fromkeys([_proxy_url(hint), *(f'http://127.0.0.1:{port}' for port in ports)])
    deadline = time.monotonic() + 18
    with requests.Session() as session:
        session.trust_env = False
        for proxy in filter(None, candidates):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            timeout = min(5, remaining)
            try:
                with session.get(PROBE_URL, proxies={'https': proxy},
                                 timeout=(timeout, timeout), allow_redirects=False, stream=True) as response:
                    if response.status_code == 200:
                        return {'proxy': proxy}
            except requests.RequestException:
                continue
    return {'proxy': ''}
