"""GovernanceLayer — dual-repo memory management for Hermes OS.

Dual-repo structure:
- Private:  ~/.hermes/users/{user_id}/brain/        (read-write, user-owned)
- Public:   ~/.hermes/global_wiki/                  (read-only, org-wide)

GovernanceManager responsibilities:
1. promote_to_global(): sanitize private MD → public wiki
2. get_combined_context(): weighted search (private=1.0, global=0.5)
3. Donation workflow: detect quality → prompt user → promote on approval
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_GLOBAL_WIKI_BASE = Path.home() / ".hermes" / "global_wiki"
_PRIVATE_BRAIN_BASE = Path.home() / ".hermes" / "users"

# Quality threshold for triggering donation prompt
_QUALITY_THRESHOLD = 0.3

# Default sanitization prompt for LLM-based PII removal
_DEFAULT_SANITIZATION_PROMPT = """You are a content sanitizer. Given input content, produce a sanitized version that:
1. Removes or redacts personal names → "[REDACTED_NAME]"
2. Removes email addresses → "[REDACTED_EMAIL]"
3. Removes phone numbers → "[REDACTED_PHONE]"
4. Removes specific project/code/company names → "[REDACTED_ENTITY]"
5. PRESERVES all technical content, concepts, processes, and generic knowledge
6. Returns ONLY the sanitized content, no explanation, no markdown code fences

Input content:
{content}"""


@dataclass
class PromotionResult:
    """Result of a promote_to_global() call."""

    success: bool
    global_path: str | None = None
    sanitized: bool = False
    error: str | None = None


@dataclass
class GovernanceConfig:
    """Configuration for governance behavior."""

    quality_threshold: float = _QUALITY_THRESHOLD
    global_wiki_base: Path = field(default_factory=lambda: _GLOBAL_WIKI_BASE)
    private_brain_base: Path = field(default_factory=lambda: _PRIVATE_BRAIN_BASE)
    sanitization_prompt: str = _DEFAULT_SANITIZATION_PROMPT


class GovernanceManager:
    """
    Manages dual-repo memory with governance policies.

    Private brain (user-owned) always beats public wiki (org-wide).
    Promotion to global requires user approval and LLM sanitization.
    """

    def __init__(
        self,
        db_path: str = "hermes_os.db",
        jarvis: Any = None,
    ) -> None:
        self._db_path = db_path
        self._jarvis = jarvis
        self._config = GovernanceConfig()
        self._ensure_global_wiki_exists()

    # -------------------------------------------------------------------------
    # Initialization helpers
    # -------------------------------------------------------------------------

    def _ensure_global_wiki_exists(self) -> None:
        """Create global_wiki structure if it doesn't exist."""
        self._config.global_wiki_base.mkdir(parents=True, exist_ok=True)
        wiki_dir = self._config.global_wiki_base / "wiki"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        for category in ["概念", "项目", "人物", "规则", "流程", "模板"]:
            (wiki_dir / category).mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # Core governance methods
    # -------------------------------------------------------------------------

    async def promote_to_global(
        self,
        user_id: str,
        path_to_md: str | Path,
        rules: dict[str, Any] | None = None,
    ) -> PromotionResult:
        """
        Sanitize and promote a private MD file to global_wiki.

        Steps:
        1. Read the private MD content
        2. Send to LLM for sanitization (remove PII)
        3. Determine target category from path or rules
        4. Write sanitized content to global_wiki
        5. Update CONTRIBUTORS.md

        Args:
            user_id: Owner of the content
            path_to_md: Path to the private .md file to promote
            rules: Optional sanitization rules (e.g., category override)

        Returns:
            PromotionResult with success, global_path, sanitized flag
        """
        try:
            src_path = Path(path_to_md)
            if not src_path.exists():
                return PromotionResult(success=False, error=f"File not found: {path_to_md}")

            content = src_path.read_text(encoding="utf-8")
            original_length = len(content)

            # LLM sanitization
            sanitized_content = await self._sanitize_content(content)
            sanitized = sanitized_content != content

            # Determine target category
            category = self._infer_category(src_path, rules)

            # Generate target filename (handle conflicts)
            filename = src_path.name
            target_dir = self._config.global_wiki_base / "wiki" / category
            target_path = target_dir / filename

            if target_path.exists():
                # Conflict: add timestamp suffix
                timestamp = datetime.now(UTC).strftime("%Y%m%d")
                stem = target_path.stem
                target_path = target_dir / f"{stem}_{timestamp}.md"

            # Write sanitized content
            target_path.write_text(sanitized_content, encoding="utf-8")

            # Record contribution
            await self._record_contribution(user_id, str(src_path), str(target_path))

            logger.info(
                "GovernanceManager: promoted %s → %s (sanitized=%s)",
                src_path,
                target_path,
                sanitized,
            )

            return PromotionResult(
                success=True,
                global_path=str(target_path),
                sanitized=sanitized,
            )

        except Exception as e:
            logger.exception("promote_to_global failed")
            return PromotionResult(success=False, error=str(e))

    async def get_combined_context(
        self,
        user_id: str,
        query: str,
    ) -> dict[str, Any]:
        """
        Search both private brain and global wiki with weighted scoring.

        Private (user brain): weight = 1.0
        Global (org wiki):     weight = 0.5

        When content exists in both, private wins (weight override to 1.0).

        Args:
            user_id: The user whose private brain to search
            query: Search keyword/phrase

        Returns:
            dict with keys: results (list), query (str),
            private_count (int), global_count (int)
        """
        # Import here to avoid circular deps
        from hermes_os.brain_indexer import BrainIndexer
        from hermes_os.global_wiki_indexer import GlobalWikiIndexer

        brain_indexer = BrainIndexer()
        wiki_indexer = GlobalWikiIndexer(base_path=self._config.global_wiki_base)

        # Search both sources in parallel
        private_results, global_results = await asyncio.gather(
            brain_indexer.search_wiki(user_id, query),
            wiki_indexer.search_wiki(query),
        )

        # Merge with weighted scoring
        merged: list[dict[str, Any]] = []
        seen_paths: set[str] = set()

        # Add private results first (higher priority)
        for r in private_results:
            r["weighted_score"] = 1.0
            seen_paths.add(r["path"])
            merged.append(r)

        # Add global results
        for r in global_results:
            if r["path"] not in seen_paths:
                r["weighted_score"] = 0.5
                merged.append(r)
            else:
                # Override: private beats global
                for existing in merged:
                    if existing["path"] == r["path"]:
                        existing["weighted_score"] = 1.0
                        break

        # Sort by weighted_score descending
        merged.sort(key=lambda x: x["weighted_score"], reverse=True)

        return {
            "results": merged,
            "query": query,
            "private_count": len(private_results),
            "global_count": len(global_results),
        }

    async def request_donation(
        self,
        user_id: str,
        content_path: str,
        category: str,
        snippet: str,
        task_id: str,
    ) -> None:
        """
        Send Feishu card prompting user to donate content to global wiki.

        Card has two buttons:
        - "✅ 贡献" → calls promote_to_global
        - "❌ 暂不" → declines

        Args:
            user_id: Feishu open_id
            content_path: Path to the content being donated
            category: Wiki category (概念/项目/etc)
            snippet: Preview of the content
            task_id: Task ID for card persistence
        """
        if self._jarvis is None:
            logger.debug("request_donation: no jarvis configured, skipping")
            return

        title = "🌐 贡献知识到全局知识库？"
        content = (
            f"您在「{category}/{Path(content_path).stem}」创建了高质量内容：\n\n"
            f"**{snippet[:200]}**\n\n"
            f"贡献到全局知识库可让所有团队成员受益。内容将经过脱敏处理。"
        )
        actions = [
            {
                "text": "✅ 贡献",
                "value": "donate_to_global",
                "type": "primary",
                "task_id": task_id,
                "content_path": content_path,
                "category": category,
            },
            {
                "text": "❌ 暂不",
                "value": "decline_donation",
                "type": "default",
                "task_id": task_id,
            },
        ]

        try:
            await self._jarvis.send_card_with_nl(
                user_id=user_id,
                title=title,
                content=content,
                actions=actions,
                nl_summary=f"请求贡献知识: {Path(content_path).stem}",
                task_id=task_id,
            )
            logger.info("GovernanceManager: donation card sent to user=%s", user_id)
        except Exception:
            logger.warning("Failed to send donation card to user %s", user_id)

    # -------------------------------------------------------------------------
    # Quality evaluation
    # -------------------------------------------------------------------------

    def _evaluate_content_quality(self, content: str) -> float:
        """
        Evaluate content quality for donation eligibility.

        Scoring factors:
        - Length: > 500 chars = +0.2
        - Structure: has ## or headers = +0.15
        - Lists: has bullet/numbered lists = +0.1
        - No placeholders: no TODO/FIXME/... = +0.1
        - Has substantial paragraphs = +0.1

        Returns: score 0.0 to 1.0
        """
        if not content:
            return 0.0

        score = 0.0

        # Length > 500 chars
        if len(content) > 500:
            score += 0.2

        # Has headers (## or #)
        if "##" in content or "\n# " in content:
            score += 0.15

        # Has lists (- or 1. or 2.)
        if any(marker in content for marker in ["\n- ", "\n1. ", "\n2. ", "\n* "]):
            score += 0.1

        # No placeholders
        placeholder_markers = ["TODO", "FIXME", "...", "TBD", "XXX"]
        if not any(marker in content.upper() for marker in placeholder_markers):
            score += 0.1

        # Has multiple paragraphs (blank line separated)
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        if len(paragraphs) >= 3:
            score += 0.1

        return min(score, 1.0)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    async def _sanitize_content(self, content: str) -> str:
        """Use LLM to sanitize content (remove PII)."""
        from hermes_os.claude_code_invocator import invoke

        prompt = self._config.sanitization_prompt.format(content=content)
        try:
            result = await invoke(
                prompt=prompt,
                max_turns=2,
                timeout_sec=30,
                output_format="text",
            )
            if result.ok and result.stdout.strip():
                return result.stdout.strip()
            return content
        except Exception:
            logger.warning("LLM sanitization failed, using original content")
            return content

    def _infer_category(self, path: Path, rules: dict[str, Any] | None = None) -> str:
        """Infer target category from path or rules."""
        if rules and "category" in rules:
            return rules["category"]

        path_str = str(path).lower()
        if "项目" in path_str or "project" in path_str:
            return "项目"
        if "人物" in path_str or "person" in path_str:
            return "人物"
        if "规则" in path_str or "rule" in path_str:
            return "规则"
        if "流程" in path_str or "process" in path_str:
            return "流程"
        if "模板" in path_str or "template" in path_str:
            return "模板"
        return "概念"  # default

    async def _record_contribution(
        self,
        user_id: str,
        source_path: str,
        target_path: str,
    ) -> None:
        """Append contribution to CONTRIBUTORS.md."""
        contributors_file = self._config.global_wiki_base / "CONTRIBUTORS.md"
        entry = (
            f"\n- **{datetime.now(UTC).strftime('%Y-%m-%d')}** {user_id}: "
            f"`{source_path}` → `{target_path}`"
        )
        existing = ""
        if contributors_file.exists():
            existing = contributors_file.read_text(encoding="utf-8")
        contributors_file.write_text(existing + entry, encoding="utf-8")
