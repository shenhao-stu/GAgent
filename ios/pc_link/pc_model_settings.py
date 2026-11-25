"""Session-scoped PC Link model preferences. Never exposes or edits stored credentials."""
import hashlib
import json


def _error(code, message):
    return {'error': message, 'code': code}


def _nodes(backend):
    return getattr(backend, '_sessions', None) or [backend]


def _efforts(backend):
    # Only offer tuning for already configured reasoning transports. Unknown models stay intact.
    choices = {'low', 'medium', 'high', 'xhigh', 'max'}
    for node in _nodes(backend):
        if not getattr(node, 'reasoning_effort', None):
            return []
        if 'Claude' in type(node).__name__:
            choices &= {'low', 'medium', 'high', 'max'}
    return [x for x in ('low', 'medium', 'high', 'xhigh', 'max') if x in choices]


class ModelSettings:
    def __init__(self, agent):
        self.agent = agent
        self.defaults = {}

    def _snapshot(self):
        agent = self.agent
        agent.load_llm_sessions()
        profiles = []
        for index, (key, client) in enumerate(zip(agent._llm_config_keys, agent.llmclients)):
            backend = getattr(client, 'backend', None)
            if backend is None:
                continue
            nodes = _nodes(backend)
            self.defaults.setdefault(backend, [getattr(n, 'reasoning_effort', None) for n in nodes])
            values = {getattr(n, 'reasoning_effort', None) for n in nodes}
            current = next(iter(values)) if len(values) == 1 else 'mixed'
            profile = {
                'id': hashlib.sha256(key.encode()).hexdigest()[:16],
                'index': index,
                'name': str(getattr(backend, 'name', '')),
                'models': list(dict.fromkeys(str(getattr(n, 'model', '')) for n in nodes)),
                'reasoning': {'value': current or 'default', 'choices': _efforts(backend)},
            }
            profiles.append(profile)
        self.defaults = {b: v for b, v in self.defaults.items()
                         if any(getattr(c, 'backend', None) is b for c in agent.llmclients)}
        selected = next((p['id'] for p in profiles if p['index'] == agent.llm_no), None)
        state = {'profiles': profiles, 'selected': selected}
        state['revision'] = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()[:24]
        state['busy'] = bool(agent.is_running or getattr(getattr(agent, 'task_queue', None), 'unfinished_tasks', 0))
        return state

    def __call__(self, change=None):
        with self.agent._model_lock:
            state = self._snapshot()
            if change is None:
                return state
            if state['busy']:
                return _error('busy', '任务运行中，请结束后再调整模型')
            if not isinstance(change, dict) or set(change) != {'revision', 'profile', 'reasoning'}:
                return _error('badop', 'Invalid model preference request')
            if change['revision'] != state['revision']:
                return _error('conflict', '电脑配置已更新，请重新选择')
            profile = next((p for p in state['profiles'] if p['id'] == change['profile']), None)
            if profile is None:
                return _error('badop', '电脑上的这个模型已不可用')
            effort = change['reasoning']
            if effort != 'default' and effort not in profile['reasoning']['choices']:
                return _error('badop', '此模型不支持所选思考强度')
            self.agent.next_llm(profile['index'])
            if self.agent.llm_no != profile['index']:
                return _error('busy', '模型未切换，请稍后重试')
            backend = self.agent.llmclient.backend
            for node, default in zip(_nodes(backend), self.defaults[backend]):
                if effort != 'default' or hasattr(node, 'reasoning_effort'):
                    node.reasoning_effort = default if effort == 'default' else effort
            return {'ok': 1, **self._snapshot()}
