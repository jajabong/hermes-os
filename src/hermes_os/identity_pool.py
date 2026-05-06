"""Identity_Pool — Multi-platform, multi-identity session management.

Manages sessions for:
- Amazon KDP (publication empire)
- Patent offices (patent empire)
- TikTok/YouTube (short drama empire)
- Social media accounts (multi-platform presence)

Each identity has:
- platform: str (e.g., "amazon_kdp", "us_patent_office", "tiktok")
- identity_id: str (unique within platform)
- session_token: str (authentication token)
- status: str ("active", "suspended", "expired")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Identity:
    """A registered platform identity with session."""

    platform: str
    identity_id: str
    session_token: str
    status: str = "active"
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_active(self) -> bool:
        """Check if identity is active and usable."""
        return self.status == "active"


class IdentityPool:
    """
    Pool of platform identities for multi-account operations.

    Usage:
        pool = IdentityPool()
        pool.register("amazon_kdp", "alice-001", "session_token_xyz")
        identity = pool.get_identity("amazon_kdp", "alice-001")
        pool.mark_used("amazon_kdp", "alice-001")
    """

    def __init__(self) -> None:
        # _identities[platform][identity_id] = Identity
        self._identities: dict[str, dict[str, Identity]] = {}

    def register(
        self,
        platform: str,
        identity_id: str,
        session_token: str,
        **metadata: Any,
    ) -> Identity:
        """
        Register a new platform identity.

        Args:
            platform: Platform name (e.g., "amazon_kdp", "patent_office")
            identity_id: Unique ID within platform
            session_token: Authentication token
            **metadata: Additional metadata (email, name, etc.)

        Returns:
            The created Identity object
        """
        if platform not in self._identities:
            self._identities[platform] = {}

        identity = Identity(
            platform=platform,
            identity_id=identity_id,
            session_token=session_token,
            metadata=metadata,
        )
        self._identities[platform][identity_id] = identity
        logger.debug("Registered identity: %s/%s", platform, identity_id)
        return identity

    def get_identity(self, platform: str, identity_id: str) -> Identity | None:
        """
        Get an identity by platform and ID.

        Returns None if not found.
        """
        platform_identities = self._identities.get(platform, {})
        identity = platform_identities.get(identity_id)
        if identity:
            identity.last_used = time.time()
        return identity

    def list_identities(self, platform: str) -> list[str]:
        """List all identity IDs for a platform."""
        return list(self._identities.get(platform, {}).keys())

    def get_active_identity(self, platform: str) -> Identity | None:
        """
        Get the most recently used active identity for a platform.

        Useful for round-robin session selection.
        """
        platform_identities = self._identities.get(platform, {})
        active = [i for i in platform_identities.values() if i.is_active()]
        if not active:
            return None
        return max(active, key=lambda i: i.last_used)

    def mark_used(self, platform: str, identity_id: str) -> None:
        """Mark an identity as recently used."""
        identity = self.get_identity(platform, identity_id)
        if identity:
            identity.last_used = time.time()

    def mark_suspended(self, platform: str, identity_id: str) -> None:
        """Mark an identity as suspended."""
        identity = self.get_identity(platform, identity_id)
        if identity:
            identity.status = "suspended"
            logger.warning("Identity %s/%s marked suspended", platform, identity_id)

    def mark_expired(self, platform: str, identity_id: str) -> None:
        """Mark an identity as expired."""
        identity = self.get_identity(platform, identity_id)
        if identity:
            identity.status = "expired"
            logger.warning("Identity %s/%s marked expired", platform, identity_id)

    def remove(self, platform: str, identity_id: str) -> bool:
        """Remove an identity from the pool."""
        if platform in self._identities:
            if identity_id in self._identities[platform]:
                del self._identities[platform][identity_id]
                return True
        return False

    def list_platforms(self) -> list[str]:
        """List all registered platforms."""
        return list(self._identities.keys())

    def stats(self) -> dict[str, Any]:
        """Get pool statistics."""
        total = sum(len(ids) for ids in self._identities.values())
        active = sum(1 for ids in self._identities.values() for i in ids.values() if i.is_active())
        return {
            "total_identities": total,
            "active_identities": active,
            "platforms": len(self._identities),
        }
