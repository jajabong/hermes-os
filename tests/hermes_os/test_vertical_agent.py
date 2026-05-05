"""Tests for vertical_agent.py — TDD for VerticalAgent protocol and AgentRegistry."""

from __future__ import annotations

import asyncio

import pytest
from typing import Any

from hermes_os.vertical_agent import (
    AgentRequest,
    AgentResult,
    VerticalAgent,
    AgentRegistry,
    get_agent_registry,
)


class MockAgent:
    """A mock VerticalAgent implementation for testing."""

    def __init__(self, name: str = "mock") -> None:
        self._name = name

    async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
        return AgentResult(success=True, output=f"mock-{self._name}")


class NonConformingAgent:
    """An agent class that does NOT implement VerticalAgent."""

    async def do_something(self, x: int) -> str:
        return "not a valid agent"


# ---------------------------------------------------------------------------
# AgentRequest / AgentResult dataclass tests
# ---------------------------------------------------------------------------

def test_agent_request_dataclass() -> None:
    """AgentRequest should store intent, params, context."""
    req = AgentRequest(
        intent="code",
        params={"task": "write tests"},
        context={"user_id": "u123"},
    )
    assert req.intent == "code"
    assert req.params == {"task": "write tests"}
    assert req.context == {"user_id": "u123"}


def test_agent_result_dataclass() -> None:
    """AgentResult should store success, output, token_usage, error."""
    res = AgentResult(success=True, output="done", token_usage=100)
    assert res.success is True
    assert res.output == "done"
    assert res.token_usage == 100
    assert res.error is None


def test_agent_result_defaults() -> None:
    """AgentResult should have sensible defaults."""
    res = AgentResult(success=False, error="failed")
    assert res.success is False
    assert res.output == ""
    assert res.token_usage == 0
    assert res.error == "failed"


def test_agent_result_with_metadata() -> None:
    """AgentResult should support metadata dict."""
    res = AgentResult(
        success=True,
        output="ok",
        metadata={"agent": "test", "duration_ms": 50},
    )
    assert res.metadata["agent"] == "test"
    assert res.metadata["duration_ms"] == 50


# ---------------------------------------------------------------------------
# VerticalAgent Protocol tests
# ---------------------------------------------------------------------------

def test_vertical_agent_protocol_conformance() -> None:
    """MockAgent should satisfy VerticalAgent Protocol at runtime."""
    agent = MockAgent()
    assert isinstance(agent, VerticalAgent)


def test_non_conforming_agent_fails_protocol_check() -> None:
    """NonConformingAgent should NOT satisfy VerticalAgent Protocol."""
    agent = NonConformingAgent()
    assert not isinstance(agent, VerticalAgent)


# ---------------------------------------------------------------------------
# AgentRegistry tests
# ---------------------------------------------------------------------------

def test_agent_registry_register_and_get() -> None:
    """register() should store agent class; get_agent() should instantiate it."""
    registry = AgentRegistry()
    registry.register("test_agent", MockAgent)

    agent = registry.get_agent("test_agent")
    assert isinstance(agent, MockAgent)


def test_agent_registry_get_unknown_raises() -> None:
    """get_agent() with unregistered name should raise ValueError."""
    registry = AgentRegistry()

    with pytest.raises(ValueError, match="not found"):
        registry.get_agent("nonexistent_agent")


def test_agent_registry_list_agents() -> None:
    """list_agents() should return all registered agent names."""
    registry = AgentRegistry()
    registry.register("agent_a", MockAgent)
    registry.register("agent_b", MockAgent)

    names = registry.list_agents()
    assert "agent_a" in names
    assert "agent_b" in names


def test_agent_registry_singleton() -> None:
    """get_agent_registry() should return the same singleton instance."""
    reg1 = get_agent_registry()
    reg2 = get_agent_registry()
    assert reg1 is reg2


def test_agent_registry_register_same_name_twice() -> None:
    """Registering the same name twice should overwrite the previous registration."""
    registry = AgentRegistry()
    registry.register("dup", MockAgent)

    class AnotherAgent:
        async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
            return AgentResult(success=True, output="another")

    registry.register("dup", AnotherAgent)

    agent = registry.get_agent("dup")
    # Should be the second registration
    result = asyncio.run(
        agent.invoke(
            AgentRequest(intent="x", params={}, context={}),
            {},
        )
    )
    assert result.output == "another"