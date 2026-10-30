"""层级(back)提示、点空就地重试、画面指纹推进判定、入口索引注入 的契约。

对应真机 2026-10-30 09:04~09:16 的四个会话(三角洲/炉石):
  ① 三角洲: 看完"今日密码"后, 后续任务入口在**上一级**页面, 模型却一直在弹窗层里点
     "取消/×" —— 6 次点击的 diff 都是 85.850%(同一 bbox), 从 diff 看每步都"成功",
     实际一步没走。diff 判不了"原地打转", 要用画面指纹。
  ② 炉石: `target='套牌'` 首候选是正文里的同名文字, 点 3 次 diff 0.3~0.5%; 换下一个
     候选才点到导航栏 —— 候选清单本来就在手上, 本地换比再问模型快一轮(5~6s)。
  ③ 每个任务开头都先 file_read phone_use.md + app_cards.md 两条(≈4s), 只拿到前 60 行;
     "微信里小程序/朋友圈/表情包在哪"这类知识应该直接注入。
"""
import sys
import types
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import ga_android


def _handler():
    h = object.__new__(ga_android.GenericAgentHandler)
    h.history_info = ['[USER] 打开微信 搜索三角洲 查看今日密码 再看后续任务']
    h.current_turn = 3
    h.parent = types.SimpleNamespace(task_dir=None, verbose=False, _turn_end_hooks={})
    h.working = {}
    h.print = lambda *a, **k: None
    h._gui_actions = 4
    h._task_finished = False
    return h


class LayerHintTest(unittest.TestCase):
    def test_two_distinct_frames_trigger_back_hint(self):
        h = _handler()
        h._screen_hist = deque(maxlen=6)
        seq = ['aa', 'bb', 'aa', 'bb']
        out = {}
        with patch.dict(sys.modules, {'droid': types.SimpleNamespace(frame_digest=lambda: seq.pop(0))}):
            for _ in range(4):
                h._note_progress(out)
        self.assertIn('layer_hint', out)
        self.assertIn('上一级', out['layer_hint'])
        self.assertIn('back', out['layer_hint'])

    def test_distinct_frames_do_not_trigger(self):
        h = _handler()
        h._screen_hist = deque(maxlen=6)
        seq = ['a1', 'b2', 'c3', 'd4']
        out = {}
        with patch.dict(sys.modules, {'droid': types.SimpleNamespace(frame_digest=lambda: seq.pop(0))}):
            for _ in range(4):
                h._note_progress(out)
        self.assertNotIn('layer_hint', out)

    def test_no_digest_is_silent(self):
        h = _handler()
        out = {}
        with patch.dict(sys.modules, {'droid': types.SimpleNamespace(frame_digest=lambda: '')}):
            h._note_progress(out)
        self.assertEqual(out, {})


class NoopRetryTest(unittest.TestCase):
    def test_alternate_candidate_is_tried_and_wins(self):
        h = _handler()
        h._attached_img_wh = None
        out = {'action': 'tap', 'point': [600, 300],
               'target': {'text': '套牌', 'matches': 2, 'index': 0,
                          'alternatives': [{'index': 1, 't': '套牌', 'point': [1004, 2490]}]}}
        calls = []
        diffs = {600: 'diff: 0.308%', 1004: 'diff: 69.247%'}

        def fake_tap(x, y, **kw):
            calls.append((x, y))
            return {'diff': diffs[x]}

        with patch.dict(sys.modules, {'droid': types.SimpleNamespace(tap=fake_tap,
                                                                     longpress=fake_tap)}):
            h._retry_noop_action('tap', {}, out, {'t': '套牌', '_matches': 2, '_index': 0,
                                                  '_alternatives': [{'index': 1, 't': '套牌',
                                                                     'point': [1004, 2490]}]})
        self.assertEqual(calls, [(1004, 2490)])
        self.assertEqual(out['point'], [1004, 2490])
        self.assertEqual(out['auto_retry']['kind'], 'target_alternate')
        self.assertEqual(out['target']['chosen_by'], 'auto_retry')

    def test_image_point_is_rescaled_once(self):
        h = _handler()
        h._attached_img_wh = (647, 1440)
        h._attached_screen_wh = (1200, 2670)
        out = {'action': 'tap', 'point': [100, 200]}
        calls = []

        def fake_tap(x, y, **kw):
            calls.append((x, y))
            return {'diff': 'diff: 38.500%'}

        with patch.dict(sys.modules, {'droid': types.SimpleNamespace(tap=fake_tap,
                                                                     longpress=fake_tap)}):
            h._retry_noop_action('tap', {}, out, None)
        self.assertEqual(calls, [(int(round(100 * 1200 / 647)), int(round(200 * 2670 / 1440)))])
        self.assertEqual(out['auto_retry']['kind'], 'img_scale')
        self.assertGreater(out['auto_retry']['to'][0], out['auto_retry']['from'][0])

    def test_no_candidates_no_image_is_a_noop(self):
        h = _handler()
        out = {'action': 'tap', 'point': [10, 10]}
        with patch.dict(sys.modules, {'droid': types.SimpleNamespace()}):
            h._retry_noop_action('tap', {}, out, None)
        self.assertNotIn('auto_retry', out)


class KbBlockTest(unittest.TestCase):
    def test_index_is_injected_on_the_first_turns(self):
        h = _handler()
        h.current_turn = 1
        block = h._kb_block()
        self.assertIn('[KB]', block)
        self.assertIn('app_cards.md', block)          # 指回细节, 不复制正文
        self.assertIn('小程序', block)
        self.assertNotIn('# app_index', block)        # 标题行不重复注入

    def test_later_turns_do_not_pay_for_it(self):
        h = _handler()
        h.current_turn = 9
        self.assertEqual(h._kb_block(), '')

    def test_the_index_file_exists_and_stays_small(self):
        p = CORE / 'memory/app_index.md'
        self.assertTrue(p.exists())
        self.assertLess(len(p.read_text(encoding='utf-8')), 4000)

    def test_missing_file_degrades_to_empty(self):
        h = _handler()
        h.current_turn = 1
        with patch.object(ga_android, 'script_dir', str(CORE / 'nope')):
            h._kb_text = None
            self.assertEqual(h._kb_block(), '')


class MissingTargetSaysGoUpTest(unittest.TestCase):
    def test_target_miss_soft_result_points_at_the_parent_page(self):
        # target 没命中现在是 SoftMiss(软失败结果, 带 near 候选), 不再是 [Error]:
        # 文案仍要指"上一级页面", 并且必须把这一屏真实存在的近似文字一起带回去。
        src = (CORE / 'ga_android.py').read_text(encoding='utf-8')
        i = src.find('raise SoftMiss(')
        self.assertGreater(i, 0)
        msg = src[i:i + 1200]
        self.assertIn('上一级', msg)
        self.assertIn('back', msg)
        self.assertIn('near', msg)


if __name__ == '__main__':
    unittest.main()
