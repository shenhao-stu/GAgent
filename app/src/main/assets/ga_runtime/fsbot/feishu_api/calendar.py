# -*- coding: utf-8 -*-
"""日历域 — 日历列表 / 日程查询 / 创建日程。"""

from ._base import FeishuApiBase, FeishuApiError


class CalendarAPI(FeishuApiBase):
    _domain_name = "calendar"
    _scopes = ["calendar:calendar", "calendar:calendar:readonly",
               "calendar:event"]   # 真实 scope 字符串

    # ------------------------------------------------------------------
    # 日历列表
    # ------------------------------------------------------------------

    def list_calendars(self):
        """列出我订阅的日历。

        实测结构: {calendar_list: [...], has_more, page_token, sync_token}
        注意: calendar_list 本身就是 list（非嵌套 items），
              且使用 sync_token 增量同步，不走 _paginate 的 page_token 逻辑。
        """
        result = self._call("GET", "/calendar/v4/calendars",
                            params={"page_size": 50})
        if not isinstance(result, dict):
            return []
        cal_list = result.get("calendar_list", [])
        return cal_list if isinstance(cal_list, list) else []

    def _probe_permission(self):
        """探测: 列日历。权限不足会返回 code=99991663。"""
        self.list_calendars()
        return None

    # ------------------------------------------------------------------
    # 日程查询
    # ------------------------------------------------------------------

    def get_agenda(self, start_ts, end_ts, calendar_id="primary",
                   page_size=50):
        """查询某日历在 [start_ts, end_ts) 内的日程。

        实测结构: /calendar/v4/calendars/{id}/events → {items:[...], page_token, has_more}
        """
        params = {
            "start_time": str(start_ts),
            "end_time": str(end_ts),
            "page_size": page_size,
        }
        return self._paginate(
            "GET", f"/calendar/v4/calendars/{calendar_id}/events",
            params=params, items_key="items")

    # ------------------------------------------------------------------
    # 创建日程
    # ------------------------------------------------------------------

    def create_event(self, calendar_id, summary, start_ts, end_ts,
                     description="", location_name="", attendees=None):
        """创建日程。

        attendees: list[str] 用户 open_id/邮箱；为空则只建自己的。
        """
        event = {
            "summary": summary,
            "description": description,
            "start_time": {"timestamp": str(start_ts)},
            "end_time": {"timestamp": str(end_ts)},
        }
        if location_name:
            event["location"] = {"name": location_name}
        if attendees:
            event["attendees"] = [{"type": "open_id", "open_id": a}
                                  if not a.startswith(("u:", "@"))
                                  else {"type": "user_id",
                                        "user_id": a.lstrip("u:")}
                                  for a in attendees]
        payload = event
        result = self._call(
            "POST", f"/calendar/v4/calendars/{calendar_id}/events",
            payload=payload)
        return result   # {event_id, ...}
