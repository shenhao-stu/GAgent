"""Use the same signed Python payload as Xcode in an isolated temporary workspace."""
import atexit
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "app/src/main/assets/ga_runtime"
_tmp = tempfile.TemporaryDirectory(prefix="ga-ios-tests-")
atexit.register(_tmp.cleanup)
BUNDLE = Path(_tmp.name).resolve() / "GAgent.app"
HOST = BUNDLE / "gacore"
CORE = HOST / "gacore"
DATA = BUNDLE.parent / "workspace"
DATA.mkdir()
os.environ["GA_DIR"] = str(DATA)
shutil.copytree(ROOT / "ios/py", BUNDLE / "py", ignore=shutil.ignore_patterns("__pycache__"))
stage = runpy.run_path(str(ROOT / "ios/deps/stage_runtime.py"))["stage"]
stage(HOST)
for name in ("ga", "llmcore", "agentmain", "android_entry", "kernel_adapter", "ios_policy"):
    loaded = sys.modules.get(name)
    if loaded and not Path(loaded.__file__).resolve().is_relative_to(HOST):
        raise RuntimeError("Run iOS and Android tests in separate Python processes: " + name)
sys.path[:0] = [str(CORE), str(HOST), str(BUNDLE / "py")]
