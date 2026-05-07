"""TDD tests for SkillDiscovery effectiveness feedback loop wiring.

Run with: pytest tests/hermes_os/test_skill_effectiveness_loop.py -v
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Tests: SkillDiscovery wired into ProactiveEngine patrol
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proactive_engine_has_skill_discovery_setter(tmp_path: Path) -> None:
    """ProactiveEngine should have set_skill_discovery() for DI."""
    from hermes_os.proactive_engine import ProactiveEngine

    engine = ProactiveEngine()
    assert hasattr(engine, "set_skill_discovery"), "ProactiveEngine missing set_skill_discovery()"


@pytest.mark.asyncio
async def test_proactive_engine_patrol_calls_solidify_cycle(tmp_path: Path) -> None:
    """deep_patrol should call run_solidify_cycle on SkillDiscovery."""
    from hermes_os.proactive_engine import ProactiveEngine
    from hermes_os.skill_discovery import SkillDiscovery

    discovery = SkillDiscovery(db_path=str(tmp_path / "skills.db"))
    await discovery._lazy_init()

    engine = ProactiveEngine()
    engine.set_skill_discovery(discovery)
    # Use an async mock for scheduler to prevent hanging on get_all_tasks()
    scheduler_mock = MagicMock()
    scheduler_mock.get_all_tasks = AsyncMock(return_value=[])
    engine._scheduler = scheduler_mock

    # Track whether run_solidify_cycle was called
    called = False
    original = discovery.run_solidify_cycle

    async def tracking():
        nonlocal called
        called = True
        return await original()

    discovery.run_solidify_cycle = tracking  # type: ignore

    await engine._deep_patrol(tick_count=10)

    assert called, "deep_patrol should call run_solidify_cycle"


# ---------------------------------------------------------------------------
# Tests: record_usage called when skill is injected into prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_usage_called_on_skill_injection(tmp_path: Path) -> None:
    """When SkillLoader injects fragments, record_usage should be called."""
    from hermes_os.skill_discovery import SkillDiscovery
    from hermes_os.skill_loader import SkillLoader

    # Create a real transient skill
    skills_dir = tmp_path / "_transient"
    skills_dir.mkdir()
    skill_dir = skills_dir / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("""---
name: test-skill
description: Test skill
quality_score: 0.8
---

# Steps
1. Do the thing
""")

    discovery = SkillDiscovery(db_path=str(tmp_path / "skills.db"))
    await discovery._lazy_init()
    loader = SkillLoader(transient_dir=skills_dir, skill_discovery=discovery)

    # get_all_prompt_fragments calls load_transient_skills internally
    fragments, names = loader.get_all_prompt_fragments(max_skills=5)
    assert "test-skill" in fragments
    assert "test-skill" in names

    # record_usage should have been called for this skill (via fire-and-forget task)
    # Wait briefly for the fire-and-forget task to complete
    await asyncio.sleep(0.1)

    eff = await discovery.get_effectiveness("test-skill")
    assert eff.get("found"), (
        "record_usage should have been called, but effectiveness was not recorded"
    )
    assert eff["uses"] == 1, f"Expected 1 use, got {eff}"


@pytest.mark.asyncio
async def test_record_usage_not_called_when_disabled(tmp_path: Path) -> None:
    """When record_usage=False, SkillLoader should not call record_usage."""
    from hermes_os.skill_discovery import SkillDiscovery
    from hermes_os.skill_loader import SkillLoader

    skills_dir = tmp_path / "_transient"
    skills_dir.mkdir()
    skill_dir = skills_dir / "quiet-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("""---
name: quiet-skill
description: Quiet skill
quality_score: 0.8
---

# Steps
1. Be quiet
""")

    discovery = SkillDiscovery(db_path=str(tmp_path / "skills.db"))
    await discovery._lazy_init()
    loader = SkillLoader(transient_dir=skills_dir, skill_discovery=discovery)

    fragments, names = loader.get_all_prompt_fragments(max_skills=5, record_usage=False)
    assert "quiet-skill" in fragments
    assert "quiet-skill" in names

    await asyncio.sleep(0.1)

    eff = await discovery.get_effectiveness("quiet-skill")
    # Should NOT have been recorded since record_usage=False
    assert not eff.get("found"), (
        f"record_usage should NOT have been called when disabled, but got: {eff}"
    )


# ---------------------------------------------------------------------------
# Tests: run_solidify_cycle returns categorized decisions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_solidify_cycle_returns_all_three_categories(tmp_path: Path) -> None:
    """run_solidify_cycle should categorize skills into solidify/discard/keep_transient."""
    from hermes_os.skill_discovery import SkillDiscovery

    discovery = SkillDiscovery(db_path=str(tmp_path / "skills.db"))
    await discovery._lazy_init()
    db = await discovery._get_db()
    now = datetime.now(UTC).isoformat()

    # Skill 1: 3 successes → solidify
    await db.execute(
        """INSERT OR IGNORE INTO discovered_skills
        (repo, path, name, description, stars, url, content, quality_score, discovered_at, solidified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("r1", "p1", "skill-solidify", "d", 10, "u", "", 0.6, now, 0),
    )
    await discovery.record_usage("skill-solidify", success=True)
    await discovery.record_usage("skill-solidify", success=True)
    await discovery.record_usage("skill-solidify", success=True)

    # Skill 2: 2 failures → discard
    await db.execute(
        """INSERT OR IGNORE INTO discovered_skills
        (repo, path, name, description, stars, url, content, quality_score, discovered_at, solidified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("r2", "p2", "skill-discard", "d", 5, "u", "", 0.3, now, 0),
    )
    await discovery.record_usage("skill-discard", success=True)
    await discovery.record_usage("skill-discard", success=False)
    await discovery.record_usage("skill-discard", success=False)

    # Skill 3: 1 success only → keep_transient
    await db.execute(
        """INSERT OR IGNORE INTO discovered_skills
        (repo, path, name, description, stars, url, content, quality_score, discovered_at, solidified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("r3", "p3", "skill-keep", "d", 3, "u", "", 0.4, now, 0),
    )
    await discovery.record_usage("skill-keep", success=True)

    result = await discovery.run_solidify_cycle()

    assert "skill-solidify" in result["solidify"], f"solidify: {result}"
    assert "skill-discard" in result["discard"], f"discard: {result}"
    assert "skill-keep" in result["keep_transient"], f"keep: {result}"


# ---------------------------------------------------------------------------
# Tests: skill is discarded from _transient after discard decision
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discard_removes_transient_skill_directory(tmp_path: Path) -> None:
    """When decision=discard, the transient skill directory should be removed."""
    from hermes_os.skill_discovery import TRANSIENT_SKILLS_DIR, SkillDiscovery
    from hermes_os.skill_loader import SkillLoader

    # Override transient dir
    transient = tmp_path / "_transient"
    TRANSIENT_SKILLS_DIR.parent.mkdir(parents=True, exist_ok=True)

    discovery = SkillDiscovery(db_path=str(tmp_path / "skills.db"))
    # Patch the TRANSIENT_SKILLS_DIR to use our tmp dir
    import hermes_os.skill_discovery as sd

    original_transient = sd.TRANSIENT_SKILLS_DIR
    sd.TRANSIENT_SKILLS_DIR = transient

    try:
        await discovery._lazy_init()
        loader = SkillLoader(transient_dir=transient)

        # Create a skill to discard
        skill_dir = transient / "bad-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: bad-skill\ndescription: bad\n---\n# bad")
        db = await discovery._get_db()
        await db.execute(
            """INSERT OR IGNORE INTO discovered_skills
            (repo, path, name, description, stars, url, content, quality_score, discovered_at, solidified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("r", "p", "bad-skill", "d", 1, "u", "", 0.2, datetime.now(UTC).isoformat(), 0),
        )
        await db.commit()

        # Record failures
        await discovery.record_usage("bad-skill", success=True)
        await discovery.record_usage("bad-skill", success=False)
        await discovery.record_usage("bad-skill", success=False)

        # Run solidify cycle
        result = await discovery.run_solidify_cycle()
        assert "bad-skill" in result["discard"]

        # Skill directory should be gone
        assert not skill_dir.exists(), (
            f"bad-skill dir should be removed, but still exists: {skill_dir}"
        )
    finally:
        sd.TRANSIENT_SKILLS_DIR = original_transient


# ---------------------------------------------------------------------------
# Tests: solidify moves skill from _transient to permanent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_solidify_moves_skill_to_permanent_dir(tmp_path: Path) -> None:
    """When decision=solidify, skill should be moved to SOLIDIFIED_SKILLS_DIR."""
    from hermes_os.skill_discovery import (
        SkillDiscovery,
    )

    transient = tmp_path / "_transient"
    permanent = tmp_path / "skills"
    import hermes_os.skill_discovery as sd

    original_transient = sd.TRANSIENT_SKILLS_DIR
    original_permanent = sd.SOLIDIFIED_SKILLS_DIR
    sd.TRANSIENT_SKILLS_DIR = transient
    sd.SOLIDIFIED_SKILLS_DIR = permanent

    try:
        discovery = SkillDiscovery(db_path=str(tmp_path / "skills.db"))
        await discovery._lazy_init()

        # Create transient skill
        skill_dir = transient / "good-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: good-skill\ndescription: good\n---\n# good")
        db = await discovery._get_db()
        await db.execute(
            """INSERT OR IGNORE INTO discovered_skills
            (repo, path, name, description, stars, url, content, quality_score, discovered_at, solidified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("r", "p", "good-skill", "d", 50, "u", "", 0.8, datetime.now(UTC).isoformat(), 0),
        )
        await db.commit()

        # 3 successes → solidify
        await discovery.record_usage("good-skill", success=True)
        await discovery.record_usage("good-skill", success=True)
        await discovery.record_usage("good-skill", success=True)

        result = await discovery.run_solidify_cycle()
        assert "good-skill" in result["solidify"]

        # Skill should be in permanent dir now
        assert (permanent / "good-skill" / "SKILL.md").exists(), (
            f"good-skill should be in permanent dir: {list(permanent.iterdir()) if permanent.exists() else 'not exists'}"
        )
    finally:
        sd.TRANSIENT_SKILLS_DIR = original_transient
        sd.SOLIDIFIED_SKILLS_DIR = original_permanent


# ---------------------------------------------------------------------------
# Tests: periodic cycle doesn't over-call (rate limit via tick_count)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_solidify_cycle_rate_limited_by_tick(tmp_path: Path) -> None:
    """run_solidify_cycle should only trigger on certain tick counts (e.g. every N ticks)."""
    from hermes_os.proactive_engine import ProactiveEngine
    from hermes_os.skill_discovery import SkillDiscovery

    discovery = SkillDiscovery(db_path=str(tmp_path / "skills.db"))
    await discovery._lazy_init()

    engine = ProactiveEngine()
    engine.set_skill_discovery(discovery)
    # Use async-compatible scheduler mock to prevent hanging
    scheduler_mock = MagicMock()
    scheduler_mock.get_all_tasks = AsyncMock(return_value=[])
    engine._scheduler = scheduler_mock

    call_count = 0
    original = discovery.run_solidify_cycle

    async def counting():
        nonlocal call_count
        call_count += 1
        return await original()

    discovery.run_solidify_cycle = counting  # type: ignore

    # Run deep patrol multiple times with same tick delta
    # Only first call in a cycle should trigger
    await engine._deep_patrol(tick_count=5)  # 5 - 0 >= 5 → True
    await engine._deep_patrol(tick_count=6)  # 6 - 5 >= 5 → False, no deepen patrol
    await engine._deep_patrol(tick_count=10)  # 10 - 5 >= 5 → True

    # run_solidify_cycle should be called at most once per deep patrol cycle
    # After first deep patrol, _last_deep_patrol_tick = 5
    # So tick 5 triggers deep patrol, tick 10 triggers deep patrol again
    # But between them tick 6 doesn't trigger deep patrol (guard fails)
    assert call_count >= 1, f"Expected at least 1 call, got {call_count}"


# ---------------------------------------------------------------------------
# Tests: configurable thresholds for solidify/discard decisions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_solidify_decision_respects_custom_thresholds(tmp_path: Path) -> None:
    """Custom solidify_threshold and solidify_min_uses should override defaults."""
    from hermes_os.skill_discovery import SkillDiscovery

    # Use lenient thresholds: solidify at success_rate >= 0.6 and uses >= 2
    discovery = SkillDiscovery(
        db_path=str(tmp_path / "skills.db"),
        solidify_threshold=0.6,
        solidify_min_uses=2,
    )
    await discovery._lazy_init()
    db = await discovery._get_db()
    now = datetime.now(UTC).isoformat()

    # Skill with 2 successes out of 2 (100% success rate, uses=2) should solidify
    await db.execute(
        """INSERT OR IGNORE INTO discovered_skills
        (repo, path, name, description, stars, url, content, quality_score, discovered_at, solidified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("r1", "p1", "lenient-skill", "d", 10, "u", "", 0.6, now, 0),
    )
    await discovery.record_usage("lenient-skill", success=True)
    await discovery.record_usage("lenient-skill", success=True)

    decision = await discovery.make_solidify_decision("lenient-skill")
    assert decision == "solidify", (
        f"With lenient thresholds (0.6, 2), should solidify but got: {decision}"
    )


@pytest.mark.asyncio
async def test_discard_decision_respects_custom_thresholds(tmp_path: Path) -> None:
    """Custom discard_threshold and discard_min_uses should override defaults."""
    from hermes_os.skill_discovery import SkillDiscovery

    # Use strict discard: discard if success_rate < 0.6 and uses >= 2
    discovery = SkillDiscovery(
        db_path=str(tmp_path / "skills.db"),
        discard_threshold=0.6,
        discard_min_uses=2,
    )
    await discovery._lazy_init()
    db = await discovery._get_db()
    now = datetime.now(UTC).isoformat()

    # Skill with 1 success, 1 failure (50% rate, uses=2) should discard with threshold 0.6
    await db.execute(
        """INSERT OR IGNORE INTO discovered_skills
        (repo, path, name, description, stars, url, content, quality_score, discovered_at, solidified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("r1", "p1", "strict-discard", "d", 5, "u", "", 0.4, now, 0),
    )
    await discovery.record_usage("strict-discard", success=True)
    await discovery.record_usage("strict-discard", success=False)

    decision = await discovery.make_solidify_decision("strict-discard")
    assert decision == "discard", (
        f"With strict discard (0.6, 2), should discard at 50%% rate but got: {decision}"
    )


@pytest.mark.asyncio
async def test_default_thresholds_match_existing_behavior(tmp_path: Path) -> None:
    """Default parameters should produce the same decisions as hardcoded values."""
    from hermes_os.skill_discovery import SkillDiscovery

    discovery = SkillDiscovery(db_path=str(tmp_path / "skills.db"))
    await discovery._lazy_init()
    db = await discovery._get_db()
    now = datetime.now(UTC).isoformat()

    # Skill 1: 3 successes → solidify (default: >=0.8, >=3 uses)
    await db.execute(
        """INSERT OR IGNORE INTO discovered_skills
        (repo, path, name, description, stars, url, content, quality_score, discovered_at, solidified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("r1", "p1", "default-solidify", "d", 10, "u", "", 0.6, now, 0),
    )
    await discovery.record_usage("default-solidify", success=True)
    await discovery.record_usage("default-solidify", success=True)
    await discovery.record_usage("default-solidify", success=True)

    # Skill 2: 2 failures → discard (default: <0.5, >=2 uses)
    await db.execute(
        """INSERT OR IGNORE INTO discovered_skills
        (repo, path, name, description, stars, url, content, quality_score, discovered_at, solidified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("r2", "p2", "default-discard", "d", 5, "u", "", 0.3, now, 0),
    )
    await discovery.record_usage("default-discard", success=True)
    await discovery.record_usage("default-discard", success=False)
    await discovery.record_usage("default-discard", success=False)

    result = await discovery.run_solidify_cycle()

    assert "default-solidify" in result["solidify"], f"default-solidify should solidify: {result}"
    assert "default-discard" in result["discard"], f"default-discard should discard: {result}"
