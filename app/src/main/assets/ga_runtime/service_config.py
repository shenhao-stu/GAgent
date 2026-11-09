"""Pure integration validation; explicit file I/O at the runtime boundary."""
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
import threading

_WRITE_LOCK = threading.Lock()

SERVICES = {
    'ganet': ('https', ('token', 'owner_id')),
    'voice': ('wss', ('token', 'model')),
    'apk': ('https', ('token',)),
    'pclink': ('wss', ('token',)),
}


def config_path():
    root = Path(os.environ.get('GA_DIR') or Path(__file__).resolve().parent)
    return root / 'kv' / 'ga.integrations.json'


def validate_service(name, value):
    if name not in SERVICES or not isinstance(value, dict):
        raise ValueError('Unknown integration or invalid configuration')
    scheme, fields = SERVICES[name]
    if set(value) - {'url', *fields}:
        raise ValueError('Unknown integration field')
    if any(not isinstance(v, str) for v in value.values()):
        raise ValueError('Integration values must be strings')
    url = value.get('url', '').strip().rstrip('/')
    if not url:
        return {}
    parsed = urlsplit(url)
    if (parsed.scheme != scheme or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.fragment
            or parsed.query or any(ord(c) < 33 or ord(c) == 127 for c in url)):
        raise ValueError('%s requires a %s URL without embedded credentials' % (name, scheme))
    if any(k.lower() in {'token', 'key', 'api_key', 'apikey', 'secret'}
           for k, _ in parse_qsl(parsed.query)):
        raise ValueError('Credentials belong in the token field, not the URL')
    parsed.port  # Reject malformed ports before storing or performing I/O.
    result = {'url': url, **{k: value.get(k, '').strip() for k in fields}}
    if name in ('ganet', 'apk', 'pclink') and not result['token']:
        raise ValueError('%s requires a service token' % name)
    if name == 'ganet' and not result['owner_id'].isdigit():
        raise ValueError('Mesh owner_id must be a numeric identity issued by your server')
    if any('\r' in v or '\n' in v for v in result.values()):
        raise ValueError('Integration fields cannot contain line breaks')
    return result


def merge_config(current, updates):
    """Blank token retains it only for the same endpoint; endpoint changes clear it."""
    if not isinstance(updates, dict) or set(updates) - SERVICES.keys():
        raise ValueError('Unknown integration')
    result = {name: dict(value) for name, value in current.items()}
    for name, incoming in updates.items():
        if not isinstance(incoming, dict):
            raise ValueError('Integration must be an object')
        value = dict(incoming)
        previous = current.get(name, {})
        if (not value.get('token') and 'token' in SERVICES[name][1]
                and value.get('url', '').strip().rstrip('/') == previous.get('url')):
            value['token'] = previous.get('token', '')
        normalized = validate_service(name, value)
        if normalized:
            result[name] = normalized
        else:
            result.pop(name, None)
    return result


def load_config():
    path = config_path()
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding='utf-8'))
    return merge_config({}, value)


def get_service(name):
    config = load_config().get(name)
    if not config:
        raise ValueError('Configure %s in Settings > Integrations first' % name)
    return config


def public_config():
    return {name: {**{k: v for k, v in config.items() if k != 'token'},
                   'has_token': bool(config.get('token'))}
            for name, config in load_config().items()}


def save_config(updates):
    with _WRITE_LOCK:
        _save_config(updates)


def _save_config(updates):
    value = merge_config(load_config(), updates)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.integrations-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


# PC Link has no build-provided default. Relay credentials come only from the
# user's own Optional modules settings, so no shared signing material is bundled.
# A stale pclink_defaults.json left by an older build is deliberately ignored.
def pclink_config():
    return load_config().get('pclink') or None
