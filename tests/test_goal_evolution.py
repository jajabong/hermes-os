"""Tests for GoalTracker Evolution Log — track goal changes over time.

Instead of overwriting old goals, we record an "evolution path" so the system
can answer "why did the goal change?" and help users recover context.
"""

import os
from datetime import UTC, datetime

import pytest

from hermes_os.goal_tracker import GoalTracker

# ---------------------------------------------------------------------------
# EvolutionEntry and EvolutionLog
# ---------------------------------------------------------------------------


class TestEvolutionEntry:
    def test_evolution_entry_fields(self) -> None:
        from hermes_os.goal_tracker import EvolutionEntry

        entry = EvolutionEntry(
            goal_id="g1",
            timestamp=datetime.now(UTC),
            previous_description="研究供应商",
            new_description="实现供应商对比",
            reason="用户决定从研究转向实现",
            trigger="user_input",
        )
        assert entry.previous_description == "研究供应商"
        assert entry.new_description == "实现供应商对比"
        assert entry.trigger == "user_input"


# ---------------------------------------------------------------------------
# append_evolution_log
# ---------------------------------------------------------------------------


class TestGoalEvolution:
    @pytest.fixture
    def tracker(self) -> GoalTracker:
        db_path = "/tmp/test_hermes_evolution.db"
        for path in [db_path, db_path + "-wal", db_path + "-shm"]:
            if os.path.exists(path):
                os.remove(path)
        t = GoalTracker(db_path=db_path)
        return t

    @pytest.mark.asyncio
    async def test_append_evolution_log_creates_record(self, tracker: GoalTracker) -> None:
        """Appending an evolution log creates a DB record."""
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="研究供应商",
            initial_intent="research",
        )

        await tracker.append_evolution_log(
            goal_id=goal.goal_id,
            new_description="实现供应商对比",
            reason="用户决定从研究转向实现",
            trigger="user_input",
        )

        history = await tracker.get_evolution_history(goal.goal_id)
        assert len(history) == 1
        assert history[0].previous_description == "研究供应商"
        assert history[0].new_description == "实现供应商对比"
        assert history[0].reason == "用户决定从研究转向实现"

    @pytest.mark.asyncio
    async def test_multiple_evolutions_tracked(self, tracker: GoalTracker) -> None:
        """Multiple goal changes are all recorded (not overwritten)."""
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="研究",
            initial_intent="research",
        )

        await tracker.append_evolution_log(
            goal_id=goal.goal_id,
            new_description="实现",
            reason="转向实现",
            trigger="user_input",
        )
        await tracker.append_evolution_log(
            goal_id=goal.goal_id,
            new_description="重构",
            reason="代码需要重构",
            trigger="user_input",
        )

        history = await tracker.get_evolution_history(goal.goal_id)
        assert len(history) == 2
        assert history[0].new_description == "实现"
        assert history[1].new_description == "重构"

    @pytest.mark.asyncio
    async def test_get_evolution_history_returns_ordered(self, tracker: GoalTracker) -> None:
        """Evolution history is returned in chronological order (oldest first)."""
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="初始目标",
            initial_intent="research",
        )

        await tracker.append_evolution_log(goal.goal_id, "目标2", "原因1", "user_input")
        await tracker.append_evolution_log(goal.goal_id, "目标3", "原因2", "user_input")

        history = await tracker.get_evolution_history(goal.goal_id)
        assert len(history) == 2
        assert history[0].new_description == "目标2"
        assert history[1].new_description == "目标3"

    @pytest.mark.asyncio
    async def test_get_evolution_history_empty_for_unknown_goal(self, tracker: GoalTracker) -> None:
        """Unknown goal returns empty history."""
        await tracker.initialize()
        history = await tracker.get_evolution_history("nonexistent")
        assert history == []

    @pytest.mark.asyncio
    async def test_get_latest_evolution_reason(self, tracker: GoalTracker) -> None:
        """Can retrieve just the most recent reason for context disambiguation."""
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="初始",
            initial_intent="research",
        )

        await tracker.append_evolution_log(goal.goal_id, "中期目标", "第一个改变", "user_input")
        await tracker.append_evolution_log(
            goal.goal_id, "最终目标", "用户明确最终方向", "user_input"
        )

        latest = await tracker.get_latest_evolution_reason(goal.goal_id)
        assert latest == "用户明确最终方向"


# ---------------------------------------------------------------------------
# get_context_with_evolution
# ---------------------------------------------------------------------------


class TestGetContextWithEvolution:
    @pytest.fixture
    def tracker(self) -> GoalTracker:
        db_path = "/tmp/test_hermes_evolution_ctx.db"
        for path in [db_path, db_path + "-wal", db_path + "-shm"]:
            if os.path.exists(path):
                os.remove(path)
        t = GoalTracker(db_path=db_path)
        return t

    @pytest.mark.asyncio
    async def test_context_includes_evolution_history(self, tracker: GoalTracker) -> None:
        """When getting goal context, evolution history is included."""
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="供应商对比分析",
            initial_intent="research",
        )

        await tracker.append_evolution_log(
            goal.goal_id,
            "供应商对比分析v2",
            "用户要求更详细",
            "user_input",
        )

        context = await tracker.get_context_with_evolution("alice")

        assert "供应商对比分析" in context
        assert "v2" in context
        assert "用户要求更详细" in context or "evolution" in context.lower()

    @pytest.mark.asyncio
    async def test_context_without_evolution_history(self, tracker: GoalTracker) -> None:
        """If no evolution happened, context is same as before."""
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="供应商对比",
            initial_intent="research",
        )

        context = await tracker.get_context_with_evolution("alice")
        context_no_evo = await tracker.get_active_goal_context("alice")

        assert context == context_no_evo


class TestEvolutionEdgeCases:
    """Edge cases for evolution tracking."""

    @pytest.fixture
    def tracker(self) -> GoalTracker:
        db_path = "/tmp/test_evolution_edge.db"
        for path in [db_path, db_path + "-wal", db_path + "-shm"]:
            if os.path.exists(path):
                os.remove(path)
        t = GoalTracker(db_path=db_path)
        return t

    @pytest.mark.asyncio
    async def test_append_evolution_invalid_goal_raises(self, tracker: GoalTracker) -> None:
        """Appending evolution log for non-existent goal raises ValueError."""
        await tracker.initialize()
        with pytest.raises(ValueError, match="Goal .* not found"):
            await tracker.append_evolution_log(
                goal_id="nonexistent-id",
                new_description="新描述",
                reason="测试原因",
                trigger="user_input",
            )

    @pytest.mark.asyncio
    async def test_evolution_trigger_types(self, tracker: GoalTracker) -> None:
        """Different trigger types are recorded correctly."""
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="初始目标",
            initial_intent="research",
        )

        triggers = ["user_input", "system_suggestion", "completion"]
        for i, trigger in enumerate(triggers):
            await tracker.append_evolution_log(
                goal.goal_id,
                f"目标版本{i + 1}",
                f"触发原因{i}",
                trigger=trigger,
            )

        history = await tracker.get_evolution_history(goal.goal_id)
        assert len(history) == 3
        assert history[0].trigger == "user_input"
        assert history[1].trigger == "system_suggestion"
        assert history[2].trigger == "completion"

    @pytest.mark.asyncio
    async def test_evolution_preserves_previous_description(self, tracker: GoalTracker) -> None:
        """Each evolution entry preserves the previous description."""
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="v1.0",
            initial_intent="research",
        )

        await tracker.append_evolution_log(goal.goal_id, "v2.0", "更新", "user_input")
        await tracker.append_evolution_log(goal.goal_id, "v3.0", "再次更新", "user_input")

        history = await tracker.get_evolution_history(goal.goal_id)
        assert history[0].previous_description == "v1.0"
        assert history[0].new_description == "v2.0"
        assert history[1].previous_description == "v2.0"
        assert history[1].new_description == "v3.0"

    @pytest.mark.asyncio
    async def test_get_latest_evolution_reason_empty(self, tracker: GoalTracker) -> None:
        """No evolution returns None for latest reason."""
        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="无历史目标",
            initial_intent="query",
        )

        latest = await tracker.get_latest_evolution_reason(goal.goal_id)
        assert latest is None

    @pytest.mark.asyncio
    async def test_evolution_timestamps_increasing(self, tracker: GoalTracker) -> None:
        """Evolution timestamps are in chronological order."""
        import time

        await tracker.initialize()
        goal = await tracker.create_goal(
            user_id="alice",
            description="时间戳测试",
            initial_intent="research",
        )

        await tracker.append_evolution_log(goal.goal_id, "版本2", "原因1", "user_input")
        time.sleep(0.01)  # Small delay to ensure different timestamps
        await tracker.append_evolution_log(goal.goal_id, "版本3", "原因2", "user_input")

        history = await tracker.get_evolution_history(goal.goal_id)
        assert len(history) == 2
        assert history[0].timestamp <= history[1].timestamp
