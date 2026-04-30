"""UserFileManager — per-user file storage for Hermes OS.

Each user has a directory tree:
  ~/.hermes/users/{user_id}/
  ├── files/
  │   └── {task_id}/
  │       ├── card.json        # outbound Feishu card payload
  │       ├── result.md        # task execution result
  │       └── context.json     # conversation context at creation time
  └── metadata/
      └── user_preferences.json

All operations are async. Directory is created lazily on first write.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_USER_FILES_BASE = Path.home() / ".hermes" / "users"


class UserFileManager:
    """
    Manages per-user file storage.

    File hierarchy:
      ~/.hermes/users/{user_id}/files/{task_id}/
    """

    def __init__(self) -> None:
        self._base = _USER_FILES_BASE

    # -------------------------------------------------------------------------
    # Path helpers
    # -------------------------------------------------------------------------

    def _user_dir(self, user_id: str) -> Path:
        return self._base / user_id / "files"

    def _task_dir(self, user_id: str, task_id: str) -> Path:
        return self._user_dir(user_id) / task_id

    # -------------------------------------------------------------------------
    # Card storage
    # -------------------------------------------------------------------------

    async def save_card(
        self,
        user_id: str,
        task_id: str,
        card_payload: dict[str, Any],
        nl_summary: str | None = None,
    ) -> Path:
        """
        Save a Feishu card payload to user's task directory.

        Creates directory structure if needed.

        Returns path to the saved card.json.
        """
        task_dir = self._task_dir(user_id, task_id)
        task_dir.mkdir(parents=True, exist_ok=True)

        card_path = task_dir / "card.json"
        record = {
            "card": card_payload,
            "nl_summary": nl_summary,
            "task_id": task_id,
        }
        await self._write_json(card_path, record)
        logger.debug("Saved card for user %s task %s", user_id, task_id)
        return card_path

    async def load_card(self, user_id: str, task_id: str) -> dict | None:
        """Load card payload for a task, or None if not found."""
        card_path = self._task_dir(user_id, task_id) / "card.json"
        if not card_path.exists():
            return None
        return await self._read_json(card_path)

    # -------------------------------------------------------------------------
    # Result storage
    # -------------------------------------------------------------------------

    async def save_result(
        self,
        user_id: str,
        task_id: str,
        result: str,
        metadata: dict | None = None,
    ) -> Path:
        """Save task execution result to user's task directory."""
        task_dir = self._task_dir(user_id, task_id)
        task_dir.mkdir(parents=True, exist_ok=True)

        result_path = task_dir / "result.md"
        record = {
            "result": result,
            "metadata": metadata or {},
        }
        await self._write_text(result_path, result)
        logger.debug("Saved result for user %s task %s", user_id, task_id)
        return result_path

    async def load_result(self, user_id: str, task_id: str) -> str | None:
        """Load result for a task, or None."""
        result_path = self._task_dir(user_id, task_id) / "result.md"
        if not result_path.exists():
            return None
        return await self._read_text(result_path)

    # -------------------------------------------------------------------------
    # Context storage
    # -------------------------------------------------------------------------

    async def save_context(
        self,
        user_id: str,
        task_id: str,
        context: dict[str, Any],
    ) -> Path:
        """Save conversation context snapshot for a task."""
        task_dir = self._task_dir(user_id, task_id)
        task_dir.mkdir(parents=True, exist_ok=True)

        ctx_path = task_dir / "context.json"
        await self._write_json(ctx_path, context)
        return ctx_path

    async def load_context(self, user_id: str, task_id: str) -> dict | None:
        """Load context snapshot, or None."""
        ctx_path = self._task_dir(user_id, task_id) / "context.json"
        if not ctx_path.exists():
            return None
        return await self._read_json(ctx_path)

    # -------------------------------------------------------------------------
    # Task directory management
    # -------------------------------------------------------------------------

    async def list_tasks(self, user_id: str) -> list[str]:
        """List all task IDs for a user."""
        user_dir = self._user_dir(user_id)
        if not user_dir.exists():
            return []
        return [p.name for p in user_dir.iterdir() if p.is_dir()]

    async def delete_task(self, user_id: str, task_id: str) -> bool:
        """Delete a task directory. Returns True if deleted."""
        import shutil

        task_dir = self._task_dir(user_id, task_id)
        if task_dir.exists():
            shutil.rmtree(task_dir)
            logger.debug("Deleted task dir %s", task_dir)
            return True
        return False

    # -------------------------------------------------------------------------
    # Async file I/O
    # -------------------------------------------------------------------------

    async def _write_text(self, path: Path, content: str) -> None:
        loop = __import__("asyncio").get_running_loop()
        await loop.run_in_executor(None, lambda: path.write_text(content, "utf-8"))

    async def _read_text(self, path: Path) -> str:
        loop = __import__("asyncio").get_running_loop()
        return await loop.run_in_executor(None, lambda: path.read_text("utf-8"))

    async def _write_json(self, path: Path, data: dict) -> None:
        loop = __import__("asyncio").get_running_loop()
        await loop.run_in_executor(None, lambda: path.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8"))

    async def _read_json(self, path: Path) -> dict:
        loop = __import__("asyncio").get_running_loop()
        return await loop.run_in_executor(None, lambda: json.loads(path.read_text("utf-8")))