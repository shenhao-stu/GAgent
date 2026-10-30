"""每 turn 运行指标: 纯聚合、判定归因、分位与落盘(SPEC.md Part 4.6 / Phase 0)。

全部合成 fixture: 不连设备、不联网、不需要模型 key。
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import run_metrics


@pytest.fixture
def clean_verify():
    """排空线程本地的 verify 累加器(线程本地, 不影响其他测试)。"""
    run_metrics.take_verify_seconds()
    yield
    run_metrics.take_verify_seconds()


class TestExtractVerdict:
    def test_booleans_and_short_enums_are_kept(self):
        data = {'verified': True, 'uncertain': False, 'scrolled': True,
                'evidence': 'pixel', 'performed': True, 'hit': True,
                'hint': 'x' * 500, 'fg': 'com.example.app'}
        assert run_metrics.extract_verdict(data) == {
            'verified': True, 'uncertain': False, 'scrolled': True,
            'evidence': 'pixel', 'performed': True, 'hit': True}

    def test_diff_becomes_a_bare_percentage_without_bbox(self):
        v = run_metrics.extract_verdict({'diff': 'diff: 1.234% bbox=[10,20,30,40]'})
        assert v == {'diff_pct': 1.234}

    def test_unparseable_or_missing_diff_is_dropped(self):
        assert run_metrics.extract_verdict({'diff': 'diff: n/a'}) == {}
        assert run_metrics.extract_verdict({'diff': None}) == {}
        assert run_metrics.extract_verdict({'diff': 12}) == {}

    def test_non_dict_result_yields_nothing(self):
        assert run_metrics.extract_verdict(None) == {}
        assert run_metrics.extract_verdict('a very long tool result') == {}
        assert run_metrics.extract_verdict([{'t': 'node'}]) == {}

    def test_gui_act_json_string_result_is_parsed(self):
        # gui_act 的返回是 json.dumps(out) 字符串。不解析它, 结构化动作通道的判定
        # 全部落进 tools_no_verdict 桶, hit/uncertain/diff_pct 永远不计(评审实证)。
        payload = json.dumps({'action': 'tap', 'point': [500, 500],
                              'diff': 'diff: 12.5% bbox=[1,2,3,4]', 'fg': 'com.example.app'},
                             ensure_ascii=False)
        assert run_metrics.extract_verdict(payload) == {'diff_pct': 12.5}

        assert run_metrics.extract_verdict(json.dumps({'action': 'text', 'hit': True})) == {'hit': True}
        assert run_metrics.extract_verdict(json.dumps({'action': 'text', 'hit': False,
                                                      'uncertain': True})) == {'hit': False, 'uncertain': True}

    def test_non_json_string_still_yields_nothing(self):
        assert run_metrics.extract_verdict('{"broken') == {}
        assert run_metrics.extract_verdict('42') == {}

    def test_expect_verified_is_a_first_class_verdict(self):
        assert run_metrics.extract_verdict({'expect_verified': True}) == {'expect_verified': True}
        assert run_metrics.classify_verdict({'expect_verified': True}) == 'verified'
        # 未命中是软提示, 不是动作失败: 长句期望读不到不能计入 negative。
        assert run_metrics.classify_verdict({'expect_verified': False}) == 'none'
        assert run_metrics.classify_verdict({'expect_verified': False, 'diff_pct': 12.0}) == 'pixel'
        # 真正的动作失败仍然由 verified=False 计负。
        assert run_metrics.classify_verdict({'expect_verified': False, 'verified': False}) == 'negative'
        assert run_metrics.classify_verdict({'expect_verified': False, 'uncertain': True}) == 'uncertain'


class TestAttribVerifier:
    @pytest.mark.parametrize('tool,verdict,expected', [
        ('droid.tap', {'verified': True, 'diff_pct': 1.2}, '_img_diff_str'),
        ('tap', {'uncertain': True, 'diff_pct': 0.0}, '_img_diff_str'),
        ('swipe', {'diff_pct': 2.0}, '_img_diff_str'),
        ('scroll_view', {'scrolled': True, 'evidence': 'text'}, '_scroll_verdict'),
        ('scroll', {'scrolled': False, 'evidence': 'none'}, '_scroll_verdict'),
        ('paste', {'hit': True}, '_classify_paste_rows'),
        ('paste', {'hit': False, 'uncertain': True}, '_classify_paste_rows'),
        ('tap', {'verified': True}, None),          # 无像素证据 → 不归因
        ('file_read', {'verified': True}, None),    # 非判定类工具 → 不归因
        ('dump', {}, None),
        # gui_act 是多路复用器, 按它实际调的既有函数归因
        ('gui_act', {'diff_pct': 12.5}, '_img_diff_str'),
        ('gui_act', {'hit': True}, '_classify_paste_rows'),
    ])
    def test_mapping(self, tool, verdict, expected):
        assert run_metrics.attrib_verifier(tool, verdict) == expected


class TestPercentile:
    def test_empty(self):
        assert run_metrics.percentile([], 50) is None

    def test_single_value(self):
        assert run_metrics.percentile([4.2], 95) == 4.2

    def test_interpolates(self):
        assert run_metrics.percentile([1, 2, 3, 4], 50) == 2.5
        assert run_metrics.percentile([1, 2, 3, 4], 95) == 3.85

    def test_ignores_non_numbers(self):
        assert run_metrics.percentile([1, None, 'x', 3], 50) == 2.0


class TestVerifyAccumulator:
    """打点发生在 code_run 的子线程(ga_android.do_code_run 起 Thread), 结算发生在 agent
    循环线程 —— 累加器必须跨线程, 否则 verify_wait_s 在真实路径上恒为 0。"""

    def test_no_mark_means_no_verify_time(self, clean_verify):
        assert run_metrics.take_verify_seconds() is None

    def test_mark_then_take_is_non_negative_and_one_shot(self, clean_verify):
        run_metrics.mark_action_dispatched()
        first = run_metrics.take_verify_seconds()
        assert first is not None and first >= 0.0
        assert run_metrics.take_verify_seconds() is None

    def test_consecutive_actions_split_the_wait(self, clean_verify):
        """code_run 里连续多个动作: 每段"动作后验"都要计入, 不能只算最后一个。"""
        run_metrics.mark_action_dispatched()
        time.sleep(0.02)
        run_metrics.mark_action_dispatched()      # 第二段动作开始 → 第一段入账
        time.sleep(0.02)
        total = run_metrics.take_verify_seconds()
        assert total >= 0.04

    def test_mark_from_a_child_thread_is_still_counted(self, clean_verify):
        """droid._act 在 code_run 子线程里打点; 线程本地累加器会把这里全丢成 0。"""
        t = threading.Thread(target=run_metrics.mark_action_dispatched, daemon=True)
        t.start(); t.join()
        time.sleep(0.02)
        total = run_metrics.take_verify_seconds()
        assert total is not None and total >= 0.02

    def test_reset_drops_a_stale_mark(self, clean_verify):
        run_metrics.mark_action_dispatched()
        run_metrics.reset_verify_accumulator()
        assert run_metrics.take_verify_seconds() is None


class TestJsonlIO:
    def test_jsonl_line_survives_non_scalar_values(self):
        line = run_metrics.jsonl_line({'a': {1, 2}, 'b': object()})
        assert '\n' not in line
        assert json.loads(line)['b']

    def test_append_creates_the_directory_and_one_object_per_line(self, tmp_path):
        p = tmp_path / 'a' / 'b' / 'metrics_1.jsonl'
        assert run_metrics.append_jsonl(str(p), ['{"a": 1}', '{"b": 2}']) is True
        assert run_metrics.append_jsonl(str(p), ['{"c": 3}']) is True
        assert [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines()] == [
            {'a': 1}, {'b': 2}, {'c': 3}]

    def test_unwritable_path_returns_false_instead_of_raising(self, tmp_path):
        blocker = tmp_path / 'blocker'
        blocker.write_text('not a directory', encoding='utf-8')
        assert run_metrics.append_jsonl(str(blocker / 'x.jsonl'), ['{}']) is False

    def test_prune_keeps_only_the_newest_files(self, tmp_path):
        for i, name in enumerate(['metrics_a.jsonl', 'metrics_b.jsonl', 'metrics_c.jsonl']):
            p = tmp_path / name
            p.write_text('{}', encoding='utf-8')
            os.utime(p, (1000 + i, 1000 + i))
        assert run_metrics.prune_oldest(str(tmp_path), 'metrics_', keep=2) == 1
        assert sorted(x.name for x in tmp_path.iterdir()) == ['metrics_b.jsonl', 'metrics_c.jsonl']

    def test_prune_ignores_other_files_and_missing_dirs(self, tmp_path):
        (tmp_path / 'session_x.json').write_text('{}', encoding='utf-8')
        assert run_metrics.prune_oldest(str(tmp_path), 'metrics_', keep=5) == 0
        assert run_metrics.prune_oldest(str(tmp_path / 'nope'), 'metrics_') == 0


class _FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, secs):
        self.t += secs
        return self.t


class _Sink:
    def __init__(self):
        self.lines = []

    def __call__(self, lines):
        self.lines.extend(lines)


class TestRunRecorder:
    def _rec(self, sink):
        clock = _FakeClock()
        return run_metrics.RunRecorder(run_id='r1', gen=7, clock=clock, sink=sink), clock

    def test_turn_line_carries_the_phase_zero_metric_set(self):
        sink = _Sink()
        rec, clock = self._rec(sink)
        rec.start_turn(1)
        rec.llm_start(); clock.advance(4.8); rec.note_tokens(1975, 42); rec.llm_end()
        rec.set_resend_chars(48213)
        rec.tool_start(); clock.advance(1.35)
        rec.tool_end('droid.tap', {'verified': True, 'diff': 'diff: 1.234% bbox=[1,2,3,4]'}, 0.98)
        clock.advance(0.05)
        rec.end_turn()
        rec.end_run('CURRENT_TASK_DONE')
        turn, summary = (json.loads(x) for x in sink.lines)
        assert turn['type'] == 'turn' and turn['turn'] == 1 and turn['layer'] == 'L4'
        assert turn['model_wait_s'] == 4.8
        assert turn['tool_exec_s'] == 1.35
        assert turn['verify_wait_s'] == 0.98
        assert (turn['in_tok'], turn['out_tok']) == (1975, 42)
        assert turn['resend_chars'] == 48213
        assert turn['n_tools'] == 1 and turn['tools'] == ['droid.tap']
        assert turn['tool_records'][0]['verifier'] == '_img_diff_str'
        assert turn['tool_records'][0]['verdict'] == {'verified': True, 'diff_pct': 1.234}
        assert turn['escalations'] == []
        assert summary['type'] == 'run_summary'
        assert summary['turns'] == 1 and summary['model_calls'] == 1
        assert summary['p50_turn_s'] == 6.15 and summary['p95_turn_s'] == 6.15
        assert summary['tools_verified'] == 1
        assert summary['tools_total'] == 1
        assert summary['tools_uncertain'] == 0 and summary['tools_no_verdict'] == 0

    def test_tokens_are_attributed_to_the_turn_that_asked(self):
        sink = _Sink()
        rec, clock = self._rec(sink)
        rec.start_turn(1); rec.llm_start(); rec.note_tokens(10, 1); rec.llm_end(); rec.end_turn()
        rec.start_turn(2); rec.llm_start(); clock.advance(1.0); rec.llm_end(); rec.end_turn()
        rec.end_run('MAX_TURNS_EXCEEDED')
        t1, t2 = (json.loads(x) for x in sink.lines[:2])
        assert (t1['in_tok'], t1['out_tok']) == (10, 1)
        assert (t2['in_tok'], t2['out_tok']) == (0, 0)

    def test_one_request_reporting_usage_twice_is_not_double_counted(self):
        """Claude 流式: message_start 的 output_tokens 是占位值, message_delta 才是终值。"""
        sink = _Sink()
        rec, clock = self._rec(sink)
        rec.start_turn(1); rec.llm_start()
        rec.note_tokens(1975, 1); rec.note_tokens(0, 42)
        rec.llm_end(); rec.end_turn()
        assert json.loads(sink.lines[0])['out_tok'] == 42

    def test_unfinished_turn_is_flushed_when_the_run_ends(self):
        """循环被 break(末轮不走 turn_after)时, 最后一轮仍要落一行, 不丢。"""
        sink = _Sink()
        rec, clock = self._rec(sink)
        rec.start_turn(3); rec.llm_start(); clock.advance(2.0); rec.llm_end()
        rec.end_run('CURRENT_TASK_DONE')
        assert [json.loads(x)['turn'] for x in sink.lines[:-1]] == [3]   # 末行是汇总, 没有 turn 键
        assert json.loads(sink.lines[-1])['turns'] == 1

    def test_a_failing_sink_never_raises(self):
        """观测失败绝不能影响 agent 主循环。"""
        def boom(lines):
            raise OSError('disk full')

        rec = run_metrics.RunRecorder(run_id='r', clock=_FakeClock(), sink=boom)
        rec.start_turn(1); rec.llm_start(); rec.llm_end(); rec.end_turn()
        rec.end_run('done')          # 不抛即通过

    def test_summary_counters_partition_every_tool_record(self):
        """五个计数器必须互斥且穷尽, 否则 verified-action rate 会悄悄漏算最常见动作。"""
        sink = _Sink()
        rec, clock = self._rec(sink)
        rec.start_turn(1)
        rec.tool_start(); clock.advance(1.0)
        rec.tool_end('droid.tap', {'uncertain': True}, None)                      # uncertain
        rec.tool_start(); clock.advance(1.0)
        rec.tool_end('droid.scroll_view', {'scrolled': True, 'evidence': 'text'}, 0.4)   # verified
        rec.tool_start(); clock.advance(1.0)
        rec.tool_end('droid.paste', {'hit': False}, None)                          # negative
        rec.tool_start(); clock.advance(1.0)
        rec.tool_end('gui_act', {'diff': 'diff: 9.125% bbox=[1,2,3,4]'}, None)      # pixel
        rec.tool_start(); clock.advance(1.0)
        rec.tool_end('file_read', {'content': 'x' * 100}, None)                    # 无判定键
        rec.end_turn(); rec.end_run('done')
        s = json.loads(sink.lines[-1])
        assert (s['tools_verified'], s['tools_uncertain'], s['tools_negative'],
                s['tools_pixel_evidence'], s['tools_no_verdict']) == (1, 1, 1, 1, 1)
        assert (s['tools_verified'] + s['tools_uncertain'] + s['tools_negative']
                + s['tools_pixel_evidence'] + s['tools_no_verdict']
                == s['tools_total'] == 5)
        assert s['verify_wait_s'] == 0.4
        assert s['tool_exec_s'] == 5.0

    def test_pixel_evidence_is_not_counted_as_no_verdict(self):
        """回归(真机实证): 46 轮微信任务里 16 次 gui_act 只带 diff_pct, 旧实现把它们
        算进 tools_no_verdict → tools_no_verdict=42/45、verified-action rate 显示 0%。
        diff_pct 是 extract_verdict 解析出的判定键, 不是"无判定"。"""
        sink = _Sink()
        rec, clock = self._rec(sink)
        rec.start_turn(1)
        for _ in range(16):
            rec.tool_start(); clock.advance(1.0)
            # 真机形态: gui_act 返回 {'action':'tap','diff':'diff: 22.658% ...'},
            # diff_pct 由 extract_verdict 从 diff 字符串解析出来
            rec.tool_end('gui_act', {'diff': 'diff: 22.658% bbox=[1,2,3,4]'}, None)
        for _ in range(3):
            rec.tool_start(); clock.advance(1.0)
            rec.tool_end('code_run', {}, None)
        rec.end_turn(); rec.end_run('done')
        s = json.loads(sink.lines[-1])
        assert (s['tools_pixel_evidence'], s['tools_no_verdict']) == (16, 3)
        assert s['tools_verified'] == 0          # 像素证据不虚高成功率

    def test_uncertain_outranks_a_simultaneous_hit_true(self):
        """回归: {'hit': True, 'uncertain': True} 曾同时计入 verified 和 uncertain,
        五桶相加越过 tools_total, 把 tools_no_verdict 算成负数。"""
        sink = _Sink()
        rec, clock = self._rec(sink)
        rec.start_turn(1)
        rec.tool_start(); clock.advance(1.0)
        rec.tool_end('gui_act', {'hit': True, 'uncertain': True}, None)
        rec.end_turn(); rec.end_run('done')
        s = json.loads(sink.lines[-1])
        assert (s['tools_verified'], s['tools_uncertain']) == (0, 1)
        assert (s['tools_verified'] + s['tools_uncertain'] + s['tools_negative']
                + s['tools_pixel_evidence'] + s['tools_no_verdict']) == s['tools_total'] == 1

    def test_boolean_verdict_with_diff_still_lands_in_its_boolean_bucket(self):
        # 同时带布尔判定和 diff_pct 时, 布尔优先(diff 只是附带证据)
        assert run_metrics.classify_verdict({'hit': True, 'diff_pct': 8.0}) == 'verified'
        assert run_metrics.classify_verdict({'hit': False, 'diff_pct': 0.01}) == 'negative'
        assert run_metrics.classify_verdict({'uncertain': True, 'diff_pct': 100.0}) == 'uncertain'

    def test_classify_verdict_edge_cases(self):
        assert run_metrics.classify_verdict({}) == 'none'
        assert run_metrics.classify_verdict(None) == 'none'
        assert run_metrics.classify_verdict({'diff_pct': 0.0}) == 'pixel'   # 0.0 也是证据(明确无变化)
        assert run_metrics.classify_verdict({'evidence': 'none'}) == 'negative'

    def test_unknown_resend_chars_stays_null_not_zero(self):
        """取不到重发体量时必须落 null; 0 会被读成"历史是空的"。"""
        sink = _Sink()
        rec, clock = self._rec(sink)
        rec.start_turn(1); rec.llm_start(); rec.llm_end(); rec.end_turn()
        assert json.loads(sink.lines[0])['resend_chars'] is None

    def test_tool_without_a_dispatched_action_has_no_verify_time(self):
        sink = _Sink()
        rec, clock = self._rec(sink)
        rec.start_turn(1)
        rec.tool_start(); clock.advance(0.5)
        rec.tool_end('file_read', {}, None)
        rec.end_turn()
        assert json.loads(sink.lines[0])['tool_records'][0]['verify_s'] is None


class TestRecoveredSummary:
    """B: 手动中止/跨线程的 run 只剩 turn 行, 汇总要从这些行重建, 不能只留 stub。"""

    def _turn(self, n, model, tool, in_tok, out_tok, verdicts):
        return {'type': 'turn', 'turn': n, 'layer': 'L4', 't_start': 1000 + n * 10,
                'model_wait_s': model, 'tool_exec_s': tool, 'verify_wait_s': 0,
                'in_tok': in_tok, 'out_tok': out_tok, 'resend_chars': 100 + n,
                'escalations': [],
                'tool_records': [{'name': 'gui_act', 'exec_s': 1, 'verify_s': 0,
                                  'verdict': v, 'verifier': None} for v in verdicts]}

    def test_rebuilds_totals_buckets_and_span_from_turn_rows(self):
        turns = [self._turn(1, 4, 2, 100, 10, [{'diff_pct': 5.0}, {'hit': True}]),
                 self._turn(2, 6, 3, 200, 20, [{'uncertain': True}])]
        s = run_metrics.recovered_summary('r1', turns)
        assert s['recovered'] is True
        assert s['summary_source'] == 'turn_rows'
        assert s['ended_at_estimated'] is True
        assert s['turns'] == 2 and s['model_calls'] == 2
        assert s['model_wait_s'] == 10 and s['tool_exec_s'] == 5
        assert s['in_tok'] == 300 and s['out_tok'] == 30
        assert s['started_at'] == 1010
        assert s['ended_at'] == 1029          # 最后一轮 t_start + model_wait + tool_exec
        assert (s['tools_verified'], s['tools_uncertain'], s['tools_pixel_evidence'],
                s['tools_no_verdict']) == (1, 1, 1, 0)
        assert s['tools_total'] == 3
        assert s['p50_turn_s'] == 7.5          # [4+2, 6+3] 的中位
        assert s['end_reason'] == 'unfinished'

    def test_no_turn_rows_returns_none_so_caller_keeps_the_honest_stub(self):
        assert run_metrics.recovered_summary('r1', []) is None
        assert run_metrics.recovered_summary('r1', [{'type': 'run_summary'}]) is None


class TestActionMark:
    """droid._act() 是动作派发唯一入口; 打完点必须原样返回, 且任何异常路径不得被观测改变。"""

    def test_act_marks_the_dispatch_and_returns_unchanged(self, monkeypatch, clean_verify):
        import droid
        marks = []
        monkeypatch.setattr(droid.run_metrics, 'mark_action_dispatched', lambda: marks.append(1))
        monkeypatch.setattr(droid, '_gate_injection', lambda op: None)
        monkeypatch.setattr(droid, '_record_path', lambda kind: None)
        monkeypatch.setattr(droid, '_base', lambda: 'http://127.0.0.1:1')   # 否则回退分支会 ping 真机总线
        monkeypatch.setattr(droid, '_check', lambda r: {'ok': True, 'x': 1})
        monkeypatch.setattr(droid, '_SESSION', type('S', (), {'post': staticmethod(lambda *a, **k: None)})())
        assert droid._act(op='tap', x=1, y=2) == {'ok': True, 'x': 1}
        assert marks == [1]

    def test_a_failing_mark_never_breaks_a_dispatched_action(self, monkeypatch, clean_verify):
        """观测绝不能把"已经发出去的手势"报成失败——那会诱发结局未知的重试。"""
        import droid

        def boom():
            raise RuntimeError('observer bug')

        monkeypatch.setattr(droid.run_metrics, 'mark_action_dispatched', boom)
        monkeypatch.setattr(droid, '_gate_injection', lambda op: None)
        monkeypatch.setattr(droid, '_record_path', lambda kind: None)
        monkeypatch.setattr(droid, '_base', lambda: 'http://127.0.0.1:1')
        monkeypatch.setattr(droid, '_check', lambda r: {'ok': True})
        monkeypatch.setattr(droid, '_SESSION', type('S', (), {'post': staticmethod(lambda *a, **k: None)})())
        assert droid._act(op='tap', x=1, y=2) == {'ok': True}
