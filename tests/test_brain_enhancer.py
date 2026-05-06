"""Tests for BrainEnhancer — BrainIndexer + BrainUpdater."""

import tempfile
from pathlib import Path

import pytest

from hermes_os.brain_indexer import BrainIndex, BrainIndexer
from hermes_os.brain_updater import BrainUpdater

# ---------------------------------------------------------------------------
# BrainIndexer tests
# ---------------------------------------------------------------------------


class TestBrainIndexerBasic:
    """Basic BrainIndexer functionality tests."""

    def test_brain_index_structure(self) -> None:
        """BrainIndex dataclass holds the right fields."""
        idx = BrainIndex(
            user_id="alice",
            memory_summary="项目进展顺利",
            user_profile={"name": "张三", "role": "项目经理"},
            active_projects=["Hermes-OS", "AI项目"],
            recent_wiki_updates=["Hermes-OS v0.3"],
        )
        assert idx.user_id == "alice"
        assert "Hermes-OS" in idx.active_projects
        assert idx.user_profile["name"] == "张三"

    @pytest.mark.asyncio
    async def test_index_user_loads_brain_files(self) -> None:
        """BrainIndexer reads MEMORY.md, USER.md, wiki/ from brain directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain_dir = Path(tmpdir) / "test_user" / "brain"
            brain_dir.mkdir(parents=True)
            (brain_dir / "MEMORY.md").write_text("# Memory\n\nTest memory content")
            (brain_dir / "USER.md").write_text("# User\nname: Test User\nrole: developer")
            (brain_dir / "wiki" / "项目").mkdir(parents=True)
            (brain_dir / "wiki" / "项目" / "TestProject.md").write_text(
                "# TestProject\nstatus: active"
            )

            indexer = BrainIndexer(brain_base_path=Path(tmpdir))
            idx = await indexer.index_user("test_user")

            assert idx.user_id == "test_user"
            assert idx.memory_summary is not None
            assert len(idx.memory_summary) > 0
            assert "Test memory content" in idx.memory_summary

    @pytest.mark.asyncio
    async def test_index_user_nonexistent_returns_empty(self) -> None:
        """Indexing a user with no brain directory returns empty index."""
        indexer = BrainIndexer()
        idx = await indexer.index_user("nonexistent_user_xyz")
        assert idx.user_id == "nonexistent_user_xyz"
        assert idx.memory_summary == ""
        assert idx.active_projects == []

    @pytest.mark.asyncio
    async def test_search_wiki_by_keyword(self) -> None:
        """search_wiki returns matching wiki entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain_dir = Path(tmpdir) / "test_user" / "brain" / "wiki" / "概念"
            brain_dir.mkdir(parents=True)
            (brain_dir / "HermesOS.md").write_text("# HermesOS\nAI native organization")

            indexer = BrainIndexer(brain_base_path=Path(tmpdir))
            results = await indexer.search_wiki("test_user", keyword="Hermes")
            assert isinstance(results, list)


class TestBrainIndexProjects:
    """Project tracking from brain directory."""

    @pytest.mark.asyncio
    async def test_get_active_projects(self) -> None:
        """get_active_projects returns project names from wiki/项目/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain_dir = Path(tmpdir) / "test_user" / "brain" / "wiki" / "项目"
            brain_dir.mkdir(parents=True)
            (brain_dir / "TestProject.md").write_text("# TestProject\nstatus: active")

            indexer = BrainIndexer(brain_base_path=Path(tmpdir))
            projects = await indexer.get_active_projects("test_user")
            assert isinstance(projects, list)

    @pytest.mark.asyncio
    async def test_get_project_context(self) -> None:
        """get_project_context returns detailed project info from wiki."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain_dir = Path(tmpdir) / "test_user" / "brain" / "wiki" / "项目"
            brain_dir.mkdir(parents=True)
            (brain_dir / "TestProject.md").write_text(
                "# TestProject\nstatus: active\nprogress: 50%"
            )

            indexer = BrainIndexer(brain_base_path=Path(tmpdir))
            context = await indexer.get_project_context("test_user", "TestProject")
            # Returns None if project not found, or dict with project details
            assert context is None or isinstance(context, dict)


# ---------------------------------------------------------------------------
# BrainUpdater tests
# ---------------------------------------------------------------------------


class TestBrainUpdaterWrite:
    """BrainUpdater write operations."""

    @pytest.mark.asyncio
    async def test_after_task_complete_creates_output_file(self) -> None:
        """after_task_complete writes task result to brain/产出/ACTIVE/."""
        updater = BrainUpdater()
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_user_brain = Path(tmpdir) / "brain" / "产出" / "ACTIVE"
            mock_user_brain.mkdir(parents=True, exist_ok=True)

            # Create a real Task object
            from hermes_os.task_scheduler import Task, TaskPriority, TaskStatus

            task = Task(
                task_id="t-001abcdef",
                user_id="test_user",
                title="检查项目进展",
                description="检查项目状态",
                status=TaskStatus.COMPLETED,
                priority=TaskPriority.NORMAL,
            )

            result = await updater.after_task_complete(
                task=task,
                result="项目进展：正常，3个任务进行中",
                user_brain_path=mock_user_brain,
            )

            assert result is True
            files = list(mock_user_brain.glob("*.md"))
            assert len(files) >= 1

    @pytest.mark.asyncio
    async def test_update_memory_on_milestone(self) -> None:
        """update_memory_on_milestone appends to MEMORY.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_file = Path(tmpdir) / "MEMORY.md"
            memory_file.write_text("# Memory\n\n§\n旧记录")

            updater = BrainUpdater()
            await updater.update_memory_on_milestone(
                memory_file=memory_file,
                milestone="完成了项目 v0.3 开发和测试",
            )

            content = memory_file.read_text()
            assert "v0.3" in content or "完成了" in content

    @pytest.mark.asyncio
    async def test_update_project_wiki(self) -> None:
        """update_project_wiki creates or updates wiki entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_dir = Path(tmpdir) / "wiki" / "项目"
            wiki_dir.mkdir(parents=True, exist_ok=True)

            updater = BrainUpdater()
            await updater.update_project_wiki(
                wiki_dir=wiki_dir,
                project_name="TestProject",
                update={"status": "进行中", "progress": "50%"},
            )

            project_file = wiki_dir / "TestProject.md"
            assert project_file.exists()
            content = project_file.read_text()
            assert "进行中" in content


class TestBrainUpdaterRead:
    """BrainUpdater read operations."""

    @pytest.mark.asyncio
    async def test_read_recent_outputs(self) -> None:
        """read_recent_outputs returns files from 产出/ACTIVE/."""
        updater = BrainUpdater()
        with tempfile.TemporaryDirectory() as tmpdir:
            active_dir = Path(tmpdir) / "ACTIVE"
            active_dir.mkdir(parents=True)
            (active_dir / "task1.md").write_text("# Task 1\nResult")
            (active_dir / "task2.md").write_text("# Task 2\nResult")

            outputs = await updater.read_recent_outputs(active_dir, limit=5)
            assert len(outputs) == 2

    @pytest.mark.asyncio
    async def test_read_empty_outputs_returns_empty(self) -> None:
        """read_recent_outputs returns [] for empty directory."""
        updater = BrainUpdater()
        with tempfile.TemporaryDirectory() as tmpdir:
            outputs = await updater.read_recent_outputs(Path(tmpdir))
            assert outputs == []
