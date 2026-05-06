"""TDD tests for IntentLink — step-level intent tracking for "继续" continuity.

Tests what needs to be built:
1. IntentLink table in SQLite: records dag-level step state per user intent
2. When a DAG subtask completes/fails, IntentLink.current_step advances
3. When user says "继续", the enriched block tells exact step to resume
4. IntentLink is_active=false when DAG fully completes
5. Resumption count tracks how many times user said "继续"
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hermes_os.task_scheduler import TaskPriority, TaskStatus


@pytest.fixture
def scheduler(tmp_path: Path) -> TaskScheduler:
    from hermes_os.task_scheduler import TaskScheduler
    return TaskScheduler(db_path=str(tmp_path / "test_intent_link.db"))


# ---------------------------------------------------------------------------
# IntentLink table creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intent_link_table_created(scheduler: TaskScheduler) -> None:
    """_lazy_init creates intent_links table."""
    await scheduler._lazy_init()
    db = await scheduler._get_db()
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='intent_links'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None, "intent_links table should be created"


@pytest.mark.asyncio
async def test_create_intent_link(scheduler: TaskScheduler) -> None:
    """create_intent_link() creates a record and returns IntentLinkData."""
    await scheduler._lazy_init()
    link = await scheduler.create_intent_link(
        user_id="alice",
        topic="投资组合分析",
        intent_type="investment",
        dag_id="dag-001",
        dag_parent_task_id="parent-001",
        total_steps=5,
    )
    assert link is not None
    assert link.user_id == "alice"
    assert link.topic == "投资组合分析"
    assert link.dag_id == "dag-001"
    assert link.current_step == 1
    assert link.total_steps == 5
    assert link.is_active is True
    assert link.resumption_count == 0


# ---------------------------------------------------------------------------
# Advance current step on subtask completion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_advance_step_on_subtask_complete(scheduler: TaskScheduler) -> None:
    """_on_task_completed advances IntentLink.current_step when a subtask completes."""
    await scheduler._lazy_init()

    step1 = await scheduler.create_task(
        user_id="alice",
        title="Step 1",
        description="First",
        metadata={"dag_id": "dag-002", "dag_step": 1},
    )
    step2 = await scheduler.create_task(
        user_id="alice",
        title="Step 2",
        description="Second",
        metadata={"dag_id": "dag-002", "dag_step": 2},
    )
    step3 = await scheduler.create_task(
        user_id="alice",
        title="Step 3",
        description="Third",
        metadata={"dag_id": "dag-002", "dag_step": 3},
    )

    # Create IntentLink with pending step IDs populated
    link = await scheduler.create_intent_link(
        user_id="alice",
        topic="研究计划",
        intent_type="research",
        dag_id="dag-002",
        dag_parent_task_id="parent-002",
        total_steps=3,
    )
    # Manually set pending IDs (in real flow, create_intent_link would be called
    # after all tasks are created, with full knowledge of task IDs)
    link.pending_step_ids = [step1.task_id, step2.task_id, step3.task_id]
    await scheduler.update_intent_link(link)

    # Simulate completing step 1
    await scheduler.update_task_status(step1.task_id, TaskStatus.COMPLETED)

    # Reload and check current_step advanced to 2
    updated = await scheduler.get_intent_link_by_dag("dag-002")
    assert updated is not None
    assert updated.current_step == 2
    assert updated.pending_step_ids == [step2.task_id, step3.task_id]


@pytest.mark.asyncio
async def test_intent_link_deactivates_on_dag_complete(scheduler: TaskScheduler) -> None:
    """IntentLink.is_active becomes False when all DAG steps complete."""
    await scheduler._lazy_init()

    step1 = await scheduler.create_task(
        user_id="alice",
        title="唯一步骤",
        description="Only",
        metadata={"dag_id": "dag-003", "dag_step": 1},
    )

    link = await scheduler.create_intent_link(
        user_id="alice",
        topic="短任务",
        intent_type="code",
        dag_id="dag-003",
        dag_parent_task_id="parent-003",
        total_steps=1,
    )
    link.pending_step_ids = [step1.task_id]
    await scheduler.update_intent_link(link)

    await scheduler.update_task_status(step1.task_id, TaskStatus.COMPLETED)

    updated = await scheduler.get_intent_link_by_dag("dag-003")
    assert updated is not None
    assert updated.is_active is False


@pytest.mark.asyncio
async def test_failed_step_preserves_error_context(scheduler: TaskScheduler) -> None:
    """When a subtask fails, the error is stored in IntentLink."""
    await scheduler._lazy_init()

    step1 = await scheduler.create_task(
        user_id="alice",
        title="API 调用",
        description="Call API",
        metadata={"dag_id": "dag-004", "dag_step": 1},
    )
    step2 = await scheduler.create_task(
        user_id="alice",
        title="API 处理",
        description="Process",
        metadata={"dag_id": "dag-004", "dag_step": 2},
    )

    link = await scheduler.create_intent_link(
        user_id="alice",
        topic="API 集成",
        intent_type="code",
        dag_id="dag-004",
        dag_parent_task_id="parent-004",
        total_steps=2,
    )
    link.pending_step_ids = [step1.task_id, step2.task_id]
    await scheduler.update_intent_link(link)

    # Simulate failure
    await scheduler.update_task_status(
        step1.task_id,
        TaskStatus.FAILED,
        error="API rate limit exceeded",
    )

    updated = await scheduler.get_intent_link_by_dag("dag-004")
    assert updated is not None
    assert updated.current_step == 1  # still on step 1
    assert updated.last_error == "API rate limit exceeded"
    assert updated.retry_count == 1


# ---------------------------------------------------------------------------
# Resumption tracking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_resumption_increments_count(scheduler: TaskScheduler) -> None:
    """record_resumption() increments resumption_count each time user says '继续'."""
    await scheduler._lazy_init()

    step1 = await scheduler.create_task(user_id="alice", title="S1", description="", metadata={"dag_id": "dag-005", "dag_step": 1})
    step2 = await scheduler.create_task(user_id="alice", title="S2", description="", metadata={"dag_id": "dag-005", "dag_step": 2})
    step3 = await scheduler.create_task(user_id="alice", title="S3", description="", metadata={"dag_id": "dag-005", "dag_step": 3})

    link = await scheduler.create_intent_link(
        user_id="alice",
        topic="文档撰写",
        intent_type="write",
        dag_id="dag-005",
        dag_parent_task_id="parent-005",
        total_steps=3,
    )
    link.pending_step_ids = [step1.task_id, step2.task_id, step3.task_id]
    await scheduler.update_intent_link(link)

    await scheduler.record_resumption("dag-005")
    await scheduler.record_resumption("dag-005")
    await scheduler.record_resumption("dag-005")

    updated = await scheduler.get_intent_link_by_dag("dag-005")
    assert updated is not None
    assert updated.resumption_count == 3


@pytest.mark.asyncio
async def test_get_active_intent_link(scheduler: TaskScheduler) -> None:
    """get_active_intent_link(user_id) returns the active IntentLink for a user."""
    await scheduler._lazy_init()

    step1 = await scheduler.create_task(user_id="alice", title="S1", description="", metadata={"dag_id": "dag-complete", "dag_step": 1})
    step2 = await scheduler.create_task(user_id="alice", title="S2", description="", metadata={"dag_id": "dag-active", "dag_step": 1})
    step3 = await scheduler.create_task(user_id="alice", title="S3", description="", metadata={"dag_id": "dag-active", "dag_step": 2})

    link1 = await scheduler.create_intent_link(
        user_id="alice",
        topic="已完成的任务",
        intent_type="research",
        dag_id="dag-complete",
        dag_parent_task_id="parent-complete",
        total_steps=1,
    )
    link1.pending_step_ids = [step1.task_id]
    await scheduler.update_intent_link(link1)

    link2 = await scheduler.create_intent_link(
        user_id="alice",
        topic="进行中的任务",
        intent_type="code",
        dag_id="dag-active",
        dag_parent_task_id="parent-active",
        total_steps=2,
    )
    link2.pending_step_ids = [step2.task_id, step3.task_id]
    await scheduler.update_intent_link(link2)

    await scheduler.update_task_status(step1.task_id, TaskStatus.COMPLETED)

    active = await scheduler.get_active_intent_link("alice")
    assert active is not None
    assert active.dag_id == "dag-active"


# ---------------------------------------------------------------------------
# Enriched block for "继续" detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_continuation_context_returns_enriched_block(scheduler: TaskScheduler) -> None:
    """get_continuation_context(dag_id) returns step-level info for LLM."""
    await scheduler._lazy_init()

    step1 = await scheduler.create_task(
        user_id="alice",
        title="数据收集",
        description="收集数据",
        metadata={"dag_id": "dag-006", "dag_step": 1},
    )
    step2 = await scheduler.create_task(
        user_id="alice",
        title="数据分析",
        description="分析数据",
        metadata={"dag_id": "dag-006", "dag_step": 2},
    )
    step3 = await scheduler.create_task(
        user_id="alice",
        title="报告撰写",
        description="写报告",
        metadata={"dag_id": "dag-006", "dag_step": 3},
    )

    link = await scheduler.create_intent_link(
        user_id="alice",
        topic="投资组合分析",
        intent_type="investment",
        dag_id="dag-006",
        dag_parent_task_id="parent-006",
        total_steps=3,
    )
    link.pending_step_ids = [step1.task_id, step2.task_id, step3.task_id]
    await scheduler.update_intent_link(link)

    await scheduler.update_task_status(step1.task_id, TaskStatus.COMPLETED)

    ctx = await scheduler.get_continuation_context("dag-006")
    assert ctx is not None
    assert ctx.current_step == 2
    assert ctx.step_title == "数据分析"
    assert ctx.completed_steps == 1
    assert ctx.total_steps == 3
    assert ctx.completion_pct == 33
    assert ctx.pending_step_ids == [step2.task_id, step3.task_id]
    assert ctx.last_error is None


# ---------------------------------------------------------------------------
# Task failure attribution — error categorization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_intent_link_on_task_failure_stores_error(scheduler: TaskScheduler) -> None:
    """Task failure with InvocationError stores error + categorizes."""
    await scheduler._lazy_init()

    step1 = await scheduler.create_task(
        user_id="alice",
        title="生成代码",
        description="Generate code",
        metadata={"dag_id": "dag-007", "dag_step": 1},
    )
    step2 = await scheduler.create_task(
        user_id="alice",
        title="测试代码",
        description="Test",
        metadata={"dag_id": "dag-007", "dag_step": 2},
    )

    link = await scheduler.create_intent_link(
        user_id="alice",
        topic="代码生成",
        intent_type="code",
        dag_id="dag-007",
        dag_parent_task_id="parent-007",
        total_steps=2,
    )
    link.pending_step_ids = [step1.task_id, step2.task_id]
    await scheduler.update_intent_link(link)

    await scheduler.update_task_status(
        step1.task_id,
        TaskStatus.FAILED,
        error="Tool timeout: claude code took > 120s",
    )

    updated = await scheduler.get_intent_link_by_dag("dag-007")
    assert updated is not None
    assert updated.last_error == "Tool timeout: claude code took > 120s"
    assert updated.retry_count == 1
    assert updated.error_category == "timeout"


@pytest.mark.asyncio
async def test_retry_count_increments_on_failure(scheduler: TaskScheduler) -> None:
    """Each failure increments retry_count on the IntentLink."""
    await scheduler._lazy_init()

    step1 = await scheduler.create_task(
        user_id="alice",
        title="运行测试",
        description="Run tests",
        metadata={"dag_id": "dag-008", "dag_step": 1},
    )

    link = await scheduler.create_intent_link(
        user_id="alice",
        topic="测试任务",
        intent_type="test",
        dag_id="dag-008",
        dag_parent_task_id="parent-008",
        total_steps=1,
    )
    link.pending_step_ids = [step1.task_id]
    await scheduler.update_intent_link(link)

    await scheduler.update_task_status(step1.task_id, TaskStatus.FAILED, error="Flaky test")
    await scheduler.update_task_status(step1.task_id, TaskStatus.PENDING)  # reset for retry
    await scheduler.update_task_status(step1.task_id, TaskStatus.FAILED, error="Flaky test again")

    updated = await scheduler.get_intent_link_by_dag("dag-008")
    assert updated is not None
    assert updated.retry_count == 2


# ---------------------------------------------------------------------------
# Helper: classify error category from error message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_category_classification(scheduler: TaskScheduler) -> None:
    """Error messages are classified into categories: timeout, skill, rate_limit, auth, unknown."""
    from hermes_os.task_scheduler import _classify_error

    assert _classify_error("Tool timeout: exceeded 120s") == "timeout"
    assert _classify_error("Skill not found: unknown_skill") == "skill"
    assert _classify_error("API rate limit exceeded") == "rate_limit"
    assert _classify_error("Authentication failed: invalid token") == "auth"
    assert _classify_error("Something completely unexpected") == "unknown"


# ---------------------------------------------------------------------------
# IntentLinkData dataclass exists and has required fields
# ---------------------------------------------------------------------------


def test_intent_link_dataclass_fields() -> None:
    """IntentLinkData has all required fields for step-level continuation."""
    from hermes_os.task_scheduler import IntentLinkData

    fields = IntentLinkData.__dataclass_fields__.keys()
    required = {
        "user_id", "topic", "intent_type", "dag_id", "dag_parent_task_id",
        "current_step", "total_steps", "completed_steps", "pending_step_ids",
        "last_error", "error_category", "retry_count", "resumption_count", "is_active",
    }
    assert required.issubset(fields), f"Missing fields: {required - fields}"
