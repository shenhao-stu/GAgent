"""Foreground recovery must be prompt without periodic application pings."""
import asyncio
import importlib.util
import json
import types
from unittest.mock import AsyncMock

import pytest

from .test_pclink_reconnect import CORE


@pytest.fixture
def link(monkeypatch):
    spec = importlib.util.spec_from_file_location('pclink_resume_test', CORE / 'pclink.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    clock = [100.0]
    monkeypatch.setattr(mod, 'time', types.SimpleNamespace(monotonic=lambda: clock[0]))
    mod.clock = clock
    config = {'url': 'wss://relay.example/ws', 'token': 'fixture-token'}
    mod.service_config = types.SimpleNamespace(pclink_config=lambda: config)
    mod._sock_config = config
    return mod


def test_recent_traffic_skips_probe_and_status_is_local(link, monkeypatch):
    async def run():
        link._sock = object()
        link._last_rx[0] = 99
        link._api = AsyncMock()
        await link._resume()
        link._api.assert_not_called()
        monkeypatch.setattr(link, '_paired', lambda: True)
        monkeypatch.setattr(link, '_ensure_loop', lambda: None)
        monkeypatch.setattr(link, '_signal', lambda: 'test')
        monkeypatch.setattr(link, '_resume', AsyncMock())
        for _ in range(100):
            assert json.loads(link.handle('/pclink.status'))['connected']
        link._resume.assert_not_called()
        link._api.assert_not_called()
    asyncio.run(run())


def test_resume_is_single_flight_and_rate_limited(link):
    async def run():
        link._sock = object()
        started, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def api(*args, **kwargs):
            calls.append(args)
            started.set()
            await release.wait()
        link._api = api
        task = asyncio.create_task(link._resume())
        await started.wait()
        link.clock[0] += 31
        await link._resume()  # cooldown expired but probe still in flight
        assert len(calls) == 1
        release.set()
        await task
        link.clock[0] = 110
        await link._resume()
        assert len(calls) == 1
        link.clock[0] = 131
        await link._resume()
        assert len(calls) == 2
    asyncio.run(run())


def test_disconnected_resume_bypasses_probe_cooldown(link):
    async def run():
        link._wake[0] = asyncio.Event()
        link._resume_at[0] = 100
        link._resume_busy[0] = True  # a previous connection's probe may still be unwinding
        for now in (100, 101, 129, 130):
            link.clock[0] = now
            await link._resume()
            assert link._wake[0].is_set()
            link._wake[0].clear()
    asyncio.run(run())


@pytest.mark.parametrize('outcome', ['dead', 'second_success', 'traffic', 'replaced'])
def test_probe_requires_two_failures_without_intervening_response(link, outcome):
    async def run():
        old = link._sock = object()
        calls = []
        async def api(*args, **kwargs):
            assert kwargs['count_timeout'] is False
            calls.append(args)
            if len(calls) == 1:
                if outcome == 'traffic':
                    link._last_rx[0] = link.clock[0]
                elif outcome == 'replaced':
                    link._sock = object()
            elif outcome == 'second_success':
                return {'status': 403}
            raise asyncio.TimeoutError()
        link._api = api
        link._drop = AsyncMock()
        await link._resume()
        assert len(calls) == (1 if outcome in ('traffic', 'replaced') else 2)
        assert link._drop.await_count == (1 if outcome == 'dead' else 0)
        if outcome == 'dead':
            link._drop.assert_awaited_once_with(old)
        assert not link._resume_busy[0]
    asyncio.run(run())


def test_old_receiver_does_not_cancel_new_requests(link):
    async def run():
        future = asyncio.get_running_loop().create_future()
        link._pending['new'] = future
        current = link._sock = object()
        link._wake[0] = asyncio.Event()
        old = types.SimpleNamespace(recv=AsyncMock(side_effect=ConnectionError('old')),
                                    close=AsyncMock())
        await link._receiver(old)
        assert link._sock is current
        assert not future.done()
        assert link._pending['new'] is future
        assert not link._wake[0].is_set()
        assert link._err[0] == ''
    asyncio.run(run())


def test_probe_deadline_includes_blocked_send(link):
    async def run():
        async def send(_):
            await asyncio.Event().wait()
        sock = link._sock = types.SimpleNamespace(send=AsyncMock(side_effect=send),
                                                 close=AsyncMock())
        link._wake[0] = asyncio.Event()
        loop = asyncio.get_running_loop()
        started = loop.time()
        await asyncio.wait_for(link._resume(), 10)
        elapsed = loop.time() - started
        assert 7.5 <= elapsed < 10
        assert sock.send.await_count == 2
        assert link._sock is None
        assert link._wake[0].is_set()
        assert not link._pending
        assert not link._resume_busy[0]
    asyncio.run(run())


def test_matching_response_is_recorded_as_liveness(link):
    async def run():
        future = asyncio.get_running_loop().create_future()
        link._pending['req'] = future
        release = asyncio.Event()
        calls = []
        async def recv():
            calls.append(1)
            if len(calls) == 1:
                return json.dumps({'type': 'p2p-http.res', 'id': 'req', 'status': 403})
            await release.wait()
            raise ConnectionError('closed')
        sock = link._sock = types.SimpleNamespace(recv=recv, close=AsyncMock())
        task = asyncio.create_task(link._receiver(sock))
        assert (await asyncio.wait_for(future, 1))['status'] == 403
        assert link._last_rx[0] == link.clock[0]
        release.set()
        await task
    asyncio.run(run())
