"""Skill loader — reads transient skills and formats them for execution context.

Closes the SkillDiscovery feedback loop:
discover_and_learn() writes skills to ~/.hermes/skills/_transient/
SkillLoader reads them and injects into claude -p context.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hermes_os.skill_discovery import SkillDiscovery

# Transient skills written by SkillDiscovery
TRANSIENT_SKILLS_DIR = Path.home() / ".hermes" / "skills" / "_transient"


class SkillLoader:
    """Load, format, and manage transient skills discovered at runtime."""

    def __init__(
        self,
        transient_dir: Path | None = None,
        skill_discovery: SkillDiscovery | None = None,
    ) -> None:
        self._transient_dir = transient_dir or TRANSIENT_SKILLS_DIR
        self._transient_dir.mkdir(parents=True, exist_ok=True)
        self._skill_discovery = skill_discovery

    def _record_usage_async(self, skill_name: str) -> None:
        """Fire-and-forget record_usage call — doesn't block skill loading."""
        if self._skill_discovery is None:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._skill_discovery.record_usage(skill_name, success=True))
        except RuntimeError:
            pass  # No running loop

    def load_transient_skills(self, record_usage: bool = True) -> list[dict[str, Any]]:
        """Read all SKILL.md files in _transient/ and return metadata + content.

        Returns:
            List of skill dicts, each with keys:
            - name, description, quality_score, stars, content, discovered_from
        """
        skills: list[dict[str, Any]] = []

        if not self._transient_dir.exists():
            return skills

        for skill_dir in self._transient_dir.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                content = skill_file.read_text(encoding="utf-8")
                skill_data = self._parse_skill_file(content, skill_dir.name)
                if skill_data:
                    skills.append(skill_data)
            except Exception:
                continue

        # Sort by quality score descending
        skills.sort(key=lambda s: s.get("quality_score", 0.0), reverse=True)

        # Track usage for effectiveness loop (fire-and-forget)
        if record_usage:
            for skill in skills:
                self._record_usage_async(skill.get("name", ""))

        return skills

    def _parse_skill_file(self, content: str, dir_name: str) -> dict[str, Any] | None:
        """Parse a SKILL.md file, extracting frontmatter and body."""
        # Split frontmatter from body
        match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
        if not match:
            return None

        frontmatter_text = match.group(1)
        body = content[match.end() :].strip()

        # Parse frontmatter key:value lines
        data: dict[str, Any] = {"content": body}
        for line in frontmatter_text.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            data[key] = value

        # Type conversions
        data["quality_score"] = float(data.get("quality_score", 0.0))
        data["stars"] = int(data.get("stars", 0))
        data["name"] = data.get("name", dir_name)
        data["description"] = data.get("description", "")
        data["discovered_from"] = data.get("discovered_from", "")

        return data

    MAX_CONTENT_CHARS = 800  # Hard cap to prevent prompt bloat

    def get_skill_prompt_fragment(self, skill: dict[str, Any]) -> str:
        """Format a single skill as an injectable prompt fragment.

        Output format:
        ### Transient Skill: {name}
        Description: {description}
        Source: {discovered_from}

        {content_truncated}
        ---
        """
        name = skill.get("name", "unknown")
        description = skill.get("description", "")
        discovered_from = skill.get("discovered_from", "")
        content = skill.get("content", "")

        # Truncate content to MAX_CONTENT_CHARS to avoid prompt overflow
        if len(content) > self.MAX_CONTENT_CHARS:
            content = content[: self.MAX_CONTENT_CHARS].rstrip() + "\n…[truncated]"

        parts = [f"### Transient Skill: {name}"]
        if description:
            parts.append(f"Description: {description}")
        if discovered_from:
            parts.append(f"Source: {discovered_from}")
        parts.append("")
        parts.append(content)
        parts.append("---")
        return "\n".join(parts)

    def get_all_prompt_fragments(self, max_skills: int = 10, record_usage: bool = True) -> str:
        """Load all transient skills and return a merged fragment string.

        Useful for injecting into claude -p system_prompt or appending to prompt.
        Skips skills with quality_score < 0.3 (low quality).
        """
        skills = self.load_transient_skills(record_usage=record_usage)

        fragments: list[str] = []
        for skill in skills[:max_skills]:
            score = skill.get("quality_score", 0.0)
            if score < 0.3:
                continue
            fragments.append(self.get_skill_prompt_fragment(skill))

        if not fragments:
            return ""

        header = "## Transient Skills (auto-discovered, high quality)\n"
        return header + "\n\n".join(fragments)

    def get_skill_by_name(self, name: str) -> dict[str, Any] | None:
        """Get a single skill by name."""
        skills = self.load_transient_skills()
        for skill in skills:
            if skill.get("name") == name:
                return skill
        return None

    def invalidate_skill(self, skill_name: str) -> bool:
        """Delete a transient skill directory.

        Returns True if deleted, False if not found.
        """
        import shutil

        skill_path = self._transient_dir / skill_name
        if skill_path.exists() and skill_path.is_dir():
            shutil.rmtree(skill_path)
            return True
        return False

    def get_skill_count(self) -> int:
        """Return the number of transient skills currently loaded."""
        if not self._transient_dir.exists():
            return 0
        return sum(
            1 for d in self._transient_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()
        )
