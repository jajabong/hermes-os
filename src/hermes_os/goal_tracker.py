"""Goal Tracker — deep goal understanding for Hermes OS.

Enables ChiefAgent to understand multi-session goals:
1. GoalPattern — common multi-session patterns (研究→实现→测试, 调研→方案→审批→实施)
2. GoalState — tracks which phase of a goal the user is in
3. GoalTracker — persists goal state, infers next step, suggests next action

This is the "深层目标理解" layer: not just "what does the user want now"
but "what is the user ultimately trying to achieve across multiple sessions."
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import aiosqlite


class GoalPhase(str, Enum):
    """Phases within a goal lifecycle."""
    INITIATED = "initiated"      # Goal identified, not started
    IN_PROGRESS = "in_progress"  # Active work on this goal
    BLOCKED = "blocked"          # Waiting on external factor (approval, response)
    COMPLETED = "completed"      # Goal achieved
    ABANDONED = "abandoned"     # User explicitly gave up


class GoalPattern(str, Enum):
    """
    Common multi-session goal patterns.

    Each pattern defines the ordered phases a goal goes through.
    """
    # Research → Implement → Test → Deploy
    RESEARCH_TO_DEPLOY = "research_to_deploy"
    # Investigate → Propose → Get Approval → Implement
    PROPOSAL_TO_IMPLEMENT = "proposal_to_implement"
    # Study → Plan → Execute → Review
    STUDY_TO_REVIEW = "study_to_review"
    # Single-shot task (no multi-session decomposition)
    ONE_SHOT = "one_shot"


# Pattern → ordered phase lists
_GOAL_PHASES: dict[GoalPattern, list[str]] = {
    GoalPattern.RESEARCH_TO_DEPLOY: [
        "research",
        "plan",
        "implement",
        "test",
        "deploy",
    ],
    GoalPattern.PROPOSAL_TO_IMPLEMENT: [
        "investigate",
        "propose",
        "await_approval",
        "implement",
        "verify",
    ],
    GoalPattern.STUDY_TO_REVIEW: [
        "study",
        "plan",
        "execute",
        "review",
    ],
    GoalPattern.ONE_SHOT: [
        "execute",
    ],
}

# Keyword → GoalPattern mapping for intent-based detection
_PATTERN_KEYWORDS: dict[GoalPattern, list[str]] = {
    GoalPattern.RESEARCH_TO_DEPLOY: [
        "研究", "实现", "测试", "部署", "上线",
        "research", "implement", "deploy", "研究一下", "做一下",
    ],
    GoalPattern.PROPOSAL_TO_IMPLEMENT: [
        "请示", "申请", "方案", "审批", "汇报",
        "request", "proposal", "approve", "方案评审",
    ],
    GoalPattern.STUDY_TO_REVIEW: [
        "调研", "方案", "评审", "review", "audit",
    ],
}

# Intent → default pattern for when user says a goal intent
_INTENT_TO_PATTERN: dict[str, GoalPattern] = {
    "research": GoalPattern.RESEARCH_TO_DEPLOY,
    "code": GoalPattern.RESEARCH_TO_DEPLOY,
    "fix_bug": GoalPattern.RESEARCH_TO_DEPLOY,
    "deploy": GoalPattern.RESEARCH_TO_DEPLOY,
    "review": GoalPattern.STUDY_TO_REVIEW,
    "test": GoalPattern.RESEARCH_TO_DEPLOY,
    "query": GoalPattern.ONE_SHOT,
    "build": GoalPattern.RESEARCH_TO_DEPLOY,
}


@dataclass
class GoalState:
    """A tracked goal with phase progression."""
    goal_id: str
    user_id: str
    pattern: GoalPattern
    current_phase: str
    phase_index: int
    description: str         # Human-readable goal description
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def phases(self) -> list[str]:
        return _GOAL_PHASES.get(self.pattern, ["execute"])

    @property
    def next_phase(self) -> str | None:
        idx = self.phase_index + 1
        if idx < len(self.phases):
            return self.phases[idx]
        return None

    @property
    def is_completed(self) -> bool:
        return self.current_phase == "completed" or self.completed_at is not None

    @property
    def progress(self) -> float:
        """0.0-1.0 progress through phases."""
        total = len(self.phases)
        if total == 0:
            return 1.0
        return min(1.0, self.phase_index / total)


@dataclass
class EvolutionEntry:
    """A record of goal description change — records the evolution path."""
    goal_id: str
    timestamp: datetime
    previous_description: str
    new_description: str
    reason: str              # Why the goal changed (free text)
    trigger: str             # What triggered the change: "user_input", "system_suggestion", "completion"


class GoalTracker:
    """
    Tracks multi-session goal state per user.

    Usage:
        tracker = GoalTracker(db_path="hermes_os.db")
        await tracker.initialize()

        # When user starts a multi-session goal
        goal = await tracker.create_goal(
            user_id="alice",
            description="完成供应商对比分析项目",
            initial_intent="research",
        )

        # When user sends a new message, update phase
        updated_goal = await tracker.advance_phase("alice", "implement")

        # Get current goal context for ChiefAgent
        context = await tracker.get_active_goal_context("alice")
    """

    def __init__(self, db_path: str = "hermes_os.db") -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._apply_pragmas(self._db)
        await self._create_table()

    async def _apply_pragmas(self, db: aiosqlite.Connection) -> None:
        """Enforce WAL mode and normal synchronous for better concurrency."""
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _get_db(self) -> aiosqlite.Connection:
        if self._db is None:
            await self.initialize()
        return self._db  # type: ignore[return-value]

    async def _create_table(self) -> None:
        db = await self._get_db()
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS goal_states (
                goal_id TEXT PRIMARY KEY,
                user_id TEXT,
                pattern TEXT,
                current_phase TEXT,
                phase_index INTEGER,
                description TEXT,
                created_at TEXT,
                updated_at TEXT,
                completed_at TEXT,
                metadata TEXT
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_goals_user ON goal_states(user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_goals_status ON goal_states(completed_at)"
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS goal_evolution_log (
                entry_id TEXT PRIMARY KEY,
                goal_id TEXT,
                timestamp TEXT,
                previous_description TEXT,
                new_description TEXT,
                reason TEXT,
                trigger TEXT
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_evo_goal ON goal_evolution_log(goal_id)"
        )
        await db.commit()

    # -------------------------------------------------------------------------
    # Goal lifecycle
    # -------------------------------------------------------------------------

    async def create_goal(
        self,
        user_id: str,
        description: str,
        initial_intent: str | None = None,
        pattern: GoalPattern | None = None,
        metadata: dict | None = None,
    ) -> GoalState:
        """
        Create a new goal for a user.

        Args:
            user_id: Owner of the goal
            description: Human-readable goal description
            initial_intent: Intent action (e.g., "research", "code") to infer pattern
            pattern: Explicit pattern override
        """
        db = await self._get_db()

        # Infer pattern from intent if not specified
        if pattern is None and initial_intent:
            pattern = _INTENT_TO_PATTERN.get(initial_intent, GoalPattern.ONE_SHOT)

        pattern = pattern or GoalPattern.ONE_SHOT
        phases = _GOAL_PHASES[pattern]
        initial_phase = phases[0]

        goal_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        await db.execute(
            """
            INSERT INTO goal_states
            (goal_id, user_id, pattern, current_phase, phase_index,
             description, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                goal_id,
                user_id,
                pattern.value,
                initial_phase,
                0,
                description,
                now.isoformat(),
                now.isoformat(),
                json.dumps(metadata or {}),
            ),
        )
        await db.commit()

        return GoalState(
            goal_id=goal_id,
            user_id=user_id,
            pattern=pattern,
            current_phase=initial_phase,
            phase_index=0,
            description=description,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )

    async def advance_phase(
        self,
        user_id: str,
        next_phase: str | None = None,
        goal_id: str | None = None,
    ) -> GoalState | None:
        """
        Advance the active goal to the next phase (or a specific phase).

        If next_phase is None, advances to the next phase in the pattern.

        Args:
            user_id: User whose goal to advance
            next_phase: Specific phase to jump to (for backward/forward jumps)
            goal_id: Specific goal to advance (default: active goal for user)
        """
        goal = goal_id or (await self.get_active_goal(user_id))
        if not goal:
            return None

        if goal.is_completed:
            return goal

        db = await self._get_db()
        now = datetime.now(UTC)

        if next_phase:
            # Jump to specific phase
            if next_phase in goal.phases:
                new_index = goal.phases.index(next_phase)
            else:
                # Treat as completion
                new_phase = "completed"
                new_index = len(goal.phases)
        else:
            # Advance to next phase
            new_index = goal.phase_index + 1
            if new_index >= len(goal.phases):
                new_phase = "completed"
            else:
                new_phase = goal.phases[new_index]

        completed_at = now.isoformat() if new_phase == "completed" else None

        await db.execute(
            """
            UPDATE goal_states
            SET current_phase = ?, phase_index = ?, updated_at = ?, completed_at = ?
            WHERE goal_id = ?
            """,
            (new_phase, new_index, now.isoformat(), completed_at, goal.goal_id),
        )
        await db.commit()

        return await self.get_goal(goal.goal_id)

    async def complete_goal(self, goal_id: str) -> GoalState | None:
        """Mark a goal as completed."""
        goal = await self.get_goal(goal_id)
        if not goal:
            return None

        db = await self._get_db()
        now = datetime.now(UTC)

        await db.execute(
            """
            UPDATE goal_states
            SET current_phase = 'completed', completed_at = ?, updated_at = ?
            WHERE goal_id = ?
            """,
            (now.isoformat(), now.isoformat(), goal_id),
        )
        await db.commit()
        return await self.get_goal(goal_id)

    async def abandon_goal(self, goal_id: str) -> GoalState | None:
        """Mark a goal as abandoned."""
        goal = await self.get_goal(goal_id)
        if not goal:
            return None

        db = await self._get_db()
        now = datetime.now(UTC)

        await db.execute(
            """
            UPDATE goal_states
            SET current_phase = 'abandoned', completed_at = ?, updated_at = ?
            WHERE goal_id = ?
            """,
            (now.isoformat(), now.isoformat(), goal_id),
        )
        await db.commit()
        return await self.get_goal(goal_id)

    # -------------------------------------------------------------------------
    # Queries
    # -------------------------------------------------------------------------

    async def get_goal(self, goal_id: str) -> GoalState | None:
        """Get a goal by ID."""
        db = await self._get_db()
        async with db.execute(
            "SELECT * FROM goal_states WHERE goal_id = ?", (goal_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_goal(row) if row else None

    async def get_active_goal(self, user_id: str) -> GoalState | None:
        """Get the most recent active (not completed) goal for a user."""
        db = await self._get_db()
        async with db.execute(
            """
            SELECT * FROM goal_states
            WHERE user_id = ? AND completed_at IS NULL
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_goal(row) if row else None

    async def get_active_goal_context(self, user_id: str) -> str:
        """
        Get a context string describing the user's active goal.
        Used by ChiefAgent to inject goal context into parse_intent().
        """
        goal = await self.get_active_goal(user_id)
        if not goal:
            return ""

        context_parts = [
            f"Goal: {goal.description}",
            f"Phase {goal.phase_index + 1}/{len(goal.phases)}: {goal.current_phase}",
            f"Pattern: {goal.pattern.value}",
        ]
        if goal.next_phase:
            context_parts.append(f"Next step: {goal.next_phase}")
        context_parts.append(f"Progress: {int(goal.progress * 100)}%")

        return "\n".join(context_parts)

    async def get_recent_goals(
        self, user_id: str, limit: int = 5
    ) -> list[GoalState]:
        """Get recently updated goals for a user."""
        db = await self._get_db()
        async with db.execute(
            """
            SELECT * FROM goal_states
            WHERE user_id = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_goal(row) for row in rows]

    async def append_evolution_log(
        self,
        goal_id: str,
        new_description: str,
        reason: str,
        trigger: str = "user_input",
    ) -> EvolutionEntry:
        """
        Record a goal description change as an evolution entry.

        This preserves the "why did the goal change?" trail for context disambiguation.
        """
        db = await self._get_db()
        goal = await self.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        entry_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        previous_description = goal.description

        await db.execute(
            """
            INSERT INTO goal_evolution_log
            (entry_id, goal_id, timestamp, previous_description,
             new_description, reason, trigger)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                goal_id,
                now.isoformat(),
                previous_description,
                new_description,
                reason,
                trigger,
            ),
        )
        await db.commit()

        return EvolutionEntry(
            goal_id=goal_id,
            timestamp=now,
            previous_description=previous_description,
            new_description=new_description,
            reason=reason,
            trigger=trigger,
        )

    async def get_evolution_history(self, goal_id: str) -> list[EvolutionEntry]:
        """Get the full evolution history for a goal (chronological order)."""
        db = await self._get_db()
        async with db.execute(
            """
            SELECT * FROM goal_evolution_log
            WHERE goal_id = ?
            ORDER BY timestamp ASC
            """,
            (goal_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_evolution(row) for row in rows]

    async def get_latest_evolution_reason(self, goal_id: str) -> str | None:
        """Get the most recent reason for goal change, or None if no evolution."""
        history = await self.get_evolution_history(goal_id)
        if not history:
            return None
        return history[-1].reason

    async def get_context_with_evolution(self, user_id: str) -> str:
        """
        Get goal context including evolution history.
        Used when user instructions are ambiguous — the evolution history
        helps JARVIS answer "why did we change the goal?"
        """
        goal = await self.get_active_goal(user_id)
        if not goal:
            return ""

        context_parts = [
            f"Goal: {goal.description}",
            f"Phase {goal.phase_index + 1}/{len(goal.phases)}: {goal.current_phase}",
            f"Pattern: {goal.pattern.value}",
        ]
        if goal.next_phase:
            context_parts.append(f"Next step: {goal.next_phase}")
        context_parts.append(f"Progress: {int(goal.progress * 100)}%")

        history = await self.get_evolution_history(goal.goal_id)
        if history:
            evolution_lines = ["\nGoal Evolution History:"]
            for entry in history:
                evolution_lines.append(
                    f"  - [{entry.timestamp.strftime('%Y-%m-%d')}] "
                    f"{entry.previous_description} → {entry.new_description} "
                    f"(reason: {entry.reason})"
                )
            context_parts.append("\n".join(evolution_lines))

        return "\n".join(context_parts)

    async def infer_next_action(
        self, user_id: str, current_message: str
    ) -> str | None:
        """
        Given the user's current message, infer if they're advancing
        the active goal or starting something new.

        Returns a suggestion for the next goal phase, or None if ambiguous.
        """
        goal = await self.get_active_goal(user_id)
        if not goal or goal.is_completed:
            return None

        msg_lower = current_message.lower()

        # Check if the message indicates the current phase is done
        completion_signals = [
            "完成了", "搞定了", "done", "finished", "完成了",
            "好了", "搞定", "可以了", "end",
        ]
        if any(s in msg_lower for s in completion_signals):
            if goal.next_phase:
                return f"advance to {goal.next_phase}"

        # Check if this is an approval-related message
        if goal.current_phase == "await_approval":
            approval_signals = ["同意", "批准", "驳回", "不同意", "approved", "rejected"]
            if any(s in msg_lower for s in approval_signals):
                return "process approval response"

        # Otherwise, suggest the next phase
        if goal.next_phase:
            return f"suggest continuing to {goal.next_phase}"

        return None

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _row_to_goal(self, row: aiosqlite.Row) -> GoalState:
        metadata_str = row.get("metadata")
        metadata: dict = {}
        if metadata_str:
            try:
                metadata = json.loads(metadata_str)
            except json.JSONDecodeError:
                metadata = {}

        try:
            created_at = datetime.fromisoformat(row["created_at"])
        except (ValueError, TypeError):
            created_at = datetime.now(UTC)

        try:
            updated_at = datetime.fromisoformat(row["updated_at"])
        except (ValueError, TypeError):
            updated_at = datetime.now(UTC)

        completed_at = None
        if row.get("completed_at"):
            try:
                completed_at = datetime.fromisoformat(row["completed_at"])
            except (ValueError, TypeError):
                completed_at = None

        try:
            pattern = GoalPattern(row["pattern"])
        except ValueError:
            pattern = GoalPattern.ONE_SHOT

        return GoalState(
            goal_id=row["goal_id"],
            user_id=row["user_id"],
            pattern=pattern,
            current_phase=row["current_phase"],
            phase_index=row["phase_index"],
            description=row["description"],
            created_at=created_at,
            updated_at=updated_at,
            completed_at=completed_at,
            metadata=metadata,
        )

    def _row_to_evolution(self, row: aiosqlite.Row) -> EvolutionEntry:
        return EvolutionEntry(
            goal_id=row["goal_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            previous_description=row["previous_description"],
            new_description=row["new_description"],
            reason=row["reason"],
            trigger=row["trigger"],
        )
