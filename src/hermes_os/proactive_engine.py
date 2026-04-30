"""Proactive Engine — Hermes OS autonomous patrol layer.

Drives 7x24 autonomous behavior by listening to CRON_TICK events and:
1. Patrol failed/blocked tasks → auto-create fix tasks
2. Patrol completed tasks → trigger follow-up actions
3. Periodic health checks → notify on anomalies
4. Proactive suggestions → push to users via Feishu

Wired into HermesOSEventLoop via gateway_hook.py registration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from hermes_os.event_loop import Event, EventType, HermesOSEventLoop

if TYPE_CHECKING:
    from hermes_os.org_memory import OrgMemory
    from hermes_os.task_scheduler import Task, TaskScheduler

logger = logging.getLogger(__name__)

# Patrol interval: do deep checks every N ticks (every N * 60 seconds)
_DEEP_PATROL_INTERVAL = 5  # every 5 minutes


class ProactiveEngine:
    """
    Autonomous patrol engine — listens to CRON_TICK and drives proactive actions.

    Does NOT run tasks itself — it monitors task state and creates new tasks
    or sends notifications. Actual task execution goes through TaskScheduler.

    Design principle: this engine should never block. All heavy operations
    are fire-and-forget coroutines.
    """

    def __init__(self, scheduler: TaskScheduler | None = None) -> None:
        self._scheduler = scheduler
        self._org_memory: "OrgMemory | None" = None
        self._last_deep_patrol_tick = 0
        self._pending_notifications: list[str] = []

    def set_scheduler(self, scheduler: TaskScheduler) -> None:
        """Inject scheduler after lazy initialization."""
        self._scheduler = scheduler

    def set_org_memory(self, org_memory: "OrgMemory") -> None:
        """Inject OrgMemory instance."""
        self._org_memory = org_memory

    # -------------------------------------------------------------------------
    # Event handler registration
    # -------------------------------------------------------------------------

    def register_with_loop(self, loop: HermesOSEventLoop) -> None:
        """Register this engine's handlers with an event loop."""
        loop.register_handler(EventType.CRON_TICK, self.on_cron_tick)
        loop.register_handler(EventType.TASK_COMPLETED, self.on_task_completed)
        loop.register_handler(EventType.TASK_FAILED, self.on_task_failed)
        logger.info("ProactiveEngine registered with event loop")

    # -------------------------------------------------------------------------
    # CRON_TICK handler — the heartbeat of autonomous operation
    # -------------------------------------------------------------------------

    async def on_cron_tick(self, event: Event) -> None:
        """
        Every CRON_TICK (60s by default):
        - Shallow check every tick (fast: just count stats)
        - Deep patrol every _DEEP_PATROL_INTERVAL ticks (5 min)
        """
        tick_count = event.payload.get("tick_count", 0)

        # Shallow: always run (fast)
        await self._shallow_patrol(tick_count)

        # Deep: every N ticks
        if tick_count - self._last_deep_patrol_tick >= _DEEP_PATROL_INTERVAL:
            self._last_deep_patrol_tick = tick_count
            await self._deep_patrol(tick_count)

    async def _shallow_patrol(self, tick_count: int) -> None:
        """Fast health check every tick — log stats only."""
        if not self._scheduler:
            return
        try:
            # Log task counts (non-blocking snapshot)
            stats = await self._get_task_stats()
            if stats["failed"] > 0 or stats["blocked"] > 0:
                logger.info(
                    "Patrol #%d — pending=%d running=%d failed=%d blocked=%d",
                    tick_count,
                    stats["pending"],
                    stats["running"],
                    stats["failed"],
                    stats["blocked"],
                )
        except Exception:
            pass

    async def _deep_patrol(self, tick_count: int) -> None:
        """
        Deep patrol every ~5 minutes:
        1. Failed tasks → auto-create fix tasks
        2. Blocked tasks → try to auto-unblock
        3. Long-running tasks → check for hangs
        4. Send proactive notifications to users
        """
        if not self._scheduler:
            return

        logger.info("=== Deep Patrol #%d ===", tick_count)

        try:
            # 1. Patrol all users with failed tasks
            await self._patrol_failed_tasks()

            # 2. Patrol blocked tasks
            await self._patrol_blocked_tasks()

            # 3. Check for hanging tasks
            await self._patrol_hanging_tasks()

            # 4. Send proactive notifications
            await self._send_proactive_notifications()

        except Exception:
            logger.exception("Deep patrol failed")

    # -------------------------------------------------------------------------
    # Per-category patrol logic
    # -------------------------------------------------------------------------

    async def _patrol_failed_tasks(self) -> None:
        """For each failed task, auto-create a fix subtask if none exists."""
        if not self._scheduler:
            return

        try:
            # Get all failed tasks across all users
            all_tasks = await self._scheduler.get_all_tasks()
            failed_tasks = [t for t in all_tasks if t.status.value == "failed"]

            for task in failed_tasks:
                # Check if a fix task already exists for this failure
                if await self._has_auto_fix_task(task):
                    continue

                # Create auto-fix task
                fix_title = f"[Auto-fix] {task.title}"
                fix_desc = (
                    f"Automatically created to resolve failed task.\n\n"
                    f"Original task: {task.title}\n"
                    f"Error: {task.error or 'Unknown error'}\n\n"
                    f"Steps:\n"
                    f"1. Read the error above\n"
                    f"2. Fix the root cause\n"
                    f"3. Verify the fix works\n"
                    f"4. Re-run or test the original task"
                )

                # Inherit relevant metadata from parent task
                metadata = {
                    "auto_created": True,
                    "parent_task_id": task.task_id,
                    "intent_action": task.metadata.get("intent_action", "fix_bug"),
                    "role": task.metadata.get("role", "executor"),
                    "system_prompt": task.metadata.get("system_prompt"),
                    "org_identity": task.metadata.get("org_identity"),
                    "role_definition": task.metadata.get("role_definition"),
                }

                await self._scheduler.create_macro_task(
                    user_id=task.user_id,
                    title=fix_title,
                    subtasks=[{"title": fix_title, "description": fix_desc}],
                    metadata=metadata,
                )

                logger.info(
                    "Auto-fix task created for failed task %s: %s",
                    task.task_id,
                    task.title,
                )

                # Notify user via Feishu
                await self._enqueue_notification(
                    user_id=task.user_id,
                    message=(
                        f"检测到失败任务: {task.title}\n"
                        f"已自动创建修复任务: {fix_title}\n"
                        f"错误摘要: {task.error[:100] if task.error else '未知'}"
                    ),
                )

        except Exception:
            logger.exception("Failed task patrol error")

    async def _patrol_blocked_tasks(self) -> None:
        """For blocked tasks, try to auto-unblock if dependencies are satisfied."""
        if not self._scheduler:
            return

        try:
            all_tasks = await self._scheduler.get_all_tasks()
            blocked_tasks = [t for t in all_tasks if t.status.value == "blocked"]

            for task in blocked_tasks:
                # Check if all dependencies are now completed
                dep_ids = task.depends_on or []
                if not dep_ids:
                    # No dependencies but still blocked — unblock it
                    await self._scheduler.update_task_status(
                        task.task_id, task.status, error=None
                    )
                    logger.info("Auto-unblocked task %s (no dependencies)", task.task_id)
                    continue

                # Check each dependency
                all_deps_completed = True
                for dep_id in dep_ids:
                    dep_task = await self._scheduler.get_task_by_id(dep_id)
                    if not dep_task or dep_task.status.value != "completed":
                        all_deps_completed = False
                        break

                if all_deps_completed:
                    # Mark as pending (runnable)
                    from hermes_os.task_scheduler import TaskStatus

                    await self._scheduler.update_task_status(
                        task.task_id, TaskStatus.PENDING, error=None
                    )
                    logger.info(
                        "Auto-unblocked task %s (dependencies satisfied)",
                        task.task_id,
                    )

        except Exception:
            logger.exception("Blocked task patrol error")

    async def _patrol_hanging_tasks(self) -> None:
        """Detect tasks running for too long and mark them as potentially hanging."""
        if not self._scheduler:
            return

        try:
            all_tasks = await self._scheduler.get_all_tasks()
            running_tasks = [t for t in all_tasks if t.status.value == "running"]

            # Tasks running > 30 minutes might be hanging
            # (This is advisory — we don't auto-fail them, just notify)
            for task in running_tasks:
                # Check metadata for start time or running duration hint
                max_duration_min = task.metadata.get("max_duration_min", 30)
                # For now, just log — actual hang detection would need
                # task start time tracking (future enhancement)

                if task.metadata.get("warned_hang"):
                    continue

                logger.warning(
                    "Task %s has been running for a while. "
                    "You may want to check its status.",
                    task.task_id,
                )

                # Mark as warned to avoid repeated warnings
                task.metadata["warned_hang"] = True

        except Exception:
            logger.exception("Hanging task patrol error")

    async def _send_proactive_notifications(self) -> None:
        """Send enqueued notifications via Feishu."""
        if not self._pending_notifications:
            return

        notifications = self._pending_notifications[:]
        self._pending_notifications = []

        for user_id, message in notifications:
            try:
                await self._send_feishu_message(user_id, message)
            except Exception:
                logger.exception("Failed to send proactive notification to user %s", user_id)

    # -------------------------------------------------------------------------
    # Task event handlers (TASK_COMPLETED, TASK_FAILED)
    # -------------------------------------------------------------------------

    async def on_task_completed(self, event: Event) -> None:
        """When a task completes, trigger downstream actions."""
        task_id = event.payload.get("task_id")
        user_id = event.payload.get("user_id")
        if not task_id or not user_id:
            return

        logger.info("Task completed: %s", task_id)

        # If this was an auto-fix task, notify user of resolution
        if not self._scheduler:
            return

        try:
            task = await self._scheduler.get_task_by_id(task_id)
            if task and task.metadata.get("auto_created"):
                parent_id = task.metadata.get("parent_task_id")
                await self._enqueue_notification(
                    user_id=user_id,
                    message=(
                        f"✅ 自动修复任务完成: {task.title}\n"
                        f"原始任务已解决。"
                    ),
                )

            # Unblock any tasks waiting on this one
            newly_runnable = await self._scheduler.unblock_dependents(task_id)
            if newly_runnable:
                logger.info("Unblocked %d dependent tasks after %s", len(newly_runnable), task_id)

        except Exception:
            logger.exception("Task completed handler error")

    async def on_task_failed(self, event: Event) -> None:
        """When a task fails, immediately create a fix task."""
        task_id = event.payload.get("task_id")
        user_id = event.payload.get("user_id")
        if not task_id or not user_id:
            return

        logger.info("Task failed: %s", task_id)

        if not self._scheduler:
            return

        try:
            task = await self._scheduler.get_task_by_id(task_id)
            if not task:
                return

            # Skip if already has an auto-fix
            if await self._has_auto_fix_task(task):
                return

            # Immediately create fix task
            fix_title = f"[Auto-fix] {task.title}"
            fix_desc = (
                f"Fix the failed task: {task.title}\n\n"
                f"Error: {task.error or 'Unknown'}\n\n"
                f"1. Analyze the error\n"
                f"2. Fix the root cause\n"
                f"3. Verify and test"
            )

            metadata = {
                "auto_created": True,
                "parent_task_id": task.task_id,
                "intent_action": task.metadata.get("intent_action", "fix_bug"),
                "role": "executor",
                "system_prompt": task.metadata.get("system_prompt"),
            }

            await self._scheduler.create_macro_task(
                user_id=user_id,
                title=fix_title,
                subtasks=[{"title": fix_title, "description": fix_desc}],
                metadata=metadata,
            )

            await self._enqueue_notification(
                user_id=user_id,
                message=(
                    f"⚠️ 任务失败: {task.title}\n"
                    f"已自动创建修复任务\n"
                    f"错误: {task.error[:80] if task.error else '未知'}"
                ),
            )

        except Exception:
            logger.exception("Task failed handler error")

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    async def _get_task_stats(self) -> dict:
        """Get a quick snapshot of task counts by status."""
        if not self._scheduler:
            return {"pending": 0, "running": 0, "failed": 0, "blocked": 0}
        try:
            all_tasks = await self._scheduler.get_all_tasks()
            return {
                "pending": sum(1 for t in all_tasks if t.status.value == "pending"),
                "running": sum(1 for t in all_tasks if t.status.value == "running"),
                "failed": sum(1 for t in all_tasks if t.status.value == "failed"),
                "blocked": sum(1 for t in all_tasks if t.status.value == "blocked"),
            }
        except Exception:
            return {"pending": 0, "running": 0, "failed": 0, "blocked": 0}

    async def _has_auto_fix_task(self, parent_task: Task) -> bool:
        """Check if a fix task already exists for this parent."""
        if not self._scheduler:
            return False
        try:
            all_tasks = await self._scheduler.get_all_tasks()
            return any(
                t.metadata.get("parent_task_id") == parent_task.task_id
                and t.metadata.get("auto_created")
                for t in all_tasks
            )
        except Exception:
            return False

    async def _enqueue_notification(self, user_id: str, message: str) -> None:
        """Add a notification to the queue (sent on next patrol cycle)."""
        self._pending_notifications.append((user_id, message))

    async def _send_feishu_message(self, user_id: str, message: str) -> None:
        """
        Send a Feishu message to a user.
        Uses JarvisInterface for unified outbound communication.
        """
        try:
            from hermes_os.jarvis_interface import JarvisInterface

            jarvis = JarvisInterface()
            await jarvis._feishu.send_message_to_user(user_id=user_id, message=message)
            logger.debug("Proactive Feishu notification sent to %s", user_id)
            return
        except ImportError:
            pass
        except Exception:
            logger.exception("Feishu send failed, falling back to log")

        # Fallback: log
        logger.info("Proactive notification to %s: %s", user_id, message)

    # -------------------------------------------------------------------------
    # Proactive suggestions (called by ChiefAgent or external consumers)
    # -------------------------------------------------------------------------

    async def get_suggestions_for_user(self, user_id: str) -> list[str]:
        """
        Return proactive suggestions for a specific user.
        Used by the event loop or Feishu to push actionable items.
        """
        if not self._scheduler:
            return []

        suggestions: list[str] = []
        try:
            all_tasks = await self._scheduler.get_all_tasks()
            user_tasks = [t for t in all_tasks if t.user_id == user_id]

            failed = [t for t in user_tasks if t.status.value == "failed"][:1]
            for t in failed:
                suggestions.append(
                    f"❌ 失败任务需要关注: {t.title}\n"
                    f"  错误: {t.error[:60] if t.error else '未知'}..."
                )

            blocked = [t for t in user_tasks if t.status.value == "blocked"][:1]
            for t in blocked:
                deps = ", ".join(t.depends_on[:2])
                suggestions.append(f"🔒 任务被阻塞: {t.title}\n  等待: {deps}")

            pending = [t for t in user_tasks if t.status.value == "pending"][:1]
            for t in pending:
                if t.metadata.get("macro_title"):
                    suggestions.append(
                        f"📋 进行中的任务: {t.metadata['macro_title']}\n"
                        f"  待处理: {t.title}"
                    )

        except Exception:
            logger.exception("get_suggestions_for_user error")

        return suggestions[:3]
