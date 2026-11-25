"""System access for code_run scripts on iOS. Use it from a script with `import ios`.

Primitives:
    ios.objc                      rubicon-objc; ios.objc.ObjCClass('UIDevice') reaches any iOS class
    ios.on_main(function)         run function() on the main thread (UIKit needs it), return its result
    ios.sh('ls -la | head')       built-in shell; returns returncode and stdout
    ios.pip_install('humanize')   pure-Python packages only

Recipes written with objc and on_main; read their source as examples for other frameworks:
    ios.is_foreground()
    ios.open_url('weixin://')          any scheme; True when iOS opened it
    ios.open_app('com.tencent.xin')    launch an installed app by bundle identifier
    ios.clipboard_set('text'); ios.clipboard_get()
A shortcut runs through its URL: 'shortcuts://run-shortcut?name=' + urllib.parse.quote(name).

iOS lets an app open URLs or other apps and write the clipboard only while that app is in
front, so check ios.is_foreground() when the phone may have left GAgent. A wrong selector raises
AttributeError, but wrong argument types can crash the app: keep Objective-C calls small.
"""
import codecs
import contextlib
import importlib
import os
import subprocess
import sys
import threading
import uuid

import ios_policy as policy

PACKAGE_FOLDER = 'pylib'
OPEN_ANSWER_SECONDS = 10
FOREGROUND_ACTIVE = 0  # UIApplicationStateActive


class IOSError(RuntimeError):
    """An iOS helper could not do what was asked."""


def _native():
    try:
        import _ganative
    except ImportError:
        raise IOSError('ios helpers work only inside the iOS app') from None
    return _ganative


def _objc():
    # rubicon-objc loads the Objective-C runtime on import, so it is imported on first use.
    return importlib.import_module('rubicon.objc')


def _class(name):
    try:
        return _objc().ObjCClass(name)
    except NameError:
        raise IOSError('%s is not available on this system' % name) from None


def on_main(function):
    """Call function() on the main thread and return its result.

    UIKit objects reached through ios.objc must be used on the main thread. The interface is
    frozen while function runs, so keep it short.
    """
    return _native().on_main(function)


def is_foreground():
    """True while GAgent is the app in front."""
    return on_main(lambda: _class('UIApplication').sharedApplication.applicationState == FOREGROUND_ACTIVE)


def open_url(url):
    """Ask iOS to open a URL. Returns False when nothing handles it or GAgent is not in front."""
    target = _class('NSURL').URLWithString_(str(url))
    if target is None or target.scheme is None:
        raise IOSError('url must be an absolute URL')
    answered = threading.Event()
    opened = []

    def finished(success: bool) -> None:
        opened.append(bool(success))
        answered.set()

    on_main(lambda: _class('UIApplication').sharedApplication.openURL_options_completionHandler_(
        target, {}, finished))
    if not answered.wait(OPEN_ANSWER_SECONDS):
        raise IOSError('iOS did not answer the open request within %s seconds' % OPEN_ANSWER_SECONDS)
    return opened[0]


def open_app(bundle_id):
    """Launch an installed app by bundle identifier. Raises IOSError when iOS does not open it."""
    workspace = _class('LSApplicationWorkspace').defaultWorkspace()
    if not on_main(lambda: bool(workspace.openApplicationWithBundleID_(str(bundle_id)))):
        raise IOSError('iOS did not open %s: it is not installed, or GAgent is not in front' % bundle_id)


def clipboard_get():
    """The clipboard text, or None. iOS may ask the user to allow pasting from another app."""
    text = on_main(lambda: _class('UIPasteboard').generalPasteboard.string)
    return None if text is None else str(text)


def clipboard_set(text):
    """Put text on the clipboard. Returns False when iOS ignored the write."""
    def write():
        pasteboard = _class('UIPasteboard').generalPasteboard
        before = pasteboard.changeCount
        pasteboard.string = str(text)
        return pasteboard.changeCount != before
    return on_main(write)


def _keep_imports_open():
    """Stop pip from guarding imports around an installation.

    pip assumes it owns the process: it fails every import made while it writes files, and
    warns about each new import for the rest of the process. Here the agent's other threads
    keep importing, and the warnings would land in the output of every later code_run.
    """
    from pip._internal.commands import install
    if hasattr(install, '_prevent_further_imports'):
        install._prevent_further_imports = lambda **options: contextlib.nullcontext()


def pip_install(*requirements):
    """Install pure-Python packages for later code_run calls. Raises IOSError when pip fails.

    iOS loads compiled extensions only from the signed app, so packages (or dependencies)
    that need one cannot be installed; pip reports them as having no matching distribution.
    A package that is already imported keeps running its old code until the app restarts.
    """
    from pip._internal.cli.main import main as pip_main
    _keep_imports_open()
    target = policy.data_root() / PACKAGE_FOLDER
    status = pip_main(['install', '--disable-pip-version-check', '--no-input', '--upgrade',
                       '--target', str(target), '--only-binary=:all:',
                       '--implementation', 'py', '--abi', 'none', '--platform', 'any',
                       *map(str, requirements)])
    importlib.invalidate_caches()
    if status != 0:
        raise IOSError('pip exited with status %s' % status)


def _forward(descriptor, write):
    """Pass everything readable from a pipe to write(text) until every writer has closed it."""
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    with open(descriptor, 'rb', buffering=0) as pipe:
        while chunk := pipe.read(65536):
            write(decoder.decode(chunk))
    write(decoder.decode(b'', final=True))


def run_shell(script, cwd, write):
    """Run a POSIX shell script in the built-in shell and return its exit status.

    The script's stdout and stderr go to write(text) as they arrive. The call returns when the
    script and every command it started have ended. Only one script can run at a time.
    """
    native = _native()
    folder = policy.data_root() / 'temp'
    folder.mkdir(parents=True, exist_ok=True)
    script_file = folder / ('.sh_%s.sh' % uuid.uuid4().hex)
    script_file.write_text(script, encoding='utf-8')
    read_end, write_end = os.pipe()
    reader = threading.Thread(target=_forward, args=(read_end, write), name='shell output', daemon=True)
    # Not part of the code_run that started it: cancelling the run must not kill the reader.
    reader._ga_token = None
    reader.start()
    previous = os.getcwd()
    try:
        return native.shell_run('dash "%s"' % script_file, os.path.abspath(cwd), write_end)
    except RuntimeError as error:
        raise IOSError(str(error)) from None
    finally:
        os.close(write_end)
        reader.join()
        os.chdir(previous)  # The shell leaves the process in the script's directory.
        script_file.unlink(missing_ok=True)


def cancel_shell():
    """Ask the running shell script, if any, to stop. Repeat until run_shell returns."""
    native = sys.modules.get('_ganative')
    if native is not None:
        native.shell_cancel()


def sh(script, cwd=None):
    """Run a POSIX shell script in the built-in shell.

    Returns subprocess.CompletedProcess with returncode and stdout (stderr is merged into it).
    The shell is dash with ls, cp, mv, rm, mkdir, cat, grep, sed, awk, sort, head, tail, wc,
    find, xargs, gzip, date and similar. Its commands are threads of the app, so there
    are no subshells, and a script cannot start another sh.
    """
    chunks = []
    status = run_shell(script, cwd or os.getcwd(), chunks.append)
    return subprocess.CompletedProcess(script, status, ''.join(chunks))


def __getattr__(name):
    if name == 'objc':
        return _objc()
    raise AttributeError('module %r has no attribute %r' % (__name__, name))
