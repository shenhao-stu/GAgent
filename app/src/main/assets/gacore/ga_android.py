import sys, os, re, json, time, threading, importlib
from datetime import datetime
from pathlib import Path
import tempfile, traceback, subprocess, itertools, collections, difflib, shutil
if sys.stdout is None: sys.stdout = open(os.devnull, "w")
if sys.stderr is None: sys.stderr = open(os.devnull, "w")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent_loop import BaseHandler, StepOutcome, json_default
import run_guard   # 僵尸线程协作取消护栏(超时/停止后仍在后台派发手势的线程, 下一次操作手机即自毁)
import phone_ledger   # 动作账本(SPEC W3): 每轮 [LOOP-GUARD] 提示注入; 与 droid 执行边界守卫共用 ACTIVE 实例(本模块保持设备无关, 不 import droid)
import geom          # 坐标换算唯一权威(0-1000 ↔ 像素) + 实测系统 UI 锚带; 纯函数无设备依赖
run_guard.install_thread_inheritance()   # 让用户代码派生的子线程也继承取消令牌(僵尸孙线程同样受护栏); 幂等
script_dir = os.path.dirname(os.path.abspath(__file__))


class SoftFail(ValueError):
    """动作参数/前置条件不成立, 但现场有可行动事实可以回给模型 —— 不渲染成 [Error]。

    真机统计(2026-10-29~30, 22 次会话 45 条 `[Error]`): target 没命中 14 条、坐标越界/状态栏
    6 条、其余参数类 12 条, 真正的设备故障只有 2 条(无障碍未开)。这些"错误"其实都能当场给出
    正确写法(近似候选/正确单位/当前屏幕尺寸), 却因为 raise 变成了 UI 上的红块 —— 用户看到的
    就是"刚开始执行就一堆 error", 而模型还要再花一轮(真机 5.0-5.6s)才改对。
    SoftFail 由 _do_gui_act 的兜底转成 {"ok": false, "soft": true, ...} 的普通结果。
    继承 ValueError 是刻意的: 这些守卫的老契约与老测试都断言 ValueError。
    """
    def __init__(self, payload=None, message=''):
        self.payload = dict(payload or {})
        super().__init__(message or str(self.payload.get('hint') or 'soft failure'))


class SoftMiss(LookupError):
    """target 在这一屏没命中: 回近似候选清单, 不报错。继承 LookupError 保持老契约。"""
    def __init__(self, payload=None, message=''):
        self.payload = dict(payload or {})
        super().__init__(message or str(self.payload.get('hint') or 'target miss'))

def safe_print(*args, **kwargs):
    try: print(*args, **kwargs)
    except: pass

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
            # 截止时刻一并登记: droid.ask_vision 之类的昂贵调用据此自算总时长预算
            run_guard.enter(token, time.time() + timeout)
            old_out, old_err, old_cwd = sys.stdout, sys.stderr, os.getcwd()
            try:
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
                try: os.chdir(old_cwd)
                except: pass
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
        exit_code = box.get('exit')
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


def ask_user(question, candidates=None):
    """question: 向用户提出的问题。candidates: 可选的候选项列表"""
    return {"status": "INTERRUPT", "intent": "HUMAN_INTERVENTION",
        "data": {"question": question, "candidates": candidates or []}}

def format_error(e):
    exc_type, exc_value, exc_traceback = sys.exc_info()
    tb = traceback.extract_tb(exc_traceback)
    if tb:
        f = tb[-1]
        fname = os.path.basename(f.filename)
        return f"{exc_type.__name__}: {str(e)} @ {fname}:{f.lineno}, {f.name} -> `{f.line}`"
    return f"{exc_type.__name__}: {str(e)}"

def log_memory_access(path):
    if 'memory' not in path: return
    stats_file = os.path.join(script_dir, 'memory/file_access_stats.json')
    try:
        with open(stats_file, 'r', encoding='utf-8') as f: stats = json.load(f)
    except: stats = {}
    fname = os.path.basename(path)
    stats[fname] = {'count': stats.get(fname, {}).get('count', 0) + 1, 'last': datetime.now().strftime('%Y-%m-%d')}
    with open(stats_file, 'w', encoding='utf-8') as f: json.dump(stats, f, indent=2, ensure_ascii=False)

def expand_file_refs(text, base_dir=None):
    """展开文本中的 {{file:路径:起始行:结束行}} 引用为实际文件内容。
    可与普通文本混排。展开失败抛 ValueError。
    base_dir: 相对路径的基准目录，默认为进程 cwd"""
    pattern = r'\{\{file:(.+?):(\d+):(\d+)\}\}'
    def replacer(match):
        path, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        path = os.path.abspath(os.path.join(base_dir or '.', path))
        if not os.path.isfile(path): raise ValueError(f"引用文件不存在: {path}")
        with open(path, 'r', encoding='utf-8') as f: lines = f.readlines()
        if start < 1 or end > len(lines) or start > end: raise ValueError(f"行号越界: {path} 共{len(lines)}行, 请求{start}-{end}")
        return ''.join(lines[start-1:end])
    return re.sub(pattern, replacer, text)
    
def file_patch(path: str, old_content: str, new_content: str):
    """在文件中寻找唯一的 old_content 块并替换为 new_content"""
    path = str(Path(path).resolve())
    try:
        if not os.path.exists(path): return {"status": "error", "msg": "文件不存在"}
        with open(path, 'r', encoding='utf-8') as f: full_text = f.read()
        if not old_content: return {"status": "error", "msg": "old_content 为空，请确认 arguments"}
        count = full_text.count(old_content)
        if count == 0: return {"status": "error", "msg": "未找到匹配的旧文本块，建议：先用 file_read 确认当前内容，再分小段进行 patch。若多次失败则询问用户，严禁自行使用 overwrite 或代码替换。"}
        if count > 1: return {"status": "error", "msg": f"找到 {count} 处匹配，无法确定唯一位置。请提供更长、更具体的旧文本块以确保唯一性。建议：包含上下文行来增强特征，或分小段逐个修改。"}
        updated_text = full_text.replace(old_content, new_content)
        with open(path, 'w', encoding='utf-8') as f: f.write(updated_text)
        return {"status": "success", "msg": "文件局部修改成功"}
    except Exception as e: return {"status": "error", "msg": str(e)}

_read_dirs = set()
def _scan_files(base, depth=2):
    try:
        for e in os.scandir(base):
            if e.is_file(): yield (e.name, e.path)
            elif depth > 0 and e.is_dir(follow_symlinks=False): yield from _scan_files(e.path, depth - 1)
    except (PermissionError, OSError): pass
def file_read(path, start=1, keyword=None, count=200, show_linenos=True):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            stream = ((i, l.rstrip('\r\n')) for i, l in enumerate(f, 1))
            stream = itertools.dropwhile(lambda x: x[0] < start, stream)
            if keyword:
                before = collections.deque(maxlen=count//3)
                for i, l in stream:
                    if keyword.lower() in l.lower():
                        res = list(before) + [(i, l)] + list(itertools.islice(stream, count - len(before) - 1))
                        break
                    before.append((i, l))
                else: return f"Keyword '{keyword}' not found after line {start}. Falling back to content from line {start}:\n\n" \
                               + file_read(path, start, None, count, show_linenos)
            else: res = list(itertools.islice(stream, count))
            realcnt = len(res); L_MAX = min(max(100, 256000//max(realcnt,1)), 8000); TAG = " ... [TRUNCATED]"
            remaining = sum(1 for _ in itertools.islice(stream, 5000))
            total_lines = (res[0][0] - 1 if res else start - 1) + realcnt + remaining
            tl_str = f"{total_lines}+" if remaining >= 5000 else str(total_lines)
            partial = total_lines > realcnt
            total_tag = f"[FILE] {tl_str} lines" + (f" | PARTIAL showing {realcnt}; assess need for more" if partial else "") + "\n"
            res = [(i, l if len(l) <= L_MAX else l[:L_MAX] + TAG) for i, l in res]
            result = "\n".join(f"{i}|{l}" if show_linenos else l for i, l in res)
            if show_linenos: result = total_tag + result
            elif partial: result += f"\n\n[FILE PARTIAL: showing {realcnt}/{tl_str} lines; assess need for more]"
            _read_dirs.add(os.path.dirname(os.path.abspath(path)))
            return result
    except FileNotFoundError:
        msg = f"Error: File not found: {path}"
        try:
            tgt = os.path.basename(path); scan = os.path.dirname(os.path.dirname(os.path.abspath(path)))
            roots = [scan] + [d for d in _read_dirs if not d.startswith(scan)]
            cands = list(itertools.islice((c for base in roots for c in _scan_files(base)), 2000))
            top = sorted([(difflib.SequenceMatcher(None, tgt.lower(), c[0].lower()).ratio(), c) for c in cands[:2000]], key=lambda x: -x[0])[:5]
            top = [(s, c) for s, c in top if s > 0.3]
            if top: msg += "\n\nDid you mean:\n" + "\n".join(f"  {c[1]}  ({s:.0%})" for s, c in top)
        except Exception: pass
        return msg
    except Exception as e: return f"Error: {str(e)}"

def smart_format(data, max_str_len=100, omit_str=' ... '):
    if not isinstance(data, str): data = str(data)
    if len(data) < max_str_len + len(omit_str)*2: return data
    return f"{data[:max_str_len//2]}{omit_str}{data[-max_str_len//2:]}"

def consume_file(dr, file):
    if dr and os.path.exists(os.path.join(dr, file)): 
        with open(os.path.join(dr, file), encoding='utf-8', errors='replace') as f: content = f.read()
        os.remove(os.path.join(dr, file))
        return content

# see() 描述性问句的本地类别闸判据(纯函数, 无设备依赖, 可单测)。
# 22cae1a 已在 SOP 劝"目标明确先问 point", 但真机 14:49 仍先打全屏描述性 see()
# ("查看游戏当前画面")再问目标——每次 11-40s 对定位毫无帮助。这里在代码层兜底:
# 只在问句**纯问画面类别**时用本地 screen_kind() 应答, 不打 VLM。
_SEE_CLASS_INTENT = ('这是什么', '什么屏幕', '什么页面', '哪个页面', '什么界面', '哪个界面',
                     '当前画面', '当前屏', '是不是游戏', '是游戏吗', '大厅吗', '主界面吗', 'canvas')
# 内容/定位词: 命中任一即否决拦截, 放行 VLM(问的是内容或位置, 不是画面类别)。
_SEE_CONTENT_WORDS = ('在哪', '位置', '坐标', '有什么', '哪些', '写着', '文字', '内容', '模块', '按钮',
                      '输入框', '入口', '弹窗', '列表', '价格', '名称', '数量', '点哪', '怎么', '多少', '几个',
                      '是否', '有没有', '显示', '可见', '包含')
_KIND_MEANING = {
    'tree': '普通控件树(有可点/可读节点)',
    'blanked': '敏感 App 或未解析前台, 控件树被置空',
    'canvas': '自绘/游戏/SurfaceView 画面, 无可用控件树',
}

# 完成契约: 这些都是"控制消息/工具调用", 不是给用户的最终答复。模型偶尔会把它们当正文输出,
# 旧 do_no_tool 直接当作任务完成, 结果打开 finish_task/update_working_checkpoint 的 XML 也被当成 done。
_CONTROL_TAG_RE = re.compile(
    r'<\s*(?:update_working_checkpoint|tool_use|tool_call|finish_task|file_content|key_info)\b',
    re.I)
# 只匹配明确的"还在路上"信号, 不把普通结果里的"需要"误伤成未完成。
_INCOMPLETE_RE = re.compile(
    r'(需要依次|接下来|下一步|我将|我准备|正在(?:尝试|执行|查找|等待)|'
    r'尚未完成|还需要|待完成|即将(?:点击|打开|执行|完成)|'
    r'\b(?:next step|i will|i\'ll|i am going to|i\'m going to|still need|not yet|will now)\b)',
    re.I)


def _has_unparsed_control(text):
    """正文里出现控制/工具标签, 说明模型把协议消息写进了回复, 没有真正调用工具。"""
    return bool(_CONTROL_TAG_RE.search(text or ''))

def _visible_reply_text(text):
    """去掉内部块后的自然语言正文。只看这个判断是否真的给了用户一个结果。"""
    x = text or ''
    x = re.sub(r'<thinking>[\s\S]*?</thinking>', '', x, flags=re.I)
    x = re.sub(r'<summary>[\s\S]*?</summary>', '', x, flags=re.I)
    x = re.sub(r'<file_content[^>]*>[\s\S]*?</file_content>', '', x, flags=re.I)
    x = re.sub(r'<[^>]+>', ' ', x)
    return re.sub(r'\s+', ' ', x).strip()


def _looks_like_screen_class_question(q):
    """问句是否只在问"画面类别"而非内容/定位(see() 本地闸判据, 纯函数)。

    有类别意图词**且无**内容/定位词才拦。任何不确定都返回 False 放行 VLM——
    宁可多打一次贵的视觉, 不可把合理的内容诉求拦掉让模型多绕一轮。"""
    s = str(q or '')
    if not any(w in s for w in _SEE_CLASS_INTENT):
        return False
    return not any(w in s for w in _SEE_CONTENT_WORDS)

class GenericAgentHandler(BaseHandler):
    '''Generic Agent 工具库，包含多种工具的实现。工具函数自动加上了 do_ 前缀。实际工具名没有前缀。'''
    def __init__(self, parent, last_history=None, cwd='./temp'):
        phone_ledger.ACTIVE.clear()   # 任务边界: 动作账本不跨任务存活。上个任务卡死的尾巴(等价+aborted)会让
                                      # 新任务第一次动作直接被判 aborted 不下发, 并注入陈旧 [LOOP-GUARD](评审 C1 实证)
        try:
            import droid; droid.reset_trace()   # 操作痕迹同理: 不清则上个任务的 dump/tap 混进本次 recipe_record
        except Exception: pass                   # PC 侧/无设备环境下 droid 不可 import, 不影响工具库注册
        try:
            import droid; droid.reset_vision_fuse()   # 视觉熔断同理: 两次失败即冻结 120s, 上个任务
                                                      # 早期连撞两次(选中的模型不支持图片就会 2.4s 连错两次)
                                                      # 会让新任务整个游戏阶段失去唯一的 grounding 通道
        except Exception: pass
        try:
            import droid; droid.set_active_backend(self._vision_backend())   # 任务边界登记模型后端:
                                                      # 不登记则 ask_vision 只会报"没有可用模型后端"
        except Exception: pass
        self.parent = parent
        self.working = {}
        self.cwd = cwd;  self.current_turn = 0
        self.history_info = last_history if last_history else []
        self.code_stop_signal = []
        self._done_hooks = []
        self.print = safe_print
        # 通用任务状态: 完成必须由 finish_task 显式标记; GUI 动作计数用于判断
        # "模型只是输出计划/控制 XML" 时不能当成任务结束。
        self._gui_actions = 0
        self._task_finished = False
        self._no_tool_retries = 0
        self._finish_prompted = False
        self._vision_in_turn_attached = False
        self._see_cache = None
        self._see_failed_digest = None
        self._see_turn = -1
        self._memory_tip_shown = False
        # 动作核验/目标重注需要的状态位(读的时候全走 getattr 兜底, 旧 session 复用不会崩)
        self._last_act_ok = True      # 上一个 GUI 动作是否被后验证明生效
        self._last_expect = None      # 上次没命中的期望 → 下一轮当 [UNMET] 展示
        self._done_steps = []         # 已被动作验证过的里程碑 → 下一轮当 [DONE] 展示
        self._silent_exit_warned = False
        self._goal_text = ''
        self._last_bbox = None    # 最近一次画面变化的 bbox: close 只在这个范围里找关闭控件
        # 任务第一步必须让模型看到"此刻"的屏幕: 真机 15:29/15:34 两次任务里, 会话历史还带着
        # 上一个任务的截图与"弹窗已打开、密码是 XXXX"的结论, 而这一轮因为前台是桌面(auto 模式
        # 只在视觉型页面上附图)根本没发图 —— 模型凭旧记忆判断"弹窗还开着", 于是在桌面上连按
        # close/back, 把小程序退掉了。下面这个位保证第一步一定附图, 并清掉历史里的旧截图。
        self._task_frame_pending = True
        self._trap_seen = []      # 标题栏右侧(分享/更多)点过的位置: 同一处不再照点
        for _line in self.history_info:      # [USER] 行就是原始任务陈述: 每轮重注它, 防止子目标漂移
            _s = str(_line)
            if _s.startswith('[USER]'):
                self._goal_text = _s[len('[USER]'):].strip(' :：')
                break

    def _get_abs_path(self, path):
        if not path: return ""
        return os.path.abspath(os.path.join(self.cwd, path))   

    def _extract_code_block(self, response, code_type):
        code_type = {'python':'python|py', 'powershell':'powershell|ps1|pwsh', 'bash':'bash|sh|shell'}.get(code_type, re.escape(code_type))
        matches = re.findall(rf"```(?:{code_type})\n(.*?)\n```", response.content, re.DOTALL)
        if matches: return matches[-1].strip()
        # 兜底: 无语言标签的裸围栏(模型高频发; 旧正则只认带标签的→提取失败→整轮作废, 实证连废2轮≈19s)
        bare = re.findall(r"```\n(.*?)\n```", response.content, re.DOTALL)
        return bare[-1].strip() if bare else None

    def _vision_backend(self):
        """当前任务选择的模型后端: 视觉问答复用同一 provider/model/key/proxy, 随任务页切换。

        由 __init__(任务边界)与 turn_end_callback(每轮前) 登记进 droid._ACTIVE_BACKEND。
        模块级而不是 threading.local: 后者不跨线程继承, 用户代码自起子线程调 ask_vision
        会莫名拿不到后端。"""
        try:
            c = getattr(self.parent, 'llmclient', None)
            return getattr(c, 'backend', None) if c is not None else None
        except Exception:
            return None

    def do_code_run(self, args, response):
        '''执行代码片段，有长度限制，不允许代码中放大量数据，如有需要应当通过文件读取进行。'''
        code_type = args.get("type", "python")
        code = args.get("code") or args.get("script")
        if not code:
            code = self._extract_code_block(response, code_type)
            if not code:
                return StepOutcome(
                    "[Error] code_run 被调用但既没有 'script' 参数, 回复里也没有 ```python 代码块。"
                    "代码必须二选一: ①(推荐)放进本次工具调用的 script 参数; "
                    "②或在本条回复正文附一个带 python 标签的 ```python 代码块。"
                    "注意: 只在回复里写代码而不发这次工具调用, 代码不会被执行(该轮直接作废)。",
                    next_prompt="\n")
        try: timeout = int(args.get("timeout", 60))
        except: timeout = 60
        raw_path = os.path.join(self.cwd, args.get("cwd", './'))
        cwd = os.path.normpath(os.path.abspath(raw_path))
        code_cwd = os.path.normpath(self.cwd)
        maxlen = 6000 // args.get('_tool_num', 1)
        if code_type == 'python' and args.get("inline_eval"):
            ns = {'handler':self, 'parent':self.parent, 'history':json.dumps(self.parent.llmclient.backend.history)}
            old_cwd = os.getcwd()
            try:
                os.chdir(cwd)
                try:
                    try: result = repr(eval(code, ns))
                    except SyntaxError: exec(code, ns); result = ns.get('_r', 'OK')
                except Exception as e: result = f'Error: {e}'
            finally:
                os.chdir(old_cwd)
        else: result = yield from code_run(code, code_type, timeout, cwd, code_cwd=code_cwd, stop_signal=self.code_stop_signal, maxlen=maxlen, myprint=self.print)
        next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
        return StepOutcome(result, next_prompt=next_prompt)
    
    _GUI_ACTIONS = ('tap', 'swipe', 'longpress', 'text', 'key', 'launch', 'back', 'home', 'wait', 'close',
                    'search_app', 'exit_miniapp')

    _SEE_BUDGET_S = 20    # see() 自己的墙钟预算。视觉调用实测 15-46s; 超过 20s 的调用通常
                          # 是供应商卡住或整屏大图, 继续等只会把一次失败放大成 40-60s。超时后
                          # 让模型改走本地 observe/ocr, 而不是在同一屏上反复重试。

    def _coord_space_hint(self, args, out):
        """点了但屏幕没变时, 顺手排除一个高频成因: 坐标是从附图量的, 却填进了 `point`。

        只在 diff≈0 时说话 —— 那种情况"原样再点一次"本来也没有信息增益, 而附图坐标当设备像素
        用会整体缩到左上(真机 1200x2670 屏 / 647x1440 图 = 缩到 0.539 倍), 表现正是"点了没反应"。
        不改落点、不猜单位: 只把"你是不是从图上量的"这个问题摆出来, 并给出 img_point 写法。
        """
        wh = getattr(self, '_attached_img_wh', None)
        if not wh:
            return None
        pct = self._parse_diff_pct(out)
        if pct is None or pct >= 0.2:
            return None
        pv = args.get('point')
        if not isinstance(pv, (list, tuple)) or len(pv) != 2:
            return None
        try:
            px, py = float(pv[0]), float(pv[1])
        except (TypeError, ValueError):
            return None
        iw, ih = wh
        if not (0 <= px <= iw and 0 <= py <= ih):
            return None
        sw, sh = getattr(self, '_attached_screen_wh', None) or (0, 0)
        return ('point=%r 落在本轮附图尺寸 %dx%d 之内, 而屏幕是 %dx%d —— diff≈0 说明这次点没有生效。'
                '如果这个坐标是从附图(那张缩过的截图)上量的, 改传 img_point=%r, 换算由我做; '
                '如果它来自 obs/ocr 的 x/y, 那单位没错, 换个目标或先 observe 看清当前页。'
                % ([px, py], iw, ih, sw, sh, [px, py]))

    _RETRY_ALT_MAX = 2
    _PROGRESS_WINDOW = 6

    def _retry_noop_action(self, act, args, out, target_info):
        """点空以后就地换一个候选/换一种单位再点一次。

        真机实证(2026-10-30)两类白跑都能在这里救回来:
          · `target='套牌'` 首候选是正文里的同名文字, 点了三次 diff 0.3~0.5%, 第四次才点到
            底部导航栏 —— 候选清单本来就在手上, 换下一个候选比再问模型快得多;
          · 模型把附图(647x1440)上的坐标填进 point(设备像素), 上一次点击落在屏幕的 1/1.86 处,
            diff≈0, 它下一轮往往原样重发 —— 换算成设备像素再点一次通常就打中了。
        只在"确实点空"时触发, 每次最多 tap 两次, 不改变正常路径的耗时。"""
        import droid
        alts = list((target_info or {}).get('_alternatives') or [])
        tried = []
        if alts:
            for a in alts[:self._RETRY_ALT_MAX]:
                pt = a.get('point') or []
                if len(pt) != 2:
                    continue
                try:
                    r2 = (droid.tap(int(pt[0]), int(pt[1])) if act == 'tap'
                          else droid.longpress(int(pt[0]), int(pt[1]), int(args.get('ms') or 800)))
                except Exception:
                    break
                p2 = self._parse_diff_pct({'diff': r2.get('diff')})
                tried.append({'point': [int(pt[0]), int(pt[1])], 'diff': r2.get('diff')})
                if p2 is not None and p2 >= 0.2:
                    out['point'] = [int(pt[0]), int(pt[1])]
                    out['diff'] = r2.get('diff')
                    out['auto_retry'] = {'kind': 'target_alternate', 'index': a.get('index'),
                                         'tried': tried}
                    if out.get('target'):
                        tv = dict(out['target'])
                        tv['point'] = [int(pt[0]), int(pt[1])]
                        tv['index'] = a.get('index')
                        tv['chosen_by'] = 'auto_retry'
                        tv['alternatives'] = [x for x in (tv.get('alternatives') or [])
                                              if x.get('index') != a.get('index')]
                        tv['hint'] = ('第一次点空(diff≈0), 我换成了候选 %r; 还不对就传 '
                                      'target_index=<alternatives 里的 index>' % (a.get('index'),))
                        out['target'] = tv
                    return out
        # 没有别的候选: 试"图坐标 → 设备像素"
        # 只在**没给 target** 时才做: 给了 target 说明模型本来要的是那段文字, 位置是它自己量的,
        # 按比例硬换算过去常常落到别的控件上(09:45 那次就是这么点开分享的)。
        if args.get('target'):
            return out
        pt = out.get('point') or []
        iw, ih = getattr(self, '_attached_img_wh', None) or (None, None)
        if len(pt) == 2 and iw and ih:
            try:
                sw, sh = getattr(self, '_attached_screen_wh', None) or droid.screen()
            except Exception:
                sw = sh = None
            if sw and sh and (int(sw) != int(iw) or int(sh) != int(ih)) and 0 <= pt[0] <= iw and 0 <= pt[1] <= ih:
                sx, sy = int(round(pt[0] * float(sw) / iw)), int(round(pt[1] * float(sh) / ih))
                landed = self._landed_text(sx, sy)          # 点之前先认一下那位置是什么字
                try:
                    r3 = (droid.tap(sx, sy) if act == 'tap'
                          else droid.longpress(sx, sy, int(args.get('ms') or 800)))
                except Exception:
                    return out
                p3 = self._parse_diff_pct({'diff': r3.get('diff')})
                out['auto_retry'] = {'kind': 'img_scale',
                                     'from': [int(pt[0]), int(pt[1])], 'to': [sx, sy],
                                     'diff': r3.get('diff')}
                if landed:
                    out['auto_retry']['landed_on'] = landed  # 换算后落在什么控件上, 让模型能立刻纠正
                if p3 is not None and p3 >= 0.2:
                    out['point'] = [sx, sy]
                    out['diff'] = r3.get('diff')
                    # 第一次点空的 hint 到这里已经过期(画面明明变了), 留着只会误导下一轮
                    out.pop('hint', None)
                    out['retry_note'] = ('你给的坐标像附图坐标, 我按 %.2fx 换算成设备像素后点到了 %r; '
                                         '同一次别重复这个数 —— 直接给 img_point 或 target。'
                                         % (float(sw) / float(iw), landed or '该位置'))
        return out

    _CLOSE_WORDS = ('关闭', '关掉', '收起', '退出', '返回', '取消', 'close', 'dismiss', 'exit')

    @classmethod
    def _close_intent(cls, args):
        """这一步是不是"想把这一层关掉"。只看 expect/note 里的意图词, 不猜坐标。

        真机 2026-10-30 10:26: 模型连点标题栏右角 5 次, expect 全是"关闭今日密码弹窗" ——
        意图明确、位置错。这种组合下换成本地 close 比让它再点一次划算得多。"""
        txt = ' '.join(str(args.get(k) or '') for k in ('expect', 'note', 'reason', 'why'))
        return any(w in txt.lower() for w in cls._CLOSE_WORDS)

    _EXIT_WORDS = ('关闭小程序', '退出小程序', '离开小程序', '关掉小程序', '退到聊天',
                   'exit miniapp', 'close miniapp', 'quit miniapp')

    @classmethod
    def _exit_intent(cls, args):
        """这一步是不是"要离开整个小程序"(不是关页内弹层)。

        两者走的是不同控件: 页内弹层有自己的关闭键(action=close), 而"离开小程序"只能按
        小程序总控胶囊右侧那个键(action=exit_miniapp)。用户 2026-10-30 明确: 胶囊是总控,
        非必要不要点。"""
        txt = ' '.join(str(args.get(k) or '') for k in ('expect', 'note', 'reason', 'why'))
        return any(w in txt.lower() for w in cls._EXIT_WORDS)

    def _trap_note(self, x, y):
        """记住「标题栏右侧(分享/更多)」点过的位置 —— 测试替身可能没有这个属性。"""
        try:
            seen = getattr(self, '_trap_seen', None)
            if seen is None:
                seen = []
                self._trap_seen = seen
            seen.append((int(x), int(y)))
        except Exception:
            pass

    def _trap_tapped(self, x, y, tol=40):
        """这个任务里是否已经在标题栏右侧同一处点过(±40px)。"""
        for px, py in getattr(self, '_trap_seen', []) or []:
            if abs(int(px) - int(x)) <= tol and abs(int(py) - int(y)) <= tol:
                return True
        return False

    @staticmethod
    def _share_trap(x, y):
        """(x,y) 是否落在"标题栏右侧"——小程序/微信那段是分享/更多, 不是页内按钮。

        只用来挡"target 没命中、退回模型目测坐标"这一种情况: 那时点这里的期望是关掉一层,
        实际动作是把分享面板打开, 代价是后面 6 轮都在关分享(真机 2026-10-30 10:06)。
        正常指名 target 或 img_point 的点击不受影响。"""
        try:
            import droid, geom
            w, h = droid.screen()
            band = (getattr(geom, 'BANDS', {}) or {}).get('title') or (0.0, 0.055, 1.0, 0.120)
            y1, y2 = float(band[1]) * h, float(band[3]) * h
        except Exception:
            return False
        if not w or not h:
            return False
        return x > 0.55 * w and (y1 - 0.02 * h) <= y <= (y2 + 0.02 * h)

    @staticmethod
    def _diff_bbox(out):
        """从 'diff: 85.850% bbox=[0, 0, 1199, 2669]' 里取 bbox → [x1,y1,x2,y2], 取不到返回 None。"""
        try:
            txt = str(out.get('diff') or '')
            i = txt.find('bbox=[')
            if i < 0:
                return None
            body = txt[i + 6:txt.index(']', i)]
            vals = [int(float(v)) for v in body.split(',')]
            return vals[:4] if len(vals) >= 4 else None
        except Exception:
            return None

    @staticmethod
    def _landed_text(x, y, pad_x=220, pad_y=70):
        """点之前认一下 (x,y) 附近是什么字 —— 换算坐标最怕"点到了别的控件"。"""
        import droid
        try:
            img = droid.shot()
            H, W = img.shape[:2]
            x1, x2 = max(0, int(x) - pad_x), min(W, int(x) + pad_x)
            y1, y2 = max(0, int(y) - pad_y), min(H, int(y) + pad_y)
            texts = [str(t).strip() for _b, t, _s in (droid.ocr(img[y1:y2, x1:x2]) or [])]
            texts = [t for t in texts if t]
            return '|'.join(texts)[:60]
        except Exception:
            return ''

    def _note_progress(self, out):
        """按画面指纹判断"这一步真的往前走了吗", 并在原地给出层级提示。

        三角洲会话(2026-10-30 09:15)的死循环: 模型在"分享菜单打开/关闭"之间来回点 6 次,
        每次 diff 都是 85.850%(同一 bbox) —— 从 diff 看每步都成功, 实际一步没走; 而它要找
        的后续入口在**上一级**页面, 越在这一层点越出不来。指纹序列只有 ≤2 种值就是铁证,
        此时直接说"退到上一层", 比让它再观察一轮更快也更准。"""
        try:
            import droid
            dg = droid.frame_digest()
        except Exception:
            dg = ''
        if not dg:
            return
        hist = getattr(self, '_screen_hist', None)
        if hist is None:
            from collections import deque
            hist = self._screen_hist = deque(maxlen=self._PROGRESS_WINDOW)
        hist.append(dg)
        if len(hist) < 4:
            return
        distinct = set(hist)
        if len(distinct) <= 2:
            out['layer_hint'] = (
                '最近 %d 次动作的画面指纹只有 %d 种: 你在同一处"开了又关", 一步没往前走。'
                '目标不在这两幅画面里 —— 它更可能在**上一级**页面。回退用 '
                'gui_act action=back(它会先点屏上的「返回/关闭/×」按钮, 找不到才按系统返回); '
                '自绘/canvas/小程序页面里系统返回键通常无效, 所以也可以直接 target="返回"/"关闭"。'
                '站到上一级再找, 不要继续在这一层换坐标点。' % (len(hist), len(distinct)))
            hist.clear()

    @staticmethod
    def _parse_diff_pct(out):
        """把动作结果里的 'diff': '83.904%' 解析成 83.904; 解析不了返回 None(宁可不判, 也不猜)。"""
        d = (out or {}).get('diff')
        if isinstance(d, str) and '%' in d:
            try:
                return float(d.split('%', 1)[0].rsplit(' ', 1)[-1])
            except (TypeError, ValueError):
                return None
        return None

    _GUI_ACT_BUDGET_S = 120   # gui_act 硬墙钟。code_run 已有 timeout(默认 60s, 模型可传),
                              # see() 有自己的 90s; gui_act 曾是唯一没有上限的工具 —— 真机一次
                              # wait(seconds=8) 跑了 260s 并返回空 tool_result。

    def do_see(self, args, response):
        """看图问答(第一级工具, 不走 code_run)。

        什么时候用: 画面是游戏/自绘 canvas/混淆页(没有可用控件树, observe() 的定位通道为空)、
        或目标不在 obs 里、或需要理解画面语义。普通控件树上的图标/按钮/输入框已经在 obs 里,
        不要为"某个图标在哪"打 see() —— 本地 31ms, 视觉 15-46s。

        want='point' 拿坐标(固定问句 + 只认 0-1000 + 拒百分号, 可直接传 gui_act 的 rel);
        want='text' 拿自由文本。roi 送锚带名('title'/'status'/'navbar')或 0-1000 四元组,
        裁到局部像素量降 3-6 倍, 单次从 25-50s 降到 8-15s。失败永不要求重试。"""
        import json
        import time
        import droid
        q = str(args.get('question') or '').strip()
        if not q:
            return StepOutcome('[Error] see needs question (what you want to know about the screen)',
                               next_prompt='\n')
        want = str(args.get('want') or 'text')
        if want not in ('text', 'point'):
            return StepOutcome("[Error] see want must be 'text' or 'point'", next_prompt='\n')
        if want == 'text' and _looks_like_screen_class_question(q):
            # 1a: 问句纯问画面类别 → 本地 screen_kind() 应答, 不打 VLM/shot(省 15-40s)。
            # 判据见 _looks_like_screen_class_question(内容/定位问句一律放行)。本地拿不到
            # 可靠类别(unknown 或抛异常)就回落 VLM, 不装懂——截图/自称都不是成功证据。
            t1 = time.time()
            try:
                kind = droid.screen_kind()
            except Exception:
                kind = 'unknown'
            if kind != 'unknown':
                backend = droid.active_backend()
                out = {'ok': True, 'kind': kind, 'source': 'local',
                       'answer': '本地判定当前画面 kind=%s(%s)。这只是画面类别、不含内容: '
                                 '要定位某物请用 want="point" 直接问位置; 要读画面内容请用更具体的问题再 ask。'
                                 '(本次未调用视觉, 省 15-40s)'
                                 % (kind, _KIND_MEANING.get(kind, '')),
                       'model': (droid._backend_id(backend)[:80] if backend else None),
                       'ms': round((time.time() - t1) * 1000, 1)}
                return StepOutcome(json.dumps(out, ensure_ascii=False),
                                   next_prompt=self._get_anchor_prompt(skip=args.get('_index', 0) > 0))
        # 本轮主循环已经附了当前截图时, 再调 want='text' 只是在同一张图上重付一次 prefill+TTFT。
        # 精确文字优先用 ocr, 目标定位优先用 observe; 只有需要看语义/画面细节才允许强制 see。
        if want == 'text' and getattr(self, '_vision_in_turn_attached', False) and not args.get('force'):
            return StepOutcome(json.dumps({
                'ok': False, 'reason': 'redundant_image',
                'hint': '本轮消息已附当前屏幕截图, 直接读图即可; 需要精确文字用 ocr, '
                        '需要控件坐标用 observe。确需视觉语义复核再传 force=true。'
            }, ensure_ascii=False), next_prompt='\n')
        try:
            box = droid._resolve_roi(args.get('roi')) if args.get('roi') else (0, 0, geom.NORM, geom.NORM)
        except ValueError as e:
            return StepOutcome('[Error] see roi: %s' % e, next_prompt='\n')
        try:
            max_pixels = int(args['max_pixels']) if args.get('max_pixels') else None
        except (TypeError, ValueError):
            return StepOutcome('[Error] see max_pixels must be an int', next_prompt='\n')
        backend = droid.active_backend()
        if backend is None:
            return StepOutcome(json.dumps({
                'ok': False, 'reason': 'no_backend',
                'hint': '当前任务没有可用模型后端, 视觉不可用。改用 obs 里的本地图标框或 droid.ocr() '
                        '读屏; 确需看图请在任务页选择支持图片的模型。'}, ensure_ascii=False),
                next_prompt='\n')
        if droid._vision_cap(backend) == 'no_vision':
            return StepOutcome(json.dumps({
                'ok': False, 'reason': 'model_no_vision',
                'model': droid._backend_id(backend)[:80],
                'hint': '当前模型不支持图片, 视觉通道已停用。改用 obs 里的本地图标框或 droid.ocr() '
                        '读屏; 确需看图请换个支持图片的模型(切模型会自动解除)。'}, ensure_ascii=False),
                next_prompt='\n')
        t0 = time.time()
        try:
            img = droid.shot()
            # 同屏同问缓存: 重复 see 不改变答案, 但每次要重付 15-20s。截图摘要只用于判同屏。
            try:
                # 去掉状态栏时钟区域后再判同屏; 否则时间跳一分钟就会让缓存失效。
                h = img.shape[0]
                digest = hash(img[int(h * 0.04):, :].tobytes())
            except Exception:
                digest = None
            if digest is not None and getattr(self, '_see_failed_digest', None) == digest \
                    and not args.get('force'):
                return StepOutcome(json.dumps({
                    'ok': False, 'reason': 'already_failed',
                    'hint': '这一屏的 see 已经失败过; 按失败 hint 改走 observe/ocr 或 ask_user, '
                            '不要把同一张图再送一次。页面改变或确需强制复核再传 force=true。'
                }, ensure_ascii=False), next_prompt='\n')
            cache_key = (digest, want, q, tuple(box), max_pixels)
            prev = getattr(self, '_see_cache', None)
            if digest is not None and prev and prev.get('key') == cache_key:
                cached = dict(prev.get('out') or {})
                cached.update({'cached': True, 'ms': 0.0,
                               'hint': '同一屏同一问题已问过, 直接复用上次结果; 不要重复 see。'})
                return StepOutcome(json.dumps(cached, ensure_ascii=False),
                                   next_prompt=self._get_anchor_prompt(skip=args.get('_index', 0) > 0))
            # 同一轮已经调用过一次 see: 第二个问句通常是基于同一张图写的,
            # 模型实际还没看到第一个答案。先让它用已有结果做下一步, 避免同轮多付 20s。
            if getattr(self, '_see_turn', -1) == self.current_turn and not args.get('force'):
                return StepOutcome(json.dumps({
                    'ok': False, 'reason': 'redundant_turn',
                    'hint': '本轮已经调用过一次 see; 先用已有结果或 observe/ocr 做下一步, '
                            '不要在同一轮再问一次。确需强制复核传 force=true。'
                }, ensure_ascii=False), next_prompt='\n')
            # 观察入账(账本以前只记动作): see 是最贵的通道(实测均值 20.8s、最高 66.2s), 而同一屏
            # 反复问不同问句基本拿不到新信息。真机 25 轮里 11 次 see(合计 164s)一次都没被任何一档
            # 拦住。放在缓存/同轮闸之后: 那两档是"答案已经在手"(零成本), 这里才是"要再烧一次 20s"。
            _obs_hint = phone_ledger.ACTIVE.note_observation('see', digest, q)
            if _obs_hint and not args.get('force'):
                return StepOutcome(json.dumps({'ok': False, 'reason': 'repeated_observation',
                                               'hint': _obs_hint}, ensure_ascii=False),
                                   next_prompt=chr(10))
            self._see_turn = self.current_turn
            if want == 'point':
                text = droid.ask_vision(img, droid._ASK_POINT_PROMPT % q, roi=box,
                                        timeout=self._SEE_BUDGET_S, max_pixels=max_pixels)
                cx, cy = droid._parse_point(text)
                rx1, ry1, rx2, ry2 = box
                rx = int(round(rx1 + cx / float(geom.NORM) * (rx2 - rx1)))
                ry = int(round(ry1 + cy / float(geom.NORM) * (ry2 - ry1)))
                out = {'ok': True, 'rx': rx, 'ry': ry}
            else:
                concise_q = q + ('\n只回答当前画面可直接看到的事实，最多3行或200字；'
                                 '不要解释、不要推测、不要补充与问题无关的常识。')
                answer = str(droid.ask_vision(img, concise_q, roi=box, timeout=self._SEE_BUDGET_S,
                                              max_pixels=max_pixels))
                # 视觉回答最容易漂成长段散文。只保留前 600 字; 需要精确全文时用 ocr,
                # 不把一次 VLM 的跑题输出永久写进后续每轮上下文。
                if len(answer) > 600:
                    answer = answer[:600] + '…[truncated]'
                out = {'ok': True, 'answer': answer}
        except Exception as e:
            self._see_failed_digest = locals().get('digest')
            return StepOutcome(json.dumps({
                'ok': False, 'reason': 'call_failed',
                'error': '%s: %s' % (type(e).__name__, str(e)[:200]),
                'hint': '不要重试 see。直接调用 observe 工具(不是 code_run print(droid.observe())); '
                        '需要精确文字用 ocr 工具。确需看图检查当前模型是否支持图片, 或 ask_user。'},
                ensure_ascii=False),
                next_prompt='\n')
        out.update({'ms': round((time.time() - t0) * 1000, 1),
                    'model': droid._backend_id(backend)[:80]})
        self._see_cache = {'key': cache_key, 'out': dict(out)}
        self._see_failed_digest = None
        if want == 'point' and not args.get('roi'):
            # 1b: point 未传 roi → 全屏视觉 25-40s; 在执行点复述 roi 代价, 增强模型成本感知。
            # 只增字段、不改 rx/ry、不改成功路径; 传了 roi 不加。
            out['hint'] = ('未传 roi: 全屏视觉约 25-40s。若目标大致在顶/底/中, '
                           '传 roi=title/lower/middle 可降到约 8-15s。')
        return StepOutcome(json.dumps(out, ensure_ascii=False),
                           next_prompt=self._get_anchor_prompt(skip=args.get('_index', 0) > 0))

    def _resolve_point(self, args, key, rel_key):
        """gui_act 坐标: `point`=像素, `rel`=0-1000。两个具名字段二选一, 不猜单位。

        为什么不再用一个 point 猜(旧 _norm_pt 的「任一轴 >1000 就当像素」): 在
        1200x2670 上, y<=1000(屏幕上方 37%)且 x<=1000(宽 83%)的区域里, 像素坐标会被
        静默当成归一化值再缩一遍。实测放大镜像素 (996,215) → (1195,574), 偏 199px
        右、359px 下; 搜索框 (635,245) → (762,654), 偏 409px 下。不报错、无 hint,
        模型只看到 diff=0, 于是反复重点。而搜索框/放大镜/标题行**全在这片区域**,
        「点不到搜索框」因此是必然, 不是偶发。单位无法从一个数值对里可靠推断, 所以
        让调用方显式选: 观测 API(dump/look/find/obs 的 x,y)给的像素走 point,
        ask_vision 给的千分比走 rel。

        越界像素**报错而不夹取**: 夹取会把"单位选错"变成一个看似合理的落点, 正是要消掉
        的那类静默失败; 报错带上当前屏幕尺寸和 rel 写法, 模型一轮就能改对。rel 侧
        仍夹取(见 geom.to_px): VLM 估算溢出几个单位是噪声, 不值得废一轮。

        落在状态栏里的像素点同样报错: 状态栏(geom 的 status 锚带, 本机 y 0-4%)没有
        可点目标, SOP 也明令"绝不点状态栏", 所以踩进去几乎只有一个成因——把 0-1000
        的数对当成了像素。真机 17:48 实证: ask_vision 回的是百分数(85%), 模型乘 10 得
        850、又猜了 y=45, 当 point 传进去 → 实际点 (1020,120) 状态栏, 搜索页从未打开,
        而模型只看到 diff 29% 以为成功了。这里把它变成一句能自解释的错。
        确需点状态栏(极少数)走 code_run 的 droid.tap(x,y), 那条路没有这道门。"""
        import droid
        w, h = droid.screen()
        img_key = 'img_' + key
        has_px = args.get(key) is not None
        has_rel = args.get(rel_key) is not None
        has_img = args.get(img_key) is not None
        if sum(1 for f in (has_px, has_rel, has_img) if f) > 1:
            raise SoftFail({'units_given': [n for n in (img_key, key, rel_key)
                                            if args.get(n) is not None],
                            'hint': ('同一处坐标只填一个单位: %s=附图上量的像素(我换算), '
                                     'point=设备像素(obs/ocr 的 x,y), %s=0-1000(see 的 rx/ry)。'
                                     % (img_key, rel_key))},
                           '%s/%s/%s are the same coordinate in three units; pass only one'
                           % (img_key, key, rel_key))
        if not (has_px or has_rel or has_img):
            raise SoftFail({'screen': [w, h],
                            'hint': ('这个动作要位置: %s=[x,y](附图上量的像素, 我换算到设备像素) / '
                                     'point=[x,y](设备像素, 取 obs 或 ocr 的 x,y) / '
                                     '%s=[x,y](0-1000, 取 see 的 rx,ry)。当前屏幕 %dx%d。'
                                     % (img_key, rel_key, w, h))},
                           '%s needs %s [x,y] in the attached screenshot pixels, '
                           'point [x,y] in device pixels (dump()/look()/obs x,y) or '
                           '%s [x,y] in 0-1000 (see/ask_vision); screen is %dx%d'
                           % (key, img_key, rel_key, w, h))
        name = img_key if has_img else (key if has_px else rel_key)
        v = args[name]
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            raise SoftFail({'value': v, 'hint': '%s 要给 [x, y] 两个数, 例如 [612, 316]。' % name},
                           '%s must be [x, y], got %r' % (name, v))
        try:
            a, b = float(v[0]), float(v[1])
        except (TypeError, ValueError):
            raise SoftFail({'value': v, 'hint': '%s 的两个分量都要是数字; 现在是 %r。' % (name, v)},
                           '%s must be two numbers, got %r' % (name, v))
        if has_img:
            # 附图坐标(in-image pixels) → 设备像素。为什么必须有这条路: 每轮附给主模型的
            # 截图是缩放过的(长边 1440), 而 point/rel 分别是设备像素与 0-1000, 两者都不等于
            # "这张图上的像素"。真机实证(run 1793267115, 屏幕 1200x2670 / 附图 647x1440):
            # 模型照着提示"按图的像素给 point"给了 (334,270), 实际落到屏幕上 (334,270),
            # 偏左/偏上 1.855 倍, y>1440 的下半屏根本点不到 —— 搜索之后每一步都在偏处点,
            # 也就是"进了自绘页面就漂"。换算由代码做, 单位仍不猜(三选一, 只给一个)。
            wh = getattr(self, '_attached_img_wh', None)
            if not wh:
                raise SoftFail({'attached': False,
                                'hint': ('这一轮没有附图(文本协议会话或视觉关闭), 用不了 %s; '
                                         '改用 point=[x,y](设备像素, 取 obs/ocr 的 x,y) 或 %s(0-1000)。'
                                         % (img_key, rel_key))},
                               '%s needs a screenshot attached to this turn, but none was '
                               '(text-only session? vision off?) — use point (device pixels '
                               'from obs/ocr) or %s' % (img_key, rel_key))
            iw, ih = wh
            sw0, sh0 = getattr(self, '_attached_screen_wh', None) or (w, h)
            if not (0 <= a <= iw and 0 <= b <= ih):
                if 0 <= a <= sw0 and 0 <= b <= sh0:
                    # 数值超出附图、但落在屏幕范围内: 这其实是设备像素(obs/ocr 的 x,y)。
                    # 报错要白烧一轮, 而两种单位差 1.86 倍 —— 直接按设备像素用, 并把
                    # "我按 point 理解了"带回去, 下一轮它就知道该给 img_point。
                    self._unit_notes = getattr(self, '_unit_notes', None) or []
                    self._unit_notes.append('img_point %r 超出附图 %dx%d, 但落在屏幕 %dx%d 内: '
                                            '我按设备像素(point)处理了。' % (list(v), iw, ih, sw0, sh0))
                    return (int(a), int(b))
                raise SoftFail({'img': [iw, ih], 'screen': [sw0, sh0],
                                'hint': ('%s %r 超出附图范围 %dx%d。图上量的坐标是这张图的像素, '
                                         '不是设备像素: 重看附图上你要点的位置(图只有 %dx%d), '
                                         '或改用 point(设备像素)/%s(0-1000)。'
                                         % (img_key, v, iw, ih, iw, ih, rel_key))},
                               '%s %r is outside the attached screenshot (%dx%d); read the '
                               'position off the image of this turn, or pass point/rel'
                               % (img_key, v, iw, ih))
            sw, sh = getattr(self, '_attached_screen_wh', None) or (w, h)
            x = int(round(a * float(sw) / float(max(1, iw))))
            y = int(round(b * float(sh) / float(max(1, ih))))
            return (max(0, min(sw - 1, x)), max(0, min(sh - 1, y)))
        if has_rel:
            return geom.to_px(a, b, w, h)
        if not (0 <= a < w and 0 <= b < h):
            raise SoftFail({'screen': [w, h], 'value': v,
                            'hint': ('%s %r 超出屏幕 %dx%d。若这是 0-1000 的归一化值, 改成 %s=[%d, %d]; '
                                     '若是附图上的像素, 改成 %s。'
                                     % (name, v, w, h, rel_key, int(min(999, a)),
                                        int(min(999, b)), 'img_' + key))},
                           '%s %r is outside the current screen (%dx%d). If those are '
                           '0-1000 normalized values, pass them as %s instead.'
                           % (name, v, w, h, rel_key))
        if w > 1 and h > 1 and geom.in_band('status', int(a), int(b), w, h):
            nx, ny = geom.to_norm(int(a), int(b), w, h)
            raise SoftFail({'band': 'status', 'screen': [w, h], 'value': v,
                            'rel_suggestion': [nx, ny],
                            'hint': ('%s %r 落在状态栏(y 0-%d / %dx%d), 那里没有可点目标。'
                                     '这几乎总是把 0-1000 的归一化值当成了像素: 改成 %s=[%d, %d]。'
                                     '确需点状态栏就在 code_run 里用 droid.tap(x, y)。'
                                     % (name, v, int(0.04 * h), w, h, rel_key, nx, ny))},
                           '%s %r lands in the status bar (y 0-%d on a %dx%d screen), '
                           'which has no tap target. That almost always means these are '
                           '0-1000 normalized values, not pixels — pass them as %s '
                           '(e.g. %s:[%d, %d]). If you really must tap the status bar, '
                           'use droid.tap(x, y) in code_run.'
                           % (name, v, int(0.04 * h), w, h, rel_key, rel_key, nx, ny))
        return int(a), int(b)

    def _find_target_candidates(self, target, exact=False):
        """按可见文本/描述找目标。先走控件树, 再走 observe 的 YOLO+OCR, 最后直接 OCR。

        这是通用动作落地, 不是给某个 App 写坐标: 按钮/标签/输入框的文字在哪个通道能看到,
        就从哪个通道取边界。返回项统一带 x/y/bbox/source/t。找不到返回 []。
        """
        import droid
        target = str(target or '').strip()
        if not target:
            return []
        cands = []

        def add(item, source, text=''):
            try:
                x, y = int(item['x']), int(item['y'])
                t = str(text or item.get('t') or item.get('desc') or '')
                bbox = item.get('bbox') or [x, y, x, y]
                cands.append({'x': x, 'y': y, 'bbox': list(bbox), 't': t, 'src': source})
            except Exception:
                pass

        try:
            for n in droid.find(target, exact=exact):
                add(n, 'tree', n.get('t') or n.get('d') or '')
        except Exception:
            pass
        if cands:
            return self._dedupe_candidates(cands)

        try:
            obs = droid.observe()
            for it in obs.get('items') or []:
                hay = '%s %s %s' % (it.get('t') or '', it.get('desc') or '', it.get('cls') or '')
                if (hay.strip() == target) if exact else (target in hay):
                    add(it, 'observe', it.get('t') or it.get('desc') or '')
        except Exception:
            pass
        if cands:
            return self._dedupe_candidates(cands)

        # 树为空/敏感 App 时 observe 的 YOLO 可能拿不到语义图标; OCR 是文本目标的最后一层。
        try:
            import numpy as np
            img = droid.shot()
            H, W = img.shape[:2]
            pool = []   # 这一帧 OCR 到的全部文字, 供 miss 时给近似候选(见 _near_targets)
            for box, text, score in droid.ocr(img) or []:
                label = str(text).strip()
                pts = np.asarray(box)
                gx = int((pts[:, 0].min() + pts[:, 0].max()) / 2)
                gy = int((pts[:, 1].min() + pts[:, 1].max()) / 2)
                if label:
                    pool.append({'t': label[:30], 'point': [gx, gy]})
                if (label != target) if exact else (target not in label):
                    continue
                add({'x': gx, 'y': gy, 't': str(text),
                     'bbox': [int(pts[:, 0].min()), int(pts[:, 1].min()),
                              int(pts[:, 0].max()), int(pts[:, 1].max())]}, 'ocr', str(text))
            self._target_pool = pool[:40]
        except Exception:
            pass
        return self._dedupe_candidates(cands)

    @staticmethod
    def _dedupe_candidates(cands):
        out = []
        seen = set()
        for c in cands:
            key = (c['x'], c['y'], c['t'])
            if key in seen:
                continue
            seen.add(key)
            out.append(c)
        return out

    @staticmethod
    def _norm_target_text(s):
        """比较用归一: 只留字母/数字, 去掉空白与中英标点。

        模型常把 '三角洲行动 小程序' 写成带空格的样子, 而 OCR 出来的是 '三角洲行动小程序' ——
        只差一个空格就 miss, 一次 5-6s(真机 14/45 条 `[Error]` 是这类 target 未命中)。
        不用正则: 转义字符在生成脚本里已经被吃过一次, 直接按 isalnum 过滤最稳。
        """
        s = str(s or '').strip().lower()
        return ''.join(ch for ch in s if ch.isalnum())

    def _near_targets(self, target, limit=5):
        """target 没命中时给近似候选: 复用刚才那次候选搜索留下的文本池, 不再多截一张图。

        为什么必须有: 真机 45 条 `[Error]` 里 14 条是 `LookupError: target ... was not found`,
        而 miss 时返回里一个可用字符串都没有 —— 模型只能盲猜下一个写法。把这一屏真实存在
        的文字(带设备像素点)直接摆出来, 它同一轮就能照抄原文, 而不是再花 5-6s 试一次。
        """
        pool = getattr(self, '_target_pool', None) or []
        t0 = self._norm_target_text(target)
        scored = []
        for it in pool:
            t = str(it.get('t') or '')
            if not t:
                continue
            r = difflib.SequenceMatcher(None, t0, self._norm_target_text(t)).ratio()
            if r >= 0.5:
                scored.append({'t': t, 'point': list(it.get('point') or []), 'ratio': round(r, 2)})
        scored.sort(key=lambda x: -x['ratio'])
        return scored[:limit]

    @staticmethod
    def _rank_target_candidates(target, cands):
        """候选排序: 完全相等 > 前缀就是目标 > 只是包含 > 其它, 同一档按屏幕从上到下、从左到右。

        真机实证(2026-10-29, 微信搜"元梦之星"后的结果页): 8 个候选里既有搜索框回显 `Q元梦之星`
        @(292,245), 也有真正的结果行 `元梦之星` @(306,527)。旧实现直接抛错让模型重来一轮
        (5.6s/轮), 而按"完全相等 + y 最小"排, 选中的正好是那条结果行。
        """
        t0 = str(target or '')

        def key(c):
            t = str(c.get('t') or '')
            cls = 0 if t == t0 else (1 if t.startswith(t0) else (2 if t0 in t else 3))
            return (cls, int(c.get('y') or 0), int(c.get('x') or 0))

        return sorted(cands, key=key)

    @staticmethod
    def _target_view(info):
        """target 命中结果的统一呈现: 哪个候选、还有哪些候选、怎么改。

        "点了但没反应"最常见的成因之一就是同名多解选错了行; 把落选清单直接塞进结果,
        模型在同一轮就能改 target_index, 不必多跑一轮(真机 5.6s/轮)。
        """
        view = {'text': str(info.get('t') or '')[:60], 'src': info.get('src'),
                'point': [int(info.get('x') or 0), int(info.get('y') or 0)],
                'matches': info.get('_matches', 1)}
        alts = info.get('_alternatives') or []
        if int(view['matches']) > 1:
            view['index'] = info.get('_index', 0)
            view['chosen_by'] = 'auto'
            if alts:
                view['alternatives'] = alts
            view['hint'] = ('同名 %d 个, 我按"完全相等 + 从上到下"选了第 %d 个; 不对就传 '
                            'target_index=<alternatives 里的 index>' % (view['matches'], view['index']))
        return view

    def _close_expect_text(self, args):
        """从 target/expect 里抽出「这一层叫什么」, 给 close_dialog 做关闭后的消失核验。

        真机 15:11:34: 模型说 close 时弹窗里「航天基地」卡片刚好在 bbox 右上方, 旧实现把它
        当图标叉点了(进到航天基地详情), 又因卡片轮播抖 10% 判成功 —— 于是"关了"却还在弹窗里,
        下一句 target="制造推荐" 直接穿透到弹窗后面的卡片。
        例: '关闭今日密码弹窗' → '今日密码'; 抽不出(少于 2 字)返回 None, 退回只看画面变化。
        """
        raw = str(args.get('target') or args.get('expect') or '')
        for w in ('关闭窗口', '关闭弹窗', '关掉', '关闭', '弹窗', '弹层', '窗口',
                  '按钮', '页面', '对话框', '图标', '叉', '×', 'x', 'X'):
            raw = raw.replace(w, '')
        raw = raw.strip()
        return raw if len(raw) >= 2 else None

    def _resolve_action_target(self, args):
        """gui_act 的 target → 像素点。

        三个真机教训写在这里:
          · 模型经常同时给 target 和 point(它把 target 当成"我要点的是这个"), 旧实现直接
            ValueError 拒掉 —— 一轮 5.6s 白烧, 4 次/会话。现在两者共存不报错。
          · **target 优先于坐标**(2026-10-30 09:45 三角洲会话的教训): 模型给
            target="查看今日密码" + point=[513,115](那是 647x1440 附图上量的), 位置优先 → 落在
            屏幕 (951,213), 正好是标题栏右上角的**分享**图标, 于是"看一眼今日密码"变成了打开分享
            面板, 之后在取消/返回里绕了 6 轮。target 是全分辨率 OCR 的文字匹配, 与坐标单位无关,
            所以在文字能命中的时候它是更可信的那一个; 坐标只在 target 不存在/没命中时兜底。
          · 同名多解时不抛错, 按 _rank_target_candidates 选一个并**把落选清单一起带回去**,
            模型在同一轮内就能用 target_index 纠正, 不必多跑一轮。
        """
        target = str(args.get('target') or '').strip()
        if not target:
            return None
        if target in ('×', '✕', '╳', '✖') or self._norm_target_text(target) == 'x':
            # 真机 15:08:55 三角洲: 模型拿 target="X" 去关 canvas 弹窗, 文字层上正好有个别的
            # 'X' 字, 于是点到了 (361,2366) 底栏 —— 弹窗没关, 人已经跑偏。
            raise SoftFail({
                'target': target, 'zone': 'close_icon',
                'hint': ('别用 target=%r 关弹窗: canvas 弹窗上那个叉是画出来的, 文字层里没有它, '
                         '硬点只会命中屏幕上随便一个同样的字。要关这一层用 gui_act '
                         '{"action":"close"}; 要离开整个小程序用 {"action":"exit_miniapp"}。' % (target,))})
        try:
            idx = int(args.get('target_index')) if args.get('target_index') is not None else None
        except (TypeError, ValueError):
            raise SoftFail({'hint': 'target_index 必须是整数(0 起): 你要挑第几个候选就把序号填进来。'},
                            'target_index must be an int')
        cands = self._find_target_candidates(target, exact=bool(args.get('exact')))
        if not cands:
            # 没命中不是"错误", 是"这一屏没有这段字": 把这一屏真实存在的近似文字摆出来
            # (真机 14/45 条 [Error] 都是这里, 而旧返回里一个可用字符串都没有 → 模型盲猜)。
            near = self._near_targets(target)
            if near:
                best = near[0]
                runner = near[1]['ratio'] if len(near) > 1 else 0.0
                if best['point'] and best['ratio'] >= 0.85 and best['ratio'] - runner >= 0.15:
                    # 只差空格/标点/一个多余的字('三角洲行动 小程序' vs OCR 的 '三角洲行动小程序'):
                    # 直接命中, 并把"我把它当成了哪个"写回结果 —— 报错要白烧一轮(5-6s)。
                    fx, fy = int(best['point'][0]), int(best['point'][1])
                    return fx, fy, {'x': fx, 'y': fy, 't': best['t'], 'src': 'fuzzy',
                                    'bbox': [fx, fy, fx, fy], '_matches': 1, '_index': 0,
                                    '_alternatives': [], '_fuzzy': best['t'],
                                    '_ratio': best['ratio']}
            raise SoftMiss({'target_miss': target, 'near': near,
                            'hint': ('这一层没有 %r 这段文字。near 是这一屏 OCR 到的、和它最像的几行'
                                     '(t/point/ratio, point 是设备像素) —— 直接用 near 里的 t 作为 target, '
                                     '或按它的 point 点。若都不对, 说明入口在**上一级**页面: '
                                     '用 gui_act action=back(先点屏上的返回/关闭按钮) 或 action=close(关页内弹层)。'
                                     % target)},
                           'target %r not found; near=%r' % (target, [n['t'] for n in near]))
        cands = self._rank_target_candidates(target, cands)
        if idx is not None and not (0 <= idx < len(cands)):
            raise SoftFail({'target_index': idx, 'matches': len(cands),
                            'candidates': [{'index': i, 't': str(x.get('t') or '')[:30],
                                            'point': [int(x['x']), int(x['y'])]}
                                           for i, x in enumerate(cands[:6])],
                            'hint': 'target_index %r 超出范围 0..%d: 这些是这一屏的候选, 序号照 candidates 填。'
                                    % (idx, len(cands) - 1)},
                           'target_index %r out of range 0..%d' % (idx, len(cands) - 1))

        use = 0 if idx is None else idx
        c = dict(cands[use])
        c['_matches'] = len(cands)
        c['_index'] = use
        c['_alternatives'] = [{'index': i, 't': str(x.get('t') or '')[:30],
                               'point': [int(x['x']), int(x['y'])]}
                              for i, x in enumerate(cands[:6]) if i != use]
        return int(c['x']), int(c['y']), c

    def _expect_seen(self, expect, out):
        """动作后核验 expect 文本。返回 (True|False|None, 证据列表)。
        None = 当前通道读不到文字, 不伪造失败; False = 读到了文字但 expect 不在其中。

        只复用本次动作已带回的紧凑 obs, 不再额外截图/OCR。expect 是软确认, 不是动作
        成功判据: 每个动作都为它多付 1-3s 会直接拖慢任务, 而长句期望几乎必然误判。
        """
        if isinstance(expect, (list, tuple)):
            expect = '|'.join(str(x) for x in expect)
        parts = [p.strip() for p in re.split(r'\s*\|\s*', str(expect or '')) if p.strip()]
        if not parts:
            return True, []
        hay = []
        for it in out.get('obs') or []:
            for k in ('t', 'label', 'desc'):
                if it.get(k):
                    hay.append(str(it[k]))
        joined = ' '.join(hay).strip()
        if not joined:
            return None, []
        ok = any(p in joined for p in parts)
        return ok, [p for p in parts if p in joined]

    def do_gui_act(self, args, response):
        """GUI structured action: the model picks an action instead of writing Python.
        Measured on a real device against the alternative design: a free-form code agent
        burns 1-3 model calls per round exploring APIs; the structured action protocol
        finished 31 steps with almost no wasted turns. This design measured better."""
        # 看门狗: gui_act 此前是三个工具里唯一没有墙钟上限的。真机一次 wait(seconds=8)
        # 跑了 260s 并返回空 tool_result, 只能中止整个任务从头再来。设备侧每次调用自带
        # 60s 超时, 故检查点式看门狗把失控半径压到 ≤1 次设备调用。
        try:
            run_guard.enter_deadline(self._GUI_ACT_BUDGET_S)
        except Exception:
            pass
        try:
            return self._do_gui_act(args)
        except run_guard.WatchdogExpired:
            return StepOutcome('[Error] gui_act 超过墙钟上限 %ds 已停止: 不要原样重试 —— '
                               '先 dump()/observe() 看屏幕现在什么样, 再决定下一步, 或 ask_user。'
                               % self._GUI_ACT_BUDGET_S, next_prompt='\n')
        finally:
            run_guard.clear_deadline()

    def _do_gui_act(self, args):
        import droid
        act = str(args.get('action') or '')
        # 单位自纠的说明: _resolve_point 在"换了单位替我点"时往这里写一句, 由动作结果带回模型。
        self._unit_notes = []
        if act not in self._GUI_ACTIONS:
            return StepOutcome('[Error] gui_act unknown action %r, choose from: %s'
                               % (act, '/'.join(self._GUI_ACTIONS)), next_prompt='\n')
        if act == 'search_app':
            # 确定性搜索入口: 只固化"打开 App → 点搜索入口 → 输入关键词"这段固定路径(入口位置
            # 是 App 自身标题栏的稳定锚点), 结果列表/详情这些业务页仍然必须当帧观测 ——
            # geom.py:15-19 的边界没被破。真机实测: 模型为找放大镜花 16.3s 打一次 see()。
            # 关键词别名: 模型经常把关键词塞进 target/text(它以为 action=search_app 的"目标"就是词)
            q = str(args.get('value') or args.get('query')
                    or args.get('target') or args.get('text') or '').strip()
            pkg = str(args.get('pkg') or args.get('package') or '').strip()
            t0 = time.time()
            try:
                res = droid.app_search(pkg=pkg, query=q, wait=float(args.get('wait') or 2.0))
            except Exception as e:
                return StepOutcome(json.dumps({'ok': False, 'action': 'search_app',
                                               'error': '%s: %s' % (type(e).__name__, str(e)[:180]),
                                               'hint': '搜索入口原语失败; 改用 tap/text 手动一步步走。'},
                                              ensure_ascii=False), next_prompt=chr(10))
            res['action'] = 'search_app'
            res['ms'] = int((time.time() - t0) * 1000)
            self._gui_actions = getattr(self, '_gui_actions', 0) + 1
            self._finish_prompted = False
            self._no_tool_retries = 0
            self._see_failed_digest = None
            self._last_act_ok = bool(res.get('ok'))
            if res.get('ok'):
                self._done_steps = (getattr(self, '_done_steps', []) + ['已把 %r 输入搜索框' % q])[-6:]
            else:
                self._last_expect = '搜索入口未确认(%s)' % (res.get('hint') or '')[:40]
            return StepOutcome(json.dumps(res, ensure_ascii=False),
                               next_prompt=self._get_anchor_prompt(skip=args.get('_index', 0) > 0))
        if act in ('tap', 'longpress', 'swipe'):
            # 预观测: 动作落账要带「动作前」的观测, 才能从点所在节点推导 recipe locator。
            # 不喂它, gui_act 通道录出的配方 locator 全是 any, 回放第一步就升级(评审实证)。
            # 只对需要坐标的动作做: back/home/key/wait 没有可定位的目标。
            # 按需而非每次: 模型在 code_run 里刚 dump()/look() 过时观测仍然有效,
            # 再 dump 一次是纯浪费(真机 39 轮任务约 20 次 gui_act 各多付一次 a11y 往返)。
            try: droid.ensure_fresh_obs()
            except Exception: pass
        try:
            if act in ('tap', 'longpress'):
                target_info = None
                info = None
                target_miss = ''
                out_hint = ''
                if args.get('target'):
                    try:
                        info = self._resolve_action_target(args)
                    except (LookupError, ValueError) as e:
                        # target 没命中(或 index 越界)但给了坐标: 退回坐标这一手还能试 ——
                        # 但把没命中的原因带回去, 别让模型以为"文字找到了"。
                        has_pos = (args.get('point') is not None or args.get('rel') is not None
                                   or args.get('img_point') is not None)
                        if not has_pos:
                            raise
                        target_miss = str(e)[:160]
                if info:                       # target 命中就用它(文字比模型目测的坐标可信)
                    x, y, target_info = info
                else:
                    x, y = self._resolve_point(args, 'point', 'rel')
                    if target_miss and self._share_trap(x, y):
                        # 指名要找的文字不在屏上、退回的又是标题栏右角: 一步都别点。
                        raise SoftFail(
                            {'zone': 'miniapp_capsule', 'point': [x, y],
                             'target_miss': args.get('target'),
                             'hint': ('(%d,%d) 是小程序总控胶囊(左分享右关闭), 而 %r 不在这一屏: '
                                      '别点胶囊。要关这一层用 gui_act {"action":"close"}; '
                                      '要点真实文字用 target=... (先 ocr 看原文); '
                                      '要用图上的位置用 img_point=[x,y]。'
                                      % (x, y, args.get('target')))},
                            'point %r looks like the mini-program title bar right corner '
                            '(share/more), and target %r is not on screen. Close the layer with '
                            'gui_act action="close", or aim at real text with target=..., or use '
                            'img_point=[x,y] with pixels read off the attached screenshot.'
                            % ([x, y], args.get('target')))
                if self._share_trap(x, y) and (self._exit_intent(args) or self._close_intent(args)):
                    # 只拦"想关/想退"却点到右上角"的那一类: 标题栏右侧在小程序里是总控胶囊
                    # (左分享右关闭), 在微信主界面上却是放大镜 —— 光凭坐标分不开, 所以用意图分。
                    # 真机 2026-10-30 10:06 / 10:26 / 10:52 三次: 右上角是**小程序的总控胶囊**,
                    # 里面并排两个键 —— 左「分享/更多」, 右「关闭(退出小程序)」。用户要求:
                    # 非必要不要点。以前"第一次照点 + 提示"仍会点开分享面板(10:52:17 那次
                    # [890,200] diff 85.867% 就是它), 所以这里一步都不点, 只按意图改道:
                    #   · 意图是"离开小程序" → 交给 exit_miniapp 点胶囊右侧那个键;
                    #   · 其它意图(包括"关掉这一层") → 直接拒, 让它用 close/target/ocr。
                    if self._exit_intent(args):
                        res = droid.exit_miniapp()
                        out = {'action': act, 'redirect': 'miniapp_capsule_close',
                               'via': res.get('via'), 'diff': res.get('diff'),
                               'point': res.get('point') or [x, y],
                               'hint': ('(%d,%d) 是小程序总控胶囊: 左分享右关闭。你要离开小程序, '
                                        '我改点右边的关闭键: ' % (x, y))}
                        for k in ('ok', 'text', 'hint'):
                            if res.get(k) not in (None, ''):
                                out[k if k != 'hint' else 'close_hint'] = res[k]
                        if res.get('more'):
                            out['more'] = res['more']
                        self._trap_note(x, y)
                        self._last_act_ok = out.get('ok') is True
                        return StepOutcome(json.dumps(out, ensure_ascii=False, default=str),
                                           next_prompt=self._get_anchor_prompt(skip=True))
                    if self._close_intent(args):
                        # 意图是"关掉这一层"(页内弹层)却给了胶囊坐标: 不点胶囊, 改成 close 去
                        # 弹层自己的范围里找关闭控件(真机 10:26 那次就是这样连点 5 次分享键)。
                        res = droid.close_dialog(bbox=self._last_bbox,
                                                 expect_text=self._close_expect_text(args))
                        out = {'action': act, 'redirect': 'title_band_close',
                               'via': res.get('via'), 'diff': res.get('diff'),
                               'point': res.get('point') or [x, y],
                               'hint': ('(%d,%d) 是小程序总控胶囊(左分享右关闭), 不点它; 你要关这一层, '
                                        '我改成在弹层范围里找关闭键: ' % (x, y))}
                        for k in ('ok', 'text', 'hint'):
                            if res.get(k) not in (None, ''):
                                out[k if k != 'hint' else 'close_hint'] = res[k]
                        if res.get('tried'):
                            out['tried'] = res['tried']
                        self._trap_note(x, y)
                        self._last_act_ok = out.get('ok') is True
                        return StepOutcome(json.dumps(out, ensure_ascii=False, default=str),
                                           next_prompt=self._get_anchor_prompt(skip=True))
                if self._share_trap(x, y):
                    # 意图不是"关/退": 这一下可能是微信主界面的放大镜(0.83w), 放行但把语义讲清楚,
                    # 免得模型把它当"关闭/退出"反复点。
                    out_hint = ('[title-zone] 标题栏右侧([%d,%d])在小程序里是总控胶囊(左=分享/更多, '
                                '右=关闭/退出小程序), 非必要不要点; 微信主界面这里则是放大镜。'
                                '要关页内弹层用 gui_act {"action":"close"}, 要离开小程序用 '
                                '{"action":"exit_miniapp"}。' % (x, y))
                if act == 'tap':
                    ret = droid.tap(x, y)
                else:
                    ret = droid.longpress(x, y, int(args.get('ms') or 800))
                # verified/uncertain/hint/fg 必须一起转发: 坐标失效(屏幕形态变化)、点到非热区、
                # 验证不可用在模型眼里要能区分。只给 diff 会把"没变化"当成"点到了但没反应"反复重发。
                out = {'action': act, 'point': [x, y], 'diff': ret.get('diff')}
                if getattr(self, '_unit_notes', None):
                    out_hint = ((out_hint + ' ') if out_hint else '') + ' '.join(self._unit_notes)
                    self._unit_notes = []
                if out_hint:
                    out['zone_hint'] = out_hint
                if self._share_trap(x, y):
                    self._trap_note(x, y)
                if target_info:
                    out['target'] = self._target_view(target_info)
                if target_miss:
                    out['target_miss'] = target_miss          # 文字没找到, 这段坐标是兜底
                for k in ('verified', 'uncertain', 'hint', 'fg', 'screen', 'rot', 'orientation', 'orientation_changed'):
                    if ret.get(k) is not None:
                        out[k] = ret[k]
            elif act == 'swipe':
                x1, y1 = self._resolve_point(args, 'point1', 'rel1')
                x2, y2 = self._resolve_point(args, 'point2', 'rel2')
                ret = droid.swipe(x1, y1, x2, y2, int(args.get('ms') or 300))
                out = {'action': act, 'diff': ret.get('diff')}
                for k in ('verified', 'uncertain', 'hint', 'fg', 'screen', 'rot', 'orientation', 'orientation_changed'):
                    if ret.get(k) is not None:
                        out[k] = ret[k]
            elif act == 'text':
                val = str(args.get('value') or '')
                if not val:
                    return StepOutcome('[Error] text needs value (the content to type)', next_prompt='\n')
                # point/rel = 输入框中心(可选): 敏感 App 的 GUI 粘贴要长按输入框唤出菜单,
                # 由模型直接给比让它猜"最近点过哪儿"稳。给了就传, 没给交给 droid 用手势落点兜底。
                anchor = None
                target_info = None
                if args.get('target'):
                    try:
                        info = self._resolve_action_target(args)
                        if info:
                            ax, ay, target_info = info
                            anchor = (ax, ay)
                        else:              # 同时给了位置: 位置优先, target 只当标注
                            anchor = self._resolve_point(args, 'point', 'rel')
                    except Exception as e:
                        # 显式给了 target 就说明模型认为这个输入框位置很关键; 静默换成"最近落点"
                        # 会把定位失败伪装成一次成功粘贴。
                        return StepOutcome('[Error] gui_act text target failed: %s: %s'
                                           % (type(e).__name__, e), next_prompt='\n')
                elif (args.get('point') is not None or args.get('rel') is not None
                      or args.get('img_point') is not None):
                    try: anchor = self._resolve_point(args, 'point', 'rel')
                    except Exception: anchor = None
                ret = droid.paste(val, point=anchor) if anchor is not None else droid.paste(val)
                out = {'action': act, 'hit': ret.get('hit'), 'uncertain': ret.get('uncertain')}
                if target_info:
                    out['target'] = self._target_view(target_info)
                # 敏感 App(微信等): 文本经剪贴板 + 自动 GUI 粘贴落屏。hit=true 才是真上屏;
                # needs_gui_paste/hint 必须原样带回, 否则模型只看到 hit=false/uncertain,
                # 会误判“输入失败”并重复点搜索框。
                for k in ('needs_gui_paste', 'hint', 'ime_hint', 'ime_label',
                          'verify', 'paste_via', 'text', 'steps', 'replace_unverified'):
                    if ret.get(k) is not None:
                        out[k] = ret[k]
            elif act == 'key':
                droid.key(str(args.get('value') or 'ENTER'))
                out = {'action': act}
            elif act == 'launch':
                ret = droid.launch(str(args.get('value') or ''))
                out = {'action': act, 'fg': ret.get('fg')}
                # fg_ok/frame_fresh 也要一起转发: 前者是"拉起是否真的到了目标包"的唯一判据
                # (没有它, 上层只能拿 fg 的非空与否当成功), 后者说明这一帧是不是拉起后新截的。
                for k in ('screen', 'rot', 'orientation', 'fullscreen', 'shell', 'policy', 'hint',
                          'fg_ok', 'frame_fresh'):
                    # fullscreen/shell/hint 必须一起转发: Kotlin 在两条 shell 通道都不可用时**故意**
                    # 回一份自解释的降级载荷(fullscreen:false + 两条通道真值 + 怎么修)。丢掉它,
                    # stepOS 把第三方 uid 的启动改写成小窗, 而 ping() 仍报整屏几何——于是后续所有
                    # 相对坐标全部落在小窗之外, agent 既不知道原因, 也没法告诉用户怎么修。
                    if ret.get(k) is not None:
                        out[k] = ret[k]
            elif act == 'close':
                # 关掉当前弹层(弹窗/抽屉/分享面板): 只在**弹层自己的范围**里找关闭控件。
                # 模型没法知道 canvas 弹窗里那个 × 在哪(OCR 读不出文字), 与其让它猜坐标
                # —— 真机 10:06 猜成标题栏右角, 一点就把分享面板打开了 —— 不如让它只说要关。
                res = droid.close_dialog(bbox=self._last_bbox,
                                          expect_text=self._close_expect_text(args))
                out = {'action': act, 'via': res.get('via'), 'diff': res.get('diff')}
                for k in ('ok', 'text', 'point', 'hint'):
                    if res.get(k) not in (None, ''):
                        out[k] = res[k]
                if res.get('tried'):
                    out['tried'] = res['tried']
                if 'still_there' in res:
                    # 关完再 OCR 一次的结果: 关键字还在屏上 = 没关上。此前这个字段在 handler 里
                    # 被丢掉了(droid 算出来也没人看见), 模型拿不到"其实没关掉"的事实。
                    out['still_there'] = res['still_there']
            elif act == 'exit_miniapp':
                # 离开整个小程序: canvas 页吃系统返回键, 唯一出口是小程序总控胶囊右侧那个键。
                # 只点右边(关闭), 绝不点左边(分享/更多) —— 真机 10:06/10:26/10:52 三次都点开分享。
                res = droid.exit_miniapp()
                out = {'action': act, 'via': res.get('via'), 'diff': res.get('diff'),
                       'point': res.get('point')}
                for k in ('ok', 'hint'):
                    if res.get(k) not in (None, ''):
                        out[k] = res[k]
                if res.get('more'):
                    out['more'] = res['more']
                if not res.get('ok'):
                    out['hint'] = ((out.get('hint') or '') +
                                   ' 胶囊右侧的关闭键没把小程序关掉: 先用 observe 看清当前在哪一层, '
                                   '页内弹层用 action=close, 回上一级用 action=back。').strip()
            elif act == 'back':
                # back 在自绘 canvas/小程序/H5 页面上没有响应(系统返回键被页面吃掉), 这类页面
                # 的唯一出口是屏幕上的「返回/关闭/×」按钮。所以 back 先在当帧里找那个按钮点它,
                # 点不到才按系统返回 —— 否则模型想回上一级时只能在原地瞎点(真机 2026-10-30 09:15)。
                # target/expect 里写了「弹窗/弹层/对话框/窗口」= 这是弹层, 不是整页:
                # 关不掉时不许按系统返回(在自绘小程序里那会把整个小程序退掉)。
                _layer = any(w in (str(args.get('target') or '') + str(args.get('expect') or ''))
                             for w in ('弹窗', '弹层', '对话框', '窗口'))
                res = droid.ui_back(allow_system=not _layer)
                out = {'action': act, 'via': res.get('via'), 'diff': res.get('diff')}
                for k in ('ok', 'text', 'point', 'hint'):
                    if res.get(k) not in (None, ''):
                        out[k] = res[k]
                if res.get('tried'):
                    out['tried'] = res['tried']
                if not res.get('ok'):
                    out['hint'] = ((out.get('hint') or '') +
                                   ' 屏上没找到可点的返回/关闭按钮, 系统返回也没让画面变化: '
                                   '看看有没有弹窗/浮层需要先关掉, 或用 target="返回"/"关闭" 指名点。').strip()
            elif act == 'home':
                droid.home()
                out = {'action': act}
            else:
                sec = min(float(args.get('seconds') or 2), 30)
                st = droid.wait_stable(max_wait=sec)
                out = {'action': act, 'stable': st.get('stable'), 'waited_s': round(st.get('waited_s', 0), 2)}
        except (SoftFail, SoftMiss) as e:
            # 见 SoftFail 的说明: 参数/命中类失败回"带现场事实的普通结果", 不是 [Error]。
            # 模型能在同一轮按 near / unit 提示改对, 不必先读一遍红字再重来一轮(5.0-5.6s)。
            body = {'ok': False, 'action': act, 'soft': True}
            body.update(getattr(e, 'payload', None) or {})
            body.setdefault('hint', str(e))
            try:
                return StepOutcome(json.dumps(body, ensure_ascii=False, default=json_default),
                                   next_prompt=self._get_anchor_prompt(skip=True))
            except Exception:
                return StepOutcome(str(body), next_prompt='\n')
        except Exception as e:
            return StepOutcome('[Error] gui_act failed: %s: %s' % (type(e).__name__, e), next_prompt='\n')
        # 动作后自动等页面稳定(F1): 静态页几乎不花时间, 加载页不抢跑。
        # 但动作自带后验已经证明页面变了(diff 超带/hit/fg)时不再等: 消除类棋盘/视频/动画页
        # 永远等不到两帧 diff<=1.5%, 每步白睡满 max_wait——那等于把 d60f6be 想消掉的固定
        # action_sleep 又请回来, 只是从 5s 变成 3s 且换成隐式发生。
        # wait 动作自己就是等待, 不重复等。
        changed = bool(out.get('orientation_changed'))
        want_pkg = str(args.get('value') or '') if act == 'launch' else None
        proved = self._act_proved_change(act, out, want_pkg)
        pct = self._parse_diff_pct(out)
        # 大跳变(diff ≥ 30%)说明这一下触发了页面切换/转场: 此时"变了"不等于"停稳了"。旧口径只要
        # diff > 1.5% 就整段跳过等待, 模型拿到的就是过渡帧(真机 t21/t32 的 83.9%/77.6% 之后正是
        # 这种帧) → 照过渡帧算坐标 → 越点越偏。现在大跳变仍然等, 只是先让它跑完再判稳定。
        jump = pct is not None and pct >= self._TRANSITION_PCT
        if act != 'wait' and not changed and not proved:
            try:
                st = droid.wait_stable()
                out['stable'] = st.get('stable')
                if st.get('uncertain'):
                    out['stable_uncertain'] = True
            except Exception:
                pass
        self._last_bbox = self._diff_bbox(out) or getattr(self, '_last_bbox', None)
        if jump:
            # 不调 wait_stable(那会白睡满 3s, 也是 "skips redundant wait" 那条既有契约),
            # 但也不再复用 pending 帧: 大跳变说明页面正在切换, 那一刻的帧是过渡帧。等一小段
            # (截屏最小间隔量级)再重新截一张, 成本 0.35s, 换来模型看到的是到位后的画面。
            time.sleep(self._SETTLE_AFTER_JUMP_S)
        # 点空就地重试: diff≈0 时不再把整轮还给模型。真机最常见的白跑就是"同一坐标点 2~3 次,
        # 每次 diff 0.0xx%"(2026-10-30 09:15 三角洲: [601,2460] 点了 4 次, 每次白烧 5~6s)。
        # 两种救法都不需要模型参与: ① target 还有别的候选 → 换下一个; ② 坐标落在附图范围内
        # 而图比屏幕小 → 用换算后的设备像素再点一次。
        if act in ('tap', 'longpress') and not proved and pct is not None and pct < 0.2:
            try:
                self._retry_noop_action(act, args, out, target_info)
            except Exception:
                pass
        self._last_act_ok = bool(out.get('verified') is True or out.get('hit') is True
                                 or out.get('expect_verified') is True
                                 or (act == 'launch' and out.get('fg_ok'))
                                 # close/back 的 ok 是"这一层关掉了"的自身证据(diff 已核验),
                                 # 不收进来的话下面的收尾守卫会把已成功的关闭当成未验证动作
                                 or (act in ('close', 'back') and out.get('ok') is True))
        # C. 用画面指纹判断"真的在推进吗"。只看 diff 会被"开了又关"的 A/B 两帧骗过去
        # (三角洲那次每步 diff 85.850% 却一步没走), 指纹序列只有 ≤2 种值就是铁证。
        if act in ('tap', 'longpress', 'swipe', 'back', 'close', 'home', 'key', 'launch'):
            self._note_progress(out)
        # 动作后带回一份紧凑观测: 否则模型必须再花一整轮 code_run 去 dump()/look()
        # 才知道屏幕上现在有什么, "观察一轮→动作一轮"把每个动作的成本翻倍。
        # 真机实证: 39 轮任务里约 20 次是纯观察轮; 在供应商 p50 延迟 5~10s 的现状下,
        # 省一轮就是省 5~10s。观测封顶 12 项、标签截断, 比模型自己 print 全量节点小一个量级。
        # 旋转/折叠时 wait_stable 仍跳过(那是 16.3s/15.6s 后验的主要来源), 但必须给新画面的
        # 紧凑观测: 只给 screen/rot 不足以让弱模型继续——真机 3.7flash 看到横屏后直接放弃。
        if act in ('tap', 'swipe', 'longpress', 'back', 'home', 'key', 'launch'):
            if self._vision_covers_screen():
                # 视觉型页面(微信等): 本地只剩 YOLO 一条腿, 每步 1.5~2.6s; 而本轮已经把整张图
                # 发给主模型了, 再算一遍框是纯重复。留给模型自己看, 需要文字时它会用 look().
                if self._session_takes_images():
                    out['obs_note'] = ('当前屏幕截图已附在本轮消息里(visual-only 页面, 本地不再出框)。'
                                       '定位优先级: ① target="屏上看得见的文字" —— 我拿全分辨率截图做 '
                                       'OCR 定位, 你不用换算也不会偏; ② img_point=[x,y] —— 图上量的像素, '
                                       '我按 图→屏幕 比例换算; ③ rel(0-1000)。**别把图坐标填进 point**(那是'
                                       '设备像素, 填错会整体偏一半以上)。④ 要关掉这一层(弹窗/抽屉/'
                                       '分享面板)直接 gui_act {"action":"close"}, 不用给坐标。右上角那两个键是小程序的'
                                       '总控胶囊(左=分享/更多, 右=关闭/退出小程序), 非必要不要点: 要离开整个小程序'
                                       '用 action="exit_miniapp", 点它旁边只会打开分享面板。需要文字内容时用 '
                                       'code_run 的 look()/ocr')
                else:
                    # 这句以前无条件说"已附": 真机 25 轮里说了 8 次, 实际一帧都没发出去(会话是文本
                    # 协议), 于是模型既不换定位通道也不再质问画面, 只在 see/ocr 之间来回。话术必须与
                    # 事实同源 —— 由 _session_takes_images() 决定说不说。
                    out['obs_note'] = ('本会话收不到图片(文本协议), 这一屏没有图可看 —— 不要假设"已附图": '
                                       '定位用 see(want="point", roi=...) 或 gui_act 的 rel/obs; '
                                       '精确文字用 ocr; 中文输入用 text(必要时按 hint 补一次粘贴)。')
            else:
                try:
                    # 动作后验已经截过一帧: 交给 observe 复用。再截一次不但多 ~0.16s,
                    # 还会撞 Android 的截屏最小间隔(code=3)再白等 0.35s。
                    pending = getattr(droid, 'take_pending_frame', None)
                    if jump:
                        # 大跳变=页面正在切换: 复用的 pending 帧极可能是过渡帧 → 重新截一张
                        out['obs'] = self._compact_obs(droid.shot())
                        out['frame_after_jump'] = True
                    else:
                        out['obs'] = self._compact_obs(pending() if pending else None)
                except Exception:
                    pass
        # 通用动作后验: expect 只做正向确认, 未命中是软提示, 不是动作失败。
        # 把 expect 当硬判据会让"进入某页面"这类长句期望永远 false, 模型于是反复重试;
        # 每步还会多截一帧+OCR, 真机实测每个动作多 1.9-3.6s。
        expect = args.get('expect')
        if expect and act != 'wait':
            ok, seen = self._expect_seen(expect, out)
            out['expect'] = expect if isinstance(expect, str) else list(expect)
            out['expect_verified'] = ok
            out['expect_state'] = 'seen' if ok is True else ('unreadable' if ok is None else 'not_seen')
            if ok is True:
                out['verified'] = True
            elif ok is False:
                # 只提示，不覆盖 verified/uncertain：diff 和动作返回仍是一等证据。
                prev = out.get('hint')
                out['expect_soft'] = True
                out['hint'] = ('expect=%r 未在当前可读文字里命中 (软提示, 不是动作失败); '
                               '先看当前截图/obs 再决定, 不要只因此重试。' % (expect,))
                if prev:
                    out['hint'] = prev + ' | ' + out['hint']
        # 里程碑记账(必须在 expect 判完之后): 兑现的期望进 [DONE], 没兑现的进 [UNMET]。
        # 这是"每轮重注目标"的原料 —— 以前锚点里只有折叠过的历史, 没有"到底完成了哪几步"。
        if out.get('expect') and act != 'wait':
            # expect 的确认发生在动作之后: 它也是证据, 补进"这个动作生效了"的口径里
            if out.get('expect_verified') is True:
                self._last_act_ok = True
                self._done_steps = (getattr(self, '_done_steps', [])
                                    + [str(out['expect'])[:40]])[-6:]
                self._last_expect = None
            elif out.get('expect_verified') is False:
                self._last_expect = str(out['expect'])[:60]
        if act != 'wait':
            self._gui_actions = getattr(self, '_gui_actions', 0) + 1
            self._see_failed_digest = None   # 动作后允许对当前画面重新做一次视觉复核
            self._finish_prompted = False    # 新动作后的停止仍要先问一次 finish_task
            self._no_tool_retries = 0        # 动作推进后重置短回复重试预算
        if act in ('tap', 'longpress', 'swipe'):
            try:
                _ch = self._coord_space_hint(args, out)
                if _ch:
                    out['coord_hint'] = _ch
            except Exception:
                pass
        next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
        return StepOutcome(json.dumps(out, ensure_ascii=False), next_prompt=next_prompt)

    # 动作后观测的条目上限: 够模型选下一个目标, 又不把工具结果撑大(模型自己 print
    # 全量 look() 常常 2~5K 字符, 这里封顶后约 800)
    _OBS_ITEMS = 12
    _OBS_LABEL = 24
    _TRANSITION_PCT = 30.0        # diff ≥ 这个值 = 触发了页面切换/转场: "变了"不等于"停稳了"
    _SETTLE_AFTER_JUMP_S = 0.35   # 大跳变后到重截一张的等待(转场动画量级; 不调 wait_stable)
    _OBS_RESULT_ITEMS = 16

    # 每轮附图: 长边 1440 + q70 ≈ 1.4k image token(真机 1200x2670 原图直发太贵)
    _VISION_MAX_SIDE = 1440
    _VISION_QUALITY = 70

    def _vision_mode(self):
        """off/auto/always —— 每轮现读 kv, 用户改完立刻生效。"""
        try:
            import agent_settings
            return agent_settings.vision_in_turn()
        except Exception:
            return 'auto'

    def _vision_covers_screen(self):
        """这一屏的本地通道是不是"看不到结构"(视觉型 App / 前台未解析) → 交给图。"""
        if self._vision_mode() == 'off':
            return False
        try:
            import droid
            return bool(droid._sensitive_fg())
        except Exception:
            return False

    def _session_takes_images(self):
        """当前 LLM 会话能不能吃图块。

        口径来自能力位, 不来自类名拼写: 会话来声明 supports_images(BaseSession=False,
        NativeClaudeSession/NativeOAISession=True), 客户端来声明(NativeToolClient=True,
        ToolClient=False)。旧实现按类型名白名单猜, 把 NativeOAISession 误判成"文本协议"
        排除了 —— 它其实经 _msgs_claude2oai 能带图, 真机 25 轮里因此一帧图都没发出去。"""
        parent = getattr(self, 'parent', None)
        cli = getattr(parent, 'llmclient', None) if parent is not None else None
        backend = getattr(cli, 'backend', None) if cli is not None else None
        # 能力位优先: 客户端/会话自己声明能不能携带图片块(llmcore 的 supports_images)。
        # 上一版按类型名白名单猜, 把 NativeOAISession 当成"文本协议"排除了 —— 它其实经
        # _msgs_claude2oai 完全能带图。真机 25 轮因此一帧图都没发出去, 而 obs_note 还说了 8 次
        # "截图已附"。判定口径必须来自声明, 不能来自类名拼写。
        if cli is None:
            return True       # 探测不到会话: 放行(真机默认就是能带图的客户端), 别把"不知道"当"不能"
        cap = getattr(cli, 'supports_images', None)
        if cap is None:
            cap = getattr(backend, 'supports_images', None)
        if cap is None:   # 老对象/测试替身没有这一位: 退回类型名, 但补上 NativeOAISession
            return type(backend).__name__ in ('LLMSession', 'ClaudeSession', 'NativeClaudeSession',
                                              'NativeOAISession')
        return bool(cap)

    def turn_content_blocks(self):
        """给主模型这一轮消息附上"当前屏幕"图片块; 不需要时返回 None。

        为什么不每步调 see(): see() 是**独立请求**——实测均值 20.8s、最高 66.2s(今天 7 次),
        因为它要重付一次 prefill+TTFT。而主循环这一轮本来就要发, 多一张图只增加约 1.4k
        token 的 prefill(约 0.3~0.5s)。所以"全量看视觉"的正确形态是**把图放进这一轮**,
        不是每步多调一次视觉模型。see() 仍留给"这屏是什么意思"这类一次性提问。
        """
        mode = self._vision_mode()
        first = bool(getattr(self, '_task_frame_pending', False))
        # 每轮先清"这一轮的附图尺寸": 它决定 img_point 能不能换算、换算比例是多少。
        # 留着上一轮的尺寸比不留更糟 —— 会被当成这轮的像素基准。
        self._attached_img_wh = None
        self._attached_screen_wh = None
        if mode == 'off' or not self._session_takes_images():
            self._vision_in_turn_attached = False
            return None
        if mode == 'auto' and not first and not self._vision_covers_screen():
            # auto: 只在"本地通道看不到结构"的视觉型页面上附图; 但**任务第一步例外** ——
            # 开局必须知道现在到底在哪一屏(桌面? 微信? canvas 小程序?), 一帧图约 1.4k token。
            self._vision_in_turn_attached = False
            return None
        try:
            import droid
            b64, (w, h) = droid.shot_frame_b64(max_side=self._VISION_MAX_SIDE,
                                               quality=self._VISION_QUALITY)
            try:
                sw, sh = droid.screen()
            except Exception:
                sw, sh = (0, 0)
        except Exception as exc:
            self._vision_in_turn_attached = False
            return [{"type": "text", "text": "[当前屏幕截图不可用: %s]" % type(exc).__name__}]
        if first:
            # 只有真拿到这一帧才清标志 + 清旧图: 先清的话, shot 一抛错"第一步必附图"就静默
            # 失效, 而历史里的旧图已经剪掉了(不可回滚), 模型会拿上一任务的画面当现在。
            self._task_frame_pending = False
            self._drop_stale_frame_history()
        self._vision_in_turn_attached = True
        self._attached_img_wh = (int(w), int(h))
        self._attached_screen_wh = (int(sw), int(sh)) if sw and sh else None
        # 提示词必须写清"图"和"屏幕"是两个不同的像素基准: 真机 run 1793267115 的屏幕是
        # 1200x2670, 附图是 647x1440; 旧文案"坐标按这张图的像素给 point"让模型把图坐标当设备
        # 像素填进 point, 于是搜索之后每一步都点在偏左/偏上 1.855 倍的位置(y>1440 的下半屏
        # 根本点不到)。改成三个具名单位, 并明确"图坐标用 img_point, 我来换算"。
        head = ''
        if first:
            head = ('任务刚开始(第 1 步): 这是**此刻**的真实屏幕。上一个任务/上一轮的截图、坐标、'
                    '"已经打开了什么页面"的结论一律作废, 先按这张图判断现在在哪一屏。')
            try:
                _fg = str(droid.ping().get('pkg') or '')
            except Exception:
                _fg = ''
            if _fg:
                head += '当前前台: %s。' % _fg
        if sw and sh:
            note = head + ('当前屏幕截图（%dx%d，由 %dx%d 设备像素按长边缩放而来）。'
                    'gui_act 坐标三选一: img_point=[x,y] 用这张图上的像素(我按比例换算); '
                    'point=[x,y] 用设备像素(obs/ocr 的 x/y); rel=[rx,ry] 用 0-1000(see 的 rx/ry)。'
                    % (w, h, sw, sh))
        else:
            note = head + ('当前屏幕截图（%dx%d）。像素基准与设备屏幕不同: 图上位置请用 '
                    'img_point=[x,y](我换算), 设备像素用 point, 0-1000 用 rel。' % (w, h))
        return [
            {"type": "text", "text": note},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
        ]

    def _drop_stale_frame_history(self):
        """任务开始时把会话历史里的旧截图块摘掉。

        旧图留在历史里有两条害处: ① 模型会把上一任务的画面当成"现在"(真机 15:29 就是这样在
        桌面上找弹窗); ② 每张图约 1.4k token, 历史里堆十几张会把上下文吃光(真机日志见过
        1.5MB 的 prompt)。文字记录保留, 只清图块。

        解耦: 历史库和"图留几张"的策略都属于会话(llmcore.BaseSession), 这里只**请求**它清,
        不再自己去遍历改写 parent.history —— handler 不该知道消息体的形状, 也不该有第二份
        老化规则(那版漏了 image_url 块, 占位文字也和 IMAGE_PLACEHOLDER 不一致)。"""
        p = getattr(self, 'parent', None)
        drop = getattr(p, 'drop_stale_images', None)
        if not callable(drop):
            return 0
        try:
            n = int(drop() or 0)
        except Exception:
            return 0
        if n:
            print('[GA] 任务开始: 移除历史里 %d 张旧截图(避免把上一任务的画面当成现在)' % n)
        return n

    def _compact_obs(self, frame=None):
        """动作后的紧凑观测: [{t, src, label, cls, x, y, rx, ry, click}], 只留选目标必需的字段。

        路由在 droid.observe() 里(_classify 决定跑哪些通道), 这里只负责截断成模型看得动的
        条数。旧实现在这里分 dump/look 两路 + canvas 特判, 还要额外付一次 screen_kind() 的
        dump_state 往返; canvas 页现在直接由 observe 返回空, 不再白跑一次全屏 look。
        frame 给出则直接用它(动作后验帧), 不再截图。"""
        import droid
        try:
            res = droid.observe(img=frame) if frame is not None else droid.observe()
        except TypeError:
            res = droid.observe()          # 旧 droid 没有 img= 形参时的降级
        except Exception:
            return []
        return [self._obs_item_view(i, self._OBS_LABEL)
                for i in res['items'][:self._OBS_ITEMS]]

    @staticmethod
    def _act_proved_change(act, out, want_pkg=None):
        """动作自带后验是否已证明页面变了(此时再等页面稳定是纯浪费)。
        阈值用 phone_ledger.EVIDENCE_PCT(与账本同一口径): diff 超过它=产出新证据。
        ⚠️ tap/swipe 的 fg 只是"当前前台包名", 恒有——它不是变化证据。
        只有 launch 的 fg(目标包已在前台)才是。"""
        if act == 'launch':
            fg = out.get('fg') or ''
            # 只认"前台就是目标包": _wait_fg 超时返回的是最后一次前台(可能是桌面), 旧口径只判
            # fg 非空 → 拉起失败也算"已到位" → 跳过等待 → 拿拉起之前那一帧算坐标。这正是
            # "有时在拉起微信前就确定了位置"的来源。
            return (fg == want_pkg) if want_pkg else bool(fg)
        if out.get('hit') is True:
            return True
        pct = GenericAgentHandler._parse_diff_pct(out)
        return pct is not None and pct > phone_ledger.EVIDENCE_PCT

    def do_ask_user(self, args, response):
        question = args.get("question", "请提供输入：")
        candidates = args.get("candidates", [])
        result = ask_user(question, candidates)
        yield f"Waiting for your answer ...\n"
        return StepOutcome(result, next_prompt="", should_exit=True)
    
    def do_finish_task(self, args, response):
        """显式结束任务。只有这个工具能把"任务完成"与"模型停止输出"分开。

        设计口径:
        - `result` 是给用户的最终交付物, 由 agent_loop 直接展示(不要把它再塞进普通正文);
        - `evidence` 是本轮/本任务里已核验的证据(屏幕文字、工具返回、文件检查等);
        - `status=done` 且做过 GUI 动作时必须有 evidence, 否则拒绝——屏幕变了不等于任务完成;
        - `blocked` 用于登录/权限/风控等不可继续的人为边界, 也要写清原因。
        """
        status = str(args.get('status') or '').strip().lower()
        result = str(args.get('result') or '').strip()
        raw_evidence = args.get('evidence')
        if isinstance(raw_evidence, str):
            evidence = [raw_evidence.strip()] if raw_evidence.strip() else []
        elif isinstance(raw_evidence, (list, tuple)):
            evidence = [str(x).strip() for x in raw_evidence if str(x).strip()]
        else:
            evidence = []
        if status not in ('done', 'blocked', 'needs_user'):
            return StepOutcome('[Error] finish_task.status must be done/blocked/needs_user',
                               next_prompt=self._get_anchor_prompt())
        if not result:
            return StepOutcome('[Error] finish_task needs result: the final user-facing answer',
                               next_prompt=self._get_anchor_prompt())
        if status == 'done' and getattr(self, '_gui_actions', 0) and not evidence:
            return StepOutcome('[Error] finish_task(done) needs evidence after GUI actions; '
                               'include the observed text/page or tool result that proves completion',
                               next_prompt=self._get_anchor_prompt())
        self._task_finished = True
        # agent_loop 会对 finish_task 的结果做专门的用户可见输出, 不把它当普通 tool_result。
        return StepOutcome({'status': status, 'result': result, 'evidence': evidence},
                           next_prompt=None, should_exit=True)

    def _obs_item_view(self, item, label_limit=24):
        """观测项 → 模型可读的紧凑项。所有观察工具共用, 防止各通道字段漂移。"""
        label = str(item.get('t') or item.get('desc') or item.get('cls') or '').strip()[:label_limit]
        return {'t': label, 'src': item.get('src'), 'label': label,
                'cls': str(item.get('cls') or '')[:16],
                'x': item.get('x'), 'y': item.get('y'),
                'rx': item.get('rx'), 'ry': item.get('ry'),
                'click': item.get('click')}

    def do_observe(self, args, response):
        """第一级本地观测: 一次截图 + 控件树/YOLO, 返回最多 N 个紧凑目标。

        这是 `print(droid.observe())` 的结构化替代。旧路径让模型在 code_run 里打印全量
        dict, 一次 8~12K 字符, 既撑上下文又难读; 这里只保留选目标必需字段。
        """
        import droid
        try:
            limit = int(args.get('limit') or self._OBS_RESULT_ITEMS)
        except (TypeError, ValueError):
            return StepOutcome('[Error] observe.limit must be an int', next_prompt='\n')
        limit = max(1, min(limit, 40))
        try:
            res = droid.observe(roi=args.get('roi')) if args.get('roi') else droid.observe()
        except Exception as e:
            return StepOutcome(json.dumps({
                'ok': False, 'reason': 'observe_failed',
                'error': '%s: %s' % (type(e).__name__, str(e)[:180]),
                'hint': '本地观测失败; 不要反复重试。若是 canvas/自绘页, 用 see(want="point"/"text", roi=...)。'
            }, ensure_ascii=False), next_prompt='\n')
        items = [self._obs_item_view(i) for i in (res.get('items') or [])[:limit]]
        out = {'ok': True, 'source': 'local', 'kind': res.get('kind'),
               'items': items, 'notes': list(res.get('notes') or []),
               'needs_vision': bool(res.get('needs_vision')),
               'ms': res.get('ms')}
        # 只读观察入账(以前账本只记动作): 同一屏反复 observe 也是空转, 而且 observe 是这三条
        # 观察通道里最便宜的一条, 连着问两遍通常说明模型不知道该干什么了。
        try:
            _dg = hash(tuple((i.get('x'), i.get('y'), str(i.get('t') or '')[:16]) for i in items))
        except Exception:
            _dg = None
        _obs_hint = phone_ledger.ACTIVE.note_observation('observe', _dg, 'observe(%d 项)' % len(items))
        if _obs_hint:
            out['obs_guard'] = _obs_hint
        if not items:
            out['hint'] = ('本地没有可用框; 只有需要定位/理解画面时才用 '
                           'see(want="point"/"text", roi=...), 不要反复 observe。')
        elif res.get('needs_vision'):
            out['hint'] = ('本地框不足; 先从 items 里选目标; 确需定位再用 '
                           'see(want="point", roi=...)。')
        return StepOutcome(json.dumps(out, ensure_ascii=False),
                           next_prompt=self._get_anchor_prompt(skip=args.get('_index', 0) > 0))

    def do_ocr(self, args, response):
        """第一级 OCR: 只返回 {text, x, y, rx, ry, conf}, 不把 numpy 数组 repr 塞给模型。"""
        import droid
        import numpy as np
        try:
            limit = int(args.get('limit') or 24)
        except (TypeError, ValueError):
            return StepOutcome('[Error] ocr.limit must be an int', next_prompt='\n')
        try:
            min_conf = float(args.get('min_conf') or 0.0)
        except (TypeError, ValueError):
            return StepOutcome('[Error] ocr.min_conf must be a number', next_prompt='\n')
        t0 = time.time()
        try:
            img = droid.shot()
            H, W = img.shape[:2]
            # 同屏去重 + 入账: do_ocr 以前既无缓存也无次数上限(see 有四道闸), 于是"该看图"时
            # 模型会在 ocr 里反复兜圈子, 而且只读观察不进账本 → 循环守卫看不见。
            try:
                _dg = (hash(img[int(H * 0.04):, :].tobytes()), str(args.get('roi') or ''),
                       str(args.get('min_conf') or ''))
            except Exception:
                _dg = None
            _ocr_hint = phone_ledger.ACTIVE.note_observation('ocr', _dg, str(args.get('roi') or '全屏'))
            if _ocr_hint and not args.get('force'):
                return StepOutcome(json.dumps({'ok': False, 'reason': 'repeated_observation',
                                               'hint': _ocr_hint}, ensure_ascii=False),
                                   next_prompt=chr(10))
            roi = args.get('roi')
            if roi:
                box = droid._resolve_roi(roi)
                x1n, y1n, x2n, y2n = box
                px1, py1 = int(x1n / 1000.0 * W), int(y1n / 1000.0 * H)
                px2, py2 = int(x2n / 1000.0 * W), int(y2n / 1000.0 * H)
                crop = img[py1:py2, px1:px2]
            else:
                px1 = py1 = 0
                crop = img
            raw = droid.ocr(crop)
        except Exception as e:
            return StepOutcome(json.dumps({
                'ok': False, 'reason': 'ocr_failed',
                'error': '%s: %s' % (type(e).__name__, str(e)[:180]),
                'hint': 'OCR 失败; 不要反复重试。需要语义理解再用 see。'
            }, ensure_ascii=False), next_prompt='\n')
        items = []
        for box, text, score in raw or []:
            try:
                pts = np.asarray(box)
                lx1, ly1 = int(pts[:, 0].min()), int(pts[:, 1].min())
                lx2, ly2 = int(pts[:, 0].max()), int(pts[:, 1].max())
                gx, gy = px1 + (lx1 + lx2) // 2, py1 + (ly1 + ly2) // 2
                rx, ry = geom.to_norm(gx, gy, W, H)
                text = str(text).strip()
                if text and float(score) >= min_conf:
                    items.append({'text': text, 'x': gx, 'y': gy, 'rx': rx, 'ry': ry,
                                  'bbox': [px1 + lx1, py1 + ly1, px1 + lx2, py1 + ly2],
                                  'conf': round(float(score), 3)})
            except Exception:
                continue
        items.sort(key=lambda z: (z['y'], z['x']))
        items = items[:max(1, min(limit, 80))]
        return StepOutcome(json.dumps({'ok': True, 'source': 'ocr', 'items': items,
                                       'ms': round((time.time() - t0) * 1000, 1)},
                                      ensure_ascii=False),
                           next_prompt=self._get_anchor_prompt(skip=args.get('_index', 0) > 0))

    def do_file_patch(self, args, response):
        path = self._get_abs_path(args.get("path", ""))
        yield f"[Action] Patching file: {path}\n"
        old_content = args.get("old_content", "")
        new_content = args.get("new_content", "")
        try: new_content = expand_file_refs(new_content, base_dir=self.cwd)
        except ValueError as e:
            yield f"[Status] ❌ 引用展开失败: {e}\n"
            return StepOutcome({"status": "error", "msg": str(e)}, next_prompt="\n")
        result = file_patch(path, old_content, new_content)
        yield f"\n{str(result)}\n"
        next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
        return StepOutcome(result, next_prompt=next_prompt)
    
    def do_file_write(self, args, response):
        '''用于对整个文件的大量处理，精细修改要用file_patch。
        需要将要写入的内容放在<file_content>标签内，或者放在代码块中'''
        path = self._get_abs_path(args.get("path", ""))
        mode = args.get("mode", "overwrite")  # overwrite/append/prepend
        action_str = {"prepend": "Prepending to", "append": "Appending to"}.get(mode, "Overwriting")
        yield f"[Action] {action_str} file: {os.path.basename(path)}\n"

        def extract_robust_content(text):
            tags = re.findall(r"<file_content[^>]*>(.*?)</file_content>", text, re.DOTALL)
            if tags: return tags[-1].strip()
            blocks = re.findall(r"```[^\n]*\n([\s\S]*?)```", text)
            if blocks: return blocks[-1].strip()
            return None
        
        content = args.get('content') or extract_robust_content(response.content)
        if not content:
            yield f"[Status] ❌ 失败: 未在回复中找到<file_content>代码块内容\n"
            return StepOutcome({"status": "error", "msg": "No content found. Blank is not supported. Put content inside <file_content>...</file_content> tags in your reply body before call file_write."}, next_prompt="\n")
        try:
            new_content = expand_file_refs(content, base_dir=self.cwd)
            if mode == "prepend":
                old = open(path, 'r', encoding="utf-8").read() if os.path.exists(path) else ""
                open(path, 'w', encoding="utf-8").write(new_content + old)
            else:
                with open(path, 'a' if mode == "append" else 'w', encoding="utf-8") as f: f.write(new_content)
            yield f"[Status] ✅ {mode.capitalize()} 成功 ({len(new_content)} bytes)\n"
            next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
            return StepOutcome({"status": "success", 'writed_bytes': len(new_content)}, next_prompt=next_prompt)
        except Exception as e:
            yield f"[Status] ❌ 写入异常: {str(e)}\n"
            return StepOutcome({"status": "error", "msg": str(e)}, next_prompt="\n")
        
    def do_file_read(self, args, response):
        '''读取文件内容。从第start行开始读取。如有keyword则返回第一个keyword(忽略大小写)周边内容'''
        path = self._get_abs_path(args.get("path", ""))
        yield f"\n[Action] Reading file: {path}\n"
        start = args.get("start", 1)
        # 通用上下文约束: 记忆/SOP 文件通常很长, 默认只取一屏; 需要更多时显式传 count。
        default_count = 60 if ('memory' in path or 'sop' in path) else 200
        count = args.get("count", default_count)
        keyword = args.get("keyword")
        show_linenos = args.get("show_linenos", True)
        result = file_read(path, start=start, keyword=keyword,
                           count=count, show_linenos=show_linenos)
        if show_linenos and not result.startswith("Error:"): result = '由于设置了show_linenos，以下返回信息为：(行号|)内容 。\n' + result 
        if ' ... [TRUNCATED]' in result: result += '\n\n（某些行被截断，如需完整内容可改用 code_run 读取）'
        maxlen = 10000 // args.get('_tool_num', 1)
        result = smart_format(result, max_str_len=maxlen, omit_str='\n\n[omitted long content]\n\n')
        next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
        log_memory_access(path)
        if ('memory' in path or 'sop' in path) and not getattr(self, '_memory_tip_shown', False):
            # 同一任务只提示一次; 每次 file_read 都追加会变成上下文噪音。
            self._memory_tip_shown = True
            next_prompt += ("\n[SYSTEM TIPS] 正在读取记忆或SOP文件，若决定按sop执行请提取关键点"
                            "（特别是靠后的）update working memory；默认只返回前80行，"
                            "需要后续段落请带 start/count 或 keyword。")
        return StepOutcome(result, next_prompt=next_prompt)
    
    def _in_plan_mode(self): return self.working.get('in_plan_mode')
    def _exit_plan_mode(self): self.working.pop('in_plan_mode', None)
    def enter_plan_mode(self, plan_path): 
        self.working['in_plan_mode'] = plan_path; self.max_turns = 100
        self.print(f"[Info] Entered plan mode with plan file: {plan_path}")
        return plan_path
    def _check_plan_completion(self):
        if not os.path.isfile(p:=self._in_plan_mode() or ''): return None
        try: return len(re.findall(r'\[ \]', open(p, encoding='utf-8', errors='replace').read()))
        except: return None
    
    def do_update_working_checkpoint(self, args, response):
        '''为整个任务设定后续需要临时记忆的重点。'''
        key_info = args.get("key_info", "")
        related_sop = args.get("related_sop", "")
        if "key_info" in args: self.working['key_info'] = key_info
        if "related_sop" in args: self.working['related_sop'] = related_sop
        self.working['passed_sessions'] = 0
        yield f"[Info] Updated key_info and related_sop.\n"
        next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
        #next_prompt += '\n[SYSTEM TIPS] 此函数一般在任务开始或中间时调用，如果任务已成功完成应该是start_long_term_update用于结算长期记忆。\n'
        return StepOutcome({"result": "working key_info updated"}, next_prompt=next_prompt)

    def _retry_or_exit(self, prompt):
        self._empty_ct = getattr(self, '_empty_ct', 0) + 1
        if self._empty_ct >= 3: return StepOutcome({}, should_exit=True)
        return StepOutcome({}, next_prompt=prompt)

    def do_no_tool(self, args, response):
        '''这是一个特殊工具，由引擎自主调用，不要包含在TOOLS_SCHEMA里。
        当模型在一轮中未显式调用任何工具时，由引擎自动触发。
        二次确认仅在回复几乎只包含<thinking>/<summary>和一段大代码块时触发。'''
        content = getattr(response, 'content', '') or ""
        thinking = getattr(response, 'thinking', '') or ""
        if not response or (not content.strip() and not thinking.strip()):
            yield "[Warn] LLM returned an empty response. Retrying...\n"
            return self._retry_or_exit("[System] Blank response, regenerate and tooluse")
        if '[!!! 流异常中断' in content[-100:] or '!!!Error:' in content[-100:]:
            return self._retry_or_exit("[System] Incomplete response. Regenerate and tooluse.")
        if 'max_tokens !!!]' in content[-100:]:
            return self._retry_or_exit("[System] max_tokens limit reached. Use multi small steps to do it.")

        # 通用完成契约: 控制/工具标签被当正文输出, 或只输出"下一步/我准备..."时,
        # 不是任务完成。旧逻辑把它们直接当作 CURRENT_TASK_DONE, 真机已出现两次。
        visible = _visible_reply_text(content)
        if _has_unparsed_control(content):
            yield "[Warn] Detected control/tool markup without an actual tool call.\n"
            return StepOutcome({}, next_prompt=(
                "[System] 你刚才把控制标签/工具XML写进了回复正文, 但没有真正调用工具。"
                "请用实际 tool_call 调用对应工具; 如果已有最终结果, 调用 finish_task(status, result, evidence)。"))
        if getattr(self, '_gui_actions', 0) and not visible:
            yield "[Warn] GUI task ended without a user-facing result.\n"
            return StepOutcome({}, next_prompt=(
                "[System] 当前任务已经执行过 GUI 动作, 但本轮没有给用户最终结果。"
                "继续执行, 或调用 finish_task(status='done'|'blocked', result=..., evidence=[...])。"))
        # 有实际动作却直接输出普通正文: 先给一次显式 finish_task 的机会。这不是为了多一轮,
        # 而是把"模型停止输出"和"任务已完成"分开; 第二次仍不调用则允许结束, 避免死循环。
        if getattr(self, '_gui_actions', 0) and not getattr(self, '_task_finished', False) \
                and not getattr(self, '_finish_prompted', False):
            self._finish_prompted = True
            yield "[Warn] GUI task ended without finish_task.\n"
            return StepOutcome({}, next_prompt=(
                "[System] 你已经做过 GUI 动作, 但本轮没有调用 finish_task。"
                "若任务已完成, 调用 finish_task(status='done', result=<完整最终答案>, evidence=[...]); "
                "若被登录/权限/风控阻塞, 用 status='blocked' 并写清原因; 否则继续执行。"))
        # 最后一层兜底: 有 GUI 动作、没 finish_task、上一个动作也没被后验证明生效 —— 这时任何
        # "看起来说完了"的文本都不是交付。真机 t33 只发了一段"多次点击套牌按钮失败"的 checkpoint
        # 文本, agent_loop 见 next_prompt 为空就 CURRENT_TASK_DONE, 用户什么都没收到。只强制问一轮。
        if self._needs_explicit_finish():
            self._silent_exit_warned = True
            yield "[Warn] Refusing silent exit: finish_task or ask_user first." + chr(10)
            _why = ("上一步 GUI 动作没有被验证生效(没有 hit / expect_verified / fg_ok)"
                    if not getattr(self, '_last_act_ok', True) else
                    "你这一轮只写了文字, 没有把结果交付出去")
            return StepOutcome({}, next_prompt=(
                "[System] " + _why + ", 而你正准备结束 —— 用户会收到空结果。"
                "二选一: (a) 已经拿到答案 → finish_task(status='done', result=<完整最终答案>, "
                "evidence=[...]); (b) 还没拿到 → finish_task(status='blocked', "
                "result=<做到哪一步、卡在哪>, evidence=[...]) 或 ask_user 说明需要什么。"))
        if getattr(self, '_gui_actions', 0) and _INCOMPLETE_RE.search(visible):
            self._no_tool_retries = getattr(self, '_no_tool_retries', 0) + 1
            yield "[Warn] Detected progress/plan text, not a finished task.\n"
            return StepOutcome({}, next_prompt=(
                "[System] 你只是在描述计划/下一步, 没有完成交付。继续执行; "
                "若已经得到最终结果, 必须调用 finish_task(status, result, evidence)。"
                "不要把‘需要点击/接下来/我将’当成任务完成。"))
        if getattr(self, '_gui_actions', 0) and not getattr(self, '_task_finished', False) \
                and getattr(self, '_no_tool_retries', 0) < 2 and len(visible) < 12:
            # 极短且没有结论的停止(如只输出"ok")也先问一次; 正常结果/纯聊天不会走到这里,
            # 因为只在有 GUI 动作且任务未显式 finish 时触发。
            self._no_tool_retries = getattr(self, '_no_tool_retries', 0) + 1
            return StepOutcome({}, next_prompt=(
                "[System] 若有最终结果, 请直接给出完整答案并调用 "
                "finish_task(status='done'|'blocked', result=..., evidence=[...])。"))

        if self._in_plan_mode() and any(kw in content for kw in ['任务完成', '全部完成', '已完成所有', '🏁']):
            if 'VERDICT' not in content and '[VERIFY]' not in content and '验证subagent' not in content:
                yield "[Warn] Plan模式完成声明拦截。\n"
                return StepOutcome({}, next_prompt="⛔ [验证拦截] 检测到你在plan模式下声称完成，但未执行[VERIFY]验证步骤。请先按plan_sop §四执行验证（实际工具调用取证），获得VERDICT后才能声称完成。")
            
        # 2. 检测"包含较大代码块但未调用工具"的情况
        # 关键特征：恰好1个大代码块 + 代码块直接结尾（后面只有空白）
        code_block_pattern = r"```[a-zA-Z0-9_]*\n[\s\S]{50,}?```"
        blocks = re.findall(code_block_pattern, content)
        if len(blocks) == 1:
            m = re.search(code_block_pattern, content)
            after_block = content[m.end():]
            if not after_block.strip():
                residual = content.replace(m.group(0), "")
                residual = re.sub(r"<thinking>[\s\S]*?</thinking>", "", residual, flags=re.IGNORECASE)
                residual = re.sub(r"<summary>[\s\S]*?</summary>", "", residual, flags=re.IGNORECASE)
                clean_residual = re.sub(r"\s+", "", residual)
                if len(clean_residual) <= 30:
                    yield "[Info] Detected large code block without tool call and no extra natural language. Requesting clarification.\n"
                    next_prompt = (
                        "[System] 检测到你在上一轮回复中主要内容是较大代码块，且本轮未调用任何工具。\n"
                        "如果这些代码需要执行、写入文件或进一步分析，请重新组织回复并显式调用相应工具"
                        "（例如：code_run、file_write、file_patch 等）；\n"
                        "如果只是向用户展示或讲解代码片段，请在回复中补充自然语言说明，"
                        "并明确是否还需要额外的实际操作。"
                    )
                    return StepOutcome({}, next_prompt=next_prompt)
                
        if self._in_plan_mode():
            remaining = self._check_plan_completion()
            if remaining == 0:
                self._exit_plan_mode(); yield "[Info] Plan完成：plan.md中0个[ ]残留，退出plan模式。\n"
        
        #yield "[Info] Final response to user.\n"
        return StepOutcome(response, next_prompt=None)
    
    def do_start_long_term_update(self, args, response):
        '''Agent觉得当前任务完成后有重要信息需要记忆时调用此工具。'''
        prompt = '''### [总结提炼经验] 既然你觉得当前任务有重要信息需要记忆，请提取最近一次任务中【事实验证成功且长期有效】的环境事实、用户偏好、重要步骤，更新记忆。
本工具是标记开启结算过程，若已在更新记忆过程或没有值得记忆的点，忽略本次调用。
**如果没有经验证的，未来能用上的信息，忽略本次调用！**
**只能提取行动验证成功的信息**：
- **环境事实**（路径/凭证/配置）→ `file_patch` 更新 L2，同步 L1
- **复杂任务经验**（关键坑点/前置条件/重要步骤）→ L3 精简 SOP（只记你被坑得多次重试的核心要点）
**禁止**：临时变量、具体推理过程、未验证信息、通用常识、你可以轻松复现的细节、只是做了但没有验证的信息
**操作**：严格遵循提供的L0的记忆更新SOP。本工具结果已附记忆库结构与 L1 现状——
**除非确知要改哪个文件，否则不要额外 `file_read` 去"看现有"**；直接判断类型 → 最小化
`file_patch` 更新 → 无新内容跳过，保证对记忆库最小局部修改。\n
''' + get_global_memory()
        yield "[Info] Start distilling good memory for long-term storage.\n"
        path = './memory/memory_management_sop.md'
        if os.path.exists(path): result = 'This is L0:\n' + file_read(path, show_linenos=False)
        else: result = "Memory Management SOP not found. Do not update memory."
        return StepOutcome(result, next_prompt=prompt)

    def _fold_earlier(self, lines):
        FALLBACK = '直接回答了用户问题'
        parts, cnt, last = [], 0, ''
        def flush():
            if cnt:
                if FALLBACK in last: parts.append(f'[Agent]（{cnt} turns）')
                else: parts.append(f'{last}（{cnt} turns）')
        for line in lines:
            if line.startswith('[USER]'):
                flush(); parts.append(line); cnt = 0; last = ''
            else: cnt += 1; last = line
        flush()
        return "\n".join(parts[-70:])

    def _needs_explicit_finish(self):
        """有 GUI 动作却没调过 finish_task: 不许静默退出。

        真机 t33 只输出了一段 checkpoint 文本("多次点击套牌按钮失败"), agent_loop 见 next_prompt
        为空就判 CURRENT_TASK_DONE —— 用户那边什么都没有。命中条件刻意收窄到"最后一个动作没有
        被验证": 干净的收尾仍走既有的"给一次 finish_task 机会"契约(test_agent_protocol_v2 锁着
        "第二次允许结束"防死循环), 这里只补上它管不到的那一半 —— 动作没生效却当成做完了。
        只强制问一次(_silent_exit_warned)。"""
        return (bool(getattr(self, '_gui_actions', 0))
                and not getattr(self, '_task_finished', False)
                and not getattr(self, '_last_act_ok', True)
                and not getattr(self, '_silent_exit_warned', False))

    _KB_TURNS = 2
    _KB_MAX_LINES = 24
    _KB_MAX_INJECT = 3          # 一个任务最多注入几次"任务相关卡"(开局 + pkg 变化)

    def _kb_block(self):
        """锚点里的知识块: 开局两轮给"入口索引 + 任务相关的知识卡", 之后只在 pkg 变化时补一次。

        为什么塞进锚点而不是让模型自己 file_read: 真机每个任务开头都先 file_read
        phone_use.md(318 行只给 60 行) + app_cards.md(133 行只给 60 行), 两条 ≈4s 且经常只拿到
        无关段落(2026-10-30 四段会话里 100% 复现); 而"微信里的小程序/朋友圈在哪"这类知识每次
        任务都要用。索引只留一屏(≈1.9KB), 细节仍指向 app_cards.md, 不复制正文, 两处不会漂移。

        两段内容:
          · `[KB] 常见入口索引` —— 固定的全应用索引(memory/app_index.md), 只在前 _KB_TURNS 轮给;
          · `[KB:卡片id] ...` —— `kb.search()` 按**任务原文 + 当前前台包名**检索出来的 1-3 张卡,
            带 `[待核]` 标记, 每任务最多 _KB_MAX_INJECT 次(开局一次 + 每次换 App 一次)。
            检索发生在模型说话之前, 所以不额外花一轮工具调用(每轮往返 5-6s)。
        """
        try:
            import agent_settings
            if agent_settings.kb_mode() == 'off':      # /kv.set ga.kbmode off 可热关
                return ''
        except Exception:
            pass
        try:
            turn = int(getattr(self, 'current_turn', 0) or 0)
        except (TypeError, ValueError):
            turn = 0
        parts = []
        if turn <= self._KB_TURNS:
            text = getattr(self, '_kb_text', None)
            if text is None:
                text = ''
                try:
                    path = os.path.join(script_dir, 'memory/app_index.md')
                    with open(path, 'r', encoding='utf-8', errors='replace') as f:
                        lines = [l.rstrip() for l in f if l.strip()]
                    body = [l for l in lines if not l.startswith('# ')]
                    text = chr(10).join(body[:self._KB_MAX_LINES])
                except Exception:
                    text = ''
                self._kb_text = text
            if text:
                parts.append('### [KB] 常见入口索引（先照这个走, 省一次 file_read; 细节见 ../memory/app_cards.md）'
                             + chr(10) + text)
        # 任务相关卡: 开局给, 换 App 再给; 同一张卡不重复注入
        try:
            hits = self._kb_cards()
        except Exception:
            hits = ''
        if hits:
            parts.append(hits)
        if not parts:
            return ''
        return chr(10) + chr(10).join(parts) + chr(10)

    def _kb_cards(self):
        """按任务原文 + 当前前台包名检索知识卡(每任务最多 _KB_MAX_INJECT 次)。"""
        import droid      # 本模块刻意不 import droid(设备无关), 一律函数内 lazy import
        import kb as _kb
        try:
            turn = int(getattr(self, 'current_turn', 0) or 0)
        except (TypeError, ValueError):
            turn = 0
        injected = getattr(self, '_kb_injected', None)
        if injected is None:
            injected = self._kb_injected = {'n': 0, 'ids': set(), 'pkg': ''}
        if injected['n'] >= self._KB_MAX_INJECT:
            return ''
        try:
            pkg = droid._fg()
        except Exception:
            pkg = ''
        fresh_pkg = bool(pkg) and pkg != injected['pkg']
        if turn > self._KB_TURNS and not fresh_pkg:
            return ''
        query = ' '.join(str(x) for x in (getattr(self, '_goal_text', ''),
                                          self._last_expect or '',
                                          (droid.entry_hint(pkg) if pkg else '')) if x)
        res = _kb.search(query, pkg=pkg, k=3)
        text = res.get('text') or ''
        if not text:
            return ''
        # 已经注入过的卡不重复: 先按行切成"每张卡一块", 再按卡片 id 过滤
        blocks, cur = [], []
        for line in text.split(chr(10)):
            if line.startswith('[KB:'):
                if cur:
                    blocks.append(cur)
                cur = [line]
            elif cur:
                cur.append(line)
        if cur:
            blocks.append(cur)
        keep = []
        for block in blocks:
            cid = block[0][4:].split(']')[0].split(' ')[0].strip()
            if cid and cid not in injected['ids']:
                keep.append(chr(10).join(block))
                injected['ids'].add(cid)
        if not keep:
            return ''
        injected['n'] += 1
        injected['pkg'] = pkg
        return chr(10).join(keep)

    def _goal_block(self):
        """每轮把"原始目标 / 已验证的里程碑 / 上次没兑现的期望"重注一遍(屏幕最前面)。

        以前锚点里的历史是折叠过的(<earlier_context> 每组只留一行), 一旦 working memory 里写下
        "去排行榜看", 原始目标"先点进牌组"就不再出现在上下文里 —— 子目标漂移是这么来的。
        [UNMET] 那一行是软提示: 只提醒别假设它已经发生, 不强制重试动作。"""
        goal = (getattr(self, '_goal_text', '') or '').replace(chr(10), ' ').strip()[:240]
        done = '; '.join(str(x) for x in getattr(self, '_done_steps', [])[-4:])
        unmet = getattr(self, '_last_expect', None)
        out = ''
        if goal:
            out += chr(10) + '### [GOAL] ' + goal + chr(10)
        if done:
            out += '[DONE] ' + done[:240] + chr(10)
        if unmet:
            out += ('[UNMET] 上次期望的 %r 没有出现: 不要当成已经发生, 先核实现画面。' % (unmet,)) + chr(10)
        return out

    def _get_anchor_prompt(self, skip=False):
        if skip: return "\n"
        h = self.history_info; W = 30
        earlier = f'<earlier_context>\n{self._fold_earlier(h[:-W])}\n</earlier_context>\n' if len(h) > W else ""
        h_str = "\n".join(h[-W:])
        prompt = self._goal_block() + self._kb_block() + f"\n### [WORKING MEMORY]\n{earlier}<history>\n{h_str}\n</history>"
        prompt += f"\nCurrent turn: {self.current_turn}\n"
        if self.working.get('key_info'): prompt += f"\n<key_info>{self.working.get('key_info')}</key_info>"
        if self.working.get('related_sop'): prompt += f"\n有不清晰的地方请再次读取{self.working.get('related_sop')}"
        if getattr(self, '_gui_actions', 0) and not getattr(self, '_task_finished', False):
            prompt += ("\n[FINISH] 有过实际 GUI 动作: 完成或确认阻塞时必须调用 "
                       "finish_task(status='done'|'blocked', result=..., evidence=[...]); "
                       "不要用‘下一步/需要点击/工具XML’作为结束。")
        if getattr(self.parent, 'verbose', False): self.print(prompt)
        return prompt
    
    def turn_end_callback(self, response, tool_calls, tool_results, turn, next_prompt, exit_reason):
        # 每轮前刷新登记的模型后端: 模型在任务间隙被换掉时(/llm 换的是整个 client 对象),
        # 视觉必须跟着换, 不能拿着上个 backend 继续打。
        try:
            import droid; droid.set_active_backend(self._vision_backend())
        except Exception: pass
        _c = re.sub(r'```.*?```|<thinking>.*?</thinking>', '', response.content, flags=re.DOTALL)
        rsumm = re.search(r"<summary>(.*?)</summary>", _c, re.DOTALL)
        if rsumm: summary = rsumm.group(1).strip()
        else:
            tc = tool_calls[0]; tool_name, args = tc['tool_name'], tc['args']   # at least one because no_tool
            clean_args = {k: v for k, v in args.items() if not k.startswith('_')}
            summary = f"调用工具{tool_name}, args: {clean_args}"
            if tool_name == 'no_tool': summary = "直接回答了用户问题"
            next_prompt += "\n\n\n[SYSTEM] 必须在回复文本中包含<summary>！\n\n"
            summary = smart_format(summary.replace('\n', ''), max_str_len=40)
        summary = smart_format(summary.replace('\n', ''), max_str_len=80)
        self.history_info.append(f'[Agent] {summary}')
        _plan = self._in_plan_mode()

        if turn % 75 == 0 and (not _plan):
            next_prompt += f"\n\n[DANGER] 已连续执行第 {turn} 轮。必须总结情况进行ask_user，不允许继续重试。"
        elif turn % 7 == 0:
            next_prompt += f"\n\n[DANGER] 已连续执行第 {turn} 轮。禁止无效重试。若无有效进展，必须切换策略：1. 探测物理边界 2. 请求用户协助。如有需要，可调用 update_working_checkpoint 保存关键上下文。"
        elif turn % 10 == 0: next_prompt += get_global_memory()

        _guard = phone_ledger.ACTIVE.hint()   # 循环守卫(SPEC W3 提示级): 动作等价/界面粘滞等机械信号; 无信号零注入
        if _guard: next_prompt += f"\n\n{_guard}\n"

        if _plan and turn >= 10 and turn % 5 == 0:
            next_prompt = f"[Plan Hint] 正在计划模式。必须 file_read({_plan}) 确认当前步骤，回复开头引用：📌 当前步骤：...\n\n" + next_prompt
        if _plan and turn >= 120: next_prompt += f"\n\n[DANGER] Plan模式已运行 {turn} 轮，已达上限。必须 ask_user 汇报进度并确认是否继续。"

        injkeyinfo = consume_file(self.parent.task_dir, '_keyinfo')
        injprompt = consume_file(self.parent.task_dir, '_intervene')
        if injkeyinfo: self.working['key_info'] = self.working.get('key_info', '') + f"\n[MASTER] {injkeyinfo}"
        if injprompt: next_prompt += f"\n\n[MASTER] {injprompt}\n"
        next_prompt += lang_directive()   # 每轮重注语言指令: 中途 /lang 切换即刻生效, 压过历史语言惯性
        for hook in list(getattr(self.parent, '_turn_end_hooks', {}).values()): hook(locals())  # current readonly
        return next_prompt

def lang_directive():
    """返回当前语言的 [LANG] 回复指令(实时读 GA_LANG, 用于压过历史语言惯性; 显式 /lang 切换永远优先)。
    GA_LANG 由 UI /lang(或首启 navigator.language)与系统 locale 决定。"""
    return ("\n[LANG] Respond to the user in English, regardless of the language of context or tool output (verbatim quotes excepted).\n"
            if os.environ.get('GA_LANG', '') == 'en'
            else "\n[LANG] 用简体中文回复用户，无论上下文或工具输出是什么语言（逐字引用原文除外）。\n")


def get_global_memory():
    prompt = "\n"
    try:
        suffix = '_en' if os.environ.get('GA_LANG', '') == 'en' else ''
        with open(os.path.join(script_dir, 'memory/global_mem_insight.txt'), 'r', encoding='utf-8', errors='replace') as f: insight = f.read()
        with open(os.path.join(script_dir, f'assets/insight_fixed_structure{suffix}.txt'), 'r', encoding='utf-8') as f: structure = f.read()
        prompt += f'cwd = {os.path.join(script_dir, "temp")} (./)\n'
        prompt += f"\n[Memory] (../memory)\n"
        prompt += structure + '\n../memory/global_mem_insight.txt:\n'
        prompt += insight + "\n"
    except FileNotFoundError: pass
    return prompt
