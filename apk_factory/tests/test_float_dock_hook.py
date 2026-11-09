"""Float plugin lifecycle; no Android or agent runtime required."""
import runpy
import sys
import types
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / 'app/src/main/assets/ga_runtime/plugins/float_dock_hook.py'


@pytest.fixture
def dock(monkeypatch):
    events = []
    def original(self, value=7, error=None):
        yield 'running'
        if error:
            raise error
        return value
    handler = type('Handler', (), {'do_code_run': original})
    bridge = types.SimpleNamespace(codeRunDelta=events.append)
    monkeypatch.setitem(sys.modules, 'ga', types.SimpleNamespace(GenericAgentHandler=handler))
    monkeypatch.setitem(sys.modules, 'java', types.SimpleNamespace(jclass=lambda _: bridge))
    runpy.run_path(str(PLUGIN))
    return handler, events, bridge


def test_result_and_lazy_start(dock):
    handler, events, _ = dock
    gen = handler().do_code_run(value=42)
    assert events == []
    assert next(gen) == 'running'
    assert events == [1]
    with pytest.raises(StopIteration) as end:
        next(gen)
    assert end.value.value == 42
    assert events == [1, -1]


@pytest.mark.parametrize('error', [ValueError('bad'), KeyboardInterrupt()])
def test_exception_preserved_and_restored(dock, error):
    handler, events, _ = dock
    gen = handler().do_code_run(error=error)
    next(gen)
    with pytest.raises(type(error)) as exc:
        next(gen)
    assert exc.value is error
    assert events == [1, -1]


def test_close_and_concurrent_calls(dock):
    handler, events, _ = dock
    a, b = handler().do_code_run(), handler().do_code_run()
    next(a); next(b)
    assert sum(events) == 2
    a.close()
    assert sum(events) == 1
    b.close()
    assert sum(events) == 0


def test_install_idempotent(dock):
    handler, events, _ = dock
    wrapped = handler.do_code_run
    runpy.run_path(str(PLUGIN))
    assert handler.do_code_run is wrapped
    assert list(handler().do_code_run()) == ['running']
    assert events == [1, -1]


def test_bridge_failure_does_not_break_execution(dock):
    handler, _, bridge = dock
    def broken(_):
        raise RuntimeError('no UI')
    bridge.codeRunDelta = broken
    assert list(handler().do_code_run()) == ['running']


@pytest.mark.parametrize('inline', [False, True])
def test_real_handler_entry(monkeypatch, tmp_path, inline):
    import ast
    import os
    import re
    import json
    from types import SimpleNamespace
    core = PLUGIN.parents[1] / 'gacore/ga.py'
    tree = ast.parse(core.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GenericAgentHandler')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'do_code_run')
    events = []
    def execute(*args, **kwargs):
        assert events == [1]
        yield 'executing'
        return '42'
    env = dict(os=os, re=re, json=json, code_run=execute,
               _arg=lambda args, k, default, cast: cast(args.get(k, default)),
               StepOutcome=lambda data, **kw: SimpleNamespace(data=data))
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(core), 'exec'), env)
    handler = type('Handler', (), {'do_code_run': env['do_code_run']})
    monkeypatch.setitem(sys.modules, 'ga', SimpleNamespace(GenericAgentHandler=handler))
    monkeypatch.setitem(sys.modules, 'java', SimpleNamespace(jclass=lambda _: SimpleNamespace(codeRunDelta=events.append)))
    runpy.run_path(str(PLUGIN))
    obj = handler()
    obj.cwd = str(tmp_path)
    obj.parent = SimpleNamespace(llmclient=SimpleNamespace(backend=SimpleNamespace(history=[])))
    obj._get_tool_maxlen = lambda *a: 10000
    obj._get_anchor_prompt = lambda **kw: ''
    obj.code_stop_signal = None
    obj.print = print
    gen = obj.do_code_run({'script': '6 * 7', 'type': 'python', 'inline_eval': inline}, None)
    try:
        while True:
            next(gen)
    except StopIteration as end:
        assert end.value.data == '42'
    assert events == [1, -1]
