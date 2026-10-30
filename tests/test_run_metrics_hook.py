"""run_metrics 插件: 挂 agent_loop 既有 hook 点, 一次任务产出 SPEC Part 7.1 全指标集。

用假 client/handler 真跑 agent_runner_loop: 不连设备、不联网、不需要模型 key。
"""
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import agent_loop
import llmcore
import run_metrics
import plugins.run_metrics_hook as hook
from agent_loop import StepOutcome


class _Backend:
    def __init__(self):
        self.history = [{'role': 'user', 'content': [{'type': 'text', 'text': 'x' * 100}]}]


class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = json.dumps(arguments)


class _TC:
    def __init__(self, name, args, id='tc1'):
        self.function = _Fn(name, args)
        self.id = id


class _Resp:
    def __init__(self, tool_calls):
        self.thinking = ''
        self.content = 'ok'
        self.raw = ''
        self.tool_calls = tool_calls
        self.stop_reason = 'tool_use' if tool_calls else 'end_turn'


class _Client:
    """两轮: 第一轮调 tap, 第二轮不调工具(引擎自动触发 no_tool → 结束)。"""
    last_tools = ''

    def __init__(self, script):
        self.script = list(script)
        self.backend = _Backend()

    def chat(self, messages, tools=None):
        name = self.script.pop(0)
        llmcore._record_usage({'prompt_tokens': 1975, 'completion_tokens': 42,
                               'prompt_tokens_details': {'cached_tokens': 8}}, 'chat_completions')
        yield 'chunk'
        return _Resp([_TC(name, {})] if name else [])


class _Handler(agent_loop.BaseHandler):
    def __init__(self, parent):
        self.max_turns = 5
        self.current_turn = 0
        self._done_hooks = []
        self.parent = parent
        self.working = {}

    def do_tap(self, args, response):
        """合成替身: 代表"结果自带判定字段的工具"——即未来的结构化动作空间。
        今天所有手机动作都埋在 code_run 的 stdout 里, 工具级判定确实取不到(见模块已知限制),
        所以这条路径用替身覆盖, 不冒充真实现状。"""
        run_metrics.mark_action_dispatched()     # 模拟"动作已下发"(真实路径由 droid._act 打点)
        time.sleep(0.02)                         # 替身代 droid.tap 的稳态等待(真机 wait=1.0s)
        return StepOutcome({'verified': True, 'diff': 'diff: 1.500% bbox=[0,0,9,9]'},
                           next_prompt='next')

    def do_no_tool(self, args, response):
        return StepOutcome({'done': True}, next_prompt=None)


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('GA_DIR', str(tmp_path))
    saved = hook._current_rec()
    hook._set_rec(None)
    yield tmp_path / 'temp' / 'model_responses' / 'sessions'
    hook._set_rec(saved)


@pytest.fixture(scope='module', autouse=True)
def _unregister_plugin_hooks_after_module():
    """插件在 import 时注册进程级 hook; 本模块跑完后摘掉, 否则会污染后续驱动
    agent_runner_loop 的测试文件(那些测试没有 GA_DIR, 会往源码树里写指标)。"""
    yield
    import plugins.hooks as ph
    mine = {hook._on_agent_before, hook._on_turn_before, hook._on_llm_before, hook._on_llm_after,
            hook._on_tool_before, hook._on_tool_after, hook._on_turn_after, hook._on_agent_after}
    for name, fns in list(ph._HANDLERS.items()):
        ph._HANDLERS[name] = [f for f in fns if f not in mine]


def _drive(tmp_path, script=('tap', None), logid='1700000000000000000', handler_cls=None):
    parent = SimpleNamespace(log_path=str(tmp_path / f'model_responses_{logid}.txt'), task_dir=None)
    handler = (handler_cls or _Handler)(parent)
    # agent_runner_loop 是生成器: 必须消费掉循环体才真正执行(与 agentmain.run 的 for chunk in gen 一致)
    list(agent_loop.agent_runner_loop(_Client(list(script)), 'sys', 'read three headlines',
                                      handler, [], max_turns=5, verbose=False))
    return handler


def _lines(path):
    return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()]


def test_one_task_writes_the_phase_zero_metric_set(run_dir, tmp_path):
    _drive(tmp_path)
    files = list(run_dir.glob('metrics_*.jsonl'))
    assert len(files) == 1
    lines = _lines(files[0])
    turns = [x for x in lines if x['type'] == 'turn']
    summary = [x for x in lines if x['type'] == 'run_summary']
    assert len(turns) == 2 and len(summary) == 1
    t1 = turns[0]
    assert t1['layer'] == 'L4' and t1['turn'] == 1
    assert t1['model_wait_s'] >= 0 and t1['tool_exec_s'] >= 0
    assert t1['verify_wait_s'] > 0          # 本工具调用派发过动作 → 必须真的有后验耗时
    assert (t1['in_tok'], t1['out_tok']) == (1975, 42)
    assert t1['resend_chars'] > 0
    assert t1['tools'] == ['tap']
    assert t1['tool_records'][0]['verdict'] == {'verified': True, 'diff_pct': 1.5}
    assert t1['tool_records'][0]['verifier'] == '_img_diff_str'
    assert t1['escalations'] == []
    s = summary[0]
    assert s['turns'] == 2 and s['model_calls'] == 2
    assert s['end_reason'] == 'CURRENT_TASK_DONE'
    assert s['p50_turn_s'] is not None and s['p95_turn_s'] is not None
    assert s['in_tok'] == 3950 and s['out_tok'] == 84
    assert s['tools_verified'] == 1
    assert s['tools_uncertain'] == 0 and s['tools_no_verdict'] == 0


def test_verify_wait_survives_the_code_run_child_thread(run_dir, tmp_path):
    """真实路径: droid._act 在 code_run 的子线程里打点(ga_android.do_code_run 起 Thread),
    结算在 agent 循环线程。线程本地累加器会把这里整段丢成 0.0——真机上实测过。"""
    class _ChildThreadHandler(_Handler):
        def do_tap(self, args, response):
            t = threading.Thread(target=run_metrics.mark_action_dispatched, daemon=True)
            t.start(); t.join()
            time.sleep(0.02)
            return StepOutcome({'verified': True, 'diff': 'diff: 1.500% bbox=[0,0,9,9]'},
                               next_prompt='next')

    _drive(tmp_path, handler_cls=_ChildThreadHandler)
    t1 = [x for x in _lines(next(run_dir.glob('metrics_*.jsonl'))) if x['type'] == 'turn'][0]
    assert t1['verify_wait_s'] >= 0.02          # 子线程打的那段稳态等待必须被算进来


def test_concurrent_sessions_do_not_share_a_recorder(run_dir, tmp_path):
    """android_entry 每个会话一条 agent 线程; recorder 必须按线程隔离,
    否则两个会话的 turn/用量会互相污染, 还会给仍在运行的会话补一条假汇总。"""
    def run(logid):
        _drive(tmp_path, script=['tap', 'tap', None], logid=logid)

    a = threading.Thread(target=run, args=('111',), daemon=True)
    b = threading.Thread(target=run, args=('222',), daemon=True)
    a.start(); time.sleep(0.01); b.start(); a.join(); b.join()
    for logid in ('111', '222'):
        lines = _lines(run_dir / f'metrics_{logid}.jsonl')
        turns = [x for x in lines if x['type'] == 'turn']
        summaries = [x for x in lines if x['type'] == 'run_summary']
        assert [t['turn'] for t in turns] == [1, 2, 3], logid   # 只有自己的三轮
        assert len(summaries) == 1 and summaries[0]['turns'] == 3, logid
        assert summaries[0]['end_reason'] == 'CURRENT_TASK_DONE', logid


def test_metrics_file_sits_beside_the_session_snapshots(run_dir, tmp_path):
    _drive(tmp_path)
    assert (run_dir / 'metrics_1700000000000000000.jsonl').exists()


def test_the_engine_no_tool_call_is_not_counted_as_a_tool(run_dir, tmp_path):
    _drive(tmp_path)
    lines = _lines(next(run_dir.glob('metrics_*.jsonl')))
    turns = [x for x in lines if x['type'] == 'turn']
    assert [t['n_tools'] for t in turns] == [1, 0]
    assert turns[1]['tools'] == []


def test_pruning_keeps_only_the_newest_run_files(run_dir, tmp_path):
    for i in range(run_metrics.DEFAULT_KEEP + 3):
        _drive(tmp_path, logid=str(1700000000000000000 + i))
    # 裁剪发生在任务开局, 裁的是"除本次之外"的历史记录 → 稳态是 DEFAULT_KEEP 个历史 + 本次 1 个
    assert len(list(run_dir.glob('metrics_*.jsonl'))) == run_metrics.DEFAULT_KEEP + 1


def test_unfinished_run_is_closed_by_the_next_task(run_dir, tmp_path):
    """中止/异常时 agent_after 不触发; 下一个任务开局必须把上次标成 unfinished, 不丢也不假完成。"""
    hook._on_agent_before({'handler': _Handler(SimpleNamespace(
        log_path=str(tmp_path / 'model_responses_1.txt'), task_dir=None))})
    hook._on_turn_before({'turn': 1})
    hook._on_llm_before({})
    hook._on_llm_after({'client': _Client([])})
    hook._on_turn_after({})          # 这一轮落盘了 —— 真机中止的 run 都有已落盘的 turn 行
    # 没有 agent_after —— 模拟循环生成器被弃
    _drive(tmp_path, logid='2')
    assert _lines(run_dir / 'metrics_1.jsonl')[-1]['end_reason'] == 'unfinished'


def test_unfinished_backfill_survives_a_new_thread(run_dir, tmp_path):
    """回归: 补写必须跨线程生效。

    生产里每个任务是独立线程, 上个任务的循环线程一死, 它存在线程局部里的 recorder
    谁也读不到。原实现读 _current_rec() 补写, 因此真机连续 5 次中止全都没留下汇总行。
    上面那条同线程用例发现不了这个 bug —— 所以这里必须换线程复现。"""
    hook._on_agent_before({'handler': _Handler(SimpleNamespace(
        log_path=str(tmp_path / 'model_responses_1.txt'), task_dir=None))})
    hook._on_turn_before({'turn': 1})
    hook._on_llm_before({})
    hook._on_llm_after({'client': _Client([])})
    hook._on_turn_after({})
    # 循环生成器被弃, 且不碰 agent_after —— 与上面一样, 但整个"下一个任务"换到新线程
    box = {}

    def _next_task():
        hook._on_agent_before({'handler': _Handler(SimpleNamespace(
            log_path=str(tmp_path / 'model_responses_2.txt'), task_dir=None))})
        box['ok'] = True

    t = threading.Thread(target=_next_task)
    t.start(); t.join()
    assert box.get('ok')
    lines = _lines(run_dir / 'metrics_1.jsonl')
    last = lines[-1]
    assert last['end_reason'] == 'unfinished'
    assert last['recovered'] is True             # 标明是补写, 别被当成真实汇总
    # B: 汇总从已落盘的 turn 行重建, 不再只有 run_id/end_reason 的 stub
    assert last['summary_source'] == 'turn_rows'
    assert last['ended_at_estimated'] is True
    assert last['turns'] == 1
    assert isinstance(last['model_wait_s'], (int, float))
    assert last['started_at'] > 0
    assert last['ended_at'] >= last['started_at']


def test_backfill_does_not_touch_a_run_that_already_has_a_summary(run_dir, tmp_path):
    """正常收尾的运行不能再被补一条 unfinished(否则一次运行两条汇总, 口径就乱了)。"""
    _drive(tmp_path, logid='1')                  # 正常跑完 → 已有汇总
    before = len(_lines(run_dir / 'metrics_1.jsonl'))
    hook._on_agent_before({'handler': _Handler(SimpleNamespace(
        log_path=str(tmp_path / 'model_responses_2.txt'), task_dir=None))})
    assert len(_lines(run_dir / 'metrics_1.jsonl')) == before


def test_backfill_ignores_a_missing_file(run_dir, tmp_path):
    """上次运行的指标文件不在(被 prune 掉/从未落盘)时安静跳过, 不抛异常。"""
    hook._last_run['id'] = 'does-not-exist'
    hook._on_agent_before({'handler': _Handler(SimpleNamespace(
        log_path=str(tmp_path / 'model_responses_9.txt'), task_dir=None))})
    assert not list(run_dir.glob('metrics_does-not-exist.jsonl'))


def test_a_failing_write_never_breaks_the_task(run_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(run_metrics, 'append_jsonl',
                        lambda *a, **k: (_ for _ in ()).throw(OSError('disk full')))
    handler = _drive(tmp_path)          # 仍然正常跑完并返回终态
    assert handler.current_turn == 2


def test_ga_dir_fallback_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv('GA_DIR', raising=False)
    assert hook._ga_dir().endswith('gacore')
