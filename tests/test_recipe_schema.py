"""R1: 配方 schema 与严格校验（SPEC Phase 1）。

契约（SPEC §4.2 不变量 1 的代码面）：步骤只存 intent + locator + action + expected，
**永不存坐标**——校验层直接把坐标字段当非法输入拒绝，从结构上保证“回放必重新定位”。
"""
import sys
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import recipe


def _step(**over):
    s = {
        "intent": "打开搜索页",
        "locator": {"kind": "text", "value": "搜索"},
        "action": {"kind": "tap"},
        "expected": {"kind": "foreground_is", "value": "com.tencent.news"},
    }
    s.update(over)
    return s


def _recipe(**over):
    r = {
        "recipe_id": "news.read_top3",
        "scene": "S1",
        "app_hint": {"package": "com.tencent.news", "match": "title_contains", "value": "新闻"},
        "steps": [_step()],
        "recorded_at": "2026-10-26T00:00:00Z",
    }
    r.update(over)
    return r


class ValidateRecipeTest(unittest.TestCase):
    def test_minimal_recipe_validates(self):
        r = recipe.validate_recipe(_recipe())
        self.assertEqual(r.recipe_id, "news.read_top3")
        self.assertEqual(len(r.steps), 1)
        self.assertEqual(r.steps[0].locator["kind"], "text")

    def test_missing_required_field_rejected(self):
        for field in ("recipe_id", "scene", "app_hint", "steps"):
            obj = _recipe()
            del obj[field]
            with self.assertRaises(recipe.RecipeError):
                recipe.validate_recipe(obj)

    def test_empty_steps_rejected(self):
        with self.assertRaises(recipe.RecipeError):
            recipe.validate_recipe(_recipe(steps=[]))

    def test_unknown_locator_kind_rejected(self):
        with self.assertRaises(recipe.RecipeError):
            recipe.validate_recipe(_recipe(steps=[_step(locator={"kind": "magic", "value": "x"})]))

    def test_unknown_action_kind_rejected(self):
        with self.assertRaises(recipe.RecipeError):
            recipe.validate_recipe(_recipe(steps=[_step(action={"kind": "teleport"})]))

    def test_unknown_expected_kind_rejected(self):
        with self.assertRaises(recipe.RecipeError):
            recipe.validate_recipe(_recipe(steps=[_step(expected={"kind": "mind_read", "value": 1})]))

    def test_coordinate_fields_rejected(self):
        # 不变量 1 的结构保证: 步骤里出现坐标字段=非法(回放必须重新定位)
        for bad in ({"x": 500, "y": 1000}, {"point": [500, 1000]}, {"point2": [1, 2]}):
            with self.assertRaises(recipe.RecipeError):
                recipe.validate_recipe(_recipe(steps=[_step(**bad)]))

    def test_step_missing_intent_rejected(self):
        s = _step()
        del s["intent"]
        with self.assertRaises(recipe.RecipeError):
            recipe.validate_recipe(_recipe(steps=[s]))

    def test_locator_value_required(self):
        with self.assertRaises(recipe.RecipeError):
            recipe.validate_recipe(_recipe(steps=[_step(locator={"kind": "text"})]))

    def test_round_trip_through_json(self):
        r = recipe.validate_recipe(_recipe())
        r2 = recipe.validate_recipe(recipe.recipe_to_dict(r))
        self.assertEqual(r.recipe_id, r2.recipe_id)
        self.assertEqual(r.steps[0].expected, r2.steps[0].expected)

    def test_version_mismatch_rejected(self):
        with self.assertRaises(recipe.RecipeError):
            recipe.validate_recipe(_recipe(version=999))


if __name__ == "__main__":
    unittest.main()
