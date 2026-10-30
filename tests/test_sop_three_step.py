# -*- coding: utf-8 -*-
"""SOP 必须教三步契约, 且不得再教已搬进代码的机制细节。

为什么要锁: 判据/预算/降级都进了代码之后, SOP 里再留一份同样的表就是**双重真相**——
模型现推一遍, 代码又判一遍, 两边漂移时模型拿到的是过期规则。反过来, 属于**判断纪律**
的部分(禁把 tap diff 当成功证据、禁指纹比对认卡、层叠棋盘禁固定网格、双通道不可用即停)
是真机踩出来的, 不随机制变更而失效, 必须留着。
"""
import os
import unittest
from pathlib import Path

_SOP = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore/memory/phone_use.md'


def _sop():
    return _SOP.read_bytes().decode('utf-8')


class TestSopThreeStep(unittest.TestCase):
    def test_three_step_contract_is_at_the_top(self):
        # 取"第一个小节"而不是魔法字符数: 表里加一行(如 exit_miniapp)不该让契约测试假失败,
        # 要锁的是"三步契约就是第一屏", 不是"第一屏恰好 1400 字符"。
        body = _sop()
        start = body.find('## ')
        self.assertGreaterEqual(start, 0)
        self.assertLess(start, 200, '三步契约必须是文档开头第一节')
        end = body.find(chr(10) + '## ', start + 1)
        head = body[start:] if end < 0 else body[start:end]
        for token in ('gui_act', 'see(', 'code_run'):
            self.assertIn(token, head, token)

    def test_screen_kind_table_is_gone(self):
        """判据已进 _classify; 再留一张表就是让模型现推 + 双重真相。"""
        self.assertNotIn('## §0.05', _sop())

    def test_vision_budget_mechanics_are_gone(self):
        """预算/一轮一次/从 code_run 剩余推导 都是 see() 的内部事, 不该占模型注意力。"""
        s = _sop()
        self.assertNotIn('从 code_run 的剩余时间自动推导', s)
        self.assertNotIn('同一轮里调第二次', s)
        self.assertNotIn('每一轮最多一次视觉调用', s)

    def test_canvas_judgement_discipline_survives(self):
        """删机制, 留判断纪律 —— 这些是真机踩出来的, 不随机制变更而失效。"""
        s = _sop()
        for keep in ('不是成功证据', '指纹比对', '层叠棋盘禁固定网格', '双通道皆不可用即停',
                     '禁止自行编写 OpenCV/PIL'):
            self.assertIn(keep, s, keep)

    def test_observe_is_the_documented_local_entry(self):
        """工具表必须指向 observe(), 而不是让模型自己拼 dump+look。"""
        self.assertIn('`observe(', _sop())

    def test_local_boxes_unavailable_is_documented_as_degrade_not_fault(self):
        """YOLO 缺失/画面太密已改为自动降级; SOP 要说明这不是故障, 否则模型会停下来报错。"""
        self.assertIn('local_boxes_unavailable', _sop())


if __name__ == '__main__':
    unittest.main()
