"""Agent registry initialization — wires all agents into the VerticalAgent registry."""

from __future__ import annotations

from hermes_os.agents.book_pipeline_agent import BookPipelineAgent
from hermes_os.agents.chief_agent_adapter import ChiefAgentAdapter
from hermes_os.agents.deploy_agent import DeployAgent
from hermes_os.agents.education_agent import EducationAgent
from hermes_os.agents.investment_agent import InvestmentAgent
from hermes_os.agents.labor_agent_adapter import LaborAgentAdapter
from hermes_os.agents.legal_agent import LegalAgent
from hermes_os.agents.review_agent import ReviewAgent
from hermes_os.agents.test_agent import TestAgent
from hermes_os.labor.browser_labor import BrowserLabor
from hermes_os.labor.checker_labor import CheckerLabor
from hermes_os.labor.code_labor import CodeLabor
from hermes_os.labor.content_labor import ContentLabor
from hermes_os.labor.data_labor import DataLabor
from hermes_os.labor.feishu_labor import FeishuLabor
from hermes_os.labor.format_labor import FormatLabor
from hermes_os.labor.github_labor import GitHubLabor
from hermes_os.labor.governance_labor import GovernanceLabor
from hermes_os.labor.research_labor import ResearchLabor
from hermes_os.vertical_agent import get_agent_registry


def initialize_agents() -> None:
    """Register all agents with the global AgentRegistry.

    Iron Legion: 10 professional domain agents + 8 tool执行 agents.
    """
    registry = get_agent_registry()

    # Coordinator
    registry.register("ChiefAgent", ChiefAgentAdapter())

    # === Iron Legion: Professional Domain Agents ===
    # These agents have real invoke() implementations with domain-specific prompts
    registry.register("InvestmentAgent", InvestmentAgent())
    registry.register("LegalAgent", LegalAgent())
    registry.register("EducationAgent", EducationAgent())
    registry.register("DeployAgent", DeployAgent())
    registry.register("ReviewAgent", ReviewAgent())
    registry.register("TestAgent", TestAgent())
    registry.register("BookPipelineAgent", BookPipelineAgent())

    # === Execution Agents: Code/Content/Research ===
    # Core execution agents with full invoke() implementations
    registry.register("CodeAgent", CodeAgent())
    registry.register("ContentAgent", ContentAgent())
    registry.register("ResearchAgent", ResearchAgent())

    # === Tool Agents: Labor-backed (工具执行器) ===
    # These wrap tool-specific labors — they are executors, not strategists
    registry.register("GitHubAgent", LaborAgentAdapter(GitHubLabor(), "GitHubAgent"))
    registry.register("CheckerAgent", LaborAgentAdapter(CheckerLabor(), "CheckerAgent"))
    registry.register("DataAgent", LaborAgentAdapter(DataLabor(), "DataAgent"))
    registry.register("BrowserAgent", LaborAgentAdapter(BrowserLabor(), "BrowserAgent"))
    registry.register("FormatAgent", LaborAgentAdapter(FormatLabor(), "FormatAgent"))
    registry.register("FeishuAgent", LaborAgentAdapter(FeishuLabor(), "FeishuAgent"))
    registry.register("GovernanceAgent", LaborAgentAdapter(GovernanceLabor(), "GovernanceAgent"))


class CodeAgent:
    """Code generation and development vertical agent.

    Wraps CodeLabor but with direct invoke() for cleaner dispatch.
    """

    name = "CodeAgent"

    async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
        from hermes_os.labor.code_labor import CodeLabor
        labor = CodeLabor()
        task = request.params.get("message", "")
        meta = request.params.get("meta", {})
        workspace = context.get("workspace") or "/tmp"
        if isinstance(workspace, str):
            workspace = Path(workspace)
        try:
            result = await labor.execute(workspace, task, meta)
            return AgentResult(
                success=result.success,
                output=str(result.output) if hasattr(result, "output") else str(result),
                token_usage=getattr(result, "token_usage", 0),
                error=result.error if not result.success else None,
            )
        except Exception as e:
            return AgentResult(success=False, error=str(e))


class ContentAgent:
    """Content generation vertical agent.

    Wraps ContentLabor with direct invoke().
    """

    name = "ContentAgent"

    async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
        from hermes_os.labor.content_labor import ContentLabor
        labor = ContentLabor()
        task = request.params.get("message", "")
        meta = request.params.get("meta", {})
        workspace = context.get("workspace") or "/tmp"
        if isinstance(workspace, str):
            workspace = Path(workspace)
        try:
            result = await labor.execute(workspace, task, meta)
            return AgentResult(
                success=result.success,
                output=str(result.output) if hasattr(result, "output") else str(result),
                token_usage=getattr(result, "token_usage", 0),
                error=result.error if not result.success else None,
            )
        except Exception as e:
            return AgentResult(success=False, error=str(e))


class ResearchAgent:
    """Research and analysis vertical agent.

    Wraps ResearchLabor with direct invoke().
    """

    name = "ResearchAgent"

    async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
        from hermes_os.labor.research_labor import ResearchLabor
        labor = ResearchLabor()
        task = request.params.get("message", "")
        meta = request.params.get("meta", {})
        workspace = context.get("workspace") or "/tmp"
        if isinstance(workspace, str):
            workspace = Path(workspace)
        try:
            result = await labor.execute(workspace, task, meta)
            return AgentResult(
                success=result.success,
                output=str(result.output) if hasattr(result, "output") else str(result),
                token_usage=getattr(result, "token_usage", 0),
                error=result.error if not result.success else None,
            )
        except Exception as e:
            return AgentResult(success=False, error=str(e))