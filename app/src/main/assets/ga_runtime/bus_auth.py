"""Attach the runtime bus capability only to the app's exact loopback origin."""
import os
from pathlib import Path
from urllib.parse import urlsplit

BUS_PORT = 18765
def current_port():
    root = Path(os.environ.get('GA_DIR') or Path(__file__).resolve().parent)
    try:
        port = int((root / 'bus_port.txt').read_text(encoding='ascii').strip())
    except FileNotFoundError:
        return BUS_PORT
    if not 1 <= port <= 65535:
        raise ValueError('Invalid local bus port; restart the app')
    return port


BUS_URL = 'http://127.0.0.1:%d' % current_port()


def headers(url):
    parsed = urlsplit(url)
    if (parsed.scheme, parsed.hostname, parsed.port) != ('http', '127.0.0.1', current_port()):
        return {}
    if parsed.username is not None or parsed.password is not None:
        raise ValueError('Credentials in a bus URL are not allowed')
    root = Path(os.environ.get('GA_DIR') or Path(__file__).resolve().parent)
    token = (root / '.bus_token').read_text(encoding='ascii').strip()
    if len(token) != 64 or any(c not in '0123456789abcdef' for c in token):
        raise ValueError('Invalid local capability; restart the app')
    return {'Authorization': 'Bearer ' + token}
