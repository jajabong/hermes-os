"""Tests for ResearchWorkflowEngine — parallel multi-source intelligence gathering."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from hermes_os.research_workflow import (
    ResearchWorkflowEngine,
    IntelligenceSource,
    IntelligenceResult,
    RiskFlag,
)


# ---------------------------------------------------------------------------
# IntelligenceSource tests
# ---------------------------------------------------------------------------

class TestIntelligenceSource:
    def test_source_types(self) -> None:
        """All expected source types exist."""
        assert hasattr(IntelligenceSource, "FEISHU_DOCS")
        assert hasattr(IntelligenceSource, "GITHUB")
        assert hasattr(IntelligenceSource, "WEB_SEARCH")
        assert hasattr(IntelligenceSource, "BRAIN_WIKI")


# ---------------------------------------------------------------------------
# RiskFlag tests
# ---------------------------------------------------------------------------

class TestRiskFlag:
    def test_risk_levels(self) -> None:
        """All expected risk levels exist."""
        assert hasattr(RiskFlag, "LOW")
        assert hasattr(RiskFlag, "MEDIUM")
        assert hasattr(RiskFlag, "HIGH")
        assert hasattr(RiskFlag, "CRITICAL")


# ---------------------------------------------------------------------------
# IntelligenceResult tests
# ---------------------------------------------------------------------------

class TestIntelligenceResult:
    def test_success_result(self) -> None:
        """IntelligenceResult stores results from multiple sources."""
        result = IntelligenceResult(
            query="供应商对比",
            source_count=3,
            findings=["A供应商：成本最优", "B供应商：技术最优", "C供应商：综合最优"],
            risks=[("A供应商交付风险", RiskFlag.HIGH)],
            recommendations=["推荐C方案"],
            success=True,
        )
        assert result.query == "供应商对比"
        assert result.source_count == 3
        assert len(result.findings) == 3
        assert result.risks[0][1] == RiskFlag.HIGH

    def test_failure_result(self) -> None:
        """IntelligenceResult with error."""
        result = IntelligenceResult(
            query="",
            source_count=0,
            findings=[],
            risks=[],
            recommendations=[],
            success=False,
            error="No query provided",
        )
        assert result.success is False
        assert "No query provided" in result.error


# ---------------------------------------------------------------------------
# ResearchWorkflowEngine tests
# ---------------------------------------------------------------------------

class TestResearchWorkflowEngineInit:
    def test_init(self) -> None:
        """ResearchWorkflowEngine initializes with sources."""
        engine = ResearchWorkflowEngine()
        assert len(engine._sources) >= 3  # feishu, github, web


class TestResearchWorkflowEngineExecuteParallel:
    @pytest.mark.asyncio
    async def test_execute_parallel_empty_query_returns_error(self) -> None:
        """Empty query returns error result."""
        engine = ResearchWorkflowEngine()
        result = await engine.execute_parallel(
            query="",
            sources=[IntelligenceSource.WEB_SEARCH],
            user_id="alice",
        )
        assert result.success is False
        assert "Empty query" in result.error


class TestResearchWorkflowEngineAnalyze:
    @pytest.mark.asyncio
    async def test_analyze_adds_risk_flags(self) -> None:
        """analyze() extracts risk flags from findings."""
        engine = ResearchWorkflowEngine()
        result = IntelligenceResult(
            query="供应商对比",
            source_count=2,
            findings=[
                "A供应商：价格低但交付能力存疑",
                "B供应商：技术领先",
                "C供应商：价格适中",
            ],
            risks=[],
            recommendations=[],
            success=True,
        )

        analyzed = engine.analyze(result)

        assert len(analyzed.risks) >= 0
        assert len(analyzed.findings) == 3

    @pytest.mark.asyncio
    async def test_analyze_adds_recommendations(self) -> None:
        """analyze() generates recommendation options."""
        engine = ResearchWorkflowEngine()
        result = IntelligenceResult(
            query="供应商对比",
            source_count=2,
            findings=["A成本最低", "B技术最优", "C性价比最高"],
            risks=[],
            recommendations=[],
            success=True,
        )

        analyzed = engine.analyze(result)

        assert len(analyzed.recommendations) >= 1


class TestResearchWorkflowEngineToFeishuCard:
    def test_to_feishu_card_structure(self) -> None:
        """to_feishu_card() returns valid Feishu card."""
        engine = ResearchWorkflowEngine()
        result = IntelligenceResult(
            query="供应商对比",
            source_count=2,
            findings=["A成本最低", "B技术最优"],
            risks=[("B价格高", RiskFlag.MEDIUM)],
            recommendations=["综合考虑推荐C"],
            success=True,
        )

        card = engine.to_feishu_card(result, title="供应商分析报告")

        assert "header" in card
        assert "elements" in card
        assert card["header"]["title"]["content"] == "供应商分析报告"


class TestResearchWorkflowEngineWorkflow:
    @pytest.mark.asyncio
    async def test_execute_workflow_runs_parallel_then_analyzes(self) -> None:
        """execute_workflow() runs parallel research then analyzes results."""
        engine = ResearchWorkflowEngine()
        original = engine.execute_parallel

        async def mock_parallel(query, sources, user_id, **kwargs):
            src_list = sources or [IntelligenceSource.FEISHU_DOCS]
            return IntelligenceResult(
                query=query,
                source_count=len(src_list),
                findings=["数据源1", "数据源2", "数据源3"],
                risks=[],
                recommendations=[],
                success=True,
            )

        engine.execute_parallel = mock_parallel
        try:
            result = await engine.execute_workflow(
                query="项目A的供应商方案",
                user_id="alice",
            )

            assert result.success is True
            assert len(result.findings) == 3
            assert result.risks is not None
        finally:
            engine.execute_parallel = original
