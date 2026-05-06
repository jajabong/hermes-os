"""ContentGeneratorAgent — generates documents from key points using LLM."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from hermes_os.claude_code_invocator import invoke
from hermes_os.doc_workflow import DocType, DocWorkflowEngine


class ContentType(str, Enum):
    """Types of content that can be generated."""

    INDUSTRY_REPORT = "industry_report"  # 产业研究报告
    INVESTMENT_ANALYSIS = "investment_analysis"  # 投资分析
    WORK_SUMMARY = "work_summary"  # 工作总结
    MEETING_MINUTES = "meeting_minutes"  # 会议纪要
    NOTICE = "notice"  # 通知
    RESEARCH_BRIEF = "research_brief"  # 研究简报
    PROJECT_PLAN = "project_plan"  # 项目计划


@dataclass
class GenerationResult:
    """Result of content generation."""

    content_type: ContentType
    content: str
    source_count: int = 0
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# System prompt for content generation
_GENERATION_PROMPT_TEMPLATE = """You are a professional government and enterprise document writer for Hermes OS.

Given the user's key points, generate a structured, complete document. The output must be directly usable — a leader can sign or send it directly.

## Content Type
{content_type_description}

## User's Key Points
{key_points}

## Context
{context_str}

## Output Format
Return ONLY valid JSON matching this schema (no markdown, no explanation):
{{
  "title": "Document title",
  "sections": {{
    "section_name": "Section content..."
  }},
  "conclusion": "Conclusion or recommendation",
  "risks": "Risk points (optional, for analysis documents)"
}}

For NOTICE type, also include: "to", "sender", "date" (as placeholders like TBD).
For MEETING_MINUTES, also include: "date", "attendees", "decisions", "action_items".
For INVESTMENT_ANALYSIS, also include: "option_a", "option_b", "option_c", "recommendation".
"""


class ContentGeneratorAgent:
    """
    Generates complete documents from brief key points.

    Takes a leader's casual description and produces a polished, formal document
    ready for signature or distribution.

    Usage:
        agent = ContentGeneratorAgent()
        result = await agent.generate(
            key_points="分析一季度经济形势，重点关注数字经济",
            content_type=ContentType.INDUSTRY_REPORT,
        )
    """

    CONTENT_TYPE_DESCRIPTIONS = {
        ContentType.INDUSTRY_REPORT: "产业研究报告：宏观经济/行业分析，含趋势、风险、建议",
        ContentType.INVESTMENT_ANALYSIS: "投资分析报告：方案对比、风险评估、建议选项",
        ContentType.WORK_SUMMARY: "工作总结：完成情况、存在问题、下一步计划",
        ContentType.MEETING_MINUTES: "会议纪要：时间、参会人、决议、待办事项",
        ContentType.NOTICE: "正式通知：标题、主送、正文、落款",
        ContentType.RESEARCH_BRIEF: "研究简报：研究背景、主要发现、结论建议",
        ContentType.PROJECT_PLAN: "项目计划：目标、里程碑、责任人、时间表",
    }

    def __init__(self, model: str = "sonnet") -> None:
        self.model = model
        self._invoke_func = invoke

    async def generate(
        self,
        key_points: str,
        content_type: ContentType,
        context: dict[str, Any] | None = None,
    ) -> GenerationResult:
        """
        Generate content from key points.

        Args:
            key_points: Leader's brief description of what they need
            content_type: Type of document to generate
            context: Additional context (project name, date, etc.)

        Returns:
            GenerationResult with generated content or error
        """
        if not key_points.strip():
            return GenerationResult(
                content_type=content_type,
                content="",
                success=False,
                error="Empty key points",
            )

        context_str = self._format_context(context or {})

        prompt = _GENERATION_PROMPT_TEMPLATE.format(
            content_type_description=self.CONTENT_TYPE_DESCRIPTIONS.get(
                content_type, str(content_type)
            ),
            key_points=key_points,
            context_str=context_str,
        )

        try:
            llm_output = await self._call_llm(prompt)
            content = self._render_content(llm_output, content_type)
            return GenerationResult(
                content_type=content_type,
                content=content,
                source_count=1,
                success=True,
                metadata={"llm_output": llm_output},
            )
        except Exception as e:
            return GenerationResult(
                content_type=content_type,
                content="",
                success=False,
                error=str(e),
            )

    async def generate_streaming(
        self,
        key_points: str,
        content_type: ContentType,
        context: dict[str, Any] | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming version of generate() — yields content chunks as they're produced.

        For long documents, this allows the user to see partial results immediately.
        """
        context_str = self._format_context(context or {})
        prompt = _GENERATION_PROMPT_TEMPLATE.format(
            content_type_description=self.CONTENT_TYPE_DESCRIPTIONS.get(
                content_type, str(content_type)
            ),
            key_points=key_points,
            context_str=context_str,
        )

        async for chunk in self._stream_llm(prompt):
            yield chunk

    async def render_doc_workflow(
        self,
        result: GenerationResult,
    ):
        """
        Render generation result into DocWorkflow for government document output.

        Only works for NOTICE, REPORT, REQUEST, LETTER content types.
        """
        if not result.success:
            from hermes_os.doc_workflow import ApprovalFlow, DocWorkflowResult

            return DocWorkflowResult(
                doc_type=DocType.NOTICE,
                rendered_text="",
                approval_flow=ApprovalFlow.NONE,
                success=False,
                error=result.error,
            )

        engine = DocWorkflowEngine()
        doc_type = self._content_type_to_doc_type(result.content_type)

        # Parse the generated content into doc_workflow values
        # result.content is rendered markdown, we need the raw LLM output from metadata
        llm_output = result.metadata.get("llm_output", {})
        if not llm_output:
            # Fallback: try parsing content as markdown title
            lines = result.content.split("\n")
            title = ""
            for line in lines:
                if line.startswith("# "):
                    title = line[2:]
                    break
            llm_output = {"title": title, "sections": {}}

        values = self._extract_doc_values(llm_output, doc_type)

        return engine.render(doc_type=doc_type, values=values)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    async def _call_llm(self, prompt: str) -> dict[str, Any]:
        """Call LLM and parse JSON output."""
        from hermes_os.claude_code_invocator import DEFAULT_TIMEOUT_SEC

        result = await self._invoke_func(
            prompt=prompt,
            model=f"claude-{self.model}-4-6",
            max_turns=5,
            timeout_sec=DEFAULT_TIMEOUT_SEC,
            output_format="json",
            system_prompt="You are a professional government document writer.",
        )

        if not result.ok:
            raise Exception(f"LLM call failed: {result.stderr}")

        return json.loads(result.stdout)

    async def _stream_llm(self, prompt: str) -> AsyncGenerator[str, None]:
        """Stream LLM output as chunks."""
        from hermes_os.claude_code_invocator import invoke_stream

        async for chunk in invoke_stream(prompt, model=f"claude-{self.model}-4-6"):
            yield chunk

    def _render_content(self, llm_output: dict[str, Any], content_type: ContentType) -> str:
        """Render LLM output dict into a formatted document string."""
        title = llm_output.get("title", "")
        sections = llm_output.get("sections", {})
        body = llm_output.get("body", "")

        lines = [f"# {title}", ""] if title else []

        # NOTICE and LETTER use body field directly
        if body:
            lines.append(body)
        else:
            for name, content in sections.items():
                lines.append(f"## {name}")
                lines.append(content)
                lines.append("")

        conclusion = llm_output.get("conclusion")
        if conclusion:
            lines.append(f"## 结论\n\n{conclusion}")

        risks = llm_output.get("risks")
        if risks:
            lines.append(f"\n## 风险提示\n\n{risks}")

        return "\n".join(lines)

    def _format_context(self, context: dict[str, Any]) -> str:
        """Format context dict for prompt injection."""
        if not context:
            return "No additional context provided."
        return "\n".join(f"- {k}: {v}" for k, v in context.items())

    def _content_type_to_doc_type(self, ct: ContentType) -> DocType:
        """Map ContentType to DocType for doc workflow rendering."""
        mapping = {
            ContentType.NOTICE: DocType.NOTICE,
            ContentType.WORK_SUMMARY: DocType.REPORT,
            ContentType.RESEARCH_BRIEF: DocType.REPORT,
        }
        return mapping.get(ct, DocType.NOTICE)

    def _extract_doc_values(self, parsed: dict[str, Any], doc_type: DocType) -> dict[str, str]:
        """Extract doc workflow values from LLM output."""
        base = {
            "title": parsed.get("title", ""),
            "sender": parsed.get("sender", "TBD"),
            "date": parsed.get("date", "TBD"),
        }

        if doc_type in (DocType.NOTICE, DocType.LETTER):
            base["body"] = parsed.get("body", "") or "\n\n".join(
                parsed.get("sections", {}).values()
            )
            base["to"] = parsed.get("to", "")

        elif doc_type == DocType.REPORT:
            base["to"] = parsed.get("to", "领导")
            sections = parsed.get("sections", {})
            for i, (k, v) in enumerate(sections.items(), 1):
                base[f"section{i}"] = v

        elif doc_type == DocType.REQUEST:
            base["to"] = parsed.get("to", "领导")
            sections = parsed.get("sections", {})
            section_items = list(sections.items())
            base["section1"] = section_items[0][1] if len(section_items) > 0 else ""
            base["section2"] = section_items[1][1] if len(section_items) > 1 else ""

        return base
