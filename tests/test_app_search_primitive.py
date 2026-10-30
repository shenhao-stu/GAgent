"""搜索入口原语(gui_act action='search_app' -> droid.app_search)的契约。

背景(真机会话 temp/logpull/new/turns_15_06.txt): 任务是"打开微信→搜小程序→看套牌"。
模型为找微信主页标题栏的放大镜, 先打了一次 see(want='point', roi='title') ——
16.3 秒, 返回 rx=830, ry=79, 和 memory/phone_use.md 里早就写下的实测值完全一致。
这段路径是固定的, 不该每一步都靠视觉重新发现一遍。

本文件锁四件事:
  ① 正常路径: launch -> 等稳定 -> 点入口 -> 粘贴, 每步都有判据, 最后 ok=True;
  ② launch 后前台不是目标包名时立刻失败(旧口径只看"fg 非空", 把拉起失败当成功,
     于是 ga_android 跳过 wait_stable, 模型拿着拉起前的帧算坐标);
  ③ 入口点下去屏幕没变(diff < 1%)时停下并提示改看当帧, 不做"看起来成功了"的静默降级;
  ④ 未登记入口的 App 明确拒绝, 且业务页坐标一个都没写死(只固化入口)。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import droid


class _NoBus(unittest.TestCase):
    """把 droid 的对外原语整段替换掉: 本文件只验证编排与判据, 不碰设备。"""

    def _patch(self, **kw):
        base = dict(launch=lambda pkg, wait=1.0: {'pkg': pkg, 'fg': pkg, 'fg_ok': True},
                    wait_stable=lambda **k: {'stable': True},
                    ping=lambda: {'w': 1200, 'h': 2670, 'pkg': 'com.tencent.mm'},
                    tap=lambda x, y: {'diff': 'diff: 28.0%'},
                    paste=lambda text, **k: {'hit': True},
                    # 结果行是"当帧 OCR"的: 默认给空, 免得单测去打真机总线。
                    shot=lambda **k: (_ for _ in ()).throw(RuntimeError('no device')),
                    ocr=lambda *a, **k: [])
        base.update(kw)
        return patch.multiple(droid, **base)


class AppSearchTest(_NoBus):
    def test_happy_path_types_the_keyword_into_the_entry(self):
        calls = []

        def _tap(x, y):
            calls.append(('tap', x, y))
            return {'diff': 'diff: 28.0%'}

        def _paste(text, **k):
            calls.append(('paste', text, k))
            return {'hit': True}

        with self._patch(tap=_tap, paste=_paste):
            out = droid.app_search(pkg='com.tencent.mm', query='炉石传说')
        self.assertTrue(out['ok'], out)
        self.assertEqual(out['query'], '炉石传说')
        # 入口 = 微信主页标题栏放大镜的实测相对坐标(1200x2670 -> 996,211 附近)
        entry = out['search_entry']
        self.assertEqual(entry['rel'], [830, 79])
        self.assertTrue(900 <= entry['point'][0] <= 1100, entry)
        self.assertEqual([c[0] for c in calls], ['tap', 'paste'])
        self.assertEqual(calls[1][1], '炉石传说')
        self.assertEqual(list(calls[1][2].get('point')), list(entry['point']))
        self.assertEqual([s['step'] for s in out['steps']], ['launch', 'settle', 'entry_tap', 'paste'])

    def test_launch_that_did_not_foreground_fails_fast(self):
        with self._patch(launch=lambda pkg, wait=1.0: {'pkg': pkg, 'fg': 'com.miui.home',
                                                      'fg_ok': False}):
            out = droid.app_search(pkg='com.tencent.mm', query='炉石传说')
        self.assertFalse(out['ok'])
        self.assertIn('前台', out['hint'])
        self.assertEqual([s['step'] for s in out['steps']], ['launch'])

    def test_entry_that_changes_nothing_stops_and_does_not_type(self):
        typed = []
        with self._patch(tap=lambda x, y: {'diff': 'diff: 0.02%'},
                         paste=lambda text, **k: typed.append(text) or {'hit': True}):
            out = droid.app_search(pkg='com.tencent.mm', query='炉石传说')
        self.assertFalse(out['ok'])
        self.assertEqual(typed, [])
        self.assertIn('入口', out['hint'])
        self.assertEqual([s['step'] for s in out['steps']], ['launch', 'settle', 'entry_tap'])

    def test_paste_that_never_landed_is_reported_not_swallowed(self):
        with self._patch(paste=lambda text, **k: {'hit': False, 'needs_gui_paste': True}):
            out = droid.app_search(pkg='com.tencent.mm', query='炉石传说')
        self.assertFalse(out['ok'])
        self.assertIn('粘贴', out['hint'])
        self.assertFalse(out['steps'][-1]['hit'])

    def test_unregistered_app_is_rejected(self):
        out = droid.app_search(pkg='com.example.unknown', query='x')
        self.assertFalse(out['ok'])
        self.assertIn('入口', out['hint'])

    def test_empty_query_is_rejected(self):
        self.assertFalse(droid.app_search(pkg='com.tencent.mm', query='  ')['ok'])

    def test_schema_action_name_is_callable_on_droid(self):
        # tools_schema 宣传的 action 名必须能在 droid 里找到同名实现
        self.assertTrue(callable(getattr(droid, 'search_app', None)))


class EntryTableTest(unittest.TestCase):
    def test_only_entry_paths_are_recorded(self):
        """写死的只有"入口锚点", 且是 0-1000 相对坐标(与分辨率无关)。

        业务页坐标必须当帧观测 —— geom.py:15-19: BANDS 只描述系统 UI, App 特有位置只能来自当前帧。
        """
        for pkg, ent in droid.APP_ENTRY.items():
            self.assertTrue(pkg.count('.'), pkg)
            self.assertLessEqual(set(ent), {'label', 'search_rel'}, pkg)
            for v in ent.get('search_rel', ()):
                self.assertTrue(0 <= v <= 1000, (pkg, v))

    def test_entry_hint_is_a_copy(self):
        hint = droid.entry_hint('com.tencent.mm')
        hint['search_rel'] = (0, 0)
        self.assertEqual(droid.APP_ENTRY['com.tencent.mm']['search_rel'], (830, 79))
        self.assertEqual(droid.entry_hint('com.unknown.pkg'), {})


if __name__ == '__main__':
    unittest.main()


class SearchRowsTest(_NoBus):
    """search_app 之后直接给出结果行的位置。

    真机 2026-10-29 的第 4/5/6 个会话: 关键词上屏后, 模型手里只有一张 647x1440 的图,
    于是把图上量到的坐标填进 point(设备像素), 结果每一下都偏到 1/1.86 处, diff 反复
    0.010%/0.000%(turns 见 temp/logpull/new3/narr_slow_210s.txt)。结果行的设备像素只有
    这一帧 OCR 知道, 让原语顺手带回去, 比让模型自己换算更可靠。
    """

    @staticmethod
    def _ocr(boxes):
        return [(b, t, 0.9) for b, t in boxes]

    def test_rows_are_read_from_this_frame_and_merged_per_line(self):
        img = [[0] * 1200 for _ in range(2670)]
        boxes = [
            ([40, 560, 300, 600], '元梦之星'),        # 结果行 1 的标题
            ([40, 610, 240, 640], '游戏'),            # 同一行的第二段(会被合并)
            ([40, 900, 300, 940], '元梦之星游戏小程序'),  # 结果行 2
            ([40, 60, 300, 100], 'Q元梦之星'),         # 搜索框回显: 在 0.06H 之上, 必须被过滤
            ([40, 2600, 300, 2640], '导航栏'),          # 0.92H 之下, 必须被过滤
        ]
        with self._patch(shot=lambda **k: img, ocr=lambda *a, **k: self._ocr(boxes)):
            rows = droid._search_rows()
        self.assertEqual([r['t'] for r in rows], ['元梦之星 游戏', '元梦之星游戏小程序'])
        self.assertEqual([r['y'] for r in rows], [580, 920])
        self.assertTrue(all(r['y'] <= 2670 and r['x'] >= 0 for r in rows))

    def test_ocr_failure_never_turns_a_successful_paste_into_a_failure(self):
        with self._patch(shot=lambda **k: (_ for _ in ()).throw(RuntimeError('takeScreenshot failed')),
                         ocr=lambda *a, **k: []):
            out = droid.app_search(pkg='com.tencent.mm', query='元梦之星')
        self.assertTrue(out['ok'])
        self.assertNotIn('results', out)
        self.assertIn('关键词已上屏', out['hint'])

    def test_rows_ride_along_with_the_keyword(self):
        img = [[0] * 1200 for _ in range(2670)]
        boxes = [([40, 560, 300, 600], '元梦之星'), ([40, 900, 300, 940], '梦幻西游')]
        with self._patch(shot=lambda **k: img, ocr=lambda *a, **k: self._ocr(boxes)):
            out = droid.app_search(pkg='com.tencent.mm', query='元梦之星')
        self.assertTrue(out['ok'])
        self.assertEqual([r['t'] for r in out['results']], ['元梦之星', '梦幻西游'])
        self.assertIn('point=[x,y]', out['hint'])
        self.assertIn('别把附图上的像素填进 point', out['hint'])

    def test_rows_are_capped(self):
        img = [[0] * 1200 for _ in range(2670)]
        boxes = [([40, 400 + 80 * i, 300, 440 + 80 * i], '结果%d' % i) for i in range(12)]
        with self._patch(shot=lambda **k: img, ocr=lambda *a, **k: self._ocr(boxes)):
            rows = droid._search_rows(limit=6)
        self.assertEqual(len(rows), 6)
