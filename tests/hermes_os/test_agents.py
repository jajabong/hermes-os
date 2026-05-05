"""Tests for agents/ — TDD for VerticalAgent adapters."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

import pytest

from hermes_os.vertical_agent import AgentRequest, AgentResult
from hermes_os.agents.chief_agent_adapter import ChiefAgentAdapter
from hermes_os.agents.labor_agent_adapter import LaborAgentAdapter


# ---------------------------------------------------------------------------
# ChiefAgentAdapter tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chief_agent_adapter_invoke_returns_agent_result() -> None:
    """ChiefAgentAdapter.invoke() should return an AgentResult."""
    adapter = ChiefAgentAdapter()
    request = AgentRequest(
        intent="unknown",
        params={"message": "帮我分析投资组合"},
        context={"user_id": "u123"},
    )
    result = await adapter.invoke(request, {})
    assert isinstance(result, AgentResult)


@pytest.mark.asyncio
async def test_chief_agent_adapter_wraps_parse_intent() -> None:
    """invoke() should parse intent and return the parsed result."""
    adapter = ChiefAgentAdapter()
    request = AgentRequest(
        intent="code",
        params={"message": "帮我写一个 Python 函数"},
        context={"user_id": "u123"},
    )
    result = await adapter.invoke(request, {})
    assert result.success is True
    assert result.output != ""


@pytest.mark.asyncio
async def test_chief_agent_adapter_handles_empty_message() -> None:
    """Empty message should return failure result."""
    adapter = ChiefAgentAdapter()
    request = AgentRequest(
        intent="unknown",
        params={"message": ""},
        context={"user_id": "u123"},
    )
    result = await adapter.invoke(request, {})
    # Should handle gracefully (not crash)
    assert isinstance(result, AgentResult)


# ---------------------------------------------------------------------------
# LaborAgentAdapter tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_labor_agent_adapter_invoke_returns_agent_result() -> None:
    """LaborAgentAdapter.invoke() should return an AgentResult."""
    mock_labor = MagicMock()
    mock_labor.execute = AsyncMock()
    adapter = LaborAgentAdapter(mock_labor, "MockLabor")
    request = AgentRequest(
        intent="code",
        params={"task": "写一个函数"},
        context={},
    )
    result = await adapter.invoke(request, {})
    assert isinstance(result, AgentResult)


@pytest.mark.asyncio
async def test_labor_agent_adapter_delegates_to_labor() -> None:
    """invoke() should call labor.execute() with correct args."""
    mock_labor = MagicMock()
    mock_labor.execute = AsyncMock()
    adapter = LaborAgentAdapter(mock_labor, "MockLabor")
    request = AgentRequest(
        intent="code",
        params={"task": "写一个函数", "meta": {"key": "value"}},
        context={"workspace": "/tmp"},
    )
    await adapter.invoke(request, {})
    mock_labor.execute.assert_called_once()
    call_args = mock_labor.execute.call_args
    assert call_args[0][1] == "写一个函数"


@pytest.mark.asyncio
async def test_labor_agent_adapter_maps_labor_result_to_agent_result() -> None:
    """LaborResult.success=True → AgentResult(success=True, output=...)."""
    mock_labor = MagicMock()
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.token_usage = 100
    mock_labor.execute = AsyncMock(return_value=mock_result)
    adapter = LaborAgentAdapter(mock_labor, "MockLabor")
    request = AgentRequest(
        intent="content",
        params={"task": "写文章"},
        context={},
    )
    result = await adapter.invoke(request, {})
    assert result.success is True
    assert result.token_usage == 100


@pytest.mark.asyncio
async def test_labor_agent_adapter_maps_labor_failure() -> None:
    """LaborResult.success=False → AgentResult(success=False, error=...)."""
    mock_labor = MagicMock()
    mock_result = MagicMock()
    mock_result.success = False
    mock_result.error = "Execution failed"
    mock_labor.execute = AsyncMock(return_value=mock_result)
    adapter = LaborAgentAdapter(mock_labor, "MockLabor")
    request = AgentRequest(
        intent="code",
        params={"task": "run task"},
        context={},
    )
    result = await adapter.invoke(request, {})
    assert result.success is False
    assert "Execution failed" in (result.error or "")


# ---------------------------------------------------------------------------
# initialize_agents tests
# ---------------------------------------------------------------------------

def test_initialize_agents_registers_all_agents() -> None:
    """initialize_agents() should register ChiefAgent and all LaborAdapters."""
    from hermes_os.agents.registry_initializer import initialize_agents
    from hermes_os.vertical_agent import get_agent_registry

    initialize_agents()
    registry = get_agent_registry()
    agents = registry.list_agents()
    assert "ChiefAgent" in agents
    # Labors that map to agents
    assert "ContentAgent" in agents
    assert "CodeAgent" in agents
