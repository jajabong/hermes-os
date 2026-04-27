"""KnowledgeCLI — admin CRUD interface for the shared knowledge base."""

from __future__ import annotations

from hermes_os.knowledge_router import KnowledgeRouter


class KnowledgeCLI:
    """High-level admin interface for managing team knowledge documents.

    Wraps KnowledgeRouter to expose a richer API: idempotent add,
    bulk import with markdown inference, and typed result dicts.
    """

    def __init__(self, db_path: str = "hermes_knowledge.db") -> None:
        self._router = KnowledgeRouter(db_path=db_path)

    async def initialize(self) -> None:
        await self._router.initialize()

    async def close(self) -> None:
        await self._router.close()

    async def add(
        self, doc_id: str, team: str, title: str, content: str
    ) -> dict:
        """Store or replace a document. Returns the stored document dict."""
        await self._router.add_document(doc_id=doc_id, team=team, title=title, content=content)
        return {"doc_id": doc_id, "team": team, "title": title, "content": content}

    async def delete(self, doc_id: str) -> None:
        """Delete a document by doc_id. No-op if missing."""
        await self._router.delete_document(doc_id)

    async def get(self, doc_id: str) -> dict | None:
        """Retrieve a document by doc_id, or None if not found."""
        return await self._router.get_document(doc_id)

    async def list_docs(self, team: str) -> list[dict]:
        """Return all documents for a team."""
        return await self._router.list_documents(team=team)

    async def search(
        self, query: str, team: str, limit: int = 5
    ) -> list[dict]:
        """Full-text search across a team's documents."""
        return await self._router.search(query=query, team=team, limit=limit)

    async def import_docs(self, docs: list[dict]) -> int:
        """Bulk-import a list of documents. Returns the number actually added.

        Skips documents missing required fields (doc_id, team, title, content).
        """
        count = 0
        for doc in docs:
            if not all(k in doc for k in ("doc_id", "team", "title", "content")):
                continue
            await self.add(
                doc_id=doc["doc_id"],
                team=doc["team"],
                title=doc["title"],
                content=doc["content"],
            )
            count += 1
        return count
