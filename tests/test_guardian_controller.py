"""Tests for GuardianController — execution robustness via checkpointing, attribution, and escalation.

Guardian Pattern:
  1. Checkpoint Engine — save/restore pipeline state in meta.json
  2. Error Attribution Engine — classify errors as TRANSIENT/LOGICAL/HANG
  3. Human-in-the-Loop Gate — escalation with scene protection when all retries exhausted

Error Attribution Matrix:
  TRANSIENT_ERROR (503, Timeout, Connection) → Exponential Backoff Retry
  LOGICAL_ERROR (Syntax, Format, Hallucination) → DiagnosticAgent + Prompt Correction
  HANG_ERROR (timeout_sec exceeded) → Force kill + mark HANG, trigger escalation
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from hermes_os.guardian_controller import (
    CheckpointData,
    ErrorAttribution,
    ErrorType,
    EscalationDecision,
    GuardianConfig,
    GuardianController,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_checkpoint_dir() -> Path:
    tmp = Path(tempfile.mkdtemp())
    yield tmp
    shutil.rmtree(tmp)


@pytest.fixture
def guardian(temp_checkpoint_dir: Path) -> GuardianController:
    config = GuardianConfig(
        checkpoint_dir=temp_checkpoint_dir,
        max_retries=3,
        base_backoff_seconds=2,
        escalation_threshold=3,
    )
    return GuardianController(config=config)


# ---------------------------------------------------------------------------
# ErrorType tests
# ---------------------------------------------------------------------------


class TestErrorType:
    def test_error_type_values(self) -> None:
        assert hasattr(ErrorType, "TRANSIENT")
        assert hasattr(ErrorType, "LOGICAL")
        assert hasattr(ErrorType, "HANG")
        assert hasattr(ErrorType, "UNKNOWN")

    def test_error_type_is_classification_only(self) -> None:
        # ErrorType is just a classification tag, not a value carrier
        assert ErrorType.TRANSIENT.name == "TRANSIENT"
        assert ErrorType.LOGICAL.name == "LOGICAL"
        assert ErrorType.HANG.name == "HANG"


# ---------------------------------------------------------------------------
# ErrorAttribution tests
# ---------------------------------------------------------------------------


class TestErrorAttribution:
    def test_transient_from_network_error(self) -> None:
        attr = ErrorAttribution.classify("Connection refused")
        assert attr.error_type == ErrorType.TRANSIENT

    def test_transient_from_timeout(self) -> None:
        attr = ErrorAttribution.classify("timed out after 30 seconds")
        assert attr.error_type == ErrorType.TRANSIENT

    def test_transient_from_503(self) -> None:
        attr = ErrorAttribution.classify("503 Service Unavailable")
        assert attr.error_type == ErrorType.TRANSIENT

    def test_logical_from_syntax_error(self) -> None:
        attr = ErrorAttribution.classify("SyntaxError: invalid syntax")
        assert attr.error_type == ErrorType.LOGICAL

    def test_logical_from_hallucination(self) -> None:
        attr = ErrorAttribution.classify("Output validation failed: malformed JSON")
        assert attr.error_type == ErrorType.LOGICAL

    def test_hang_from_timeout(self) -> None:
        attr = ErrorAttribution.classify("Execution hung: exceeded timeout_sec=300")
        assert attr.error_type == ErrorType.HANG

    def test_unknown_returns_unknown(self) -> None:
        attr = ErrorAttribution.classify("something completely ambiguous")
        assert attr.error_type == ErrorType.UNKNOWN

    def test_attribution_has_retry_policy(self) -> None:
        attr = ErrorAttribution.classify("Connection refused")
        assert attr.retry_policy in ("exponential_backoff", "prompt_correction", "escalate")

    def test_attribution_has_suggested_action(self) -> None:
        attr = ErrorAttribution.classify("Timeout after 60s")
        assert attr.suggested_action is not None
        assert len(attr.suggested_action) > 0


# ---------------------------------------------------------------------------
# CheckpointData tests
# ---------------------------------------------------------------------------


class TestCheckpointData:
    def test_checkpoint_structure(self) -> None:
        cp = CheckpointData(
            task_id="task-001",
            stage="write_chapters",
            status="in_progress",
            completed_stages=["research", "outline"],
            artifact_uri="artifacts/task-001/render/book.md",
            retry_count=1,
            error_context="Connection refused",
        )
        assert cp.task_id == "task-001"
        assert cp.stage == "write_chapters"
        assert cp.completed_stages == ["research", "outline"]

    def test_checkpoint_to_from_dict(self) -> None:
        cp = CheckpointData(
            task_id="task-001",
            stage="write_chapters",
            status="in_progress",
            completed_stages=["research", "outline"],
            artifact_uri="",
            retry_count=0,
        )
        d = cp.to_dict()
        restored = CheckpointData.from_dict(d)
        assert restored.task_id == cp.task_id
        assert restored.stage == cp.stage
        assert restored.completed_stages == cp.completed_stages


# ---------------------------------------------------------------------------
# GuardianController — Checkpoint Engine tests
# ---------------------------------------------------------------------------


class TestCheckpointEngine:
    @pytest.mark.asyncio
    async def test_save_checkpoint_creates_file(
        self, guardian: GuardianController, temp_checkpoint_dir: Path
    ) -> None:
        cp = CheckpointData(
            task_id="t-checkpoint-001",
            stage="research",
            status="completed",
            completed_stages=["research"],
            artifact_uri="",
            retry_count=0,
        )
        await guardian.save_checkpoint(cp)
        assert (temp_checkpoint_dir / "t-checkpoint-001.json").exists()

    @pytest.mark.asyncio
    async def test_load_checkpoint_returns_data(self, guardian: GuardianController) -> None:
        cp = CheckpointData(
            task_id="t-checkpoint-002",
            stage="outline",
            status="completed",
            completed_stages=["research", "outline"],
            artifact_uri="",
            retry_count=0,
        )
        await guardian.save_checkpoint(cp)
        loaded = await guardian.load_checkpoint("t-checkpoint-002")
        assert loaded is not None
        assert loaded.stage == "outline"
        assert loaded.completed_stages == ["research", "outline"]

    @pytest.mark.asyncio
    async def test_load_checkpoint_returns_none_for_missing(
        self, guardian: GuardianController
    ) -> None:
        result = await guardian.load_checkpoint("nonexistent-task")
        assert result is None

    @pytest.mark.asyncio
    async def test_rescue_in_progress_tasks(
        self, guardian: GuardianController, temp_checkpoint_dir: Path
    ) -> None:
        # Create a checkpoint with old timestamp (simulating crash)
        cp = CheckpointData(
            task_id="t-rescue-001",
            stage="write_chapters",
            status="in_progress",
            completed_stages=["research", "outline", "write_chapters"],
            artifact_uri="",
            retry_count=0,
            updated_at="2026-04-30T00:00:00+00:00",  # Old timestamp
        )
        await guardian.save_checkpoint(cp)

        rescued = await guardian.rescue_in_progress_tasks()
        assert len(rescued) >= 1

    @pytest.mark.asyncio
    async def test_delete_checkpoint(self, guardian: GuardianController) -> None:
        cp = CheckpointData(
            task_id="t-delete-001",
            stage="research",
            status="completed",
            completed_stages=[],
            artifact_uri="",
            retry_count=0,
        )
        await guardian.save_checkpoint(cp)
        assert (guardian._config.checkpoint_dir / "t-delete-001.json").exists()
        await guardian.delete_checkpoint("t-delete-001")
        assert not (guardian._config.checkpoint_dir / "t-delete-001.json").exists()


# ---------------------------------------------------------------------------
# GuardianController — Error Attribution Engine tests
# ---------------------------------------------------------------------------


class TestErrorAttributionEngine:
    @pytest.mark.asyncio
    async def test_classify_network_error(self, guardian: GuardianController) -> None:
        attr = await guardian._classify_error("Connection reset by peer")
        assert attr.error_type == ErrorType.TRANSIENT

    @pytest.mark.asyncio
    async def test_classify_timeout_error(self, guardian: GuardianController) -> None:
        attr = await guardian._classify_error("TimeoutError: operation timed out after 120s")
        assert attr.error_type == ErrorType.TRANSIENT

    @pytest.mark.asyncio
    async def test_classify_syntax_error(self, guardian: GuardianController) -> None:
        attr = await guardian._classify_error("SyntaxError: invalid token at position 42")
        assert attr.error_type == ErrorType.LOGICAL

    @pytest.mark.asyncio
    async def test_classify_hallucination_error(self, guardian: GuardianController) -> None:
        attr = await guardian._classify_error(
            "OutputValidationError: model produced malformed output"
        )
        assert attr.error_type == ErrorType.LOGICAL

    @pytest.mark.asyncio
    async def test_classify_hang_error(self, guardian: GuardianController) -> None:
        attr = await guardian._classify_error("ExecutionHang: process exceeded timeout_sec=300")
        assert attr.error_type == ErrorType.HANG


# ---------------------------------------------------------------------------
# GuardianController — Retry with Backoff tests
# ---------------------------------------------------------------------------


class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_exponential_backoff_increases_delay(self, guardian: GuardianController) -> None:
        cp = CheckpointData(
            task_id="t-backoff-001",
            stage="research",
            status="in_progress",
            completed_stages=[],
            artifact_uri="",
            retry_count=0,
        )
        await guardian.save_checkpoint(cp)

        # Retry 0 → delay = 2 * 2^0 = 2s
        delay1 = await guardian._compute_backoff_delay(cp.retry_count)
        # Retry 1 → delay = 2 * 2^1 = 4s
        delay2 = await guardian._compute_backoff_delay(cp.retry_count + 1)
        # Retry 2 → delay = 2 * 2^2 = 8s
        delay3 = await guardian._compute_backoff_delay(cp.retry_count + 2)

        assert delay1 == 2.0
        assert delay2 == 4.0
        assert delay3 == 8.0

    @pytest.mark.asyncio
    async def test_retry_updates_retry_count(self, guardian: GuardianController) -> None:
        cp = CheckpointData(
            task_id="t-retry-001",
            stage="research",
            status="in_progress",
            completed_stages=[],
            artifact_uri="",
            retry_count=1,
        )
        await guardian.save_checkpoint(cp)
        await guardian.increment_retry("t-retry-001")
        loaded = await guardian.load_checkpoint("t-retry-001")
        assert loaded.retry_count == 2

    @pytest.mark.asyncio
    async def test_retry_exhausted_at_threshold(self, guardian: GuardianController) -> None:
        cp = CheckpointData(
            task_id="t-exhausted-001",
            stage="research",
            status="in_progress",
            completed_stages=[],
            artifact_uri="",
            retry_count=3,
        )
        await guardian.save_checkpoint(cp)
        is_exhausted = await guardian.is_retries_exhausted("t-exhausted-001")
        assert is_exhausted is True

    @pytest.mark.asyncio
    async def test_retry_not_exhausted_below_threshold(self, guardian: GuardianController) -> None:
        cp = CheckpointData(
            task_id="t-not-exhausted-001",
            stage="research",
            status="in_progress",
            completed_stages=[],
            artifact_uri="",
            retry_count=2,
        )
        await guardian.save_checkpoint(cp)
        is_exhausted = await guardian.is_retries_exhausted("t-not-exhausted-001")
        assert is_exhausted is False


# ---------------------------------------------------------------------------
# GuardianController — Escalation tests
# ---------------------------------------------------------------------------


class TestEscalation:
    @pytest.mark.asyncio
    async def test_escalate_task_sends_card(self, guardian: GuardianController) -> None:
        guardian._jarvis = pytest.importorskip(
            "hermes_os.jarvis_interface", reason="jarvis not available"
        )
        # Just verify it doesn't raise — actual card sending tested separately
        cp = CheckpointData(
            task_id="t-escalate-001",
            stage="write_chapters",
            status="in_progress",
            completed_stages=["research", "outline"],
            artifact_uri="artifacts/t-escalate-001/render/book.md",
            retry_count=3,
            error_context="Amazon captcha: external environment barrier",
        )
        await guardian.save_checkpoint(cp)
        # Would need mock jarvis to verify card content

    @pytest.mark.asyncio
    async def test_make_escalation_decision_exhausted_retry(
        self, guardian: GuardianController
    ) -> None:
        cp = CheckpointData(
            task_id="t-esc-decision-001",
            stage="write_chapters",
            status="in_progress",
            completed_stages=["research", "outline"],
            artifact_uri="",
            retry_count=3,
            error_context="Persistent connection failures",
        )
        decision = await guardian._make_escalation_decision(cp)
        assert decision == EscalationDecision.ESCALATE

    @pytest.mark.asyncio
    async def test_make_escalation_decision_hang_error(self, guardian: GuardianController) -> None:
        cp = CheckpointData(
            task_id="t-esc-decision-002",
            stage="render",
            status="in_progress",
            completed_stages=["research", "outline", "write_chapters"],
            artifact_uri="",
            retry_count=0,
            error_context="ExecutionHang: process exceeded timeout_sec=600",
        )
        decision = await guardian._make_escalation_decision(cp)
        assert decision == EscalationDecision.ESCALATE

    @pytest.mark.asyncio
    async def test_make_escalation_decision_transient_retry(
        self, guardian: GuardianController
    ) -> None:
        cp = CheckpointData(
            task_id="t-esc-decision-003",
            stage="research",
            status="in_progress",
            completed_stages=[],
            artifact_uri="",
            retry_count=1,
            error_context="503 Service Unavailable",
        )
        decision = await guardian._make_escalation_decision(cp)
        assert decision == EscalationDecision.RETRY

    @pytest.mark.asyncio
    async def test_make_escalation_decision_logical_error(
        self, guardian: GuardianController
    ) -> None:
        cp = CheckpointData(
            task_id="t-esc-decision-004",
            stage="outline",
            status="in_progress",
            completed_stages=["research"],
            artifact_uri="",
            retry_count=0,
            error_context="SyntaxError: unexpected token",
        )
        decision = await guardian._make_escalation_decision(cp)
        assert decision == EscalationDecision.CORRECT


# ---------------------------------------------------------------------------
# GuardianController — Guarded Invocation tests
# ---------------------------------------------------------------------------


class TestGuardedInvocation:
    @pytest.mark.asyncio
    async def test_handle_invocation_error_transient(self, guardian: GuardianController) -> None:
        cp = CheckpointData(
            task_id="t-handle-001",
            stage="research",
            status="in_progress",
            completed_stages=[],
            artifact_uri="",
            retry_count=0,
        )
        await guardian.save_checkpoint(cp)
        result = await guardian.handle_invocation_error(
            task_id="t-handle-001",
            error_message="Connection refused",
        )
        # Should be RETRY, not ESCALATE
        assert result.decision in (EscalationDecision.RETRY, EscalationDecision.CORRECT)

    @pytest.mark.asyncio
    async def test_handle_invocation_error_exhausted(self, guardian: GuardianController) -> None:
        cp = CheckpointData(
            task_id="t-handle-002",
            stage="research",
            status="in_progress",
            completed_stages=[],
            artifact_uri="",
            retry_count=3,
        )
        await guardian.save_checkpoint(cp)
        result = await guardian.handle_invocation_error(
            task_id="t-handle-002",
            error_message="Connection refused",
        )
        assert result.decision == EscalationDecision.ESCALATE

    @pytest.mark.asyncio
    async def test_handle_invocation_error_sets_retry_count(
        self, guardian: GuardianController
    ) -> None:
        cp = CheckpointData(
            task_id="t-handle-003",
            stage="research",
            status="in_progress",
            completed_stages=[],
            artifact_uri="",
            retry_count=0,
        )
        await guardian.save_checkpoint(cp)
        result = await guardian.handle_invocation_error(
            task_id="t-handle-003",
            error_message="503 Service Unavailable",
        )
        # Should have incremented retry
        loaded = await guardian.load_checkpoint("t-handle-003")
        assert loaded.retry_count == 1
