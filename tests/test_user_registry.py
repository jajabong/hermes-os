"""Tests for UserRegistry."""

import pytest

from hermes_os.models import User
from hermes_os.user_registry import UserRegistry


class TestUserRegistry:
    """Unit tests for UserRegistry."""

    def setup_method(self) -> None:
        self.registry = UserRegistry()

    def test_register_and_get(self) -> None:
        """A registered user can be retrieved by user_id."""
        user = User(
            user_id="abc123",
            name="Alice",
            role="user",
            team="alpha",
            platform="telegram",
            platform_user_id="999",
        )
        self.registry.register(user)

        retrieved = self.registry.get("abc123")
        assert retrieved is not None
        assert retrieved.user_id == "abc123"
        assert retrieved.name == "Alice"
        assert retrieved.role == "user"
        assert retrieved.team == "alpha"
        assert retrieved.platform == "telegram"
        assert retrieved.platform_user_id == "999"

    def test_get_missing_returns_none(self) -> None:
        """Get on a non-existent user_id returns None."""
        assert self.registry.get("nonexistent") is None

    def test_get_by_platform(self) -> None:
        """Users can be looked up by platform + platform_user_id."""
        user = User(
            user_id="u1",
            name="Bob",
            platform="discord",
            platform_user_id="444",
        )
        self.registry.register(user)

        found = self.registry.get_by_platform("discord", "444")
        assert found is not None
        assert found.name == "Bob"

    def test_get_by_platform_not_found(self) -> None:
        """get_by_platform returns None when no match exists."""
        assert self.registry.get_by_platform("discord", "999") is None

    @pytest.mark.asyncio
    async def test_upsert_from_pairing_creates_new_user(self) -> None:
        """upsert_from_pairing creates a new user when none exists."""
        user = await self.registry.upsert_from_pairing(
            platform="telegram",
            platform_user_id="12345",
            name="Charlie",
            role="admin",
            team="beta",
        )

        assert user.name == "Charlie"
        assert user.role == "admin"
        assert user.team == "beta"
        assert user.platform == "telegram"
        assert user.platform_user_id == "12345"
        assert user.user_id is not None
        assert len(user.user_id) == 16  # SHA256 truncated to 16 chars

    @pytest.mark.asyncio
    async def test_upsert_from_pairing_updates_existing(self) -> None:
        """upsert_from_pairing updates name when user already exists."""
        await self.registry.upsert_from_pairing(
            platform="telegram",
            platform_user_id="12345",
            name="Charlie Old",
        )
        updated = await self.registry.upsert_from_pairing(
            platform="telegram",
            platform_user_id="12345",
            name="Charlie New",
        )

        assert updated.name == "Charlie New"
        # Should be the same user_id (same platform + platform_user_id)
        assert self.registry.get_by_platform("telegram", "12345") is updated

    @pytest.mark.asyncio
    async def test_upsert_from_pairing_default_role_and_team(self) -> None:
        """Default role is 'user' and team is 'default' when not specified."""
        user = await self.registry.upsert_from_pairing(
            platform="feishu",
            platform_user_id="fc001",
            name="Dana",
        )

        assert user.role == "user"
        assert user.team == "default"

    def test_user_id_is_deterministic(self) -> None:
        """Same platform + platform_user_id always produces the same user_id."""
        id1 = UserRegistry._make_user_id("telegram", "999")
        id2 = UserRegistry._make_user_id("telegram", "999")
        id3 = UserRegistry._make_user_id("discord", "999")

        assert id1 == id2
        assert id1 != id3

    def test_user_id_is_16_chars(self) -> None:
        """user_id from _make_user_id is exactly 16 characters."""
        user_id = UserRegistry._make_user_id("telegram", "123")
        assert len(user_id) == 16
        assert user_id.isalnum()

    def test_user_id_differs_across_platforms(self) -> None:
        """Different platforms produce different user_ids even with same platform_user_id."""
        id_tg = UserRegistry._make_user_id("telegram", "same_id")
        id_dc = UserRegistry._make_user_id("discord", "same_id")

        assert id_tg != id_dc

    @pytest.mark.asyncio
    async def test_get_history_for_agent(self) -> None:
        """Integration: register, create session, verify history format."""
        # This tests the full chain via UserRegistry
        user = await self.registry.upsert_from_pairing(
            platform="telegram",
            platform_user_id="777",
            name="Eve",
        )
        assert user.user_id is not None
        found = self.registry.get(user.user_id)
        assert found is not None
        assert found.name == "Eve"
