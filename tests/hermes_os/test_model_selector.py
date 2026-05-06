"""TDD tests for model_selector.py - hybrid complexity assessment with MiniMax LLM.

Phase 1: Model complexity routing
P2: LLM evaluation - when keyword match is AMBIGUOUS, use MiniMax to assess complexity
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from hermes_os.model_selector import (
    ModelTier,
    ModelSelector,
    RoutingDecision,
)


# ---------------------------------------------------------------------------
# Test: ModelTier enum
# ---------------------------------------------------------------------------


def test_model_tier_values() -> None:
    """ModelTier should have tiers for MiniMax, blend, and baosi."""
    assert ModelTier.MINIMAX.value == "minimax"
    assert ModelTier.BLEND.value == "blend"
    assert ModelTier.BAOSI.value == "baosi"


# ---------------------------------------------------------------------------
# Test: RoutingDecision dataclass
# ---------------------------------------------------------------------------


def test_routing_decision_fields() -> None:
    """RoutingDecision should have all required fields."""
    decision = RoutingDecision(
        tier=ModelTier.MINIMAX,
        complexity_reason="Keyword match: simple query",
        needs_llm_eval=False,
    )
    assert decision.tier == ModelTier.MINIMAX
    assert "Keyword match" in decision.complexity_reason
    assert decision.needs_llm_eval is False


def test_routing_decision_with_llm() -> None:
    """RoutingDecision should track LLM evaluation results."""
    decision = RoutingDecision(
        tier=ModelTier.BLEND,
        complexity_reason="LLM evaluation: complex multi-step task",
        needs_llm_eval=True,
        llm_confidence=0.85,
    )
    assert decision.tier == ModelTier.BLEND
    assert decision.needs_llm_eval is True
    assert decision.llm_confidence == 0.85


# ---------------------------------------------------------------------------
# Test: select_model - keyword path (SIMPLE)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Now what time is it?",
        "Help me check the weather",
        "what is python?",
    ],
)
@pytest.mark.asyncio
async def test_select_model_keyword_simple(message: str) -> None:
    """Simple keyword matches should route to MiniMax."""
    selector = ModelSelector()
    decision = await selector.select_model(message)
    assert decision.tier == ModelTier.MINIMAX
    assert decision.needs_llm_eval is False


# ---------------------------------------------------------------------------
# Test: select_model - keyword path (COMPLEX)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Help me implement a deep learning framework",
        "debug why the test is failing",
        "Help me develop a chatbot",
    ],
)
@pytest.mark.asyncio
async def test_select_model_keyword_complex(message: str) -> None:
    """Complex keyword matches should route to blend."""
    selector = ModelSelector()
    decision = await selector.select_model(message)
    assert decision.tier == ModelTier.BLEND
    assert decision.needs_llm_eval is False


# ---------------------------------------------------------------------------
# Test: select_model - LLM path (AMBIGUOUS)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_model_llm_eval_ambiguous() -> None:
    """Ambiguous messages should trigger LLM evaluation."""
    selector = ModelSelector()

    # Mock the LLM call
    mock_result = RoutingDecision(
        tier=ModelTier.BLEND,
        complexity_reason="LLM evaluation: complex reasoning required",
        needs_llm_eval=True,
        llm_confidence=0.85,
    )
    selector._evaluate_with_llm = AsyncMock(return_value=mock_result)

    decision = await selector.select_model("Analyze this situation")
    assert decision.needs_llm_eval is True
    assert decision.llm_confidence == 0.85


# ---------------------------------------------------------------------------
# Test: _evaluate_with_llm - MiniMax call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_with_llm_returns_decision() -> None:
    """LLM evaluation should return a RoutingDecision."""
    selector = ModelSelector()

    # Mock the invoke function at source module
    mock_response = MagicMock()
    mock_response.stdout = "complex"

    with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
        mock_invoke.return_value = mock_response
        result = await selector._evaluate_with_llm("How to process this data?")

    assert isinstance(result, RoutingDecision)
    assert result.tier in [ModelTier.MINIMAX, ModelTier.BLEND, ModelTier.BAOSI]


# ---------------------------------------------------------------------------
# Test: get_fallback_chain
# ---------------------------------------------------------------------------


def test_get_fallback_chain_minimax() -> None:
    """MiniMax fallback chain should be: blend -> baosi."""
    selector = ModelSelector()
    chain = selector.get_fallback_chain(ModelTier.MINIMAX)
    assert chain == [ModelTier.BLEND, ModelTier.BAOSI]


def test_get_fallback_chain_blend() -> None:
    """Blend fallback chain should be: minimax -> baosi."""
    selector = ModelSelector()
    chain = selector.get_fallback_chain(ModelTier.BLEND)
    assert chain == [ModelTier.MINIMAX, ModelTier.BAOSI]


def test_get_fallback_chain_baosi() -> None:
    """Baosi is last resort, no fallback."""
    selector = ModelSelector()
    chain = selector.get_fallback_chain(ModelTier.BAOSI)
    assert chain == []


# ---------------------------------------------------------------------------
# Test: select_model - full flow with keyword + LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_model_full_flow_simple() -> None:
    """Full flow: keyword SIMPLE -> MiniMax, no LLM needed."""
    selector = ModelSelector()
    selector._evaluate_with_llm = AsyncMock()

    decision = await selector.select_model("What time is it?")

    assert decision.tier == ModelTier.MINIMAX
    assert decision.needs_llm_eval is False
    selector._evaluate_with_llm.assert_not_called()


@pytest.mark.asyncio
async def test_select_model_full_flow_llm_ambiguous() -> None:
    """Full flow: keyword AMBIGUOUS -> LLM -> determine tier."""
    selector = ModelSelector()

    mock_result = RoutingDecision(
        tier=ModelTier.BLEND,
        complexity_reason="LLM: complex task",
        needs_llm_eval=True,
        llm_confidence=0.85,
    )
    selector._evaluate_with_llm = AsyncMock(return_value=mock_result)

    decision = await selector.select_model("Analyze this situation")

    assert decision.needs_llm_eval is True
    selector._evaluate_with_llm.assert_called_once()


# ---------------------------------------------------------------------------
# Test: LLM prompt format
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_prompt_contains_message() -> None:
    """LLM prompt should include the user's message for context."""
    selector = ModelSelector()

    captured_prompt = None

    async def capture_invoke(prompt, **kwargs):
        nonlocal captured_prompt
        captured_prompt = prompt
        mock_response = MagicMock()
        mock_response.stdout = "simple"
        return mock_response

    with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock, side_effect=capture_invoke):
        await selector._evaluate_with_llm("How to debug this bug?")

    assert "How to debug this bug" in captured_prompt


# ---------------------------------------------------------------------------
# Test: ModelSelector initialization
# ---------------------------------------------------------------------------


def test_model_selector_default_tiers() -> None:
    """ModelSelector should have default tier mappings."""
    selector = ModelSelector()
    assert selector._minimax_tier == ModelTier.MINIMAX
    assert selector._blend_tier == ModelTier.BLEND
    assert selector._baosi_tier == ModelTier.BAOSI
