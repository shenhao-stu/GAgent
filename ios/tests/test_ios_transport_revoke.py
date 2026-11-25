"""Revoking an iOS grant also cancels utility connections that have no conversation owner."""
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import signed_runtime
from kernel_adapter import ios_transport as transport


class Reply:
    status_code = 200

    def __enter__(self):
        self.closed = False
        return self

    def close(self):
        self.closed = True

    def __exit__(self, *args):
        self.close()


def test_revoke_closes_an_open_utility_and_rejects_a_late_response():
    session = SimpleNamespace(stream=True, connect_timeout=1, read_timeout=1, proxies=None, verify=True)
    first, late = Reply(), Reply()

    def late_open(*args, **kwargs):
        transport.revoke()
        return late

    with patch.object(transport.ios_policy, 'model_headers', return_value={}), ExitStack() as stack:
        stack.enter_context(transport.post(SimpleNamespace(post=lambda *a, **k: first), session, 'https://example.com', {}, {}))
        assert not first.closed
        with pytest.raises(PermissionError):
            with transport.post(SimpleNamespace(post=late_open), session, 'https://example.com', {}, {}):
                pytest.fail('a response opened across revocation cannot expose its body')
        assert first.closed and late.closed


def test_timings_preserve_stream_and_never_record_request_contents():
    class Stream(Reply):
        def iter_lines(self, **kwargs):
            yield b''
            yield b'data: private-output'
        def json(self):
            return {'secret': 'body'}
    session = SimpleNamespace(stream=True, connect_timeout=1, read_timeout=1, proxies=None, verify=True)
    with patch.object(transport.ios_policy, 'model_headers', return_value={}):
        with transport.post(SimpleNamespace(post=lambda *a, **k: Stream()), session,
                            'https://secret.example', {'Authorization': 'private-key'}, {'prompt': 'private-input'}) as response:
            assert list(response.iter_lines()) == [b'', b'data: private-output']
            assert response.json() == {'secret': 'body'}
    row = transport.diagnostics()[-1]
    assert 0 <= row['headers_ms'] <= row['first_line_ms'] <= row['total_ms']
    assert row['status'] == 200
    assert 'private' not in str(row) and 'secret' not in str(row)
    row['status'] = 0
    assert transport.diagnostics()[-1]['status'] == 200
