"""Conversation State Manager — tracks per-user dialogue context and decision points.

Replaces the old 30s polling loop with explicit state transitions:
- IDLE: no active task
- IN_PROGRESS: task running
- AWAITING_CONFIRMATION: waiting for user approval (replaces polling loop)
- COMPLETED: task done, cleaning up

Used by task_scheduler to wait for user input via events instead of sleep().
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from hermes_os.event_loop import Event, EventType, get_event_bus
from hermes_os.storage import Storage

logger = logging.getLogger(__name__)


class ConversationState(str, Enum):
    """Possible states for a user's conversation context."""

    IDLE = "IDLE"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    COMPLETED = "COMPLETED"


@dataclass
class UserConversationState:
    """Full state snapshot for a user's conversation."""

    user_id: str
    state: ConversationState
    current_task_id: str | None = None
    pending_decision: str | None = None
    multi_step_progress: float = 0.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "state": self.state.value,
            "current_task_id": self.current_task_id,
            "pending_decision": self.pending_decision,
            "multi_step_progress": self.multi_step_progress,
            "last_updated": self.last_updated.isoformat(),
            "metadata": self.metadata,
        }


class ConversationStateManager:
    """
    Manages per-user conversation state with SQLite persistence.

    Provides event-driven state transitions instead of 30s polling loops.
    When a user enters AWAITING_CONFIRMATION, the event loop handles
    the wait via TASK_CONFIRM event instead of asyncio.sleep().
    """

    def __init__(self, storage: Storage | None = None) -> None:
        self._storage = storage or Storage()
        self._memory: dict[str, UserConversationState] = {}
        self._lock = asyncio.Lock()
        self._event_bus = get_event_bus()

    async def initialize(self) -> None:
        await self._storage.initialize()

    async def get_state(self, user_id: str) -> UserConversationState:
        """Get current state for user, creating IDLE if none exists."""
        async with self._lock:
            if user_id in self._memory:
                return self._memory[user_id]

            row = await self._storage.get_conversation_state(user_id)
            if row:
                state = ConversationState(row["state"])
                metadata = json.loads(row["metadata"]) if row["metadata"] else {}
                conv = UserConversationState(
                    user_id=user_id,
                    state=state,
                    current_task_id=row["current_task_id"],
                    pending_decision=row["pending_decision"],
                    multi_step_progress=row["multi_step_progress"] or 0.0,
                    metadata=metadata,
                )
            else:
                conv = UserConversationState(user_id=user_id, state=ConversationState.IDLE)

            self._memory[user_id] = conv
            return conv

    async def set_state(
        self,
        user_id: str,
        state: ConversationState,
        current_task_id: str | None = None,
        pending_decision: str | None = None,
        multi_step_progress: float = 0.0,
        metadata: dict | None = None,
    ) -> UserConversationState:
        """Update user state and persist to DB."""
        async with self._lock:
            conv = UserConversationState(
                user_id=user_id,
                state=state,
                current_task_id=current_task_id,
                pending_decision=pending_decision,
                multi_step_progress=multi_step_progress,
                last_updated=datetime.now(UTC),
                metadata=metadata or {},
            )
            self._memory[user_id] = conv

            await self._storage.save_conversation_state(
                user_id=user_id,
                state=state.value,
                current_task_id=current_task_id,
                pending_decision=pending_decision,
                multi_step_progress=multi_step_progress,
                metadata=metadata,
            )

            self._publish_state_change(conv)
            return conv

    async def enter_awaiting_confirmation(
        self,
        user_id: str,
        task_id: str,
        decision_prompt: str,
        metadata: dict | None = None,
    ) -> UserConversationState:
        """
        Transition user to AWAITING_CONFIRMATION state.

        This replaces the old 30s sleep loop with event-driven waiting.
        The caller should set up an event handler that resumes the task
        when the user responds (via card button click or text trigger).
        """
        meta = metadata or {}
        meta["decision_prompt"] = decision_prompt

        conv = await self.set_state(
            user_id=user_id,
            state=ConversationState.AWAITING_CONFIRMATION,
            current_task_id=task_id,
            pending_decision=decision_prompt,
            metadata=meta,
        )
        logger.info(
            "ConversationState: user %s awaiting confirmation for task %s",
            user_id,
            task_id,
        )
        return conv

    async def confirm(self, user_id: str) -> UserConversationState:
        """User confirmed — resume task execution."""
        conv = await self.get_state(user_id)
        if conv.state != ConversationState.AWAITING_CONFIRMATION:
            logger.warning(
                "confirm() called but state is %s (expected AWAITING_CONFIRMATION)",
                conv.state,
            )

        return await self.set_state(
            user_id=user_id,
            state=ConversationState.IN_PROGRESS,
            current_task_id=conv.current_task_id,
            pending_decision=None,
            multi_step_progress=conv.multi_step_progress,
            metadata={**conv.metadata, "confirmed_at": datetime.now(UTC).isoformat()},
        )

    async def intercept(self, user_id: str) -> UserConversationState:
        """User intercepted — cancel the task."""
        conv = await self.get_state(user_id)

        updated_meta = {**conv.metadata, "intercepted_at": datetime.now(UTC).isoformat()}
        return await self.set_state(
            user_id=user_id,
            state=ConversationState.IDLE,
            current_task_id=None,
            pending_decision=None,
            metadata=updated_meta,
        )

    async def complete(self, user_id: str) -> UserConversationState:
        """Mark conversation as completed and return to IDLE."""
        return await self.set_state(
            user_id=user_id,
            state=ConversationState.IDLE,
            current_task_id=None,
            pending_decision=None,
            multi_step_progress=0.0,
        )

    async def update_progress(self, user_id: str, progress: float) -> None:
        """Update multi-step progress (0.0 to 1.0)."""
        conv = await self.get_state(user_id)
        await self.set_state(
            user_id=user_id,
            state=conv.state,
            current_task_id=conv.current_task_id,
            pending_decision=conv.pending_decision,
            multi_step_progress=progress,
            metadata=conv.metadata,
        )

    def _publish_state_change(self, conv: UserConversationState) -> None:
        """Publish a CONVERSATION_STATE_CHANGED event."""
        try:
            event = Event(
                type=EventType.CONVERSATION_STATE_CHANGED,
                payload=conv.to_dict(),
            )
            asyncio.create_task(self._event_bus.publish(event))
        except Exception:
            logger.debug("Failed to publish conversation state change event")
