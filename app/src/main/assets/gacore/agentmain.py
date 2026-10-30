import os, sys, threading, queue, time, json, re, random, locale
os.environ.setdefault('GA_LANG', 'zh' if any(k in (locale.getlocale()[0] or '').lower() for k in ('zh', 'chinese')) else 'en')
if sys.stdout is None: sys.stdout = open(os.devnull, "w")
elif hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(errors='replace')
if sys.stderr is None: sys.stderr = open(os.devnull, "w")
elif hasattr(sys.stderr, 'reconfigure'): sys.stderr.reconfigure(errors='replace')
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from llmcore import reload_mykeys, ToolClient, MixinSession, NativeToolClient, NativeClaudeSession, NativeOAISession, resolve_client
from agent_loop import agent_runner_loop
try:
    from plugins.hooks import discover_and_load; discover_and_load()
except Exception: pass

def _track_agent_end(reason, turn):
    pass  # No telemetry transport in this distribution.

from ga_android import GenericAgentHandler, smart_format, get_global_memory, format_error, consume_file, lang_directive

script_dir = os.path.dirname(os.path.abspath(__file__))
def load_tool_schema(suffix=''):
    global TOOLS_SCHEMA
    TS = open(os.path.join(script_dir, f'assets/tools_schema{suffix}.json'), 'r', encoding='utf-8').read()
    TOOLS_SCHEMA = json.loads(TS if os.name == 'nt' else TS.replace('powershell', 'bash'))
load_tool_schema()

lang_suffix = '_en' if os.environ.get('GA_LANG', '') == 'en' else ''
mem_dir = os.path.join(script_dir, 'memory')
if not os.path.exists(mem_dir): os.makedirs(mem_dir)
mem_txt = os.path.join(mem_dir, 'global_mem.txt')
if not os.path.exists(mem_txt): open(mem_txt, 'w', encoding='utf-8').write('# [Global Memory - L2]\n')
mem_insight = os.path.join(mem_dir, 'global_mem_insight.txt')
if not os.path.exists(mem_insight):
    t = os.path.join(script_dir, f'assets/global_mem_insight_template{lang_suffix}.txt')
    open(mem_insight, 'w', encoding='utf-8').write(open(t, encoding='utf-8').read() if os.path.exists(t) else '')
else:
    # 存量设备 L1 迁移: L1 仅首装 seed 且随设备自演化漂移(措辞不定), 故 token 级修补。
    # 清理已删除 SOP 的死指针，并幂等补齐仍有效的 L3 能力索引。
    try:
        import re as _re
        _s = open(mem_insight, encoding='utf-8').read()
        _t = _s
        for _pat in (r'\s*\|\s*(?:weixin_clawbot_sop|lark_channel_sop)\([^)]*\)',
                     r'(?:weixin_clawbot_sop|lark_channel_sop)\([^)]*\)\s*(?:\|\s*)?'):
            _t = _re.sub(_pat, '', _t)
        for k, v in (('接飞书/接微信ClawBot', '接飞书·多维表格·飞书文档'), ('接飞书/接微信', '接飞书·多维表格·飞书文档'),
                     ('connect Lark bot / connect WeChat ClawBot', 'Lark-Feishu API, Base, Docs'),
                     # v2.23.1: phone_use 必读硬前置从 sys_prompt 移回 L1(中英对齐), 存量 L1 幂等补齐(新措辞不含旧串, replace 天然幂等)
                     ('手机GUI操作/截图/视觉: phone_use.md',
                      '手机GUI操作/截图/视觉: ⚠第一步必须先 file_read ../memory/phone_use.md(未读禁用droid; 内含工具选型/输入/滚动/防劫持红线)'),
                     ('Phone GUI ops/screenshot/vision: phone_use.md',
                      'Phone GUI ops/screenshot/vision: !! step 1 MUST be file_read ../memory/phone_use.md (droid forbidden until read; covers tool selection/input/scroll/anti-hijack red lines)')):
            _t = _t.replace(k, v)
        _lines = []
        for _l in _t.split('\n'):
            if _l.startswith('L3:'):
                if 'lark_sop(' not in _l:
                    _l += ' | lark_sop(飞书全接口: im/base/wiki/doc)'
                if 'notif_trigger_sop' not in _l:
                    _l += (' | notif_trigger_sop(notification trigger)' if lang_suffix == '_en'
                           else ' | notif_trigger_sop(通知触发)')
                if 'pc_use_sop' not in _l:   # GAnet(连电脑): 首装模板已含, 存量 L1 在此幂等补齐(否则老设备 GA 不知 PC SOP 存在)
                    _l += (' | pc_use_sop(connect and use the user\'s PC)' if lang_suffix == '_en'
                           else ' | pc_use_sop(连接和使用用户电脑)')
            _lines.append(_l)
        _t = '\n'.join(_lines)
        # GAnet 路由行(触发词→pc_use_sop): 与 L3 索引项配对, 缺则补在 [RULES] 之前(模板同位); 与模板逐字一致以便下次幂等
        _pc_route = ('Connect/use the user\'s PC (run commands / read files on the computer) -> read pc_use_sop; sole entry '
                     '`import ganet`, call device_tool_catalog() then call_device_tool(). Credentials are automatic '
                     '(never ssh/paramiko yourself, never ask the user for tokens/keys)' if lang_suffix == '_en' else
                     '连用户电脑/在电脑上执行命令/看电脑文件→读pc_use_sop; 唯一入口 import ganet，先 device_tool_catalog() 再 '
                     'call_device_tool()。凭据全自动(禁自己ssh/paramiko,禁向用户要token/私钥)')
        if 'pc_use_sop;' not in _t and 'pc_use_sop' in _t:
            _t = _t.replace('\n[RULES]', '\n' + _pc_route + '\n\n[RULES]', 1) if '\n[RULES]' in _t else _t.rstrip('\n') + '\n' + _pc_route + '\n'
        # r25: 「通道选择」「模式」两行整行同步到模板措辞(点名 App=已指定通道, 禁把「用顺丰速运查一下」当网页任务; 模式行枚举 快递/12306/闲鱼/大麦/会议)。
        # 标记串缺失才替换 → 幂等; 存量 L1 漏枚举时 bench 实测「用 X 查一下」三次都 T1 直开官网, 改 L3 SOP 无效, 只有 L1 生效。
        try:
            _tpl = open(os.path.join(script_dir, f'assets/global_mem_insight_template{lang_suffix}.txt'), encoding='utf-8').read().split('\n')
            _sync = ((('Channel choice:', 'named app'), ('Modes (', 'express delivery SF/Cainiao')) if lang_suffix == '_en'
                     else (('通道选择:', '点名 App'), ('模式(', '快递顺丰菜鸟')))
            # Upgrade only the built-in failure rule; preserve all user memory lines.
            _sync += ((('4. Close the loop:', 'diagnose a path') if lang_suffix == '_en'
                       else ('4. 闭环:', '先诊断')),)
            for _prefix, _marker in _sync:
                _new = next((x for x in _tpl if x.startswith(_prefix)), None)
                if _new:
                    _t = '\n'.join((_new if (x.startswith(_prefix) and _marker not in x) else x) for x in _t.split('\n'))
        except Exception: pass
        if _t != _s: open(mem_insight, 'w', encoding='utf-8').write(_t)
    except Exception: pass
cdp_cfg = os.path.join(script_dir, 'assets/tmwd_cdp_bridge/config.js')
if not os.path.exists(cdp_cfg):
    try:
        os.makedirs(os.path.dirname(cdp_cfg), exist_ok=True)
        open(cdp_cfg, 'w', encoding='utf-8').write(f"const TID = '__ljq_{hex(random.randint(0, 99999999))[2:8]}';")
    except Exception as e: print(f'[WARN] CDP config init failed: {e} — advanced web features (tmwebdriver) will be unavailable.')

def get_system_prompt():
    suffix = '_en' if os.environ.get('GA_LANG', '') == 'en' else ''   # 动态取语言变体: 原模块级 lang_suffix 冻结于 import → /lang 运行时切换不生效(中英输出 bug 根因); run() 每个新任务都重建系统提示词, 故此处现算即生效
    with open(os.path.join(script_dir, f'assets/sys_prompt{suffix}.txt'), 'r', encoding='utf-8') as f: prompt = f.read()
    prompt += f"\nToday: {time.strftime('%Y-%m-%d %a')}\n"
    prompt += get_global_memory()
    prompt += lang_directive()
    return prompt

# SDK:
# agent = GenericAgent(); threading.Thread(target=agent.run, daemon=True).start()
# output1_queue = agent.put_task(prompt1)
# output2_queue = agent.put_task(prompt2)
def _apply_session_attr(backend, k, v):
    """/session.<k>=<v> 的真正落地。返回 (是否生效, 备注)。

    两个真 bug 都是这里出去的:
    ① 裸 setattr 无保护: 聚合后端(MixinSession)的 model 是只读 @property, 赋它抛
       AttributeError; /session. 分支没有 try/except, 异常一路逃出 _handle_slash_cmd →
       GenericAgent.run() 的 while True → **该会话的 run 线程直接死掉, 再也不响应**。
       (下面 /llm 分支一直有 except AttributeError: pass 并注明原因, 这条分支漏了。)
    ② 只往壳上写: MixinSession.__setattr__ 只广播 _BROADCAST_ATTRS 那一组, 其余属性走
       object.__setattr__ 落到壳实例 __dict__, 之后 __getattr__ 永不被查询 → 成员保持旧值。
       于是 /session.thinking_type=enabled 对主链路和 vision 链路都无声失效
       (thinking_type 恰不在广播集合里, 而它正是 vision_llm 每次都要临时改的那个)。
    所以: 能写成员就写成员(并保留壳上的值供读取), 写不了就如实说写不了。"""
    # 只读派生属性(典型: MixinSession.model 是 @property, 值由当前成员决定)不能写。
    # 早先 /session.model= 就是踩这里: setattr 抛 AttributeError 且无保护, 一路逃出
    # run() 的 while True 把会话线程杀死。这里改成如实拒绝——与 /llm 分支对聚合后端的
    # 处理保持一致("型号由成员链决定, 覆盖无意义"), 而不是偷偷改写整个成员链。
    prop = getattr(type(backend), k, None)
    if isinstance(prop, property) and prop.fset is None:
        return False, '%s 是只读派生属性(由当前成员决定), 不能直接设置; 请用 /llm 切型号' % k
    target = getattr(backend, '_sessions', None)
    members = list(target) if isinstance(target, (list, tuple)) and target else [backend]
    try:
        for m in members:
            setattr(m, k, v)
    except AttributeError as e:
        return False, '%s 是只读或不存在(%s)' % (k, e)
    except Exception as e:
        return False, '%s: %s' % (type(e).__name__, e)
    # 壳上也留一份: MixinSession.__getattr__ 会把未知属性转发给 _sessions[0],
    # 不写壳则读取路径看到的是转发值, 与刚写入成员的值可能不一致。
    try:
        object.__setattr__(backend, k, v)
    except Exception:
        pass
    note = '' if len(members) == 1 else '（已同步到 %d 个成员）' % len(members)
    return True, note

class GenericAgent:
    def __init__(self):
        os.makedirs(os.path.join(script_dir, 'temp'), exist_ok=True)
        self.lock = threading.Lock()
        self.task_dir = None
        self.history = []; self.handler = None; 
        self.task_queue = queue.Queue() 
        self.is_running = False; self.stop_sig = False; self.llm_no = 0;  
        self.inc_out = False; self.verbose = True
        self.peer_hint = True
        self.force_non_stream = False
        logid = f'{(time.time_ns() + random.randrange(1_000_000)) % 1_000_000:06d}'
        self.log_path = os.path.join(script_dir, f'temp/model_responses/model_responses_{logid}.txt')
        self.load_llm_sessions()

    def load_llm_sessions(self):
        mykeys, changed = reload_mykeys()
        if not changed and hasattr(self, 'llmclients'): return
        try: oldhistory = self.llmclient.backend.history
        except: oldhistory = None
        llm_sessions = []
        for k, cfg in mykeys.items():
            if not any(x in k for x in ['api', 'config', 'cookie']): continue
            try:
                if 'mixin' in k: llm_sessions += [{'mixin_cfg': cfg}]
                elif c := resolve_client(k): llm_sessions += [c]
            except: pass
        for i, s in enumerate(llm_sessions):
            if isinstance(s, dict) and 'mixin_cfg' in s:
                try:
                    mixin = MixinSession(llm_sessions, s['mixin_cfg'])
                    if isinstance(mixin._sessions[0], (NativeClaudeSession, NativeOAISession)): llm_sessions[i] = NativeToolClient(mixin)
                    else: llm_sessions[i] = ToolClient(mixin)
                except Exception as e: print(f'\n\n\n[ERROR] Failed to init MixinSession with cfg {s["mixin_cfg"]}: {e}!!!\n\n')
        self.llmclients = llm_sessions
        if not llm_sessions: self.llmclient = None; return   # keyless: 空列表取模=除零崩构造; llmclient 悬空由调用侧 key 门兜住
        self.llmclient = self.llmclients[self.llm_no%len(self.llmclients)]
        if oldhistory: self.llmclient.backend.history = oldhistory
    
    def next_llm(self, n=-1):
        self.load_llm_sessions()
        self.llm_no = ((self.llm_no + 1) if n < 0 else n) % len(self.llmclients)
        lastc = self.llmclient
        self.llmclient = self.llmclients[self.llm_no]
        try: self.llmclient.backend.history = lastc.backend.history
        except: raise Exception('[ERROR] BAD Mixin config: Check your mykey.py')
        self.llmclient.last_tools = ''
        name = self.get_llm_name(model=True)
        if 'glm' in name or 'minimax' in name or 'kimi' in name: load_tool_schema('_cn')
        else: load_tool_schema()
    def list_llms(self): 
        self.load_llm_sessions()
        return [(i, self.get_llm_name(b), i == self.llm_no) for i, b in enumerate(self.llmclients)]
    def get_llm_name(self, b=None, model=False):
        b = self.llmclient if b is None else b
        if isinstance(b, dict): return 'BADCONFIG_MIXIN'
        if model: return b.backend.model.lower()
        return f"{type(b.backend).__name__}/{b.backend.name}"

    def abort(self):
        if not self.is_running: return
        print('Abort current task...')
        self.stop_sig = True
        if self.handler is not None: self.handler.code_stop_signal.append(1)
            
    def put_task(self, query, source="user", images=None):
        display_queue = queue.Queue()
        self.task_queue.put({"query": query, "source": source, "images": images or [], "output": display_queue})
        return display_queue

    # i know it is dangerous, but raw_query is dangerous enough it doesn't enlarge
    def _handle_slash_cmd(self, raw_query, display_queue):
        if not raw_query.startswith('/'): return raw_query

        if _sm := re.match(r'/session\.(\w+)=(.*)', raw_query.strip()):
            k, v = _sm.group(1), _sm.group(2)
            vfile = os.path.join(script_dir, 'temp', v)
            if os.path.isfile(vfile): v = open(vfile, encoding='utf-8').read().strip()
            try: v = json.loads(v)  # cover number parsing
            except (json.JSONDecodeError, ValueError): pass
            if k in ('model', 'name') and not isinstance(v, str): v = _sm.group(2)  # 防纯数字model名被转成int
            applied, note = _apply_session_attr(self.llmclient.backend, k, v)
            if not applied:
                # 如实报失败, 不要打 ✅: 曾经这里裸 setattr 后无条件报成功, 而聚合后端(mixin)上
                # 非广播属性会落到壳上、把 __getattr__ 永久遮蔽, 成员仍是旧值——用户看到
                # "✅ session.thinking_type = enabled" 而实际毫无效果。
                display_queue.put({'done': smart_format(f"❌ session.{k} 未能生效: {note}", max_str_len=500), 'source': 'system'})
                return None
            display_queue.put({'done': smart_format(f"✅ session.{k} = {repr(v)}{note}", max_str_len=500), 'source': 'system'})
            return None
        if _lm := re.match(r'/llm\s+(.+)', raw_query.strip()):   # 切换服务商session(按名或序号), 复用 next_llm(保留history)
            spec = _lm.group(1).strip(); model = None
            try:
                obj = json.loads(spec)
                if isinstance(obj, dict): spec, model = str(obj.get('name') or '').strip(), str(obj.get('model') or '').strip() or None
            except (json.JSONDecodeError, ValueError, TypeError): pass
            target = spec; self.load_llm_sessions(); idx = None
            if target.isdigit() and int(target) < len(self.llmclients): idx = int(target)
            elif target:
                matches = [i for i, b in enumerate(self.llmclients) if target == getattr(getattr(b, 'backend', None), 'name', None)]
                if not matches: matches = [i for i, b in enumerate(self.llmclients) if target in self.get_llm_name(b)]
                if len(matches) == 1: idx = matches[0]
            if idx is None:
                display_queue.put({'done': f'未找到 LLM: {target}（名称须唯一，或使用序号）', 'source': 'system'}); return None
            self.next_llm(idx)
            if model:
                try: self.llmclient.backend.model = model               # UI 选择的是 provider+model；运行中即时覆盖，避免沿用 mykey 旧默认型号
                except AttributeError: pass                             # 聚合后端(mixin)的 model 是只读派生属性: 型号由成员链决定, 覆盖无意义; 吞掉防杀死任务循环线程
            display_queue.put({'done': f'✅ 切换到 {self.get_llm_name()} · {self.get_llm_name(model=True)}', 'source': 'system'})
            return None
        if raw_query.strip() == '/resume':
            return r'帮我看看最近有哪些会话可以恢复。读model_responses/目录，按修改时间取最近10个文件，从每个文件里找最后一个<history>...</history>块，用一句话总结每个会话在聊什么，列表给我选。注意读文件后要把字面的\n替换成真换行才能正确匹配。'
        return raw_query

    def run(self):
        while True:
            task = self.task_queue.get()
            if isinstance(task, str): break
            raw_query, source, display_queue = task["query"], task["source"], task["output"]
            if self.llmclient is None:                 # 中间态防线(mykey.py 在但无可用条目): 先按 mtime 自愈(配置可能已修好),
                self.load_llm_sessions()               #  仍无则回可读终态并跳过 — 否则 215 行 try 外解引 None 会杀死本线程,
                if self.llmclient is None:             #  且 is_running 悬挂 True → /clear 永久 busy、修好 key 同会话也瘫痪
                    display_queue.put({'done': '[ERROR] No usable LLM provider. mykey.py 无可用服务商配置：请在「设置 → 服务商与模型」重新保存，或检查 mykey.py 语法后重试。', 'source': source, 'turn': 0, 'outputs': []})
                    self.task_queue.task_done(); continue
            raw_query = self._handle_slash_cmd(raw_query, display_queue)
            if raw_query is None:
                self.task_queue.task_done(); continue
            self.is_running = True
            if len(raw_query) > 2000:
                task_file = os.path.join(script_dir, 'temp', f'user_prompt_{int(time.time())}.md')
                with open(task_file, 'w', encoding='utf-8') as f: f.write(raw_query)
                raw_query = f'Long user prompt saved to {task_file}. Read and execute.'
            rquery = smart_format(raw_query.replace('\n', ' '), max_str_len=200)
            self.history.append(f"[USER]: {rquery}")
            
            sys_prompt = get_system_prompt() + getattr(self.llmclient.backend, 'extra_sys_prompt', '')
            if self.peer_hint: sys_prompt += f"\n[Peer] 用户提及其他会话/后台任务状态时: temp/model_responses/ (只找近期修改的文件尾部)\n"
            handler = GenericAgentHandler(self, self.history, os.path.join(script_dir, 'temp'))
            if getattr(self, 'no_print', False): handler.print = lambda *a, **k: None
            if self.handler and 'key_info' in self.handler.working: 
                ki = re.sub(r'\n\[SYSTEM\] 此为.*?工作记忆[。\n]*', '', self.handler.working['key_info'])  # 去旧
                handler.working['key_info'] = ki
                handler.working['passed_sessions'] = ps = self.handler.working.get('passed_sessions', 0) + 1
                if ps > 0: handler.working['key_info'] += f'\n[SYSTEM] 此为 {ps} 个对话前设置的key_info，若已在新任务，先更新或清除工作记忆。\n'
            self.handler = handler  # although new handler, the **full** history is in llmclient, so it is full history!
            self.llmclient.log_path = self.log_path
            if self.force_non_stream:
                self.llmclient.backend.stream = False
                self.llmclient.backend.read_timeout = max(self.llmclient.backend.read_timeout, 1200)
            gen = agent_runner_loop(self.llmclient, sys_prompt, raw_query, handler, TOOLS_SCHEMA, 
                                    max_turns=80, verbose=self.verbose, yield_info=True)
            try:
                full_resp = ""; last_pos = 0; curr_turn = 0; turn_resps = []
                for chunk in gen:
                    if consume_file(self.task_dir, '_stop'): self.abort() 
                    if self.stop_sig: break
                    if isinstance(chunk, dict) and 'turn' in chunk: 
                        curr_turn = chunk['turn']; turn_resps.append(''); continue
                    full_resp += chunk;  turn_resps[-1] += chunk
                    if len(full_resp) - last_pos > 30 or 'LLM Running' in chunk:
                        display_queue.put({'next': full_resp[last_pos:] if self.inc_out else full_resp, 
                                           'source': source, 'turn': curr_turn, 'outputs': turn_resps[-2:]})
                        last_pos = len(full_resp)
                if self.inc_out and last_pos < len(full_resp):
                    display_queue.put({'next': full_resp[last_pos:], 'source': source,
                                    'turn': curr_turn, 'outputs': turn_resps[-2:]})
                #if '</summary>' in full_resp: full_resp = full_resp.replace('</summary>', '</summary>\n\n')
                #if '</file_content>' in full_resp: full_resp = re.sub(r'<file_content>\s*(.*?)\s*</file_content>', r'\n````\n<file_content>\n\1\n</file_content>\n````', full_resp, flags=re.DOTALL)                
                display_queue.put({'done': full_resp, 'source': source, 'turn': curr_turn, 'outputs': turn_resps.copy()})
                self.history = handler.history_info
            except Exception as e:
                print(f"Backend Error: {format_error(e)}")
                _track_agent_end('error', curr_turn)   # 后端异常: agent_after 不触发, 显式补收尾埋点
                display_queue.put({'done': full_resp + f'\n```\n{format_error(e)}\n```', 'source': source, 'turn': curr_turn, 'outputs': turn_resps.copy()})
            finally:
                if self.stop_sig:
                    print('User aborted the task.')
                    _track_agent_end('aborted', curr_turn)   # 用户中止: 循环被 break, 显式补收尾埋点
                self.is_running = self.stop_sig = False
                self.task_queue.task_done()
                if self.handler is not None: self.handler.code_stop_signal.append(1)

GeneraticAgent = GenericAgent

if __name__ == '__main__':
    import argparse
    from datetime import datetime
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', metavar='IODIR', help='一次性任务模式(文件IO)')
    parser.add_argument('--reflect', metavar='SCRIPT', help='反射模式：加载监控脚本，check()触发时发任务')
    parser.add_argument('--input', help='prompt')
    parser.add_argument('--llm_no', type=int, default=0)
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--nobg', action='store_true')
    args, _unknown = parser.parse_known_args()
    _reflect_args = dict(zip([k.lstrip('-') for k in _unknown[::2]], _unknown[1::2])) if _unknown else {}

    if args.task and not args.nobg:
        import subprocess, platform
        cmd = [sys.executable, os.path.abspath(__file__)] + [a for a in sys.argv[1:]] + ['--nobg']
        d = os.path.join(script_dir, f'temp/{args.task}'); os.makedirs(d, exist_ok=True)
        p = subprocess.Popen(cmd, cwd=script_dir,
            creationflags=0x08000000 if platform.system() == 'Windows' else 0,
            stdout=open(os.path.join(d, 'stdout.log'), 'w', encoding='utf-8'),
            stderr=open(os.path.join(d, 'stderr.log'), 'w', encoding='utf-8'))
        print('PID:', p.pid); sys.exit(0)

    agent = GeneraticAgent()
    agent.next_llm(args.llm_no)
    agent.verbose = args.verbose
    threading.Thread(target=agent.run, daemon=True).start()

    if args.task:
        agent.peer_hint = False
        agent.force_non_stream = True
        agent.task_dir = d = os.path.join(script_dir, f'temp/{args.task}'); nround = ''
        infile = os.path.join(d, 'input.txt')
        if args.input:
            os.makedirs(d, exist_ok=True)
            import glob; [os.remove(f) for f in glob.glob(os.path.join(d, 'output*.txt'))]
            with open(infile, 'w', encoding='utf-8') as f: f.write(args.input)
        if (fh := consume_file(d, '_history.json')): agent.llmclient.backend.history = json.loads(fh)
        with open(infile, encoding='utf-8') as f: raw = f.read()
        while True:
            dq = agent.put_task(raw, source='task')
            while 'done' not in (item := dq.get(timeout=1200)): 
                if 'next' in item and random.random() < 0.95:  # 概率写一次中间结果
                    with open(f'{d}/output{nround}.txt', 'w', encoding='utf-8') as f: f.write(item.get('next', ''))
            with open(f'{d}/output{nround}.txt', 'w', encoding='utf-8') as f: f.write(item['done'] + '\n\n[ROUND END]\n')
            consume_file(d, '_stop')  # 已经成功停下来了，避免打断下次reply
            for _ in range(300):  # 等reply.txt，10分钟超时
                time.sleep(2)
                if (raw := consume_file(d, 'reply.txt')): break
            else: break
            nround = nround + 1 if isinstance(nround, int) else 1
    elif args.reflect:
        agent.peer_hint = False
        agent.force_non_stream = True
        import importlib.util
        spec = importlib.util.spec_from_file_location('reflect_script', args.reflect)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        if hasattr(mod, 'init'): mod.init(_reflect_args)
        _mt = os.path.getmtime(args.reflect)
        print(f'[Reflect] loaded {args.reflect}' + (f' args={_reflect_args}' if _reflect_args else ''))
        while True:
            if os.path.getmtime(args.reflect) != _mt:
                try:
                    spec.loader.exec_module(mod); _mt = os.path.getmtime(args.reflect)
                    if hasattr(mod, 'init'): mod.init(_reflect_args)
                    print('[Reflect] reloaded')
                except Exception as e: print(f'[Reflect] reload error: {e}')
            try: task = mod.check()
            except Exception as e: 
                print(f'[Reflect] check() error: {e}'); task = None
            if task and task == '/exit': break
            if not task:
                time.sleep(getattr(mod, 'INTERVAL', 5)); continue
            print(f'[Reflect] triggered: {task[:80]}')
            dq = agent.put_task(task, source='reflect')
            try:
                while 'done' not in (item := dq.get(timeout=1200)): pass
                result = item['done']
                print(result)
            except Exception as e:
                if getattr(mod, 'ONCE', False): raise
                print(f'[Reflect] drain error: {e}'); result = f'[ERROR] {e}'
            log_dir = os.path.join(script_dir, 'temp/reflect_logs'); os.makedirs(log_dir, exist_ok=True)
            script_name = os.path.splitext(os.path.basename(args.reflect))[0]
            open(os.path.join(log_dir, f'{script_name}_{datetime.now():%Y-%m-%d}.log'), 'a', encoding='utf-8').write(f'[{datetime.now():%m-%d %H:%M}]\n{result}\n\n')
            if (on_done := getattr(mod, 'on_done', None)):
                try: on_done(result)
                except Exception as e: print(f'[Reflect] on_done error: {e}')
            if getattr(mod, 'ONCE', False): print('[Reflect] ONCE=True, exiting.'); break
    else:
        try: import readline
        except Exception: pass
        agent.inc_out = True
        if sys.stdout.isatty():
            try: model = agent.get_llm_name(model=True) or '?'
            except Exception: model = '?'
            try:
                sys.stdout.write(f'\x1b[92m✦\x1b[0m \x1b[1mGenericAgent\x1b[0m '
                                 f'\x1b[90m· cli · model:\x1b[0m {model}\n')
                sys.stdout.flush()
            except Exception: pass
        while True:
            q = input('> ').strip()
            if not q: continue
            try:
                dq = agent.put_task(q, source='user')
                while True:
                    item = dq.get()
                    if 'next' in item: print(item['next'], end='', flush=True)
                    if 'done' in item: print(); break
            except KeyboardInterrupt:
                agent.abort()
                print('\n[Interrupted]')
