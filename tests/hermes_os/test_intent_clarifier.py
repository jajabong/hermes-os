"""TDD tests for intent_clarifier.py — fuzzy intent clarification.

Phase 1: 千人千面管家
P1: 意图澄清 — 当用户说模糊的话时，管家先问清楚再做
"""

from __future__ import annotations

from hermes_os.intent_clarifier import (
    ClarificationResult,
    ClarificationType,
    IntentClarifier,
)

# ---------------------------------------------------------------------------
# Test: ClarificationResult
# ---------------------------------------------------------------------------


def test_clarification_result_fields() -> None:
    result = ClarificationResult(
        needs_clarification=True,
        clarification_type=ClarificationType.VAGUE_SUBJECT,
        question="您想让我看什么？",
        suggestions=["合同", "报告"],
    )
    assert result.needs_clarification is True
    assert result.clarification_type == ClarificationType.VAGUE_SUBJECT
    assert "看" in result.question


def test_clarification_result_not_needed() -> None:
    result = ClarificationResult(
        needs_clarification=False,
    )
    assert result.needs_clarification is False


# ---------------------------------------------------------------------------
# Test: ClarificationType enum
# ---------------------------------------------------------------------------


def test_clarification_types() -> None:
    assert ClarificationType.VAGUE_SUBJECT.value == "vague_subject"
    assert ClarificationType.VAGUE_ACTION.value == "vague_action"


# ---------------------------------------------------------------------------
# Test: is_vague — vague action (动词一下)
# ---------------------------------------------------------------------------


def test_is_vague_action_standalone() -> None:
    """Standalone 动词一下 at end of message → vague."""
    clarifier = IntentClarifier()
    assert clarifier.is_vague("处理一下") is True
    assert clarifier.is_vague("弄一下") is True
    assert clarifier.is_vague("搞一下") is True


def test_is_vague_action_with_object() -> None:
    """动词一下 + object → NOT vague."""
    clarifier = IntentClarifier()
    assert clarifier.is_vague("处理一下这个bug") is False
    assert clarifier.is_vague("弄一下文件") is False


def test_is_vague_action_with_punctuation() -> None:
    """动词一下 + punctuation → vague."""
    clarifier = IntentClarifier()
    assert clarifier.is_vague("处理一下，") is True
    assert clarifier.is_vague("弄一下？") is True


# ---------------------------------------------------------------------------
# Test: is_vague — vague subject
# ---------------------------------------------------------------------------


def test_is_vague_subject_standalone() -> None:
    """Demonstrative + punctuation/particle → vague."""
    clarifier = IntentClarifier()
    assert clarifier.is_vague("这个") is True
    assert clarifier.is_vague("那个") is True
    assert clarifier.is_vague("这个呢") is True
    assert clarifier.is_vague("那个啊") is True
    assert clarifier.is_vague("它吗") is True


def test_is_vague_subject_with_noun() -> None:
    """Demonstrative + noun → NOT vague (it's a complete subject)."""
    clarifier = IntentClarifier()
    assert clarifier.is_vague("这个合同") is False
    assert clarifier.is_vague("那个问题") is False


# ---------------------------------------------------------------------------
# Test: is_vague — clear patterns
# ---------------------------------------------------------------------------


def test_is_not_vague_simple_greeting() -> None:
    """Simple greetings/acknowledgements → not vague."""
    clarifier = IntentClarifier()
    assert clarifier.is_vague("你好") is False
    assert clarifier.is_vague("好的") is False
    assert clarifier.is_vague("好") is False
    assert clarifier.is_vague("谢谢") is False
    assert clarifier.is_vague("知道了") is False


def test_is_not_vague_clear_command() -> None:
    """Clear commands with specific object → not vague."""
    clarifier = IntentClarifier()
    assert clarifier.is_vague("帮我看看这个合同") is False
    assert clarifier.is_vague("处理一下这个bug") is False


# ---------------------------------------------------------------------------
# Test: ask() — generates clarification question
# ---------------------------------------------------------------------------


def test_ask_vague_action_returns_question() -> None:
    """ask() for vague action → returns question."""
    clarifier = IntentClarifier()
    result = clarifier.ask("处理一下")
    assert result.needs_clarification is True
    assert result.clarification_type == ClarificationType.VAGUE_ACTION
    assert "处理" in result.question


def test_ask_vague_subject_returns_question() -> None:
    """ask() for vague subject → returns question."""
    clarifier = IntentClarifier()
    result = clarifier.ask("这个")
    assert result.needs_clarification is True
    assert result.clarification_type == ClarificationType.VAGUE_SUBJECT
    assert "看" in result.question or "什么" in result.question


def test_ask_clear_intent_no_question() -> None:
    """ask() for clear intent → no clarification needed."""
    clarifier = IntentClarifier()
    result = clarifier.ask("帮我分析这份投资报告")
    assert result.needs_clarification is False


def test_ask_greeting_no_question() -> None:
    """ask() for greeting → no clarification needed."""
    clarifier = IntentClarifier()
    result = clarifier.ask("你好")
    assert result.needs_clarification is False


# ---------------------------------------------------------------------------
# Test: ask_with_topic_context
# ---------------------------------------------------------------------------


def test_ask_with_topic_context_disambiguates_zhege() -> None:
    """With topic context, vague subject gets disambiguated suggestions."""
    clarifier = IntentClarifier()
    result = clarifier.ask_with_topic_context(
        "这个有什么问题吗",
        topic_context={"topic": "投资组合分析", "task_id": "task_1", "intent": "investment"},
    )
    assert result.needs_clarification is True
    assert len(result.suggestions) > 0
    assert "投资" in result.suggestions[0]


def test_ask_without_topic_context_vague_zhege() -> None:
    """Without topic context, vague subject still needs clarification."""
    clarifier = IntentClarifier()
    result = clarifier.ask("这个有什么问题吗")
    assert result.needs_clarification is True


# ---------------------------------------------------------------------------
# Test: ask_with_context — user preference
# ---------------------------------------------------------------------------


def test_ask_with_context_brief_style() -> None:
    """Brief communication style → shorter question."""
    clarifier = IntentClarifier()
    result = clarifier.ask_with_context(
        "处理一下",
        user_preferences={"communication_style": "brief"},
    )
    assert result.needs_clarification is True
    # Brief question should not start with "您"
    assert not result.question.startswith("您")


def test_ask_with_context_normal_style() -> None:
    """Normal style → standard question."""
    clarifier = IntentClarifier()
    result = clarifier.ask_with_context(
        "处理一下",
        user_preferences={"communication_style": "neutral"},
    )
    assert result.needs_clarification is True
    assert "处理" in result.question


# ---------------------------------------------------------------------------
# Test: Integration scenarios
# ---------------------------------------------------------------------------


def test_integration_帮我看看这个合同() -> None:
    """Full scenario: specific request → no clarification."""
    clarifier = IntentClarifier()
    result = clarifier.ask("帮我看看这个合同有没有坑")
    assert result.needs_clarification is False


def test_integration_处理一下() -> None:
    """Full scenario: vague action → needs clarification."""
    clarifier = IntentClarifier()
    result = clarifier.ask("处理一下")
    assert result.needs_clarification is True
    assert result.question != ""


def test_integration_那个() -> None:
    """Full scenario: vague subject → needs clarification."""
    clarifier = IntentClarifier()
    result = clarifier.ask("那个怎么样了")
    assert result.needs_clarification is True
    assert "哪件" in result.question or "什么事" in result.question


def test_integration_它有什么问题() -> None:
    """Full scenario: vague "它" → needs clarification."""
    clarifier = IntentClarifier()
    result = clarifier.ask("它有什么问题吗")
    assert result.needs_clarification is True
    assert "它" in result.question
