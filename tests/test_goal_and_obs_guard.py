"""目标重注(锚点里的 [GOAL]/[DONE]/[UNMET])、动作核验口径与观察节流三件事的契约。

对应真机会话里的两类偏差:
  ① 子目标漂移: 任务原文是"去牌组里看排行榜", 但 <history> 里被折叠成一行摘要, working memory
     写下的"找排行榜"顶掉了原目标 —— 模型没进牌组就开始找排行榜。锚点必须每轮重注原始目标。
  ② 观察空转: 微信是视觉型页面(本地只剩 YOLO 一条腿), 模型在 see/ocr 之间来回 11 次(164s),
     而账本只给动作记账 —— 空转的观察对 [LOOP-GUARD] 完全隐形。
"""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import ga_android
import phone_ledger


def _handler():
    h = object.__new__(ga_android.GenericAgentHandler)
    h.history_info = ['[USER] 打开微信 搜炉石传说小程序 去看看套牌里的传说榜前三组套牌',
                      '[Agent] 调用工具gui_act, args: {...}',
                      '[Agent] 已进入小程序, 停留在"线下赛"页面']
    h.current_turn = 7
    h.parent = types.SimpleNamespace(task_dir=None, verbose=False, _turn_end_hooks={})
    h.print = lambda *a, **k: None
    return h


class GoalBlockTest(unittest.TestCase):
    def test_goal_is_reinjected_verbatim_every_turn(self):
        h = _handler()
        h._goal_text = h.history_info[0][len('[USER]'):].strip(' :：')
        h._done_steps = ['已拉起微信', '已输入"炉石传说"']
        h._last_expect = '传说牌组已打开'
        block = h._goal_block()
        self.assertIn('[GOAL] 打开微信', block)
        self.assertIn('套牌里的传说榜前三组套牌', block)     # 原句必须在, 不是折叠摘要
        self.assertIn('[DONE] 已拉起微信; 已输入"炉石传说"', block)
        self.assertIn("[UNMET] 上次期望的 '传说牌组已打开' 没有出现", block)

    def test_missing_state_degrades_to_empty_block(self):
        h = object.__new__(ga_android.GenericAgentHandler)   # 老 session 复用: 状态位都还没建
        self.assertEqual(h._goal_block(), '')

    def test_long_goal_is_bounded(self):
        h = _handler()
        h._goal_text = 'x' * 5000
        self.assertLessEqual(len(h._goal_block()), 400)


class ProvedChangeTest(unittest.TestCase):
    def test_launch_requires_the_expected_package(self):
        h = _handler()
        # 拉起失败(前台还在桌面)不能算"证明变化", 否则上层会跳过 wait_stable
        self.assertFalse(h._act_proved_change('launch', {'fg': 'com.miui.home'},
                                              'com.tencent.mm'))
        self.assertTrue(h._act_proved_change('launch', {'fg': 'com.tencent.mm'},
                                             'com.tencent.mm'))

    def test_launch_without_expectation_only_needs_a_foreground(self):
        h = _handler()
        self.assertTrue(h._act_proved_change('launch', {'fg': 'com.tencent.mm'}))

    def test_diff_is_parsed_once_and_bounded(self):
        h = _handler()
        self.assertEqual(h._parse_diff_pct({'diff': 'diff: 83.904%'}), 83.904)
        self.assertEqual(h._parse_diff_pct({'diff': '77.571%'}), 77.571)
        self.assertIsNone(h._parse_diff_pct({'diff': 'weird'}))
        self.assertIsNone(h._parse_diff_pct({}))

    def test_big_jump_frame_is_taken_fresh(self):
        """diff ≥ 30% 说明页面在切换: 不能复用动作后验的 pending 帧(那可能是过渡帧)。"""
        h = _handler()
        h.cwd = '.'
        h.working = {}
        h.code_stop_signal = []
        h._gui_actions = 0
        h._finish_prompted = False
        h._no_tool_retries = 0
        h._see_failed_digest = None
        h._last_act_ok = True
        h._done_steps = []
        h._last_expect = None
        h._goal_text = ''
        shots, pendings = [], []

        def _shot():
            shots.append(1)
            return np.zeros((10, 10, 3), np.uint8)

        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            dump=lambda: [],
            tap=lambda x, y: {'diff': 'diff: 83.9%'},
            wait_stable=lambda **kw: {'stable': True},
            take_pending_frame=lambda: pendings.append(1) or np.zeros((10, 10, 3), np.uint8),
            shot=_shot,
        )
        with patch.dict(sys.modules, {'droid': fake}):
            h._compact_obs = lambda frame=None: {'got': 'frame' if frame is not None else None}
            out = h.do_gui_act({'action': 'tap', 'point': [500, 250]},
                               types.SimpleNamespace(content=''))
            if not isinstance(out, ga_android.StepOutcome):
                try:
                    next(out)
                except StopIteration as e:
                    out = e.value
        self.assertEqual(len(shots), 1)      # 重新截了一张
        self.assertEqual(pendings, [])       # 没有复用过渡帧


class ObservationGuardTest(unittest.TestCase):
    def setUp(self):
        phone_ledger.ACTIVE.clear()

    def test_same_screen_same_channel_twice_is_flagged(self):
        ledger = phone_ledger.Ledger()
        self.assertIsNone(ledger.note_observation('see', 12345, '当前页面显示什么'))
        hint = ledger.note_observation('see', 12345, '当前页面显示什么')
        self.assertIn('OBS-GUARD', hint)
        self.assertIn('see', hint)

    def test_different_channels_are_not_merged(self):
        ledger = phone_ledger.Ledger()
        ledger.note_observation('see', 999, '')
        self.assertIsNone(ledger.note_observation('ocr', 999, ''))

    def test_unknown_digest_never_blocks(self):
        ledger = phone_ledger.Ledger()
        self.assertIsNone(ledger.note_observation('ocr', None, ''))
        self.assertIsNone(ledger.note_observation('ocr', None, ''))

    def test_clear_drops_observations_too(self):
        ledger = phone_ledger.Ledger()
        ledger.note_observation('see', 1, '')
        ledger.note_observation('see', 1, '')
        ledger.clear()
        self.assertIsNone(ledger.note_observation('see', 1, ''))


class ObsNoteHonestyTest(unittest.TestCase):
    """obs_note 不许说"截图已附", 除非这一轮真的会附图。"""

    def _note(self, takes_images):
        h = object.__new__(ga_android.GenericAgentHandler)
        h._session_takes_images = lambda: takes_images
        h._vision_covers_screen = lambda: True
        return h

    def test_claims_attached_only_when_images_are_supported(self):
        h = self._note(True)
        self.assertTrue(h._session_takes_images())
        # 文案本身在 _do_gui_act 里, 这里锁判据: 不可图时必须走另一句
        fake_note = ('当前屏幕截图已附在本轮消息里' if h._session_takes_images()
                     else '本会话收不到图片')
        self.assertIn('已附', fake_note)

    def test_text_protocol_gets_the_truthful_note(self):
        h = self._note(False)
        self.assertFalse(h._session_takes_images())
        fake_note = ('当前屏幕截图已附在本轮消息里' if h._session_takes_images()
                     else '本会话收不到图片(文本协议)')
        self.assertNotIn('已附', fake_note)
        self.assertIn('文本协议', fake_note)


def _drive(gen):
    """消费生成器并取 return 值(do_no_tool 既可能 yield 进度行, 也可能直接返回)。"""
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


def _bare_handler(**attrs):
    h = object.__new__(ga_android.GenericAgentHandler)
    h.working = {}
    h.history_info = []
    h.current_turn = 0
    h._gui_actions = 0
    h._task_finished = False
    h._no_tool_retries = 0
    h._vision_in_turn_attached = False
    h._see_cache = None
    h._memory_tip_shown = False
    h.parent = types.SimpleNamespace(verbose=False)
    for k, v in attrs.items():
        setattr(h, k, v)
    return h


class SilentExitRefusedTest(unittest.TestCase):
    """动作没被验证生效就收尾 → 必须先 finish_task/ask_user。

    真机 t33: 最后一次 tap(套牌按钮)分歧 77.6% 但没进套牌页, 模型只发了一段"多次点击失败"的
    checkpoint 文本, next_prompt 为空, agent_loop 判 CURRENT_TASK_DONE —— 用户收到的是空结果。
    """

    def test_unverified_action_cannot_end_the_run_silently(self):
        h = _bare_handler(_gui_actions=2, _last_act_ok=False)
        out = _drive(h.do_no_tool({}, types.SimpleNamespace(content='多次点击套牌按钮失败, 先停在这里。',
                                                            thinking='')))
        self.assertIsNotNone(out.next_prompt)
        self.assertIn('finish_task', out.next_prompt)
        self.assertIsNot(out.should_exit, True)

    def test_verified_action_is_left_to_the_existing_contract(self):
        """干净收尾仍走既有"给一次 finish_task 机会"契约, 这里不重复拦。"""
        h = _bare_handler(_gui_actions=2, _last_act_ok=True, _finish_prompted=True)
        self.assertFalse(h._needs_explicit_finish())

    def test_finished_task_is_never_blocked(self):
        h = _bare_handler(_gui_actions=2, _last_act_ok=False, _task_finished=True)
        self.assertFalse(h._needs_explicit_finish())


if __name__ == '__main__':
    unittest.main()


class SearchAppKeywordAliasTest(unittest.TestCase):
    """search_app 的关键词别名。

    真机 2026-10-29 18:04:22: 模型给了 `{"action": "search_app", "target": "元梦之星"}`,
    旧实现只认 value/query, 回了一句"需要 value", 白烧一轮(5.6s)才重发。它的直觉没错 ——
    "target 就是要搜的东西"在 tap 里正是这个意思, 没必要在 search_app 上惩罚它。
    """

    def _run(self, args):
        h = _handler()
        h.working = {}
        seen = {}

        def fake_search(pkg='', query='', wait=2.0):
            seen['query'] = query
            seen['pkg'] = pkg
            return {'ok': True, 'pkg': pkg, 'query': query, 'steps': []}

        fake = types.SimpleNamespace(app_search=fake_search)
        with patch.dict(sys.modules, {'droid': fake}):
            h.do_gui_act(args, types.SimpleNamespace(content=''))
        return seen

    def test_target_is_accepted_as_the_keyword(self):
        self.assertEqual(self._run({'action': 'search_app', 'target': '元梦之星'})['query'], '元梦之星')

    def test_text_is_accepted_as_the_keyword(self):
        self.assertEqual(self._run({'action': 'search_app', 'text': '炉石传说'})['query'], '炉石传说')

    def test_value_still_wins(self):
        seen = self._run({'action': 'search_app', 'value': 'a', 'target': 'b'})
        self.assertEqual(seen['query'], 'a')
