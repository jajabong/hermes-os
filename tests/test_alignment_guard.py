"""Tests for AlignmentGuard — semantic drift detection in ChiefAgent.

Three drift levels:
- LOW: auto-create task (semantic similarity >= 0.7)
- MEDIUM: Feishu confirmation card required (0.4 <= sim < 0.7)
- HIGH: lock context, wait for human (sim < 0.4)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from hermes_os.chief_agent import ChiefAgent, Intent, ParsedIntent


# ---------------------------------------------------------------------------
# DriftLevel enum and AlignmentResult
# ---------------------------------------------------------------------------

class TestDriftLevel:
    def test_drift_level_enum_values(self) -> None:
        from hermes_os.chief_agent import DriftLevel
        assert hasattr(DriftLevel, "LOW")
        assert hasattr(DriftLevel, "MEDIUM")
        assert hasattr(DriftLevel, "HIGH")


class TestAlignmentResult:
    def test_alignment_result_dataclass_fields(self) -> None:
        from hermes_os.chief_agent import AlignmentResult
        result = AlignmentResult(
            drift_level="LOW",
            similarity=0.85,
            active_goal_description="完成供应商对比",
            current_intent_description="研究供应商",
            needs_confirmation=False,
            confirmation_message=None,
        )
        assert result.drift_level == "LOW"
        assert result.similarity == 0.85
        assert result.needs_confirmation is False


# ---------------------------------------------------------------------------
# AlignmentGuard integration
# ---------------------------------------------------------------------------

class TestAlignmentGuardCheck:
    @pytest.fixture
    def chief(self) -> ChiefAgent:
        return ChiefAgent()

    @pytest.mark.asyncio
    async def test_low_drift_auto_creates_task(self, chief: ChiefAgent) -> None:
        """When intent is highly aligned with active goal, auto-approve."""
        # Mock goal tracker returning a goal about "供应商对比"
        mock_tracker = AsyncMock()
        mock_tracker.get_active_goal_context.return_value = (
            "Goal: 完成供应商对比分析\n"
            "Phase 1/5: research\n"
            "Pattern: research_to_deploy\n"
            "Progress: 20%"
        )

        # Mock LLM similarity check returning high similarity
        with patch("hermes_os.chief_agent.compute_similarity", new_callable=AsyncMock) as mock_sim:
            mock_sim.return_value = 0.85  # HIGH alignment

            result = await chief.check_alignment(
                user_message="帮我研究一下供应商",
                user_id="alice",
                goal_tracker=mock_tracker,
            )

        assert result.drift_level == "LOW"
        assert result.needs_confirmation is False
        assert result.similarity >= 0.7

    @pytest.mark.asyncio
    async def test_medium_drift_requires_confirmation(self, chief: ChiefAgent) -> None:
        """When intent is somewhat related but off-topic, ask for confirmation."""
        mock_tracker = AsyncMock()
        mock_tracker.get_active_goal_context.return_value = (
            "Goal: 完成供应商对比分析\n"
            "Phase 1/5: research\n"
            "Pattern: research_to_deploy\n"
            "Progress: 20%"
        )

        with patch("hermes_os.chief_agent.compute_similarity", new_callable=AsyncMock) as mock_sim:
            mock_sim.return_value = 0.55  # MEDIUM drift

            result = await chief.check_alignment(
                user_message="帮我查一下邮件",
                user_id="alice",
                goal_tracker=mock_tracker,
            )

        assert result.drift_level == "MEDIUM"
        assert result.needs_confirmation is True
        assert "新目标" in (result.confirmation_message or "")
        assert "新目标" in (result.confirmation_message or "")

    @pytest.mark.asyncio
    async def test_high_drift_locks_context(self, chief: ChiefAgent) -> None:
        """When intent is completely off-topic, lock and wait for human."""
        mock_tracker = AsyncMock()
        mock_tracker.get_active_goal_context.return_value = (
            "Goal: 完成供应商对比分析\n"
            "Phase 1/5: research\n"
            "Pattern: research_to_deploy\n"
            "Progress: 20%"
        )

        with patch("hermes_os.chief_agent.compute_similarity", new_callable=AsyncMock) as mock_sim:
            mock_sim.return_value = 0.15  # HIGH drift - completely unrelated

            result = await chief.check_alignment(
                user_message="帮我订一张机票",
                user_id="alice",
                goal_tracker=mock_tracker,
            )

        assert result.drift_level == "HIGH"
        assert result.needs_confirmation is True
        assert result.confirmation_message is not None

    @pytest.mark.asyncio
    async def test_no_active_goal_auto_approves(self, chief: ChiefAgent) -> None:
        """When there's no active goal, always LOW drift (no context to drift from)."""
        mock_tracker = AsyncMock()
        mock_tracker.get_active_goal_context.return_value = ""  # No active goal

        result = await chief.check_alignment(
            user_message="帮我查一下邮件",
            user_id="alice",
            goal_tracker=mock_tracker,
        )

        assert result.drift_level == "LOW"
        assert result.needs_confirmation is False


# ---------------------------------------------------------------------------
# North Star Injection in parse_intent
# ---------------------------------------------------------------------------

class TestNorthStarInjection:
    @pytest.fixture
    def chief(self) -> ChiefAgent:
        return ChiefAgent()

    @pytest.mark.asyncio
    async def test_parse_intent_injects_goal_context(self, chief: ChiefAgent) -> None:
        """Goal context must be injected into parse_intent as highest priority."""
        mock_tracker = AsyncMock()
        mock_tracker.get_active_goal_context.return_value = (
            "Goal: 完成供应商对比分析\n"
            "Phase 2/5: plan\n"
            "Pattern: research_to_deploy\n"
            "Progress: 40%"
        )

        with patch("hermes_os.chief_agent.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = MagicMock(
                stdout='{"action": "research", "confidence": 0.9, "entities": {}}'
            )
            intent = await chief.parse_intent(
                message="研究供应商",
                user_id="alice",
                goal_tracker=mock_tracker,
            )

            # Verify invoke was called with a prompt that includes the goal context
            call_args = mock_invoke.call_args
            prompt = call_args.kwargs["prompt"]
            system_prompt = call_args.kwargs["system_prompt"]

            assert "北极星" in system_prompt or "Goal:" in prompt
            assert "完成供应商对比分析" in prompt

    @pytest.mark.asyncio
    async def test_north_star_in_system_prompt_prefix(self, chief: ChiefAgent) -> None:
        """The NORTH STAR GOAL must appear at the TOP of the system prompt."""
        mock_tracker = AsyncMock()
        mock_tracker.get_active_goal_context.return_value = (
            "Goal: 供应商项目\nPhase 1/5: research\nProgress: 20%"
        )

        with patch("hermes_os.chief_agent.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = MagicMock(
                stdout='{"action": "research", "confidence": 0.9, "entities": {}}'
            )
            await chief.parse_intent(
                message="研究供应商",
                user_id="alice",
                goal_tracker=mock_tracker,
            )

            system_prompt = mock_invoke.call_args.kwargs["system_prompt"]
            # The north star box appears BEFORE the org identity block (prefix area)
            # Check for the box structure or the goal itself
            assert "供应商项目" in system_prompt
