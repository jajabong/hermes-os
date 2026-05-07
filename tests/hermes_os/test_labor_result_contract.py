"""TDD: LaborInterface contract tests.

RED Phase — write tests that expose broken contracts.
GREEN Phase — fix labors to return LaborResult.

ISSUE 1: 9 of 10 labors return `bool`, but LaborInterface requires `LaborResult`.
  → Causes AttributeError in LaborAgentAdapter when accessing .token_usage on bool.
ISSUE 2: LaborAgentAdapter maps LaborResult to AgentResult, but LaborResult has no 'output' field.
  → AgentResult.output ends up as str(bool) = "True" or "False".
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from hermes_os.vertical_agent import AgentRequest, AgentResult
from hermes_os.labor_registry import LaborResult


# =============================================================================
# Helper
# =============================================================================

def make_labor_result(success: bool, token_usage: int = 0, error: str | None = None) -> LaborResult:
    """Create a proper LaborResult for mocking."""
    return LaborResult(success=success, token_usage=token_usage, error=error, metadata={})


# =============================================================================
# RED Phase: These tests FAIL — revealing broken contracts
# =============================================================================

LABORS_UNDER_TEST = [
    ("CodeLabor", "hermes_os.labor.code_labor.CodeLabor"),
    ("ContentLabor", "hermes_os.labor.content_labor.ContentLabor"),
    ("ResearchLabor", "hermes_os.labor.research_labor.ResearchLabor"),
    ("DataLabor", "hermes_os.labor.data_labor.DataLabor"),
    ("CheckerLabor", "hermes_os.labor.checker_labor.CheckerLabor"),
    ("FormatLabor", "hermes_os.labor.format_labor.FormatLabor"),
    ("BrowserLabor", "hermes_os.labor.browser_labor.BrowserLabor"),
    ("GitHubLabor", "hermes_os.labor.github_labor.GitHubLabor"),
    ("FeishuLabor", "hermes_os.labor.feishu_labor.FeishuLabor"),
    ("GovernanceLabor", "hermes_os.labor.governance_labor.GovernanceLabor"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("labor_name,labor_module", LABORS_UNDER_TEST)
async def test_all_labors_return_labor_result_not_bool(labor_name: str, labor_module: str) -> None:
    """Every labor MUST return LaborResult, not bool.

    LaborInterface.execute() contract: -> LaborResult
    Returning bool violates the protocol and causes AttributeError in callers.
    """
    module_path, class_name = labor_module.rsplit(".", 1)
    import importlib
    mod = importlib.import_module(module_path)
    labor_cls = getattr(mod, class_name)

    labor = labor_cls()
    workspace = Path(tempfile.mkdtemp())

    with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
        mock_result = MagicMock()
        mock_result.ok = True
        mock_result.stdout = "done"
        mock_invoke.return_value = mock_result

        with patch("httpx.Client", MagicMock()):
            result = await labor.execute(workspace, "test task", {"stage": "generic"})

    assert isinstance(result, LaborResult), (
        f"{labor_name}.execute() returned {type(result).__name__} ({result!r}), "
        f"expected LaborResult. This violates LaborInterface contract."
    )
    # Verify fields exist (not just bool)
    assert hasattr(result, "success")
    assert hasattr(result, "token_usage")


@pytest.mark.asyncio
async def test_labor_adapter_maps_labor_result_to_agent_result() -> None:
    """LaborAgentAdapter must map LaborResult fields to AgentResult correctly.

    AgentResult has 'output' field; LaborResult does not.
    Adapter should stringify the result appropriately.
    """
    from hermes_os.agents.labor_agent_adapter import LaborAgentAdapter

    mock_labor = MagicMock()
    mock_labor.execute = AsyncMock(return_value=make_labor_result(
        success=True,
        token_usage=100,
    ))
    adapter = LaborAgentAdapter(mock_labor, "TestLabor")

    request = AgentRequest(
        intent="test",
        params={"message": "test task"},
        context={"workspace": "/tmp"},
    )
    result = await adapter.invoke(request, {})

    assert isinstance(result, AgentResult)
    assert result.success is True
    assert result.token_usage == 100


@pytest.mark.asyncio
async def test_labor_adapter_propagates_error_from_labor() -> None:
    """LaborAgentAdapter must propagate labor errors as AgentResult failure."""
    from hermes_os.agents.labor_agent_adapter import LaborAgentAdapter

    class FailingLabor:
        async def execute(self, workspace, task_description, meta):
            raise RuntimeError("Labor execution failed: network error")

    adapter = LaborAgentAdapter(FailingLabor(), "FailingLabor")
    request = AgentRequest(
        intent="test",
        params={"message": "test"},
        context={"workspace": "/tmp"},
    )
    result = await adapter.invoke(request, {})

    assert result.success is False
    assert "Labor execution failed" in result.error


@pytest.mark.asyncio
async def test_code_agent_invokes_code_labor_with_correct_params() -> None:
    """CodeAgent.invoke() must pass message as positional task_description to labor."""
    from hermes_os.agents.registry_initializer import CodeAgent

    with patch("hermes_os.labor.code_labor.CodeLabor.execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = make_labor_result(success=True, token_usage=50)

        agent = CodeAgent()
        request = AgentRequest(
            intent="code",
            params={"message": "写一个快排函数", "meta": {"stage": "M2_CODING"}},
            context={"workspace": "/tmp"},
        )
        result = await agent.invoke(request, {})

        mock_exec.assert_called_once()
        call_args = mock_exec.call_args
        # task_description is the 2nd positional arg
        assert call_args[0][1] == "写一个快排函数"


@pytest.mark.asyncio
async def test_research_agent_invokes_research_labor_with_correct_params() -> None:
    """ResearchAgent.invoke() must pass message as positional task_description to labor."""
    from hermes_os.agents.registry_initializer import ResearchAgent

    with patch("hermes_os.labor.research_labor.ResearchLabor.execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = make_labor_result(success=True, token_usage=80)

        agent = ResearchAgent()
        # Mock IntelligenceAgent so it returns empty (no real-time data)
        with patch("hermes_os.agents.intelligence_agent._cached_search", return_value={"found": False}):
            request = AgentRequest(
                intent="research",
                params={"message": "调研量子计算最新进展"},
                context={"workspace": "/tmp"},
            )
            result = await agent.invoke(request, {})

        mock_exec.assert_called_once()
        call_args = mock_exec.call_args
        # Task should start with original message
        assert call_args[0][1].startswith("调研量子计算最新进展")


@pytest.mark.asyncio
async def test_content_agent_invokes_content_labor_with_correct_params() -> None:
    """ContentAgent.invoke() must pass message as positional task_description to labor."""
    from hermes_os.agents.registry_initializer import ContentAgent

    with patch("hermes_os.labor.content_labor.ContentLabor.execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = make_labor_result(success=True, token_usage=60)

        agent = ContentAgent()
        request = AgentRequest(
            intent="content",
            params={"message": "写一篇关于AI的技术文章"},
            context={"workspace": "/tmp"},
        )
        result = await agent.invoke(request, {})

        mock_exec.assert_called_once()
        call_args = mock_exec.call_args
        assert call_args[0][1] == "写一篇关于AI的技术文章"
