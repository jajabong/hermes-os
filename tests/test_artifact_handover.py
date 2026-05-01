"""Tests for Artifact Handover Protocol — parent_artifact_id and artifact linking.

The Artifact Handover Protocol enables pipeline chaining:
  P3 (Intelligence) → P1 (Content Assembly) → P4 (Delivery)

Each artifact can carry a `parent_artifact_id` so downstream pipelines
know what upstream artifact to consume.
"""

import pytest
import tempfile
import shutil
from pathlib import Path

from hermes_os.artifact_manager import (
    ArtifactManager,
    ArtifactWorkspace,
    ArtifactStage,
    ArtifactStatus,
    ArtifactMeta,
)
from hermes_os.pipeline_engine import PipelineEngine, PipelineStage
from typing import TYPE_CHECKING, Any


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_base() -> Path:
    tmp = Path(tempfile.mkdtemp())
    yield tmp
    shutil.rmtree(tmp)


@pytest.fixture
def am(temp_base: Path) -> ArtifactManager:
    return ArtifactManager(base_dir=temp_base / "artifacts")


# ---------------------------------------------------------------------------
# parent_artifact_id in ArtifactMeta
# ---------------------------------------------------------------------------

class TestParentArtifactId:
    """parent_artifact_id enables artifact lineage tracking."""

    @pytest.mark.asyncio
    async def test_parent_artifact_id_field_exists(self, am: ArtifactManager) -> None:
        """ArtifactMeta should have a parent_artifact_id field."""
        ws = await am.create_workspace("p3-result")
        assert hasattr(ws.meta, "parent_artifact_id")

    @pytest.mark.asyncio
    async def test_parent_artifact_id_defaults_to_empty(self, am: ArtifactManager) -> None:
        """New artifact has no parent (root of chain)."""
        ws = await am.create_workspace("p3-result")
        assert ws.meta.parent_artifact_id == ""

    @pytest.mark.asyncio
    async def test_set_parent_artifact_id(self, am: ArtifactManager) -> None:
        """Can set parent_artifact_id to link to upstream artifact."""
        ws = await am.create_workspace("p3-result")
        await am.set_parent_artifact_id("p3-result", "p3-intelligence-001")
        reloaded = await am.load_workspace("p3-result")
        assert reloaded.meta.parent_artifact_id == "p3-intelligence-001"

    @pytest.mark.asyncio
    async def test_parent_artifact_id_persisted(self, am: ArtifactManager) -> None:
        """parent_artifact_id is stored in meta.json."""
        ws = await am.create_workspace("p1-input")
        await am.set_parent_artifact_id("p1-input", "p3-artifact-xyz")
        meta_path = ws.root_path / "meta.json"
        import json
        data = json.loads(meta_path.read_text("utf-8"))
        assert data["parent_artifact_id"] == "p3-artifact-xyz"


# ---------------------------------------------------------------------------
# Artifact Linking — dependency tree
# ---------------------------------------------------------------------------

class TestArtifactLinking:
    """Artifact linking builds a dependency tree across pipeline stages."""

    @pytest.mark.asyncio
    async def test_register_child_artifact(self, am: ArtifactManager) -> None:
        """Registering a child artifact creates parent→child link."""
        parent = await am.create_workspace("parent-ws")
        child = await am.create_workspace("child-ws")

        await am.register_child_artifact("parent-ws", "child-ws")

        children = await am.get_child_artifacts("parent-ws")
        assert "child-ws" in children

    @pytest.mark.asyncio
    async def test_get_child_artifacts_empty_for_leaf(self, am: ArtifactManager) -> None:
        """Leaf artifact with no children returns empty list."""
        ws = await am.create_workspace("leaf-only")
        children = await am.get_child_artifacts("leaf-only")
        assert children == []

    @pytest.mark.asyncio
    async def test_get_child_artifacts_multiple(self, am: ArtifactManager) -> None:
        """Multiple children are all returned."""
        parent = await am.create_workspace("multi-parent")
        for i in range(3):
            await am.create_workspace(f"child-{i}")

        for i in range(3):
            await am.register_child_artifact("multi-parent", f"child-{i}")

        children = await am.get_child_artifacts("multi-parent")
        assert len(children) == 3

    @pytest.mark.asyncio
    async def test_get_artifact_lineage_root_only(self, am: ArtifactManager) -> None:
        """Root artifact with no parent returns empty lineage."""
        ws = await am.create_workspace("root-only")
        lineage = await am.get_artifact_lineage("root-only")
        assert lineage == []

    @pytest.mark.asyncio
    async def test_get_artifact_lineage_single_parent(self, am: ArtifactManager) -> None:
        """Single-level chain: root ← child."""
        p3 = await am.create_workspace("p3-artifact")
        p1 = await am.create_workspace("p1-artifact")
        await am.set_parent_artifact_id("p1-artifact", "p3-artifact")

        lineage = await am.get_artifact_lineage("p1-artifact")
        assert len(lineage) == 1
        assert lineage[0].task_id == "p3-artifact"

    @pytest.mark.asyncio
    async def test_get_artifact_lineage_full_chain(self, am: ArtifactManager) -> None:
        """Full chain: P3 → P1 → P4."""
        p3 = await am.create_workspace("p3")
        p1 = await am.create_workspace("p1")
        p4 = await am.create_workspace("p4")

        await am.set_parent_artifact_id("p1", "p3")
        await am.set_parent_artifact_id("p4", "p1")

        lineage_p4 = await am.get_artifact_lineage("p4")
        assert len(lineage_p4) == 2
        assert lineage_p4[0].task_id == "p3"
        assert lineage_p4[1].task_id == "p1"

    @pytest.mark.asyncio
    async def test_get_artifact_tree(self, am: ArtifactManager) -> None:
        """get_artifact_tree returns full dependency tree from root."""
        # P3 → P1 → P4  (P3 is root)
        p3 = await am.create_workspace("p3")
        p1 = await am.create_workspace("p1")
        p4 = await am.create_workspace("p4")

        await am.set_parent_artifact_id("p1", "p3")
        await am.set_parent_artifact_id("p4", "p1")
        await am.register_child_artifact("p3", "p1")
        await am.register_child_artifact("p1", "p4")

        tree = await am.get_artifact_tree("p3")
        assert tree["task_id"] == "p3"
        assert len(tree["children"]) == 1
        assert tree["children"][0]["task_id"] == "p1"
        assert len(tree["children"][0]["children"]) == 1
        assert tree["children"][0]["children"][0]["task_id"] == "p4"


# ---------------------------------------------------------------------------
# Pipeline Orchestrator — project.yaml driven chaining
# ---------------------------------------------------------------------------

class TestPipelineOrchestrator:
    """Project orchestrator chains multiple pipelines via project.yaml."""

    @pytest.fixture
    def temp_project(self, temp_base: Path) -> Path:
        project = temp_base / "my-book-project"
        project.mkdir()
        return project

    @pytest.fixture
    def sample_project_yaml(self, temp_project: Path) -> Path:
        yaml_content = """
name: "my-book-project"
description: "从选题到上架的完整流程"
version: "1.0"

steps:
  - pipeline: P3_Intelligence
    task_id: "topic-research"
    context:
      topic: "AI时代的组织变革"

  - pipeline: P1_Content_Assembly
    task_id: "write-book"
    depends_on: ["topic-research"]
    context:
      title: "AI时代的组织变革"

  - pipeline: P4_Delivery
    task_id: "publish-amazon"
    depends_on: ["write-book"]
    context:
      platform: "amazon"
"""
        path = temp_project / "project.yaml"
        path.write_text(yaml_content, "utf-8")
        return path

    def test_load_project_yaml(self, sample_project_yaml: Path) -> None:
        """ProjectOrchestrator loads project.yaml and parses steps."""
        from hermes_os.pipeline_orchestrator import ProjectOrchestrator, ProjectDefinition, ProjectStep

        proj = ProjectDefinition.from_yaml(sample_project_yaml)
        assert proj.name == "my-book-project"
        assert len(proj.steps) == 3

    def test_step_has_depends_on(self, sample_project_yaml: Path) -> None:
        """Step definitions include depends_on for ordering."""
        from hermes_os.pipeline_orchestrator import ProjectDefinition

        proj = ProjectDefinition.from_yaml(sample_project_yaml)
        write_step = proj.steps[1]
        assert "topic-research" in write_step.depends_on

    def test_step_sequencing_by_depends_on(self, sample_project_yaml: Path) -> None:
        """Steps are sorted so dependencies run first."""
        from hermes_os.pipeline_orchestrator import ProjectDefinition

        proj = ProjectDefinition.from_yaml(sample_project_yaml)
        ids = [s.task_id for s in proj.ordered_steps()]
        assert ids.index("topic-research") < ids.index("write-book")
        assert ids.index("write-book") < ids.index("publish-amazon")

    @pytest.mark.asyncio
    async def test_orchestrator_runs_steps_in_order(
        self, sample_project_yaml: Path, temp_project: Path
    ) -> None:
        """Orchestrator executes pipelines in dependency order."""
        from hermes_os.pipeline_orchestrator import ProjectOrchestrator

        # Use artifact manager as backend
        am = ArtifactManager(base_dir=temp_project / "artifacts")
        engine = PipelineEngine(
            artifact_base=temp_project / "artifacts",
            notification_manager=None,
        )
        orch = ProjectOrchestrator(engine=engine, artifact_manager=am)

        # Mock execute_pipeline on engine to track call order
        call_order = []
        original_execute = engine.execute_pipeline

        async def tracking_execute(task_id, definition, context):
            call_order.append(task_id)
            return {}

        engine.execute_pipeline = tracking_execute

        await orch.run_project(sample_project_yaml)

        assert call_order == ["topic-research", "write-book", "publish-amazon"]

    @pytest.mark.asyncio
    async def test_orchestrator_passes_parent_artifact_to_child(
        self, sample_project_yaml: Path, temp_project: Path
    ) -> None:
        """When child pipeline runs, parent_artifact_id is set automatically."""
        from hermes_os.pipeline_orchestrator import ProjectOrchestrator

        am = ArtifactManager(base_dir=temp_project / "artifacts")
        engine = PipelineEngine(
            artifact_base=temp_project / "artifacts",
            notification_manager=None,
        )
        orch = ProjectOrchestrator(engine=engine, artifact_manager=am)

        # Track final parent links by checking meta after run completes
        final_parent_links = {}
        original_set_parent = am.set_parent_artifact_id

        async def tracking_set_parent(task_id, parent_id):
            final_parent_links[task_id] = parent_id
            return await original_set_parent(task_id, parent_id)

        am.set_parent_artifact_id = tracking_set_parent

        # Mock execute_pipeline to avoid real execution
        async def noop_execute(*args, **kwargs):
            return {}

        engine.execute_pipeline = noop_execute

        await orch.run_project(sample_project_yaml)

        # write-book should reference topic-research as parent
        assert final_parent_links.get("write-book") == "topic-research"
        assert final_parent_links.get("publish-amazon") == "write-book"


# ---------------------------------------------------------------------------
# P3→P1→P4 End-to-End Chain Tests
# ---------------------------------------------------------------------------

class TestP3P1P4Chain:
    """End-to-end integration tests for P3→P1→P4 pipeline chaining.

    Exercises ProjectOrchestrator.run_project() with real execute_pipeline()
    (external I/O only patched), verifying artifact handover and lineage.
    """

    @pytest.fixture
    def temp_chain_dir(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        yield tmp
        shutil.rmtree(tmp)

    @pytest.fixture
    def sample_p3_p1_p4_yaml(self, temp_chain_dir: Path) -> Path:
        yaml_content = """
name: "p3-p1-p4-chain"
description: "P3 Intelligence → P1 Content Assembly → P4 Delivery"
version: "1.0"

steps:
  - pipeline: P3_Intelligence
    task_id: "topic-research"
    context:
      topic: "AI组织变革"

  - pipeline: P1_Content_Assembly
    task_id: "write-book"
    depends_on: ["topic-research"]
    context:
      title: "AI组织变革"

  - pipeline: P4_Delivery
    task_id: "publish-amazon"
    depends_on: ["write-book"]
    context:
      platform: "amazon"
"""
        path = temp_chain_dir / "project.yaml"
        path.write_text(yaml_content, "utf-8")
        return path

    @pytest.fixture
    def p3_research_content(self, temp_chain_dir: Path) -> Path:
        """Pre-populate P3 workspace with mock research output."""
        p3_root = temp_chain_dir / "artifacts" / "topic-research"
        (p3_root / "src").mkdir(parents=True, exist_ok=True)
        research_md = p3_root / "src" / "research.md"
        research_md.write_text(
            "# AI时代的组织变革研究报告\n\n"
            "本文探讨AI如何重塑组织结构和管理实践。\n",
            "utf-8",
        )
        return research_md

    @pytest.mark.asyncio
    async def test_chain_executes_all_stages(
        self,
        sample_p3_p1_p4_yaml: Path,
        temp_chain_dir: Path,
        p3_research_content: Path,
    ) -> None:
        """P3→P1→P4 chain executes all 3 pipelines with success."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from hermes_os.pipeline_engine import PipelineEngine, PipelineStage
        from hermes_os.pipeline_orchestrator import ProjectOrchestrator
        from hermes_os.artifact_manager import ArtifactManager

        am = ArtifactManager(base_dir=temp_chain_dir / "artifacts")
        engine = PipelineEngine(artifact_base=temp_chain_dir / "artifacts")
        orch = ProjectOrchestrator(engine=engine, artifact_manager=am)

        # Pre-populate P3 workspace (as if Intelligence pipeline already ran)
        p3_ws = await am.create_workspace("topic-research")
        await am.set_parent_artifact_id("topic-research", "")
        p3_src = p3_ws.root_path / "src"
        p3_src.mkdir(parents=True, exist_ok=True)
        (p3_src / "research.md").write_text(
            "# AI时代的组织变革\n\n本文探讨AI如何重塑组织结构。\n",
            "utf-8",
        )

        # Patch ContentLabor.invoke and FormatLabor subprocess
        mock_invoke_result = MagicMock()
        mock_invoke_result.stdout = "# Manuscript\n\nBook content about AI org change...\n"

        mock_subprocess_result = MagicMock()
        mock_subprocess_result.returncode = 0
        mock_subprocess_result.stdout = ""
        mock_subprocess_result.stderr = ""

        with patch(
            "hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock
        ) as mock_invoke:
            mock_invoke.return_value = mock_invoke_result

            with patch("subprocess.run", new_callable=MagicMock) as mock_run:
                mock_run.return_value = mock_subprocess_result

                results = await orch.run_project(sample_p3_p1_p4_yaml)

        # All 3 pipelines should succeed
        assert "topic-research" in results
        assert results["topic-research"]["success"] is True
        assert "write-book" in results
        assert results["write-book"]["success"] is True
        assert "publish-amazon" in results
        assert results["publish-amazon"]["success"] is True

        # write-book workspace should have content
        write_ws = await am.load_workspace("write-book")
        assert write_ws is not None
        assert (write_ws.root_path / "src").exists()

    @pytest.mark.asyncio
    async def test_artifact_handover_lineage(
        self,
        sample_p3_p1_p4_yaml: Path,
        temp_chain_dir: Path,
    ) -> None:
        """After P3→P1→P4 chain, publish-amazon lineage includes both ancestors."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from hermes_os.pipeline_engine import PipelineEngine
        from hermes_os.pipeline_orchestrator import ProjectOrchestrator
        from hermes_os.artifact_manager import ArtifactManager

        am = ArtifactManager(base_dir=temp_chain_dir / "artifacts")
        engine = PipelineEngine(artifact_base=temp_chain_dir / "artifacts")
        orch = ProjectOrchestrator(engine=engine, artifact_manager=am)

        mock_invoke_result = MagicMock()
        mock_invoke_result.stdout = "# Content\n\n..."
        mock_subprocess_result = MagicMock()
        mock_subprocess_result.returncode = 0
        mock_subprocess_result.stdout = ""
        mock_subprocess_result.stderr = ""

        with patch(
            "hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock
        ) as mock_invoke:
            mock_invoke.return_value = mock_invoke_result
            with patch("subprocess.run", new_callable=MagicMock) as mock_run:
                mock_run.return_value = mock_subprocess_result
                await orch.run_project(sample_p3_p1_p4_yaml)

        # Verify lineage: publish-amazon → write-book → topic-research
        lineage = await am.get_artifact_lineage("publish-amazon")
        lineage_ids = [ws.task_id for ws in lineage]

        assert "topic-research" in lineage_ids
        assert "write-book" in lineage_ids
        # topic-research should come before write-book (root first)
        assert lineage_ids.index("topic-research") < lineage_ids.index("write-book")

    @pytest.mark.asyncio
    async def test_parent_artifact_id_flows_to_context(
        self,
        sample_p3_p1_p4_yaml: Path,
        temp_chain_dir: Path,
    ) -> None:
        """parent_artifact_id is set in context when child pipeline runs."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from hermes_os.pipeline_engine import PipelineEngine
        from hermes_os.pipeline_orchestrator import ProjectOrchestrator
        from hermes_os.artifact_manager import ArtifactManager

        am = ArtifactManager(base_dir=temp_chain_dir / "artifacts")
        engine = PipelineEngine(artifact_base=temp_chain_dir / "artifacts")
        orch = ProjectOrchestrator(engine=engine, artifact_manager=am)

        mock_invoke_result = MagicMock()
        mock_invoke_result.stdout = "# Content\n\n..."
        mock_subprocess_result = MagicMock()
        mock_subprocess_result.returncode = 0
        mock_subprocess_result.stdout = ""
        mock_subprocess_result.stderr = ""

        # Track context passed to execute_pipeline
        captured_contexts: dict[str, dict] = {}
        original_execute = engine.execute_pipeline

        async def tracking_execute(task_id, definition, context):
            captured_contexts[task_id] = dict(context)
            return await original_execute(task_id, definition, context)

        with patch(
            "hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock
        ) as mock_invoke:
            mock_invoke.return_value = mock_invoke_result
            with patch("subprocess.run", new_callable=MagicMock) as mock_run:
                mock_run.return_value = mock_subprocess_result
                engine.execute_pipeline = tracking_execute
                await orch.run_project(sample_p3_p1_p4_yaml)

        # write-book should have topic-research as parent_artifact_id
        assert captured_contexts.get("write-book", {}).get("parent_artifact_id") == "topic-research"
        # publish-amazon should have write-book as parent_artifact_id
        assert captured_contexts.get("publish-amazon", {}).get("parent_artifact_id") == "write-book"
        # topic-research has no parent — parent_artifact_id absent from context
        assert "parent_artifact_id" not in captured_contexts.get("topic-research", {})


# ---------------------------------------------------------------------------
# Pipeline Hooks (P5 Governance)
# ---------------------------------------------------------------------------

class TestPipelineHooks:
    """Pipeline hooks enable P5 Governance as built-in middleware."""

    @pytest.fixture
    def hook_temp_dir(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        yield tmp
        shutil.rmtree(tmp)

    @pytest.fixture
    def engine(self, hook_temp_dir: Path) -> PipelineEngine:
        return PipelineEngine(
            artifact_base=hook_temp_dir / "artifacts",
            notification_manager=None,
        )

    @pytest.mark.asyncio
    async def test_pre_execute_hook_called(self, engine: PipelineEngine) -> None:
        """Pre-execute hook fires before each stage."""
        hook_calls = []

        async def my_pre_hook(task_id: str, stage_name: str, context: dict) -> None:
            hook_calls.append(("pre", task_id, stage_name))

        engine.register_hook("pre_execute", my_pre_hook)

        from hermes_os.pipeline_engine import PipelineStage
        ws = await engine.create_pipeline_workspace("hook-test-001", "test-pipeline")

        stage = PipelineStage(
            name="research",
            sequence=0,
            labor_type="content",
            description="Test stage",
        )

        await engine.execute_stage("hook-test-001", stage, {"topic": "test"})

        assert ("pre", "hook-test-001", "research") in hook_calls

    @pytest.mark.asyncio
    async def test_post_execute_hook_called(self, engine: PipelineEngine) -> None:
        """Post-execute hook fires after each stage (success or failure)."""
        hook_calls = []

        async def my_post_hook(task_id: str, stage_name: str, context: dict, result: Any) -> None:
            hook_calls.append(("post", task_id, stage_name))

        engine.register_hook("post_execute", my_post_hook)

        from hermes_os.pipeline_engine import PipelineStage
        ws = await engine.create_pipeline_workspace("hook-test-002", "test-pipeline")

        stage = PipelineStage(
            name="research",
            sequence=0,
            labor_type="content",
            description="Test stage",
        )

        await engine.execute_stage("hook-test-002", stage, {"topic": "test"})

        assert ("post", "hook-test-002", "research") in hook_calls

    @pytest.mark.asyncio
    async def test_post_execute_receives_result(self, engine: PipelineEngine) -> None:
        """Post-execute hook receives the LaborResult."""
        received_results = []

        async def result_hook(task_id: str, stage_name: str, context: dict, result: Any) -> None:
            received_results.append(result)

        engine.register_hook("post_execute", result_hook)

        from hermes_os.pipeline_engine import PipelineStage
        ws = await engine.create_pipeline_workspace("hook-test-003", "test-pipeline")

        stage = PipelineStage(
            name="research",
            sequence=0,
            labor_type="content",
            description="Test stage",
        )

        await engine.execute_stage("hook-test-003", stage, {"topic": "test"})

        assert len(received_results) == 1

    @pytest.mark.asyncio
    async def test_multiple_hooks_same_type(self, engine: PipelineEngine) -> None:
        """Multiple hooks of the same type are all called."""
        call_counts = {"pre1": 0, "pre2": 0}

        async def pre_hook1(task_id: str, stage_name: str, context: dict) -> None:
            call_counts["pre1"] += 1

        async def pre_hook2(task_id: str, stage_name: str, context: dict) -> None:
            call_counts["pre2"] += 1

        engine.register_hook("pre_execute", pre_hook1)
        engine.register_hook("pre_execute", pre_hook2)

        from hermes_os.pipeline_engine import PipelineStage
        ws = await engine.create_pipeline_workspace("hook-test-004", "test-pipeline")

        stage = PipelineStage(
            name="research",
            sequence=0,
            labor_type="content",
            description="Test stage",
        )

        await engine.execute_stage("hook-test-004", stage, {"topic": "test"})

        assert call_counts["pre1"] == 1
        assert call_counts["pre2"] == 1
