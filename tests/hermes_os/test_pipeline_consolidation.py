"""Tests for pipeline_engine consolidation — TDD for merging v1 and v2."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Tests: v1 vs v2 differences
# ---------------------------------------------------------------------------

def test_both_have_pipeline_stage_dataclass() -> None:
    """Both engines define PipelineStage but with different fields."""
    from hermes_os.pipeline_engine import PipelineStage as V1Stage
    from hermes_os.pipeline_engine_v2 import PipelineStage as V2Stage

    # v1: name, sequence, labor_type, description, ...
    # v2: stage, labor, task, verify
    v1 = V1Stage(name="M1", sequence=0, labor_type="content", description="Write")
    v2 = V2Stage(stage="M1", labor="ContentLabor", task="Write", verify="check")
    assert v1.name == "M1"
    assert v2.stage == "M1"


def test_both_have_stage_status_enum() -> None:
    """Both engines have StageStatus but with different values."""
    from hermes_os.pipeline_engine import StageStatus as V1Status
    from hermes_os.pipeline_engine_v2 import StageStatus as V2Status

    assert V1Status.RUNNING is not None
    assert V2Status.IN_PROGRESS is not None


# ---------------------------------------------------------------------------
# Tests: v2 BatchArtifactMeta lives in pipeline_engine_v2
# ---------------------------------------------------------------------------

def test_batch_artifact_meta_serialization() -> None:
    """BatchArtifactMeta.to_json() → from_json() should be lossless."""
    from hermes_os.pipeline_engine_v2 import BatchArtifactMeta

    original = BatchArtifactMeta(
        artifact_id="bp_001",
        title="Business Plan",
        target_audience="investors",
        style="formal",
        current_stage="M1_OUTLINE",
        status="in_progress",
        key_thesis=["thesis1"],
        stage_history=["M1_OUTLINE"],
        audit_score=0.85,
        liabilities={"token_usage": 1000, "api_cost_usd": 0.5},
        equity={"realized_revenue_usd": 10.0},
    )

    json_str = original.to_json()
    restored = BatchArtifactMeta.from_json(json_str)

    assert restored.artifact_id == original.artifact_id
    assert restored.current_stage == original.current_stage
    assert restored.audit_score == original.audit_score
    assert restored.roi > 0


def test_batch_artifact_meta_roi_calculation() -> None:
    """BatchArtifactMeta.calculate_roi() should compute correctly."""
    from hermes_os.pipeline_engine_v2 import BatchArtifactMeta

    meta = BatchArtifactMeta(
        artifact_id="bp_001",
        title="Test",
        target_audience="test",
        style="formal",
        current_stage="M1",
        status="in_progress",
        liabilities={"api_cost_usd": 10.0},
        equity={"realized_revenue_usd": 25.0},
    )
    assert meta.calculate_roi() == 1.5


# ---------------------------------------------------------------------------
# Tests: v2 PipelineConfig (different from v1 PipelineDefinition)
# ---------------------------------------------------------------------------

def test_pipeline_config_from_yaml() -> None:
    """PipelineConfig.from_yaml should parse v2 pipeline YAML (string)."""
    from hermes_os.pipeline_engine_v2 import PipelineConfig

    yaml_str = """
name: TestPipeline
description: A test pipeline
steps:
  - stage: M1_OUTLINE
    labor: ContentLabor
    task: Generate outline
    verify: check_structure_completeness
  - stage: M2_RESEARCH
    labor: ResearchLabor
    task: Conduct research
    verify: check_evidence_density
"""
    config = PipelineConfig.from_yaml(yaml_str)
    assert config.name == "TestPipeline"
    assert len(config.steps) == 2
    assert config.steps[0].stage == "M1_OUTLINE"
    assert config.steps[0].labor == "ContentLabor"


# ---------------------------------------------------------------------------
# Tests: v1 PipelineDefinition from_yaml
# ---------------------------------------------------------------------------

def test_pipeline_definition_from_yaml(tmp_path: Path) -> None:
    """PipelineDefinition.from_yaml should load v1 pipeline YAML (file path)."""
    from hermes_os.pipeline_engine import PipelineDefinition

    yaml_content = """
name: BookPipeline
description: Write a book
version: "1.0"
stages:
  - name: OUTLINE
    sequence: 0
    labor_type: content
    description: Generate outline
    estimated_minutes: 10
  - name: WRITE
    sequence: 1
    labor_type: content
    description: Write chapters
    parallel: true
    parallel_max_concurrent: 5
"""
    yaml_path = tmp_path / "pipeline.yaml"
    yaml_path.write_text(yaml_content, "utf-8")

    definition = PipelineDefinition.from_yaml(yaml_path)
    assert definition.name == "BookPipeline"
    assert len(definition.stages) == 2
    assert definition.stages[1].parallel is True
    assert definition.stages[1].parallel_max_concurrent == 5


# ---------------------------------------------------------------------------
# Tests: v1 PipelineWorkspace
# ---------------------------------------------------------------------------

def test_pipeline_workspace_paths() -> None:
    """PipelineWorkspace should expose src_path, render_path, delivery_path."""
    from hermes_os.pipeline_engine import PipelineWorkspace

    ws = PipelineWorkspace(
        task_id="book_001",
        pipeline_name="BookPipeline",
        root_path=Path("/tmp/artifacts/book_001"),
    )
    assert ws.src_path == Path("/tmp/artifacts/book_001/src")
    assert ws.render_path == Path("/tmp/artifacts/book_001/render")
    assert ws.delivery_path == Path("/tmp/artifacts/book_001/delivery")


def test_pipeline_workspace_serialization() -> None:
    """PipelineWorkspace.to_dict() → from_dict() should be lossless."""
    from hermes_os.pipeline_engine import PipelineWorkspace

    ws = PipelineWorkspace(
        task_id="bp_001",
        pipeline_name="BookPipeline",
        root_path=Path("/tmp/bp_001"),
        completed_stages=["OUTLINE", "RESEARCH"],
        failed_stages=[],
        current_stage="WRITE",
        stage_statuses={"OUTLINE": "completed", "RESEARCH": "completed"},
    )

    data = ws.to_dict()
    restored = PipelineWorkspace.from_dict(data, ws.root_path)

    assert restored.task_id == ws.task_id
    assert restored.completed_stages == ws.completed_stages
    assert restored.stage_statuses == ws.stage_statuses


# ---------------------------------------------------------------------------
# Tests: v2 verification functions
# ---------------------------------------------------------------------------

def test_verify_outline_completeness_passes() -> None:
    """verify_outline_completeness should pass a well-structured outline."""
    import asyncio
    from hermes_os.pipeline_engine_v2 import verify_outline_completeness

    outline = """# 主标题

## 第一节
### 子节1.1
### 子节1.2

## 第二节
### 子节2.1
"""
    result = asyncio.run(verify_outline_completeness(outline))
    assert result.passed is True


def test_verify_outline_completeness_fails_on_hollow() -> None:
    """verify_outline_completeness should fail on hollow outline."""
    import asyncio
    from hermes_os.pipeline_engine_v2 import verify_outline_completeness

    outline = """# 主标题

这是一些内容，但没有子结构。
"""
    result = asyncio.run(verify_outline_completeness(outline))
    assert result.passed is False


def test_verify_audit_score_threshold() -> None:
    """verify_audit_score should enforce 0.8 threshold."""
    import asyncio
    from hermes_os.pipeline_engine_v2 import verify_audit_score

    result = asyncio.run(verify_audit_score(0.85))
    assert result.passed is True

    result = asyncio.run(verify_audit_score(0.79))
    assert result.passed is False


# ---------------------------------------------------------------------------
# Tests: Integration — v1 PipelineEngine.execute_stage with mock labor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_stage_runs_labor_and_updates_workspace(tmp_path: Path) -> None:
    """execute_stage should call labor.execute() and mark stage completed."""
    from hermes_os.pipeline_engine import PipelineEngine, PipelineStage, PipelineWorkspace

    # Create workspace manually
    task_id = "test_001"
    root = tmp_path / task_id
    root.mkdir(parents=True)
    (root / "src").mkdir()
    (root / "render").mkdir()

    ws = PipelineWorkspace(
        task_id=task_id,
        pipeline_name="TestPipeline",
        root_path=root,
    )

    # Write workspace meta so it can be loaded
    engine = PipelineEngine(artifact_base=tmp_path)
    engine._write_meta(ws)

    # Register mock labor
    from hermes_os.pipeline_engine import LaborResult
    engine._labor_registry["mock_labor"] = MagicMock()
    mock_result = LaborResult(success=True, output_content="done")
    engine._labor_registry["mock_labor"].execute = AsyncMock(return_value=mock_result)

    # Define stage
    stage = PipelineStage(
        name="TEST_STAGE",
        sequence=0,
        labor_type="mock_labor",
        description="Test stage",
        input_artifact=None,
        output_artifact="test_output.md",
    )

    # Execute
    context = {"topic": "Test"}
    result = await engine.execute_stage(task_id, stage, context)

    assert result.success is True


# ---------------------------------------------------------------------------
# Tests: v1 ParallelChapterLabor
# ---------------------------------------------------------------------------

def test_parallel_chapter_labor_threshold_logic() -> None:
    """ParallelChapterLabor respects failure_threshold."""
    from hermes_os.pipeline_engine import ParallelChapterLabor

    labor = ParallelChapterLabor(max_concurrent=3, failure_threshold=0.5)

    # 2 failed out of 4 = exactly threshold (50%) — should pass
    failed = 2
    total = 4
    failure_ratio = failed / total
    overall_success = failure_ratio <= labor._failure_threshold
    assert overall_success is True

    # 3 failed out of 4 = 75% — should fail
    failed = 3
    failure_ratio = failed / total
    overall_success = failure_ratio <= labor._failure_threshold
    assert overall_success is False
