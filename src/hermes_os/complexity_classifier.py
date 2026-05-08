"""Complexity Classifier — keyword-based simple vs complex task classification.

Phase 1: 模型复杂度路由
P1: 关键词判断 — 简单任务 vs 复杂任务

Strategy:
- SIMPLE: 查询类任务 (what/who/where/查/找/tell me/list/show)
- COMPLEX: 实现/调试/架构/重构类任务 (implement/debug/architect/refactor/实现/开发/重构)
- AMBIGUOUS: 关键词不匹配，需要 LLM 二次评估
"""

from __future__ import annotations

from enum import Enum


class Complexity(str, Enum):
    """Task complexity level."""

    SIMPLE = "simple"  # Query-like tasks
    MODERATE = "moderate"  # Moderate complexity
    COMPLEX = "complex"  # Implementation/architecture tasks
    AMBIGUOUS = "ambiguous"  # Needs LLM assessment


# Keywords that indicate SIMPLE tasks (query-like)
_SIMPLE_KEYWORDS: list[str] = [
    # Chinese - query-like
    "查一下",
    "查查",
    "查找",
    "帮我查",
    "告诉我",
    "请问",
    "问一下",
    "什么是",
    "是什么",
    "在吗",
    "现在几点",
    "今天天气",
    "现在时间",
    "在哪里",
    "干什么的",
    "是干什么",
    "看看这个",
    "函数是干什么",
    # English - query-like
    "what is",
    "what are",
    "what time",
    "who is",
    "who are",
    "where is",
    "where are",
    "tell me",
    "show me",
    "list all",
    "find out",
    "look up",
    "can you tell",
    "i need to know",
    "how do i",
    "how to",
    "check the",
    "query",
    "simple",
]

# Keywords that indicate COMPLEX tasks (implementation/architecture)
_COMPLEX_KEYWORDS: list[str] = [
    # Chinese
    "实现",
    "开发",
    "编写",
    "写一个",
    "写代码",
    "编程",
    "重构",
    "架构",
    "设计",
    "调试",
    "修复",
    "解决",
    "创建一个",
    "从零开始",
    "帮我实现",
    "帮我开发",
    "帮我写",
    "帮我重构",
    "帮我设计",
    "很难调",
    "bug很难",
    "怎么debug",
    "如何debug",
    "debug",
    # English
    "implement",
    "develop",
    "create from scratch",
    "build from zero",
    "architect",
    "architecture",
    "design a",
    "refactor",
    "debug why",
    "debug this",
    "fix the bug",
    "solve this",
    "write a",
    "coding",
    "programming",
    "system design",
    "database schema",
    "microservices",
    "distributed",
    "pipeline",
    "compiler",
]


class ComplexityClassifier:
    """Keyword-based complexity classifier for routing decisions."""

    def classify_by_keywords(self, message: str) -> Complexity:
        """Classify task complexity using keyword matching.

        Args:
            message: User's input message

        Returns:
            Complexity enum: SIMPLE, COMPLEX, or AMBIGUOUS
        """
        if not message or not message.strip():
            return Complexity.AMBIGUOUS

        msg_lower = message.lower()

        # Check for COMPLEX keywords first (higher priority in mixed cases)
        has_complex = any(kw in msg_lower for kw in _COMPLEX_KEYWORDS)
        has_simple = any(kw in msg_lower for kw in _SIMPLE_KEYWORDS)

        if has_complex:
            return Complexity.COMPLEX
        if has_simple:
            return Complexity.SIMPLE
        return Complexity.AMBIGUOUS

    def get_complexity_for_model_routing(self, complexity: Complexity) -> str:
        """Map Complexity to model routing tier.

        Args:
            complexity: Classified complexity level

        Returns:
            Model tier name: "cheap" (MiniMax) or "heavy" (blend)
        """
        if complexity == Complexity.SIMPLE:
            return "cheap"
        if complexity == Complexity.COMPLEX:
            return "heavy"
        return "heavy"  # Default to heavy for ambiguous, LLM will assess

    def classify_by_intent(self, intent: str) -> Complexity:
        """Classify complexity from a pre-classified intent (single source of truth).

        Uses the canonical intent from UnifiedRouter.classify_intent() to determine
        model tier, avoiding re-classification of the same message.
        """
        HEAVY_INTENTS = {
            "code",
            "review",
            "content",
            "research",
            "investment",
            "legal",
        }
        MEDIUM_INTENTS = {"education", "deploy"}

        if intent in HEAVY_INTENTS:
            return Complexity.COMPLEX
        if intent in MEDIUM_INTENTS:
            return Complexity.MODERATE
        return Complexity.SIMPLE
