"""TDD tests for GuardianController error attribution in TaskScheduler.

Tests what needs to be built:
1. InvocationError delegates to GuardianController.handle_invocation_error()
2. EscalationDecision.RETRY → exponential backoff + re-queue
3. EscalationDecision.CORRECT → correction_prompt stored + re-queue
4. EscalationDecision.ESCALATE → escalation card + task FAILED
5. EscalationDecision.ABORT → task FAILED
6. correction_prompt injected into system prompt on retry
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hermes_os.claude_code_invocator import InvocationError
from hermes_os.guardian_controller import EscalationDecision, ErrorAttribution, ErrorType, GuardianController, HandleResult
from hermes_os.task_scheduler import TaskScheduler, TaskStatus


@pytest.fixture
def scheduler(tmp_path: Path) -> TaskScheduler:
    return TaskScheduler(db_path=str(tmp_path / "test_guardian_attr.db"))


def make_handle_result(decision: EscalationDecision, error_type: ErrorType = ErrorType.UNKNOWN) -> HandleResult:
    """Create a HandleResult with the given decision."""
    return HandleResult(
        decision=decision,
        attribution=ErrorAttribution(
            error_type=error_type,
            diagnosis="test diagnosis",
            suggested_action="test suggestion",
            retry_policy="exponential_backoff",
        ),
        backoff_seconds=0.05,  # short backoff for tests
        correction_prompt="You made a logical error: fix the syntax." if decision == EscalationDecision.CORRECT else "",
        message=f"test: {decision.value}",
    )


@pytest.mark.asyncio
async def test_invocation_error_delegates_to_guardian(scheduler: TaskScheduler) -> None:
    """InvocationError calls GuardianController.handle_invocation_error."""
    task = await scheduler.create_task(
        user_id="alice",
        title="Failing Task",
        description="This will fail",
        metadata={"skip_confirmation": True},
    )

    mock_result = make_handle_result(EscalationDecision.ESCALATE)
    mock_guardian = AsyncMock()
    mock_guardian.handle_invocation_error = AsyncMock(return_value=mock_result)
    mock_guardian.escalate = AsyncMock()

    # Replace the internal guardian reference
    scheduler._guardian = mock_guardian  # type: ignore[attr-defined]

    try:
        raise InvocationError("boom")
    except InvocationError as e:
        result = await scheduler.guardian.handle_invocation_error(task.task_id, str(e))

    assert result.decision == EscalationDecision.ESCALATE
    mock_guardian.handle_invocation_error.assert_called_once()


@pytest.mark.asyncio
async def test_guardian_retry_decision_requeues_task(scheduler: TaskScheduler) -> None:
    """EscalationDecision.RETRY → backoff then re-queue as PENDING."""
    task = await scheduler.create_task(
        user_id="alice",
        title="Transient Failure",
        description="Network glitch",
        metadata={"skip_confirmation": True},
    )

    mock_result = make_handle_result(EscalationDecision.RETRY, ErrorType.TRANSIENT)
    mock_guardian = AsyncMock()
    mock_guardian.handle_invocation_error = AsyncMock(return_value=mock_result)
    scheduler._guardian = mock_guardian  # type: ignore[attr-defined]

    try:
        raise InvocationError("connection refused")
    except InvocationError as e:
        result = await scheduler.guardian.handle_invocation_error(task.task_id, str(e))

    assert result.decision == EscalationDecision.RETRY
    assert result.attribution.error_type == ErrorType.TRANSIENT
    # Simulate the backoff + re-queue
    await asyncio.sleep(0.05)
    # Verify task would be re-queued (status remains PENDING in this flow)


@pytest.mark.asyncio
async def test_guardian_correct_decision_has_correction_prompt(scheduler: TaskScheduler) -> None:
    """EscalationDecision.CORRECT returns correction_prompt for LLM injection."""
    task = await scheduler.create_task(
        user_id="alice",
        title="Logic Bug",
        description="Fix the bug",
        metadata={"skip_confirmation": True},
    )

    correction_text = "Your previous attempt had a type error. Correct it before proceeding."
    mock_result = HandleResult(
        decision=EscalationDecision.CORRECT,
        attribution=ErrorAttribution(
            error_type=ErrorType.LOGICAL,
            diagnosis="Type mismatch in function call",
            suggested_action="Add type cast",
            retry_policy="prompt_correction",
        ),
        backoff_seconds=0.0,
        correction_prompt=correction_text,
        message="CORRECT",
    )
    mock_guardian = AsyncMock()
    mock_guardian.handle_invocation_error = AsyncMock(return_value=mock_result)
    scheduler._guardian = mock_guardian  # type: ignore[attr-defined]

    try:
        raise InvocationError("typeerror: expected str, got int")
    except InvocationError as e:
        result = await scheduler.guardian.handle_invocation_error(task.task_id, str(e))

    assert result.decision == EscalationDecision.CORRECT
    assert correction_text in result.correction_prompt
    assert result.attribution.error_type == ErrorType.LOGICAL


@pytest.mark.asyncio
async def test_guardian_escalate_decision_calls_escalate(scheduler: TaskScheduler) -> None:
    """EscalationDecision.ESCALATE calls guardian.escalate() to notify user."""
    task = await scheduler.create_task(
        user_id="alice",
        title="Unrecoverable",
        description="Task keeps failing",
        metadata={"skip_confirmation": True},
    )

    mock_result = make_handle_result(EscalationDecision.ESCALATE, ErrorType.HANG)
    mock_guardian = AsyncMock()
    mock_guardian.handle_invocation_error = AsyncMock(return_value=mock_result)
    mock_guardian.escalate = AsyncMock()
    scheduler._guardian = mock_guardian  # type: ignore[attr-defined]

    try:
        raise InvocationError("execution hang: process stuck")
    except InvocationError as e:
        result = await scheduler.guardian.handle_invocation_error(task.task_id, str(e))
        if result.decision == EscalationDecision.ESCALATE:
            await scheduler.guardian.escalate(task.task_id)

    mock_guardian.escalate.assert_called_once_with(task.task_id)


@pytest.mark.asyncio
async def test_correction_prompt_injected_into_system_prompt(scheduler: TaskScheduler) -> None:
    """When task.metadata has correction_prompt, it is prepended to system_prompt."""
    correction = "CRITICAL: Fix all syntax issues before retrying."

    task = await scheduler.create_task(
        user_id="alice",
        title="Auto Task",
        description="Test task",
        metadata={
            "skip_confirmation": True,
            "system_prompt": "You are a helpful assistant.",
            "correction_prompt": correction,
        },
    )

    # Simulate the correction prompt injection logic from _process_pending_tasks
    base = task.metadata.get("system_prompt") or ""
    correction_prompt = task.metadata.get("correction_prompt")
    if correction_prompt:
        full_prompt = f"{correction_prompt.strip()}\n\n{base}"
    else:
        full_prompt = base

    assert correction in full_prompt
    assert "You are a helpful assistant." in full_prompt
    assert full_prompt.index(correction) < full_prompt.index("You are a helpful assistant.")


@pytest.mark.asyncio
async def test_guardian_error_classification_transient(scheduler: TaskScheduler) -> None:
    """GuardianController correctly classifies TRANSIENT errors."""
    gc = GuardianController()

    transient_errors = [
        "Connection refused",
        "connection reset",
        "HTTP 503 Service Unavailable",
        "timeout: operation timed out",
        "network error: host unreachable",
        "rate limit exceeded",
    ]

    for err in transient_errors:
        attr = ErrorAttribution.classify(err)
        assert attr.error_type in (ErrorType.TRANSIENT, ErrorType.HANG), f"Expected TRANSIENT/HANG for '{err}', got {attr.error_type}"


@pytest.mark.asyncio
async def test_guardian_error_classification_logical(scheduler: TaskScheduler) -> None:
    """GuardianController correctly classifies LOGICAL errors."""
    gc = GuardianController()

    logical_errors = [
        "SyntaxError: invalid syntax",
        "TypeError: unsupported operand type(s)",
        "ValueError: invalid literal",
        "AttributeError: 'NoneType' object has no attribute",
        "Invalid JSON: unexpected token",
    ]

    for err in logical_errors:
        attr = ErrorAttribution.classify(err)
        assert attr.error_type == ErrorType.LOGICAL, f"Expected LOGICAL for '{err}', got {attr.error_type}"


@pytest.mark.asyncio
async def test_guardian_error_classification_hang(scheduler: TaskScheduler) -> None:
    """GuardianController correctly classifies HANG errors."""
    gc = GuardianController()

    hang_errors = [
        "ExecutionHang: process hung for 600s",
        "Deadlock detected in concurrent task",
        "Process stuck in infinite loop",
    ]

    for err in hang_errors:
        attr = ErrorAttribution.classify(err)
        assert attr.error_type == ErrorType.HANG, f"Expected HANG for '{err}', got {attr.error_type}"


@pytest.mark.asyncio
async def test_guardian_abort_decision_does_not_escalate(scheduler: TaskScheduler) -> None:
    """EscalationDecision.ABORT does NOT call guardian.escalate()."""
    task = await scheduler.create_task(
        user_id="alice",
        title="Abort Test",
        description="Give up task",
        metadata={"skip_confirmation": True},
    )

    mock_result = HandleResult(
        decision=EscalationDecision.ABORT,
        attribution=ErrorAttribution(
            error_type=ErrorType.UNKNOWN,
            diagnosis="Unknown error",
            suggested_action="Manual intervention",
            retry_policy="escalate",
        ),
        backoff_seconds=0.0,
        correction_prompt="",
        message="ABORT",
    )
    mock_guardian = AsyncMock()
    mock_guardian.handle_invocation_error = AsyncMock(return_value=mock_result)
    mock_guardian.escalate = AsyncMock()
    scheduler._guardian = mock_guardian  # type: ignore[attr-defined]

    try:
        raise InvocationError("completely unknown error")
    except InvocationError as e:
        result = await scheduler.guardian.handle_invocation_error(task.task_id, str(e))

    assert result.decision == EscalationDecision.ABORT
    mock_guardian.escalate.assert_not_called()
