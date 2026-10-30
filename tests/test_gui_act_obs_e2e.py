"""端到端验证: gui_act 结果自带观测后, 同一个任务需要多少轮。

真机实证的轮数构成: 39 轮任务里约 20 轮是纯观察(code_run + dump/look), 只为了
知道屏幕上现在有什么好点。本文件用**真实**的 agent_runner_loop + 真实
GenericAgentHandler.do_gui_act(只打桩设备侧 droid), 让脚本化模型模仿真机的
"观察→动作"模式, 直接量轮数——不靠真机、不靠真实模型, 但走的是真实代码路径。

判定口径(通用, 不针对某个 case): 脚本化模型每次只根据"手上有没有观测"决定下一步——
有观测就动作, 没观测才花一轮去观察。因此轮数差异完全来自 gui_act 是否给观测,
与具体任务内容无关。
"""
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import agent_loop
import ga_android
import phone_ledger

# 一个需要 4 次动作的合成任务: 点搜索 → 点结果 → 下滑 → 点条目
TASK_ACTIONS = [
    {'action': 'tap', 'point': [540, 500]},
    {'action': 'tap', 'point': [540, 900]},
    {'action': 'swipe', 'point1': [500, 1800], 'point2': [500, 600], 'ms': 400},
    {'action': 'tap', 'point': [540, 1200]},
]

# 每轮动作后设备上的内容(合成): 足够模型选下一个目标
SCREEN_NODES = [
    {'t': '搜索框', 'cls': 'EditText', 'x': 540, 'y': 500},
    {'t': '结果一', 'cls': 'Text', 'x': 540, 'y': 900},
    {'t': '结果二', 'cls': 'Text', 'x': 540, 'y': 1200},
    {'t': '设置', 'cls': 'Text', 'x': 900, 'y': 200},
]


def _make_droid_stub(dump_calls, look_calls, tap_calls):
    """设备侧替身: dump/look 给同一份节点, 动作只记账不改屏幕。

    observe() 也由这里提供: _compact_obs 现在只调 observe(), 通道选择在它里面做。
    契约与真实实现一致: t=显示文本, desc=contentDescription, src='tree'|'yolo'。"""
    def dump(full=False):
        dump_calls.append(1)
        return [dict(n) for n in SCREEN_NODES]

    def look(*a, **k):
        look_calls.append(1)
        return [dict(n) for n in SCREEN_NODES]

    def observe(*a, **k):
        import geom
        items = []
        for n in SCREEN_NODES:
            rx, ry = geom.to_norm(n['x'], n['y'], 1200, 2670)
            items.append({'src': 'tree', 't': n.get('t') or '', 'desc': n.get('d') or '',
                          'cls': n.get('cls') or '', 'x': n['x'], 'y': n['y'],
                          'rx': rx, 'ry': ry, 'click': bool(n.get('click')), 'type': ''})
        return {'kind': 'tree', 'items': items, 'channels': ['tree', 'yolo'], 'notes': [],
                'needs_vision': False, 'ms': 1.0}

    def tap(x, y, **k):
        tap_calls.append((x, y))
        return {'diff': 'diff: 12.0% bbox=[0,0,9,9]'}

    def swipe(*a, **k):
        tap_calls.append(('swipe',) + a)
        return {'diff': 'diff: 30.0% bbox=[0,0,9,9]'}

    return types.SimpleNamespace(
        screen=lambda: (1200, 2670),
        dump=dump, look=look, tap=tap, swipe=swipe,
        observe=observe,
        wait_stable=lambda **k: {'stable': True, 'waited_s': 0.0, 'uncertain': False},
        ensure_fresh_obs=lambda: {'nodes': [dict(n) for n in SCREEN_NODES]},
        reset_trace=lambda: None,
    )


class _ScriptedModel:
    """按"手上有没有观测"决策的脚本化模型。

    observe_first=True  → 模仿修复前的模型: 每个动作前都要花一轮 code_run 观察
    observe_first=False → 模仿会用 obs 的模型: 直接拿 gui_act 结果里的 obs 用
    """

    last_tools = ''

    def __init__(self, script, backend):
        self.script = list(script)
        self.backend = backend
        self.calls = 0

    def chat(self, messages, tools=None):
        # 必须是生成器并用 return 交出响应: agent_loop 的 exhaust() 取的是
        # StopIteration.value, 与真实 client.chat 的形态一致
        self.calls += 1
        name, args = self.script.pop(0)
        resp = types.SimpleNamespace(
            thinking='', content='ok', raw='',
            tool_calls=[self._tc(name, args)] if name else [],
            stop_reason='tool_use' if name else 'end_turn')
        yield 'chunk'
        return resp

    @staticmethod
    def _tc(name, args):
        fn = types.SimpleNamespace(name=name, arguments=json.dumps(args))
        return types.SimpleNamespace(function=fn, id='tc1')


class _Backend:
    def __init__(self):
        self.history = [{'role': 'user', 'content': [{'type': 'text', 'text': 'task'}]}]


class GuiActObsEndToEndTest(unittest.TestCase):
    """通用口径: 轮数差异只许来自"gui_act 是否给观测", 与任务内容无关。"""

    def _drive(self, observe_first):
        """跑完整个合成任务, 返回 (轮数, 动作次数, dump次数)。"""
        phone_ledger.ACTIVE.clear()
        handler = ga_android.GenericAgentHandler(types.SimpleNamespace(
            task_dir=None, verbose=False, _turn_end_hooks={}))
        handler.working = {}
        handler.history_info = []
        handler.code_stop_signal = []
        handler.current_turn = 0

        dump_calls, look_calls, tap_calls = [], [], []

        # 按需生成脚本: 每次决策都看"手上有没有观测"
        script = []
        observed = False                     # 开局没看过屏幕
        for act in TASK_ACTIONS:
            if observe_first or not observed:
                script.append(('code_run', {'script': 'import droid; print(droid.dump())'}))
                observed = True               # 这一轮之后手上就有观测了
            script.append(('gui_act', dict(act)))
            if not observe_first:
                observed = True               # gui_act 结果自带 obs → 继续有观测
        script.append(('finish_task', {'status': 'done', 'result': 'synthetic task done',
                                       'evidence': ['synthetic actions completed']}))  # 显式收尾

        backend = _Backend()
        client = _ScriptedModel(script, backend)
        with patch.dict(sys.modules, {'droid': _make_droid_stub(dump_calls, look_calls, tap_calls)}):
            chunks = list(agent_loop.agent_runner_loop(
                client, 'sys prompt', 'do the task', handler, [], max_turns=40, verbose=False))
        return client.calls, len(tap_calls), len(dump_calls)

    def test_obs_removes_the_observation_round_trips(self):
        """同一任务: 会用 obs 的模型比"每动作前先观察"的模型少花整轮。"""
        old_turns, old_acts, old_dumps = self._drive(observe_first=True)
        new_turns, new_acts, new_dumps = self._drive(observe_first=False)

        self.assertEqual(old_acts, new_acts)        # 动作数一样, 只轮数不同
        self.assertEqual(old_acts, len(TASK_ACTIONS))
        self.assertLess(new_turns, old_turns)       # 轮数真的降了
        # 4 个动作: 旧模式 4 观察 + 4 动作 + 1 收尾 = 9; 新模式 1 观察 + 4 动作 + 1 收尾 = 6
        self.assertEqual(old_turns, 9)
        self.assertEqual(new_turns, 6)

    def test_gui_act_result_actually_carries_usable_obs(self):
        """机制成立的前提: gui_act 结果里的 obs 足够选下一个目标。"""
        phone_ledger.ACTIVE.clear()
        handler = ga_android.GenericAgentHandler(types.SimpleNamespace(
            task_dir=None, verbose=False, _turn_end_hooks={}))
        handler.working = {}; handler.history_info = []
        handler.code_stop_signal = []; handler.current_turn = 0
        dumps, looks, taps = [], [], []
        with patch.dict(sys.modules, {'droid': _make_droid_stub(dumps, looks, taps)}):
            out = handler.do_gui_act({'action': 'tap', 'point': [540, 500]},
                                     types.SimpleNamespace(content=''))
            data = json.loads(out.data)
        obs = data['obs']
        self.assertTrue(obs)
        # 模型要能凭 obs 选目标: 标签 + 两种单位的坐标都必须在
        # (x/y=像素可直接当 point; rx/ry=0-1000 可直接当 rel)
        for item in obs:
            self.assertIn('t', item)
            self.assertIn('x', item)
            self.assertIn('y', item)
            self.assertIn('rx', item)
            self.assertIn('ry', item)
            self.assertTrue(0 <= item['x'] <= 1200 and 0 <= item['y'] <= 2670)
            self.assertTrue(0 <= item['rx'] <= 1000 and 0 <= item['ry'] <= 1000)
        labels = [i['t'] for i in obs]
        self.assertIn('结果一', labels)             # 下一个目标确实在里面

    def test_task_completes_without_a_real_model(self):
        """兜底: 整条链路(真实 agent_runner_loop + 真实 do_gui_act)能自己跑完。"""
        turns, acts, dumps = self._drive(observe_first=False)
        self.assertGreater(turns, 0)
        self.assertEqual(acts, len(TASK_ACTIONS))


if __name__ == '__main__':
    unittest.main()
