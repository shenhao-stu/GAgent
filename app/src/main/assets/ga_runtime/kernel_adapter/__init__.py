"""Android host wiring. gacore is copied verbatim from GenericAgent.

Upstream modules use flat imports and __file__-relative workspace paths.
Only agentmain's initialization sees the workspace path; its loader/source
remain upstream. No source rewriting or alternative agent loop is used.
"""
import importlib.util
import os
import sys
import threading
from pathlib import Path

_lock = threading.RLock()
_root = None


def install(workspace):
    global _root
    root = Path(workspace).resolve()
    with _lock:
        if _root is not None:
            if _root != root:
                raise RuntimeError('Android core already bound to another workspace')
            return sys.modules['agentmain']
        core = root / 'gacore'
        if not (core / 'agentmain.py').is_file():
            raise RuntimeError('Missing upstream gacore; reinstall the Python assets')
        for path in (str(root), str(core)):
            if path in sys.path: sys.path.remove(path)
            sys.path.insert(0, path)
        # Config (mykey) and phone modules live outside the core, on root's path.
        import ga
        if Path(ga.__file__).resolve().parent != core:
            raise RuntimeError('Another GA core is already imported')
        ga.script_dir = str(root)
        from . import executor
        executor.script_dir = str(root)
        ga.code_run = executor.code_run
        if 'agentmain' in sys.modules:
            raise RuntimeError('agentmain must be loaded by kernel_adapter first')
        spec = importlib.util.spec_from_file_location('agentmain', core / 'agentmain.py')
        module = importlib.util.module_from_spec(spec)
        # Retain upstream initialization, but direct mutable resources to the host.
        module.__file__ = str(root / 'agentmain.py')
        sys.modules['agentmain'] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop('agentmain', None)
            raise
        finally:
            module.__file__ = str(core / 'agentmain.py')
        # Android language selection is dynamic; upstream task/handler stays intact.
        original_prompt = module.get_system_prompt
        def get_system_prompt():
            module.lang_suffix = '_en' if os.environ.get('GA_LANG') == 'en' else ''
            return original_prompt()
        module.get_system_prompt = get_system_prompt
        _root = root
        return module
