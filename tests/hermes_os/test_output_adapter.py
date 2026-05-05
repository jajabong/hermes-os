"""Tests for output_adapter.py — TDD for OutputAdapter style adaptation layer."""

from __future__ import annotations

import pytest

from hermes_os.output_adapter import OutputStyle, OutputAdapter


# ---------------------------------------------------------------------------
# OutputStyle tests
# ---------------------------------------------------------------------------

def test_output_style_defaults() -> None:
    """OutputStyle should have sensible defaults."""
    style = OutputStyle()
    assert style.tone == "neutral"
    assert style.language == "auto"
    assert style.format == "markdown"
    assert style.max_length == 2000
    assert style.include_metadata is False


def test_output_style_full() -> None:
    """OutputStyle should accept all fields."""
    style = OutputStyle(
        tone="casual",
        language="zh",
        format="plain",
        max_length=500,
        include_metadata=True,
    )
    assert style.tone == "casual"
    assert style.language == "zh"
    assert style.max_length == 500


# ---------------------------------------------------------------------------
# OutputAdapter unit tests
# ---------------------------------------------------------------------------

def test_adapt_truncates_long_output() -> None:
    """Output exceeding max_length should be truncated."""
    adapter = OutputAdapter(preferences={"max_length": 50, "tone": "neutral", "language": "auto"})
    long_text = "这是很长的一段文本，超过了最大长度限制，所以应该被截断。" * 10
    result = adapter.adapt(long_text)
    assert len(result) <= 53  # 50 + "..."
    assert result.endswith("...")


def test_adapt_does_not_truncate_short_output() -> None:
    """Output within max_length should be returned unchanged."""
    adapter = OutputAdapter(preferences={"max_length": 2000, "tone": "neutral", "language": "auto"})
    short_text = "短文本"
    result = adapter.adapt(short_text)
    assert result == short_text


def test_adapt_with_casual_tone() -> None:
    """Casual tone should not add excessive formatting."""
    adapter = OutputAdapter(preferences={"tone": "casual", "max_length": 2000, "language": "auto"})
    formal_text = "您好，根据我们的分析结果表明，该投资组合具有良好的收益预期。"
    result = adapter.adapt(formal_text)
    assert len(result) <= len(formal_text) + 10  # no significant expansion


def test_adapt_with_concise_tone() -> None:
    """Concise tone should produce shorter output."""
    adapter = OutputAdapter(preferences={"tone": "concise", "max_length": 2000, "language": "auto"})
    # Use text with proper sentence-ending punctuation
    detailed_text = "根据我们的分析，首先，这是一个非常重要的发现。其次，我们需要考虑多个因素。最后，建议采取行动。" * 20
    result = adapter.adapt(detailed_text)
    # Should be significantly shorter
    assert len(result) < len(detailed_text)


def test_adapt_preserves_code_blocks() -> None:
    """Code blocks in output should be preserved."""
    adapter = OutputAdapter(preferences={"tone": "neutral", "max_length": 2000, "language": "auto"})
    code_output = "以下是代码：\n```python\ndef hello():\n    print('hi')\n```\n代码结束"
    result = adapter.adapt(code_output)
    assert "```python" in result
    assert "def hello" in result


def test_adapt_zh_language_preserved() -> None:
    """Chinese output should remain in Chinese."""
    adapter = OutputAdapter(preferences={"tone": "neutral", "max_length": 2000, "language": "zh"})
    zh_text = "张三今天投资了股票，获得了不错的收益。"
    result = adapter.adapt(zh_text)
    assert "张三" in result
    assert "投资" in result


def test_adapt_en_language_preserved() -> None:
    """English output should remain in English."""
    adapter = OutputAdapter(preferences={"tone": "neutral", "max_length": 2000, "language": "en"})
    en_text = "The investment portfolio shows strong performance."
    result = adapter.adapt(en_text)
    assert "investment" in result.lower()


def test_adapt_auto_language_detection_zh() -> None:
    """Auto language detection should recognize Chinese."""
    adapter = OutputAdapter(preferences={"tone": "neutral", "max_length": 2000, "language": "auto"})
    zh_text = "今天天气很好"
    result = adapter.adapt(zh_text)
    assert result == zh_text  # Should pass through unchanged


def test_adapt_auto_language_detection_en() -> None:
    """Auto language detection should recognize English."""
    adapter = OutputAdapter(preferences={"tone": "neutral", "max_length": 2000, "language": "auto"})
    en_text = "The weather is nice today."
    result = adapter.adapt(en_text)
    assert result == en_text  # Should pass through unchanged


def test_adapt_empty_output() -> None:
    """Empty output should return empty string."""
    adapter = OutputAdapter(preferences={"max_length": 2000, "tone": "neutral", "language": "auto"})
    result = adapter.adapt("")
    assert result == ""


def test_adapt_none_output() -> None:
    """None output should be handled gracefully."""
    adapter = OutputAdapter(preferences={"max_length": 2000, "tone": "neutral", "language": "auto"})
    result = adapter.adapt(None)
    assert result == ""


def test_adapt_markdown_format() -> None:
    """Markdown format should preserve markdown syntax."""
    adapter = OutputAdapter(preferences={"tone": "neutral", "max_length": 2000, "language": "auto", "format": "markdown"})
    md_text = "## 标题\n\n这是**加粗**文本。\n\n- 列表项1\n- 列表项2"
    result = adapter.adapt(md_text)
    assert "## 标题" in result
    assert "**加粗**" in result
    assert "- 列表项1" in result


def test_adapt_plain_format() -> None:
    """Plain format should strip markdown syntax."""
    adapter = OutputAdapter(preferences={"tone": "neutral", "max_length": 2000, "language": "auto", "format": "plain"})
    md_text = "## 标题\n\n这是**加粗**文本。"
    result = adapter.adapt(md_text)
    assert "##" not in result
    assert "**" not in result


def test_adapt_with_no_preferences() -> None:
    """adapt() with no preferences dict should use defaults."""
    adapter = OutputAdapter(preferences=None)
    text = "任何文本"
    result = adapter.adapt(text)
    # Should use OutputStyle defaults (neutral tone, 2000 max_length)
    assert result == text


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

def test_full_pipeline_style_adaptation() -> None:
    """Simulate a full pipeline: agent output → adapted for user preferences."""
    # Simulate different user preferences
    users = [
        {"preferences": {"tone": "concise", "max_length": 100, "language": "zh"}},
        {"preferences": {"tone": "neutral", "max_length": 500, "language": "en"}},
        {"preferences": {"tone": "casual", "max_length": 2000, "language": "auto"}},
    ]

    # Simulated agent output
    agent_output = "根据详细的分析，我们可以看到投资组合在过去三个月表现良好，总回报率达到15.7%，相比基准指数超出4.2个百分点。从风险角度来看，该组合的波动率为12.3%，处于中等水平。建议在未来保持当前配置，适当考虑增加债券比例以平衡风险。"

    for user in users:
        adapter = OutputAdapter(preferences=user["preferences"])
        result = adapter.adapt(agent_output)
        # All adaptations should be non-empty
        assert result.strip() != ""
        # All should be within max_length
        assert len(result) <= user["preferences"]["max_length"] + 10  # +10 for truncation ellipsis
