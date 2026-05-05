"""Agent registry initialization — wires all agents into the VerticalAgent registry."""

from __future__ import annotations

from hermes_os.vertical_agent import get_agent_registry
from hermes_os.agents.chief_agent_adapter import ChiefAgentAdapter
from hermes_os.agents.labor_agent_adapter import LaborAgentAdapter
from hermes_os.labor.content_labor import ContentLabor
from hermes_os.labor.code_labor import CodeLabor
from hermes_os.labor.github_labor import GitHubLabor
from hermes_os.labor.checker_labor import CheckerLabor
from hermes_os.labor.data_labor import DataLabor
from hermes_os.labor.browser_labor import BrowserLabor
from hermes_os.labor.research_labor import ResearchLabor
from hermes_os.labor.format_labor import FormatLabor
from hermes_os.labor.feishu_labor import FeishuLabor
from hermes_os.labor.governance_labor import GovernanceLabor


def initialize_agents() -> None:
    """Register all agents with the global AgentRegistry."""
    registry = get_agent_registry()

    # Coordinator
    registry.register("ChiefAgent", ChiefAgentAdapter())

    # Labor-backed agents
    registry.register("ContentAgent", LaborAgentAdapter(ContentLabor(), "ContentAgent"))
    registry.register("CodeAgent", LaborAgentAdapter(CodeLabor(), "CodeAgent"))
    registry.register("GitHubAgent", LaborAgentAdapter(GitHubLabor(), "GitHubAgent"))
    registry.register("CheckerAgent", LaborAgentAdapter(CheckerLabor(), "CheckerAgent"))
    registry.register("DataAgent", LaborAgentAdapter(DataLabor(), "DataAgent"))
    registry.register("BrowserAgent", LaborAgentAdapter(BrowserLabor(), "BrowserAgent"))
    registry.register("ResearchAgent", LaborAgentAdapter(ResearchLabor(), "ResearchAgent"))
    registry.register("FormatAgent", LaborAgentAdapter(FormatLabor(), "FormatAgent"))
    registry.register("FeishuAgent", LaborAgentAdapter(FeishuLabor(), "FeishuAgent"))
    registry.register("GovernanceAgent", LaborAgentAdapter(GovernanceLabor(), "GovernanceAgent"))
