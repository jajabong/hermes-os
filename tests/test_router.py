"""Tests for UserRouter (orchestration layer)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hermes_os.context_injector import ContextInjector
from hermes_os.memory_router import MemoryRouter
from hermes_os.models import Session, User
from hermes_os.router import GatewayEvent, RoutedRequest, UserRouter
from hermes_os.session_manager import SessionManager
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
        alice_user: User,
    ) -> None:
        """route() falls back to plain message when session has no history."""
        mock_registry.upsert_from_pairing.return_value = alice_user
        router.sessions.get = AsyncMock(return_value=None)

        event = GatewayEvent(
            platform="telegram",
            platform_user_id="111",
            message="Fallback message",
            user_name="Alice",
        )

        result = await router.route(event)

        assert result.enriched_message == "Fallback message"


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
        await router.store_response("session_1", alice_user.user_id, "Agent response text")

        mock_sessions.add_message.assert_called_once_with(
            alice_user.user_id, "assistant", "Agent response text"
        )
