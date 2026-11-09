# -*- coding: utf-8 -*-
"""Shared routing templates and adapter policy declarations.

Phone guide prose is reviewed with its contracts, not frozen by word matching.
Runtime guards are exercised in test_phone_task_regressions and
test_droid_paste_verify, including visual-only and unresolved foregrounds.
"""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GACORE = ROOT / "app" / "src" / "main" / "assets" / "ga_runtime"
PHONE_USE = GACORE / "memory" / "phone_use.md"
DROID = GACORE / "droid.py"

def droid_module_doc():
    source = DROID.read_text(encoding="utf-8")
    return ast.get_docstring(ast.parse(source), clean=False) or ""


def test_policy_does_not_recommend_evasion():
    droid = DROID.read_text(encoding="utf-8")
    assert "降低合成输入指纹" not in droid
    assert "微信等风控 App 建议开" not in droid


def test_sensitive_apps_share_one_code_policy():
    """Adapter entry points share the policy registry; runtime tests check effects."""
    droid = DROID.read_text(encoding="utf-8")
    assert "SENSITIVE_APPS" in droid and "com.tencent.mm" in droid   # 单一真相源=策略注册表 SENSITIVE_APPS(SENSITIVE_PKGS 为其派生)
    assert "_app_policy" in droid            # 单一策略漏斗: dump/scroll/paste 共用, 无内联复制漂移
    assert "_visual_only" in droid           # 节点许可不暴露包名
    assert "fail-closed" in droid            # 前台未解析→按敏感处理, 安全方向不可回退
    sop = PHONE_USE.read_text(encoding="utf-8")
    assert "SENSITIVE_APPS" in sop           # SOP 措辞指向代码注册表(单一真相源), 不复制清单
    for token in ("敏感App", "恒返回 []", "视觉路径"):
        assert token in sop


def test_tap_docstring_documents_safety_not_evasion():
    droid = DROID.read_text(encoding="utf-8")
    expected = (
        '    """human=True only adds small motor-tolerance jitter; '
        "it is not an anti-abuse bypass.\n"
        "    Sensitive apps must use state-driven waits and stop on "
        'security checks."""'
    )
    assert expected in droid


def test_droid_quick_reference_matches_paste_runtime_contract():
    doc = droid_module_doc()
    for token in (
        "hit=True=已确认上屏",
        "hit=False, uncertain=True=验证不可用/结论不确定",
        "禁止重复输入或盲目降级",
        "ime_label 仅为元数据",
        "只有 ime_hint 可点击",
    ):
        assert token in doc
    assert "hit=False=没上屏" not in doc


def test_droid_quick_reference_matches_scroll_runtime_contract():
    doc = droid_module_doc()
    for token in (
        "必须检查 scrolled/evidence/uncertain",
        "uncertain=True=观察不可用/结论不确定",
        "不是已验证未滚动",
        "禁盲目重试",
    ):
        assert token in doc
