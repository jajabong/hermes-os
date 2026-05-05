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

# Silence detection thresholds (in hours)
SILENCE_GREETING_HOURS = 24   # → friendly greeting card
SILENCE_REMINDER_HOURS = 72   # → goal/task reminder card
SILENCE_URGENT_HOURS = 168    # → urgent outreach (1 week)


class PatrolReport:
    """Result of a deep patrol cycle."""

    def __init__(
        self,
        tick_count: int = 0,
        silence_greeted: int = 0,
        tasks_fixed: int = 0,
        tasks_unblocked: int = 0,
        skills_solidified: int = 0,
        skills_discarded: int = 0,
        suggestions_sent: int = 0,
        approvals_reminded: int = 0,
        errors: list[str] | None = None,
    ) -> None:
        self.tick_count = tick_count
        self.silence_greeted = silence_greeted
        self.tasks_fixed = tasks_fixed
        self.tasks_unblocked = tasks_unblocked
        self.skills_solidified = skills_solidified
        self.skills_discarded = skills_discarded
        self.suggestions_sent = suggestions_sent
        self.approvals_reminded = approvals_reminded
        self.errors = errors or []

    def to_dict(self) -> dict:
        return {
            "tick_count": self.tick_count,
            "silence_greeted": self.silence_greeted,
            "tasks_fixed": self.tasks_fixed,
            "tasks_unblocked": self.tasks_unblocked,
            "skills_solidified": self.skills_solidified,
            "skills_discarded": self.skills_discarded,
            "suggestions_sent": self.suggestions_sent,
            "approvals_reminded": self.approvals_reminded,
            "errors": self.errors,
        }


class ProactiveEngine:
    """
    Autonomous patrol engine — listens to CRON_TICK and drives proactive actions.

    Does NOT run tasks itself — it monitors task state and creates new tasks
    or sends notifications. Actual task execution goes through TaskScheduler.

    Design principle: this engine should never block. All heavy operations
    are fire-and-forget coroutines.
    """

    # Rate limit: max notifications per user per minute
    MAX_NOTIFICATIONS_PER_MINUTE = 5

    def __init__(self, scheduler: TaskScheduler | None = None) -> None:
        self._scheduler = scheduler
        self._org_memory: "OrgMemory | None" = None
        self._last_deep_patrol_tick = 0
        self._pending_notifications: list[tuple[str, str]] = []
        # In-memory rate limiter: user_id → (count, window_start_ts)
        self._notif_rate: dict[str, tuple[int, float]] = {}

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

    def set_sharded_storage(self, storage: Any) -> None:
        """Inject ShardedStorage for silence detection queries."""
        self._sharded_storage = storage

    def set_skill_discovery(self, discovery: Any) -> None:
        """Inject SkillDiscovery for effectiveness feedback loop."""
        self._skill_discovery = discovery

    def set_chief_agent(self, chief: Any) -> None:
        """Inject ChiefAgent for proactive suggestions based on task patterns."""
        self._chief_agent = chief

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

    async def _deep_patrol(self, tick_count: int) -> PatrolReport:
        """
        Deep patrol every ~5 minutes.
        Returns a PatrolReport with counts of all actions taken.
        """
        if not self._scheduler:
            return PatrolReport(tick_count=tick_count, errors=["No scheduler"])

        logger.info("=== Deep Patrol #%d ===", tick_count)

        report = PatrolReport(tick_count=tick_count)

        try:
            # 1. Patrol all users with failed tasks
            report.tasks_fixed = await self._patrol_failed_tasks()

            # 2. Patrol blocked tasks
            report.tasks_unblocked = await self._patrol_blocked_tasks()

            # 3. Check for hanging tasks
            await self._patrol_hanging_tasks()

            # 4. Send proactive notifications
            report.suggestions_sent = await self._send_proactive_notifications()

            # 5. Run scheduled daily briefing (every 1440 ticks = 24h at 60s/tick)
            if tick_count > 0 and tick_count % 1440 == 0:
                await self._run_scheduled_daily_briefing()

            # 6. Patrol pending approvals (时效追踪)
            report.approvals_reminded = await self._patrol_pending_approvals()

            # 7. Patrol quality content for governance donation
            await self._patrol_quality_content()

            # 8. Silence detection + proactive outreach
            greeted, reminded, urgent = await self._detect_and_reach_out()
            report.silence_greeted = greeted + reminded + urgent

            # 9. Skill effectiveness review: solidify or discard transient skills
            solidified, discarded = await self._solidify_skill_cycle()
            report.skills_solidified = solidified
            report.skills_discarded = discarded

            # 10. Proactive suggestions: call ChiefAgent for pattern-based recommendations
            await self._patrol_proactive_suggestions()

            logger.info(
                "Deep Patrol #%d done: fixed=%d unblocked=%d silence=%d "
                "skills_solidified=%d skills_discarded=%d suggestions=%d "
                "approvals_reminded=%d",
                tick_count,
                report.tasks_fixed,
                report.tasks_unblocked,
                report.silence_greeted,
                report.skills_solidified,
                report.skills_discarded,
                report.suggestions_sent,
                report.approvals_reminded,
            )

        except Exception as e:
            logger.exception("Deep patrol failed")
            report.errors.append(str(e))

        return report

    # -------------------------------------------------------------------------
    # Per-category patrol logic
    # -------------------------------------------------------------------------

    async def _patrol_failed_tasks(self) -> int:
        """For each failed task, auto-create a fix subtask if none exists. Returns count created."""
        if not self._scheduler:
            return 0

        created = 0
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
                created += 1

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

        return created

    async def _patrol_blocked_tasks(self) -> int:
        """For blocked tasks, try to auto-unblock if dependencies are satisfied. Returns count."""
        if not self._scheduler:
            return 0

        unblocked = 0
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
                    unblocked += 1
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
                    unblocked += 1
                    logger.info(
                        "Auto-unblocked task %s (dependencies satisfied)",
                        task.task_id,
                    )

        except Exception:
            logger.exception("Blocked task patrol error")

        return unblocked

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

    async def _patrol_pending_approvals(self) -> int:
        """
        Check pending approvals for时效追踪.
        Returns count of notifications sent.
        """
        if not hasattr(self, "_approval_tracker") or not self._approval_tracker:
            return 0

        sent = 0
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
                sent += 1
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
                sent += 1
                logger.info(
                    "Approval reminder sent for: %s (approver=%s)",
                    record.title,
                    record.approver_id,
                )

        except Exception:
            logger.exception("Approval patrol error")

        return sent

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

    async def _send_proactive_notifications(self) -> int:
        """Send enqueued notifications via Feishu. Returns count of successfully sent."""
        if not self._pending_notifications:
            return 0

        notifications = self._pending_notifications[:]
        self._pending_notifications = []

        sent = 0
        for user_id, message in notifications:
            try:
                if await self._send_feishu_message(user_id, message):
                    sent += 1
            except Exception:
                logger.exception("Failed to send proactive notification to user %s", user_id)
        return sent

    # -------------------------------------------------------------------------
    # Silence detection + proactive outreach
    # -------------------------------------------------------------------------

    async def _detect_and_reach_out(self) -> tuple[int, int, int]:
        """Main entry point for silence patrol. Returns (greeted, reminded, urgent)."""
        if not hasattr(self, "_sharded_storage") or not self._sharded_storage:
            return 0, 0, 0

        greeted = reminded = urgent = 0
        try:
            silent_users = await self._detect_silent_users()
            for user in silent_users:
                level = user["silence_level"]
                if level == "greeting":
                    greeted += 1
                elif level == "reminder":
                    reminded += 1
                elif level == "urgent":
                    urgent += 1
                await self.on_user_silent(
                    user["user_id"],
                    user["silence_hours"],
                    user["silence_level"],
                )
        except Exception:
            logger.exception("Silence detection patrol error")

        return greeted, reminded, urgent

    async def _detect_silent_users(self) -> list[dict]:
        """Return list of silent users with their silence level classified.

        Returns:
            List of dicts: [{"user_id": str, "silence_hours": float, "silence_level": str}]
        """
        from datetime import UTC, datetime

        storage = self._sharded_storage
        sm = storage.shard_manager
        silent_users: list[dict] = []

        # Iterate all shard DBs to find users with conversation_states
        all_user_ids: set[str] = set()
        for db_path in sm.all_db_paths():
            # db_path = ~/.hermes/users/{shard}/{user_id}.db
            user_id = db_path.stem  # filename without .db
            all_user_ids.add(user_id)

        for user_id in all_user_ids:
            try:
                state = await storage.get_conversation_state(user_id)
                if not state:
                    continue

                last_msg_at_str = state["last_message_at"] if "last_message_at" in state.keys() else None
                if not last_msg_at_str:
                    continue

                last_msg_at = datetime.fromisoformat(last_msg_at_str)
                silence_hours = (datetime.now(UTC) - last_msg_at).total_seconds() / 3600

                if silence_hours >= SILENCE_URGENT_HOURS:
                    level = "urgent"
                elif silence_hours >= SILENCE_REMINDER_HOURS:
                    level = "reminder"
                elif silence_hours >= SILENCE_GREETING_HOURS:
                    level = "greeting"
                else:
                    continue  # Not silent enough

                silent_users.append({
                    "user_id": user_id,
                    "silence_hours": silence_hours,
                    "silence_level": level,
                })

            except Exception:
                continue

        return silent_users

    async def on_user_silent(
        self,
        user_id: str,
        silence_hours: float,
        silence_level: str,
    ) -> None:
        """Hook called when a silent user is detected.

        Override this method to customize outreach behavior.
        Default: send a Feishu card based on silence level.
        """
        from hermes_os.user_registry import UserRegistry

        # Get user's name for personalization
        name = user_id  # fallback
        try:
            registry = UserRegistry()
            user = await registry.get_user(user_id)
            if user:
                name = user.name or name
        except Exception:
            pass

        if silence_level == "greeting":
            message = self._build_silence_greeting(name, int(silence_hours))
        elif silence_level == "reminder":
            suggestions = await self.get_suggestions_for_user(user_id)
            message = self._build_silence_reminder(name, int(silence_hours), suggestions)
        else:  # urgent
            suggestions = await self.get_suggestions_for_user(user_id)
            message = self._build_silence_reminder(name, int(silence_hours), suggestions)
            message = message + "\n\n⚠️ 您已超过一周未使用Hermes OS，有任何问题请随时联系我。"

        await self._enqueue_notification(user_id, message)

    def _build_silence_greeting(self, name: str, hours: int) -> str:
        """Build a friendly greeting card for a returning user."""
        return (
            f"👋 你好{name}！\n\n"
            f"距离上次对话已有{hours}小时。\n\n"
            f"有什么我可以帮你的吗？\n"
            f"- 💻 代码/调试\n"
            f"- 📊 投资分析\n"
            f"- 📝 内容创作\n"
            f"- 🔍 市场调研\n"
            f"- ❓ 其他问题"
        )

    def _build_silence_reminder(self, name: str, hours: int, pending_tasks: list[str]) -> str:
        """Build a reminder card with the user's pending tasks/goals."""
        lines = [
            f"📌 {name}，距离上次对话已有{hours}小时。",
        ]

        if pending_tasks:
            lines.append("\n待处理事项：")
            for task in pending_tasks[:3]:
                lines.append(f"  • {task}")
        else:
            lines.append("\n目前没有待处理的任务。")

        lines.append("\n有需要随时召唤我！")
        return "\n".join(lines)

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

    async def _send_feishu_message(self, user_id: str, message: str) -> bool:
        """
        Send a Feishu message to a user with rate limiting.
        Returns True if sent, False if rate-limited.
        """
        import time

        now = time.time()
        window = 60.0  # 1-minute window

        # Rate limit check
        if user_id in self._notif_rate:
            count, window_start = self._notif_rate[user_id]
            if now - window_start < window:
                if count >= self.MAX_NOTIFICATIONS_PER_MINUTE:
                    logger.debug("Rate limit exceeded for user %s (%d/min)", user_id, count)
                    return False
                self._notif_rate[user_id] = (count + 1, window_start)
            else:
                # Window expired, reset
                self._notif_rate[user_id] = (1, now)
        else:
            self._notif_rate[user_id] = (1, now)

        try:
            from hermes_os.jarvis_interface import JarvisInterface

            jarvis = JarvisInterface()
            await jarvis._feishu.send_message_to_user(user_id=user_id, message=message)
            logger.debug("Proactive Feishu notification sent to %s", user_id)
            return True
        except ImportError:
            pass
        except Exception:
            logger.exception("Feishu send failed, falling back to log")

        # Fallback: log
        logger.info("Proactive notification to %s: %s", user_id, message)
        return True

    # -------------------------------------------------------------------------
    # Proactive suggestions (called by ChiefAgent or external consumers)
    # -------------------------------------------------------------------------

    async def get_suggestions_for_user(self, user_id: str) -> list[str]:
        """
        Return proactive suggestions for a specific user.
        Used by the event loop or Feishu to push actionable items.

        Combines task-based suggestions (from TaskScheduler) with
        ChiefAgent's proactive suggestions (from conversation patterns).
        """
        suggestions: list[str] = []

        # Task-based suggestions
        if self._scheduler:
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

        # ChiefAgent proactive suggestions (based on conversation patterns)
        if hasattr(self, "_chief_agent") and self._chief_agent and self._scheduler:
            try:
                chief_suggestions = await self._chief_agent.get_proactive_suggestions(
                    user_id=user_id,
                    scheduler=self._scheduler,
                    max_suggestions=3,
                )
                suggestions.extend(chief_suggestions)
            except Exception:
                logger.exception("ChiefAgent proactive suggestions error")

        return suggestions[:3]

    # -------------------------------------------------------------------------
    # Skill effectiveness feedback loop (solidify / discard)
    # -------------------------------------------------------------------------

    async def _solidify_skill_cycle(self) -> tuple[int, int]:
        """Review transient skills and solidify or discard based on effectiveness.

        Calls SkillDiscovery.run_solidify_cycle() which:
        - success_rate >= 0.8 and uses >= 3 → solidify (move to permanent skills/)
        - success_rate < 0.5 and uses >= 2 → discard (remove from _transient/)
        - otherwise → keep_transient

        Returns (solidified_count, discarded_count).
        """
        if not hasattr(self, "_skill_discovery") or not self._skill_discovery:
            return 0, 0

        solidified = discarded = 0
        try:
            result = await self._skill_discovery.run_solidify_cycle()
            if result.get("solidified"):
                solidified = len(result["solidified"])
            if result.get("discarded"):
                discarded = len(result["discarded"])
            if any(result.values()):
                logger.info(
                    "Skill solidify cycle: %s",
                    ", ".join(f"{k}={len(v)}" for k, v in result.items() if v),
                )
        except Exception:
            logger.exception("Skill solidify cycle error")

        return solidified, discarded

    # -------------------------------------------------------------------------
    # ChiefAgent proactive suggestions patrol
    # -------------------------------------------------------------------------

    async def _patrol_proactive_suggestions(self) -> None:
        """Iterate all shard DB users and proactively suggest next actions via ChiefAgent.

        This is the "Chief proactive mode" — analyzes conversation patterns,
        failed/blocked tasks, and goal context to suggest next actions WITHOUT
        the user having to ask.
        """
        if not hasattr(self, "_chief_agent") or not self._chief_agent:
            return
        if not hasattr(self, "_sharded_storage") or not self._sharded_storage:
            return

        try:
            sm = self._sharded_storage.shard_manager
            all_paths = sm.all_db_paths()

            # Batch-fetch all tasks ONCE to avoid O(n*m) scheduler calls
            all_tasks: list = []
            if self._scheduler:
                try:
                    all_tasks = await self._scheduler.get_all_tasks()
                except Exception:
                    pass

            for db_path in all_paths:
                user_id = db_path.stem
                try:
                    suggestions = await self._get_suggestions_for_user_batch(user_id, all_tasks)
                    if suggestions:
                        combined = "\n".join(f"• {s}" for s in suggestions[:3])
                        await self._enqueue_notification(
                            user_id=user_id,
                            message=(
                                f"💡 主动建议：\n{combined}\n\n"
                                f"有什么我可以帮您的吗？"
                            ),
                        )
                except Exception:
                    continue
        except Exception:
            logger.exception("Proactive suggestions patrol error")

    async def _get_suggestions_for_user_batch(self, user_id: str, all_tasks: list) -> list[str]:
        """Get suggestions for a user using pre-fetched task list (batch mode)."""
        suggestions: list[str] = []

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

        # ChiefAgent proactive suggestions
        if hasattr(self, "_chief_agent") and self._chief_agent and self._scheduler:
            try:
                chief_suggestions = await self._chief_agent.get_proactive_suggestions(
                    user_id=user_id,
                    scheduler=self._scheduler,
                    max_suggestions=3,
                )
                suggestions.extend(chief_suggestions)
            except Exception:
                pass

        return suggestions[:3]
