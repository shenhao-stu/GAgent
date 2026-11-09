"""Common mixin & utilities for GA chat frontends (Feishu, etc.)."""

import asyncio
import traceback

FILE_HINT = "\ud83d\udcce"  # 📎


def split_text(text, max_length=4000):
    """Split text into chunks not exceeding max_length characters."""
    if not text:
        return [""]
    if len(text) <= max_length:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        # Try to split at newline
        split_at = text.rfind("\n", 0, max_length)
        if split_at <= 0:
            split_at = max_length
        chunks.append(text[:split_at])
        text = text[split_at:]
    return chunks


class AgentChatMixin:
    """Mixin for chat frontends that need agent interaction.

    Subclasses must define:
      - label: str
      - source: str
      - split_limit: int
      - send_text(chat_id, content, *, receive_id, receive_id_type)
      - send_done(chat_id, raw_text, *, receive_id, receive_id_type)
      - run_agent(chat_id, text, *, receive_id, receive_id_type, images)

    This mixin provides:
      - __init__(self, agent, user_tasks)
      - handle_command(chat_key, user_input, *, receive_id, receive_id_type)
    """

    def __init__(self, agent, user_tasks):
        self.agent = agent
        self.user_tasks = user_tasks
        self._command_handlers = {
            "/help": self._cmd_help,
            "/stop": self._cmd_stop,
            "/status": self._cmd_status,
            "/clear": self._cmd_clear,
        }

    async def handle_command(self, chat_key, user_input, *, receive_id, receive_id_type):
        """Handle a command message (starting with /)."""
        cmd = (user_input or "").strip().split()[0].lower()
        handler = self._command_handlers.get(cmd)
        if handler:
            try:
                await handler(chat_key, user_input, receive_id=receive_id, receive_id_type=receive_id_type)
            except Exception as e:
                await self.send_text(chat_key, f"命令执行出错: {e}", receive_id=receive_id, receive_id_type=receive_id_type)
        else:
            await self.send_text(
                chat_key,
                f"未知命令 {cmd}\n\n支持的命令:\n"
                f"  /help - 帮助信息\n"
                f"  /stop - 停止当前任务\n"
                f"  /status - 查看任务状态\n"
                f"  /clear - 清除对话历史\n"
                f"  直接发送消息即可与 AI 对话",
                receive_id=receive_id,
                receive_id_type=receive_id_type,
            )

    async def _cmd_help(self, chat_key, user_input, *, receive_id, receive_id_type):
        await self.send_text(
            chat_key,
            f"🤖 **GA 飞书机器人**\n\n"
            f"支持:\n"
            f"- 文字对话: 直接发送消息\n"
            f"- 图片分析: 发送图片\n"
            f"- 文件处理: 发送文件\n"
            f"- 命令: /stop, /clear, /status, /help\n\n"
            f"群聊中请 @我 后发言",
            receive_id=receive_id,
            receive_id_type=receive_id_type,
        )

    async def _cmd_stop(self, chat_key, user_input, *, receive_id, receive_id_type):
        state = self.user_tasks.get(chat_key)
        if state and state.get("running"):
            state["running"] = False
            await self.send_text(chat_key, "⏹ 正在停止任务...", receive_id=receive_id, receive_id_type=receive_id_type)
        else:
            await self.send_text(chat_key, "当前没有运行中的任务。", receive_id=receive_id, receive_id_type=receive_id_type)

    async def _cmd_status(self, chat_key, user_input, *, receive_id, receive_id_type):
        state = self.user_tasks.get(chat_key)
        if state and state.get("running"):
            await self.send_text(chat_key, "⏳ 当前有任务正在运行中。", receive_id=receive_id, receive_id_type=receive_id_type)
        else:
            await self.send_text(chat_key, "✅ 当前空闲，等待您的消息。", receive_id=receive_id, receive_id_type=receive_id_type)

    async def _cmd_clear(self, chat_key, user_input, *, receive_id, receive_id_type):
        try:
            if hasattr(self.agent, "clear_history"):
                self.agent.clear_history(chat_key) if callable(self.agent.clear_history) else None
            await self.send_text(chat_key, "🗑 对话历史已清除。", receive_id=receive_id, receive_id_type=receive_id_type)
        except Exception as e:
            await self.send_text(chat_key, f"清除失败: {e}", receive_id=receive_id, receive_id_type=receive_id_type)
