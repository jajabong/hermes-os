"""Task scheduling and persistence for long-running macro tasks.

Enables Hermes OS to:
- Persist tasks across restarts (SQLite)
- Track task dependencies (DAG)
- Wake/resume tasks after 7*24h operation
- Support parallel and sequential task execution
"""

from __future__ import annotations

import ast
import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import aiosqlite

from hermes_os.claude_code_invocator import (
    DEFAULT_MAX_TURNS,
    DEFAULT_TIMEOUT_SEC,
    InvocationError,
    invoke,
)
from hermes_os.conversation_state import ConversationStateManager
from hermes_os.event_loop import Event, EventType, get_event_bus
from hermes_os.guardian_controller import EscalationDecision, GuardianConfig, GuardianController
from hermes_os.jarvis_interface import JarvisInterface
from hermes_os.notification_manager import NotificationManager
from hermes_os.org_context import build_team_context
from hermes_os.org_memory import OrgMemory
from hermes_os.skill_discovery import CapabilityGap, SkillDiscovery
from hermes_os.skill_loader import SkillLoader
from hermes_os.topic_tracker import TopicTracker

# Default org identity injected when no other context is available
DEFAULT_ORG_IDENTITY = (
    "You are operating as a member of Hermes OS — an AI-native virtual organization. "
    "Execute the task with full autonomy and quality."
)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"  # waiting on dependencies


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class IntentLinkData:
    """Step-level intent tracking for "继续" continuity.

    Tracks which DAG subtask the user should resume when they say "继续".
    Replaces the粗糙的 LAST_TOPIC.md approach with step-level precision.
    """

    user_id: str
    topic: str
    intent_type: str
    dag_id: str
    dag_parent_task_id: str
    current_step: int = 1
    total_steps: int = 1
    completed_steps: int = 0
    pending_step_ids: list[str] = field(default_factory=list)
    last_error: str = ""
    error_category: str = "unknown"
    retry_count: int = 0
    resumption_count: int = 0
    is_active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "topic": self.topic,
            "intent_type": self.intent_type,
            "dag_id": self.dag_id,
            "dag_parent_task_id": self.dag_parent_task_id,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "pending_step_ids": ",".join(self.pending_step_ids),
            "last_error": self.last_error,
            "error_category": self.error_category,
            "retry_count": self.retry_count,
            "resumption_count": self.resumption_count,
            "is_active": 1 if self.is_active else 0,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> IntentLinkData:
        pending_str = row.get("pending_step_ids", "")
        return cls(
            user_id=row["user_id"],
            topic=row["topic"],
            intent_type=row.get("intent_type", "unknown"),
            dag_id=row["dag_id"],
            dag_parent_task_id=row["dag_parent_task_id"],
            current_step=row.get("current_step", 1),
            total_steps=row.get("total_steps", 1),
            completed_steps=row.get("completed_steps", 0),
            pending_step_ids=[p for p in pending_str.split(",") if p],
            last_error=row.get("last_error", ""),
            error_category=row.get("error_category", "unknown"),
            retry_count=row.get("retry_count", 0),
            resumption_count=row.get("resumption_count", 0),
            is_active=bool(row.get("is_active", 1)),
        )


@dataclass
class ContinuationContext:
    """Enriched context returned when user says "继续" — step-level detail for LLM."""

    dag_id: str
    topic: str
    intent_type: str
    current_step: int
    step_title: str
    completed_steps: int
    total_steps: int
    completion_pct: int
    pending_step_ids: list[str]
    last_error: str
    error_category: str
    retry_count: int
    resumption_count: int


def _classify_error(error_msg: str) -> str:
    """Classify an error message into a category for adaptive retry."""
    msg = error_msg.lower()
    if any(p in msg for p in ("rate limit", "quota", "too many requests")):
        return "rate_limit"
    if any(p in msg for p in ("timeout", "timed out", "exceeded")):
        return "timeout"
    if any(p in msg for p in ("auth", "token", "invalid", "unauthorized", "permission")):
        return "auth"
    if any(p in msg for p in ("skill", "not found", "missing", "capability")):
        return "skill"
    if any(p in msg for p in ("syntax", "typeerror", "valueerror", "attributeerror", "invalid json")):
        return "logical"
    return "unknown"


@dataclass
class Task:
    """Represents a persisted task in the Hermes OS task graph."""

    task_id: str
    user_id: str
    title: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    depends_on: list[str] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    progress: float = 0.0  # 0.0 to 1.0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "depends_on": ",".join(self.depends_on) if self.depends_on else "",
            "result": self.result or "",
            "error": self.error or "",
            "progress": self.progress,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else "",
            "completed_at": self.completed_at.isoformat() if self.completed_at else "",
            "metadata": str(self.metadata),
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Task:
        """Reconstruct Task from a database row."""
        depends_on = row["depends_on"].split(",") if row.get("depends_on") else []
        depends_on = [d for d in depends_on if d]

        def _parse_dt(v: str | None) -> datetime | None:
            if not v:
                return None
            try:
                return datetime.fromisoformat(v)
            except (ValueError, TypeError):
                return None

        metadata_str = row.get("metadata", "")
        try:
            metadata = ast.literal_eval(metadata_str) if metadata_str else {}
        except (ValueError, SyntaxError, TypeError):
            metadata = {}

        return cls(
            task_id=row["task_id"],
            user_id=row["user_id"],
            title=row["title"],
            description=row["description"],
            status=TaskStatus(row["status"]),
            priority=TaskPriority(row.get("priority", "normal")),
            depends_on=depends_on,
            result=row.get("result") or None,
            error=row.get("error") or None,
            progress=row.get("progress", 0.0),
            created_at=_parse_dt(row.get("created_at")) or datetime.now(UTC),
            updated_at=_parse_dt(row.get("updated_at")) or datetime.now(UTC),
            started_at=_parse_dt(row.get("started_at")),
            completed_at=_parse_dt(row.get("completed_at")),
            metadata=metadata,
        )


class TaskScheduler:
    """Persistent task scheduler with DAG support and wake mechanism.

    Tasks are stored in SQLite and survive Hermes OS restarts.
    The scheduler can be woken via:
    - Interval polling (async background loop)
    - Cron-style scheduling
    - Manual trigger (user or external event)
    """

    def __init__(
        self,
        db_path: str = "hermes_os.db",
        org_memory: OrgMemory | None = None,
        conversation_state_manager: ConversationStateManager | None = None,
    ) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._stop_event = asyncio.Event()
        self._org_memory = org_memory or OrgMemory()
        self._skill_discovery = SkillDiscovery()
        self._conv_state = conversation_state_manager
        self._jarvis: JarvisInterface | None = None
        self._event_bus = get_event_bus()
        self._notification_manager: NotificationManager | None = None
        self._guardian: GuardianController | None = None

    @property
    def jarvis(self) -> JarvisInterface:
        if self._jarvis is None:
            self._jarvis = JarvisInterface()
        return self._jarvis

    @property
    def notification_manager(self) -> NotificationManager:
        if self._notification_manager is None:
            self._notification_manager = NotificationManager(jarvis=self.jarvis)
        return self._notification_manager

    @property
    def guardian(self) -> GuardianController:
        if self._guardian is None:
            self._guardian = GuardianController(
                GuardianConfig(
                    checkpoint_dir=str(Path.home() / ".hermes" / "checkpoints"),
                    jarvis_factory=lambda: self.jarvis,
                )
            )
        return self._guardian

    async def _get_db(self) -> aiosqlite.Connection:
        if self._db is None:
            self._db = await aiosqlite.connect(self.db_path)
            self._db.row_factory = aiosqlite.Row
            await self._apply_pragmas(self._db)
        return self._db

    async def _apply_pragmas(self, db: aiosqlite.Connection) -> None:
        """Enforce WAL mode and normal synchronous for better concurrency."""
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")

    async def _lazy_init(self) -> None:
        """Create task tables if they don't exist."""
        db = await self._get_db()
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'pending',
                priority TEXT DEFAULT 'normal',
                depends_on TEXT DEFAULT '',
                result TEXT DEFAULT '',
                error TEXT DEFAULT '',
                progress REAL DEFAULT 0.0,
                created_at TEXT,
                updated_at TEXT,
                started_at TEXT DEFAULT '',
                completed_at TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}'
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")

        # IntentLink table for step-level "继续" tracking
        await db.execute("""
            CREATE TABLE IF NOT EXISTS intent_links (
                user_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                intent_type TEXT DEFAULT 'unknown',
                dag_id TEXT PRIMARY KEY,
                dag_parent_task_id TEXT NOT NULL,
                current_step INTEGER DEFAULT 1,
                total_steps INTEGER DEFAULT 1,
                completed_steps INTEGER DEFAULT 0,
                pending_step_ids TEXT DEFAULT '',
                last_error TEXT DEFAULT '',
                error_category TEXT DEFAULT 'unknown',
                retry_count INTEGER DEFAULT 0,
                resumption_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1
            )
        """)
        await db.commit()

    # -------------------------------------------------------------------------
    # Task CRUD
    # -------------------------------------------------------------------------

    async def create_task(
        self,
        user_id: str,
        title: str,
        description: str = "",
        priority: TaskPriority = TaskPriority.NORMAL,
        depends_on: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        """Create a new task and persist it."""
        await self._lazy_init()
        task = Task(
            task_id=str(uuid.uuid4()),
            user_id=user_id,
            title=title,
            description=description,
            priority=priority,
            depends_on=depends_on or [],
            metadata=metadata or {},
        )
        async with self._lock:
            db = await self._get_db()
            await db.execute(
                """
                INSERT INTO tasks
                (task_id, user_id, title, description, status, priority,
                 depends_on, result, error, progress, created_at, updated_at,
                 started_at, completed_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*task.to_dict().values(),),
            )
            await db.commit()
        return task

    async def get_task(self, task_id: str) -> Task | None:
        """Load a single task by ID."""
        await self._lazy_init()
        db = await self._get_db()
        async with db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)) as cursor:
            row = await cursor.fetchone()
            return Task.from_row(dict(row)) if row else None

    async def get_tasks_for_user(
        self,
        user_id: str,
        status: TaskStatus | None = None,
        limit: int = 50,
    ) -> list[Task]:
        """Get all tasks for a user, optionally filtered by status."""
        await self._lazy_init()
        db = await self._get_db()
        if status:
            query = "SELECT * FROM tasks WHERE user_id = ? AND status = ? ORDER BY created_at DESC LIMIT ?"
            args: tuple[str, str, int] = (user_id, status.value, limit)
        else:
            query = "SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC LIMIT ?"
            args = (user_id, limit)
        async with db.execute(query, args) as cursor:
            rows = await cursor.fetchall()
            return [Task.from_row(dict(row)) for row in rows]

    async def get_all_tasks(self) -> list[Task]:
        """Return ALL tasks across all users and all statuses."""
        await self._lazy_init()
        db = await self._get_db()
        async with db.execute("SELECT * FROM tasks ORDER BY created_at DESC") as cursor:
            rows = await cursor.fetchall()
        return [Task.from_row(dict(row)) for row in rows]

    async def get_task_by_id(self, task_id: str) -> Task | None:
        """Get a single task by task_id."""
        return await self.get_task(task_id)

    # -------------------------------------------------------------------------
    # IntentLink CRUD
    # -------------------------------------------------------------------------

    async def create_intent_link(
        self,
        user_id: str,
        topic: str,
        intent_type: str,
        dag_id: str,
        dag_parent_task_id: str,
        total_steps: int,
    ) -> IntentLinkData:
        """Create an IntentLink record when a new DAG is created."""
        await self._lazy_init()
        link = IntentLinkData(
            user_id=user_id,
            topic=topic,
            intent_type=intent_type,
            dag_id=dag_id,
            dag_parent_task_id=dag_parent_task_id,
            total_steps=total_steps,
        )
        async with self._lock:
            db = await self._get_db()
            await db.execute(
                """
                INSERT OR REPLACE INTO intent_links
                (user_id, topic, intent_type, dag_id, dag_parent_task_id,
                 current_step, total_steps, completed_steps, pending_step_ids,
                 last_error, error_category, retry_count, resumption_count, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    link.user_id, link.topic, link.intent_type,
                    link.dag_id, link.dag_parent_task_id,
                    link.current_step, link.total_steps, link.completed_steps,
                    ",".join(link.pending_step_ids),
                    link.last_error, link.error_category,
                    link.retry_count, link.resumption_count,
                    1 if link.is_active else 0,
                ),
            )
            await db.commit()
        return link

    async def get_intent_link_by_dag(self, dag_id: str) -> IntentLinkData | None:
        """Load IntentLink by dag_id."""
        await self._lazy_init()
        db = await self._get_db()
        async with db.execute("SELECT * FROM intent_links WHERE dag_id = ?", (dag_id,)) as cursor:
            row = await cursor.fetchone()
            return IntentLinkData.from_row(dict(row)) if row else None

    async def get_active_intent_link(self, user_id: str) -> IntentLinkData | None:
        """Get the active (incomplete) IntentLink for a user."""
        await self._lazy_init()
        db = await self._get_db()
        async with db.execute(
            "SELECT * FROM intent_links WHERE user_id = ? AND is_active = 1 LIMIT 1",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return IntentLinkData.from_row(dict(row)) if row else None

    async def update_intent_link(self, link: IntentLinkData) -> None:
        """Persist updated IntentLinkData to DB."""
        await self._lazy_init()
        async with self._lock:
            db = await self._get_db()
            await db.execute(
                """
                UPDATE intent_links SET
                    current_step = ?, total_steps = ?, completed_steps = ?,
                    pending_step_ids = ?, last_error = ?, error_category = ?,
                    retry_count = ?, resumption_count = ?, is_active = ?
                WHERE dag_id = ?
                """,
                (
                    link.current_step, link.total_steps, link.completed_steps,
                    ",".join(link.pending_step_ids),
                    link.last_error, link.error_category,
                    link.retry_count, link.resumption_count,
                    1 if link.is_active else 0,
                    link.dag_id,
                ),
            )
            await db.commit()

    async def record_resumption(self, dag_id: str) -> None:
        """Increment resumption_count when user says "继续"."""
        await self._lazy_init()
        async with self._lock:
            db = await self._get_db()
            await db.execute(
                "UPDATE intent_links SET resumption_count = resumption_count + 1 WHERE dag_id = ?",
                (dag_id,),
            )
            await db.commit()

    async def get_continuation_context(self, dag_id: str) -> ContinuationContext | None:
        """Build step-level ContinuationContext for LLM when user says "继续"."""
        link = await self.get_intent_link_by_dag(dag_id)
        if not link:
            return None

        # Get current step task
        db = await self._get_db()
        pending_ids = link.pending_step_ids

        # Find the task for current_step (current_step is NEXT step to execute)
        step_title = f"Step {link.current_step}"
        if pending_ids:
            # pending_ids[0] is always the current/next step
            current_task_id = pending_ids[0]
            task = await self.get_task(current_task_id)
            if task:
                step_title = task.title

        pct = int(link.completed_steps / link.total_steps * 100) if link.total_steps > 0 else 0

        return ContinuationContext(
            dag_id=link.dag_id,
            topic=link.topic,
            intent_type=link.intent_type,
            current_step=link.current_step,
            step_title=step_title,
            completed_steps=link.completed_steps,
            total_steps=link.total_steps,
            completion_pct=pct,
            pending_step_ids=link.pending_step_ids,
            last_error=link.last_error if link.last_error else None,
            error_category=link.error_category if link.error_category != "unknown" else None,
            retry_count=link.retry_count,
            resumption_count=link.resumption_count,
        )

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: str | None = None,
        error: str | None = None,
        progress: float | None = None,
    ) -> None:
        """Update task status, optionally with result/error/progress."""
        await self._lazy_init()
        async with self._lock:
            db = await self._get_db()
            now = datetime.now(UTC).isoformat()
            fields = ["status = ?", "updated_at = ?"]
            values: list[Any] = [status.value, now]
            if result is not None:
                fields.append("result = ?")
                values.append(result)
            if error is not None:
                fields.append("error = ?")
                values.append(error)
            if progress is not None:
                fields.append("progress = ?")
                values.append(progress)
            if status == TaskStatus.RUNNING:
                fields.append("started_at = ?")
                values.append(now)
            if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                fields.append("completed_at = ?")
                values.append(now)
            values.append(task_id)
            await db.execute(
                f"UPDATE tasks SET {', '.join(fields)} WHERE task_id = ?",
                values,
            )
            await db.commit()

        # After status change, update DAG progress and notify if needed
        if status == TaskStatus.COMPLETED:
            await self._on_task_completed(task_id)
        elif status == TaskStatus.FAILED:
            await self._on_task_failed(task_id, error)

        # Publish TASK_COMPLETED/TASK_FAILED events for ProactiveEngine
        task = await self.get_task(task_id)
        if task:
            event_type = EventType.TASK_COMPLETED if status == TaskStatus.COMPLETED else EventType.TASK_FAILED
            await self._event_bus.publish(Event(
                type=event_type,
                payload={
                    "task_id": task_id,
                    "user_id": task.user_id,
                    "status": status.value,
                    "result": result,
                    "error": error,
                    "title": task.title,
                    "metadata": task.metadata,
                },
            ))

    async def _on_task_completed(self, task_id: str) -> None:
        """Handle task completion: update DAG parent progress, notify user, clear TopicTracker."""
        task = await self.get_task(task_id)
        if not task:
            return

        dag_id = task.metadata.get("dag_id")
        if not dag_id:
            return

        # Find DAG parent and update progress
        await self._update_dag_progress(dag_id)

        # Send progress notification if DAG has notify_target
        dag_parent = await self._find_dag_parent(dag_id)
        if dag_parent:
            await self._send_dag_progress_notification(dag_parent, task)

        # Update IntentLink: advance current_step
        link = await self.get_intent_link_by_dag(dag_id)
        if link:
            dag_step = task.metadata.get("dag_step", 0)
            new_completed = link.completed_steps + 1
            new_current = link.current_step + 1

            # Check if all steps are done
            if new_completed >= link.total_steps:
                link.completed_steps = new_completed
                link.is_active = False
            else:
                link.completed_steps = new_completed
                link.current_step = new_current
                # Advance pending_step_ids (remove first)
                if link.pending_step_ids:
                    link.pending_step_ids = link.pending_step_ids[1:]

            await self.update_intent_link(link)

        # Clear TopicTracker entry for this task so "继续上次" doesn't reference a finished task
        try:
            tracker = TopicTracker(user_id=task.user_id)
            await tracker.complete_topic(task_id)
        except Exception:
            logger.debug("Failed to complete topic for task %s", task_id)

    async def _on_task_failed(self, task_id: str, error: str | None) -> None:
        """Handle task failure: update IntentLink error context and retry count."""
        task = await self.get_task(task_id)
        if not task:
            return

        dag_id = task.metadata.get("dag_id")
        if not dag_id:
            return

        link = await self.get_intent_link_by_dag(dag_id)
        if link:
            link.last_error = error or ""
            link.error_category = _classify_error(error or "")
            link.retry_count += 1
            await self.update_intent_link(link)

    async def _update_dag_progress(self, dag_id: str) -> None:
        """Update DAG parent completion count based on completed children."""
        dag_parent = await self._find_dag_parent(dag_id)
        if not dag_parent:
            return

        total_steps = dag_parent.metadata.get("dag_total_steps", 0)
        if total_steps == 0:
            return

        # Count completed subtasks for this dag_id
        all_tasks = await self.get_tasks_for_user(dag_parent.user_id)
        completed_count = sum(
            1
            for t in all_tasks
            if t.metadata.get("dag_id") == dag_id
            and t.status == TaskStatus.COMPLETED
            and not t.metadata.get("is_dag_parent")
        )

        # Update parent metadata
        dag_parent.metadata["dag_completed_steps"] = completed_count
        await self._save_task_metadata(dag_parent.task_id, dag_parent.metadata)

    async def _find_dag_parent(self, dag_id: str) -> Task | None:
        """Find the DAG parent task for a given dag_id."""
        all_tasks = await self.get_all_tasks()
        for t in all_tasks:
            if t.metadata.get("dag_id") == dag_id and t.metadata.get("is_dag_parent"):
                return t
        return None

    async def _save_task_metadata(self, task_id: str, metadata: dict) -> None:
        """Save metadata dict to a task (used for DAG progress updates)."""
        await self._lazy_init()
        db = await self._get_db()
        # Use str() to match Python dict syntax used by Task.to_dict/from_row
        await db.execute(
            "UPDATE tasks SET metadata = ?, updated_at = ? WHERE task_id = ?",
            (str(metadata), datetime.now(UTC).isoformat(), task_id),
        )
        await db.commit()

    async def get_dag_status(self, dag_id: str) -> dict | None:
        """Return structured DAG status: completion %, next step, is_complete."""
        dag_parent = await self._find_dag_parent(dag_id)
        if not dag_parent:
            return None

        total = dag_parent.metadata.get("dag_total_steps", 0)
        completed = dag_parent.metadata.get("dag_completed_steps", 0)
        pct = int(100 * completed / total) if total > 0 else 0

        # Find next pending subtask
        all_tasks = await self.get_tasks_for_user(dag_parent.user_id)
        pending_steps = [
            t
            for t in all_tasks
            if t.metadata.get("dag_id") == dag_id
            and not t.metadata.get("is_dag_parent")
            and t.status == TaskStatus.PENDING
        ]
        next_step = pending_steps[0].task_id if pending_steps else None

        return {
            "dag_id": dag_id,
            "parent_task_id": dag_parent.task_id,
            "total_steps": total,
            "completed_steps": completed,
            "completion_pct": pct,
            "next_step": next_step,
            "is_complete": completed >= total and total > 0,
        }

    async def _send_dag_progress_notification(self, dag_parent: Task, completed_step: Task) -> None:
        """Send progress notification to user after a subtask completes."""
        notify_target = dag_parent.metadata.get("notify_target")
        if not notify_target or notify_target.get("type") != "feishu":
            return

        open_id = notify_target.get("open_id")
        if not open_id:
            return

        dag_id = dag_parent.metadata.get("dag_id")
        total = dag_parent.metadata.get("dag_total_steps", 0)
        completed = dag_parent.metadata.get("dag_completed_steps", 0)
        pct = int(100 * completed / total) if total > 0 else 0

        title = f"🎯 DAG进度: {dag_parent.title}"
        content = (
            f"**完成**: {completed_step.title}\n"
            f"**进度**: {completed}/{total} ({pct}%)\n"
            f"**状态**: {'已完成！' if completed >= total else '进行中'}"
        )
        nl_summary = (
            f"DAG '{dag_parent.title}' step {completed}/{total} completed: {completed_step.title}"
        )

        try:
            await self.jarvis.send_card_with_nl(
                user_id=open_id,
                title=title,
                content=content,
                actions=[],
                nl_summary=nl_summary,
                task_id=dag_parent.task_id,
            )
        except Exception:
            pass  # Never block on notification failure

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task. Returns True if deleted."""
        await self._lazy_init()
        async with self._lock:
            db = await self._get_db()
            cursor = await db.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            await db.commit()
            return cursor.rowcount > 0

    # -------------------------------------------------------------------------
    # Skill gap detection
    # -------------------------------------------------------------------------

    def _extract_gap_keywords(self, text: str) -> list[str]:
        """Extract significant keywords that might indicate a skill gap."""
        common = {
            "agent",
            "task",
            "skill",
            "code",
            "review",
            "test",
            "build",
            "deploy",
            "debug",
            "api",
            "web",
            "data",
            "search",
            "learn",
            "write",
            "edit",
            "run",
            "file",
            "hermes",
            "os",
            "the",
            "and",
            "for",
            "with",
            "from",
            "this",
            "that",
            "have",
            "been",
            "will",
            "are",
            "was",
            "not",
            "but",
            "what",
            "when",
            "where",
            "how",
        }
        words = re.findall(r"[a-zA-Z]{4,}", text.lower())
        return [w for w in words if w not in common][:5]

    # -------------------------------------------------------------------------
    # Dependency graph
    # -------------------------------------------------------------------------

    async def retry_task(self, task_id: str) -> bool:
        """Manually retry a failed task. Increments retry_count and re-queues as PENDING.

        Returns True if retry was scheduled, False if task not found or not in FAILED state.
        """
        task = await self.get_task(task_id)
        if not task:
            return False
        if task.status != TaskStatus.FAILED:
            return False

        retry_count = task.metadata.get("retry_count", 0)
        task.metadata["retry_count"] = retry_count + 1
        await self._save_task_metadata(task.task_id, task.metadata)
        await self.update_task_status(
            task.task_id,
            TaskStatus.PENDING,
            error=None,  # clear previous error
        )
        import logging

        logger = logging.getLogger("hermes_os.scheduler")
        logger.info("Manually retrying task %s (attempt %d)", task.task_id, retry_count + 1)
        return True

    async def _detect_cycles(self, tasks: list[Task]) -> dict[str, list[str]]:
        """Detect directed cycles in the task dependency graph.

        Uses DFS-based cycle detection. Returns a dict mapping each task in a
        cycle to the list of task_ids in that cycle.

        An empty dict means no cycles detected.
        """
        # Build adjacency list: task_id -> set of tasks it depends on
        graph: dict[str, list[str]] = {t.task_id: list(t.depends_on) for t in tasks}
        visited: set[str] = set()
        rec_stack: set[str] = set()
        cycles: dict[str, list[str]] = {}

        def dfs(node: str, path: list[str]) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor, path)
                elif neighbor in rec_stack:
                    # Found a cycle — extract the cycle nodes
                    cycle_start = path.index(neighbor)
                    cycle_nodes = path[cycle_start:]
                    for cy_node in cycle_nodes:
                        cycles[cy_node] = cycle_nodes

            path.pop()
            rec_stack.remove(node)

        for task in tasks:
            if task.task_id not in visited:
                dfs(task.task_id, [])

        return cycles

    async def get_runnable_tasks(self) -> list[Task]:
        """Get all pending tasks whose dependencies are satisfied and not in a cycle."""
        await self._lazy_init()
        db = await self._get_db()
        async with db.execute(
            "SELECT * FROM tasks WHERE status = ?", (TaskStatus.PENDING.value,)
        ) as cursor:
            all_pending = [Task.from_row(dict(row)) for row in await cursor.fetchall()]

        # Detect cycles first — exclude all cyclic tasks from being runnable
        cycles = await self._detect_cycles(all_pending)
        cyclic_task_ids = set(cycles.keys())

        runnable = []
        for task in all_pending:
            if task.task_id in cyclic_task_ids:
                continue
            if not task.depends_on:
                runnable.append(task)
                continue
            # Check all dependencies are completed
            deps_met = True
            for dep_id in task.depends_on:
                dep = await self.get_task(dep_id)
                if dep is None or dep.status != TaskStatus.COMPLETED:
                    deps_met = False
                    break
            if deps_met:
                runnable.append(task)
        return runnable

    async def get_task_graph(self, user_id: str) -> dict[str, list[str]]:
        """Get the full dependency graph for a user (task_id -> depends_on)."""
        tasks = await self.get_tasks_for_user(user_id)
        return {t.task_id: t.depends_on for t in tasks}

    async def unblock_dependents(self, completed_task_id: str) -> list[Task]:
        """Find tasks that were blocked on a completed task and can now run.

        Only unblocks tasks where ALL dependencies are COMPLETED.
        If a task has no dependencies but is blocked, it is also unblocked.
        """
        await self._lazy_init()
        db = await self._get_db()
        async with db.execute(
            "SELECT * FROM tasks WHERE status = ?", (TaskStatus.BLOCKED.value,)
        ) as cursor:
            blocked = [Task.from_row(dict(row)) for row in await cursor.fetchall()]

        newly_runnable = []
        for task in blocked:
            if completed_task_id not in task.depends_on:
                continue

            # Re-check ALL dependencies — must ALL be COMPLETED
            all_dep_done = True
            for dep_id in task.depends_on:
                dep = await self.get_task(dep_id)
                if dep is None or dep.status != TaskStatus.COMPLETED:
                    all_dep_done = False
                    break

            if all_dep_done:
                await self.update_task_status(task.task_id, TaskStatus.PENDING)
                newly_runnable.append(task)
        return newly_runnable

    # -------------------------------------------------------------------------
    # Wake / polling loop
    # -------------------------------------------------------------------------

    async def start_watcher(self, interval_seconds: float = 30.0) -> None:
        """Start background polling loop.

        This is the "wake mechanism" — Hermes OS calls this to keep
        the scheduler alive. It checks for runnable tasks and processes them.
        """
        self._stop_event.clear()
        solidify_tick = 0
        while not self._stop_event.is_set():
            try:
                await self._process_pending_tasks()
            except Exception as e:
                logger.error("Watcher: _process_pending_tasks failed: %s", str(e)[:200])

            # Periodic skill solidify review (~every 1 hour at 30s intervals)
            solidify_tick += 1
            if solidify_tick >= 120:
                solidify_tick = 0
                try:
                    await self._skill_discovery.run_solidify_cycle()
                except Exception as e:
                    logger.error("Watcher: run_solidify_cycle failed: %s", str(e)[:200])

            await asyncio.sleep(interval_seconds)

    async def stop_watcher(self) -> None:
        """Stop the background polling loop."""
        self._stop_event.set()

    async def _process_pending_tasks(self) -> None:
        """Find and execute runnable tasks via ClaudeCodeInvoker."""
        logger = logging.getLogger("hermes_os.scheduler")
        runnable = await self.get_runnable_tasks()
        for task in runnable:
            # Mark as running to prevent duplicate dispatch
            await self.update_task_status(task.task_id, TaskStatus.RUNNING)

            # Jarvis Mode: Send intent card and wait for confirmation event-driven
            user_id = task.metadata.get("notify_target", {}).get("open_id") or task.user_id

            # Auto-execute if skip_confirmation is set (DAG tasks, high-confidence intents)
            if task.metadata.get("skip_confirmation", False):
                logger.info("Jarvis: Task %s auto-confirmed (skip_confirmation=True)", task.task_id)
                confirmed = True
            else:
                await self._send_intent_card(task)
                confirmed = await self._await_confirmation(user_id, task.task_id)

            if not confirmed:
                # User intercepted or timed out
                logger.info("Jarvis: Task %s intercepted or timed out", task.task_id)
                continue

            logger.info("Jarvis: Task %s confirmed by user, executing", task.task_id)

            # Stage-by-stage push: notify when a DAG subtask starts
            dag_id = task.metadata.get("dag_id")
            if dag_id:
                try:
                    link = await self.get_intent_link_by_dag(dag_id)
                    step_label = f"Step {link.current_step}: {task.title}" if link else task.title
                    goal_ctx = f"{link.topic} ({link.intent_type})" if link else None
                    await self.notification_manager.send_running_update(
                        user_id=task.user_id,
                        task_title=task.title,
                        task_id=task.task_id,
                        step=step_label,
                        goal_context=goal_ctx,
                    )
                except Exception:
                    logger.debug("Failed to send running update for task %s", task.task_id)

            try:
                # Extract execution parameters from metadata
                cwd = task.metadata.get("cwd")
                max_turns = task.metadata.get("max_turns", DEFAULT_MAX_TURNS)
                timeout_sec = task.metadata.get("timeout_sec", DEFAULT_TIMEOUT_SEC)
                allowed_tools = task.metadata.get("allowed_tools")
                model = task.metadata.get("model")
                base_system_prompt = task.metadata.get("system_prompt") or ""

                # Inject correction prompt if Guardian returned one (CORRECT decision)
                correction_prompt = task.metadata.get("correction_prompt")
                if correction_prompt:
                    base_system_prompt = f"{correction_prompt.strip()}\n\n{base_system_prompt}"
                    # Clear after injection (one-time use)
                    task.metadata.pop("correction_prompt", None)
                    await self._save_task_metadata(task.task_id, task.metadata)

                # Build full context: org identity + role + team context
                team_context = await build_team_context(task, self)

                # Inject transient skills via SkillLoader (with effectiveness tracking)
                loader = SkillLoader(skill_discovery=self._skill_discovery)
                skills_fragment = loader.get_all_prompt_fragments(max_skills=5, record_usage=True)

                # Inject relevant org memory
                memory_fragment = self._org_memory.search_relevant_memory(task.description)

                # Compose full system prompt
                parts = [base_system_prompt] if base_system_prompt else []
                if team_context:
                    parts.append(team_context)
                if skills_fragment:
                    parts.append(skills_fragment)
                if memory_fragment:
                    parts.append(memory_fragment)
                system_prompt = "\n\n".join(parts).strip()
                # Fallback: ensure at least a minimal org identity is present
                if not system_prompt:
                    system_prompt = DEFAULT_ORG_IDENTITY

                # Execute via ClaudeCodeInvoker
                result = await invoke(
                    prompt=task.description,
                    cwd=cwd,
                    max_turns=max_turns,
                    timeout_sec=timeout_sec,
                    allowed_tools=allowed_tools,
                    model=model,
                    system_prompt=system_prompt,
                )

                # Record task result in org memory
                self._org_memory.record_task_result(task.description, success=True)

                # Track skill effectiveness via SkillDiscovery
                await self._skill_discovery.record_usage(
                    skill_name=task.metadata.get("skill_used", "unknown"),
                    success=True,
                )

                # Detect capability gaps from successful task execution
                gap_keywords = self._extract_gap_keywords(task.description)
                if gap_keywords:
                    gap = CapabilityGap(
                        gap_type="task_outcome",
                        description=task.description,
                        context=result.stdout[:500] if result.stdout else "",
                        suggested_search="+".join(gap_keywords[:3]) + "+skill+claude+agent",
                    )
                    await self._skill_discovery.detect_gap(gap)

                # Success: mark completed with result
                await self.update_task_status(
                    task.task_id,
                    TaskStatus.COMPLETED,
                    result=result.stdout[:10000],  # cap result size
                    progress=1.0,
                )

                # Unblock dependent tasks
                newly_runnable = await self.unblock_dependents(task.task_id)

                # Send notification if configured
                await self._send_notification(task, status="completed", result=result.stdout)

            except InvocationError as e:
                # Record failure in org memory
                self._org_memory.record_task_result(task.description, success=False, error=str(e))

                # Delegate error attribution and escalation decision to GuardianController
                result = await self.guardian.handle_invocation_error(
                    task.task_id,
                    str(e)[:2000],
                )

                if result.decision == EscalationDecision.RETRY:
                    # Sync retry_count from Guardian's checkpoint to task metadata
                    # MUST be done before update_task_status calls _save_task_metadata
                    cp = await self.guardian.load_checkpoint(task.task_id)
                    if cp:
                        task.metadata["retry_count"] = cp.retry_count
                        await self._save_task_metadata(task.task_id, task.metadata)

                    # Exponential backoff then re-queue
                    if result.backoff_seconds > 0:
                        logger.info(
                            "Guardian: task %s RETRY in %.0fs (attr=%s)",
                            task.task_id,
                            result.backoff_seconds,
                            result.attribution.error_type.value,
                        )
                        await asyncio.sleep(result.backoff_seconds)

                    # Re-queue for retry
                    await self.update_task_status(
                        task.task_id,
                        TaskStatus.PENDING,
                        error=f"Retry attempt ({result.attribution.error_type.value}): {str(e)[:300]}",
                    )

                elif result.decision == EscalationDecision.CORRECT:
                    # Store correction prompt for injection on retry
                    logger.info(
                        "Guardian: task %s CORRECT — %s",
                        task.task_id,
                        result.attribution.diagnosis,
                    )
                    task.metadata["correction_prompt"] = result.correction_prompt
                    task.metadata["error_attribution"] = result.attribution.error_type.value
                    await self._save_task_metadata(task.task_id, task.metadata)

                    # Backoff then re-queue with correction
                    if result.backoff_seconds > 0:
                        await asyncio.sleep(result.backoff_seconds)

                    await self.update_task_status(
                        task.task_id,
                        TaskStatus.PENDING,
                        error=f"Correcting ({result.attribution.error_type.value}): {str(e)[:300]}",
                    )

                elif result.decision == EscalationDecision.ESCALATE:
                    # Guardian handles escalation card to user
                    await self.guardian.escalate(task.task_id)
                    error_msg = str(e)[:2000]
                    await self.update_task_status(
                        task.task_id,
                        TaskStatus.FAILED,
                        error=f"Guardian escalation: {result.attribution.diagnosis} — {error_msg}",
                    )
                    # Unblock dependents
                    await self.unblock_dependents(task.task_id)

                else:  # ABORT
                    error_msg = str(e)[:2000]
                    await self.update_task_status(
                        task.task_id,
                        TaskStatus.FAILED,
                        error=f"Guardian abort: {error_msg}",
                    )
                    await self.unblock_dependents(task.task_id)

                    # Send notification if configured
                    await self._send_notification(task, status="failed", error=error_msg)

    async def _send_notification(
        self,
        task: Task,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Send notification if task has notify_target in metadata."""
        notify_target = task.metadata.get("notify_target")
        if not notify_target or notify_target.get("type") != "feishu":
            return

        open_id = notify_target.get("open_id")
        if not open_id:
            return

        if status == "completed":
            title = f"✅ 任务完成: {task.title}"
            content = f"任务已成功完成。\n\n**描述**: {task.description[:200]}"
            if result:
                content += f"\n\n**结果**: {result[:500]}"
            nl_summary = f"Task completed: {task.title}"
        elif status == "failed":
            title = f"❌ 任务失败: {task.title}"
            content = f"任务执行失败。\n\n**描述**: {task.description[:200]}"
            if error:
                content += f"\n\n**错误**: {error[:500]}"
            nl_summary = f"Task failed: {task.title}"
        else:
            title = f"📋 任务状态更新: {task.title}"
            content = f"任务状态: {status}"
            nl_summary = f"Task status update: {task.title}"

        try:
            await self.jarvis.send_card_with_nl(
                user_id=open_id,
                title=title,
                content=content,
                actions=[],
                nl_summary=nl_summary,
                task_id=task.task_id,
            )
        except Exception:
            pass  # Best-effort notification

    async def _send_intent_card(self, task: Task) -> None:
        """Jarvis Mode: Notify user of the intent before starting execution."""
        notify_target = task.metadata.get("notify_target")
        if not notify_target or notify_target.get("type") != "feishu":
            return

        open_id = notify_target.get("open_id")
        if not open_id:
            return

        title = f"🤖 Jarvis: 意图预判 - {task.title}"
        content = (
            f"检测到可执行任务，我准备开始处理：\n\n"
            f"**描述**: {task.description}\n"
            f"**优先级**: {task.priority.value}\n\n"
            f"将在后台异步执行，您可以随时在飞书查询进度。"
        )
        actions = [
            {"text": "立即执行", "value": "run_now", "type": "primary", "task_id": task.task_id},
            {"text": "拦截任务", "value": "stop_task", "type": "danger", "task_id": task.task_id},
        ]

        try:
            await self.jarvis.send_card_with_nl(
                user_id=open_id,
                title=title,
                content=content,
                actions=actions,
                nl_summary=f"Jarvis intent card for task: {task.title}",
                task_id=task.task_id,
            )
        except Exception:
            logger.warning("Failed to send Jarvis intent card for task %s", task.task_id)

    async def _await_confirmation(self, user_id: str, task_id: str) -> bool:
        """
        Event-driven wait for user confirmation.

        Replaces the old 30s polling loop. Uses an asyncio.Event that gets
        set when USER_CONFIRMED or USER_INTERCEPTED events fire.

        Timeout: 60 seconds (user can just not respond = auto-timeout).
        """
        if self._conv_state is None:
            self._conv_state = ConversationStateManager()

        # Enter awaiting confirmation state
        await self._conv_state.enter_awaiting_confirmation(
            user_id=user_id,
            task_id=task_id,
            decision_prompt=f"Confirm task execution for {task_id}",
        )

        confirm_event = asyncio.Event()
        intercept_event = asyncio.Event()
        confirmed = False

        async def on_confirm(event: Event) -> None:
            if event.payload.get("user_id") == user_id:
                confirm_event.set()

        async def on_intercept(event: Event) -> None:
            if event.payload.get("user_id") == user_id:
                intercept_event.set()

        handler1 = self._event_bus.subscribe(EventType.USER_CONFIRMED, on_confirm)
        handler2 = self._event_bus.subscribe(EventType.USER_INTERCEPTED, on_intercept)

        try:
            # Wait for either confirm, intercept, or timeout — event-driven, not polling
            import os

            timeout = int(os.environ.get("HERMES_OS_CONFIRM_TIMEOUT", "60"))
            logger = logging.getLogger("hermes_os.scheduler")
            logger.info("Jarvis: Waiting for user %s confirmation (timeout=%ds)", user_id, timeout)

            # Also check progress flag as fallback (legacy signal via DB poll)
            async def check_progress_flag() -> None:
                for _ in range(timeout):
                    await asyncio.sleep(1)
                    current = await self.get_task(task_id)
                    if current and current.progress > 0:
                        logger.info("Jarvis: User triggered [Run Now] via progress flag")
                        confirm_event.set()
                    if current and current.status in (TaskStatus.FAILED, TaskStatus.BLOCKED):
                        logger.info("Jarvis: Task %s intercepted via status change", task_id)
                        intercept_event.set()

            progress_task = asyncio.create_task(check_progress_flag())

            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(confirm_event.wait()),
                    asyncio.create_task(intercept_event.wait()),
                ],
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for p in pending:
                p.cancel()
            progress_task.cancel()

            if confirm_event.is_set():
                confirmed = True
        finally:
            self._event_bus.unsubscribe(EventType.USER_CONFIRMED, on_confirm)
            self._event_bus.unsubscribe(EventType.USER_INTERCEPTED, on_intercept)
            # Reset conversation state
            if confirmed:
                await self._conv_state.confirm(user_id)
            else:
                await self._conv_state.intercept(user_id)

        return confirmed

    async def schedule_task(
        self,
        user_id: str,
        title: str,
        description: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        depends_on: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        """Create a task and immediately mark it as pending for execution.

        Unlike create_task(), this is the fast-path for scheduling:
        - Creates the task in pending state
        - Does not wait for execution (execution happens in _process_pending_tasks)
        - Suitable for fire-and-forget patterns

        Args:
            user_id: Owner of the task
            title: Task title
            description: Claude -p prompt to execute
            priority: Task priority
            depends_on: List of task IDs this depends on
            metadata: Additional config (cwd, max_turns, timeout_sec, notify_target, etc.)

        Returns:
            The created Task object
        """
        meta = metadata or {}
        # Ensure we have default execution params
        meta.setdefault("max_turns", DEFAULT_MAX_TURNS)
        meta.setdefault("timeout_sec", DEFAULT_TIMEOUT_SEC)
        # Ensure role identity is always set
        meta.setdefault("intent_action", "unknown")
        meta.setdefault("role", "executor")
        meta.setdefault("system_prompt", "")

        return await self.create_task(
            user_id=user_id,
            title=title,
            description=description,
            priority=priority,
            depends_on=depends_on,
            metadata=meta,
        )

    # -------------------------------------------------------------------------
    # High-level workflow helpers
    # -------------------------------------------------------------------------

    async def create_macro_task(
        self,
        user_id: str,
        title: str,
        subtasks: list[dict[str, str]],
        metadata: dict[str, Any] | None = None,
    ) -> list[Task]:
        """Create a macro task with automatically managed dependencies.

        Args:
            user_id: Owner of this task chain
            title: Overall task title
            subtasks: List of {"title": ..., "description": ...} in execution order

        Returns:
            List of created tasks (first has no dependencies, each subsequent
            task depends on all previous tasks).
        """
        created: list[Task] = []
        prev_ids: list[str] = []
        meta = metadata or {}
        # Ensure role identity defaults
        meta.setdefault("role", "executor")
        meta.setdefault("intent_action", "unknown")
        meta.setdefault("system_prompt", "")

        for i, st in enumerate(subtasks):
            is_first = i == 0
            is_last = i == len(subtasks) - 1

            task = await self.create_task(
                user_id=user_id,
                title=st["title"],
                description=st["description"],
                priority=TaskPriority.HIGH if is_last else TaskPriority.NORMAL,
                depends_on=[] if is_first else prev_ids.copy(),
                metadata={
                    **meta,
                    "macro_title": title,
                    "subtask_index": i,
                    "subtask_count": len(subtasks),
                    "is_final": is_last,
                },
            )
            created.append(task)
            prev_ids.append(task.task_id)

        # Create IntentLink for step-level "继续" tracking
        if created:
            try:
                dag_id = f"dag-{created[0].task_id[:8]}"
                link = IntentLinkData(
                    user_id=user_id,
                    topic=title,
                    intent_type=meta.get("intent_action", "unknown"),
                    dag_id=dag_id,
                    dag_parent_task_id=created[0].task_id,
                    current_step=1,
                    total_steps=len(created),
                    completed_steps=0,
                    pending_step_ids=[t.task_id for t in created],
                )
                await self.create_intent_link(**{
                    "user_id": link.user_id,
                    "topic": link.topic,
                    "intent_type": link.intent_type,
                    "dag_id": link.dag_id,
                    "dag_parent_task_id": link.dag_parent_task_id,
                    "total_steps": link.total_steps,
                })
                # Then update with pending_step_ids
                await self.update_intent_link(link)
            except Exception:
                logger.debug("Failed to create IntentLink for macro task %s", created[0].task_id)

        return created

    async def create_pipeline_tasks(
        self,
        user_id: str,
        topic: str,
        pipeline_name: str = "Book Authoring Pipeline",
        metadata: dict[str, Any] | None = None,
    ) -> list[Task]:
        """Create pipeline stage tasks for a given pipeline.

        Discovers the pipeline YAML, creates one Task per stage with
        pipeline_name/stage_name/pipeline_task_id metadata so that
        PipelineTaskRunner.is_pipeline_task() detects them.

        Args:
            user_id: Owner of the tasks
            topic: Book/script topic (used for context)
            pipeline_name: Pipeline name to discover
            metadata: Additional metadata to attach

        Returns:
            List of created Task objects (one per stage)
        """
        from hermes_os.pipeline_task_runner import PipelineTaskRunner

        pipeline_task_id = f"pipeline-{uuid.uuid4().hex[:8]}"
        meta = metadata or {}
        meta.setdefault("intent_action", "write_book")
        meta.setdefault("topic", topic)

        # Discover pipeline YAML
        runner = PipelineTaskRunner(
            artifact_base=str(Path.home() / ".hermes" / "artifacts"),
        )
        pipeline_path = runner._discover_pipeline_path(pipeline_name)
        if not pipeline_path:
            logger.warning("TaskScheduler: pipeline not found: %s", pipeline_name)
            return []

        try:
            from hermes_os.pipeline_engine import PipelineDefinition

            definition = PipelineDefinition.from_yaml(pipeline_path)
        except Exception as e:
            logger.error("TaskScheduler: failed to load pipeline %s: %s", pipeline_name, e)
            return []

        # Create one task per stage with pipeline metadata
        created: list[Task] = []
        for stage in definition.stages:
            task = await self.create_task(
                user_id=user_id,
                title=f"{stage.name}: {topic}",
                description=f"{stage.description}\n\nTopic: {topic}",
                priority=TaskPriority.HIGH,
                depends_on=[],
                metadata={
                    **meta,
                    "pipeline_name": pipeline_name,
                    "pipeline_path": str(pipeline_path),
                    "stage_name": stage.name,
                    "pipeline_task_id": pipeline_task_id,
                    "topic": topic,
                },
            )
            created.append(task)

        return created

    async def get_macro_progress(self, user_id: str, macro_title: str) -> dict[str, Any]:
        """Get progress summary for all subtasks of a macro task."""
        tasks = await self.get_tasks_for_user(user_id)
        subtasks = [t for t in tasks if t.metadata.get("macro_title") == macro_title]
        if not subtasks:
            return {"found": False}

        total = len(subtasks)
        completed = sum(1 for t in subtasks if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in subtasks if t.status == TaskStatus.FAILED)
        running = sum(1 for t in subtasks if t.status == TaskStatus.RUNNING)
        pending = total - completed - failed - running

        return {
            "found": True,
            "total": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "pending": pending,
            "progress": completed / total if total > 0 else 0.0,
            "tasks": sorted(
                [
                    {
                        "task_id": t.task_id,
                        "title": t.title,
                        "status": t.status.value,
                        "progress": t.progress,
                        "result": t.result or "",
                        "error": t.error or "",
                        "_index": t.metadata.get("subtask_index", 0),
                    }
                    for t in subtasks
                ],
                key=lambda x: x["_index"],
            ),
        }
