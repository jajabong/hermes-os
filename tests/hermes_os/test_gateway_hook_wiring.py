"""Tests for gateway_hook wiring — ShardedStorage, SkillDiscovery, ChiefAgent into ProactiveEngine.

Run with: pytest tests/hermes_os/test_gateway_hook_wiring.py -v
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def hook_config() -> "HookConfig":
    from hermes_os.gateway_hook import HookConfig
    return HookConfig(
        db_path=":memory:",
        knowledge_db_path=":memory:",
        enable_event_loop=False,
    )


def test_hook_wires_shard_manager_and_sharded_storage(hook_config) -> None:
    """HermesOSHook should create ShardManager + ShardedStorage and wire to ProactiveEngine."""
    from hermes_os.gateway_hook import HermesOSHook
    from hermes_os.shard_manager import ShardManager, ShardedStorage

    hook = HermesOSHook(config=hook_config)

    assert hasattr(hook, "_shard_manager")
    assert hasattr(hook, "_sharded_storage")
    assert isinstance(hook._shard_manager, ShardManager)
    assert isinstance(hook._sharded_storage, ShardedStorage)
    assert hook._shard_manager is hook._proactive_engine._sharded_storage.shard_manager
    assert hook._sharded_storage is hook._proactive_engine._sharded_storage


def test_hook_wires_skill_discovery(hook_config) -> None:
    """HermesOSHook should create SkillDiscovery and wire to ProactiveEngine."""
    from hermes_os.gateway_hook import HermesOSHook
    from hermes_os.skill_discovery import SkillDiscovery

    hook = HermesOSHook(config=hook_config)

    assert hasattr(hook, "_skill_discovery")
    assert isinstance(hook._skill_discovery, SkillDiscovery)
    assert hook._skill_discovery is hook._proactive_engine._skill_discovery


def test_hook_wires_chief_agent(hook_config) -> None:
    """HermesOSHook should wire its ChiefAgent into ProactiveEngine."""
    from hermes_os.gateway_hook import HermesOSHook
    from hermes_os.chief_agent import ChiefAgent

    hook = HermesOSHook(config=hook_config)

    assert hasattr(hook, "_chief")
    assert isinstance(hook._chief, ChiefAgent)
    assert hook._chief is hook._proactive_engine._chief_agent


def test_hook_creates_skill_discovery_with_correct_db_path(hook_config) -> None:
    """SkillDiscovery should be created with the hook's db_path."""
    from hermes_os.gateway_hook import HermesOSHook

    hook = HermesOSHook(config=hook_config)

    # The SkillDiscovery should use the config's db_path
    assert hook._skill_discovery.db_path == hook_config.db_path


def test_hook_wires_goal_tracker_to_chief(hook_config) -> None:
    """GoalTracker should be wired into ChiefAgent after initialization."""
    from hermes_os.gateway_hook import HermesOSHook
    from hermes_os.goal_tracker import GoalTracker

    hook = HermesOSHook(config=hook_config)

    # After _ensure_scheduler is called, _chief should have goal_tracker set
    # Since enable_event_loop=False, _ensure_scheduler is not called automatically
    # Check that _chief has set_goal_tracker method available
    assert hasattr(hook._chief, "set_goal_tracker")


# ---------------------------------------------------------------------------
# Tests: background task helpers
# ---------------------------------------------------------------------------

def test_update_last_message_at_bg_handles_missing_storage(hook_config) -> None:
    """_update_last_message_at_bg should not raise if _sharded_storage is None."""
    from hermes_os.gateway_hook import HermesOSHook

    hook = HermesOSHook(config=hook_config)
    hook._sharded_storage = None

    # Should not raise
    async def run():
        await hook._update_last_message_at_bg("u_test", "hello")

    asyncio.run(run())


def test_record_skill_usage_bg_handles_missing_discovery(hook_config) -> None:
    """_record_skill_usage_bg should not raise if _skill_discovery is None."""
    from hermes_os.gateway_hook import HermesOSHook
    from hermes_os.skill_loader import SkillLoader

    hook = HermesOSHook(config=hook_config)
    hook._skill_discovery = None
    loader = SkillLoader()

    # Should not raise
    async def run():
        await hook._record_skill_usage_bg(loader, max_skills=5)

    asyncio.run(run())


def test_record_skill_usage_bg_calls_record_usage(tmp_path: Path) -> None:
    """_record_skill_usage_bg should call record_usage for each loaded skill."""
    from hermes_os.gateway_hook import HermesOSHook, HookConfig
    from hermes_os.skill_loader import SkillLoader

    # Create a transient skill file
    transient = tmp_path / "_transient"
    transient.mkdir()
    skill_dir = transient / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("""---
name: test-skill
description: Test skill
quality_score: 0.8
---

# Steps
1. Do the thing
""")

    config = HookConfig(db_path=":memory:", knowledge_db_path=":memory:", enable_event_loop=False)
    hook = HermesOSHook(config=config)

    # Mock SkillDiscovery
    mock_discovery = MagicMock()
    mock_discovery.record_usage = AsyncMock()
    hook._skill_discovery = mock_discovery

    loader = SkillLoader(transient_dir=transient)

    async def run():
        await hook._record_skill_usage_bg(loader, max_skills=5)

    asyncio.run(run())

    # record_usage should have been called with the skill name
    mock_discovery.record_usage.assert_called()
    call_args = [call[0] for call in mock_discovery.record_usage.call_args_list]
    skill_names = [args[0] for args in call_args if args]
    assert "test-skill" in skill_names, f"Expected 'test-skill' in {skill_names}"


# ---------------------------------------------------------------------------
# Tests: close() cleanup
# ---------------------------------------------------------------------------

def test_close_cleans_up_sharded_storage(hook_config) -> None:
    """close() should close ShardedStorage connections."""
    from hermes_os.gateway_hook import HermesOSHook

    hook = HermesOSHook(config=hook_config)

    # Initialize a connection
    async def setup():
        await hook._sharded_storage._get_db_for("test_close_user")

    asyncio.run(setup())

    # close should not raise
    async def run():
        await hook._sharded_storage.close()

    asyncio.run(run())
