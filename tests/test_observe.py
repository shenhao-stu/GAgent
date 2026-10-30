# -*- coding: utf-8 -*-
"""observe(): 一次截图 + 一次分类 + 按类选通道。

锁三件事:
1. 通道选择由 _classify 决定, 不靠模型现推 —— canvas 页不跑本地定位通道(游戏/混淆/自绘
   没有控件树, YOLO 的 21 个通用 Android 类只会把模型带偏);
2. YOLO 挂了只降级记 note, 不外抛(真机 10:22 那次 22 分钟的根因);
3. 缓存键含 pkg/rot —— SPEC §2.3 记着的既有缺陷: 切 App 或转屏后可能命中旧结果。
"""
import sys
import unittest
from pathlib import Path

import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import droid

_IMG = np.zeros((100, 200, 3), dtype='uint8')


def _node(x=10, y=10, click=True, text='按钮'):
    n = {'x': x, 'y': y, 'b': [x - 5, y - 5, x + 5, y + 5], 'cls': 'Text',
         'click': click, 'edit': False, 'range': None, 'sel': None}
    if text:
        n['t'] = text
    return n


def _det(x=50, y=50, label='确定', cls='TextButton'):
    return {'bbox': [x - 10, y - 10, x + 10, y + 10], 'type': 'icon', 'label': label,
            'cls': cls, 'confidence': 0.9}


def _wire(self, kind, nodes=(), dets=(), note=None, pkg='com.x'):
    """把 observe 的设备依赖全部换成可控假件; 缓存每次清空。"""
    import unittest.mock as mock
    for name, fake in (
            ('dump_state', lambda full=False: {'nodes': list(nodes), 'degraded': None, 'pkg': pkg}),
            ('_classify', lambda st: kind),
            ('shot', lambda *a, **k: _IMG),
            ('ui_detect', lambda img, conf=0.25, yolo=True: list(dets)),
            ('_detect_note', lambda: note),
            ('screen', lambda: (200, 100)),
            ('ping', lambda: {'w': 200, 'h': 100, 'rot': 0})):
        p = mock.patch.object(droid, name, fake)
        p.start()
        self.addCleanup(p.stop)
    droid._OBS_CACHE.update(thumb=None, roi=None, pkg=None, rot=None, res=None)


class RoiBoxTest(unittest.TestCase):
    """模型把 roi 写成 0-1000 数字框是合理用法(真机 15:41 就这么写然后整轮观测作废)。"""

    def test_bracketed_box(self):
        import droid as _d
        self.assertEqual(_d._roi_box('[800, 150, 950, 250]'), (800.0, 150.0, 950.0, 250.0))

    def test_bracketed_box_with_parens(self):
        import droid as _d
        self.assertEqual(_d._roi_box('(0,0,500,500)'), (0.0, 0.0, 500.0, 500.0))

    def test_unbracketed_box_is_accepted(self):
        import droid as _d
        self.assertEqual(_d._roi_box('800,150,950,250'), (800.0, 150.0, 950.0, 250.0))

    def test_a_box_clamped_to_nothing_is_not_a_box(self):
        import droid as _d
        self.assertIsNone(_d._roi_box('[2000,0,3000,500]'))     # 全在屏外: 不许静默裁成零宽
        self.assertIsNone(_d._roi_box('[0,0,0,0]'))

    def test_a_name_is_not_a_box(self):
        import droid as _d
        self.assertIsNone(_d._roi_box('title'))


class TestObserve(unittest.TestCase):
    def test_tree_kind_merges_tree_and_yolo(self):
        _wire(self, 'tree', nodes=[_node()], dets=[_det()])
        r = droid.observe()
        self.assertEqual(r['kind'], 'tree')
        self.assertEqual(sorted(i['src'] for i in r['items']), ['tree', 'yolo'])
        self.assertIn('yolo', r['channels'])
        self.assertIn('tree', r['channels'])

    def test_canvas_kind_runs_no_local_channel(self):
        """游戏/混淆/canvas: 不跑 YOLO 也不为定位跑 OCR —— 定位问 see()。"""
        _wire(self, 'canvas', nodes=[], dets=[_det()])
        r = droid.observe()
        self.assertEqual(r['kind'], 'canvas')
        self.assertEqual(r['items'], [])
        self.assertEqual(r['channels'], [])
        self.assertTrue(r['needs_vision'])

    def test_blanked_kind_runs_yolo(self):
        _wire(self, 'blanked', nodes=[], dets=[_det(label='Q', cls='Icon')])
        r = droid.observe()
        self.assertEqual(r['kind'], 'blanked')
        self.assertEqual([i['src'] for i in r['items']], ['yolo'])
        self.assertIn('yolo', r['channels'])

    def test_yolo_failure_degrades_with_note(self):
        """R2: YOLO 挂了不抛, 树项照回, 且 notes 说清为什么少了图标框。"""
        _wire(self, 'tree', nodes=[_node()], dets=[], note='RuntimeError: model not found: /x')
        r = droid.observe()
        self.assertEqual([i['src'] for i in r['items']], ['tree'])
        self.assertEqual(r['notes'], ['local_boxes_unusable: RuntimeError: model not found: /x'])
        self.assertNotIn('yolo', r['channels'])

    def test_unknown_kind_falls_back_to_tree(self):
        """R1: dump_state 抛异常 → unknown → 仍跑本地通道, 不崩也不空手。"""
        _wire(self, 'unknown', nodes=[], dets=[_det()])
        r = droid.observe()
        self.assertEqual(r['kind'], 'unknown')
        self.assertEqual([i['src'] for i in r['items']], ['yolo'])

    def test_items_carry_both_units(self):
        _wire(self, 'tree', nodes=[], dets=[_det(x=100, y=50)])
        it = droid.observe()['items'][0]
        self.assertEqual((it['x'], it['y']), (100, 50))
        # to_norm 的分母是 w-1/h-1(与 to_px 互为逆运算, geom.py:72-73), 不是 w/h
        self.assertEqual((it['rx'], it['ry']), (503, 505))

    def test_dense_scene_drops_boxes_and_asks_for_vision(self):
        """游戏 HUD: YOLO 框太密 → 闸门跳过 OCR → 不把框留给模型, 并告知要问 see()。

        真机 2026-10-28: 小程序游戏画面被判 blanked(前台包名还是微信), observe 跑了全屏
        YOLO+OCR 返回 52 个框, 模型照着它们点了 3 次才摸到通行证。"""
        _wire(self, 'blanked', nodes=[], dets=[], note='scene_too_dense: 52 yolo boxes > 24')
        r = droid.observe()
        self.assertEqual(r['items'], [])
        self.assertNotIn('yolo', r['channels'])
        self.assertTrue(r['needs_vision'])
        self.assertIn('local_boxes_unusable', r['notes'][0])

    def test_cache_miss_after_package_change(self):
        """SPEC §2.3 缺陷: 缓存键不含 pkg → 切 App 后命中旧结果。"""
        _wire(self, 'tree', nodes=[_node(x=10)], dets=[_det(x=10, y=10)])
        self.assertEqual(droid.observe()['items'][0]['x'], 10)
        _wire(self, 'tree', nodes=[_node(x=180)], dets=[_det(x=180, y=90)], pkg='com.other')
        second = droid.observe()
        self.assertEqual(second['items'][0]['x'], 180)
        self.assertFalse(second.get('cached'))

    def test_cache_hit_on_identical_screen(self):
        _wire(self, 'tree', nodes=[_node(x=10)], dets=[])
        droid.observe()
        again = droid.observe()
        self.assertTrue(again.get('cached'))

    def test_roi_offsets_coordinates(self):
        _wire(self, 'tree', nodes=[], dets=[_det(x=50, y=50)])
        r = droid.observe(roi=(0, 0, 100, 50))     # 左上 100x50 区域(像素)
        it = r['items'][0]
        self.assertEqual(it['x'], 50)
        self.assertEqual(it['bbox'], [40, 40, 60, 60])

    def test_unknown_roi_name_is_rejected(self):
        _wire(self, 'tree')
        with self.assertRaises(ValueError):
            droid.observe(roi='nope')

    def test_look_is_a_thin_wrapper_over_observe(self):
        """look() 形状与历史一致(配方/SOP 不破), 且只返回 YOLO 项。"""
        _wire(self, 'tree', nodes=[_node(x=10)], dets=[_det(x=100, y=50, label='确定')])
        out = droid.look()
        self.assertEqual(len(out), 1)
        d = out[0]
        for k in ('bbox', 'type', 'label', 'cls', 'confidence', 'x', 'y', 'rx', 'ry'):
            self.assertIn(k, d)
        self.assertEqual(d['label'], '确定')
        self.assertEqual(d['x'], 100)

    def test_look_label_filter_still_works(self):
        _wire(self, 'tree', nodes=[], dets=[_det(label='确定'), _det(x=150, label='取消')])
        out = droid.look(label='取消')
        self.assertEqual([d['label'] for d in out], ['取消'])


    def test_roi_box_string_is_read_as_the_0_1000_contract(self):
        """真机 2026-10-30 15:41 实证: 模型把 roi 写成 "[800, 150, 950, 250]",
        而名字校验只认 'top'/'title', 于是整轮观测作废
        ({"ok":false,"reason":"ocr_failed","error":"ValueError: unknown roi …"}).
        文档里 roi 的契约就是 0-1000 归一化, 数字框必须吃下。"""
        _wire(self, 'tree', nodes=[], dets=[_det(x=10, y=10)])
        r = droid.observe(roi='[500, 0, 1000, 500]')      # 右半屏上半(0-1000), 屏幕 200x100
        self.assertEqual(droid._OBS_CACHE['roi'], (100, 0, 200, 50))
        self.assertEqual(r['items'][0]['x'], 110)          # 检出坐标已换算回整屏
        self.assertEqual(r['items'][0]['y'], 10)

    def test_roi_box_helper_and_resolve(self):
        self.assertEqual(droid._roi_box('[800, 150, 950, 250]'), (800.0, 150.0, 950.0, 250.0))
        self.assertEqual(droid._roi_box('( 0 , 0 ,1000, 1000 )'), (0.0, 0.0, 1000.0, 1000.0))
        self.assertIsNone(droid._roi_box('title'))         # 名字不是数字框
        self.assertIsNone(droid._roi_box([1, 2, 3, 4]))    # 非字符串: 保持原有像素/比例语义
        self.assertIsNone(droid._roi_box('[1, 2, 3]'))
        self.assertEqual(droid._resolve_roi('[800, 150, 950, 250]'), (800, 150, 950, 250))


if __name__ == '__main__':
    unittest.main()
