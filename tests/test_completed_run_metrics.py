"""复现真机缺陷: 完成态任务的最后一个轮次与汇总行一起丢失。

真机实证(2026-10-27 14:01): UI 显示「完成 · 5 步」且答案已给出, 但 metrics 只有
4 个 turn 行、没有 run_summary。app 进程未重启, run_id 只出现在一个文件里,
.agent_events 在最后一个 turn 之后无事件(与"末轮是最终答复、无设备动作"吻合)。

怀疑链: agent_after 在 run_metrics_hook.py:221 先 _set_rec(None) 再 end_run,
而 end_run 被 _safe() 包着——任何异常都静默。若末轮之前 TLS 被清掉, 末轮 turn_after
会因 rec is None 直接跳过, 汇总也随之消失。现有测试只覆盖 2 轮且末轮即 no_tool,
覆盖不到这个形态。
"""
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

from agent_loop import StepOutcome
import agent_loop
import plugins.run_metrics_hook as hook
import run_metrics


class _Backend:
    def __init__(self):
        self.history = [{'role': 'user', 'content': [{'type': 'text', 'text': 'task'}]}]


def _tc(name, args):
    fn = types.SimpleNamespace(name=name, arguments=json.dumps(args))
    return types.SimpleNamespace(function=fn, id='tc1')


class _Resp:
    def __init__(self, tool_calls):
        self.thinking = ''; self.content = 'ok'; self.raw = ''
        self.tool_calls = tool_calls
        self.stop_reason = 'tool_use' if tool_calls else 'end_turn'


class _Client:
    """按脚本逐轮返回; 脚本为空时返回无工具调用(最终答复)。"""
    last_tools = ''

    def __init__(self, script):
        self.script = list(script)
        self.backend = _Backend()
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        item = self.script.pop(0) if self.script else (None, {})
        name, args = item
        resp = _Resp([_tc(name, args)] if name else [])
        yield 'chunk'
        return resp


class _Handler(agent_loop.BaseHandler):
    def __init__(self, parent):
        self.max_turns = 40
        self.current_turn = 0
        self._done_hooks = []
        self.parent = parent
        self.working = {}

    def do_code_run(self, args, response):
        return StepOutcome({'stdout': 'ok'}, next_prompt='next')

    def do_gui_act(self, args, response):
        return StepOutcome({'diff': 'diff: 8.0% bbox=[0,0,9,9]'}, next_prompt='next')

    def do_no_tool(self, args, response):
        # 最终答复: next_prompt 为空 → 引擎置 CURRENT_TASK_DONE 并 break
        return StepOutcome({'answer': 'Android 16'}, next_prompt=None)


def _drive(tmp_path, script, logid='1700000000000000000'):
    parent = types.SimpleNamespace(log_path=str(tmp_path / f'model_responses_{logid}.txt'),
                                   task_dir=None)
    handler = _Handler(parent)
    list(agent_loop.agent_runner_loop(_Client(list(script)), 'sys', 'do it',
                                      handler, [], max_turns=40, verbose=False))
    return handler


class CompletedRunMetricsTest(unittest.TestCase):
    """完成态任务必须落下全部轮次 + 一条汇总——这是判断成败的唯一依据。"""

    def setUp(self):
        self._saved = hook._current_rec()
        hook._set_rec(None)
        self.addCleanup(self._restore)

    def _restore(self):
        hook._set_rec(self._saved)

    def _run_dir(self, tmp_path):
        import os
        os.environ['GA_DIR'] = str(tmp_path)
        return tmp_path / 'temp' / 'model_responses' / 'sessions'

    def test_four_tool_turns_then_final_answer_keeps_everything(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._run_dir(Path(d))
            script = [('code_run', {}), ('code_run', {}), ('gui_act', {}),
                      ('code_run', {}), (None, {})]          # 末轮=最终答复
            _drive(Path(d), script)
            files = list(run_dir.glob('metrics_*.jsonl'))
            self.assertEqual(len(files), 1)
            lines = [json.loads(x) for x in files[0].read_text(encoding='utf-8').splitlines()]
            turns = [x for x in lines if x['type'] == 'turn']
            summ = [x for x in lines if x['type'] == 'run_summary']
            self.assertEqual(len(turns), 5, '5 轮必须全部落盘(真机丢了第 5 轮)')
            self.assertEqual(len(summ), 1, '汇总必须落盘(真机整条丢失)')
            self.assertEqual(summ[0]['end_reason'], 'CURRENT_TASK_DONE')
            self.assertEqual(summ[0]['turns'], 5)

    def test_summary_survives_a_final_turn_with_no_tool(self):
        """末轮无工具调用时, end_run 不能把末轮和汇总一起吞掉。"""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._run_dir(Path(d))
            _drive(Path(d), [('gui_act', {}), (None, {})])
            lines = [json.loads(x) for x in list(run_dir.glob('metrics_*.jsonl'))[0]
                     .read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len([x for x in lines if x['type'] == 'turn']), 2)
            self.assertEqual(len([x for x in lines if x['type'] == 'run_summary']), 1)

    def test_next_task_flushes_an_orphaned_recorder_from_memory(self):
        """内存兜底的价值: 留下**真汇总**(带 turns/耗时), 而不是 stub。

        两种兜底覆盖的场景重叠(文件补写也能把孤儿标成 unfinished), 差别在信息量:
        recorder 还在内存里时当场 end_run, 汇总带真实轮数与耗时; 只按文件补写则
        只能写一条只有 run_id/end_reason 的 stub——事后就看不出这次跑了多久、多少轮。
        真机 14:01 那次正是只剩 4 个 turn 行、汇总整条缺失。"""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._run_dir(Path(d))
            hook._on_agent_before({'handler': _Handler(types.SimpleNamespace(
                log_path=str(Path(d) / 'model_responses_1.txt'), task_dir=None))})
            for t in (1, 2, 3):
                hook._on_turn_before({'turn': t})
                hook._on_llm_before({})
                hook._on_llm_after({'client': _Client([])})
                hook._on_tool_before({'tool_name': 'gui_act'})
                hook._on_tool_after({'tool_name': 'gui_act',
                                     'ret': types.SimpleNamespace(data={'diff': 'diff: 8.0%'})})
                hook._on_turn_after({})
            # 故意不调 agent_after —— 模拟它没跑成
            f1 = list(run_dir.glob('metrics_*.jsonl'))[0]
            self.assertNotIn('run_summary', f1.read_text(encoding='utf-8'))

            _drive(Path(d), [('gui_act', {}), (None, {})], logid='2')
            lines = [json.loads(x) for x in f1.read_text(encoding='utf-8').splitlines()]
            summ = [x for x in lines if x['type'] == 'run_summary']
            self.assertEqual(len(summ), 1)
            self.assertEqual(summ[0]['end_reason'], 'unfinished')
            # 关键: 必须是真汇总(带轮数与耗时), 不是 stub
            self.assertEqual(summ[0]['turns'], 3, '孤儿 recorder 应留下真实轮数')
            self.assertIn('model_wait_s', summ[0])
            self.assertIn('tools_total', summ[0])
            self.assertNotIn('recovered', summ[0], '真汇总不该带 stub 的 recovered 标记')


if __name__ == '__main__':
    unittest.main()
