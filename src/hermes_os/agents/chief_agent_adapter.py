"""ChiefAgent adapter — wraps ChiefAgent as a VerticalAgent."""

from __future__ import annotations

import logging
from typing import Any

from hermes_os.chief_agent import ChiefAgent
from hermes_os.vertical_agent import AgentRequest, AgentResult

logger = logging.getLogger(__name__)


class ChiefAgentAdapter:
    """Wraps ChiefAgent to implement the VerticalAgent protocol.

    ChiefAgent handles:
    - Intent parsing (parse_intent)
    - Task DAG creation (create_task_dag)
    """

    name = "ChiefAgent"

    async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
        """Parse intent via ChiefAgent and optionally create task DAG."""
        message = request.params.get("message", "")
        user_id = request.context.get("user_id", "unknown")
        scheduler = context.get("scheduler")

        chief = ChiefAgent()

        try:
            parsed = await chief.parse_intent(message, user_id)
        except Exception as e:
            logger.warning("[ChiefAgentAdapter] parse_intent failed: %s", e)
            return AgentResult(success=False, error=str(e))

        # If TaskScheduler available and intent is actionable, create DAG
        if scheduler and parsed and hasattr(parsed, "action"):
            try:
                tasks = await chief.create_task_dag(parsed, user_id, scheduler)
                return AgentResult(
                    success=True,
                    output=f"意图已解析: {parsed.action.value}",
                    metadata={"intent": parsed, "tasks": tasks},
                )
            except Exception as e:
                logger.warning("[ChiefAgentAdapter] create_task_dag failed: %s", e)

        return AgentResult(
            success=True,
            output=f"意图已解析: {getattr(parsed, 'action', None)}",
            metadata={"intent": parsed},
        )
