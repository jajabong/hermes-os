"""HermesOS gateway hook — enriches each message with user context and knowledge."""

from __future__ import annotations

import asyncio
import logging
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from hermes_os.chief_agent import ChiefAgent
from hermes_os.event_loop import (
    Event,
    EventBus,
    EventType,
    HermesOSEventLoop,
    get_event_bus,
)
from hermes_os.gateway_hook_router import HermesOSRouter
from hermes_os.knowledge_cli import KnowledgeCLI
from hermes_os.org_memory import OrgMemory
from hermes_os.proactive_engine import ProactiveEngine
from hermes_os.router import GatewayEvent
from hermes_os.skill_loader import SkillLoader
from hermes_os.task_scheduler import TaskScheduler, TaskStatus
from hermes_os.conversation_state import ConversationStateManager
from hermes_os.approval_tracker import ApprovalTracker
from hermes_os.goal_tracker import GoalTracker

logger = logging.getLogger(__name__)

# Make hermes_state importable from hermes-agent source location
_HERMES_AGENT_SRC = Path.home() / ".hermes" / "hermes-agent"
if str(_HERMES_AGENT_SRC) not in sys.path:
    sys.path.insert(0, str(_HERMES_AGENT_SRC))


@dataclass
class HookConfig:
    """Runtime configuration for the gateway hook."""

    db_path: str = "hermes_os_v2.db"
    knowledge_db_path: str = "hermes_knowledge.db"
    enable_event_loop: bool = True  # Default to True so background tasks run
    event_loop_tick_interval: float = 60.0
    scheduler_poll_interval: float = 30.0  # How often to check for runnable tasks
    github_webhook_port: int | None = 8089  # Set to port to auto-start GitHub webhook server


class HermesOSHook:
    """Gateway hook that injects per-user context before agent:start.

    Events subscribed: agent:start

    This hook runs before hermes-agent processes each message. It:
      1. Creates a HermesOSRouter and routes the incoming event
      2. Replaces the raw message text with the enriched version
         (user block + memory context + knowledge block)
      3. Stores the agent's response in long-term memory
    """

    name: str = "hermes-os"
    events: list[str] = ["agent:start", "command:start"]

    def __init__(self, config: HookConfig | None = None) -> None:
        import os
        logger.info("JARVIS DETECTOR: Loading Hook from %s", os.path.abspath(__file__))
        # 强行覆盖类属性，确保订阅生效
        self.__class__.events = ["agent:start", "command:start"]
        
        self._config = config or HookConfig()
        self._router: HermesOSRouter | None = None
        self._cli: KnowledgeCLI | None = None
        self._event_loop: HermesOSEventLoop | None = None
        self._event_bus: EventBus = get_event_bus()
        self._chief: ChiefAgent = ChiefAgent()
        self._scheduler: TaskScheduler | None = None
        self._proactive_engine: ProactiveEngine = ProactiveEngine()
        self._org_memory: OrgMemory = OrgMemory()
        self._approval_tracker: ApprovalTracker | None = None
        self._goal_tracker: GoalTracker | None = None
        self._conv_state: ConversationStateManager | None = None

        if self._config.enable_event_loop:
            self._event_loop = HermesOSEventLoop(
                tick_interval=self._config.event_loop_tick_interval,
                auto_start=False,
            )
            self._register_event_handlers()
            # Start the event loop immediately (it runs forever in background)
            asyncio.create_task(self._event_loop.start())

        # Start GitHub webhook server if configured (skip in test mode)
        if self._config.github_webhook_port and self._config.enable_event_loop:
            self._start_github_server(self._config.github_webhook_port)

    def _register_event_handlers(self) -> None:
        """Register built-in event handlers for proactive behaviors."""
        if not self._event_loop:
            return

        async def on_tick(event: Event) -> None:
            tick_count = event.payload.get("tick_count", 0)
            logger.debug("CRON_TICK #%d", tick_count)

            # Lazy-start the scheduler watcher on first tick
            await self._ensure_scheduler()

            # Register proactive engine handlers on first tick (one-time wiring)
            if tick_count == 1 and self._scheduler:
                self._proactive_engine.register_with_loop(self._event_loop)
                logger.info("ProactiveEngine wired into event loop")

        self._event_loop.register_handler(EventType.CRON_TICK, on_tick)

    async def _ensure_scheduler(self) -> None:
        """Lazily create and start the scheduler (runs background watcher)."""
        if self._scheduler is not None:
            return
        if self._conv_state is None:
            self._conv_state = ConversationStateManager()
        self._scheduler = TaskScheduler(
            base_dir=None,  # uses default ~/.hermes/users/
            org_memory=self._org_memory,
            conversation_state_manager=self._conv_state,
        )
        # Wire scheduler into proactive engine immediately
        self._proactive_engine.set_scheduler(self._scheduler)
        # Also wire org_memory into proactive engine
        self._proactive_engine.set_org_memory(self._org_memory)
        # Wire user_registry for daily briefing opt-in
        router = await self._get_router()
        self._proactive_engine.set_user_registry(router._user_router.registry)
        # Wire approval tracker for 时效追踪
        self._approval_tracker = ApprovalTracker(db_path=self._config.db_path)
        await self._approval_tracker.initialize()
        self._proactive_engine.set_approval_tracker(self._approval_tracker)
        # Wire goal tracker for 深层目标理解 into ChiefAgent
        self._goal_tracker = GoalTracker(db_path=self._config.db_path)
        await self._goal_tracker.initialize()
        self._chief.set_goal_tracker(self._goal_tracker)
        # Wire governance manager for dual-repo memory + donation patrol
        from hermes_os.governance_layer import GovernanceManager
        self._governance_manager = GovernanceManager(db_path=self._config.db_path)
        self._proactive_engine.set_governance_manager(self._governance_manager)
        # Fire the watcher in the background (it runs forever)
        asyncio.create_task(
            self._scheduler.start_watcher(interval_seconds=self._config.scheduler_poll_interval)
        )
        logger.info("TaskScheduler watcher started (poll_interval=%.1fs)", self._config.scheduler_poll_interval)

    def _start_github_server(self, port: int) -> None:
        """Start the GitHub webhook FastAPI server in a background thread.

        Uses uvicorn's HTTP proxy mode to avoid asyncio conflict with the
        gateway hook's own event loop.
        """
        import threading
        import socket

        # Check if port is already in use before attempting to bind
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
            sock.close()
        except OSError:
            # Port is already in use — skip starting the webhook server
            logger.debug("GitHub webhook port %d already in use, skipping server start", port)
            return

        def run():
            import uvicorn
            from hermes_os.github_monitor import app as github_app

            try:
                uvicorn.run(
                    github_app,
                    host="0.0.0.0",
                    port=port,
                    log_level="warning",
                    access_log=False,
                )
            except SystemExit:
                pass  # uvicorn calls sys.exit(1) on bind failure — ignore

        t = threading.Thread(target=run, daemon=True, name="github-webhook-server")
        t.start()
        logger.info("GitHub webhook server started on port %d", port)

    async def _get_router(self) -> HermesOSRouter:
        if self._router is None:
            self._router = HermesOSRouter(
                db_path=self._config.db_path,
                knowledge_db_path=self._config.knowledge_db_path,
            )
            await self._router.initialize()
        return self._router

    async def _get_cli(self) -> KnowledgeCLI:
        if self._cli is None:
            self._cli = KnowledgeCLI(db_path=self._config.knowledge_db_path)
            await self._cli.initialize()
        return self._cli

    async def handle(self, event_type: str, context: dict) -> None:
        """Enrich the gateway event's message text before agent:start or command:start.

        Mutates ``context["event"].text`` in-place.
        """
        if event_type not in ("agent:start", "command:start"):
            return

        gateway_event_obj = context.get("event")
        if gateway_event_obj is None:
            return

        raw_message = getattr(gateway_event_obj, "text", None)
        if not raw_message:
            return

        # 贾维斯优化：冗余指令拦截 (回复 "Go" 也能触发)
        if raw_message.strip().lower() == "go":
            await self._handle_text_trigger("run_now")
            event_obj.text = ""
            return

        # 贾维斯优化：拦截交互式卡片指令 (e.g., "/card button {...}")
        if raw_message.startswith("/card"):
            await self._handle_interactive_action(raw_message, gateway_event_obj)
            return

        # Look up full user profile from hermes_state if user_id_alt is available
        profile = None
        user_id_alt = context.get("user_id_alt")
        if user_id_alt:
            profile = self._get_user_profile(user_id_alt)
            if profile:
                asyncio.create_task(self._update_last_seen_bg(user_id_alt))

        # Publish USER_MESSAGE event (non-blocking, even if processing fails)
        self._publish_user_message(context, raw_message)

        router = await self._get_router()
        gateway_event = GatewayEvent(
            platform=context.get("platform", ""),
            platform_user_id=context.get("user_id", ""),
            message=raw_message,
            user_name=context.get("user_name", "Unknown"),
            user_id_alt=user_id_alt,
            profile=profile,
        )

        routed = await router.route(gateway_event)
        gateway_event_obj.text = routed.enriched_message
        context["hermes_os_user_id"] = routed.user.user_id
        context["hermes_os_session_id"] = routed.session_id

        # ChiefAgent: parse intent and auto-create task DAG if high confidence
        await self._process_intent_and_schedule(
            message=raw_message,
            user_id=routed.user.user_id,
            user_id_alt=user_id_alt,
        )

        # Inject transient skills discovered at runtime (SkillDiscovery feedback loop)
        loader = SkillLoader()
        fragments = loader.get_all_prompt_fragments(max_skills=5)
        if fragments:
            gateway_event_obj.text = (
                f"{gateway_event_obj.text}\n\n{fragments}"
            )

    def _publish_user_message(self, context: dict, message: str) -> None:
        """Publish a USER_MESSAGE event (non-blocking, never raises)."""
        try:
            event = Event(
                type=EventType.USER_MESSAGE,
                payload={
                    "user_id": context.get("user_id", ""),
                    "platform": context.get("platform", "unknown"),
                    "message": message,
                    "user_name": context.get("user_name", "Unknown"),
                    "user_id_alt": context.get("user_id_alt"),
                    "session_id": context.get("hermes_os_session_id", ""),
                },
            )
            # Fire-and-forget: don't block the gateway
            asyncio.create_task(self._event_bus.publish(event))
        except Exception:
            logger.debug("Failed to publish USER_MESSAGE event")

    async def _process_intent_and_schedule(
        self,
        message: str,
        user_id: str,
        user_id_alt: str | None,
    ) -> None:
        """Parse intent via ChiefAgent and auto-create task DAG if confidence >= 0.75.

        This is the Chief Agent integration: intent understanding → task planning.
        Runs non-blocking (fire-and-forget) so it doesn't slow down message routing.
        """
        try:
            intent = await self._chief.parse_intent(
                message=message,
                user_id=user_id,
            )

            if not await self._chief.should_auto_create_task(intent):
                return

            # Get or create scheduler (uses lazy init + watcher)
            await self._ensure_scheduler()

            tasks = await self._chief.create_task_dag(
                intent=intent,
                user_id=user_id,
                scheduler=self._scheduler,
            )

            if tasks:
                logger.info(
                    "ChiefAgent created %d subtasks for intent=%s (confidence=%.2f)",
                    len(tasks),
                    intent.action.value,
                    intent.confidence,
                )

                # Publish skill discovery event so event loop can react
                event = Event(
                    type=EventType.USER_MESSAGE,
                    payload={
                        "user_id": user_id,
                        "message": message,
                        "intent_action": intent.action.value,
                        "tasks_created": len(tasks),
                        "chief_confidence": intent.confidence,
                    },
                )
                asyncio.create_task(self._event_bus.publish(event))

        except Exception:
            # Never let ChiefAgent errors block message processing
            logger.debug("ChiefAgent intent processing failed", exc_info=True)

    def _get_user_profile(self, user_id_alt: str) -> dict | None:
        """Look up a user profile from hermes_state.UserProfileDB by union_id."""
        try:
            from hermes_state import UserProfileDB
            updb = UserProfileDB()
            return updb.get_profile_by_alt(user_id_alt)
        except Exception:
            return None

    async def _update_last_seen_bg(self, user_id_alt: str) -> None:
        """Background task to update last_seen timestamp (non-blocking)."""
        try:
            from hermes_state import UserProfileDB
            updb = UserProfileDB()
            updb.update_last_seen(user_id_alt)
        except Exception:
            pass

    async def _enrich_message(
        self,
        platform: str,
        platform_user_id: str,
        message: str,
        user_name: str,
    ) -> str:
        """Enrich a raw message with user context and knowledge. Returns enriched text."""
        router = await self._get_router()
        gateway_event = GatewayEvent(
            platform=platform,
            platform_user_id=platform_user_id,
            message=message,
            user_name=user_name,
        )
        routed = await router.route(gateway_event)
        return routed.enriched_message

    async def _handle_text_trigger(self, action: str) -> None:
        """Handle fallback text commands like 'Go'."""
        try:
            await self._ensure_scheduler()
            # 获取最近的一个任务
            tasks = await self._scheduler.get_all_tasks()
            if not tasks:
                return
            
            target_task = tasks[0] # 最近创建的任务
            if action == "run_now":
                await self._scheduler.update_task_status(target_task.task_id, target_task.status, progress=0.1)
                logger.info("Jarvis: Fallback Text Trigger [Go] for task %s", target_task.task_id)
        except Exception:
            logger.debug("Failed to process text trigger", exc_info=True)

    async def _handle_interactive_action(self, message: str, event_obj: Any) -> None:
        """Parse card interaction, update task status, and publish confirmation events."""
        try:
            # Format: "/card button {"hermes_action": "...", "task_id": "..."}"
            json_str = message.replace("/card button ", "").strip()
            data = json.loads(json_str)
            action = data.get("hermes_action")
            task_id = data.get("task_id")

            if not task_id or task_id == "unknown":
                return

            await self._ensure_scheduler()

            # Get task to find user_id for event publishing
            task = await self._scheduler.get_task(task_id)
            user_id = task.user_id if task else None

            if action == "run_now":
                await self._scheduler.update_task_status(task_id, TaskStatus.RUNNING, progress=0.1)
                logger.info("Jarvis: User triggered [Run Now] for task %s", task_id)
                # Publish USER_CONFIRMED event for event-driven wait
                if user_id and self._event_bus:
                    event = Event(
                        type=EventType.USER_CONFIRMED,
                        payload={"user_id": user_id, "task_id": task_id},
                    )
                    asyncio.create_task(self._event_bus.publish(event))
            elif action == "stop_task":
                await self._scheduler.update_task_status(task_id, TaskStatus.FAILED, error="User intercepted task.")
                logger.info("Jarvis: User triggered [Intercept] for task %s", task_id)
                # Publish USER_INTERCEPTED event
                if user_id and self._event_bus:
                    event = Event(
                        type=EventType.USER_INTERCEPTED,
                        payload={"user_id": user_id, "task_id": task_id},
                    )
                    asyncio.create_task(self._event_bus.publish(event))
            elif action == "donate_to_global":
                # User clicked "✅ 贡献" on governance donation card
                content_path = data.get("content_path")
                category = data.get("category", "概念")
                if content_path and self._governance_manager:
                    from hermes_os.router import GatewayEvent
                    router = await self._get_router()
                    # Get user from router or use user_id from task
                    user = None
                    if hasattr(self, "_governance_manager"):
                        result = await self._governance_manager.promote_to_global(
                            user_id=user_id or "unknown",
                            path_to_md=content_path,
                            rules={"category": category},
                        )
                        if result.success:
                            logger.info(
                                "Governance: user %s donated %s to global wiki",
                                user_id,
                                content_path,
                            )
                        else:
                            logger.warning(
                                "Governance donation failed: %s",
                                result.error,
                            )
                logger.info("Jarvis: User triggered [Donate to Global] for path %s", content_path)

            # 清空消息，防止 agent 继续处理该指令
            event_obj.text = ""
        except Exception:
            logger.debug("Failed to parse interactive action", exc_info=True)

    async def close(self) -> None:
        """Release resources."""
        if self._event_loop is not None:
            await self._event_loop.stop()
            self._event_loop = None
            await self._router.close()
            self._router = None
        if self._cli:
            await self._cli.close()
            self._cli = None
        if self._approval_tracker:
            await self._approval_tracker.close()
            self._approval_tracker = None
        if self._goal_tracker:
            await self._goal_tracker.close()
            self._goal_tracker = None
