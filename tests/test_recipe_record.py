"""R4: 录制器——把一次成功运行的设备操作痕迹机械转成配方（SPEC Phase 1）。

设计要点：
- 输入是 droid 侧记录的 operation trace（每次 launch/tap/swipe/paste/scroll/look/dump/back/home），
  不是模型写的代码——所以录制零模型调用、可离线复现。
- 点的 locator 从「动作点所在的节点」推导（text/desc），解析不到才退 relative 并标记 fragile；
  观测步（look/dump）转成 observe + min_nodes；launch/back/home 用 any 定位器。
- expected 全部来自该动作已有的验证产出（diff/前台），不新造判定。
"""
import sys
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import recipe


def _op(kind, **kw):
    base = {"kind": kind, "args": {}, "result": {}, "obs": None}
    base.update(kw)
    return base


def _obs(nodes, pkg="com.tencent.news", screen=(1200, 2670)):
    return {"nodes": nodes, "detections": [], "screen": screen, "pkg": pkg}


SEARCH_NODE = {"t": "搜索", "x": 645, "y": 598, "b": "182,527,1109,670", "click": 1}
LIST_NODES = [{"t": "新闻%d" % i, "x": 600, "y": 400 + i * 100,
               "b": "0,%d,1200,%d" % (350 + i * 100, 440 + i * 100)} for i in range(5)]


class TraceToRecipeTest(unittest.TestCase):
    def test_launch_lookup_tap_becomes_three_steps(self):
        trace = [
            _op("launch", args={"pkg": "com.tencent.news"},
                result={"pkg": "com.tencent.news"}),
            _op("look", result={"count": 26}),
            _op("tap", args={"x": 645, "y": 598}, result={"diff_pct": 8.0},
                obs=_obs([SEARCH_NODE])),
        ]
        r = recipe.trace_to_recipe(trace, {"app": "腾讯新闻"})
        kinds = [s.action["kind"] for s in r.steps]
        self.assertEqual(kinds, ["launch", "observe", "tap"])
        self.assertEqual(r.app_hint["package"], "com.tencent.news")
        # 点的 locator 从所在节点推导, 不存坐标
        self.assertEqual(r.steps[2].locator, {"kind": "text", "value": "搜索"})
        self.assertEqual(r.steps[2].expected["kind"], "diff_at_least")
        # launch 步期望前台
        self.assertEqual(r.steps[0].expected, {"kind": "foreground_is", "value": "com.tencent.news"})

    def test_observe_step_uses_min_nodes(self):
        trace = [_op("look", result={"count": 26}, obs=_obs(LIST_NODES))]
        r = recipe.trace_to_recipe(trace, {"app": "腾讯新闻"})
        self.assertEqual(r.steps[0].action["kind"], "observe")
        self.assertEqual(r.steps[0].expected["kind"], "min_nodes")
        self.assertEqual(r.steps[0].expected["value"], 5)

    def test_no_effect_tap_becomes_diff_at_most(self):
        trace = [_op("tap", args={"x": 645, "y": 598}, result={"diff_pct": 0.0},
                     obs=_obs([SEARCH_NODE]))]
        r = recipe.trace_to_recipe(trace, {"app": "X"})
        self.assertEqual(r.steps[0].expected["kind"], "diff_at_most")

    def test_point_outside_any_node_falls_back_to_relative_and_marks_fragile(self):
        trace = [_op("tap", args={"x": 60, "y": 2600}, result={"diff_pct": 3.0},
                     obs=_obs([SEARCH_NODE]))]
        r = recipe.trace_to_recipe(trace, {"app": "X"})
        self.assertEqual(r.steps[0].locator["kind"], "relative")
        self.assertTrue(r.fragile)

    def test_scroll_becomes_observe_roi_step(self):
        trace = [_op("scroll", args={"direction": "up"}, result={"scrolled": True})]
        r = recipe.trace_to_recipe(trace, {"app": "X"})
        self.assertEqual(r.steps[0].action["kind"], "swipe")
        self.assertEqual(r.steps[0].locator["kind"], "roi")

    def test_wait_ops_are_dropped(self):
        trace = [_op("launch", args={"pkg": "com.tencent.news"}, result={"pkg": "com.tencent.news"}),
                 _op("wait", args={"seconds": 2}),
                 _op("back", result={"diff_pct": 12.0})]
        r = recipe.trace_to_recipe(trace, {"app": "X"})
        self.assertEqual([s.action["kind"] for s in r.steps], ["launch", "back"])

    def test_paste_step_keeps_value(self):
        # droid._settle 落 trace 用的键是 value(INPUT_KINDS 分支), 不是 text
        trace = [_op("paste", args={"value": "蓝牙"}, result={"hit": True},
                     obs=_obs([{"t": "", "edit": 1, "x": 600, "y": 2300, "b": "100,2200,1100,2300"}]))]
        r = recipe.trace_to_recipe(trace, {"app": "X"})
        self.assertEqual(r.steps[0].action, {"kind": "paste", "value": "蓝牙"})
        # expected 由 hit 推导成 text_appears(回放时靠动作后观测核验, 见 _STATE_EXPECTED)
        self.assertEqual(r.steps[0].expected, {"kind": "text_appears", "value": "蓝牙"})

    def test_paste_value_also_read_from_result_text(self):
        # 老 trace 只有 result.text 没有 args.value 时也要能取到原文
        trace = [_op("paste", args={}, result={"hit": True, "text": "蓝牙"})]
        r = recipe.trace_to_recipe(trace, {"app": "X"})
        self.assertEqual(r.steps[0].action["value"], "蓝牙")

    def test_unverified_paste_not_recorded(self):
        # 未上屏/被守卫拦下/验证不可用的输入不进配方: 录进去回放必然升级, 还把配方弄脏
        for res in ({"hit": False}, {"hit": False, "text": "x"}, {}, {"verdict": "uncertain"}):
            trace = [_op("paste", args={"value": "蓝牙"}, result=res)]
            with self.assertRaises(recipe.RecipeError):
                recipe.trace_to_recipe(trace, {"app": "X"})

    def test_paste_without_text_not_recorded(self):
        # 无原文可回放(paste('') 必抛 ValueError)
        trace = [_op("paste", args={}, result={"hit": True})]
        with self.assertRaises(recipe.RecipeError):
            recipe.trace_to_recipe(trace, {"app": "X"})

    def test_swipe_direction_comes_from_trace_not_default(self):
        # 手指方向必须来自 trace; 缺键时按坐标推, 不猜默认值
        trace = [_op("swipe", args={"x1": 900, "y1": 1800, "x2": 900, "y2": 600, "direction": "up"},
                     result={"diff_pct": 20.0})]
        r = recipe.trace_to_recipe(trace, {"app": "X"})
        self.assertEqual(r.steps[0].action["direction"], "up")

    def test_swipe_direction_derived_from_coordinates(self):
        # 向下拖(y 增大)=手指方向 down; 老 trace 没有 direction 键时的兜底
        trace = [_op("swipe", args={"x1": 600, "y1": 600, "x2": 600, "y2": 1800},
                     result={"diff_pct": 20.0})]
        r = recipe.trace_to_recipe(trace, {"app": "X"})
        self.assertEqual(r.steps[0].action["direction"], "down")

    def test_scroll_direction_comes_from_trace(self):
        # scroll 的 value 就是手指方向, 不该塌成默认 'up'
        trace = [_op("scroll", args={"direction": "down"}, result={"scrolled": True})]
        r = recipe.trace_to_recipe(trace, {"app": "X"})
        self.assertEqual(r.steps[0].action["kind"], "swipe")
        self.assertEqual(r.steps[0].action["direction"], "down")

    def test_chinese_app_names_get_distinct_recipe_ids(self):
        # 中文名经字符过滤会塌缩成同一个 '_' → 不同 App 的配方互相覆盖
        trace = [_op("launch", args={"pkg": "p"}, result={"pkg": "p"})]
        ids = {app: recipe.trace_to_recipe(trace, {"app": app}).recipe_id
               for app in ("腾讯新闻", "美团", "高德地图", "微博")}
        self.assertEqual(len(set(ids.values())), len(ids))
        self.assertNotIn("recipe._", ids.values())
        # 同一 App 必须可复现(幂等), 否则每次录制都是新配方
        self.assertEqual(recipe.trace_to_recipe(trace, {"app": "腾讯新闻"}).recipe_id,
                         ids["腾讯新闻"])

    def test_ascii_app_name_id_unchanged(self):
        trace = [_op("launch", args={"pkg": "p"}, result={"pkg": "p"})]
        self.assertEqual(recipe.trace_to_recipe(trace, {"app": "X"}).recipe_id, "recipe.X")

    def test_empty_trace_rejected(self):
        with self.assertRaises(recipe.RecipeError):
            recipe.trace_to_recipe([], {"app": "X"})

    def test_resulting_recipe_validates(self):
        trace = [
            _op("launch", args={"pkg": "com.tencent.news"}, result={"pkg": "com.tencent.news"}),
            _op("look", result={"count": 26}, obs=_obs(LIST_NODES)),
            _op("tap", args={"x": 645, "y": 598}, result={"diff_pct": 8.0}, obs=_obs([SEARCH_NODE])),
        ]
        d = recipe.recipe_to_dict(recipe.trace_to_recipe(trace, {"app": "腾讯新闻"}))
        recipe.validate_recipe(d)      # 不得抛错——产出必须是合法配方


if __name__ == "__main__":
    unittest.main()


class LeadingResetTest(unittest.TestCase):
    def test_leading_home_is_dropped(self):
        trace = [_op("home", result={"diff_pct": 12.0}),
                 _op("launch", args={"pkg": "com.tencent.news"}, result={"pkg": "com.tencent.news"}),
                 _op("tap", args={"x": 1, "y": 1}, result={"diff_pct": 3.0}, obs=_obs([SEARCH_NODE]))]
        r = recipe.trace_to_recipe(trace, {"app": "腾讯新闻"})
        self.assertEqual([s.action["kind"] for s in r.steps], ["launch", "tap"])

    def test_home_after_actions_is_kept(self):
        trace = [_op("launch", args={"pkg": "p"}, result={"pkg": "p"}),
                 _op("home", result={"diff_pct": 12.0})]
        r = recipe.trace_to_recipe(trace, {"app": "X"})
        self.assertEqual([s.action["kind"] for s in r.steps], ["launch", "home"])
