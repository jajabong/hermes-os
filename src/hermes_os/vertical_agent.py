"""VerticalAgent protocol and AgentRegistry — the agent dispatch layer for Hermes OS.

Establishes a shared protocol so any agent (ChiefAgent, labours, new vertical agents)
can be dispatched through a uniform interface without coupling to concrete classes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class AgentRequest:
    """A request dispatched to a VerticalAgent."""

    intent: str  # e.g. "code", "research", "deploy"
    params: dict[str, Any]  # action-specific parameters
    context: dict[str, Any]  # shared context: user_id, team, session_id, ...


@dataclass
class AgentResult:
    """Standard result returned by all VerticalAgents."""

    success: bool
    output: str = ""
    token_usage: int = 0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class VerticalAgent(Protocol):
    """The standard contract for all vertical agents in Hermes OS.

    Any agent that wants to be dispatched through the AgentRegistry
    must implement this protocol.
    """

    async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
        """Execute the agent's task and return a result."""
        ...


class AgentRegistry:
    """Registry for VerticalAgent implementations. Mirrors LaborRegistry pattern."""

    def __init__(self) -> None:
        self._agents: dict[str, type[VerticalAgent]] = {}

    def register(self, name: str, agent_class: type[VerticalAgent]) -> None:
        """Register an agent class with a unique name."""
        self._agents[name] = agent_class
        logger.debug("Registered agent: %s", name)

    def get_agent(self, name: str, **kwargs: Any) -> VerticalAgent:
        """Resolve an agent name to an instance, injecting dependencies via kwargs.

        If a class was registered, instantiates with kwargs.
        If an instance was registered, returns it directly (for complex agents
        that need constructor args or stateful initialization).
        """
        agent_cls_or_instance = self._agents.get(name)
        if not agent_cls_or_instance:
            raise ValueError(f"Agent '{name}' not found in registry.")

        # If it's already an instance (not a type), return directly
        if not isinstance(agent_cls_or_instance, type):
            return agent_cls_or_instance

        # Otherwise it's a class — instantiate with kwargs
        try:
            return agent_cls_or_instance(**kwargs)  # type: ignore
        except TypeError as e:
            logger.error("Failed to instantiate agent %s: %s", name, e)
            raise

    def unregister(self, name: str) -> bool:
        """Remove an agent from the registry.

        Returns:
            True if the agent was removed, False if it wasn't registered.
        """
        if name in self._agents:
            del self._agents[name]
            logger.debug("Unregistered agent: %s", name)
            return True
        return False

    def list_agents(self) -> list[str]:
        """Return a list of all registered agent names."""
        return list(self._agents.keys())


_global_agent_registry = AgentRegistry()


def get_agent_registry() -> AgentRegistry:
    """Get the global singleton AgentRegistry."""
    return _global_agent_registry
