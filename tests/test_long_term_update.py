"""start_long_term_update 的记忆结算: 结果必须自带记忆结构, 否则"不要额外 file_read"
就是让模型瞎改——两者是耦合的, 一起锁。

真机实证: 唯一跑完的 39 轮任务里, turn 35-38 四轮全花在记忆维护上
(start_long_term_update → code_run → file_read → file_read/file_patch), 占 10%。
schema 规定"15 轮以上的任务必须调用它", 所以每个长任务都要付这笔钱。
原提示词写着"先 file_read 看现有", 而工具结果里其实已经带了记忆库结构和 L1 现状。
"""
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import ga_android
from agent_loop import StepOutcome


class LongTermUpdateTest(unittest.TestCase):
    def setUp(self):
        self.handler = object.__new__(ga_android.GenericAgentHandler)
        self.handler.working = {}
        self.handler.history_info = []
        self.handler.code_stop_signal = []
        self.handler.current_turn = 0
        self.handler.parent = types.SimpleNamespace(task_dir=None, verbose=False)

    def _run(self, cwd):
        """do_start_long_term_update 是生成器: yield 一行 info, return 才交 StepOutcome。"""
        gen = self.handler.do_start_long_term_update({}, types.SimpleNamespace(content=''))
        value = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            value = e.value
        return value

    def test_result_carries_the_memory_structure_and_l1(self):
        """前提: 提示词里必须带记忆结构和 L1 现状, "不要额外 file_read"才站得住。"""
        old = os.getcwd()
        os.chdir(CORE)                     # 工具用相对路径 ./memory/... 取文件
        try:
            out = self._run(CORE)
        finally:
            os.chdir(old)
        self.assertIsInstance(out, StepOutcome)
        self.assertIn('L0', str(out.data))                 # data: 记忆更新 SOP 本身
        prompt = str(out.next_prompt)
        self.assertIn('[Memory]', prompt)                  # 记忆库结构
        self.assertIn('global_mem_insight', prompt)        # L1 现状

    def test_prompt_says_not_to_re_read_what_is_already_provided(self):
        old = os.getcwd()
        os.chdir(CORE)
        try:
            out = self._run(CORE)
        finally:
            os.chdir(old)
        prompt = str(out.next_prompt)
        self.assertIn('不要额外', prompt)
        self.assertIn('file_read', prompt)              # 说的是"不要"它, 不是没提
        # 不能再出现"先 file_read 看现有"这种强制多一轮的指令
        self.assertNotIn('先 `file_read` 看现有', prompt)

    def test_missing_sop_is_reported_not_silently_skipped(self):
        """SOP 不在时必须明说, 否则模型会在没有任何规程的情况下去改记忆库。"""
        with patch.object(ga_android.os.path, 'exists', lambda p: False):
            out = self._run(CORE)
        self.assertIn('not found', str(out.data))


if __name__ == '__main__':
    unittest.main()
