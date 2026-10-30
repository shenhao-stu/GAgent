"""dump_state(): 结构化树观测——把「[]」的三种成因变成机器可判的原因码。

背景（SPEC Phase 3 路由器不变式 1 的前置）: 路由器不能把「策略置空/前台未解析/真空树」
当作同一种 []——前者走视觉、前者中的未解析需要重查、真空树才是真的无可交互元素。
本测试锁住 dump_state 的契约与 dump() 的既有行为不回退。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import droid


class DumpStateTest(unittest.TestCase):
    def _patch(self, fg, nodes):
        ctx = [patch.object(droid, '_resolve_fg', return_value=fg),
               patch.object(droid, '_track'),
               patch.object(droid, '_get', return_value=nodes)]
        for c in ctx:
            c.start(); self.addCleanup(c.stop)

    def test_sensitive_pkg_reports_sensitive_blank(self):
        self._patch("com.tencent.mm", [{"t": "poison"}])
        r = droid.dump_state()
        self.assertEqual(r["nodes"], [])
        self.assertEqual(r["degraded"], {"reason": "sensitive_blank", "channel": "dump"})
        self.assertEqual(r["pkg"], "com.tencent.mm")

    def test_unresolved_fg_reports_unresolved(self):
        self._patch("", [{"t": "x"}])
        r = droid.dump_state()
        self.assertEqual(r["nodes"], [])
        self.assertEqual(r["degraded"]["reason"], "unresolved_fg")
        self.assertEqual(r["pkg"], "")

    def test_empty_tree_reports_tree_empty(self):
        self._patch("com.android.settings", [])
        r = droid.dump_state()
        self.assertEqual(r["nodes"], [])
        self.assertEqual(r["degraded"], {"reason": "tree_empty", "channel": "dump"})

    def test_nodes_present_has_no_degraded(self):
        nodes = [{"t": "WLAN", "x": 100, "y": 200, "click": 1}]
        self._patch("com.android.settings", nodes)
        r = droid.dump_state()
        self.assertIsNone(r["degraded"])
        self.assertEqual(r["nodes"], nodes)

    def test_dump_still_returns_plain_list_for_sensitive(self):
        self._patch("com.tencent.mm", [{"t": "poison"}])
        self.assertEqual(droid.dump(), [])

    def test_dump_still_returns_nodes_for_normal_app(self):
        nodes = [{"t": "蓝牙"}]
        self._patch("com.android.settings", nodes)
        self.assertEqual(droid.dump(), nodes)

    def test_dump_state_full_passes_full_flag(self):
        self._patch("com.android.settings", [])
        with patch.object(droid, '_get', return_value=[]) as get:
            droid.dump_state(full=True)
        self.assertEqual(get.call_args.kwargs, {"full": 1})


if __name__ == "__main__":
    unittest.main()
