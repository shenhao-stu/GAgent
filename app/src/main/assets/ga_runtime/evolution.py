"""设备端"演化安全"引擎(issue#1): 把 GA 的自演化改动从"热更新覆盖"中救回来。

模型 = 设备端的 git 三路:
  base   = 上一次官方版(.evolution/baseline, 由 Kotlin 解压时刷新)
  ours   = 工作区(用户/GA 自演化改过的 gacore 文件)
  theirs = 新官方版(本次 APK 内置 asset)

按钮「热更新」(Kotlin 机制): 覆盖工作区为官方版前, 把 ours≠base 的文件连同 {base,ours} 打包成
  .evolution/backups/pre-<oldVer>-<stamp>.zip —— 永远先落地干净官方版, 本地改动零丢失。
按钮「演化融合」(本模块策略): 取最近 backup zip 做逐文件 3-way 合并(base,ours,theirs=当前工作区),
  干净的写回工作区; 冲突的不写脏(保官方版可启动), 另存 .evolution/conflicts/ 供人/GA 决议。

纯函数为主, 无副作用的合并核心(merge3/merge_text)可独立单测; 落盘只在 evo_merge 一处。
"""
import os, io, json, zipfile, difflib, shutil, time

# ── 跟踪范围: 只跟"可自演化的文本文件", 排除模型/三方压缩库(必须与 Kotlin isTrackedText 一致) ──
_TRACKED_EXT = ('.py', '.md', '.txt', '.json', '.js', '.css', '.html')

def is_tracked(rel):
    r = (rel or '').replace('\\', '/').lstrip('/')
    if '..' in r.split('/'):                       # 真·拦目录穿越(evo_prepare/evo_merge 共用此守卫): 防 zip 内 ../ 落盘越界
        return False
    if r.startswith('.evolution/') or r.startswith('models/') or r.startswith('webui/vendor/'):
        return False
    if r.endswith('.min.js'):
        return False
    return r.endswith(_TRACKED_EXT)

# ── 3-way 合并核心(canonical diff3, 同步区锚定法) ──────────────────────────
def _matching_blocks(a, b):
    return difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()

def _sync_regions(base, a, b):
    """产出 base/a/b 三方都相等的同步区 (b_lo,b_hi, a_lo,a_hi, t_lo,t_hi)(base 坐标 + a/b 坐标)。
    取 (base,a) 与 (base,b) 匹配块在 base 上的交集; difflib 末尾哨兵零长块给出 EOF 同步点。"""
    am = _matching_blocks(base, a); bm = _matching_blocks(base, b)
    ia = ib = 0; out = []
    while ia < len(am) and ib < len(bm):
        ab, aj, al = am[ia]; bb, bj, bl = bm[ib]
        lo = max(ab, bb); hi = min(ab + al, bb + bl)
        if lo < hi:
            out.append((lo, hi, aj + (lo - ab), aj + (hi - ab), bj + (lo - bb), bj + (hi - bb)))
        if ab + al < bb + bl: ia += 1
        else: ib += 1
    out.append((len(base), len(base), len(a), len(a), len(b), len(b)))   # 显式 EOF 同步点: 收尾"末尾变更区"(difflib 哨兵不保证被相交命中)
    return out

def _nl(lines):
    """保证片段末行有换行(冲突标记前后对齐); 空片段原样。"""
    if lines and not lines[-1].endswith('\n'):
        return lines[:-1] + [lines[-1] + '\n']
    return lines

def merge3(base, ours, theirs):
    """逐行 3-way 合并。返回 (merged_lines, n_conflicts)。ours=本地, theirs=官方。"""
    out = []; conflicts = 0; bi = oi = ti = 0
    for (zb_lo, zb_hi, zo_lo, zo_hi, zt_lo, zt_hi) in _sync_regions(base, ours, theirs):
        oseg = ours[oi:zo_lo]; tseg = theirs[ti:zt_lo]; bseg = base[bi:zb_lo]   # 本同步点前的"变更区"
        if oseg == tseg:        out.extend(oseg)                 # 两侧改法一致(或都没改)
        elif oseg == bseg:      out.extend(tseg)                 # 仅官方改 → 取官方
        elif tseg == bseg:      out.extend(oseg)                 # 仅本地改 → 保本地
        else:                                                   # 双方各改 → 冲突标记
            conflicts += 1
            out.append('<<<<<<< LOCAL (本地自演化)\n'); out.extend(_nl(oseg))
            out.append('=======\n'); out.extend(_nl(tseg))
            out.append('>>>>>>> OFFICIAL (官方最新)\n')
        out.extend(base[zb_lo:zb_hi])                           # 同步(相等)区
        bi, oi, ti = zb_hi, zo_hi, zt_hi
    return out, conflicts

def merge_text(base_text, ours_text, theirs_text):
    """文本级 3-way。快路径: 单侧改/两侧同 → 无冲突直接定夺; 否则走逐行 merge3。"""
    if ours_text == theirs_text:   return theirs_text, 0
    if ours_text == base_text:     return theirs_text, 0        # 本地没改 → 官方
    if theirs_text == base_text:   return ours_text, 0          # 官方没改 → 本地(自演化常态)
    lines, conf = merge3(base_text.splitlines(keepends=True),
                         ours_text.splitlines(keepends=True),
                         theirs_text.splitlines(keepends=True))
    return ''.join(lines), conf

# ── 备份枚举 ────────────────────────────────────────────────────────────────
def _evo_dir(ga_dir): return os.path.join(ga_dir, '.evolution')
def _backups_dir(ga_dir): return os.path.join(_evo_dir(ga_dir), 'backups')

def list_backups(ga_dir):
    d = _backups_dir(ga_dir)
    if not os.path.isdir(d): return []
    out = []
    for n in os.listdir(d):
        if not n.endswith('.zip'): continue
        p = os.path.join(d, n)
        meta = {}; count = 0
        try:
            with zipfile.ZipFile(p) as z:
                if 'meta.json' in z.namelist():
                    meta = json.loads(z.read('meta.json').decode('utf-8', 'replace'))
                count = sum(1 for x in z.namelist() if x.startswith('ours/') and not x.endswith('/'))
        except Exception:
            continue
        out.append({'name': n, 'path': p, 'count': count,
                    'oldVer': meta.get('oldVer', '?'), 'newVer': meta.get('newVer', '?'),
                    'ts': meta.get('ts') or int(os.path.getmtime(p))})
    out.sort(key=lambda b: b['ts'], reverse=True)
    return out

def _zip_rels(path):
    """备份 zip 内 ours/ 下的文件 rel 集合; 坏 zip 返回空集(与 list_backups 跳过一致)。"""
    try:
        with zipfile.ZipFile(path) as z:
            return {n[len('ours/'):] for n in z.namelist() if n.startswith('ours/') and not n.endswith('/')}
    except Exception:
        return set()

def evo_status(ga_dir):
    bks = list_backups(ga_dir)
    rels = set().union(*[_zip_rels(b['path']) for b in bks]) if bks else set()
    return {'baseline': os.path.isdir(os.path.join(_evo_dir(ga_dir), 'baseline')),
            'backups': bks, 'latest': bks[0] if bks else None,
            'files': len(rels)}   # 全部备份去重后的待融合文件数: 徽标/融合弹窗/门禁的唯一计数源

# ── 演化融合: 取最近 backup zip, 逐文件 3-way 合并回灌工作区 ──────────────────
# 不变量(先融合后删除): 备份 zip 只在其内容被完全吸收(全部 merged/unchanged, 0 冲突 0 失败)后才被删除;
# 有冲突/失败的 zip 保留, 供决议或 LLM 融合(/evo.fuseprompt)重试。
def evo_merge(ga_dir, zip_name=None):
    bks = list_backups(ga_dir)
    if not bks: return {'ok': False, 'error': 'no-backup'}
    target = next((b for b in bks if b['name'] == zip_name), None) if zip_name else bks[0]
    if target is None: return {'ok': False, 'error': 'zip-not-found'}
    merged, conflicted, unchanged, failed = [], [], [], []
    premerge = os.path.join(_evo_dir(ga_dir), 'premerge', str(target['ts']))   # 改动前快照, 可回滚
    conf_dir = os.path.join(_evo_dir(ga_dir), 'conflicts', str(target['ts']))  # 按 zip 分目录: 多备份同名文件的冲突互不覆盖
    try:
        with zipfile.ZipFile(target['path']) as z:
            names = set(z.namelist())
            rels = sorted({n[len('ours/'):] for n in names if n.startswith('ours/') and not n.endswith('/')})
            for rel in rels:
                if not is_tracked(rel): failed.append(rel); continue   # is_tracked 已拦 ../ 穿越 + 排除模型/三方库
                try:
                    ours = z.read('ours/' + rel).decode('utf-8', 'replace')
                    base = z.read('base/' + rel).decode('utf-8', 'replace') if ('base/' + rel in names) else ''
                except Exception:
                    failed.append(rel); continue
                wf = os.path.join(ga_dir, rel)
                theirs = ''
                try:
                    if os.path.exists(wf): theirs = io.open(wf, encoding='utf-8', errors='replace').read()
                except Exception: pass
                if ours == theirs: unchanged.append(rel); continue     # 本地改动已等于当前官方
                text, conf = merge_text(base, ours, theirs)
                if conf:                                               # 冲突: 不写脏到可启动的工作区, 另存供决议
                    _dump(os.path.join(conf_dir, rel), text)
                    conflicted.append({'file': rel, 'conflicts': conf}); continue
                _dump(os.path.join(premerge, rel), theirs)             # 干净合并: 先存回滚点再写回
                _dump(wf, text); merged.append(rel)
    except Exception as e:
        return {'ok': False, 'error': type(e).__name__ + ': ' + str(e)[:160]}
    absorbed = not conflicted and not failed
    if absorbed:
        try: os.remove(target['path'])
        except OSError: absorbed = False
    return {'ok': True, 'zip': target['name'], 'removed': absorbed,
            'merged': merged, 'conflicted': conflicted, 'unchanged': unchanged, 'failed': failed,
            'conflictsDir': conf_dir if conflicted else '', 'premergeDir': premerge if merged else '',
            'counts': {'merged': len(merged), 'conflicted': len(conflicted),
                       'unchanged': len(unchanged), 'failed': len(failed)}}

def evo_merge_all(ga_dir):
    """全部备份按时间旧→新逐 zip 融合(旧改动先落, 新改动可覆写), 完全吸收的 zip 随融合即删。
    返回逐 zip 结果 + 聚合计数; 任一 zip 失败不中断后续(结果里可见)。"""
    zips = [b['name'] for b in sorted(list_backups(ga_dir), key=lambda b: b['ts'])]
    if not zips: return {'ok': False, 'error': 'no-backup'}
    results = [evo_merge(ga_dir, n) for n in zips]
    agg = {k: sum(r.get('counts', {}).get(k, 0) for r in results)
           for k in ('merged', 'conflicted', 'unchanged', 'failed')}
    agg['removedZips'] = sum(1 for r in results if r.get('removed'))
    return {'ok': all(r.get('ok') for r in results), 'zips': results, 'counts': agg}

def _dump(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, 'w', encoding='utf-8').write(text)

# ── LLM 演化融合: 把备份的 base/ours 抽到可读工作目录, 交给智能体做三路智能合并 ──────
def evo_prepare(ga_dir, zip_name=None):
    """抽取备份三路素材到 temp/evo_merge/<ts>/, 供智能体用普通文件工具做三路
    合并(theirs=当前工作区=新官方版)。zip_name=None 聚合全部备份(旧→新, 同 rel 取
    最旧 base=首次改动前的官方版 + 最新 ours, 范围与 /evo.status files 一致);
    指定 zip_name 只抽该 zip。只在工作目录落地素材, 不碰可启动的工作区。
    返回 manifest: {ok, zip, zips, oldVer, newVer, workDir, files:[{rel, base, ours, live}]}。"""
    bks = list_backups(ga_dir)
    if not bks: return {'ok': False, 'error': 'no-backup'}
    targets = ([b for b in bks if b['name'] == zip_name] if zip_name
               else sorted(bks, key=lambda b: b['ts']))
    if not targets: return {'ok': False, 'error': 'zip-not-found'}
    work = os.path.join(ga_dir, 'temp', 'evo_merge', str(targets[-1]['ts']))
    shutil.rmtree(work, ignore_errors=True)                         # 保证 disk↔manifest 一致: 同 ts 不同 zip 内容时不残留陈旧素材
    seen = {}                                                       # rel -> {'base','ours'}; 旧→新遍历, ours 后写者胜
    for tgt in targets:
        with zipfile.ZipFile(tgt['path']) as z:
            names = set(z.namelist())
            for rel in {n[len('ours/'):] for n in names if n.startswith('ours/') and not n.endswith('/')}:
                if not is_tracked(rel): continue                    # is_tracked 已拦 ../ 穿越 + 排除模型/三方库
                odst = os.path.join(work, 'ours', rel)
                _dump(odst, z.read('ours/' + rel).decode('utf-8', 'replace'))
                ent = seen.setdefault(rel, {'base': '', 'ours': odst})   # base 留空 = 本地新增文件, 智能体按新增处理
                if not ent['base'] and 'base/' + rel in names:
                    bdst = os.path.join(work, 'base', rel)
                    _dump(bdst, z.read('base/' + rel).decode('utf-8', 'replace'))
                    ent['base'] = bdst
    files = [{'rel': rel, 'base': e['base'], 'ours': e['ours'], 'live': os.path.join(ga_dir, rel)}
             for rel, e in sorted(seen.items())]
    return {'ok': True, 'zip': ', '.join(t['name'] for t in targets), 'zips': len(targets),
            'oldVer': targets[0]['oldVer'], 'newVer': targets[-1]['newVer'],
            'workDir': work, 'files': files}

def evo_clear_backups(ga_dir):
    """删除演化备份与中间产物(backups/premerge/conflicts), 保留 baseline(下次备份的 base 基准)。返回删除文件数。"""
    removed = 0
    for sub in ('backups', 'premerge', 'conflicts'):
        d = os.path.join(_evo_dir(ga_dir), sub)
        if not os.path.isdir(d): continue
        for _root, _dirs, fs in os.walk(d): removed += len(fs)
        shutil.rmtree(d, ignore_errors=True)
    return removed
