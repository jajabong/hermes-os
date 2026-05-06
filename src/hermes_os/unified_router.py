"""UnifiedRouter — single entry point for all routing decisions in Hermes OS.

Pipeline phases:
1. User resolution     → User object (UserRegistry)
2. Memory assembly   → ContextMemory (MemoryHub)
3. Intent parsing     → ParsedIntent (ChiefAgent or keyword-based)
4. Agent matching     → agent name (INTENT_AGENT_MAP)
5. Agent invocation   → AgentResult (matched VerticalAgent)
6. Response storage  → MemoryHub + SessionManager

Replaces the fragmented routing across:
- UserRouter.route() (message enrichment only)
- ChiefAgent.parse_intent() (intent parsing only)
- LaborRegistry (labor dispatch only)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from hermes_os.delegation_protocol import DelegationProtocol
from hermes_os.intent_clarifier import IntentClarifier
from hermes_os.memory_hub import MemoryHub
from hermes_os.persona_assembler import PersonaAssembler
from hermes_os.router import GatewayEvent
from hermes_os.topic_tracker import TopicContext
from hermes_os.vertical_agent import AgentRegistry, AgentRequest, get_agent_registry

if TYPE_CHECKING:
    from hermes_os.user_registry import UserRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Intent → Agent mapping
# ---------------------------------------------------------------------------

INTENT_AGENT_MAP: dict[str, str] = {
    # Vertical agents
    "code": "CodeAgent",
    "fix_bug": "CodeAgent",
    "research": "ResearchAgent",
    "investment": "InvestmentAgent",
    "legal": "LegalAgent",
    "content": "ContentAgent",
    "education": "EducationAgent",
    "deploy": "DeployAgent",
    "review": "ReviewAgent",
    "test": "TestAgent",
    "write_book": "BookPipelineAgent",
    # Default fallback
    "unknown": "ChiefAgent",
}


# ---------------------------------------------------------------------------
# RouteResult
# ---------------------------------------------------------------------------


@dataclass
class RouteResult:
    """Result of a routing decision."""

    intent: str = "unknown"
    agent_name: str = "ChiefAgent"
    is_fallback: bool = True  # True = used ChiefAgent (unknown intent)
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    continuation_context: TopicContext | None = None  # set when user said "接着上次"


# ---------------------------------------------------------------------------
# UnifiedRouter
# ---------------------------------------------------------------------------


class UnifiedRouter:
    """Single entry point for all routing decisions.

    Coordinates:
    - UserRegistry (user resolution)
    - MemoryHub (4-layer memory assembly)
    - ChiefAgent (intent parsing)
    - AgentRegistry (agent dispatch)

    Example:
        router = UnifiedRouter()
        result = await router.route(gateway_event)
        # result.intent = "investment"
        # result.agent_name = "InvestmentAgent"
        # result.message = "投资分析结果..."
    """

    INTENT_PATTERNS: dict[str, list[str]] = {
        "investment": [
            "投资",
            "理财",
            "股票",
            "基金",
            "资产配置",
            "收益率",
            "风险",
            "组合",
            "财务",
        ],
        "legal": [
            "法律",
            "合同",
            "合规",
            "条款",
            "协议",
            "律师",
            "法规",
            "法律咨询",
        ],
        "code": [
            "代码",
            "编程",
            "开发",
            "函数",
            "api",
            "调试",
            "bug",
            "架构",
            "技术",
            "fastapi",
            "python",
            "接口",
            "函数",
            "class ",
            "def ",
            "async def",
            "typescript",
            "javascript",
            "rust",
            "java",
            "golang",
            "写代码",
            "写程序",
        ],
        "content": [
            "写文章",
            "写报告",
            "写文案",
            "写内容",
            "创作",
            "标题",
            "大纲",
            "草稿",
            "写作",
        ],
        "research": [
            "研究",
            "调研",
            "分析报告",
            "市场",
            "竞品",
            "调查",
            "分析",
        ],
        "education": [
            "教育",
            "学习",
            "课程",
            "培训",
            "孩子",
            "老师",
            "作业",
            "升学",
        ],
    }

    def __init__(
        self,
        memory_hub_factory: Callable[[str], MemoryHub] | None = None,
        agent_registry: AgentRegistry | None = None,
        user_registry: "UserRegistry | None" = None,
        topic_tracker_factory: Callable[[str], Any] | None = None,
        delegation_protocol: "DelegationProtocol | None" = None,
    ) -> None:
        self._memory_hub_factory = memory_hub_factory or MemoryHub
        self._agent_registry = agent_registry or get_agent_registry()
        self._user_registry = user_registry  # Lazily initialized in route()
        self._topic_tracker_factory = topic_tracker_factory
        self._delegation_protocol = delegation_protocol

    def classify_intent(self, message: str) -> str:
        """Fast keyword-based intent classification.

        Uses exact substring matching against INTENT_PATTERNS.
        Returns 'unknown' if no pattern matches.
        """
        msg_lower = message.lower()
        for intent, keywords in self.INTENT_PATTERNS.items():
            if any(kw in msg_lower for kw in keywords):
                return intent
        return "unknown"

    def match_agent(self, intent: str) -> str:
        """Match an intent to the best available agent name.

        Falls back to 'ChiefAgent' for unknown intents.
        """
        return INTENT_AGENT_MAP.get(intent, "ChiefAgent")

    async def route(self, event: GatewayEvent) -> RouteResult:
        """Execute the full routing pipeline.

        Pipeline:
        1. Resolve user (UserRegistry)
        2. Assemble memory context (MemoryHub)
        3. Parse intent (ChiefAgent or keyword-based)
        4. Match and invoke agent
        5. Store response (MemoryHub + SessionManager)

        Returns:
            RouteResult with intent, agent_name, is_fallback, and message
        """
        from hermes_os.chief_agent import ChiefAgent
        from hermes_os.session_manager import SessionManager
        from hermes_os.user_registry import UserRegistry

        # Phase 1: Resolve user
        if self._user_registry is None:
            self._user_registry = UserRegistry()
        registry = self._user_registry
        user = await registry.upsert_from_pairing(
            platform=event.platform,
            platform_user_id=event.platform_user_id,
            name=event.user_name,
        )

        # Phase 2: Session management
        sessions = SessionManager()
        session = await sessions.get_or_create(user.user_id)
        await sessions.add_message(user.user_id, "user", event.message)

        # Phase 3: Assemble memory context
        hub = self._memory_hub_factory(user_id=user.user_id)
        await hub.initialize()
        ctx = await hub.get_context()

        # Phase 3b: Assemble user persona from preferences (千人千面核心)
        persona_assembler = PersonaAssembler(user_id=user.user_id, memory_hub=hub)
        persona_block = await persona_assembler.assemble()

        # Phase 3c: Check for continuation intent ("接着上次继续")
        continuation_context = None
        if self._topic_tracker_factory is not None:
            tracker = self._topic_tracker_factory(user_id=user.user_id)
            should_resume, continuation_context = await tracker.detect_and_resume(event.message)

        # Phase 3d: Check if clarification is needed (模糊意图澄清)
        clarification_result = None
        if not continuation_context:
            clarifier = IntentClarifier()
            # Try to use topic context for disambiguation
            if self._topic_tracker_factory is not None:
                tracker = self._topic_tracker_factory(user_id=user.user_id)
                topic_ctx = await tracker.get_current_topic()
                topic_dict = topic_ctx.to_dict() if topic_ctx else None
                clarification_result = clarifier.ask_with_topic_context(
                    event.message,
                    topic_context=topic_dict,
                )
            else:
                clarification_result = clarifier.ask(event.message)

            if clarification_result.needs_clarification:
                # Return clarification question instead of routing to agent
                return RouteResult(
                    intent="clarification_needed",
                    agent_name="ChiefAgent",
                    is_fallback=True,
                    message=clarification_result.question,
                    metadata={
                        "user": user,
                        "session_id": session.session_id if session else "",
                        "clarification_type": clarification_result.clarification_type.value
                        if clarification_result.clarification_type
                        else None,
                        "suggestions": clarification_result.suggestions,
                    },
                )

        # Phase 4: Parse intent
        # Try fast keyword-based first, then ChiefAgent LLM parsing for complex cases
        intent = self.classify_intent(event.message)

        if intent == "unknown":
            # Use ChiefAgent for ambiguous cases
            chief = ChiefAgent()
            try:
                parsed = await chief.parse_intent(event.message, user.user_id)
                intent = (
                    parsed.action.value if hasattr(parsed.action, "value") else str(parsed.action)
                )
            except Exception as e:
                logger.warning("[UnifiedRouter] ChiefAgent.parse_intent failed: %s", e)

        # Phase 5: Match and invoke agent
        agent_name = self.match_agent(intent)
        is_fallback = agent_name == "ChiefAgent"

        # Phase 5b: Check if task should be delegated (HEAVY tasks → TaskScheduler)
        delegation_result = None
        if self._delegation_protocol is not None:
            should_delegate = self._delegation_protocol.should_delegate(event.message)
            if should_delegate:
                try:
                    delegation_result = await self._delegation_protocol.delegate(
                        user=user,
                        message=event.message,
                        intent=intent,
                    )
                except Exception as e:
                    logger.warning("[UnifiedRouter] DelegationProtocol.delegate failed: %s", e)

                if delegation_result and delegation_result.status.value == "delegated":
                    # Task delegated to TaskScheduler — return immediate reply
                    await hub.store(delegation_result.immediate_reply, layer="recent")
                    await sessions.add_message(user.user_id, "assistant", delegation_result.immediate_reply)
                    return RouteResult(
                        intent=intent,
                        agent_name=delegation_result.agent_name,
                        is_fallback=False,
                        message=delegation_result.immediate_reply,
                        metadata={
                            "user": user,
                            "session_id": session.session_id if session else "",
                            "task_id": delegation_result.task_id,
                        },
                    )
                # If delegation returned NOT_DELAGATED (MEDIUM complexity), continue to agent

        result_message = ""
        try:
            agent = self._agent_registry.get_agent(agent_name)
            request = AgentRequest(
                intent=intent,
                params={"message": event.message},
                context={
                    "user": user,
                    "session_id": session.session_id if session else "",
                    "memory_context": ctx,
                    "persona_block": persona_block,
                },
            )
            agent_result = await agent.invoke(request, {"hub": hub, "user": user})
            result_message = agent_result.output

            # Phase 6: Store response
            if agent_result.success:
                await hub.store(result_message, layer="recent")
                await sessions.add_message(user.user_id, "assistant", result_message)
            else:
                # Agent returned failure — fall back to ChiefAgent
                logger.warning(
                    "[UnifiedRouter] Agent '%s' returned failure, falling back: %s",
                    agent_name,
                    agent_result.error,
                )
                is_fallback = True
                agent_name = "ChiefAgent"
                raise ValueError(f"Agent {agent_name} returned success=False")

        except ValueError as e:
            # Agent not found or returned failure — fall back to ChiefAgent
            logger.warning("[UnifiedRouter] Falling back to ChiefAgent: %s", e)
            is_fallback = True
            agent_name = "ChiefAgent"
            try:
                chief = ChiefAgent()
                chief_result = await chief.invoke(
                    AgentRequest(
                        intent=intent,
                        params={"message": event.message},
                        context={"user": user, "persona_block": persona_block},
                    ),
                    {"hub": hub, "user": user},
                )
                result_message = chief_result.output
                # Store fallback response
                await hub.store(result_message, layer="recent")
                await sessions.add_message(user.user_id, "assistant", result_message)
            except Exception as e2:
                logger.error("[UnifiedRouter] ChiefAgent fallback failed: %s", e2)
                result_message = "抱歉，处理您的请求时遇到问题。"

        return RouteResult(
            intent=intent,
            agent_name=agent_name,
            is_fallback=is_fallback,
            message=result_message,
            metadata={
                "user": user,
                "session_id": session.session_id if session else "",
            },
        )
