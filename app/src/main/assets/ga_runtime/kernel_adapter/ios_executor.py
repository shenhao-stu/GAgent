"""iOS execution backend for code_run. The agent and handler remain upstream GA.

iOS forbids child processes, so code runs on a worker thread inside the app process: Python in
the embedded interpreter, sh in the built-in shell (ios.run_shell). A Python run is cancelled
through its run_guard token plus an asynchronous exception, a shell script through the shell's
own cancel. A thread that is blocked inside a native call cannot be stopped; the result says so
instead of pretending.
"""
import ctypes
import json
import linecache
import os
import re
import sys
import threading
import time
import traceback
import uuid

import ios
import ios_policy as policy
import run_guard
from ga import safe_print, smart_format

run_guard.install_thread_inheritance()

PYTHON_TYPES = ('python', 'py')
SHELL_TYPES = ('sh', 'shell', 'bash')
PREAMBLE = 'import sys, os, json, re, time\n'
SOURCE_NAME = '<code_run>'
MARKER_NAME = '.code_run_inflight'
CANCEL_GRACE_SECONDS = 2.0
POLL_SECONDS = 0.1
OMITTED = '\n\n[omitted long output]\n\n'
BUSY = '[Executor busy] 上一次 code_run 的线程仍停在原生调用里，本次代码未执行；等它返回后再试。'

# Identifies this app launch, so a marker left by an earlier launch can be recognised.
LAUNCH_ID = uuid.uuid4().hex

# The working directory is process-global, so only one run may be active at a time.
_slot_lock = threading.Lock()
_active_run = None


class Run(list):
    """One code_run execution.

    It is the run_guard token itself (a one-element list holding the cancelled flag), so every
    thread started by the user code inherits it. It also collects the output of those threads.
    """

    def __init__(self):
        super().__init__([False])
        self.chunks = []
        self.collecting = True
        self.in_user_code = False
        self.exit_code = None
        self.worker = None

    def collect(self, text):
        if self.collecting:
            self.chunks.append(str(text))

    def output(self):
        return ''.join(self.chunks)


def current_run():
    """The run that owns the calling thread, or None for the app's own threads."""
    token = getattr(run_guard._tls, 'token', None)
    return token if isinstance(token, Run) else None


class OutputRouter:
    """Stands in for sys.stdout and sys.stderr and sends each thread's text to its own run.

    Replacing the streams for the duration of a run would also capture what the app's other
    threads print meanwhile, so the router stays installed and decides per write.
    """

    def __init__(self, fallback):
        self.fallback = fallback

    def write(self, text):
        run = current_run()
        if run is not None and run.collecting:
            run.chunks.append(str(text))
            return len(text)
        if self.fallback is None:
            return len(text)
        return self.fallback.write(text)

    def flush(self):
        if current_run() is None and self.fallback is not None:
            self.fallback.flush()

    def __getattr__(self, name):
        return getattr(self.fallback, name)


def install_output_router():
    for name in ('stdout', 'stderr'):
        stream = getattr(sys, name)
        if not isinstance(stream, OutputRouter):
            setattr(sys, name, OutputRouter(stream))


def marker_path():
    return policy.data_root() / 'temp' / MARKER_NAME


def write_marker(preview):
    """Leave a note that survives the process, in case this run takes the app down."""
    marker = {'launch': LAUNCH_ID, 'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'preview': preview}
    path = marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(marker, ensure_ascii=False), encoding='utf-8')


def take_interrupted_run_notice():
    """Describe a run that never finished because an earlier app launch ended while it ran."""
    path = marker_path()
    try:
        marker = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ''
    if not isinstance(marker, dict) or marker.get('launch') == LAUNCH_ID:
        return ''
    path.unlink(missing_ok=True)
    return ('[Notice] 上一次 code_run（%s 开始：%s）执行期间 App 进程结束了，'
            '可能是那段代码使 App 崩溃或被系统终止。\n' % (marker.get('started'), marker.get('preview')))


def exit_status(run, code):
    """Map SystemExit.code to a process-style exit code, like the interpreter does."""
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    run.chunks.append(str(code) + '\n')
    return 1


def user_traceback():
    """Format the active exception without this module's own frame."""
    kind, error, trace = sys.exc_info()
    return ''.join(traceback.format_exception(kind, error, trace.tb_next if trace else None))


def execute(run, code, cwd):
    """Run the user's code on the calling thread, recording its exit code and traceback."""
    try:
        run_guard.enter(run)
        os.chdir(cwd)
        namespace = {'__name__': '__main__', '__file__': os.path.join(cwd, '_code_run.py')}
        exec(PREAMBLE, namespace)
        # Register the source so that tracebacks show the failing line.
        linecache.cache[SOURCE_NAME] = (len(code), None, code.splitlines(True), SOURCE_NAME)
        compiled = compile(code, SOURCE_NAME, 'exec')
        try:
            run.in_user_code = True
            exec(compiled, namespace)
        finally:
            run.in_user_code = False
        run.exit_code = 0
    except SystemExit as request:
        run.exit_code = exit_status(run, request.code)
    except run_guard.RunCancelled:
        run.exit_code = None
    except BaseException:
        run.chunks.append(user_traceback())
        run.exit_code = 1


def execute_shell(run, script, cwd):
    """Run a shell script through the built-in shell on the calling thread."""
    try:
        run_guard.enter(run)
        run.exit_code = ios.run_shell(script, cwd, run.collect)
    except run_guard.RunCancelled:
        run.exit_code = None
    except ios.IOSError as error:
        run.chunks.append('内置 shell 不可用：%s\n' % error)
        run.exit_code = 1


def free_slot(run):
    global _active_run
    with _slot_lock:
        if _active_run is run:
            _active_run = None


def release(run, previous_cwd):
    """Undo the process-wide effects of a run on its worker thread. Safe to repeat."""
    run.in_user_code = False
    run_guard.leave()
    if previous_cwd is not None:
        try:
            os.chdir(previous_cwd)
        except OSError:
            pass
    free_slot(run)


def worker_main(run, body, code, cwd):
    """Thread entry of a run. body is execute or execute_shell."""
    try:
        previous_cwd = os.getcwd()
    except OSError:
        previous_cwd = None
    try:
        body(run, code, cwd)
    except run_guard.RunCancelled:
        pass  # The cancellation arrived between two of execute's own handlers.
    finally:
        # A cancellation may still arrive here. It is injected only while in_user_code is set,
        # which release() clears first, so repeating the cleanup always terminates.
        while True:
            try:
                release(run, previous_cwd)
                break
            except run_guard.RunCancelled:
                continue


def raise_in_thread(thread):
    """Ask CPython to raise RunCancelled in another thread at its next bytecode instruction."""
    if thread.ident is not None:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(thread.ident),
                                                   ctypes.py_object(run_guard.RunCancelled))


def child_threads(run):
    """Live threads started by the user code. run_guard records the token they were created under."""
    return [thread for thread in threading.enumerate()
            if thread is not run.worker and getattr(thread, '_ga_token', None) is run]


def cancel(run):
    """Stop a run's threads. Returns True when the worker is still alive after the grace period."""
    run_guard.cancel(run)
    signalled = set()

    def signal_children():
        # Once per thread: a second exception would land in the thread's own exit handling.
        for thread in child_threads(run):
            if thread not in signalled:
                signalled.add(thread)
                raise_in_thread(thread)

    deadline = time.monotonic() + CANCEL_GRACE_SECONDS
    while run.worker.is_alive() and time.monotonic() < deadline:
        # A shell script (type sh, or ios.sh() called from Python) only stops through the shell.
        ios.cancel_shell()
        # Repeat for the worker: user code may swallow one exception, and a pending one is not
        # queued twice. in_user_code keeps the repeats out of the worker's cleanup.
        if run.in_user_code:
            raise_in_thread(run.worker)
        signal_children()
        run.worker.join(POLL_SECONDS)
    signal_children()
    return run.worker.is_alive()


def run_code(body, code, timeout, cwd, stop_signal, preview):
    """Execute code with body (execute or execute_shell) and return (output, exit_code).

    exit_code is None when the run was cancelled.
    """
    global _active_run
    run = Run()
    with _slot_lock:
        if _active_run is not None:
            return BUSY, 1
        _active_run = run
    try:
        install_output_router()
        notice = take_interrupted_run_notice()
        write_marker(preview)
        run.worker = threading.Thread(target=worker_main, args=(run, body, code, cwd), name='code_run',
                                      daemon=True)
        run.worker.start()
    except BaseException:
        free_slot(run)
        raise
    deadline = time.monotonic() + timeout
    reason = None
    while run.worker.is_alive():
        if time.monotonic() > deadline:
            reason = '[Timeout Error] 超过 %s 秒' % timeout
            break
        if stop_signal:
            reason = '[Stopped] 用户请求终止'
            break
        run.worker.join(POLL_SECONDS)
    stuck = cancel(run) if reason else False
    run.collecting = False
    marker_path().unlink(missing_ok=True)
    output = notice + run.output()
    if not reason:
        return output, run.exit_code
    if stuck:
        reason += ('；执行线程停在一次原生调用里（如 sleep、网络或文件等待），无法强制终止。'
                   '它返回后会自行结束，在此之前新的 code_run 会被拒绝。')
    else:
        reason += '，已中止执行。'
    return output + '\n' + reason, None


def code_run(code, code_type='python', timeout=60, cwd=None, code_cwd=None, stop_signal=None,
             maxlen=10000, myprint=safe_print):
    """代码执行器 (iOS: python 和 sh 都在 App 进程内执行，没有子进程)"""
    preview = (code[:60].replace('\n', ' ') + '...') if len(code) > 60 else code.strip()
    cwd = cwd or str(policy.data_root() / 'temp')
    yield f"[Action] Running {code_type} in {os.path.basename(cwd)}: {preview}\n"
    if code_type in PYTHON_TYPES:
        body = execute
    elif code_type in SHELL_TYPES:
        body = execute_shell
    else:
        return {'status': 'error', 'msg': f'不支持的类型: {code_type}'}
    os.makedirs(cwd, exist_ok=True)
    myprint('code run output:')
    output, exit_code = run_code(body, code, timeout, cwd, stop_signal, preview)
    myprint(output)
    status = 'success' if exit_code == 0 else 'error'
    icon = '✅' if exit_code == 0 else ('⏳' if exit_code is None else '❌')
    snippet = smart_format(output, max_str_len=600, omit_str=OMITTED)
    # Keep a long backtick run in the output from closing the chat's code fence.
    snippet = re.sub(r'`{4,}', lambda match: match.group(0)[:3] + '\u200b' + match.group(0)[3:], snippet)
    yield f"[Status] {icon} Exit Code: {exit_code}\n[Stdout]\n{snippet}\n"
    return {'status': status,
            'stdout': smart_format(output, max_str_len=maxlen, omit_str=OMITTED),
            'exit_code': exit_code}
