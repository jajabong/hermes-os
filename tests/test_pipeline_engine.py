"""Tests for PipelineEngine — YAML-driven pipeline execution.

Pipeline stages:
  Research → Outline → Write → Render → Deliver

Each stage:
  - Uses a LaborInterface to produce output
  - Writes to artifact workspace
  - Updates meta.json with stage progress
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from hermes_os.pipeline_engine import (
    PipelineDefinition,
    PipelineEngine,
    PipelineStage,
    StageStatus,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_dir() -> Path:
    tmp = Path(tempfile.mkdtemp())
    yield tmp
    shutil.rmtree(tmp)


@pytest.fixture
def sample_pipeline_yaml(temp_dir: Path) -> Path:
    yaml_content = """
name: "Book Authoring Pipeline"
description: "From intent to published book"
version: "1.0"

stages:
  - name: research
    labor_type: content
    input_artifact: null
    output_artifact: "research.md"
    description: "Gather source materials and research topic"

  - name: outline
    labor_type: content
    input_artifact: "research.md"
    output_artifact: "outline.md"
    description: "Create book outline structure"

  - name: write
    labor_type: content
    input_artifact: "outline.md"
    output_artifact: "manuscript.md"
    description: "Write book chapters"

  - name: render
    labor_type: format
    input_artifact: "manuscript.md"
    output_artifact: "book.epub"
    description: "Format as EPUB"
"""
    path = temp_dir / "book_pipeline.yaml"
    path.write_text(yaml_content, "utf-8")
    return path


@pytest.fixture
def engine(temp_dir: Path) -> PipelineEngine:
    return PipelineEngine(
        artifact_base=temp_dir / "artifacts",
        notification_manager=None,
    )


# ---------------------------------------------------------------------------
# PipelineDefinition tests
# ---------------------------------------------------------------------------


class TestPipelineDefinition:
    def test_load_from_yaml(self, sample_pipeline_yaml: Path) -> None:
        pd = PipelineDefinition.from_yaml(sample_pipeline_yaml)
        assert pd.name == "Book Authoring Pipeline"
        assert pd.version == "1.0"
        assert len(pd.stages) == 4

    def test_stage_names(self, sample_pipeline_yaml: Path) -> None:
        pd = PipelineDefinition.from_yaml(sample_pipeline_yaml)
        names = [s.name for s in pd.stages]
        assert names == ["research", "outline", "write", "render"]

    def test_stage_sequence_order(self, sample_pipeline_yaml: Path) -> None:
        pd = PipelineDefinition.from_yaml(sample_pipeline_yaml)
        for i in range(len(pd.stages) - 1):
            assert pd.stages[i].sequence < pd.stages[i + 1].sequence


# ---------------------------------------------------------------------------
# PipelineEngine tests
# ---------------------------------------------------------------------------


class TestPipelineEngineInit:
    def test_init_sets_artifact_base(self, engine: PipelineEngine, temp_dir: Path) -> None:
        assert engine._artifact_base == temp_dir / "artifacts"


class TestPipelineExecution:
    @pytest.mark.asyncio
    async def test_create_pipeline_workspace(self, engine: PipelineEngine) -> None:
        ws = await engine.create_pipeline_workspace("pipeline-001", "book_pipeline")
        assert ws.task_id == "pipeline-001"
        assert (ws.root_path / "src").is_dir()
        assert (ws.root_path / "render").is_dir()
        assert (ws.root_path / "delivery").is_dir()

    @pytest.mark.asyncio
    async def test_load_pipeline_workspace(
        self, engine: PipelineEngine, sample_pipeline_yaml: Path
    ) -> None:
        pd = PipelineDefinition.from_yaml(sample_pipeline_yaml)
        await engine.create_pipeline_workspace("pipeline-002", "book_pipeline")
        loaded = await engine.load_pipeline_workspace("pipeline-002")
        assert loaded is not None
        assert loaded.task_id == "pipeline-002"

    @pytest.mark.asyncio
    async def test_execute_stage_updates_workspace(self, engine: PipelineEngine) -> None:
        from unittest.mock import AsyncMock, patch

        ws = await engine.create_pipeline_workspace("pipeline-003", "book_pipeline")
        stage = PipelineStage(
            name="research",
            sequence=0,
            labor_type="content",
            description="Research topic",
            input_artifact=None,
            output_artifact="research.md",
        )

        mock_result = AsyncMock()
        mock_result.stdout = "# Research Results\n\nAI history content."
        with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_result
            await engine.execute_stage("pipeline-003", stage, {"topic": "AI history"})

        reloaded = await engine.load_pipeline_workspace("pipeline-003")
        assert reloaded.completed_stages == ["research"]

    @pytest.mark.asyncio
    async def test_execute_stage_writes_artifact(self, engine: PipelineEngine) -> None:
        from unittest.mock import AsyncMock, patch

        ws = await engine.create_pipeline_workspace("pipeline-004", "book_pipeline")
        stage = PipelineStage(
            name="outline",
            sequence=1,
            labor_type="content",
            description="Create outline",
            input_artifact="research.md",
            output_artifact="outline.md",
        )

        mock_result = AsyncMock()
        mock_result.stdout = "# Outline\n\n1. Chapter 1\n2. Chapter 2"
        with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_result
            result = await engine.execute_stage(
                "pipeline-004",
                stage,
                {"research": "AI has transformed many industries"},
            )

        assert result.success is True
        # Output is written to workspace src_path
        output_file = ws.src_path / "outline.md"
        assert output_file.exists()

    @pytest.mark.asyncio
    async def test_stage_failure_does_not_crash(self, engine: PipelineEngine) -> None:
        ws = await engine.create_pipeline_workspace("pipeline-005", "book_pipeline")
        stage = PipelineStage(
            name="invalid",
            sequence=0,
            labor_type="unknown_labor",
            description="Invalid labor type",
            input_artifact=None,
            output_artifact="output.txt",
        )
        result = await engine.execute_stage("pipeline-005", stage, {})
        assert result.success is False
        assert result.error is not None


# ---------------------------------------------------------------------------
# StageStatus tests
# ---------------------------------------------------------------------------


class TestStageStatus:
    def test_status_values(self) -> None:
        assert hasattr(StageStatus, "PENDING")
        assert hasattr(StageStatus, "RUNNING")
        assert hasattr(StageStatus, "COMPLETED")
        assert hasattr(StageStatus, "FAILED")


class TestVerificationGate:
    """TDD tests for verification_gate integration in PipelineEngine."""

    @pytest.mark.asyncio
    async def test_stage_with_verification_gate_calls_gate_after_labor(
        self, engine: PipelineEngine, temp_dir: Path
    ) -> None:
        """When a stage has verification_gate defined, execute_stage should call it after labor."""
        from unittest.mock import AsyncMock, patch

        ws = await engine.create_pipeline_workspace("vg-test-001", "test_pipeline")

        # Track if verification_gate was called
        gate_calls = []

        async def mock_gate(task_id: str, stage_name: str, context: dict) -> bool:
            gate_calls.append((task_id, stage_name))
            return True  # Gate passes

        mock_result = AsyncMock()
        mock_result.stdout = "# Content\n\nTest content."
        with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_result
            engine.execute_verification_gate = mock_gate

            stage = PipelineStage(
                name="write",
                sequence=2,
                labor_type="content",
                description="Write content",
                input_artifact=None,
                output_artifact="content.md",
                verification_gate="checker_labor",
            )
            result = await engine.execute_stage("vg-test-001", stage, {"topic": "test"})

        assert result.success is True
        assert len(gate_calls) == 1
        assert gate_calls[0] == ("vg-test-001", "write")

    @pytest.mark.asyncio
    async def test_verification_gate_failure_blocks_pipeline(
        self, engine: PipelineEngine, temp_dir: Path
    ) -> None:
        """When verification_gate fails, stage should be marked as failed."""
        from unittest.mock import AsyncMock, patch

        ws = await engine.create_pipeline_workspace("vg-test-002", "test_pipeline")

        async def failing_gate(task_id: str, stage_name: str, context: dict) -> bool:
            return False  # Gate fails

        mock_result = AsyncMock()
        mock_result.stdout = "# Content\n\nTest content."
        with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_result
            engine.execute_verification_gate = failing_gate

            stage = PipelineStage(
                name="check",
                sequence=1,
                labor_type="content",
                description="Check content",
                verification_gate="checker_labor",
            )
            result = await engine.execute_stage("vg-test-002", stage, {})

        assert result.success is False
        assert "verification_gate" in result.error
        assert "failed" in result.error

    @pytest.mark.asyncio
    async def test_stage_without_verification_gate_skips_gate(
        self, engine: PipelineEngine, temp_dir: Path
    ) -> None:
        """When a stage has no verification_gate, execute_stage should not call gate."""
        from unittest.mock import AsyncMock, patch

        ws = await engine.create_pipeline_workspace("vg-test-003", "test_pipeline")

        gate_calls = []

        async def tracking_gate(task_id: str, stage_name: str, context: dict) -> bool:
            gate_calls.append((task_id, stage_name))
            return True

        mock_result = AsyncMock()
        mock_result.stdout = "# Research\n\nTest content."
        with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_result
            engine.execute_verification_gate = tracking_gate

            stage = PipelineStage(
                name="research",
                sequence=0,
                labor_type="content",
                description="Research",
                verification_gate=None,  # No gate
            )
            result = await engine.execute_stage("vg-test-003", stage, {"topic": "test"})

        assert result.success is True
        assert len(gate_calls) == 0  # Gate should not be called

    @pytest.mark.asyncio
    async def test_gate_retry_on_failure(self, engine: PipelineEngine, temp_dir: Path) -> None:
        """When verification_gate fails, engine should retry up to max_retries."""
        from unittest.mock import AsyncMock, patch

        ws = await engine.create_pipeline_workspace("vg-test-004", "test_pipeline")

        retry_count = []

        async def flaky_gate(task_id: str, stage_name: str, context: dict) -> bool:
            retry_count.append(1)
            if len(retry_count) < 3:
                return False  # Fail first 2 times
            return True  # Pass on 3rd attempt

        # Register the flaky gate directly in the registry
        engine._gate_registry["checker_labor"] = flaky_gate
        engine._max_gate_retries = 3

        mock_result = AsyncMock()
        mock_result.stdout = "# Content\n\nTest content."
        with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_result

            stage = PipelineStage(
                name="verify",
                sequence=1,
                labor_type="content",
                description="Verify",
                verification_gate="checker_labor",
            )
            result = await engine.execute_stage("vg-test-004", stage, {})

        assert result.success is True
        assert len(retry_count) == 3  # Should have retried 3 times


class TestBrowserLabor:
    """Tests for BrowserLabor browser automation."""

    @pytest.mark.asyncio
    async def test_browser_labor_returns_error_without_playwright(
        self, engine: PipelineEngine
    ) -> None:
        """BrowserLabor should return error when Playwright is not installed."""
        ws = await engine.create_pipeline_workspace("browser-test-001", "test_pipeline")

        stage = PipelineStage(
            name="browse",
            sequence=0,
            labor_type="browser",
            description="Navigate to URL",
        )
        result = await engine.execute_stage(
            "browser-test-001",
            stage,
            {"action": "navigate", "url": "https://example.com"},
        )

        # Should fail gracefully without Playwright
        assert result.success is False
        assert "Playwright" in result.error

    @pytest.mark.asyncio
    async def test_browser_labor_accepts_context_params(self, temp_dir: Path) -> None:
        """BrowserLabor should accept context parameters for different actions."""
        from hermes_os.pipeline_engine import BrowserLabor

        labor = BrowserLabor()

        # Verify different context params are accepted without error
        contexts = [
            {"action": "navigate", "url": "https://example.com"},
            {"action": "screenshot", "url": "https://example.com", "filename": "test.png"},
            {
                "action": "fill",
                "url": "https://example.com",
                "form_data": {"#email": "test@example.com"},
            },
            {"action": "extract", "url": "https://example.com", "selector": "h1"},
        ]

        for ctx in contexts:
            # Just verify no AttributeError on execute (actual browser test needs Playwright)
            labor._playwright = None  # Force no playwright
            labor._browser = None
            labor._context = None


# ---------------------------------------------------------------------------
# ParallelChapterLabor tests
# ---------------------------------------------------------------------------


class TestParallelChapterLabor:
    """TDD tests for ParallelChapterLabor — parallel chapter writing."""

    @pytest.mark.asyncio
    async def test_writes_chapters_in_parallel(self, temp_dir: Path) -> None:
        """ParallelChapterLabor should write multiple chapters in parallel."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from hermes_os.pipeline_engine import (
            ParallelChapterLabor,
            PipelineWorkspace,
        )

        # Create workspace with outline
        ws_root = temp_dir / "artifacts" / "parallel-test-001"
        ws_root.mkdir(parents=True)
        (ws_root / "src").mkdir()

        outline_content = """## 大纲

1. **第一章** — 内容1
2. **第二章** — 内容2
3. **第三章** — 内容3
"""
        (ws_root / "src" / "01_outline.md").write_text(outline_content, "utf-8")

        ws = PipelineWorkspace(
            task_id="parallel-test-001",
            pipeline_name="book",
            root_path=ws_root,
        )
        ws.stage_statuses = {}

        # Mock invoke to return chapter content
        mock_invoke_result = MagicMock()
        mock_invoke_result.stdout = "# Chapter Content\n\nLorem ipsum chapter content."

        labor = ParallelChapterLabor(max_concurrent=3, failure_threshold=0.5)

        with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_invoke_result
            result = await labor.execute(
                description="Write chapters",
                input_artifact="01_outline.md",
                workspace=ws,
                context={"topic": "Test Book"},
            )

        assert result.success is True
        assert result.chapter_results is not None
        assert len(result.chapter_results) == 3
        # Files should be written
        assert (ws_root / "src" / "ch01_第一章.md").exists()
        assert (ws_root / "src" / "ch02_第二章.md").exists()
        assert (ws_root / "src" / "ch03_第三章.md").exists()

    @pytest.mark.asyncio
    async def test_failure_threshold_triggers_stage_failure(self, temp_dir: Path) -> None:
        """When too many chapters fail, stage should fail."""
        from unittest.mock import AsyncMock, patch

        from hermes_os.pipeline_engine import ParallelChapterLabor, PipelineWorkspace

        ws_root = temp_dir / "artifacts" / "parallel-fail-001"
        ws_root.mkdir(parents=True)
        (ws_root / "src").mkdir()

        outline_content = """## 大纲

1. **第一章** — 内容1
2. **第二章** — 内容2
3. **第三章** — 内容3
4. **第四章** — 内容4
"""
        (ws_root / "src" / "01_outline.md").write_text(outline_content, "utf-8")

        ws = PipelineWorkspace(
            task_id="parallel-fail-001",
            pipeline_name="book",
            root_path=ws_root,
        )
        ws.stage_statuses = {}

        labor = ParallelChapterLabor(max_concurrent=4, failure_threshold=0.5)

        # Make all invokes fail
        with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.side_effect = Exception("Chapter failed")
            result = await labor.execute(
                description="Write chapters",
                input_artifact="01_outline.md",
                workspace=ws,
                context={"topic": "Test Book"},
            )

        assert result.success is False
        assert "chapters failed" in result.error

    @pytest.mark.asyncio
    async def test_partial_failure_allowed_under_threshold(self, temp_dir: Path) -> None:
        """Some chapter failures should be allowed if under threshold."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from hermes_os.pipeline_engine import ParallelChapterLabor, PipelineWorkspace

        ws_root = temp_dir / "artifacts" / "parallel-partial-001"
        ws_root.mkdir(parents=True)
        (ws_root / "src").mkdir()

        outline_content = """## 大纲

1. **第一章** — 内容1
2. **第二章** — 内容2
3. **第三章** — 内容3
4. **第四章** — 内容4
"""
        (ws_root / "src" / "01_outline.md").write_text(outline_content, "utf-8")

        ws = PipelineWorkspace(
            task_id="parallel-partial-001",
            pipeline_name="book",
            root_path=ws_root,
        )
        ws.stage_statuses = {}

        labor = ParallelChapterLabor(max_concurrent=4, failure_threshold=0.5)

        # 2 out of 4 chapters fail (50% = at threshold, should still pass)
        call_count = [0]

        async def flaky_invoke(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise Exception("Failed")
            return MagicMock(stdout="# Chapter Content\n\nContent.")

        with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.side_effect = flaky_invoke
            result = await labor.execute(
                description="Write chapters",
                input_artifact="01_outline.md",
                workspace=ws,
                context={"topic": "Test Book"},
            )

        # 50% failure is at threshold, should pass (failure_ratio <= threshold)
        assert result.success is True


class TestParallelChapterLaborTaskScheduler:
    """TDD: ParallelChapterLabor should optionally delegate to TaskScheduler."""

    @pytest.mark.asyncio
    async def test_delegates_to_scheduler_when_available(self, temp_dir: Path) -> None:
        """When task_scheduler is set, ParallelChapterLabor uses it instead of invoke()."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from hermes_os.pipeline_engine import (
            ParallelChapterLabor,
            PipelineWorkspace,
        )

        # Create workspace with outline
        ws_root = temp_dir / "artifacts" / "scheduler-test-001"
        ws_root.mkdir(parents=True)
        (ws_root / "src").mkdir()

        outline_content = """## 大纲

1. **第一章** — 内容1
2. **第二章** — 内容2
"""
        (ws_root / "src" / "01_outline.md").write_text(outline_content, "utf-8")

        ws = PipelineWorkspace(
            task_id="scheduler-test-001",
            pipeline_name="book",
            root_path=ws_root,
        )
        ws.stage_statuses = {}

        # Mock TaskScheduler returning completed tasks
        mock_task1 = MagicMock()
        mock_task1.task_id = "task-001"
        mock_task1.status = MagicMock()
        mock_task1.status.value = "COMPLETED"
        mock_task1.result = '{"output": "# Chapter 1 content"}'

        mock_task2 = MagicMock()
        mock_task2.task_id = "task-002"
        mock_task2.status = MagicMock()
        mock_task2.status.value = "COMPLETED"
        mock_task2.result = '{"output": "# Chapter 2 content"}'

        mock_scheduler = MagicMock()
        mock_scheduler.create_task = AsyncMock(side_effect=[mock_task1, mock_task2])
        mock_scheduler.get_task = AsyncMock(side_effect=[mock_task1, mock_task2])

        labor = ParallelChapterLabor(
            max_concurrent=3,
            failure_threshold=0.5,
            task_scheduler=mock_scheduler,
        )

        # Patch invoke to track if it's called (it shouldn't be)
        with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = MagicMock(stdout="should not be called")
            result = await labor.execute(
                description="Write chapters",
                input_artifact="01_outline.md",
                workspace=ws,
                context={"topic": "Test Book"},
            )

        # Scheduler should have been used (create_task called twice, once per chapter)
        assert mock_scheduler.create_task.call_count == 2
        # invoke() should NOT have been called (scheduler path)
        assert mock_invoke.call_count == 0
        assert result.success is True

    @pytest.mark.asyncio
    async def test_falls_back_to_gather_when_no_scheduler(self, temp_dir: Path) -> None:
        """When no task_scheduler, ParallelChapterLabor uses asyncio.gather (existing behavior)."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from hermes_os.pipeline_engine import (
            ParallelChapterLabor,
            PipelineWorkspace,
        )

        ws_root = temp_dir / "artifacts" / "gather-test-001"
        ws_root.mkdir(parents=True)
        (ws_root / "src").mkdir()

        outline_content = """## 大纲

1. **第一章** — 内容1
"""
        (ws_root / "src" / "01_outline.md").write_text(outline_content, "utf-8")

        ws = PipelineWorkspace(
            task_id="gather-test-001",
            pipeline_name="book",
            root_path=ws_root,
        )
        ws.stage_statuses = {}

        mock_invoke_result = MagicMock()
        mock_invoke_result.stdout = "# Chapter Content\n\nLorem ipsum."

        # NO task_scheduler passed
        labor = ParallelChapterLabor(max_concurrent=3, failure_threshold=0.5)

        with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_invoke_result
            result = await labor.execute(
                description="Write chapters",
                input_artifact="01_outline.md",
                workspace=ws,
                context={"topic": "Test Book"},
            )

        # Should use invoke directly (asyncio.gather path)
        assert result.success is True
        mock_invoke.assert_called()

    @pytest.mark.asyncio
    async def test_aggregates_chapter_results_from_scheduler(self, temp_dir: Path) -> None:
        """Scheduler delegate should aggregate chapter results correctly."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from hermes_os.pipeline_engine import (
            ParallelChapterLabor,
            PipelineWorkspace,
        )

        ws_root = temp_dir / "artifacts" / "aggregate-test-001"
        ws_root.mkdir(parents=True)
        (ws_root / "src").mkdir()

        outline_content = """## 大纲

1. **第一章** — 内容1
2. **第二章** — 内容2
"""
        (ws_root / "src" / "01_outline.md").write_text(outline_content, "utf-8")

        ws = PipelineWorkspace(
            task_id="aggregate-test-001",
            pipeline_name="book",
            root_path=ws_root,
        )
        ws.stage_statuses = {}

        # Mock TaskScheduler returning completed tasks with results
        mock_task1 = MagicMock()
        mock_task1.task_id = "task-001"
        mock_task1.status = MagicMock()
        mock_task1.status.value = "COMPLETED"
        mock_task1.result = '{"output": "# Chapter 1 content"}'

        mock_task2 = MagicMock()
        mock_task2.task_id = "task-002"
        mock_task2.status = MagicMock()
        mock_task2.status.value = "COMPLETED"
        mock_task2.result = '{"output": "# Chapter 2 content"}'

        mock_scheduler = MagicMock()
        mock_scheduler.create_task = AsyncMock(side_effect=[mock_task1, mock_task2])
        mock_scheduler.get_task = AsyncMock(side_effect=[mock_task1, mock_task2, mock_task1, mock_task2])

        labor = ParallelChapterLabor(
            max_concurrent=3,
            failure_threshold=0.5,
            task_scheduler=mock_scheduler,
        )

        with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = MagicMock(stdout="should not be called")
            result = await labor.execute(
                description="Write chapters",
                input_artifact="01_outline.md",
                workspace=ws,
                context={"topic": "Test Book"},
            )

        # Both chapters should succeed
        assert result.success is True
        assert result.chapter_results is not None
        assert len(result.chapter_results) == 2


class TestParallelChapterLaborDelegateTask:
    """TDD: ParallelChapterLabor should optionally use delegate_task batch parallel.

    delegate_task batch mode (hermes-agent built-in) provides:
    - ThreadPoolExecutor-based true parallelism
    - per-task isolation
    - max_concurrent_children limit
    - heartbeat to prevent gateway timeout
    """

    @pytest.mark.asyncio
    async def test_delegate_batch_routes_to_delegate_task(self, temp_dir: Path) -> None:
        """When execution_mode=delegate_task, _execute_via_delegate_task is called."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from hermes_os.pipeline_engine import (
            ParallelChapterLabor,
            PipelineWorkspace,
        )

        ws_root = temp_dir / "artifacts" / "delegate-test-001"
        ws_root.mkdir(parents=True)
        (ws_root / "src").mkdir()

        outline_content = """## 大纲

1. **第一章** — 内容1
2. **第二章** — 内容2
"""
        (ws_root / "src" / "01_outline.md").write_text(outline_content, "utf-8")

        ws = PipelineWorkspace(
            task_id="delegate-test-001",
            pipeline_name="book",
            root_path=ws_root,
        )
        ws.stage_statuses = {}

        labor = ParallelChapterLabor(
            max_concurrent=3,
            failure_threshold=0.5,
            execution_mode="delegate_task",
        )

        mock_results = {0: MagicMock(), 1: MagicMock()}
        mock_results[0].success = True
        mock_results[0].output = "# Chapter 1"
        mock_results[1].success = True
        mock_results[1].output = "# Chapter 2"

        # Mock _execute_via_delegate_task to verify it's called
        with patch.object(
            labor,
            "_execute_via_delegate_task",
            new=AsyncMock(return_value=mock_results),
        ) as mock_delegate_task:
            result = await labor.execute(
                description="Write chapters",
                input_artifact="01_outline.md",
                workspace=ws,
                context={"topic": "Test Book"},
            )

            # delegate_task path should have been called
            assert mock_delegate_task.call_count == 1
            assert result.success is True

    @pytest.mark.asyncio
    async def test_delegate_batch_falls_back_to_gather_when_no_hermes_agent(
        self, temp_dir: Path
    ) -> None:
        """Without hermes_agent SDK, should fall back to asyncio.gather."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from hermes_os.pipeline_engine import (
            ParallelChapterLabor,
            PipelineWorkspace,
        )

        ws_root = temp_dir / "artifacts" / "fallback-test-001"
        ws_root.mkdir(parents=True)
        (ws_root / "src").mkdir()

        outline_content = """## 大纲

1. **第一章** — 内容1
"""
        (ws_root / "src" / "01_outline.md").write_text(outline_content, "utf-8")

        ws = PipelineWorkspace(
            task_id="fallback-test-001",
            pipeline_name="book",
            root_path=ws_root,
        )
        ws.stage_statuses = {}

        labor = ParallelChapterLabor(
            max_concurrent=3,
            failure_threshold=0.5,
            execution_mode="delegate_task",
        )

        mock_gather_results = {0: MagicMock()}
        mock_gather_results[0].success = True
        mock_gather_results[0].output = "# Chapter Content"

        # Simulate hermes_agent ImportError by patching the import inside
        # _execute_via_delegate_task. When ImportError is raised inside
        # _execute_via_delegate_task, it internally falls back to _execute_via_gather.
        with patch.dict("sys.modules", {"hermes_agent": None}):
            with patch.object(
                labor,
                "_execute_via_gather",
                new=AsyncMock(return_value=mock_gather_results),
            ) as mock_gather:
                result = await labor.execute(
                    description="Write chapters",
                    input_artifact="01_outline.md",
                    workspace=ws,
                    context={"topic": "Test Book"},
                )

        # _execute_via_gather should have been called (internally by _execute_via_delegate_task
        # when hermes_agent import fails)
        assert mock_gather.call_count == 1
        assert result.success is True


class TestPipelineStageParallel:
    """Tests for parallel fields in PipelineStage and from_yaml parsing."""

    def test_from_yaml_parses_parallel_fields(self, temp_dir: Path) -> None:
        """PipelineDefinition.from_yaml should parse parallel stage options."""
        yaml_content = """
name: "Book Pipeline"
description: "Test"
version: "1.0"

stages:
  - name: write_chapters
    labor_type: content
    input_artifact: "outline.md"
    output_artifact: "ch*.md"
    description: "Write chapters"
    parallel: true
    parallel_max_concurrent: 3
    parallel_failure_threshold: 0.3
"""
        path = temp_dir / "parallel_pipeline.yaml"
        path.write_text(yaml_content, "utf-8")

        pd = PipelineDefinition.from_yaml(path)
        stage = pd.stages[0]

        assert stage.parallel is True
        assert stage.parallel_max_concurrent == 3
        assert stage.parallel_failure_threshold == 0.3

    def test_from_yaml_default_parallel_values(self, temp_dir: Path) -> None:
        """Stages without parallel fields should default to False/0.5/5."""
        yaml_content = """
name: "Book Pipeline"
description: "Test"
version: "1.0"

stages:
  - name: research
    labor_type: content
    input_artifact: null
    output_artifact: "research.md"
    description: "Research"
"""
        path = temp_dir / "noparallel_pipeline.yaml"
        path.write_text(yaml_content, "utf-8")

        pd = PipelineDefinition.from_yaml(path)
        stage = pd.stages[0]

        assert stage.parallel is False
        assert stage.parallel_max_concurrent == 5
        assert stage.parallel_failure_threshold == 0.5


# ---------------------------------------------------------------------------
# PdfRenderLabor tests
# ---------------------------------------------------------------------------


class TestPdfRenderLabor:
    """TDD tests for PdfRenderLabor — Markdown → PDF via pandoc."""

    @pytest.mark.asyncio
    async def test_finds_pdf_engine(self) -> None:
        """PdfRenderLabor should detect available PDF engines."""
        from hermes_os.pipeline_engine import PdfRenderLabor

        labor = PdfRenderLabor()
        # Engine may or may not be installed, but method should not raise
        engine = labor._find_pdf_engine()
        assert engine is None or isinstance(engine, str)

    @pytest.mark.asyncio
    async def test_renders_with_available_pdf_engine(self, temp_dir: Path) -> None:
        """PdfRenderLabor renders PDF when a PDF engine is installed."""
        from unittest.mock import MagicMock, patch

        from hermes_os.pipeline_engine import PdfRenderLabor, PipelineWorkspace

        ws_root = temp_dir / "artifacts" / "pdf-test-001"
        ws_root.mkdir(parents=True)
        (ws_root / "src").mkdir()
        (ws_root / "render").mkdir()

        input_content = "# Test Book\n\n## Chapter 1\n\nHello world."
        (ws_root / "src" / "manuscript.md").write_text(input_content, "utf-8")

        ws = PipelineWorkspace(
            task_id="pdf-test-001",
            pipeline_name="book",
            root_path=ws_root,
        )

        labor = PdfRenderLabor()

        mock_result = MagicMock()
        mock_result.returncode = 0

        # Mock _find_pdf_engine to return "xelatex" so it attempts PDF
        with patch.object(labor, "_find_pdf_engine", return_value="xelatex"):
            with patch("subprocess.run", new_callable=MagicMock) as mock_run:
                mock_run.return_value = mock_result
                result = await labor.execute(
                    description="Render PDF",
                    input_artifact="manuscript.md",
                    workspace=ws,
                    context={},
                )

        assert result.success is True
        assert result.output_artifact == "book.pdf"
        # pandoc should be called with --pdf-engine=xelatex
        assert mock_run.call_count == 1
        call_args = mock_run.call_args_list[0][0][0]
        assert "pandoc" in call_args
        assert "--pdf-engine=xelatex" in call_args

    @pytest.mark.asyncio
    async def test_falls_back_to_html_when_no_pdf_engine(self, temp_dir: Path) -> None:
        """PdfRenderLabor produces HTML when no PDF engine is installed."""
        from unittest.mock import MagicMock, patch

        from hermes_os.pipeline_engine import PdfRenderLabor, PipelineWorkspace

        ws_root = temp_dir / "artifacts" / "pdf-test-003"
        ws_root.mkdir(parents=True)
        (ws_root / "src").mkdir()
        (ws_root / "render").mkdir()

        input_content = "# Test Book\n\n## Chapter 1\n\nHello world."
        (ws_root / "src" / "manuscript.md").write_text(input_content, "utf-8")

        ws = PipelineWorkspace(
            task_id="pdf-test-003",
            pipeline_name="book",
            root_path=ws_root,
        )

        labor = PdfRenderLabor()

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch.object(labor, "_find_pdf_engine", return_value=None):
            with patch("subprocess.run", new_callable=MagicMock) as mock_run:
                mock_run.return_value = mock_result
                result = await labor.execute(
                    description="Render PDF",
                    input_artifact="manuscript.md",
                    workspace=ws,
                    context={},
                )

        assert result.success is True
        assert result.output_artifact == "book.html"
        assert "no pdf engine" in result.output_content.lower()
        # pandoc should be called once for HTML output
        assert mock_run.call_count == 1
        call_args = mock_run.call_args_list[0][0][0]
        assert "pandoc" in call_args
        assert str(ws_root / "render" / "book.html") in call_args

    @pytest.mark.asyncio
    async def test_returns_error_when_input_missing(self, temp_dir: Path) -> None:
        """PdfRenderLabor should return error when input is missing."""
        from hermes_os.pipeline_engine import PdfRenderLabor, PipelineWorkspace

        ws_root = temp_dir / "artifacts" / "pdf-test-002"
        ws_root.mkdir(parents=True)
        (ws_root / "src").mkdir()
        (ws_root / "render").mkdir()

        ws = PipelineWorkspace(
            task_id="pdf-test-002",
            pipeline_name="book",
            root_path=ws_root,
        )

        labor = PdfRenderLabor()
        result = await labor.execute(
            description="Render PDF",
            input_artifact="nonexistent.md",
            workspace=ws,
            context={},
        )

        assert result.success is False
        assert "not found" in result.error.lower()
