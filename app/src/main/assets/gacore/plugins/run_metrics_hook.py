"""run_metrics 插件 —— 每 turn 指标落盘(docs/SPEC.md Phase 0 / Part 4.6)。

契约与 tool_events_hook 一致: 执行层零改动, 只挂 agent_loop 既有 hook 点;
任何失败静默(hooks.trigger 已吞异常, 这里再兜一层); 指标只写文件, 不回灌模型上下文。

落盘: <GA_DIR>/temp/model_responses/sessions/metrics_<logid>.jsonl
  —— _clear_temp() 唯一保留的子树, 与 session_*.json 同级。
  <logid> 取自 handler.parent.log_path 的文件名根(与既有 LLM 响应日志同根, 可互相印证),
  **每个会话一份**: 同一会话的多个任务追加到同一文件(agentmain 只在历史截断时轮换 log_path),
  所以 prune_oldest 的"保留最近 N 个"实际是"保留最近 N 个会话的文件"。
已知限制(如实记录):
  - 结构化动作空间(gui_act)落地后工具级判定已经能取到: extract_verdict 解析它的
    json.dumps 结果, attrib_verifier 归因到 droid 侧既有判定函数(_img_diff_str/
    _scroll_verdict/_classify_paste_rows)。走 code_run 的观察与多步逻辑仍无判定键
    → 落 tools_no_verdict, 这是预期: 它正是 SPEC silent-failure rate 的候选。
    只有 diff_pct、没有布尔判定的动作进 tools_pixel_evidence——屏幕变了证不出成功
    也证不出失败, 单列一桶, 不虚高 verified-action rate, 也不算"无判定"。
  - layer 恒为 'L4'、escalations 恒为空: 今天没有路由器, 没有"层"可选。
    字段先立住, Phase 3 路由落地后由路由决策填真值。
  - 后验计时累加器是模块级的(打点在 code_run 子线程, 结算在循环线程, 跨线程)。
    一个 agent 同时只有一个工具调用在飞, 串行场景归属正确; 多会话并行时两段后验
    会落进同一累加器, 归属不再精确——这是已知的取舍, 比"恒为 0"好。
  - 任务被用户中止或抛异常时, agent_loop 的 agent_after 不触发 → 只落已完成的 turn 行,
    没有汇总行; 下一次任务开局会把上次补一条 end_reason='unfinished' 的汇总。
  - 一轮里供应商侧重试/故障转移产生的多次 HTTP 请求只记一次 model_wait(墙钟已含重试)。
"""
import json
import os
import threading
import time

from plugins.hooks import register
import run_metrics

_PREFIX = 'metrics_'
_SUFFIX = '.jsonl'
_lock = threading.Lock()
_tls = threading.local()          # 当前线程(agent 循环线程)的 RunRecorder: 每会话一条线程, 必须按线程隔离
_last_run = {'id': None}          # 上一次运行的 run_id: 模块级, 补写汇总必须跨线程才生效


def _safe(fn, *a):
    try:
        fn(*a)
    except Exception:
        pass


def _current_rec():
    return getattr(_tls, 'rec', None)


def _set_rec(rec):
    _tls.rec = rec


def _ga_dir():
    """进程级真相(android_entry.init 固化); CLI 未设时回退到本文件上两级 = gacore/。"""
    d = os.environ.get('GA_DIR')
    if d:
        return d
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _metrics_dir():
    return os.path.join(_ga_dir(), 'temp', 'model_responses', 'sessions')


def _logid(ctx):
    """与既有 LLM 日志同根(model_responses_<ns>.txt) → 指标与响应日志可互相印证。"""
    raw = ''
    try:
        lp = getattr(getattr(ctx.get('handler'), 'parent', None), 'log_path', '') or ''
        if lp:
            raw = os.path.splitext(os.path.basename(lp))[0].replace('model_responses', '').lstrip('_')
    except Exception:
        raw = ''
    raw = raw or str(time.time_ns())
    return ''.join(c for c in raw if c.isalnum() or c in '_-')[:64] or 'run'


def _gen():
    """Android 侧代际号(与 poll/tool_events 同源); 无归属会话返回 0。"""
    try:
        from kernel_adapter import patches
        st = getattr(patches.current_sess(), 'state', None)
        if isinstance(st, dict):
            return int(st.get('gen', 0) or 0)
    except Exception:
        pass
    return 0


def _resend_chars(ctx):
    """本轮请求往返完成后 BaseSession.history 的序列化字符数(含本轮 user+assistant),
    即下一轮实际重发量的基线。取不到返回 None——不猜, 也不落 0。"""
    try:
        hist = getattr(getattr(ctx.get('client'), 'backend', None), 'history', None)
        if isinstance(hist, list):
            return sum(len(json.dumps(m, ensure_ascii=False, default=str)) for m in hist)
    except Exception:
        pass
    return None


def _make_sink(run_id):
    """每个 run 自带写入口(不读全局/线程变量): end_run 可能在 recorder 已经换人之后才回调,
    届时读"当前 recorder"会静默丢弃整次运行的记录。"""
    def sink(lines):
        run_metrics.append_jsonl(
            os.path.join(_metrics_dir(), _PREFIX + run_id + _SUFFIX), lines)
    return sink


def _install_usage_observer():
    """把 llmcore 的用量观察者接到当前 recorder(幂等; recorder 每次任务换新, 由闭包现取)。"""
    try:
        import llmcore
        llmcore.add_usage_observer(_on_usage)
    except Exception:
        pass


def _on_usage(in_tok, out_tok, cached_tok):
    rec = _current_rec()
    if rec is not None:
        _safe(rec.note_tokens, in_tok, out_tok)


def _has_summary(path):
    """该 run 的指标文件里有没有汇总行。读不了就返回 True(当作有), 不猜也不补写。"""
    try:
        with open(path, encoding='utf-8') as f:
            return any('"run_summary"' in l for l in f)
    except OSError:
        return True


def _backfill_unfinished(run_id):
    """给没有汇总行的运行补一条 end_reason='unfinished', 不丢也不假完成。

    为什么按文件复查, 而不是像原实现那样读内存里的 recorder: agent_after 不在
    agent_loop 的 finally 里, 任务被中止或抛异常时它不触发 → 那次运行只剩 turn 行。
    原实现指望"下次开局时上个 recorder 还在内存里", 但 recorder 存在**线程局部**,
    而上个任务的 agent 循环线程已经死了, 新任务换线程后 _current_rec() 永远读到
    None —— 文档承诺的补写因此在构造上不可能发生。真机实证: 连续 5 次被中止的 run
    全都没有汇总行, 设备上 grep 不到任何 unfinished。单线程测试发现不了这个 bug,
    因为两次 _on_agent_before 落在同一线程, TLS 正好读得到(回归测试因此必须换线程)。"""
    if not run_id:
        return
    path = os.path.join(_metrics_dir(), _PREFIX + run_id + _SUFFIX)
    try:
        if not os.path.exists(path) or _has_summary(path):
            return
        turns = []
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(obj, dict) and obj.get('type') == 'turn':
                    turns.append(obj)
        summary = run_metrics.recovered_summary(run_id, turns) or run_metrics.unfinished_summary(run_id)
        run_metrics.append_jsonl(path, [run_metrics.jsonl_line(summary)])
    except Exception:
        pass


def _on_agent_before(ctx):
    # 兜底一(内存): 上一个 recorder 还在 TLS 里, 说明它的 agent_after 没跑成
    # (中止/异常/末轮 end_turn 被 _safe 吞掉)。当场 flush——turn 行虽是增量写的,
    # 但**最后一个轮次和汇总只由 end_run 落**, 不 flush 就随 recorder 一起蒸发。
    prev = _current_rec()
    _set_rec(None)
    if prev is not None:
        _safe(prev.end_run, 'unfinished')
    # 兜底二(文件): 上个任务的循环线程已经死了, 它的 recorder 只留在那条线程的
    # TLS 里, 新任务换线程后 _current_rec() 永远读到 None——所以还要按文件复查。
    _backfill_unfinished(_last_run.get('id'))
    run_id = _logid(ctx)
    _last_run['id'] = run_id
    _set_rec(run_metrics.RunRecorder(run_id=run_id, gen=_gen(), sink=_make_sink(run_id)))
    _install_usage_observer()
    run_metrics.reset_verify_accumulator()   # 上一轮被中止时可能有僵尸线程还在打点
    _safe(run_metrics.prune_oldest, _metrics_dir(), _PREFIX, run_metrics.DEFAULT_KEEP)


def _on_turn_before(ctx):
    rec = _current_rec()
    if rec is not None:
        _safe(rec.start_turn, int(ctx.get('turn') or 0))


def _on_llm_before(ctx):
    rec = _current_rec()
    if rec is not None:
        _safe(rec.llm_start)


def _on_llm_after(ctx):
    rec = _current_rec()
    if rec is None:
        return
    n = _resend_chars(ctx)
    if n is not None:
        _safe(rec.set_resend_chars, n)
    _safe(rec.llm_end)


def _on_tool_before(ctx):
    if (ctx.get('tool_name') or '') == 'no_tool':
        return                              # 引擎自动触发, 不是工具调用
    rec = _current_rec()
    if rec is not None:
        _safe(rec.tool_start)


def _on_tool_after(ctx):
    if (ctx.get('tool_name') or '') == 'no_tool':
        return                              # 引擎自动触发, 不是工具调用
    rec = _current_rec()
    if rec is None:
        run_metrics.take_verify_seconds()   # 没有进行中的运行也要清账, 别把耗时漏给下一段
        return
    verify_s = run_metrics.take_verify_seconds()   # 先取: 取的过程自己出问题不应连带丢掉工具耗时
    _safe(rec.tool_end, str(ctx.get('tool_name') or ''),
          getattr(ctx.get('ret'), 'data', None), verify_s)


def _on_turn_after(ctx):
    rec = _current_rec()
    if rec is not None:
        _safe(rec.end_turn)


def _on_agent_after(ctx):
    rec = _current_rec()
    _set_rec(None)
    if rec is None:
        return
    reason = ctx.get('exit_reason')
    reason = reason.get('result', '') if isinstance(reason, dict) else ''
    _safe(rec.end_run, reason or 'MAX_TURNS_EXCEEDED')


register('agent_before', _on_agent_before)
register('turn_before', _on_turn_before)
register('llm_before', _on_llm_before)
register('llm_after', _on_llm_after)
register('tool_before', _on_tool_before)
register('tool_after', _on_tool_after)
register('turn_after', _on_turn_after)
register('agent_after', _on_agent_after)
