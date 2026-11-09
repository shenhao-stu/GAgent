"""Android model selection calls the real upstream API, never a chat command."""
import ast
import json
from pathlib import Path
import queue
import threading
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'app/src/main/assets/ga_runtime'


def load_function(path, name, env):
    tree = ast.parse(path.read_text('utf-8'))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), env)
    return env[name]


class ProviderSelection(unittest.TestCase):
    def setUp(self):
        self.schema_calls = []
        self.env = {'load_tool_schema': lambda: self.schema_calls.append(True)}
        self.next_llm = load_function(RUNTIME / 'gacore/agentmain.py', 'next_llm', self.env)
        self.select = load_function(RUNTIME / 'android_entry.py', '_select_agent_model', {})

    def agent(self, names):
        clients = [SimpleNamespace(backend=SimpleNamespace(name=n, model='original', history=[])) for n in names]
        a = SimpleNamespace(_model_lock=threading.RLock(), is_running=False,
                            task_queue=queue.Queue(), llmclients=clients,
                            llmclient=clients[0], llm_no=0, history=[{'keep': True}])
        a.llmclient.backend.history = [{'message': 'preserve me'}]
        a.load_llm_sessions = lambda: None
        a.next_llm = lambda no: self.next_llm(a, no)
        return SimpleNamespace(agent=a, lock=threading.RLock(), retired=False, state={'running': False})

    def test_exact_selection_calls_upstream_preserves_history_and_never_enqueues(self):
        s = self.agent(['alpha', 'beta'])
        history = s.agent.llmclient.backend.history
        result = self.select(s, 'beta', 'chosen-model')
        self.assertTrue(result['ok'])
        self.assertEqual(s.agent.llm_no, 1)
        self.assertEqual(s.agent.llmclient.backend.model, 'chosen-model')
        self.assertIs(s.agent.llmclient.backend.history, history)
        self.assertEqual(s.agent.history, [{'keep': True}])
        self.assertTrue(s.agent.task_queue.empty())
        self.assertEqual(len(self.schema_calls), 1)

    def test_names_are_exact_not_substrings_or_indexes(self):
        for name in ('', 'missing', 'a', '1'):
            s = self.agent(['alpha', 'beta'])
            with self.assertRaises(ValueError): self.select(s, name, 'wrong')
            self.assertEqual(s.agent.llm_no, 0)
            self.assertEqual(s.agent.llmclient.backend.model, 'original')
            self.assertTrue(s.agent.task_queue.empty())

    def test_duplicate_names_rejected(self):
        with self.assertRaises(ValueError): self.select(self.agent(['alpha', 'alpha']), 'alpha')

    def test_busy_and_queued_tasks_rejected(self):
        for mode in ('host', 'core', 'queue', 'retired'):
            s = self.agent(['alpha', 'beta'])
            if mode == 'host': s.state['running'] = True
            if mode == 'core': s.agent.is_running = True
            if mode == 'queue': s.agent.task_queue.put({'query': 'real task'})
            if mode == 'retired': s.retired = True
            with self.assertRaises(RuntimeError): self.select(s, 'beta')
            self.assertEqual(s.agent.llm_no, 0)
            self.assertEqual(s.agent.llmclient.backend.model, 'original')

    def test_auto_selection_does_not_override_model(self):
        s = self.agent(['alpha', 'auto'])
        self.select(s, 'auto')
        self.assertEqual(s.agent.llm_no, 1)
        self.assertEqual(s.agent.llmclient.backend.model, 'original')

    def test_no_legacy_llm_command_in_android_control_path(self):
        for name in ('android_entry.py', 'webui/app.js'):
            self.assertNotIn('/llm', (RUNTIME / name).read_text('utf-8'))
        js = (RUNTIME / 'webui/app.js').read_text('utf-8')
        self.assertIn('GA.selectModel(name,model', js)



if __name__ == '__main__':
    unittest.main()
