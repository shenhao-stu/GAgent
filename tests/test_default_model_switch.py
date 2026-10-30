# -*- coding: utf-8 -*-
"""设置页「设为默认模型」必须真正切运行时, 不只写持久层。

漏的那次(2026-10-28 代码审查): setDefaultModel 只写 kv/ga.active.json + mykey.py 的
model 字段, **不发 /llm**。于是当前会话的 agent backend 不切, 主对话和 vision 都继续
用旧型号, 要等下次显式 selectModel 或冷启才生效 —— 而用户以为自己已经切过去了。

同类入口都是成对的: selectEff = saveProvToMk + reapplyActiveLlm, removeProvider 也会补
sendLlmSwitch。setDefaultModel 是这条链上唯一"只改持久层"的。
"""
import os
import re
import unittest
from pathlib import Path

_JS = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore/webui/app.js'


def _fn(name):
    src = _JS.read_text(encoding='utf-8')
    m = re.search(r'function %s\(([^)]*)\)\{(.*?)\n\}' % re.escape(name), src, re.S)
    assert m, 'function %s not found' % name
    return m.group(2)


class TestDefaultModelSwitch(unittest.TestCase):
    def test_set_default_model_switches_runtime(self):
        body = _fn('setDefaultModel')
        self.assertIn('sendLlmSwitch', body,
                      'setDefaultModel 必须发 /llm, 否则运行时模型不切换')

    def test_select_model_still_switches_runtime(self):
        body = _fn('selectModel')
        self.assertIn('sendLlmSwitch', body)

    def test_every_model_mutator_switches_runtime(self):
        """切模型的入口一个都不能漏: 漏一个就是"UI 显示切了, 实际没切"。"""
        for fn in ('selectModel', 'selectAuto', 'setDefaultModel'):
            body = _fn(fn)
            self.assertTrue('sendLlmSwitch' in body or 'reapplyActiveLlm' in body,
                            '%s 既不发 /llm 也不重放, 运行时不会切' % fn)


if __name__ == '__main__':
    unittest.main()
