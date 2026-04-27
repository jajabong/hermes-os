"""Per-user session management with persistence."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from hermes_os.models import Message, Session
from hermes_os.storage import Storage


class SessionManager:
    """Manages user sessions with SQLite storage.

    All mutating operations (add_message, clear) are fully atomic — the lock
    covers the entire operation, not just session lookup.
    """

    def __init__(self, storage: Storage | None = None) -> None:
        self.storage = storage or Storage()
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def _ensure_session(self, user_id: str) -> Session:
        """Get existing session from memory, or load from storage, or create new.

        MUST be called inside self._lock.
        """
        if user_id in self._sessions:
            return self._sessions[user_id]

        # Load history from storage
        history_rows = await self.storage.get_messages(user_id)
        history = [
            Message(role=row["role"], content=row["content"])
            for row in history_rows
        ]

        # Load persisted session_id, or generate a new one
        session_id = await self.storage.get_session_id(user_id)
        if session_id is None:
            session_id = str(uuid.uuid4())
            await self.storage.save_session_id(user_id, session_id)

        session = Session(
            session_id=session_id,
            user_id=user_id,
            conversation_history=history,
        )
        self._sessions[user_id] = session
        return session

    async def get_or_create(self, user_id: str) -> Session:
        """Return existing session for user_id, or load from DB / create new."""
        async with self._lock:
            return await self._ensure_session(user_id)

    async def get(self, user_id: str) -> Session | None:
        """Return existing session for user_id, or None if not yet created."""
        return self._sessions.get(user_id)

    async def add_message(self, user_id: str, role: str, content: str) -> None:
        """Atomically append a message: get-or-create + modify + persist.

        The entire operation is protected by self._lock so that concurrent
        calls for the same user_id cannot interleave and lose messages.
        """
        async with self._lock:
            session = await self._ensure_session(user_id)
            session.add_message(role, content)

            await self.storage.save_message(
                user_id=user_id,
                role=role,
                content=content,
                timestamp=datetime.now(UTC).isoformat(),
            )

    async def clear(self, user_id: str) -> None:
        """Reset session history in memory and DB atomically."""
        async with self._lock:
            if user_id in self._sessions:
                self._sessions[user_id].conversation_history.clear()
                self._sessions[user_id].last_active = datetime.now(UTC)

            await self.storage.clear_messages(user_id)
