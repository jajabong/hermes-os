"""NotificationManager — JARVIS 风格的通知系统.

替代 TaskScheduler 中的空 stub `_send_notification`，
实现真正的生命周期通知 + Heads-up 预警。

核心功能：
1. 生命周期事件：STARTED → RUNNING → COMPLETED/FAILED
2. 三段式卡片：使用 ConclusionExtractor 萃取结论
3. Heads-up 预警：长时间任务超过预估 50% 时主动告知
4. Goal 语境注入：每次通知附带当前目标上下文
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from hermes_os.conclusion_extractor import (
    ConclusionExtractor,
    ConclusionCard,
    ConclusionLevel,
    ConclusionLevel as Level,
)

logger = logging.getLogger(__name__)


class NotificationEvent(str, Enum):
    """通知事件类型，对应不同的图标和卡片模板。"""
    STARTED = "started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WARNING = "warning"

    @property
    def icon(self) -> str:
        return {
            NotificationEvent.STARTED: "🔄",
            NotificationEvent.RUNNING: "🔄",
            NotificationEvent.COMPLETED: "✅",
            NotificationEvent.FAILED: "❌",
            NotificationEvent.WARNING: "⚠️",
        }[self]

    @property
    def level(self) -> ConclusionLevel:
        return {
            NotificationEvent.STARTED: Level.RUNNING,
            NotificationEvent.RUNNING: Level.RUNNING,
            NotificationEvent.COMPLETED: Level.SUCCESS,
            NotificationEvent.FAILED: Level.FAILURE,
            NotificationEvent.WARNING: Level.WARNING,
        }[self]

    @property
    def template_color(self) -> str:
        return self.level.template


@dataclass
class SendThresholds:
    """Heads-up 发送阈值配置。"""
    heads_up_progress_threshold: float = 0.5  # 超过预估时间 50% 时触发
    min_elapsed_seconds: int = 60              # 至少运行 60 秒才发 heads-up
    warning_progress_threshold: float = 0.8   # 超过 80% 时发送警告


_SEND_THRESHOLDS = SendThresholds()


class NotificationManager:
    """
    JARVIS 风格通知管理器。

    使用 ConclusionExtractor 将原始输出转换为三段式卡片，
    并在关键生命周期节点主动发送 Heads-up 通知。

    使用方式:
        nm = NotificationManager()
        await nm.send_notification(
            user_id="alice",
            task_title="部署服务",
            task_id="t123",
            event=NotificationEvent.COMPLETED,
            result="Deployment successful",
            goal_context="完成供应商对比 (Phase 2/5)",
        )
    """

    def __init__(
        self,
        jarvis: Any = None,
        extractor: ConclusionExtractor | None = None,
    ) -> None:
        self._jarvis = jarvis
        self._extractor = extractor or ConclusionExtractor()

    async def send_notification(
        self,
        user_id: str,
        task_title: str,
        task_id: str,
        event: NotificationEvent,
        result: str = "",
        error: str = "",
        goal_context: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        发送 JARVIS 风格的三段式通知卡片。

        Args:
            user_id: 飞书用户 open_id
            task_title: 任务名称
            task_id: 任务 ID
            event: 事件类型 (STARTED/RUNNING/COMPLETED/FAILED/WARNING)
            result: 任务输出（用于萃取结论）
            error: 错误信息（失败时）
            goal_context: 当前目标语境
            metadata: 额外元数据（如 progress, elapsed 等）
        """
        if self._jarvis is None:
            logger.debug("send_notification: no jarvis configured, skipping")
            return

        # Input validation
        if not user_id or not task_id or not task_title:
            logger.warning("send_notification: missing required parameter")
            return

        # Build conclusion card
        if event == NotificationEvent.FAILED:
            raw = error or "任务执行失败"
            status = "failed"
        elif event == NotificationEvent.COMPLETED:
            raw = result or "任务完成"
            status = "completed"
        elif event == NotificationEvent.WARNING:
            raw = result or "任务存在警告"
            status = "completed"
        elif event == NotificationEvent.STARTED:
            raw = result or f"开始执行: {task_title}"
            status = "running"
        else:
            raw = result or "任务进行中"
            status = "running"

        card = self._extractor.extract_summary(
            raw_output=raw,
            task_title=task_title,
            task_id=task_id,
            status=status,
            goal_context=goal_context,
        )

        # Override level based on event
        card.level = event.level

        # Build title
        title = f"{event.icon} {task_title}"

        # Build content from card markdown
        content = card.to_markdown()

        # Add progress info if available
        if metadata:
            progress = metadata.get("progress")
            if progress is not None:
                pct = int(progress * 100)
                content += f"\n\n📊 进度: {pct}%"

        try:
            await self._jarvis.send_card_with_nl(
                user_id=user_id,
                title=title,
                content=content,
                actions=[],
                nl_summary=f"{event.icon} {task_title}: {card.conclusion}",
                task_id=task_id,
            )
            logger.info(
                "NotificationManager: sent %s notification for task=%s user=%s",
                event.value,
                task_id,
                user_id,
            )
        except (AttributeError, RuntimeError, OSError, TimeoutError) as e:
            logger.warning("Failed to send notification to user %s: %s", user_id, str(e)[:100])

    async def send_heads_up(
        self,
        user_id: str,
        task_title: str,
        task_id: str,
        progress: float,
        elapsed_seconds: int,
        estimated_total: int,
        goal_context: str | None = None,
    ) -> None:
        """
        发送 Heads-up 通知：当任务运行超过预估时间 50% 时主动告知。

        Args:
            user_id: 用户 ID
            task_title: 任务名称
            task_id: 任务 ID
            progress: 当前进度 (0.0-1.0)
            elapsed_seconds: 已运行时间（秒）
            estimated_total: 预估总时间（秒）
            goal_context: 当前目标语境
        """
        # Input validation
        if not user_id or not task_id or not task_title:
            logger.warning("send_heads_up: missing required parameter")
            return

        # Check thresholds
        if elapsed_seconds < _SEND_THRESHOLDS.min_elapsed_seconds:
            return

        if progress < _SEND_THRESHOLDS.heads_up_progress_threshold:
            return

        if self._jarvis is None:
            return

        # Build heads-up message
        pct = int(progress * 100)
        elapsed_min = elapsed_seconds // 60

        content = (
            f"🔄 **{task_title}** 进行中...\n\n"
            f"📊 当前进度: **{pct}%**\n"
            f"⏱️ 已运行: **{elapsed_min}分钟**\n\n"
            f"正在处理中，请放心，我会持续跟进。"
        )

        if goal_context:
            content += f"\n\n🎯 目标: {goal_context}"

        try:
            await self._jarvis.send_card_with_nl(
                user_id=user_id,
                title=f"🔄 {task_title} — 进度更新",
                content=content,
                actions=[],
                nl_summary=f"进度更新: {task_title} {pct}%",
                task_id=task_id,
            )
            logger.info(
                "NotificationManager: heads-up sent for task=%s progress=%d%%",
                task_id,
                pct,
            )
        except (AttributeError, RuntimeError, OSError, TimeoutError) as e:
            logger.warning("Failed to send heads-up to user %s: %s", user_id, str(e)[:100])

    async def send_running_update(
        self,
        user_id: str,
        task_title: str,
        task_id: str,
        step: str,
        goal_context: str | None = None,
    ) -> None:
        """
        发送运行中更新（如任务已开始处理某个步骤）。

        Args:
            user_id: 用户 ID
            task_title: 任务名称
            task_id: 任务 ID
            step: 当前步骤描述
            goal_context: 当前目标语境
        """
        # Input validation
        if not user_id or not task_id or not task_title:
            logger.warning("send_running_update: missing required parameter")
            return

        if self._jarvis is None:
            return

        content = f"🔄 **{task_title}**\n\n📋 当前: {step}"
        if goal_context:
            content += f"\n\n🎯 目标: {goal_context}"

        try:
            await self._jarvis.send_card_with_nl(
                user_id=user_id,
                title=f"🔄 {task_title} — 开始执行",
                content=content,
                actions=[],
                nl_summary=f"开始: {task_title} — {step}",
                task_id=task_id,
            )
        except (AttributeError, RuntimeError, OSError, TimeoutError) as e:
            logger.warning("Failed to send running update to user %s: %s", user_id, str(e)[:100])