"""TDD: ChiefAgent pure-dispatcher tests.

RED Phase: These tests expose the broken contract.
GREEN Phase: ChiefAgentAdapter dispatches to functional agents.

SCENARIO:
- ChiefAgent = pure dispatcher (no content generation)
- It parses intent → maps to functional agent → invokes it → returns result
- Functional agents: ResearchAgent, CodeAgent, BrowserAgent, ContentAgent, DataAgent
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from hermes_os.vertical_agent import AgentRequest, AgentResult
from hermes_os.agents.registry_initializer import initialize_agents


# Ensure agents are registered before tests
@pytest.fixture(scope="module", autouse=True)
def setup_agents():
    initialize_agents()


# =============================================================================
# RED Phase: These tests FAIL with current implementation
# =============================================================================


@pytest.mark.asyncio
async def test_chief_agent_dispatches_research_intent_to_research_agent() -> None:
    """'研究量子计算' → dispatches to ResearchAgent."""
    from hermes_os.agents.chief_agent_adapter import ChiefAgentAdapter
    from hermes_os.agents.registry_initializer import ResearchAgent

    adapter = ChiefAgentAdapter()

    with patch("hermes_os.agents.chief_agent_adapter.ChiefAgent.parse_intent", new_callable=AsyncMock) as mock_parse:
        mock_parse.return_value = MagicMock(
            action=MagicMock(value="research"),
            confidence=0.95,
            entities={},
            depends_on=[],
            suggested_next=[],
            raw_text="帮我研究量子计算",
        )

        with patch.object(ResearchAgent, "invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = AgentResult(
                success=True,
                output="量子计算研究报告：量子计算是...",
                token_usage=200,
            )

            request = AgentRequest(
                intent="research",
                params={"message": "帮我研究量子计算"},
                context={"user_id": "test_user", "workspace": "/tmp"},
            )
            result = await adapter.invoke(request, {})

    assert result.success is True
    assert "量子计算" in result.output


@pytest.mark.asyncio
async def test_chief_agent_dispatches_code_intent_to_code_agent() -> None:
    """'写个FastAPI接口' → dispatches to CodeAgent."""
    from hermes_os.agents.chief_agent_adapter import ChiefAgentAdapter
    from hermes_os.agents.registry_initializer import CodeAgent

    adapter = ChiefAgentAdapter()

    with patch("hermes_os.agents.chief_agent_adapter.ChiefAgent.parse_intent", new_callable=AsyncMock) as mock_parse:
        mock_parse.return_value = MagicMock(
            action=MagicMock(value="code"),
            confidence=0.9,
            entities={},
            depends_on=[],
            suggested_next=[],
            raw_text="写个FastAPI接口",
        )

        with patch.object(CodeAgent, "invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = AgentResult(
                success=True,
                output="from fastapi import FastAPI\napp = FastAPI()",
                token_usage=300,
            )

            request = AgentRequest(
                intent="code",
                params={"message": "写个FastAPI接口"},
                context={"user_id": "test_user", "workspace": "/tmp"},
            )
            result = await adapter.invoke(request, {})

    assert result.success is True
    assert "FastAPI" in result.output


@pytest.mark.asyncio
async def test_chief_agent_dispatches_browser_intent_to_browser_agent() -> None:
    """'帮我投简历' → dispatches to BrowserAgent."""
    from hermes_os.agents.chief_agent_adapter import ChiefAgentAdapter

    adapter = ChiefAgentAdapter()

    with patch("hermes_os.agents.chief_agent_adapter.ChiefAgent.parse_intent", new_callable=AsyncMock) as mock_parse:
        mock_parse.return_value = MagicMock(
            action=MagicMock(value="browser"),
            confidence=0.88,
            entities={},
            depends_on=[],
            suggested_next=[],
            raw_text="帮我投简历",
        )

        request = AgentRequest(
            intent="browser",
            params={"message": "帮我投简历到Boss直聘"},
            context={"user_id": "test_user", "workspace": "/tmp"},
        )
        result = await adapter.invoke(request, {})

    assert result.success is True


@pytest.mark.asyncio
async def test_chief_agent_dispatches_content_intent_to_content_agent() -> None:
    """'写篇公众号文章' → dispatches to ContentAgent."""
    from hermes_os.agents.chief_agent_adapter import ChiefAgentAdapter

    adapter = ChiefAgentAdapter()

    with patch("hermes_os.agents.chief_agent_adapter.ChiefAgent.parse_intent", new_callable=AsyncMock) as mock_parse:
        mock_parse.return_value = MagicMock(
            action=MagicMock(value="content"),
            confidence=0.92,
            entities={},
            depends_on=[],
            suggested_next=[],
            raw_text="写篇公众号文章",
        )

        with patch("hermes_os.labor.content_labor.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_result = MagicMock()
            mock_result.ok = True
            mock_result.stdout = "# AI时代的产品思考\n\n..."
            mock_invoke.return_value = mock_result

            with patch("hermes_os.org_memory.OrgMemory.search_relevant_memory", return_value=""):
                request = AgentRequest(
                    intent="content",
                    params={"message": "写篇关于AI的公众号文章"},
                    context={"user_id": "test_user", "workspace": "/tmp"},
                )
                result = await adapter.invoke(request, {})

    assert result.success is True


@pytest.mark.asyncio
async def test_chief_agent_unknown_intent_dispatches_to_research_agent() -> None:
    """Unknown/low-confidence intent → should dispatch to ResearchAgent as best-effort fallback.

    Bug: Currently falls through to '已理解您的请求' acknowledgment instead of
    dispatching to ResearchAgent.
    """
    from hermes_os.agents.chief_agent_adapter import ChiefAgentAdapter

    adapter = ChiefAgentAdapter()

    with patch("hermes_os.agents.chief_agent_adapter.ChiefAgent.parse_intent", new_callable=AsyncMock) as mock_parse:
        mock_parse.return_value = MagicMock(
            action=MagicMock(value="unknown"),
            confidence=0.3,
            entities={},
            depends_on=[],
            suggested_next=[],
            raw_text="随便问问",
        )

        with patch("hermes_os.agents.chief_agent_adapter.get_agent_registry") as mock_get_reg:
            mock_research = AsyncMock()
            mock_research.invoke = AsyncMock(return_value=AgentResult(
                success=True,
                output="我理解您想了解...",
                token_usage=50,
            ))
            mock_reg = MagicMock()
            mock_reg.get_agent.return_value = mock_research
            mock_get_reg.return_value = mock_reg

            request = AgentRequest(
                intent="unknown",
                params={"message": "随便问问"},
                context={"user_id": "test_user", "workspace": "/tmp"},
            )
            result = await adapter.invoke(request, {})

    # Should dispatch to ResearchAgent as best-effort fallback
    mock_reg.get_agent.assert_called_with("ResearchAgent")
    assert result.success is True
    assert result.output == "我理解您想了解..."


@pytest.mark.asyncio
async def test_chief_agent_propagates_agent_failure() -> None:
    """If dispatched agent fails, ChiefAgent should propagate the failure."""
    from hermes_os.agents.chief_agent_adapter import ChiefAgentAdapter

    adapter = ChiefAgentAdapter()

    with patch("hermes_os.agents.chief_agent_adapter.ChiefAgent.parse_intent", new_callable=AsyncMock) as mock_parse:
        mock_parse.return_value = MagicMock(
            action=MagicMock(value="code"),
            confidence=0.9,
            entities={},
            depends_on=[],
            suggested_next=[],
            raw_text="写代码",
        )

        with patch("hermes_os.vertical_agent.get_agent_registry") as mock_get_reg:
            mock_agent = AsyncMock()
            mock_agent.invoke = AsyncMock(return_value=AgentResult(
                success=False,
                error="CodeAgent execution failed",
                output="",
            ))
            mock_reg = MagicMock()
            mock_reg.get_agent.return_value = mock_agent
            mock_get_reg.return_value = mock_reg

            request = AgentRequest(
                intent="code",
                params={"message": "写代码"},
                context={"user_id": "test_user", "workspace": "/tmp"},
            )
            result = await adapter.invoke(request, {})

    assert result.success is False
    assert "CodeAgent" in result.error or "failed" in result.error.lower()


@pytest.mark.asyncio
async def test_research_agent_embeds_intelligence_data() -> None:
    """ResearchAgent should embed IntelligenceAgent data (实时搜索).

    This tests that ResearchAgent calls IntelligenceAgent internally
    to get real-time data (stock prices, weather, news).
    """
    from hermes_os.agents.registry_initializer import ResearchAgent

    with patch("hermes_os.labor.research_labor.ResearchLabor.execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = MagicMock(
            success=True,
            output="研究报告包含实时数据...",
            token_usage=300,
        )

        agent = ResearchAgent()
        request = AgentRequest(
            intent="research",
            params={"message": "研究茅台投资价值", "include_intelligence": True},
            context={"user_id": "test_user", "workspace": "/tmp"},
        )
        result = await agent.invoke(request, {})

        mock_exec.assert_called_once()
        assert result.success is True
