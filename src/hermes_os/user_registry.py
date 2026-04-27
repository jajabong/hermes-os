"""User identity and routing with persistence."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from hermes_os.models import User
from hermes_os.storage import Storage


class UserRegistry:
    """User registry with SQLite persistence."""

    def __init__(self, storage: Storage | None = None) -> None:
        self.storage = storage or Storage()
        self._users_cache: dict[str, User] = {}

    def register(self, user: User) -> None:
        """Cache user in memory. Database sync happens in upsert."""
        self._users_cache[user.user_id] = user

    def get(self, user_id: str) -> User | None:
        return self._users_cache.get(user_id)

    def get_by_platform(self, platform: str, platform_user_id: str) -> User | None:
        """Look up user by platform identity (from cache)."""
        for user in self._users_cache.values():
            if user.platform == platform and user.platform_user_id == platform_user_id:
                return user
        return None

    async def upsert_from_pairing(
        self,
        platform: str,
        platform_user_id: str,
        name: str,
        role: str = "user",
        team: str = "default",
    ) -> User:
        """Register or update a user from gateway pairing event with persistence."""
        # 1. Try cache
        existing = self.get_by_platform(platform, platform_user_id)

        # 2. Try database if not in cache
        if not existing:
            row = await self.storage.get_user_by_platform(platform, platform_user_id)
            if row:
                existing = User(
                    user_id=row["user_id"],
                    name=row["name"],
                    role=row["role"],
                    team=row["team"],
                    platform=row["platform"],
                    platform_user_id=row["platform_user_id"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                self.register(existing)

        if existing:
            if existing.name != name:
                existing.name = name
                await self.storage.save_user(existing.__dict__)
            return existing

        # 3. Create new
        user_id = self._make_user_id(platform, platform_user_id)
        user = User(
            user_id=user_id,
            name=name,
            role=role,
            team=team,
            platform=platform,
            platform_user_id=platform_user_id,
            created_at=datetime.now(UTC),
        )
        self.register(user)
        await self.storage.save_user(user.__dict__)
        return user

    @staticmethod
    def _make_user_id(platform: str, platform_user_id: str) -> str:
        raw = f"{platform}:{platform_user_id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
