"""BrainUpdater — automatically updates brain directory after task completion."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hermes_os.task_scheduler import Task

logger = logging.getLogger(__name__)

_USER_BRAIN_BASE = Path.home() / ".hermes" / "users"


class BrainUpdater:
    """
    Automatically updates brain directory after task completion.

    Operations:
    - Write task output to brain/产出/ACTIVE/
    - Update MEMORY.md on milestones
    - Update wiki/项目/ for project-related tasks
    """

    def __init__(self) -> None:
        self._project_keywords = {
            "项目": "wiki/项目/",
            "研究": "wiki/概念/",
            "会议": "wiki/事件/",
        }

    def _brain_path(self, user_id: str) -> Path:
        return _USER_BRAIN_BASE / user_id / "brain"

    async def after_task_complete(
        self,
        task: Task,
        result: str,
        user_brain_path: Path | None = None,
    ) -> bool:
        """
        After a task completes, archive the result to brain.

        Args:
            task: The completed task object
            result: Task execution result string
            user_brain_path: Optional explicit path (for testing)

        Returns:
            True if written successfully, False otherwise
        """
        try:
            if user_brain_path:
                output_dir = user_brain_path
            else:
                brain_dir = self._brain_path(task.user_id)
                output_dir = brain_dir / "产出" / "ACTIVE"
            output_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            output_file = output_dir / f"{timestamp}_{task.task_id[:8]}.md"

            content = self._format_output(task, result)
            await self._write_file(output_file, content)

            logger.info(
                "BrainUpdater: archived task result to %s",
                output_file,
            )
            return True

        except Exception as e:
            logger.warning("BrainUpdater: failed to write output: %s", e)
            return False

    async def update_memory_on_milestone(
        self,
        memory_file: Path,
        milestone: str,
    ) -> None:
        """
        Append a milestone to MEMORY.md.

        Format: section separator + milestone entry
        """
        separator = "\n§\n"
        entry = f"**{datetime.now(UTC).strftime('%Y-%m-%d')}**: {milestone}\n"

        existing = ""
        if memory_file.exists():
            existing = memory_file.read_text(encoding="utf-8")

        updated = existing + separator + entry

        await self._write_file(memory_file, updated)

    async def update_project_wiki(
        self,
        wiki_dir: Path,
        project_name: str,
        update: dict[str, Any],
    ) -> None:
        """
        Create or update a project wiki entry.

        Args:
            wiki_dir: Path to wiki/项目/
            project_name: Name of the project (file stem)
            update: Dict with fields like {status, progress, notes}
        """
        project_file = wiki_dir / f"{project_name}.md"
        existing = ""
        if project_file.exists():
            existing = project_file.read_text(encoding="utf-8")

        # Build updated content
        content = self._build_project_wiki(project_name, update, existing)
        await self._write_file(project_file, content)

    async def read_recent_outputs(
        self,
        output_dir: Path,
        limit: int = 10,
    ) -> list[str]:
        """Read recent output files from 产出/ACTIVE/."""
        if not output_dir.exists():
            return []

        files = sorted(
            output_dir.glob("*.md"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )[:limit]

        results = []
        for f in files:
            try:
                results.append(f.read_text(encoding="utf-8"))
            except Exception:
                continue

        return results

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _format_output(self, task: Task, result: str) -> str:
        """Format task result as a brain output entry."""
        title = task.title or "Untitled"
        task_id = task.task_id[:8]
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")

        # Truncate long results
        truncated = result[:2000] + "..." if len(result) > 2000 else result

        return f"""# {title}

**Task ID**: {task_id}
**Completed**: {timestamp}
**Status**: {task.status.value if hasattr(task.status, "value") else str(task.status)}

## Result

{truncated}

## Metadata

- Priority: {task.priority.value if hasattr(task.priority, "value") else str(task.priority)}
"""

    def _build_project_wiki(
        self,
        project_name: str,
        update: dict[str, Any],
        existing: str,
    ) -> str:
        """Build or update a project wiki entry."""
        lines = [f"# {project_name}\n"]

        for key, value in update.items():
            lines.append(f"**{key}**: {value}")

        if existing:
            # Append update to existing content
            lines.append(f"\n---\n*Updated {datetime.now(UTC).strftime('%Y-%m-%d')}*")

        return "\n".join(lines)

    async def _write_file(self, path: Path, content: str) -> None:
        """Async file write."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: path.write_text(content, encoding="utf-8"),
        )
