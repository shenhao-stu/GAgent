"""mykey.py 写入器(android_entry._write_mykey_patch / _write_mykey_py_from_dict / _provider_save / _provider_delete)的 PC 侧回归.
不 import android_entry(顶层带 Android 依赖): 用 ast 只抠出写入器相关的顶层 def/赋值, 在干净命名空间里执行.
每个 case = 一份 mykey.py 文本 + 一次操作 → 断言不变量:
  I1 结果可 py_compile;  I2 目标块唯一(同 ename 不出现两块);  I3 块顺序不变(新块只在末尾/mixin 只在顶);
  I4 其它块逐字节不动;  I5 幂等(同操作再做一次文本不变);  I6 非字面量块不被静默丢字段(显式报错).
用法: python tools/test_mykey_writer.py"""
import ast, os, py_compile, re, sys, tempfile, threading, secrets, json
import importlib.util
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'app', 'src', 'main', 'assets', 'ga_runtime', 'android_entry.py')
NAMES = ['_mykey_py_path', '_py_repr', '_cfg_type', '_var_type', '_retype_block_var', '_FIELD_RE', '_line_patchable',
         '_rebuild_single_line_block', '_drop_duplicate_blocks', '_find_mykey_blocks', '_format_mykey_block', '_UI_MANAGED_OPT',
         '_patch_block_lines', '_mykey_lock', '_reindex_mykey_blocks', '_write_mykey_file', '_write_mykey_py_from_dict',
         '_write_mykey_patch', '_provider_save', '_provider_delete']

def load_writer():
    pure = os.path.join(os.path.dirname(SRC), 'provider_config.py')
    spec = importlib.util.spec_from_file_location('provider_config_under_test', pure)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    tree = ast.parse(open(SRC, encoding='utf-8').read())
    want = set(NAMES); picked = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in want: picked.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in want for t in node.targets): picked.append(node)
    got = {n.name if isinstance(n, ast.FunctionDef) else n.targets[0].id for n in picked}
    got.update(name for name in want if hasattr(module, name))
    assert got == want, f'missing writer dependencies: {want - got}'
    g = {'os': os, 're': re, 'ast': ast, 'json': json, 'py_compile': py_compile, 'threading': threading, 'secrets': secrets}
    g.update({name: getattr(module, name) for name in want if hasattr(module, name)})
    exec(compile(ast.Module(body=picked, type_ignores=[]), SRC, 'exec'), g)
    g['_atomic_write'] = lambda path, text: open(path, 'w', encoding='utf-8', newline='\n').write(text)
    g['_refresh_mykeys'] = lambda: None
    g['_load_mykeys'] = None
    return g

W = load_writer()
def with_file(text):
    d = tempfile.mkdtemp(); p = os.path.join(d, 'mykey.py')
    open(p, 'w', encoding='utf-8', newline='\n').write(text); W['_mykey_py_path'] = lambda: p; return p
def read(p): return open(p, encoding='utf-8').read()
def blocks(p): return W['_find_mykey_blocks'](read(p).splitlines())
def enames(p): return [b['ename'] for b in blocks(p)]
def load(p):
    ns = {}; exec(read(p), ns); return {k: v for k, v in ns.items() if isinstance(v, dict) and not k.startswith('_')}
def by_name(p, name): return next(v for v in load(p).values() if v.get('name') == name)
def check_invariants(p, before_enames, touched, appended=(), removed=()):
    py_compile.compile(p, doraise=True)                                                   # I1
    en = enames(p); assert len(en) == len(set(en)), f'I2 duplicate enames {en}'          # I2
    expect = [e for e in before_enames if e not in removed] + list(appended)
    assert en == expect, f'I3 order {en} != {expect}'                                     # I3

CODEX_OLD = """
native_oai_config_fixture = {
    'name': 'Fixture Provider',
    'apikey': 'sk-ga-1',
    'apibase': 'https://relay.example/v1',
    'model': 'auto-flash',
    'models': ['auto-flash'],
}

native_oai_config = {
    'name': 'Codex',
    'apikey': 'sk-old',
    'apibase': 'https://sub2api.example/v1',
    'models': ['gpt-5.6', 'gpt-5.6-sol'],
    'model': 'gpt-5.6', 'read_timeout': 120}

native_claude_config = {
    'name': 'KIMI',
    'apikey': 'sk-k',
    'apibase': 'https://cn.example',
    'thinking_type': 'adaptive',
    'models': ['kimi-k3'],
    'model': 'kimi-k3',
    'reasoning_effort': 'max'}

native_oai_config = {
    'name': 'Codex',
    'apikey': 'sk-old',
    'apibase': 'https://sub2api.example/v1',
    'model': 'gpt-5.6-sol',
    'models': ['gpt-5.6', 'gpt-5.6-sol'],
}
"""
CANON = """
native_oai_config_a = {
    'name': 'A',
    'apikey': 'sk-a',
    'apibase': 'https://a.example/v1',
    # 用户手写注释: 保留
    'model': 'm1',
    'models': ['m1', 'm2'],
    'read_timeout': 120,
    'custom_note': 'keep-me',
}

native_claude_config_b = {
    'name': 'B',
    'apikey': 'sk-b',
    'apibase': 'https://b.example',
    'model': 'c1',
    'models': ['c1'],
}
"""
codex_cfg = lambda **kw: dict({'name': 'Codex', 'apikey': 'sk-new', 'apibase': 'https://sub2api.example/v1', 'model': 'gpt-6-astra',
                               'models': ['gpt-5.6', 'gpt-5.6-sol', 'gpt-6-astra'], 'type': 'oai', 'reasoning_effort': 'high', 'read_timeout': 240}, **kw)
def load_text_block(text, name):
    ns = {}; exec(text, ns); return next(v for v in ns.values() if isinstance(v, dict) and v.get('name') == name)
RESULTS = []
def case(name):
    def deco(fn):
        try: fn(); RESULTS.append((name, True, ''))
        except Exception as e: RESULTS.append((name, False, f'{type(e).__name__}: {e}'))
        return fn
    return deco

@case('C1 inline-`}` 旧块(设备原文) + 同名影子块: 保存重建为单块, 位置不变, 其余块不动')
def _():
    p = with_file(CODEX_OLD); before = read(p)
    W['_write_mykey_patch']([('native_oai_config', codex_cfg())], [])
    py_compile.compile(p, doraise=True)
    en = enames(p); assert en == ['Fixture Provider', 'Codex', 'KIMI'], en                        # I2+I3: 影子块消失, Codex 留在原位
    cx = by_name(p, 'Codex'); assert cx['model'] == 'gpt-6-astra' and 'gpt-6-astra' in cx['models'] and cx['read_timeout'] == 240
    assert all(b['canonical'] for b in blocks(p) if b['ename'] == 'Codex')
    for nm in ('Fixture Provider', 'KIMI'): assert by_name(p, nm) == load_text_block(before, nm)   # I4
    t1 = read(p); W['_write_mykey_patch']([('native_oai_config', codex_cfg())], []); assert read(p) == t1, 'I5 idempotent'

@case('C2 canonical 块原地补丁: 改值/删受管缺失键/保留未管键与注释/顺序不变/幂等')
def _():
    p = with_file(CANON)
    W['_write_mykey_patch']([('native_oai_config_a', {'name': 'A', 'apikey': 'sk-a2', 'apibase': 'https://a.example/v1', 'model': 'm2', 'models': ['m1', 'm2', 'm3'], 'type': 'oai'})], [])
    check_invariants(p, ['A', 'B'], 'A')
    a = by_name(p, 'A'); assert a['model'] == 'm2' and a['models'] == ['m1', 'm2', 'm3'] and a['apikey'] == 'sk-a2'
    assert 'read_timeout' not in a, 'drop_absent 受管键应被删'
    assert a['custom_note'] == 'keep-me' and '# 用户手写注释' in read(p)
    assert by_name(p, 'B') == load_text_block(CANON, 'B')
    t1 = read(p); W['_write_mykey_patch']([('native_oai_config_a', {'name': 'A', 'apikey': 'sk-a2', 'apibase': 'https://a.example/v1', 'model': 'm2', 'models': ['m1', 'm2', 'm3'], 'type': 'oai'})], []); assert read(p) == t1

@case('C3 新服务商: 追加到末尾, 规范格式, 其余不动')
def _():
    p = with_file(CANON)
    W['_write_mykey_patch']([('native_oai_config', {'name': 'C', 'apikey': 'sk-c', 'apibase': 'https://c.example/v1', 'model': 'x', 'models': ['x'], 'type': 'oai'})], [])
    check_invariants(p, ['A', 'B'], 'C', appended=['C'])
    assert blocks(p)[-1]['canonical'] and by_name(p, 'C')['model'] == 'x'

@case('C4 跨行列表值的块(standalone `}` 但字段跨行) → 判非规范 → 整块重建, 不留半截')
def _():
    p = with_file("""
native_oai_config_x = {
    'name': 'X',
    'apikey': 'sk-x',
    'apibase': 'https://x.example/v1',
    'models': [
        'a',
        'b',
    ],
    'model': 'a',
}
""")
    assert blocks(p)[0]['canonical'] is False
    W['_write_mykey_patch']([('native_oai_config_x', {'name': 'X', 'apikey': 'sk-x', 'apibase': 'https://x.example/v1', 'model': 'b', 'models': ['a', 'b', 'c'], 'type': 'oai'})], [])
    check_invariants(p, ['X'], 'X'); assert by_name(p, 'X')['models'] == ['a', 'b', 'c'] and blocks(p)[0]['canonical']

@case('C5 canonical 块内非字面量单行表达式(os.environ) → 仍可逐行补丁且不在 cfg 内的表达式行原样保留')
def _():
    p = with_file("""import os
native_oai_config_e = {
    'name': 'E',
    'apikey': os.environ.get('E_KEY', 'sk-env'),
    'apibase': 'https://e.example/v1',
    'model': 'm',
    'models': ['m'],
}
""")
    assert blocks(p)[0]['canonical'] is True
    W['_write_mykey_patch']([('native_oai_config_e', {'name': 'E', 'apibase': 'https://e.example/v1', 'model': 'm2', 'models': ['m', 'm2'], 'type': 'oai'})], [])
    py_compile.compile(p, doraise=True); assert "os.environ.get('E_KEY', 'sk-env')" in read(p) and by_name(p, 'E')['model'] == 'm2'

@case('C6 非规范块 + 非字面量 → 显式 ValueError, 文件不变(I6: 不静默丢字段)')
def _():
    p = with_file("""import os
native_oai_config_f = {
    'name': 'F', 'apikey': os.environ['F_KEY'], 'apibase': 'https://f.example/v1', 'model': 'm', 'models': ['m']}
""")
    before = read(p)
    try: W['_write_mykey_patch']([('native_oai_config_f', {'name': 'F', 'apibase': 'https://f.example/v1', 'model': 'm2', 'models': ['m', 'm2'], 'type': 'oai'})], []); raise AssertionError('should raise')
    except ValueError as e: assert '非字面量' in str(e)
    assert read(p) == before

@case('C7 类型切换 oai→claude: canonical 改 var 名; 非规范块重建时 var 按新类型')
def _():
    p = with_file(CANON)
    W['_write_mykey_patch']([('native_oai_config_a', {'name': 'A', 'apikey': 'sk-a', 'apibase': 'https://a.example/v1', 'model': 'm1', 'models': ['m1'], 'type': 'claude', 'thinking_type': 'adaptive'})], [])
    check_invariants(p, ['A', 'B'], 'A'); assert blocks(p)[0]['var'].startswith('native_claude_config')
    p2 = with_file(CODEX_OLD)
    W['_write_mykey_patch']([('native_oai_config', codex_cfg(type='claude', thinking_type='adaptive'))], [])
    assert next(b for b in blocks(p2) if b['ename'] == 'Codex')['var'].startswith('native_claude_config')

@case('C8 删除: 同名影子块全删; 从 mixin 链剔除; 链空则 mixin 一并删')
def _():
    p = with_file("mixin_config_auto = {\n    'name': 'auto',\n    'llm_nos': ['Codex', 'KIMI'],\n    'max_retries': 3,\n}\n" + CODEX_OLD)
    W['_write_mykey_patch']([('mixin_config_auto', {'name': 'auto', 'llm_nos': ['KIMI'], 'max_retries': 3})], ['Codex'])
    py_compile.compile(p, doraise=True); en = enames(p); assert 'Codex' not in en and en[0] == 'auto', en
    assert load(p)['mixin_config_auto']['llm_nos'] == ['KIMI']
    W['_write_mykey_patch']([], ['KIMI', 'auto']); assert enames(p) == ['Fixture Provider'], enames(p)

@case('C9 mixin 保存: 旧 mixin 全部替换, 新块钉在文件顶, 服务商块不动')
def _():
    p = with_file("mixin_config = {'name': 'old', 'llm_nos': ['A']},\n" + CANON)
    W['_write_mykey_patch']([('mixin_config_auto', {'name': 'auto', 'llm_nos': ['A', 'B'], 'max_retries': 10, 'base_delay': 0.5, 'spring_back': 300})], [])
    py_compile.compile(p, doraise=True); en = enames(p); assert en == ['auto', 'A', 'B'], en
    assert by_name(p, 'A') == load_text_block(CANON, 'A')

@case('C10 单行 tuple 写法 `var = {...},` → 重建为规范块')
def _():
    p = with_file("native_oai_config_t = {'name': 'T', 'apikey': 'k', 'apibase': 'https://t.example/v1', 'model': 'm', 'models': ['m']},\n")
    W['_write_mykey_patch']([('native_oai_config_t', {'name': 'T', 'apikey': 'k', 'apibase': 'https://t.example/v1', 'model': 'm2', 'models': ['m', 'm2'], 'type': 'oai'})], [])
    check_invariants(p, ['T'], 'T'); assert blocks(p)[0]['canonical'] and by_name(p, 'T')['model'] == 'm2'

@case('C11 空文件/无文件 → 直接追加')
def _():
    p = with_file(''); os.remove(p)
    W['_write_mykey_patch']([('native_oai_config', {'name': 'N', 'apikey': 'k', 'apibase': 'https://n.example/v1', 'model': 'm', 'models': ['m'], 'type': 'oai'})], [])
    check_invariants(p, [], 'N', appended=['N'])

@case('C12 文件里的 import/函数/注释等非块语句逐字保留')
def _():
    extra = "import os\n# 顶部注释\ndef helper():\n    return 1\n\nX_WORKFLOW = {'plan_llm_nos': ['A'], 'name': 'wf'}\n"
    p = with_file(extra + CANON)
    W['_write_mykey_patch']([('native_oai_config_a', {'name': 'A', 'apikey': 'sk-a', 'apibase': 'https://a.example/v1', 'model': 'm2', 'models': ['m1', 'm2'], 'type': 'oai'})], ['wf'])
    py_compile.compile(p, doraise=True); t = read(p)
    assert t.startswith(extra), 'workflow 块受硬保护且非块语句不动'

@case('C13 CRLF 文件 → 正常解析, 输出 LF 且可编译')
def _():
    p = with_file(CANON.replace('\n', '\r\n'))
    W['_write_mykey_patch']([('native_oai_config_a', {'name': 'A', 'apikey': 'sk-a', 'apibase': 'https://a.example/v1', 'model': 'm2', 'models': ['m1', 'm2'], 'type': 'oai'})], [])
    check_invariants(p, ['A', 'B'], 'A'); assert '\r' not in open(p, 'rb').read().decode()

@case('C14 _provider_save 载荷归一: models 字串→list / 数值串→int / connect_timeout→timeout / 无 name 拒绝')
def _():
    p = with_file(CANON)
    r = json.loads(W['_provider_save'](json.dumps({'name': 'A', 'apikey': 'sk-a', 'apibase': 'https://a.example/v1', 'type': 'oai', 'model': 'm1', 'models': 'm1', 'read_timeout': '240', 'connect_timeout': '15', 'max_tokens': 'abc'})))
    assert r['ok'], r; a = by_name(p, 'A'); assert a['models'] == ['m1'] and a['read_timeout'] == 240 and a['timeout'] == 15 and 'max_tokens' not in a and 'connect_timeout' not in a
    assert json.loads(W['_provider_save'](json.dumps({'apikey': 'x'})))['ok'] is False

@case('C15 _provider_save 对设备原文(inline `}`+影子块) 返回 ok 而非 SyntaxError 回滚')
def _():
    p = with_file(CODEX_OLD)
    r = json.loads(W['_provider_save'](json.dumps(codex_cfg()))); assert r == {'ok': True, 'name': 'Codex'}, r
    assert enames(p) == ['Fixture Provider', 'Codex', 'KIMI']

@case('C16 全量同步 _write_mykey_py_from_dict: 同样处理非规范块与影子块')
def _():
    p = with_file(CODEX_OLD)
    W['_write_mykey_py_from_dict']({'native_oai_config': codex_cfg(), 'native_oai_config_fixture': {'name': 'Fixture Provider', 'apikey': 'sk-ga-1', 'apibase': 'https://relay.example/v1', 'model': 'auto-flash', 'models': ['auto-flash']},
                                   'native_claude_config': {'name': 'KIMI', 'apikey': 'sk-k', 'apibase': 'https://cn.example', 'model': 'kimi-k3', 'models': ['kimi-k3'], 'type': 'claude'}})
    py_compile.compile(p, doraise=True); assert enames(p) == ['Fixture Provider', 'Codex', 'KIMI'], enames(p); assert by_name(p, 'Codex')['model'] == 'gpt-6-astra'

@case('C17 推理强度切回「默认」: 载荷不含 reasoning_effort → 删掉旧值(界面显示默认而后端仍是 low 的回归)')
def _():
    p = with_file(CANON)
    W['_provider_save'](json.dumps({'name': 'A', 'apikey': 'sk-a', 'apibase': 'https://a.example/v1', 'type': 'oai', 'model': 'm1', 'models': ['m1'], 'reasoning_effort': 'low'}))
    assert by_name(p, 'A')['reasoning_effort'] == 'low'
    W['_provider_save'](json.dumps({'name': 'A', 'apikey': 'sk-a', 'apibase': 'https://a.example/v1', 'type': 'oai', 'model': 'm1', 'models': ['m1']}))
    assert 'reasoning_effort' not in by_name(p, 'A')

if __name__ == '__main__':
    for name, ok, err in RESULTS: print(('PASS' if ok else 'FAIL'), name, ('' if ok else ' -> ' + err))
    n_ok = sum(1 for _, ok, _ in RESULTS if ok); print(f'\n{n_ok}/{len(RESULTS)} PASS')
    sys.exit(0 if n_ok == len(RESULTS) else 1)
