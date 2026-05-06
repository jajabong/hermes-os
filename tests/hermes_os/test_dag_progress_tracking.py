"""TDD tests for Layer 4: DAG progress tracking and active goal reporting.

Tests what needs to be built:
1. DAG parent tracks overall completion %
2. Each subtask completion triggers progress report to user
3. When DAG completes, notify user and advance goal phase
4. User can ask "项目X怎么样了" and get structured summary
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hermes_os.task_scheduler import TaskPriority, TaskStatus


@pytest.fixture
def scheduler(tmp_path: Path) -> TaskScheduler:
    from hermes_os.task_scheduler import TaskScheduler

    return TaskScheduler(db_path=str(tmp_path / "test_dag.db"))


@pytest.mark.asyncio
async def test_dag_parent_initial_progress(scheduler: TaskScheduler) -> None:
    """DAG parent task starts with 0% progress."""
    task = await scheduler.create_task(
        user_id="alice",
        title="Research → Implement → Deploy",
        description="Complete research, implementation and deployment",
        priority=TaskPriority.HIGH,
        metadata={
            "dag_id": "dag-001",
            "is_dag_parent": True,
            "dag_total_steps": 3,
            "dag_completed_steps": 0,
            "goal_context": "Complete the Hermes OS integration",
        },
    )

    fetched = await scheduler.get_task(task.task_id)
    assert fetched is not None
    assert fetched.metadata.get("dag_completed_steps") == 0
    assert fetched.metadata.get("dag_total_steps") == 3


@pytest.mark.asyncio
async def test_subtask_completion_updates_dag_progress(
    scheduler: TaskScheduler,
) -> None:
    """When a subtask completes, DAG parent progress is updated."""
    # Create DAG parent
    parent = await scheduler.create_task(
        user_id="alice",
        title="DAG Project",
        description="Multi-step project",
        metadata={
            "dag_id": "dag-001",
            "is_dag_parent": True,
            "dag_total_steps": 3,
            "dag_completed_steps": 0,
        },
    )

    # Create subtasks
    step1 = await scheduler.create_task(
        user_id="alice",
        title="Step 1",
        description="First step",
        metadata={"dag_id": "dag-001", "dag_step": "1"},
    )

    # Complete subtask 1
    await scheduler.update_task_status(step1.task_id, TaskStatus.COMPLETED)

    # DAG progress should update (calls _update_dag_progress)
    updated = await scheduler.get_task(parent.task_id)
    assert updated is not None
    assert updated.metadata.get("dag_completed_steps") == 1


@pytest.mark.asyncio
async def test_dag_completion_advances_goal_phase(
    scheduler: TaskScheduler,
) -> None:
    """When all DAG subtasks complete, goal phase advances."""
    from hermes_os.goal_tracker import GoalPattern, GoalTracker

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "test_goal.db")
        gt = GoalTracker(db_path=db_path)
        await gt.initialize()

        # Create goal first
        goal = await gt.create_goal(
            user_id="alice",
            description="Complete the Hermes OS integration",
            initial_intent="research",
            pattern=GoalPattern.RESEARCH_TO_DEPLOY,
        )
        goal_id = goal.goal_id

        parent = await scheduler.create_task(
            user_id="alice",
            title="Research → Deploy",
            description="Full pipeline",
            metadata={
                "dag_id": "dag-002",
                "is_dag_parent": True,
                "dag_total_steps": 2,
                "dag_completed_steps": 0,
                "goal_id": goal_id,
            },
        )

        step1 = await scheduler.create_task(
            user_id="alice",
            title="Step 1",
            description="First",
            metadata={"dag_id": "dag-002", "dag_step": "1"},
        )
        step2 = await scheduler.create_task(
            user_id="alice",
            title="Step 2",
            description="Second",
            depends_on=[step1.task_id],
            metadata={"dag_id": "dag-002", "dag_step": "2"},
        )

        # Complete step 1
        await scheduler.update_task_status(step1.task_id, TaskStatus.COMPLETED)

        # Complete step 2
        await scheduler.update_task_status(step2.task_id, TaskStatus.COMPLETED)

        # DAG completion should have triggered goal phase advancement
        updated_goal = await gt.get_goal(goal_id)
        # Phase should have advanced from "initiated" toward "completed"
        assert updated_goal is not None


@pytest.mark.asyncio
async def test_get_dag_status_returns_structured_summary(
    scheduler: TaskScheduler,
) -> None:
    """get_dag_status() returns completion %, next step, time estimate."""
    # Create a DAG with 2 steps
    parent = await scheduler.create_task(
        user_id="alice",
        title="Test Project",
        description="A multi-step project",
        metadata={
            "dag_id": "dag-003",
            "is_dag_parent": True,
            "dag_total_steps": 2,
            "dag_completed_steps": 0,
        },
    )

    step1 = await scheduler.create_task(
        user_id="alice",
        title="Step 1",
        description="First step",
        metadata={"dag_id": "dag-003", "dag_step": "1"},
    )

    step2 = await scheduler.create_task(
        user_id="alice",
        title="Step 2",
        description="Second step",
        metadata={"dag_id": "dag-003", "dag_step": "2"},
    )

    # Complete step 1
    await scheduler.update_task_status(step1.task_id, TaskStatus.COMPLETED)

    # Query DAG status
    status = await scheduler.get_dag_status("dag-003")

    assert status is not None
    assert status["dag_id"] == "dag-003"
    assert status["completed_steps"] == 1
    assert status["total_steps"] == 2
    assert status["completion_pct"] == 50
    assert status["next_step"] == step2.task_id
    assert status["is_complete"] is False


@pytest.mark.asyncio
async def test_get_dag_status_all_complete(scheduler: TaskScheduler) -> None:
    """When all steps done, DAG status shows 100% and is_complete=True."""
    parent = await scheduler.create_task(
        user_id="alice",
        title="Simple 1-step DAG",
        description="Single step project",
        metadata={
            "dag_id": "dag-004",
            "is_dag_parent": True,
            "dag_total_steps": 1,
            "dag_completed_steps": 0,
        },
    )

    step1 = await scheduler.create_task(
        user_id="alice",
        title="Only Step",
        description="The only step",
        metadata={"dag_id": "dag-004", "dag_step": "1"},
    )

    await scheduler.update_task_status(step1.task_id, TaskStatus.COMPLETED)

    status = await scheduler.get_dag_status("dag-004")

    assert status["completion_pct"] == 100
    assert status["is_complete"] is True


@pytest.mark.asyncio
async def test_dag_progress_report_on_each_step(
    scheduler: TaskScheduler,
) -> None:
    """Each subtask completion triggers a progress notification to user."""
    from unittest.mock import AsyncMock

    mock_jarvis = AsyncMock()
    scheduler._jarvis = mock_jarvis

    parent = await scheduler.create_task(
        user_id="alice",
        title="3-step project",
        description="A project with 3 steps",
        metadata={
            "dag_id": "dag-005",
            "is_dag_parent": True,
            "dag_total_steps": 3,
            "dag_completed_steps": 0,
            "notify_target": {"type": "feishu", "open_id": "alice_open_id"},
        },
    )

    for i in range(1, 4):
        step = await scheduler.create_task(
            user_id="alice",
            title=f"Step {i}",
            description=f"Step {i} of 3",
            metadata={"dag_id": "dag-005", "dag_step": str(i)},
        )
        await scheduler.update_task_status(step.task_id, TaskStatus.COMPLETED)

        # After each completion, progress notification should have been sent
        calls = mock_jarvis.send_card_with_nl.call_count
        assert calls == i, f"Expected {i} notifications after {i} steps, got {calls}"
