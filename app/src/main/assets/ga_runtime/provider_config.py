"""Provider parsing and transformations. Inputs are not modified; no I/O or global session state."""
import ast
import re

def _py_repr(v):
    return repr(v)


def _cfg_type(var, cfg):
    if cfg.get('type') in ('claude', 'oai'): return cfg['type']   # UI 显式类型优先
    if 'claude' in str(var) or cfg.get('thinking_type') or cfg.get('fake_cc_system_prompt'):
        return 'claude'
    return 'oai'


def _var_type(var):
    """协议类⟺块变量名(llmcore.resolve_session 按 var 名分发, 'claude' 优先于 'oai'/'native'), 判型必须与之同构。"""
    return 'claude' if 'claude' in str(var) else 'oai'


_FIELD_RE = re.compile(r"^(\s*)(['\"])([^'\"]+)\2(\s*:\s*)(.*?)(,?\s*)$")   # 块体一行 = 一个 `'key': value,` 字段


def _line_patchable(line):
    """块体行能否被 _patch_block_lines 单独改写: 空行/注释恒可; 字段行要求 value 在本行就是完整表达式
    (`'models': [` 这种跨行列表的首行不是 → 逐行改写会留下半截尾巴)。"""
    s = line.strip()
    if not s or s.startswith('#'): return True
    m = _FIELD_RE.match(line)
    if not m: return False
    try: ast.parse(m.group(5).strip(), mode='eval'); return True
    except SyntaxError: return False

def _drop_duplicate_blocks(lines, blocks, keep):
    """同一导出身份(ename)出现多块时只保留 keep 的内容(文件中最后一块 = Python 同名变量的实际生效值), 删掉影子块;
    保留内容落在**最早那块的位置**——/config 的 item_N 按文件顺序编号, UI 的 active.pid 就是它, 顺序一变活跃服务商就跑偏。
    影子块来源: 旧版按正则找不到非规范块的 `}` → 判为"不存在"→ 追加新块。留着它, 下次仍可能被误当成块边界。"""
    lines = list(lines)
    dups = [b for b in blocks if b['ename'] == keep['ename'] and b is not keep and not b['is_mixin']
            and 'workflow' not in b['var'] and any(x in b['var'] for x in ('api', 'config'))]
    if not dups: return lines, False
    kept = lines[keep['start']:keep['end'] + 1]
    first = min(dups + [keep], key=lambda x: x['start'])
    for b in sorted(dups + [keep], key=lambda x: x['start'], reverse=True):
        del lines[b['start']:b['end'] + 1]
        if b is not first and b['start'] < len(lines) and b['start'] > 0 and not lines[b['start']].strip() and not lines[b['start'] - 1].strip():
            del lines[b['start']]                                       # 删块后留下的连续空行收成一行
    lines[first['start']:first['start']] = kept
    return lines, True


def _find_mykey_blocks(lines):
    """Parse top-level mykey.py config blocks: `var = { ... }`, multi-line OR single-line.
    Identity (name/model/is_mixin) is read from the block's TOP-LEVEL keys via ast.literal_eval —
    so a top-level 'llm_nos' list (真 mixin) is detected but `plan_llm_nos`(x_workflow) is NOT misread
    as a mixin, and a nested sub-dict's 'name'/'model' never poisons the block identity.
    ename = name|model|var = the SAME identity _export_config shows the UI (matches name-less glm too)."""
    def _regex_f(text, key):
        m = re.search(r"['\"]" + key + r"['\"]\s*:\s*['\"]([^'\"]*)['\"]", text)
        return m.group(1) if m else None
    def _ident(src, body_lines, var):
        try:
            d = ast.literal_eval(src)
            if isinstance(d, dict):
                nm = d.get('name'); md = d.get('model')
                return (nm if isinstance(nm, str) else None,
                        md if isinstance(md, str) else None,
                        ('mixin' in var) or isinstance(d.get('llm_nos'), list))
        except Exception:
            pass
        nm = md = None; mix = 'mixin' in var               # 解析失败(含非字面量)时的尽力兜底
        for ln in body_lines:
            nm = nm or _regex_f(ln, 'name'); md = md or _regex_f(ln, 'model')
            if re.search(r"['\"]llm_nos['\"]\s*:", ln): mix = True
        return nm, md, mix
    blocks = []
    i, n = 0, len(lines)
    hdr_multi = re.compile(r'^(\w+)\s*=\s*\{\s*$')
    hdr_single = re.compile(r'^(\w+)\s*=\s*(\{.*\})\s*,?\s*$')
    closing = re.compile(r'^\}\s*,?\s*$')
    # 首选 ast: 顶层 `var = {...}` 赋值的 (lineno, end_lineno) 就是块边界, 与 `}` 是否独占一行、是否尾随逗号无关。
    # 正则扫描只在文件本身不可解析时兜底(下面的 while)。canonical=header 独占一行且 `}` 独占一行——只有这种块才允许逐行补丁,
    # 其余(单行块 / 收尾 `}` 与字段同行 / tuple 写法)一律走 _rebuild_single_line_block 整块重建。
    try:
        tree = ast.parse('\n'.join(lines))
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name): continue
            val = node.value
            if isinstance(val, ast.Tuple) and len(val.elts) == 1: val = val.elts[0]
            if not isinstance(val, ast.Dict): continue
            st, en, var = node.lineno - 1, node.end_lineno - 1, node.targets[0].id
            body_src = re.sub(r'^\w+\s*=\s*', '', '\n'.join(lines[st:en + 1]), count=1).strip().rstrip(',')
            name, model, is_mixin = _ident(body_src, lines[st:en + 1], var)
            blocks.append({'start': st, 'end': en, 'var': var, 'name': name, 'model': model,
                           'is_mixin': is_mixin, 'ename': name or model or var,
                           'canonical': st < en and bool(hdr_multi.match(lines[st])) and bool(closing.match(lines[en]))
                                        and all(_line_patchable(x) for x in lines[st + 1:en])})
        return blocks
    except SyntaxError:
        pass
    while i < n:
        ms = hdr_single.match(lines[i])           # 单行 dict(如旧版 mixin_config={...}): start==end, 便于整块删/替
        if ms:
            var, body = ms.group(1), ms.group(2)
            name, model, is_mixin = _ident(body, [body], var)
            blocks.append({'start': i, 'end': i, 'var': var, 'name': name, 'model': model,
                           'is_mixin': is_mixin, 'ename': name or model or var, 'canonical': False})
            i += 1; continue
        m = hdr_multi.match(lines[i])
        if not m:
            i += 1; continue
        st, var = i, m.group(1); j = i + 1
        while j < n and not re.match(r'^\}\s*,?\s*$', lines[j]):
            j += 1
        if j >= n:
            i += 1; continue
        body_lines = lines[st + 1:j]
        name, model, is_mixin = _ident('{\n' + '\n'.join(body_lines) + '\n}', body_lines, var)
        blocks.append({'start': st, 'end': j, 'var': var, 'name': name, 'model': model,
                       'is_mixin': is_mixin, 'ename': name or model or var, 'canonical': True})
        i = j + 1
    return blocks


def _format_mykey_block(var, cfg):
    preferred = ['name','apikey','apibase','model','api_mode','thinking_type','fake_cc_system_prompt','user_agent','reasoning_effort','max_tokens','proxy','llm_nos','max_retries','read_timeout','timeout','base_delay','spring_back']
    keys = [k for k in preferred if k in cfg] + [k for k in cfg.keys() if k not in preferred]
    out = [f'{var} = {{']
    for k in keys:
        out.append(f"    {k!r}: {_py_repr(cfg[k])},")
    out.append('}')
    return out


_UI_MANAGED_OPT = ('fake_cc_system_prompt', 'user_agent', 'max_retries', 'read_timeout', 'timeout', 'connect_timeout', 'max_tokens', 'api_mode', 'proxy', 'type', 'enabled', 'label', 'reasoning_effort')   # 编辑器完全掌管的可选字段: 重存时缺失=用户关掉/清空 → 必须从块中删除(否则透传CC/UA/超时等"关不掉")。connect_timeout/type 是死键(编辑器只写 live 的 timeout; type 只决定 var 名不落块), 列入→编辑旧块时顺带清理。enabled: 前端仅在停用时发 False; 重新启用=载荷缺失→删残留行, 缺省即启用; reasoning_effort: 推理强度选「默认」时载荷不带该键, 必须删行, 否则界面显示默认而后端仍沿用旧档位


def _patch_block_lines(lines, block, cfg, drop_absent=None):
    """Patch fields in a matched block: overwrite present, insert missing before the closing brace,
    and DELETE any 'drop_absent' (UI-managed) key that's absent from cfg — so a save is authoritative
    for the fields the editor controls (turning a toggle off / clearing a field removes its line).
    Unmanaged keys, comments and blank lines inside the block are preserved verbatim."""
    st, en = block['start'], block['end']
    drop = set(drop_absent or ()) - set(cfg)        # 受管字段在本次保存里缺失 → 视为用户清空, 删行
    done, body = set(), []
    for idx in range(st + 1, en):
        m = _FIELD_RE.match(lines[idx])
        if m:
            key = m.group(3)
            if key in drop: continue
            if key in cfg:
                body.append(f"{m.group(1)}{m.group(2)}{key}{m.group(2)}{m.group(4)}{_py_repr(cfg[key])},")
                done.add(key); continue
        body.append(lines[idx])
    for key, val in cfg.items():
        if key not in done:
            body.append(f"    {key!r}: {_py_repr(val)},")
    return lines[:st + 1] + body + lines[en:]


def _reindex_mykey_blocks(lines, id_key):
    """改行后重新定位块表: id_key='name' 按字面 name 字段索引(无 name 的块不进索引, 全量同步语义);
    id_key='ename' 按导出身份(name|model|var, 恒非空)索引(补丁语义)。返回 (blocks, index, used_vars)。"""
    blocks = _find_mykey_blocks(lines)
    if id_key == 'name':
        idx = {b['name']: b for b in blocks if b.get('name')}
    else:
        idx = {b['ename']: b for b in blocks}
    return blocks, idx, {b['var'] for b in blocks}
