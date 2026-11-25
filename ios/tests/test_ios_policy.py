"""Offline regression tests for the open-source iOS Agent's runtime boundary.
Run: python3 -m unittest discover -s ios/tests -p 'test_ios_policy.py' -v
No credentials, model calls, device operations, or production files are used.
"""
import asyncio
import json
import os
import queue
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from signed_runtime import CORE, HOST
import ios_policy as policy
import requests
import ga
import agentmain
from kernel_adapter.ios_host import IOSHandler
import llmcore
import android_entry
from agent_loop import exhaust


class IOSPolicyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name).resolve()
        for name in ('temp', 'memory', 'uploads', 'kv'):
            (self.root / name).mkdir()
        self.env = patch.dict(os.environ, {'GA_DIR': str(self.root)})
        self.env.start()
        self.platform = patch.object(sys, 'platform', 'ios')
        self.platform.start()
        policy._sessions.clear()
        policy.invalidate_policy()
        self.write_config()

    def tearDown(self):
        self.platform.stop()
        self.env.stop()
        self.directory.cleanup()
        policy._sessions.clear()

    def write_config(self, source=None):
        (self.root / 'mykey.py').write_text(
            source or "native_oai_config = dict(apibase='https://example.com/v1', apikey='test-only', model='model-a', name='Custom')\n"
        )

    def grant(self):
        state = policy.consent_status(refresh=True)
        return json.loads(policy.consent_command('/ios.consent ' + json.dumps({
            'version': state['version'], 'providerSignature': state['providerSignature'], 'accepted': True})))

    def session(self, endpoint='https://example.com/v1', model='model-a'):
        class Session: pass
        s = Session()
        s.api_base, s.model, s.api_key, s.proxies, s.verify = endpoint, model, 'test-only', None, True
        s.name, s.stream = 'Fixture', False
        policy.register_session(s)
        return s

    def test_legacy_literals_aliases_and_constructors(self):
        result = policy.parse_config(
            "key='demo'\nbase=dict(apibase='https://example.com',apikey=key)\n"
            "native_oai_config={**base,'model':'a','temperature':-0.5}\n"
            "mixin_config=dict(llm_nos=list(['a','b']))\n"
        )
        self.assertEqual(result['native_oai_config']['apikey'], 'demo')
        self.assertEqual(result['mixin_config']['llm_nos'], ['a', 'b'])

    def test_dynamic_config_never_executes_and_keeps_source(self):
        marker = self.root / 'executed'
        for source in (
            f"open({str(marker)!r}, 'w').write('bad')",
            "import os",
            "native_oai_config = dict(apikey=__import__('os').getcwd())",
            "x=[i for i in range(5)]",
            "x = {}; x.update(a=1)",
        ):
            self.write_config(source)
            with self.assertRaises(ValueError):
                policy.load_config()
            self.assertEqual((self.root / 'mykey.py').read_text(), source)
            self.assertFalse(marker.exists())

    def test_writable_mykey_is_read_as_data_not_imported(self):
        values = llmcore._load_mykeys()
        self.assertEqual(values['native_oai_config']['model'], 'model-a')
        self.assertNotIn('mykey', sys.modules)

    def test_file_paths_traversal_and_symlinks(self):
        self.assertEqual(policy.checked_path('../memory/note.md', write=True), str(self.root / 'memory/note.md'))
        for name in ('../mykey.py', '../kv/ga.auth.json', '../../outside', str(CORE / 'agentmain.py')):
            with self.assertRaises(ValueError):
                policy.checked_path(name, write=True)
        (self.root / 'temp' / 'escape').symlink_to(self.root / 'kv', target_is_directory=True)
        with self.assertRaises(ValueError):
            policy.checked_path('escape/ga.auth.json', write=True)
        self.assertEqual(policy.checked_path('../memory/helper.py', write=True), str(self.root / 'memory/helper.py'))
        with self.assertRaises(ValueError):
            policy.checked_path('../memory/helper.so', write=True)
        self.assertEqual(policy.checked_path('pc-script.py', write=True), str(self.root / 'temp/pc-script.py'))

    def test_file_tools_keep_their_scope_and_code_run_executes(self):
        handler = IOSHandler(agentmain.GenericAgent(), cwd=str(self.root / 'temp'))
        response = types.SimpleNamespace(content='')
        result = exhaust(handler.dispatch('file_write', {'path': 'note.txt', 'content': 'Hello'}, response))
        self.assertEqual(result.data['status'], 'success')
        result = exhaust(handler.dispatch('file_patch', {'path': 'note.txt', 'old_content': 'Hello', 'new_content': 'Hello iOS'}, response))
        self.assertEqual(result.data['status'], 'success')
        self.assertIn('Hello iOS', ga.file_read(str(self.root / 'temp/note.txt')))
        denied = exhaust(handler.dispatch('file_write', {'path': '../mykey.py', 'content': 'bad'}, response))
        self.assertEqual(denied.data['status'], 'error')
        result = exhaust(handler.dispatch('code_run', {'script': "open('ran.txt','w').write('tool'); print('done')"}, response))
        self.assertEqual((result.data['status'], result.data['exit_code']), ('success', 0))
        self.assertIn('done', result.data['stdout'])
        self.assertEqual((self.root / 'temp/ran.txt').read_text(), 'tool')
        inline = exhaust(handler.dispatch('code_run', {'script': '1 + 1', 'inline_eval': True}, response))
        self.assertEqual(inline.data, '2')
        self.assertEqual(exhaust(ga.code_run("print('direct')"))['stdout'], 'direct\n')
        for unsupported in ('web_scan', 'pc_catalog', 'pc_call'):
            missing = exhaust(handler.dispatch(unsupported, {}, response))
            self.assertEqual(missing.data, {'status': 'error', 'msg': policy.UNSUPPORTED_TOOL})

    def test_file_refs_and_missing_file_suggestions_never_expose_credentials(self):
        temp = self.root / 'temp'
        (temp / 'public.txt').write_text('permitted line\n')
        (temp / 'alias.txt').symlink_to(self.root / 'mykey.py')
        self.assertEqual(ga.expand_file_refs('{{file:public.txt:1:1}}', temp), 'permitted line\n')
        for path in ('../mykey.py', 'alias.txt'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                ga.expand_file_refs('{{file:' + path + ':1:1}}', temp)
        result = ga.file_read(str(temp / 'myke.py'))
        self.assertNotIn(str(self.root / 'mykey.py'), result)
        self.assertNotIn('test-only', result)

    def test_runtime_session_command_never_loads_paths_or_sets_recipient(self):
        agent = agentmain.GenericAgent()
        agent.llmclient = types.SimpleNamespace(backend=types.SimpleNamespace(model='existing'))
        outputs = queue.Queue()
        for key in ('api_base', 'api_key', 'log_path', '__class__'):
            agent._handle_slash_cmd('/session.' + key + '=../mykey.py', outputs)
            reply = outputs.get_nowait()['done']
            self.assertEqual(vars(agent.llmclient.backend), {'model': 'existing'})
            self.assertNotIn('test-only', reply)
        agent._handle_slash_cmd('/session.model=../mykey.py', outputs)
        self.assertEqual(agent.llmclient.backend.model, '../mykey.py')
        self.assertNotIn('test-only', outputs.get_nowait()['done'])

    def test_memory_index_cannot_expose_a_symlinked_credential_file_in_model_prompt(self):
        index = self.root / 'memory/global_mem_insight.txt'
        index.symlink_to(self.root / 'mykey.py')
        self.assertNotIn('test-only', agentmain.get_system_prompt())
        self.assertNotIn('test-only', ga.load_L1())

    def test_reading_a_note_cannot_overwrite_credentials_through_statistics_link(self):
        note = self.root / 'memory/notes.md'
        note.write_text('permitted note')
        credentials = self.root / 'mykey.py'
        original = credentials.read_bytes()
        (self.root / 'memory/file_access_stats.json').symlink_to(credentials)
        agent = agentmain.GenericAgent()
        agent.llmclient = types.SimpleNamespace(backend=types.SimpleNamespace(maxlen_multiplier=1))
        handler = IOSHandler(agent, cwd=str(self.root / 'temp'))
        with patch.object(ga, 'script_dir', str(self.root)):
            reply = exhaust(handler.dispatch('file_read', {'path': '../memory/notes.md'}, types.SimpleNamespace(content='')))
        self.assertIn('permitted note', reply.data)
        self.assertEqual(credentials.read_bytes(), original)

    def test_consent_required_for_model_and_pc_first_run(self):
        with self.assertRaises(policy.ConsentRequired):
            policy.require_consent()
        with self.assertRaises(policy.ConsentRequired):
            policy.model_headers(self.session())
        self.grant()
        self.assertTrue(policy.has_consent())
        self.assertEqual(policy.model_headers(self.session()), {})

    def test_model_key_and_mixin_changes_keep_same_recipient_consent(self):
        session = self.session()
        original = self.grant()
        session.model = 'model-b'
        session.api_key = 'rotated-test-only'
        self.write_config(
            "native_oai_config=dict(apibase='https://example.com/v1',apikey='rotated-test-only',model='model-b',name='Custom')\n"
            "mixin_config={'llm_nos':['Custom','Other']}\n"
        )
        self.assertEqual(policy.model_headers(session), {})
        with (self.root / 'mykey.py').open('a') as f:
            f.write("mixin_config = {'llm_nos':['Other','Custom']}\n")
        current = policy.consent_status()
        self.assertTrue(current['accepted'])
        self.assertTrue(all(r['accepted'] for r in current['receivers']))
        self.assertEqual(current['providerSignature'], original['providerSignature'])
        self.assertEqual(policy.model_headers(session), {})
        self.assertTrue(policy.has_consent())

    def test_unused_new_config_and_old_session_do_not_revoke_current_receiver(self):
        self.grant()
        with (self.root / 'mykey.py').open('a') as f:
            f.write("other_oai_config=dict(apibase='https://unused.example/v1',apikey='unused',model='other',name='Other')\n")
        stale = self.session('https://old.example/v1', 'old')
        state = policy.consent_status()
        current = next(r for r in state['receivers'] if r['providerId'] == state['providerIds']['Custom'])
        self.assertTrue(current['accepted'])
        self.assertFalse(state['accepted'])
        self.assertTrue(any(not r['accepted'] for r in state['receivers']))
        self.assertEqual(policy.model_headers(self.session()), {})
        with self.assertRaises(policy.ConsentRequired):
            policy.model_headers(stale)
        with self.assertRaises(policy.ConsentRequired):
            policy.model_headers(self.session('https://unused.example/v1', 'other'))

    def test_legacy_grants_survive_model_key_change_restart_and_union(self):
        state = policy.consent_status()
        legacy = {
            'version': state['version'], 'acceptedAt': 1, 'pcAccepted': True,
            'mixinSignature': 'legacy-routing-hash',
            'receivers': [{k: v for k, v in r.items() if k not in ('accepted', 'needsRefresh')} for r in state['receivers']],
        }
        policy._consent_file().write_text(json.dumps(legacy))
        self.write_config("other_oai_config=dict(apibase='https://other.example/v1',apikey='other',model='other')\n")
        shown = policy.consent_status()
        granted = self.grant()
        self.assertTrue(granted['accepted'])
        self.assertTrue(all(r['accepted'] for r in granted['receivers']))
        self.assertEqual(shown['providerSignature'], granted['providerSignature'])
        self.assertEqual(len(policy._saved_consent()['receivers']), 2)
        policy._sessions.clear()
        policy.invalidate_policy()
        self.write_config("native_oai_config=dict(apibase='https://example.com/v1',apikey='new-key',model='new-model',name='Custom')\n")
        self.assertTrue(policy.consent_status()['accepted'])
        session = self.session(model='new-model')
        session.api_key = 'new-key'
        self.assertEqual(policy.model_headers(session), {})

    def test_invalid_unused_endpoint_is_isolated_and_redacted(self):
        with (self.root / 'mykey.py').open('a') as f:
            f.write("bad_oai_config = dict(apibase='https://user:do-not-expose@example.com/v1?key=do-not-expose',apikey='test-only',model='bad')\n")
        state = self.grant()
        self.assertNotIn('do-not-expose', json.dumps(state))
        self.assertTrue(any(r.get('unavailable') for r in state['receivers']))
        self.assertEqual(policy.model_headers(self.session()), {})
        self.assertTrue(policy.has_consent())

    def test_revoke_blocks_new_requests_without_losing_documents(self):
        self.grant()
        (self.root / 'temp/note.txt').write_text('keep')
        policy.consent_command('/ios.consent {"accepted":false}')
        self.assertFalse(policy.has_consent())
        with self.assertRaises(policy.ConsentRequired):
            policy.model_headers(self.session())
        self.assertEqual((self.root / 'temp/note.txt').read_text(), 'keep')

    def test_actual_model_http_entry_denies_before_network(self):
        session = self.session()
        session.max_retries = 0
        with patch.object(requests, 'post', side_effect=AssertionError('network must not run')) as post:
            result = ''.join(llmcore._stream_with_retry(session, 'https://example.com/v1/chat/completions', {}, {}, lambda r: iter(())))
        self.assertIn('ios_consent_required', result)
        post.assert_not_called()

    def test_subset_accept_grants_only_displayed_scopes_and_rejects_wrong_signature(self):
        with (self.root / 'mykey.py').open('a') as f:
            f.write("other_oai_config=dict(name='Other',apibase='https://other.example/v1',apikey='other',model='other')\n")
        selected = policy.provider_id('https://example.com/v1', 'test-only')
        other = policy.provider_id('https://other.example/v1', 'other')
        shown = policy.consent_status(provider_ids=[selected])
        payload = {
            'accepted': True, 'version': shown['version'],
            'providerSignature': shown['providerSignature'], 'providerIds': [selected],
        }
        command = lambda p: json.loads(policy.consent_command('/ios.consent ' + json.dumps(p)))
        with self.assertRaises(policy.ConsentRequired):
            command({**payload, 'providerIds': [other]})
        for ids in ('invalid', [1], ['unknown']):
            with self.assertRaises(ValueError):
                command({**payload, 'providerIds': ids})
        self.assertFalse(policy._consent_file().exists())
        granted = command(payload)
        self.assertTrue(granted['accepted'])
        self.assertEqual(len(granted['receivers']), 1)
        self.assertEqual(len(policy._saved_consent()['receivers']), 1)
        self.assertEqual(policy.model_headers(self.session()), {})
        with self.assertRaises(policy.ConsentRequired):
            policy.model_headers(self.session('https://other.example/v1', 'other'))

    def test_refresh_command_uses_existing_background_job(self):
        job = json.loads(android_entry.send('/ios.consent.refresh'))['job']
        deadline = time.monotonic() + 2
        while True:
            result = json.loads(android_entry.send('/jobresult ' + job))
            if not result['pending'] or time.monotonic() >= deadline:
                break
            time.sleep(.01)
        self.assertFalse(result['pending'])
        state = json.loads(result['result'])
        self.assertEqual(state, json.loads(android_entry.send('/ios.consent.status')))

    def test_bad_endpoint_never_discloses_embedded_credentials(self):
        for url in ('http://example.com/v1', 'https://user:secret@example.com/v1', 'https://example.com/v1?key=secret'):
            with self.assertRaises(ValueError) as error:
                policy._endpoint(url)
            self.assertNotIn('secret', str(error.exception))

    def test_tool_schema_keeps_code_run_agent_memory_and_minimal_device_tools(self):
        schema = json.loads((HOST / 'assets/tools_schema.json').read_text())
        changed = policy.tool_schema(schema)
        names = [x['function']['name'] for x in changed]
        for name in ('code_run', 'file_read', 'file_write', 'file_patch', 'ask_user', 'start_long_term_update',
                     'screen', 'hid', 'pc_link'):
            self.assertIn(name, names)
        for name in ('web_scan', 'web_execute_js', 'device_tool', 'pc_catalog', 'pc_call'):
            self.assertNotIn(name, names)

    def test_explicit_save_recovers_dynamic_config_with_exact_private_backup(self):
        source = "import os\nnative_oai_config = dict(apikey=os.getenv('KEY'))\n"
        self.write_config(source)
        with patch.object(android_entry, 'GA_DIR', str(self.root)), patch.object(android_entry, '_refresh_mykeys'):
            with self.assertRaises(ValueError):
                android_entry._write_mykey_patch([('native_oai_config', {'name': 'Background', 'apibase': 'https://example.com/v1', 'apikey': 'test-only'})])
            self.assertEqual((self.root / 'mykey.py').read_text(), source)
            result = json.loads(android_entry._provider_save(json.dumps({
                'name': 'Recovered', 'type': 'oai',
                'apikey': 'test-only', 'apibase': 'https://example.com/v1', 'model': 'model-a',
            })))
        self.assertTrue(result['ok'])
        backup = self.root / result['recoveredBackup']
        self.assertEqual(backup.read_text(), source)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertTrue(result['recoveryNote'])
        values, _ = policy.load_config()
        self.assertEqual(next(v for v in values.values() if isinstance(v, dict))['name'], 'Recovered')

    def test_static_constructor_config_remains_editable_through_existing_ui(self):
        self.write_config("base = dict(apikey='test-only', apibase='https://example.com/v1')\nnative_oai_config = dict(base, name='Custom', model='model-a')\n")
        with patch.object(android_entry, 'GA_DIR', str(self.root)), patch.object(android_entry, '_refresh_mykeys'):
            result = json.loads(android_entry._provider_save(json.dumps({
                'name': 'Custom', 'type': 'oai',
                'apikey': 'test-only', 'apibase': 'https://example.com/v1', 'model': 'model-b',
            })))
        self.assertTrue(result['ok'])
        self.assertFalse(result['recoveredBackup'])
        values, _ = policy.load_config()
        self.assertEqual(values['native_oai_config']['model'], 'model-b')

    def test_memory_update_reads_preserved_data_sop_independently_of_process_cwd(self):
        (self.root / 'memory/memory_management_sop.md').write_text('Preserved user memory rules')
        handler = IOSHandler(types.SimpleNamespace(), cwd=str(self.root / 'temp'))
        handler.current_turn = 10
        with patch.object(ga, 'script_dir', str(self.root)):
            result = exhaust(handler.do_start_long_term_update({}, types.SimpleNamespace(content='')))
        self.assertIn('Preserved user memory rules', result.data)
        self.assertNotIn('not found', result.data)

    def test_android_modules_and_pruned_extras_are_absent_from_signed_runtime(self):
        for rel in ('droid.py', 'evolution.py', 'kernel_adapter/executor.py', 'ganet.py', 'sense.py', 'bus_client.py',
                    'plugins/browser_events_hook.py', 'plugins/float_dock_hook.py', 'plugins/push_nudge_hook.py',
                    'assets/sys_prompt.txt', 'assets/global_mem_insight_template_en.txt', 'memory/phone_use.md'):
            self.assertFalse((HOST / rel).exists(), rel)
        with patch.dict(os.environ, GA_SAFE_MODE='marker'):
            for command in ('/safemode off', '/evo.status', '/evo.clearbackups', '/evo.merge all', '/clearupdcache'):
                for send in (android_entry.send, lambda text: android_entry.send2('probe', text)):
                    with self.subTest(command=command):
                        self.assertEqual(json.loads(send(command))['error'], 'unsupported_on_ios')
            self.assertEqual(os.environ['GA_SAFE_MODE'], 'marker')

    def test_named_failover_selects_chain_and_routes_to_second_provider_on_http_failure(self):
        self.write_config(
            "mixin_config_auto=dict(name='auto',llm_nos=['Primary','Backup'],max_retries=1,base_delay=0)\n"
            "native_oai_config=dict(name='Primary',apikey='fixture',apibase='https://primary.example/v1',model='a',api_mode='responses',stream=False)\n"
            "native_claude_config=dict(name='Backup',apikey='fixture',apibase='https://backup.example/v1',model='b',stream=False)\n"
        )
        self.grant()
        agent = agentmain.GenericAgent()
        focus = types.SimpleNamespace(agent=agent, lock=threading.RLock(), retired=False, state={})
        with patch.object(android_entry, '_focus', return_value=focus), \
             patch.object(android_entry, '_MODEL_SELECTION'), patch.object(android_entry, '_preset_seq'):
            self.assertTrue(json.loads(android_entry.select_model('auto'))['ok'])
        responses = []
        for code, body in ((503, {'error': 'fixture unavailable'}),
                           (200, {'content': [{'type': 'text', 'text': 'fallback response'}]})):
            response = requests.Response()
            response.status_code = code
            response._content = json.dumps(body).encode()
            response._content_consumed = True
            responses.append(response)
        with patch.object(requests, 'post', side_effect=responses) as post:
            result = list(agent.llmclient.backend.raw_ask([{'role': 'user', 'content': [{'type': 'text', 'text': 'fixture'}]}]))
        self.assertEqual(result, ['fallback response'])
        self.assertEqual([call.args[0] for call in post.call_args_list],
                         ['https://primary.example/v1/responses', 'https://backup.example/v1/messages?beta=true'])
        self.assertEqual(agent.llmclient.backend.current_name, 'Backup')

    def test_history_cleanup_removes_capture_artifacts_and_keeps_user_files(self):
        workspace = self.root / 'Library/Application Support/ga'
        removable = [
            workspace / 'temp/iphone_screens/frame.jpg',
            workspace / 'temp/computer_screenshots/frame.jpg',
            self.root / 'Documents/board-vision-run/before/screen.jpg',
            self.root / 'tmp/WKWebFileUpload-123/image.jpg',
        ]
        preserved = [workspace / 'temp/report.png', workspace / 'uploads/personal.jpg', self.root / 'Documents/notes.txt']
        for path in removable + preserved:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture')
        with patch.dict(os.environ, GA_DIR=str(workspace)):
            policy.clear_history_screenshots()
        self.assertTrue(all(not path.exists() for path in removable))
        self.assertTrue(all(path.is_file() for path in preserved))

    def test_model_transport_preserves_headers_but_never_follows_redirects(self):
        session = self.session()
        session.max_retries = 0
        session.stream = False
        session.connect_timeout, session.read_timeout = 5, 20
        self.grant()
        response = types.SimpleNamespace(status_code=200)
        class ResponseContext:
            def __enter__(self): return response
            def __exit__(self, *args): pass
        with patch.object(requests, 'post', return_value=ResponseContext()) as post:
            list(llmcore._stream_with_retry(
                session, 'https://example.com/v1/chat/completions',
                {'Authorization': 'Bearer test-only'}, {}, lambda r: iter(['reply'])
            ))
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        self.assertTrue(post.call_args.kwargs['verify'])
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer test-only')

    def test_ios_proxy_switch_controls_an_existing_model_session(self):
        session = self.session()
        session.max_retries = 0
        session.stream = False
        session.connect_timeout, session.read_timeout = 5, 20
        session.proxies = {'https': 'http://127.0.0.1:7890'}
        self.grant()
        response = requests.Response()
        response.status_code = 200
        response._content_consumed = True
        url = 'https://example.com/v1/chat/completions'
        with patch.object(android_entry, 'GA_DIR', str(self.root)), \
             patch.dict(os.environ, HTTPS_PROXY='http://127.0.0.1:7890'), \
             patch.object(requests, 'post', return_value=response) as post:
            self.assertTrue(android_entry.send('/proxy http://127.0.0.1:1082').startswith('代理已设置'))
            list(llmcore._stream_with_retry(session, url, {}, {}, lambda _: iter(['reply'])))
            self.assertEqual(post.call_args.kwargs['proxies']['https'], 'http://127.0.0.1:1082')
            self.assertEqual(android_entry.send('/proxy clear'), '代理已清除')
            list(llmcore._stream_with_retry(session, url, {}, {}, lambda _: iter(['reply'])))
            self.assertEqual(post.call_args.kwargs['proxies'], {'http': '', 'https': '', 'all': ''})

    def test_custom_provider_http409_remains_real_http_error(self):
        session = self.session()
        session.max_retries = 0
        session.stream = False
        session.connect_timeout, session.read_timeout = 5, 20
        self.grant()
        response = types.SimpleNamespace(status_code=409, text='normal provider conflict')
        class ResponseContext:
            def __enter__(self): return response
            def __exit__(self, *args): pass
        with patch.object(requests, 'post', return_value=ResponseContext()), patch.object(policy, 'invalidate_policy') as invalidate:
            out = ''.join(llmcore._stream_with_retry(session, 'https://example.com/v1/chat/completions', {}, {}, lambda r: iter(())))
        self.assertIn('HTTP 409', out)
        self.assertNotIn('ios_consent_required', out)
        invalidate.assert_not_called()

    def test_pc_late_connection_is_closed_after_consent_revocation(self):
        import pclink
        closed = []
        class Socket:
            async def close(self): closed.append(True)
        async def run():
            with patch.object(pclink, 'IS_IOS', True):
                with self.assertRaises(PermissionError):
                    pclink._attach(Socket(), {'signalUrl': 'wss://relay.example.invalid/ws'})
            await asyncio.sleep(0)
        asyncio.run(run())
        self.assertEqual(closed, [True])


if __name__ == '__main__':
    unittest.main()
