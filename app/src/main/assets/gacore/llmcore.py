import os, json, re, time, requests, sys, threading, urllib3, base64, importlib, uuid, pathlib
from datetime import datetime
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_RESP_CACHE_KEY = str(uuid.uuid4())
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path: sys.path.append(_ROOT)

mykey_lock = threading.RLock()
def _load_mykeys():
    global _mykey_path
    with mykey_lock:
        try:
            # importlib.reload() re-executes code in the existing module dict and
            # leaves names that were removed from mykey.py behind. Delete the module
            # first so provider deletion is reflected immediately in /config.
            sys.modules.pop('mykey', None)
            mykey = importlib.import_module('mykey'); _mykey_path = mykey.__file__
            return {k: v for k, v in vars(mykey).items() if not k.startswith('_')}
        except ImportError as e:
            if getattr(e, 'name', None) != 'mykey':
                raise Exception(f'[ERROR] mykey.py found but failed to import: {e}') from e
        except SyntaxError as e:
            raise Exception(f'[ERROR] mykey.py has syntax error: {e}') from e
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mykey.json')
        if not os.path.exists(p): raise Exception('[ERROR] mykey.py not found in sys.path and mykey.json not found. Run "python configure_mykey.py" or copy mykey_template.py to mykey.py and fill in your keys.')
        with open(_mykey_path := p, encoding='utf-8') as f: mk = json.load(f)
        if isinstance(mk, dict) and 'remote_url' in mk: return requests.get(mk['remote_url'], timeout=10).json()
    return mk

_mykey_path = _mykey_mtime = None
def reload_mykeys():
    global _mykey_mtime
    try:
        mt = os.stat(_mykey_path).st_mtime_ns if _mykey_path else -1
        if mt == _mykey_mtime: return globals().get('mykeys', {}), False
        mk = _load_mykeys(); _mykey_mtime = os.stat(_mykey_path).st_mtime_ns
        print(f'[Info] Load mykeys from {_mykey_path}')
        globals().update(mykeys=mk)
        return mk, True
    except: return globals().get('mykeys', {}), False

def __getattr__(name):  # once guard in PEP 562
    if name == 'mykeys': return reload_mykeys()[0]
    raise AttributeError(f"module 'llmcore' has no attribute {name}")

def compress_history_tags(messages, keep_recent=4, max_len=600, force=False, interval=5,
                          recent_max_len=3000):
    """Compress <thinking>/<tool_use>/<tool_result> tags in older messages to save tokens.
    默认值经实测对比选择此方案效果更佳: keep_recent=4(只保留最近 4 轮完整脚本/结果)、
    max_len=600——长任务(30+ 轮)下 in_tok 从 11K 涨到 36K、model_wait 从 3s 涨到 37s,
    旧轮次的完整代码块与结果对后续决策无增益, 只撑上下文。

    recent_max_len: 最近 keep_recent 条的上限。**原来这几条完全不做限制**, 而真机实测
    它们平均 4922 字符、占 resend 的 67%(19687/29287)——压缩把旧的压到 600, 却把体量
    全留给最新的几条, 每轮输入照样膨胀。in_tok 与 model_wait 的相关系数 r=0.574:
    in_tok 11.2K→6.0s、13.6K→8.7s、14.5K→13.9s。给近期轮次一个宽松但有限的上限,
    输入体量才真的封得住。"""
    compress_history_tags._cd = getattr(compress_history_tags, '_cd', 0) + 1
    if force: compress_history_tags._cd = 0
    if compress_history_tags._cd % interval != 0: return messages
    _before = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
    _pats = {tag: re.compile(rf'(<{tag}>)([\s\S]*?)(</{tag}>)') for tag in ('thinking', 'think', 'tool_use', 'tool_result')}
    _hist_pat = re.compile(r'<(history|key_info|earlier_context)>[\s\S]*?</\1>')
    _n = len(messages)
    _MARK = '\n...[Truncated]...\n'
    def _limit(i): return max_len if i < _n - keep_recent else max(max_len, recent_max_len)
    def _cut(s, lim):
        """截到 lim 以内(marker 也算进预算, 否则实际是 lim+19, 上限名不副实)。"""
        if not isinstance(s, str) or len(s) <= lim: return s
        budget = max(lim - len(_MARK), 2)
        return s[:budget // 2] + _MARK + s[-budget // 2:]
    def _trunc(text, lim):
        text = _hist_pat.sub(lambda m: f'<{m.group(1)}>[...]</{m.group(1)}>', text)
        for pat in _pats.values(): text = pat.sub(lambda m: m.group(1) + _cut(m.group(2), lim) + m.group(3), text)
        # 标签外的裸长文本也要压: 旧实现只截 tag 内部, 消息里标签外的结果/代码原文
        # (占大头)原样保留, 压缩率远低于预期——长任务上下文照样膨胀。
        return _cut(text, lim) if len(text) > lim else text
    for i, msg in enumerate(messages):
        # [0] 是协议载体: _build_protocol_prompt 把 system + 交互协议 + 工具清单 + L1 记忆索引
        # 一次性拼成首条 prompt, 后续每条只是它的重复。裁它 = 把交互协议从上下文里删掉,
        # 第 N 轮起模型既看不到 <tool_use> 协议也看不到记忆路由(实测 7827→619 字符, 全丢)。
        # system 消息同理: 常驻约束, 不属于"旧轮次"。
        if i == 0 or msg.get('role') == 'system':
            continue
        lim = _limit(i)
        c = msg['content']
        if isinstance(c, str): msg['content'] = _trunc(c, lim)
        elif isinstance(c, list):
            for b in c:
                if not isinstance(b, dict): continue
                t = b.get('type')
                if t == 'text' and isinstance(b.get('text'), str): b['text'] = _trunc(b['text'], lim)
                elif t == 'tool_result':
                    tc = b.get('content')
                    if isinstance(tc, str): b['content'] = _cut(tc, lim)
                    elif isinstance(tc, list):
                        for sub in tc:
                            if isinstance(sub, dict) and sub.get('type') == 'text': sub['text'] = _cut(sub.get('text'), lim)
                elif t == 'tool_use' and isinstance(b.get('input'), dict):
                    for k, v in b['input'].items(): b['input'][k] = _cut(v, lim)
    print(f"[Cut] {_before} -> {sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)}")
    return messages

def _sanitize_leading_user_msg(msg):
    """把 user 消息里的 tool_result 块改写成纯文本，避免孤立引用。
    history 统一使用 Claude content-block 格式：content 是 list of blocks。"""
    msg = dict(msg)  # 浅拷贝外层 dict
    content = msg.get('content')
    if not isinstance(content, list): return msg
    texts = []
    for block in content:
        if not isinstance(block, dict): continue
        if block.get('type') == 'tool_result':
            c = block.get('content', '')
            if isinstance(c, list):  # content 本身也可能是 list[{type:text,text:...}]
                texts.extend(b.get('text', '') for b in c if isinstance(b, dict))
            else: texts.append(str(c))
        elif block.get('type') == 'text': texts.append(block.get('text', ''))
    msg['content'] = [{"type": "text", "text": '\n'.join(t for t in texts if t)}]
    return msg

_oldprint = print
def safeprint(*argv):
    try: _oldprint(*argv)
    except OSError: pass
print = safeprint

def _drop_oldest_turn(history):
    """丢一条最旧的对话轮次(保留 [0]); 丢完把新的首条 user 消息净化,
    避免孤立 tool_result 引用。原地修改, 调用方依赖这一点。"""
    history.pop(1)
    while len(history) > 1 and history[1].get('role') != 'user': history.pop(1)
    if len(history) > 1 and history[1].get('role') == 'user':
        history[1] = _sanitize_leading_user_msg(history[1])


IMAGE_PLACEHOLDER = '[earlier screenshot omitted to save context]'


def age_image_blocks(history, keep=1):
    """只留最近 keep 张图, 更早的换成一行占位文字。返回被替换的张数。

    图在历史里是 base64(一张缩略后的截图 ~80KB): 20 条历史就是 1.6MB 的重发体积,
    足以把上下文窗口和每轮 prefill 一起顶爆。所以"每轮附图"必须配这条老化规则——
    模型只需要看当前这一屏, 上一屏的像素对下一步没有增益(位置信息走 obs/文字)。"""
    seen = 0
    replaced = 0
    for msg in reversed(history or []):
        content = msg.get('content')
        if not isinstance(content, list):
            continue
        for i in range(len(content) - 1, -1, -1):
            block = content[i]
            if not isinstance(block, dict) or block.get('type') not in ('image', 'image_url'):
                continue
            seen += 1
            if seen <= keep:
                continue
            content[i] = {"type": "text", "text": IMAGE_PLACEHOLDER}
            replaced += 1
    return replaced


def _history_cost(history):
    """上下文体积估算: 图片按固定 2k 字符计, 不让 base64 长度决定裁剪策略。"""
    total = 0
    for m in history or []:
        content = m.get('content')
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get('type') in ('image', 'image_url'):
                    total += 2000
                else:
                    total += len(json.dumps(b, ensure_ascii=False))
        else:
            total += len(json.dumps(content, ensure_ascii=False))
    return total


def trim_messages_history(history, sess):
    cap = sess.context_win * 3
    target = int(cap * getattr(sess, 'trim_keep_rate', 0.6))
    def cost(): return _history_cost(history)
    age_image_blocks(history, keep=1)      # 先老化图片: 否则一条图就能顶到 cap, 触发无谓的历史裁剪
    compress_history_tags(history, interval=getattr(sess, 'cut_msg_interval', 5))
    print(f'[Debug] Current context: {cost()} chars, {len(history)} messages.')
    # 条数上限必须排在体积上限前面: 每轮重发全部历史, 条数不封顶时单轮成本随轮数
    # 线性上涨、总时间平方上涨。真机实证: 19 轮 resend 829→50017 字符(60x),
    # model_wait 3.1s→32.5s, 用户因太慢把任务取消; 而体积上限 context_win*3 高达
    # 9 万字符, 那条路根本等不到——压缩只把单条压到 600, 压不掉条数本身。
    # 20 条 ≈ 10 轮原始上下文; 更早的轮次由 anchor prompt 的 <history>/<key_info>
    # 工作记忆兜着(设计上旧轮次"对后续决策无增益")。
    max_msgs = int(getattr(sess, 'max_history_msgs', 20))
    while len(history) > max_msgs:
        _drop_oldest_turn(history)
    if cost() <= cap: return
    compress_history_tags(history, keep_recent=4, force=True)   # 超限强压: 与默认一致, 旧轮次只留头尾
    if cost() <= target: return
    while len(history) > 9 and cost() > target:
        _drop_oldest_turn(history)
    print(f'[Debug] Trimmed context, current: {cost()} chars, {len(history)} messages.')

def auto_make_url(base, path):
    b, p = base.rstrip('/'), path.strip('/')
    if b.endswith('$'): return b[:-1].rstrip('/')
    if b.endswith(p): return b
    return f"{b}/{p}" if re.search(r'/v\d+(/|$)', b) else f"{b}/v1/{p}"

def _parse_claude_json(data):
    content_blocks = data.get("content", [])
    _record_usage(data.get("usage", {}), "messages")
    for b in content_blocks:
        if b.get("type") == "text": yield b.get("text", "")
        elif b.get("type") == "thinking": yield ""
    return content_blocks

def _parse_claude_sse(resp_lines):
    """Parse Anthropic SSE stream. Yields text chunks, returns list[content_block]."""
    content_blocks = []; current_block = None; tool_json_buf = ""
    stop_reason = None; got_message_stop = False; warn = None
    for line in resp_lines:
        if not line: continue
        line = line.decode('utf-8') if isinstance(line, bytes) else line
        if not line.startswith("data:"): continue
        data_str = line[5:].lstrip()
        if data_str == "[DONE]": break
        try: evt = json.loads(data_str)
        except Exception as e:
            print(f"[SSE] JSON parse error: {e}, line: {data_str[:200]}")
            continue
        evt_type = evt.get("type", "")
        if evt_type == "message_start":
            usage = evt.get("message", {}).get("usage", {})
            _record_usage(usage, "messages")
        elif evt_type == "content_block_start":
            block = evt.get("content_block", {})
            if block.get("type") == "text": current_block = {"type": "text", "text": ""}
            elif block.get("type") == "thinking": current_block = {"type": "thinking", "thinking": "", "signature": ""}
            elif block.get("type") == "tool_use":
                current_block = {"type": "tool_use", "id": block.get("id", ""), "name": block.get("name", ""), "input": {}}
                tool_json_buf = ""
        elif evt_type == "content_block_delta":
            delta = evt.get("delta", {})
            if delta.get("type") == "text_delta":
                text = delta.get("text", "")
                if current_block and current_block.get("type") == "text": current_block["text"] += text
                if text: yield text
            elif delta.get("type") == "thinking_delta":
                if current_block and current_block.get("type") == "thinking": current_block["thinking"] += delta.get("thinking", "")
            elif delta.get("type") == "signature_delta":
                if current_block and current_block.get("type") == "thinking":
                    current_block["signature"] = current_block.get("signature", "") + delta.get("signature", "")
            elif delta.get("type") == "input_json_delta": tool_json_buf += delta.get("partial_json", "")
        elif evt_type == "content_block_stop":
            if current_block:
                if current_block["type"] == "tool_use":
                    try: current_block["input"] = json.loads(tool_json_buf) if tool_json_buf else {}
                    except: current_block["input"] = {"_raw": tool_json_buf}
                content_blocks.append(current_block)
                current_block = None
        elif evt_type == "message_delta":
            delta = evt.get("delta", {})
            stop_reason = delta.get("stop_reason", stop_reason)
            out_usage = evt.get("usage", {})
            out_tokens = out_usage.get("output_tokens", 0)
            if out_tokens:
                print(f"[Output] tokens={out_tokens} stop_reason={stop_reason}")
                # Claude 流式 output_tokens 不经 _record_usage; 只补输出, 输入仍由 message_start 上报
                _emit_usage(0, out_tokens, 0)
        elif evt_type == "message_stop": got_message_stop = True
        elif evt_type == "error":
            err = evt.get("error", {})
            emsg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            warn = f"\n\n!!!Error: SSE {emsg}"; break
    if not warn:
        if not got_message_stop and not stop_reason: warn = "\n\n[!!! 流异常中断，未收到完整响应 !!!]"
        elif stop_reason == "max_tokens": warn = "\n\n[!!! Response truncated: max_tokens !!!]"
    if current_block:
        if current_block["type"] == "tool_use":
            try: current_block["input"] = json.loads(tool_json_buf) if tool_json_buf else {}
            except: current_block["input"] = {"_raw": tool_json_buf}
        content_blocks.append(current_block); current_block = None
    if warn:
        print(f"[WARN] {warn.strip()}")
        content_blocks.append({"type": "text", "text": warn}); yield warn
    return content_blocks

def _try_parse_tool_args(raw):
    """Parse tool args string; split concatenated JSON objects like {..}{..} if needed.
    Returns list of parsed dicts."""
    if not raw: return [{}]
    try: return [json.loads(raw)]
    except: pass
    parts = re.split(r'(?<=\})(?=\{)', raw)
    if len(parts) > 1:
        parsed = []
        for p in parts:
            try: parsed.append(json.loads(p))
            except: return [{"_raw": raw}]
        return parsed
    return [{"_raw": raw}]

def _parse_openai_sse(resp_lines, api_mode="chat_completions"):
    """Parse OpenAI SSE stream (chat_completions or responses API).
    Yields text chunks, returns list[content_block].
    content_block: {type:'text', text:str} | {type:'tool_use', id:str, name:str, input:dict}
    """
    content_text = ""
    if api_mode == "responses":
        seen_delta = False; fc_buf = {}; current_fc_idx = None
        for line in resp_lines:
            if not line: continue
            line = line.decode('utf-8', errors='replace') if isinstance(line, bytes) else line
            if not line.startswith("data:"): continue
            data_str = line[5:].lstrip()
            if data_str == "[DONE]": break
            try: evt = json.loads(data_str)
            except: continue
            etype = evt.get("type", "")
            if etype == "response.output_text.delta":
                delta = evt.get("delta", "")
                if delta: seen_delta = True; content_text += delta; yield delta
            elif etype == "response.output_text.done" and not seen_delta:
                text = evt.get("text", "")
                if text: content_text += text; yield text
            elif etype == "response.output_item.added":
                item = evt.get("item", {})
                if item.get("type") == "function_call":
                    idx = evt.get("output_index", 0)
                    fc_buf[idx] = {"id": item.get("call_id", item.get("id", "")), "name": item.get("name", ""), "args": ""}
                    current_fc_idx = idx
            elif etype == "response.function_call_arguments.delta":
                idx = evt.get("output_index", current_fc_idx or 0)
                if idx in fc_buf: fc_buf[idx]["args"] += evt.get("delta", "")
            elif etype == "response.function_call_arguments.done":
                idx = evt.get("output_index", current_fc_idx or 0)
                if idx in fc_buf: fc_buf[idx]["args"] = evt.get("arguments", fc_buf[idx]["args"])
            elif etype == "error":
                err = evt.get("error", {})
                emsg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                if emsg: content_text += f"!!!Error: {emsg}"; yield f"!!!Error: {emsg}"
                break
            elif etype == "response.completed":
                usage = evt.get("response", {}).get("usage", {})
                _record_usage(usage, api_mode)
                break
        blocks = []
        if content_text: blocks.append({"type": "text", "text": content_text})
        for idx in sorted(fc_buf):
            fc = fc_buf[idx]
            inps = _try_parse_tool_args(fc["args"])
            for i, inp in enumerate(inps):
                bid = fc["id"] or ''
                if len(inps) > 1: bid = f"{bid}_{i}" if bid else f"split_{i}"
                blocks.append({"type": "tool_use", "id": bid, "name": fc["name"], "input": inp})
        return blocks
    else:
        tc_buf = {}  # index -> {id, name, args}
        reasoning_text = ""
        last_usage = None   # chat_completions 流式: 每个 chunk 都可能带 usage(累计值), 只记最后一次
        for line in resp_lines:
            if not line: continue
            line = line.decode('utf-8', errors='replace') if isinstance(line, bytes) else line
            if not line.startswith("data:"): continue
            data_str = line[5:].lstrip()
            if data_str == "[DONE]": break
            try: evt = json.loads(data_str)
            except: continue
            if not evt.get("choices") and (evt.get("error") or evt.get("message")):
                _em = evt.get("error") or evt
                _msg = _em.get("message") if isinstance(_em, dict) else str(_em)
                if _msg:
                    content_text += "!!!Error: " + str(_msg)
                    yield "!!!Error: " + str(_msg)
                continue
            ch = (evt.get("choices") or [{}])[0]
            delta = ch.get("delta") or {}
            if delta.get("reasoning_content"):
                reasoning_text += delta["reasoning_content"]
            if delta.get("content"):
                text = delta["content"]; content_text += text; yield text
            for tc in (delta.get("tool_calls") or []):
                idx = tc.get("index", 0)
                has_name = bool(tc.get("function", {}).get("name"))
                if idx not in tc_buf:
                    if has_name or not tc_buf: tc_buf[idx] = {"id": tc.get("id") or '', "name": "", "args": ""}
                    else: idx = max(tc_buf)
                if has_name: tc_buf[idx]["name"] = tc["function"]["name"]
                if tc.get("function", {}).get("arguments"): tc_buf[idx]["args"] += tc["function"]["arguments"]
                if tc.get("id") and not tc_buf[idx]["id"]: tc_buf[idx]["id"] = tc["id"]
            usage = evt.get("usage")
            if usage: last_usage = usage
        if last_usage: _record_usage(last_usage, api_mode)   # 一次请求只记一次; 每 chunk 累计上报会放大几百倍
        blocks = []
        if reasoning_text: blocks.append({"type": "thinking", "thinking": reasoning_text})
        if content_text: blocks.append({"type": "text", "text": content_text})
        for idx in sorted(tc_buf):
            tc = tc_buf[idx]
            inps = _try_parse_tool_args(tc["args"])
            for i, inp in enumerate(inps):
                bid = tc["id"] or ''
                if len(inps) > 1: bid = f"{bid}_{i}" if bid else f"split_{i}"
                blocks.append({"type": "tool_use", "id": bid, "name": tc["name"], "input": inp})
        return blocks

_USAGE_OBSERVERS = []   # 只观察消费者(如 run_metrics): 每次收到服务商用量即回调; 异常吞掉, 不影响解析


def add_usage_observer(fn):
    """注册用量观察者 fn(in_tok, out_tok, cached_tok)。同一 fn 只注册一次。
    存在原因: _record_usage 原先只 print, token 无法按 turn 归集(SPEC Part 4.6)。"""
    if fn not in _USAGE_OBSERVERS:
        _USAGE_OBSERVERS.append(fn)


def _emit_usage(inp, out, cached=0):
    """把已归一的用量发给观察者; 观察者出错绝不影响协议解析。"""
    for fn in list(_USAGE_OBSERVERS):
        try:
            fn(int(inp or 0), int(out or 0), int(cached or 0))
        except Exception:
            pass


def _record_usage(usage, api_mode):
    if not usage: return
    if api_mode == 'responses':
        cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
        inp = usage.get("input_tokens", 0); out = usage.get("output_tokens", 0)
        print(f"[Cache] input={inp} cached={cached}")
        if out: print(f"[Output] tokens={out}")
        _emit_usage(inp, out, cached)
    elif api_mode == 'chat_completions':
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        inp = usage.get("prompt_tokens", 0); out = usage.get("completion_tokens", 0)
        print(f"[Cache] input={inp} cached={cached}")
        if out: print(f"[Output] tokens={out}")
        _emit_usage(inp, out, cached)
    elif api_mode == 'messages':
        ci, cr, inp = usage.get("cache_creation_input_tokens", 0), usage.get("cache_read_input_tokens", 0), usage.get("input_tokens", 0)
        print(f"[Cache] input={inp} creation={ci} read={cr}")
        # 计费口径与 kernel_adapter.patch_usage 一致: 缓存创建/读取都计入输入; cached 单列供缓存命中分析
        _emit_usage(inp + ci + cr, out=usage.get("output_tokens", 0), cached=cr)
    
def _parse_openai_json(data, api_mode="chat_completions"):
    blocks = []
    if api_mode == "responses":
        _record_usage(data.get("usage") or {}, api_mode)
        for item in (data.get("output") or []):
            if item.get("type") == "message":
                for p in (item.get("content") or []):
                    if p.get("type") in ("output_text", "text") and p.get("text"):
                        blocks.append({"type": "text", "text": p["text"]}); yield p["text"]
            elif item.get("type") == "function_call":
                try: args = json.loads(item.get("arguments", "")) if item.get("arguments") else {}
                except: args = {"_raw": item.get("arguments", "")}
                blocks.append({"type": "tool_use", "id": item.get("call_id", item.get("id", "")),
                               "name": item.get("name", ""), "input": args})
    else:
        _record_usage(data.get("usage") or {}, api_mode)
        msg = (data.get("choices") or [{}])[0].get("message", {})
        reasoning = msg.get("reasoning_content", "")
        if reasoning:
            blocks.append({"type": "thinking", "thinking": reasoning})
        content = msg.get("content", "")
        if content:
            blocks.append({"type": "text", "text": content}); yield content
        for tc in (msg.get("tool_calls") or []):
            fn = tc.get("function", {})
            try: args = json.loads(fn.get("arguments", "")) if fn.get("arguments") else {}
            except: args = {"_raw": fn.get("arguments", "")}
            blocks.append({"type": "tool_use", "id": tc.get("id", ""), "name": fn.get("name", ""), "input": args})
    return blocks

def _stamp_oai_cache_markers(messages, model):
    """Add cache_control to last 2 user messages for Anthropic models via OAI-compatible relay."""
    ml = model.lower()
    if not any(k in ml for k in ('claude', 'anthropic')): return
    user_idxs = [i for i, m in enumerate(messages) if m.get('role') == 'user']
    for idx in user_idxs[-2:]:
        c = messages[idx].get('content')
        if isinstance(c, str):
            messages[idx] = {**messages[idx], 'content': [{'type': 'text', 'text': c, 'cache_control': {'type': 'ephemeral'}}]}
        elif isinstance(c, list) and c:
            c = list(c); c[-1] = dict(c[-1], cache_control={'type': 'ephemeral'})
            messages[idx] = {**messages[idx], 'content': c}

class _RecProxy:
    """包一层响应对象, 记录原始 SSE 行数/首行/是否见到 [DONE]。

    用途: app 报的 "empty response" 到底是真·空 body, 还是 body 里有 data 但解析器没认出来
    (例如网关把错误包成 data: {"error": ...} 事件, 或者只回了一个 data: [DONE])。
    """
    def __init__(self, resp):
        self._resp = resp
        self.n = 0
        self.first = b''
        self.done = False

    def iter_lines(self, *a, **k):
        for ln in self._resp.iter_lines(*a, **k):
            if ln:
                self.n += 1
                if not self.first: self.first = ln[:400]
                if b'[DONE]' in ln: self.done = True
            yield ln

    def json(self):
        return self._resp.json()


def _shrink_payload(o):
    """把请求体缩到可落盘的形状: 长字符串(图片 base64/大提示词)只留长度。"""
    if isinstance(o, str):
        return o if len(o) < 400 else f"<str len={len(o)}>"
    if isinstance(o, list):
        return [_shrink_payload(x) for x in o]
    if isinstance(o, dict):
        return {k: _shrink_payload(v) for k, v in o.items()}
    return o


def _stream_diag(sess, url, payload, resp, proxy, why):
    """空流出问题时落一份现场到 temp/stream_diag_<ts>.json, 不用再靠猜。"""
    try:
        d = {"t": time.time(), "why": why, "url": url, "model": getattr(sess, "model", ""),
             "status": getattr(resp, "status_code", None),
             "content_type": (getattr(resp, "headers", {}) or {}).get("Content-Type"),
             "raw_lines": getattr(proxy, "n", 0), "saw_done": getattr(proxy, "done", False),
             "first_line": (getattr(proxy, "first", b"") or b"").decode("utf-8", "replace"),
             "payload": _shrink_payload(payload)}
        path = pathlib.Path(__file__).parent.joinpath("temp", "stream_diag_%d.json" % int(time.time() * 1000))
        path.parent.mkdir(parents=True, exist_ok=True)
        if len(list(path.parent.glob("stream_diag_*.json"))) >= 20: return   # 最多留 20 份, 别把设备刷满
        path.write_text(json.dumps(d, ensure_ascii=False)[:200000], encoding="utf-8")
        print("[LLM Diag] " + path.name + " lines=" + str(d["raw_lines"]) + " done=" + str(d["saw_done"]))
    except Exception as e:
        print("[LLM Diag] dump failed: " + type(e).__name__ + ": " + str(e))


def _stream_with_retry(sess, url, headers, payload, parse_fn, json_fn=None):
    _RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 527, 529}
    def _delay(resp, attempt):
        try: ra = float((resp.headers or {}).get("retry-after"))
        except: ra = None
        return max(0.5, ra if ra is not None else min(30.0, 1.5 * (2 ** attempt)))
    for attempt in range(sess.max_retries + 1):
        streamed = False
        try:
            with requests.post(url, headers=headers, json=payload, stream=sess.stream, 
                               timeout=(sess.connect_timeout, sess.read_timeout), proxies=sess.proxies, verify=sess.verify) as r:
                if r.status_code >= 400:
                    if r.status_code in _RETRYABLE and attempt < sess.max_retries:
                        d = _delay(r, attempt)
                        print(f"[LLM Retry] HTTP {r.status_code}, retry in {d:.1f}s ({attempt+1}/{sess.max_retries+1})")
                        time.sleep(d); continue
                    try: body = r.text.strip()[:500]
                    except: body = ""
                    err = f"!!!Error: HTTP {r.status_code}" + (f": {body}" if body else "")
                    yield err; return [{"type": "text", "text": err}]
                rec = _RecProxy(r)
                gen = parse_fn(rec)
                try:
                    while True: chunk = next(gen); streamed = True; yield chunk
                except StopIteration as e:
                    if not e.value and not streamed:
                        _stream_diag(sess, url, payload, r, rec, "empty response")
                        _ct = str((getattr(r, "headers", None) or {}).get("Content-Type"))
                        raise requests.ConnectionError(
                            "empty response (http " + str(r.status_code) + ", raw_lines=" + str(rec.n)
                            + ", saw_done=" + str(rec.done) + ", ct=" + _ct + ")")
                    return e.value or []
        except (requests.Timeout, requests.ConnectionError) as e:
            #pathlib.Path(__file__).parent.joinpath('temp','bad_requests.json').write_text(json.dumps({"url":url,"headers":headers,"payload":payload,"err":str(e),"t":time.time()},ensure_ascii=False),encoding='utf-8')
            # 空流(HTTP 200 但一个 chunk 都没来)先怀疑"流式被网关吞掉": 同一个请求改成非流式再要一次。
            # 真机实测(StepFun step_plan, 2026-10-30): 20 条历史任务里 4 条死在这里(约 20%), 且都死在很靠前的回合,
            # 看起来就是"刚开始执行就报一堆 error"。非流式走的是另一条网关路径, 拿得到完整回复的概率明显更高。
            if json_fn and not streamed and 'empty response' in str(e) and payload.get('stream'):
                try:
                    p2 = dict(payload); p2['stream'] = False; p2.pop('stream_options', None)
                    with requests.post(url, headers=dict(headers, Accept='application/json'), json=p2,
                                       timeout=(sess.connect_timeout, sess.read_timeout),
                                       proxies=sess.proxies, verify=sess.verify) as r2:
                        if r2.status_code < 400:
                            # json_fn 与 SSE 解析器同形: 边 yield 文本边用 StopIteration.value 交回内容块。
                            gen2, blocks, got = json_fn(r2), [], False
                            try:
                                while True:
                                    c2 = next(gen2)
                                    if c2: got = True; yield c2
                            except StopIteration as stop2:
                                blocks = stop2.value or []
                            if got:
                                print('[LLM Retry] empty stream -> non-stream fallback ok')
                                return blocks
                        else:
                            print(f'[LLM Retry] non-stream fallback HTTP {r2.status_code}')
                except Exception as e2:
                    print(f'[LLM Retry] non-stream fallback failed: {type(e2).__name__}: {e2}')
            err = f"!!!Error: {type(e).__name__}: {e}" if str(e) else f"!!!Error: {type(e).__name__}"
            if 'empty response' in str(e):
                err += (f" -- 上游这一回合一个字都没回(空流), 已重试 {attempt + 1} 次。"
                        "这是网络/供应商侧的问题, 不是任务做错了: 过一会儿重发同一句就能继续, 也可以先换个模型。")
            if attempt < sess.max_retries:
                d = _delay(None, attempt)
                print(f"[LLM Retry] {type(e).__name__}, retry in {d:.1f}s ({attempt+1}/{sess.max_retries+1})")
                # 中间重试不再把 !!!Error 塞进正文: 真机一轮空流会连着重试好几次, 用户看到的就是"开机就一堆红字"。
                # 内部仍然重试(退避见 _delay), 只在全部用尽后往正文里放一条(见下方 yield err)。
                time.sleep(d); continue
            yield err; return [{"type": "text", "text": err}]
        except Exception as e:
            err = f"\n\n[!!! 流异常中断 {type(e).__name__}: {e} !!!]" if streamed else f"!!!Error: {type(e).__name__}: {e}"
            yield err; return [{"type": "text", "text": err}]

# 推理强度按模型钳制(单一真相源): GA 画布 7 档 {none,minimal,low,medium,high,xhigh,max}(max 镜像上游 247cb23),
# 但各模型合法档位窗不一(2026-07 官方文档/实测): OpenAI gpt-5.6+ 到 max, 5.2~5.5/codex-max 到 xhigh, 5.1 无 minimal/xhigh,
# gpt-5-pro 只收 high, gpt-5 之前(4o/4.1/o 系以外)不收该参; xAI grok 收 low/medium/high(multi-agent 额外 xhigh),
# imagine/build/composer/non-reasoning 变体发 effort 必 400; Claude output_config.effort 上限 max; 未知/兼容中转
# 走通用安全集 {low,medium,high}(原 _map_effort 行为)。请求前把档位夹进该模型的窗: 窗内透传零改, 窗外收敛到
# 最近合法档(平手取高: 保用户"要更多思考"的意图, 与旧 xhigh→Claude max 语义一致), none/空窗→不带参数(用上游默认)。
# 不变量: 绝不发出该模型必拒的档位。
_EFF_ORDER = ('minimal', 'low', 'medium', 'high', 'xhigh', 'max')

def _effort_window(model, proto='oai'):
    ml = (model or '').lower()
    if proto == 'claude': return ('low', 'medium', 'high', 'max')
    if 'grok' in ml:
        if any(x in ml for x in ('imagine', 'build', 'composer', 'non-reasoning')): return ()
        return ('low', 'medium', 'high', 'xhigh') if 'multi-agent' in ml else ('low', 'medium', 'high')
    m = re.search(r'\bgpt-(\d+)(?:\.(\d+))?', ml)
    if m:
        v = (int(m.group(1)), int(m.group(2) or 0))
        if v < (5, 0): return ()                                       # gpt-4o/4.1 等非推理模型: 不收该参
        if '-pro' in ml: return ('high',)
        if v >= (5, 6): return _EFF_ORDER[1:]                          # low..max
        if v >= (5, 2) or 'codex-max' in ml: return _EFF_ORDER[1:5]    # low..xhigh
        if v == (5, 1): return ('low', 'medium', 'high')
        return ('minimal', 'low', 'medium', 'high')                    # gpt-5 初代(minimal 随 gpt-5 引入)
    if re.match(r'o[134]\b|o[134]-', ml): return ('low', 'medium', 'high')   # o 系早于 minimal 档
    return ('low', 'medium', 'high')                                   # 未知/兼容中转: 通用安全集(原行为不变)

def _clamp_effort(effort, model, proto='oai'):
    if not effort or effort == 'none': return None
    win = _effort_window(model, proto)
    if not win: return None
    if effort in win: return effort
    i = _EFF_ORDER.index(effort) if effort in _EFF_ORDER else 1
    return min(win, key=lambda w: (abs(_EFF_ORDER.index(w) - i), -_EFF_ORDER.index(w)))


def _openai_stream(sess, messages):
    model, api_mode = sess.model, sess.api_mode
    ml = model.lower()
    temperature = sess.temperature
    if 'kimi' in ml or 'moonshot' in ml: temperature = 1
    elif 'minimax' in ml: temperature = max(0.01, min(temperature, 1.0))  # MiniMax requires temp in (0, 1]
    headers = {"Authorization": f"Bearer {sess.api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
    headers["User-Agent"] = sess.user_agent
    # 不变量: responses 与 chat_completions 是两套独立协议; api_mode 解析后即固定, 运行期绝不互切。
    #   responses 上游报错由 _stream_with_retry 以 !!!Error: 如实上抛——不"回退"成 chat_completions(那会掩盖上游渠道问题)。
    if api_mode == "responses":
        url = auto_make_url(sess.api_base, "responses")
        payload = {"model": model, "input": _to_responses_input(messages), "stream": sess.stream,
                   "prompt_cache_key": _RESP_CACHE_KEY, "instructions": sess.system or "You are an Omnipotent Executor."}
        eff = _clamp_effort(sess.reasoning_effort, model)
        if eff: payload["reasoning"] = {"effort": eff}
        if sess.max_tokens: payload["max_output_tokens"] = sess.max_tokens
    else:
        url = auto_make_url(sess.api_base, "chat/completions")
        if sess.system: messages = [{"role": "system", "content": sess.system}] + messages
        _stamp_oai_cache_markers(messages, model)
        payload = {"model": model, "messages": messages, "stream": sess.stream}
        if sess.stream: payload["stream_options"] = {"include_usage": True}
        if temperature != 1: payload["temperature"] = temperature
        if sess.max_tokens: payload["max_completion_tokens" if ml.startswith(("gpt-5", "o1", "o2", "o3", "o4")) else "max_tokens"] = sess.max_tokens
        eff = _clamp_effort(sess.reasoning_effort, model)
        if eff: payload["reasoning_effort"] = eff
        payload["enable_thinking"] = False   # 2026-10-25: step_plan 端点唯一实测有效的关思考开关（reasoning_effort 被端点忽略，单轮实测 12.2s 仍思考）；需推理质量的复杂任务删此行即可回退
    tools = getattr(sess, 'tools', None)
    if tools: payload["tools"] = _prepare_oai_tools(tools, api_mode)
    if sess.service_tier: payload["service_tier"] = sess.service_tier
    parse_fn = (lambda r: _parse_openai_sse(r.iter_lines(), api_mode)) if sess.stream else (lambda r: _parse_openai_json(r.json(), api_mode))
    json_fn = lambda r: _parse_openai_json(r.json(), api_mode)
    return (yield from _stream_with_retry(sess, url, headers, payload, parse_fn, json_fn))
        
def _prepare_oai_tools(tools, api_mode="chat_completions"):
    if api_mode == "responses":
        resp_tools = []
        for t in tools:
            if t.get("type") == "function" and "function" in t:
                rt = {"type": "function"}; rt.update(t["function"])
                resp_tools.append(rt)
            else: resp_tools.append(t)
        return resp_tools
    return tools

def _to_responses_input(messages):
    result, pending = [], []
    for msg in messages:
        role = str(msg.get("role", "user")).lower()
        if role == "tool":
            cid = msg.get("tool_call_id") or (pending.pop(0) if pending else f"call_{uuid.uuid4().hex[:8]}")
            result.append({"type": "function_call_output", "call_id": cid, "output": msg.get("content", "")})
            continue
        if role not in ["user", "assistant", "system", "developer"]: role = "user"
        if role == "system": role = "developer"  # Responses API uses 'developer' instead of 'system'
        content = msg.get("content", "")
        text_type = "output_text" if role == "assistant" else "input_text"
        parts = []
        if isinstance(content, str):
            if content: parts.append({"type": text_type, "text": content})
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict): continue
                ptype = part.get("type")
                if ptype == "text":
                    text = part.get("text", "")
                    if text: parts.append({"type": text_type, "text": text})
                elif ptype == "image_url":
                    url = (part.get("image_url") or {}).get("url", "")
                    if url and role != "assistant": parts.append({"type": "input_image", "image_url": url})
        if len(parts) == 0: parts = [{"type": text_type, "text": str(content) if not isinstance(content, list) else '[empty]'}]
        result.append({"role": role, "content": parts})
        pending = []
        for tc in (msg.get("tool_calls") or []):
            f = tc.get("function", {})
            cid = tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"
            pending.append(cid)
            result.append({"type": "function_call", "call_id": cid, "name": f.get("name", ""), "arguments": f.get("arguments", "")})
    return result


def _image_block_to_url(b):
    """把 claude 的 image 块转成 OpenAI 的 image_url 块(已是 image_url 原样返回); 非图片返回 None。"""
    if not isinstance(b, dict):
        return None
    if b.get("type") == "image_url":
        return b
    if b.get("type") != "image":
        return None
    src = b.get("source") or {}
    if src.get("type") == "base64" and src.get("data"):
        return {"type": "image_url",
                "image_url": {"url": "data:%s;base64,%s" % (src.get("media_type", "image/png"), src.get("data", ""))}}
    if src.get("type") == "url" and src.get("url"):
        return {"type": "image_url", "image_url": {"url": src["url"]}}
    return None


def _collect_image_blocks(content):
    """从(可能是 list 的)工具结果内容里挑出图片块, 供上提到 user 消息。"""
    if not isinstance(content, list):
        return []
    return [u for u in (_image_block_to_url(x) for x in content) if u]


def _msgs_claude2oai(messages):
    result = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": str(content)}]
        if role == "assistant":
            text_parts, tool_calls, reasoning = [], [], ""
            for b in blocks:
                if not isinstance(b, dict): continue
                if b.get("type") == "thinking" and b.get("thinking"): reasoning = b["thinking"]
                elif b.get("type") == "text" and b.get("text"): text_parts.append({"type": "text", "text": b.get("text", "")})
                elif b.get("type") == "tool_use":
                    tool_calls.append({
                        "id": b.get("id") or '', "type": "function",
                        "function": {"name": b.get("name", ""), "arguments": json.dumps(b.get("input", {}), ensure_ascii=False)}
                    })
            m = {"role": "assistant"}
            if reasoning: m["reasoning_content"] = reasoning
            if text_parts: m["content"] = text_parts
            elif not tool_calls: m["content"] = "."
            if tool_calls: m["tool_calls"] = tool_calls
            result.append(m)
        elif role == "user":
            text_parts = []
            for b in blocks:
                if not isinstance(b, dict): continue
                if b.get("type") == "tool_result":
                    if text_parts:
                        result.append({"role": "user", "content": text_parts})
                        text_parts = []
                    tr = b.get("content", "")
                    if isinstance(tr, list):
                        tr = "\n".join(x.get("text", "") for x in tr if isinstance(x, dict) and x.get("type") == "text")
                    result.append({"role": "tool", "tool_call_id": b.get("tool_use_id") or '', "content": tr if isinstance(tr, str) else str(tr)})
                    # tool_result 里夹带的图片块不能留在 tool 角色里(多数 OpenAI 兼容端点对
                    # tool 消息的 content 只收字符串, 直接 400), 上提到紧随其后的 user 消息;
                    # 文本仍留在 tool 消息内, 语义不变。以前这里只挑 text 块, 图片被静默丢弃。
                    _imgs = _collect_image_blocks(b.get("content"))
                    if _imgs:
                        result.append({"role": "user", "content": list(_imgs)})
                elif b.get("type") == "image":
                    src = b.get("source") or {}
                    if src.get("type") == "base64" and src.get("data"):
                        text_parts.append({"type": "image_url", "image_url": {"url": f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}"}})
                elif b.get("type") == "image_url": text_parts.append(b)
                elif b.get("type") == "text" and b.get("text"): text_parts.append({"type": "text", "text": b.get("text", "")})
            if text_parts: result.append({"role": "user", "content": text_parts})
        else: result.append(msg)
    return result


class BaseSession:
    # 会话协议能否携带图片块(类属性, 供工具层判"这一轮能不能附图"):
    # 基类走 ask(prompt: str) —— 整段消息被拼成一个字符串, 图块无处安放, 只能算 False。
    # 子类按自己的传输协议覆盖: NativeClaudeSession/NativeOAISession 传的是结构化消息列表。
    supports_images = False
    def __init__(self, cfg):
        self.api_key = cfg['apikey']
        self.api_base = cfg['apibase'].rstrip('/')
        self.model = cfg.get('model', '')
        default_context_win = 30000
        if 'deepseek' in self.model.lower():
            default_context_win = 70000; self.cut_msg_interval = 5; self.trim_keep_rate = 0.3
        self.context_win = cfg.get('context_win', default_context_win)
        self.history = []; self.lock = threading.Lock(); self.system = ""
        self.name = cfg.get('name', self.model)
        proxy = cfg.get('proxy'); 
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.max_retries = max(0, int(cfg.get('max_retries', 4)))
        self.verify = cfg.get('verify', True)
        self.stream = cfg.get('stream', True)
        default_ct, default_rt = (5, 40) if self.stream else (10, 240)
        self.connect_timeout = max(1, int(cfg.get('timeout', default_ct)))
        self.read_timeout = max(5, int(cfg.get('read_timeout', default_rt)))
        def _enum(key, valid):
            v = cfg.get(key); v = None if v is None else str(v).strip().lower()
            return v if not v or v in valid else print(f"[WARN] Invalid {key} {v!r}, ignored.")
        self.reasoning_effort = _enum('reasoning_effort', {'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'})   # max 镜像上游 247cb23(gpt-5.6+ 档位)
        self.service_tier = _enum('service_tier', {'auto', 'default', 'priority', 'flex'})
        self.thinking_type = _enum('thinking_type', {'adaptive', 'enabled', 'disabled'})
        self.thinking_budget_tokens = cfg.get('thinking_budget_tokens')
        # api_mode 每会话固定(运行期不变); responses/chat_completions 是独立协议, 出错不互相回退(见 _openai_stream)。
        mode = str(cfg.get('api_mode', 'chat_completions')).strip().lower().replace('-', '_')
        self.api_mode = 'responses' if mode in ('responses', 'response') else 'chat_completions'
        self.temperature = cfg.get('temperature', 1)
        self.max_tokens = cfg.get('max_tokens')
        self.default_ua = "claude-cli/2.1.152 (external, cli)"
        self.user_agent = cfg.get("user_agent", self.default_ua)
    def drop_stale_images(self):
        """任务边界: 把历史里的旧截图全部换成占位文字(keep=0)。返回被换掉的张数。

        为什么放在会话侧: 历史(self.history)属于这里, "图该不该留"的老化规则也在这里
        (见 age_image_blocks)。上层(agent handler)只需要"请求清掉旧图"这一个动作,
        不该自己去遍历并改写消息体 —— 那样两处策略会漂移(漏 image_url 块、占位文字不同),
        而且会绕过 trim_messages_history 的既有约定。"""
        return age_image_blocks(self.history, keep=0)

    def _apply_claude_thinking(self, payload):
        if self.thinking_type:
            thinking = {"type": self.thinking_type}
            if self.thinking_type == 'enabled':
                if self.thinking_budget_tokens is None: print("[WARN] thinking_type='enabled' requires thinking_budget_tokens, ignored.")
                else:
                    thinking["budget_tokens"] = self.thinking_budget_tokens; payload["thinking"] = thinking
            else: payload["thinking"] = thinking
        effort = _clamp_effort(self.reasoning_effort, self.model, proto='claude')   # Claude output_config.effort 窗=low..max; minimal→low, none→省略
        if effort: payload["output_config"] = {"effort": effort}
    def ask(self, prompt):
        def _ask_gen():
            with self.lock:
                self.history.append({"role": "user", "content": [{"type": "text", "text": prompt}]})
                trim_messages_history(self.history, self)
                messages = self.make_messages(self.history)
            content_blocks = None; content = ''
            gen = self.raw_ask(messages)
            try:
                while True: chunk = next(gen); content += chunk; yield chunk
            except StopIteration as e: content_blocks = e.value or []
            if len(content_blocks) > 1: print(f"[DEBUG BaseSession.ask] content_blocks: {content_blocks}")
            for block in (content_blocks or []):
                if block.get('type', '') == 'tool_use':
                    tu = {'name': block.get('name', ''), 'arguments': block.get('input', {})}
                    yield f'<tool_use>{json.dumps(tu, ensure_ascii=False)}</tool_use>'
            if content.strip() and not content.startswith("!!!Error:"): self.history.append({"role": "assistant", "content": [{"type": "text", "text": content}]})
        return _ask_gen()

def _keep_claude_block(b): return not isinstance(b, dict) or b.get("type") != "thinking" or b.get("signature")
def _drop_unsigned_thinking(messages):
    for m in messages:
        c = m.get("content")
        if isinstance(c, list): m["content"] = [b for b in c if _keep_claude_block(b)]
    return messages

def _ensure_thinking_blocks(messages, model):
    """deepseek needs thinking in history!"""
    if 'deepseek' not in model.lower(): return messages
    for m in messages:
        if m.get("role") != "assistant": continue
        c = m.get("content")
        if not isinstance(c, list): continue
        has_thinking = any(isinstance(b, dict) and b.get("type") == "thinking" for b in c)
        if not has_thinking: m["content"] = [{"type": "thinking", "thinking": "...", "signature": "placeholder"}, *c]
    return messages

class ClaudeSession(BaseSession):
    def raw_ask(self, messages):
        messages = _fix_messages(messages)
        if self.max_tokens is None: self.max_tokens = 8192
        model, beta = self.model, "prompt-caching-2024-07-31"
        if "[1m]" in model.lower():   # [1m] 后缀约定与 NativeClaudeSession 同构: 剥后缀 + 1M 上下文 beta 头
            beta += ",context-1m-2025-08-07"; model = model.replace("[1m]", "").replace("[1M]", "")
        headers = {"x-api-key": self.api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01", "anthropic-beta": beta}
        payload = {"model": model, "messages": messages, "max_tokens": self.max_tokens, "stream": self.stream}
        if self.temperature != 1: payload["temperature"] = self.temperature
        self._apply_claude_thinking(payload)
        if self.system: payload["system"] = [{"type": "text", "text": self.system, "cache_control": {"type": "persistent"}}]
        url = auto_make_url(self.api_base, "messages")
        parse_fn = (lambda r: _parse_claude_sse(r.iter_lines())) if self.stream else (lambda r: _parse_claude_json(r.json()))
        json_fn = lambda r: _parse_claude_json(r.json())
        return (yield from _stream_with_retry(self, url, headers, payload, parse_fn, json_fn))
    def make_messages(self, raw_list):
        msgs = _drop_unsigned_thinking([{"role": m['role'], "content": list(m['content'])} for m in raw_list])
        user_idxs = [i for i, m in enumerate(msgs) if m['role'] == 'user']
        for idx in user_idxs[-2:]:
            msgs[idx]["content"][-1] = dict(msgs[idx]["content"][-1], cache_control={"type": "ephemeral"})
        return msgs

class LLMSession(BaseSession):
    def raw_ask(self, messages): return (yield from _openai_stream(self, messages))
    def make_messages(self, raw_list): return _msgs_claude2oai(_fix_messages(raw_list))

def _fix_messages(messages):
    if not messages: return messages
    W = lambda c: c if isinstance(c, list) else [{"type": "text", "text": str(c)}]
    merged = []
    for m in messages:
        if m.get('role') not in ('user', 'assistant'): continue
        blocks = W(m.get('content', []))
        if merged and m['role'] == merged[-1]['role']:
            merged[-1]['content'] += [{"type": "text", "text": "\n"}] + blocks
        else:
            merged.append({"role": m['role'], "content": list(blocks)})
    while merged and merged[0]['role'] != 'user': merged.pop(0)
    if not merged: return []
    prev_uses = []
    for m in merged:
        c = m['content']
        if m['role'] == 'assistant':
            seen, out = set(), []
            for b in c:
                uid = b.get('id') if isinstance(b, dict) and b.get('type') == 'tool_use' else None
                if uid and uid in seen: continue
                if uid: seen.add(uid)
                out.append(b)
            m['content'] = out
            prev_uses = [b.get('id') for b in out if isinstance(b, dict) and b.get('type') == 'tool_use']
        else:
            got, rest = {}, []
            for b in c:
                tid = b.get('tool_use_id') if isinstance(b, dict) and b.get('type') == 'tool_result' else None
                if tid and tid in prev_uses and tid not in got: got[tid] = b
                elif isinstance(b, dict) and b.get('type') == 'tool_result': rest.append({"type": "text", "text": str(b.get('content', ''))})
                else: rest.append(b)
            m['content'] = [got.get(u) or {"type": "tool_result", "tool_use_id": u, "content": "(error)"} for u in prev_uses] + rest
            prev_uses = []
    return merged

class NativeClaudeSession(BaseSession):
    # 原生协议: raw_ask 收的是结构化消息列表, image 块原样进 payload —— 可以附图。
    supports_images = True
    native_ua = "claude-cli/2.1.152 (native, cli)"
    def __init__(self, cfg):
        super().__init__(cfg)
        self.fake_cc_system_prompt = cfg.get("fake_cc_system_prompt", False)
        self._session_id = str(uuid.uuid4())
        self._account_uuid = str(uuid.uuid4())
        self._device_id = uuid.uuid4().hex + uuid.uuid4().hex[:32]
        self.tools = None
        if self.user_agent == self.default_ua: self.user_agent = self.native_ua
    def raw_ask(self, messages):
        if self.max_tokens is None: self.max_tokens = 8192
        model = self.model
        messages = _fix_messages(messages)
        if 'claude' in model.lower(): messages = _drop_unsigned_thinking(messages)
        messages = _ensure_thinking_blocks(messages, self.model)
        beta_parts = ["claude-code-20250219", "interleaved-thinking-2025-05-14", "redact-thinking-2026-02-12", "context-management-2025-06-27", "prompt-caching-scope-2026-01-05", "effort-2025-11-24"]
        if "[1m]" in model.lower():
            beta_parts.insert(1, "context-1m-2025-08-07"); model = model.replace("[1m]", "").replace("[1M]", "")
        headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01",
            "anthropic-beta": ",".join(beta_parts), "anthropic-dangerous-direct-browser-access": "true",
            "user-agent": self.user_agent, "x-app": "cli"}
        headers.update({"Accept": "application/json", "X-Claude-Code-Session-Id": self._session_id, "X-Stainless-Arch": "x64", "X-Stainless-Lang": "js", "X-Stainless-OS": "Windows", "X-Stainless-Package-Version": "0.94.0", "X-Stainless-Retry-Count": "0", "X-Stainless-Runtime": "node", "X-Stainless-Runtime-Version": "v24.3.0", "X-Stainless-Timeout": "600"})
        if self.api_key.startswith("sk-ant-"): headers["x-api-key"] = self.api_key
        else: headers["authorization"] = f"Bearer {self.api_key}"
        payload = {"model": model, "messages": messages, "max_tokens": self.max_tokens, "stream": self.stream}
        #if self.fake_cc_system_prompt: payload["max_tokens"] = 64000
        if self.temperature != 1: payload["temperature"] = self.temperature
        self._apply_claude_thinking(payload)
        payload["context_management"] = {"edits": [{"type": "clear_thinking_20251015", "keep": "all"}]}; 
        if self.fake_cc_system_prompt:
            if 'thinking' not in payload: payload["thinking"] = {"type": "adaptive"}
            if 'output_config' not in payload: payload["output_config"] = {"effort": "medium"}
        payload["metadata"] = {"user_id": json.dumps({"device_id": self._device_id, "account_uuid": "", "session_id": self._session_id}, separators=(',', ':'))}
        if self.tools:
            claude_tools = openai_tools_to_claude(self.tools)
            tools = [dict(t) for t in claude_tools]; tools[-1]["cache_control"] = {"type": "ephemeral"}
            payload["tools"] = tools
        else: print("[ERROR] No tools provided for this session.")
        payload['system'] = [{"type": "text", "text": "You are Claude Code, Anthropic's official CLI for Claude.", "cache_control": {"type": "ephemeral"}}]
        if self.system:
            if self.fake_cc_system_prompt: payload["system"].append({"type": "text", "text": self.system})
            else: payload["system"] = [{"type": "text", "text": self.system}]
        user_idxs = [i for i, m in enumerate(messages) if m['role'] == 'user']
        for idx in user_idxs[-2:]:
            messages[idx] = {**messages[idx], "content": list(messages[idx]["content"])}
            messages[idx]["content"][-1] = dict(messages[idx]["content"][-1], cache_control={"type": "ephemeral"})
        url = auto_make_url(self.api_base, "messages") + '?beta=true'
        parse_fn = (lambda r: _parse_claude_sse(r.iter_lines())) if self.stream else (lambda r: _parse_claude_json(r.json()))
        json_fn = lambda r: _parse_claude_json(r.json())
        return (yield from _stream_with_retry(self, url, headers, payload, parse_fn, json_fn))

    def ask(self, msg):
        assert type(msg) is dict
        with self.lock:
            self.history.append(msg)
            trim_messages_history(self.history, self)
            messages = [{"role": m["role"], "content": list(m["content"])} for m in self.history]
        content_blocks = None
        gen = self.raw_ask(messages)
        try:
            while True: yield next(gen)
        except StopIteration as e: content_blocks = e.value or []
        if content_blocks and (_injected := _ensure_text_block(content_blocks)): yield _injected
        if content_blocks and not (len(content_blocks) == 1 and content_blocks[0].get("text", "").startswith("!!!Error:")):
            self.history.append({"role": "assistant", "content": content_blocks})
        text_parts = [b["text"] for b in content_blocks if b.get("type") == "text"]
        content = "\n".join(text_parts).strip()
        tool_calls = [MockToolCall(b["name"], b.get("input", {}), id=b.get("id", "")) for b in content_blocks if b.get("type") == "tool_use"]
        if not tool_calls: tool_calls, content = _parse_text_tool_calls(content)
        thinking_parts = [b["thinking"] for b in content_blocks if b.get("type") == "thinking"]
        thinking = "\n".join(thinking_parts).strip()
        if not thinking:
            think_pattern = r"<think(?:ing)?>(.*?)</think(?:ing)?>"
            think_match = re.search(think_pattern, content, re.DOTALL)
            if think_match:
                thinking = think_match.group(1).strip()
                content = re.sub(think_pattern, "", content, flags=re.DOTALL)
        return MockResponse(thinking, content, tool_calls, str(content_blocks))

class NativeOAISession(NativeClaudeSession):
    native_ua = "codex_cli_rs/0.1.2025062000 (Windows 11 10.0.26100; x86_64) Windows_Terminal"
    def raw_ask(self, messages):
        messages = _fix_messages(messages)
        messages = _ensure_thinking_blocks(messages, self.model)
        return (yield from _openai_stream(self, _msgs_claude2oai(messages)))

def openai_tools_to_claude(tools):
    """[{type:'function', function:{name,description,parameters}}] → [{name,description,input_schema}]."""
    result = []
    for t in tools:
        if 'input_schema' in t: result.append(t); continue  # 已是claude格式
        fn = t.get('function', t)
        result.append({'name': fn['name'], 'description': fn.get('description', ''),
            'input_schema': fn.get('parameters', {'type': 'object', 'properties': {}})})
    return result

class MockFunction:
    def __init__(self, name, arguments): self.name, self.arguments = name, arguments  
         
class MockToolCall:
    def __init__(self, name, args, id=''):
        arg_str = json.dumps(args, ensure_ascii=False) if isinstance(args, (dict, list)) else (args or '{}')
        self.function = MockFunction(name, arg_str); self.id = id

class MockResponse:
    def __init__(self, thinking, content, tool_calls, raw, stop_reason='end_turn'):
        self.thinking = thinking; self.content = content          
        self.tool_calls = tool_calls; self.raw = raw
        self.stop_reason = 'tool_use' if tool_calls else stop_reason
    def __repr__(self):    
        return f"<MockResponse thinking={bool(self.thinking)}, content='{self.content}', tools={bool(self.tool_calls)}>"

def _keep_content_block(c):
    """图片块没有 text 字段: 用"去空白块"过滤时必须单独放行, 否则附图会被静默删掉。"""
    if not isinstance(c, dict):
        return False
    if c.get("type") in ("image", "image_url"):
        return True
    return bool(str(c.get("text", "")).strip())


class ToolClient:
    # 文本协议客户端: chat() 把 messages 压成 _build_protocol_prompt(...) 的一整段字符串再
    # backend.ask(str) —— 图片块进不来（进来也只是一段 Python repr/base64 文本）。工具层据此
    # 判"这一轮不要附图"。别再按"类型名白名单"猜: 那个口径已经把 NativeOAISession 判错过。
    supports_images = False
    def __init__(self, backend, auto_save_tokens=True):
        self.backend = backend
        self.auto_save_tokens = auto_save_tokens
        self.last_tools = ''
        self.name = self.backend.name
        self.total_cd_tokens = 0
        self.log_path = None

    def chat(self, messages, tools=None):
        tools = json.loads(json.dumps(tools, ensure_ascii=False)) if tools else tools
        for t in tools or []:
            f = t.get('function', {})
            if f.get('name') == 'file_write':
                props = f.get('parameters', {}).get('properties', {})
                props.pop('content', None)
                extra = '. Content must be placed in <file_content> tags in reply body, not in args'
                if extra not in f.get('description', ''): f['description'] = f.get('description', '') + extra
                break
        full_prompt = self._build_protocol_prompt(messages, tools)
        print("Full prompt length:", len(full_prompt), 'chars')
        gen = self.backend.ask(full_prompt)
        _write_llm_log('Prompt', full_prompt, self.log_path)
        raw_text = ''
        for chunk in gen:
            raw_text += chunk; yield chunk
        _write_llm_log('Response', raw_text, self.log_path)
        return self._parse_mixed_response(raw_text)

    def _prepare_tool_instruction(self, tools):
        tool_instruction = ""
        if not tools: return tool_instruction
        tools_json = json.dumps(tools, ensure_ascii=False, separators=(',', ':'))
        _en = os.environ.get('GA_LANG') == 'en'
        if _en:
            tool_instruction = f"""
### Interaction Protocol (must follow strictly, always in effect)
Follow these steps to think and act:
1. **Think**: Analyze the current situation and strategy inside `<thinking>` tags.
2. **Summarize**: Output a minimal one-line (<30 words) physical snapshot in `<summary>`: new info from last tool result + current tool call intent. This goes into long-term working memory. Must contain real information, no filler.
3. **Act**: If you need to call tools, output one or more **<tool_use> blocks** after your reply, then stop.
"""
        else:
            tool_instruction = f"""
### 交互协议 (必须严格遵守，持续有效)
请按照以下步骤思考并行动：
1. **思考**: 在 `<thinking>` 标签中先进行思考，分析现状和策略。
2. **总结**: 在 `<summary>` 中输出*极为简短*的高度概括的单行（<30字）物理快照，包括上次工具调用结果产生的新信息+本次工具调用意图。此内容将进入长期工作记忆，记录关键信息，严禁输出无实际信息增量的描述。
3. **行动**: 如需调用工具，请在回复正文之后输出一个（或多个）**<tool_use>块**，然后结束。
"""
        tool_instruction += f'\nFormat: ```<tool_use>{{"name": "tool_name", "arguments": {{...}}}}</tool_use>```\n\n### Tools (mounted, always in effect):\n{tools_json}\n'
        if self.auto_save_tokens and self.last_tools == tools_json:
            tool_instruction = "\n### Tools: still active, **ready to call**. Protocol unchanged.\n" if _en else "\n### 工具库状态：持续有效（code_run/file_read等），**可正常调用**。调用协议沿用。\n"
        else: self.total_cd_tokens = 0
        self.last_tools = tools_json
        return tool_instruction

    def _build_protocol_prompt(self, messages, tools):
        system_content = next((m['content'] for m in messages if m['role'].lower() == 'system'), "")
        history_msgs = [m for m in messages if m['role'].lower() != 'system']
        tool_instruction = self._prepare_tool_instruction(tools)
        system = ""; user = ""
        if system_content: system += f"{system_content}\n"
        system += f"{tool_instruction}"
        for m in history_msgs:
            role = "USER" if m['role'] == 'user' else "ASSISTANT"
            user += f"=== {role} ===\n"
            for tr in m.get('tool_results', []): user += f'<tool_result>{tr["content"]}</tool_result>\n'
            user += str(m['content']) + "\n"
            self.total_cd_tokens += len(user) // 3
        if self.total_cd_tokens > 9000: self.last_tools = ''
        user += "=== ASSISTANT ===\n" 
        return system + user

    def _parse_mixed_response(self, text):
        remaining_text = text; thinking = ''
        think_match = re.search(r"<think(?:ing)?>(.*?)</think(?:ing)?>", text, re.DOTALL)
        if think_match:
            thinking = think_match.group(1).strip()
            remaining_text = re.sub(r"<think(?:ing)?>(.*?)</think(?:ing)?>", "", remaining_text, flags=re.DOTALL)
        tool_calls, remaining_text = _parse_text_tool_calls(remaining_text)
        if not tool_calls:
            json_strs = []; errors = []
            if '<tool_use>' in remaining_text:
                weaktoolstr = remaining_text.split('<tool_use>')[-1].strip().strip('><')
                json_str = weaktoolstr if weaktoolstr.endswith('}') else ''
                if json_str == '' and '```' in weaktoolstr and weaktoolstr.split('```')[0].strip().endswith('}'):
                    json_str = weaktoolstr.split('```')[0].strip()
                if json_str: json_strs.append(json_str)
                remaining_text = remaining_text.replace('<tool_use>'+weaktoolstr, "")
            elif '"name":' in remaining_text and '"arguments":' in remaining_text:
                json_match = re.search(r'\{.*"name":.*\}', remaining_text, re.DOTALL)
                if json_match:
                    json_strs.append(json_match.group(0).strip())
                    remaining_text = remaining_text.replace(json_match.group(0), "").strip()
            for json_str in json_strs:
                try:
                    data = tryparse(json_str)
                    func_name = data.get('name') or data.get('function') or data.get('tool')
                    args = _tool_arguments(data)
                    if func_name: tool_calls.append(MockToolCall(func_name, args))
                except json.JSONDecodeError:
                    errors.append(f'Failed to parse tool_use JSON: {json_str[:200]}')
                    self.last_tools = ''
                except: pass
            if not tool_calls:
                for e in errors:
                    print(f"[Warn] {e}"); tool_calls.append(MockToolCall('bad_json', {'msg': e}))
        return MockResponse(thinking, remaining_text.strip(), tool_calls, text)

def _tool_arguments(data):
    """Preserve explicit argument objects, including empty ones, or flat tool fields."""
    for key in ('arguments', 'args', 'input', 'params', 'parameters'):
        if key in data:
            value = data[key]
            if not isinstance(value, dict):
                raise ValueError('Tool arguments must be an object')
            return value
    return {k: v for k, v in data.items() if k not in ('name', 'function', 'tool', 'id')}


def _parse_text_tool_calls(content):
    """Fallback: extract tool calls from text when model doesn't use native tool_use blocks."""
    tcs = []
    # try JSON array: [{"type":"tool_use", "name":..., "input":...}]
    _jp = next((p for p in ['[{"type":"tool_use"', '[{"type": "tool_use"'] if p in content), None)
    if _jp and content.endswith('}]'):
        try:
            idx = content.index(_jp); raw = json.loads(content[idx:])
            tcs = [MockToolCall(b["name"], b.get("input", {}), id=b.get("id", "")) for b in raw if b.get("type") == "tool_use"]
            return tcs, content[:idx].strip()
        except: pass
    # try XML tags: <tool_call>{"name":..., "arguments":...}</tool_call>
    _xp = r"<(?:tool_use|tool_call)>\s*(\{(?:(?!<(?:tool_use|tool_call)>).)*?)(?:</(?:tool_use|tool_call)>|(?=\r?\n[ \t]*```[ \t]*(?:\r?\n|$))|$)"
    for s in re.findall(_xp, content, re.DOTALL):
        try:
            d = tryparse(s.strip()); name = d.get('name')
            args = _tool_arguments(d)
            if not isinstance(name, str) or not name.strip():
                raise ValueError('Tool name must be a nonempty string')
            tcs.append(MockToolCall(name, args))
        except (ValueError, TypeError, AttributeError):
            # Never execute a partial batch: a repair could repeat its side effects.
            error = 'Malformed tool-call JSON. No tools in this reply were executed. Resend the complete calls with valid JSON objects and closing braces.'
            return [MockToolCall('bad_json', {'msg': error})], content
    if tcs: content = re.sub(_xp, "", content, flags=re.DOTALL).strip()
    return tcs, content

def _ensure_text_block(blocks):
    """If response has thinking but no text block, inject a synthetic summary from thinking's first line."""
    if any(b.get("type") == "text" for b in blocks): return None
    th = next((b.get("thinking", "") for b in blocks if b.get("type") == "thinking"), "")
    if not th: return None
    line = th.strip().split('\n', 1)[0]
    txt = "<summary>" + (line[:60] + '...' if len(line) > 60 else line) + "</summary>"
    blocks.insert(1, {"type": "text", "text": txt})
    return txt

def _write_llm_log(label, content, log_path=None):
    if not log_path:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'temp/model_responses/model_responses_{os.getpid()}.txt')
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(log_path, 'a', encoding='utf-8', errors='replace') as f:
        f.write(f"=== {label} === {ts}\n{content}\n\n")

def tryparse(json_str):
    try: return json.loads(json_str)
    except: pass
    json_str = json_str.strip().strip('`').replace('json\n', '', 1).strip()
    try: return json.loads(json_str)
    except: pass
    try: return json.loads(json_str[:-1])
    except: pass
    if '}' in json_str: json_str = json_str[:json_str.rfind('}') + 1]
    return json.loads(json_str)

class MixinSession:
    """Multi-session fallback with spring-back to primary."""
    def __init__(self, all_sessions, cfg):
        self._retries, self._base_delay = cfg.get('max_retries', 3), cfg.get('base_delay', 1.5)
        self._spring_sec = cfg.get('spring_back', 300)
        self._sessions = [all_sessions[i].backend if isinstance(i, int) else 
                          next(s.backend for s in all_sessions if type(s) is not dict and s.backend.name == i) for i in cfg.get('llm_nos', [])]
        is_native = lambda s: 'Native' in s.__class__.__name__
        groups = {is_native(s) for s in self._sessions}
        assert len(groups) == 1, f"MixinSession: sessions must be in same group (Native or non-Native), got {[type(s).__name__ for s in self._sessions]}"
        self.name = cfg.get('name') or '|'.join(s.name for s in self._sessions)   # 可命名(如 'auto') → UI /llm 稳定选中; 未命名回退成员名拼接
        import copy; self._sessions = [copy.copy(s) for s in self._sessions]
        for s in self._sessions: s.max_retries = 0
        self._orig_raw_asks = [s.raw_ask for s in self._sessions]
        self._sessions[0].raw_ask = self._raw_ask
        self._cur_idx, self._switched_at = 0, 0.0
    def __getattr__(self, name): return getattr(self._sessions[0], name)
    _BROADCAST_ATTRS = frozenset({'system', 'tools', 'temperature', 'max_tokens', 'reasoning_effort', 'history', 'stream', 'read_timeout'})
    def __setattr__(self, name, value):
        if name in self._BROADCAST_ATTRS:
            for s in self._sessions:
                v = openai_tools_to_claude(value) if name == 'tools' and type(s) is NativeClaudeSession else value
                setattr(s, name, v)
        else: object.__setattr__(self, name, value)
    @property
    def primary(self): return self._sessions[0]
    @property
    def model(self): return getattr(self._sessions[self._cur_idx], 'model', None)
    def _pick(self):
        if self._cur_idx and time.time() - self._switched_at > self._spring_sec: self._cur_idx = 0
        return self._cur_idx
    def _raw_ask(self, *args, **kwargs):
        base, n = self._pick(), len(self._sessions)
        test_error = lambda x: isinstance(x, str) and x.lstrip().startswith(('!!!Error:', '[Error:'))
        for attempt in range(self._retries + 1):
            idx = (base + attempt) % n
            gen = self._orig_raw_asks[idx](*args, **kwargs)
            print(f'[MixinSession] Using session ({self._sessions[idx].name})')
            last_chunk, return_val, yielded = None, [], False
            try:
                while True:
                    chunk = next(gen); last_chunk = chunk
                    if not yielded and test_error(chunk): continue
                    yield chunk; yielded = True
            except StopIteration as e: return_val = e.value or []
            is_err = test_error(last_chunk)
            if not is_err:
                if attempt > 0: self._cur_idx = idx; self._switched_at = time.time()
                elif isinstance(last_chunk, str) and '[!!! 流异常中断' in last_chunk and n > 1:
                    self._cur_idx = (idx + 1) % n; self._switched_at = time.time()
                    print(f'[MixinSession] Partial failure, next call → s{self._cur_idx} ({self._sessions[self._cur_idx].name})')
                return return_val
            if attempt >= self._retries:
                yield last_chunk; return return_val
            nxt = (base + attempt + 1) % n
            if nxt == base:  # full round failed, delay before next
                rnd = (attempt + 1) // n
                delay = min(30, self._base_delay * (1.5 ** rnd))
                print(f'[MixinSession] {last_chunk[:80]}, round {rnd} exhausted, retry in {delay:.1f}s')
                time.sleep(delay)
            else: print(f'[MixinSession] {last_chunk[:80]}, retry {attempt+1}/{self._retries} (s{idx}→s{nxt})')

THINKING_PROMPT_ZH = """
### 行动规范（持续有效）
每次回复（含工具调用轮）都先在回复文字中包含一个<summary></summary> 中输出极简单行（<30字）物理快照：上次结果新信息+本次意图。此内容进入长期工作记忆。
\n**若用户需求未完成，必须进行工具调用！**
""".strip()
THINKING_PROMPT_EN = """
### Action Protocol (always in effect)
The reply body should first include a minimal one-line (<30 words) physical snapshot in <summary></summary>: new info from last result + current intent. This goes into long-term working memory.
\n**If the user's request is not yet complete, tool calls are required!**
""".strip()

class NativeToolClient:
    # 原生协议客户端: chat() 把 messages 里的结构化块原样合并后交给 backend.ask(dict),
    # 图片块(_keep_content_block 放行)能一路到达 payload —— 可以附图。
    supports_images = True
    @staticmethod
    def _thinking_prompt(): return THINKING_PROMPT_EN if os.environ.get('GA_LANG') == 'en' else THINKING_PROMPT_ZH
    def __init__(self, backend):
        self.backend = backend
        self.backend.system = self._thinking_prompt()
        self.name = self.backend.name
        self._pending_tool_ids = []
        self.log_path = None
    def set_system(self, extra_system):
        combined = f"{extra_system}\n\n{self._thinking_prompt()}" if extra_system else self._thinking_prompt()
        if combined != self.backend.system: print(f"[Debug] Updated system prompt, length {len(combined)} chars.")
        self.backend.system = combined
    def chat(self, messages, tools=None):
        if tools: self.backend.tools = tools
        if not self.backend.history: self._pending_tool_ids = []
        combined_content = []; resp = None; tool_results = []
        for msg in messages:
            c = msg.get('content', '')
            if msg['role'] == 'system': 
                self.set_system(c); continue
            if isinstance(c, str): combined_content.append({"type": "text", "text": c})
            elif isinstance(c, list): combined_content.extend(c)
            if msg['role'] == 'user' and msg.get('tool_results'): tool_results.extend(msg['tool_results'])
        tr_id_set = set();  tool_result_blocks = []
        for tr in tool_results:
            tool_use_id, content = tr.get("tool_use_id", ""), tr.get("content", "")
            tr_id_set.add(tool_use_id)
            if tool_use_id: tool_result_blocks.append({"type": "tool_result", "tool_use_id": tool_use_id, "content": tr.get("content", "")})
            else: combined_content = [{"type": "text", "text": f'<tool_result>{content}</tool_result>'}] + combined_content
        for tid in self._pending_tool_ids:
            if tid not in tr_id_set: tool_result_blocks.append({"type": "tool_result", "tool_use_id": tid, "content": ""})
        self._pending_tool_ids = []
        # Filter whitespace-only text blocks that cause 400 on strict API proxies
        filtered_content = [c for c in combined_content if _keep_content_block(c)]
        final_content = tool_result_blocks + filtered_content
        if not final_content: final_content = [{"type": "text", "text": "."}]
        merged = {"role": "user", "content": final_content}
        _write_llm_log('Prompt', json.dumps(merged, ensure_ascii=False, indent=2), self.log_path)
        gen = self.backend.ask(merged)
        try:
            while True: 
                chunk = next(gen); yield chunk
        except StopIteration as e: resp = e.value
        if resp: _write_llm_log('Response', resp.raw, self.log_path)
        if resp and hasattr(resp, 'tool_calls') and resp.tool_calls: self._pending_tool_ids = [tc.id for tc in resp.tool_calls]
        return resp

def resolve_session(cfg_name):
    cfg = reload_mykeys()[0].get(cfg_name)
    if not cfg: raise ValueError(f"Config '{cfg_name}' not in mykey")
    if 'native' in cfg_name: return (NativeClaudeSession if 'claude' in cfg_name else NativeOAISession)(cfg=cfg)
    if 'claude' in cfg_name: return ClaudeSession(cfg=cfg)
    return LLMSession(cfg=cfg) if 'oai' in cfg_name else None

def resolve_client(cfg_name):
    s = resolve_session(cfg_name)
    return (NativeToolClient(s) if isinstance(s, (NativeClaudeSession, NativeOAISession)) else ToolClient(s)) if s else None

def fast_ask(prompt, cfg_name):
    sess = resolve_session(cfg_name)
    if not sess: raise ValueError(f"fast_ask: '{cfg_name}' unsupported")
    return "".join(sess.raw_ask([{"role": "user", "content": prompt}]))
