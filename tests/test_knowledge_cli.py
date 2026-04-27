"""Tests for KnowledgeCLI — admin CRUD for the shared knowledge base."""

import pytest

from hermes_os.knowledge_cli import KnowledgeCLI


@pytest.fixture
async def cli() -> KnowledgeCLI:
    c = KnowledgeCLI(db_path=":memory:")
    await c.initialize()
    return c


class TestAddDocument:
    """Tests for cli.add()."""

    @pytest.mark.asyncio
    async def test_add_document_succeeds(self, cli: KnowledgeCLI) -> None:
        """add() stores a document and returns it with doc_id."""
        doc = await cli.add(
            doc_id="onboarding-001",
            team="engineering",
            title="Engineering Onboarding",
            content="Step 1: run `make setup`.",
        )
        assert doc["doc_id"] == "onboarding-001"
        assert doc["team"] == "engineering"
        assert doc["title"] == "Engineering Onboarding"

    @pytest.mark.asyncio
    async def test_add_document_is_idempotent(self, cli: KnowledgeCLI) -> None:
        """add() replaces an existing document with the same doc_id."""
        await cli.add("doc-x", team="t", title="V1", content="Version 1")
        doc = await cli.add("doc-x", team="t", title="V2", content="Version 2")

        assert doc["title"] == "V2"
        assert doc["content"] == "Version 2"

        all_docs = await cli.list_docs(team="t")
        titles = [d["title"] for d in all_docs]
        assert titles.count("V2") == 1  # no duplicates


class TestDeleteDocument:
    """Tests for cli.delete()."""

    @pytest.mark.asyncio
    async def test_delete_removes_document(self, cli: KnowledgeCLI) -> None:
        """delete() removes the document by doc_id."""
        await cli.add("del-doc", team="t", title="Delete Me", content="Gone.")
        await cli.delete("del-doc")

        doc = await cli.get("del-doc")
        assert doc is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_is_noop(self, cli: KnowledgeCLI) -> None:
        """delete() does not raise for a missing doc_id."""
        await cli.delete("ghost-doc")  # must not raise


class TestListDocs:
    """Tests for cli.list_docs()."""

    @pytest.mark.asyncio
    async def test_list_docs_returns_team_docs(self, cli: KnowledgeCLI) -> None:
        """list_docs() returns all documents for a team."""
        await cli.add("a", team="alpha", title="A", content="Alpha doc.")
        await cli.add("b", team="alpha", title="B", content="Alpha doc 2.")
        await cli.add("c", team="beta", title="C", content="Beta doc.")

        alpha_docs = await cli.list_docs(team="alpha")
        doc_ids = [d["doc_id"] for d in alpha_docs]

        assert "a" in doc_ids
        assert "b" in doc_ids
        assert "c" not in doc_ids

    @pytest.mark.asyncio
    async def test_list_docs_empty_team(self, cli: KnowledgeCLI) -> None:
        """list_docs() returns [] for a team with no documents."""
        docs = await cli.list_docs(team="empty-team")
        assert docs == []


class TestGetDocument:
    """Tests for cli.get()."""

    @pytest.mark.asyncio
    async def test_get_returns_document(self, cli: KnowledgeCLI) -> None:
        """get() returns the full document by doc_id."""
        await cli.add("get-test", team="t", title="Get Doc", content="Full content.")
        doc = await cli.get("get-test")

        assert doc is not None
        assert doc["doc_id"] == "get-test"
        assert doc["title"] == "Get Doc"
        assert doc["content"] == "Full content."

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, cli: KnowledgeCLI) -> None:
        """get() returns None for a nonexistent doc_id."""
        doc = await cli.get("nonexistent")
        assert doc is None


class TestSearchDocs:
    """Tests for cli.search()."""

    @pytest.mark.asyncio
    async def test_search_returns_matches(self, cli: KnowledgeCLI) -> None:
        """search() returns matching documents for a team."""
        await cli.add("s1", team="eng", title="Git Guide", content="Git workflow steps.")
        await cli.add("s2", team="eng", title="Deploy", content="How to deploy.")
        await cli.add("s3", team="eng", title="Git Branching", content="Branching model.")

        results = await cli.search("git", team="eng")
        doc_ids = [r["doc_id"] for r in results]
        assert "s1" in doc_ids
        assert "s3" in doc_ids
        assert "s2" not in doc_ids

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, cli: KnowledgeCLI) -> None:
        """search() respects the limit parameter."""
        for i in range(5):
            await cli.add(f"limit-{i}", team="t", title=f"Term {i}", content="common term.")

        results = await cli.search("common term", team="t", limit=2)
        assert len(results) <= 2


class TestBulkImport:
    """Tests for cli.import_docs()."""

    @pytest.mark.asyncio
    async def test_import_docs_adds_all(self, cli: KnowledgeCLI) -> None:
        """import_docs() adds all documents and returns the count."""
        docs = [
            {"doc_id": "imp-1", "team": "alpha", "title": "Import 1", "content": "First."},
            {"doc_id": "imp-2", "team": "alpha", "title": "Import 2", "content": "Second."},
        ]
        count = await cli.import_docs(docs)
        assert count == 2

        all_docs = await cli.list_docs(team="alpha")
        assert len(all_docs) == 2

    @pytest.mark.asyncio
    async def test_import_docs_with_markdown(self, cli: KnowledgeCLI) -> None:
        """import_docs() accepts markdown strings (title inferred from first heading)."""
        docs = [
            {
                "doc_id": "md-1",
                "team": "t",
                "title": "# Deploy Guide\n\nRun `make deploy`.",
                "content": "# Deploy Guide\n\nRun `make deploy`.",
            },
        ]
        count = await cli.import_docs(docs)
        assert count == 1
        doc = await cli.get("md-1")
        assert doc is not None
        assert "Deploy Guide" in doc["title"]

    @pytest.mark.asyncio
    async def test_import_docs_skips_invalid(self, cli: KnowledgeCLI) -> None:
        """import_docs() skips documents missing required fields."""
        docs = [
            {"doc_id": "valid", "team": "t", "title": "Valid", "content": "OK."},
            {"doc_id": "missing-content", "team": "t", "title": "Incomplete"},  # no content
            {"doc_id": "missing-team", "title": "No Team", "content": "OK."},
        ]
        count = await cli.import_docs(docs)
        assert count == 1


class TestLifecycle:
    """Tests for close() lifecycle."""

    @pytest.mark.asyncio
    async def test_close_clears_connection(self, cli: KnowledgeCLI) -> None:
        """close() delegates to the router's close()."""
        await cli.close()  # must not raise
