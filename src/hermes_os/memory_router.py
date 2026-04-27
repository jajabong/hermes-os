"""Per-user memory routing via mem0."""

from __future__ import annotations

from typing import Any, cast

try:
    from mem0 import Memory
except ImportError:
    Memory = None

from hermes_os.models import User


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
            self._clients[user.user_id] = Memory()

        return self._clients[user.user_id]

    async def store(self, user: User, memory: str, metadata: dict | None = None) -> None:
        """Store a memory entry for a specific user. No-op when mem0 is unavailable."""
        client = self._client_for(user)
        if client is None:
            return
        await client.add(
            memory,
            user_id=user.user_id,
            metadata=metadata or {},
        )

    async def search(self, user: User, query: str, limit: int = 5) -> list[dict]:
        """Search a specific user's memory. Returns [] when mem0 is unavailable."""
        client = self._client_for(user)
        if client is None:
            return []
        result = await client.search(query, user_id=user.user_id, limit=limit)
        return cast("list[dict]", result.get("results", []))

    async def get_all(self, user: User) -> list[dict]:
        """Retrieve all memories for a user. Returns [] when mem0 is unavailable."""
        client = self._client_for(user)
        if client is None:
            return []
        result = await client.get_all(user_id=user.user_id)
        return cast("list[dict]", result.get("results", []))
