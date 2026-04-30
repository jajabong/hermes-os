"""Organization Memory System — tracks skill effectiveness, decisions, and error patterns.

Provides:
- SkillLibrary: skill_name -> effectiveness score + use count
- DecisionLog: (task_id, decision, reason, timestamp)
- ErrorKnowledge: error_pattern -> solution

Used by TaskScheduler to inject relevant memory into invoke() calls.
"""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SkillRecord:
    """Tracks a skill's effectiveness over time."""
    name: str
    effectiveness: float = 0.5  # 0.0 to 1.0
    use_count: int = 0
    success_count: int = 0
    last_used: float = field(default_factory=time.time)

    def record_result(self, success: bool) -> None:
        """Update effectiveness based on task result."""
        self.use_count += 1
        if success:
            self.success_count += 1
        # Rolling average: blend previous effectiveness with new result
        new_effectiveness = self.success_count / self.use_count
        self.effectiveness = 0.7 * self.effectiveness + 0.3 * new_effectiveness
        self.last_used = time.time()


@dataclass
class DecisionRecord:
    """Logs a decision made during task execution."""
    task_id: str
    decision: str
    reason: str
    timestamp: float = field(default_factory=time.time)
    task_description: str = ""


class OrgMemory:
    """
    Organization-wide memory for tracking what works.
    
    Thread-safe singleton-like storage (no persistence across restarts yet).
    Integrates with TaskScheduler to inject relevant context into invoke() calls.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._skill_library: dict[str, SkillRecord] = {}
        self._decision_log: list[DecisionRecord] = []
        self._error_knowledge: dict[str, str] = {}  # pattern -> solution
        self._task_successes: dict[str, tuple[str, bool]] = {}  # task_desc_hash -> (description, success)

    # -------------------------------------------------------------------------
    # Skill effectiveness tracking
    # -------------------------------------------------------------------------

    def record_skill_use(self, skill_name: str, success: bool) -> None:
        """Record the result of using a skill (called by SkillLoader feedback)."""
        with self._lock:
            if skill_name not in self._skill_library:
                self._skill_library[skill_name] = SkillRecord(name=skill_name)
            self._skill_library[skill_name].record_result(success)

    def get_skill_effectiveness(self, skill_name: str) -> float:
        """Get effectiveness score for a skill (0.0 to 1.0)."""
        with self._lock:
            record = self._skill_library.get(skill_name)
            return record.effectiveness if record else 0.0

    def get_effective_skills(self, min_effectiveness: float = 0.3, limit: int = 10) -> list[tuple[str, float]]:
        """Return skills sorted by effectiveness descending.
        
        Args:
            min_effectiveness: Minimum score to include (0.0 to 1.0)
            limit: Maximum number of skills to return
            
        Returns:
            List of (skill_name, effectiveness) tuples
        """
        with self._lock:
            skills = [
                (name, rec.effectiveness)
                for name, rec in self._skill_library.items()
                if rec.effectiveness >= min_effectiveness and rec.use_count > 0
            ]
            skills.sort(key=lambda x: x[1], reverse=True)
            return skills[:limit]

    # -------------------------------------------------------------------------
    # Task result recording
    # -------------------------------------------------------------------------

    def record_task_result(self, task_description: str, success: bool, error: str | None = None) -> None:
        """Record what happened when a task was executed.
        
        This is the core feedback loop — call after every task completes.
        """
        with self._lock:
            # Generate a simple hash for the task description
            desc_hash = hash(task_description) % (10**9)
            self._task_successes[desc_hash] = (task_description, success)
            
            # Extract and record any skills mentioned in the task description
            skill_names = self._extract_skill_names(task_description)
            for skill_name in skill_names:
                if skill_name not in self._skill_library:
                    self._skill_library[skill_name] = SkillRecord(name=skill_name)
                self._skill_library[skill_name].record_result(success)
            
            # Record error knowledge if this was a failure
            if not success and error:
                self._record_error_pattern(task_description, error)

    def _extract_skill_names(self, text: str) -> list[str]:
        """Try to extract skill/tool names from task description."""
        names: list[str] = []
        # Common skill name patterns
        patterns = [
            r'use\s+skill[:\s]+([a-zA-Z0-9_-]+)',
            r'with\s+skill[:\s]+([a-zA-Z0-9_-]+)',
            r'apply\s+([a-zA-Z0-9_-]+)\s+skill',
            r'call\s+([a-zA-Z0-9_-]+)\s+tool',
            r'use\s+tool[:\s]+([a-zA-Z0-9_-]+)',
            r'execute\s+([a-zA-Z0-9_-]+)\s+skill',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                name = match.group(1).strip()
                if name:
                    names.append(name)
        return names

    def _record_error_pattern(self, task_description: str, error: str) -> None:
        """Record an error pattern and its attempted resolution."""
        # Normalize error: lowercase, strip line numbers
        normalized = error.lower()
        normalized = re.sub(r'line\s+\d+', 'line_N', normalized)
        normalized = re.sub(r'0x[0-9a-f]+', 'ADDR', normalized)
        normalized = re.sub(r'\d{4,}', 'NUM', normalized)
        normalized = normalized[:200]  # cap length
        
        if normalized and len(normalized) > 20:
            # Store error pattern -> solution (task that attempted to fix it)
            if normalized not in self._error_knowledge:
                self._error_knowledge[normalized] = task_description[:200]

    # -------------------------------------------------------------------------
    # Decision logging
    # -------------------------------------------------------------------------

    def record_decision(
        self,
        task_id: str,
        decision: str,
        reason: str,
        task_description: str = "",
    ) -> None:
        """Log a decision made during task planning/execution."""
        with self._lock:
            record = DecisionRecord(
                task_id=task_id,
                decision=decision,
                reason=reason,
                task_description=task_description,
            )
            self._decision_log.append(record)
            # Keep log bounded
            if len(self._decision_log) > 1000:
                self._decision_log = self._decision_log[-500:]

    # -------------------------------------------------------------------------
    # Memory search (injected into invoke system_prompt)
    # -------------------------------------------------------------------------

    def search_relevant_memory(self, query: str) -> str:
        """Search org memory and return relevant context as a formatted string.
        
        Called by TaskScheduler before invoke() to enrich the system prompt.
        Returns an empty string if nothing relevant is found.
        """
        if not query:
            return ""

        parts: list[str] = []
        
        # 1. Find similar past tasks and their outcomes
        similar_outcome = self._find_similar_tasks(query)
        if similar_outcome:
            parts.append(f"## Past Task Outcomes\n{similar_outcome}")
        
        # 2. Find relevant effective skills
        effective_skills = self.get_effective_skills(min_effectiveness=0.5, limit=5)
        if effective_skills:
            skill_lines = [f"- **{name}** (effectiveness: {score:.2f})" for name, score in effective_skills]
            parts.append(f"## Effective Skills\n" + "\n".join(skill_lines))
        
        # 3. Find error solutions for related errors
        error_solutions = self._find_error_solutions(query)
        if error_solutions:
            parts.append(f"## Known Error Solutions\n{error_solutions}")
        
        if not parts:
            return ""
        
        return "\n\n".join(parts)

    def _find_similar_tasks(self, query: str, max_results: int = 3) -> str:
        """Find tasks with similar descriptions and their outcomes."""
        query_words = set(query.lower().split())
        if not query_words:
            return ""
        
        results: list[tuple[int, str, bool]] = []  # score, description, success
        
        for desc_hash, (description, success) in list(self._task_successes.items()):
            desc_words = set(description.lower().split())
            # Score by word overlap
            overlap = query_words & desc_words
            if overlap:
                results.append((len(overlap), description, success))
        
        if not results:
            return ""
        
        # Sort by overlap score descending
        results.sort(key=lambda x: x[0], reverse=True)
        
        lines: list[str] = []
        for score, description, success in results[:max_results]:
            outcome = "SUCCESS" if success else "FAILED"
            lines.append(f"- [{outcome}] {description[:150]}")
        
        return "\n".join(lines)

    def _find_error_solutions(self, query: str, max_results: int = 3) -> str:
        """Find error patterns that match the query and their solutions."""
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        solutions: list[str] = []
        for pattern, solution in self._error_knowledge.items():
            pattern_words = set(pattern.split())
            # Check word overlap
            overlap = query_words & pattern_words
            if len(overlap) >= 2:  # at least 2 common words
                solutions.append(f"- Problem pattern: \"{pattern[:80]}...\"\n  Solution: {solution[:100]}")
        
        if not solutions:
            return ""
        return "\n".join(solutions[:max_results])

    # -------------------------------------------------------------------------
    # Stats / introspection
    # -------------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return memory statistics."""
        with self._lock:
            return {
                "skill_count": len(self._skill_library),
                "decision_log_size": len(self._decision_log),
                "error_pattern_count": len(self._error_knowledge),
                "task_record_count": len(self._task_successes),
                "top_skills": [
                    {"name": name, "effectiveness": rec.effectiveness, "uses": rec.use_count}
                    for name, rec in sorted(
                        self._skill_library.items(),
                        key=lambda x: x[1].effectiveness,
                        reverse=True,
                    )[:5]
                ],
            }
