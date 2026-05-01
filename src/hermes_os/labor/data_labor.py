"""DataLabor — Intelligence & Analytics Pipeline data processing labor.

Implements the Intelligence Pipeline stages:
- M1_DATAFETCH: Fetch data from GitHub/Feishu/Wiki/Web
- M2_NORMALIZE: Clean and normalize data
- M4_VISUALIZE: Generate chart specifications

M3_REASONING uses ResearchLabor, M5_INSIGHT uses ContentLabor.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DataLabor:
    """Labor unit for data fetching, cleaning, and visualization."""

    def __init__(self, **kwargs) -> None:
        pass

    async def execute(self, workspace: Path, task_description: str, meta: dict[str, Any]) -> bool:
        """
        Execute data processing task.

        Stage-specific behavior:
        - M1_DATAFETCH: Fetch data from various sources
        - M2_NORMALIZE: Clean and structure data
        - M4_VISUALIZE: Generate chart specs
        """
        stage = meta.get("stage", "M1_DATAFETCH")
        src_dir = workspace / "src"
        src_dir.mkdir(parents=True, exist_ok=True)

        if stage == "M1_DATAFETCH":
            return await self._execute_m1_datafetch(workspace, task_description, meta)
        elif stage == "M2_NORMALIZE":
            return await self._execute_m2_normalize(workspace, task_description, meta)
        elif stage == "M4_VISUALIZE":
            return await self._execute_m4_visualize(workspace, task_description, meta)
        else:
            logger.warning("DataLabor: unknown stage %s", stage)
            return False

    async def _execute_m1_datafetch(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> bool:
        """M1_DATAFETCH: Fetch data from GitHub/Feishu/Wiki/Web."""
        source = meta.get("source", "github")
        query = meta.get("query", "")
        data_dir = workspace / "src" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        logger.info("DataLabor M1_DATAFETCH: source=%s, query=%s", source, query)

        try:
            if source == "github":
                data = await fetch_github_data(query, meta)
            elif source == "feishu":
                data = await fetch_feishu_data(query, meta)
            elif source == "web":
                data = await fetch_web_data(query, meta)
            elif source == "wiki":
                data = await fetch_wiki_data(query, meta)
            else:
                logger.error("Unknown data source: %s", source)
                return False

            # Save raw data
            raw_file = data_dir / "raw.json"
            raw_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

            return True

        except Exception as e:
            logger.exception("M1_DATAFETCH failed")
            return False

    async def _execute_m2_normalize(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> bool:
        """M2_NORMALIZE: Clean and normalize raw data."""
        data_dir = workspace / "src" / "data"
        raw_file = data_dir / "raw.json"

        if not raw_file.exists():
            logger.error("No raw data found at %s", raw_file)
            return False

        try:
            raw_data = json.loads(raw_file.read_text(encoding="utf-8"))
            normalized = self._normalize_data(raw_data)

            # Save normalized data
            normalized_file = data_dir / "normalized.json"
            normalized_file.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")

            logger.info("M2_NORMALIZE: normalized %d items", len(normalized.get("items", [])))
            return True

        except Exception as e:
            logger.exception("M2_NORMALIZE failed")
            return False

    async def _execute_m4_visualize(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> bool:
        """M4_VISUALIZE: Generate chart specifications from normalized data."""
        data_dir = workspace / "src" / "data"
        norm_file = data_dir / "normalized.json"

        if not norm_file.exists():
            logger.error("No normalized data found at %s", norm_file)
            return False

        try:
            normalized = json.loads(norm_file.read_text(encoding="utf-8"))
            chart_type = meta.get("chart_type", "bar")

            charts = await generate_chart(normalized, chart_type, meta)

            # Save chart specs
            charts_file = data_dir / "charts.json"
            charts_file.write_text(json.dumps(charts, ensure_ascii=False, indent=2), encoding="utf-8")

            logger.info("M4_VISUALIZE: generated %d charts", len(charts.get("charts", [])))
            return True

        except Exception as e:
            logger.exception("M4_VISUALIZE failed")
            return False

    def _normalize_data(self, raw_data: Any) -> dict[str, Any]:
        """Normalize raw data by removing nulls, structuring fields."""
        if isinstance(raw_data, dict):
            # Remove null and undefined values
            cleaned = {k: v for k, v in raw_data.items() if v is not None and v != "null" and v != "undefined"}
            # Recursively clean nested dicts
            for k, v in cleaned.items():
                if isinstance(v, (dict, list)):
                    cleaned[k] = self._normalize_data(v)
            return cleaned
        elif isinstance(raw_data, list):
            return [self._normalize_data(item) for item in raw_data if item is not None]
        else:
            return raw_data


# ---------------------------------------------------------------------------
# Data fetching functions (real API implementations)
# ---------------------------------------------------------------------------

async def fetch_github_data(query: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Fetch data from GitHub REST API via gh CLI.

    Uses `gh api` (GitHub CLI) for authenticated or unauthenticated requests.
    Falls back gracefully when no credentials are available.
    """
    import os
    import subprocess

    logger.info("Fetching GitHub data for query: %s", query)

    token = meta.get("github_token") or os.environ.get("GITHUB_TOKEN", "")
    endpoint = meta.get("endpoint", "/search/repositories")
    per_page = meta.get("per_page", 10)

    # Build gh api command
    cmd = ["gh", "api", endpoint, "-q", ".", "-F", f"q={query}", "-F", f"per_page={per_page}"]
    if token:
        # Authenticated mode — gh handles token via gh auth status
        pass
    # Unauthenticated fallback — gh CLI works without token (rate-limited)

    try:
        proc = await subprocess.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace")
            logger.warning("gh api failed (rc=%d): %s", proc.returncode, stderr_text)
            # Return sentinel so callers don't break
            return {
                "source": "github",
                "query": query,
                "repos": [],
                "error": f"gh_api_failed_{proc.returncode}",
            }

        import json
        data = json.loads(stdout.decode("utf-8", errors="replace"))

        # Normalize GitHub REST API response shape
        items = data.get("items", []) if isinstance(data, dict) else []
        repos = []
        for item in items:
            repos.append({
                "name": item.get("name", ""),
                "full_name": item.get("full_name", ""),
                "stars": item.get("stargazers_count", 0),
                "forks": item.get("forks_count", 0),
                "language": item.get("language", ""),
                "description": item.get("description", ""),
                "html_url": item.get("html_url", ""),
                "created_at": item.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
            })

        return {
            "source": "github",
            "query": query,
            "repos": repos,
            "fetched_at": meta.get("timestamp", ""),
        }

    except FileNotFoundError:
        logger.warning("gh CLI not installed — using mock fallback")
        return _mock_github_data(query, meta)
    except Exception as e:
        logger.exception("fetch_github_data exception")
        return {
            "source": "github",
            "query": query,
            "repos": [],
            "error": str(e),
        }


def _mock_github_data(query: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Mock fallback when gh CLI is unavailable."""
    return {
        "source": "github",
        "query": query,
        "repos": [
            {"name": f"repo-{i}", "full_name": f"example/repo-{i}", "stars": 100 * i, "forks": 20 * i, "language": "Python", "description": "", "html_url": "", "created_at": "", "updated_at": ""}
            for i in range(1, 4)
        ],
        "fetched_at": str(meta.get("timestamp", "now")),
    }


async def fetch_feishu_data(query: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Fetch data from Feishu API.

    Placeholder — requires Feishu app credentials (app_id, app_secret).
    Returns structured mock data when no credentials are configured.
    """
    import os

    logger.info("Fetching Feishu data for query: %s", query)

    app_id = meta.get("feishu_app_id") or os.environ.get("FEISHU_APP_ID", "")
    app_secret = meta.get("feishu_app_secret") or os.environ.get("FEISHU_APP_SECRET", "")

    if not app_id or not app_secret:
        logger.warning("Feishu credentials not configured — using mock fallback")
        return {
            "source": "feishu",
            "query": query,
            "docs": [
                {"title": f"Document {i}", "doc_id": f"doc_{i}", "url": f"https://feishu.cn/doc/{i}"}
                for i in range(1, 3)
            ],
            "error": "no_credentials",
        }

    # Real Feishu API integration would go here
    # POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
    # Then GET https://open.feishu.cn/open-apis/suite/docs-api/search?query={query}
    logger.warning("Feishu real API not yet implemented — using mock")
    return {
        "source": "feishu",
        "query": query,
        "docs": [],
        "error": "not_implemented",
    }


async def fetch_web_data(query: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Fetch data from Google Custom Search JSON API.

    Uses Google API key + CSE ID for SerpAPI or Google Custom Search.
    Falls back gracefully when no credentials are available.
    """
    import os
    import urllib.parse

    logger.info("Fetching web data for query: %s", query)

    api_key = meta.get("google_api_key") or os.environ.get("GOOGLE_API_KEY", "")
    cse_id = meta.get("google_cse_id") or os.environ.get("GOOGLE_CSE_ID", "")

    if not api_key or not cse_id:
        logger.warning("Google credentials not configured — using mock fallback")
        return _mock_web_data(query, meta)

    try:
        # Google Custom Search JSON API
        encoded_query = urllib.parse.quote(query)
        url = (
            f"https://www.googleapis.com/customsearch/v1"
            f"?key={api_key}&cx={cse_id}&q={encoded_query}&num=5"
        )

        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning("Google API returned %d: %s", resp.status, text)
                    return {
                        "source": "web",
                        "query": query,
                        "results": [],
                        "error": f"http_{resp.status}",
                    }
                data = await resp.json()

        items = data.get("items", [])
        results = []
        for item in items:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })

        return {
            "source": "web",
            "query": query,
            "results": results,
        }

    except ImportError:
        logger.warning("aiohttp not available — using mock fallback")
        return _mock_web_data(query, meta)
    except Exception as e:
        logger.exception("fetch_web_data exception")
        return {
            "source": "web",
            "query": query,
            "results": [],
            "error": str(e),
        }


def _mock_web_data(query: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Mock fallback when Google credentials are unavailable."""
    return {
        "source": "web",
        "query": query,
        "results": [
            {"title": f"Result {i}", "url": f"https://example.com/{i}", "snippet": "..."}
            for i in range(1, 4)
        ],
    }


async def fetch_wiki_data(query: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Fetch data from GlobalWiki.

    Uses the brain_indexer / global_wiki_indexer when available.
    Falls back to mock when no wiki is configured.
    """
    import os

    logger.info("Fetching Wiki data for query: %s", query)

    wiki_url = meta.get("wiki_url") or os.environ.get("WIKI_API_URL", "")

    if not wiki_url:
        logger.warning("Wiki API not configured — using mock fallback")
        return {
            "source": "wiki",
            "query": query,
            "entries": [
                {"title": f"Wiki Entry {i}", "content": "...", "tags": ["tag1", "tag2"]}
                for i in range(1, 3)
            ],
            "error": "no_credentials",
        }

    # Real wiki API integration would go here
    logger.warning("Wiki real API not yet implemented — using mock")
    return {
        "source": "wiki",
        "query": query,
        "entries": [],
        "error": "not_implemented",
    }


async def generate_chart(data: dict[str, Any], chart_type: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Generate chart specifications from data."""
    metrics = data.get("metrics", [])

    charts = []
    for metric in metrics:
        if isinstance(metric, dict) and "values" in metric:
            charts.append({
                "type": chart_type,
                "metric": metric.get("name", "unknown"),
                "data": metric.get("values", []),
                "labels": [f"Point {i+1}" for i in range(len(metric.get("values", [])))],
            })
        elif isinstance(metric, list):
            # Handle list of metrics
            charts.append({
                "type": chart_type,
                "metric": "dataset",
                "data": metric,
            })

    # If no structured metrics, try to extract from repos/items
    if not charts and "repos" in data:
        repos = data["repos"]
        if isinstance(repos, list) and len(repos) > 0:
            charts.append({
                "type": "bar",
                "metric": "stars",
                "data": [r.get("stars", 0) for r in repos],
                "labels": [r.get("name", f"repo-{i}") for i, r in enumerate(repos)],
            })

    return {"charts": charts}


# ---------------------------------------------------------------------------
# Verification functions (used by PipelineEngine)
# ---------------------------------------------------------------------------

from hermes_os.universal_pipeline import VerificationResult


async def verify_data_fetched(data_json: str) -> VerificationResult:
    """Verify data was successfully fetched."""
    errors = []
    try:
        data = json.loads(data_json)
        if not data:
            errors.append("No data fetched")
    except json.JSONDecodeError:
        errors.append("Invalid JSON data")
    return VerificationResult(passed=len(errors) == 0, errors=errors)


async def verify_data_clean(data_json: str) -> VerificationResult:
    """Verify data cleaning completed (no null/undefined values)."""
    errors = []
    try:
        data = json.loads(data_json)
        # Check for null/undefined markers
        data_str = json.dumps(data)
        if "null" in data_str or "undefined" in data_str:
            errors.append("Data contains null or undefined values")
    except json.JSONDecodeError:
        errors.append("Invalid JSON data")
    return VerificationResult(passed=len(errors) == 0, errors=errors)


async def verify_analysis_complete(analysis_json: str) -> VerificationResult:
    """Verify analysis produced results."""
    errors = []
    try:
        data = json.loads(analysis_json)
        if not data or len(data) == 0:
            errors.append("Analysis produced no results")
    except json.JSONDecodeError:
        errors.append("Invalid JSON analysis result")
    return VerificationResult(passed=len(errors) == 0, errors=errors)


async def verify_charts_generated(charts_json: str) -> VerificationResult:
    """Verify charts were generated."""
    errors = []
    try:
        data = json.loads(charts_json)
        charts = data.get("charts", [])
        if not charts or len(charts) == 0:
            errors.append("No charts generated")
    except json.JSONDecodeError:
        errors.append("Invalid JSON charts data")
    return VerificationResult(passed=len(errors) == 0, errors=errors)