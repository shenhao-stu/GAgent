"""R5b: droid 侧接线（SPEC Phase 1 最后一公里）。

- 每次设备操作（launch/tap/swipe/paste/scroll/look/dump/back/home）进 operation trace，
  观测带紧凑快照——录制因此零模型调用、可离线复现；
- recipe_record() 从 trace 机械派生配方落盘；recipe_run() 回放（observe/act 接真 droid），
  升级即记账并交回上层（L4）；
- 回放全程无 LLM 路径。
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import droid
import recipe


SEARCH_NODES = [{"t": "搜索", "x": 645, "y": 598, "b": "182,527,1109,670", "click": 1}]


class _Bus(unittest.TestCase):
    def setUp(self):
        droid._TRACE.clear()
        droid._LAST_OBS = None
        phone_ledger_clear = getattr(droid, "_LEDGER", None)
        if phone_ledger_clear is not None:
            phone_ledger_clear.clear()
        self.tmp = tempfile.mkdtemp(prefix="recipe_run_")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        patches = [
            patch.object(droid, 'ping', return_value={"w": 1200, "h": 2670, "rot": 0, "pkg": "com.tencent.news"}),
            patch.object(droid, 'shot', return_value=np.zeros((2670, 1200, 3), dtype=np.uint8)),
            patch.object(droid, '_fg', return_value="com.tencent.news"),
            patch.object(droid, '_track'),
            patch.object(droid.time, 'sleep'),
            patch.object(droid, '_img_diff_str', lambda a, b: "8.000% changed"),
            patch.object(droid, '_act', side_effect=lambda **kw: {}),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)

    def _store(self):
        return recipe.RecipeStore(self.tmp)


class TraceRecordingTest(_Bus):
    def test_tap_records_trace_with_compact_obs(self):
        droid._LAST_OBS = {"nodes": SEARCH_NODES, "detections": [], "screen": (1200, 2670),
                           "pkg": "com.tencent.news"}
        droid.tap(645, 598)
        ops = list(droid._TRACE)
        self.assertEqual(ops[-1]["kind"], "tap")
        self.assertEqual(ops[-1]["args"]["x"], 645)
        self.assertIn("diff_pct", ops[-1]["result"])
        self.assertEqual(ops[-1]["obs"]["nodes"][0]["t"], "搜索")

    def test_dump_records_observation(self):
        with patch.object(droid, '_get', return_value=SEARCH_NODES), \
             patch.object(droid, '_sensitive_fg', return_value=False):
            nodes = droid.dump()
        self.assertEqual(list(droid._TRACE)[-1]["kind"], "dump")
        self.assertEqual(list(droid._TRACE)[-1]["result"]["count"], 1)

    def test_launch_records_trace(self):
        with patch.object(droid, '_act', return_value={"ok": 1, "fg": "com.tencent.news"}):
            droid.launch("com.tencent.news")
        op = list(droid._TRACE)[-1]
        self.assertEqual((op["kind"], op["args"]["pkg"]), ("launch", "com.tencent.news"))


class RecipeRecordTest(_Bus):
    def test_record_derives_recipe_from_trace(self):
        droid._LAST_OBS = {"nodes": SEARCH_NODES, "screen": (1200, 2670), "pkg": "com.tencent.news"}
        droid.tap(645, 598)
        with patch.object(droid, '_act', return_value={"ok": 1, "fg": "com.tencent.news"}):
            droid.launch("com.tencent.news")
        with patch.object(droid, '_recipe_store', return_value=self._store()):
            r = droid.recipe_record({"app": "腾讯新闻"})
        self.assertEqual(r.app_hint["package"], "com.tencent.news")
        kinds = [s.action["kind"] for s in r.steps]
        self.assertIn("tap", kinds)
        self.assertEqual([s.locator["kind"] for s in r.steps if s.action["kind"] == "tap"], ["text"])
        self.assertTrue((Path(self.tmp) / (r.recipe_id + ".json")).exists())


class RecipeRunTest(_Bus):
    def _seed_recipe(self):
        r = recipe.validate_recipe({
            "recipe_id": "news.read", "scene": "S1",
            "app_hint": {"package": "com.tencent.news", "match": "title_contains", "value": "腾讯新闻"},
            "steps": [
                {"intent": "打开", "locator": {"kind": "any"}, "action": {"kind": "launch", "pkg": "com.tencent.news"},
                 "expected": {"kind": "foreground_is", "value": "com.tencent.news"}},
                {"intent": "读列表", "locator": {"kind": "roi", "value": [0, 100, 1000, 900]},
                 "action": {"kind": "observe"}, "expected": {"kind": "min_nodes", "value": 1}}],
            "recorded_at": "2026-10-26T00:00:00Z"})
        self._store().save(r)
        return r

    def test_run_replays_without_model(self):
        self._seed_recipe()
        with patch.object(droid, '_recipe_store', return_value=self._store()), \
             patch.object(droid, 'dump', return_value=SEARCH_NODES), \
             patch.object(droid, '_act', return_value={"ok": 1, "fg": "com.tencent.news"}) as act:
            res = droid.recipe_run({"pkg": "com.tencent.news"})
        self.assertEqual(res.status, "completed")
        self.assertEqual(res.model_calls, 0)
        self.assertEqual([c.kwargs.get('op') for c in act.call_args_list], ['launch'])  # 只派发 launch, 无 tap/swipe

    def test_run_escalation_is_recorded(self):
        r = self._seed_recipe()
        with patch.object(droid, '_recipe_store', return_value=self._store()), \
             patch.object(droid, 'dump', return_value=[]), \
             patch.object(droid, 'look', return_value=[]):
            res = droid.recipe_run({"pkg": "com.tencent.news"})
        self.assertEqual(res.status, "escalated")
        self.assertEqual(self._store().escalations("news.read"), 1)

    def test_no_recipe_returns_none(self):
        with patch.object(droid, '_recipe_store', return_value=self._store()):
            self.assertIsNone(droid.recipe_run({"pkg": "com.tencent.mm"}))


if __name__ == "__main__":
    unittest.main()


class ActionResultNormalizeTest(unittest.TestCase):
    """tap/swipe 返回 → 期望判定字段的归一(真机实证: 不归一会永远 uncertain)。"""

    def test_diff_string_parsed(self):
        out = droid._norm_action_result({"diff": "diff: 43.547% bbox=[0, 0, 1199, 2533]", "fg": "com.tencent.news"})
        self.assertEqual(out["diff_pct"], 43.547)
        self.assertEqual(out["pkg"], "com.tencent.news")

    def test_numeric_diff_passthrough(self):
        self.assertEqual(droid._norm_action_result({"diff_pct": 8.0})["diff_pct"], 8.0)

    def test_missing_diff_yields_no_key(self):
        self.assertEqual(droid._norm_action_result({"fg": "x"}), {"pkg": "x"})

    def test_unparseable_diff_yields_no_key(self):
        self.assertEqual(droid._norm_action_result({"diff": "weird"}), {})


class RecipeListTest(_Bus):
    def test_list_returns_available_recipes(self):
        r = recipe.validate_recipe({
            "recipe_id": "news.read", "scene": "S1",
            "app_hint": {"package": "com.tencent.news", "match": "title_contains", "value": "腾讯新闻"},
            "steps": [{"intent": "读", "locator": {"kind": "roi", "value": [0, 100, 1000, 900]},
                       "action": {"kind": "observe"}, "expected": {"kind": "min_nodes", "value": 3}}],
            "recorded_at": "2026-10-26T00:00:00Z"})
        self._store().save(r)
        with patch.object(droid, '_recipe_store', return_value=self._store()):
            lst = droid.recipe_list()
        # 内置 app_search 入口说明总在列表里(不依赖 memory/recipes 目录); 这里只对账存下来的配方
        stored = [x for x in lst if not x.get('builtin')]
        self.assertEqual([x["recipe_id"] for x in stored], ["news.read"])
        self.assertIn("app_search:com.tencent.mm", [x["recipe_id"] for x in lst])
        self.assertEqual(stored[0]["app"], "腾讯新闻")
        self.assertEqual(stored[0]["steps"], 1)

    def test_unstable_recipes_hidden(self):
        r = recipe.validate_recipe({
            "recipe_id": "news.read", "scene": "S1", "app_hint": {"package": "p", "value": "A"},
            "steps": [{"intent": "读", "locator": {"kind": "any"}, "action": {"kind": "observe"},
                       "expected": {"kind": "min_nodes", "value": 1}}]})
        store = self._store()
        store.save(r)
        store.record_escalation("news.read")
        store.record_escalation("news.read")
        with patch.object(droid, '_recipe_store', return_value=store):
            # 不稳定配方必须被隐藏; 内置入口不是配方文件, 不参与稳定性判定
            self.assertEqual([x for x in droid.recipe_list() if not x.get('builtin')], [])
