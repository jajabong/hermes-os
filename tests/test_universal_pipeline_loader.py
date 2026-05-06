"""Tests for UniversalPipelineLoader — the unified entry point for all 5 Pipelines.

RED phase: Define the contract first.

This module tests:
1. LaborRegistry: all labors are registered and callable
2. UniversalPipelineLoader: loads Pipeline.yaml, executes stages via Registry
3. All 5 Pipelines can be loaded and executed through the same interface
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from hermes_os.universal_pipeline import (
    # 5 Pipeline types
    LaborHandler,
    LaborRegistry,
    PipelineLoadError,
    StageResult,
    UniversalPipelineLoader,
)


class TestLaborRegistry:
    """Test LaborRegistry is the single source of truth for all Labor handlers."""

    def test_registry_has_all_5_labors(self) -> None:
        """Registry must contain handlers for all 5 pipeline labors."""
        registry = LaborRegistry()
        required_labors = [
            "ContentLabor",
            "ResearchLabor",
            "CheckerLabor",
            "FormatLabor",
            "FeishuLabor",
            "CodeLabor",
            "BrowserLabor",
            "GitHubLabor",
            "DataLabor",
            "GovernanceLabor",
        ]
        for labor in required_labors:
            assert labor in registry._handlers, f"Missing labor: {labor}"

    def test_registry_register_handler(self) -> None:
        """Registry allows dynamic handler registration."""
        registry = LaborRegistry()
        handler = LaborHandler(name="TestLabor", execute=AsyncMock(return_value="ok"))
        registry.register("TestLabor", handler)
        assert "TestLabor" in registry._handlers

    def test_registry_unregister_handler(self) -> None:
        """Registry allows handler removal."""
        registry = LaborRegistry()
        registry.unregister("ContentLabor")
        assert "ContentLabor" not in registry._handlers

    def test_registry_get_handler(self) -> None:
        """Registry returns handler for a labor name."""
        registry = LaborRegistry()
        handler = registry.get("ContentLabor")
        assert handler is not None
        assert handler.name == "ContentLabor"

    def test_registry_returns_none_for_unknown(self) -> None:
        """Registry returns None for unregistered labor."""
        registry = LaborRegistry()
        handler = registry.get("NonExistentLabor")
        assert handler is None


class TestUniversalPipelineLoader:
    """Test UniversalPipelineLoader loads YAML and executes via Registry."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil

        shutil.rmtree(path, ignore_errors=True)

    @pytest.fixture
    def loader(self) -> UniversalPipelineLoader:
        return UniversalPipelineLoader()

    def test_loads_valid_pipeline_yaml(
        self, loader: UniversalPipelineLoader, temp_dir: str
    ) -> None:
        """Loader can parse a valid Pipeline.yaml."""
        yaml_content = """
name: "Test Pipeline"
description: "A test pipeline"
steps:
  - stage: M1
    labor: ContentLabor
    task: "Generate content"
    verify: "check_content"
"""
        yaml_path = Path(temp_dir) / "test_pipeline.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")

        config = loader.load(str(yaml_path))
        assert config.name == "Test Pipeline"
        assert len(config.steps) == 1
        assert config.steps[0].stage == "M1"

    def test_loads_content_assembly_pipeline(self, loader: UniversalPipelineLoader) -> None:
        """Loader can load the Content Assembly pipeline definition."""
        config = loader.load_pipeline("content_assembly")
        assert config.name == "Content Assembly Pipeline"
        # Must have 6 stages
        stage_names = [s.stage for s in config.steps]
        assert "M1_OUTLINE" in stage_names
        assert "M6_DELIVERY" in stage_names

    def test_loads_all_5_pipelines(self, loader: UniversalPipelineLoader) -> None:
        """Loader can load all 5 pipeline definitions."""
        for pipeline_name in [
            "content_assembly",
            "engineering",
            "intelligence",
            "deployment",
            "governance",
        ]:
            config = loader.load_pipeline(pipeline_name)
            assert config.name is not None
            assert len(config.steps) > 0

    def test_load_raises_on_invalid_yaml(
        self, loader: UniversalPipelineLoader, temp_dir: str
    ) -> None:
        """Loader raises PipelineLoadError on malformed YAML."""
        yaml_path = Path(temp_dir) / "invalid.yaml"
        yaml_path.write_text("invalid: [yaml: content", encoding="utf-8")
        with pytest.raises(PipelineLoadError):
            loader.load(str(yaml_path))

    @pytest.mark.asyncio
    async def test_execute_stage_calls_labor(
        self, loader: UniversalPipelineLoader, temp_dir: str
    ) -> None:
        """execute_stage() calls the registered Labor handler."""
        # Create a mock handler
        mock_handler = LaborHandler(
            name="ContentLabor",
            execute=AsyncMock(return_value="content output"),
        )
        loader.registry.register("ContentLabor", mock_handler)

        # Create a simple pipeline
        yaml_content = """
name: "Test"
description: "Test"
steps:
  - stage: M1
    labor: ContentLabor
    task: "Generate"
    verify: "check"
"""
        yaml_path = Path(temp_dir) / "test.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")

        config = loader.load(str(yaml_path))
        result = await loader.execute_stage(config.steps[0], {}, temp_dir)

        assert result.passed is True
        assert mock_handler.execute.called

    @pytest.mark.asyncio
    async def test_execute_full_pipeline(
        self, loader: UniversalPipelineLoader, temp_dir: str
    ) -> None:
        """execute_full_pipeline() runs all stages in sequence."""
        # Mock all handlers to succeed
        for labor_name in loader.registry._handlers.keys():
            mock_handler = LaborHandler(
                name=labor_name,
                execute=AsyncMock(return_value=f"{labor_name} output"),
            )
            loader.registry.register(labor_name, mock_handler)

        config = loader.load_pipeline("content_assembly")
        result = await loader.execute_full_pipeline(
            pipeline_config=config,
            artifact_id="doc_001",
            base_dir=temp_dir,
        )

        assert result.success is True
        assert result.stages_completed == len(config.steps)


class TestPipelineDefinitions:
    """Test that all 5 pipeline YAML definitions are valid."""

    def test_content_assembly_has_6_stages(self) -> None:
        """Content Assembly Pipeline: M1_OUTLINE → M6_DELIVERY."""
        config = UniversalPipelineLoader().load_pipeline("content_assembly")
        stages = [s.stage for s in config.steps]
        expected = [
            "M1_OUTLINE",
            "M2_RESEARCH",
            "M3_DRAFTING",
            "M4_RENDERING",
            "M5_AUDIT",
            "M6_DELIVERY",
        ]
        assert stages == expected

    def test_engineering_has_5_stages(self) -> None:
        """Engineering Pipeline: M1_Spec → M5_GitMerge."""
        config = UniversalPipelineLoader().load_pipeline("engineering")
        stages = [s.stage for s in config.steps]
        expected = ["M1_SPEC", "M2_CODING", "M3_SELFTEST", "M4_LINTING", "M5_GITMERGE"]
        assert stages == expected

    def test_intelligence_has_5_stages(self) -> None:
        """Intelligence Pipeline: M1_DataFetch → M5_Insight."""
        config = UniversalPipelineLoader().load_pipeline("intelligence")
        stages = [s.stage for s in config.steps]
        expected = ["M1_DATAFETCH", "M2_NORMALIZE", "M3_REASONING", "M4_VISUALIZE", "M5_INSIGHT"]
        assert stages == expected

    def test_deployment_has_5_stages(self) -> None:
        """Deployment Pipeline: M1_StateAuth → M5_Finalize."""
        config = UniversalPipelineLoader().load_pipeline("deployment")
        stages = [s.stage for s in config.steps]
        expected = [
            "M1_STATEDAUTH",
            "M2_FORMFILLING",
            "M3_UPLOAD",
            "M4_VERIFICATION",
            "M5_FINALIZE",
        ]
        assert stages == expected

    def test_governance_has_4_stages(self) -> None:
        """Governance Pipeline: M1_Detection → M4_Sync."""
        config = UniversalPipelineLoader().load_pipeline("governance")
        stages = [s.stage for s in config.steps]
        expected = ["M1_DETECTION", "M2_SANITIZE", "M3_PROMOTION", "M4_SYNC"]
        assert stages == expected


class TestPipelineExecutionResult:
    """Test StageResult and PipelineExecutionResult."""

    def test_stage_result_fields(self) -> None:
        """StageResult has required fields."""
        result = StageResult(
            passed=True,
            stage="M1_OUTLINE",
            output="generated outline",
            errors=[],
            warnings=["minor warning"],
        )
        assert result.passed is True
        assert result.stage == "M1_OUTLINE"
        assert result.output == "generated outline"
        assert len(result.warnings) == 1

    def test_pipeline_result_fields(self) -> None:
        """PipelineExecutionResult aggregates all stage results."""
        from hermes_os.universal_pipeline import PipelineExecutionResult

        results = [
            StageResult(passed=True, stage="M1", output="ok"),
            StageResult(passed=True, stage="M2", output="ok"),
        ]
        result = PipelineExecutionResult(
            pipeline_name="test",
            artifact_id="doc_001",
            success=True,
            stages_completed=2,
            stage_results=results,
        )
        assert result.success is True
        assert result.stages_completed == 2
        assert len(result.stage_results) == 2
