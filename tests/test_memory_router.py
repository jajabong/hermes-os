"""Tests for MemoryRouter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hermes_os.memory_router import MemoryRouter
from hermes_os.models import User

# ---------------------------------------------------------------------------
# Shared mock client — patched at module level so patch stays active across
# all async calls (fixture-level patch with `yield` exits before async runs)
# ---------------------------------------------------------------------------

_shared_mock_client: MagicMock = MagicMock()


def _reset_mock() -> None:
    """Reset mock state before each test that uses the router fixture."""
    _shared_mock_client.reset_mock(return_value=True, side_effect=True)
    _shared_mock_client.add = AsyncMock()
    _shared_mock_client.search = AsyncMock(return_value={"results": []})
    _shared_mock_client.get_all = AsyncMock(return_value={"results": []})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def alice() -> User:
    return User(
        user_id="alice_mid",
        name="Alice",
        role="user",
        team="alpha",
        platform="telegram",
        platform_user_id="111",
    )


@pytest.fixture
def bob() -> User:
    return User(
        user_id="bob_mid",
        name="Bob",
        role="admin",
        team="beta",
        platform="discord",
        platform_user_id="222",
    )


@pytest.fixture
def router() -> MemoryRouter:
    """Router with the shared mock client injected via module-level patch."""
    _reset_mock()
    # Patch Memory at module level — stays active for the entire fixture lifetime
    # (until yield returns, which is after the test completes).
    # _client_for() calls Memory() but the patch intercepts it.
    with patch("hermes_os.memory_router.Memory", return_value=_shared_mock_client):
        yield MemoryRouter()


# ---------------------------------------------------------------------------
# Init tests (no router fixture needed — these test __init__ in isolation)
# ---------------------------------------------------------------------------

class TestMemoryRouterInit:
    """Tests for MemoryRouter initialization."""

    def test_init_starts_with_empty_clients(self) -> None:
        """Router initializes with empty _clients dict."""
        with patch("hermes_os.memory_router.Memory"):
            router = MemoryRouter()
            assert router._clients == {}

    @pytest.mark.asyncio
    async def test_client_for_raises_without_mem0(self) -> None:
        """Router raises RuntimeError when _client_for is called and mem0 is unavailable."""
        with patch("hermes_os.memory_router.Memory", None):
            router = MemoryRouter()
            user = User(user_id="test", name="Test", platform="x", platform_user_id="1")
            with pytest.raises(RuntimeError, match="mem0"):
                await router.store(user, "memory")


# ---------------------------------------------------------------------------
# Store tests
# ---------------------------------------------------------------------------

class TestMemoryRouterStore:
    """Tests for MemoryRouter.store()."""

    @pytest.mark.asyncio
    async def test_store_calls_client_add(self, router: MemoryRouter, alice: User) -> None:
        """store() calls mem0 client's add() method."""
        await router.store(alice, "memory text")
        assert _shared_mock_client.add.await_count == 1

    @pytest.mark.asyncio
    async def test_store_passes_user_id(
        self, router: MemoryRouter, alice: User
    ) -> None:
        """store() passes the correct user_id to mem0.add()."""
        await router.store(alice, "I like Python", {"source": "chat"})

        _shared_mock_client.add.assert_awaited_once_with(
            "I like Python",
            user_id=alice.user_id,
            metadata={"source": "chat"},
        )

    @pytest.mark.asyncio
    async def test_store_passes_empty_metadata_when_none(
        self, router: MemoryRouter, bob: User
    ) -> None:
        """store() passes empty dict when metadata is None."""
        await router.store(bob, "Admin memory")

        _shared_mock_client.add.assert_awaited_once_with(
            "Admin memory",
            user_id=bob.user_id,
            metadata={},
        )

    @pytest.mark.asyncio
    async def test_store_multiple_calls_accumulate(
        self, router: MemoryRouter, alice: User
    ) -> None:
        """Multiple store() calls each trigger a separate add()."""
        await router.store(alice, "Memory 1")
        await router.store(alice, "Memory 2")
        assert _shared_mock_client.add.await_count == 2


# ---------------------------------------------------------------------------
# Search tests
# ---------------------------------------------------------------------------

class TestMemoryRouterSearch:
    """Tests for MemoryRouter.search()."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self, router: MemoryRouter, alice: User) -> None:
        """search() returns results from mem0 search."""
        _shared_mock_client.search = AsyncMock(
            return_value={"results": [{"memory": "Likes dark mode"}]}
        )

        results = await router.search(alice, "dark mode", limit=5)

        _shared_mock_client.search.assert_awaited_once_with(
            "dark mode", user_id=alice.user_id, limit=5
        )
        assert results == [{"memory": "Likes dark mode"}]

    @pytest.mark.asyncio
    async def test_search_uses_user_id_for_isolation(
        self, router: MemoryRouter, alice: User, bob: User
    ) -> None:
        """search() uses user_id so different users query their own namespace."""
        await router.search(alice, "query")
        await router.search(bob, "query")

        assert _shared_mock_client.search.await_count == 2
        calls = _shared_mock_client.search.await_args_list
        assert calls[0].kwargs["user_id"] == alice.user_id
        assert calls[1].kwargs["user_id"] == bob.user_id

    @pytest.mark.asyncio
    async def test_search_default_limit(self, router: MemoryRouter, alice: User) -> None:
        """search() defaults to limit=5 when not specified."""
        await router.search(alice, "query")
        call_args = _shared_mock_client.search.call_args
        assert call_args.kwargs["limit"] == 5

    @pytest.mark.asyncio
    async def test_search_handles_empty_results(
        self, router: MemoryRouter, alice: User
    ) -> None:
        """search() returns empty list when no results found."""
        _shared_mock_client.search = AsyncMock(return_value={"results": []})
        results = await router.search(alice, "nothing found")
        assert results == []


# ---------------------------------------------------------------------------
# get_all tests
# ---------------------------------------------------------------------------

class TestMemoryRouterGetAll:
    """Tests for MemoryRouter.get_all()."""

    @pytest.mark.asyncio
    async def test_get_all_returns_all_memories(
        self, router: MemoryRouter, alice: User
    ) -> None:
        """get_all() returns all memories for a user."""
        _shared_mock_client.get_all = AsyncMock(
            return_value={
                "results": [
                    {"memory": "First fact"},
                    {"memory": "Second fact"},
                ]
            }
        )

        results = await router.get_all(alice)

        _shared_mock_client.get_all.assert_awaited_once_with(user_id=alice.user_id)
        assert len(results) == 2
        assert results[0]["memory"] == "First fact"

    @pytest.mark.asyncio
    async def test_get_all_user_isolation(
        self, router: MemoryRouter, alice: User, bob: User
    ) -> None:
        """Different users' get_all() calls use their own user_id."""
        _shared_mock_client.get_all = AsyncMock(return_value={"results": []})

        await router.get_all(alice)
        await router.get_all(bob)

        calls = _shared_mock_client.get_all.await_args_list
        assert calls[0].kwargs["user_id"] == alice.user_id
        assert calls[1].kwargs["user_id"] == bob.user_id


# ---------------------------------------------------------------------------
# Cross-user isolation
# ---------------------------------------------------------------------------

class TestMemoryRouterCrossUser:
    """Verify memory isolation between users."""

    @pytest.mark.asyncio
    async def test_concurrent_users_have_separate_namespaces(
        self, alice: User, bob: User
    ) -> None:
        """Two users' store() calls route to their own namespaces via user_id."""
        client = MagicMock()
        client.add = AsyncMock()

        with patch("hermes_os.memory_router.Memory", return_value=client):
            router = MemoryRouter()
            await router.store(alice, "Alice memory")
            await router.store(bob, "Bob memory")

        calls = client.add.await_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["user_id"] == "alice_mid"
        assert calls[1].kwargs["user_id"] == "bob_mid"
        assert calls[0].kwargs["user_id"] != calls[1].kwargs["user_id"]
