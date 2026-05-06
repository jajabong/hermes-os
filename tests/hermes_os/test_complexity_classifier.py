"""TDD tests for complexity_classifier.py — simple vs complex task classification.

Phase 1: 模型复杂度路由
P1: 关键词判断 — 简单任务 vs 复杂任务
"""

from __future__ import annotations

import pytest
from hermes_os.complexity_classifier import (
    Complexity,
    ComplexityClassifier,
)


# ---------------------------------------------------------------------------
# Test: Complexity enum
# ---------------------------------------------------------------------------


def test_complexity_enum_values() -> None:
    """Complexity should have three levels."""
    assert Complexity.SIMPLE.value == "simple"
    assert Complexity.MODERATE.value == "moderate"
    assert Complexity.COMPLEX.value == "complex"


# ---------------------------------------------------------------------------
# Test: SIMPLE task keywords
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "现在几点？",
        "今天天气怎么样？",
        "帮我查一下北京的人口",
        "告诉我什么是AI",
        "list all files",
        "what is python?",
        "who is the president?",
        "查找最近的新闻",
        "帮我看看这个文件内容",
        "这个函数是干什么的？",
        "解释一下什么是机器学习",
        "上海在哪里？",
        "i need to know the time",
        "show me the logs",
        "tell me about the project",
        "查一下明天的天气",
    ],
)
def test_simple_task_keywords(message: str) -> None:
    """Messages with simple task keywords should be classified as SIMPLE."""
    classifier = ComplexityClassifier()
    result = classifier.classify_by_keywords(message)
    assert result == Complexity.SIMPLE, f"Expected SIMPLE for: {message}"


# ---------------------------------------------------------------------------
# Test: COMPLEX task keywords
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "帮我实现一个深度学习框架",
        "debug why the test is failing",
        "architect a microservices system",
        "refactor the entire auth module",
        "implement a new feature from scratch",
        "帮我写一个完整的REST API",
        "帮我开发一个聊天机器人",
        "design a database schema for e-commerce",
        "create a CI/CD pipeline from zero",
        "这个bug很难调，帮我看看",
        "帮我重构整个项目结构",
        "implement distributed caching system",
        "build a real-time data pipeline",
        "写一个编译器后端",
        "帮我开发这个iOS应用",
        "帮我做系统架构设计",
    ],
)
def test_complex_task_keywords(message: str) -> None:
    """Messages with complex task keywords should be classified as COMPLEX."""
    classifier = ComplexityClassifier()
    result = classifier.classify_by_keywords(message)
    assert result == Complexity.COMPLEX, f"Expected COMPLEX for: {message}"


# ---------------------------------------------------------------------------
# Test: AMBIGUOUS (no keywords match)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "帮我看看",
        "这个怎么处理？",
        "怎么办才好？",
        "分析一下这个情况",
        "怎么处理这个数据？",
    ],
)
def test_ambiguous_task_keywords(message: str) -> None:
    """Messages without simple or complex keywords should be classified as AMBIGUOUS."""
    classifier = ComplexityClassifier()
    result = classifier.classify_by_keywords(message)
    assert result == Complexity.AMBIGUOUS, f"Expected AMBIGUOUS for: {message}"


# ---------------------------------------------------------------------------
# Test: classify_by_keywords returns Complexity
# ---------------------------------------------------------------------------


def test_classify_by_keywords_returns_enum() -> None:
    """classify_by_keywords should always return a Complexity enum."""
    classifier = ComplexityClassifier()
    result = classifier.classify_by_keywords("simple query?")
    assert isinstance(result, Complexity)
    assert result == Complexity.SIMPLE


# ---------------------------------------------------------------------------
# Test: Multi-language support
# ---------------------------------------------------------------------------


def test_multilingual_simple() -> None:
    """Should detect simple tasks in Chinese and English."""
    classifier = ComplexityClassifier()
    assert classifier.classify_by_keywords("查一下") == Complexity.SIMPLE
    assert classifier.classify_by_keywords("tell me") == Complexity.SIMPLE
    assert classifier.classify_by_keywords("what is") == Complexity.SIMPLE


def test_multilingual_complex() -> None:
    """Should detect complex tasks in Chinese and English."""
    classifier = ComplexityClassifier()
    assert classifier.classify_by_keywords("实现") == Complexity.COMPLEX
    assert classifier.classify_by_keywords("implement") == Complexity.COMPLEX
    assert classifier.classify_by_keywords("debug") == Complexity.COMPLEX


# ---------------------------------------------------------------------------
# Test: Mixed keywords — first match wins
# ---------------------------------------------------------------------------


def test_mixed_keywords_complexity() -> None:
    """When both simple and complex keywords present, complex takes precedence."""
    classifier = ComplexityClassifier()
    # "帮我查一下怎么debug" has both simple (查) and complex (debug)
    result = classifier.classify_by_keywords("帮我查一下怎么debug")
    # Complex keywords should take precedence
    assert result == Complexity.COMPLEX


# ---------------------------------------------------------------------------
# Test: Empty/whitespace input
# ---------------------------------------------------------------------------


def test_empty_input() -> None:
    """Empty or whitespace input should return AMBIGUOUS."""
    classifier = ComplexityClassifier()
    assert classifier.classify_by_keywords("") == Complexity.AMBIGUOUS
    assert classifier.classify_by_keywords("   ") == Complexity.AMBIGUOUS


# ---------------------------------------------------------------------------
# Test: Case insensitivity
# ---------------------------------------------------------------------------


def test_case_insensitive() -> None:
    """Keyword matching should be case insensitive."""
    classifier = ComplexityClassifier()
    assert classifier.classify_by_keywords("DEBUG this") == Complexity.COMPLEX
    assert classifier.classify_by_keywords("What IS this") == Complexity.SIMPLE
    assert classifier.classify_by_keywords("IMPLEMENT it") == Complexity.COMPLEX
