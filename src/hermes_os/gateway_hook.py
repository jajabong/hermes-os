"""HermesOS gateway hook — enriches each message with user context and knowledge."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermes_os.agents.registry_initializer import initialize_agents

initialize_agents()

from hermes_os.approval_tracker import ApprovalTracker
from hermes_os.chief_agent import ChiefAgent
from hermes_os.conversation_state import ConversationStateManager
from hermes_os.event_loop import (
    Event,
    EventBus,
    EventType,
    HermesOSEventLoop,
    get_event_bus,
)
from hermes_os.gateway_hook_router import HermesOSRouter
from hermes_os.goal_tracker import GoalTracker
from hermes_os.knowledge_cli import KnowledgeCLI
from hermes_os.org_memory import OrgMemory
from hermes_os.proactive_engine import ProactiveEngine
from hermes_os.router import GatewayEvent
from hermes_os.shard_manager import ShardedStorage, ShardManager
from hermes_os.skill_discovery import SkillDiscovery
from hermes_os.skill_loader import SkillLoader
from hermes_os.task_scheduler import TaskScheduler, TaskStatus
from hermes_os.topic_tracker import TopicTracker
from hermes_os.intent_clarifier import IntentClarifier

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
        self._intent_clarifier: IntentClarifier = IntentClarifier()

        # Track fire-and-forget async tasks to prevent leak
        self._pending_tasks: set[asyncio.Task[None]] = set()

        # Initialize ShardedStorage for silence detection (sync, no event loop needed)
        self._shard_manager = ShardManager()
        self._sharded_storage = ShardedStorage(shard_manager=self._shard_manager)

        # Initialize SkillDiscovery for effectiveness feedback loop (lazy init on first use)
        self._skill_discovery = SkillDiscovery(db_path=self._config.db_path)

        # Wire all dependencies into ProactiveEngine immediately so they are
        # available in both event-loop and standalone/non-event-loop modes
        self._proactive_engine.set_chief_agent(self._chief)
        self._proactive_engine.set_sharded_storage(self._sharded_storage)
        self._proactive_engine.set_skill_discovery(self._skill_discovery)

        if self._config.enable_event_loop:
            self._event_loop = HermesOSEventLoop(
                tick_interval=self._config.event_loop_tick_interval,
                auto_start=False,
            )
            self._register_event_handlers()
            # Start the event loop immediately (it runs forever in background)
            self._spawn(self._event_loop.start())

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
        from hermes_os.jarvis_interface import JarvisInterface

        self._governance_manager = GovernanceManager(
            db_path=self._config.db_path,
            jarvis=JarvisInterface(),
        )
        self._proactive_engine.set_governance_manager(self._governance_manager)
        # Fire the watcher in the background (it runs forever)
        self._spawn(
            self._scheduler.start_watcher(interval_seconds=self._config.scheduler_poll_interval)
        )
        logger.info(
            "TaskScheduler watcher started (poll_interval=%.1fs)",
            self._config.scheduler_poll_interval,
        )

    def _start_github_server(self, port: int) -> None:
        """Start the GitHub webhook FastAPI server in a background thread.

        Uses uvicorn's HTTP proxy mode to avoid asyncio conflict with the
        gateway hook's own event loop.
        """
        import socket
        import threading

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

    def _get_topic_tracker(self, user_id: str) -> TopicTracker:
        """Create a TopicTracker for the given user (stateless, cheap to create)."""
        return TopicTracker(user_id=user_id)

    async def _get_cli(self) -> KnowledgeCLI:
        if self._cli is None:
            self._cli = KnowledgeCLI(db_path=self._config.knowledge_db_path)
            await self._cli.initialize()
        return self._cli

    def _spawn(self, coro) -> None:
        """Launch a fire-and-forget async task, tracking it for cleanup."""
        task = asyncio.create_task(coro)
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

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
            gateway_event_obj.text = ""
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
                self._spawn(self._update_last_seen_bg(user_id_alt))

        # Publish USER_MESSAGE event (non-blocking, even if processing fails)
        asyncio.create_task(self._publish_user_message(context, raw_message))

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
        context["model_tier"] = routed.model_tier
        os.environ["HERMES_OS_MODEL_TIER"] = routed.model_tier

        # Update last_message_at in shard DB for silence detection (non-blocking)
        self._spawn(self._update_last_message_at_bg(routed.user.user_id, raw_message))

        # ChiefAgent: parse intent and auto-create task DAG if high confidence
        await self._process_intent_and_schedule(
            message=raw_message,
            user_id=routed.user.user_id,
            user_id_alt=user_id_alt,
        )

        # Inject per-user context blocks: GoalTracker → TopicTracker → Skills → Persona
        user_id = routed.user.user_id

        # GoalTracker context: enables "继续上次那件事" goal understanding
        if user_id and self._goal_tracker:
            try:
                goal_ctx = await self._goal_tracker.get_active_goal_context(user_id)
                if goal_ctx:
                    gateway_event_obj.text = (
                        f"{gateway_event_obj.text}\n\n<goal_context>\n{goal_ctx}\n</goal_context>"
                    )
            except Exception:
                logger.debug("Failed to inject goal context for user %s", user_id)

        # TopicTracker context: enables "继续上次那件事" topic continuation
        if user_id:
            try:
                tracker = self._get_topic_tracker(user_id)
                should_resume, topic_ctx = await tracker.detect_and_resume(raw_message)
                if should_resume and topic_ctx:
                    topic_block = (
                        f"<last_topic>\n"
                        f"  <topic>{topic_ctx.topic}</topic>\n"
                        f"</last_topic>"
                    )
                    gateway_event_obj.text = f"{gateway_event_obj.text}\n\n{topic_block}"
            except Exception:
                logger.debug("Failed to inject topic context for user %s", user_id)

        # Inject transient skills discovered at runtime (SkillDiscovery feedback loop)
        loader = SkillLoader(skill_discovery=self._skill_discovery)
        fragments, _ = loader.get_all_prompt_fragments(max_skills=5, record_usage=True)
        if fragments:
            gateway_event_obj.text = f"{gateway_event_obj.text}\n\n{fragments}"

        # Inject per-user persona: communication style, detail level, tone
        if user_id:
            from hermes_os.persona_assembler import PersonaAssembler

            assembler = PersonaAssembler(user_id=user_id)
            persona_block = await assembler.assemble()
            gateway_event_obj.text = f"{persona_block.render()}\n\n{gateway_event_obj.text}"

    async def _publish_user_message(self, context: dict, message: str) -> None:
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
            # Fire-and-forget: spawn as task so we don't block the gateway
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
        Enforces a 30s timeout to prevent LLM blocking from stalling message processing.
        """
        try:
            intent = await asyncio.wait_for(
                self._chief.parse_intent(
                    message=message,
                    user_id=user_id,
                ),
                timeout=30.0,
            )

            if not await self._chief.should_auto_create_task(intent):
                # Check for vague message — if IntentClarifier says it's vague, ask user to clarify
                clar = self._intent_clarifier.ask(message)
                if clar.needs_clarification:
                    self._spawn(self._send_clarification_question(user_id, clar.question))
                return

            # Get or create scheduler (uses lazy init + watcher)
            await self._ensure_scheduler()

            tasks = await asyncio.wait_for(
                self._chief.create_task_dag(
                    intent=intent,
                    user_id=user_id,
                    scheduler=self._scheduler,
                ),
                timeout=30.0,
            )

            if tasks:
                logger.info(
                    "ChiefAgent created %d subtasks for intent=%s (confidence=%.2f)",
                    len(tasks),
                    intent.action.value,
                    intent.confidence,
                )

                # Record topic for TopicTracker continuity
                self._spawn(
                    self._record_topic_bg(
                        user_id=user_id,
                        topic=intent.action.value,
                        task_id=tasks[0].task_id if tasks else "",
                        intent_type=intent.action.value,
                    )
                )

                # Delegation feedback: tell the user "收到，我去安排"
                self._spawn(
                    self._send_delegation_feedback(
                        user_id=user_id,
                        task_type=intent.action.value,
                        task_count=len(tasks),
                    )
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
                self._spawn(self._event_bus.publish(event))

        except TimeoutError:
            logger.warning("ChiefAgent intent processing timed out after 30s for user %s", user_id)
        except Exception:
            # Never let ChiefAgent errors block message processing
            logger.debug("ChiefAgent intent processing failed", exc_info=True)

    async def _send_delegation_feedback(
        self,
        user_id: str,
        task_type: str,
        task_count: int,
    ) -> None:
        """Send "收到，我去安排" delegation feedback to user (non-blocking).

        This is the 管家's immediate acknowledgment when a task is created.
        Sends a brief plain-text Feishu message — no card, no buttons.
        """
        from hermes_os.feishu_enhancer import FeishuEnhancer

        action_verbs = {
            "research": "调研",
            "code": "写代码",
            "build": "构建",
            "deploy": "部署",
            "fix_bug": "修复",
            "review": "审查",
            "test": "测试",
            "write_book": "写书",
            "write": "写作",
        }
        verb = action_verbs.get(task_type, "处理")
        count_hint = f"{task_count} 个子任务" if task_count > 1 else "任务"

        message = f"收到，我去{verb}。已创建 {count_hint}，正在调度执行，完成后向您汇报。"

        try:
            feishu = FeishuEnhancer()
            await feishu.send_message_to_user(user_id=user_id, message=message)
        except Exception:
            logger.debug("Delegation feedback send failed for user %s", user_id)

    async def _send_clarification_question(self, user_id: str, question: str) -> None:
        """Send an intent clarification question to the user (non-blocking)."""
        from hermes_os.feishu_enhancer import FeishuEnhancer

        try:
            feishu = FeishuEnhancer()
            await feishu.send_message_to_user(user_id=user_id, message=question)
        except Exception:
            logger.debug("Clarification question send failed for user %s", user_id)

    async def _record_topic_bg(
        self,
        user_id: str,
        topic: str,
        task_id: str,
        intent_type: str,
    ) -> None:
        """Record current topic to LAST_TOPIC.md for session continuity (non-blocking)."""
        try:
            tracker = TopicTracker(user_id=user_id)
            await tracker.record_topic(topic=topic, task_id=task_id, intent=intent_type)
        except Exception:
            logger.debug("TopicTracker record failed for user %s", user_id)

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

            def _update() -> None:
                updb.update_last_seen(user_id_alt)

            await asyncio.to_thread(_update)
        except Exception:
            pass

    async def _update_last_message_at_bg(self, user_id: str, message: str) -> None:
        """Background task to update last_message_at in shard DB (non-blocking)."""
        try:
            if not hasattr(self, "_sharded_storage") or self._sharded_storage is None:
                return
            await self._sharded_storage.add_message(user_id, "user", message)
        except Exception:
            pass

    async def _record_skill_usage_bg(self, loader: SkillLoader, max_skills: int) -> None:
        """Background task to record skill usage for effectiveness feedback loop."""
        try:
            if not hasattr(self, "_skill_discovery") or self._skill_discovery is None:
                return
            skills = loader.load_transient_skills()
            for skill in skills[:max_skills]:
                name = skill.get("name")
                if name:
                    await self._skill_discovery.record_usage(name, success=True)
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

            target_task = tasks[0]  # 最近创建的任务
            if action == "run_now":
                await self._scheduler.update_task_status(
                    target_task.task_id, target_task.status, progress=0.1
                )
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
                    self._spawn(self._event_bus.publish(event))
            elif action == "stop_task":
                await self._scheduler.update_task_status(
                    task_id, TaskStatus.FAILED, error="User intercepted task."
                )
                logger.info("Jarvis: User triggered [Intercept] for task %s", task_id)
                # Publish USER_INTERCEPTED event
                if user_id and self._event_bus:
                    event = Event(
                        type=EventType.USER_INTERCEPTED,
                        payload={"user_id": user_id, "task_id": task_id},
                    )
                    self._spawn(self._event_bus.publish(event))
            elif action == "donate_to_global":
                # User clicked "✅ 贡献" on governance donation card
                content_path = data.get("content_path")
                category = data.get("category", "概念")
                if content_path and self._governance_manager:
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

        # Cancel all pending fire-and-forget tasks
        self._cancel_pending()

    def _cancel_pending(self) -> None:
        """Cancel and clear all tracked pending tasks."""
        for task in self._pending_tasks:
            task.cancel()
        self._pending_tasks.clear()
        logger.debug("Cancelled %d pending tasks", len(self._pending_tasks))
