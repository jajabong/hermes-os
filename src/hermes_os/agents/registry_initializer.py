"""Agent registry initialization — wires all agents into the VerticalAgent registry.

Architecture (第一性原理):
- ChiefAgent = 纯调度器(接收请求 → 分解 → 调度功能Agent)
- 6 个功能 Agent = Research/Code/Browser/Content/Data/Intelligence
- 无领域型 Agent (Investment/Legal/Education...全部归约到功能Agent)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hermes_os.agents.chief_agent_adapter import ChiefAgentAdapter
from hermes_os.agents.intelligence_agent import IntelligenceAgent
from hermes_os.agents.labor_agent_adapter import LaborAgentAdapter
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
from hermes_os.vertical_agent import AgentRequest, AgentResult, get_agent_registry


def initialize_agents() -> None:
    """Register all agents with the global AgentRegistry.

    6 functional agents (按功能分工, 不是按领域):
      ChiefAgent      — 调度中枢
      ResearchAgent  — 研究/分析/实时数据
      CodeAgent      — 代码生成/debug/测试
      ContentAgent   — 写作/文案
      BrowserAgent   — 浏览器自动化
      DataAgent      — 数据处理
      IntelligenceAgent — 实时数据(被ResearchAgent调用)
    """
    registry = get_agent_registry()

    # Coordinator — 纯调度，不生成内容
    registry.register("ChiefAgent", ChiefAgentAdapter())

    # === 6 Functional Agents ===
    registry.register("ResearchAgent", ResearchAgent())
    registry.register("CodeAgent", CodeAgent())
    registry.register("ContentAgent", ContentAgent())
    registry.register("BrowserAgent", LaborAgentAdapter(BrowserLabor(), "BrowserAgent"))
    registry.register("DataAgent", LaborAgentAdapter(DataLabor(), "DataAgent"))
    registry.register("IntelligenceAgent", IntelligenceAgent())  # 被ResearchAgent内部调用

    # === Tool Agents (工具执行器, 执行特定操作) ===
    registry.register("GitHubAgent", LaborAgentAdapter(GitHubLabor(), "GitHubAgent"))
    registry.register("CheckerAgent", LaborAgentAdapter(CheckerLabor(), "CheckerAgent"))
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
                output=result.output,
                token_usage=result.token_usage,
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
                output=result.output,
                token_usage=result.token_usage,
                error=result.error if not result.success else None,
            )
        except Exception as e:
            return AgentResult(success=False, error=str(e))


class ResearchAgent:
    """Research + real-time intelligence agent.

    Embeds IntelligenceAgent to fetch live data (stock prices, news, weather)
    before conducting research. This is the PRIMARY agent for all research,
    analysis, and investment-related queries.

    Flow:
    1. Check if task needs real-time data (stock/news/search)
    2. Fetch via IntelligenceAgent if needed
    3. Execute research via ResearchLabor
    4. Combine and return results
    """

    name = "ResearchAgent"

    async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
        from hermes_os.labor.research_labor import ResearchLabor
        from hermes_os.agents.intelligence_agent import _cached_search

        task = request.params.get("message", "")
        meta = request.params.get("meta", {})
        workspace = context.get("workspace") or "/tmp"
        user_id = context.get("user_id", "anonymous") if context else "anonymous"
        if isinstance(workspace, str):
            workspace = Path(workspace)

        # Step 1: Check if real-time data is needed
        intelligence_context = ""
        needs_realtime = any(kw in task.lower() for kw in [
            "投资", "股票", "股价", "行情", "分析",
            "新闻", "最新", "今日", "当前",
        ])

        if needs_realtime:
            try:
                # Extract potential search queries from task
                search_query = task[:100]
                intel_data = _cached_search(user_id, search_query, max_results=5)
                if intel_data.get("found"):
                    snippets = [r["snippet"] for r in intel_data.get("results", [])]
                    intelligence_context = (
                        "\n\n## 📡 实时情报 (来自 Tavily)\n" +
                        "\n\n".join(f"- {s[:150]}" for s in snippets[:3])
                    )
            except Exception:
                pass  # IntelligenceAgent unavailable, continue without it

        # Step 2: Build enhanced prompt with real-time data
        if intelligence_context:
            enhanced_task = f"{task}\n{intelligence_context}"
        else:
            enhanced_task = task

        # Step 3: Execute research
        try:
            labor = ResearchLabor()
            result = await labor.execute(workspace, enhanced_task, meta)
            return AgentResult(
                success=result.success,
                output=result.output,
                token_usage=result.token_usage,
                error=result.error if not result.success else None,
            )
        except Exception as e:
            return AgentResult(success=False, error=str(e))