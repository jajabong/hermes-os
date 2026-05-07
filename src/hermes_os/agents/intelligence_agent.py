"""IntelligenceAgent — shared real-time intelligence for Iron Legion.

Used by all Iron Legion agents that need live data (stock prices, legal
regulations, tech docs, security vulnerabilities, etc.).

Cached: duplicate queries within 5 minutes return the same results.
"""

from __future__ import annotations

import time
from typing import Any

from hermes_os.vertical_agent import AgentRequest, AgentResult

# Lazy import — Tavily only needed if IntelligenceAgent is actually used
_tavily_client: Any = None

# ---------------------------------------------------------------------------
# Simple in-memory cache (user_id → query → (timestamp, results))
# ---------------------------------------------------------------------------
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def _get_tavily() -> Any:
    global _tavily_client
    if _tavily_client is None:
        try:
            from tavily import TavilyClient

            _tavily_client = TavilyClient("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")
        except Exception:
            pass
    return _tavily_client


def _cache_key(user_id: str, query: str) -> str:
    return f"{user_id}:{query[:80]}"


def _cached_search(user_id: str, query: str, max_results: int = 5) -> dict[str, Any]:
    """Search with 5-minute in-memory cache per user."""
    key = _cache_key(user_id, query)
    now = time.time()

    # Hit cache if fresh
    if key in _cache:
        ts, results = _cache[key]
        if now - ts < _CACHE_TTL_SECONDS:
            return results

    # Miss — search Tavily
    tavily = _get_tavily()
    if not tavily:
        return {"found": False, "error": "Tavily not available", "query": query}

    try:
        resp = tavily.search(query, search_depth="advanced", max_results=max_results)
        results = {
            "found": True,
            "query": query,
            "count": len(resp.get("results", [])),
            "results": [
                {
                    "title": r.get("title", "")[:80],
                    "url": r.get("url", ""),
                    "snippet": r.get("content", "")[:300],
                }
                for r in resp.get("results", [])
            ],
        }
        _cache[key] = (now, results)
        return results
    except Exception as e:
        return {"found": False, "error": str(e), "query": query}


INTELLIGENCE_SYSTEM_PROMPT = """你是 Hermes OS 的情报专家。

职责：
- 为其他 Iron Legion agents 提供实时数据搜索
- 搜索股票行情、法规文件、技术文档、安全漏洞等最新信息
- 返回结构化的搜索结果（title + url + snippet）

当其他 agent 请求情报时，使用 WebSearch 工具搜索并返回结果。

注意：
- 使用 Tavily 搜索（已配置）
- 缓存搜索结果5分钟
- 返回格式：{found, count, results: [{title, url, snippet}]}"""


class IntelligenceAgent:
    """Shared intelligence agent — used by all Iron Legion agents for live data."""

    name = "IntelligenceAgent"

    async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
        """Handle intelligence requests.

        Params (in request.params):
            query: str — search query
            max_results: int — max results (default 5)
            user_id: str — for cache key

        Returns:
            AgentResult with structured search data in output field (JSON)
        """
        query = request.params.get("query", "")
        max_results = request.params.get("max_results", 5)
        user_id = request.params.get("user_id", "anonymous")

        if not query:
            return AgentResult(success=False, error="No query provided")

        try:
            data = _cached_search(user_id, query, max_results)
            import json

            output = json.dumps(data, ensure_ascii=False, indent=2)
            return AgentResult(
                success=data.get("found", False),
                output=output,
                token_usage=len(output) // 4,
                metadata={"query": query, "count": data.get("count", 0)},
            )
        except Exception as e:
            return AgentResult(success=False, error=str(e))
