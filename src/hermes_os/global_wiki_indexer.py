"""GlobalWikiIndexer — indexes the public global_wiki directory.

Mirrors BrainIndexer but for ~/.hermes/global_wiki/
Used by GovernanceManager.get_combined_context() for weighted search.

Directory structure:
    ~/.hermes/global_wiki/
    ├── wiki/
    │   ├── 概念/
    │   ├── 项目/
    │   ├── 人物/
    │   ├── 规则/
    │   ├── 流程/
    │   └── 模板/
    ├── MEMORY.md
    └── CONTRIBUTORS.md
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_GLOBAL_WIKI_BASE = Path.home() / ".hermes" / "global_wiki"


class GlobalWikiIndexer:
    """
    Reads and indexes the global_wiki directory.
    """

    def __init__(self, base_path: Path | None = None) -> None:
        self._base = base_path or _GLOBAL_WIKI_BASE
        self._cache: dict[str, str] = {}

    async def search_wiki(self, keyword: str) -> list[dict[str, Any]]:
        """
        Search global wiki entries for a keyword.
        Returns list of matching entries with category, file, path, snippet, source.
        """
        wiki_dir = self._base / "wiki"
        if not wiki_dir.exists():
            return []

        results: list[dict[str, Any]] = []
        keyword_lower = keyword.lower()

        for category_dir in wiki_dir.iterdir():
            if not category_dir.is_dir():
                continue
            for md_file in category_dir.iterdir():
                if md_file.suffix != ".md":
                    continue
                content = await self._read_file(md_file)
                if keyword_lower and keyword_lower not in content.lower():
                    continue

                # Extract snippet (first 200 chars)
                snippet = content[:200].replace("\n", " ").strip()

                results.append({
                    "category": category_dir.name,
                    "file": md_file.stem,
                    "path": str(md_file),
                    "snippet": snippet,
                    "source": "global_wiki",
                })

        return results

    async def list_all(self) -> list[dict[str, Any]]:
        """Return all wiki entries regardless of keyword match."""
        wiki_dir = self._base / "wiki"
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
                snippet = content[:200].replace("\n", " ").strip()

                results.append({
                    "category": category_dir.name,
                    "file": md_file.stem,
                    "path": str(md_file),
                    "snippet": snippet,
                    "source": "global_wiki",
                })

        return results

    async def _read_file(self, path: Path) -> str:
        """Read a file with caching, return empty string if not found."""
        key = str(path)
        if key in self._cache:
            return self._cache[key]

        if not path.exists():
            return ""

        try:
            content = path.read_text(encoding="utf-8")
            self._cache[key] = content
            return content
        except Exception:
            return ""