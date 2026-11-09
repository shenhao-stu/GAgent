# Android in-process execution: no process-global subprocess monkey patches.
import sys, os, json, re, time, subprocess
_memory = os.path.join(os.environ.get('GA_DIR', os.path.dirname(os.path.dirname(__file__))), 'memory')
if _memory not in sys.path:
    sys.path.append(_memory)
try:
    import droid
    from droid import ask_vision
except Exception:
    pass
