# -*- coding: utf-8 -*-
"""feishu_api 包入口 — 命令路由注册 + 帮助文本。

register_all_commands(app) 构建 CommandRouter 并注册各域处理器。
每个域处理器: (app, Command) -> 回复文本(str)
"""

from .command_router import (CommandRouter, parse_command,
                              parse_date, parse_date_or_range,
                              parse_time_of_day, CommandParseError)
from . import formatters as F


# ======================================================================
# 帮助文本
# ======================================================================

HELP_TEXT = """## 📋 飞书业务域命令

### 📅 日历 / 日程
- `/日历 list` — 列出我订阅的日历
- `/日程 今日` / `/日程 明天` — 今日 / 明日日程
- `/日程 2026-07-14` — 指定日期日程
- `/日程 明天 10:00-11:00 团队周会` — 创建日程（标题可含空格）

### 💬 群聊 / 消息
- `/群聊 list` — 列出机器人所在群
- `/消息 --chat <chat_id> --kw <关键词>` — 群内搜索消息

### 📄 文档
- `/文档 list` — 列出文档
- `/文档 read --token <doc_token>` — 读取文档全文
- `/文档 create [--title 标题] [--folder <folder_token>]` — 创建新文档

### 📁 云空间 / 文件
- `/文件 list` — 列出文件
- `/文件 upload --path <本地路径>` — 上传文件
- `/文件 download --token <file_token> --save <本地路径>` — 下载文件

### ⚙️ 其他
- `/权限` — 权限总览
- `/帮助` — 本说明

> 💡 不以 `/` 开头的消息仍走 AI Agent
"""


# ======================================================================
# 域处理器
# ======================================================================

def _calendar_handler(app, cmd):
    from .calendar import CalendarAPI
    cal = CalendarAPI()
    if cmd.action in ("list", "列表"):
        return F.format_calendar_list(cal.list_calendars())
    return "用法: /日历 list"


def _agenda_handler(app, cmd):
    """日程: 查询/创建。"""
    from .calendar import CalendarAPI
    cal = CalendarAPI()
    action = cmd.action
    args = cmd.args

    # /日程 日期 HH:MM-HH:MM 标题  → 创建
    # 判定: args 第2个元素(索引1)是否为时间区间
    if len(args) >= 2 and "-" in args[0] and ":" in args[0] and \
            args[0].count("-") >= 1 and args[0].split("-")[0].count(":") == 1:
        # args[0]=HH:MM-HH:MM, args[1:]=标题
        time_range = args[0]
        summary = " ".join(args[1:])
        date_ts = parse_date(action)
        start, end = _parse_time_range(date_ts, time_range)
        result = cal.create_event("primary", summary, start, end)
        return F.format_event_created(result)

    # 查询: /日程 [今日|明天|2026-07-14]
    date_expr = action or "今日"
    if not date_expr:
        date_expr = "今日"
    start, end = parse_date_or_range(date_expr)
    events = cal.get_agenda(start, end, calendar_id="primary")
    return F.format_event_list(events, date_label=date_expr + " ")


def _chat_handler(app, cmd):
    from .im import InstantMessagingAPI
    im = InstantMessagingAPI()
    if cmd.action in ("list", "列表"):
        return F.format_chat_list(im.list_chats())
    return "用法: /群聊 list"


def _message_handler(app, cmd):
    from .im import InstantMessagingAPI
    im = InstantMessagingAPI()
    chat_id = cmd.kwargs.get("chat") or cmd.kwargs.get("chat_id")
    keyword = cmd.kwargs.get("kw") or cmd.kwargs.get("keyword", "")
    if not chat_id:
        return ("用法: /消息 --chat <chat_id> --kw <关键词>\n"
                "提示: 用 /群聊 list 获取 chat_id")
    matched = im.search_in_chat(chat_id, keyword)
    return F.format_message_list(matched, keyword=keyword)


def _doc_handler(app, cmd):
    from .docx import DocxAPI
    docx = DocxAPI()
    if cmd.action in ("list", "列表"):
        return F.format_document_list(docx.list_documents())
    if cmd.action in ("read", "读取"):
        token = cmd.kwargs.get("token") or cmd.kwargs.get("doc")
        if not token:
            return "用法: /文档 read --token <doc_token>"
        text = docx.get_text(token)
        return "📝 文档内容:\n" + (text or "(空文档)")
    if cmd.action in ("create", "新建", "创建"):
        title = cmd.kwargs.get("title")
        folder = cmd.kwargs.get("folder") or cmd.kwargs.get("folder_token")
        result = docx.create_document(folder_token=folder)
        did = ""
        if isinstance(result, dict):
            did = result.get("document", {}).get("document_id", "")
        if title and did:
            try:
                docx.add_text_blocks(did, [title])
            except Exception:
                pass
        return F.format_document_created(result)
    return "用法: /文档 list | /文档 read --token <token> | /文档 create [--title 标题]"


def _file_handler(app, cmd):
    from .drive import DriveAPI
    drive = DriveAPI()
    if cmd.action in ("list", "列表"):
        return F.format_file_list(drive.list_files())
    if cmd.action == "upload":
        path = cmd.kwargs.get("path")
        if not path:
            return "用法: /文件 upload --path <本地路径>"
        result = drive.upload_file(path)
        return F.format_file_uploaded(result)
    if cmd.action == "download":
        token = cmd.kwargs.get("token") or cmd.kwargs.get("file_token")
        save = cmd.kwargs.get("save") or cmd.kwargs.get("path")
        if not token:
            return "用法: /文件 download --token <file_token> --save <本地路径>"
        out = drive.download_file(token, save_path=save)
        return F.format_file_downloaded(out if isinstance(out, str)
                                          else "(内存bytes,未保存)")
    return ("用法:\n"
            "  /文件 list\n"
            "  /文件 upload --path <本地路径>\n"
            "  /文件 download --token <token> --save <本地路径>")


def _permission_handler(app, cmd):
    from .permissions import check_all_permissions
    report = check_all_permissions()
    return F.format_permissions(report)


def _help_handler(app, cmd):
    return HELP_TEXT


# ======================================================================
# 时间区间解析辅助
# ======================================================================

import re as _re
_TR_RE = _re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")


def _parse_time_range(date_ts, expr):
    """date_ts 当日 + HH:MM-HH:MM → (start, end) Unix秒。"""
    m = _TR_RE.match(expr)
    if not m:
        raise CommandParseError(f"时间区间格式应为 HH:MM-HH:MM: {expr}")
    h1, m1, h2, m2 = (int(x) for x in m.groups())
    start = date_ts + h1 * 3600 + m1 * 60
    end = date_ts + h2 * 3600 + m2 * 60
    return start, end


# ======================================================================
# 注册入口
# ======================================================================

_DOMAIN_MAP = {
    "日历": _calendar_handler,
    "日程": _agenda_handler,
    "群聊": _chat_handler,
    "消息": _message_handler,
    "文档": _doc_handler,
    "文件": _file_handler,
    "权限": _permission_handler,
    "帮助": _help_handler,
    "help": _help_handler,
}


def build_router():
    """构建并返回配置好的 CommandRouter。"""
    router = CommandRouter()
    for domain, handler in _DOMAIN_MAP.items():
        router.register(domain, handler)
    return router


def register_all_commands(app):
    """为 app 注册命令路由。惰性、容错: 失败仅记录，不抛。"""
    try:
        app._feishu_router = build_router()
        app._feishu_domains = list(_DOMAIN_MAP.keys())
        return True
    except Exception as e:
        app._feishu_router = None
        app._feishu_init_error = str(e)
        return False


def dispatch_command(app, user_input):
    """解析并分发命令。返回 (handled, reply)。

    handled=True  表示是域命令，已处理;
    handled=False 表示非域命令，交由父类兜底。
    """
    router = getattr(app, "_feishu_router", None)
    if router is None:
        return False, None
    try:
        cmd = parse_command(user_input)
    except CommandParseError:
        return False, None   # 非域命令，交父类
    reply = router.dispatch(app, cmd)
    return True, reply
