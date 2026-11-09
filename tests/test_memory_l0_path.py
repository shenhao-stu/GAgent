"""Exercise the real memory tool through the Android host, without live credentials."""
from pathlib import Path
import shutil
import subprocess
import sys

RUNTIME = Path(__file__).resolve().parents[1] / 'app/src/main/assets/ga_runtime'


def test_l0_uses_host_root_not_process_cwd(tmp_path):
    workspace = tmp_path / 'ga'
    shutil.copytree(RUNTIME, workspace, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    script = r'''
import os, pathlib, sys
from types import SimpleNamespace
w = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(w))
from kernel_adapter import install
install(w)
import ga
from agent_loop import exhaust
assert pathlib.Path(ga.script_dir) == w
handler = ga.GenericAgentHandler(SimpleNamespace(), cwd=str(w / 'temp'))
handler.current_turn = 20
memory = w / 'memory'
memory.mkdir(exist_ok=True)
l0 = memory / 'memory_management_sop.md'
l0.write_text('HOST_ROOT_L0', encoding='utf-8')
(memory / 'global_mem_insight.txt').write_text('HOST_ROOT_L1', encoding='utf-8')
other = w / 'other'
(other / 'memory').mkdir(parents=True)
(other / 'memory/memory_management_sop.md').write_text('WRONG_CWD_L0', encoding='utf-8')
(w / 'temp').mkdir(exist_ok=True)
for cwd in (w, w / 'temp', other):
    os.chdir(cwd)
    result = exhaust(handler.do_start_long_term_update({}, None))
    assert result.data == 'This is L0:\nHOST_ROOT_L0', (cwd, result.data)
    assert 'HOST_ROOT_L1' in result.next_prompt
# A missing real L0 must not fall back to a file in the process cwd.
l0.unlink()
result = exhaust(handler.do_start_long_term_update({}, None))
assert result.data == 'Memory Management SOP not found. Do not update memory.'
# Preserve the existing short-task guard.
l0.write_text('HOST_ROOT_L0', encoding='utf-8')
handler.current_turn = 2
result = exhaust(handler.do_start_long_term_update({}, None))
assert result.data == 'start_long_term_update is only used after completing a long turn task!'
assert result.next_prompt == '\n'
print('L0_PATH_OK')
'''
    result = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-c', script, str(workspace)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'L0_PATH_OK' in result.stdout
