"""JarvisInterface — unified outbound communication for Hermes OS.

Sends Feishu cards + natural language messages + saves to user file directory.
All outbound communication for a user goes through this interface to ensure:
1. Feishu card/text is always sent
2. Card payload is always saved to user's file directory
3. Natural language summary is always recorded

Usage:
    jarvis = JarvisInterface()
    await jarvis.send_card_with_nl(user_id, title, content, actions, nl_summary, task_id)
    await jarvis.send_progress_update(user_id, task_title, progress)
    await jarvis.send_confirmation_request(user_id, question, task_id, accept_action, decline_action)
"""

from __future__ import annotations

import logging
from typing import Any

from hermes_os.feishu_enhancer import FeishuEnhancer
from hermes_os.user_file_manager import UserFileManager

logger = logging.getLogger(__name__)


class JarvisInterface:
    """
    Unified outbound communication interface.

    Wraps FeishuEnhancer and UserFileManager to ensure every outbound
    message is both sent AND persisted to the user's file directory.
    """

    def __init__(
        self,
        feishu_enhancer: FeishuEnhancer | None = None,
        file_manager: UserFileManager | None = None,
    ) -> None:
        self._feishu = feishu_enhancer or FeishuEnhancer()
        self._files = file_manager or UserFileManager()

    # -------------------------------------------------------------------------
    # Core send methods
    # -------------------------------------------------------------------------

    async def send_card_with_nl(
        self,
        user_id: str,
        title: str,
        content: str,
        actions: list[dict[str, Any]],
        nl_summary: str,
        task_id: str | None = None,
    ) -> None:
        """
        Send a Feishu card AND save to user file directory.

        Args:
            user_id: Feishu open_id
            title: Card header title
            content: Card body text (markdown)
            actions: List of button descriptors [{text, value, type, task_id}]
            nl_summary: Natural language summary for file storage
            task_id: Optional task ID for file path organization
        """
        card_payload = self._build_card(title, content, actions)

        # Send via Feishu
        try:
            await self._feishu.send_action_card(
                user_id=user_id,
                title=title,
                content=content,
                actions=actions,
            )
        except Exception as e:
            logger.warning("Feishu card send failed for user %s: %s", user_id, e)

        # Always persist to user file directory
        if task_id:
            await self._files.save_card(
                user_id=user_id,
                task_id=task_id,
                card_payload=card_payload,
                nl_summary=nl_summary,
            )

        logger.info(
            "Jarvis card sent + saved: user=%s task=%s title=%s",
            user_id,
            task_id,
            title,
        )

    async def send_progress_update(
        self,
        user_id: str,
        task_title: str,
        progress: float,
        detail: str | None = None,
        task_id: str | None = None,
    ) -> None:
        """
        Send a task progress update as natural language + file save.

        Args:
            user_id: Feishu open_id
            task_title: Name of the task
            progress: 0.0 to 1.0
            detail: Optional additional context
            task_id: Optional for file storage
        """
        pct = int(progress * 100)
        nl = f"📋 [{pct}%] {task_title}"
        if detail:
            nl += f"\n{detail}"

        try:
            await self._feishu.send_message_to_user(user_id=user_id, message=nl)
        except Exception as e:
            logger.warning("Feishu progress send failed for user %s: %s", user_id, e)

        if task_id:
            await self._files.save_card(
                user_id=user_id,
                task_id=task_id,
                card_payload={"type": "progress_update", "progress": progress, "detail": detail},
                nl_summary=nl,
            )

    async def send_confirmation_request(
        self,
        user_id: str,
        question: str,
        task_id: str,
        accept_text: str = "立即执行",
        decline_text: str = "拦截任务",
        metadata: dict | None = None,
    ) -> None:
        """
        Send a confirmation card with Accept/Decline buttons.

        This is the event-driven replacement for the old 30s polling loop.
        The card is saved, and ConversationStateManager handles the wait via events.

        Args:
            user_id: Feishu open_id
            question: What to ask the user
            task_id: Task being confirmed
            accept_text: Button text for accept
            decline_text: Button text for decline
            metadata: Additional context for the confirmation
        """
        actions = [
            {"text": accept_text, "value": "run_now", "type": "primary", "task_id": task_id},
            {"text": decline_text, "value": "stop_task", "type": "danger", "task_id": task_id},
        ]

        content = f"**任务**: {question}\n\n请确认是否继续执行。"
        nl_summary = f"确认请求: {question}"

        card_payload = self._build_card(
            title=f"🤖 Jarvis: 意图确认 - {task_id[:8]}...",
            content=content,
            actions=actions,
        )

        # Send via Feishu
        try:
            await self._feishu.send_action_card(
                user_id=user_id,
                title=f"🤖 Jarvis: 意图确认 - {task_id[:8]}...",
                content=content,
                actions=actions,
            )
        except Exception as e:
            logger.warning("Feishu confirmation card failed for user %s: %s", user_id, e)

        # Persist
        await self._files.save_card(
            user_id=user_id,
            task_id=task_id,
            card_payload=card_payload,
            nl_summary=nl_summary,
        )

        logger.info(
            "Jarvis confirmation request sent: user=%s task=%s",
            user_id,
            task_id,
        )

    async def send_completion_notification(
        self,
        user_id: str,
        task_title: str,
        result_summary: str,
        task_id: str | None = None,
    ) -> None:
        """
        Send task completion notification.

        Args:
            user_id: Feishu open_id
            task_title: Name of completed task
            result_summary: Brief result description
            task_id: For file storage
        """
        nl = f"✅ 任务完成: {task_title}\n\n{result_summary}"

        try:
            await self._feishu.send_message_to_user(user_id=user_id, message=nl)
        except Exception as e:
            logger.warning("Feishu completion send failed for user %s: %s", user_id, e)

        if task_id:
            await self._files.save_card(
                user_id=user_id,
                task_id=task_id,
                card_payload={"type": "completion", "result": result_summary},
                nl_summary=nl,
            )

    async def send_failure_notification(
        self,
        user_id: str,
        task_title: str,
        error_summary: str,
        task_id: str | None = None,
    ) -> None:
        """
        Send task failure notification.

        Args:
            user_id: Feishu open_id
            task_title: Name of failed task
            error_summary: Error description
            task_id: For file storage
        """
        nl = f"❌ 任务失败: {task_title}\n\n错误: {error_summary}"

        try:
            await self._feishu.send_message_to_user(user_id=user_id, message=nl)
        except Exception as e:
            logger.warning("Feishu failure send failed for user %s: %s", user_id, e)

        if task_id:
            await self._files.save_card(
                user_id=user_id,
                task_id=task_id,
                card_payload={"type": "failure", "error": error_summary},
                nl_summary=nl,
            )

    # -------------------------------------------------------------------------
    # Card builder
    # -------------------------------------------------------------------------

    def _build_card(
        self,
        title: str,
        content: str,
        actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build a Feishu card payload dict."""
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": content},
                },
                {"tag": "action", "actions": []},
            ],
        }

        for action in actions:
            btn_value = {
                "hermes_action": action.get("value", ""),
                "task_id": action.get("task_id", "unknown"),
            }
            card["elements"][1]["actions"].append(
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": action.get("text", "")},
                    "type": action.get("type", "default"),
                    "value": btn_value,
                }
            )

        return card