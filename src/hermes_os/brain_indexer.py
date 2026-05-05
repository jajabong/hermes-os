"""BrainIndexer — reads and indexes user brain directories."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_USER_BRAIN_BASE = Path.home() / ".hermes" / "users"


@dataclass
class BrainIndex:
    """Full index of a user's brain directory."""

    user_id: str
    memory_summary: str = ""
    user_profile: dict[str, Any] = field(default_factory=dict)
    active_projects: list[str] = field(default_factory=list)
    recent_wiki_updates: list[str] = field(default_factory=list)
    last_indexed: datetime = field(default_factory=lambda: datetime.now(UTC))


class BrainIndexer:
    """
    Reads and indexes a user's brain directory.

    Brain structure:
        ~/.hermes/users/{user_id}/brain/
        ├── MEMORY.md       — compressed memory
        ├── USER.md         — user identity
        ├── wiki/项目/       — project entries
        ├── wiki/人物/       — person entries
        ├── wiki/概念/       — concept entries
        └── ...
    """

    def __init__(self, brain_base_path: Path | None = None) -> None:
        self._cache: dict[str, BrainIndex] = {}
        self._base_path = brain_base_path or _USER_BRAIN_BASE

    def _brain_path(self, user_id: str) -> Path:
        return self._base_path / user_id / "brain"

    async def index_user(self, user_id: str) -> BrainIndex:
        """
        Read and index a user's brain directory.

        Returns an empty BrainIndex if the brain directory doesn't exist.
        """
        if user_id in self._cache:
            return self._cache[user_id]

        brain_dir = self._brain_path(user_id)
        if not brain_dir.exists():
            return BrainIndex(user_id=user_id)

        memory_summary = await self._read_file(brain_dir / "MEMORY.md")
        user_profile = await self._read_user_md(brain_dir / "USER.md")
        active_projects = await self._list_projects(brain_dir / "wiki" / "项目")
        recent_wiki = await self._list_recent_wiki(brain_dir / "wiki")

        index = BrainIndex(
            user_id=user_id,
            memory_summary=memory_summary,
            user_profile=user_profile,
            active_projects=active_projects,
            recent_wiki_updates=recent_wiki,
        )

        self._cache[user_id] = index
        return index

    async def search_wiki(self, user_id: str, keyword: str) -> list[dict[str, Any]]:
        """Search wiki entries for a keyword."""
        brain_dir = self._brain_path(user_id)
        wiki_dir = brain_dir / "wiki"
        if not wiki_dir.exists():
            return []

        results: list[dict[str, Any]] = []
        for category_dir in wiki_dir.iterdir():
            if not category_dir.is_dir():
                continue
            for md_file in category_dir.iterdir():
                if md_file.suffix != ".md":
                    continue
                content = await self._read_file(md_file)
                if keyword.lower() in content.lower():
                    results.append({
                        "category": category_dir.name,
                        "file": md_file.stem,
                        "path": str(md_file),
                        "snippet": content[:200],
                    })
        return results

    async def get_active_projects(self, user_id: str) -> list[str]:
        """List all project names from wiki/项目/."""
        brain_dir = self._brain_path(user_id)
        projects_dir = brain_dir / "wiki" / "项目"
        if not projects_dir.exists():
            return []

        return [f.stem for f in projects_dir.iterdir() if f.suffix == ".md"]

    async def get_project_context(
        self, user_id: str, project_name: str
    ) -> dict[str, Any] | None:
        """Read a project wiki entry."""
        brain_dir = self._brain_path(user_id)
        project_file = brain_dir / "wiki" / "项目" / f"{project_name}.md"
        if not project_file.exists():
            return None

        content = await self._read_file(project_file)
        return {
            "name": project_name,
            "content": content,
            "path": str(project_file),
        }

    async def _read_file(self, path: Path) -> str:
        """Read a file, return empty string if not found."""
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return ""

    async def _read_user_md(self, path: Path) -> dict[str, Any]:
        """Parse USER.md into a profile dict."""
        content = await self._read_file(path)
        if not content:
            return {}

        profile: dict[str, Any] = {}
        for line in content.split("\n"):
            if "，" in line and not line.startswith("#"):
                parts = line.split("，", 1)
                if len(parts) >= 2:
                    profile.setdefault("name", parts[0])
                    profile.setdefault("org", parts[1])
            if line.startswith("§"):
                break
        return profile

    async def _list_projects(self, projects_dir: Path) -> list[str]:
        """List project names from wiki/项目/ directory."""
        if not projects_dir.exists():
            return []
        return [f.stem for f in projects_dir.iterdir() if f.suffix == ".md"]

    async def _list_recent_wiki(self, wiki_dir: Path) -> list[str]:
        """List recently updated wiki entries."""
        if not wiki_dir.exists():
            return []
        results = []
        for category_dir in wiki_dir.iterdir():
            if not category_dir.is_dir():
                continue
            for md_file in category_dir.iterdir():
                if md_file.suffix == ".md":
                    results.append(f"{category_dir.name}/{md_file.stem}")
        return results[-10:]  # last 10 updates