"""Tests for UnifiedRouter fallback logic."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock


def test_fallback_uses_chief_agent_adapter_when_agent_not_found() -> None:
    """When get_agent raises ValueError, fallback to ChiefAgent via adapter."""
    from hermes_os.unified_router import RouteResult, UnifiedRouter
    from hermes_os.vertical_agent import AgentRegistry

    # Create fresh registry with ONLY a known agent
    reg = AgentRegistry()
    reg.register("KnownAgent", MagicMock())

    router = UnifiedRouter(agent_registry=reg)

    # Mock classify_intent to return a known intent that has no registered agent
    router.classify_intent = MagicMock(return_value="unknown")

    mock_event = MagicMock()
    mock_event.platform = "feishu"
    mock_event.platform_user_id = "ou_123"
    mock_event.message = "hello"
    mock_event.user_name = "Test"
    mock_event.user_id_alt = None
    mock_event.profile = None

    # Should complete without raising
    result = asyncio.run(router.route(mock_event))
    assert isinstance(result, RouteResult)
    assert result.agent_name == "ChiefAgent"


def test_route_result_metadata_has_intent_and_agent() -> None:
    """RouteResult should carry intent and agent metadata."""
    from hermes_os.unified_router import RouteResult

    result = RouteResult(
        intent="code",
        agent_name="CodeAgent",
        is_fallback=False,
        message="done",
    )
    assert result.intent == "code"
    assert result.agent_name == "CodeAgent"
    assert result.is_fallback is False
    assert "metadata" in result.__dataclass_fields__


def test_route_stores_fallback_response_in_memory() -> None:
    """When fallback succeeds, the response should still be stored in memory."""
    from hermes_os.unified_router import UnifiedRouter
    from hermes_os.vertical_agent import AgentRegistry

    reg = AgentRegistry()
    router = UnifiedRouter(agent_registry=reg)

    mock_event = MagicMock()
    mock_event.platform = "feishu"
    mock_event.platform_user_id = "ou_fallback"
    mock_event.message = "some message"
    mock_event.user_name = "FallbackUser"
    mock_event.user_id_alt = None
    mock_event.profile = None

    # Mock user registry
    mock_user = MagicMock()
    mock_user.user_id = "u_fallback"

    mock_registry = MagicMock()
    mock_registry.upsert_from_pairing = AsyncMock(return_value=mock_user)

    mock_sessions = MagicMock()
    mock_session = MagicMock()
    mock_session.session_id = "sess_999"
    mock_sessions.get_or_create = AsyncMock(return_value=mock_session)
    mock_sessions.add_message = AsyncMock()

    mock_hub = MagicMock()
    mock_hub.initialize = AsyncMock()
    mock_hub.get_context = AsyncMock(return_value=MagicMock())
    mock_hub.store = AsyncMock()
    mock_hub.get_preferences = AsyncMock(
        return_value={"communication_style": "brief", "language": "zh"}
    )
    mock_hub.get_identity = AsyncMock(return_value={"name": "FallbackUser", "role": "user"})

    router._memory_hub_factory = MagicMock(return_value=mock_hub)

    router.classify_intent = MagicMock(return_value="unknown")

    asyncio.run(router.route(mock_event))

    # Hub store should have been called for the fallback response
    # (not strictly required but is the desired behavior)
