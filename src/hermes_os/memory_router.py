"""Per-user memory routing via mem0."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

try:
    from mem0 import Memory
    from mem0.configs.base import MemoryConfig
except ImportError:
    Memory = None
    MemoryConfig = None

from hermes_os.models import User

_logger = logging.getLogger("hermes-os.memory_router")


class MemoryRouter:
    """Routes memory operations to per-user namespaces via mem0.

    Falls back gracefully when mem0 is not available.
    """

    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}

    def _client_for(self, user: User) -> Any | None:
        if user.user_id not in self._clients:
            if Memory is None:
                return None
            try:
                history_db_path = Path.home() / ".mem0" / f"history_{user.user_id}.db"
                self._clients[user.user_id] = Memory(
                    config=MemoryConfig(history_db_path=str(history_db_path))
                )
            except Exception as e:
                _logger.warning(
                    "[memory_router] Memory init failed for user %s, falling back to no-op: %s",
                    user.user_id,
                    e,
                )
                self._clients[user.user_id] = None
                return None

        return self._clients[user.user_id]

    async def store(self, user: User, memory: str, metadata: dict | None = None) -> None:
        """Store a memory entry for a specific user. No-op when mem0 is unavailable."""
        client = self._client_for(user)
        if client is None:
            return
        try:
            await client.add(
                memory,
                user_id=user.user_id,
                metadata=metadata or {},
            )
        except Exception as e:
            _logger.warning("[memory_router] store failed for user %s: %s", user.user_id, e)

    async def search(self, user: User, query: str, limit: int = 5) -> list[dict]:
        """Search a specific user's memory. Returns [] when mem0 is unavailable."""
        client = self._client_for(user)
        if client is None:
            return []
        try:
            result = await client.search(query, filters={"user_id": user.user_id}, limit=limit)
            return cast("list[dict]", result.get("results", []))
        except Exception as e:
            _logger.warning("[memory_router] search failed for user %s: %s", user.user_id, e)
            return []

    async def get_all(self, user: User) -> list[dict]:
        """Retrieve all memories for a user. Returns [] when mem0 is unavailable."""
        client = self._client_for(user)
        if client is None:
            return []
        try:
            result = await client.get_all(filters={"user_id": user.user_id})
            return cast("list[dict]", result.get("results", []))
        except Exception as e:
            _logger.warning("[memory_router] get_all failed for user %s: %s", user.user_id, e)
            return []
