"""Tests for GlobalWikiIndexer — indexes ~/.hermes/global_wiki/."""

import shutil
import tempfile
from pathlib import Path

import pytest

from hermes_os.global_wiki_indexer import GlobalWikiIndexer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class TempGlobalWiki:
    """Creates a temporary global_wiki with test content."""

    def __init__(self) -> None:
        self._tmp: Path | None = None

    def __enter__(self) -> Path:
        self._tmp = Path(tempfile.mkdtemp())
        wiki = self._tmp / "global_wiki"
        wiki.mkdir()
        wiki_dir = wiki / "wiki"
        wiki_dir.mkdir()

        for cat in ["概念", "项目", "人物", "规则", "流程", "模板"]:
            (wiki_dir / cat).mkdir()

        # Write test content
        (wiki_dir / "概念" / "test_concept.md").write_text(
            "这是一个测试概念，包含关键词test。", encoding="utf-8"
        )
        (wiki_dir / "项目" / "test_project.md").write_text(
            "这是一个测试项目，内容关于项目管理。", encoding="utf-8"
        )
        (wiki_dir / "概念" / "another.md").write_text("另一个概念文件。", encoding="utf-8")

        # Write MEMORY.md
        (wiki / "MEMORY.md").write_text("# Global Memory", encoding="utf-8")

        return wiki

    def __exit__(self, *args) -> None:
        if self._tmp:
            shutil.rmtree(self._tmp)


@pytest.fixture
def temp_gwiki() -> Path:
    with TempGlobalWiki() as g:
        yield g


# ---------------------------------------------------------------------------
# GlobalWikiIndexer tests
# ---------------------------------------------------------------------------


class TestGlobalWikiIndexerInit:
    def test_default_base_path(self) -> None:
        idx = GlobalWikiIndexer()
        from hermes_os.global_wiki_indexer import _GLOBAL_WIKI_BASE

        assert idx._base == _GLOBAL_WIKI_BASE

    def test_custom_base_path(self, temp_gwiki: Path) -> None:
        idx = GlobalWikiIndexer(base_path=temp_gwiki)
        assert idx._base == temp_gwiki


class TestGlobalWikiSearchWiki:
    @pytest.fixture
    def idx(self, temp_gwiki: Path) -> GlobalWikiIndexer:
        return GlobalWikiIndexer(base_path=temp_gwiki)

    @pytest.mark.asyncio
    async def test_search_wiki_returns_matches(self, idx: GlobalWikiIndexer) -> None:
        results = await idx.search_wiki("测试")
        assert len(results) >= 2  # test_concept.md and test_project.md

    @pytest.mark.asyncio
    async def test_search_wiki_returns_empty_for_no_match(self, idx: GlobalWikiIndexer) -> None:
        results = await idx.search_wiki("xyz_nonexistent_keyword_12345")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_search_wiki_case_insensitive(self, idx: GlobalWikiIndexer) -> None:
        results = await idx.search_wiki("TEST")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_search_wiki_returns_correct_structure(self, idx: GlobalWikiIndexer) -> None:
        results = await idx.search_wiki("概念")
        assert len(results) >= 1
        r = results[0]
        assert "category" in r
        assert "file" in r
        assert "path" in r
        assert "snippet" in r
        assert "source" in r
        assert r["source"] == "global_wiki"

    @pytest.mark.asyncio
    async def test_search_wiki_empty_when_wiki_dir_missing(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            idx = GlobalWikiIndexer(base_path=tmp / "nonexistent")
            results = await idx.search_wiki("test")
            assert len(results) == 0
        finally:
            shutil.rmtree(tmp)

    @pytest.mark.asyncio
    async def test_search_wiki_caches_results(self, idx: GlobalWikiIndexer) -> None:
        # First call
        results1 = await idx.search_wiki("测试")
        # Second call should use cache
        results2 = await idx.search_wiki("测试")
        assert results1 == results2


class TestGlobalWikiReadFile:
    @pytest.fixture
    def idx(self, temp_gwiki: Path) -> GlobalWikiIndexer:
        return GlobalWikiIndexer(base_path=temp_gwiki)

    @pytest.mark.asyncio
    async def test_read_file_returns_content(self, idx: GlobalWikiIndexer) -> None:
        path = idx._base / "wiki" / "概念" / "test_concept.md"
        content = await idx._read_file(path)
        assert "测试概念" in content
        assert "关键词test" in content

    @pytest.mark.asyncio
    async def test_read_file_returns_empty_for_nonexistent(self, idx: GlobalWikiIndexer) -> None:
        content = await idx._read_file(Path("/nonexistent/file.md"))
        assert content == ""

    @pytest.mark.asyncio
    async def test_read_file_caches(self, idx: GlobalWikiIndexer) -> None:
        path = idx._base / "wiki" / "概念" / "test_concept.md"
        await idx._read_file(path)
        assert str(path) in idx._cache


class TestGlobalWikiListAllEntries:
    @pytest.fixture
    def idx(self, temp_gwiki: Path) -> GlobalWikiIndexer:
        return GlobalWikiIndexer(base_path=temp_gwiki)

    @pytest.mark.asyncio
    async def test_list_all_returns_all_entries(self, idx: GlobalWikiIndexer) -> None:
        entries = await idx.list_all()
        assert len(entries) >= 3  # test_concept, test_project, another

    @pytest.mark.asyncio
    async def test_list_all_returns_correct_structure(self, idx: GlobalWikiIndexer) -> None:
        entries = await idx.list_all()
        assert len(entries) >= 1
        e = entries[0]
        assert "category" in e
        assert "file" in e
        assert "path" in e
        assert "source" in e

    @pytest.mark.asyncio
    async def test_list_all_empty_when_wiki_missing(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            idx = GlobalWikiIndexer(base_path=tmp / "nonexistent")
            entries = await idx.list_all()
            assert len(entries) == 0
        finally:
            shutil.rmtree(tmp)
