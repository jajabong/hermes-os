"""Chief Agent — Intent Understanding Layer for Hermes OS.

Responsibilities:
1. Parse natural language into structured intents (via LLM)
2. Create task DAGs from intents (via TaskScheduler)
3. Proactively suggest next actions based on pending/failed tasks
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from hermes_os.claude_code_invocator import (
    DEFAULT_MAX_TURNS,
    DEFAULT_TIMEOUT_SEC,
    invoke,
)
from hermes_os.models import User
from hermes_os.org_context import (
    ORG_IDENTITY,
    ROLE_DEFINITIONS,
    Role,
    build_org_context,
    get_role_for_intent,
    _build_org_preamble,
)

# System prompt for ChiefAgent's parse_intent() — provides org identity context
CHIEF_SYSTEM_PROMPT = f"""You are the Intent Understanding Layer of Hermes OS — an AI-native virtual organization.

=== HERMES OS ORGANIZATION IDENTITY ===
{_build_org_preamble()}
"""
from hermes_os.task_scheduler import TaskPriority, TaskScheduler


class Intent(str, Enum):
    FIX_BUG = "fix_bug"
    DEPLOY = "deploy"
    RESEARCH = "research"
    CODE = "code"
    REVIEW = "review"
    TEST = "test"
    BUILD = "build"
    QUERY = "query"
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
  "action": "fix_bug|deploy|research|code|review|test|build|query|unknown",
  "confidence": 0.0-1.0,
  "entities": {{
    "target": "file/module/server target",
    "language": "programming language if applicable",
    "server": "deployment target if applicable",
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

    async def parse_intent(
        self,
        message: str,
        user_id: str,
        recent_tasks: str = "",
        recent_messages: str = "",
    ) -> ParsedIntent:
        """Parse user message into a structured ParsedIntent using LLM.

        Args:
            message: Raw user message
            user_id: For logging/context
            recent_tasks: Recent task history (optional)
            recent_messages: Recent conversation messages (optional)
        """
        context_parts = []
        if recent_tasks:
            context_parts.append(f"Recent tasks:\n{recent_tasks}")
        if recent_messages:
            context_parts.append(f"Recent messages:\n{recent_messages}")
        context = "\n\n".join(context_parts) or "No recent context available."

        prompt = INTENT_PROMPT_TEMPLATE.format(
            message=message,
            context=context,
        )

        try:
            result = await invoke(
                prompt=prompt,
                model=f"claude-{self.model}-4-6",
                max_turns=3,
                timeout_sec=30,
                output_format="json",
                json_schema=json.dumps(INTENT_SCHEMA),
                system_prompt=CHIEF_SYSTEM_PROMPT,
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

    def _rule_based_parse(self, message: str, context_parts: list[str] | None = None) -> ParsedIntent:
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
            },
        )
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
                    f"Task '{task.title}' is blocked by: {dep_ids}. "
                    f"Resolve the dependencies first."
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
        )
