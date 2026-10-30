"""R2: locator 解析与 expected 判定（SPEC Phase 1）。

resolve_locator：把配方的 locator 解析到**当前观测**上的具体目标——永不猜：
多命中=不解析(交升级)，零命中=不解析。relative 是最后一级(canvas 类)，总是解析。
check_expected：只做编排，判定数据来自既有验证函数的产出(diff_pct/前台/节点)，
缺数据返回 None(uncertain)——uncertain 一律升级，永不当成功。
"""
import sys
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import recipe


def _obs(nodes=(), detections=(), screen=(1200, 2670), pkg="com.tencent.news"):
    return {"nodes": list(nodes), "detections": list(detections),
            "screen": screen, "pkg": pkg}


NODES = [
    {"t": "搜索", "x": 645, "y": 598, "b": "182,527,1109,670", "click": 1},
    {"t": "要闻", "x": 300, "y": 300, "b": "100,250,500,350"},
    {"d": "返回", "x": 60, "y": 120, "b": "10,80,110,160", "click": 1},
]


class ResolveLocatorTest(unittest.TestCase):
    def test_text_unique_resolves_to_node_center(self):
        r = recipe.resolve_locator(_obs(nodes=NODES), {"kind": "text", "value": "搜索"})
        self.assertEqual(r["point"], (645, 598))
        self.assertEqual(r["source"], "node")

    def test_text_multiple_matches_is_ambiguous(self):
        nodes = NODES + [{"t": "搜索历史", "x": 700, "y": 900, "b": "600,850,800,950"}]
        self.assertIsNone(recipe.resolve_locator(_obs(nodes=nodes), {"kind": "text", "value": "搜索"}))

    def test_text_no_match_returns_none(self):
        self.assertIsNone(recipe.resolve_locator(_obs(nodes=NODES), {"kind": "text", "value": "不存在"}))

    def test_desc_resolves(self):
        r = recipe.resolve_locator(_obs(nodes=NODES), {"kind": "desc", "value": "返回"})
        self.assertEqual(r["point"], (60, 120))

    def test_detections_used_when_nodes_empty(self):
        dets = [{"label": "登录", "cls": "TextButton", "x": 900, "y": 400, "bbox": [800, 350, 1000, 450]}]
        r = recipe.resolve_locator(_obs(detections=dets), {"kind": "text", "value": "登录"})
        self.assertEqual(r["point"], (900, 400))
        self.assertEqual(r["source"], "detection")

    def test_nodes_take_priority_over_detections(self):
        dets = [{"label": "搜索", "cls": "Text", "x": 999, "y": 999, "bbox": [900, 900, 1100, 1100]}]
        r = recipe.resolve_locator(_obs(nodes=NODES, detections=dets), {"kind": "text", "value": "搜索"})
        self.assertEqual(r["source"], "node")

    def test_cls_unique_resolves_multiple_is_ambiguous(self):
        nodes = [{"t": "A", "cls": "Switch", "x": 100, "y": 100, "b": "50,50,150,150"},
                 {"t": "B", "cls": "Switch", "x": 300, "y": 100, "b": "250,50,350,150"}]
        self.assertIsNone(recipe.resolve_locator(_obs(nodes=nodes), {"kind": "cls", "value": "Switch"}))
        r = recipe.resolve_locator(_obs(nodes=nodes[:1]), {"kind": "cls", "value": "Switch"})
        self.assertEqual(r["point"], (100, 100))

    def test_roi_filters_by_region_and_optional_text(self):
        nodes = [{"t": "跳过", "x": 1100, "y": 80, "b": "1000,40,1200,120"}]
        loc = {"kind": "roi", "value": [800, 0, 1000, 100], "text": "跳过"}
        r = recipe.resolve_locator(_obs(nodes=nodes, screen=(1200, 2670)), loc)
        self.assertEqual(r["point"], (1100, 80))

    def test_roi_without_text_unique_in_region(self):
        nodes = [{"t": "跳过", "x": 1100, "y": 80, "b": "1000,40,1200,120"}]
        r = recipe.resolve_locator(_obs(nodes=nodes), {"kind": "roi", "value": [800, 0, 1000, 100]})
        self.assertEqual(r["point"], (1100, 80))

    def test_roi_two_in_region_is_ambiguous(self):
        nodes = [{"t": "跳过", "x": 1100, "y": 80, "b": "1000,40,1200,120"},
                 {"t": "广告", "x": 1050, "y": 200, "b": "1000,160,1200,240"}]
        self.assertIsNone(recipe.resolve_locator(_obs(nodes=nodes), {"kind": "roi", "value": [800, 0, 1000, 100]}))

    def test_relative_always_resolves_and_scales(self):
        r = recipe.resolve_locator(_obs(screen=(1200, 2670)), {"kind": "relative", "value": [500, 250]})
        self.assertEqual(r["point"], (600, 667))


class CheckExpectedTest(unittest.TestCase):
    def test_foreground_is(self):
        self.assertTrue(recipe.check_expected({"kind": "foreground_is", "value": "com.tencent.news"},
                                              {"pkg": "com.tencent.news"}))
        self.assertFalse(recipe.check_expected({"kind": "foreground_is", "value": "com.tencent.news"},
                                               {"pkg": "com.tencent.mm"}))

    def test_foreground_missing_is_uncertain(self):
        self.assertIsNone(recipe.check_expected({"kind": "foreground_is", "value": "x"}, {}))

    def test_diff_at_least_and_at_most(self):
        self.assertTrue(recipe.check_expected({"kind": "diff_at_least", "value": 1.5}, {"diff_pct": 8.0}))
        self.assertFalse(recipe.check_expected({"kind": "diff_at_least", "value": 1.5}, {"diff_pct": 0.2}))
        self.assertTrue(recipe.check_expected({"kind": "diff_at_most", "value": 0.05}, {"diff_pct": 0.0}))
        self.assertFalse(recipe.check_expected({"kind": "diff_at_most", "value": 0.05}, {"diff_pct": 3.0}))

    def test_diff_missing_is_uncertain(self):
        self.assertIsNone(recipe.check_expected({"kind": "diff_at_least", "value": 1.5}, {}))

    def test_min_nodes(self):
        self.assertTrue(recipe.check_expected({"kind": "min_nodes", "value": 3}, {"nodes": [1, 2, 3]}))
        self.assertFalse(recipe.check_expected({"kind": "min_nodes", "value": 3}, {"nodes": [1]}))

    def test_text_appears(self):
        outcome = {"nodes": [{"t": "二十届五中全会"}, {"t": "其他"}]}
        self.assertTrue(recipe.check_expected({"kind": "text_appears", "value": "五中全会"}, outcome))
        self.assertFalse(recipe.check_expected({"kind": "text_appears", "value": "地震"}, outcome))

    def test_text_in_roi(self):
        outcome = {"nodes": [{"t": "跳过", "b": "1000,40,1200,120"}], "screen": (1200, 2670)}
        loc = {"kind": "text_in_roi", "value": "跳过", "roi": [800, 0, 1000, 100]}
        self.assertTrue(recipe.check_expected(loc, outcome))
        self.assertFalse(recipe.check_expected({"kind": "text_in_roi", "value": "广告", "roi": [800, 0, 1000, 100]}, outcome))


if __name__ == "__main__":
    unittest.main()
