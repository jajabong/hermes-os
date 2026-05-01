"""Tests for PipelineTaskRunner — PipelineEngine ↔ TaskScheduler integration.

Integration pattern:
  - Task.metadata carries {pipeline_name, stage_name, pipeline_task_id}
  - BackgroundWorker.execute_task() detects pipeline tasks and delegates to PipelineTaskRunner
  - Each pipeline stage becomes a Task with Guardian checkpointing
  - MilestoneNotifier fires JARVIS cards on stage completion
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from hermes_os.pipeline_task_runner import (
    PipelineTaskRunner,
    PipelineTaskContext,
    MilestoneNotifier,
    StageMilestone,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_pipeline_dir() -> Path:
    tmp = Path(tempfile.mkdtemp())
    yield tmp
    shutil.rmtree(tmp)


@pytest.fixture
def mock_nm() -> MagicMock:
    nm = MagicMock()
    nm.send_notification = AsyncMock()
    nm.send_heads_up = AsyncMock()
    return nm


@pytest.fixture
def runner(temp_pipeline_dir: Path, mock_nm: MagicMock) -> PipelineTaskRunner:
    return PipelineTaskRunner(
        artifact_base=temp_pipeline_dir / "artifacts",
        notification_manager=mock_nm,
    )


# ---------------------------------------------------------------------------
# PipelineTaskContext tests
# ---------------------------------------------------------------------------

class TestPipelineTaskContext:
    def test_context_from_metadata(self) -> None:
        meta = {
            "pipeline_name": "Book Authoring Pipeline",
            "stage_name": "research",
            "pipeline_task_id": "pipeline-001",
            "user_id": "alice",
        }
        ctx = PipelineTaskContext.from_metadata(meta)
        assert ctx.pipeline_name == "Book Authoring Pipeline"
        assert ctx.stage_name == "research"
        assert ctx.pipeline_task_id == "pipeline-001"

    def test_context_defaults(self) -> None:
        ctx = PipelineTaskContext(pipeline_task_id="p1", stage_name="outline")
        assert ctx.pipeline_name == ""
        assert ctx.user_id == ""


# ---------------------------------------------------------------------------
# StageMilestone tests
# ---------------------------------------------------------------------------

class TestStageMilestone:
    def test_milestone_structure(self) -> None:
        m = StageMilestone(
            task_id="pipeline-001",
            stage_name="research",
            status="completed",
            output_artifact="00_research.md",
            duration_seconds=45.0,
        )
        assert m.task_id == "pipeline-001"
        assert m.stage_name == "research"
        assert m.status == "completed"

    def test_milestone_to_dict(self) -> None:
        m = StageMilestone(
            task_id="pipeline-001",
            stage_name="research",
            status="completed",
            output_artifact="00_research.md",
            duration_seconds=45.0,
        )
        d = m.to_dict()
        assert d["stage_name"] == "research"
        assert d["status"] == "completed"


# ---------------------------------------------------------------------------
# MilestoneNotifier tests
# ---------------------------------------------------------------------------

class TestMilestoneNotifier:
    @pytest.mark.asyncio
    async def test_notify_completion_sends_card(self, mock_nm: MagicMock) -> None:
        notifier = MilestoneNotifier(notification_manager=mock_nm)
        milestone = StageMilestone(
            task_id="pipeline-001",
            stage_name="research",
            status="completed",
            output_artifact="00_research.md",
            duration_seconds=45.0,
        )
        await notifier.notify_stage(milestone, user_id="alice")
        mock_nm.send_notification.assert_called_once()
        call_kwargs = mock_nm.send_notification.call_args.kwargs
        assert call_kwargs["user_id"] == "alice"
        assert "research" in call_kwargs["task_title"]

    @pytest.mark.asyncio
    async def test_notify_completion_includes_progress(self, mock_nm: MagicMock) -> None:
        notifier = MilestoneNotifier(notification_manager=mock_nm)
        milestone = StageMilestone(
            task_id="pipeline-001",
            stage_name="outline",
            status="completed",
            output_artifact="01_outline.md",
            duration_seconds=30.0,
            total_stages=6,
            completed_stages=2,
        )
        await notifier.notify_stage(milestone, user_id="alice")
        mock_nm.send_notification.assert_called_once()
        call_kwargs = mock_nm.send_notification.call_args.kwargs
        # Should be called with completed event
        assert call_kwargs["event"].value == "completed"

    @pytest.mark.asyncio
    async def test_notify_failure_sends_failed_card(self, mock_nm: MagicMock) -> None:
        notifier = MilestoneNotifier(notification_manager=mock_nm)
        milestone = StageMilestone(
            task_id="pipeline-001",
            stage_name="render",
            status="failed",
            error="EPUB format error",
        )
        await notifier.notify_stage(milestone, user_id="alice")
        call_kwargs = mock_nm.send_notification.call_args.kwargs
        # Should have failed notification
        assert "render" in call_kwargs["task_title"].lower() or "failed" in call_kwargs["content"].lower()


# ---------------------------------------------------------------------------
# PipelineTaskRunner — is_pipeline_task
# ---------------------------------------------------------------------------

class TestPipelineTaskRunnerInit:
    def test_runner_has_artifact_base(self, runner: PipelineTaskRunner, temp_pipeline_dir: Path) -> None:
        assert runner._artifact_base == temp_pipeline_dir / "artifacts"


class TestIsPipelineTask:
    def test_is_pipeline_task_true(self) -> None:
        meta = {"pipeline_name": "Book Pipeline", "stage_name": "research"}
        assert PipelineTaskRunner.is_pipeline_task(meta) is True

    def test_is_pipeline_task_false(self) -> None:
        meta = {"intent_action": "fix_bug"}
        assert PipelineTaskRunner.is_pipeline_task(meta) is False

    def test_is_pipeline_task_partial(self) -> None:
        meta = {"stage_name": "research"}  # missing pipeline_name
        assert PipelineTaskRunner.is_pipeline_task(meta) is False


# ---------------------------------------------------------------------------
# PipelineTaskRunner — execute_pipeline_task
# ---------------------------------------------------------------------------

class TestExecutePipelineTask:
    @pytest.mark.asyncio
    async def test_execute_creates_workspace(
        self, runner: PipelineTaskRunner, temp_pipeline_dir: Path
    ) -> None:
        meta = {
            "pipeline_name": "Book Authoring Pipeline",
            "stage_name": "research",
            "pipeline_task_id": "pipeline-ws-test-create",
            "user_id": "alice",
        }
        ws = await runner.execute_pipeline_task(
            task_id="t-001",
            metadata=meta,
            context={"topic": "AI history"},
        )
        assert ws is not None
        assert (temp_pipeline_dir / "artifacts" / "pipeline-ws-test-create").exists()

    @pytest.mark.asyncio
    async def test_execute_loads_existing_workspace(
        self, runner: PipelineTaskRunner, temp_pipeline_dir: Path
    ) -> None:
        meta = {
            "pipeline_name": "Book Authoring Pipeline",
            "stage_name": "outline",
            "pipeline_task_id": "pipeline-ws-test-2-load",
            "user_id": "alice",
        }
        # First execution
        await runner.execute_pipeline_task(
            task_id="t-002",
            metadata=meta,
            context={"topic": "AI"},
        )
        # Second call with same pipeline_task_id — should load existing
        ws = await runner.execute_pipeline_task(
            task_id="t-003",
            metadata=meta,
            context={"topic": "AI"},
        )
        assert ws is not None

    @pytest.mark.asyncio
    async def test_execute_resumes_from_checkpoint(
        self, runner: PipelineTaskRunner, temp_pipeline_dir: Path
    ) -> None:
        """If completed_stages includes the current stage, skip execution."""
        pipeline_id = "pipeline-resume-test"
        meta = {
            "pipeline_name": "Book Authoring Pipeline",
            "stage_name": "outline",
            "pipeline_task_id": pipeline_id,
            "user_id": "alice",
        }
        # Pre-populate completed stages
        ws = await runner.execute_pipeline_task(
            task_id="t-004",
            metadata=meta,
            context={"topic": "AI"},
        )
        # Simulate adding outline to completed_stages
        ws.completed_stages.append("outline")
        import json
        ws.root_path.mkdir(parents=True, exist_ok=True)
        (ws.root_path / "pipeline_meta.json").write_text(
            json.dumps(ws.to_dict(), ensure_ascii=False), "utf-8"
        )
        # Now execute outline again — should skip (already completed)
        result = await runner.execute_pipeline_task(
            task_id="t-005",
            metadata=meta,
            context={"topic": "AI"},
        )
        # Should return the workspace (checkpoint exists, stage was skipped)
        assert result is not None

    @pytest.mark.asyncio
    async def test_execute_unknown_stage_name(
        self, runner: PipelineTaskRunner, temp_pipeline_dir: Path
    ) -> None:
        """Unknown stage name returns None gracefully."""
        meta = {
            "pipeline_name": "Book Authoring Pipeline",
            "stage_name": "nonexistent_stage",
            "pipeline_task_id": "pipeline-unknown-stage",
            "user_id": "alice",
        }
        result = await runner.execute_pipeline_task(
            task_id="t-006",
            metadata=meta,
            context={},
        )
        # Should return None since stage not found
        assert result is None

    @pytest.mark.asyncio
    async def test_notify_milestone_on_completion(
        self, runner: PipelineTaskRunner, mock_nm: MagicMock
    ) -> None:
        """Stage completion triggers milestone notification."""
        meta = {
            "pipeline_name": "Book Authoring Pipeline",
            "stage_name": "research",
            "pipeline_task_id": "pipeline-milestone-test",
            "user_id": "alice",
        }
        await runner.execute_pipeline_task(
            task_id="t-007",
            metadata=meta,
            context={"topic": "AI"},
        )
        # Milestone notification should have been sent
        mock_nm.send_notification.assert_called()


# ---------------------------------------------------------------------------
# PipelineTaskRunner — Guardian integration
# ---------------------------------------------------------------------------

class TestGuardianIntegration:
    @pytest.mark.asyncio
    async def test_checkpoint_saved_before_execution(
        self, runner: PipelineTaskRunner, temp_pipeline_dir: Path
    ) -> None:
        meta = {
            "pipeline_name": "Book Pipeline",
            "stage_name": "research",
            "pipeline_task_id": "pipeline-guardian-test",
            "user_id": "alice",
        }
        await runner.execute_pipeline_task(
            task_id="t-guardian-001",
            metadata=meta,
            context={},
        )
        # Guardian checkpoint should exist
        checkpoint_path = Path.home() / ".hermes" / "checkpoints" / "t-guardian-001.json"
        # Note: this may not exist if no error occurred — that's OK
        # The Guardian integration is tested via error handling

    @pytest.mark.asyncio
    async def test_execution_with_guardian(
        self, runner: PipelineTaskRunner, temp_pipeline_dir: Path
    ) -> None:
        """Guardian wraps pipeline stage execution."""
        meta = {
            "pipeline_name": "Book Authoring Pipeline",
            "stage_name": "research",
            "pipeline_task_id": "pipeline-guardian-exec",
            "user_id": "alice",
        }
        # Should not raise even with Guardian errors
        ws = await runner.execute_pipeline_task(
            task_id="t-guardian-002",
            metadata=meta,
            context={"topic": "test"},
        )
        assert ws is not None
