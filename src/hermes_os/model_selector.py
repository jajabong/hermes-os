"""Model Selector — hybrid complexity assessment for model routing.

Phase 1: 模型复杂度路由
P2: LLM 评估 — 当关键词判断为 AMBIGUOUS 时，用 MiniMax 评估复杂度

Routing Strategy:
- SIMPLE (keyword) → MiniMax-M2.7 (cheap, fast)
- COMPLEX (keyword) → blend (powerful, local/single API)
- AMBIGUOUS → MiniMax LLM 评估 → 选择 MiniMax 或 blend
- Fallback chain: primary → secondary → baosi (last resort)

Model tier mapping:
- MINIMAX: MiniMax-M2.7 (fast, cheap, good for simple tasks)
- BLEND: blend (localhost or API, powerful for complex tasks)
- BAOSI: claude-sonnet-4-6 (last resort fallback)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from hermes_os.complexity_classifier import Complexity, ComplexityClassifier


class ModelTier(str, Enum):
    """Model tier for routing decisions."""

    MINIMAX = "minimax"
    BLEND = "blend"
    BAOSI = "baosi"


LLM_EVAL_PROMPT_TEMPLATE = """You are a task complexity analyzer for an AI assistant routing system.

Classify the following user message as either "simple" or "complex":

User Message: {message}

Respond with ONLY one word:
- "simple" if the task is a simple query, lookup, or basic information request
- "complex" if the task requires multi-step reasoning, implementation, debugging, or creative work

Response (simple or complex only):
"""


@dataclass
class RoutingDecision:
    """Result of model selection decision."""

    tier: ModelTier
    complexity_reason: str
    needs_llm_eval: bool = False
    llm_confidence: float | None = None


class ModelSelector:
    """Hybrid model selector combining keyword + LLM assessment.

    Flow:
    1. Keyword-based classification (fast path)
    2. If AMBIGUOUS, use MiniMax LLM to assess complexity
    3. Return RoutingDecision with model tier and metadata
    """

    def __init__(self) -> None:
        self._classifier = ComplexityClassifier()
        self._minimax_tier = ModelTier.MINIMAX
        self._blend_tier = ModelTier.BLEND
        self._baosi_tier = ModelTier.BAOSI

    async def select_model(self, message: str) -> RoutingDecision:
        """Select appropriate model tier based on task complexity.

        Args:
            message: User's input message

        Returns:
            RoutingDecision with selected tier and metadata
        """
        # Step 1: Fast keyword-based classification
        complexity = self._classifier.classify_by_keywords(message)

        if complexity == Complexity.SIMPLE:
            return RoutingDecision(
                tier=self._minimax_tier,
                complexity_reason=f"Keyword match: {complexity.value} query",
                needs_llm_eval=False,
            )

        if complexity == Complexity.COMPLEX:
            return RoutingDecision(
                tier=self._blend_tier,
                complexity_reason=f"Keyword match: {complexity.value} task",
                needs_llm_eval=False,
            )

        # Step 2: AMBIGUOUS - use LLM to assess
        return await self._evaluate_with_llm(message)

    async def _evaluate_with_llm(self, message: str) -> RoutingDecision:
        """Use MiniMax LLM to evaluate task complexity.

        Args:
            message: User's input message

        Returns:
            RoutingDecision based on LLM assessment
        """
        try:
            from hermes_os.claude_code_invocator import invoke

            prompt = LLM_EVAL_PROMPT_TEMPLATE.format(message=message)

            result = await invoke(
                prompt=prompt,
                model="minimax",  # Use MiniMax for fast LLM evaluation
                max_turns=1,
                timeout_sec=15,
                system_prompt="You are a task complexity classifier. Respond with ONLY 'simple' or 'complex'.",
            )

            response = result.stdout.strip().lower()

            if "complex" in response:
                return RoutingDecision(
                    tier=self._blend_tier,
                    complexity_reason="LLM evaluation: complex reasoning required",
                    needs_llm_eval=True,
                    llm_confidence=0.8,
                )
            else:
                return RoutingDecision(
                    tier=self._minimax_tier,
                    complexity_reason="LLM evaluation: simple query task",
                    needs_llm_eval=True,
                    llm_confidence=0.8,
                )

        except Exception:
            # Default to blend on LLM failure (better to over-estimate than under)
            return RoutingDecision(
                tier=self._blend_tier,
                complexity_reason="LLM evaluation failed, defaulting to complex",
                needs_llm_eval=True,
                llm_confidence=0.0,
            )

    def get_fallback_chain(self, tier: ModelTier) -> list[ModelTier]:
        """Get fallback chain for a given tier.

        Args:
            tier: Primary selected tier

        Returns:
            Ordered list of fallback tiers
        """
        if tier == ModelTier.MINIMAX:
            # MiniMax -> blend -> baosi
            return [self._blend_tier, self._baosi_tier]
        if tier == ModelTier.BLEND:
            # blend -> minimax -> baosi
            return [self._minimax_tier, self._baosi_tier]
        # baosi is last resort, no further fallback
        return []
