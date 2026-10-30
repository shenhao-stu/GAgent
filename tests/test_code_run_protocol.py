"""code_run 协议修复（2026-10-26 慢因归因）。

实证：tools_schema 描述建议“ prefer reply code block ”，模型照做后两轮作废——
a5 只给 desc 不给 script（无代码可执行），a7 只回复代码块不发工具调用（纯回复不执行）。
修复：①错误信息说清“script 参数或同回复内的 ```python 块，且工具调用必须发”；
②_extract_code_block 增加无语言标签围栏的兜底；③schema 描述不再推荐回复代码块。
"""
import sys
import types
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import ga_android
from agent_loop import StepOutcome


class ExtractCodeBlockTest(unittest.TestCase):
    def setUp(self):
        self.h = object.__new__(ga_android.GenericAgentHandler)

    def _resp(self, content):
        return types.SimpleNamespace(content=content)

    def test_tagged_block_extracted(self):
        r = self._resp("<summary>x</summary>\n```python\nprint(1)\n```")
        self.assertEqual(self.h._extract_code_block(r, "python"), "print(1)")

    def test_untagged_fence_falls_back(self):
        # 模型常发无语言标签的裸围栏: 旧正则不匹配 → 整轮作废(实证浪费 2 轮)
        r = self._resp("<summary>x</summary>\n```\nprint('hi')\n```")
        self.assertEqual(self.h._extract_code_block(r, "python"), "print('hi')")

    def test_tagged_block_wins_over_untagged(self):
        r = self._resp("```\nprint('decoy')\n```\n```python\nprint('real')\n```")
        self.assertEqual(self.h._extract_code_block(r, "python"), "print('real')")

    def test_no_block_returns_none(self):
        self.assertIsNone(self.h._extract_code_block(self._resp("<summary>nothing</summary>"), "python"))


class CodeRunMissingCodeTest(unittest.TestCase):
    def setUp(self):
        self.h = object.__new__(ga_android.GenericAgentHandler)

    def _missing_code_outcome(self, args, content):
        # do_code_run 是生成器: 提前 return 经 StopIteration.value 传出
        try:
            next(self.h.do_code_run(args, types.SimpleNamespace(content=content)))
        except StopIteration as e:
            return e.value
        self.fail("do_code_run 应在缺代码时直接返回")

    def test_missing_code_error_names_both_paths_and_requires_tool_call(self):
        outcome = self._missing_code_outcome({"desc": "启动腾讯新闻"}, "<summary>x</summary>")
        self.assertIsInstance(outcome, StepOutcome)
        msg = str(outcome.data)
        self.assertIn("script", msg)
        self.assertIn("```python", msg)

    def test_missing_code_error_mentions_tool_call_required(self):
        outcome = self._missing_code_outcome({}, "没有代码")
        self.assertIn("工具调用", str(outcome.data))


if __name__ == "__main__":
    unittest.main()
