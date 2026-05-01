"""Tests for ConclusionExtractor — JARVIS 三段式总结卡片.

三段式卡片结构:
- 结论 (Conclusion): 一句话概括结果
- 证据 (Evidence): 关键指标/数据
- 详情 (Details): 折叠的原始日志

优化目标:
- 消除"日志焦虑"：用户只看结论，不用翻日志
- 信息分层：按需展开详情
- 情绪安全：明确的成功/失败状态
"""

import pytest
from dataclasses import dataclass

from hermes_os.conclusion_extractor import (
    ConclusionExtractor,
    ConclusionCard,
    ConclusionLevel,
)


# ---------------------------------------------------------------------------
# ConclusionCard dataclass tests
# ---------------------------------------------------------------------------

class TestConclusionCard:
    def test_conclusion_card_fields(self) -> None:
        card = ConclusionCard(
            level=ConclusionLevel.SUCCESS,
            conclusion="部署完成，服务已重启",
            evidence=["测试耗时 2s", "成功率 100%"],
            details="原始日志...",
            task_title="测试任务",
            task_id="abc123",
        )
        assert card.level == ConclusionLevel.SUCCESS
        assert "部署完成" in card.conclusion
        assert len(card.evidence) == 2
        assert card.task_id == "abc123"

    def test_conclusion_card_markdown(self) -> None:
        card = ConclusionCard(
            level=ConclusionLevel.SUCCESS,
            conclusion="任务完成",
            evidence=["指标A: 100"],
            details="原始日志",
            task_title="Test",
            task_id="t1",
        )
        md = card.to_markdown()
        assert "✅" in md
        assert "任务完成" in md
        assert "指标A: 100" in md
        assert "原始日志" in md

    def test_conclusion_card_feishu_elements(self) -> None:
        card = ConclusionCard(
            level=ConclusionLevel.SUCCESS,
            conclusion="编译成功",
            evidence=["编译时间: 45s"],
            details="make output...",
            task_title="Build",
            task_id="b1",
        )
        elements = card.to_feishu_elements()
        # Should have: conclusion div + evidence div + collapsible details
        assert len(elements) >= 2
        # First element is conclusion
        assert elements[0]["tag"] == "div"
        # Last element is collapsible details
        assert elements[-1]["tag"] == "note"


class TestConclusionLevel:
    def test_level_values(self) -> None:
        assert hasattr(ConclusionLevel, "SUCCESS")
        assert hasattr(ConclusionLevel, "FAILURE")
        assert hasattr(ConclusionLevel, "WARNING")
        assert hasattr(ConclusionLevel, "RUNNING")
        assert hasattr(ConclusionLevel, "INFO")

    def test_level_to_icon(self) -> None:
        assert ConclusionLevel.SUCCESS.icon == "✅"
        assert ConclusionLevel.FAILURE.icon == "❌"
        assert ConclusionLevel.WARNING.icon == "⚠️"
        assert ConclusionLevel.RUNNING.icon == "🔄"
        assert ConclusionLevel.INFO.icon == "ℹ️"


# ---------------------------------------------------------------------------
# ConclusionExtractor.extract_summary tests
# ---------------------------------------------------------------------------

class TestExtractSummaryBasic:
    @pytest.fixture
    def extractor(self) -> ConclusionExtractor:
        return ConclusionExtractor()

    def test_extract_from_short_output(self, extractor: ConclusionExtractor) -> None:
        result = extractor.extract_summary(
            raw_output="Hello world",
            task_title="Simple task",
            task_id="t1",
        )
        assert result.level == ConclusionLevel.SUCCESS
        assert result.task_id == "t1"
        assert len(result.conclusion) > 0

    def test_extract_detects_failure(self, extractor: ConclusionExtractor) -> None:
        result = extractor.extract_summary(
            raw_output="Error: connection refused\nTraceback: ...",
            task_title="Connect task",
            task_id="t2",
        )
        assert result.level == ConclusionLevel.FAILURE
        assert "失败" in result.conclusion or "Error" in result.conclusion

    def test_extract_from_deployment_output(self, extractor: ConclusionExtractor) -> None:
        output = """
[INFO] Building image...
[INFO] Pushing to registry...
[INFO] Deploying to cluster...
[INFO] Health check passed
Deployment completed in 45s
"""
        result = extractor.extract_summary(
            raw_output=output,
            task_title="部署服务",
            task_id="t3",
        )
        assert result.level == ConclusionLevel.SUCCESS
        assert "部署" in result.conclusion or "完成" in result.conclusion
        assert any("45s" in e or "成功" in e for e in result.evidence)

    def test_extract_from_test_output(self, extractor: ConclusionExtractor) -> None:
        output = """
Test Results:
  All Passed: 42
  Errors: 0
  Skipped: 3

Duration: 12.5s
"""
        result = extractor.extract_summary(
            raw_output=output,
            task_title="运行测试",
            task_id="t4",
        )
        assert result.level == ConclusionLevel.SUCCESS
        assert any("42" in e or "All" in e for e in result.evidence)


class TestExtractSummaryEvidence:
    @pytest.fixture
    def extractor(self) -> ConclusionExtractor:
        return ConclusionExtractor()

    def test_extracts_time_evidence(self, extractor: ConclusionExtractor) -> None:
        output = "Task completed in 120 seconds"
        result = extractor.extract_summary(output, "Task", "t1")
        # Should extract time
        assert len(result.evidence) >= 1

    def test_extracts_count_metrics(self, extractor: ConclusionExtractor) -> None:
        output = "Processed 150 files, 3 errors, 147 successful"
        result = extractor.extract_summary(output, "Process", "t2")
        assert len(result.evidence) >= 1
        # Should find some metric

    def test_no_evidence_when_empty_output(self, extractor: ConclusionExtractor) -> None:
        result = extractor.extract_summary("", "Empty", "t3")
        assert len(result.evidence) == 0


class TestExtractSummaryDetails:
    @pytest.fixture
    def extractor(self) -> ConclusionExtractor:
        return ConclusionExtractor()

    def test_details_truncated_long_output(self, extractor: ConclusionExtractor) -> None:
        long_output = "line\n" * 500
        result = extractor.extract_summary(long_output, "Long task", "t1")
        # Details should be truncated
        assert len(result.details) <= 2000

    def test_details_preserves_short_output(self, extractor: ConclusionExtractor) -> None:
        short = "short output"
        result = extractor.extract_summary(short, "Short", "t2")
        assert result.details == short

    def test_details_marked_as_collapsible(self, extractor: ConclusionExtractor) -> None:
        result = extractor.extract_summary("some output", "Task", "t3")
        assert result.details != ""


class TestExtractSummaryHeadsUp:
    @pytest.fixture
    def extractor(self) -> ConclusionExtractor:
        return ConclusionExtractor()

    def test_running_extraction(self, extractor: ConclusionExtractor) -> None:
        result = extractor.extract_summary(
            raw_output="Still processing step 3/10...",
            task_title="Long task",
            task_id="t1",
            status="running",
        )
        assert result.level == ConclusionLevel.RUNNING
        assert "进行中" in result.conclusion or "处理中" in result.conclusion

    def test_warning_detection(self, extractor: ConclusionExtractor) -> None:
        output = "Warning: memory usage high (85%)\nContinuing..."
        result = extractor.extract_summary(output, "Monitor", "t2")
        # Warning level if contains warning but continues
        assert result.level in (ConclusionLevel.WARNING, ConclusionLevel.RUNNING)


# ---------------------------------------------------------------------------
# Integration: extractor with GoalTracker context
# ---------------------------------------------------------------------------

class TestExtractWithGoalContext:
    @pytest.fixture
    def extractor(self) -> ConclusionExtractor:
        return ConclusionExtractor()

    def test_goal_context_injected_when_provided(self, extractor: ConclusionExtractor) -> None:
        result = extractor.extract_summary(
            raw_output="Task completed successfully.",
            task_title="任务A",
            task_id="t1",
            goal_context="完成供应商对比分析 (Phase 2/5)",
        )
        # Goal context should be stored and rendered in markdown
        assert result.goal_context == "完成供应商对比分析 (Phase 2/5)"
        md = result.to_markdown()
        assert "供应商" in md  # goal_context appears in rendered output

    def test_goal_context_empty_when_not_provided(self, extractor: ConclusionExtractor) -> None:
        result = extractor.extract_summary(
            raw_output="Done.",
            task_title="任务",
            task_id="t2",
        )
        # Should work without goal_context
        assert result.conclusion != ""