# -*- coding: utf-8 -*-
"""命令路由 — 解析 /域 动作 [--参数 值] 并分发到域 API。

命令格式示例:
  /日历 list                 列日历
  /日程 今日                  今日日程
  /日程 明天                  明日日程
  /日程 2026-07-14            指定日期日程
  /日程 明天 10:00-11:00 团队周会   创建日程
  /群聊 list                 列群聊
  /消息 --chat oc_xxx --kw 关键词   群内搜索
  /文档 list                 列文档
  /文件 list                 列文件
  /文件 upload --path /sdcard/x.txt
  /文件 download --token boxcnXXX --save /sdcard/y.txt
  /权限                      权限总览
"""

import re
import time
from datetime import datetime, timedelta

WEEK_OFFSET = 8 * 3600   # 东八区


class CommandParseError(Exception):
    """命令解析错误。"""


class Command:
    __slots__ = ("domain", "action", "args", "kwargs")

    def __init__(self, domain, action, args, kwargs):
        self.domain = domain      # 日历/日程/群聊/消息/文档/文件/权限
        self.action = action      # list/今日/明天/upload/...
        self.args = args          # 位置参数 list
        self.kwargs = kwargs      # 命名参数 dict

    def __repr__(self):
        return f"Command({self.domain}/{self.action} args={self.args} kw={self.kwargs})"


# ======================================================================
# 时间解析
# ======================================================================

_WEEKDAY_MAP = {
    "周一": 0, "周二": 1, "周三": 2, "周四": 3,
    "周五": 4, "周六": 5, "周日": 6,
    "星期一": 0, "星期二": 1, "星期三": 2, "星期四": 3,
    "星期五": 4, "星期六": 5, "星期日": 6, "星期天": 6,
    "周天": 6,
}

_RELATIVE_DAY_MAP = {
    "今天": 0, "今日": 0, "today": 0,
    "明天": 1, "明日": 1, "tomorrow": 1,
    "后天": 2,
    "昨天": -1, "昨日": -1, "yesterday": -1,
    "前天": -2,
}

_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_TIME_RANGE_RE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")
_WEEKDAY_RE = re.compile(
    r"^([上下本])?(周[一二三四五六日天]|星期[一二三四五六日天])$")


def _today_start_utc8():
    """今日0点(东八区)的Unix秒。"""
    now = int(time.time())
    return now - (now % 86400) - WEEK_OFFSET


def parse_date(expr):
    """解析日期 → 当日0点(东八区)Unix秒。支持相对日/星期/绝对日期。"""
    expr = (expr or "").strip()
    if not expr:
        raise CommandParseError("空日期表达式")

    # 绝对日期 YYYY-MM-DD (设备时区=CST UTC+8, naive datetime 按 CST 解析)
    m = _DATE_RE.match(expr)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return int(datetime(y, mo, d).timestamp())   # 当日0点CST

    # 相对日 (今天/明天/昨天...)
    if expr in _RELATIVE_DAY_MAP:
        return _today_start_utc8() + _RELATIVE_DAY_MAP[expr] * 86400

    # 星期 (上/下/本周+周X)
    m = _WEEKDAY_RE.match(expr)
    if m:
        prefix, wd = m.group(1), m.group(2)
        target = _WEEKDAY_MAP[wd]
        today = _today_start_utc8()
        today_wd = datetime.fromtimestamp(today + WEEK_OFFSET).weekday()
        delta = target - today_wd
        if prefix == "上":
            if delta >= 0:
                delta -= 7
        elif prefix == "下":
            if delta <= 0:
                delta += 7
        # 无前缀或"本": 本周(可能已过，取本周该日)
        return today + delta * 86400

    raise CommandParseError(f"无法解析日期: {expr}")


def parse_time_of_day(date_start_ts, hhmm):
    """在 date_start_ts 当日上叠加 HH:MM → Unix秒。"""
    m = _TIME_RE.match(hhmm or "")
    if not m:
        raise CommandParseError(f"时间格式应为 HH:MM: {hhmm}")
    return date_start_ts + int(m.group(1)) * 3600 + int(m.group(2)) * 60


def parse_date_or_range(expr):
    """解析日期表达式 → (start_ts, end_ts) 区间。

    支持: 今日/明天/周X (整天) / YYYY-MM-DD
    """
    start = parse_date(expr)
    end = start + 86400
    return start, end


# ======================================================================
# 命令解析
# ======================================================================

_KW_ARG_RE = re.compile(r"^--([a-zA-Z][\w-]*)$")


def parse_command(user_input):
    """解析用户输入 → Command。

    格式: /域 动作 [位置参数...] [--key value ...]
    纯 / 或不带域 → 抛 CommandParseError(交由父类兜底)
    """
    text = (user_input or "").strip()
    if not text.startswith("/"):
        raise CommandParseError("非域命令(无/前缀)")
    body = text[1:].strip()
    if not body:
        raise CommandParseError("空命令")

    tokens = _tokenize(body)
    domain = tokens[0]
    if not domain:
        raise CommandParseError("缺少域")

    # 解析动作 + 位置参数 + 命名参数
    action = tokens[1] if len(tokens) > 1 else ""
    args = []
    kwargs = {}
    i = 2
    while i < len(tokens):
        tok = tokens[i]
        m = _KW_ARG_RE.match(tok)
        if m:   # --key value
            key = m.group(1)
            if i + 1 >= len(tokens):
                raise CommandParseError(f"参数 --{key} 缺少值")
            kwargs[key] = _sanitize_value(tokens[i + 1])
            i += 2
        else:
            args.append(tok)
            i += 1

    return Command(domain, action, args, kwargs)


def _tokenize(s):
    """简单分词: 双引号支持空格。"""
    tokens = []
    cur = []
    in_quote = False
    for ch in s:
        if ch == '"':
            in_quote = not in_quote
        elif ch == " " and not in_quote:
            if cur:
                tokens.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        tokens.append("".join(cur))
    return tokens


def _sanitize_value(v):
    """清洗命名参数值: strip 空白; 剥离包裹的尖括号/引号。

    HELP_TEXT 占位符写作 <token>, 用户照抄会把尖括号一起传入,
    导致飞书 API 路径含 <...> → invalid param。此处兜底剥离
    成对的 < > 或 ' 或 ", 使照抄占位符也能正常工作。
    飞书 token/id/路径类参数均不含这些字符, 剥离安全。
    """
    if not isinstance(v, str):
        return v
    v = v.strip()
    if len(v) >= 2 and v[0] == "<" and v[-1] == ">":
        v = v[1:-1].strip()
    elif len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        v = v[1:-1].strip()
    return v


# ======================================================================
# 路由分发
# ======================================================================

class CommandRouter:
    """命令路由器: 持有域处理器，分发命令。"""

    def __init__(self):
        self._handlers = {}   # domain -> callable(app, command) -> str

    def register(self, domain, handler):
        self._handlers[domain] = handler

    def dispatch(self, app, command):
        """分发命令，返回回复文本。"""
        handler = self._handlers.get(command.domain)
        if handler is None:
            available = "、".join(self._handlers.keys()) or "(无)"
            return f"未知域「{command.domain}」。可用: {available}\n输入 /帮助 查看完整说明。"
        try:
            return handler(app, command)
        except CommandParseError as e:
            return f"❌ 参数错误: {e}\n输入 /帮助 查看用法。"
        except Exception as e:
            return f"❌ 执行失败: {e}"

    @property
    def domains(self):
        return list(self._handlers.keys())
