"""desc_inject 插件 —— D3「模型侧短语摘要」运行时注入(PLAN_UX_ROUND2 §4, 路线 A)。

架构契约(VISITABLE_EXEC_ENV §2 豁免申报 / PLAN_UX_ROUND2 §1.2):
  与 GA **解耦**: assets/tools_schema{,_cn}.json / agent_loop.py / ga_android.py / android_entry.py
    全部零字节改动; 注入只发生在事件层插件的 `llm_before` 钩子里, 对 agent_loop 传进来的
    活对象 ctx['tools_schema'] 做**原地幂等 mutate**。
  不新增任何 tool 条目 —— 只往既有 7 个工具的 t['function']['parameters']['properties']
    追加一个可选 string 参数 `desc`(不产生 required 键), 工具数/工具名有序列表逐字不变。
  开关 `ga.desc_off`(kv) 为真时**显式移除**已注入的 desc(不是「不再注入」): TOOLS_SCHEMA 是
    agentmain 模块级全局对象, 原地 mutate 过的 desc 不会自愈(PLAN §4.1 / R5b)。
  字节稳定纪律(护住 llmcore 的 last_tools 缓存, PLAN §4.4 / R5c):
    ON 分支**只在缺键时追加**(dict 末尾, 位置稳定), 绝不「先 pop 再 add」;
    同一 schema 连续两次注入后 compact JSON 必须逐字相同, 否则 tools_json 每轮变化
    ⇒ auto_save_tokens 缓存永久失效 ⇒ 工具库每轮全量重发。
  kv 读失败(import 异常 / 读异常)一律「不做任何 mutate、直接 return」——
    避免 kv 抖动导致 schema 反复增删, 破坏上述字节稳定性。
  故障半径为零: hooks.trigger 吞异常(plugins/hooks.py), 注入失败静默降级为「无 desc」,
    前端 humanize 的 `desc > 词典` 优先级自动回落词典兜底。
  事件回流在 tool_events_hook(add-only 的 'desc' 字段), 本插件不写事件、不碰 sess。
"""
import os

from plugins.hooks import register

KEY = 'desc'
KV_OFF = 'ga.desc_off'
_TRUE = ('1', 'true', 'on', 'yes')

# 混合档(PLAN §4.4): 仅 code_run 带完整说明并注明「所有工具同义」, 其余 6 个裸 {"type":"string"},
# 把 schema 增量压在个位数百分比。文案随 GA_LANG 定于 import 期(运行期不变 ⇒ 字节稳定)。
_EN = os.environ.get('GA_LANG', '') == 'en'
DOC = ('Optional. Ultra-short phrase of what this call does, shown to the user. Same for all tools.'
       if _EN else
       '可选。极短短语说明本次调用做什么，用于向用户显示；各工具同义。')

DOC_TOOL = 'code_run'   # 唯一携带完整说明的工具


def _spec(tool_name):
    if tool_name == DOC_TOOL:
        return {'type': 'string', 'description': DOC}
    return {'type': 'string'}


def _props(t):
    """取 t['function']['parameters']['properties'](实测结构; t 这一层没有 parameters 键)。
    结构不符一律返回 None ⇒ 跳过该条, 绝不新建中间层。"""
    if not isinstance(t, dict):
        return None, ''
    f = t.get('function')
    if not isinstance(f, dict):
        return None, ''
    p = f.get('parameters')
    if not isinstance(p, dict):
        return None, ''
    props = p.get('properties')
    if not isinstance(props, dict):
        return None, ''
    return props, str(f.get('name') or '')


def inject(tools_schema):
    """ON: 缺键才追加(幂等 + 位置稳定)。返回实际改动条数。"""
    n = 0
    for t in tools_schema or []:
        props, name = _props(t)
        if props is None or KEY in props:
            continue
        props[KEY] = _spec(name)     # 追加到 dict 末尾; 不创建 required 键
        n += 1
    return n


def strip(tools_schema):
    """OFF: 幂等移除(无 desc 时是 no-op)。返回实际改动条数。

    只移除**本插件注入的那一份** —— 判据是 props[KEY] 与 _spec(name) 逐字相等
    (监察 #GU1 意见 10: 裸 pop 无来源标记, 将来某工具原生带 desc 属性会被误删)。
    今天 7 个工具原文均无 desc, 该判据下行为与裸 pop 完全一致; 一旦上游 schema
    自带 desc, inject() 本就跳过(缺键才写), strip() 也随之不动 —— 两端对称。"""
    n = 0
    for t in tools_schema or []:
        props, name = _props(t)
        if props is None or KEY not in props:
            continue
        if props[KEY] != _spec(name):
            continue                 # 非本插件注入(上游原生 desc) ⇒ 不代删
        props.pop(KEY, None)
        n += 1
    return n


def _off():
    """读 kv ga.desc_off。返回 True/False/None(None = 读失败 ⇒ 调用方不做任何 mutate)。
    惰性 import: discover_and_load() 在 agentmain 很早期执行, 模块级 import android_entry 有循环风险。
    判真口径对齐 android_entry._multi_enabled(kv 原文可能带 JSON 引号)。"""
    try:
        from android_entry import _kv_get_val
    except Exception:
        return None
    try:
        raw = _kv_get_val(KV_OFF, '0')
    except Exception:
        return None
    try:
        return str(raw).strip().strip('"').lower() in _TRUE
    except Exception:
        return None


def _on_llm_before(ctx):
    ts = (ctx or {}).get('tools_schema')
    if not isinstance(ts, list) or not ts:
        return
    off = _off()
    if off is None:
        return          # kv 读失败: 维持上一状态, 不 mutate(见文件头字节稳定纪律)
    strip(ts) if off else inject(ts)


register('llm_before', _on_llm_before)
