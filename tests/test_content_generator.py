"""Tests for ContentGeneratorAgent — generates documents from key points."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from hermes_os.content_generator import (
    ContentGeneratorAgent,
    ContentType,
    GenerationResult,
)


# ---------------------------------------------------------------------------
# ContentType tests
# ---------------------------------------------------------------------------

class TestContentType:
    def test_content_types(self) -> None:
        """All expected content types exist."""
        assert hasattr(ContentType, "INDUSTRY_REPORT")
        assert hasattr(ContentType, "INVESTMENT_ANALYSIS")
        assert hasattr(ContentType, "WORK_SUMMARY")
        assert hasattr(ContentType, "MEETING_MINUTES")
        assert hasattr(ContentType, "NOTICE")
        assert hasattr(ContentType, "RESEARCH_BRIEF")
        assert hasattr(ContentType, "PROJECT_PLAN")


# ---------------------------------------------------------------------------
# GenerationResult tests
# ---------------------------------------------------------------------------

class TestGenerationResult:
    def test_success_result(self) -> None:
        """GenerationResult stores generated content."""
        result = GenerationResult(
            content_type=ContentType.INDUSTRY_REPORT,
            content="# 一季度产业分析报告\n\n正文...",
            source_count=3,
            success=True,
        )
        assert result.content_type == ContentType.INDUSTRY_REPORT
        assert "产业分析报告" in result.content
        assert result.success is True
        assert result.error is None

    def test_failure_result(self) -> None:
        """GenerationResult with error."""
        result = GenerationResult(
            content_type=ContentType.INVESTMENT_ANALYSIS,
            content="",
            source_count=0,
            success=False,
            error="LLM timeout",
        )
        assert result.success is False
        assert "LLM timeout" in result.error


# ---------------------------------------------------------------------------
# ContentGeneratorAgent tests
# ---------------------------------------------------------------------------

class TestContentGeneratorAgentInit:
    def test_init_with_defaults(self) -> None:
        """ContentGeneratorAgent initializes with default model."""
        agent = ContentGeneratorAgent()
        assert agent.model == "sonnet"
        assert agent._invoke_func is not None


class TestContentGeneratorAgentGenerate:
    @pytest.mark.asyncio
    async def test_generate_industry_report(self) -> None:
        """generate() produces industry report content."""
        agent = ContentGeneratorAgent()

        with patch.object(agent, "_call_llm", new=AsyncMock(return_value={
            "title": "一季度经济形势分析",
            "sections": {
                "overview": "本季度GDP同比增长5.3%...",
                "trends": "数字经济、新能源汽车表现强劲",
                "risks": "房地产持续低迷、外部需求疲软",
            },
            "conclusion": "建议加大对数字经济支持力度",
        })):
            result = await agent.generate(
                key_points="分析一季度经济形势，重点关注数字经济和新能源",
                content_type=ContentType.INDUSTRY_REPORT,
                context={"industry": "宏观经济"},
            )

        assert result.success is True
        assert result.content_type == ContentType.INDUSTRY_REPORT
        assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_generate_investment_analysis(self) -> None:
        """generate() for investment analysis includes risk and options."""
        agent = ContentGeneratorAgent()

        with patch.object(agent, "_call_llm", new=AsyncMock(return_value={
            "title": "供应商方案对比分析",
            "sections": {
                "option_a": "成本最低，技术成熟度中等",
                "option_b": "技术最优，成本较高",
                "option_c": "综合性价比最高",
            },
            "risks": "A供应商交付风险、B成本超支",
            "recommendation": "推荐C方案",
        })):
            result = await agent.generate(
                key_points="对比三家供应商方案，给出投资建议",
                content_type=ContentType.INVESTMENT_ANALYSIS,
                context={},
            )

        assert result.success is True
        assert "供应商" in result.content

    @pytest.mark.asyncio
    async def test_generate_work_summary(self) -> None:
        """generate() produces structured work summary."""
        agent = ContentGeneratorAgent()

        with patch.object(agent, "_call_llm", new=AsyncMock(return_value={
            "title": "季度工作总结",
            "sections": {
                "accomplishments": "完成项目A、B两个模块开发",
                "challenges": "人员紧张，部分延期",
                "next_steps": "Q2重点推进C项目",
            },
        })):
            result = await agent.generate(
                key_points="写一季度工作总结，包含完成情况、问题、下一步",
                content_type=ContentType.WORK_SUMMARY,
                context={},
            )

        assert result.success is True
        assert "工作" in result.content

    @pytest.mark.asyncio
    async def test_generate_meeting_minutes(self) -> None:
        """generate() produces meeting minutes format."""
        agent = ContentGeneratorAgent()

        with patch.object(agent, "_call_llm", new=AsyncMock(return_value={
            "title": "项目评审会议纪要",
            "date": "2026年4月30日",
            "attendees": "张三、李四、王五",
            "decisions": "1. 同意进入测试阶段 2. 5月10日上线",
            "action_items": "张三：完成联调；李四：准备演示",
        })):
            result = await agent.generate(
                key_points="整理会议纪要：参会人张三李四王五，决定5月10上线",
                content_type=ContentType.MEETING_MINUTES,
                context={},
            )

        assert result.success is True
        assert "会议" in result.content

    @pytest.mark.asyncio
    async def test_llm_failure_returns_error(self) -> None:
        """LLM call failure returns error in result."""
        agent = ContentGeneratorAgent()

        with patch.object(agent, "_call_llm", new=AsyncMock(side_effect=Exception("timeout"))):
            result = await agent.generate(
                key_points="生成报告",
                content_type=ContentType.INDUSTRY_REPORT,
                context={},
            )

        assert result.success is False
        assert result.error is not None
        assert "timeout" in result.error


class TestContentGeneratorAgentRender:
    @pytest.mark.asyncio
    async def test_render_doc_workflow(self) -> None:
        """render_doc_workflow() renders generated content into DocWorkflow."""
        agent = ContentGeneratorAgent()

        with patch.object(agent, "_call_llm", new=AsyncMock(return_value={
            "title": "关于开展安全检查的通知",
            "to": "各部门",
            "body": "拟于5月开展安全检查，请各部门配合做好自查工作。",
            "sender": "XX办公室",
            "date": "2026年4月30日",
        })):
            result = await agent.generate(
                key_points="发个通知，要求各部门开展安全检查",
                content_type=ContentType.NOTICE,
                context={},
            )

        doc_result = await agent.render_doc_workflow(result)

        assert doc_result.success is True
        assert "安全检查" in doc_result.rendered_text
        assert doc_result.approval_flow.name in ("NONE", "IMMEDIATE", "AWAIT_REPLY")


class TestContentGeneratorAgentStreaming:
    @pytest.mark.asyncio
    async def test_generate_streaming_yields_chunks(self) -> None:
        """generate_streaming() yields content chunks as they are generated."""
        agent = ContentGeneratorAgent()

        async def mock_stream(*args, **kwargs):
            chunks = ["# 一季度", "经济分析", "报告\n\n", "正文..."]
            for chunk in chunks:
                yield chunk

        with patch.object(agent, "_stream_llm", new=mock_stream):
            chunks = []
            async for chunk in agent.generate_streaming(
                key_points="分析一季度经济",
                content_type=ContentType.INDUSTRY_REPORT,
                context={},
            ):
                chunks.append(chunk)

            assert len(chunks) >= 1
            full = "".join(chunks)
            assert len(full) > 0
