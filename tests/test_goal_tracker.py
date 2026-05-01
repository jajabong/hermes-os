"""Tests for GoalTracker — deep multi-session goal understanding."""

import pytest
import os
from datetime import datetime, UTC

from hermes_os.goal_tracker import (
    GoalTracker,
    GoalState,
    GoalPhase,
    GoalPattern,
    _GOAL_PHASES,
)


# ---------------------------------------------------------------------------
# GoalPattern and _GOAL_PHASES tests
# ---------------------------------------------------------------------------

class TestGoalPattern:
    def test_pattern_values(self) -> None:
        assert hasattr(GoalPattern, "RESEARCH_TO_DEPLOY")
        assert hasattr(GoalPattern, "PROPOSAL_TO_IMPLEMENT")
        assert hasattr(GoalPattern, "STUDY_TO_REVIEW")
        assert hasattr(GoalPattern, "ONE_SHOT")

    def test_phases_for_research_to_deploy(self) -> None:
        phases = _GOAL_PHASES[GoalPattern.RESEARCH_TO_DEPLOY]
        assert phases == ["research", "plan", "implement", "test", "deploy"]

    def test_phases_for_proposal_to_implement(self) -> None:
        phases = _GOAL_PHASES[GoalPattern.PROPOSAL_TO_IMPLEMENT]
        assert "await_approval" in phases

    def test_phases_for_one_shot(self) -> None:
        phases = _GOAL_PHASES[GoalPattern.ONE_SHOT]
        assert phases == ["execute"]


# ---------------------------------------------------------------------------
# GoalState tests
# ---------------------------------------------------------------------------

class TestGoalState:
    def test_goal_state_properties(self) -> None:
        now = datetime.now(UTC)
        goal = GoalState(
            goal_id="g1",
            user_id="alice",
            pattern=GoalPattern.RESEARCH_TO_DEPLOY,
            current_phase="research",
            phase_index=0,
            description="完成供应商对比",
            created_at=now,
            updated_at=now,
        )
        assert goal.goal_id == "g1"
        assert goal.current_phase == "research"
        assert goal.phase_index == 0
        assert goal.progress == 0.0
        assert goal.next_phase == "plan"

    def test_goal_progress(self) -> None:
        now = datetime.now(UTC)
        goal = GoalState(
            goal_id="g1",
            user_id="alice",
            pattern=GoalPattern.RESEARCH_TO_DEPLOY,
            current_phase="implement",
            phase_index=2,
            description="实现",
            created_at=now,
            updated_at=now,
        )
        # 2 / 5 = 0.4
        assert 0.3 < goal.progress < 0.5

    def test_goal_is_completed(self) -> None:
        now = datetime.now(UTC)
        goal = GoalState(
            goal_id="g1",
            user_id="alice",
            pattern=GoalPattern.ONE_SHOT,
            current_phase="execute",
            phase_index=0,
            description="",
            created_at=now,
            updated_at=now,
            completed_at=now,
        )
        assert goal.is_completed

    def test_goal_no_next_phase_at_end(self) -> None:
        now = datetime.now(UTC)
        goal = GoalState(
            goal_id="g1",
            user_id="alice",
            pattern=GoalPattern.ONE_SHOT,
            current_phase="execute",
            phase_index=0,
            description="",
            created_at=now,
            updated_at=now,
        )
        assert goal.next_phase is None


# ---------------------------------------------------------------------------
# GoalTracker integration tests (DB-backed)
# ---------------------------------------------------------------------------

class TestGoalTrackerCreate:
    @pytest.fixture
    def tracker(self) -> GoalTracker:
        db_path = "/tmp/test_hermes_goal.db"
        if os.path.exists(db_path):
            os.remove(db_path)
        t = GoalTracker(db_path=db_path)
        return t

    @pytest.mark.asyncio
    async def test_create_goal_defaults_to_one_shot(self, tracker: GoalTracker) -> None:
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="快速查询",
            initial_intent="query",
        )
        assert goal.pattern == GoalPattern.ONE_SHOT
        assert goal.current_phase == "execute"

    @pytest.mark.asyncio
    async def test_create_goal_infers_pattern_from_intent(self, tracker: GoalTracker) -> None:
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="供应商对比分析",
            initial_intent="research",
        )
        assert goal.pattern == GoalPattern.RESEARCH_TO_DEPLOY
        assert goal.current_phase == "research"
        assert goal.phase_index == 0
        assert goal.next_phase == "plan"

    @pytest.mark.asyncio
    async def test_create_goal_with_explicit_pattern(self, tracker: GoalTracker) -> None:
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="申请经费",
            pattern=GoalPattern.PROPOSAL_TO_IMPLEMENT,
        )
        assert goal.pattern == GoalPattern.PROPOSAL_TO_IMPLEMENT
        assert goal.current_phase == "investigate"

    @pytest.mark.asyncio
    async def test_get_goal_returns_created_goal(self, tracker: GoalTracker) -> None:
        await tracker.initialize()
        created = await tracker.create_goal(
            user_id="alice",
            description="测试目标",
        )
        fetched = await tracker.get_goal(created.goal_id)
        assert fetched is not None
        assert fetched.goal_id == created.goal_id
        assert fetched.description == "测试目标"


class TestGoalTrackerAdvance:
    @pytest.fixture
    def tracker(self) -> GoalTracker:
        db_path = "/tmp/test_hermes_goal2.db"
        if os.path.exists(db_path):
            os.remove(db_path)
        t = GoalTracker(db_path=db_path)
        return t

    @pytest.mark.asyncio
    async def test_advance_phase_moves_forward(self, tracker: GoalTracker) -> None:
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="供应商对比",
            initial_intent="research",
        )

        updated = await tracker.advance_phase("alice")

        assert updated is not None
        assert updated.current_phase == "plan"
        assert updated.phase_index == 1
        assert updated.next_phase == "implement"

    @pytest.mark.asyncio
    async def test_advance_to_completion(self, tracker: GoalTracker) -> None:
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="一次完成",
            initial_intent="query",
        )

        updated = await tracker.advance_phase("alice")

        assert updated is not None
        assert updated.current_phase == "completed"
        assert updated.is_completed

    @pytest.mark.asyncio
    async def test_complete_goal_marks_completed(self, tracker: GoalTracker) -> None:
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="测试",
            initial_intent="research",
        )

        completed = await tracker.complete_goal(goal.goal_id)

        assert completed is not None
        assert completed.current_phase == "completed"
        assert completed.is_completed

    @pytest.mark.asyncio
    async def test_abandon_goal(self, tracker: GoalTracker) -> None:
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="测试",
            initial_intent="research",
        )

        abandoned = await tracker.abandon_goal(goal.goal_id)

        assert abandoned is not None
        assert abandoned.current_phase == "abandoned"


class TestGoalTrackerGetActive:
    @pytest.fixture
    def tracker(self) -> GoalTracker:
        db_path = "/tmp/test_hermes_goal3.db"
        if os.path.exists(db_path):
            os.remove(db_path)
        t = GoalTracker(db_path=db_path)
        return t

    @pytest.mark.asyncio
    async def test_get_active_goal_returns_most_recent(self, tracker: GoalTracker) -> None:
        await tracker.initialize()
        await tracker.create_goal(user_id="alice", description="旧目标", initial_intent="query")
        newer = await tracker.create_goal(user_id="alice", description="新目标", initial_intent="query")

        active = await tracker.get_active_goal("alice")

        assert active is not None
        assert active.goal_id == newer.goal_id
        assert active.description == "新目标"

    @pytest.mark.asyncio
    async def test_get_active_goal_excludes_completed(self, tracker: GoalTracker) -> None:
        await tracker.initialize()
        goal = await tracker.create_goal(user_id="alice", description="完成它", initial_intent="query")
        await tracker.complete_goal(goal.goal_id)
        await tracker.create_goal(user_id="alice", description="新目标", initial_intent="query")

        active = await tracker.get_active_goal("alice")

        assert active is not None
        assert active.description == "新目标"

    @pytest.mark.asyncio
    async def test_get_active_goal_context_formats_correctly(self, tracker: GoalTracker) -> None:
        await tracker.initialize()
        await tracker.create_goal(
            user_id="alice",
            description="供应商对比分析项目",
            initial_intent="research",
        )

        context = await tracker.get_active_goal_context("alice")

        assert "供应商对比分析项目" in context
        assert "Phase 1/5" in context
        assert "research" in context
        assert "Progress:" in context

    @pytest.mark.asyncio
    async def test_get_active_goal_context_empty_when_no_goal(self, tracker: GoalTracker) -> None:
        await tracker.initialize()
        context = await tracker.get_active_goal_context("nobody")
        assert context == ""


class TestGoalTrackerPhaseTransitions:
    @pytest.fixture
    def tracker(self) -> GoalTracker:
        db_path = "/tmp/test_hermes_goal4.db"
        if os.path.exists(db_path):
            os.remove(db_path)
        t = GoalTracker(db_path=db_path)
        return t

    @pytest.mark.asyncio
    async def test_full_research_to_deploy_progression(self, tracker: GoalTracker) -> None:
        """Test going through all phases of RESEARCH_TO_DEPLOY pattern."""
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="完整项目",
            initial_intent="research",
        )

        phases_reached = [goal.current_phase]

        # Advance through all phases
        for _ in range(10):
            goal = await tracker.advance_phase("alice")
            if goal is None or goal.is_completed:
                break
            phases_reached.append(goal.current_phase)

        assert "research" in phases_reached
        assert "plan" in phases_reached
        assert "implement" in phases_reached
        assert "deploy" in phases_reached
        assert goal is not None and goal.is_completed

    @pytest.mark.asyncio
    async def test_get_recent_goals(self, tracker: GoalTracker) -> None:
        await tracker.initialize()
        g1 = await tracker.create_goal(user_id="alice", description="目标1", initial_intent="query")
        g2 = await tracker.create_goal(user_id="alice", description="目标2", initial_intent="query")
        await tracker.complete_goal(g1.goal_id)

        recent = await tracker.get_recent_goals("alice", limit=5)

        assert len(recent) == 2
        # Both goals should be in recent list
        recent_ids = [g.goal_id for g in recent]
        assert g1.goal_id in recent_ids
        assert g2.goal_id in recent_ids
