"""R5a: 配方存储与稳定性（SPEC Phase 1 不变量 4）。

- 存储：memory/recipes/<recipe_id>.json，加载即严格校验（坏文件=不存在，不半截加载）。
- 匹配：按 app_hint 的 package 或 title 值确定性匹配，无向量、无模型。
- 稳定性：单任务内升级两次 → unstable，路由器不再提供，直到重新录制（删档或重录覆盖）。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import recipe


def _recipe_dict(rid="news.read_top3", pkg="com.tencent.news", app="腾讯新闻"):
    return {
        "recipe_id": rid, "scene": "S1",
        "app_hint": {"package": pkg, "match": "title_contains", "value": app},
        "steps": [{"intent": "读列表", "locator": {"kind": "roi", "value": [0, 100, 1000, 900]},
                   "action": {"kind": "observe"}, "expected": {"kind": "min_nodes", "value": 3}}],
        "recorded_at": "2026-10-26T00:00:00Z",
    }


class RecipeStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="recipe_store_")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.store = recipe.RecipeStore(self.tmp)

    def test_save_then_load_round_trip(self):
        r = recipe.validate_recipe(_recipe_dict())
        self.store.save(r)
        loaded = self.store.load("news.read_top3")
        self.assertEqual(loaded.recipe_id, "news.read_top3")
        self.assertEqual(loaded.app_hint["package"], "com.tencent.news")

    def test_load_missing_returns_none(self):
        self.assertIsNone(self.store.load("nope"))

    def test_corrupt_file_is_invisible_not_half_loaded(self):
        (Path(self.tmp) / "bad.json").write_text("{ not json", encoding="utf-8")
        self.assertIsNone(self.store.load("bad"))
        (Path(self.tmp) / "bad2.json").write_text('{"recipe_id":"bad2"}', encoding="utf-8")
        self.assertIsNone(self.store.load("bad2"))     # schema 不完整=不可用

    def test_match_by_package(self):
        self.store.save(recipe.validate_recipe(_recipe_dict()))
        r = self.store.match({"pkg": "com.tencent.news"})
        self.assertIsNotNone(r)
        self.assertEqual(r.recipe_id, "news.read_top3")

    def test_match_by_app_name(self):
        self.store.save(recipe.validate_recipe(_recipe_dict()))
        self.assertIsNotNone(self.store.match({"app": "腾讯新闻"}))
        self.assertIsNone(self.store.match({"app": "微信"}))

    def test_two_escalations_mark_unstable_and_hide(self):
        self.store.save(recipe.validate_recipe(_recipe_dict()))
        self.store.record_escalation("news.read_top3")
        self.assertFalse(self.store.is_unstable("news.read_top3"))
        self.assertIsNotNone(self.store.match({"pkg": "com.tencent.news"}))
        self.store.record_escalation("news.read_top3")     # 第二次 → unstable
        self.assertTrue(self.store.is_unstable("news.read_top3"))
        self.assertIsNone(self.store.match({"pkg": "com.tencent.news"}))
        self.assertIsNone(self.store.load("news.read_top3"))

    def test_rerecord_clears_unstable(self):
        self.store.save(recipe.validate_recipe(_recipe_dict()))
        self.store.record_escalation("news.read_top3")
        self.store.record_escalation("news.read_top3")
        self.store.save(recipe.validate_recipe(_recipe_dict()))   # 重新录制即覆盖
        self.assertFalse(self.store.is_unstable("news.read_top3"))
        self.assertIsNotNone(self.store.load("news.read_top3"))

    def test_escalation_count_survives_reload(self):
        self.store.save(recipe.validate_recipe(_recipe_dict()))
        self.store.record_escalation("news.read_top3")
        store2 = recipe.RecipeStore(self.tmp)
        self.assertEqual(store2.escalations("news.read_top3"), 1)


if __name__ == "__main__":
    unittest.main()
