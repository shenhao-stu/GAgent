# iOS signed-bundle bootstrap: application code comes exclusively from Bundle/gacore.
# <AppSupport>/ga is retained as data (memory, conversations, uploads and static provider settings);
# only its memory/ and pylib/ folders are importable, after everything signed, for code_run scripts.
import os
import sys
import threading

_ga_dir = None
_heal_lock = threading.Lock()


def init(ga_dir):
    global _ga_dir
    _ga_dir = ga_dir
    os.environ['GA_DIR'] = ga_dir
    # Start from the signed application bundle only; the writable folders are re-added last, below.
    bundle = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if sys.platform == 'ios':
        sys.path[:] = [p for p in sys.path if p and os.path.realpath(p).startswith(bundle + os.sep)]
    else:
        # Host tests retain their host standard library; drop every writable GA data entry.
        sys.path[:] = [
            p for p in sys.path
            if p and not os.path.realpath(p).startswith(os.path.realpath(ga_dir) + os.sep)
            and os.path.realpath(p) != os.path.realpath(ga_dir)
        ]
    core = os.path.join(bundle, 'gacore')
    for path in (core, os.path.join(core, 'gacore')):
        if path not in sys.path:
            sys.path.insert(0, path)
    import ios_entry
    r = ios_entry.init(ga_dir)
    # android_entry also serves host tests; remove its legacy path insertion after host init.
    sys.path[:] = [p for p in sys.path if p and os.path.realpath(p) != os.path.realpath(ga_dir)]
    # code_run may import the user's helper modules and the pure-Python packages it installed.
    # Appended last, so they can never replace a module of the signed bundle or the standard library.
    for name in ('memory', 'pylib'):
        path = os.path.join(ga_dir, name)
        if path not in sys.path:
            sys.path.append(path)
    ios_entry._INITED = True
    return r


def call(fn, *args):
    if fn not in {'send', 'send2', 'poll', 'poll2', 'poll_all', 'abort', 'abort2', 'caps',
                  'select_model', 'ios_has_consent', 'iphone_abort', 'model_diagnostics',
                  'phone_takeover', 'presence_snapshot'}:
        return '{"error":"unknown_engine_fn"}'
    if fn == 'ios_has_consent':
        from ios_policy import has_consent
        return 'true' if has_consent() else 'false'
    if fn == 'iphone_abort':
        from ios_entry import iphone_abort
        return str(iphone_abort())
    if fn == 'presence_snapshot':
        # Read-only view for the status UI (ios/Presence). It must not start or heal the engine.
        import presence_snapshot
        return presence_snapshot.snapshot()
    import ios_entry
    if _ga_dir:
        healed = getattr(ios_entry, '_INITED', False)
        if healed:
            try:
                import android_entry
                healed = getattr(android_entry, '_INITED', False)
            except Exception:
                healed = False
        if not healed:
            with _heal_lock:
                if (not getattr(ios_entry, '_INITED', False)
                        or not getattr(__import__('android_entry'), '_INITED', False)):
                    init(_ga_dir)
    return str(getattr(ios_entry, fn)(*args))
