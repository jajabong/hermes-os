"""Tests for KnowledgeRouter — shared knowledge base search."""

import pytest

from hermes_os.knowledge_router import KnowledgeRouter


@pytest.fixture
async def kb() -> KnowledgeRouter:
    router = KnowledgeRouter(db_path=":memory:")
    await router.initialize()
    return router


class TestKnowledgeSchema:
    """Schema validation for knowledge_docs table."""

    @pytest.mark.asyncio
    async def test_knowledge_docs_table_exists(self, kb: KnowledgeRouter) -> None:
        cursor = await kb._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge_docs'"
        )
        row = await cursor.fetchone()
        assert row is not None, "knowledge_docs table should exist after initialize()"

    @pytest.mark.asyncio
    async def test_knowledge_docs_fts_index_exists(self, kb: KnowledgeRouter) -> None:
        """FTS5 virtual table is created for full-text search."""
        cursor = await kb._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge_docs_fts'"
        )
        row = await cursor.fetchone()
        assert row is not None, "knowledge_docs FTS virtual table should exist"


class TestAddDocument:
    """Tests for add_document()."""

    @pytest.mark.asyncio
    async def test_add_document_persists_and_searchable(self, kb: KnowledgeRouter) -> None:
        """Adding a document makes it retrievable via search."""
        await kb.add_document(
            doc_id="doc-001",
            team="engineering",
            title="Dev Onboarding",
            content="First day: set up your dev environment with `make setup`.",
        )
        results = await kb.search("dev environment setup", team="engineering")
        assert len(results) >= 1
        assert any("doc-001" in r.get("doc_id", "") for r in results)

    @pytest.mark.asyncio
    async def test_add_document_multiple_docs_searchable(self, kb: KnowledgeRouter) -> None:
        """Multiple documents can be added and searched independently."""
        await kb.add_document(
            doc_id="doc-a", team="eng", title="Git Workflow", content="Branch from main."
        )
        await kb.add_document(
            doc_id="doc-b", team="eng", title="Deploy Guide", content="Run `make deploy`."
        )
        results = await kb.search("deploy", team="eng")
        assert any("doc-b" in r.get("doc_id", "") for r in results)


class TestSearch:
    """Tests for search()."""

    @pytest.mark.asyncio
    async def test_search_returns_empty_when_no_match(self, kb: KnowledgeRouter) -> None:
        """Search with no matching documents returns empty list."""
        await kb.add_document(
            doc_id="x", team="t", title="T", content="Only matches specific terms."
        )
        results = await kb.search("zzz", team="t")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_is_team_scoped(self, kb: KnowledgeRouter) -> None:
        """Documents are only returned for the matching team."""
        await kb.add_document(
            doc_id="secret", team="alpha", title="Alpha Only", content="Alpha secret info."
        )
        await kb.add_document(
            doc_id="shared", team="beta", title="Beta Doc", content="Beta visible info."
        )
        results = await kb.search("info", team="alpha")
        doc_ids = [r.get("doc_id", "") for r in results]
        assert "secret" in doc_ids
        assert "shared" not in doc_ids

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, kb: KnowledgeRouter) -> None:
        """search() returns at most `limit` results."""
        for i in range(5):
            await kb.add_document(
                doc_id=f"doc-{i}", team="t", title=f"Title {i}", content="common term."
            )
        results = await kb.search("common term", team="t", limit=2)
        assert len(results) <= 2


class TestSearchResultFormat:
    """Output format validation for search()."""

    @pytest.mark.asyncio
    async def test_search_result_contains_required_fields(self, kb: KnowledgeRouter) -> None:
        """Each result dict has doc_id, title, content."""
        await kb.add_document(
            doc_id="fmt", team="x", title="My Title", content="The body content."
        )
        results = await kb.search("title", team="x")
        assert len(results) >= 1
        r = results[0]
        assert "doc_id" in r
        assert "title" in r
        assert "content" in r

    @pytest.mark.asyncio
    async def test_search_result_content_is_snippet(self, kb: KnowledgeRouter) -> None:
        """Returned content is a readable snippet, not raw FTS data."""
        long_content = "This is a long document " * 50
        await kb.add_document(
            doc_id="long", team="x", title="Long Doc", content=long_content
        )
        results = await kb.search("long document", team="x")
        assert len(results) >= 1
        assert len(results[0]["content"]) <= 300


class TestGetDocument:
    """Tests for get_document()."""

    @pytest.mark.asyncio
    async def test_get_document_returns_doc(self, kb: KnowledgeRouter) -> None:
        """get_document returns the full document by id."""
        await kb.add_document(
            doc_id="get-test", team="t", title="Get Doc", content="Full content here."
        )
        doc = await kb.get_document("get-test")
        assert doc is not None
        assert doc["doc_id"] == "get-test"
        assert doc["title"] == "Get Doc"
        assert doc["content"] == "Full content here."

    @pytest.mark.asyncio
    async def test_get_document_returns_none_for_missing(self, kb: KnowledgeRouter) -> None:
        """get_document returns None when doc_id does not exist."""
        doc = await kb.get_document("nonexistent")
        assert doc is None


class TestLifecycle:
    """Tests for close() lifecycle."""

    @pytest.mark.asyncio
    async def test_close_clears_connection(self, kb: KnowledgeRouter) -> None:
        """close() sets _db to None so subsequent operations re-initialize."""
        assert kb._db is not None
        await kb.close()
        assert kb._db is None
        assert kb._initialized is False
