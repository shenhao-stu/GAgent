"""droid → recipe 的 trace 键契约（评审实证的两个静默缺陷）。

落账侧 `_trace_args` 写出的键必须与 recipe.trace_to_recipe 读取的键一一对应。
错键不会报错，只会让录制字段恒为空/恒落默认值：
- scroll 的 direction 全落默认 'up' → 回放朝反方向滚，列表底部必然 scrolled=False → 升级；
- paste 的 value 恒 '' → 回放 paste('') 直接抛 ValueError 逃出 recipe_run。
另覆盖 longpress（schema/记忆宣传了 9 个动作，droid 侧曾缺实现）与
_pre_dispatch 的 ABORT 优先级（曾被 sensitive_fg 清空，无效点击继续打进敏感 App）。
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


class _BusCase(unittest.TestCase):
    diff = "0.000% changed"

    def setUp(self):
        phone_ledger.ACTIVE.clear()
        droid._TRACE.clear()
        self.addCleanup(phone_ledger.ACTIVE.clear)
        self.addCleanup(droid._TRACE.clear)
        self.acts = []
        patches = [
            patch.object(droid, 'ping', return_value={"w": 1200, "h": 2670, "rot": 0, "pkg": "com.android.settings"}),
            patch.object(droid, 'shot', return_value=np.zeros((2670, 1200, 3), dtype=np.uint8)),
            patch.object(droid, '_fg', return_value="com.android.settings"),
            patch.object(droid, '_track'),
            patch.object(droid.time, 'sleep'),
            patch.object(droid, '_img_diff_str', lambda a, b: self.diff),
            patch.object(droid, '_act', side_effect=lambda **kw: self.acts.append(kw) or {}),
            patch.object(droid, '_sensitive_fg', return_value=False),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)


class TraceArgsTest(unittest.TestCase):
    """_trace_args 的键映射: 每个 kind 都要写出 recipe 侧读得到的键。"""

    def _args(self, kind, **kw):
        rec = phone_ledger.ActionRecord(kind=kind, **kw)
        return droid._trace_args(rec)

    def test_scroll_writes_direction_from_value(self):
        # scroll 的 value 就是手指方向; 写 {} 会让 recipe 落默认 'up'
        self.assertEqual(self._args("scroll", value="down"), {"direction": "down"})
        self.assertEqual(self._args("scroll", value="left"), {"direction": "left"})

    def test_swipe_writes_direction_derived_from_points(self):
        self.assertEqual(self._args("swipe", point=(600, 1800), point2=(600, 600))["direction"], "up")
        self.assertEqual(self._args("swipe", point=(600, 600), point2=(600, 1800))["direction"], "down")
        self.assertEqual(self._args("swipe", point=(200, 900), point2=(900, 900))["direction"], "right")
        self.assertEqual(self._args("swipe", point=(900, 900), point2=(200, 900))["direction"], "left")

    def test_swipe_without_displacement_has_no_direction(self):
        # 原地手势没有方向; recipe 侧见不到键会自己按坐标推, 不该塞一个假方向
        self.assertNotIn("direction", self._args("swipe", point=(600, 900), point2=(600, 900)))

    def test_swipe_keeps_raw_coordinates(self):
        # dx=dy 时按水平轴判(right), 与 droid._finger_direction 的实现一致
        self.assertEqual(self._args("swipe", point=(1, 2), point2=(3, 4)),
                         {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "direction": "right"})

    def test_point_kinds_write_x_y(self):
        self.assertEqual(self._args("tap", point=(500, 1000)), {"x": 500, "y": 1000})
        self.assertEqual(self._args("longpress", point=(500, 1000)), {"x": 500, "y": 1000})

    def test_input_kinds_write_value(self):
        # recipe 侧读 args['value']; 曾写成 'text' 导致 paste 文本恒空
        self.assertEqual(self._args("paste", value="蓝牙"), {"value": "蓝牙"})

    def test_unhandled_kind_writes_nothing(self):
        self.assertEqual(self._args("key", value="ENTER"), {})


class SettleTraceResultTest(_BusCase):
    """_settle 落 trace 的 result: hit 与 paste 原文必须进去, 否则 recipe 判不出该不该录。"""

    def test_paste_result_carries_hit_and_text(self):
        rec = phone_ledger.ActionRecord(kind="paste", value="蓝牙")
        droid._settle(rec, verdict="settled", diff_pct=99.0, hit=True)
        result = droid._TRACE[-1]["result"]
        self.assertTrue(result["hit"])
        self.assertEqual(result["text"], "蓝牙")

    def test_paste_not_on_screen_records_hit_false(self):
        rec = phone_ledger.ActionRecord(kind="paste", value="蓝牙")
        droid._settle(rec, verdict="settled", diff_pct=0.0, hit=False)
        self.assertIs(droid._TRACE[-1]["result"]["hit"], False)

    def test_tap_result_has_no_text_key(self):
        rec = phone_ledger.ActionRecord(kind="tap", point=(500, 1000))
        droid._settle(rec, verdict="settled", diff_pct=8.0)
        self.assertNotIn("text", droid._TRACE[-1]["result"])

    def test_scroll_settle_writes_direction_into_trace(self):
        # 端到端: scroll() 落账后 trace 里必须能读到 direction(recipe 的唯一来源)
        droid.scroll("down", verify=False)
        self.assertEqual(list(droid._TRACE), [])   # verify=False 无证据不落账(铁律)
        droid.scroll("down")
        entry = droid._TRACE[-1]
        self.assertEqual(entry["kind"], "scroll")
        self.assertEqual(entry["args"]["direction"], "down")

    def test_swipe_settle_writes_direction_into_trace(self):
        droid.swipe(600, 1800, 600, 600)
        entry = droid._TRACE[-1]
        self.assertEqual(entry["kind"], "swipe")
        self.assertEqual(entry["args"]["direction"], "up")


class LongPressTest(_BusCase):
    """longpress: schema/记忆宣传的 9 个动作之一, droid 侧必须真的存在。"""

    def test_longpress_exists_and_dispatches_same_point_swipe(self):
        self.assertTrue(callable(getattr(droid, "longpress", None)))
        droid.longpress(600, 1200, 900)
        self.assertEqual(len(self.acts), 1)
        act = self.acts[0]
        self.assertEqual((act["x1"], act["y1"]), (600, 1200))
        self.assertEqual((act["x2"], act["y2"]), (600, 1200))   # 同点=长按, 不新增总线 op
        self.assertEqual(act["dur"], 900)

    def test_longpress_duration_is_clamped(self):
        droid.longpress(600, 1200, 99)        # 过短退化成点击
        self.assertEqual(self.acts[0]["dur"], 200)
        droid.longpress(600, 1200, 99999)     # 过长白等
        self.assertEqual(self.acts[1]["dur"], 5000)

    def test_longpress_settles_with_point_evidence(self):
        droid.longpress(600, 1200)
        rec = droid._LEDGER.recent()[-1]
        self.assertEqual((rec.kind, rec.point), ("longpress", (600, 1200)))
        self.assertEqual(rec.outcome["verdict"], "settled")
        self.assertTrue(rec.outcome["screenshot_exactly_same"])

    def test_longpress_goes_through_loop_guard(self):
        # 与 tap 同类: 连续无效长按同样受阶梯约束, 不新增豁免
        for _ in range(5):
            droid._LEDGER.append(phone_ledger.ActionRecord(
                kind="longpress", point=(600, 1200), screen=(1200, 2670),
                outcome={"verdict": "settled", "screenshot_exactly_same": True, "diff_pct": 0.0}))
        ret = droid.longpress(600, 1200)
        self.assertTrue(ret.get("aborted"))
        self.assertEqual(self.acts, [])


class AbortBeatsSensitiveForegroundTest(_BusCase):
    """ABORT 必须先于敏感前台判定(它被清空后, 无效点击会继续打进敏感 App)。"""

    def _abort_tail(self, kind="tap"):
        for _ in range(5):
            droid._LEDGER.append(phone_ledger.ActionRecord(
                kind=kind, point=(500, 1000), screen=(1200, 2670),
                outcome={"verdict": "settled", "screenshot_exactly_same": True, "diff_pct": 0.0}))

    def test_abort_survives_sensitive_foreground(self):
        self._abort_tail()
        with patch.object(droid, '_sensitive_fg', return_value=True):
            ret = droid.tap(500, 1000)
        self.assertTrue(ret.get("aborted"))
        self.assertEqual(self.acts, [])      # 一个事件都没注入

    def test_abort_in_non_sensitive_foreground(self):
        self._abort_tail()
        ret = droid.tap(500, 1000)
        self.assertTrue(ret.get("aborted"))

    def test_plain_recovery_is_still_suppressed_on_sensitive_fg(self):
        # 恢复档(系统代发 BACK/HOME)在敏感前台仍要跳过——那正是原设计意图, 不能一起改坏
        for i in range(2):
            droid._LEDGER.append(phone_ledger.ActionRecord(
                kind="tap", point=(500, 1000), screen=(1200, 2670),
                outcome={"verdict": "settled", "screenshot_exactly_same": True, "diff_pct": 0.0}))
        with patch.object(droid, '_sensitive_fg', return_value=True):
            ret = droid.tap(500, 1000)
        self.assertNotIn("recovered", ret)
        self.assertIn("tap", [a.get("op") for a in self.acts])


class InvalidScrollDirectionTest(_BusCase):
    """评审 M5: 方向校验必须先于守卫与落账。

    原实现先建账并跑 _pre_dispatch, 再在 _scroll_impl 里校验方向: 非法方向会被
    守卫改写成 recovered/rejected 并落账, 模型看到的是一个"执行过的动作",
    而不是参数错误。校验提前后, 非法调用 fail-fast 且不污染账本。
    """

    def test_invalid_direction_raises_before_guard_and_is_not_recorded(self):
        for _ in range(5):
            droid._LEDGER.append(phone_ledger.ActionRecord(
                kind="scroll", value="bogus", screen=(1200, 2670),
                outcome={"verdict": "settled", "screenshot_exactly_same": True, "diff_pct": 0.0}))
        with self.assertRaises(ValueError):
            droid.scroll("bogus")
        self.assertEqual(len(droid._LEDGER.recent()), 5)     # 非法调用不新增账


class RecoveryScreenshotFailureTest(_BusCase):
    """评审 M6: 恢复路径的截图失败不能把异常抛给模型。

    _apply_guard 在恢复档先 shot() 再执行 BACK/HOME; 截图失败时原实现直接抛异常,
    待发动作既不结算也不返回。观察不可用时也不能盲目注入系统导航, 只如实结算
    uncertain 并让模型重新观察。
    """

    def _settled_taps(self, n):
        for _ in range(n):
            droid._LEDGER.append(phone_ledger.ActionRecord(
                kind="tap", point=(500, 1000), screen=(1200, 2670),
                outcome={"verdict": "settled", "screenshot_exactly_same": True, "diff_pct": 0.0}))

    def test_screenshot_failure_during_recovery_does_not_raise(self):
        self._settled_taps(3)                  # 第 4 次等价点击 → BACK 档
        with patch.object(droid, 'shot', side_effect=RuntimeError('no frame')):
            ret = droid.tap(500, 1000)
        self.assertTrue(ret.get("uncertain"))
        self.assertNotIn("recovered", ret)     # 没核验就不宣称恢复成功
        self.assertEqual(self.acts, [])        # 观察不可用时不盲目注入 BACK/HOME
        rec = droid._LEDGER.recent()[-1]
        self.assertEqual(rec.outcome.get("verdict"), "uncertain")

    def test_normal_recovery_still_reports_recovered(self):
        self._settled_taps(3)
        ret = droid.tap(500, 1000)
        self.assertEqual(ret.get("recovered"), "BACK")
        self.assertEqual(self.acts[0].get("op"), "back")


class OrientationChangeTest(_BusCase):
    """打开游戏/小程序后屏幕会转横屏: 动作后用一次 ping 检测几何变化,
    立刻返回 uncertain+screen/rot, 不再取 after 截图做昂贵的 diff。"""

    def test_tap_rotation_returns_orientation_without_after_shot(self):
        pings = [
            {"w": 1200, "h": 2670, "rot": 0, "pkg": "com.tencent.mm"},
            {"w": 2670, "h": 1200, "rot": 1, "pkg": "com.tencent.mm"},
        ]
        shots = []
        def _shot(*a, **k):
            shots.append(1)
            return np.zeros((2670, 1200, 3), dtype=np.uint8)
        with patch.object(droid, 'ping', side_effect=pings), \
             patch.object(droid, 'shot', side_effect=_shot):
            ret = droid.tap(500, 1000)
        self.assertTrue(ret.get("uncertain"))
        self.assertTrue(ret.get("orientation_changed"))
        self.assertEqual(ret.get("screen"), (2670, 1200))
        self.assertEqual(ret.get("rot"), 1)
        self.assertEqual(ret.get("orientation"), "landscape")
        self.assertEqual(len(shots), 1)          # 只取动作前帧; 旋转后不再取 after
        rec = droid._LEDGER.recent()[-1]
        self.assertEqual(rec.outcome.get("verdict"), "uncertain")

    def test_tap_reports_current_orientation_when_unchanged(self):
        with patch.object(droid, 'ping', return_value={"w": 1200, "h": 2670, "rot": 0,
                                                       "pkg": "com.android.settings"}):
            ret = droid.tap(500, 1000)
        self.assertEqual(ret.get("screen"), (1200, 2670))
        self.assertEqual(ret.get("rot"), 0)
        self.assertEqual(ret.get("orientation"), "portrait")
        self.assertNotIn("orientation_changed", ret)


class LaunchOrientationTest(_BusCase):
    def test_launch_returns_screen_and_orientation(self):
        with patch.object(droid, '_wait_fg', return_value='com.tencent.mm'), \
             patch.object(droid, 'ping', return_value={"w": 2670, "h": 1200, "rot": 1,
                                                       "pkg": "com.tencent.mm"}):
            ret = droid.launch('com.tencent.mm')
        self.assertEqual(ret.get('screen'), (2670, 1200))
        self.assertEqual(ret.get('rot'), 1)
        self.assertEqual(ret.get('orientation'), 'landscape')


class ResetTraceTest(unittest.TestCase):
    def test_reset_trace_clears_trace_and_last_obs(self):
        droid._LAST_OBS = {"nodes": [{"t": "x"}], "detections": [], "screen": None, "pkg": "p"}
        droid._trace("dump", result={"count": 1})
        self.assertTrue(droid._TRACE)
        droid.reset_trace()
        self.assertEqual(list(droid._TRACE), [])
        self.assertIsNone(droid._LAST_OBS)

    def test_new_task_does_not_inherit_previous_trace(self):
        # 任务边界: 上个任务(或上一次 recipe_run 自己)的 dump/tap 痕迹不能混进本次录制
        import types
        import ga_android
        droid._LAST_OBS = {"nodes": [{"t": "x"}], "detections": [], "screen": None, "pkg": "p"}
        droid._trace("tap", args={"x": 500, "y": 1000}, result={"diff_pct": 8.0})
        ga_android.GenericAgentHandler(types.SimpleNamespace())
        self.assertEqual(list(droid._TRACE), [])
        self.assertIsNone(droid._LAST_OBS)


class EnsureFreshObsTest(unittest.TestCase):
    """gui_act 的预观测必须按需: 观测还有效时不该再 dump 一次。

    真机实证: 39 轮任务里模型在 code_run 中用 look() 观测, 而 look() 同样更新
    _LAST_OBS —— 原先 gui_act 每次 tap/swipe/longpress 都无条件先 dump 一次,
    约 20 次各多付一次 a11y 往返。但"动作后必须重新观测"这条安全属性不能丢:
    否则会用动作前的旧观测推导 recipe locator。"""

    def setUp(self):
        droid._TRACE.clear()
        droid._LAST_OBS = None
        droid._OBS_STALE = True
        self.addCleanup(self._restore)

    def _restore(self):
        droid._TRACE.clear()
        droid._LAST_OBS = None
        droid._OBS_STALE = True

    def _stub_dump(self, calls):
        def _dump(full=False):
            calls.append(1)
            droid._LAST_OBS = {"nodes": [{"t": "x"}], "detections": [],
                               "screen": None, "pkg": "p"}
            droid._OBS_STALE = False
            return [{"t": "x"}]
        return _dump

    def test_fresh_observation_is_not_refetched(self):
        calls = []
        with patch.object(droid, 'dump', self._stub_dump(calls)):
            droid.ensure_fresh_obs()                 # 首次: 必须取
            self.assertEqual(len(calls), 1)
            droid.ensure_fresh_obs()                 # 观测仍有效: 不该再取
            self.assertEqual(len(calls), 1)

    def test_stale_observation_is_refetched(self):
        calls = []
        with patch.object(droid, 'dump', self._stub_dump(calls)):
            droid.ensure_fresh_obs()
            droid._OBS_STALE = True                  # 模拟动作已派发
            droid.ensure_fresh_obs()
            self.assertEqual(len(calls), 2)

    def test_dispatch_marks_the_observation_stale(self):
        """安全属性: 动作经 _act 派发后, 观测必须作废——否则会用旧观测推 locator。"""
        calls = []
        with patch.object(droid, 'dump', self._stub_dump(calls)), \
             patch.object(droid, '_base', lambda: 'http://stub'), \
             patch.object(droid, '_SESSION') as sess, \
             patch.object(droid, '_check', lambda r: {}):
            sess.post.return_value = _FakeResp({})
            droid.ensure_fresh_obs()
            self.assertEqual(len(calls), 1)
            droid._act(op='tap', x=1, y=2)
            with patch.object(droid, 'dump', self._stub_dump(calls)):
                droid.ensure_fresh_obs()
            self.assertEqual(len(calls), 2)          # 动作后重新取了

    def test_look_also_refreshes_the_observation(self):
        """模型常用 look() 而非 dump(); look 拿到的东西也该算有效观测。"""
        droid._LAST_OBS = {"nodes": [], "detections": [{"label": "x"}],
                           "screen": (1200, 2670), "pkg": "p"}
        droid._OBS_STALE = False                     # 模拟 look() 刚跑过
        calls = []
        with patch.object(droid, 'dump', self._stub_dump(calls)):
            droid.ensure_fresh_obs()
        self.assertEqual(calls, [])

    def test_no_observation_at_all_forces_a_fetch(self):
        droid._LAST_OBS = None
        droid._OBS_STALE = False                     # 标志说有效但没有观测 → 仍要取
        calls = []
        with patch.object(droid, 'dump', self._stub_dump(calls)):
            droid.ensure_fresh_obs()
        self.assertEqual(len(calls), 1)

    def test_reset_trace_marks_observation_stale(self):
        droid._LAST_OBS = {"nodes": [], "detections": [], "screen": None, "pkg": "p"}
        droid._OBS_STALE = False
        droid.reset_trace()
        self.assertTrue(droid._OBS_STALE)            # 新任务第一次动作前必须补观测


class _FakeResp:
    def __init__(self, payload): self._p = payload
    def json(self): return self._p


if __name__ == '__main__':
    unittest.main()
