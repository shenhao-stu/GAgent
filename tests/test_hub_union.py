"""A target and a response must remain bound to the selected PC connection."""
import asyncio
import base64
import importlib.util
import json
from pathlib import Path
import sys


PATH = Path(__file__).parents[1] / 'app/src/main/assets/ga_runtime/p2p_ws_client.py'
spec = importlib.util.spec_from_file_location('union_transport', PATH)
p2p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p2p
spec.loader.exec_module(p2p)


class Socket:
    def __init__(self):
        self.inbox = asyncio.Queue()
        self.sent = asyncio.Queue()

    async def send(self, data):
        await self.sent.put(json.loads(data))

    async def recv(self):
        return await self.inbox.get()


def test_missing_explicit_hub_never_falls_back():
    async def scenario():
        union = p2p.HubUnion()
        union.hubs['other'] = Socket()
        sent = []
        async def record(*args):
            sent.append(args)
            return 200, b'{"name":"new"}'
        union._one = record
        for target, body in [('/api/phone-1%40gone/put', b'{"text":"task"}'),
                             ('/api/sessions', b'{"hub":"gone"}')]:
            status, _ = await union.request('POST', target, body)
            assert status == 503
        assert not sent
    asyncio.run(scenario())


def test_encoded_session_stays_on_requested_hub():
    async def scenario():
        union = p2p.HubUnion()
        union.hubs.update(a=Socket(), b=Socket())
        sent = []
        async def record(*args):
            sent.append(args)
            return 200, b'{}'
        union._one = record
        await union.request('GET', '/api/phone%20one%40b/messages?off=2')
        assert sent == [('b', 'GET', '/api/phone%20one/messages?off=2', b'')]
    asyncio.run(scenario())


def test_response_cannot_cross_hubs_or_connection_generations():
    async def scenario():
        union = p2p.HubUnion(timeout=1)
        old, other, current = Socket(), Socket(), Socket()
        tasks = [asyncio.create_task(union.use(old, 'hub:a')),
                 asyncio.create_task(union.use(other, 'hub:b'))]
        await asyncio.sleep(0)
        tasks.append(asyncio.create_task(union.use(current, 'hub:a')))
        await asyncio.sleep(0)
        request = asyncio.create_task(union._one('a', 'GET', '/api/peers'))
        try:
            frame = await current.sent.get()
            response = {'v': 1, 'type': 'p2p-http.res', 'id': frame['id'],
                        'status': 200, 'body': base64.b64encode(b'correct').decode()}
            for source in (other, old):
                await source.inbox.put(json.dumps({**response, 'body': 'd3Jvbmc='}))
                await asyncio.sleep(0)
                assert not request.done()
            await current.inbox.put(json.dumps({**response, 'type': 'p2p-http.req'}))
            await asyncio.sleep(0)
            assert not request.done()
            await current.inbox.put(json.dumps(response))
            assert await request == (200, b'correct')
        finally:
            request.cancel()
            for task in tasks:
                task.cancel()
            await asyncio.gather(request, *tasks, return_exceptions=True)
    asyncio.run(scenario())


def test_disconnect_fails_owned_request_without_waiting_for_timeout():
    async def scenario():
        union, socket = p2p.HubUnion(timeout=10), Socket()
        receiver = asyncio.create_task(union.use(socket, 'hub:a'))
        await asyncio.sleep(0)
        request = asyncio.create_task(union._one('a', 'GET', '/api/peers'))
        await socket.sent.get()
        receiver.cancel()
        await asyncio.gather(receiver, return_exceptions=True)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        try:
            assert request.done()
            assert isinstance(request.exception(), ConnectionError)
        finally:
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)
    asyncio.run(scenario())


def test_legacy_receiver_cannot_complete_requests_on_replacement_socket():
    """A delayed old receiver must not consume a new connection's request ID."""
    import types
    from unittest.mock import AsyncMock
    sys.path.insert(0, str(PATH.parent))
    spec = importlib.util.spec_from_file_location('legacy_link_under_test', PATH.with_name('pclink.py'))
    link = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(link)

    async def scenario():
        old, current = Socket(), Socket()
        old.close = current.close = AsyncMock()
        link._sock = current
        future = asyncio.get_running_loop().create_future()
        link._pending['1'] = future
        receivers = [asyncio.create_task(link._receiver(s)) for s in (old, current)]
        frame = json.dumps({'type': 'p2p-http.res', 'id': '1', 'status': 200})
        try:
            await old.inbox.put(frame)
            await asyncio.sleep(0)
            assert not future.done()
            assert link._pending['1'] is future
            await current.inbox.put(frame)
            assert (await asyncio.wait_for(future, .5))['status'] == 200
        finally:
            for receiver in receivers:
                receiver.cancel()
            await asyncio.gather(*receivers, return_exceptions=True)
    asyncio.run(scenario())
