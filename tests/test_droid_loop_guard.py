"""droid 执行边界的循环守卫（SPEC 赋能 W3b）：落账 + 恢复/拒绝。

契约：
- 只有带证据的动作才落账（verify=True 的 tap/swipe、scroll 聚合、paste 验证后）；
  verify=False 无证据不落账——守卫只判断已证明的事实（SPEC 铁律）。
- 恢复级在 tap 内把动作换成 WAIT→BACK→HOME（有界），拒绝级直接不下发；
  两者都如实结算（恢复后重新截图算 diff），屏幕一变等价尾即断。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import droid
import phone_ledger


def _settled(kind="tap", point=(500, 1000), point2=(), value="", exact=True, pct=0.0):
    return phone_ledger.ActionRecord(
        kind=kind, point=point, point2=point2, value=value, screen=(1200, 2670),
        outcome={"verdict": "settled", "screenshot_exactly_same": exact, "diff_pct": pct})


class _BusCase(unittest.TestCase):
    diff = "0.000% changed"

    def setUp(self):
        phone_ledger.ACTIVE.clear()
        self.addCleanup(phone_ledger.ACTIVE.clear)
        self.acts = []
        patches = [
            patch.object(droid, 'ping', return_value={"w": 1200, "h": 2670, "rot": 0, "pkg": "com.android.settings"}),
            patch.object(droid, 'shot', return_value=np.zeros((2670, 1200, 3), dtype=np.uint8)),
            patch.object(droid, '_fg', return_value="com.android.settings"),
            patch.object(droid, '_track'),
            patch.object(droid.time, 'sleep'),
            patch.object(droid, '_img_diff_str', lambda a, b: self.diff),
            patch.object(droid, '_act', side_effect=lambda **kw: self.acts.append(kw) or {}),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)

    def seed(self, records):
        for r in records:
            droid._LEDGER.append(r)

    def _patch_paste(self, verdict):
        # 按验证阶段名分发: dump 要 list(编辑框节点), ocr_classify 要 dict(判定), shot 走真截屏(已 patch); 其余走默认值
        def _fake_verify(name, fn, errors, default=None):
            if name == "dump":
                return [{"t": "", "edit": 1, "x": 600, "y": 2300, "b": "100,2200,1100,2300"}]
            if name == "ocr_classify":
                return dict(verdict)
            if name == "shot":
                return fn()
            return default
        patches = [
            patch.object(droid, '_sensitive_fg', return_value=False),
            patch.object(droid, 'ocr_text', return_value=("", 0.0)),
            patch.object(droid, '_try_paste_verification', side_effect=_fake_verify),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)


class TapLedgerTest(_BusCase):
    def test_tap_records_settled_with_exact_evidence(self):
        droid.tap(500, 1000)
        r = droid._LEDGER.recent()[-1]
        self.assertEqual((r.kind, r.point), ("tap", (500, 1000)))
        self.assertEqual(r.outcome["verdict"], "settled")
        self.assertTrue(r.outcome["screenshot_exactly_same"])

    def test_tap_with_visible_change_records_diff(self):
        self.diff = "5.000% changed"
        droid.tap(500, 1000)
        r = droid._LEDGER.recent()[-1]
        self.assertFalse(r.outcome["screenshot_exactly_same"])
        self.assertEqual(r.outcome["diff_pct"], 5.0)

    def test_unverified_tap_is_not_recorded(self):
        droid.tap(500, 1000, verify=False)
        self.assertEqual(droid._LEDGER.recent(), [])

    def test_third_equivalent_no_effect_tap_is_replaced_by_wait(self):
        self.seed([_settled(), _settled()])
        ret = droid.tap(500, 1000)
        self.assertEqual(ret.get("recovered"), "WAIT")
        self.assertNotIn("tap", [a.get("op") for a in self.acts])
        r = droid._LEDGER.recent()[-1]
        self.assertEqual(r.outcome.get("recovery"), "WAIT")

    def test_fourth_equivalent_no_effect_tap_escalates_to_back(self):
        waited = phone_ledger.ActionRecord(
            kind="tap", point=(500, 1000), screen=(1200, 2670),
            outcome={"verdict": "recovered", "recovery": "WAIT",
                     "screenshot_exactly_same": True, "diff_pct": 0.0})
        self.seed([_settled(), _settled(), waited])
        ret = droid.tap(500, 1000)
        self.assertEqual(ret.get("recovered"), "BACK")
        self.assertIn("back", [a.get("op") for a in self.acts])

    def test_fifth_equivalent_no_effect_tap_escalates_to_home(self):
        # tap 有恢复阶梯: 第 5 次等价点击=HOME 改写(拒绝级是无阶梯种类如 swipe 的兜底)
        self.seed([_settled() for _ in range(4)])
        ret = droid.tap(500, 1000)
        self.assertEqual(ret.get("recovered"), "HOME")
        self.assertIn("home", [a.get("op") for a in self.acts])

    def test_sixth_equivalent_no_effect_tap_aborts_bounded(self):
        self.seed([_settled() for _ in range(5)])
        ret = droid.tap(500, 1000)
        self.assertTrue(ret.get("aborted"))
        self.assertEqual(self.acts, [])
        self.assertEqual(droid._LEDGER.recent()[-1].outcome["verdict"], "aborted")

    def test_productive_tap_breaks_the_ladder(self):
        self.seed([_settled(), _settled(), _settled(exact=False, pct=8.0)])
        ret = droid.tap(500, 1000)
        self.assertNotIn("recovered", ret)
        self.assertNotIn("rejected", ret)
        self.assertIn("tap", [a.get("op") for a in self.acts])

    def test_recovery_returns_hint_telling_model_to_reobserve(self):
        self.seed([_settled(), _settled()])
        ret = droid.tap(500, 1000)
        self.assertIn("重新观察", ret.get("hint", ""))


class SwipeLedgerTest(_BusCase):
    def test_swipe_records_both_endpoints(self):
        droid.swipe(600, 2000, 600, 800)
        r = droid._LEDGER.recent()[-1]
        self.assertEqual((r.kind, r.point, r.point2), ("swipe", (600, 2000), (600, 800)))

    def test_swipe_has_no_recovery_ladder_but_rejects_on_fifth(self):
        self.seed([_settled(kind="swipe", point=(600, 2000), point2=(600, 800)) for _ in range(4)])
        ret = droid.swipe(600, 2000, 600, 800)
        self.assertEqual(ret.get("rejected"), "repeated_no_effect")
        self.assertEqual(self.acts, [])

    def test_swipe_recovery_not_substituted(self):
        self.seed([_settled(kind="swipe", point=(600, 2000), point2=(600, 800)) for _ in range(3)])
        ret = droid.swipe(600, 2000, 600, 800)
        self.assertNotIn("recovered", ret)
        self.assertIn("swipe", [a.get("op") for a in self.acts])

    def test_uncertain_swipe_recorded_as_uncertain(self):
        with patch.object(droid, '_shape_changed', return_value=True):
            droid.swipe(600, 2000, 600, 800)
        self.assertEqual(droid._LEDGER.recent()[-1].outcome["verdict"], "uncertain")


class LedgerResetTest(unittest.TestCase):
    def test_clear_empties_records(self):
        led = phone_ledger.Ledger()
        led.append(_settled())
        led.clear()
        self.assertEqual(led.recent(), [])


if __name__ == "__main__":
    unittest.main()


class ScrollLedgerTest(_BusCase):
    """scroll 聚合落账: 一次调用一条记录; 有效滚动带 evidence_new(长列表扫描豁免), 滑不动才计等价。"""

    def _patch_scroll(self, pixel_pct, text_ratio=0.5):
        patches = [
            patch.object(droid, 'dump', return_value=[]),
            patch.object(droid, '_scroll_shot', return_value=np.zeros((2670, 1200, 3), dtype=np.uint8)),
            patch.object(droid, '_pixel_change_pct', return_value=pixel_pct),
            patch.object(droid, '_text_change_ratio', return_value=text_ratio),
            patch.object(droid, 'swipe', return_value={}),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)

    def test_productive_scroll_records_evidence_new(self):
        self._patch_scroll(8.0)
        ret = droid.scroll("up")
        self.assertTrue(ret.get("scrolled"))
        r = phone_ledger.ACTIVE.recent()[-1]
        self.assertEqual((r.kind, r.value), ("scroll", "up"))
        self.assertTrue(r.outcome.get("evidence_new"))

    def test_stuck_scroll_records_exact_same(self):
        self._patch_scroll(0.0, text_ratio=0.0)
        ret = droid.scroll("up")
        self.assertFalse(ret.get("scrolled"))
        r = phone_ledger.ACTIVE.recent()[-1]
        self.assertTrue(r.outcome.get("screenshot_exactly_same"))

    def test_scroll_times_records_once(self):
        self._patch_scroll(8.0)
        droid.scroll("up", times=3)
        self.assertEqual(len(phone_ledger.ACTIVE.recent()), 1)

    def test_sixth_stuck_scroll_is_rejected(self):
        self._patch_scroll(0.0, text_ratio=0.0)
        for _ in range(5):
            droid.scroll("up")
        ret = droid.scroll("up")
        self.assertEqual(ret.get("rejected"), "repeated_no_effect")
        self.assertNotIn("swipe", [a.get("op") for a in self.acts])


class PasteLedgerTest(_BusCase):
    """paste 落账: hit=新证据(断尾); 明确未上屏=可证明无效果(进阶梯); 敏感/未解析=uncertain。"""

    def test_paste_hit_records_evidence_new(self):
        self._patch_paste({"hit": True})
        ret = droid.paste("hello")
        self.assertTrue(ret.get("hit"))
        r = phone_ledger.ACTIVE.recent()[-1]
        self.assertEqual(r.kind, "paste")
        self.assertEqual(r.value, "hello")
        self.assertTrue(r.outcome.get("evidence_new"))

    def test_paste_clean_miss_records_exact_same(self):
        self._patch_paste({"hit": False})
        ret = droid.paste("hello")
        self.assertFalse(ret.get("hit"))
        r = phone_ledger.ACTIVE.recent()[-1]
        self.assertTrue(r.outcome.get("screenshot_exactly_same"))

    def test_second_failed_paste_gets_refocus(self):
        phone_ledger.ACTIVE.append(phone_ledger.ActionRecord(
            kind="paste", value="hello", screen=(1200, 2670),
            outcome={"verdict": "settled", "screenshot_exactly_same": True, "diff_pct": 0.0}))
        self._patch_paste({"hit": False})
        ret = droid.paste("hello")
        self.assertEqual(ret.get("recovered"), "REFOCUS")
        self.assertNotIn("paste", [a.get("op") for a in self.acts])

    def test_fourth_failed_paste_aborts_bounded(self):
        for _ in range(3):
            phone_ledger.ACTIVE.append(phone_ledger.ActionRecord(
                kind="paste", value="hello", screen=(1200, 2670),
                outcome={"verdict": "settled", "screenshot_exactly_same": True, "diff_pct": 0.0}))
        self._patch_paste({"hit": False})
        ret = droid.paste("hello")
        self.assertTrue(ret.get("aborted"))
        self.assertNotIn("paste", [a.get("op") for a in self.acts])

    def test_sensitive_paste_records_uncertain(self):
        with patch.object(droid, '_sensitive_fg', return_value=True), \
                patch.object(droid, '_act', side_effect=lambda **kw: self.acts.append(kw) or {}):
            ret = droid.paste("hello")
        self.assertTrue(ret.get("needs_gui_paste"))
        self.assertEqual(phone_ledger.ACTIVE.recent()[-1].outcome["verdict"], "uncertain")
        # 长按“准确的输入框”是有效粘贴路径; 长按空白处才会收起键盘/搜索框
        hint = ret.get("hint", "")
        self.assertIn("长按输入框", hint)
        self.assertIn("粘贴菜单", hint)
        self.assertIn("空白处", hint)


class NoEffectBandTest(_BusCase):
    """I1: 强证据档用「无可观察变化」带(≤0.05%, 与文件内既有 miss 阈值一致), 不用像素全等——
    状态栏时钟跳字≈0.009%, 全等判据会让改写/拒绝两档在有时钟的页面上永不触发。"""

    def test_clock_tick_page_still_gets_ladder(self):
        # 状态栏时钟跳字≈0.009%: 每条记录都算"无可观察变化", 第3次等价点击仍被改写
        self.diff = "0.009% changed"
        droid.tap(500, 1000)
        droid.tap(500, 1000)
        ret = droid.tap(500, 1000)
        self.assertEqual(ret.get("recovered"), "WAIT")

    def test_record_band_classification(self):
        self.diff = "0.009% changed"
        droid.tap(500, 1000)
        self.assertTrue(phone_ledger.ACTIVE.recent()[-1].outcome["screenshot_exactly_same"])
        self.diff = "0.060% changed"
        droid.tap(600, 1300)
        self.assertFalse(phone_ledger.ACTIVE.recent()[-1].outcome["screenshot_exactly_same"])

    def test_clock_tick_page_still_gets_reject(self):
        self.diff = "0.009% changed"
        for _ in range(4):
            droid.swipe(600, 2000, 600, 800)
        ret = droid.swipe(600, 2000, 600, 800)
        self.assertEqual(ret.get("rejected"), "repeated_no_effect")


class SensitiveGuardTest(_BusCase):
    """I2: 策略敏感 App(act=gui)下恢复档不得自主注入 BACK/HOME——只到拒绝/ABORT, 不自主导航。"""

    def _sensitive(self):
        return patch.object(droid, '_sensitive_fg', return_value=True)

    def test_sensitive_fg_skips_recovery_rung(self):
        self.seed([_settled(), _settled()])
        with self._sensitive():
            ret = droid.tap(500, 1000)
        self.assertNotIn("recovered", ret)
        self.assertIn("tap", [a.get("op") for a in self.acts])     # 未到拒绝窗口, 正常派发
        self.assertNotIn("back", [a.get("op") for a in self.acts])
        self.assertNotIn("home", [a.get("op") for a in self.acts])

    def test_sensitive_fg_still_rejects_at_window(self):
        self.seed([_settled() for _ in range(4)])
        with self._sensitive():
            ret = droid.tap(500, 1000)
        self.assertEqual(ret.get("rejected"), "repeated_no_effect")
        self.assertEqual(self.acts, [])

    def test_sensitive_fg_never_dispatches_back_or_home(self):
        self.seed([_settled() for _ in range(6)])
        with self._sensitive():
            for _ in range(3):
                droid.tap(500, 1000)
        ops = [a.get("op") for a in self.acts]
        self.assertNotIn("back", ops)
        self.assertNotIn("home", ops)


class PasteRetryRungTest(_BusCase):
    """M1 的测试半边: RETRY 档放行后再失败必须推进到 ABORT(droid 层锁定最 subtle 的路径)。"""

    def _failed_pastes(self, n):
        for _ in range(n):
            phone_ledger.ACTIVE.append(phone_ledger.ActionRecord(
                kind="paste", value="hello", screen=(1200, 2670),
                outcome={"verdict": "settled", "screenshot_exactly_same": True, "diff_pct": 0.0}))

    def test_retry_rung_dispatches_then_aborts(self):
        self._failed_pastes(2)                      # 第 3 次attempt → RETRY(放行)
        self._patch_paste({"hit": False})
        ret = droid.paste("hello")
        self.assertIn("paste", [a.get("op") for a in self.acts])
        r = phone_ledger.ACTIVE.recent()[-1]
        self.assertTrue(r.outcome.get("screenshot_exactly_same"))   # 放行后又失败=可证明无效果
        ret2 = droid.paste("hello")                 # 第 4 次attempt → ABORT
        self.assertTrue(ret2.get("aborted"))
        self.assertEqual([a.get("op") for a in self.acts].count("paste"), 1)
