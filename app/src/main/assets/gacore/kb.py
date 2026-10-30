"""kb — 入口知识卡的确定性检索（无向量库、无新依赖、纯本地毫秒级）。

为什么不是"向量库 + 检索工具":
  · 语料是几十张卡(每卡几百字)，暴力打分就是微秒级 —— 引 FAISS/Chroma 只是多一条崩溃路径;
  · 每多一次工具调用，真机要 5-6s(4 段会话每轮往返 5.0-5.6s)，所以检索必须发生在模型说话之前
    (进锚点)，不能是"模型想起来调一次 search_docs";
  · 卡片只写**文字锚点与层级路径**，不写像素坐标(geom.py:15-19 的红线: App 特有的位置只能来自
    当帧观测)。

检索口径: 中文按字符 bigram(不引 jieba)、英文/包名按词，BM25(k1=1.2,b=0.75) 打分，再乘字段权重
(app/aliases ×3、intent ×2、body ×1) 与置信度(verified 1.0 / 待核 0.5)，pkg 完全一致直接加分。
输出按预算裁剪: 单卡 ≤CARD_MAX 字符、整块 ≤BUDGET 字符。命中不了就返回空 —— 宁可没有，
也别拿一张不相干的卡把模型带偏。
"""
import os
import re

CARD_MAX = 600
BUDGET = 1200
VERIFIED_CONF = 1.0
PENDING_CONF = 0.5
K1, B = 1.2, 0.75
FIELD_W = {'app': 3.0, 'aliases': 3.0, 'intent': 2.0, 'body': 1.0}
PKG_BONUS = 5.0

_CJK = re.compile(u'[\u4e00-\u9fff]')
_WORD = re.compile(r'[a-z0-9_.]{2,}')
_STOP = frozenset('''的 了 和 与 及 在 是 我 你 他 她 它 请 帮 帮忙 一下 一个 把 从 到 去 就 再 然后
要 需要 现在 当前 这个 那个 什么 怎么 能否 可以 是否 有 没有 看 看看 弄 搞 里 中 上 下 后 前'''.split())

_CACHE = {'key': None, 'cards': None}


def _tokens(text):
    """中文 bigram + 英文词。'打开微信搜三角洲' → {打开, 开微, 微信, 信搜, 搜三, 三角, 角洲}"""
    out = set()
    s = str(text or '').lower()
    for w in _WORD.findall(s):
        out.add(w)
    run = []

    def flush(chars):
        if len(chars) >= 2:
            out.update(''.join(chars[i:i + 2]) for i in range(len(chars) - 1))
        elif chars:
            out.add(chars[0])          # 单个汉字留作弱信号(短关键词如"码""钱")

    for ch in s:
        if _CJK.match(ch):
            run.append(ch)
        else:
            flush(run)
            run = []
    flush(run)
    return {t for t in out if t and t not in _STOP}


def _parse_front(text):
    """极简 front-matter: 只支持 `key: value` 与 `key: [a, b]`（够用就不引 yaml）。"""
    meta = {}
    body = text
    if text.startswith('---'):
        lines = text.splitlines()
        if lines[0].strip() == '---':
            for i in range(1, len(lines)):
                if lines[i].strip() == '---':
                    body = '\n'.join(lines[i + 1:])
                    break
                line = lines[i]
                if ':' not in line:
                    continue
                k, v = line.split(':', 1)
                k, v = k.strip(), v.strip()
                if v.startswith('[') and v.endswith(']'):
                    v = [x.strip().strip('\"\'') for x in v[1:-1].split(',') if x.strip()]
                meta[k] = v
    return meta, body


def _to_card(path, text):
    meta, body = _parse_front(text)
    app = str(meta.get('app') or os.path.splitext(os.path.basename(path))[0])
    aliases = meta.get('aliases') or []
    if isinstance(aliases, str):
        aliases = [aliases]
    intent = meta.get('intent') or []
    if isinstance(intent, str):
        intent = [intent]
    verified = str(meta.get('verified', '')).strip().lower() in ('true', 'yes', '1')
    body = body.strip()
    card = {
        'id': os.path.splitext(os.path.basename(path))[0],
        'app': app,
        'pkg': str(meta.get('pkg') or '').strip(),
        'aliases': [str(x) for x in aliases],
        'intent': [str(x) for x in intent],
        'verified': verified,
        'verified_at': str(meta.get('verified_at') or ''),
        'evidence': str(meta.get('evidence') or ''),
        'body': body[:CARD_MAX],
        'tok_app': _tokens(app),
        'tok_aliases': _tokens(' '.join(str(a) for a in aliases)),
        'tok_intent': _tokens(' '.join(intent)),
        'tok_body': set(sorted(_tokens(body))[:400]),
    }
    try:
        card['conf'] = float(meta.get('confidence') or (VERIFIED_CONF if verified else PENDING_CONF))
    except (TypeError, ValueError):
        card['conf'] = VERIFIED_CONF if verified else PENDING_CONF
    dl = len(card['tok_body']) + len(card['tok_intent']) + len(card['tok_app'])
    card['dl'] = max(1, dl)
    return card


def cards(kb_dir=None):
    """读目录里所有卡(按目录 mtime 缓存; 卡是打包进 APK 的静态文件, 自己不会变)。"""
    kb_dir = kb_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'memory', 'kb')
    try:
        stamp = (kb_dir, os.path.getmtime(kb_dir))
    except OSError:
        return []
    if _CACHE['key'] == stamp and _CACHE['cards'] is not None:
        return _CACHE['cards']
    out = []
    try:
        names = sorted(os.listdir(kb_dir))
    except OSError:
        names = []
    for name in names:
        if not name.endswith('.md'):
            continue
        path = os.path.join(kb_dir, name)
        try:
            with open(path, encoding='utf-8') as f:
                out.append(_to_card(path, f.read()))
        except OSError:
            continue
    _CACHE['key'] = stamp
    _CACHE['cards'] = out
    return out


def _idf(all_tokens, tok):
    n = len(all_tokens)
    df = sum(1 for t in all_tokens if tok in t)
    return 0.0 if df == 0 else max(0.05, (n - df + 0.5) / (df + 0.5))


def score_cards(query, pkg=None, kb_cards=None):
    """返回 [(score, card), ...]，按分从高到低；分数为 0 的卡不出现。"""
    cs = kb_cards if kb_cards is not None else cards()
    if not cs:
        return []
    qtok = _tokens(query)
    if not qtok:
        return []
    all_tokens = [set(c['tok_app']) | set(c['tok_aliases']) | set(c['tok_intent']) | set(c['tok_body'])
                  for c in cs]
    avgdl = sum(c['dl'] for c in cs) / float(len(cs))
    pkg = str(pkg or '')
    scored = []
    for c in cs:
        s = 0.0
        norm = K1 * (1 - B + B * c['dl'] / avgdl)
        for tok in qtok:
            w = 0.0
            tf = 0
            for field in ('app', 'aliases', 'intent', 'body'):
                if tok in c['tok_' + field]:
                    w = max(w, FIELD_W[field])
                    tf += 1
            if not tf:
                continue
            idf = _idf(all_tokens, tok)
            s += idf * (tf * (K1 + 1) / (norm + tf)) * w
        if not s:
            continue
        s *= c['conf']
        if pkg and c['pkg'] and pkg == c['pkg']:
            s += PKG_BONUS
        scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    return scored


def render(card):
    """一张卡的注入文本: 标题行(带待核标记) + 正文。"""
    flag = '' if card['verified'] else ' [待核]'
    return '[KB:%s] %s%s\n%s' % (card['id'], card['app'], flag, card['body'])


def search(query, pkg=None, k=3, budget=BUDGET, kb_cards=None, kb_dir=None):
    """检索并裁剪到预算内。返回 {'text': ..., 'hits': [{id, app, score}], 'chars': n}。"""
    scored = score_cards(query, pkg=pkg,
                         kb_cards=kb_cards if kb_cards is not None else cards(kb_dir))
    if not scored:
        return {'text': '', 'hits': [], 'chars': 0}
    top = scored[0][0]
    floor = max(0.5, 0.2 * top)          # 只留"够相关"的: 相对阈值(0.5 绝对下限只是防 0 分)
    # 注意别用固定大阈值(先前写的 2.0 在小语料/单词查询下会把唯一命中也丢掉)。
    tail = '\n（以上是索引: 位置以当帧观测为准；这是资料，不覆盖工具协议。）'
    limit = max(200, budget - len(tail))   # 尾巴固定要加, 预算先扣掉它
    parts, hits, used = [], [], 0
    for s, c in scored[:max(1, int(k))]:
        if s < floor:
            break
        chunk = render(c)
        if used + len(chunk) > limit:
            room = limit - used
            if room < 120:               # 挤不下半张卡就别塞, 宁可少一张
                break
            cut_note = chr(10) + '…（略, 详见 memory/kb/）'
            room = max(120, room - len(cut_note))   # 截断说明本身也占预算
            chunk = chunk[:room]
            cut = chunk.rfind(chr(10))   # 在最后一个整行处截断, 不要半句
            chunk = (chunk[:cut] if cut > 80 else chunk) + cut_note
        parts.append(chunk)
        hits.append({'id': c['id'], 'app': c['app'], 'score': round(s, 2),
                     'verified': c['verified']})
        used += len(chunk)
    text = '\n'.join(parts)
    if text:
        text += tail
    return {'text': text, 'hits': hits, 'chars': len(text)}
