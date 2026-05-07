"""ChiefAgent adapter — wraps ChiefAgent as a VerticalAgent (pure dispatcher).

ChiefAgent responsibilities (per第一性原理分析):
- 对接用户: 接收请求，返回结果
- 通用任务: 简单请求直接 dispatch 到功能 Agent
- 分解任务: 复杂任务 → sub-agent (claude -p) + 功能 Agent 协作
- 协调: 组合多个 Agent 的结果返回给用户

ChiefAgent does NOT generate content directly. It dispatches.
"""

from __future__ import annotations

import logging
from typing import Any

from hermes_os.chief_agent import ChiefAgent
from hermes_os.vertical_agent import AgentRequest, AgentResult, get_agent_registry

logger = logging.getLogger(__name__)


# Intent → Functional Agent mapping (单一定义源)
# Mirrors INTENT_AGENT_MAP in intent_constants.py
# unknown intent → ResearchAgent as best-effort fallback
INTENT_TO_AGENT: dict[str, str] = {
    "code": "CodeAgent",
    "fix_bug": "CodeAgent",
    "test": "CodeAgent",
    "review": "CodeAgent",
    "deploy": "CodeAgent",
    "research": "ResearchAgent",
    "investment": "ResearchAgent",
    "legal": "ResearchAgent",
    "education": "ContentAgent",
    "write_book": "ContentAgent",
    "content": "ContentAgent",
    "browser": "BrowserAgent",
    "data": "DataAgent",
    "unknown": "ResearchAgent",  # Best-effort fallback — never return empty acknowledgment
}


class ChiefAgentAdapter:
    """Wraps ChiefAgent to implement the VerticalAgent protocol as a pure dispatcher.

    Responsibilities:
    1. Parse intent via ChiefAgent (parse_intent)
    2. Dispatch to appropriate functional agent
    3. Return the dispatched agent's result
    """

    name = "ChiefAgent"

    async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
        """Dispatch user request to the appropriate functional agent.

        Flow:
        1. Parse intent via ChiefAgent.parse_intent()
        2. Map intent → functional agent name
        3. Get agent from registry
        4. Invoke and return result
        """
        message = request.params.get("message", "")
        user_id = request.context.get("user_id", "unknown")
        scheduler = context.get("scheduler")

        chief = ChiefAgent()

        # Phase 1: Parse intent
        try:
            parsed = await chief.parse_intent(message, user_id)
        except Exception as e:
            logger.warning("[ChiefAgentAdapter] parse_intent failed: %s", e)
            return AgentResult(success=False, error=f"意图解析失败: {e}")

        # Phase 2: Determine target agent
        intent_name = getattr(parsed.action, "value", "unknown") if parsed else "unknown"

        # Try to dispatch to functional agent
        if intent_name in INTENT_TO_AGENT:
            agent_name = INTENT_TO_AGENT[intent_name]
            try:
                registry = get_agent_registry()
                agent = registry.get_agent(agent_name)
                logger.info("[ChiefAgentAdapter] dispatching '%s' → %s", intent_name, agent_name)

                # Invoke the functional agent
                result = await agent.invoke(request, context)
                return result

            except Exception as e:
                logger.warning("[ChiefAgentAdapter] dispatch to %s failed: %s", agent_name, e)
                # Fall through to task DAG creation

        # Phase 3: Fallback — create task DAG for complex/long-running tasks
        if scheduler and parsed and hasattr(parsed, "action"):
            try:
                tasks = await chief.create_task_dag(parsed, user_id, scheduler)
                return AgentResult(
                    success=True,
                    output=f"任务已分解，共 {len(tasks) if tasks else 0} 个子任务",
                    metadata={"intent": parsed, "tasks": tasks},
                )
            except Exception as e:
                logger.warning("[ChiefAgentAdapter] create_task_dag failed: %s", e)

        # Phase 4: Last resort — dispatch to ResearchAgent as best-effort fallback
        # Never return empty acknowledgment to user
        try:
            registry = get_agent_registry()
            agent = registry.get_agent("ResearchAgent")
            logger.info("[ChiefAgentAdapter] best-effort fallback → ResearchAgent")
            return await agent.invoke(request, context)
        except Exception as e:
            logger.error("[ChiefAgentAdapter] even ResearchAgent fallback failed: %s", e)
            return AgentResult(
                success=False,
                error=f"无法处理请求: {e}",
            )
