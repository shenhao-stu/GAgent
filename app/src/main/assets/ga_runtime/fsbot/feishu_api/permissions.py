# -*- coding: utf-8 -*-
"""权限检测 — 汇总各域权限状态，生成一键开通链接。"""

from ._base import _build_setup_url


def _domain_classes():
    """惰性导入各域类（避免权限模块拖累包导入）。"""
    from .calendar import CalendarAPI
    from .im import InstantMessagingAPI
    from .drive import DriveAPI
    from .docx import DocxAPI
    return [
        ("日历", CalendarAPI),
        ("群聊/消息", InstantMessagingAPI),
        ("云空间/文件", DriveAPI),
        ("文档", DocxAPI),
    ]


def check_all_permissions(as_user=False):
    """检测所有域权限。

    Returns:
        list of {domain, granted, missing_scopes, setup_url}
    """
    report = []
    for name, cls in _domain_classes():
        try:
            api = cls(as_user=as_user)
            r = api.check_scopes()
            r["domain"] = name
            report.append(r)
        except Exception as e:
            report.append({
                "domain": name, "granted": False,
                "missing_scopes": list(getattr(cls, "_scopes", [])),
                "setup_url": _build_setup_url(getattr(cls, "_scopes", [])),
                "error": str(e),
            })
    return report


def collect_missing_scopes(report):
    """从报告汇总所有缺失的 scope（去重）。"""
    seen = []
    for r in report:
        for s in r.get("missing_scopes", []):
            if s not in seen:
                seen.append(s)
    return seen
