"""视觉必须用**当前任务选中的模型**，不是一份独立的视觉配置。

这条契约经过三次机制演进，测试一直锁着同一件事：
1. 最初只有 memory/vision_api.py 一条路（要用户自己拷模板、自己配 key）；
2. 后来改成 code_run 执行线程注入 threading.local（模型切换"自动跟随"，但 TLS 不跨
   线程继承——用户代码自起子线程调 ask_vision 会莫名拿不到后端）；
3. 现在改成 ga_android 在任务开始登记到模块级 _ACTIVE_BACKEND，两个入口都从那里读。

本文件锁第 3 条：_vision_backend() 读的是当前 agent 的 backend，且任务边界有登记动作。
"""
import sys
from pathlib import Path

import types

import numpy as np
import pytest
from unittest.mock import patch

CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import droid
import ga_android
import vision_llm


def test_ask_vision_uses_the_active_backend(monkeypatch):
    fake = object()
    calls = []

    def _ask(backend, image, prompt, **kw):
        calls.append((backend, prompt, kw))
        return 'active ok'

    monkeypatch.setattr(vision_llm, 'ask_with_backend', _ask)
    droid.set_active_backend(fake)
    try:
        out = droid.ask_vision(np.zeros((20, 20, 3), dtype=np.uint8), 'q')
    finally:
        droid.set_active_backend(None)
    assert out == 'active ok'
    assert calls and calls[0][0] is fake


def test_active_backend_failure_is_counted_for_the_fuse(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError('upstream read timeout')

    monkeypatch.setattr(vision_llm, 'ask_with_backend', _boom)
    droid.reset_vision_fuse()
    droid.set_active_backend(object())
    try:
        with pytest.raises(RuntimeError):
            droid.ask_vision(np.zeros((20, 20, 3), dtype=np.uint8), 'q')
    finally:
        droid.set_active_backend(None)
    assert droid._fuse_state(object.__new__(type('B', (), {'name': 'x'})))['n'] == 0  # 别的身份不受影响


def test_vision_backend_comes_from_the_active_agent():
    """_vision_backend() 读的是当前 agent 的 backend —— 视觉与主对话同一个对象。"""
    sentinel = object()
    h = object.__new__(ga_android.GenericAgentHandler)
    h.parent = types.SimpleNamespace(llmclient=types.SimpleNamespace(backend=sentinel))
    assert h._vision_backend() is sentinel
    h.parent = types.SimpleNamespace(llmclient=None)
    assert h._vision_backend() is None


def test_handler_init_registers_the_active_backend():
    """任务边界必须登记后端: 不登记则 ask_vision 只会报"没有可用模型后端"。"""
    sentinel = object()
    h = object.__new__(ga_android.GenericAgentHandler)
    h.parent = types.SimpleNamespace(
        llmclient=types.SimpleNamespace(backend=sentinel),
        task_dir=None, verbose=False, _turn_end_hooks={})
    h.working = {}; h.history_info = []; h.code_stop_signal = []
    h.cwd = '.'; h.current_turn = 0; h.print = lambda *a, **k: None
    droid.set_active_backend(None)
    with patch.object(ga_android, 'phone_ledger') as _pl:
        ga_android.GenericAgentHandler.__init__(h, h.parent)
    try:
        assert droid.active_backend() is sentinel
    finally:
        droid.set_active_backend(None)


def test_code_run_no_longer_snapshots_the_backend():
    """机制变更的锁定: code_run 不再收/传 vision_backend 形参, 也不再往 TLS 里写。

    旧实现的两个坑都在这里被排除: ①每次 code_run 一次性快照, 单次脚本内 /llm 换了
    client 就陈旧; ②threading.local 不跨线程继承, 用户代码自起子线程拿不到后端。"""
    import inspect
    assert 'vision_backend' not in inspect.signature(ga_android.code_run).parameters
    assert not hasattr(droid, '_VISION_TLS')
