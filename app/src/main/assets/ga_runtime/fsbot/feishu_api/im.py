# -*- coding: utf-8 -*-
"""即时通讯域 — 群聊列表 / 群消息 / 群内搜索 / 发消息。"""

import json
from ._base import FeishuApiBase, FeishuApiError


class InstantMessagingAPI(FeishuApiBase):
    _domain_name = "im"
    _scopes = ["im:chat", "im:chat:readonly", "im:message",
               "im:message:send_as_bot", "im:resource"]

    # ------------------------------------------------------------------
    # 群聊列表
    # ------------------------------------------------------------------

    def list_chats(self, page_size=50):
        """列出机器人所在的群聊。

        实测结构: {items:[...], page_token, has_more}
        """
        return self._paginate("GET", "/im/v1/chats",
                              params={"page_size": page_size},
                              items_key="items")

    def _probe_permission(self):
        """探测: 列群聊。"""
        self.list_chats()
        return None

    # ------------------------------------------------------------------
    # 群消息
    # ------------------------------------------------------------------

    def get_messages(self, container_id, container_id_type="chat",
                     page_size=50):
        """获取指定会话的消息列表。

        container_id: 群 chat_id 或用户 open_id（需 as_user=True）
        """
        params = {
            "container_id": container_id,
            "container_id_type": container_id_type,
            "page_size": page_size,
        }
        return self._paginate("GET", "/im/v1/messages",
                              params=params, items_key="items")

    def search_in_chat(self, chat_id, keyword, page_size=50, max_msgs=200):
        """在指定群聊内按关键词过滤消息（客户端过滤）。

        飞书 bot 无全局消息搜索 API，故对群内消息做关键词子串匹配。
        返回匹配项 list。
        """
        msgs = self.get_messages(chat_id, page_size=page_size)
        # get_messages 已分页（默认最多 max_pages*page_size），客户端再过滤
        kw = (keyword or "").lower()
        matched = []
        for m in msgs:
            content = self._extract_text(m)
            if kw and kw in (content or "").lower():
                matched.append(m)
        return matched

    @staticmethod
    def _extract_text(message):
        """从消息体提取纯文本（容错）。"""
        try:
            body = message.get("body", {}) if isinstance(message, dict) else {}
            content_str = body.get("content", "{}") if isinstance(body, dict) else "{}"
            content = json.loads(content_str) if isinstance(content_str, str) else content_str
            if isinstance(content, dict):
                text = content.get("text")
                if text:
                    return text
                # 富文本/其他结构尝试取 title
                title = content.get("title")
                if isinstance(title, dict):
                    return title.get("content", "")
                return json.dumps(content, ensure_ascii=False)
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------------
    # 发消息
    # ------------------------------------------------------------------

    def send_text(self, receive_id, text, receive_id_type="chat_id"):
        """发送文本消息到群/用户。"""
        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        }
        return self._call("POST", "/im/v1/messages",
                          params={"receive_id_type": receive_id_type},
                          payload=payload)
