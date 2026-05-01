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
    from hermes_os.workflow_engine import WorkflowResult
    from hermes_os.jarvis_interface import JarvisInterface
    from hermes_os.user_registry import UserRegistry
    from hermes_os.approval_tracker import ApprovalTracker
    from hermes_os.governance_layer import GovernanceManager

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

    def set_user_registry(self, registry: Any) -> None:
        """Inject user registry for scheduled briefing opt-in."""
        self._user_registry = registry

    def set_approval_tracker(self, tracker: Any) -> None:
        """Inject approval tracker for 时效追踪 patrol."""
        self._approval_tracker = tracker

    def set_governance_manager(self, manager: Any) -> None:
        """Inject governance manager for quality content patrol."""
        self._governance_manager = manager

    # -------------------------------------------------------------------------
    # Workflow engine access
    # -------------------------------------------------------------------------

    def _get_workflow_engine(self) -> "WorkflowEngine":
        """Get or create the workflow engine singleton."""
        from hermes_os.workflow_engine import WorkflowEngine
        from hermes_os.hermes_tool_registry import get_tool_registry
        if not hasattr(self, "_workflow_engine"):
            self._workflow_engine = WorkflowEngine()
            registry = get_tool_registry()
            registry.register_all_with(self._workflow_engine)
        return self._workflow_engine

    def _get_jarvis(self) -> "JarvisInterface":
        """Get or create JarvisInterface singleton."""
        from hermes_os.jarvis_interface import JarvisInterface
        if not hasattr(self, "_jarvis"):
            self._jarvis = JarvisInterface()
        return self._jarvis

    async def execute_scheduled_workflow(
        self,
        user_id: str,
        workflow_name: str,
    ) -> "WorkflowResult":
        """
        Execute a scheduled workflow (e.g., daily_briefing) for a user.

        This is the key bridge between CRON_TICK and WorkflowEngine:
        every tick where tick_count % N == 0 (configurable), we run
        the daily briefing for all opted-in users.
        """
        engine = self._get_workflow_engine()
        result = await engine.execute(
            user_id=user_id,
            workflow_name=workflow_name,
            context={"user_id": user_id},
        )

        # Send result to user via Feishu
        if result.success:
            card = result.to_feishu_card(title=f"📋 每日汇报 — {user_id}")
            jarvis = self._get_jarvis()
            try:
                await jarvis.send_card_with_nl(
                    user_id=user_id,
                    title=card["header"]["title"]["content"],
                    content=card["elements"][0]["text"]["content"],
                    actions=[],
                    nl_summary=f"每日汇报: {', '.join(result.results[:2])}",
                )
            except Exception:
                logger.warning("Failed to send daily briefing card to %s", user_id)

        return result

    async def _run_scheduled_daily_briefing(self) -> None:
        """Run daily briefing workflow for all opted-in users."""
        try:
            users = await self._get_users_with_daily_briefing_enabled()
            logger.info("Running scheduled daily briefing for %d users", len(users))
            for user_id in users:
                try:
                    await self.execute_scheduled_workflow(
                        user_id=user_id,
                        workflow_name="daily_briefing",
                    )
                except Exception:
                    logger.exception("Daily briefing failed for user %s", user_id)
        except Exception:
            logger.exception("Failed to run scheduled daily briefing")

    async def _get_users_with_daily_briefing_enabled(self) -> list[str]:
        """Return user IDs who have enabled daily briefing schedule."""
        if not hasattr(self, "_user_registry") or not self._user_registry:
            return []
        try:
            return await self._user_registry.list_users_with_flag("daily_briefing")
        except Exception:
            return []

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
        5. Run scheduled workflows (daily briefing at tick_count % 1440 == 0)
        6. Patrol pending approvals → reminders + auto-expire
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

            # 5. Run scheduled daily briefing (every 1440 ticks = 24h at 60s/tick)
            if tick_count > 0 and tick_count % 1440 == 0:
                await self._run_scheduled_daily_briefing()

            # 6. Patrol pending approvals (时效追踪)
            await self._patrol_pending_approvals()

            # 7. Patrol quality content for governance donation
            await self._patrol_quality_content()

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

    async def _patrol_pending_approvals(self) -> None:
        """
        Check pending approvals for时效追踪:
        1. Send reminders to approvers when reminder_at has passed
        2. Expire approvals past deadline and notify submitter
        """
        if not hasattr(self, "_approval_tracker") or not self._approval_tracker:
            return

        try:
            # 1. Expire approvals past deadline
            expired = await self._approval_tracker.check_expired()
            for record in expired:
                await self._approval_tracker.expire(record.approval_id)
                await self._enqueue_notification(
                    user_id=record.user_id,
                    message=(
                        f"⏰ 审批已超时: {record.title}\n"
                        f"批复人: {record.approver_id}\n"
                        f"超期未批复，已自动过期。"
                    ),
                )
                logger.info(
                    "Approval %s expired for document: %s",
                    record.approval_id,
                    record.title,
                )

            # 2. Send reminders to approvers (deadline approaching)
            reminders = await self._approval_tracker.check_reminders()
            for record in reminders:
                await self._enqueue_notification(
                    user_id=record.approver_id,
                    message=(
                        f"🔔 审批提醒: {record.title}\n"
                        f"提交人: {record.user_id}\n"
                        f"请尽快批复，超期将自动过期。"
                    ),
                )
                logger.info(
                    "Approval reminder sent for: %s (approver=%s)",
                    record.title,
                    record.approver_id,
                )

        except Exception:
            logger.exception("Approval patrol error")

    async def _patrol_quality_content(self) -> None:
        """
        Check for high-quality content in user brain/产出/ACTIVE/ directories
        and prompt users to donate to global_wiki.

        Only checks if GovernanceManager is wired in.
        """
        if not hasattr(self, "_governance_manager") or not self._governance_manager:
            return

        from pathlib import Path

        users_dir = Path.home() / ".hermes" / "users"
        if not users_dir.exists():
            return

        try:
            for user_dir in users_dir.iterdir():
                if not user_dir.is_dir():
                    continue

                output_dir = user_dir / "brain" / "产出" / "ACTIVE"
                if not output_dir.exists():
                    continue

                # Get recent outputs (last 3)
                from hermes_os.brain_updater import BrainUpdater
                updater = BrainUpdater()
                outputs = await updater.read_recent_outputs(output_dir, limit=3)

                for i, content in enumerate(outputs):
                    # Check if already promoted (skip recently checked)
                    score = self._governance_manager._evaluate_content_quality(content)
                    if score < 0.3:
                        continue

                    # Get corresponding output file
                    output_files = sorted(
                        output_dir.glob("*.md"),
                        key=lambda f: f.stat().st_mtime,
                        reverse=True,
                    )
                    if i >= len(output_files):
                        continue

                    output_file = output_files[i]
                    category = self._governance_manager._infer_category(output_file, None)

                    # Prompt donation
                    snippet = content[:200].replace("\n", " ").strip()
                    await self._governance_manager.request_donation(
                        user_id=user_dir.name,
                        content_path=str(output_file),
                        category=category,
                        snippet=snippet,
                        task_id=f"gov_patrol_{output_file.stem}",
                    )
                    logger.info(
                        "Governance patrol: prompted donation for user=%s file=%s",
                        user_dir.name,
                        output_file.name,
                    )
                    break  # Only prompt once per user per patrol cycle

        except Exception:
            logger.exception("Quality content patrol error")

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
