"""Tests for SkillDiscovery effectiveness feedback loop."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from hermes_os.skill_discovery import SkillDiscovery


@pytest.fixture
def discovery() -> SkillDiscovery:
    return SkillDiscovery(db_path=":memory:")


# ---------------------------------------------------------------------------
# record_usage tests
# ---------------------------------------------------------------------------

class TestRecordUsage:
    """Tests for record_usage() tracking."""

    @pytest.mark.asyncio
    async def test_record_usage_inserts_new_row(self, discovery: SkillDiscovery) -> None:
        """First record_usage for a skill creates a new effectiveness row."""
        await discovery.record_usage("tdd-workflow", success=True)

        eff = await discovery.get_effectiveness("tdd-workflow")
        assert eff["found"] is True
        assert eff["uses"] == 1
        assert eff["successes"] == 1
        assert eff["failures"] == 0
        assert eff["success_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_record_usage_accumulates_multiple(self, discovery: SkillDiscovery) -> None:
        """Multiple record_usage calls for same skill accumulate correctly."""
        await discovery.record_usage("tdd-workflow", success=True)
        await discovery.record_usage("tdd-workflow", success=True)
        await discovery.record_usage("tdd-workflow", success=False)

        eff = await discovery.get_effectiveness("tdd-workflow")
        assert eff["uses"] == 3
        assert eff["successes"] == 2
        assert eff["failures"] == 1
        assert eff["success_rate"] == pytest.approx(2 / 3)

    @pytest.mark.asyncio
    async def test_record_usage_failure_decrements_rate(self, discovery: SkillDiscovery) -> None:
        """Failures drive success_rate down."""
        await discovery.record_usage("risky-skill", success=True)
        await discovery.record_usage("risky-skill", success=True)
        await discovery.record_usage("risky-skill", success=False)

        eff = await discovery.get_effectiveness("risky-skill")
        assert eff["success_rate"] == pytest.approx(2 / 3)

    @pytest.mark.asyncio
    async def test_record_usage_unknown_skill_has_no_entry(self, discovery: SkillDiscovery) -> None:
        """get_effectiveness for never-used skill returns found=False."""
        eff = await discovery.get_effectiveness("never-used-skill")
        assert eff["found"] is False


# ---------------------------------------------------------------------------
# make_solidify_decision tests
# ---------------------------------------------------------------------------

class TestSolidifyDecision:
    """Tests for make_solidify_decision() — the solidify/discard/keep logic."""

    @pytest.mark.asyncio
    async def test_decision_solidify_high_success(self, discovery: SkillDiscovery) -> None:
        """success_rate >= 0.8 and uses >= 3 → solidify."""
        for _ in range(3):
            await discovery.record_usage("good-skill", success=True)

        decision = await discovery.make_solidify_decision("good-skill")
        assert decision == "solidify"

    @pytest.mark.asyncio
    async def test_decision_discard_low_success(self, discovery: SkillDiscovery) -> None:
        """success_rate < 0.5 and uses >= 2 → discard."""
        await discovery.record_usage("bad-skill", success=True)
        await discovery.record_usage("bad-skill", success=False)
        await discovery.record_usage("bad-skill", success=False)

        decision = await discovery.make_solidify_decision("bad-skill")
        assert decision == "discard"

    @pytest.mark.asyncio
    async def test_decision_keep_transient_insufficient_data(self, discovery: SkillDiscovery) -> None:
        """uses < 2 or 0.5 <= success_rate < 0.8 → keep_transient."""
        # only 1 use — not enough for any decision
        await discovery.record_usage("new-skill", success=True)
        decision = await discovery.make_solidify_decision("new-skill")
        assert decision == "keep_transient"

    @pytest.mark.asyncio
    async def test_decision_keep_transient_borderline_rate(self, discovery: SkillDiscovery) -> None:
        """60% success rate (>= 0.5 but < 0.8) → keep_transient even with 3 uses."""
        await discovery.record_usage("mid-skill", success=True)
        await discovery.record_usage("mid-skill", success=True)
        await discovery.record_usage("mid-skill", success=False)

        decision = await discovery.make_solidify_decision("mid-skill")
        assert decision == "keep_transient"

    @pytest.mark.asyncio
    async def test_decision_unknown_skill_keeps_transient(self, discovery: SkillDiscovery) -> None:
        """skill with no record_usage → keep_transient."""
        decision = await discovery.make_solidify_decision("ghost-skill")
        assert decision == "keep_transient"


# ---------------------------------------------------------------------------
# run_solidify_cycle tests
# ---------------------------------------------------------------------------

class TestSolidifyCycle:
    """Tests for run_solidify_cycle() periodic review."""

    @pytest.mark.asyncio
    async def test_solidify_cycle_returns_summary(self, discovery: SkillDiscovery) -> None:
        """run_solidify_cycle returns categorized decisions dict."""
        # Set up skills with different outcomes
        await discovery.record_usage("solidify-me", success=True)
        await discovery.record_usage("solidify-me", success=True)
        await discovery.record_usage("solidify-me", success=True)  # 100%, uses=3

        await discovery.record_usage("discard-me", success=True)
        await discovery.record_usage("discard-me", success=False)  # 50%

        result = await discovery.run_solidify_cycle()
        assert "solidify" in result
        assert "discard" in result
        assert "keep_transient" in result

    # ---------------------------------------------------------------------------
# Integration test: record_usage → solidify cycle feedback loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_solidify_decision_after_successes() -> None:
    """After 3 successes, make_solidify_decision returns 'solidify'."""
    discovery = SkillDiscovery(db_path=":memory:")
    await discovery._lazy_init()
    db = await discovery._get_db()
    now = datetime.now(UTC).isoformat()

    # Insert a discoverable skill
    await db.execute(
        """
        INSERT OR REPLACE INTO discovered_skills
        (repo, path, name, description, stars, url, content, quality_score, discovered_at, solidified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("test-repo", "/test/SKILL.md", "integration-skill", "desc", 50, "https://github.com/test", "", 0.5, now, 0),
    )
    await db.commit()

    # Record 3 successes → should solidify
    for _ in range(3):
        await discovery.record_usage("integration-skill", success=True)

    # Verify effectiveness before calling solidify cycle
    eff = await discovery.get_effectiveness("integration-skill")
    assert eff["found"], f"effectiveness not found: {eff}"
    assert eff["uses"] == 3, f"expected 3 uses, got {eff['uses']}"

    decision = await discovery.make_solidify_decision("integration-skill")
    assert decision == "solidify", f"expected solidify, got {decision} with eff={eff}"


@pytest.mark.asyncio
async def test_solidify_decision_after_failures() -> None:
    """After 2 failures and 1 success (33%), make_solidify_decision returns 'discard'."""
    discovery = SkillDiscovery(db_path=":memory:")
    await discovery._lazy_init()
    db = await discovery._get_db()
    now = datetime.now(UTC).isoformat()

    await db.execute(
        """
        INSERT OR REPLACE INTO discovered_skills
        (repo, path, name, description, stars, url, content, quality_score, discovered_at, solidified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("discard-repo", "/discard/SKILL.md", "discard-skill", "desc", 10, "https://github.com/test", "", 0.3, now, 0),
    )
    await db.commit()

    # 33% success rate → discard
    await discovery.record_usage("discard-skill", success=True)
    await discovery.record_usage("discard-skill", success=False)
    await discovery.record_usage("discard-skill", success=False)

    eff = await discovery.get_effectiveness("discard-skill")
    assert eff["found"]
    assert eff["success_rate"] == pytest.approx(1 / 3)

    decision = await discovery.make_solidify_decision("discard-skill")
    assert decision == "discard", f"expected discard, got {decision}"


# ---------------------------------------------------------------------------
# record_usage_from_task — automatic feedback from TaskScheduler
# ---------------------------------------------------------------------------

class TestRecordUsageFromTask:
    """Tests for automatic skill_name extraction from task metadata."""

    @pytest.mark.asyncio
    async def test_record_usage_accepts_skill_name(self, discovery: SkillDiscovery) -> None:
        """record_usage stores a skill_name in effectiveness table."""
        await discovery.record_usage("tdd-workflow", success=True)
        eff = await discovery.get_effectiveness("tdd-workflow")
        assert eff["found"] is True
        assert eff["uses"] == 1

    @pytest.mark.asyncio
    async def test_record_usage_empty_skill_name_still_works(self, discovery: SkillDiscovery) -> None:
        """record_usage with empty skill_name is silently ignored (no DB entry)."""
        # Empty string skill should not raise
        await discovery.record_usage("", success=True)
        # ghost skill
        eff = await discovery.get_effectiveness("")
        assert eff["found"] is False  # empty string not stored