"""Labor adapter — wraps any LaborInterface-compliant labor as a VerticalAgent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hermes_os.vertical_agent import AgentRequest, AgentResult


class LaborAgentAdapter:
    """Wraps any LaborInterface labor as a VerticalAgent.

    The labor is assumed to already be instantiated.
    """

    def __init__(self, labor: Any, name: str) -> None:
        self.name = name
        self._labor = labor

    async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
        """Execute the wrapped labor and map the result to AgentResult."""
        task = request.params.get("task", "")
        meta = request.params.get("meta", {})
        workspace = Path(context.get("workspace", "/tmp"))

        try:
            result = await self._labor.execute(workspace, task, meta)
            return AgentResult(
                success=result.success,
                output=str(result) if result else "",
                token_usage=getattr(result, "token_usage", 0),
                error=result.error if not result.success else None,
                metadata=result.metadata if hasattr(result, "metadata") else {},
            )
        except Exception as e:
            return AgentResult(success=False, error=str(e))
