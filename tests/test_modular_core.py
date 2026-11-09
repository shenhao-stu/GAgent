"""Exercise the unmodified core through Android's host in a fresh process."""
from pathlib import Path
import shutil
import subprocess
import sys

RUNTIME = Path(__file__).resolve().parents[1] / 'app/src/main/assets/ga_runtime'


def test_android_host_core_roundtrip(tmp_path):
    workspace = tmp_path / 'ga'
    shutil.copytree(RUNTIME, workspace, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    script = r'''
import pathlib, sys, threading
from types import SimpleNamespace
w = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(w))
from kernel_adapter import install
m = install(w)
import ga, llmcore, android_entry
from agent_loop import exhaust
assert install(w) is m
assert pathlib.Path(m.__file__).parent == w / 'gacore'
assert m.script_dir == str(w)
assert ga.code_run.__module__ == 'kernel_adapter.executor'
assert llmcore.MixinSession.__module__ == 'llmcore'
r = exhaust(ga.code_run('print(6*7)', myprint=lambda *a, **kw: None))
assert r['status'] == 'success' and '42' in r['stdout'], r
# Deterministic model transport; real GenericAgent queue, loop and handler.
class Client:
    def __init__(self):
        self.backend = SimpleNamespace(history=[], model='smoke', name='smoke',
                                       maxlen_multiplier=1, extra_sys_prompt='')
        self.turn = 0
    def chat(self, messages, tools):
        self.turn += 1
        if self.turn == 1:
            response = llmcore.MockResponse(thinking='', raw=None, content='Running local tool', tool_calls=[
                llmcore.MockToolCall('code_run', {'script': "print('MODULAR_CORE_OK')"})])
        else:
            assert 'MODULAR_CORE_OK' in str(messages), messages
            response = llmcore.MockResponse(thinking='', raw=None, content='Task complete.', tool_calls=[])
        yield response.content
        return response
agent = m.GenericAgent()
client = Client()
agent.llmclient = client
agent.llmclients = [client]
agent.no_print = True
agent.log_path = False
thread = threading.Thread(target=agent.run, daemon=True)
thread.start()
output = agent.put_task('Run the local smoke test')
while True:
    event = output.get(timeout=15)
    if 'done' in event:
        assert 'Task complete.' in event['done'], event
        assert client.turn == 2, client.turn
        break
agent.task_queue.put('stop')
thread.join(3)
assert not thread.is_alive()
# Cancellation delegates to upstream, without replacing requests/time.
from kernel_adapter import patches
assert llmcore.requests.__name__ == 'requests'
assert llmcore.time.__name__ == 'time'
called = []
patches.abort_streams(SimpleNamespace(agent=SimpleNamespace(abort=lambda: called.append(True))))
assert called == [True]
# A timed-out script must not perform a later guarded phone action.
import time, subprocess, os
old_run, old_popen = subprocess.run, subprocess.Popen.__init__
old_out, old_err, old_cwd = sys.stdout, sys.stderr, os.getcwd()
marker = w / 'cancelled-action'
code = 'import time, run_guard; time.sleep(0.8); run_guard.check(); open(' + repr(str(marker)) + ', "w").write("bad")'
r = exhaust(ga.code_run(code, timeout=0.05, myprint=lambda *a, **kw: None))
assert r['status'] == 'error', r
time.sleep(1)
assert not marker.exists()
assert sys.stdout is old_out and sys.stderr is old_err and os.getcwd() == old_cwd
assert subprocess.run is old_run and subprocess.Popen.__init__ is old_popen
android_entry._refresh_mykeys()
assert llmcore.mykeys_store.path is None  # fresh install has no credentials
print('MODULAR_CORE_ROUNDTRIP_OK')
'''
    result = subprocess.run([sys.executable, '-I', '-c', script, str(workspace)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'MODULAR_CORE_ROUNDTRIP_OK' in result.stdout
