# -*- coding: utf-8 -*-
"""被 observe()/see() 取代的机制必须真删掉, 不是留着不调。

死代码铁律: 留着"暂时不用"的开关比没有更糟——下一个读代码的人会以为它还有效,
照它改一遍, 而真正的路径在别处。本组用例按名字逐条确认它们已经不在了。
"""
import os
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'


def _py_src():
    """只取 .py 源码; 排除 .md/.template(那里提旧名字是文档说明, 不是代码)。"""
    out = []
    for dirpath, dirs, files in os.walk(_ROOT):
        if '__pycache__' in dirpath:
            continue
        for f in files:
            if f.endswith('.py') and not f.endswith('.template.py'):
                out.append(open(os.path.join(dirpath, f), encoding='utf-8',
                                errors='replace').read())
    return '\n'.join(out)


class TestDeadCodeGone(unittest.TestCase):
    def test_vision_total_budget_is_gone(self):
        self.assertNotIn('_vision_total_budget', _py_src())

    def test_budget_constants_are_gone(self):
        s = _py_src()
        for c in ('_VISION_TOTAL_S', '_VISION_RESERVE_S', '_VISION_MIN_S'):
            self.assertNotIn(c, s, c)

    def test_vision_api_fallback_is_gone(self):
        """memory/vision_api.py 从来不存在(只有 .template.py), 那条兜底必然报错。"""
        self.assertNotIn('from vision_api import', _py_src())

    def test_vision_tls_is_gone(self):
        self.assertNotIn('_VISION_TLS', _py_src())

    def test_process_wide_fuse_singleton_is_gone(self):
        """进程级单例熔断让"上个模型的失败"罚下一个模型; 已改成按 backend 身份。"""
        self.assertNotIn('_VISION_FAILS', _py_src())

    def test_yolo_flag_is_gone_from_public_signatures(self):
        """通道选择搬进了 observe 的 _classify; 公开入口再留 yolo= 形参就是假开关。"""
        import inspect
        import droid
        self.assertNotIn('yolo', inspect.signature(droid.look).parameters)
        self.assertNotIn('yolo', inspect.signature(droid.ui_detect).parameters)

    def test_old_look_cache_is_gone(self):
        """缓存键已补 pkg/rot, 旧结构留着会让人照它改。"""
        self.assertNotIn('_LOOK_CACHE', _py_src())

    def test_run_guard_check_is_still_wired_everywhere(self):
        """看门狗复用既有检查点; 确认它们没被顺手删掉。"""
        self.assertGreaterEqual(_py_src().count('run_guard.check()'), 8)


if __name__ == '__main__':
    unittest.main()
