"""code_run 临时贴边；仅 UI 信号，不改执行结果，finally 覆盖异常/关闭。"""
from functools import wraps
import ga


def _notify(delta):
    try:
        from java import jclass
        jclass('com.ljq.ga.FloatService').codeRunDelta(delta)
    except Exception:
        pass  # 无 Android/浮窗桥不可用时，不影响工具执行。


def _install():
    original = ga.GenericAgentHandler.do_code_run
    if getattr(original, '_ga_float_dock', False):
        return

    @wraps(original)
    def docked(*args, **kwargs):
        _notify(1)
        try:
            return (yield from original(*args, **kwargs))
        finally:
            _notify(-1)

    docked._ga_float_dock = True
    ga.GenericAgentHandler.do_code_run = docked


_install()
