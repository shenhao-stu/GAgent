"""tool_events 插件 —— 把工具调用升格为结构化事件, 供 WebUI 工具条展示(参观层数据源)。

架构契约(PLAN_TOOL_STRUCTURING_V3 v3.1 / 监察 #007):
  执行层零改动; 事件只进 poll→UI 通道, 绝不回灌模型上下文。
  归属靠数据: 每条事件自带 gen, 前端只渲染 event.gen == payload.gen
    (send→首次工具调用间的 poll 会带出上一任务事件, 靠清空时序挡不住); 本插件清列表仅为内存回收。
  终态推断在前端: 工具抛异常会终止整个 agent 循环, 插件侧不存在补偿时机(#007 发现 1),
    滞留 running 的事件由前端按「任务已停」显示为中断; abort 时 code_run 经 stop_signal
    提前正常返回会记 done —— 如实展示, 不粉饰(#007 发现 4)。
  写入纪律: 字段只允许纯 str/int/float —— poll 的 json.dumps 无 default 兜底,
    一条坏类型事件会毒死整个 poll 通道(#007 发现 2); 全部写操作持 sess.lock(发现 7)。
"""
import json, time
from plugins.hooks import register
from kernel_adapter import patches

MAX_EVENTS = 50    # 环形上限(超出丢最旧)
NAME_CAP = 80
SUM_CAP = 300


def _text(v, cap):
    """任意值 → 纯 str 且截断。绝不让非标量出插件。"""
    try:
        if isinstance(v, str):
            s = v
        else:
            s = json.dumps(v, ensure_ascii=False, default=str)
    except Exception:
        try: s = str(v)
        except Exception: s = '?'
    return s[:cap]


def _sess():
    s = patches.current_sess()
    if s is None or getattr(s, 'retired', False):
        return None
    return s


def _on_tool_before(ctx):
    name = ctx.get('tool_name') or ''
    if not name or name == 'no_tool':
        return
    sess = _sess()
    if sess is None:
        return
    # 真实 tool_call id(dispatch 作用域无 tid, 经 response+index 取; 先例见 agent_loop L70-71)
    tcid = ''
    try:
        tcs = getattr(ctx.get('response'), 'tool_calls', None) or []
        tcid = str(tcs[ctx.get('index') or 0].id or '')
    except Exception:
        pass
    turn = 0
    try: turn = int(getattr(ctx.get('self'), 'current_turn', 0) or 0)
    except Exception: pass
    with sess.lock:
        st = sess.state
        gen = int(st.get('gen', 0) or 0)
        evs = st.setdefault('tool_events', [])
        if st.get('_tool_gen') != gen:            # 代际变化 → 清旧事件(仅内存回收, 归属由 event.gen 保证)
            del evs[:]
            st['_tool_gen'] = gen
            st['_tool_seq'] = 0
        st['_tool_seq'] = int(st.get('_tool_seq', 0) or 0) + 1
        evs.append({
            'gen': gen,
            'seq': st['_tool_seq'],
            'id': tcid[:NAME_CAP],
            'name': _text(name, NAME_CAP),
            'status': 'running',
            'turn': turn,
            't_start': round(time.time(), 3),
            't_end': 0,
            # D3(add-only, PLAN_UX_ROUND2 §4.3①): 模型自述的动作短语, 事件顶层唯一权威副本。
            # 前端由 app.js:_twTitle 把 e.desc 桥接进 humanize 的 a.desc(desc > 词典 优先级), 缺省空串。
            'desc': _text((ctx.get('args') or {}).get('desc', ''), NAME_CAP),
            # 滤 dispatch 注入的 _index/_tool_num 内部键; desc 同口径剔除(PLAN §4.3② / R9):
            # 顶层已有权威副本, 留在此处只会白占 SUM_CAP=300 预算、把业务参数挤出截断窗口。
            'input_summary': _text({k: v for k, v in (ctx.get('args') or {}).items()
                                    if not str(k).startswith('_') and str(k) != 'desc'}, SUM_CAP),
            'result_summary': '',
            'error': '',
        })
        trim(evs)


def trim(evs):
    """环形上限: 超出时丢最旧的已结束事件; 运行中的宿主事件不淘汰, 否则 tool_after 找不到它来收尾。"""
    over = len(evs) - MAX_EVENTS
    if over > 0:
        for i in reversed([i for i, e in enumerate(evs) if e.get('status') != 'running'][:over]):
            del evs[i]


def _on_tool_after(ctx):
    name = ctx.get('tool_name') or ''
    if not name or name == 'no_tool':
        return
    sess = _sess()
    if sess is None:
        return
    ret = ctx.get('ret')
    data = getattr(ret, 'data', None)
    # 窄启发式(#007 A3: StepOutcome 无错误位, 异常路径到不了这里; 只认 dict.status=='error')
    is_err = isinstance(data, dict) and str(data.get('status', '')).lower() == 'error'
    with sess.lock:
        evs = sess.state.get('tool_events') or []
        # 会话线程内工具严格串行且异常即终止循环 ⇒ 待收尾的是最近一条同名 running 事件。
        # F4 起 browser_events_hook 会在宿主工具(code_run)运行期间追加浏览器跳事件(带 step_i 字段),
        # 尾部不再必然是宿主事件 ⇒ 从尾部向前找同名 running(跳事件名为 webcdp.*/droid.*, 与工具名不冲突)。
        ev = None
        for e in reversed(evs):
            if e.get('status') == 'running' and e.get('name') == _text(name, NAME_CAP):
                ev = e
                break
        if ev is None:
            return
        ev['status'] = 'error' if is_err else 'done'
        ev['t_end'] = round(time.time(), 3)
        ev['result_summary'] = _text(data if data is not None else '', SUM_CAP)
        if is_err:
            ev['error'] = _text(data.get('error') or data.get('message') or 'error', SUM_CAP)


register('tool_before', _on_tool_before)
register('tool_after', _on_tool_after)
