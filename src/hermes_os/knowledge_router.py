"""Shared knowledge base router — team-scoped full-text search via SQLite FTS5."""

from __future__ import annotations

import aiosqlite


class KnowledgeRouter:
    """Team-scoped shared knowledge search backed by SQLite FTS5.

    No external dependencies — suitable for MVP. Uses a standalone FTS5 virtual
    table so the index is fully self-contained and not tied to content table rowids.
    """

    def __init__(self, db_path: str = "hermes_knowledge.db") -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._initialized: bool = False

    async def _get_db(self) -> aiosqlite.Connection:
        if self._db is None:
            self._db = await aiosqlite.connect(self.db_path)
            self._db.row_factory = aiosqlite.Row
        return self._db

    async def initialize(self) -> None:
        """Create tables. Idempotent — safe to call multiple times."""
        if self._initialized:
            return
        db = await self._get_db()
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_docs (
                doc_id TEXT PRIMARY KEY,
                team TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_docs_fts "
            "USING fts5(doc_id, title, content)"
        )
        await db.commit()
        self._initialized = True

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
        self._initialized = False

    async def add_document(
        self, doc_id: str, team: str, title: str, content: str
    ) -> None:
        """Store or replace a document for a team."""
        await self.initialize()
        db = await self._get_db()
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        await db.execute(
            """
            INSERT OR REPLACE INTO knowledge_docs (doc_id, team, title, content, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (doc_id, team, title, content, now),
        )
        await db.execute(
            "INSERT OR REPLACE INTO knowledge_docs_fts(doc_id, title, content) VALUES (?, ?, ?)",
            (doc_id, title, content),
        )
        await db.commit()

    async def search(
        self, query: str, team: str, limit: int = 5
    ) -> list[dict]:
        """Return up to `limit` matching documents for a team."""
        await self.initialize()
        db = await self._get_db()
        async with db.execute(
            """
            SELECT k.doc_id, k.title, k.content
            FROM knowledge_docs k
            JOIN knowledge_docs_fts fts ON k.doc_id = fts.doc_id
            WHERE fts.knowledge_docs_fts MATCH ?
              AND k.team = ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, team, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {"doc_id": r["doc_id"], "title": r["title"], "content": r["content"][:300]}
                for r in rows
            ]

    async def get_document(self, doc_id: str) -> dict | None:
        """Retrieve a single document by id, or None if not found."""
        await self.initialize()
        db = await self._get_db()
        async with db.execute(
            "SELECT doc_id, team, title, content FROM knowledge_docs WHERE doc_id = ?",
            (doc_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
