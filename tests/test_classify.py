# -*- coding: utf-8 -*-
"""_classify: 画面分类谓词(纯函数, 无设备依赖)。

回归来源(真机 2026-10-28): 旧 screen_kind() 只认 degraded.reason=='tree_empty',
两个方向都错 ——
- 漏: 王者荣耀是 1 个不可点节点("Game view"), 不是 tree_empty → 判成 ui,
  YOLO 照样在游戏画面上跑, 21 个通用 Android 类的框把模型带偏;
- 误: 海报页/骨架屏/WebView 首帧所有节点都无 text/desc/clickable → tree_empty
  → 判成 canvas, 该拿图标框的普通页被跳过 YOLO, _compact_obs 还直接返回 []。

共同根因: 判的是"树是不是空", 而该判的是"有没有可用控件树"。低信息树判据
(节点数<=1 且无可点节点)把两头同时收进来。
"""
import sys
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import droid


def _node(click=False, text='x'):
    """dump_state 节点契约: {t,d,x,y,b,cls,click,edit,range,sel}(SPEC §2.3)。

    Kotlin 侧(BusA11yService.kt:275-279)只在文字非空时才 put "t"/"d", 故无文字节点
    根本没有这两个键 —— 辅助函数照此建模, 不拿 'icon' 之类的占位值冒充文字。"""
    n = {'x': 1, 'y': 1, 'b': [0, 0, 9, 9], 'cls': 'Text',
         'click': click, 'edit': False, 'range': None, 'sel': None}
    if text:
        n['t'] = text
    return n


def _st(nodes, reason=None):
    return {'nodes': nodes, 'degraded': {'reason': reason} if reason else None, 'pkg': 'com.x'}


class TestClassify(unittest.TestCase):
    def test_tree_when_normal_widget_tree(self):
        self.assertEqual(droid._classify(_st([_node(click=True), _node(click=True)])), 'tree')

    def test_blanked_when_sensitive_blank(self):
        self.assertEqual(droid._classify(_st([], 'sensitive_blank')), 'blanked')

    def test_blanked_when_unresolved_fg(self):
        self.assertEqual(droid._classify(_st([], 'unresolved_fg')), 'blanked')

    def test_canvas_when_tree_empty(self):
        self.assertEqual(droid._classify(_st([], 'tree_empty')), 'canvas')

    def test_canvas_when_low_information_tree(self):
        """王者荣耀实测形态: 1 个不可点节点("Game view")。旧判据只认 tree_empty 会漏。"""
        self.assertEqual(droid._classify(_st([_node(click=False)])), 'canvas')

    def test_canvas_when_nodes_exist_but_none_clickable(self):
        """海报/骨架屏/WebView 首帧: 多个节点但全无 text/desc/clickable。"""
        nodes = [_node(click=False, text=''), _node(click=False, text='')]
        self.assertEqual(droid._classify(_st(nodes)), 'canvas')

    def test_tree_when_many_text_nodes_but_none_clickable(self):
        """文章页: 没有可点目标, 但有大量文字 —— 树至少可读, 不是 canvas。"""
        nodes = [_node(click=False, text='标题%d' % i) for i in range(6)]
        self.assertEqual(droid._classify(_st(nodes)), 'tree')

    def test_unknown_when_state_is_none(self):
        self.assertEqual(droid._classify(None), 'unknown')

    def test_one_clickable_node_is_not_canvas(self):
        """有 1 个可点节点就不是低信息树 —— 双向收口的另一侧。"""
        self.assertEqual(droid._classify(_st([_node(click=False), _node(click=True)])), 'tree')

    def test_screen_kind_maps_unknown_to_ui(self):
        """screen_kind() 是历史公开契约(ui/blanked/canvas), unknown 归一成 ui。"""
        import unittest.mock as mock
        with mock.patch.object(droid, 'dump_state', side_effect=RuntimeError('bus down')):
            self.assertEqual(droid.screen_kind(), 'ui')
        with mock.patch.object(droid, 'dump_state', return_value=_st([_node(click=False)])):
            self.assertEqual(droid.screen_kind(), 'canvas')
        with mock.patch.object(droid, 'dump_state', return_value=_st([], 'sensitive_blank')):
            self.assertEqual(droid.screen_kind(), 'blanked')


if __name__ == '__main__':
    unittest.main()
