import importlib.util
from pathlib import Path
from types import SimpleNamespace
import threading

spec = importlib.util.spec_from_file_location('pc_model_settings', Path(__file__).parents[1] / 'pc_link/pc_model_settings.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Backend:
    def __init__(self, name, effort):
        self.name, self.model, self.reasoning_effort = name, name + '-model', effort
        self.api_key = 'must-not-leave-computer'
        self.history = [{'role': 'user', 'content': 'existing conversation'}]


class Agent:
    def __init__(self):
        self._model_lock = threading.RLock()
        self._llm_config_keys = ['first_api', 'second_api']
        self.llmclients = [SimpleNamespace(backend=Backend('A', 'high')), SimpleNamespace(backend=Backend('B', None))]
        self.llm_no, self.is_running = 0, False
        self.llmclient = self.llmclients[0]
        self.task_queue = SimpleNamespace(unfinished_tasks=0)

    def load_llm_sessions(self):
        pass

    def next_llm(self, no):
        history = self.llmclient.backend.history
        self.llm_no, self.llmclient = no, self.llmclients[no]
        self.llmclient.backend.history = history


def change(state, **overrides):
    return {'revision': state['revision'], 'profile': state['profiles'][0]['id'], 'reasoning': 'low', **overrides}


def test_preferences_are_session_scoped_without_secrets_or_history_loss():
    a, b = Agent(), Agent()
    handler = module.ModelSettings(a)
    original = a.llmclient.backend.history
    state = handler()
    assert 'must-not-leave-computer' not in str(state)
    assert 'existing conversation' not in str(state)
    assert handler(change(state))['ok'] == 1
    assert a.llmclient.backend.reasoning_effort == 'low'
    assert b.llmclient.backend.reasoning_effort == 'high'
    state = handler()
    assert handler(change(state, reasoning='default'))['ok'] == 1
    assert a.llmclient.backend.reasoning_effort == 'high'
    state = handler()
    assert handler(change(state, profile=state['profiles'][1]['id'], reasoning='default'))['ok'] == 1
    assert a.llm_no == 1 and a.llmclient.backend.history is original


def test_stale_unknown_and_queued_changes_are_rejected_without_mutation():
    a = Agent(); handler = module.ModelSettings(a); state = handler()
    assert handler(change(state, revision='stale'))['code'] == 'conflict'
    assert handler(change(state, profile='unknown'))['code'] == 'badop'
    assert handler(change(state, profile=state['profiles'][1]['id']))['code'] == 'badop'
    for busy in ('is_running', 'queue'):
        a.is_running = busy == 'is_running'
        a.task_queue.unfinished_tasks = int(busy == 'queue')
        assert handler(change(state))['code'] == 'busy'
    assert a.llmclient.backend.reasoning_effort == 'high'


def test_mixed_transport_defaults_restore_each_node_independently():
    a = Agent()
    backend = a.llmclient.backend
    backend._sessions = [Backend('X', 'high'), Backend('Y', 'medium')]
    handler = module.ModelSettings(a); state = handler()
    assert state['profiles'][0]['reasoning']['value'] == 'mixed'
    assert handler(change(state))['ok'] == 1
    assert [n.reasoning_effort for n in backend._sessions] == ['low', 'low']
    assert handler(change(handler(), reasoning='default'))['ok'] == 1
    assert [n.reasoning_effort for n in backend._sessions] == ['high', 'medium']
