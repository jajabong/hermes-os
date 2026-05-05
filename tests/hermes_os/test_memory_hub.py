"""Tests for memory_hub.py — TDD for 4-layer user memory."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hermes_os.memory_hub import (
    MemoryHub,
    ContextMemory,
    IdentityMemory,
    PreferencesMemory,
    RecentContextMemory,
    KnowledgeMemory,
)


# ---------------------------------------------------------------------------
# Layer unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_identity_memory_read_write(tmp_path: Path) -> None:
    """IdentityMemory should read/write brain/USER.md."""
    uid = "test_user_identity"
    brain_dir = tmp_path / uid / "brain"
    brain_dir.mkdir(parents=True)

    identity = IdentityMemory(user_id=uid, base_path=tmp_path)
    await identity.save({"name": "张三", "role": "admin", "team": "ai"})

    loaded = await identity.load()
    assert loaded["name"] == "张三"
    assert loaded["role"] == "admin"
    assert loaded["team"] == "ai"


@pytest.mark.asyncio
async def test_identity_memory_load_empty_when_no_file(tmp_path: Path) -> None:
    """load() should return {} when brain/USER.md doesn't exist."""
    identity = IdentityMemory(user_id="ghost_user", base_path=tmp_path)
    result = await identity.load()
    assert result == {}


@pytest.mark.asyncio
async def test_preferences_memory_read_write(tmp_path: Path) -> None:
    """PreferencesMemory should read/write brain/PREFERENCES.md."""
    uid = "test_user_prefs"
    brain_dir = tmp_path / uid / "brain"
    brain_dir.mkdir(parents=True)

    prefs = PreferencesMemory(user_id=uid, base_path=tmp_path)
    await prefs.save({
        "communication_style": "casual",
        "detail_level": "high",
        "language": "zh",
    })

    loaded = await prefs.load()
    assert loaded["communication_style"] == "casual"
    assert loaded["detail_level"] == "high"
    assert loaded["language"] == "zh"


@pytest.mark.asyncio
async def test_preferences_memory_load_returns_defaults_when_no_file(tmp_path: Path) -> None:
    """load() should return DEFAULT_PREFERENCES when brain/PREFERENCES.md doesn't exist."""
    prefs = PreferencesMemory(user_id="ghost_user", base_path=tmp_path)
    result = await prefs.load()
    # Returns DEFAULT_PREFERENCES for graceful degradation (not {})
    assert result["communication_style"] == "neutral"
    assert result["detail_level"] == "medium"


@pytest.mark.asyncio
async def test_preferences_memory_default_values() -> None:
    """load() should return default preference values when file exists but is empty-ish."""
    # PreferencesMemory falls back to defaults when no file
    prefs = PreferencesMemory(user_id="ghost", base_path=Path("/tmp/nonexistent"))
    result = await prefs.load()
    # Should return default values
    assert "communication_style" in result
    assert "detail_level" in result


@pytest.mark.asyncio
async def test_recent_context_search_delegates_to_mem0() -> None:
    """RecentContextMemory.search() should delegate to MemoryRouter."""
    mock_router = MagicMock()
    mock_router.search = AsyncMock(return_value=[
        {"text": "用户上次说要理财", "metadata": {"type": "preference"}}
    ])

    recent = RecentContextMemory(memory_router=mock_router)
    results = await recent.search("理财", limit=3)

    mock_router.search.assert_called_once()
    assert len(results) == 1
    assert "理财" in results[0]["text"]


@pytest.mark.asyncio
async def test_recent_context_search_falls_back_when_no_mem0() -> None:
    """RecentContextMemory.search() should return [] when mem0 unavailable."""
    recent = RecentContextMemory(memory_router=None)
    results = await recent.search("理财", limit=3)
    assert results == []


@pytest.mark.asyncio
async def test_recent_context_store_delegates_to_mem0() -> None:
    """RecentContextMemory.store() should delegate to MemoryRouter."""
    mock_router = MagicMock()
    mock_router.store = AsyncMock()

    recent = RecentContextMemory(memory_router=mock_router)
    await recent.store("用户说想要理财", metadata={"topic": "investment"})

    mock_router.store.assert_called_once()


@pytest.mark.asyncio
async def test_knowledge_memory_search_delegates_to_brain_indexer() -> None:
    """KnowledgeMemory.search() should delegate to BrainIndexer."""
    mock_indexer = MagicMock()
    mock_indexer.search_wiki = AsyncMock(return_value=[
        {"category": "项目", "file": "AI研究", "snippet": "...关于AI的分析..."}
    ])

    knowledge = KnowledgeMemory(brain_indexer=mock_indexer)
    results = await knowledge.search("AI", limit=5)

    mock_indexer.search_wiki.assert_called_once()
    assert len(results) == 1
    assert results[0]["category"] == "项目"


@pytest.mark.asyncio
async def test_knowledge_memory_search_returns_empty_when_no_results() -> None:
    """KnowledgeMemory.search() should return [] when BrainIndexer returns nothing."""
    mock_indexer = MagicMock()
    mock_indexer.search_wiki = AsyncMock(return_value=[])

    knowledge = KnowledgeMemory(brain_indexer=mock_indexer)
    results = await knowledge.search("nonexistent_topic", limit=5)
    assert results == []


# ---------------------------------------------------------------------------
# MemoryHub integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_hub_initializes_all_layers(tmp_path: Path) -> None:
    """MemoryHub should initialize all 4 layers without error."""
    hub = MemoryHub(user_id="test_user", base_path=tmp_path)
    await hub.initialize()

    assert hub._identity is not None
    assert hub._preferences is not None
    assert hub._recent is not None
    assert hub._knowledge is not None


@pytest.mark.asyncio
async def test_memory_hub_get_context_assembles_all_layers(tmp_path: Path) -> None:
    """get_context() should return ContextMemory with all layers populated."""
    hub = MemoryHub(user_id="test_user_ctx", base_path=tmp_path)
    await hub.initialize()

    # Pre-populate identity and preferences
    await hub._identity.save({"name": "李四", "role": "user"})
    await hub._preferences.save({"communication_style": "brief"})

    ctx = await hub.get_context()

    assert isinstance(ctx, ContextMemory)
    assert ctx.identity["name"] == "李四"
    assert ctx.preferences["communication_style"] == "brief"
    assert isinstance(ctx.recent_results, list)
    assert isinstance(ctx.long_term_results, list)


@pytest.mark.asyncio
async def test_memory_hub_learn_preference_updates_preferences(tmp_path: Path) -> None:
    """learn_preference() should update the preferences layer."""
    hub = MemoryHub(user_id="test_user_learn", base_path=tmp_path)
    await hub.initialize()

    await hub.learn_preference("communication_style", "casual")
    await hub.learn_preference("detail_level", "low")

    prefs = await hub._preferences.load()
    assert prefs["communication_style"] == "casual"
    assert prefs["detail_level"] == "low"


@pytest.mark.asyncio
async def test_memory_hub_store_to_recent_layer(tmp_path: Path) -> None:
    """store(content, layer='recent') should delegate to RecentContextMemory."""
    mock_router = MagicMock()
    mock_router.store = AsyncMock()
    mock_router.search = AsyncMock(return_value=[])

    hub = MemoryHub(user_id="test_user_store", base_path=tmp_path, memory_router=mock_router)
    await hub.initialize()

    await hub.store("用户今天问了投资问题", layer="recent", metadata={"topic": "investment"})

    mock_router.store.assert_called_once()


@pytest.mark.asyncio
async def test_memory_hub_store_unknown_layer_raises(tmp_path: Path) -> None:
    """store(content, layer='unknown') should raise ValueError."""
    hub = MemoryHub(user_id="test_user_unknown_layer", base_path=tmp_path)
    await hub.initialize()

    with pytest.raises(ValueError, match="Unknown memory layer"):
        await hub.store("some content", layer="unknown_layer")


@pytest.mark.asyncio
async def test_memory_hub_graceful_degradation_no_mem0(tmp_path: Path) -> None:
    """MemoryHub should work even when mem0 (L3) is unavailable."""
    hub = MemoryHub(user_id="test_user_no_mem0", base_path=tmp_path, memory_router=None)
    await hub.initialize()

    # L3 should return empty list gracefully
    ctx = await hub.get_context()
    assert isinstance(ctx.recent_results, list)
    # Should not raise


@pytest.mark.asyncio
async def test_context_memory_defaults() -> None:
    """ContextMemory should have sensible defaults."""
    ctx = ContextMemory(
        identity={},
        preferences={},
        recent_results=[],
        long_term_results=[],
    )
    assert ctx.identity == {}
    assert ctx.recent_results == []


@pytest.mark.asyncio
async def test_identity_memory_creates_brain_directory(tmp_path: Path) -> None:
    """IdentityMemory should auto-create brain directory on save."""
    uid = "new_user_auto_create"
    brain_dir = tmp_path / uid / "brain"

    identity = IdentityMemory(user_id=uid, base_path=tmp_path)
    assert not brain_dir.exists()

    await identity.save({"name": "王五"})

    assert brain_dir.exists()
    assert (brain_dir / "USER.md").exists()


@pytest.mark.asyncio
async def test_preferences_memory_creates_brain_directory(tmp_path: Path) -> None:
    """PreferencesMemory should auto-create brain directory on save."""
    uid = "new_user_prefs_auto"
    brain_dir = tmp_path / uid / "brain"

    prefs = PreferencesMemory(user_id=uid, base_path=tmp_path)
    assert not brain_dir.exists()

    await prefs.save({"communication_style": "formal"})

    assert brain_dir.exists()
    assert (brain_dir / "PREFERENCES.md").exists()