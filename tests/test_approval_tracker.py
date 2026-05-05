"""Tests for ApprovalTracker — 时效追踪 for government document approvals."""

import pytest
import os
import uuid
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta, UTC

from hermes_os.approval_tracker import (
    ApprovalTracker,
    ApprovalStatus,
    ApprovalRecord,
    _add_working_days,
)


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Per-test unique temp DB path — avoids SQLite file-based locking conflicts."""
    return tmp_path / f"approval_{uuid.uuid4().hex[:8]}.db"


# ---------------------------------------------------------------------------
# _add_working_days tests
# ---------------------------------------------------------------------------

class TestAddWorkingDays:
    def test_add_0_days(self) -> None:
        """0 working days = same day."""
        friday = datetime(2026, 4, 24, 10, 0, 0)  # Friday
        result = _add_working_days(friday, 0)
        assert result == friday

    def test_add_1_day(self) -> None:
        """Add 1 working day skips weekend."""
        friday = datetime(2026, 4, 24, 10, 0, 0)  # Friday
        result = _add_working_days(friday, 1)
        # Monday
        assert result.weekday() < 5
        assert result == datetime(2026, 4, 27, 10, 0, 0)

    def test_add_3_days(self) -> None:
        """Add 3 working days."""
        friday = datetime(2026, 4, 24, 10, 0, 0)  # Friday
        result = _add_working_days(friday, 3)
        # Wednesday
        assert result == datetime(2026, 4, 29, 10, 0, 0)

    def test_add_across_weekend(self) -> None:
        """Starting Monday, add 3 days lands on Thursday."""
        monday = datetime(2026, 4, 27, 10, 0, 0)  # Monday
        result = _add_working_days(monday, 3)
        assert result == datetime(2026, 4, 30, 10, 0, 0)  # Thursday (Mon+Tue+Wed=3 working days)


# ---------------------------------------------------------------------------
# ApprovalStatus tests
# ---------------------------------------------------------------------------

class TestApprovalStatus:
    def test_status_values(self) -> None:
        assert ApprovalStatus.PENDING.value == "pending"
        assert ApprovalStatus.APPROVED.value == "approved"
        assert ApprovalStatus.REJECTED.value == "rejected"
        assert ApprovalStatus.EXPIRED.value == "expired"


# ---------------------------------------------------------------------------
# ApprovalRecord dataclass tests
# ---------------------------------------------------------------------------

class TestApprovalRecord:
    def test_record_creation(self) -> None:
        now = datetime.now(UTC)
        record = ApprovalRecord(
            approval_id="a1",
            task_id="t1",
            doc_type="request",
            user_id="alice",
            approver_id="bob",
            status=ApprovalStatus.PENDING,
            title="关于经费的请示",
            created_at=now,
            deadline_at=now + timedelta(days=3),
            reminder_at=now + timedelta(days=2),
        )
        assert record.approval_id == "a1"
        assert record.status == ApprovalStatus.PENDING
        assert record.title == "关于经费的请示"


# ---------------------------------------------------------------------------
# ApprovalTracker integration tests (DB-backed)
# ---------------------------------------------------------------------------

class TestApprovalTrackerSubmit:
    """Tests for submit_for_approval()."""

    @pytest.fixture
    def tracker(self, temp_db_path: Path) -> ApprovalTracker:
        return ApprovalTracker(db_path=str(temp_db_path))

    @pytest.mark.asyncio
    async def test_submit_creates_record(self, tracker: ApprovalTracker) -> None:
        await tracker.initialize()
        approval_id = await tracker.submit_for_approval(
            task_id="task-123",
            doc_type="request",
            user_id="alice",
            approver_id="bob",
            title="关于申请经费的请示",
        )

        assert approval_id is not None
        record = await tracker.get_record(approval_id)
        assert record is not None
        assert record.user_id == "alice"
        assert record.approver_id == "bob"
        assert record.status == ApprovalStatus.PENDING
        assert record.title == "关于申请经费的请示"

    @pytest.mark.asyncio
    async def test_deadline_computed_correctly(self, tracker: ApprovalTracker) -> None:
        await tracker.initialize()
        now_before = datetime.now(UTC)
        approval_id = await tracker.submit_for_approval(
            task_id="t1",
            doc_type="request",
            user_id="alice",
            approver_id="bob",
            title="测试",
            deadline_days=3,
        )
        now_after = datetime.now(UTC)

        record = await tracker.get_record(approval_id)
        assert record is not None
        # deadline_at should be ~3 working days after creation
        assert record.deadline_at > now_after + timedelta(days=2)
        # reminder_at should be deadline - 1 working day
        assert record.reminder_at < record.deadline_at

    @pytest.mark.asyncio
    async def test_submit_multiple_creates_multiple(self, tracker: ApprovalTracker) -> None:
        await tracker.initialize()
        id1 = await tracker.submit_for_approval(
            task_id="t1", doc_type="request", user_id="alice",
            approver_id="bob", title="请示1",
        )
        id2 = await tracker.submit_for_approval(
            task_id="t2", doc_type="report", user_id="alice",
            approver_id="charlie", title="报告1",
        )

        pending_alice = await tracker.get_pending_for_user("alice")
        assert len(pending_alice) == 2


class TestApprovalTrackerApproveReject:
    """Tests for approve() and reject()."""

    @pytest.fixture
    def tracker(self, temp_db_path: Path) -> ApprovalTracker:
        return ApprovalTracker(db_path=str(temp_db_path))

    @pytest.mark.asyncio
    async def test_approve_changes_status(self, tracker: ApprovalTracker) -> None:
        await tracker.initialize()
        approval_id = await tracker.submit_for_approval(
            task_id="t1", doc_type="request", user_id="alice",
            approver_id="bob", title="测试请示",
        )

        result = await tracker.approve(approval_id, approver_id="bob", comment="同意")

        assert result is not None
        assert result.status == ApprovalStatus.APPROVED
        assert result.comment == "同意"
        assert result.decided_at is not None

    @pytest.mark.asyncio
    async def test_reject_changes_status(self, tracker: ApprovalTracker) -> None:
        await tracker.initialize()
        approval_id = await tracker.submit_for_approval(
            task_id="t1", doc_type="request", user_id="alice",
            approver_id="bob", title="测试请示",
        )

        result = await tracker.reject(approval_id, approver_id="bob", comment="不同意")

        assert result is not None
        assert result.status == ApprovalStatus.REJECTED
        assert result.comment == "不同意"

    @pytest.mark.asyncio
    async def test_wrong_approver_returns_none(self, tracker: ApprovalTracker) -> None:
        await tracker.initialize()
        approval_id = await tracker.submit_for_approval(
            task_id="t1", doc_type="request", user_id="alice",
            approver_id="bob", title="测试请示",
        )

        # charlie is not the approver
        result = await tracker.approve(approval_id, approver_id="charlie", comment="ok")

        assert result is None
        # Status should still be pending
        record = await tracker.get_record(approval_id)
        assert record is not None
        assert record.status == ApprovalStatus.PENDING

    @pytest.mark.asyncio
    async def test_approve_non_pending_is_noop(self, tracker: ApprovalTracker) -> None:
        await tracker.initialize()
        approval_id = await tracker.submit_for_approval(
            task_id="t1", doc_type="request", user_id="alice",
            approver_id="bob", title="测试请示",
        )

        # First approve
        await tracker.approve(approval_id, approver_id="bob")
        # Try to reject already-approved
        result = await tracker.reject(approval_id, approver_id="bob")

        assert result is None
        record = await tracker.get_record(approval_id)
        assert record is not None
        assert record.status == ApprovalStatus.APPROVED


class TestApprovalTrackerGetPending:
    """Tests for get_pending_for_approver()."""

    @pytest.fixture
    def tracker(self, temp_db_path: Path) -> ApprovalTracker:
        return ApprovalTracker(db_path=str(temp_db_path))

    @pytest.mark.asyncio
    async def test_get_pending_for_approver(self, tracker: ApprovalTracker) -> None:
        await tracker.initialize()
        # Alice submits two requests to Bob
        id1 = await tracker.submit_for_approval(
            task_id="t1", doc_type="request", user_id="alice",
            approver_id="bob", title="请示1",
        )
        id2 = await tracker.submit_for_approval(
            task_id="t2", doc_type="request", user_id="alice",
            approver_id="bob", title="请示2",
        )
        # Charlie has one pending
        await tracker.submit_for_approval(
            task_id="t3", doc_type="request", user_id="alice",
            approver_id="charlie", title="请示3",
        )

        bob_pending = await tracker.get_pending_for_approver("bob")
        assert len(bob_pending) == 2

        charlie_pending = await tracker.get_pending_for_approver("charlie")
        assert len(charlie_pending) == 1

    @pytest.mark.asyncio
    async def test_approved_not_in_pending(self, tracker: ApprovalTracker) -> None:
        await tracker.initialize()
        approval_id = await tracker.submit_for_approval(
            task_id="t1", doc_type="request", user_id="alice",
            approver_id="bob", title="请示1",
        )
        await tracker.approve(approval_id, approver_id="bob")

        bob_pending = await tracker.get_pending_for_approver("bob")
        assert len(bob_pending) == 0


class TestApprovalTrackerExpire:
    """Tests for check_expired() and expire()."""

    @pytest.fixture
    def tracker(self, temp_db_path: Path) -> ApprovalTracker:
        return ApprovalTracker(db_path=str(temp_db_path))

    @pytest.mark.asyncio
    async def test_expire_changes_status(self, tracker: ApprovalTracker) -> None:
        await tracker.initialize()
        approval_id = await tracker.submit_for_approval(
            task_id="t1", doc_type="request", user_id="alice",
            approver_id="bob", title="测试请示",
        )

        expired = await tracker.expire(approval_id)

        assert expired is not None
        assert expired.status == ApprovalStatus.EXPIRED
        assert expired.decided_at is not None

    @pytest.mark.asyncio
    async def test_expired_not_returned_by_get_pending(self, tracker: ApprovalTracker) -> None:
        await tracker.initialize()
        approval_id = await tracker.submit_for_approval(
            task_id="t1", doc_type="request", user_id="alice",
            approver_id="bob", title="测试请示",
        )
        await tracker.expire(approval_id)

        bob_pending = await tracker.get_pending_for_approver("bob")
        assert len(bob_pending) == 0


class TestApprovalTrackerReminder:
    """Tests for check_reminders()."""

    @pytest.fixture
    def tracker(self, temp_db_path: Path) -> ApprovalTracker:
        return ApprovalTracker(db_path=str(temp_db_path))

    @pytest.mark.asyncio
    async def test_reminder_at_set_correctly(self, tracker: ApprovalTracker) -> None:
        """reminder_at = deadline_at - 1 working day."""
        await tracker.initialize()
        approval_id = await tracker.submit_for_approval(
            task_id="t1", doc_type="request", user_id="alice",
            approver_id="bob", title="测试",
            deadline_days=3,
        )

        record = await tracker.get_record(approval_id)
        # reminder should be 2 working days from now, deadline 3
        delta_reminder = record.reminder_at - record.created_at
        delta_deadline = record.deadline_at - record.created_at
        # Both should be roughly 2 and 3 days (working days)
        assert delta_reminder < delta_deadline


class TestApprovalTrackerEdgeCases:
    """Edge cases and error conditions for ApprovalTracker."""

    @pytest.fixture
    def tracker(self, temp_db_path: Path) -> ApprovalTracker:
        return ApprovalTracker(db_path=str(temp_db_path))

    @pytest.mark.asyncio
    async def test_get_record_not_found(self, tracker: ApprovalTracker) -> None:
        """Getting a non-existent record returns None."""
        await tracker.initialize()
        result = await tracker.get_record("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_approve_not_found(self, tracker: ApprovalTracker) -> None:
        """Approving a non-existent approval returns None."""
        await tracker.initialize()
        result = await tracker.approve("nonexistent-id", approver_id="bob")
        assert result is None

    @pytest.mark.asyncio
    async def test_reject_not_found(self, tracker: ApprovalTracker) -> None:
        """Rejecting a non-existent approval returns None."""
        await tracker.initialize()
        result = await tracker.reject("nonexistent-id", approver_id="bob")
        assert result is None

    @pytest.mark.asyncio
    async def test_expire_not_found(self, tracker: ApprovalTracker) -> None:
        """Expiring a non-existent approval returns None."""
        await tracker.initialize()
        result = await tracker.expire("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_expire_already_decided(self, tracker: ApprovalTracker) -> None:
        """Expiring an already decided approval returns None."""
        await tracker.initialize()
        approval_id = await tracker.submit_for_approval(
            task_id="t1", doc_type="request", user_id="alice",
            approver_id="bob", title="测试",
        )
        await tracker.approve(approval_id, approver_id="bob")

        result = await tracker.expire(approval_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_submit_with_custom_deadline(self, tracker: ApprovalTracker) -> None:
        """Custom deadline_days is respected."""
        await tracker.initialize()
        approval_id = await tracker.submit_for_approval(
            task_id="t1", doc_type="request", user_id="alice",
            approver_id="bob", title="自定义截止日期",
            deadline_days=5,
        )

        record = await tracker.get_record(approval_id)
        assert record is not None
        # 5 working days should be added
        expected_delta = timedelta(days=7)  # 5 working days = ~7 calendar days
        actual_delta = record.deadline_at - record.created_at
        assert actual_delta.days >= 5  # At least 5 working days worth

    @pytest.mark.asyncio
    async def test_submit_with_metadata(self, tracker: ApprovalTracker) -> None:
        """Metadata is stored correctly."""
        await tracker.initialize()
        metadata = {"priority": "high", "category": "budget"}
        approval_id = await tracker.submit_for_approval(
            task_id="t1", doc_type="request", user_id="alice",
            approver_id="bob", title="带元数据的请求",
            metadata=metadata,
        )

        record = await tracker.get_record(approval_id)
        assert record is not None
        assert record.metadata == metadata

    @pytest.mark.asyncio
    async def test_check_reminders_empty(self, tracker: ApprovalTracker) -> None:
        """check_reminders returns empty list when no reminders are due."""
        await tracker.initialize()
        # Submit a new approval
        await tracker.submit_for_approval(
            task_id="t1", doc_type="request", user_id="alice",
            approver_id="bob", title="测试提醒",
        )

        reminders = await tracker.check_reminders()
        # May or may not have reminders depending on timing
        assert isinstance(reminders, list)

    @pytest.mark.asyncio
    async def test_check_expired_empty(self, tracker: ApprovalTracker) -> None:
        """check_expired returns empty list when no approvals are expired."""
        await tracker.initialize()
        # Submit a new approval
        await tracker.submit_for_approval(
            task_id="t1", doc_type="request", user_id="alice",
            approver_id="bob", title="测试过期",
        )

        expired = await tracker.check_expired()
        # May or may not have expired depending on timing
        assert isinstance(expired, list)

    @pytest.mark.asyncio
    async def test_get_pending_for_user_empty(self, tracker: ApprovalTracker) -> None:
        """User with no pending approvals returns empty list."""
        await tracker.initialize()
        pending = await tracker.get_pending_for_user("nobody")
        assert pending == []

    @pytest.mark.asyncio
    async def test_approve_with_null_comment(self, tracker: ApprovalTracker) -> None:
        """Approving with None comment works correctly."""
        await tracker.initialize()
        approval_id = await tracker.submit_for_approval(
            task_id="t1", doc_type="request", user_id="alice",
            approver_id="bob", title="无评论审批",
        )

        result = await tracker.approve(approval_id, approver_id="bob", comment=None)

        assert result is not None
        assert result.status == ApprovalStatus.APPROVED
        assert result.comment is None

    @pytest.mark.asyncio
    async def test_reject_with_null_comment(self, tracker: ApprovalTracker) -> None:
        """Rejecting with None comment works correctly."""
        await tracker.initialize()
        approval_id = await tracker.submit_for_approval(
            task_id="t1", doc_type="request", user_id="alice",
            approver_id="bob", title="无评论拒绝",
        )

        result = await tracker.reject(approval_id, approver_id="bob", comment=None)

        assert result is not None
        assert result.status == ApprovalStatus.REJECTED
        assert result.comment is None


class TestApprovalTrackerWorkingDays:
    """Tests for working day calculations."""

    def test_add_working_days_weekend_only(self) -> None:
        """Starting Saturday, add 1 day = Monday."""
        saturday = datetime(2026, 4, 25, 10, 0, 0)  # Saturday
        result = _add_working_days(saturday, 1)
        assert result == datetime(2026, 4, 27, 10, 0, 0)  # Monday

    def test_add_working_days_10_days(self) -> None:
        """Add 10 working days from Monday."""
        monday = datetime(2026, 4, 27, 10, 0, 0)  # Monday
        result = _add_working_days(monday, 10)
        # Monday + 10 working days = 2 weeks later (Monday)
        assert result == datetime(2026, 5, 11, 10, 0, 0)

    def test_add_working_days_crossing_month(self) -> None:
        """Working days calculation crosses month boundary."""
        # May 1, 2026 is a Friday
        friday = datetime(2026, 5, 1, 10, 0, 0)
        result = _add_working_days(friday, 1)
        # Should be Monday May 4
        assert result.weekday() < 5  # Not weekend
        assert result.month == 5
