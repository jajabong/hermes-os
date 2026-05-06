"""Chief Agent — Intent Understanding Layer for Hermes OS.

Responsibilities:
1. Parse natural language into structured intents (via LLM)
2. Create task DAGs from intents (via TaskScheduler)
3. Proactively suggest next actions based on pending/failed tasks
4. Track multi-session goals (GoalTracker) for deep goal understanding
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum

from hermes_os.claude_code_invocator import (
    invoke,
)
from hermes_os.goal_tracker import EvolutionEntry, GoalTracker
from hermes_os.org_context import (
    ORG_IDENTITY,
    ROLE_DEFINITIONS,
    _build_org_preamble,
    build_org_context,
    get_role_for_intent,
)
from hermes_os.task_scheduler import TaskPriority, TaskScheduler


class DriftLevel(str, Enum):
    """Semantic drift severity levels from active goal."""

    LOW = "LOW"  # < 0.7 similarity — auto-approve
    MEDIUM = "MEDIUM"  # 0.4-0.7 — confirmation required
    HIGH = "HIGH"  # < 0.4 — lock context, wait for human


@dataclass
class AlignmentResult:
    """Result of alignment check between user intent and active goal."""

    drift_level: DriftLevel
    similarity: float
    active_goal_description: str
    current_intent_description: str
    needs_confirmation: bool
    confirmation_message: str | None
    evolution_history: list[EvolutionEntry] = field(default_factory=list)


# Threshold constants
_DRIFT_SIMILARITY_LOW = 0.7
_DRIFT_SIMILARITY_MEDIUM = 0.4

CHIEF_SYSTEM_PROMPT_TEMPLATE = """You are the Intent Understanding Layer of Hermes OS — an AI-native virtual organization.

{north_star_block}

=== HERMES OS ORGANIZATION IDENTITY ===
{org_preamble}

=== GOAL-ALIGNED INTERACTION STYLE ===
When responding or creating tasks, you MUST:
1. Begin every reply with: "🎯 当前目标: [Goal Name]" when goal context is available
2. Always include: "[结果摘要] + [对目标的贡献度]"
3. Never produce raw execution logs — always summarize to conclusion first
4. Keep the user's goal visible in every interaction

This ensures the user feels JARVIS is always working WITH them, not just executing commands.
"""

CHIEF_SYSTEM_PROMPT = _build_org_preamble()


def build_chief_system_prompt(north_star_goal: str | None = None) -> str:
    """Build the ChiefAgent system prompt, injecting north star goal at top."""
    if north_star_goal:
        north_star_block = (
            f"╔══════════════════════════════════════════════════════════════╗\n"
            f"║  🎯 北极星指标 (NORTH STAR GOAL) — ALL ACTIONS MUST SERVE THIS   ║\n"
            f"║  {north_star_goal[:60]:<60}  ║\n"
            f"║  You are working toward the goal above. If any instruction      ║\n"
            f"║  conflicts with it, correct the instruction, don't abandon it. ║\n"
            f"╚══════════════════════════════════════════════════════════════╝"
        )
    else:
        north_star_block = ""
    return CHIEF_SYSTEM_PROMPT_TEMPLATE.format(
        org_preamble=_build_org_preamble(),
        north_star_block=north_star_block,
    )


class Intent(str, Enum):
    FIX_BUG = "fix_bug"
    DEPLOY = "deploy"
    RESEARCH = "research"
    CODE = "code"
    REVIEW = "review"
    TEST = "test"
    BUILD = "build"
    QUERY = "query"
    WRITE_BOOK = "write_book"  # Book pipeline trigger
    UNKNOWN = "unknown"


@dataclass
class ParsedIntent:
    """A structured intent parsed from natural language."""

    action: Intent
    confidence: float  # 0.0-1.0
    entities: dict[str, str] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    suggested_next: list[str] = field(default_factory=list)
    raw_text: str = ""


# JSON schema for structured LLM output
INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [a.value for a in Intent],
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "entities": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "suggested_next": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["action", "confidence", "entities"],
}


INTENT_PROMPT_TEMPLATE = """You are the Intent Understanding Layer of Hermes OS — an AI-native organization.

Parse the user's message into a structured intent. If multiple distinct actions are present,
return the PRIMARY one (highest confidence).

## User Message
{message}

## Recent Context (for disambiguation)
{context}

## Output Schema
Return ONLY valid JSON matching this schema (no markdown, no explanation):
{{
  "action": "fix_bug|deploy|research|code|review|test|build|query|write_book|unknown",
  "confidence": 0.0-1.0,
  "entities": {{
    "target": "file/module/server target",
    "language": "programming language if applicable",
    "server": "deployment target if applicable",
    "topic": "book/script topic if applicable",
    "urgency": "low|normal|high|critical"
  }},
  "suggested_next": ["suggested follow-up action 1", "..."]
}}

Rules:
- confidence < 0.5 → action should be "unknown"
- If user says "fix this bug and deploy", pick ONE primary action
- suggested_next should be natural language descriptions of follow-up tasks
"""


class ChiefAgent:
    """Chief Agent: orchestrates intent parsing, task planning, and proactive suggestions."""

    def __init__(self, model: str = "sonnet") -> None:
        self.model = model
        self._goal_tracker: GoalTracker | None = None

    def set_goal_tracker(self, tracker: GoalTracker) -> None:
        """Inject GoalTracker for deep goal understanding."""
        self._goal_tracker = tracker

    async def parse_intent(
        self,
        message: str,
        user_id: str,
        recent_tasks: str = "",
        recent_messages: str = "",
        goal_tracker: GoalTracker | None = None,
    ) -> ParsedIntent:
        """Parse user message into a structured ParsedIntent using LLM.

        Args:
            message: Raw user message
            user_id: For logging/context
            recent_tasks: Recent task history (optional)
            recent_messages: Recent conversation messages (optional)
            goal_tracker: GoalTracker instance for deep goal context injection
        """
        tracker = goal_tracker or self._goal_tracker
        context_parts = []
        north_star_goal: str | None = None

        # Inject multi-session goal context + evolution history if GoalTracker available
        if tracker:
            try:
                goal_context = await tracker.get_active_goal_context(user_id)
                if goal_context:
                    context_parts.append(f"Active Goal (deep context):\n{goal_context}")
                    # Extract north star goal for system prompt injection
                    for line in goal_context.split("\n"):
                        if line.startswith("Goal:"):
                            north_star_goal = line.removeprefix("Goal:").strip()
                            break
                    # Also append evolution history if available
                    active_goal = await tracker.get_active_goal(user_id)
                    if active_goal:
                        evolution = await tracker.get_evolution_history(active_goal.goal_id)
                        if evolution:
                            evo_lines = ["\nGoal Evolution History:"]
                            for e in evolution:
                                evo_lines.append(
                                    f"  - [{e.timestamp.strftime('%Y-%m-%d')}] "
                                    f"{e.previous_description} → {e.new_description} "
                                    f"(reason: {e.reason})"
                                )
                            context_parts.append("\n".join(evo_lines))
            except Exception:
                pass
        if recent_tasks:
            context_parts.append(f"Recent tasks:\n{recent_tasks}")
        if recent_messages:
            context_parts.append(f"Recent messages:\n{recent_messages}")
        context = "\n\n".join(context_parts) or "No recent context available."

        prompt = INTENT_PROMPT_TEMPLATE.format(
            message=message,
            context=context,
        )

        # Build system prompt with North Star Goal at the top
        system_prompt = build_chief_system_prompt(north_star_goal=north_star_goal)

        try:
            result = await invoke(
                prompt=prompt,
                model=f"claude-{self.model}-4-6",
                max_turns=3,
                timeout_sec=30,
                output_format="json",
                json_schema=json.dumps(INTENT_SCHEMA),
                system_prompt=system_prompt,
            )

            data = json.loads(result.stdout)

            # Validate and sanitize
            action_str = data.get("action", "unknown")
            try:
                action = Intent(action_str)
            except ValueError:
                action = Intent.UNKNOWN

            return ParsedIntent(
                action=action,
                confidence=float(data.get("confidence", 0.0)),
                entities=data.get("entities", {}),
                suggested_next=data.get("suggested_next", []),
                raw_text=message,
            )

        except Exception:
            # Fallback: rule-based parsing (context not used in rule-based mode)
            return self._rule_based_parse(message, context_parts)

    def _rule_based_parse(
        self, message: str, context_parts: list[str] | None = None
    ) -> ParsedIntent:
        """Simple rule-based fallback when LLM parsing fails.

        Args:
            message: Raw user message
            context_parts: Optional context from recent_tasks/recent_messages for future enhancement
        """
        msg_lower = message.lower()

        # Detect intent by keywords
        if any(k in msg_lower for k in ["fix", "bug", "error", "crash", "broken"]):
            action = Intent.FIX_BUG
            confidence = 0.6
        elif any(k in msg_lower for k in ["deploy", "release", "push to", "ship"]):
            action = Intent.DEPLOY
            confidence = 0.7
        elif any(k in msg_lower for k in ["research", "find out", "investigate", "look up"]):
            action = Intent.RESEARCH
            confidence = 0.6
        elif any(k in msg_lower for k in ["review", "check code", "audit"]):
            action = Intent.REVIEW
            confidence = 0.6
        elif any(k in msg_lower for k in ["test", "run tests"]):
            action = Intent.TEST
            confidence = 0.7
        elif any(k in msg_lower for k in ["build", "compile", "make"]):
            action = Intent.BUILD
            confidence = 0.6
        elif any(k in msg_lower for k in ["write code", "implement", "add feature"]):
            action = Intent.CODE
            confidence = 0.6
        elif any(
            k in msg_lower for k in ["写一本", "写本书", "创作书籍", "写一本关于", "book pipeline"]
        ):
            action = Intent.WRITE_BOOK
            confidence = 0.8
        else:
            action = Intent.UNKNOWN
            confidence = 0.3

        return ParsedIntent(
            action=action,
            confidence=confidence,
            entities={},
            raw_text=message,
        )

    async def create_task_dag(
        self,
        intent: ParsedIntent,
        user_id: str,
        scheduler: TaskScheduler,
    ) -> list:
        """Create a task DAG from a parsed intent.

        Uses TaskScheduler.create_macro_task() to create dependent subtasks.

        Args:
            intent: Parsed intent from parse_intent()
            user_id: Owner of the tasks
            scheduler: TaskScheduler instance

        Returns:
            List of created Task objects
        """
        action = intent.action.value
        target = intent.entities.get("target", "")
        language = intent.entities.get("language", "")
        urgency = intent.entities.get("urgency", "normal")

        priority = {
            "critical": TaskPriority.CRITICAL,
            "high": TaskPriority.HIGH,
            "normal": TaskPriority.NORMAL,
            "low": TaskPriority.LOW,
        }.get(urgency, TaskPriority.NORMAL)

        if intent.action == Intent.FIX_BUG and target:
            # Bug fix workflow: investigate → fix → test → review
            subtasks = [
                {
                    "title": f"Investigate bug in {target}",
                    "description": f"Investigate the bug in {target}. "
                    f"Read the relevant code, identify root cause, "
                    f"and describe your findings. Message: {intent.raw_text}",
                },
                {
                    "title": f"Fix bug in {target}",
                    "description": f"Fix the bug identified in {target}. "
                    f"Make minimal, targeted changes. After fixing, "
                    f"explain what was changed and why.",
                },
                {
                    "title": f"Test fix for {target}",
                    "description": f"Write or run tests to verify the fix for {target}. "
                    f"Confirm the bug is resolved and no regressions.",
                },
            ]
        elif intent.action == Intent.DEPLOY and target:
            subtasks = [
                {
                    "title": f"Prepare deployment to {target}",
                    "description": f"Prepare deployment to {target}. "
                    f"Check build status, review changes, ensure all tests pass.",
                },
                {
                    "title": f"Deploy to {target}",
                    "description": f"Execute deployment to {target}. "
                    f"Monitor logs during deployment.",
                },
                {
                    "title": f"Verify deployment to {target}",
                    "description": f"Verify deployment to {target} succeeded. "
                    f"Check health endpoints, run smoke tests.",
                },
            ]
        elif intent.action == Intent.CODE and target:
            subtasks = [
                {
                    "title": f"Plan implementation for {target}",
                    "description": f"Plan the implementation of {target}. "
                    f"Outline the approach, file structure, and key decisions.",
                },
                {
                    "title": f"Implement {target}",
                    "description": f"Implement {target} "
                    f"{'in ' + language if language else ''}. "
                    f"Follow best practices. Message: {intent.raw_text}",
                },
                {
                    "title": f"Review implementation of {target}",
                    "description": f"Review the implementation of {target}. "
                    f"Check for bugs, style issues, and missing edge cases.",
                },
            ]
        elif intent.action == Intent.RESEARCH:
            subtasks = [
                {
                    "title": f"Research: {intent.raw_text[:60]}",
                    "description": f"Research the following topic thoroughly. "
                    f"Search the web, check documentation, and summarize findings.\n\n"
                    f"Topic: {intent.raw_text}",
                },
            ]
        elif intent.action == Intent.WRITE_BOOK:
            # Extract topic from raw text (e.g., "写一本关于人工智能的书")
            topic = intent.entities.get("topic", "")
            if not topic:
                # Strip common prefixes to extract topic
                topic = intent.raw_text
                for prefix in ["写一本关于", "关于", "的书", "写一本", "写本书"]:
                    topic = topic.replace(prefix, "")
                topic = topic.strip()

            # Use create_pipeline_tasks for Book Pipeline
            priority = TaskPriority.HIGH
            goal_context_for_task = ""
            if self._goal_tracker:
                try:
                    goal_context_for_task = await self._goal_tracker.get_active_goal_context(
                        user_id
                    )
                except Exception:
                    pass

            tasks = await scheduler.create_pipeline_tasks(
                user_id=user_id,
                topic=topic,
                pipeline_name="Book Authoring Pipeline",
                metadata={
                    "intent_action": Intent.WRITE_BOOK.value,
                    "priority": priority.value,
                    "role": "book_author",
                    "goal_context": goal_context_for_task,
                    "raw_request": intent.raw_text,
                    # High-confidence intents auto-execute without user confirmation
                    "skip_confirmation": intent.confidence >= 0.85,
                },
            )

            # Advance goal phase after creating tasks
            if self._goal_tracker and tasks:
                try:
                    await self._goal_tracker.advance_phase(
                        user_id, next_phase=Intent.WRITE_BOOK.value
                    )
                except Exception:
                    pass

            return tasks
        else:
            # Generic single-task
            subtasks = [
                {
                    "title": f"{action}: {target or intent.raw_text[:40]}",
                    "description": intent.raw_text,
                },
            ]

        # Determine role from intent action and build full org context
        role = get_role_for_intent(action)
        org_ctx = build_org_context(role)

        # Inject goal context into task metadata for notification enrichment
        goal_context_for_task = ""
        if self._goal_tracker:
            try:
                goal_context_for_task = await self._goal_tracker.get_active_goal_context(user_id)
            except Exception:
                pass

        tasks = await scheduler.create_macro_task(
            user_id=user_id,
            title=f"{action}: {target or intent.raw_text[:40]}",
            subtasks=subtasks,
            metadata={
                "intent_action": action,
                "priority": priority.value,
                "role": role.value,
                "system_prompt": org_ctx.system_prompt,
                "org_identity": ORG_IDENTITY,
                "role_definition": ROLE_DEFINITIONS[role],
                "goal_context": goal_context_for_task,
                # High-confidence intents auto-execute without user confirmation
                "skip_confirmation": intent.confidence >= 0.85,
            },
        )

        # Advance goal phase after creating tasks (deep goal understanding)
        if self._goal_tracker and tasks:
            try:
                await self._goal_tracker.advance_phase(user_id, next_phase=action)
            except Exception:
                pass  # Non-blocking — don't fail task creation for goal tracking errors

        return tasks

    async def get_proactive_suggestions(
        self,
        user_id: str,
        scheduler: TaskScheduler,
        max_suggestions: int = 3,
    ) -> list[str]:
        """Analyze pending/failed tasks and suggest next actions.

        This is called proactively — without user input — to drive
        the 7x24 autonomous behavior.
        """
        suggestions: list[str] = []

        try:
            # Check failed tasks → suggest retry or alternative approach
            failed = await scheduler.get_tasks_for_user(user_id, status=None)
            failed_tasks = [t for t in failed if t.status.value == "failed"][:2]

            for task in failed_tasks:
                if task.error:
                    suggestions.append(
                        f"Task '{task.title}' failed with: {task.error[:80]}. "
                        f"Consider fixing and retrying."
                    )

            # Check blocked tasks → suggest resolving dependencies
            blocked = await scheduler.get_tasks_for_user(user_id, status=None)
            blocked_tasks = [t for t in blocked if t.status.value == "blocked"][:2]

            for task in blocked_tasks:
                dep_ids = ", ".join(task.depends_on[:2])
                suggestions.append(
                    f"Task '{task.title}' is blocked by: {dep_ids}. Resolve the dependencies first."
                )

            # Check long-running tasks → suggest follow-up
            pending = await scheduler.get_tasks_for_user(user_id, status=None)
            pending_tasks = [t for t in pending if t.status.value == "pending"][:2]

            for task in pending_tasks:
                if task.metadata.get("macro_title"):
                    suggestions.append(
                        f"Macro task '{task.metadata['macro_title']}' "
                        f"has pending subtasks. Check progress."
                    )

        except Exception:
            pass

        return suggestions[:max_suggestions]

    async def should_auto_create_task(self, intent: ParsedIntent) -> bool:
        """Decide whether to automatically create a task DAG.

        Auto-create when:
        - confidence >= 0.75 (high certainty)
        - action is not UNKNOWN
        - action is a multi-step operation (FIX_BUG, DEPLOY, CODE, RESEARCH)
        """
        if intent.confidence < 0.75:
            return False
        if intent.action == Intent.UNKNOWN:
            return False
        return intent.action in (
            Intent.FIX_BUG,
            Intent.DEPLOY,
            Intent.CODE,
            Intent.RESEARCH,
            Intent.BUILD,
            Intent.TEST,
            Intent.WRITE_BOOK,
        )

    # -------------------------------------------------------------------------
    # Alignment Guard — semantic drift detection
    # -------------------------------------------------------------------------

    async def check_alignment(
        self,
        user_message: str,
        user_id: str,
        goal_tracker: GoalTracker,
    ) -> AlignmentResult:
        """
        Check semantic drift between user message and active goal.

        Uses LLM to compute similarity. Returns AlignmentResult with drift level
        and confirmation message if needed.
        """
        goal_context = await goal_tracker.get_active_goal_context(user_id)
        active_goal_description = ""

        if not goal_context:
            # No active goal — nothing to drift from
            return AlignmentResult(
                drift_level=DriftLevel.LOW,
                similarity=1.0,
                active_goal_description="",
                current_intent_description=user_message,
                needs_confirmation=False,
                confirmation_message=None,
                evolution_history=[],
            )

        # Extract goal description from context (first line: "Goal: ...")
        for line in goal_context.split("\n"):
            if line.startswith("Goal:"):
                active_goal_description = line.removeprefix("Goal:").strip()
                break

        # Fetch evolution history for context
        active_goal = await goal_tracker.get_active_goal(user_id)
        evolution_history: list[EvolutionEntry] = []
        if active_goal:
            evolution_history = await goal_tracker.get_evolution_history(active_goal.goal_id)

        # Compute similarity via LLM
        similarity = await compute_similarity(user_message, active_goal_description)

        if similarity >= _DRIFT_SIMILARITY_LOW:
            drift_level = DriftLevel.LOW
            needs_confirmation = False
            confirmation_message = None
        elif similarity >= _DRIFT_SIMILARITY_MEDIUM:
            drift_level = DriftLevel.MEDIUM
            needs_confirmation = True
            confirmation_message = (
                f"检测到您发起的任务似乎属于另一个领域。"
                f"\n当前目标：{active_goal_description}"
                f"\n您的输入：{user_message}"
                f"\n是否创建一个新目标？"
            )
        else:
            drift_level = DriftLevel.HIGH
            needs_confirmation = True
            confirmation_message = (
                f"⚠️ 检测到高偏离！当前任务与您正在进行的目标无关。"
                f"\n当前目标：{active_goal_description}"
                f"\n您的输入：{user_message}"
                f"\n请确认是否要创建全新的任务？"
            )

        return AlignmentResult(
            drift_level=drift_level,
            similarity=similarity,
            active_goal_description=active_goal_description,
            current_intent_description=user_message,
            needs_confirmation=needs_confirmation,
            confirmation_message=confirmation_message,
            evolution_history=evolution_history,
        )


async def compute_similarity(text_a: str, text_b: str) -> float:
    """
    Compute semantic similarity between two strings using LLM.

    Returns a float in [0.0, 1.0]:
      >= 0.7 → LOW drift (aligned)
      0.4-0.7 → MEDIUM drift (confirmation required)
      < 0.4 → HIGH drift (context lock)
    """
    prompt = f"""Compute semantic similarity between two strings.

String A: "{text_a}"
String B: "{text_b}"

Rate how semantically related they are on a scale of 0.0 to 1.0:
- 1.0 = identical or perfectly aligned (same topic/goal)
- 0.7-0.9 = same domain, slightly different angle
- 0.4-0.7 = loosely related, could be same project
- 0.1-0.4 = tangentially related, different context
- 0.0 = completely unrelated

Return ONLY a number between 0.0 and 1.0 (no explanation).
"""
    try:
        result = await invoke(
            prompt=prompt,
            model="claude-haiku-4-5",
            max_turns=1,
            timeout_sec=15,
        )
        parsed = float(result.stdout.strip())
        return max(0.0, min(1.0, parsed))
    except Exception:
        # Fallback: keyword overlap as a rough similarity estimate
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())
        if not words_a or not words_b:
            return 0.0
        overlap = len(words_a & words_b) / len(words_a | words_b)
        return overlap
