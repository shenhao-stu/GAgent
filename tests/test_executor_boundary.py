"""One embedded Python worker owns process-global cwd/stdio until it exits."""
from pathlib import Path
import subprocess
import sys

RUNTIME = Path(__file__).resolve().parents[1] / 'app/src/main/assets/ga_runtime'


def test_live_or_timed_out_worker_rejects_new_python(tmp_path):
    script = r'''
import sys, pathlib, types, threading, os, time, traceback
sys.excepthook = lambda *args: traceback.print_exception(*args, file=sys.__stderr__)
sys.path.insert(0, sys.argv[1])
fake = types.ModuleType('ga')
fake.safe_print = lambda *a: None
fake.smart_format = lambda s, **kw: s
fake.format_error = str
sys.modules['ga'] = fake
from kernel_adapter import executor as ex
root = pathlib.Path(sys.argv[2]); ex.script_dir = str(root)
state = types.ModuleType('_boundary_state')
state.started = threading.Event(); state.release = threading.Event()
sys.modules[state.__name__] = state
before = os.getcwd(); streams = sys.stdout, sys.stderr

def exhaust(g):
    while True:
        try: next(g)
        except StopIteration as e: return e.value

results = []
def first():
    results.append(exhaust(ex.code_run('import _boundary_state as s; s.started.set(); s.release.wait(8)',
        cwd=str(root / 'first'), timeout=.1)))
t = threading.Thread(target=first); t.start()
assert state.started.wait(3)
try:
    # Timeout returns, but the worker remains alive: do not release exclusivity yet.
    t.join(2); assert not t.is_alive()
    marker = root / 'should_not_exist'
    result = exhaust(ex.code_run('open(%r,"w").write("bad")' % str(marker),
                                cwd=str(root / 'second'), timeout=1))
    assert result['status'] == 'error', result
    assert 'busy' in str(result).lower(), result
    assert not marker.exists()
finally:
    state.release.set(); t.join(3)
for _ in range(100):
    if sys.stdout is streams[0] and os.getcwd() == before: break
    time.sleep(.02)
assert (sys.stdout, sys.stderr) == streams and os.getcwd() == before
result = exhaust(ex.code_run('print("AFTER_RELEASE")', cwd=str(root / 'third')))
assert result['status'] == 'success' and 'AFTER_RELEASE' in result['stdout'], result
print('EXECUTOR_BOUNDARY_OK')
'''
    result = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-c', script, str(RUNTIME), str(tmp_path)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'EXECUTOR_BOUNDARY_OK' in result.stdout
