"""ResearchWorkflowEngine — parallel multi-source intelligence gathering.

Scenario 2: Leader says "compare supplier solutions, give me an investment judgment"

This engine:
1. Calls multiple sources in parallel (feishu docs + github + web search + brain wiki)
2. Aggregates findings
3. Extracts risk flags
4. Generates structured recommendations (A/B/C options)
5. Outputs as Feishu card
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from hermes_os.brain_indexer import BrainIndexer
from hermes_os.hermes_tool_registry import get_tool_registry


class IntelligenceSource(str, Enum):
    """Sources for intelligence gathering."""

    FEISHU_DOCS = "feishu_docs"  # 飞书文档
    GITHUB = "github"  # GitHub (PRs, issues, repos)
    WEB_SEARCH = "web_search"  # 网上情报搜索
    BRAIN_WIKI = "brain_wiki"  # 用户脑目录 wiki


class RiskFlag(str, Enum):
    """Risk severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class IntelligenceResult:
    """Result of parallel intelligence gathering."""

    query: str
    source_count: int
    findings: list[str]
    risks: list[tuple[str, RiskFlag]]  # (description, flag)
    recommendations: list[str]
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# Risk keywords → RiskFlag
_RISK_KEYWORDS: list[tuple[str, RiskFlag]] = [
    (r"风险|危险|隐患", RiskFlag.MEDIUM),
    (r"重大|严重|高风险", RiskFlag.HIGH),
    (r"致命|破产|崩溃", RiskFlag.CRITICAL),
    (r"存疑|不确定|待定", RiskFlag.LOW),
    (r"超支|延期|逾期", RiskFlag.MEDIUM),
]


class ResearchWorkflowEngine:
    """
    Executes parallel multi-source intelligence gathering.

    Usage:
        engine = ResearchWorkflowEngine()
        result = await engine.execute_workflow(
            query="供应商方案对比",
            user_id="alice",
        )
        card = engine.to_feishu_card(result)
    """

    def __init__(self) -> None:
        self._sources: list[IntelligenceSource] = [
            IntelligenceSource.FEISHU_DOCS,
            IntelligenceSource.GITHUB,
            IntelligenceSource.WEB_SEARCH,
            IntelligenceSource.BRAIN_WIKI,
        ]
        self._brain = BrainIndexer()
        self._tool_registry = get_tool_registry()

    async def execute_parallel(
        self,
        query: str,
        sources: list[IntelligenceSource] | None = None,
        user_id: str = "default",
    ) -> IntelligenceResult:
        """
        Execute intelligence gathering across multiple sources in parallel.

        Args:
            query: The research question
            sources: Which sources to search (default: all)
            user_id: For brain wiki lookup

        Returns:
            IntelligenceResult with all findings
        """
        if not query.strip():
            return IntelligenceResult(
                query="",
                source_count=0,
                findings=[],
                risks=[],
                recommendations=[],
                success=False,
                error="Empty query",
            )

        target_sources = sources or self._sources

        # Launch all source calls concurrently
        tasks = [self._call_source(source, query, user_id=user_id) for source in target_sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_findings: list[str] = []
        errors: list[str] = []

        for source, result in zip(target_sources, results):
            if isinstance(result, Exception):
                errors.append(f"{source.value}: {result}")
            else:
                findings = result.get("findings", [])
                all_findings.extend(findings)

        if not all_findings and errors:
            return IntelligenceResult(
                query=query,
                source_count=len(target_sources),
                findings=[],
                risks=[],
                recommendations=[],
                success=False,
                error="; ".join(errors),
            )

        return IntelligenceResult(
            query=query,
            source_count=len(target_sources),
            findings=all_findings,
            risks=[],
            recommendations=[],
            success=True,
        )

    async def execute_workflow(
        self,
        query: str,
        user_id: str = "default",
        sources: list[IntelligenceSource] | None = None,
    ) -> IntelligenceResult:
        """
        Full research workflow: parallel gather → analyze → risk extraction.

        Args:
            query: Research question
            user_id: For brain wiki context
            sources: Sources to search (default: all)

        Returns:
            IntelligenceResult with findings, risks, recommendations
        """
        result = await self.execute_parallel(query, sources, user_id)
        if not result.success:
            return result

        return self.analyze(result)

    def analyze(self, result: IntelligenceResult) -> IntelligenceResult:
        """
        Analyze gathered intelligence:
        - Extract risk flags from keywords
        - Generate recommendation options (A/B/C)

        Modifies result in-place but also returns it.
        """
        risks: list[tuple[str, RiskFlag]] = []
        for finding in result.findings:
            for pattern, flag in _RISK_KEYWORDS:
                if re.search(pattern, finding):
                    risks.append((finding, flag))
                    break

        # Generate recommendation options based on findings
        recommendations = self._generate_recommendations(result.findings)

        result.risks = risks
        result.recommendations = recommendations
        return result

    def to_feishu_card(
        self, result: IntelligenceResult, title: str = "情报研究结果"
    ) -> dict[str, Any]:
        """Format intelligence result as a Feishu card."""
        if not result.success:
            content = f"❌ 情报收集失败: {result.error}"
        else:
            findings_lines = "\n".join(f"• {f}" for f in result.findings[:10])
            risks_lines = (
                "\n".join(f"⚠️ {r[0]} [{r[1].value}]" for r in result.risks)
                if result.risks
                else "✅ 无明显风险"
            )
            rec_lines = (
                "\n".join(f"📋 {rec}" for rec in result.recommendations)
                if result.recommendations
                else ""
            )

            content_parts = [
                f"**来源数**: {result.source_count}",
                f"**发现** ({len(result.findings)}条):",
                findings_lines,
            ]
            if risks_lines:
                content_parts.extend(["", f"**风险** ({len(result.risks)}条):", risks_lines])
            if rec_lines:
                content_parts.extend(["", "**建议选项**:", rec_lines])

            content = "\n".join(content_parts)

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "red" if result.risks else "blue",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content[:500]}},
            ],
        }

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    async def _call_source(
        self,
        source: IntelligenceSource,
        query: str,
        user_id: str = "default",
    ) -> dict[str, Any]:
        """Call a single intelligence source."""
        if source == IntelligenceSource.FEISHU_DOCS:
            return await self._call_feishu_docs(query)
        elif source == IntelligenceSource.GITHUB:
            return await self._call_github(query)
        elif source == IntelligenceSource.WEB_SEARCH:
            return await self._call_web_search(query)
        elif source == IntelligenceSource.BRAIN_WIKI:
            return await self._call_brain_wiki(query, user_id)
        return {"findings": []}

    async def _call_feishu_docs(self, query: str) -> dict[str, Any]:
        """Search feishu documents."""
        handler = self._tool_registry.get("feishu_doc_search")
        if not handler:
            return {"findings": []}
        try:
            result = handler({"query": query})
            return {"findings": [result] if result else []}
        except Exception:
            return {"findings": []}

    async def _call_github(self, query: str) -> dict[str, Any]:
        """Search GitHub — delegates to web search for now."""
        # GitHub-specific API search would go here
        # For now, use web search with "site:github.com"
        handler = self._tool_registry.get("web_search")
        if not handler:
            return {"findings": []}
        try:
            result = handler({"query": f"{query} site:github.com", "top_n": 5})
            return {"findings": [result] if result else []}
        except Exception:
            return {"findings": []}

    async def _call_web_search(self, query: str) -> dict[str, Any]:
        """General web search."""
        handler = self._tool_registry.get("web_search")
        if not handler:
            return {"findings": []}
        try:
            result = handler({"query": query, "top_n": 10})
            return {"findings": [result] if result else []}
        except Exception:
            return {"findings": []}

    async def _call_brain_wiki(self, query: str, user_id: str) -> dict[str, Any]:
        """Search user's brain wiki."""
        try:
            results = await self._brain.search_wiki(user_id, keyword=query)
            return {
                "findings": [f"{r['category']}/{r['file']}: {r['snippet']}" for r in results[:5]]
            }
        except Exception:
            return {"findings": []}

    def _generate_recommendations(self, findings: list[str]) -> list[str]:
        """Generate recommendation options (A/B/C) from findings."""
        if not findings:
            return []

        recommendations: list[str] = []

        # Try to identify option patterns in findings
        options: dict[str, list[str]] = {}
        for f in findings:
            # Look for option labels like "A供应商", "B方案"
            m = re.search(r"([ABC][方案供应商])[:：]?\s*(.+)", f)
            if m:
                key = m.group(1)
                val = m.group(2)
                options.setdefault(key, []).append(val)

        if options:
            for opt, details in options.items():
                recommendations.append(f"**{opt}**: {'；'.join(details[:2])}")
        else:
            # Generic recommendation from top findings
            recommendations.append(f"基于 {len(findings)} 条信息综合分析，建议进一步评估")

        return recommendations
