"""Decision, freshness and cancellation contracts without a device or network."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1] / "app/src/main/assets/ga_runtime"
sys.path.insert(0, str(CORE))
import jev_ui as jev
import run_guard


def snapshot(fingerprint="same"):
    return {"pkg": "com.example.settings", "window_id": 1, "rot": 0, "w": 400, "h": 800,
            "fingerprint": fingerprint, "captured_ms": 1, "blockers": [], "nodes": [
                {"click": 1, "l": 0, "b": "20,100,380,180", "x": 200, "y": 140},
                {"t": "显示和亮度", "l": 1, "b": "40,110,200,160"},
                {"t": "声音", "click": 1, "l": 0, "b": "20,200,380,280", "x": 200, "y": 240}]}


def response(choice="0", probs=None):
    probs = probs or {"0": .97, "2": .01, "none": .02}
    return {"model": jev.MODEL, "answers": {"target": {
        "type": "choice", "choice": choice, "confidence": probs.get(choice, .99), "probabilities": probs}},
        "usage": {"input_tokens": 120, "output_tokens": 21}}


class Device:
    def __init__(self, states=None, action=None):
        self.states = iter(states or [snapshot(), snapshot(), snapshot("changed")])
        self.actions = []
        self.action = {"dispatched": True} if action is None else action

    def ui_snapshot(self, package):
        return next(self.states)

    def _tap_observed(self, state, index):
        run_guard.check()
        self.actions.append(index)
        if isinstance(self.action, Exception):
            raise self.action
        return self.action


class Contracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = patch.object(jev, "configuration", return_value="test-only")
        self.file = patch.object(jev, "__file__", str(Path(self.tmp.name) / "jev_ui.py"))
        self.sleep = patch.object(jev.time, "sleep")
        self.config.start(); self.file.start(); self.sleep.start()
        self.token = [False]
        run_guard.enter(self.token)

    def tearDown(self):
        run_guard.leave()
        self.config.stop(); self.file.stop(); self.sleep.stop()
        self.tmp.cleanup()

    def run_target(self, device, reply=None, effect=None):
        with patch.object(jev, "_request", return_value=reply or response(), side_effect=effect):
            return jev.tap_target(device, "显示设置", "com.example.settings")

    def test_clickable_parent_is_bound_to_child_label(self):
        opts = jev.candidates(snapshot())
        self.assertEqual(opts["0"]["label"], "显示和亮度")
        self.assertEqual(jev.choose(response(), opts)["index"], 0)

    def test_controls_and_ancestors_are_excluded(self):
        for field in ("checkable", "edit", "disabled", "password"):
            with self.subTest(field=field):
                s = snapshot(); s["nodes"][1][field] = 1
                self.assertNotIn("0", jev.candidates(s))

    def test_clickable_children_do_not_lend_their_label_to_parent(self):
        s = snapshot(); s["nodes"][0]["t"] = "更多"; s["nodes"][1]["click"] = 1
        opts = jev.candidates(s)
        self.assertNotIn("0", opts)
        self.assertEqual(opts["1"]["label"], "显示和亮度")

    def test_missing_bounds_hidden_partial_and_occluded_targets(self):
        for change in (lambda s: s["nodes"][0].pop("b"),
                       lambda s: s["nodes"][0].update(hidden=1),
                       lambda s: s["nodes"][0].update(b="-10,100,380,180"),
                       lambda s: s.update(blockers=[[180,100,240,170]])):
            s = snapshot(); change(s)
            self.assertNotIn("0", jev.candidates(s))

    def test_irreversible_control_cannot_be_a_choice(self):
        s = snapshot(); s["nodes"][1]["t"] = "立即付款"
        self.assertNotIn("0", jev.candidates(s))

    def test_icon_description_alone_cannot_authorize_a_navigation_click(self):
        s = snapshot(); s["nodes"][1].pop("t"); s["nodes"][1]["d"] = "更多"
        self.assertNotIn("0", jev.candidates(s))

    def test_malformed_distribution_is_not_accepted(self):
        changes = [lambda r: r.update(model="jev-latest"),
                   lambda r: r["answers"]["target"].update(choice="alien"),
                   lambda r: r["answers"]["target"].update(confidence=float("nan")),
                   lambda r: r["answers"]["target"]["probabilities"].update({"0": True}),
                   lambda r: r["answers"]["target"]["probabilities"].update(extra=0),
                   lambda r: r["answers"]["target"]["probabilities"].update({"0": .4}),
                   lambda r: r["answers"]["target"].update(type="text")]
        for change in changes:
            r = response(); change(r)
            with self.subTest(response=r), self.assertRaises(jev.Fallback):
                jev.choose(r, jev.candidates(snapshot()))

    def test_none_low_confidence_and_ambiguity_decline(self):
        for r in (response("none", {"0": .01, "2": .01, "none": .98}),
                  response("0", {"0": .6, "2": .39, "none": .01})):
            d = Device(); result = self.run_target(d, r)
            self.assertEqual(result["status"], "fallback")
            self.assertEqual(d.actions, [])

    def test_provider_confidence_need_not_equal_selected_probability(self):
        r = response(); r["answers"]["target"]["confidence"] = .88
        self.assertEqual(jev.choose(r, jev.candidates(snapshot()))["index"], 0)

    def test_changed_screen_and_transport_error_never_dispatch(self):
        for states, failure in (([snapshot(), snapshot("new")], None),
                                (None, jev.requests.Timeout())):
            d = Device(states); result = self.run_target(d, effect=failure)
            self.assertFalse(result["action_dispatched"])
            self.assertEqual(d.actions, [])

    def test_cancelled_late_response_never_dispatches_and_is_archived(self):
        def late(*args):
            run_guard.cancel(self.token)
            return response()
        d = Device()
        with self.assertRaises(run_guard.RunCancelled):
            self.run_target(d, effect=late)
        self.assertEqual(d.actions, [])
        records = list(Path(self.tmp.name).glob("temp/jev/*.json"))
        self.assertEqual(json.loads(records[0].read_text(encoding="utf-8"))["status"], "cancelled")

    def test_stale_refresh_is_archived_without_expanding_planner_output(self):
        changed = snapshot("new"); changed["blockers"] = [[40, 50, 60, 70]]
        d = Device([snapshot(), changed]); result = self.run_target(d)
        self.assertEqual(result["reason"], "stale_observation")
        self.assertNotIn("refreshed", result)
        trace = json.loads(Path(result["trace_path"]).read_text(encoding="utf-8"))
        self.assertEqual(trace["refreshed"], changed)
        self.assertEqual(d.actions, [])

    def test_deadline_expiry_never_dispatches(self):
        d = Device()
        with patch.object(jev.time, "monotonic", side_effect=[0, 0, 0, 9, 9, 9]):
            result = self.run_target(d)
        self.assertEqual(result["reason"], "deadline")
        self.assertEqual(d.actions, [])

    def test_guard_rejection_and_ambiguous_action_are_distinct(self):
        rejected = self.run_target(Device(action={"dispatched": False, "reason": "stale_snapshot"}))
        unknown = self.run_target(Device(action=jev.requests.Timeout()))
        self.assertFalse(rejected["action_dispatched"])
        self.assertEqual(rejected["status"], "fallback")
        self.assertIsNone(unknown["action_dispatched"])
        self.assertEqual(unknown["status"], "uncertain")

    def test_missing_or_malformed_action_receipt_is_uncertain(self):
        for action in ({}, {"dispatched": "false"}, {"dispatched": 0}, "broken"):
            result = self.run_target(Device(action=action))
            self.assertIsNone(result["action_dispatched"])
            self.assertEqual(result["status"], "uncertain")

    def test_one_action_compact_result_and_full_private_evidence(self):
        d = Device(); result = self.run_target(d)
        self.assertEqual(d.actions, [0])
        self.assertEqual(result["status"], "observed")
        self.assertIsNone(result["task_success"])
        self.assertEqual(result["usage"]["output_tokens"], 21)
        self.assertNotIn("request", result)
        trace = Path(result["trace_path"]).read_text(encoding="utf-8")
        self.assertNotIn("test-only", trace)
        self.assertIn("observation", json.loads(trace))

    def test_post_action_animation_is_observed_without_a_second_action(self):
        empty = snapshot("transition"); empty["nodes"] = [{"l": 0}]
        d = Device([snapshot(), snapshot(), empty, snapshot("changed")])
        result = self.run_target(d)
        self.assertEqual(result["status"], "observed")
        self.assertIn("显示和亮度", result["visible_text"])
        self.assertEqual(d.actions, [0])

    def test_exact_selector_uses_same_guard_without_network_or_config(self):
        d = Device()
        with patch.object(jev, "_request") as request, patch.object(jev, "configuration") as config:
            result = jev.tap_target(d, "显示和亮度", "com.example.settings", use_jev=False)
        self.assertEqual(d.actions, [0])
        self.assertEqual(result["selector"], "exact")
        self.assertIsNone(result["model"])
        request.assert_not_called(); config.assert_not_called()

    def test_node_rejection_has_no_fallback_gesture(self):
        d = Device(action={"dispatched": True, "method": "node_click", "action_result": False})
        result = self.run_target(d)
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(d.actions, [0])

    def test_droid_cancellation_after_gate_prevents_post(self):
        import droid
        with patch.object(droid, "_gate_injection", side_effect=lambda _: run_guard.cancel(self.token)), \
             patch.object(droid, "_record_path"), patch.object(droid._SESSION, "post") as post:
            with self.assertRaises(run_guard.RunCancelled):
                droid._act(op="tap", x=1, y=1)
            post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
