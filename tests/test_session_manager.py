"""Tests for SessionManager."""

import asyncio

import pytest

from hermes_os.models import Message, Session
from hermes_os.session_manager import SessionManager
from hermes_os.storage import Storage


@pytest.fixture
async def manager() -> SessionManager:
    storage = Storage(db_path=":memory:")
    await storage.initialize()
    return SessionManager(storage=storage)


class TestSessionManager:
    """Unit tests for SessionManager."""

    # --- get_or_create ---

    @pytest.mark.asyncio
    async def test_get_or_create_creates_new_session(self, manager: SessionManager) -> None:
        """First call for a user_id creates a new session."""
        session = await manager.get_or_create("user_001")

        assert session.user_id == "user_001"
        assert session.session_id is not None
        assert len(session.session_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_get_or_create_returns_existing(self, manager: SessionManager) -> None:
        """Subsequent calls return the same session."""
        first = await manager.get_or_create("user_001")
        second = await manager.get_or_create("user_001")

        assert first is second
        assert first.session_id == second.session_id

    @pytest.mark.asyncio
    async def test_get_or_create_different_users_get_different_sessions(
        self, manager: SessionManager
    ) -> None:
        """Different user_ids get different sessions."""
        s1 = await manager.get_or_create("alice")
        s2 = await manager.get_or_create("bob")

        assert s1.user_id != s2.user_id
        assert s1.session_id != s2.session_id

    @pytest.mark.asyncio
    async def test_get_or_create_session_has_timestamps(
        self, manager: SessionManager
    ) -> None:
        """New session has created_at and last_active timestamps."""
        session = await manager.get_or_create("user_x")

        assert session.created_at is not None
        assert session.last_active is not None

    # --- get ---

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, manager: SessionManager) -> None:
        """Get on unknown user returns None — does NOT auto-create."""
        result = await manager.get("unknown")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_existing_session(self, manager: SessionManager) -> None:
        """Get returns the correct session after it was created."""
        created = await manager.get_or_create("user_001")
        retrieved = await manager.get("user_001")

        assert retrieved is created

    # --- add_message ---

    @pytest.mark.asyncio
    async def test_add_message_appends_to_history(self, manager: SessionManager) -> None:
        """add_message appends a Message to the session's conversation_history."""
        await manager.add_message("alice", "user", "Hello")

        session = await manager.get("alice")
        assert session is not None
        assert len(session.conversation_history) == 1
        assert session.conversation_history[0].role == "user"
        assert session.conversation_history[0].content == "Hello"

    @pytest.mark.asyncio
    async def test_add_message_multiple_messages(self, manager: SessionManager) -> None:
        """Multiple messages accumulate in history."""
        await manager.add_message("alice", "user", "Hi")
        await manager.add_message("alice", "assistant", "Hi there!")
        await manager.add_message("alice", "user", "Thanks")

        session = await manager.get("alice")
        assert session is not None
        assert len(session.conversation_history) == 3
        assert session.conversation_history[0].content == "Hi"
        assert session.conversation_history[1].content == "Hi there!"
        assert session.conversation_history[2].content == "Thanks"

    @pytest.mark.asyncio
    async def test_add_message_updates_last_active(self, manager: SessionManager) -> None:
        """last_active is updated when a message is added."""
        session = await manager.get_or_create("alice")
        original_last_active = session.last_active

        await asyncio.sleep(0.01)
        await manager.add_message("alice", "user", "New message")

        session = await manager.get("alice")
        assert session is not None
        assert session.last_active >= original_last_active

    @pytest.mark.asyncio
    async def test_add_message_creates_session_if_missing(
        self, manager: SessionManager
    ) -> None:
        """add_message on unknown user creates session first."""
        await manager.add_message("new_user", "user", "First message")

        session = await manager.get("new_user")
        assert session is not None
        assert session.user_id == "new_user"
        assert len(session.conversation_history) == 1

    # --- clear ---

    @pytest.mark.asyncio
    async def test_clear_removes_conversation_history(self, manager: SessionManager) -> None:
        """clear empties the session history for a user."""
        await manager.add_message("alice", "user", "Hello")
        await manager.add_message("alice", "assistant", "Hi!")
        await manager.clear("alice")

        session = await manager.get("alice")
        assert session is not None
        assert len(session.conversation_history) == 0

    @pytest.mark.asyncio
    async def test_clear_nonexistent_user_is_noop(self, manager: SessionManager) -> None:
        """clear on unknown user does not raise."""
        await manager.clear("ghost")  # should not raise

    @pytest.mark.asyncio
    async def test_clear_preserves_session_object(self, manager: SessionManager) -> None:
        """clear keeps the session object but empties history."""
        session = await manager.get_or_create("alice")
        original_session_id = session.session_id

        await manager.clear("alice")
        session = await manager.get("alice")

        assert session is not None
        assert session.session_id == original_session_id
        assert session.user_id == "alice"

    @pytest.mark.asyncio
    async def test_clear_updates_last_active(self, manager: SessionManager) -> None:
        """clear updates last_active timestamp."""
        await manager.add_message("alice", "user", "Hi")
        await asyncio.sleep(0.01)
        await manager.clear("alice")

        session = await manager.get("alice")
        assert session is not None


class TestConcurrentAddMessage:
    """Verify add_message is safe under concurrent access to the same user."""

    @pytest.fixture
    async def concurrent_manager(self) -> SessionManager:
        storage = Storage(db_path=":memory:")
        await storage.initialize()
        return SessionManager(storage=storage)

    @pytest.mark.asyncio
    async def test_concurrent_add_message_no_message_loss(
        self, concurrent_manager: SessionManager
    ) -> None:
        """Concurrent add_message calls for the same user must not lose messages."""
        user_id = "alice"
        num_messages = 50

        async def add_nth(i: int) -> None:
            await concurrent_manager.add_message(user_id, "user", f"Message {i}")

        await asyncio.gather(*[add_nth(i) for i in range(num_messages)])

        session = await concurrent_manager.get(user_id)
        assert session is not None
        assert len(session.conversation_history) == num_messages
        contents = [m.content for m in session.conversation_history]
        for i in range(num_messages):
            assert f"Message {i}" in contents

    @pytest.mark.asyncio
    async def test_concurrent_add_message_order_preserved(
        self, concurrent_manager: SessionManager
    ) -> None:
        """Concurrent messages are stored — every message appears exactly once."""
        user_id = "bob"
        num_messages = 20

        async def add_nth(i: int) -> None:
            await concurrent_manager.add_message(user_id, "user", f"Msg {i}")

        await asyncio.gather(*[add_nth(i) for i in range(num_messages)])

        session = await concurrent_manager.get(user_id)
        assert session is not None
        contents = [m.content for m in session.conversation_history]
        assert sorted(contents) == sorted(f"Msg {i}" for i in range(num_messages))

    @pytest.mark.asyncio
    async def test_concurrent_different_users_isolated(
        self, concurrent_manager: SessionManager
    ) -> None:
        """Concurrent add_message on different users are fully isolated."""
        num_users = 10
        msgs_per_user = 10

        async def user_flow(uid: int) -> None:
            for i in range(msgs_per_user):
                await concurrent_manager.add_message(
                    f"user_{uid}", "user", f"U{uid}M{i}"
                )

        await asyncio.gather(*[user_flow(uid) for uid in range(num_users)])

        for uid in range(num_users):
            session = await concurrent_manager.get(f"user_{uid}")
            assert session is not None
            assert len(session.conversation_history) == msgs_per_user


class TestSessionModel:
    """Unit tests for Session model methods."""

    def test_add_message(self) -> None:
        """Session.add_message appends Message and updates last_active."""
        session = Session(session_id="s1", user_id="u1")
        session.add_message("user", "Hello")

        assert len(session.conversation_history) == 1
        msg = session.conversation_history[0]
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.timestamp is not None

    def test_get_history_for_agent(self) -> None:
        """get_history_for_agent returns list of role/content dicts."""
        session = Session(session_id="s1", user_id="u1")
        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi there")

        history = session.get_history_for_agent()
        assert history == [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]

    def test_get_history_for_agent_empty(self) -> None:
        """Empty session returns empty list."""
        session = Session(session_id="s1", user_id="u1")
        assert session.get_history_for_agent() == []

    # --- session_id stability ---

    @pytest.mark.asyncio
    async def test_session_id_is_stable_across_loads(self, manager: SessionManager) -> None:
        """Same user always gets the same session_id, even after re-load from storage."""
        session1 = await manager.get_or_create("alice")
        first_id = session1.session_id

        # Simulate process restart: drop in-memory cache and reload
        manager._sessions.clear()
        session2 = await manager.get_or_create("alice")

        assert session2.session_id == first_id, (
            f"session_id changed after reload: {first_id} != {session2.session_id}"
        )

    @pytest.mark.asyncio
    async def test_add_message_preserves_existing_session_id(
        self, manager: SessionManager
    ) -> None:
        """add_message does not change session_id for an existing session."""
        await manager.get_or_create("alice")
        original_id = manager._sessions["alice"].session_id

        # Re-create via add_message path (session already in memory)
        await manager.add_message("alice", "user", "Hello")
        assert manager._sessions["alice"].session_id == original_id

        # Simulate eviction then add_message
        manager._sessions.clear()
        await manager.add_message("alice", "user", "Hello again")
        post_add_id = manager._sessions["alice"].session_id

        # Should load existing history and keep original session_id
        manager._sessions.clear()
        session3 = await manager.get_or_create("alice")
        assert session3.session_id == post_add_id

    def test_conversation_history_order(self) -> None:
        """Messages are stored in insertion order."""
        session = Session(session_id="s1", user_id="u1")
        for i in range(5):
            session.add_message("user", f"Msg {i}")

        assert len(session.conversation_history) == 5
        for i, msg in enumerate(session.conversation_history):
            assert msg.content == f"Msg {i}"


class TestMessageModel:
    """Unit tests for Message model."""

    def test_message_has_timestamp(self) -> None:
        """Message has a timestamp when created."""
        msg = Message(role="user", content="test")
        assert msg.timestamp is not None

    def test_message_fields(self) -> None:
        """Message stores role and content correctly."""
        msg = Message(role="assistant", content="response")
        assert msg.role == "assistant"
        assert msg.content == "response"
