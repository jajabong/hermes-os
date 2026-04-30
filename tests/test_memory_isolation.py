"""Tests for memory isolation between users."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from hermes_os.memory_router import MemoryRouter
from hermes_os.models import User


@pytest.fixture
def alice() -> User:
    return User(
        user_id="alice_test",
        name="Alice",
        role="user",
        team="alpha",
        platform="telegram",
        platform_user_id="111",
    )


@pytest.fixture
def bob() -> User:
    return User(
        user_id="bob_test",
        name="Bob",
        role="user",
        team="beta",
        platform="discord",
        platform_user_id="222",
    )


@pytest.mark.asyncio
async def test_memory_isolation(alice: User, bob: User) -> None:
    """Memory stores are isolated per user — alice cannot see bob's memories and vice versa."""
    mock_client = MagicMock()
    mock_client.add = AsyncMock()
    mock_client.search = AsyncMock(return_value={"results": []})
    mock_client.get_all = AsyncMock(return_value={"results": []})

    async def search_effect(query: str, *, filters: dict, limit: int = 5, **kwargs):
        user_id = filters.get("user_id", "")
        if user_id == alice.user_id:
            return {"results": [{"text": f"Alice memory for: {query}"}]}
        elif user_id == bob.user_id:
            return {"results": [{"text": f"Bob memory for: {query}"}]}
        return {"results": []}

    mock_client.search.side_effect = search_effect

    with patch("hermes_os.memory_router.Memory", return_value=mock_client):
        router = MemoryRouter()

        # Search for alice
        alice_results = await router.search(alice, "project")
        # Search for bob
        bob_results = await router.search(bob, "project")

        # Verify searches used correct user filters
        assert mock_client.search.call_count == 2
        calls = mock_client.search.call_args_list

        alice_call_filters = calls[0].kwargs.get("filters", {})
        bob_call_filters = calls[1].kwargs.get("filters", {})

        assert alice_call_filters.get("user_id") == alice.user_id
        assert bob_call_filters.get("user_id") == bob.user_id

        # Verify results are user-specific (no cross-contamination)
        alice_content = str(alice_results)
        bob_content = str(bob_results)

        # Results must be different per user
        assert alice_content != bob_content or alice_content == ""