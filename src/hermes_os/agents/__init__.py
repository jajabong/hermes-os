"""Agents package — VerticalAgent adapters for Hermes OS."""

from hermes_os.agents.chief_agent_adapter import ChiefAgentAdapter
from hermes_os.agents.labor_agent_adapter import LaborAgentAdapter
from hermes_os.agents.registry_initializer import initialize_agents

__all__ = [
    "ChiefAgentAdapter",
    "LaborAgentAdapter",
    "initialize_agents",
]
