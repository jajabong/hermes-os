"""Tests for unified_router.py — TDD for unified routing engine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hermes_os.unified_router import (
    INTENT_AGENT_MAP,
    RouteResult,
    UnifiedRouter,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_gateway_event() -> MagicMock:
    """A mock GatewayEvent."""
    event = MagicMock()
    event.platform = "feishu"
    event.platform_user_id = "ou_123"
    event.message = "帮我分析一下投资组合"
    event.user_name = "张三"
    event.user_id_alt = None
    event.profile = None
    return event


@pytest.fixture
def mock_user() -> MagicMock:
    """A mock User object."""
    user = MagicMock()
    user.user_id = "user_abc123"
    user.name = "张三"
    user.role = "user"
    user.team = "default"
    user.platform = "feishu"
    return user


@pytest.fixture
def mock_context_memory() -> MagicMock:
    """A mock ContextMemory."""
    ctx = MagicMock()
    ctx.identity = {"name": "张三", "role": "user"}
    ctx.preferences = {"communication_style": "brief", "language": "zh"}
    ctx.recent_results = [{"text": "用户上次问了理财"}]
    ctx.long_term_results = []
    ctx.brain_index = None
    return ctx


# ---------------------------------------------------------------------------
# INTENT_AGENT_MAP tests
# ---------------------------------------------------------------------------


def test_intent_agent_map_has_required_intents() -> None:
    """INTENT_AGENT_MAP should cover all major intent types."""
    required = {"code", "research", "fix_bug", "deploy", "write_book"}
    assert required.issubset(INTENT_AGENT_MAP.keys()), (
        f"Missing: {required - INTENT_AGENT_MAP.keys()}"
    )


def test_intent_agent_map_values_are_strings() -> None:
    """All values in INTENT_AGENT_MAP should be agent name strings."""
    for key, value in INTENT_AGENT_MAP.items():
        assert isinstance(key, str)
        assert isinstance(value, str)


# ---------------------------------------------------------------------------
# RouteResult tests
# ---------------------------------------------------------------------------


def test_route_result_defaults() -> None:
    """RouteResult should have sensible defaults."""
    result = RouteResult()
    assert result.intent == "unknown"
    assert result.agent_name == "ChiefAgent"
    assert result.is_fallback is True
    assert result.message == ""


def test_route_result_full() -> None:
    """RouteResult should hold all routing decision fields."""
    result = RouteResult(
        intent="code",
        agent_name="CodeAgent",
        is_fallback=False,
        message="def foo(): pass",
    )
    assert result.intent == "code"
    assert result.agent_name == "CodeAgent"
    assert result.is_fallback is False
    assert "def foo" in result.message


# ---------------------------------------------------------------------------
# UnifiedRouter unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_intent_investment() -> None:
    """Message with '投资'/'理财' should classify as 'investment'."""
    router = UnifiedRouter()
    intent = router.classify_intent("帮我分析一下投资组合")
    assert intent == "investment"


@pytest.mark.asyncio
async def test_classify_intent_code() -> None:
    """Message with '代码'/'编程' should classify as 'code'."""
    router = UnifiedRouter()
    intent = router.classify_intent("帮我写一段 Python 代码")
    assert intent == "code"


@pytest.mark.asyncio
async def test_classify_intent_legal() -> None:
    """Message with '法律'/'合同' should classify as 'legal'."""
    router = UnifiedRouter()
    intent = router.classify_intent("请帮我审查这份合同条款")
    assert intent == "legal"


@pytest.mark.asyncio
async def test_classify_intent_content() -> None:
    """Message with '写'/'创作' should classify as 'content'."""
    router = UnifiedRouter()
    intent = router.classify_intent("帮我写一篇关于AI的文章")
    assert intent == "content"


@pytest.mark.asyncio
async def test_classify_intent_unknown_falls_back() -> None:
    """Generic message with no keyword should classify as 'unknown'."""
    router = UnifiedRouter()
    intent = router.classify_intent("今天天气怎么样")
    assert intent == "unknown"


@pytest.mark.asyncio
async def test_match_agent_for_known_intent() -> None:
    """Known intent should match the configured agent."""
    router = UnifiedRouter()
    agent_name = router.match_agent("code")
    assert agent_name == "CodeAgent"


@pytest.mark.asyncio
async def test_match_agent_for_unknown_intent() -> None:
    """Unknown intent should fall back to ChiefAgent."""
    router = UnifiedRouter()
    agent_name = router.match_agent("unknown")
    assert agent_name == "ChiefAgent"


# ---------------------------------------------------------------------------
# Integration tests (mocked external dependencies)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_full_pipeline(
    mock_gateway_event: MagicMock,
    mock_user: MagicMock,
    mock_context_memory: MagicMock,
) -> None:
    """Full route() pipeline: resolve user → assemble memory → parse intent → match agent."""
    router = UnifiedRouter()

    # Mock internal dependencies
    router._registry = MagicMock()
    router._registry.upsert_from_pairing = AsyncMock(return_value=mock_user)
    router._sessions = MagicMock()
    router._sessions.get_or_create = AsyncMock()
    router._sessions.add_message = AsyncMock()

    # Mock MemoryHub
    mock_hub = MagicMock()
    mock_hub.get_context = AsyncMock(return_value=mock_context_memory)
    mock_hub.initialize = AsyncMock()
    mock_hub.store = AsyncMock()
    mock_hub.get_preferences = AsyncMock(
        return_value={"communication_style": "brief", "language": "zh"}
    )
    mock_hub.get_identity = AsyncMock(return_value={"name": "张三", "role": "user"})
    router._memory_hub_factory = MagicMock(return_value=mock_hub)

    # Mock ChiefAgent for intent parsing
    router._chief = MagicMock()
    mock_parsed_intent = MagicMock()
    mock_parsed_intent.action.value = "investment"
    mock_parsed_intent.raw_text = mock_gateway_event.message
    router._chief.parse_intent = AsyncMock(return_value=mock_parsed_intent)

    # Mock AgentRegistry
    router._agent_registry = MagicMock()
    mock_agent = MagicMock()
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.output = "投资分析结果"
    mock_agent.invoke = AsyncMock(return_value=mock_result)
    router._agent_registry.get_agent = MagicMock(return_value=mock_agent)

    # Execute route
    result = await router.route(mock_gateway_event)

    assert result.intent == "investment"
    assert result.agent_name == "InvestmentAgent"
    assert result.is_fallback is False
    assert "投资分析" in result.message


@pytest.mark.asyncio
async def test_route_unknown_intent_falls_back_to_chief(
    mock_gateway_event: MagicMock,
    mock_user: MagicMock,
    mock_context_memory: MagicMock,
) -> None:
    """When get_agent fails, should fall back to ChiefAgent."""
    router = UnifiedRouter()

    router._registry = MagicMock()
    router._registry.upsert_from_pairing = AsyncMock(return_value=mock_user)
    router._sessions = MagicMock()
    router._sessions.get_or_create = AsyncMock()

    mock_hub = MagicMock()
    mock_hub.get_context = AsyncMock(return_value=mock_context_memory)
    mock_hub.initialize = AsyncMock()
    mock_hub.get_preferences = AsyncMock(
        return_value={"communication_style": "brief", "language": "zh"}
    )
    mock_hub.get_identity = AsyncMock(return_value={"name": "张三", "role": "user"})
    router._memory_hub_factory = MagicMock(return_value=mock_hub)

    # Use a message that triggers "unknown" classification (no keywords)
    mock_gateway_event.message = "今天天气怎么样？"

    # classify_intent returns "unknown" → match_agent maps to "ChiefAgent"
    # But get_agent raises ValueError → fallback to ChiefAgent class directly

    # Mock ChiefAgent.parse_intent to return "unknown"
    router._chief = MagicMock()
    mock_parsed_intent = MagicMock()
    mock_parsed_intent.action.value = "unknown"
    mock_parsed_intent.raw_text = mock_gateway_event.message
    router._chief.parse_intent = AsyncMock(return_value=mock_parsed_intent)

    # Make get_agent("ChiefAgent") raise ValueError (simulating agent not found)
    router._agent_registry = MagicMock()
    router._agent_registry.get_agent = MagicMock(side_effect=ValueError("not found"))

    result = await router.route(mock_gateway_event)

    # Should still get a result (from error handling)
    assert result.agent_name == "ChiefAgent"


@pytest.mark.asyncio
async def test_route_stores_response_in_memory(
    mock_gateway_event: MagicMock,
    mock_user: MagicMock,
    mock_context_memory: MagicMock,
) -> None:
    """After successful agent execution, response should be stored in memory."""
    router = UnifiedRouter()

    router._registry = MagicMock()
    router._registry.upsert_from_pairing = AsyncMock(return_value=mock_user)
    router._sessions = MagicMock()
    router._sessions.get_or_create = AsyncMock()
    router._sessions.add_message = AsyncMock()

    mock_hub = MagicMock()
    mock_hub.get_context = AsyncMock(return_value=mock_context_memory)
    mock_hub.initialize = AsyncMock()
    mock_hub.store = AsyncMock()
    mock_hub.get_preferences = AsyncMock(
        return_value={"communication_style": "brief", "language": "zh"}
    )
    mock_hub.get_identity = AsyncMock(return_value={"name": "张三", "role": "user"})
    router._memory_hub_factory = MagicMock(return_value=mock_hub)

    router._chief = MagicMock()
    mock_parsed_intent = MagicMock()
    mock_parsed_intent.action.value = "content"
    mock_parsed_intent.raw_text = mock_gateway_event.message
    router._chief.parse_intent = AsyncMock(return_value=mock_parsed_intent)

    mock_agent = MagicMock()
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.output = "文章已完成"
    mock_agent.invoke = AsyncMock(return_value=mock_result)
    router._agent_registry = MagicMock()
    router._agent_registry.get_agent = MagicMock(return_value=mock_agent)

    await router.route(mock_gateway_event)

    # Verify memory was updated with the agent's output
    mock_hub.store.assert_called_once()


@pytest.mark.asyncio
async def test_route_returns_route_result(
    mock_gateway_event: MagicMock,
    mock_user: MagicMock,
    mock_context_memory: MagicMock,
) -> None:
    """route() should return a RouteResult with intent and agent info."""
    router = UnifiedRouter()

    router._registry = MagicMock()
    router._registry.upsert_from_pairing = AsyncMock(return_value=mock_user)

    mock_session = MagicMock()
    mock_session.session_id = "sess_123"
    router._sessions = MagicMock()
    router._sessions.get_or_create = AsyncMock(return_value=mock_session)

    mock_hub = MagicMock()
    mock_hub.get_context = AsyncMock(return_value=mock_context_memory)
    mock_hub.initialize = AsyncMock()
    mock_hub.store = AsyncMock()
    mock_hub.get_preferences = AsyncMock(
        return_value={"communication_style": "brief", "language": "zh"}
    )
    mock_hub.get_identity = AsyncMock(return_value={"name": "张三", "role": "user"})
    router._memory_hub_factory = MagicMock(return_value=mock_hub)

    router._chief = MagicMock()

    mock_result = MagicMock()
    mock_result.success = True
    mock_result.output = "代码已完成"

    router._agent_registry = MagicMock()
    mock_agent = MagicMock()
    mock_agent.invoke = AsyncMock(return_value=mock_result)
    router._agent_registry.get_agent = MagicMock(return_value=mock_agent)

    # "帮我分析一下投资组合" → classify_intent returns "investment"
    result = await router.route(mock_gateway_event)

    assert isinstance(result, RouteResult)
    assert result.agent_name == "InvestmentAgent"


@pytest.mark.asyncio
async def test_route_assembles_persona_block_and_passes_to_agent(
    mock_gateway_event: MagicMock,
    mock_user: MagicMock,
) -> None:
    """route() should assemble persona_block from preferences and pass it to agent."""
    router = UnifiedRouter()

    router._registry = MagicMock()
    router._registry.upsert_from_pairing = AsyncMock(return_value=mock_user)

    mock_session = MagicMock()
    mock_session.session_id = "sess_persona"
    router._sessions = MagicMock()
    router._sessions.get_or_create = AsyncMock(return_value=mock_session)

    # Mock MemoryHub with known preferences
    mock_ctx = MagicMock()
    mock_ctx.identity = {"name": "陆总", "role": "executive"}
    mock_ctx.preferences = {
        "communication_style": "brief",
        "detail_level": "medium",
        "tone": "direct",
    }

    mock_hub = MagicMock()
    mock_hub.get_context = AsyncMock(return_value=mock_ctx)
    mock_hub.initialize = AsyncMock()
    mock_hub.get_preferences = AsyncMock(
        return_value={
            "communication_style": "brief",
            "detail_level": "medium",
            "tone": "direct",
        }
    )
    mock_hub.get_identity = AsyncMock(return_value={"name": "陆总", "role": "executive"})
    mock_hub.store = AsyncMock()
    router._memory_hub_factory = MagicMock(return_value=mock_hub)

    # Capture the request passed to agent.invoke
    captured_request = None

    class MockAgent:
        async def invoke(self, request, context):
            nonlocal captured_request
            captured_request = request
            result = MagicMock()
            result.success = True
            result.output = "简洁回复"
            return result

    router._agent_registry = MagicMock()
    router._agent_registry.get_agent = MagicMock(return_value=MockAgent())

    # Message triggers "investment" intent
    result = await router.route(mock_gateway_event)

    # Verify persona_block was assembled and passed in context
    assert captured_request is not None
    assert "persona_block" in captured_request.context
    persona = captured_request.context["persona_block"]
    assert persona.communication_style == "brief"
    assert persona.tone == "direct"
    # Verify render() produces valid XML with owner name
    rendered = persona.render()
    assert "<assistant_persona>" in rendered
    assert "陆总" in rendered
    assert "简洁" in rendered
