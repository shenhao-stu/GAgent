"""Android execution backend. The agent and handler remain upstream GA."""
import os, sys, re, time, threading, subprocess, traceback
from ga import safe_print, smart_format, format_error
import run_guard
script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
run_guard.install_thread_inheritance()
# cwd/stdio are process-global. Reject overlap; never queue stale phone actions.
_python_worker_lock = threading.Lock()

def code_run(code, code_type="python", timeout=60, cwd=None, code_cwd=None, stop_signal=None, maxlen=10000, myprint=safe_print):
    """代码执行器 (Android: python进程内exec, sh走/system/bin/sh)"""
    preview = (code[:60].replace('\n', ' ') + '...') if len(code) > 60 else code.strip()
    cwd = cwd or os.path.join(script_dir, 'temp')
    yield f"[Action] Running {code_type} in {os.path.basename(cwd)}: {preview}\n"
    os.makedirs(cwd, exist_ok=True)
    myprint("code run output:")
    full_stdout = []; exit_code = None
    if code_type in ["python", "py"]:
        header = ''
        cr_header = os.path.join(script_dir, 'assets', 'code_run_header.py')
        if os.path.exists(cr_header): header = open(cr_header, encoding='utf-8').read()
        box = {}
        class _Cap:
            def write(self, t): full_stdout.append(t)
            def flush(self): pass
        token = [False]   # 协作取消令牌: 超时/停止时置位; 僵尸线程下一次经 droid 副作用入口即抛 RunCancelled 自毁
        def _run():
            if not _python_worker_lock.acquire(blocking=False):
                full_stdout.append('[Executor busy] Previous Python worker is still active; no code executed.')
                box['exit'] = 1
                return
            old_out, old_err, old_cwd = sys.stdout, sys.stderr, None
            try:
                run_guard.enter(token)
                old_cwd = os.getcwd()
                os.chdir(cwd)
                sys.stdout = sys.stderr = _Cap()
                exec(compile(header + '\n' + code, '<code_run>', 'exec'),
                     {'__name__': '__main__', '__file__': os.path.join(cwd, '_code_run.py')})
                box['exit'] = 0
            except SystemExit as e:
                box['exit'] = int(e.code) if str(e.code).isdigit() else (0 if not e.code else 1)
            except run_guard.RunCancelled:
                box['exit'] = 1   # 被取消令牌中止: 静默退出(输出早已被监督线程取走), 不喷 traceback
            except BaseException:
                full_stdout.append(traceback.format_exc()); box['exit'] = 1
            finally:
                run_guard.leave()
                sys.stdout, sys.stderr = old_out, old_err
                try:
                    if old_cwd is not None: os.chdir(old_cwd)
                except OSError: pass
                finally: _python_worker_lock.release()
        t = threading.Thread(target=_run, daemon=True)
        start_t = time.time(); t.start()
        while t.is_alive():
            if time.time() - start_t > timeout:
                run_guard.cancel(token)
                full_stdout.append("\n[Timeout Error] 超时(令牌已取消; 僵尸线程下一次操作手机即自毁, 不再驱动整机)"); break
            if stop_signal:
                run_guard.cancel(token)
                full_stdout.append("\n[Stopped] 用户请求终止(令牌已取消; 僵尸线程下一次操作手机即自毁)"); break
            time.sleep(0.3)
        t.join(timeout=0.2)
        exit_code = None if token[0] else box.get('exit')
    elif code_type in ["sh", "shell", "bash", "powershell", "ps1", "pwsh"]:
        try:
            p = subprocess.run(["sh", "-c", code], capture_output=True, timeout=timeout, cwd=cwd)
            full_stdout.append(p.stdout.decode('utf-8', errors='replace') + p.stderr.decode('utf-8', errors='replace'))
            exit_code = p.returncode
        except subprocess.TimeoutExpired as e:
            full_stdout.append((e.stdout or b'').decode('utf-8', 'replace') + "\n[Timeout Error] 超时强制终止")
        except Exception as e:
            full_stdout.append(format_error(e)); exit_code = 1
    else:
        return {"status": "error", "msg": f"不支持的类型: {code_type}"}
    stdout_str = "".join(full_stdout)
    myprint(stdout_str)
    status = "success" if exit_code == 0 else "error"
    status_icon = "✅" if exit_code == 0 else ("⏳" if exit_code is None else "❌")
    output_snippet = smart_format(stdout_str, max_str_len=600, omit_str='\n\n[omitted long output]\n\n')
    output_snippet = re.sub(r'`{4,}', lambda m: m.group(0)[:3] + '\u200b' + m.group(0)[3:], output_snippet)
    yield f"[Status] {status_icon} Exit Code: {exit_code}\n[Stdout]\n{output_snippet}\n"
    return {"status": status,
            "stdout": smart_format(stdout_str, max_str_len=maxlen, omit_str='\n\n[omitted long output]\n\n'),
            "exit_code": exit_code}
