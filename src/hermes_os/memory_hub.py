"""MemoryHub — 4-layer user memory for Hermes OS.

Layers:
- L1 Identity:     brain/USER.md        — user profile, role, team
- L2 Preferences:  brain/PREFERENCES.md — communication style, detail level, language
- L3 Recent:       MemoryRouter (mem0)  — recent conversations
- L4 Knowledge:     BrainIndexer         — wiki, long-term memory

This unifies the fragmented memory components (MemoryRouter, BrainIndexer,
BrainUpdater) into a single coherent interface for Main Hermes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hermes_os.brain_indexer import BrainIndex

logger = logging.getLogger(__name__)

# Default preference values when PREFERENCES.md doesn't exist
DEFAULT_PREFERENCES = {
    "communication_style": "neutral",  # "formal" | "casual" | "brief"
    "detail_level": "medium",          # "high" | "medium" | "low"
    "language": "auto",                 # "zh" | "en" | "auto"
    "tone": "neutral",                 # "technical" | "casual" | "neutral"
    "format": "markdown",             # "markdown" | "plain" | "card"
    "max_length": 2000,
    "timezone": "Asia/Shanghai",
    "active_hours": [9, 10, 11, 14, 15, 16, 17, 20, 21],
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ContextMemory:
    """Aggregated memory context from all 4 layers."""

    identity: dict[str, Any] = field(default_factory=dict)
    preferences: dict[str, Any] = field(default_factory=dict)
    recent_results: list[dict] = field(default_factory=list)
    long_term_results: list[dict] = field(default_factory=list)
    brain_index: "BrainIndex | None" = None


# ---------------------------------------------------------------------------
# L1: Identity Memory
# ---------------------------------------------------------------------------

class IdentityMemory:
    """L1: Reads/writes brain/USER.md.

    Stores: name, role, team, platform, created_at.
    """

    def __init__(self, user_id: str, base_path: Path | None = None) -> None:
        self.user_id = user_id
        self.base_path = base_path or (Path.home() / ".hermes" / "users")

    def _brain_path(self) -> Path:
        return self.base_path / self.user_id / "brain"

    def _user_md_path(self) -> Path:
        return self._brain_path() / "USER.md"

    async def load(self) -> dict[str, Any]:
        """Load user identity from brain/USER.md. Returns {} if not found."""
        path = self._user_md_path()
        if not path.exists():
            return {}
        try:
            content = path.read_text(encoding="utf-8")
            return self._parse_user_md(content)
        except Exception:
            return {}

    async def save(self, profile: dict[str, Any]) -> None:
        """Save user identity to brain/USER.md. Auto-creates directory."""
        brain_dir = self._brain_path()
        brain_dir.mkdir(parents=True, exist_ok=True)

        path = self._user_md_path()
        content = self._format_user_md(profile)
        await self._write_file(path, content)

    def _parse_user_md(self, content: str) -> dict[str, Any]:
        """Parse USER.md into a profile dict."""
        result: dict[str, Any] = {}
        for line in content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "：" in line:
                key_value = line.split("：", 1)
                if len(key_value) == 2:
                    result[key_value[0].strip()] = key_value[1].strip()
            elif "=" in line:
                key_value = line.split("=", 1)
                result[key_value[0].strip()] = key_value[1].strip()
        return result

    def _format_user_md(self, profile: dict[str, Any]) -> str:
        """Format a profile dict as USER.md."""
        lines = ["# User Identity\n"]
        for key, value in profile.items():
            lines.append(f"{key}：{value}")
        return "\n".join(lines)

    async def _write_file(self, path: Path, content: str) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, lambda: path.write_text(content, encoding="utf-8")
        )


# ---------------------------------------------------------------------------
# L2: Preferences Memory
# ---------------------------------------------------------------------------

class PreferencesMemory:
    """L2: Reads/writes brain/PREFERENCES.md.

    Stores: communication_style, detail_level, language, tone, format, etc.
    Falls back to DEFAULT_PREFERENCES when file doesn't exist.
    """

    def __init__(self, user_id: str, base_path: Path | None = None) -> None:
        self.user_id = user_id
        self.base_path = base_path or (Path.home() / ".hermes" / "users")

    def _brain_path(self) -> Path:
        return self.base_path / self.user_id / "brain"

    def _preferences_path(self) -> Path:
        return self._brain_path() / "PREFERENCES.md"

    async def load(self) -> dict[str, Any]:
        """Load preferences from brain/PREFERENCES.md.

        Returns DEFAULT_PREFERENCES if file doesn't exist or is empty.
        """
        path = self._preferences_path()
        if not path.exists():
            return dict(DEFAULT_PREFERENCES)
        try:
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                return dict(DEFAULT_PREFERENCES)
            data = json.loads(content)
            # Merge with defaults so all keys are present
            return {**DEFAULT_PREFERENCES, **data}
        except (json.JSONDecodeError, OSError):
            return dict(DEFAULT_PREFERENCES)

    async def save(self, preferences: dict[str, Any]) -> None:
        """Save preferences to brain/PREFERENCES.md. Auto-creates directory."""
        brain_dir = self._brain_path()
        brain_dir.mkdir(parents=True, exist_ok=True)

        path = self._preferences_path()
        # Merge with defaults before saving
        merged = {**DEFAULT_PREFERENCES, **preferences}
        content = json.dumps(merged, ensure_ascii=False, indent=2)
        await self._write_file(path, content)

    async def update(self, key: str, value: Any) -> None:
        """Update a single preference key."""
        prefs = await self.load()
        prefs[key] = value
        await self.save(prefs)

    async def _write_file(self, path: Path, content: str) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, lambda: path.write_text(content, encoding="utf-8")
        )


# ---------------------------------------------------------------------------
# L3: Recent Context Memory (mem0 wrapper)
# ---------------------------------------------------------------------------

class RecentContextMemory:
    """L3: Wraps MemoryRouter (mem0) for recent conversation context.

    Falls back to no-op when mem0 is unavailable.
    """

    def __init__(self, memory_router: Any) -> None:
        self._router = memory_router

    async def search(self, query: str, limit: int = 5) -> list[dict]:
        """Search recent context via mem0. Returns [] when mem0 unavailable."""
        if self._router is None:
            return []
        try:
            # MemoryRouter.search takes (user, query, limit)
            # We need to pass a mock User-like object with user_id
            class _DummyUser:
                user_id: str
            dummy_user = _DummyUser()
            dummy_user.user_id = getattr(self._router, "_user_id", "default")

            # Actually use the router directly since it doesn't need user context for search
            result = await self._router.search(query, limit=limit)
            return result
        except Exception as e:
            logger.warning("[RecentContextMemory] search failed: %s", e)
            return []

    async def store(self, content: str, metadata: dict | None = None) -> None:
        """Store a recent context entry via mem0. No-op when mem0 unavailable."""
        if self._router is None:
            return
        try:
            await self._router.store(content, metadata=metadata or {})
        except Exception as e:
            logger.warning("[RecentContextMemory] store failed: %s", e)


# ---------------------------------------------------------------------------
# L4: Knowledge Memory (BrainIndexer wrapper)
# ---------------------------------------------------------------------------

class KnowledgeMemory:
    """L4: Wraps BrainIndexer for long-term wiki knowledge search."""

    def __init__(self, brain_indexer: Any) -> None:
        self._indexer = brain_indexer

    async def search(self, query: str, limit: int = 5) -> list[dict]:
        """Search wiki knowledge via BrainIndexer. Returns [] when not found."""
        if self._indexer is None:
            return []
        try:
            results = await self._indexer.search_wiki(query=query)
            return results[:limit]
        except Exception as e:
            logger.warning("[KnowledgeMemory] search failed: %s", e)
            return []


# ---------------------------------------------------------------------------
# MemoryHub — Unified 4-layer interface
# ---------------------------------------------------------------------------

class MemoryHub:
    """Unified 4-layer memory interface for Main Hermes.

    Coordinates:
    - L1 Identity:   IdentityMemory (brain/USER.md)
    - L2 Preferences: PreferencesMemory (brain/PREFERENCES.md)
    - L3 Recent:     RecentContextMemory (mem0)
    - L4 Knowledge:   KnowledgeMemory (BrainIndexer)

    Example:
        hub = MemoryHub(user_id="u123")
        await hub.initialize()

        # Get all context for a user
        ctx = await hub.get_context()
        print(ctx.identity)      # L1: name, role, team
        print(ctx.preferences)   # L2: communication_style, etc.

        # Store a conversation
        await hub.store("用户问理财", layer="recent")

        # Learn a preference
        await hub.learn_preference("communication_style", "casual")
    """

    def __init__(
        self,
        user_id: str,
        base_path: Path | None = None,
        memory_router: Any = None,
        brain_indexer: Any = None,
        brain_updater: Any = None,
    ) -> None:
        self.user_id = user_id
        self.base_path = base_path or (Path.home() / ".hermes" / "users")

        # L1: Identity
        self._identity = IdentityMemory(user_id=user_id, base_path=self.base_path)

        # L2: Preferences
        self._preferences = PreferencesMemory(user_id=user_id, base_path=self.base_path)

        # L3: Recent context (mem0)
        if memory_router is None:
            try:
                from hermes_os.memory_router import MemoryRouter
                memory_router = MemoryRouter()
            except Exception:
                memory_router = None
        self._recent = RecentContextMemory(memory_router=memory_router)

        # L4: Knowledge (BrainIndexer)
        if brain_indexer is None:
            try:
                from hermes_os.brain_indexer import BrainIndexer
                brain_indexer = BrainIndexer()
            except Exception:
                brain_indexer = None
        self._knowledge = KnowledgeMemory(brain_indexer=brain_indexer)

        # Brain indexer reference for get_context
        self._brain_indexer = brain_indexer

    async def initialize(self) -> None:
        """Initialize layers. Idempotent — safe to call multiple times."""
        # All layers are lazy; initialize just validates paths exist
        brain_dir = self.base_path / self.user_id / "brain"
        brain_dir.mkdir(parents=True, exist_ok=True)

    async def get_context(self) -> ContextMemory:
        """Load all 4 layers and assemble into a ContextMemory.

        Returns:
            ContextMemory with identity, preferences, recent_results,
            long_term_results, and brain_index.
        """
        identity = await self._identity.load()
        preferences = await self._preferences.load()
        recent = await self._recent.search("", limit=10)
        knowledge = await self._knowledge.search("", limit=5)

        # Get full BrainIndex if available
        brain_index = None
        if self._brain_indexer is not None:
            try:
                brain_index = await self._brain_indexer.index_user(self.user_id)
            except Exception as e:
                logger.warning("[MemoryHub] BrainIndexer.index_user failed: %s", e)

        return ContextMemory(
            identity=identity,
            preferences=preferences,
            recent_results=recent or [],
            long_term_results=knowledge or [],
            brain_index=brain_index,
        )

    async def store(self, content: str, layer: str = "recent", metadata: dict | None = None) -> None:
        """Store content to the specified layer.

        Args:
            content: The content to store
            layer: Which layer to store to ("recent" or "knowledge")
            metadata: Optional metadata dict (used by L3)

        Raises:
            ValueError: if layer is unknown
        """
        if layer == "recent":
            await self._recent.store(content, metadata)
        elif layer == "knowledge":
            # L4 knowledge storage is task-output driven, not general-purpose
            logger.debug("[MemoryHub] knowledge layer storage not implemented (use BrainUpdater)")
        else:
            raise ValueError(f"Unknown memory layer: {layer!r}. Use 'recent' or 'knowledge'.")

    async def learn_preference(self, key: str, value: Any) -> None:
        """Update a single preference key and persist it.

        Args:
            key: Preference key (e.g., "communication_style")
            value: New value for this key
        """
        await self._preferences.update(key, value)

    async def get_preferences(self) -> dict[str, Any]:
        """Return the user's current preferences dict."""
        return await self._preferences.load()

    async def get_identity(self) -> dict[str, Any]:
        """Return the user's identity dict."""
        return await self._identity.load()
