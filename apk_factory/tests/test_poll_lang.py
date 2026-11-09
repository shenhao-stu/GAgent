# -*- coding: utf-8 -*-
"""poll() 附加 lang 键回归: 悬浮窗原生文案的语言真相源 = android_entry._LANG(/lang 设置)。
/lang 分支位于 has_key() 闸前 → 无 key 可测; poll 只读 _LANG, 加键不改原形状。"""
import json
import os
import sys
from pathlib import Path

GACORE = Path(__file__).resolve().parents[2] / "app" / "src" / "main" / "assets" / "ga_runtime"
sys.path.insert(0, str(GACORE))
import android_entry as ae  # noqa: E402


def test_poll_lang_defaults_zh_flips_via_lang_command_and_restores():
    assert json.loads(ae.poll('0'))['lang'] == 'zh'   # 首拉/键缺省语义: 默认与 _LANG 一致 = zh
    try:
        assert ae.send('/lang en') == 'lang=en'
        assert json.loads(ae.poll('0'))['lang'] == 'en'
        assert os.environ.get('GA_LANG') == 'en'      # 智能体输出语言 env 同步跟随
    finally:
        ae.send('/lang zh')                           # 还原, 不污染同进程其他用例
    assert json.loads(ae.poll('0'))['lang'] == 'zh'
    assert os.environ.get('GA_LANG') == 'zh'
