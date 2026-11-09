# -*- coding: utf-8 -*-
"""输出格式化 — 把各域 API 返回结构转成可读文本(markdown，供卡片渲染)。"""

import json
from datetime import datetime, timedelta

WEEK_OFFSET = 8 * 3600


def _ts_to_str(ts):
    """Unix秒 → 'MM-DD HH:MM'。容错 None/空。"""
    if not ts:
        return "--"
    try:
        n = int(ts)
        dt = datetime.fromtimestamp(n)
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return str(ts)


def _full_ts_to_str(ts):
    if not ts:
        return "--"
    try:
        n = int(ts)
        return datetime.fromtimestamp(n).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


# ----------------------------------------------------------------------
# 日历/日程
# ----------------------------------------------------------------------

def format_calendar_list(calendars):
    if not calendars:
        return "📭 暂无日历"
    lines = [f"📅 **日历列表**（{len(calendars)}个）"]
    for c in calendars:
        role = c.get("role", "?")
        summary = c.get("summary", "(未命名)")
        cal_id = c.get("calendar_id", "")
        lines.append(f"- **{summary}** `{role}`")
        lines.append(f"  `{cal_id}`")
    return "\n".join(lines)


def format_event_list(events, date_label=""):
    if not events:
        return f"📭 {date_label}暂无日程" if date_label else "📭 暂无日程"
    lines = [f"📅 **{date_label}日程**（{len(events)}项）"] if date_label else [f"📅 **日程**（{len(events)}项）"]
    for e in events:
        summary = e.get("summary") or "(无标题)"
        st = e.get("start_time", {})
        et = e.get("end_time", {})
        st_ts = st.get("timestamp") if isinstance(st, dict) else st
        et_ts = et.get("timestamp") if isinstance(et, dict) else et
        loc = ""
        if isinstance(e.get("location"), dict):
            loc = e.get("location", {}).get("name", "")
        loc_str = f" · {loc}" if loc else ""
        lines.append(f"- `{_ts_to_str(st_ts)}~{_ts_to_str(et_ts)}` **{summary}**{loc_str}")
    return "\n".join(lines)


def format_event_created(result):
    eid = ""
    if isinstance(result, dict):
        eid = result.get("event_id", result.get("calendar_event_id", ""))
    return f"✅ 日程已创建 · `event_id`=`{eid}`"


# ----------------------------------------------------------------------
# IM / 群聊 / 消息
# ----------------------------------------------------------------------

def format_chat_list(chats):
    if not chats:
        return "📭 机器人未加入任何群聊"
    lines = [f"💬 **群聊列表**（{len(chats)}个）"]
    for c in chats:
        name = c.get("name", "(未命名)")
        cid = c.get("chat_id", "")
        ext = "外部" if c.get("external") else "内部"
        lines.append(f"- **{name}** `{ext}`")
        lines.append(f"  `{cid}`")
    return "\n".join(lines)


def format_message_list(messages, keyword=""):
    if not messages:
        kw = f"关键词「{keyword}」" if keyword else ""
        return f"📭 未找到{kw}相关消息"
    kw = f"(关键词「{keyword}」)" if keyword else ""
    lines = [f"📨 **匹配消息** {kw}（{len(messages)}条）"]
    for m in messages[:20]:   # 最多展示20条
        sender = m.get("sender", {})
        sender_id = ""
        if isinstance(sender, dict):
            sender_id = sender.get("id", "")
        body = m.get("body", {})
        content_str = body.get("content", "{}") if isinstance(body, dict) else "{}"
        text = content_str
        try:
            c = json.loads(content_str) if isinstance(content_str, str) else content_str
            if isinstance(c, dict):
                text = c.get("text") or c.get("title", "")
                if isinstance(text, dict):
                    text = text.get("content", "")
        except Exception:
            pass
        create = m.get("create_time", "")
        ct = _full_ts_to_str(create) if create and str(create).isdigit() else ""
        prefix = f"`{ct}` " if ct else ""
        lines.append(f"- {prefix}{text[:60]}")
    if len(messages) > 20:
        lines.append(f"  …还有 {len(messages)-20} 条")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# 文档
# ----------------------------------------------------------------------

def format_document_list(documents):
    if not documents:
        return "📭 暂无文档"
    lines = [f"📝 **文档列表**（{len(documents)}个）"]
    for d in documents:
        name = d.get("name", "(未命名)")
        token = d.get("document_id") or d.get("token", "")
        owner = d.get("owner", {})
        owner_id = owner.get("id", "") if isinstance(owner, dict) else ""
        lines.append(f"- **{name}**")
        lines.append(f"  `{token}`")
    return "\n".join(lines)


def format_blocks(blocks):
    if not blocks:
        return "📭 文档为空"
    lines = [f"📝 **文档内容**"]
    for b in blocks:
        bt = b.get("block_type", 0)
        eid = b.get("block_id", "")
        text = ""
        elements = b.get("text", {}).get("elements", []) if isinstance(b.get("text"), dict) else []
        for el in elements:
            if isinstance(el, dict) and "text_run" in el:
                text += el["text_run"].get("content", "")
        if text:
            lines.append(text)
    return "\n".join(lines)


def format_document_created(result):
    doc = {}
    if isinstance(result, dict):
        doc = result.get("document", result)
    did = doc.get("document_id", "") if isinstance(doc, dict) else ""
    lines = ["✅ 文档已创建"]
    if did:
        lines.append(f"  `document_id`=`{did}`")
        lines.append(f"  🔗 https://feishu.cn/docx/{did}")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# 云空间/文件
# ----------------------------------------------------------------------

def format_file_list(files):
    if not files:
        return "📭 暂无文件"
    lines = [f"📁 **文件列表**（{len(files)}个）"]
    for f in files:
        name = f.get("name", "(未命名)")
        token = f.get("token", "")
        ftype = f.get("type", "")
        size = f.get("size", 0)
        size_str = _human_size(size)
        lines.append(f"- **{name}** `{ftype}` `{size_str}`")
        lines.append(f"  `{token}`")
    return "\n".join(lines)


def _human_size(size):
    try:
        n = int(size)
        for unit in ["B", "K", "M", "G"]:
            if n < 1024:
                return f"{n}{unit}"
            n /= 1024
        return f"{n:.1f}T"
    except Exception:
        return str(size)


def format_file_uploaded(result):
    token = result.get("file_token", "") if isinstance(result, dict) else ""
    return f"✅ 文件已上传 · `token`=`{token}`"


def format_file_downloaded(path):
    return f"✅ 文件已下载到：`{path}`"


# ----------------------------------------------------------------------
# 权限
# ----------------------------------------------------------------------

def format_permissions(report):
    """report: list of {domain, granted, missing_scopes, setup_url}"""
    lines = ["🔐 **权限总览**"]
    for r in report:
        domain = r.get("domain", "?")
        if r.get("granted"):
            lines.append(f"- ✅ **{domain}** 已开通")
        else:
            missing = r.get("missing_scopes", [])
            url = r.get("setup_url", "")
            lines.append(f"- ❌ **{domain}** 缺 `{', '.join(missing)}`")
            if url:
                lines.append(f"  开通：{url}")
    return "\n".join(lines)
