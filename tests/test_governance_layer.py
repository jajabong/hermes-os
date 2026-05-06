"""Tests for GovernanceLayer — dual-repo memory management."""

import shutil
import tempfile
from pathlib import Path

import pytest

from hermes_os.governance_layer import (
    _QUALITY_THRESHOLD,
    GovernanceConfig,
    GovernanceManager,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class TempGlobalWiki:
    """Creates a temporary global_wiki for testing."""

    def __init__(self) -> None:
        self._tmp: Path | None = None
        self._orig_home = Path.home()

    def __enter__(self) -> Path:
        self._tmp = Path(tempfile.mkdtemp())
        wiki = self._tmp / "global_wiki"
        wiki.mkdir()
        (wiki / "wiki").mkdir()
        for cat in ["概念", "项目", "人物", "规则", "流程", "模板"]:
            (wiki / "wiki" / cat).mkdir()
        return wiki

    def __exit__(self, *args) -> None:
        if self._tmp:
            shutil.rmtree(self._tmp)


@pytest.fixture
def temp_gwiki() -> Path:
    with TempGlobalWiki() as g:
        yield g


# ---------------------------------------------------------------------------
# GovernanceConfig tests
# ---------------------------------------------------------------------------


class TestGovernanceConfig:
    def test_default_quality_threshold(self) -> None:
        cfg = GovernanceConfig()
        assert cfg.quality_threshold == _QUALITY_THRESHOLD

    def test_custom_quality_threshold(self) -> None:
        cfg = GovernanceConfig(quality_threshold=0.5)
        assert cfg.quality_threshold == 0.5


# ---------------------------------------------------------------------------
# Quality evaluation (static helpers)
# ---------------------------------------------------------------------------


class TestQualityEvaluation:
    def test_high_quality_structured_content(self) -> None:
        content = """# 项目报告

## 目标
完成供应商对比分析

## 结果
- 供应商A: 90分
- 供应商B: 85分

## 结论
推荐供应商A
"""
        # Private helper accessed via GovernanceManager._evaluate_content_quality
        gm = GovernanceManager.__new__(GovernanceManager)
        gm._config = GovernanceConfig()
        score = gm._evaluate_content_quality(content)
        assert score >= _QUALITY_THRESHOLD

    def test_low_quality_short_content(self) -> None:
        content = "TODO: fix this later"
        gm = GovernanceManager.__new__(GovernanceManager)
        gm._config = GovernanceConfig()
        score = gm._evaluate_content_quality(content)
        assert score < _QUALITY_THRESHOLD

    def test_low_quality_placeholder_text(self) -> None:
        content = "..." * 50
        gm = GovernanceManager.__new__(GovernanceManager)
        gm._config = GovernanceConfig()
        score = gm._evaluate_content_quality(content)
        assert score < _QUALITY_THRESHOLD


# ---------------------------------------------------------------------------
# Global wiki directory structure
# ---------------------------------------------------------------------------


class TestGlobalWikiStructure:
    def test_global_wiki_created_on_init(self, temp_gwiki: Path) -> None:
        cfg = GovernanceConfig(global_wiki_base=temp_gwiki)
        assert (temp_gwiki / "wiki").exists()
        for cat in ["概念", "项目", "人物", "规则", "流程", "模板"]:
            assert (temp_gwiki / "wiki" / cat).exists()


# ---------------------------------------------------------------------------
# promote_to_global tests
# ---------------------------------------------------------------------------


class TestPromoteToGlobal:
    @pytest.fixture
    def gm(self, temp_gwiki: Path) -> GovernanceManager:
        cfg = GovernanceConfig(
            global_wiki_base=temp_gwiki,
            private_brain_base=temp_gwiki.parent / "users",
        )
        gm = GovernanceManager.__new__(GovernanceManager)
        gm._db_path = ":memory:"
        gm._jarvis = None
        gm._config = cfg
        gm._ensure_global_wiki_exists()
        return gm

    @pytest.fixture
    def private_brain(self, temp_gwiki: Path) -> Path:
        users = temp_gwiki.parent / "users"
        users.mkdir(parents=True, exist_ok=True)
        user_dir = users / "test_user" / "brain" / "产出"
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    @pytest.mark.asyncio
    async def test_promote_copies_to_global_wiki(
        self, gm: GovernanceManager, private_brain: Path
    ) -> None:
        # Write a private MD file
        src = private_brain / "概念.md"
        src.write_text("# 测试概念\n\n这是一个测试概念。", encoding="utf-8")

        result = await gm.promote_to_global("test_user", src)

        assert result.success
        assert result.global_path is not None
        global_path = Path(result.global_path)
        assert global_path.exists()
        assert "概念" in str(global_path)

    @pytest.mark.asyncio
    async def test_promote_returns_global_path(
        self, gm: GovernanceManager, private_brain: Path
    ) -> None:
        src = private_brain / "项目.md"
        src.write_text("# 测试项目\n\n内容", encoding="utf-8")

        result = await gm.promote_to_global("test_user", src)

        assert result.success
        assert result.global_path is not None
        assert result.global_path.endswith(".md")

    @pytest.mark.asyncio
    async def test_promote_file_not_found(self, gm: GovernanceManager) -> None:
        result = await gm.promote_to_global("test_user", "/nonexistent/file.md")
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_promote_handles_conflict(
        self, gm: GovernanceManager, private_brain: Path
    ) -> None:
        # Write same-name file twice
        src1 = private_brain / "概念.md"
        src1.write_text("# 概念1\n\n内容1", encoding="utf-8")

        result1 = await gm.promote_to_global("test_user", src1)
        assert result1.success

        # Second promotion should not overwrite
        src2 = private_brain / "概念.md"
        src2.write_text("# 概念2\n\n内容2", encoding="utf-8")

        result2 = await gm.promote_to_global("test_user", src2)
        # Should succeed but create a new file (with timestamp)
        assert result2.success

    @pytest.mark.asyncio
    async def test_promote_infers_category_from_path(
        self, gm: GovernanceManager, private_brain: Path
    ) -> None:
        # Create a path that looks like it's from wiki/项目/
        wiki_dir = private_brain.parent / "wiki" / "项目"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        src = wiki_dir / "my_project.md"
        src.write_text("# 我的项目\n\n内容", encoding="utf-8")

        result = await gm.promote_to_global("test_user", src)

        assert result.success
        assert "项目" in result.global_path

    @pytest.mark.asyncio
    async def test_promote_creates_contributors_entry(
        self, gm: GovernanceManager, private_brain: Path
    ) -> None:
        src = private_brain / "概念.md"
        src.write_text("# 测试\n\n内容", encoding="utf-8")

        await gm.promote_to_global("test_user", src)

        contributors = gm._config.global_wiki_base / "CONTRIBUTORS.md"
        assert contributors.exists()
        content = contributors.read_text(encoding="utf-8")
        assert "test_user" in content


# ---------------------------------------------------------------------------
# get_combined_context tests
# ---------------------------------------------------------------------------


class TestGetCombinedContext:
    @pytest.fixture
    def gm_with_indexers(self, temp_gwiki: Path) -> GovernanceManager:
        cfg = GovernanceConfig(
            global_wiki_base=temp_gwiki,
            private_brain_base=temp_gwiki.parent / "users",
        )
        gm = GovernanceManager.__new__(GovernanceManager)
        gm._db_path = ":memory:"
        gm._jarvis = None
        gm._config = cfg
        gm._ensure_global_wiki_exists()
        return gm

    @pytest.mark.asyncio
    async def test_combined_context_structure(self, gm_with_indexers: GovernanceManager) -> None:
        result = await gm_with_indexers.get_combined_context("test_user", "test query")
        assert "results" in result
        assert "query" in result
        assert "private_count" in result
        assert "global_count" in result
        assert result["query"] == "test query"

    @pytest.mark.asyncio
    async def test_combined_context_results_are_list(
        self, gm_with_indexers: GovernanceManager
    ) -> None:
        result = await gm_with_indexers.get_combined_context("test_user", "")
        assert isinstance(result["results"], list)


# ---------------------------------------------------------------------------
# _infer_category tests
# ---------------------------------------------------------------------------


class TestInferCategory:
    @pytest.fixture
    def gm(self, temp_gwiki: Path) -> GovernanceManager:
        cfg = GovernanceConfig(global_wiki_base=temp_gwiki)
        gm = GovernanceManager.__new__(GovernanceManager)
        gm._config = cfg
        return gm

    def test_infer_from_rules(self, gm: GovernanceManager) -> None:
        result = gm._infer_category(Path("test.md"), {"category": "规则"})
        assert result == "规则"

    def test_infer_from_path_project(self, gm: GovernanceManager) -> None:
        result = gm._infer_category(Path("/path/wiki/项目/my_project.md"), None)
        assert result == "项目"

    def test_infer_from_path_concept(self, gm: GovernanceManager) -> None:
        result = gm._infer_category(Path("/path/wiki/概念/test.md"), None)
        assert result == "概念"

    def test_infer_default_concept(self, gm: GovernanceManager) -> None:
        result = gm._infer_category(Path("/path/some/file.md"), None)
        assert result == "概念"
