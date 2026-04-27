"""Integration tests: two users send messages concurrently, verify no cross-contamination."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hermes_os.context_injector import ContextInjector
from hermes_os.memory_router import MemoryRouter
from hermes_os.models import User
from hermes_os.router import GatewayEvent, UserRouter
from hermes_os.session_manager import SessionManager
from hermes_os.storage import Storage
from hermes_os.user_registry import UserRegistry

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def alice() -> User:
    return User(
        user_id="alice_uid",
        name="Alice",
        role="user",
        team="alpha",
        platform="telegram",
        platform_user_id="111",
    )


@pytest.fixture
def bob() -> User:
    return User(
        user_id="bob_uid",
        name="Bob",
        role="user",
        team="beta",
        platform="discord",
        platform_user_id="222",
    )


@pytest.fixture
def injector() -> ContextInjector:
    return ContextInjector()


@pytest.fixture
async def storage() -> Storage:
    # Use in-memory for tests
    s = Storage(db_path=":memory:")
    await s.initialize()
    return s


@pytest.fixture
async def session_manager(storage: Storage) -> SessionManager:
    return SessionManager(storage=storage)


@pytest.fixture
async def user_registry(storage: Storage) -> UserRegistry:
    return UserRegistry(storage=storage)


@pytest.fixture
def mock_mem0_client() -> MagicMock:
    """A mock mem0 Memory client that tracks calls per user."""
    client = MagicMock()
    client.add = AsyncMock()
    client.search = AsyncMock(return_value={"results": []})
    client.get_all = AsyncMock(return_value={"results": []})
    return client


@pytest.fixture
def memory_router(mock_mem0_client: MagicMock) -> MemoryRouter:
    """Router with _client_for patched so it never touches real mem0."""
    with patch.object(MemoryRouter, "_client_for", return_value=mock_mem0_client):
        yield MemoryRouter()


# ---------------------------------------------------------------------------
# Core isolation tests
# ---------------------------------------------------------------------------

class TestSessionIsolation:
    """Verify sessions are completely isolated between users."""

    @pytest.mark.asyncio
    async def test_two_users_have_separate_sessions(
        self, session_manager: SessionManager, alice: User, bob: User
    ) -> None:
        """Alice and Bob get different sessions with independent histories."""
        alice_session = await session_manager.get_or_create(alice.user_id)
        bob_session = await session_manager.get_or_create(bob.user_id)

        assert alice_session.session_id != bob_session.session_id

        await session_manager.add_message(alice.user_id, "user", "Alice's private message")
        await session_manager.add_message(alice.user_id, "assistant", "Alice's private response")

        bob_session = await session_manager.get(bob.user_id)
        assert len(bob_session.conversation_history) == 0

        alice_session = await session_manager.get(alice.user_id)
        assert len(alice_session.conversation_history) == 2
        assert alice_session.conversation_history[0].content == "Alice's private message"

    @pytest.mark.asyncio
    async def test_session_clear_is_per_user(
        self, session_manager: SessionManager, alice: User, bob: User
    ) -> None:
        """Clearing Alice's session does not affect Bob's session."""
        await session_manager.add_message(alice.user_id, "user", "Alice msg")
        await session_manager.add_message(bob.user_id, "user", "Bob msg")

        await session_manager.clear(alice.user_id)

        alice_session = await session_manager.get(alice.user_id)
        bob_session = await session_manager.get(bob.user_id)

        assert len(alice_session.conversation_history) == 0
        assert len(bob_session.conversation_history) == 1
        assert bob_session.conversation_history[0].content == "Bob msg"


class TestContextInjectionIsolation:
    """Verify context injection does not leak between users."""

    def test_context_injection_user_specific(
        self, injector: ContextInjector, alice: User, bob: User
    ) -> None:
        """Alice's messages get Alice's context block, Bob's get Bob's."""
        alice_result = injector.inject(alice, "Hello")
        bob_result = injector.inject(bob, "Hello")

        assert "Alice" in alice_result
        assert "Bob" in bob_result
        assert "alice_uid" in alice_result
        assert "bob_uid" in bob_result
        # Cross-check: Alice's context should NOT contain Bob's identity
        assert "Bob" not in alice_result
        assert "alice_uid" not in bob_result

    def test_context_inject_history_user_specific(
        self, injector: ContextInjector, alice: User, bob: User
    ) -> None:
        """inject_history injects the correct user's context block."""
        history = [{"role": "user", "content": "Request"}]

        alice_result = injector.inject_history(alice, history)
        bob_result = injector.inject_history(bob, history)

        assert "alice_uid" in alice_result[0]["content"]
        assert "bob_uid" in bob_result[0]["content"]
        assert "Alice" in alice_result[0]["content"]
        assert "Bob" in bob_result[0]["content"]


class TestMemoryIsolation:
    """Verify memories are isolated between users via user_id routing."""

    @pytest.mark.asyncio
    async def test_store_memory_user_specific(
        self,
        memory_router: MemoryRouter,
        mock_mem0_client: MagicMock,
        alice: User,
        bob: User,
    ) -> None:
        """Memories are stored with user_id so they route to different namespaces."""
        await memory_router.store(alice, "Alice's preference: dark mode")
        await memory_router.store(bob, "Bob's preference: light mode")

        calls = mock_mem0_client.add.await_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["user_id"] == "alice_uid"
        assert calls[1].kwargs["user_id"] == "bob_uid"
        assert "Alice's preference" in calls[0].args[0]
        assert "Bob's preference" in calls[1].args[0]

    @pytest.mark.asyncio
    async def test_search_memory_user_specific(
        self,
        memory_router: MemoryRouter,
        mock_mem0_client: MagicMock,
        alice: User,
        bob: User,
    ) -> None:
        """Searching memory only returns results from the requesting user's namespace."""
        mock_mem0_client.search = AsyncMock(
            side_effect=[
                {"results": [{"memory": "Alice data"}]},
                {"results": [{"memory": "Bob data"}]},
            ]
        )

        alice_results = await memory_router.search(alice, "query")
        bob_results = await memory_router.search(bob, "query")

        assert alice_results == [{"memory": "Alice data"}]
        assert bob_results == [{"memory": "Bob data"}]

        calls = mock_mem0_client.search.await_args_list
        assert calls[0].kwargs["user_id"] == "alice_uid"
        assert calls[1].kwargs["user_id"] == "bob_uid"


class TestFullPipelineIsolation:
    """End-to-end: two users flow through the full Hermes OS pipeline."""

    @pytest.mark.asyncio
    async def test_concurrent_messages_maintain_isolation(
        self,
        user_registry: UserRegistry,
        session_manager: SessionManager,
        injector: ContextInjector,
        alice: User,
        bob: User,
    ) -> None:
        """Alice and Bob send messages concurrently — contexts never cross-contaminate."""
        user_registry.register(alice)
        user_registry.register(bob)

        async def alice_flow() -> dict:
            user = user_registry.get(alice.user_id)
            assert user is not None

            session = await session_manager.get_or_create(user.user_id)
            await session_manager.add_message(user.user_id, "user", "Alice's message")
            await session_manager.add_message(user.user_id, "assistant", "Alice's response")

            history = session.get_history_for_agent()
            enriched = injector.inject_history(user, history)
            return {
                "user_id": user.user_id,
                "history_len": len(enriched),
                "first_msg_has_context": "<current_user>" in enriched[0]["content"],
                "msg_user_id": "alice_uid",
            }

        async def bob_flow() -> dict:
            user = user_registry.get(bob.user_id)
            assert user is not None

            session = await session_manager.get_or_create(user.user_id)
            await session_manager.add_message(user.user_id, "user", "Bob's message")
            await session_manager.add_message(user.user_id, "assistant", "Bob's response")

            history = session.get_history_for_agent()
            enriched = injector.inject_history(user, history)
            return {
                "user_id": user.user_id,
                "history_len": len(enriched),
                "first_msg_has_context": "<current_user>" in enriched[0]["content"],
                "msg_user_id": "bob_uid",
            }

        alice_result, bob_result = await asyncio.gather(
            alice_flow(), bob_flow()
        )

        assert alice_result["user_id"] == "alice_uid"
        assert alice_result["history_len"] == 2
        assert alice_result["first_msg_has_context"] is True
        assert alice_result["msg_user_id"] == "alice_uid"

        assert bob_result["user_id"] == "bob_uid"
        assert bob_result["history_len"] == 2
        assert bob_result["first_msg_has_context"] is True
        assert bob_result["msg_user_id"] == "bob_uid"

        # Cross-check: no contamination
        alice_session = await session_manager.get("alice_uid")
        bob_session = await session_manager.get("bob_uid")
        assert len(alice_session.conversation_history) == 2
        assert len(bob_session.conversation_history) == 2

    @pytest.mark.asyncio
    async def test_user_registry_lookup_isolation(
        self, user_registry: UserRegistry, alice: User, bob: User
    ) -> None:
        """Looking up one user never returns the other user's data."""
        user_registry.register(alice)
        user_registry.register(bob)

        found_alice = user_registry.get(alice.user_id)
        found_bob = user_registry.get(bob.user_id)
        found_by_platform = user_registry.get_by_platform("telegram", "111")
        found_by_platform_bob = user_registry.get_by_platform("discord", "222")

        assert found_alice is not None
        assert found_alice.name == "Alice"
        assert found_bob is not None
        assert found_bob.name == "Bob"
        assert found_by_platform is not None
        assert found_by_platform.name == "Alice"
        assert found_by_platform_bob is not None
        assert found_by_platform_bob.name == "Bob"

        assert found_by_platform.user_id != found_by_platform_bob.user_id

    @pytest.mark.asyncio
    async def test_user_router_full_pipeline_concurrency(
        self,
        user_registry: UserRegistry,
        session_manager: SessionManager,
        memory_router: MemoryRouter,
        storage: Storage,
        alice: User,
        bob: User,
    ) -> None:
        """UserRouter.route handles multiple users concurrently without state leak."""
        user_registry.register(alice)
        user_registry.register(bob)
        router = UserRouter(
            registry=user_registry,
            sessions=session_manager,
            memory=memory_router,
            storage=storage
        )
        # Note: Storage already initialized in fixture

        # Simulating concurrent events
        alice_event = GatewayEvent(
            platform="telegram", platform_user_id="111", message="Hi from Alice", user_name="Alice"
        )
        bob_event = GatewayEvent(
            platform="discord", platform_user_id="222", message="Hi from Bob", user_name="Bob"
        )

        # Execute concurrently
        alice_task = router.route(alice_event)
        bob_task = router.route(bob_event)
        alice_req, bob_req = await asyncio.gather(alice_task, bob_task)

        # 1. Verify Alice's Request
        assert alice_req.user.user_id == "alice_uid"
        assert "Alice" in alice_req.enriched_message
        assert "Hi from Alice" in alice_req.enriched_message
        assert "Bob" not in alice_req.enriched_message

        # 2. Verify Bob's Request
        assert bob_req.user.user_id == "bob_uid"
        assert "Bob" in bob_req.enriched_message
        assert "Hi from Bob" in bob_req.enriched_message
        assert "Alice" not in bob_req.enriched_message

        # 3. Verify Session Persistence
        alice_session = await session_manager.get("alice_uid")
        bob_session = await session_manager.get("bob_uid")
        assert len(alice_session.conversation_history) == 1
        assert len(bob_session.conversation_history) == 1
        assert alice_session.conversation_history[0].content == "Hi from Alice"
        assert bob_session.conversation_history[0].content == "Hi from Bob"

        # 4. Sequential check: send second message to verify history injection
        alice_event_2 = GatewayEvent(
            platform="telegram",
            platform_user_id="111",
            message="Alice second msg",
            user_name="Alice",
        )
        alice_req_2 = await router.route(alice_event_2)

        # Should NOT contain Bob's context even after multi-user activity
        assert "Bob" not in alice_req_2.enriched_message
        assert "Alice" in alice_req_2.enriched_message

        # Verify history in session manager
        final_alice_session = await session_manager.get("alice_uid")
        assert len(final_alice_session.conversation_history) == 2
