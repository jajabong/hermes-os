"""Approval Tracker — 时效追踪 for government document approval flows.

Tracks 政务公文 (REQUEST type) approval lifecycle:
1. Submit for approval → PENDING status with 3 working-day deadline
2. Approver approves/rejects → APPROVED / REJECTED
3. Deadline approaches → reminder notification to approver
4. Deadline passes → auto-expire → notify submitter

Wired into ProactiveEngine via set_approval_tracker() for patrol checks.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum

import aiosqlite


class ApprovalStatus(str, Enum):
    PENDING = "pending"     # 待批复
    APPROVED = "approved"   # 已批准
    REJECTED = "rejected"  # 已拒绝
    EXPIRED = "expired"    # 已过期（超时未批复）


# 3 working days deadline
_DEFAULT_DEADLINE_DAYS = 3
# Remind 1 working day before deadline
_REMINDER_DAYS_BEFORE = 1


def _add_working_days(start: datetime, days: int) -> datetime:
    """Add N working days (skip weekends) to a date."""
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        # Skip Saturday (weekday 5) and Sunday (weekday 6)
        if current.weekday() < 5:
            added += 1
    return current


@dataclass
class ApprovalRecord:
    """A pending or completed approval record."""
    approval_id: str
    task_id: str
    doc_type: str          # DocType.value
    user_id: str           # 提交人
    approver_id: str       # 批复人
    status: ApprovalStatus
    title: str             # 文档标题（用于显示）
    created_at: datetime
    deadline_at: datetime  # deadline = created_at + 3 working days
    reminder_at: datetime  # reminder = deadline - 1 working day
    decided_at: datetime | None = None
    comment: str | None = None
    metadata: dict = field(default_factory=dict)


class ApprovalTracker:
    """
    DB-backed approval lifecycle tracker.

    Usage:
        tracker = ApprovalTracker(db_path="hermes_os.db")
        await tracker.initialize()

        approval_id = await tracker.submit_for_approval(
            task_id="task-123",
            doc_type="request",
            user_id="alice",
            approver_id="bob",
            title="关于申请经费的请示",
        )

        records = await tracker.get_pending_for_approver("bob")

        await tracker.approve(approval_id, approver_id="bob", comment="同意")
    """

    def __init__(self, db_path: str = "hermes_os.db") -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Initialize DB connection and create tables."""
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._apply_pragmas(self._db)
        await self._create_table()

    async def _apply_pragmas(self, db: aiosqlite.Connection) -> None:
        """Enforce WAL mode and normal synchronous for better concurrency."""
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")

    async def close(self) -> None:
        """Close DB connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def _get_db(self) -> aiosqlite.Connection:
        if self._db is None:
            await self.initialize()
        return self._db  # type: ignore[return-value]

    async def _create_table(self) -> None:
        db = await self._get_db()
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS approval_records (
                approval_id TEXT PRIMARY KEY,
                task_id TEXT,
                doc_type TEXT,
                user_id TEXT,
                approver_id TEXT,
                status TEXT DEFAULT 'pending',
                title TEXT,
                created_at TEXT,
                deadline_at TEXT,
                reminder_at TEXT,
                decided_at TEXT,
                comment TEXT,
                metadata TEXT
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_approvals_approver ON approval_records(approver_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_approvals_status ON approval_records(status)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_approvals_user ON approval_records(user_id)"
        )
        await db.commit()

    # -------------------------------------------------------------------------
    # Core CRUD
    # -------------------------------------------------------------------------

    async def submit_for_approval(
        self,
        task_id: str,
        doc_type: str,
        user_id: str,
        approver_id: str,
        title: str,
        deadline_days: int = _DEFAULT_DEADLINE_DAYS,
        metadata: dict | None = None,
    ) -> str:
        """
        Submit a document for approval. Returns approval_id.

        Computes deadline_at = created_at + deadline_days working days
        Computes reminder_at = deadline_at - 1 working day
        """
        db = await self._get_db()
        now = datetime.now(UTC)
        deadline_at = _add_working_days(now, deadline_days)
        reminder_at = _add_working_days(now, max(0, deadline_days - _REMINDER_DAYS_BEFORE))
        approval_id = str(uuid.uuid4())

        await db.execute(
            """
            INSERT INTO approval_records
            (approval_id, task_id, doc_type, user_id, approver_id, status, title,
             created_at, deadline_at, reminder_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                approval_id,
                task_id,
                doc_type,
                user_id,
                approver_id,
                ApprovalStatus.PENDING.value,
                title,
                now.isoformat(),
                deadline_at.isoformat(),
                reminder_at.isoformat(),
                json.dumps(metadata or {}),
            ),
        )
        await db.commit()
        return approval_id

    async def approve(
        self, approval_id: str, approver_id: str, comment: str | None = None
    ) -> ApprovalRecord | None:
        """Mark an approval as APPROVED. Verifies approver_id matches."""
        record = await self._get_record(approval_id)
        if not record:
            return None
        if record.approver_id != approver_id:
            return None
        if record.status != ApprovalStatus.PENDING:
            return None

        now = datetime.now(UTC)
        db = await self._get_db()
        await db.execute(
            """
            UPDATE approval_records
            SET status = ?, decided_at = ?, comment = ?
            WHERE approval_id = ?
            """,
            (ApprovalStatus.APPROVED.value, now.isoformat(), comment, approval_id),
        )
        await db.commit()
        return await self._get_record(approval_id)

    async def reject(
        self, approval_id: str, approver_id: str, comment: str | None = None
    ) -> ApprovalRecord | None:
        """Mark an approval as REJECTED. Verifies approver_id matches."""
        record = await self._get_record(approval_id)
        if not record:
            return None
        if record.approver_id != approver_id:
            return None
        if record.status != ApprovalStatus.PENDING:
            return None

        now = datetime.now(UTC)
        db = await self._get_db()
        await db.execute(
            """
            UPDATE approval_records
            SET status = ?, decided_at = ?, comment = ?
            WHERE approval_id = ?
            """,
            (ApprovalStatus.REJECTED.value, now.isoformat(), comment, approval_id),
        )
        await db.commit()
        return await self._get_record(approval_id)

    async def expire(self, approval_id: str) -> ApprovalRecord | None:
        """Mark a pending approval as EXPIRED (called by patrol)."""
        record = await self._get_record(approval_id)
        if not record or record.status != ApprovalStatus.PENDING:
            return None

        now = datetime.now(UTC)
        db = await self._get_db()
        await db.execute(
            """
            UPDATE approval_records
            SET status = ?, decided_at = ?
            WHERE approval_id = ?
            """,
            (ApprovalStatus.EXPIRED.value, now.isoformat(), approval_id),
        )
        await db.commit()
        return await self._get_record(approval_id)

    # -------------------------------------------------------------------------
    # Queries
    # -------------------------------------------------------------------------

    async def get_pending_for_approver(self, approver_id: str) -> list[ApprovalRecord]:
        """Return all PENDING approvals for a given approver."""
        db = await self._get_db()
        async with db.execute(
            """
            SELECT * FROM approval_records
            WHERE approver_id = ? AND status = ?
            ORDER BY created_at ASC
            """,
            (approver_id, ApprovalStatus.PENDING.value),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_record(row) for row in rows]

    async def get_pending_for_user(self, user_id: str) -> list[ApprovalRecord]:
        """Return all PENDING approvals submitted by a given user."""
        db = await self._get_db()
        async with db.execute(
            """
            SELECT * FROM approval_records
            WHERE user_id = ? AND status = ?
            ORDER BY created_at ASC
            """,
            (user_id, ApprovalStatus.PENDING.value),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_record(row) for row in rows]

    async def check_reminders(self) -> list[ApprovalRecord]:
        """
        Return PENDING approvals where reminder_at <= now (need to send reminder).
        Reminder is sent 1 working day before deadline.
        """
        db = await self._get_db()
        now = datetime.now(UTC).isoformat()
        async with db.execute(
            """
            SELECT * FROM approval_records
            WHERE status = ? AND reminder_at <= ?
            ORDER BY reminder_at ASC
            """,
            (ApprovalStatus.PENDING.value, now),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_record(row) for row in rows]

    async def check_expired(self) -> list[ApprovalRecord]:
        """Return PENDING approvals where deadline_at < now (need to expire)."""
        db = await self._get_db()
        now = datetime.now(UTC).isoformat()
        async with db.execute(
            """
            SELECT * FROM approval_records
            WHERE status = ? AND deadline_at < ?
            ORDER BY deadline_at ASC
            """,
            (ApprovalStatus.PENDING.value, now),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_record(row) for row in rows]

    async def get_record(self, approval_id: str) -> ApprovalRecord | None:
        """Get a single approval record by ID."""
        return await self._get_record(approval_id)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    async def _get_record(self, approval_id: str) -> ApprovalRecord | None:
        db = await self._get_db()
        async with db.execute(
            "SELECT * FROM approval_records WHERE approval_id = ?",
            (approval_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_record(row) if row else None

    def _row_to_record(self, row: aiosqlite.Row) -> ApprovalRecord | None:
        """Convert a DB row to an ApprovalRecord."""
        try:
            metadata_str = row["metadata"]
            metadata: dict = {}
            if metadata_str:
                try:
                    metadata = json.loads(metadata_str)
                except json.JSONDecodeError:
                    metadata = {}

            status = ApprovalStatus(row["status"])
        except ValueError:
            return None

        try:
            created_at = datetime.fromisoformat(row["created_at"])
        except (ValueError, TypeError):
            return None

        try:
            deadline_at = datetime.fromisoformat(row["deadline_at"])
        except (ValueError, TypeError):
            return None

        try:
            reminder_at = datetime.fromisoformat(row["reminder_at"]) if row["reminder_at"] else None
        except (ValueError, TypeError):
            reminder_at = None

        decided_at = None
        if row["decided_at"]:
            try:
                decided_at = datetime.fromisoformat(row["decided_at"])
            except (ValueError, TypeError):
                decided_at = None

        return ApprovalRecord(
            approval_id=row["approval_id"],
            task_id=row["task_id"],
            doc_type=row["doc_type"],
            user_id=row["user_id"],
            approver_id=row["approver_id"],
            status=status,
            title=row["title"],
            created_at=created_at,
            deadline_at=deadline_at,
            reminder_at=reminder_at,
            decided_at=decided_at,
            comment=row["comment"],
            metadata=metadata,
        )
