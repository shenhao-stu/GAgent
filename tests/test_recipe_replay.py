"""R3: 回放引擎（SPEC Phase 1）。

核心不变量：
- 零模型调用（结构性地：引擎只调注入的 observe/act，无 LLM 路径）；
- 每步先按**当前观测**重新解析 locator，解析不到/歧义 → 立即升级，不猜；
- expected 判定用既有验证数据；False 或 None(uncertain) → 立即升级，不当成功；
- 配方内无重试循环：第一个失败即结束本次回放。
"""
import sys
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import recipe


def _recipe(steps):
    return recipe.validate_recipe({
        "recipe_id": "t.r", "scene": "S1",
        "app_hint": {"package": "com.tencent.news"},
        "steps": steps, "recorded_at": "2026-10-26T00:00:00Z"})


def _step(intent, locator, action, expected):
    return {"intent": intent, "locator": locator, "action": action, "expected": expected}


TAP_SEARCH = _step("点搜索", {"kind": "text", "value": "搜索"}, {"kind": "tap"},
                   {"kind": "diff_at_least", "value": 1.5})
OBSERVE_LIST = _step("读列表", {"kind": "roi", "value": [0, 100, 1000, 900]}, {"kind": "observe"},
                     {"kind": "min_nodes", "value": 3})


class FakeDevice:
    """可编排的 observe/act：按步骤序号返回不同观测，记录 act 调用。"""

    def __init__(self, observations, act_outcomes=None):
        self.observations = list(observations)
        self.act_outcomes = list(act_outcomes or [{"diff_pct": 8.0, "pkg": "com.tencent.news"}] * 10)
        self.act_calls = []
        self.observe_calls = 0

    def observe(self):
        self.observe_calls += 1
        return self.observations[min(self.observe_calls - 1, len(self.observations) - 1)]

    def act(self, action, resolved):
        self.act_calls.append((action, resolved))
        i = min(len(self.act_calls) - 1, len(self.act_outcomes) - 1)
        return dict(self.act_outcomes[i])


def _obs(nodes, pkg="com.tencent.news", screen=(1200, 2670)):
    return {"nodes": nodes, "detections": [], "screen": screen, "pkg": pkg}


NODES_WITH_SEARCH = [{"t": "搜索", "x": 645, "y": 598, "b": "182,527,1109,670", "click": 1}]
NODES_LIST = [{"t": "新闻%d" % i, "x": 600, "y": 400 + i * 100, "b": "0,%d,1200,%d" % (350 + i * 100, 440 + i * 100)}
              for i in range(5)]


class ReplayEngineTest(unittest.TestCase):
    def test_all_steps_pass_completes_with_zero_model_calls(self):
        dev = FakeDevice([_obs(NODES_WITH_SEARCH), _obs(NODES_LIST)])
        r = recipe.replay(_recipe([TAP_SEARCH, OBSERVE_LIST]), dev.observe, dev.act)
        self.assertEqual(r.status, "completed")
        self.assertEqual(r.steps_done, 2)
        self.assertEqual(r.model_calls, 0)
        self.assertEqual(len(dev.act_calls), 1)          # observe 步不发动作

    def test_locator_miss_escalates_immediately(self):
        dev = FakeDevice([_obs([{"t": "热点", "x": 1, "y": 1}])])
        r = recipe.replay(_recipe([TAP_SEARCH]), dev.observe, dev.act)
        self.assertEqual(r.status, "escalated")
        self.assertEqual(r.escalated_at, 0)
        self.assertEqual(r.reason, "locator_miss")
        self.assertEqual(dev.act_calls, [])              # 没解析到就不发动作

    def test_locator_ambiguous_escalates(self):
        nodes = [{"t": "搜索", "x": 1, "y": 1}, {"t": "搜索2", "x": 2, "y": 2}]
        r = recipe.replay(_recipe([TAP_SEARCH]), FakeDevice([_obs(nodes)]).observe,
                          FakeDevice([_obs(nodes)]).act)
        self.assertEqual((r.status, r.reason), ("escalated", "locator_miss"))

    def test_expected_false_escalates_with_evidence(self):
        dev = FakeDevice([_obs(NODES_WITH_SEARCH)], act_outcomes=[{"diff_pct": 0.01, "pkg": "com.tencent.news"}])
        r = recipe.replay(_recipe([TAP_SEARCH]), dev.observe, dev.act)
        self.assertEqual(r.status, "escalated")
        self.assertEqual(r.reason, "expected_failed")
        self.assertEqual(r.evidence["outcome"]["diff_pct"], 0.01)

    def test_expected_none_is_uncertain_escalation(self):
        dev = FakeDevice([_obs(NODES_WITH_SEARCH)], act_outcomes=[{"pkg": "com.tencent.news"}])  # 无 diff_pct
        r = recipe.replay(_recipe([TAP_SEARCH]), dev.observe, dev.act)
        self.assertEqual((r.status, r.reason), ("escalated", "uncertain"))

    def test_post_observation_only_for_state_expected(self):
        # min_nodes 需要动作后观测; diff_at_least 不需要
        dev = FakeDevice([_obs(NODES_WITH_SEARCH), _obs(NODES_LIST)])
        recipe.replay(_recipe([TAP_SEARCH]), dev.observe, dev.act)
        self.assertEqual(dev.observe_calls, 1)
        dev2 = FakeDevice([_obs(NODES_WITH_SEARCH), _obs(NODES_LIST)])
        recipe.replay(_recipe([OBSERVE_LIST]), dev2.observe, dev2.act)
        self.assertEqual(dev2.observe_calls, 1)          # observe 步: 解析时的那一次即后验

    def test_observe_step_reads_post_state(self):
        dev = FakeDevice([_obs(NODES_LIST)])
        r = recipe.replay(_recipe([OBSERVE_LIST]), dev.observe, dev.act)
        self.assertEqual(r.status, "completed")
        self.assertEqual(dev.act_calls, [])

    def test_first_failure_stops_no_internal_retry(self):
        dev = FakeDevice([_obs(NODES_WITH_SEARCH), _obs(NODES_WITH_SEARCH), _obs(NODES_LIST)],
                         act_outcomes=[{"diff_pct": 0.0, "pkg": "com.tencent.news"}] * 3)
        r = recipe.replay(_recipe([TAP_SEARCH, OBSERVE_LIST]), dev.observe, dev.act)
        self.assertEqual((r.status, r.escalated_at), ("escalated", 0))
        self.assertEqual(len(dev.act_calls), 1)          # 失败即停, 不重试同一动作

    def test_resolved_point_passed_to_act(self):
        dev = FakeDevice([_obs(NODES_WITH_SEARCH)])
        recipe.replay(_recipe([TAP_SEARCH]), dev.observe, dev.act)
        action, resolved = dev.act_calls[0]
        self.assertEqual(resolved["point"], (645, 598))


if __name__ == "__main__":
    unittest.main()


class ReplayObservationTest(unittest.TestCase):
    def test_completed_result_carries_observation_texts(self):
        dev = FakeDevice([_obs(NODES_LIST)])
        r = recipe.replay(_recipe([OBSERVE_LIST]), dev.observe, dev.act)
        self.assertEqual(r.status, "completed")
        self.assertIn("新闻0", r.observation["texts"])
        self.assertEqual(r.observation["pkg"], "com.tencent.news")

    def test_escalated_result_also_carries_observation(self):
        dev = FakeDevice([_obs(NODES_WITH_SEARCH)], act_outcomes=[{"diff_pct": 0.0}])
        r = recipe.replay(_recipe([TAP_SEARCH]), dev.observe, dev.act)
        self.assertEqual(r.status, "escalated")
        self.assertIn("搜索", r.observation["texts"])
