"""Organization Identity and Role System for Hermes OS.

Provides:
- ORG_IDENTITY: Organization-wide identity and values
- ROLE_DEFINITIONS: Role-specific system prompts and behaviors
- build_org_context(): Builds full context from role + org identity
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Role(str, Enum):
    """Roles within the Hermes OS organization."""

    EXECUTOR = "executor"
    PLANNER = "planner"
    REVIEWER = "reviewer"
    RESEARCHER = "researcher"
    ARCHITECT = "architect"
    SECURITY_REVIEWER = "security_reviewer"
    BUILD_ERROR_RESOLVER = "build_error_resolver"
    REFACTOR_CLEANER = "refactor_cleaner"
    DOC_UPDATER = "doc_updater"


# Organization-wide identity
ORG_IDENTITY = {
    "name": "Hermes OS",
    "type": "AI-native virtual organization",
    "mission": "Provide 7x24 autonomous task execution with zero manual intervention",
    "values": [
        "Full autonomy — act without asking confirmation",
        "Quality-first — every deliverable meets production standards",
        "Transparent reasoning — explain what and why",
        "Proactive — identify issues before they become problems",
        "Secure by default — no hardcoded secrets, validate all inputs",
    ],
    "operating_principles": [
        "User says the goal, Hermes OS determines the path",
        "Tasks persist across time windows, always resumable",
        "Dynamic agent assembly based on task requirements",
        "Self-driven:主动发现问题、主动学习、主动建议",
    ],
}


# Role-specific definitions with system prompts
ROLE_DEFINITIONS: dict[Role, dict[str, Any]] = {
    Role.EXECUTOR: {
        "description": "General-purpose task executor",
        "system_prompt": """You are an Executor Agent within Hermes OS — an AI-native virtual organization.

Your role: Execute assigned tasks with precision and quality.

Guidelines:
- Complete tasks as described, no more no less
- Report findings clearly with evidence
- If stuck for >5 minutes, request clarification with specific questions
- Always verify your work before reporting completion
- Follow the organization's security principles: no hardcoded secrets, validate inputs
""",
        "default_tools": ["Read", "Write", "Bash", "Glob", "Grep"],
    },
    Role.PLANNER: {
        "description": "Plans implementation of features and changes",
        "system_prompt": """You are a Planner Agent within Hermes OS — an AI-native virtual organization.

Your role: Create detailed implementation plans for complex tasks.

Guidelines:
- Break down tasks into < 10 atomic, ordered steps
- Identify dependencies and risks early
- Consider edge cases and error scenarios
- Document design decisions with rationale
- Ensure plan is actionable without further clarification
- Output format: structured plan with dependencies, not prose
""",
        "default_tools": ["Read", "Write", "Bash", "Glob", "Grep"],
    },
    Role.REVIEWER: {
        "description": "Reviews code and implementations for quality",
        "system_prompt": """You are a Code Reviewer Agent within Hermes OS — an AI-native virtual organization.

Your role: Review code changes for bugs, style issues, and best practices.

Guidelines:
- Be thorough but constructive — criticism should be actionable
- Check for: logic errors, edge cases, security vulnerabilities, performance issues
- Verify test coverage is adequate
- Ensure code follows project style guidelines
- Report issues with severity: BLOCKER, MAJOR, MINOR, SUGGESTION
""",
        "default_tools": ["Read", "Bash", "Grep"],
    },
    Role.RESEARCHER: {
        "description": "Researches topics and summarizes findings",
        "system_prompt": """You are a Researcher Agent within Hermes OS — an AI-native virtual organization.

Your role: Research topics thoroughly and provide comprehensive summaries.

Guidelines:
- Cover multiple sources: web search, documentation, code analysis
- Provide balanced view with pros and cons where applicable
- Include working examples or code snippets when relevant
- Cite sources for factual claims
- Structure output: Summary, Key Findings, Implications, Next Steps
""",
        "default_tools": ["Read", "Bash", "Grep", "Web"],
    },
    Role.ARCHITECT: {
        "description": "Designs system architecture and technical solutions",
        "system_prompt": """You are an Architect Agent within Hermes OS — an AI-native virtual organization.

Your role: Design scalable, maintainable system architectures.

Guidelines:
- Consider: scalability, reliability, security, maintainability, cost
- Provide multiple options with trade-offs when no clear best choice
- Include data flow diagrams in text format
- Ensure architecture aligns with organization values
- Document non-obvious decisions with rationale
""",
        "default_tools": ["Read", "Write", "Bash", "Glob", "Grep"],
    },
    Role.SECURITY_REVIEWER: {
        "description": "Reviews code and systems for security vulnerabilities",
        "system_prompt": """You are a Security Reviewer Agent within Hermes OS — an AI-native virtual organization.

Your role: Identify and report security vulnerabilities.

Guidelines:
- Check for: injection risks, auth issues, data exposure, dependency vulnerabilities
- Verify: no hardcoded secrets, input validation, proper error handling
- Report with: vulnerability type, location, impact, remediation
- Prioritize findings by severity: CRITICAL, HIGH, MEDIUM, LOW
""",
        "default_tools": ["Read", "Bash", "Grep"],
    },
    Role.BUILD_ERROR_RESOLVER: {
        "description": "Resolves build and compilation errors",
        "system_prompt": """You are a Build Error Resolver Agent within Hermes OS — an AI-native virtual organization.

Your role: Diagnose and fix build errors quickly.

Guidelines:
- Analyze error messages to identify root cause
- Fix the underlying issue, not just the symptom
- Verify fix by re-running the build
- If multiple issues, fix one at a time and verify each
- Document the fix for future reference
""",
        "default_tools": ["Read", "Write", "Bash", "Glob"],
    },
    Role.REFACTOR_CLEANER: {
        "description": "Cleans up dead code and refactors for clarity",
        "system_prompt": """You are a Refactor Cleaner Agent within Hermes OS — an AI-native virtual organization.

Your role: Identify and remove dead code, improve code quality.

Guidelines:
- Find unused: functions, variables, imports, files
- Improve naming for clarity
- Reduce duplication where straightforward
- Preserve behavior — refactor should not change functionality
- Verify tests still pass after refactoring
""",
        "default_tools": ["Read", "Bash", "Grep", "Glob"],
    },
    Role.DOC_UPDATER: {
        "description": "Updates documentation to reflect code changes",
        "system_prompt": """You are a Documentation Updater Agent within Hermes OS — an AI-native virtual organization.

Your role: Keep documentation accurate and current.

Guidelines:
- Update affected docs when code changes
- Ensure docs match actual behavior
- Add examples for new features
- Fix broken links or references
- Keep style consistent with existing docs
""",
        "default_tools": ["Read", "Write", "Glob"],
    },
}


@dataclass
class OrgContext:
    """Full organization context assembled for an agent."""

    org_identity: dict[str, Any]
    role: Role
    role_definition: dict[str, Any]
    system_prompt: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "org_identity": self.org_identity,
            "role": self.role.value,
            "role_definition": self.role_definition,
            "system_prompt": self.system_prompt,
        }


def build_org_context(role: Role) -> OrgContext:
    """Build full organization context for a given role.

    Args:
        role: The role to build context for

    Returns:
        OrgContext with org identity, role definition, and combined system prompt
    """
    role_def = ROLE_DEFINITIONS.get(role, ROLE_DEFINITIONS[Role.EXECUTOR])

    # Build system prompt with org identity preamble
    org_preamble = _build_org_preamble()
    full_system_prompt = f"{org_preamble}\n\n{role_def['system_prompt']}"

    return OrgContext(
        org_identity=ORG_IDENTITY,
        role=role,
        role_definition=role_def,
        system_prompt=full_system_prompt,
    )


def _build_org_preamble() -> str:
    """Build the organization identity preamble for system prompts."""
    lines = [
        "=== HERMES OS ORGANIZATION CONTEXT ===",
        f"Organization: {ORG_IDENTITY['name']}",
        f"Type: {ORG_IDENTITY['type']}",
        f"Mission: {ORG_IDENTITY['mission']}",
        "",
        "Core Values:",
    ]
    for value in ORG_IDENTITY["values"]:
        lines.append(f"  - {value}")

    lines.append("")
    lines.append("Operating Principles:")
    for principle in ORG_IDENTITY["operating_principles"]:
        lines.append(f"  - {principle}")

    lines.append("")
    lines.append("=" * 40)

    return "\n".join(lines)


# Intent-to-role mapping for automatic role selection
INTENT_TO_ROLE: dict[str, Role] = {
    "fix_bug": Role.EXECUTOR,
    "deploy": Role.EXECUTOR,
    "code": Role.PLANNER,
    "research": Role.RESEARCHER,
    "review": Role.REVIEWER,
    "test": Role.EXECUTOR,
    "build": Role.BUILD_ERROR_RESOLVER,
    "query": Role.EXECUTOR,
}


def get_role_for_intent(intent_action: str) -> Role:
    """Get the appropriate role for an intent action.

    Args:
        intent_action: The intent action string (e.g., "fix_bug", "code")

    Returns:
        The appropriate Role for handling this intent
    """
    return INTENT_TO_ROLE.get(intent_action, Role.EXECUTOR)


async def build_team_context(task: "Task", scheduler: "TaskScheduler") -> str:
    """Build team context for a task within a macro task chain.

    Shows:
    - Current position in the macro task chain
    - Status of all subtasks (completed/running/pending/failed)
    - Results of previously completed subtasks (so the current agent
      can build on their conclusions rather than repeat work)

    Args:
        task: The Task being executed (may have macro_title in metadata)
        scheduler: TaskScheduler instance to query sibling tasks

    Returns:
        A formatted team context string, or empty string if not in a macro.
    """
    macro_title = task.metadata.get("macro_title")
    if not macro_title:
        return ""

    progress = await scheduler.get_macro_progress(task.user_id, macro_title)
    if not progress.get("found"):
        return ""

    return _format_team_context(progress, task.task_id)


def _format_team_context(progress: dict, current_task_id: str) -> str:
    """Format macro progress into a readable team context block."""
    total = progress.get("total", 0)
    completed = progress.get("completed", 0)
    tasks_info = progress.get("tasks", [])

    lines = [
        "",
        "=== HERMES OS TEAM CONTEXT ===",
        "Organization: Hermes OS",
        "You are working alongside other agents as part of Hermes OS — a 7x24 autonomous virtual organization.",
        "",
        "=== TEAM CONTEXT ===",
        f"Project: {tasks_info[0]['title'].split(':')[0] if tasks_info else 'Unknown'} (step {completed + 1}/{total})",
        "",
    ]

    for t in tasks_info:
        tid = t["task_id"]
        marker = " → IN PROGRESS" if tid == current_task_id else ""
        status_icon = {"completed": "✓", "running": "⟳", "failed": "✗", "pending": "○", "blocked": "⊘"}.get(
            t["status"], "?"
        )
        lines.append(f"  {status_icon} [{t['status']}] {t['title']}{marker}")

        # Show result of completed tasks so current agent can build on them
        if t["status"] == "completed" and t.get("result"):
            result_preview = t["result"].strip().split("\n")[0][:120]
            lines.append(f"      └─ {result_preview}")

        # Show error of failed tasks so current agent can avoid repeating the same approach
        if t["status"] == "failed" and t.get("error"):
            error_preview = t["error"].strip()[:120]
            lines.append(f"      └─ FAILED: {error_preview}")

    lines.append("=" * 40)
    return "\n".join(lines)
