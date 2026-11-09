"""A configured room owns exactly one group; revocation also closes its peers."""
import asyncio
from pathlib import Path
import importlib.util
import sys
import types

PATH = Path(__file__).parents[1] / 'app/src/main/assets/ga_runtime/pclink.py'
sys.path.insert(0, str(PATH.parent))


def fixture(monkeypatch):
    spec = importlib.util.spec_from_file_location('group_link_test', PATH)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    config = {'url': 'wss://relay.example/ws', 'token': 'fixture-one'}
    state = {'config': config, 'saved': {'room': 'fixture-room', 'signal_url': config['url']},
             'groups': [], 'closed': [], 'release': asyncio.Event(), 'closing': asyncio.Event()}
    class Group:
        def __init__(self, url, room, me, serve, use, **kwargs):
            self.token = kwargs['access_key']; state['groups'].append(self)
        async def run(self):
            try:
                await asyncio.Event().wait()
            finally:
                state['closing'].set()
                await state['release'].wait()
                state['closed'].append(self)
    monkeypatch.setattr(mod.service_config, 'pclink_config', lambda: state['config'])
    monkeypatch.setitem(sys.modules, 'p2p_ws_client', types.SimpleNamespace(
        load_room=lambda *a, **k: state['saved'], Group=Group,
        HubUnion=lambda: types.SimpleNamespace(use=None)))
    return mod, state


def test_group_tracks_credential_rotation_and_disabled_configuration(monkeypatch):
    mod, state = fixture(monkeypatch)
    async def run():
        state['release'].set()
        assert await mod._sync_group(state['config'])
        await asyncio.sleep(0)
        assert not await mod._sync_group(state['config'])
        state['config'] = {**state['config'], 'token': 'fixture-two'}
        assert await mod._sync_group(state['config'])
        await asyncio.sleep(0)
        assert len(state['closed']) == 1
        assert state['groups'][-1].token == 'fixture-two'
        state['config'] = None
        assert not await mod._sync_group(None)
        assert len(state['closed']) == 2
        assert mod._group == [None, None, None]
    asyncio.run(run())


def test_group_does_not_reuse_room_at_a_changed_origin(monkeypatch):
    mod, state = fixture(monkeypatch)
    state['config'] = {**state['config'], 'url': 'wss://different.example/ws'}
    assert not asyncio.run(mod._sync_group(state['config']))
    assert not state['groups']


def test_overlapping_group_changes_do_not_leave_unowned_connections(monkeypatch):
    mod, state = fixture(monkeypatch)
    async def run():
        await mod._sync_group(state['config'])
        await asyncio.sleep(0)
        state['config'] = {**state['config'], 'token': 'fixture-two'}
        first = asyncio.create_task(mod._sync_group(state['config']))
        await asyncio.wait_for(state['closing'].wait(), .5)
        second = asyncio.create_task(mod._sync_group(state['config']))
        await asyncio.sleep(0)
        state['release'].set()
        await asyncio.wait_for(asyncio.gather(first, second), .5)
        await asyncio.sleep(0)
        try:
            assert len(state['groups']) == 2
        finally:
            state['config'] = None
            await mod._sync_group(None)
    asyncio.run(run())
