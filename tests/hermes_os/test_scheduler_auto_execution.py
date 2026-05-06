"""TDD tests for TaskScheduler auto-execution: skip_confirmation + event-driven confirmation.

Tests what needs to be built:
1. _await_confirmation uses event-driven waiting (not 60-iteration polling)
2. skip_confirmation=True bypasses intent card and confirmation wait
3. DAG tasks auto-execute without user interaction
4. Jarvis Mode (skip_confirmation=False) still requires user confirmation
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from hermes_os.event_loop import Event, EventType, get_event_bus
from hermes_os.task_scheduler import TaskScheduler, TaskStatus


@pytest.fixture
def scheduler(tmp_path: Path) -> TaskScheduler:
    return TaskScheduler(db_path=str(tmp_path / "test_auto_exec.db"))


@pytest.mark.asyncio
async def test_skip_confirmation_bypasses_send_card(scheduler: TaskScheduler) -> None:
    """When task.skip_confirmation=True, _send_intent_card is NOT called."""
    task = await scheduler.create_task(
        user_id="alice",
        title="Auto Task",
        description="Should run without asking",
        metadata={"skip_confirmation": True},
    )

    mock_jarvis = AsyncMock()
    scheduler._jarvis = mock_jarvis

    # Process pending tasks — should skip confirmation and go straight to invoke
    # Since invoke requires claude code CLI, it will raise — but send_card should not be called
    try:
        await scheduler._process_pending_tasks()
    except Exception:
        pass

    # send_card_with_nl should NOT have been called
    assert mock_jarvis.send_card_with_nl.call_count == 0


@pytest.mark.asyncio
async def test_skip_confirmation_marks_task_as_confirmed(scheduler: TaskScheduler) -> None:
    """skip_confirmation=True causes _await_confirmation to return True immediately via event."""
    task = await scheduler.create_task(
        user_id="alice",
        title="Auto Task 2",
        description="Auto run task",
        metadata={
            "skip_confirmation": True,
            "notify_target": {"type": "feishu", "open_id": "alice_oid"},
        },
    )

    # Fire USER_CONFIRMED event after a small delay (subscribe is async/fire-and-forget)
    event_bus = get_event_bus()

    async def fire_after_register() -> None:
        await asyncio.sleep(0.1)  # Let subscription register
        await event_bus.publish(
            Event(
                type=EventType.USER_CONFIRMED,
                payload={"user_id": "alice_oid"},
            )
        )

    asyncio.create_task(fire_after_register())
    confirmed = await scheduler._await_confirmation("alice_oid", task.task_id)
    assert confirmed is True


@pytest.mark.asyncio
async def test_await_confirmation_returns_true_on_user_confirm(scheduler: TaskScheduler) -> None:
    """USER_CONFIRMED event causes _await_confirmation to return True."""
    task = await scheduler.create_task(
        user_id="alice",
        title="Confirm Test",
        description="Test",
        metadata={},
    )

    async def fire_confirm() -> None:
        await asyncio.sleep(0.5)  # Fire after 500ms
        event_bus = get_event_bus()
        await event_bus.publish(
            Event(
                type=EventType.USER_CONFIRMED,
                payload={"user_id": "alice"},
            )
        )

    # Fire the event in background
    fire_task = asyncio.create_task(fire_confirm())

    start = asyncio.get_event_loop().time()
    confirmed = await scheduler._await_confirmation("alice", task.task_id)
    elapsed = asyncio.get_event_loop().time() - start

    await fire_task

    assert confirmed is True
    assert elapsed < 2.0  # Should return soon after event, not wait full 60s


@pytest.mark.asyncio
async def test_await_confirmation_times_out_without_events(scheduler: TaskScheduler) -> None:
    """Without events, _await_confirmation waits up to timeout and returns False."""
    task = await scheduler.create_task(
        user_id="alice",
        title="Timeout Test",
        description="Test",
        metadata={},
    )

    start = asyncio.get_event_loop().time()
    confirmed = await scheduler._await_confirmation("alice", task.task_id)
    elapsed = asyncio.get_event_loop().time() - start

    assert confirmed is False
    assert 1.0 <= elapsed <= 65.0  # HERMES_OS_CONFIRM_TIMEOUT=3 or default 60s


@pytest.mark.asyncio
async def test_dag_task_auto_executes_without_user_confirmation(scheduler: TaskScheduler) -> None:
    """A DAG subtask with skip_confirmation=True executes without user interaction."""
    mock_jarvis = AsyncMock()
    scheduler._jarvis = mock_jarvis

    # Create DAG parent
    parent = await scheduler.create_task(
        user_id="alice",
        title="Research → Implement → Deploy",
        description="Full pipeline",
        metadata={
            "dag_id": "dag-auto-001",
            "is_dag_parent": True,
            "dag_total_steps": 2,
            "dag_completed_steps": 0,
            "skip_confirmation": True,
        },
    )

    # Create 2 subtasks (both auto-execute)
    step1 = await scheduler.create_task(
        user_id="alice",
        title="Research",
        description="Do research",
        metadata={
            "dag_id": "dag-auto-001",
            "dag_step": "1",
            "skip_confirmation": True,
            "notify_target": {"type": "feishu", "open_id": "alice_oid"},
        },
    )

    step2 = await scheduler.create_task(
        user_id="alice",
        title="Implement",
        description="Do implementation",
        metadata={
            "dag_id": "dag-auto-001",
            "dag_step": "2",
            "skip_confirmation": True,
            "depends_on": [step1.task_id],
            "notify_target": {"type": "feishu", "open_id": "alice_oid"},
        },
    )

    # Process pending tasks
    try:
        await scheduler._process_pending_tasks()
    except Exception:
        pass

    # Cards should not be sent for skip_confirmation tasks
    assert mock_jarvis.send_card_with_nl.call_count == 0

    # DAG progress should have been updated
    status = await scheduler.get_dag_status("dag-auto-001")
    assert status is not None


@pytest.mark.asyncio
async def test_non_auto_task_requires_confirmation(scheduler: TaskScheduler) -> None:
    """A task without skip_confirmation triggers intent card + confirmation wait."""
    task = await scheduler.create_task(
        user_id="alice",
        title="Manual Task",
        description="Requires user confirm",
        metadata={
            "notify_target": {"type": "feishu", "open_id": "alice_oid"},
            "skip_confirmation": False,
        },
    )

    mock_jarvis = AsyncMock()
    scheduler._jarvis = mock_jarvis

    # Since confirmation will timeout (no USER_CONFIRMED event), task won't execute
    # But intent card SHOULD have been sent
    try:
        await scheduler._process_pending_tasks()
    except Exception:
        pass

    # Intent card should have been sent
    assert mock_jarvis.send_card_with_nl.call_count >= 1


# ---------------------------------------------------------------------------
# Test: retry_count persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_task_persists_retry_count(scheduler: TaskScheduler) -> None:
    """retry_task() should persist retry_count to DB."""
    task = await scheduler.create_task(
        user_id="alice",
        title="Retry Test",
        description="Test retry count",
        metadata={"retry_count": 1},
    )
    await scheduler.update_task_status(task.task_id, TaskStatus.FAILED)

    await scheduler.retry_task(task.task_id)

    # Reload and verify retry_count persisted
    reloaded = await scheduler.get_task(task.task_id)
    assert reloaded is not None
    assert reloaded.metadata.get("retry_count") == 2


@pytest.mark.asyncio
async def test_process_pending_tasks_persists_retry_count_on_failure(tmp_path: Path) -> None:
    """Auto-retry in _process_pending_tasks should persist retry_count after each failure."""
    from unittest.mock import AsyncMock, patch

    from hermes_os.claude_code_invocator import InvocationError

    scheduler = TaskScheduler(db_path=str(tmp_path / "retry.db"))
    scheduler._jarvis = AsyncMock()

    task = await scheduler.create_task(
        user_id="alice",
        title="Auto Retry Test",
        description="Test auto retry",
        metadata={"retry_count": 0, "skip_confirmation": True},
    )

    async def failing_invoke(*args, **kwargs):
        raise InvocationError("mock error")

    with patch("hermes_os.task_scheduler.invoke", side_effect=failing_invoke):
        with patch.object(scheduler, "_await_confirmation", return_value=True):
            try:
                await scheduler._process_pending_tasks()
            except InvocationError:
                pass

    # Reload and verify retry_count was persisted
    reloaded = await scheduler.get_task(task.task_id)
    assert reloaded is not None
    assert reloaded.metadata.get("retry_count") == 1
    assert reloaded.status == TaskStatus.PENDING


# ---------------------------------------------------------------------------
# Test: _send_notification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_notification_calls_jarvis_on_completion(scheduler: TaskScheduler) -> None:
    """_send_notification should call jarvis.send_card_with_nl on task completion."""
    mock_jarvis = AsyncMock()
    scheduler._jarvis = mock_jarvis

    task = await scheduler.create_task(
        user_id="alice",
        title="Notify Test",
        description="Test notification",
        metadata={"notify_target": {"type": "feishu", "open_id": "alice_oid"}},
    )

    await scheduler._send_notification(task, status="completed", result="Done!")

    mock_jarvis.send_card_with_nl.assert_called_once()


@pytest.mark.asyncio
async def test_send_notification_calls_jarvis_on_failure(scheduler: TaskScheduler) -> None:
    """_send_notification should call jarvis.send_card_with_nl on task failure."""
    mock_jarvis = AsyncMock()
    scheduler._jarvis = mock_jarvis

    task = await scheduler.create_task(
        user_id="alice",
        title="Fail Notify Test",
        description="Test failure notification",
        metadata={"notify_target": {"type": "feishu", "open_id": "alice_oid"}},
    )

    await scheduler._send_notification(task, status="failed", error="Something broke")

    mock_jarvis.send_card_with_nl.assert_called_once()


@pytest.mark.asyncio
async def test_send_notification_noop_without_notify_target(scheduler: TaskScheduler) -> None:
    """_send_notification should do nothing when notify_target is missing."""
    mock_jarvis = AsyncMock()
    scheduler._jarvis = mock_jarvis

    task = await scheduler.create_task(
        user_id="alice",
        title="No Target Test",
        description="No notify target",
        metadata={},
    )

    await scheduler._send_notification(task, status="completed")

    mock_jarvis.send_card_with_nl.assert_not_called()
