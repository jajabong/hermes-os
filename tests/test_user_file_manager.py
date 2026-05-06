"""Tests for UserFileManager — per-user file storage."""

import pytest

from hermes_os.user_file_manager import _USER_FILES_BASE, UserFileManager


class TestUserFileManagerPaths:
    """Tests for directory path construction."""

    def test_user_dir(self) -> None:
        """User dir is at ~/.hermes/users/{user_id}/files."""
        mgr = UserFileManager()
        path = mgr._user_dir("alice")
        expected = _USER_FILES_BASE / "alice" / "files"
        assert path == expected

    def test_task_dir(self) -> None:
        """Task dir is at ~/.hermes/users/{user_id}/files/{task_id}."""
        mgr = UserFileManager()
        path = mgr._task_dir("alice", "t-001")
        expected = _USER_FILES_BASE / "alice" / "files" / "t-001"
        assert path == expected


class TestUserFileManagerCardStorage:
    """Tests for save_card / load_card."""

    @pytest.mark.asyncio
    async def test_save_card_creates_directory(self) -> None:
        """save_card creates the task directory if it doesn't exist."""
        mgr = UserFileManager()
        await mgr.save_card(
            user_id="alice",
            task_id="t-001",
            card_payload={"header": {"title": "Test"}},
            nl_summary="Test card",
        )
        task_dir = mgr._task_dir("alice", "t-001")
        assert task_dir.exists()

    @pytest.mark.asyncio
    async def test_save_and_load_card(self) -> None:
        """Card can be saved and loaded."""
        mgr = UserFileManager()
        await mgr.save_card(
            user_id="alice",
            task_id="t-001",
            card_payload={"header": {"title": "Test"}},
            nl_summary="Test card",
        )
        loaded = await mgr.load_card("alice", "t-001")
        assert loaded is not None
        assert loaded["card"]["header"]["title"] == "Test"
        assert loaded["nl_summary"] == "Test card"

    @pytest.mark.asyncio
    async def test_load_nonexistent_card_returns_none(self) -> None:
        """load_card returns None for unknown task."""
        mgr = UserFileManager()
        result = await mgr.load_card("alice", "nonexistent")
        assert result is None


class TestUserFileManagerResultStorage:
    """Tests for save_result / load_result."""

    @pytest.mark.asyncio
    async def test_save_and_load_result(self) -> None:
        """Result can be saved and loaded."""
        mgr = UserFileManager()
        await mgr.save_result(
            user_id="alice",
            task_id="t-001",
            result="Task completed successfully",
            metadata={"duration_sec": 120},
        )
        loaded = await mgr.load_result("alice", "t-001")
        assert loaded == "Task completed successfully"

    @pytest.mark.asyncio
    async def test_load_nonexistent_result_returns_none(self) -> None:
        """load_result returns None for unknown task."""
        mgr = UserFileManager()
        result = await mgr.load_result("alice", "nonexistent")
        assert result is None


class TestUserFileManagerTaskListing:
    """Tests for list_tasks."""

    @pytest.mark.asyncio
    async def test_list_tasks_empty_user(self) -> None:
        """list_tasks returns empty list for user with no tasks."""
        mgr = UserFileManager()
        tasks = await mgr.list_tasks("newuser")
        assert tasks == []

    @pytest.mark.asyncio
    async def test_list_tasks_returns_task_ids(self) -> None:
        """list_tasks returns all task IDs for a user."""
        mgr = UserFileManager()
        await mgr.save_card("alice", "t-001", {"card": {}}, "c1")
        await mgr.save_card("alice", "t-002", {"card": {}}, "c2")
        tasks = await mgr.list_tasks("alice")
        assert set(tasks) == {"t-001", "t-002"}


class TestUserFileManagerDeleteTask:
    """Tests for delete_task."""

    @pytest.mark.asyncio
    async def test_delete_existing_task(self) -> None:
        """delete_task removes the task directory."""
        mgr = UserFileManager()
        await mgr.save_card("alice", "t-001", {"card": {}}, "c1")
        result = await mgr.delete_task("alice", "t-001")
        assert result is True
        assert not mgr._task_dir("alice", "t-001").exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_task_returns_false(self) -> None:
        """delete_task returns False for unknown task."""
        mgr = UserFileManager()
        result = await mgr.delete_task("alice", "nonexistent")
        assert result is False
