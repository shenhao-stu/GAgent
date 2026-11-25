"""Behaviour of the in-process iOS code_run executor, on the signed payload.
Run: python3 -m pytest -q ios/tests/test_ios_code_run.py
No credentials, model calls or device operations are used.
"""
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from signed_runtime import HOST
from agent_loop import exhaust
from kernel_adapter import ios_executor as executor


class ShellStub(types.ModuleType):
    """Stands in for the built-in _ganative module: a shell that understands a few fixed scripts."""

    def __init__(self):
        super().__init__('_ganative')
        self.calls = []
        self.cancel_requests = 0
        self.stop = threading.Event()

    def shell_run(self, command, directory, output_fd):
        script_file = Path(command.removeprefix('dash "').removesuffix('"'))
        script = script_file.read_text(encoding='utf-8')
        self.calls.append((script, directory))
        os.chdir(directory)  # The real shell leaves the process in the script's directory.
        if script == 'sleep 60':
            os.write(output_fd, b'begin\n')
            self.stop.wait(30)
            return 0
        if script == 'broken':
            raise RuntimeError('this build has no built-in shell')
        os.write(output_fd, '目录 '.encode() + os.path.basename(directory).encode() + b'\n')
        return 3 if script == 'exit 3' else 0

    def shell_cancel(self):
        self.cancel_requests += 1
        self.stop.set()


class IOSCodeRunTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name).resolve()
        self.temp = self.root / 'temp'
        self.temp.mkdir()
        self.env = patch.dict(os.environ, {'GA_DIR': str(self.root)})
        self.env.start()
        self.start_cwd = os.getcwd()

    def tearDown(self):
        self.wait_until_idle()
        self.assertEqual(os.getcwd(), self.start_cwd)
        self.env.stop()
        self.directory.cleanup()

    def run_code(self, code, **options):
        return exhaust(executor.code_run(code, cwd=str(self.temp), **options))

    def wait_until_idle(self, seconds=10):
        deadline = time.monotonic() + seconds
        while executor._active_run is not None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertIsNone(executor._active_run)

    def test_runs_in_the_requested_directory_with_the_preamble(self):
        self.assertTrue(Path(executor.__file__).resolve().is_relative_to(HOST))
        result = self.run_code("print(json.dumps({'cwd': os.getcwd(), 'name': __name__}))\n"
                               "open('made.txt', 'w').write('x')")
        self.assertEqual((result['status'], result['exit_code']), ('success', 0))
        self.assertEqual(json.loads(result['stdout']), {'cwd': str(self.temp), 'name': '__main__'})
        self.assertTrue((self.temp / 'made.txt').is_file())
        self.assertFalse((self.temp / executor.MARKER_NAME).exists())

    def test_reports_the_failing_line_without_executor_frames(self):
        result = self.run_code("value = 1\nraise ValueError('broken %d' % value)\n")
        self.assertEqual((result['status'], result['exit_code']), ('error', 1))
        self.assertIn('File "<code_run>", line 2', result['stdout'])
        self.assertIn("raise ValueError('broken %d' % value)", result['stdout'])
        self.assertIn('ValueError: broken 1', result['stdout'])
        self.assertNotIn('ios_executor.py', result['stdout'])

    def test_system_exit_sets_the_exit_code(self):
        self.assertEqual(self.run_code('sys.exit(3)')['exit_code'], 3)
        self.assertEqual(self.run_code('sys.exit()')['exit_code'], 0)
        failed = self.run_code("sys.exit('gave up')")
        self.assertEqual((failed['exit_code'], failed['stdout']), (1, 'gave up\n'))

    def test_timeout_interrupts_a_python_loop_even_if_it_catches_exceptions(self):
        code = ("print('started')\n"
                "while True:\n"
                "    try:\n"
                "        sum(range(1000))\n"
                "    except Exception:\n"
                "        pass\n")
        started = time.monotonic()
        result = self.run_code(code, timeout=0.3)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual((result['status'], result['exit_code']), ('error', None))
        self.assertIn('started', result['stdout'])
        self.assertIn('[Timeout Error]', result['stdout'])
        self.assertIn('已中止执行', result['stdout'])
        self.assertEqual(self.run_code("print('next')")['stdout'], 'next\n')

    def test_a_thread_blocked_in_a_native_call_is_reported_and_blocks_the_next_run(self):
        result = self.run_code("time.sleep(3)\nopen('after_sleep.txt', 'w').write('x')", timeout=0.2)
        self.assertIsNone(result['exit_code'])
        self.assertIn('无法强制终止', result['stdout'])
        busy = self.run_code("print('must not run')")
        self.assertEqual((busy['status'], busy['exit_code']), ('error', 1))
        self.assertEqual(busy['stdout'], executor.BUSY)
        self.wait_until_idle()
        # The cancellation is delivered when the native call returns, before the next statement.
        self.assertFalse((self.temp / 'after_sleep.txt').exists())
        self.assertEqual(self.run_code("print('free again')")['stdout'], 'free again\n')

    def test_stop_signal_ends_the_run(self):
        stop_signal = []
        threading.Timer(0.3, stop_signal.append, args=(1,)).start()
        result = self.run_code("while True:\n    sum(range(1000))\n", timeout=30, stop_signal=stop_signal)
        self.assertIsNone(result['exit_code'])
        self.assertIn('[Stopped]', result['stdout'])

    def test_output_comes_only_from_the_run_and_its_own_threads(self):
        stop = threading.Event()

        def host_noise():
            while not stop.is_set():
                print('HOST-NOISE')
                time.sleep(0.01)

        host = threading.Thread(target=host_noise)
        host.start()
        try:
            result = self.run_code("import threading\n"
                                   "child = threading.Thread(target=lambda: print('from child'))\n"
                                   "child.start(); child.join()\n"
                                   "time.sleep(0.2)\n"
                                   "print('from main', file=sys.stderr)\n")
        finally:
            stop.set()
            host.join()
        self.assertEqual(result['stdout'], 'from child\nfrom main\n')

    # The cancelled child thread ends with an unhandled RunCancelled; that is the mechanism.
    @pytest.mark.filterwarnings('ignore::pytest.PytestUnhandledThreadExceptionWarning')
    def test_timeout_also_stops_threads_started_by_the_code(self):
        code = ("import threading\n"
                "def spin():\n"
                "    while True:\n"
                "        sum(range(1000))\n"
                "threading.Thread(target=spin, name='code-run-child', daemon=True).start()\n"
                "spin()\n")
        self.run_code(code, timeout=0.3)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and any(t.name == 'code-run-child' for t in threading.enumerate()):
            time.sleep(0.05)
        self.assertFalse(any(t.name == 'code-run-child' for t in threading.enumerate()))

    def test_a_marker_left_by_an_earlier_launch_is_reported_once(self):
        marker = self.temp / executor.MARKER_NAME
        marker.write_text(json.dumps({'launch': 'earlier-launch', 'started': '2026-11-11 10:00:00',
                                      'preview': 'crashy()'}), encoding='utf-8')
        code = f"print(json.load(open({executor.MARKER_NAME!r}))['launch'] == {executor.LAUNCH_ID!r})"
        first = self.run_code(code)
        self.assertTrue(first['stdout'].startswith('[Notice] '))
        self.assertIn('crashy()', first['stdout'])
        self.assertTrue(first['stdout'].endswith('True\n'))
        self.assertFalse(marker.exists())
        self.assertEqual(self.run_code("print('clean')")['stdout'], 'clean\n')

    def shell(self):
        stub = ShellStub()
        modules = patch.dict(sys.modules, {'_ganative': stub})
        modules.start()
        self.addCleanup(modules.stop)
        return stub

    def test_shell_scripts_run_in_the_built_in_shell(self):
        stub = self.shell()
        for code_type in ('sh', 'shell', 'bash'):
            result = self.run_code('ls -la', code_type=code_type)
            self.assertEqual(result, {'status': 'success', 'stdout': '目录 temp\n', 'exit_code': 0})
        self.assertEqual(stub.calls, [('ls -la', str(self.temp))] * 3)
        failed = self.run_code('exit 3', code_type='sh')
        self.assertEqual((failed['status'], failed['exit_code']), ('error', 3))
        self.assertEqual(list(self.temp.glob('.sh_*')), [])

    def test_a_shell_script_is_stopped_through_the_shell_on_timeout(self):
        stub = self.shell()
        started = time.monotonic()
        result = self.run_code('sleep 60', code_type='sh', timeout=0.3)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual((result['status'], result['exit_code']), ('error', None))
        self.assertTrue(result['stdout'].startswith('begin\n'))
        self.assertIn('[Timeout Error]', result['stdout'])
        self.assertIn('已中止执行', result['stdout'])
        self.assertGreaterEqual(stub.cancel_requests, 1)
        self.assertEqual(self.run_code("print('next')")['stdout'], 'next\n')

    def test_python_code_can_call_the_shell_and_is_stopped_with_it(self):
        stub = self.shell()
        result = self.run_code("import ios\ndone = ios.sh('ls')\nprint(done.returncode, done.stdout.strip())")
        self.assertEqual((result['exit_code'], result['stdout']), (0, '0 目录 temp\n'))
        stopped = self.run_code("import ios\nios.sh('sleep 60')\nprint('unreachable')", timeout=0.3)
        self.assertIsNone(stopped['exit_code'])
        self.assertNotIn('unreachable', stopped['stdout'])
        self.assertGreaterEqual(stub.cancel_requests, 1)

    def test_a_missing_shell_and_unknown_types_are_reported(self):
        without_app = self.run_code('touch ran', code_type='sh')
        self.assertEqual((without_app['status'], without_app['exit_code']), ('error', 1))
        self.assertIn('内置 shell 不可用', without_app['stdout'])
        self.shell()
        missing = self.run_code('broken', code_type='sh')
        self.assertIn('this build has no built-in shell', missing['stdout'])
        self.assertEqual(self.run_code('1', code_type='powershell'), {'status': 'error', 'msg': '不支持的类型: powershell'})
        self.assertEqual(list(self.temp.glob('.sh_*')), [])


if __name__ == '__main__':
    unittest.main()
