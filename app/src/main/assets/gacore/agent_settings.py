"""运行期开关：读 GA_DIR/kv/<key>.json（与前端 /kv.* 桥同一份文件级 KV）。

为什么单独一个模块：`/kv.set` 是**用户能在 GA 聊天框直接敲的命令**（`_CMDS_PRE` 里就分发，
不进 LLM、不烧积分），所以开关放在这里就等于"可热改、不用重装 APK"。
读的是纯文件，没有设备副作用，测试可以直接给 root。

取值约定（全部小写、容错）：
  off/0/false/no   = 关
  always/all/1/on  = 每轮都带图
  auto（默认）      = 只有"本地定位拿不到东西"的页面才带图（视觉型 App / 无树 / canvas）
"""
import os
import re

KV_DIRNAME = 'kv'
KEY_VISION_IN_TURN = 'ga.visioninturn'
KEY_KB_MODE = 'ga.kbmode'
KB_MODES = ('off', 'lexical', 'recall', 'both')
MODES = ('off', 'auto', 'always')
_ON = {'1', 'true', 'on', 'yes', 'always', 'all'}
_OFF = {'0', 'false', 'no', 'off', 'none'}


def _ga_dir(root=None):
    """GA_DIR：显式给出 > android_entry.GA_DIR > 本文件所在目录（本模块就住在 GA_DIR 下）。"""
    if root:
        return str(root)
    try:
        import android_entry              # 延迟导入: 设备上有, PC 单测没有
        d = getattr(android_entry, 'GA_DIR', None)
        if d:
            return str(d)
    except Exception:
        pass
    return os.path.dirname(os.path.abspath(__file__))


def kv_path(key, root=None):
    safe = re.sub(r'[^A-Za-z0-9._-]', '_', str(key))[:64] or 'kv'
    return os.path.join(_ga_dir(root), KV_DIRNAME, safe + '.json')


def kv_get(key, default='', root=None):
    """读原文字符串；缺文件/异常 → default（与 android_entry._kv_get_val 同语义）。"""
    try:
        with open(kv_path(key, root), encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return default


def kv_set(key, value, root=None):
    """原子写：先写 .tmp 再 replace，避免半截文件被读成"空设置"。"""
    p = kv_path(key, root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(str(value))
    os.replace(tmp, p)
    return str(value)


def _mode(raw, default='auto'):
    v = str(raw or '').strip().lower()
    if not v:
        return default
    if v in _OFF:
        return 'off'
    if v in _ON:
        return 'always'
    return v if v in MODES else default


def vision_in_turn(root=None):
    """'off' | 'auto' | 'always'。每轮现读，用户改了立刻生效（不用重启会话）。"""
    return _mode(kv_get(KEY_VISION_IN_TURN, '', root), 'auto')


def vision_on(root=None):
    return vision_in_turn(root) != 'off'


def kb_mode(root=None):
    """知识库注入档位：'off' | 'lexical'（默认）| 'recall' | 'both'。

    Stage 1 只有 lexical（卡片检索）；recall/both 是 Stage 2 的开关位，先留名字，
    读到也不报错（当前实现按 lexical 处理），这样灰度脚本不用等代码。
    默认开: 注入一次 ≈1.2KB 字符, 而模型自己 file_read 两轮 ≈4s + 经常只拿到无关段落。
    用户可在聊天框直接 `/kv.set ga.kbmode off` 热关(不用重装)。
    """
    v = str(kv_get(KEY_KB_MODE, '', root) or '').strip().lower()
    if not v:
        return 'lexical'
    if v in _OFF:
        return 'off'
    if v in _ON:
        return 'lexical'
    return v if v in KB_MODES else 'lexical'


def vision_always(root=None):
    return vision_in_turn(root) == 'always'


def parse_vision_cmd(text):
    """/vision off|auto|always|（空=查）→ (mode or None, message)。供聊天命令与测试共用。"""
    parts = str(text or '').split()
    arg = parts[1].lower() if len(parts) > 1 else ''
    if not arg:
        return None, vision_in_turn()
    if arg in _OFF:
        return 'off', 'off'
    if arg in _ON:
        return 'always', 'always'
    if arg == 'auto':
        return 'auto', 'auto'
    return None, 'unknown: use off|auto|always'
