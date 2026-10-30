# -*- coding: utf-8 -*-
"""run_guard 看门狗: 工具调用超硬墙钟即自裁。

回归来源(真机 2026-10-28): 一次 gui_act(action='wait', seconds=8) 跑了 **260 秒**并返回
空 tool_result; 早一次 ask_point 挂了 213 秒同样空返回。两次的恢复方式都只能是中止整个
任务、从原 prompt 重启 —— 此前进度全部作废。

为什么复用 run_guard.check() 而不是新加检查点: droid 的每个读写入口早已调 check()
(droid.py:180/429/435/990/1947/1957/1972/2062/2077/2090), 于是墙钟一超, 下一个设备
操作即自裁, 把失控半径压到 ≤1 次设备调用, 且零新增调用点。

WatchdogExpired 继承 BaseException: 用户代码常见的 `except Exception` 不该吞掉它。
"""
import sys
import time
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import run_guard


class TestWatchdog(unittest.TestCase):
    def setUp(self):
        run_guard.clear_deadline()
        self.addCleanup(run_guard.clear_deadline)
        self.addCleanup(run_guard.leave)

    def test_check_raises_past_deadline(self):
        run_guard.enter_deadline(0.05)
        time.sleep(0.15)
        with self.assertRaises(run_guard.WatchdogExpired):
            run_guard.check()

    def test_check_passes_before_deadline(self):
        run_guard.enter_deadline(30)
        run_guard.check()          # 不得抛

    def test_clear_deadline_is_idempotent(self):
        run_guard.clear_deadline()
        run_guard.clear_deadline()
        run_guard.check()          # 无截止上下文永不抛

    def test_watchdog_expired_is_base_exception(self):
        """用户代码常见的 except Exception 不该吞掉它。"""
        self.assertTrue(issubclass(run_guard.WatchdogExpired, BaseException))
        self.assertFalse(issubclass(run_guard.WatchdogExpired, Exception))

    def test_cancel_token_still_wins_alongside_deadline(self):
        """两个闸门并存: 令牌取消优先(它是更具体的"这次 code_run 已作废")。"""
        tok = [False]
        run_guard.enter(tok, None)
        run_guard.enter_deadline(30)
        run_guard.cancel(tok)
        with self.assertRaises(run_guard.RunCancelled):
            run_guard.check()

    def test_enter_deadline_rejects_non_positive(self):
        run_guard.enter_deadline(0)
        run_guard.check()          # 0 = 不设, 不是"立刻超时"
        run_guard.enter_deadline(-5)
        run_guard.check()

    def test_watchdog_left_reports_remaining(self):
        run_guard.enter_deadline(30)
        left = run_guard.watchdog_left()
        self.assertIsNotNone(left)
        self.assertGreater(left, 25)
        run_guard.clear_deadline()
        self.assertIsNone(run_guard.watchdog_left())


class TestGuiActWatchdog(unittest.TestCase):
    """gui_act 挂住时必须返回结构化错误, 不是空 tool_result。

    真机实证(2026-10-28): 一次 gui_act(action='wait', seconds=8) 跑了 260s 并返回空
    tool_result, 恢复只能中止整个任务从原 prompt 重启, 此前进度全部作废。"""

    def setUp(self):
        import types
        from unittest.mock import patch
        import ga_android
        self._patch = patch
        self.ga = ga_android
        h = object.__new__(ga_android.GenericAgentHandler)
        h.cwd = '.'; h.working = {}; h.history_info = []
        h.code_stop_signal = []; h.current_turn = 1
        h.parent = types.SimpleNamespace(task_dir=None, verbose=False, _turn_end_hooks={})
        h.print = lambda *a, **k: None
        self.h = h

    def test_expired_gui_act_returns_structured_error(self):
        import json
        import time
        import types
        from unittest.mock import patch

        def slow_tap(x, y):
            time.sleep(0.15)          # 超过 0.05s 的墙钟
            run_guard.check()         # 设备调用入口的检查点 → 抛 WatchdogExpired
            return {'diff': 'diff: 8.0%'}

        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            ensure_fresh_obs=lambda: {'nodes': []},
            dump=lambda: [], dump_state=lambda: {'nodes': [], 'degraded': None},
            look=lambda *a, **k: [],
            tap=slow_tap,
            wait_stable=lambda **kw: {'stable': True})
        with patch.object(self.ga.GenericAgentHandler, '_GUI_ACT_BUDGET_S', 0.05), \
             patch.dict(__import__('sys').modules, {'droid': fake}):
            out = self.h.do_gui_act({'action': 'tap', 'point': [500, 250]},
                                    types.SimpleNamespace(content=''))
        data = str(out.data)
        self.assertIn('墙钟上限', data)
        self.assertNotIn('diff: 8.0%', data)        # 没让它把动作结果混进来
        self.assertIn('不要原样重试', data)


if __name__ == '__main__':
    unittest.main()
