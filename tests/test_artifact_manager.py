"""Tests for ArtifactManager — standardized artifact workspace.

Artifact workspace structure:
  /artifacts/{task_id}/
    ├── src/          (raw inputs)
    ├── render/        (intermediate formats: Markdown)
    ├── delivery/     (final output: PDF/EPUB)
    └── meta.json     (stage, status, artifact_uri, dependency_hash)
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

from hermes_os.artifact_manager import (
    ArtifactManager,
    ArtifactWorkspace,
    ArtifactStage,
    ArtifactStatus,
)


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
# ArtifactStage tests
# ---------------------------------------------------------------------------

class TestArtifactStage:
    def test_stage_values(self) -> None:
        assert hasattr(ArtifactStage, "CREATED")
        assert hasattr(ArtifactStage, "RESEARCH")
        assert hasattr(ArtifactStage, "WRITING")
        assert hasattr(ArtifactStage, "RENDERING")
        assert hasattr(ArtifactStage, "DELIVERING")
        assert hasattr(ArtifactStage, "COMPLETED")
        assert hasattr(ArtifactStage, "FAILED")

    def test_stage_order(self) -> None:
        order = [
            ArtifactStage.CREATED,
            ArtifactStage.RESEARCH,
            ArtifactStage.WRITING,
            ArtifactStage.RENDERING,
            ArtifactStage.DELIVERING,
            ArtifactStage.COMPLETED,
        ]
        for i in range(len(order) - 1):
            assert order[i].value < order[i + 1].value


# ---------------------------------------------------------------------------
# ArtifactWorkspace tests
# ---------------------------------------------------------------------------

class TestArtifactWorkspaceInit:
    @pytest.mark.asyncio
    async def test_creates_all_subdirs(self, am: ArtifactManager, temp_base: Path) -> None:
        ws = await am.create_workspace("task-001")
        assert ws.task_id == "task-001"
        assert (temp_base / "artifacts" / "task-001" / "src").is_dir()
        assert (temp_base / "artifacts" / "task-001" / "render").is_dir()
        assert (temp_base / "artifacts" / "task-001" / "delivery").is_dir()
        assert (temp_base / "artifacts" / "task-001" / "meta.json").is_file()

    @pytest.mark.asyncio
    async def test_meta_json_structure(self, am: ArtifactManager, temp_base: Path) -> None:
        ws = await am.create_workspace("task-002")
        meta = ws.meta
        assert meta.task_id == "task-002"
        assert meta.stage == ArtifactStage.CREATED
        assert meta.status == ArtifactStatus.IN_PROGRESS
        assert meta.artifact_uri == ""
        assert meta.last_updated is not None

    @pytest.mark.asyncio
    async def test_workspace_idempotent(self, am: ArtifactManager, temp_base: Path) -> None:
        ws1 = await am.create_workspace("task-003")
        ws2 = await am.create_workspace("task-003")  # should not raise
        assert ws1.task_id == ws2.task_id == "task-003"


# ---------------------------------------------------------------------------
# create_workspace tests
# ---------------------------------------------------------------------------

class TestCreateWorkspace:
    @pytest.mark.asyncio
    async def test_workspace_access_paths(self, am: ArtifactManager) -> None:
        ws = await am.create_workspace("t1")
        assert ws.src_path.exists()
        assert ws.render_path.exists()
        assert ws.delivery_path.exists()

    @pytest.mark.asyncio
    async def test_meta_persisted(self, am: ArtifactManager) -> None:
        ws = await am.create_workspace("t2")
        import json
        meta_path = ws.root_path / "meta.json"
        loaded = json.loads(meta_path.read_text("utf-8"))
        assert loaded["task_id"] == "t2"
        assert loaded["stage"] == ArtifactStage.CREATED.value

    @pytest.mark.asyncio
    async def test_workspace_with_user_id(self, am: ArtifactManager) -> None:
        ws = await am.create_workspace("t3", user_id="alice")
        assert ws.user_id == "alice"


# ---------------------------------------------------------------------------
# update_stage tests
# ---------------------------------------------------------------------------

class TestUpdateStage:
    @pytest.mark.asyncio
    async def test_update_stage_changes_meta(self, am: ArtifactManager) -> None:
        ws = await am.create_workspace("t4")
        await am.update_stage("t4", ArtifactStage.RESEARCH)
        reloaded = await am.load_workspace("t4")
        assert reloaded.meta.stage == ArtifactStage.RESEARCH

    @pytest.mark.asyncio
    async def test_update_stage_updates_timestamp(self, am: ArtifactManager) -> None:
        ws = await am.create_workspace("t5")
        original = ws.meta.last_updated
        await am.update_stage("t5", ArtifactStage.WRITING)
        reloaded = await am.load_workspace("t5")
        assert reloaded.meta.last_updated >= original

    @pytest.mark.asyncio
    async def test_update_stage_not_found(self, am: ArtifactManager) -> None:
        result = await am.update_stage("nonexistent", ArtifactStage.RESEARCH)
        assert result is None


# ---------------------------------------------------------------------------
# update_status tests
# ---------------------------------------------------------------------------

class TestUpdateStatus:
    @pytest.mark.asyncio
    async def test_update_status_to_completed(self, am: ArtifactManager) -> None:
        ws = await am.create_workspace("t6")
        await am.update_stage("t6", ArtifactStage.COMPLETED, status=ArtifactStatus.COMPLETED)
        reloaded = await am.load_workspace("t6")
        assert reloaded.meta.status == ArtifactStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_update_status_to_failed(self, am: ArtifactManager) -> None:
        ws = await am.create_workspace("t7")
        await am.update_stage("t7", ArtifactStage.RENDERING, status=ArtifactStatus.FAILED)
        reloaded = await am.load_workspace("t7")
        assert reloaded.meta.status == ArtifactStatus.FAILED


# ---------------------------------------------------------------------------
# load_workspace tests
# ---------------------------------------------------------------------------

class TestLoadWorkspace:
    @pytest.mark.asyncio
    async def test_load_returns_workspace(self, am: ArtifactManager) -> None:
        ws1 = await am.create_workspace("t8")
        ws2 = await am.load_workspace("t8")
        assert ws2 is not None
        assert ws2.task_id == "t8"

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, am: ArtifactManager) -> None:
        result = await am.load_workspace("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# set_artifact_uri tests
# ---------------------------------------------------------------------------

class TestSetArtifactUri:
    @pytest.mark.asyncio
    async def test_set_artifact_uri(self, am: ArtifactManager) -> None:
        ws = await am.create_workspace("t9")
        await am.set_artifact_uri("t9", "delivery/book.epub")
        reloaded = await am.load_workspace("t9")
        assert reloaded.meta.artifact_uri == "delivery/book.epub"


# ---------------------------------------------------------------------------
# write_src / write_render / write_delivery tests
# ---------------------------------------------------------------------------

class TestWriteArtifactFiles:
    @pytest.mark.asyncio
    async def test_write_src_file(self, am: ArtifactManager) -> None:
        ws = await am.create_workspace("t10")
        path = await am.write_src("t10", "chapter1.md", "# Chapter 1\n\nContent")
        assert path.exists()
        assert "Chapter 1" in path.read_text("utf-8")

    @pytest.mark.asyncio
    async def test_write_render_file(self, am: ArtifactManager) -> None:
        ws = await am.create_workspace("t11")
        path = await am.write_render("t11", "book.md", "# Book\n\nContent")
        assert path.exists()

    @pytest.mark.asyncio
    async def test_write_delivery_file(self, am: ArtifactManager) -> None:
        ws = await am.create_workspace("t12")
        path = await am.write_delivery("t12", "book.epub", b"fake epub content")
        assert path.exists()
        assert path.read_bytes() == b"fake epub content"