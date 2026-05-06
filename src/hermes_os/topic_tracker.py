"""TopicTracker — cross-session memory continuity for Hermes OS.

Phase 1: 千人千面管家
P0: 记忆粘性 — 「接着上次那件事继续」无缝续接

核心职责：
1. 记录用户当前话题（last_topic + last_task_id）
2. 当用户说「接着/继续」时，检测并续接
3. 提供 get_current_topic() / resume_from_topic() 接口

存储位置：~/.hermes/users/{user_id}/brain/LAST_TOPIC.md

Architecture:
    UnifiedRouter.route()
        ↓
    TopicTracker.record_topic(topic, task_id, intent)  # 每次开始新任务时
        ↓
    LAST_TOPIC.md (brain/ 目录)
        ↓
    TopicTracker.get_current_topic() / resume_from_topic()  # 下次对话时
        ↓
    检测「接着」意图 → 续接对应任务/话题
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TopicContext:
    """当前话题上下文 — 用于续接「上次那件事」。"""

    topic: str  # 话题描述
    task_id: str  # 关联的任务 ID
    intent: str  # 意图类型
    recorded_at: str  # ISO 时间戳
    is_incomplete: bool = True  # 是否未完成（默认 True）

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TopicContext:
        return cls(
            topic=data.get("topic", ""),
            task_id=data.get("task_id", ""),
            intent=data.get("intent", "unknown"),
            recorded_at=data.get("recorded_at", ""),
            is_incomplete=data.get("is_incomplete", True),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "task_id": self.task_id,
            "intent": self.intent,
            "recorded_at": self.recorded_at,
            "is_incomplete": self.is_incomplete,
        }


# ---------------------------------------------------------------------------
# TopicTracker
# ---------------------------------------------------------------------------


class TopicTracker:
    """跨 Session 话题跟踪器。

    在 brain/LAST_TOPIC.md 中持久化用户当前进行中的任务。
    当用户说「接着上次」时，系统能查询并续接。

    Example:
        tracker = TopicTracker(user_id="lu_zong")
        await tracker.record_topic("投资组合分析", "task_123", "investment")
        # ...
        # Next session, user says "接着上次继续"
        context = await tracker.get_current_topic()
        if context:
            # 续接 task_123
    """

    # 检测「继续/接着」意图的关键词
    CONTINUATION_PATTERNS = (
        "接着",
        "继续",
        "然后",
        "然后呢",
        "继续上",
        "接上",
        "上次的",
        "继续做",
        "接着做",
    )

    def __init__(self, user_id: str, base_path: Path | None = None) -> None:
        self.user_id = user_id
        self.base_path = base_path or (Path.home() / ".hermes" / "users")

    def _brain_path(self) -> Path:
        return self.base_path / self.user_id / "brain"

    def _last_topic_path(self) -> Path:
        return self._brain_path() / "LAST_TOPIC.md"

    async def _read_topic_file(self) -> dict[str, Any] | None:
        """读取 LAST_TOPIC.md，返回 None 如果不存在。"""
        path = self._last_topic_path()
        if not path.exists():
            return None
        try:
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                return None
            return json.loads(content)
        except (json.JSONDecodeError, OSError):
            return None

    async def _write_topic_file(self, data: dict[str, Any]) -> None:
        """写入 LAST_TOPIC.md。"""
        brain_dir = self._brain_path()
        brain_dir.mkdir(parents=True, exist_ok=True)
        path = self._last_topic_path()
        content = json.dumps(data, ensure_ascii=False, indent=2)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: path.write_text(content, encoding="utf-8"))

    async def record_topic(
        self,
        topic: str,
        task_id: str,
        intent: str = "unknown",
    ) -> None:
        """记录当前话题（每次开始新任务时调用）。

        会覆盖之前的话题（因为用户在做新任务）。
        """
        data = {
            "topic": topic,
            "task_id": task_id,
            "intent": intent,
            "recorded_at": datetime.now(UTC).isoformat(),
            "is_incomplete": True,
        }
        await self._write_topic_file(data)

    async def complete_topic(self, task_id: str) -> None:
        """标记话题为已完成（任务完成时调用）。

        Args:
            task_id: 要标记完成的任务 ID（必须是当前 topic 的 task_id）
        """
        data = await self._read_topic_file()
        if data is None:
            return
        if data.get("task_id") != task_id:
            return  # 不是当前话题，不处理
        data["is_incomplete"] = False
        await self._write_topic_file(data)

    async def get_current_topic(self) -> TopicContext | None:
        """获取当前未完成的话题上下文。

        Returns:
            TopicContext 如果有未完成的话题，None 如果没有。
        """
        data = await self._read_topic_file()
        if data is None:
            return None
        ctx = TopicContext.from_dict(data)
        # 只有未完成的话题才返回
        if ctx.is_incomplete:
            return ctx
        return None

    async def resume_from_topic(self) -> TopicContext | None:
        """获取可续接的话题上下文。

        等同于 get_current_topic()，语义上表示「可以从这里继续」。
        """
        return await self.get_current_topic()

    async def get_topic_summary(self) -> str | None:
        """获取话题的人类可读摘要（用于「接着上次」检测后展示给用户）。

        Returns:
            形如「上次您在做：投资组合分析（进行中）」的字符串，
            None 如果没有话题。
        """
        ctx = await self.get_current_topic()
        if ctx is None:
            return None
        return f"上次您在做：{ctx.topic}（进行中）"

    def detect_continuation(self, message: str) -> bool:
        """检测消息是否表示「继续上次的任务」。

        Args:
            message: 用户发送的消息

        Returns:
            True 如果消息表达了继续/接着意图，且有未完成的话题。
        """
        msg_lower = message.lower()

        # 先检查是否有继续关键词
        has_continuation = any(kw in msg_lower for kw in self.CONTINUATION_PATTERNS)
        if not has_continuation:
            return False

        # 再检查是否有对应的话题可以续接（同步检查，无需 await）
        # 这里只做消息层面的检测，实际续接需要 await get_current_topic()
        return True

    async def detect_and_resume(self, message: str) -> tuple[bool, TopicContext | None]:
        """检测「继续」意图并返回可续接的话题。

        这是主要的入口方法，同时检查消息意图和是否有话题可续接。

        Args:
            message: 用户发送的消息

        Returns:
            (should_resume, topic_context) 元组。
            - should_resume: True 如果应该续接
            - topic_context: 可续接的话题上下文（如果没有则为 None）
        """
        # 先检查消息是否表达继续意图
        if not self._has_continuation_signal(message):
            return False, None

        # 再检查是否有话题可以续接
        ctx = await self.get_current_topic()
        if ctx is None:
            return False, None

        return True, ctx

    def _has_continuation_signal(self, message: str) -> bool:
        """检查消息是否包含继续/接着意图关键词（同步）。"""
        msg_lower = message.lower()
        return any(kw in msg_lower for kw in self.CONTINUATION_PATTERNS)
