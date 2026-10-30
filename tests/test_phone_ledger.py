"""phone_ledger: 动作账本与三档防循环（SPEC 赋能 W3a 纯函数层）。

铁律（对应 SPEC 红线「无未知结果重试」的加强）：
- 所有判定只消费已结算记录（outcome.verdict 已知），不猜未落地结果；
- 恢复阶梯每步有界、以 ABORT 收尾，屏幕一变或换动作即解除；
- 产出新证据的滚动不计循环（长列表有效扫描豁免，来自 mobile-agent 的教训）。
"""
import re
import sys
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import phone_ledger as pl


def rec(kind="tap", point=(500, 1000), point2=(), value="", screen=(1200, 2670),
        verdict="settled", exact=False, pct=0.0, fg="com.android.settings", **extra):
    outcome = {"verdict": verdict, "screenshot_exactly_same": exact, "diff_pct": pct, "fg": fg}
    outcome.update(extra)
    return pl.ActionRecord(kind=kind, point=point, point2=point2, value=value,
                           screen=screen, outcome=outcome)


def n_taps(n, exact=True, pct=0.0, point=(500, 1000)):
    return [rec("tap", point=point, exact=exact, pct=pct) for _ in range(n)]


class EquivalenceTest(unittest.TestCase):
    def test_same_tap_within_tolerance_is_equivalent(self):
        self.assertTrue(pl.equivalent(rec(point=(500, 1000)), rec(point=(505, 1004))))

    def test_same_tap_beyond_tolerance_is_not_equivalent(self):
        self.assertFalse(pl.equivalent(rec(point=(500, 1000)), rec(point=(560, 1000))))

    def test_different_kind_is_never_equivalent(self):
        self.assertFalse(pl.equivalent(rec("tap"), rec("key", value="ENTER")))

    def test_same_physical_point_on_rotated_screen_is_not_equivalent(self):
        # 归一化按各自记录时的屏幕: 同物理点在不同宽高=不同相对位置
        self.assertFalse(pl.equivalent(rec(point=(600, 300), screen=(1200, 2670)),
                                       rec(point=(600, 300), screen=(2670, 1200))))

    def test_swipe_compares_both_endpoints(self):
        a = rec("swipe", point=(600, 2000), point2=(600, 800))
        b = rec("swipe", point=(604, 1996), point2=(596, 804))
        c = rec("swipe", point=(600, 2000), point2=(600, 400))
        self.assertTrue(pl.equivalent(a, b))
        self.assertFalse(pl.equivalent(a, c))

    def test_paste_compares_value_not_point(self):
        self.assertTrue(pl.equivalent(rec("paste", value="hello", point=()), rec("paste", value="hello", point=(1, 2))))
        self.assertFalse(pl.equivalent(rec("paste", value="hello"), rec("paste", value="hell0")))


class RepetitionHintTest(unittest.TestCase):
    def test_five_equivalent_taps_with_exact_evidence_state_no_effect(self):
        hint = pl.repetition_hint(n_taps(5, exact=True))
        self.assertIn("逐次无可观察变化", hint)
        self.assertIn("没有产生可观察效果", hint)

    def test_repetition_without_exact_evidence_asks_to_compare_not_asserts(self):
        hint = pl.repetition_hint(n_taps(5, exact=False, pct=0.01))
        self.assertIn("不能仅根据动作意图判断它是否生效", hint)
        self.assertNotIn("没有产生可观察效果", hint)

    def test_four_equivalent_taps_do_not_trigger(self):
        self.assertIsNone(pl.repetition_hint(n_taps(4, exact=True)))

    def test_abab_sequence_is_reported_as_strategy_loop(self):
        rs = [rec("tap", point=(300, 900)), rec("tap", point=(900, 900)),
              rec("tap", point=(300, 900)), rec("tap", point=(900, 900))]
        hint = pl.repetition_hint(rs)
        self.assertIn("策略循环", hint)

    def test_six_identical_taps_are_not_reported_as_abab(self):
        # 全部互相等价=单动作重复, 由等价规则管; ABAB 规则要求序列内不完全等价
        self.assertNotIn("策略循环", pl.repetition_hint(n_taps(6)) or "")

    def test_four_types_in_five_steps_trigger_type_hint(self):
        rs = [rec("paste", value="13800138000", point=(600, 2300)) for _ in range(4)] + [rec("tap")]
        hint = pl.repetition_hint(rs)
        self.assertIn("文本输入", hint)

    def test_successful_multi_field_inputs_do_not_trigger_type_hint(self):
        # 评审 M2: 多字段填表时每次输入都成功上屏(evidence_new), "最近都在输入"不是循环。
        # 原实现只数 kind, 4 个不同字段的 paste 也会误报"输入未生效"。
        rs = [rec("paste", value=v, point=(600, 2300), evidence_new=True, hit=True)
              for v in ("张三", "13800138000", "北京市", "100000")] + [rec("tap")]
        self.assertIsNone(pl.repetition_hint(rs))

    def test_failed_inputs_still_trigger_type_hint(self):
        # 没有 evidence_new 的连续输入(没确认上屏)仍要提示核对
        rs = [rec("paste", value=v, point=(600, 2300), hit=False)
              for v in ("张三", "13800138000", "北京市", "100000")] + [rec("tap")]
        self.assertIn("文本输入", pl.repetition_hint(rs))

    def test_screen_stuck_needs_three_kinds_all_exact_same(self):
        rs = [rec("tap", exact=True), rec("back", exact=True),
              rec("swipe", point=(600, 2000), point2=(600, 800), exact=True), rec("tap", exact=True)]
        hint = pl.repetition_hint(rs)
        self.assertIn("遮挡", hint)

    def test_screen_stuck_not_triggered_when_a_step_changed_screen(self):
        rs = [rec("tap"), rec("back"), rec("swipe", point=(600, 2000), point2=(600, 800)),
              rec("tap", exact=False, pct=3.0)]
        self.assertIsNone(pl.repetition_hint(rs))


class RejectTest(unittest.TestCase):
    def test_five_settled_equivalent_exact_same_taps_are_rejected(self):
        self.assertEqual(pl.reject_reason(n_taps(5, exact=True)), "repeated_no_effect")

    def test_reject_not_triggered_when_one_step_changed_screen(self):
        rs = n_taps(4, exact=True) + [rec("tap", exact=False, pct=2.0)]
        self.assertIsNone(pl.reject_reason(rs))

    def test_reject_not_triggered_when_a_step_is_uncertain(self):
        rs = n_taps(4, exact=True) + [rec("tap", verdict="uncertain")]
        self.assertIsNone(pl.reject_reason(rs))


class RecoveryLadderTest(unittest.TestCase):
    def test_click_ladder_advances_and_is_bounded(self):
        self.assertEqual(pl.click_recovery(n_taps(3, exact=True)), "WAIT")
        self.assertEqual(pl.click_recovery(n_taps(4, exact=True)), "BACK")
        self.assertEqual(pl.click_recovery(n_taps(5, exact=True)), "HOME")
        self.assertEqual(pl.click_recovery(n_taps(6, exact=True)), "ABORT")
        self.assertEqual(pl.click_recovery(n_taps(9, exact=True)), "ABORT")

    def test_click_recovery_requires_exact_evidence(self):
        self.assertIsNone(pl.click_recovery(n_taps(6, exact=False, pct=0.2)))

    def test_click_recovery_ignores_other_kinds_at_tail(self):
        rs = n_taps(3, exact=True) + [rec("back")]
        self.assertIsNone(pl.click_recovery(rs))

    def test_longpress_walks_the_same_click_ladder(self):
        # 长按与点击同阶梯: kind 曾硬编码 'tap', 长按记录让 _settled_tail 一开头就断,
        # 同一位置反复无效长按永远不拦(评审实证)。
        lp = lambda n: [rec("longpress", point=(600, 1200), exact=True) for _ in range(n)]
        self.assertEqual(pl.click_recovery(lp(3), kind="longpress"), "WAIT")
        self.assertEqual(pl.click_recovery(lp(5), kind="longpress"), "HOME")
        self.assertEqual(pl.click_recovery(lp(6), kind="longpress"), "ABORT")
        # 不传 kind 时仍按 tap 判(向后兼容): 长按记录不该触发 tap 阶梯
        self.assertIsNone(pl.click_recovery(lp(6)))

    def test_tap_records_do_not_trigger_longpress_ladder(self):
        self.assertIsNone(pl.click_recovery(n_taps(6, exact=True), kind="longpress"))

    def test_type_ladder_advances_and_is_bounded(self):
        pastes = lambda n: [rec("paste", value="123456", point=(600, 2300), exact=True) for _ in range(n)]
        self.assertEqual(pl.type_recovery(pastes(2)), "REFOCUS")
        self.assertEqual(pl.type_recovery(pastes(3)), "RETRY")
        self.assertEqual(pl.type_recovery(pastes(4)), "ABORT")
        self.assertEqual(pl.type_recovery(pastes(7)), "ABORT")

    def test_productive_scrolls_never_trigger_loop_guard(self):
        # 长列表有效扫描豁免: 每步都有新证据(截图在变)→ 不提示、不恢复、不拒绝
        rs = [rec("scroll", point=(600, 2000), point2=(600, 800), exact=False, pct=8.0) for _ in range(8)]
        self.assertIsNone(pl.repetition_hint(rs))
        self.assertIsNone(pl.click_recovery(rs))
        self.assertIsNone(pl.reject_reason(rs))

    def test_scroll_at_list_end_is_caught_after_repeats(self):
        # 滑不动了(截图逐次一致)重复 5 次 → 提示(这是正确行为: 可能到底)
        rs = [rec("scroll", point=(600, 2000), point2=(600, 800), exact=True) for _ in range(5)]
        self.assertIsNotNone(pl.repetition_hint(rs))


class KindCoverageTest(unittest.TestCase):
    """评审 M3: 账本声称处理的 kind 必须真的有生产者(droid._new_record)。

    集合里留着产不出记录的类型, 会让"已覆盖"看起来比实际宽——例如
    adb_input_text 从未被任何代码落账, 却出现在输入类集合里。
    """

    def test_every_ledger_kind_has_a_record_producer(self):
        src = (CORE / 'droid.py').read_text(encoding='utf-8')
        produced = set(re.findall(r'_new_record\(\s*"([a-z_]+)"', src))
        self.assertTrue(pl.INPUT_KINDS <= produced,
                        "INPUT_KINDS 含无生产者: %s" % (pl.INPUT_KINDS - produced))
        self.assertTrue(pl._VALUE_KINDS <= produced,
                        "_VALUE_KINDS 含无生产者: %s" % (pl._VALUE_KINDS - produced))


class GuardHintTest(unittest.TestCase):
    def test_guard_hint_none_when_no_signal(self):
        self.assertIsNone(pl.guard_hint([rec("tap"), rec("tap", exact=False, pct=5.0)]))

    def test_guard_hint_present_on_repetition(self):
        self.assertIn("LOOP", pl.guard_hint(n_taps(5, exact=True)))

    def test_ledger_records_and_reports(self):
        led = pl.Ledger()
        for r in n_taps(3, exact=True):
            led.append(r)
        self.assertEqual(len(led.recent(10)), 3)
        self.assertEqual(led.recent(2)[0].kind, "tap")


if __name__ == "__main__":
    unittest.main()
