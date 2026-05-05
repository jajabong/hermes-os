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
from hermes_os.org_context import build_team_context
from hermes_os.skill_loader import SkillLoader
from hermes_os.skill_discovery import SkillDiscovery, CapabilityGap
from hermes_os.org_memory import OrgMemory
from hermes_os.feishu_enhancer import FeishuEnhancer
from hermes_os.conversation_state import ConversationStateManager, ConversationState
from hermes_os.jarvis_interface import JarvisInterface
from hermes_os.event_loop import get_event_bus, Event, EventType


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

    def __init__(self, db_path: str = "hermes_os.db", org_memory: OrgMemory | None = None, conversation_state_manager: ConversationStateManager | None = None) -> None:
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

    @property
    def jarvis(self) -> JarvisInterface:
        if self._jarvis is None:
            self._jarvis = JarvisInterface()
        return self._jarvis

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
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)"
        )
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
        async with db.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ) as cursor:
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
        async with db.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
        return [Task.from_row(dict(row)) for row in rows]

    async def get_task_by_id(self, task_id: str) -> Task | None:
        """Get a single task by task_id."""
        return await self.get_task(task_id)

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

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task. Returns True if deleted."""
        await self._lazy_init()
        async with self._lock:
            db = await self._get_db()
            cursor = await db.execute(
                "DELETE FROM tasks WHERE task_id = ?", (task_id,)
            )
            await db.commit()
            return cursor.rowcount > 0

    # -------------------------------------------------------------------------
    # Skill gap detection
    # -------------------------------------------------------------------------

    def _extract_gap_keywords(self, text: str) -> list[str]:
        """Extract significant keywords that might indicate a skill gap."""
        common = {
            "agent", "task", "skill", "code", "review", "test", "build",
            "deploy", "debug", "api", "web", "data", "search", "learn",
            "write", "edit", "run", "file", "hermes", "os", "the", "and",
            "for", "with", "from", "this", "that", "have", "been", "will",
            "are", "was", "not", "but", "what", "when", "where", "how",
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
        runnable = await self.get_runnable_tasks()
        for task in runnable:
            # Mark as running to prevent duplicate dispatch
            await self.update_task_status(task.task_id, TaskStatus.RUNNING)

            # Jarvis Mode: Send intent card and wait for confirmation event-driven
            await self._send_intent_card(task)

            # Event-driven wait: set AWAITING_CONFIRMATION and listen for user response
            user_id = task.metadata.get("notify_target", {}).get("open_id") or task.user_id
            confirmed = await self._await_confirmation(user_id, task.task_id)

            if not confirmed:
                # User intercepted or timed out
                logger.info("Jarvis: Task %s intercepted or timed out", task.task_id)
                continue

            logger.info("Jarvis: Task %s confirmed by user, executing", task.task_id)

            try:
                # Extract execution parameters from metadata
                cwd = task.metadata.get("cwd")
                max_turns = task.metadata.get("max_turns", DEFAULT_MAX_TURNS)
                timeout_sec = task.metadata.get("timeout_sec", DEFAULT_TIMEOUT_SEC)
                allowed_tools = task.metadata.get("allowed_tools")
                model = task.metadata.get("model")
                base_system_prompt = task.metadata.get("system_prompt") or ""

                # Build full context: org identity + role + team context
                team_context = await build_team_context(task, self)
                
                # Inject transient skills via SkillLoader
                loader = SkillLoader()
                skills_fragment = loader.get_all_prompt_fragments(max_skills=5)
                
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

                # On task failure, proactively search for solutions
                discovered = await self._skill_discovery.proactive_discovery(
                    task_description=f"fix: {task.description}",
                    gap_type="failed_task",
                )
                if discovered:
                    import logging
                    logger = logging.getLogger("hermes_os.scheduler")
                    logger.info(
                        "Discovered %d solution skill(s) for failed task %s",
                        len(discovered), task.task_id,
                    )

                # Retry logic: if retry_count < 3, re-queue as PENDING
                retry_count = task.metadata.get("retry_count", 0)
                if retry_count < 3:
                    task.metadata["retry_count"] = retry_count + 1
                    await self.update_task_status(
                        task.task_id,
                        TaskStatus.PENDING,  # re-queue instead of fail
                        error=f"Retry {retry_count + 1}/3: {str(e)[:500]}",
                    )
                    import logging
                    logger = logging.getLogger("hermes_os.scheduler")
                    logger.warning(
                        "Task %s failed (attempt %d/%d), re-queued: %s",
                        task.task_id, retry_count + 1, 3, str(e)[:200],
                    )
                else:
                    # Failure: mark failed with error (exceeded retries)
                    error_msg = str(e)[:2000]
                    await self.update_task_status(
                        task.task_id,
                        TaskStatus.FAILED,
                        error=f"Exceeded retries: {error_msg}",
                    )

                    # Unblock dependent tasks even on failure
                    await self.unblock_dependents(task.task_id)

                    # Send notification if configured
                    await self._send_notification(
                        task, status="failed", error=error_msg
                    )

    async def _send_notification(
        self,
        task: Task,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Send notification if task has notify_target in metadata."""
        # ... (existing implementation)

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
            {"text": "拦截任务", "value": "stop_task", "type": "danger", "task_id": task.task_id}
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
            import logging
            logger = logging.getLogger("hermes_os.scheduler")
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
            # Wait for either confirm, intercept, or 60s timeout
            timeout = 60
            logger = logging.getLogger("hermes_os.scheduler")
            logger.info("Jarvis: Waiting for user %s confirmation (timeout=%ds)", user_id, timeout)

            for _ in range(timeout):
                await asyncio.sleep(1)
                # Also check progress flag as fallback (legacy signal)
                current = await self.get_task(task_id)
                if current and current.progress > 0:
                    logger.info("Jarvis: User triggered [Run Now] via progress flag")
                    confirmed = True
                    break
                if current and current.status in (TaskStatus.FAILED, TaskStatus.BLOCKED):
                    logger.info("Jarvis: Task %s intercepted via status change", task_id)
                    break

            # If we got here without confirm_event/intercept_event firing,
            # check if either event was triggered (non-blocking check)
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

    async def get_macro_progress(
        self, user_id: str, macro_title: str
    ) -> dict[str, Any]:
        """Get progress summary for all subtasks of a macro task."""
        tasks = await self.get_tasks_for_user(user_id)
        subtasks = [t for t in tasks if t.metadata.get("macro_title") == macro_title]
        if not subtasks:
            return {"found": False}

        total = len(subtasks)
        completed = sum(
            1 for t in subtasks if t.status == TaskStatus.COMPLETED
        )
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
