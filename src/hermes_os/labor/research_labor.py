"""ResearchLabor — Intelligence Pipeline reasoning and analysis labor.

Implements Intelligence Pipeline stage:
- M3_REASONING: Compute metrics and analyze patterns

Used by: Intelligence Pipeline
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ResearchLabor:
    """Labor unit for research and reasoning tasks."""

    def __init__(self, **kwargs) -> None:
        pass

    async def execute(self, workspace: Path, task_description: str, meta: dict[str, Any]) -> bool:
        """
        Execute reasoning/analysis task.

        Stage-specific behavior:
        - M2_RESEARCH: Retrieve context from GlobalWiki and PrivateWiki (content assembly)
        - M3_REASONING: Compute metrics and analyze patterns (intelligence)
        """
        stage = meta.get("stage", "M3_REASONING")

        if stage == "M2_RESEARCH":
            return await self._execute_m2_research(workspace, task_description, meta)
        elif stage == "M3_REASONING":
            return await self._execute_m3_reasoning(workspace, task_description, meta)
        else:
            logger.warning("ResearchLabor: unknown stage %s", stage)
            return False

    async def _execute_m2_research(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> bool:
        """M2_RESEARCH: Retrieve context from GlobalWiki and PrivateWiki."""
        wiki_dir = workspace / "wiki" if workspace else Path("wiki")
        wiki_dir.mkdir(parents=True, exist_ok=True)

        logger.info("ResearchLabor M2_RESEARCH: retrieving context")

        try:
            # Mock retrieval - in production, would query GlobalWiki/PrivateWiki
            research_data = {
                "source": "wiki",
                "context_ retrieved": True,
                "query": task_description,
                "references": [
                    {"title": "Reference 1", "url": "https://wiki.example.com/ref1"},
                    {"title": "Reference 2", "url": "https://wiki.example.com/ref2"},
                ],
            }

            # Save research context
            research_file = wiki_dir / "research_context.json"
            research_file.write_text(json.dumps(research_data, ensure_ascii=False, indent=2), encoding="utf-8")

            logger.info("M2_RESEARCH: retrieved %d references", len(research_data["references"]))
            return True

        except Exception as e:
            logger.exception("M2_RESEARCH failed")
            return False

    async def _execute_m3_reasoning(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> bool:
        """M3_REASONING: Compute metrics and analyze patterns."""
        data_dir = workspace / "src" / "data"
        norm_file = data_dir / "normalized.json"

        if not norm_file.exists():
            logger.error("No normalized data found at %s", norm_file)
            return False

        logger.info("ResearchLabor M3_REASONING: analyzing patterns")

        try:
            normalized = json.loads(norm_file.read_text(encoding="utf-8"))
            metrics = self._compute_metrics(normalized)

            # Save analysis results
            analysis_file = data_dir / "analysis.json"
            analysis_file.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

            logger.info("M3_REASONING: computed %d metrics", len(metrics.get("metrics", [])))
            return True

        except Exception as e:
            logger.exception("M3_REASONING failed")
            return False

    def _compute_metrics(self, data: dict[str, Any]) -> dict[str, Any]:
        """Compute metrics from normalized data."""
        metrics = []

        # Extract repos if present
        repos = data.get("repos", [])
        if isinstance(repos, list) and len(repos) > 0:
            stars = [r.get("stars", 0) for r in repos if isinstance(r, dict)]
            forks = [r.get("forks", 0) for r in repos if isinstance(r, dict)]

            metrics.append({
                "name": "repository_stats",
                "values": {
                    "total_repos": len(repos),
                    "total_stars": sum(stars),
                    "total_forks": sum(forks),
                    "avg_stars": sum(stars) / len(stars) if stars else 0,
                    "avg_forks": sum(forks) / len(forks) if forks else 0,
                }
            })

        # Extract docs if present
        docs = data.get("docs", [])
        if isinstance(docs, list) and len(docs) > 0:
            metrics.append({
                "name": "document_count",
                "values": {
                    "total_docs": len(docs),
                }
            })

        return {"metrics": metrics}


# ---------------------------------------------------------------------------
# Verification functions (used by PipelineEngine)
# ---------------------------------------------------------------------------

from hermes_os.universal_pipeline import VerificationResult


async def verify_analysis_complete(analysis_json: str) -> VerificationResult:
    """Verify analysis produced results."""
    errors = []
    try:
        data = json.loads(analysis_json)
        if not data or "metrics" not in data:
            errors.append("Analysis produced no results")
        elif not data["metrics"]:
            errors.append("No metrics computed")
    except json.JSONDecodeError:
        errors.append("Invalid JSON analysis result")
    return VerificationResult(passed=len(errors) == 0, errors=errors)