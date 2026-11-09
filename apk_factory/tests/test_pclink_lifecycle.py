"""Pairing, automatic reconnect and unlink must share one connection owner."""
import asyncio
import contextlib
import json
import sys
import threading
import types
from concurrent.futures import TimeoutError as FutureTimeoutError
from unittest.mock import AsyncMock

import pytest

from .test_pclink_reconnect import _module


@pytest.fixture
def link(monkeypatch, tmp_path):
    mod = _module()
    rooms = tmp_path / 'rooms.json'
    rooms.write_text('{}')
    mod.ROOMS = str(rooms)
    monkeypatch.setattr(mod, '_signal', lambda: 'wss://relay.example/ws')
    monkeypatch.setattr(mod, '_sync_group', AsyncMock(return_value=False))
    monkeypatch.setattr(mod, '_paired', lambda: 'pc' in json.loads(rooms.read_text()))
    monkeypatch.setattr(mod, '_attach', lambda sock, config: setattr(mod, '_sock', sock))
    return mod, rooms


async def stop(task):
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def test_pair_excludes_automatic_reconnect(link, monkeypatch):
    mod, rooms = link

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        sock = types.SimpleNamespace(close=AsyncMock())

        async def pair(*args, **kwargs):
            rooms.write_text('{"pc":{"room":"synthetic","signal_url":"wss://relay.example/ws"}}')
            started.set()
            await release.wait()
            return sock

        saved = AsyncMock(return_value=sock)
        monkeypatch.setitem(sys.modules, 'p2p_ws_client', types.SimpleNamespace(load_room=lambda *a, **k: json.loads(rooms.read_text())['pc'], 
            connect_code=pair, connect_saved=saved))
        pairing = asyncio.create_task(mod._pair('123456789'))
        await asyncio.wait_for(started.wait(), 1)
        keeper = asyncio.create_task(mod._keeper())
        try:
            await asyncio.sleep(0.02)
            saved.assert_not_called()
            release.set()
            await pairing
            assert mod._sock is sock
        finally:
            await stop(keeper)
            await stop(pairing)

    asyncio.run(scenario())


@pytest.mark.parametrize('return_after_cancel', [False, True])
def test_unpair_cancels_inflight_reconnect(link, monkeypatch, return_after_cancel):
    mod, rooms = link
    rooms.write_text('{"pc":{"room":"synthetic","signal_url":"wss://relay.example/ws"},"other":{"room":"keep"}}')

    async def scenario():
        started, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        sock = types.SimpleNamespace(close=AsyncMock())

        async def saved(*args, **kwargs):
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                if not return_after_cancel:
                    raise
            return sock

        monkeypatch.setitem(sys.modules, 'p2p_ws_client', types.SimpleNamespace(connect_saved=saved, load_room=lambda *a, **k: json.loads(rooms.read_text())['pc']))
        keeper = asyncio.create_task(mod._keeper())
        try:
            await asyncio.wait_for(started.wait(), 1)
            await asyncio.wait_for(mod._unpair(), 0.5)
            release.set()
            await asyncio.sleep(0.02)
            assert mod._sock is None
            assert cancelled.is_set()
            assert not keeper.done(), 'unlink must not kill the reconnect worker'
            assert json.loads(rooms.read_text()) == {'other': {'room': 'keep'}}
            if return_after_cancel:
                sock.close.assert_awaited_once()
        finally:
            await stop(keeper)

    asyncio.run(scenario())


def test_new_pair_waits_for_old_reconnect_cleanup(link, monkeypatch):
    mod, rooms = link
    rooms.write_text('{"pc":{"room":"synthetic","signal_url":"wss://relay.example/ws"}}')

    async def scenario():
        started, cancelled = asyncio.Event(), asyncio.Event()
        new = types.SimpleNamespace(close=AsyncMock())

        async def saved(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        async def pair(*args, **kwargs):
            assert cancelled.is_set(), 'new handshake overlaps the old socket'
            return new

        monkeypatch.setitem(sys.modules, 'p2p_ws_client', types.SimpleNamespace(load_room=lambda *a, **k: json.loads(rooms.read_text())['pc'], 
            connect_saved=saved, connect_code=pair))
        keeper = asyncio.create_task(mod._keeper())
        try:
            await asyncio.wait_for(started.wait(), 1)
            await asyncio.wait_for(mod._pair('123456789'), 0.5)
            assert mod._sock is new
            assert not keeper.done()
        finally:
            await stop(keeper)

    asyncio.run(scenario())


def test_unpair_settles_old_requests(link):
    mod, _ = link

    async def scenario():
        mod._sock = types.SimpleNamespace(close=AsyncMock())
        pending = asyncio.get_running_loop().create_future()
        mod._pending['old'] = pending
        await mod._unpair()
        assert pending.cancelled()
        assert not mod._pending

    asyncio.run(scenario())


@pytest.mark.parametrize('return_after_cancel', [False, True])
def test_unpair_supersedes_an_inflight_pair(link, monkeypatch, return_after_cancel):
    mod, rooms = link

    async def scenario():
        started = asyncio.Event()
        sock = types.SimpleNamespace(close=AsyncMock())

        async def pair(*args, **kwargs):
            rooms.write_text('{"pc":{"room":"synthetic","signal_url":"wss://relay.example/ws"}}')
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                if not return_after_cancel:
                    raise
            return sock

        monkeypatch.setitem(sys.modules, 'p2p_ws_client', types.SimpleNamespace(load_room=lambda *a, **k: json.loads(rooms.read_text())['pc'], connect_code=pair))
        pairing = asyncio.create_task(mod._pair('123456789'))
        try:
            await asyncio.wait_for(started.wait(), 1)
            await asyncio.wait_for(mod._unpair(), 0.5)
            with pytest.raises(ConnectionError, match='replaced'):
                await asyncio.wait_for(pairing, 0.5)
            assert not mod._paired() and mod._sock is None
            if return_after_cancel:
                sock.close.assert_awaited_once()
        finally:
            if not pairing.done():
                await stop(pairing)

    asyncio.run(scenario())


def test_repeated_pair_replacement_finishes_socket_cleanup(link, monkeypatch):
    mod, _ = link

    async def scenario():
        closing, release = asyncio.Event(), asyncio.Event()
        old = types.SimpleNamespace(closed=False, cleaned=False)

        async def close():
            if old.closed:
                return
            old.closed = True
            closing.set()
            await release.wait()
            old.cleaned = True

        old.close = close
        mod._sock = old
        new = types.SimpleNamespace(close=AsyncMock())
        connected = AsyncMock(return_value=new)
        monkeypatch.setitem(sys.modules, 'p2p_ws_client', types.SimpleNamespace(load_room=lambda *a, **k: json.loads(rooms.read_text())['pc'], connect_code=connected))
        pairs = [asyncio.create_task(mod._pair('123456789'))]
        try:
            await closing.wait()
            for code in ('234567891', '345678912'):
                pairs.append(asyncio.create_task(mod._pair(code)))
                await asyncio.sleep(0.02)
            connected.assert_not_called()
            release.set()
            results = await asyncio.wait_for(asyncio.gather(*pairs, return_exceptions=True), 0.5)
            assert all(isinstance(result, ConnectionError) for result in results[:-1])
            assert results[-1] is None
            assert old.cleaned and mod._sock is new
            assert connected.call_args.args[1] == '345678912'
            assert connected.await_count == 1
        finally:
            release.set()
            await asyncio.gather(*pairs, return_exceptions=True)

    asyncio.run(scenario())


def test_unpair_write_failure_is_reported_and_keeps_saved_rooms(link, monkeypatch):
    mod, rooms = link
    original = '{"pc":{"room":"synthetic","signal_url":"wss://relay.example/ws"},"other":{"room":"keep"}}'
    rooms.write_text(original)
    real_open = open

    def blocked_write(path, mode='r', *args, **kwargs):
        if str(path) == str(rooms) and 'w' in mode:
            raise PermissionError('read-only pairing store')
        return real_open(path, mode, *args, **kwargs)

    def blocked_remove(path):
        raise PermissionError('read-only pairing store')

    monkeypatch.setattr('builtins.open', blocked_write)
    monkeypatch.setattr(mod.os, 'remove', blocked_remove)
    monkeypatch.setattr(mod.os, 'replace', lambda *args: blocked_remove(args[0]))
    with pytest.raises(PermissionError, match='read-only'):
        asyncio.run(mod._unpair())
    assert rooms.read_text() == original


@pytest.mark.parametrize('mode', ['reconnect', 'pair'])
def test_new_connection_waits_for_receiver_cleanup(link, monkeypatch, mode):
    mod, rooms = link
    rooms.write_text('{"pc":{"room":"synthetic","signal_url":"wss://relay.example/ws"}}')

    async def scenario():
        closing, release, connected = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def close():
            closing.set()
            await release.wait()

        old = mod._sock = types.SimpleNamespace(close=close)
        new = types.SimpleNamespace(close=AsyncMock())

        async def connect(*args, **kwargs):
            connected.set()
            return new

        monkeypatch.setitem(sys.modules, 'p2p_ws_client', types.SimpleNamespace(load_room=lambda *a, **k: json.loads(rooms.read_text())['pc'], 
            connect_saved=connect, connect_code=connect))
        dropping = asyncio.create_task(mod._drop(old))
        await closing.wait()
        action = asyncio.create_task(mod._keeper() if mode == 'reconnect' else mod._pair('123456789'))
        try:
            await asyncio.sleep(0.02)
            assert not connected.is_set(), 'old receiver is still releasing its room'
            release.set()
            await dropping
            await asyncio.wait_for(connected.wait(), 0.5)
            assert mod._sock is new
        finally:
            release.set()
            await dropping
            await stop(action)

    asyncio.run(scenario())


def test_bridge_timeout_cancels_background_operation(link, monkeypatch):
    mod, _ = link
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever)
    thread.start()
    cancelled = threading.Event()
    monkeypatch.setattr(mod, '_ensure_loop', lambda: loop)

    async def blocked():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def cleanup():
        tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    try:
        with pytest.raises(FutureTimeoutError):
            mod._call(blocked(), 0.02)
        assert cancelled.wait(0.5), 'timed-out bridge operation is still running'
    finally:
        asyncio.run_coroutine_threadsafe(cleanup(), loop).result(1)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(1)
        loop.close()
