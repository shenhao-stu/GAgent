"""iOS runtime boundary. This module is imported only from the signed bundle.

Provider configuration is read as data and never imported. The file tools stay inside the
workspace data folders. code_run executes Python and sh in the app process (kernel_adapter.ios_executor)
and is limited by the app sandbox, not by this module.
"""
import ast
import hashlib
import json
import os
import shutil
import sys
import threading
import time
import weakref
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

CONSENT_VERSION = '2026-09-12-original-ios-v2'
UNSUPPORTED_TOOL = 'iOS 没有这个工具；请使用当前工具列表中的工具。'
_sessions = weakref.WeakSet()
_policy_cache = {}
_lock = threading.RLock()


def is_ios():
    return sys.platform == 'ios'


def data_root():
    return Path(os.environ['GA_DIR']).resolve()


def code_root():
    return Path(__file__).resolve().parent


def checked_path(path, *, write=False, base=None):
    """Agent/PC transfer paths: data roots only, with real-path symlink containment."""
    if not isinstance(path, (str, os.PathLike)) or not str(path).strip():
        raise ValueError('文件路径不能为空')
    root = data_root()
    p = Path(path)
    p = ((Path(base) if base else root / 'temp') / p).resolve()
    for name in ('temp', 'memory', 'uploads'):
        allowed = root / name
        if p.is_relative_to(allowed) and allowed.resolve() == allowed:
            if p == allowed and write:
                raise ValueError('不能修改工作区根目录')
            if name == 'memory' and write and p.suffix.lower() not in ('.txt', '.md', '.json', '.py'):
                raise ValueError('记忆与技能仅支持文本和 Python 模块 (.txt/.md/.json/.py)')
            return str(p)
    if not write and (p.is_relative_to(code_root() / 'assets') or p == phone_guide()):
        return str(p)
    raise ValueError('iOS 文件工具仅访问 temp、memory、uploads；应用代码和凭据不可修改或读取')


def phone_guide():
    return code_root() / 'memory/phone_use_ios.md'


def parse_config(source):
    """Read legacy mykey.py as an assignment-only data format, never execute it.

    Supports aliases, literals, dict/list/tuple constructors and literal dict unpacking.
    Unknown imports, method calls, comprehensions and mutations fail without changing source.
    """
    if len(source.encode('utf-8')) > 2 * 1024 * 1024:
        raise ValueError('mykey.py 太大；请在服务商设置重新保存，原文件已保留')
    values = {}

    def bad(node):
        raise ValueError('mykey.py 第 %s 行不是静态配置；请在服务商设置重新保存，原文件已保留' % getattr(node, 'lineno', '?'))

    def val(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (str, int, float, bool, type(None))):
            return n.value
        if isinstance(n, ast.Name) and n.id in values:
            return values[n.id]
        if isinstance(n, (ast.List, ast.Tuple)):
            return [val(x) for x in n.elts]
        if isinstance(n, ast.Dict):
            result = {}
            for k, v in zip(n.keys, n.values):
                if k is None:
                    d = val(v)
                    if not isinstance(d, dict):
                        bad(v)
                    result.update(d)
                else:
                    result[val(k)] = val(v)
            return result
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            number = val(n.operand)
            if type(number) not in (int, float):
                bad(n)
            return -number if isinstance(n.op, ast.USub) else number
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr):
            a, b = val(n.left), val(n.right)
            if isinstance(a, dict) and isinstance(b, dict):
                return {**a, **b}
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            name = n.func.id
            if name == 'dict' and len(n.args) <= 1:
                out = val(n.args[0]) if n.args else {}
                if not isinstance(out, dict):
                    bad(n)
                out = dict(out)
                for kw in n.keywords:
                    if kw.arg is None:
                        d = val(kw.value)
                        if not isinstance(d, dict):
                            bad(kw.value)
                        out.update(d)
                    else:
                        out[kw.arg] = val(kw.value)
                return out
            if name in ('list', 'tuple') and len(n.args) <= 1 and not n.keywords:
                out = val(n.args[0]) if n.args else []
                if isinstance(out, list):
                    return list(out)
        bad(n)

    try:
        tree = ast.parse(source, filename='mykey.py', mode='exec')
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue  # module docstring
            if isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) for t in node.targets):
                value = val(node.value)
                for t in node.targets:
                    values[t.id] = value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
                values[node.target.id] = val(node.value)  # annotations are never evaluated
            else:
                bad(node)
    except (SyntaxError, TypeError, RecursionError) as e:
        raise ValueError('mykey.py 不是可读取的静态配置；请在服务商设置重新保存，原文件已保留') from e
    return {k: v for k, v in values.items() if not k.startswith('_')}


def load_config():
    p = data_root() / 'mykey.py'
    if p.exists():
        return parse_config(p.read_text(encoding='utf-8')), str(p)
    p = data_root() / 'mykey.json'
    if not p.exists():
        return {}, str(p)
    data = json.loads(p.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or 'remote_url' in data:
        raise ValueError('iOS 配置须保存到本机静态服务商配置；不加载远程配置，原文件已保留')
    return data, str(p)


def clear_history_screenshots():
    """Remove capture artifacts owned by the app. Imported files and the photo library are separate."""
    root = data_root()
    targets = [root / 'temp/iphone_screens', root / 'temp/computer_screenshots']
    library = root.parent.parent
    if root.parent.name == 'Application Support' and library.name == 'Library':
        container = library.parent
        targets.append(container / 'Documents/board-vision-run')
        # WebKit creates transient copies when a captured image is attached to a chat.
        for folder in (container / 'tmp').glob('WKWebFileUpload-*'):
            if folder.is_dir() and not folder.is_symlink():
                for path in folder.iterdir():
                    if path.is_file() and path.suffix.lower() in {'.jpg', '.jpeg', '.png', '.heic'}:
                        targets.append(path)
    for target in targets:
        if target.is_symlink():
            target.unlink()
        elif target.exists() and target.resolve() == target:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()


def register_session(session):
    with _lock:
        _sessions.add(session)


def _endpoint(value):
    p = urlsplit(str(value or '').strip())
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.fragment:
        raise ValueError('iOS 服务商必须使用不含登录信息的完整 HTTPS API 地址')
    # Queries may contain API credentials; disallow rather than disclose them in consent.
    if p.query:
        raise ValueError('请把 API 密钥放入密钥字段；iOS API 地址不能包含查询参数')
    return urlunsplit(('https', p.netloc.lower(), p.path.rstrip('/'), '', ''))


def provider_id(endpoint, key):
    return hashlib.sha256((_endpoint(endpoint) + '\0' + str(key)).encode()).hexdigest()


def _receiver(endpoint, model, key, *, refresh=False, fetched=None):
    endpoint = _endpoint(endpoint)
    identity = provider_id(endpoint, key)
    return {
        'endpoint': endpoint,
        'model': str(model),
        'providerId': identity,
        'recipients': ['用户配置的服务商；其下游处理方由该服务商管理'],
    }


def _receivers(cfg, *, refresh=False, provider_ids=None):
    sources = [(v.get('apibase'), v.get('model', ''), v.get('apikey', ''))
               for k, v in cfg.items() if isinstance(v, dict) and v.get('apibase')
               and any(s in k for s in ('api', 'config', 'cookie')) and 'mixin' not in k]
    with _lock:
        sessions = list(_sessions)
    sources += [(s.api_base, s.model, s.api_key) for s in sessions]
    unique, fetched = {}, {}
    for endpoint, model, key in sources:
        try:
            selected = provider_ids is None or provider_id(endpoint, key) in provider_ids
            r = _receiver(endpoint, model, key, refresh=refresh and selected, fetched=fetched)
        except ValueError as e:
            # Never display an invalid URL: it may include userinfo or a key-bearing query.
            unique[('unsupported', str(model))] = {
                'endpoint': '不支持的服务商地址（已隐藏）',
                'model': str(model),
                'unavailable': True,
                'disclosureError': str(e),
                'recipients': ['未批准发送；请在服务商设置填写有效 HTTPS API 地址'],
            }
            continue
        unique[(r['endpoint'], r['model'], r['providerId'])] = r
    return sorted(unique.values(), key=lambda r: (r['endpoint'], r['model'], r.get('providerId', '')))


def _scope(receiver):
    # Credentials select verified metadata; models and routing order do not add recipients.
    return {
        'endpoint': receiver['endpoint'],
        'recipients': sorted(set(receiver.get('recipients', []))),
        **({'policyRevision': receiver['policyRevision']} if 'policyRevision' in receiver else {}),
    }


def _scopes(receivers):
    # Also projects legacy grants, which included model, key hash and mixin fields.
    scopes = {}
    for r in receivers:
        if r.get('unavailable'):
            continue
        scope = _scope(r)
        scopes[json.dumps(scope, ensure_ascii=False, sort_keys=True)] = scope
    return [scopes[k] for k in sorted(scopes)]


def _covered(receiver, scopes):
    return any(receiver['endpoint'] == grant['endpoint']
               and receiver.get('policyRevision') == grant.get('policyRevision')
               and set(receiver.get('recipients', [])).issubset(grant['recipients']) for grant in scopes)


def _consent_file():
    return data_root() / 'kv' / 'iosDataConsent.json'


def _saved_consent():
    try:
        saved = json.loads(_consent_file().read_text(encoding='utf-8'))
        return saved if isinstance(saved, dict) and saved.get('version') == CONSENT_VERSION and saved.get('acceptedAt') else {}
    except (OSError, ValueError):
        return {}


def _consent_status(config, saved, *, refresh=False, provider_ids=None):
    receivers = _receivers(config, refresh=refresh, provider_ids=provider_ids)
    if provider_ids is not None:
        if set(provider_ids) - {r.get('providerId') for r in receivers}:
            raise ValueError('服务商配置已变化，请重试')
        receivers = [r for r in receivers if r.get('providerId') in provider_ids]
    provider_map = {}
    for name, cfg in config.items():
        if (isinstance(cfg, dict) and cfg.get('apibase') and cfg.get('apikey')
                and any(x in name for x in ('api', 'config'))
                and not name.startswith('_') and 'mixin' not in name and 'workflow' not in name):
            try:
                provider_map.setdefault(cfg.get('name') or cfg.get('model') or name,
                                        provider_id(cfg['apibase'], cfg['apikey']))
            except ValueError:
                pass  # Invalid URLs remain redacted in receivers.
    saved_scopes = _scopes(saved.get('receivers', []))
    for r in receivers:
        r['needsRefresh'] = False
        r['accepted'] = not r.get('unavailable', False) and _covered(r, saved_scopes)
    scopes = _scopes(receivers)
    signature = hashlib.sha256(json.dumps({
        'version': CONSENT_VERSION,
        'receivers': scopes,
    }, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    accepted = bool(saved.get('pcAccepted')) and all(r['accepted'] for r in receivers if not r.get('unavailable'))
    return {
        'ok': True,
        'version': CONSENT_VERSION,
        'receivers': receivers,
        'providerSignature': signature,
        'accepted': accepted,
        'needsRefresh': False,
        'providerIds': provider_map,
        'pcAccepted': bool(saved.get('pcAccepted')),
        'pcRecipients': ['用户配对的电脑（电脑侧模型由用户管理）', '用户在可选组件中配置的 PC Link 信令及中继服务'],
    }


def consent_status(*, refresh=False, provider_ids=None):
    if provider_ids is not None and (not isinstance(provider_ids, list) or not all(isinstance(x, str) for x in provider_ids)):
        raise ValueError('providerIds must be a list of strings')
    config, _ = load_config()
    return _consent_status(config, _saved_consent(), refresh=refresh, provider_ids=provider_ids)


class ConsentRequired(PermissionError):
    def __init__(self, status):
        self.status = {**status, 'ok': False, 'error': 'ios_consent_required'}
        super().__init__(json.dumps(self.status, ensure_ascii=False))


def require_consent():
    if not is_ios():
        return {}
    saved = _saved_consent()
    if saved.get('pcAccepted'):
        return {'accepted': True, 'pcAccepted': True}
    config, _ = load_config()
    raise ConsentRequired(_consent_status(config, saved))


def has_consent():
    try:
        return not is_ios() or bool(_saved_consent().get('pcAccepted'))
    except Exception:
        return False


def model_headers(session):
    if not is_ios():
        return {}
    r = _receiver(session.api_base, session.model, session.api_key, refresh=True)
    # Read durable authorization after building receiver metadata, so revocation
    # stops unbound utility requests (such as share summaries) immediately.
    config, _ = load_config()
    saved = _saved_consent()
    if r.get('unavailable'):
        raise ValueError(r.get('disclosureError') or '无效的 HTTPS 服务商配置')
    if not saved or not _covered(r, _scopes(saved.get('receivers', []))):
        raise ConsentRequired(_consent_status(config, saved))
    if not session.verify:
        raise ValueError('iOS 模型请求必须验证 HTTPS 证书')
    return {}


def invalidate_policy():
    with _lock:
        _policy_cache.clear()


def consent_command(text):
    if text == '/ios.consent.status':
        return json.dumps(consent_status(), ensure_ascii=False)
    if not text.startswith('/ios.consent '):
        return None
    p = json.loads(text[len('/ios.consent '):])
    if not isinstance(p, dict):
        raise ValueError('bad consent object')
    f = _consent_file()
    if p.get('accepted') is False:
        f.unlink(missing_ok=True)
        from kernel_adapter.ios_transport import revoke
        revoke()
        entry = sys.modules.get('android_entry')
        if entry:
            for sess in list(getattr(entry, '_REG', {}).values()):
                if sess.agent:
                    sess.agent.abort()
        pc = sys.modules.get('pclink')
        if pc and pc._loop and pc._loop.is_running():
            import asyncio
            asyncio.run_coroutine_threadsafe(pc._disconnect(), pc._loop)
        return json.dumps({'ok': True, 'accepted': False})
    provider_ids = p.get('providerIds')
    status = consent_status(provider_ids=provider_ids)
    if p.get('accepted') is not True or p.get('version') != CONSENT_VERSION or p.get('providerSignature') != status['providerSignature']:
        raise ConsentRequired(status)
    f.parent.mkdir(parents=True, exist_ok=True)
    out = {k: status[k] for k in ('version', 'providerSignature')}
    out['acceptedAt'] = int(time.time())
    out['receivers'] = _scopes(_saved_consent().get('receivers', []) + status['receivers'])
    out['pcAccepted'] = True
    temp = f.with_suffix('.tmp')
    temp.write_text(json.dumps(out), encoding='utf-8')
    os.replace(temp, f)
    return json.dumps(consent_status(provider_ids=provider_ids), ensure_ascii=False)


MEMORY_SEED = '''# [Global Memory Insight]
L0: memory_management_sop.md
L2: ../memory/global_mem.txt
L3: phone_use_ios.md | memory_cleanup_sop.md
L4: L4_raw_sessions/
'''

MEMORY_STRUCTURE = '''Facts: ../memory/global_mem.txt; SOP text: ../memory/*.md.
Helper modules: ../memory/*.py, importable by name from code_run.
Read ../memory/memory_management_sop.md before updating memories. Keep the L1 index concise.
Use file_read/file_patch for existing memory; file_write for new text. Never store secrets.
Imported SOPs may describe another platform. The current iOS tool list is authoritative.
'''


MEMORY_ROUTES = f'''
[iOS capability routes]
Phone GUI / screenshots / app navigation: read {phone_guide()}; use the screen and hid tools.
Local scripts: code_run runs Python or sh inside this app; its limits are in the platform section.
Plan and Goal, file tools, editable memory/SOP text, multi-provider reasoning and paired-PC sessions remain available.
PC Link: pc_link GET /api/peers shows connected PC sessions; GET /api/hubs lists computers.
Web: code_run with requests (and bs4 for page text) for HTTP APIs and pages; use iPhone GUI for interactive sites.
'''


def project_memory(insight, factory_sources):
    """Project factory Android routes onto iOS; never rewrite the user's stored memory."""
    factory = {line for source in factory_sources for line in source.splitlines()}
    android_routes = ('phone_use.md', 'import ', 'Android', 'VLM', 'modes_index', 'ls ../memory/')
    kept = [line for line in insight.splitlines()
            if line not in factory or not any(marker in line for marker in android_routes)]
    result = '\n'.join(kept) + '\n'
    return result if MEMORY_ROUTES.strip() in result else result + MEMORY_ROUTES


SYSTEM_PROMPT = f'''
[iOS permanent platform capabilities]
This is the original Agent on iOS. Model reasoning, tool loops, Goal, memories/SOP text,
multiple providers and paired-PC sessions remain available.
code_run executes inside this app's own process, because iOS has no child processes: subprocess
and os.system do not work. Type python is CPython 3.13 in the app sandbox with network access: it
can use the standard library, requests, websockets, numpy, PIL and bs4, read and write this app's
files, and import helper modules saved as ../memory/*.py. Other apps' data is out of reach.
Type sh is a built-in dash for short file and text commands: ls, cp, mv, rm, mkdir, cat, grep,
sed, awk, sort, head, tail, wc, find, xargs, gzip, date. ios.sh(script) runs the same shell
from Python. It has no python, curl, git, ssh or tar (use Python's tarfile and zipfile). Its
commands are threads, so a script cannot start another sh (source files with `.` instead),
`( ... )` does not isolate cd or variables, a loop cannot be piped into a command, and
`echo ... >&2` is lost. Use python beyond that.
`import ios` reaches the system from python: objc (rubicon-objc, any iOS framework), on_main,
sh, pip_install (pure-Python packages only), and the recipes is_foreground, open_url (any
scheme), open_app (bundle id), clipboard_get/clipboard_set; print(ios.__doc__) lists them.
Opening URLs or apps and writing the clipboard need GAgent in front (ios.is_foreground()).
Give every network call its own timeout. On timeout or stop a pure-Python loop or a shell script
is interrupted, but a thread blocked in a native call cannot be killed and blocks later code_run
calls until it returns.
A crash in native code ends the whole app; work in small steps and write long results to files.
Keep scripts to temp, ../memory and ../uploads: changing the app's other files (webui, kv, mykey,
conversations) can break the app or expose credentials.
Use file_read/file_write/file_patch for files under the displayed temp cwd, ../memory or ../uploads.
For computer conversations use pc_link (GET /api/peers; GET /api/hubs).
List and delete local files with code_run.
iPhone GUI control has two atomic tools: screen provides an image, frame_id and optional OCR elements;
hid delivers keyboard or pointer input and reports delivery. The host composes them after an input
when this conversation has read the screen. Python scripts can import screen and hid independently.
Capabilities and examples: {phone_guide()}. This guide is in the signed bundle; user memory is separate.
hid status reports input_ready separately from screen readiness. Standalone HID needs no shared screen.
ReplayKit captures the screen locally; the paired ESP32-S3 delivers Bluetooth or USB HID input.
An input can name the frame it depends on. The host supplies the last delivered frame for a conversation
using screen; button gestures need no frame. A changed target returns frame_changed and a current image.
Elements are optional OCR candidates, not proof of buttons. Coordinates refer to the full-screen image;
region enlargements are for reading. Missing, stopped or catching-up sources have no current image.
type pastes specified text; stage_text prepares it while GAgent is in front for use in another app.
method keys types ASCII through the current input method. key cmd+v is the system's ordinary Paste.
tap count:2 clicks twice in place, including system prompts that ignore the first click after movement.
System prompts are part of the UI and can be handled within the user's authorization.
ios.open_app and ios.open_url need GAgent in front; button and swipe provide GUI navigation.
The model chooses the route, tool sequence, observations and recovery according to the task and results.
User takeover pauses input until explicit handback. ask_user releases input and invalidates old frames;
after handback, screen or button navigation can establish the current state. A delivery receipt is not
proof of the intended UI outcome; action_sent means input may have reached the phone, including on error.
Report actual observations and tool results; an unsuccessful code_run exit is not a successful execution.
Current tools and these platform capabilities supersede cross-platform examples in memory.
Before each tool call, give a concise <summary> of the next step in the user's language.
Errors and delivery receipts provide evidence for deciding whether and how to retry.
'''


LOCAL_TOOLS = frozenset({'code_run', 'ask_user', 'file_read', 'file_write', 'file_patch',
                         'update_working_checkpoint', 'start_long_term_update'})


DEVICE_TOOLS = frozenset({'screen', 'hid', 'pc_link'})


def _function(name, description, parameters):
    return {'type': 'function', 'function': {'name': name, 'description': description, 'parameters': parameters}}


def tool_schema(schema):
    """The shared local tools plus the iOS atomic tools, each with its own argument schema."""
    import hid
    import screen
    result = [t for t in schema if t.get('function', {}).get('name') in LOCAL_TOOLS]
    result.append(_function('screen', screen.DESCRIPTION, screen.PARAMETERS))
    result.append(_function('hid', hid.DESCRIPTION, hid.PARAMETERS))
    result.append(_function(
        'pc_link', 'Paired computer sessions through the hub. GET /api/hubs lists computers, GET /api/peers '
        'lists connected PC sessions; then use the documented paths.',
        {'type': 'object', 'properties': {'method': {'type': 'string'}, 'path': {'type': 'string'},
                                          'body': {'type': 'object'}}, 'required': ['path']}))
    return result


def _pc_tool(args):
    if not is_ios():
        raise ValueError('PC tools are iOS only')
    if not isinstance(args, dict):
        raise ValueError('arguments must be an object')
    require_consent()


def pc_link(args):
    _pc_tool(args)
    import pclink
    return pclink.ios_request(args.get('method', 'GET'), args.get('path', ''), args.get('body'))
