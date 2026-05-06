"""Tests for GoalTracker — deep multi-session goal understanding."""

import os
from datetime import UTC, datetime

import pytest

from hermes_os.goal_tracker import (
    _GOAL_PHASES,
    GoalPattern,
    GoalState,
    GoalTracker,
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
        for path in [db_path, db_path + "-wal", db_path + "-shm"]:
            if os.path.exists(path):
                os.remove(path)
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
        newer = await tracker.create_goal(
            user_id="alice", description="新目标", initial_intent="query"
        )

        active = await tracker.get_active_goal("alice")

        assert active is not None
        assert active.goal_id == newer.goal_id
        assert active.description == "新目标"

    @pytest.mark.asyncio
    async def test_get_active_goal_excludes_completed(self, tracker: GoalTracker) -> None:
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice", description="完成它", initial_intent="query"
        )
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


class TestGoalTrackerEdgeCases:
    """Edge cases and error conditions for GoalTracker."""

    @pytest.fixture
    def tracker(self) -> GoalTracker:
        db_path = "/tmp/test_hermes_goal_edge.db"
        for path in [db_path, db_path + "-wal", db_path + "-shm"]:
            if os.path.exists(path):
                os.remove(path)
        t = GoalTracker(db_path=db_path)
        return t

    @pytest.mark.asyncio
    async def test_advance_phase_no_active_goal(self, tracker: GoalTracker) -> None:
        """Advancing when no active goal returns None."""
        await tracker.initialize()
        result = await tracker.advance_phase("nobody")
        assert result is None

    @pytest.mark.asyncio
    async def test_complete_nonexistent_goal(self, tracker: GoalTracker) -> None:
        """Completing a non-existent goal returns None."""
        await tracker.initialize()
        result = await tracker.complete_goal("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_abandon_nonexistent_goal(self, tracker: GoalTracker) -> None:
        """Abandoning a non-existent goal returns None."""
        await tracker.initialize()
        result = await tracker.abandon_goal("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_goal_not_found(self, tracker: GoalTracker) -> None:
        """Getting a non-existent goal returns None."""
        await tracker.initialize()
        result = await tracker.get_goal("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_create_goal_with_metadata(self, tracker: GoalTracker) -> None:
        """Creating a goal with custom metadata works correctly."""
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="带元数据的测试",
            initial_intent="research",
            metadata={"priority": "high", "tags": ["important", "urgent"]},
        )

        assert goal.metadata == {"priority": "high", "tags": ["important", "urgent"]}

        # Verify metadata persists
        fetched = await tracker.get_goal(goal.goal_id)
        assert fetched is not None
        assert fetched.metadata == {"priority": "high", "tags": ["important", "urgent"]}

    @pytest.mark.asyncio
    async def test_advance_phase_jump_forward(self, tracker: GoalTracker) -> None:
        """Can jump to a specific phase instead of advancing sequentially."""
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="跳阶段测试",
            initial_intent="research",
        )

        # Jump directly to deploy phase
        updated = await tracker.advance_phase("alice", next_phase="deploy")

        assert updated is not None
        assert updated.current_phase == "deploy"
        assert updated.phase_index == 4  # deploy is index 4

    @pytest.mark.asyncio
    async def test_multiple_users_isolated(self, tracker: GoalTracker) -> None:
        """Goals for different users are isolated."""
        await tracker.initialize()
        alice_goal = await tracker.create_goal(
            user_id="alice",
            description="Alice的目标",
            initial_intent="query",
        )
        bob_goal = await tracker.create_goal(
            user_id="bob",
            description="Bob的目标",
            initial_intent="query",
        )

        alice_active = await tracker.get_active_goal("alice")
        bob_active = await tracker.get_active_goal("bob")

        assert alice_active is not None
        assert bob_active is not None
        assert alice_active.goal_id == alice_goal.goal_id
        assert bob_active.goal_id == bob_goal.goal_id

    @pytest.mark.asyncio
    async def test_complete_already_completed_goal(self, tracker: GoalTracker) -> None:
        """Completing an already completed goal returns the goal without changes."""
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="测试",
            initial_intent="query",
        )
        await tracker.complete_goal(goal.goal_id)

        # Complete again
        result = await tracker.complete_goal(goal.goal_id)
        assert result is not None
        assert result.is_completed

    @pytest.mark.asyncio
    async def test_progress_calculation_accurate(self, tracker: GoalTracker) -> None:
        """Progress is calculated correctly at different stages."""
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="进度测试",
            initial_intent="research",
        )

        # Phase 0 of 5 phases
        assert goal.progress == 0.0

        # Advance to phase 2
        await tracker.advance_phase("alice", next_phase="implement")
        goal = await tracker.get_goal(goal.goal_id)
        assert goal is not None
        # phase_index 2 / 5 = 0.4
        assert 0.35 <= goal.progress <= 0.45


class TestGoalTrackerInferNextAction:
    """Tests for infer_next_action() functionality."""

    @pytest.fixture
    def tracker(self) -> GoalTracker:
        db_path = "/tmp/test_hermes_infer.db"
        for path in [db_path, db_path + "-wal", db_path + "-shm"]:
            if os.path.exists(path):
                os.remove(path)
        t = GoalTracker(db_path=db_path)
        return t

    @pytest.mark.asyncio
    async def test_infer_next_action_completion_signal(self, tracker: GoalTracker) -> None:
        """Completion signals trigger next phase suggestion."""
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="测试推断",
            initial_intent="research",
        )

        suggestion = await tracker.infer_next_action("alice", "研究已经完成了")
        assert suggestion is not None
        assert "plan" in suggestion

    @pytest.mark.asyncio
    async def test_infer_next_action_no_active_goal(self, tracker: GoalTracker) -> None:
        """No suggestion when no active goal."""
        await tracker.initialize()
        suggestion = await tracker.infer_next_action("nobody", "做点什么")
        assert suggestion is None

    @pytest.mark.asyncio
    async def test_infer_next_action_completed_goal(self, tracker: GoalTracker) -> None:
        """No suggestion when goal is already completed."""
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="已完成的目标",
            initial_intent="query",
        )
        await tracker.complete_goal(goal.goal_id)

        suggestion = await tracker.infer_next_action("alice", "继续下一步")
        assert suggestion is None

    @pytest.mark.asyncio
    async def test_infer_next_action_approval_phase(self, tracker: GoalTracker) -> None:
        """Approval-related messages in await_approval phase."""
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="等待审批",
            pattern=GoalPattern.PROPOSAL_TO_IMPLEMENT,
        )
        # Advance to await_approval phase
        await tracker.advance_phase("alice", next_phase="await_approval")

        suggestion = await tracker.infer_next_action("alice", "领导已经同意了")
        assert suggestion is not None
        assert "approval" in suggestion
