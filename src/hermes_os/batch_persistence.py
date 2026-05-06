"""Batch Persistence — SQLite persistence for BatchRunner pipeline runs.

Enables:
- Save pipeline run state to SQLite
- Resume interrupted runs
- Track progress across restarts

Uses TaskScheduler patterns:
- WAL mode for concurrency
- Lazy _get_db() initialization
- INSERT OR REPLACE upsert
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


@dataclass
class PipelineRun:
    """A persisted pipeline run record."""

    run_id: str
    artifact_id: str
    pipeline_name: str
    status: str  # "running" | "completed" | "failed"
    current_stage: str
    stages_completed: int
    total_stages: int
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata_json: str = "{}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "artifact_id": self.artifact_id,
            "pipeline_name": self.pipeline_name,
            "status": self.status,
            "current_stage": self.current_stage,
            "stages_completed": self.stages_completed,
            "total_stages": self.total_stages,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata_json": self.metadata_json,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> PipelineRun:
        return cls(
            run_id=row["run_id"],
            artifact_id=row["artifact_id"],
            pipeline_name=row["pipeline_name"],
            status=row["status"],
            current_stage=row["current_stage"],
            stages_completed=row["stages_completed"],
            total_stages=row["total_stages"],
            error=row.get("error"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata_json=row.get("metadata_json", "{}"),
        )


class BatchPersistence:
    """
    SQLite persistence for batch pipeline runs.

    Usage:
        persistence = BatchPersistence(db_path="/artifacts/batch_runs.db")
        await persistence.save_run(run)
        incomplete = await persistence.get_incomplete_runs()
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def _get_db(self) -> aiosqlite.Connection:
        """Get database connection, creating if needed."""
        if self._db is None:
            self._db = await aiosqlite.connect(str(self.db_path))
            self._db.row_factory = aiosqlite.Row
            await self._apply_pragmas(self._db)
            await self._create_table()
        return self._db

    async def _apply_pragmas(self, db: aiosqlite.Connection) -> None:
        """Enforce WAL mode for better concurrency."""
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")

    async def _create_table(self) -> None:
        """Create pipeline_runs table if not exists."""
        db = await self._get_db()
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL,
                pipeline_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                current_stage TEXT NOT NULL DEFAULT '',
                stages_completed INTEGER NOT NULL DEFAULT 0,
                total_stages INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_runs_artifact ON pipeline_runs(artifact_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_runs_status ON pipeline_runs(status)
        """)
        await db.commit()

    async def save_run(self, run: PipelineRun) -> None:
        """Save or update a pipeline run."""
        async with self._lock:
            db = await self._get_db()
            run.updated_at = datetime.now(UTC).isoformat()
            await db.execute(
                """
                INSERT OR REPLACE INTO pipeline_runs
                (run_id, artifact_id, pipeline_name, status, current_stage,
                 stages_completed, total_stages, error, created_at, updated_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    run.run_id,
                    run.artifact_id,
                    run.pipeline_name,
                    run.status,
                    run.current_stage,
                    run.stages_completed,
                    run.total_stages,
                    run.error,
                    run.created_at,
                    run.updated_at,
                    run.metadata_json,
                ),
            )
            await db.commit()
            logger.debug("Saved run %s: status=%s", run.run_id, run.status)

    async def get_run(self, run_id: str) -> PipelineRun | None:
        """Get a pipeline run by ID."""
        db = await self._get_db()
        async with db.execute(
            "SELECT * FROM pipeline_runs WHERE run_id = ?",
            (run_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return PipelineRun.from_row(dict(row))
        return None

    async def get_incomplete_runs(self) -> list[PipelineRun]:
        """Get all runs that are still 'running' (for resume)."""
        db = await self._get_db()
        runs = []
        async with db.execute(
            "SELECT * FROM pipeline_runs WHERE status = 'running' ORDER BY created_at ASC"
        ) as cursor:
            async for row in cursor:
                runs.append(PipelineRun.from_row(dict(row)))
        return runs

    async def get_runs_by_artifact(self, artifact_id: str) -> list[PipelineRun]:
        """Get all runs for a specific artifact."""
        db = await self._get_db()
        runs = []
        async with db.execute(
            "SELECT * FROM pipeline_runs WHERE artifact_id = ? ORDER BY created_at DESC",
            (artifact_id,),
        ) as cursor:
            async for row in cursor:
                runs.append(PipelineRun.from_row(dict(row)))
        return runs

    async def get_runs_by_status(self, status: str) -> list[PipelineRun]:
        """Get all runs with a specific status."""
        db = await self._get_db()
        runs = []
        async with db.execute(
            "SELECT * FROM pipeline_runs WHERE status = ? ORDER BY created_at DESC",
            (status,),
        ) as cursor:
            async for row in cursor:
                runs.append(PipelineRun.from_row(dict(row)))
        return runs

    async def update_run_status(
        self,
        run_id: str,
        status: str,
        current_stage: str = "",
        stages_completed: int = 0,
        error: str | None = None,
    ) -> None:
        """Update just the status fields of a run."""
        async with self._lock:
            db = await self._get_db()
            updated_at = datetime.now(UTC).isoformat()
            await db.execute(
                """
                UPDATE pipeline_runs
                SET status = ?, current_stage = ?, stages_completed = ?, error = ?, updated_at = ?
                WHERE run_id = ?
            """,
                (status, current_stage, stages_completed, error, updated_at, run_id),
            )
            await db.commit()

    async def delete_run(self, run_id: str) -> bool:
        """Delete a pipeline run."""
        async with self._lock:
            db = await self._get_db()
            cursor = await db.execute(
                "DELETE FROM pipeline_runs WHERE run_id = ?",
                (run_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_stats(self) -> dict[str, Any]:
        """Get aggregate statistics."""
        db = await self._get_db()
        stats = {}
        async with db.execute("""
            SELECT status, COUNT(*) as count FROM pipeline_runs GROUP BY status
        """) as cursor:
            async for row in cursor:
                stats[row["status"]] = row["count"]

        async with db.execute("SELECT COUNT(*) as total FROM pipeline_runs") as cursor:
            row = await cursor.fetchone()
            stats["total"] = row["total"] if row else 0

        return stats

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None
