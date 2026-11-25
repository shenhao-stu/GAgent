"""Two actual loopback hub sockets; a named operation may never move to the other computer."""
import asyncio
import base64
import contextlib
import json
import sys
from unittest.mock import patch

import pytest
import websockets

import signed_runtime
import pclink
from p2p_ws_client import HubUnion


def test_selected_hub_routes_encoded_names_and_never_falls_back_after_disconnect():
    async def check():
        sent = {'A': [], 'B': []}
        def handler(hub):
            async def respond(ws, *_):
                async for raw in ws:
                    req = json.loads(raw)
                    sent[hub].append((req['method'], req['target'], base64.b64decode(req['body'])))
                    payload = ({'rows': [{'name': 'd.new'}], 'psig': 'v1'}
                               if req['target'].startswith('/api/peers') else {'name': 'phone-1'})
                    await ws.send(json.dumps({'type': 'p2p-http.res', 'status': 200, 'id': req['id'],
                        'body': base64.b64encode(json.dumps(payload).encode()).decode()}))
            return respond
        union = HubUnion(timeout=2)
        async with contextlib.AsyncExitStack() as ctx:
            async def open_hub(hub):
                srv = await ctx.enter_async_context(websockets.serve(handler(hub), '127.0.0.1', 0))
                ws = await ctx.enter_async_context(websockets.connect('ws://127.0.0.1:%s' % srv.sockets[0].getsockname()[1]))
                task = asyncio.create_task(union.use(ws, 'hub:' + hub))
                return ws, task
            a, ta = await open_hub('A')
            b, tb = await open_hub('B')
            await asyncio.sleep(0)
            cfg = {'url': 'wss://relay.example.invalid/ws', 'token': 'tok'}
            with patch.object(pclink, '_config', return_value=cfg), \
                 patch.object(pclink, '_group', [('synthetic', cfg['url'], cfg['token']), None, union]):
                async def call(method, path, body=''):
                    reply = await pclink._api(method, path, body)
                    return reply['status'], json.loads(reply['body'])
                assert await call('GET', '/api/hubs') == (200, ['A', 'B'])
                assert [p['name'] for p in (await call('GET', '/api/peers'))[1]] == ['d.new@A', 'd.new@B']
                assert (await call('POST', '/api/sessions', '{}'))[0] == 409
                assert (await call('POST', '/api/sessions', '{"hub":"B"}'))[1]['name'] == 'phone-1@B'
                await call('POST', '/api/phone-1%40B/put', '{"text":"synthetic"}')
                assert sent['B'][-1] == ('POST', '/api/phone-1/put', b'{"text":"synthetic"}')
                assert sent['A'] == [('GET', '/api/peers?psig=', b'')]
                await b.close()
                await asyncio.gather(tb, return_exceptions=True)
                for missing in ('B', 'unknown'):
                    assert (await call('POST', '/api/phone-1%40'+missing+'/put', '{}'))[0] == 503
                assert len(sent['A']) == 1
                await a.close()
                await asyncio.gather(ta, return_exceptions=True)
    asyncio.run(check())


@pytest.mark.parametrize('method,path', [('GET','https://evil.invalid/api/peers'),
    ('GET','/api/%2e%2e/messages'),('POST','/api/a%2fb/put'),('POST','/api/x%252f/put'),
    ('GET','/api/a%5cb/messages'),('GET','/api/a%0a/messages'),('POST','/api/sessions/continue'),('POST','/api/hubs'),('DELETE','/api/desk/messages')])
def test_fixed_tool_rejects_untrusted_routes_before_request(method,path):
    with patch.object(pclink, 'handle', side_effect=AssertionError('must not send')):
        with pytest.raises(ValueError):
            pclink.ios_request(method,path)


def test_revocation_cancels_group_without_erasing_saved_room(tmp_path):
    async def run():
        room = tmp_path / 'pclink_rooms.json'
        room.write_text('{"pc":{"room":"synthetic"}}')
        running = asyncio.create_task(asyncio.sleep(3600))
        with patch.object(pclink,'ROOMS',str(room)), patch.object(pclink,'_group',['synthetic',running,HubUnion()]):
            await pclink._disconnect()
            assert running.cancelled()
            assert pclink._group == [None,None,None] and room.is_file()
    asyncio.run(run())


def test_group_target_never_falls_back_to_legacy_socket():
    class OtherComputer:
        async def send(self, data):
            pytest.fail('explicit hub must not fall back to a legacy computer')
    async def check():
        cfg = {'url': 'wss://relay.example.invalid/ws', 'token': 'tok'}
        with patch.object(pclink, '_config', return_value=cfg), \
             patch.object(pclink, '_sock_config', cfg), \
             patch.object(pclink, '_group', [None, None, None]), patch.object(pclink, '_sock', OtherComputer()):
            for path, body in [('/api/d.new%40A/put', '{}'),('/api/sessions','{"hub":"A"}')]:
                assert (await pclink._api('POST', path, body))['status'] == 503
    asyncio.run(check())
