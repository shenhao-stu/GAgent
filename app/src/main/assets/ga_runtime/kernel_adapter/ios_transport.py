"""Model transport boundaries of the signed iOS host."""
from contextlib import contextmanager
import json
import time
from collections import deque
import threading
import ios_policy


# The lock protects admission, not network I/O. Revocation invalidates pending opens too.
_lock = threading.Lock()
_epoch = 0
_active = {}
_timings = deque(maxlen=64)


def diagnostics(thread=None):
    with _lock:
        return [dict(row) for row in _timings if thread is None or row['thread'] == thread]


class MeasuredResponse:
    def __init__(self, response, started, row):
        self._response, self._started, self._row = response, started, row

    def __getattr__(self, name):
        return getattr(self._response, name)

    def iter_lines(self, *args, **kwargs):
        for line in self._response.iter_lines(*args, **kwargs):
            if line and 'first_line_ms' not in self._row:
                with _lock:
                    self._row['first_line_ms'] = round((time.monotonic() - self._started) * 1000)
            yield line


def revoke():
    global _epoch
    with _lock:
        _epoch += 1
        streams = tuple(_active.values())
        _active.clear()
    for stream in streams:
        try:
            stream.close()
        except OSError:
            pass


def split_images(messages):
    images, text = [], []
    for message in messages:
        parts = message.get('content')
        if not isinstance(parts, list):
            text.append(message)
            continue
        images.extend(p for p in parts if p.get('type') == 'image')
        text.append({**message, 'content': '\n'.join(p['text'] for p in parts if p.get('type') == 'text')})
    return text, images


def context_cost(message):
    """Estimate context characters, not Base64 transport bytes; keep the actual pixels untouched.

    Budget 4k token-equivalents per image (12k characters), conservatively for the host's
    1600-pixel screenshots. This is a pruning estimate, never provider billing telemetry.
    """
    def measured(value):
        if isinstance(value, dict):
            if value.get('type') in ('image', 'image_url', 'input_image'):
                return {'image_context_budget': '.' * 12_000}
            return {key: measured(part) for key, part in value.items()}
        if isinstance(value, list):
            return [measured(part) for part in value]
        return value
    return len(json.dumps(measured(message), ensure_ascii=False))


@contextmanager
def post(http, session, url, headers, payload):
    with _lock:
        epoch = _epoch
    headers = {**headers, **ios_policy.model_headers(session)}
    with _lock:
        if epoch != _epoch:
            raise PermissionError('模型数据分享已撤销')

    started = time.monotonic()
    row = {'started': time.time(), 'thread': threading.get_ident()}
    with _lock:
        _timings.append(row)
    try:
        with _measured_post(http, session, url, headers, payload, epoch, started, row) as response:
            yield response
    except Exception as exc:
        with _lock:
            row['error'] = type(exc).__name__
        raise
    finally:
        with _lock:
            row['total_ms'] = round((time.monotonic() - started) * 1000)


@contextmanager
def _measured_post(http, session, url, headers, payload, epoch, started, row):
    from kernel_adapter.ios_proxy import request_proxies

    with http.post(url, headers=headers, json=payload, stream=session.stream,
                   timeout=(session.connect_timeout, session.read_timeout),
                   proxies=request_proxies(url), verify=session.verify, allow_redirects=False) as response:
        with _lock:
            if epoch != _epoch:
                raise PermissionError('模型数据分享已撤销')
            _active[id(response)] = response
            row['headers_ms'] = round((time.monotonic() - started) * 1000)
            row['status'] = response.status_code
        try:
            if 300 <= response.status_code < 400:
                raise ValueError('iOS 不向重定向端点发送模型请求')
            yield MeasuredResponse(response, started, row)
        finally:
            with _lock:
                _active.pop(id(response), None)
