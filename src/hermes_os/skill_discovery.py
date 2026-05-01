"""GitHub-based skill discovery and auto-learning.

Enables Hermes OS to:
- Detect capability gaps during task execution
- Search GitHub for relevant skills/agents/best practices
- Read and understand skill formats
- Store as transient skills for immediate use
- Evaluate effectiveness and decide whether to solidify
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite


# Path where transient skills are stored
TRANSIENT_SKILLS_DIR = Path.home() / ".hermes" / "skills" / "_transient"
SOLIDIFIED_SKILLS_DIR = Path.home() / ".hermes" / "skills"


@dataclass
class DiscoveredSkill:
    """A skill discovered from GitHub."""
    repo: str
    path: str
    name: str
    description: str
    stars: int
    url: str
    content: str | None = None
    quality_score: float = 0.0
    discovered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    usage_count: int = 0
    last_used: datetime | None = None
    solidified: bool = False


@dataclass
class CapabilityGap:
    """A detected gap in Hermes OS capabilities."""
    gap_type: str  # "missing_agent", "missing_skill", "missing_knowledge"
    description: str
    context: str  # What task triggered this detection
    suggested_search: str  # GitHub search query
    discovered_skills: list[DiscoveredSkill] = field(default_factory=list)
    resolved: bool = False


class SkillDiscovery:
    """Discovers, learns, and manages skills from GitHub.

    The discovery loop:
    1. Detect gap (during task execution or proactively)
    2. Search GitHub (via gh CLI or direct API)
    3. Evaluate and select best match
    4. Read and understand the skill
    5. Store as transient skill
    6. Use in task execution
    7. Evaluate effectiveness
    8. Decide: solidify or discard
    """

    def __init__(self, db_path: str = "hermes_os.db") -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._gh_available: bool | None = None

    async def _get_db(self) -> aiosqlite.Connection:
        if self._db is None:
            self._db = await aiosqlite.connect(self.db_path)
            self._db.row_factory = aiosqlite.Row
            await self._apply_pragmas(self._db)
        return self._db

    async def _apply_pragmas(self, db: aiosqlite.Connection) -> None:
        """Enforce WAL mode and normal synchronous for better concurrency."""
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")

    async def _lazy_init(self) -> None:
        db = await self._get_db()
        await db.execute("""
            CREATE TABLE IF NOT EXISTS discovered_skills (
                repo TEXT,
                path TEXT,
                name TEXT,
                description TEXT,
                stars INTEGER DEFAULT 0,
                url TEXT,
                content TEXT DEFAULT '',
                quality_score REAL DEFAULT 0.0,
                discovered_at TEXT,
                usage_count INTEGER DEFAULT 0,
                last_used TEXT,
                solidified INTEGER DEFAULT 0,
                PRIMARY KEY (repo, path)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS capability_gaps (
                gap_id TEXT PRIMARY KEY,
                gap_type TEXT,
                description TEXT,
                context TEXT,
                suggested_search TEXT,
                resolved INTEGER DEFAULT 0,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS skill_effectiveness (
                skill_key TEXT PRIMARY KEY,
                uses INTEGER DEFAULT 0,
                successes INTEGER DEFAULT 0,
                failures INTEGER DEFAULT 0,
                last_evaluated TEXT,
                decision TEXT DEFAULT ''
            )
        """)
        await db.commit()

        # Ensure transient skills directory exists
        TRANSIENT_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    def _check_gh(self) -> bool:
        """Check if gh CLI is available."""
        if self._gh_available is None:
            try:
                subprocess.run(
                    ["gh", "--version"],
                    capture_output=True,
                    timeout=5,
                )
                self._gh_available = True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                self._gh_available = False
        return self._gh_available

    # -------------------------------------------------------------------------
    # Gap Detection
    # -------------------------------------------------------------------------

    async def detect_gap(
        self, gap_type: str, description: str, context: str, suggested_search: str
    ) -> CapabilityGap:
        """Record a detected capability gap."""
        await self._lazy_init()
        import uuid

        gap = CapabilityGap(
            gap_type=gap_type,
            description=description,
            context=context,
            suggested_search=suggested_search,
        )

        db = await self._get_db()
        await db.execute(
            """
            INSERT OR IGNORE INTO capability_gaps
            (gap_id, gap_type, description, context, suggested_search, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                gap_type,
                description,
                context,
                suggested_search,
                datetime.now(UTC).isoformat(),
            ),
        )
        await db.commit()
        return gap

    async def get_unresolved_gaps(self) -> list[CapabilityGap]:
        """Get all unresolved capability gaps."""
        await self._lazy_init()
        db = await self._get_db()
        async with db.execute(
            "SELECT * FROM capability_gaps WHERE resolved = 0"
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                CapabilityGap(
                    gap_type=row["gap_type"],
                    description=row["description"],
                    context=row["context"],
                    suggested_search=row["suggested_search"],
                    resolved=bool(row["resolved"]),
                )
                for row in rows
            ]

    async def resolve_gap(self, gap_id: str) -> None:
        """Mark a gap as resolved."""
        await self._lazy_init()
        db = await self._get_db()
        await db.execute(
            "UPDATE capability_gaps SET resolved = 1 WHERE gap_id = ?",
            (gap_id,),
        )
        await db.commit()

    # -------------------------------------------------------------------------
    # GitHub Search
    # -------------------------------------------------------------------------

    async def search_github(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """Search GitHub for repositories matching a query.

        Uses gh CLI if available, falls back to direct API via curl.
        """
        await self._lazy_init()

        if self._check_gh():
            return await self._search_via_gh(query, max_results)
        else:
            return await self._search_via_api(query, max_results)

    async def _search_via_gh(self, query: str, max_results: int) -> list[dict[str, Any]]:
        """Search via gh CLI."""
        cmd = [
            "gh", "api",
            f"/search/repositories?q={query}&sort=stars&per_page={max_results}",
            "--jq", ".items[] | {full_name, description, stargazers_count, html_url, topics}"
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                return [json.loads(line) for line in lines if line.strip()]
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            pass
        return []

    async def _search_via_api(self, query: str, max_results: int) -> list[dict[str, Any]]:
        """Search via direct GitHub API (rate limited, use carefully)."""
        import os
        token = os.environ.get("GITHUB_TOKEN", "")

        headers = {
            "Accept": "application/vnd.github.v3+json",
        }
        if token:
            headers["Authorization"] = f"token {token}"

        url = f"https://api.github.com/search/repositories?q={query}&sort=stars&per_page={max_results}"

        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", "-L", url,
                "-H", f"Authorization: token {token}" if token else "",
                "-H", "Accept: application/vnd.github.v3+json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            data = json.loads(stdout.decode())
            return [
                {
                    "full_name": r["full_name"],
                    "description": r.get("description", ""),
                    "stargazers_count": r.get("stargazers_count", 0),
                    "html_url": r.get("html_url", ""),
                    "topics": r.get("topics", []),
                }
                for r in data.get("items", [])
            ]
        except (asyncio.TimeoutError, json.JSONDecodeError, OSError):
            return []

    async def read_file_from_repo(
        self, repo: str, path: str
    ) -> str | None:
        """Read a specific file from a GitHub repository.

        Uses gh CLI for authenticated requests, falls back to raw.githubusercontent.com.
        """
        if self._check_gh():
            cmd = ["gh", "api", f"/repos/{repo}/contents/{path}", "--jq", ".content"]
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0:
                    import base64
                    content = result.stdout.strip()
                    # gh returns base64-encoded content with newlines
                    try:
                        return base64.b64decode(content).decode("utf-8")
                    except Exception:
                        return content
            except (subprocess.TimeoutExpired, OSError):
                pass

        # Fallback: raw.githubusercontent.com
        url = f"https://raw.githubusercontent.com/{repo}/main/{path}"
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", "-L", url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            return stdout.decode("utf-8")
        except (asyncio.TimeoutError, OSError):
            return None

    # -------------------------------------------------------------------------
    # Skill Evaluation
    # -------------------------------------------------------------------------

    def evaluate_skill_quality(
        self,
        content: str,
        stars: int,
        description: str,
        query: str,
    ) -> float:
        """Score a discovered skill for quality.

        Factors:
        - Star count (social proof)
        - Relevance to query (keyword match)
        - Completeness (has required sections)
        - Format quality (SKILL.md pattern)
        """
        score = 0.0

        # Stars factor (log scale, max 0.3)
        import math
        score += min(0.3, math.log1p(stars) / 20)

        # Description relevance (max 0.2)
        query_keywords = query.lower().split()
        desc_lower = description.lower()
        matches = sum(1 for kw in query_keywords if kw in desc_lower)
        score += min(0.2, matches * 0.05)

        # Content quality checks (max 0.5)
        content_lower = content.lower()
        has_trigger = any(kw in content_lower for kw in [
            "when", "trigger", "if the user", "task", "skill"
        ])
        has_steps = any(kw in content_lower for kw in [
            "step", "1.", "2.", "first", "then", "##"
        ])
        has_tools = any(kw in content_lower for kw in [
            "tool", "bash", "read", "write", "edit", "terminal"
        ])

        if has_trigger:
            score += 0.15
        if has_steps:
            score += 0.15
        if has_tools:
            score += 0.2

        return min(1.0, score)

    async def discover_and_learn(
        self,
        query: str,
        gap_type: str = "missing_skill",
        context: str = "",
    ) -> DiscoveredSkill | None:
        """Full discovery loop: search → evaluate → store as transient skill.

        Returns the discovered skill if successful, None otherwise.
        """
        await self._lazy_init()

        # Step 1: Search GitHub
        results = await self.search_github(query, max_results=5)
        if not results:
            return None

        best: DiscoveredSkill | None = None
        best_score = 0.0

        for repo_info in results:
            repo = repo_info["full_name"]
            # Try common skill file paths
            for path_candidate in [
                f"skills/{query.split()[0]}/SKILL.md",
                f"skills/{query.replace(' ', '-').lower()}/SKILL.md",
                "SKILL.md",
                "README.md",
                f"agent.md",
            ]:
                content = await self.read_file_from_repo(repo, path_candidate)
                if not content or len(content) < 200:
                    continue

                score = self.evaluate_skill_quality(
                    content=content,
                    stars=repo_info.get("stargazers_count", 0),
                    description=repo_info.get("description", ""),
                    query=query,
                )

                if score > best_score:
                    skill_name = self._extract_skill_name(path_candidate, repo, query)
                    skill = DiscoveredSkill(
                        repo=repo,
                        path=path_candidate,
                        name=skill_name,
                        description=repo_info.get("description", ""),
                        stars=repo_info.get("stargazers_count", 0),
                        url=repo_info.get("html_url", ""),
                        content=content,
                        quality_score=score,
                    )
                    best_score = score
                    best = skill

        if best is None:
            return None

        # Step 2: Store as transient skill
        await self._store_transient_skill(best)

        # Step 3: Persist discovery metadata
        await self._persist_discovery(best)

        return best

    def _extract_skill_name(self, path: str, repo: str, query: str) -> str:
        """Derive a skill name from path or query."""
        if path == "SKILL.md":
            return f"transient-{query.replace(' ', '-').lower()[:30]}"
        parts = Path(path).parts
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1][:30]}"
        return query.replace(" ", "-").lower()[:30]

    async def _store_transient_skill(self, skill: DiscoveredSkill) -> Path:
        """Write a transient skill file to ~/.hermes/skills/_transient/."""
        if not skill.content:
            raise ValueError("Cannot store skill with no content")

        skill_dir = TRANSIENT_SKILLS_DIR / skill.name
        skill_dir.mkdir(parents=True, exist_ok=True)

        skill_file = skill_dir / "SKILL.md"
        # Prepend discovery metadata as frontmatter
        frontmatter = f"""---
name: {skill.name}
description: "{skill.description}"
discovered_from: {skill.repo}
discovered_url: {skill.url}
quality_score: {skill.quality_score:.2f}
stars: {skill.stars}
transient: true
---

"""
        full_content = frontmatter + skill.content
        skill_file.write_text(full_content, encoding="utf-8")
        return skill_file

    async def _persist_discovery(self, skill: DiscoveredSkill) -> None:
        """Save discovery metadata to SQLite."""
        db = await self._get_db()
        await db.execute(
            """
            INSERT OR REPLACE INTO discovered_skills
            (repo, path, name, description, stars, url, content,
             quality_score, discovered_at, solidified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                skill.repo,
                skill.path,
                skill.name,
                skill.description,
                skill.stars,
                skill.url,
                skill.content or "",
                skill.quality_score,
                skill.discovered_at.isoformat(),
                0,
            ),
        )
        await db.commit()

    # -------------------------------------------------------------------------
    # Effectiveness tracking
    # -------------------------------------------------------------------------

    async def record_usage(self, skill_name: str, success: bool) -> None:
        """Record a skill usage for effectiveness evaluation."""
        if not skill_name:
            return  # Silently ignore empty skill names
        await self._lazy_init()
        db = await self._get_db()

        if success:
            await db.execute(
                """
                INSERT INTO skill_effectiveness (skill_key, uses, successes, last_evaluated)
                VALUES (?, 1, 1, ?)
                ON CONFLICT(skill_key) DO UPDATE SET
                    uses = uses + 1,
                    successes = successes + 1,
                    last_evaluated = ?
                """,
                (skill_name, datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
            )
        else:
            await db.execute(
                """
                INSERT INTO skill_effectiveness (skill_key, uses, failures, last_evaluated)
                VALUES (?, 1, 1, ?)
                ON CONFLICT(skill_key) DO UPDATE SET
                    uses = uses + 1,
                    failures = failures + 1,
                    last_evaluated = ?
                """,
                (skill_name, datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
            )
        await db.commit()

    async def get_effectiveness(self, skill_name: str) -> dict[str, Any]:
        """Get effectiveness metrics for a skill."""
        await self._lazy_init()
        db = await self._get_db()
        async with db.execute(
            "SELECT * FROM skill_effectiveness WHERE skill_key = ?",
            (skill_name,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return {"found": False}

            uses = row["uses"]
            successes = row["successes"]
            failures = row["failures"]

            return {
                "found": True,
                "uses": uses,
                "successes": successes,
                "failures": failures,
                "success_rate": successes / uses if uses > 0 else 0.0,
                "decision": row["decision"],
            }

    async def make_solidify_decision(self, skill_name: str) -> str:
        """Decide whether to solidify a transient skill.

        Decision logic:
        - success_rate >= 0.8 and uses >= 3 → "solidify"
        - success_rate < 0.5 and uses >= 2 → "discard"
        - otherwise → "keep_transient"
        """
        eff = await self.get_effectiveness(skill_name)
        if not eff.get("found"):
            return "keep_transient"

        if eff["success_rate"] >= 0.8 and eff["uses"] >= 3:
            decision = "solidify"
        elif eff["success_rate"] < 0.5 and eff["uses"] >= 2:
            decision = "discard"
        else:
            decision = "keep_transient"

        db = await self._get_db()
        await db.execute(
            "UPDATE skill_effectiveness SET decision = ? WHERE skill_key = ?",
            (decision, skill_name),
        )
        await db.commit()

        # Execute decision
        if decision == "solidify":
            await self._solidify_skill(skill_name)
        elif decision == "discard":
            await self._discard_skill(skill_name)

        return decision

    async def run_solidify_cycle(self) -> dict[str, Any]:
        """Review all transient skills and make solidify/discard decisions.

        Call this periodically (e.g. once per hour of watcher runtime).
        Returns a summary dict of decisions made.
        """
        await self._lazy_init()
        db = await self._get_db()
        decisions: dict[str, list[str]] = {"solidify": [], "discard": [], "keep_transient": []}

        async with db.execute(
            """
            SELECT name FROM discovered_skills
            WHERE solidified = 0
            ORDER BY discovered_at DESC
            LIMIT 50
            """
        ) as cursor:
            async for row in cursor:
                skill_key = row["name"]
                decision = await self.make_solidify_decision(skill_key)
                if decision in decisions:
                    decisions[decision].append(skill_key)

        return decisions

    async def _solidify_skill(self, skill_name: str) -> None:
        """Move a transient skill to permanent skills directory."""
        transient_path = TRANSIENT_SKILLS_DIR / skill_name
        if not transient_path.exists():
            return

        permanent_path = SOLIDIFIED_SKILLS_DIR / skill_name
        permanent_path.mkdir(parents=True, exist_ok=True)

        for f in transient_path.iterdir():
            (permanent_path / f.name).write_bytes(f.read_bytes())

        # Mark in DB
        db = await self._get_db()
        await db.execute(
            "UPDATE discovered_skills SET solidified = 1 WHERE name = ?",
            (skill_name,),
        )
        await db.commit()

    async def _discard_skill(self, skill_name: str) -> None:
        """Remove a transient skill."""
        import shutil
        transient_path = TRANSIENT_SKILLS_DIR / skill_name
        if transient_path.exists():
            shutil.rmtree(transient_path)

    # -------------------------------------------------------------------------
    # Convenience: proactive discovery
    # -------------------------------------------------------------------------

    async def proactive_discovery(
        self,
        task_description: str,
        gap_type: str = "missing_skill",
    ) -> list[DiscoveredSkill]:
        """Given a task description, proactively search for relevant skills.

        Returns list of discovered skills (up to 3).
        """
        discovered: list[DiscoveredSkill] = []

        # Build search queries from task description
        queries = self._build_queries_from_task(task_description)

        for query in queries[:3]:  # Limit to 3 queries
            skill = await self.discover_and_learn(
                query=query,
                gap_type=gap_type,
                context=task_description,
            )
            if skill:
                discovered.append(skill)

        return discovered

    def _build_queries_from_task(self, task: str) -> list[str]:
        """Extract search queries from a task description."""
        # Simple keyword extraction + common patterns
        keywords = re.findall(r"[a-zA-Z]{4,}", task.lower())
        common = {
            "agent", "task", "skill", "code", "review", "test",
            "build", "deploy", "debug", "api", "web", "data",
            "search", "learn", "write", "edit", "run", "file"
        }
        significant = [k for k in keywords if k not in common]

        queries = []
        if significant[:3]:
            queries.append("+".join(significant[:3]) + "+skill+claude+agent")
        if keywords[:5]:
            queries.append("+".join(keywords[:5]) + "+claude+code+agent")
        queries.append("AI+agent+skill+automation+" + "+".join(keywords[:3]))

        return queries
