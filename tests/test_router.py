"""Tests for UserRouter (orchestration layer)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hermes_os.context_injector import ContextInjector
from hermes_os.knowledge_router import KnowledgeRouter
from hermes_os.memory_router import MemoryRouter
from hermes_os.models import Session, User
from hermes_os.router import GatewayEvent, RoutedRequest, UserRouter
from hermes_os.session_manager import SessionManager
from hermes_os.storage import Storage
from hermes_os.user_registry import UserRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_registry() -> MagicMock:
    return MagicMock(spec=UserRegistry)


@pytest.fixture
def mock_sessions() -> MagicMock:
    sessions = MagicMock(spec=SessionManager)
    sessions.add_message = AsyncMock()
    sessions.get = AsyncMock()
    return sessions


@pytest.fixture
def mock_memory() -> MagicMock:
    memory = MagicMock(spec=MemoryRouter)
    memory.store = AsyncMock()
    memory.search = AsyncMock(return_value=[])
    return memory


@pytest.fixture
def mock_knowledge() -> MagicMock:
    knowledge = MagicMock(spec=KnowledgeRouter)
    knowledge.search = AsyncMock(return_value=[])
    return knowledge


@pytest.fixture
def router(
    mock_registry: MagicMock,
    mock_sessions: MagicMock,
    mock_memory: MagicMock,
) -> UserRouter:
    return UserRouter(
        registry=mock_registry,
        sessions=mock_sessions,
        memory=mock_memory,
    )


@pytest.fixture
def router_with_knowledge(
    mock_registry: MagicMock,
    mock_sessions: MagicMock,
    mock_memory: MagicMock,
    mock_knowledge: MagicMock,
) -> UserRouter:
    return UserRouter(
        registry=mock_registry,
        sessions=mock_sessions,
        memory=mock_memory,
        knowledge=mock_knowledge,
    )


@pytest.fixture
def alice_user() -> User:
    return User(
        user_id="alice_router",
        name="Alice",
        role="user",
        team="alpha",
        platform="telegram",
        platform_user_id="111",
    )


# ---------------------------------------------------------------------------
# GatewayEvent dataclass
# ---------------------------------------------------------------------------

class TestGatewayEvent:
    """Tests for GatewayEvent."""

    def test_minimal_event(self) -> None:
        """Can create GatewayEvent with required fields only."""
        event = GatewayEvent(platform="telegram", platform_user_id="123", message="Hi")

        assert event.platform == "telegram"
        assert event.platform_user_id == "123"
        assert event.message == "Hi"
        assert event.user_name == "Unknown"  # default

    def test_full_event(self) -> None:
        """Can create GatewayEvent with all fields."""
        event = GatewayEvent(
            platform="discord",
            platform_user_id="456",
            message="Hello",
            user_name="Bob",
        )

        assert event.platform == "discord"
        assert event.platform_user_id == "456"
        assert event.message == "Hello"
        assert event.user_name == "Bob"


# ---------------------------------------------------------------------------
# RoutedRequest dataclass
# ---------------------------------------------------------------------------

class TestRoutedRequest:
    """Tests for RoutedRequest."""

    def test_fields(self) -> None:
        """RoutedRequest stores all required fields."""
        user = User(user_id="u1", name="Test", platform="x", platform_user_id="1")
        req = RoutedRequest(user=user, enriched_message="enriched", session_id="s1")

        assert req.user == user
        assert req.enriched_message == "enriched"
        assert req.session_id == "s1"


# ---------------------------------------------------------------------------
# UserRouter.__init__
# ---------------------------------------------------------------------------

class TestUserRouterInit:
    """Tests for UserRouter initialization."""

    def test_init_with_explicit_deps(
        self,
        mock_registry: MagicMock,
        mock_sessions: MagicMock,
        mock_memory: MagicMock,
    ) -> None:
        """UserRouter accepts explicit dependencies."""
        router = UserRouter(
            registry=mock_registry,
            sessions=mock_sessions,
            memory=mock_memory,
        )

        assert router.registry is mock_registry
        assert router.sessions is mock_sessions
        assert router.memory is mock_memory
        assert isinstance(router.injector, ContextInjector)

    def test_init_creates_defaults(self) -> None:
        """UserRouter creates its own instances when deps are not provided."""
        router = UserRouter()

        assert isinstance(router.registry, UserRegistry)
        assert isinstance(router.sessions, SessionManager)
        assert isinstance(router.memory, MemoryRouter)
        assert isinstance(router.injector, ContextInjector)


# ---------------------------------------------------------------------------
# UserRouter.route()
# ---------------------------------------------------------------------------

class TestUserRouterRoute:
    """Tests for UserRouter.route()."""

    @pytest.mark.asyncio
    async def test_route_upserts_user_from_pairing(
        self,
        router: UserRouter,
        mock_registry: MagicMock,
        alice_user: User,
    ) -> None:
        """route() calls registry.upsert_from_pairing with event data."""
        mock_registry.upsert_from_pairing.return_value = alice_user
        router.sessions.get = AsyncMock(return_value=None)
        session = Session(session_id="s1", user_id=alice_user.user_id)
        session.add_message("user", "Hello")
        router.sessions.get_or_create = AsyncMock(return_value=session)

        event = GatewayEvent(
            platform="telegram",
            platform_user_id="111",
            message="Hello",
            user_name="Alice",
        )

        await router.route(event)

        mock_registry.upsert_from_pairing.assert_called_once_with(
            platform="telegram",
            platform_user_id="111",
            name="Alice",
        )

    @pytest.mark.asyncio
    async def test_route_adds_user_message_to_session(
        self,
        router: UserRouter,
        alice_user: User,
    ) -> None:
        """route() records the user's message in their session."""
        mock_registry = router.registry
        mock_registry.upsert_from_pairing.return_value = alice_user

        session = Session(session_id="s1", user_id=alice_user.user_id)
        router.sessions.get = AsyncMock(return_value=session)

        event = GatewayEvent(
            platform="telegram",
            platform_user_id="111",
            message="My request",
            user_name="Alice",
        )

        await router.route(event)

        router.sessions.add_message.assert_called_once_with(
            alice_user.user_id, "user", "My request"
        )

    @pytest.mark.asyncio
    async def test_route_injects_context_into_message(
        self,
        router: UserRouter,
        alice_user: User,
    ) -> None:
        """route() returns the enriched message with context block."""
        mock_registry = router.registry
        mock_registry.upsert_from_pairing.return_value = alice_user

        session = Session(session_id="s1", user_id=alice_user.user_id)
        session.add_message("user", "Original message")
        router.sessions.get = AsyncMock(return_value=session)

        event = GatewayEvent(
            platform="telegram",
            platform_user_id="111",
            message="Original message",
            user_name="Alice",
        )

        result = await router.route(event)

        assert "<current_user>" in result.enriched_message
        assert "alice_router" in result.enriched_message
        assert "Alice" in result.enriched_message

    @pytest.mark.asyncio
    async def test_route_returns_correct_session_id(
        self,
        router: UserRouter,
        alice_user: User,
    ) -> None:
        """route() returns the user's session_id in RoutedRequest."""
        mock_registry = router.registry
        mock_registry.upsert_from_pairing.return_value = alice_user

        session = Session(session_id="session_abc", user_id=alice_user.user_id)
        router.sessions.get = AsyncMock(return_value=session)

        event = GatewayEvent(
            platform="telegram",
            platform_user_id="111",
            message="Hi",
            user_name="Alice",
        )

        result = await router.route(event)

        assert result.session_id == "session_abc"

    @pytest.mark.asyncio
    async def test_route_returns_user_object(
        self,
        router: UserRouter,
        mock_registry: MagicMock,
        alice_user: User,
    ) -> None:
        """route() includes the resolved User in RoutedRequest."""
        mock_registry.upsert_from_pairing.return_value = alice_user
        router.sessions.get = AsyncMock(return_value=None)
        session = Session(session_id="s1", user_id=alice_user.user_id)
        router.sessions.get_or_create = AsyncMock(return_value=session)

        event = GatewayEvent(
            platform="telegram",
            platform_user_id="111",
            message="Hi",
            user_name="Alice",
        )

        result = await router.route(event)

        assert result.user is alice_user

    @pytest.mark.asyncio
    async def test_route_empty_history_returns_plain_message(
        self,
        router: UserRouter,
        mock_registry: MagicMock,
        mock_sessions: MagicMock,
        alice_user: User,
    ) -> None:
        """route() falls back to plain message when session has no history."""
        mock_registry.upsert_from_pairing.return_value = alice_user
        # sessions.get returns None → should fall back to get_or_create
        mock_sessions.get = AsyncMock(return_value=None)
        mock_sessions.get_or_create = AsyncMock()
        # Simulate a fresh session with no history
        fresh_session = Session(session_id="fresh_s1", user_id=alice_user.user_id)
        mock_sessions.get_or_create.return_value = fresh_session

        event = GatewayEvent(
            platform="telegram",
            platform_user_id="111",
            message="Fallback message",
            user_name="Alice",
        )

        result = await router.route(event)

        assert result.enriched_message == "Fallback message"
        assert result.session_id == "fresh_s1"

    @pytest.mark.asyncio
    async def test_route_none_session_does_not_raise(
        self,
        router: UserRouter,
        mock_registry: MagicMock,
        mock_sessions: MagicMock,
        alice_user: User,
    ) -> None:
        """route() does not raise when sessions.get returns None."""
        mock_registry.upsert_from_pairing.return_value = alice_user
        mock_sessions.get = AsyncMock(return_value=None)
        fresh_session = Session(session_id="s2", user_id=alice_user.user_id)
        mock_sessions.get_or_create = AsyncMock(return_value=fresh_session)

        event = GatewayEvent(
            platform="telegram",
            platform_user_id="111",
            message="Hi",
            user_name="Alice",
        )
        # Should not raise AttributeError
        result = await router.route(event)
        assert result.session_id == "s2"


# ---------------------------------------------------------------------------
# UserRouter.store_response()
# ---------------------------------------------------------------------------

class TestUserRouterStoreResponse:
    """Tests for UserRouter.store_response()."""

    @pytest.mark.asyncio
    async def test_store_response_adds_to_session(
        self,
        router: UserRouter,
        mock_sessions: MagicMock,
        alice_user: User,
    ) -> None:
        """store_response() records the assistant response in the session."""
        await router.store_response(alice_user, "session_1", "Agent response text")

        mock_sessions.add_message.assert_called_once_with(
            alice_user.user_id, "assistant", "Agent response text"
        )

    @pytest.mark.asyncio
    async def test_store_response_also_stores_in_memory(
        self,
        router: UserRouter,
        mock_sessions: MagicMock,
        mock_memory: MagicMock,
        alice_user: User,
    ) -> None:
        """store_response() persists the assistant response to long-term memory."""
        await router.store_response(alice_user, "session_1", "Agent response text")

        mock_memory.store.assert_called_once_with(
            alice_user, "Agent response text", metadata={"session_id": "session_1"}
        )


# ---------------------------------------------------------------------------
# Memory integration in route()
# ---------------------------------------------------------------------------

class TestStorageLifecycle:
    """Tests for Storage lifecycle management."""

    @pytest.mark.asyncio
    async def test_router_supports_async_context_manager(self) -> None:
        """UserRouter can be used as an async context manager for clean shutdown."""
        storage = Storage(db_path=":memory:")
        router = UserRouter(
            registry=UserRegistry(storage=storage),
            sessions=SessionManager(storage=storage),
            storage=storage,
        )

        async with router:
            # Warm up: route one event to open the DB connection
            await router.initialize()
            alice_event = GatewayEvent(
                platform="telegram",
                platform_user_id="test_123",
                message="Hello",
                user_name="Alice",
            )
            await router.route(alice_event)

        # After exiting context manager, storage should be closed
        assert storage._db is None

    @pytest.mark.asyncio
    async def test_storage_close_is_idempotent(self) -> None:
        """Calling close() multiple times does not raise."""
        storage = Storage(db_path=":memory:")
        await storage.initialize()
        await storage.close()
        await storage.close()  # must not raise


class TestPlatformAgnosticContext:
    """Tests that context block is platform-agnostic."""

    def test_context_block_contains_only_user_fields(self) -> None:
        """Context block has user fields but no platform-specific instructions."""
        user = User(
            user_id="test_uid",
            name="Test User",
            role="admin",
            team="alpha",
            platform="telegram",
            platform_user_id="123",
        )
        block = user.to_context_block()

        assert "<current_user>" in block
        assert "test_uid" in block
        assert "Test User" in block
        assert "admin" in block
        assert "alpha" in block
        # Platform-specific instructions must NOT appear in context block
        assert "feishu" not in block.lower()
        assert "feishu_message_history" not in block
        assert "MEDIA:" not in block
        assert "File Delivery" not in block


class TestMemoryIntegration:
    """Tests for memory.search() integration in route()."""

    @pytest.mark.asyncio
    async def test_route_searches_memory_and_injects_context(
        self,
        mock_registry: MagicMock,
        mock_sessions: MagicMock,
        mock_memory: MagicMock,
        alice_user: User,
    ) -> None:
        """route() calls memory.search() and injects results into enriched_message."""
        mock_registry.upsert_from_pairing.return_value = alice_user
        session = Session(session_id="s1", user_id=alice_user.user_id)
        session.add_message("user", "Hello")
        mock_sessions.get = AsyncMock(return_value=session)

        # Simulate prior memory: user previously mentioned "JavaScript project"
        mock_memory.search = AsyncMock(return_value=[
            {"text": "Alice is working on a JavaScript project", "score": 0.9},
            {"text": "Alice prefers dark mode", "score": 0.8},
        ])

        router = UserRouter(
            registry=mock_registry,
            sessions=mock_sessions,
            memory=mock_memory,
        )

        event = GatewayEvent(
            platform="telegram",
            platform_user_id="111",
            message="Hello",
            user_name="Alice",
        )
        result = await router.route(event)

        # Should call memory.search with the user's query
        mock_memory.search.assert_called_once()
        call_args = mock_memory.search.call_args
        assert call_args[0][0] == alice_user  # user object
        assert call_args[0][1] == "Hello"      # query from event.message

        # Enriched message should contain memory content
        assert "JavaScript project" in result.enriched_message
        assert "dark mode" in result.enriched_message

    @pytest.mark.asyncio
    async def test_route_memory_search_empty_is_noop(
        self,
        mock_registry: MagicMock,
        mock_sessions: MagicMock,
        mock_memory: MagicMock,
        alice_user: User,
    ) -> None:
        """route() works fine when memory returns no results."""
        mock_registry.upsert_from_pairing.return_value = alice_user
        session = Session(session_id="s1", user_id=alice_user.user_id)
        session.add_message("user", "Hello")
        mock_sessions.get = AsyncMock(return_value=session)
        mock_memory.search = AsyncMock(return_value=[])

        router = UserRouter(
            registry=mock_registry,
            sessions=mock_sessions,
            memory=mock_memory,
        )

        event = GatewayEvent(
            platform="telegram",
            platform_user_id="111",
            message="Hello",
            user_name="Alice",
        )
        result = await router.route(event)

        # Should still have user context block; no memory results means nothing extra added
        assert "<current_user>" in result.enriched_message
        assert "Alice" in result.enriched_message


class TestKnowledgeIntegration:
    """Tests for KnowledgeRouter.search() integration in route()."""

    @pytest.mark.asyncio
    async def test_route_searches_knowledge_and_injects_context(
        self,
        router_with_knowledge: UserRouter,
        mock_registry: MagicMock,
        mock_sessions: MagicMock,
        mock_memory: MagicMock,
        mock_knowledge: MagicMock,
        alice_user: User,
    ) -> None:
        """route() calls knowledge.search() and injects <knowledge> block."""
        mock_registry.upsert_from_pairing.return_value = alice_user
        session = Session(session_id="s1", user_id=alice_user.user_id)
        session.add_message("user", "What is our deployment process?")
        mock_sessions.get = AsyncMock(return_value=session)
        mock_memory.search = AsyncMock(return_value=[])
        mock_knowledge.search = AsyncMock(return_value=[
            {
                "doc_id": "deploy-guide",
                "title": "Deployment Guide",
                "content": "Run `make deploy` to deploy to production.",
            },
        ])

        event = GatewayEvent(
            platform="telegram",
            platform_user_id="111",
            message="What is our deployment process?",
            user_name="Alice",
        )
        result = await router_with_knowledge.route(event)

        mock_knowledge.search.assert_called_once()
        call_args = mock_knowledge.search.call_args
        assert call_args[0][0] == "What is our deployment process?"
        assert call_args[1]["team"] == alice_user.team

        assert "<knowledge>" in result.enriched_message
        assert "Deployment Guide" in result.enriched_message
        assert "make deploy" in result.enriched_message

    @pytest.mark.asyncio
    async def test_route_knowledge_results_empty_is_noop(
        self,
        router_with_knowledge: UserRouter,
        mock_registry: MagicMock,
        mock_sessions: MagicMock,
        mock_memory: MagicMock,
        mock_knowledge: MagicMock,
        alice_user: User,
    ) -> None:
        """route() has no <knowledge> block when knowledge returns no results."""
        mock_registry.upsert_from_pairing.return_value = alice_user
        session = Session(session_id="s1", user_id=alice_user.user_id)
        session.add_message("user", "Hello")
        mock_sessions.get = AsyncMock(return_value=session)
        mock_memory.search = AsyncMock(return_value=[])
        mock_knowledge.search = AsyncMock(return_value=[])

        event = GatewayEvent(
            platform="telegram",
            platform_user_id="111",
            message="Hello",
            user_name="Alice",
        )
        result = await router_with_knowledge.route(event)

        assert "<knowledge>" not in result.enriched_message

    @pytest.mark.asyncio
    async def test_route_knowledge_results_after_memory(
        self,
        router_with_knowledge: UserRouter,
        mock_registry: MagicMock,
        mock_sessions: MagicMock,
        mock_memory: MagicMock,
        mock_knowledge: MagicMock,
        alice_user: User,
    ) -> None:
        """route() injects memory first, then knowledge block."""
        mock_registry.upsert_from_pairing.return_value = alice_user
        session = Session(session_id="s1", user_id=alice_user.user_id)
        session.add_message("user", "How do I deploy?")
        mock_sessions.get = AsyncMock(return_value=session)
        mock_memory.search = AsyncMock(return_value=[
            {"text": "Alice worked on the deploy script last week"},
        ])
        mock_knowledge.search = AsyncMock(return_value=[
            {
                "doc_id": "deploy-doc",
                "title": "Deploy Doc",
                "content": "Use `make deploy`.",
            },
        ])

        event = GatewayEvent(
            platform="telegram",
            platform_user_id="111",
            message="How do I deploy?",
            user_name="Alice",
        )
        result = await router_with_knowledge.route(event)

        msg = result.enriched_message
        assert msg.index("## Relevant Memory") < msg.index("<knowledge>")
        assert "deploy script" in msg
        assert "<knowledge>" in msg
        assert "Deploy Doc" in msg
