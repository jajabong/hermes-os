"""Event-driven loop for Hermes OS — time-triggered + internal events.

Enables Hermes OS to run proactively instead of passively waiting for user messages.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Built-in event types."""

    USER_MESSAGE = "hermes_os.user_message"
    CRON_TICK = "hermes_os.cron_tick"
    TASK_COMPLETED = "hermes_os.task_completed"
    TASK_FAILED = "hermes_os.task_failed"
    SKILL_DISCOVERED = "hermes_os.skill_discovered"
    SKILL_EFFECTIVENESS_UPDATED = "hermes_os.skill_effectiveness_updated"
    AGENT_RESPONSE = "hermes_os.agent_response"
    CONVERSATION_STATE_CHANGED = "hermes_os.conversation_state_changed"
    USER_CONFIRMED = "hermes_os.user_confirmed"
    USER_INTERCEPTED = "hermes_os.user_intercepted"

    # GitHub PR events
    PULL_REQUEST_OPENED = "github.pull_request.opened"
    PULL_REQUEST_CLOSED = "github.pull_request.closed"
    PULL_REQUEST_MERGED = "github.pull_request.merged"
    PULL_REQUEST_REOPENED = "github.pull_request.reopened"
    PULL_REQUEST_SYNCED = "github.pull_request.synced"
    PULL_REQUEST_REVIEW_REQUESTED = "github.pull_request.review_requested"

    # GitHub push events
    PUSH = "github.push"

    # GitHub issue events
    ISSUE_OPENED = "github.issue.opened"
    ISSUE_CLOSED = "github.issue.closed"
    ISSUE_REOPENED = "github.issue.reopened"
    ISSUE_LABELED = "github.issue.labeled"
    ISSUE_COMMENT = "github.issue.comment"

    # GitHub review events
    PULL_REQUEST_REVIEW = "github.pull_request.review"
    PULL_REQUEST_REVIEW_COMMENT = "github.pull_request.review_comment"


@dataclass
class Event:
    """A domain event in the Hermes OS event system."""

    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    source: str = "hermes_os"

    def __post_init__(self) -> None:
        if isinstance(self.type, str):
            self.type = EventType(self.type)


EventHandler = Callable[[Event], Awaitable[None]]


class EventBus:
    """Central pub/sub bus for Hermes OS events.

    All components communicate through this bus. Handlers are called
    asynchronously and do not block the event publisher.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: EventType | str, handler: EventHandler) -> None:
        """Register a handler for an event type."""
        key = event_type.value if isinstance(event_type, EventType) else event_type
        asyncio.create_task(self._subscribe_async(key, handler))

    async def _subscribe_async(self, key: str, handler: EventHandler) -> None:
        async with self._lock:
            if key not in self._handlers:
                self._handlers[key] = []
            if handler not in self._handlers[key]:
                self._handlers[key].append(handler)

    def unsubscribe(self, event_type: EventType | str, handler: EventHandler) -> None:
        """Remove a handler from an event type."""
        key = event_type.value if isinstance(event_type, EventType) else event_type
        asyncio.create_task(self._unsubscribe_async(key, handler))

    async def _unsubscribe_async(self, key: str, handler: EventHandler) -> None:
        async with self._lock:
            if key in self._handlers and handler in self._handlers[key]:
                self._handlers[key].remove(handler)

    async def publish(self, event: Event) -> None:
        """Publish an event to all registered handlers.

        Handlers are called fire-and-forget — exceptions are logged but
        do not propagate or block other handlers.
        """
        key = event.type.value if isinstance(event.type, EventType) else event.type
        async with self._lock:
            handlers = list(self._handlers.get(key, []))

        if not handlers:
            return

        for handler in handlers:
            try:
                asyncio.create_task(self._safe_handle(handler, event))
            except Exception:
                pass

    async def _safe_handle(self, handler: EventHandler, event: Event) -> None:
        """Call handler, logging any exceptions."""
        try:
            await handler(event)
        except Exception as e:
            logger.exception("Event handler %s raised: %s", handler.__name__, e)

    async def publish_sync(self, event: Event) -> None:
        """Publish synchronously (for testing/debugging)."""
        key = event.type.value if isinstance(event.type, EventType) else event.type
        async with self._lock:
            handlers = list(self._handlers.get(key, []))
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.exception("Event handler %s raised: %s", handler.__name__, e)


# Global singleton
_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get the global EventBus singleton."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


class HermesOSEventLoop:
    """Event-driven loop for proactive Hermes OS operation.

    Supports:
    - CRON_TICK: time-triggered events (default 60s interval)
    - Internal events: published via EventBus
    - Custom handlers: register for any event type

    Usage:
        loop = HermesOSEventLoop()
        await loop.start()

        # Or with auto-start:
        loop = HermesOSEventLoop(auto_start=True)
    """

    DEFAULT_TICK_INTERVAL = 60.0  # seconds

    def __init__(
        self,
        tick_interval: float = DEFAULT_TICK_INTERVAL,
        auto_start: bool = False,
    ) -> None:
        self.tick_interval = tick_interval
        self.auto_start = auto_start
        self._bus = get_event_bus()
        self._running = False
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._handlers: list[tuple[str, EventHandler]] = []

    def register_handler(
        self,
        event_type: EventType | str,
        handler: EventHandler,
    ) -> None:
        """Register a handler before the loop starts."""
        key = event_type.value if isinstance(event_type, EventType) else event_type
        self._handlers.append((key, handler))

    async def start(self) -> None:
        """Start the event loop."""
        if self._running:
            return

        # Register pre-registered handlers
        for key, handler in self._handlers:
            self._bus.subscribe(key, handler)

        self._running = True
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "HermesOSEventLoop started (tick_interval=%.1fs)",
            self.tick_interval,
        )

    async def stop(self) -> None:
        """Stop the event loop gracefully."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except TimeoutError:
                pass
            self._task = None
        logger.info("HermesOSEventLoop stopped")

    async def _run_loop(self) -> None:
        """Main loop: tick CRON_TICK at regular intervals."""
        tick_count = 0
        while not self._stop_event.is_set():
            tick_count += 1
            event = Event(
                type=EventType.CRON_TICK,
                payload={
                    "tick_count": tick_count,
                    "interval": self.tick_interval,
                },
            )
            # Publish asynchronously — don't block the loop
            asyncio.create_task(self._bus.publish(event))

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.tick_interval,
                )
                # stop_event was set, exit cleanly
                break
            except TimeoutError:
                # Normal tick timeout
                pass

    def publish_user_message(
        self,
        user_id: str,
        message: str,
        platform: str = "unknown",
        session_id: str = "",
    ) -> None:
        """Publish a USER_MESSAGE event (non-blocking)."""
        event = Event(
            type=EventType.USER_MESSAGE,
            payload={
                "user_id": user_id,
                "message": message,
                "platform": platform,
                "session_id": session_id,
            },
        )
        asyncio.create_task(self._bus.publish(event))

    def publish_task_event(
        self,
        event_type: EventType,
        task_id: str,
        user_id: str,
        **kwargs: Any,
    ) -> None:
        """Publish a task-related event (non-blocking)."""
        event = Event(
            type=event_type,
            payload={
                "task_id": task_id,
                "user_id": user_id,
                **kwargs,
            },
        )
        asyncio.create_task(self._bus.publish(event))


# Convenience: tick handler decorator
def on_cron_tick(
    tick_interval: float | None = None,
) -> Callable[[EventHandler], EventHandler]:
    """Decorator to mark a handler as a CRON_TICK handler."""

    def decorator(handler: EventHandler) -> EventHandler:
        handler._hermes_os_event_type = EventType.CRON_TICK
        if tick_interval:
            handler._hermes_os_tick_interval = tick_interval
        return handler

    return decorator


def on_event(event_type: EventType) -> Callable[[EventHandler], EventHandler]:
    """Decorator to mark a handler for a specific event type."""

    def decorator(handler: EventHandler) -> EventHandler:
        handler._hermes_os_event_type = event_type
        return handler

    return decorator
