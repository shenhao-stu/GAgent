"""插件 hook 分发器 —— agent_loop.py 用 try/except 兜底加载本模块。
契约: agent_loop.py 在关键节点调 trigger(name, ctx)，ctx 是当时的 locals() 字典。
注册的 handler 抛错一律吞掉（埋点/插件绝不能拖垮 agent 主循环）。

已支持的 hook 名（见 agent_loop.py）:
  agent_before / agent_after — 单次任务开始/结束(ctx 有 user_input, turn, exit_reason 等)
  turn_before / turn_after   — 每个 LLM turn 前后(ctx 有 turn)
  llm_before / llm_after     — LLM 调用前后
  tool_before / tool_after   — 每个工具调用前后(ctx 有 tool_name, args)
"""
_HANDLERS = {}   # name -> [fn, ...]


def register(name, fn):
    _HANDLERS.setdefault(name, []).append(fn)


def trigger(name, ctx=None):
    for fn in _HANDLERS.get(name, ()):
        try:
            fn(ctx or {})
        except Exception:
            pass   # 插件失败不影响 agent


def discover_and_load():
    """agentmain.py 启动时调用: 导入本包下所有 *_hook.py, 让其在 import 时自注册。"""
    import os, importlib
    here = os.path.dirname(os.path.abspath(__file__))
    for f in sorted(os.listdir(here)):
        if f.endswith('_hook.py'):
            try:
                importlib.import_module(f'plugins.{f[:-3]}')
            except Exception:
                pass
