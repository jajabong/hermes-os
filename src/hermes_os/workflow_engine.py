"""WorkflowEngine — intent-driven tool orchestration.

Orchestrates hermes-agent tools (feishu_calendar, feishu_doc, browser, etc.)
into executable workflows based on user intent.

Workflow template → fill params → execute steps → aggregate results → output format
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class WorkflowStep:
    """A single step in a workflow."""

    tool_name: str
    action: str
    args: dict[str, Any]
    description: str

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "action": self.action,
            "args": self.args,
            "description": self.description,
        }


@dataclass
class Workflow:
    """A multi-step workflow with metadata."""

    workflow_id: str
    user_id: str
    name: str
    steps: list[WorkflowStep] = field(default_factory=list)
    context_template: str = ""
    output_format: str = "text"  # "feishu_card" | "text" | "file"

    def to_dict(self) -> dict:
        return {
            "workflow_id": self.workflow_id,
            "user_id": self.user_id,
            "name": self.name,
            "steps": [s.to_dict() for s in self.steps],
            "context_template": self.context_template,
            "output_format": self.output_format,
        }


@dataclass
class WorkflowResult:
    """Result of a workflow execution."""

    workflow_id: str
    success: bool
    steps_completed: int
    results: list[str]
    output: str
    error: str | None = None

    def to_feishu_card(self, title: str = "Workflow Result") -> dict[str, Any]:
        """Format result as a Feishu card."""
        content = "\n".join(f"• {r}" for r in self.results) if self.results else self.error or "无结果"
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue" if self.success else "red",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content}},
            ],
        }

    def to_text(self) -> str:
        """Format result as plain text."""
        if self.error:
            return f"❌ Error: {self.error}"
        return "\n".join(self.results)


class WorkflowEngine:
    """
    Orchestrates tool calls into executable workflows.

    Usage:
        engine = WorkflowEngine()
        engine.register_tool("feishu_calendar_events", my_handler)
        result = await engine.execute("alice", "check_project_status", {})
    """

    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}
        self._workflows: dict[str, Workflow] = {}
        self._register_default_workflows()

    # -------------------------------------------------------------------------
    # Tool registration
    # -------------------------------------------------------------------------

    def register_tool(self, name: str, handler: Callable[..., Any]) -> None:
        """Register a tool handler for workflow steps."""
        self._tools[name] = handler

    def unregister_tool(self, name: str) -> None:
        """Remove a registered tool."""
        self._tools.pop(name, None)

    async def _execute_tool(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute a registered tool and return result string."""
        handler = self._tools.get(tool_name)
        if not handler:
            return f"[Tool not found: {tool_name}]"

        try:
            # hermes-agent tool handlers take (args: dict, **kwargs)
            result = handler(args, **{})
            if asyncio.iscoroutine(result):
                result = await result
            return str(result)
        except Exception as e:
            logger.warning("Tool %s failed: %s", tool_name, e)
            return f"[Error: {e}]"

    # -------------------------------------------------------------------------
    # Workflow execution
    # -------------------------------------------------------------------------

    async def execute(
        self,
        user_id: str,
        workflow_name: str,
        context: dict[str, Any],
    ) -> WorkflowResult:
        """
        Execute a named workflow with given context.

        Args:
            user_id: Owner of the workflow
            workflow_name: Name of workflow template to use
            context: Parameters to fill into workflow template

        Returns:
            WorkflowResult with all step results
        """
        workflow = self._workflows.get(workflow_name)
        if not workflow:
            return WorkflowResult(
                workflow_id=workflow_name,
                success=False,
                steps_completed=0,
                results=[],
                output="",
                error=f"Unknown workflow: {workflow_name}",
            )

        results: list[str] = []
        for i, step in enumerate(workflow.steps):
            # Fill context variables in args
            filled_args = {
                k: _fill_template(str(v), context) for k, v in step.args.items()
            }

            result_str = await self._execute_tool(step.tool_name, filled_args)
            results.append(result_str)

        return WorkflowResult(
            workflow_id=workflow.workflow_id,
            success=True,
            steps_completed=len(workflow.steps),
            results=results,
            output="",
            error=None,
        )

    # -------------------------------------------------------------------------
    # Default workflow templates
    # -------------------------------------------------------------------------

    def _register_default_workflows(self) -> None:
        """Register built-in workflow templates."""
        self._workflows["check_project_status"] = Workflow(
            workflow_id="check_project_status",
            user_id="",
            name="check_project_status",
            steps=[
                WorkflowStep(
                    tool_name="feishu_calendar_events",
                    action="query",
                    args={"days": "7"},
                    description="获取未来7天日历事件",
                ),
                WorkflowStep(
                    tool_name="feishu_task_list",
                    action="query",
                    args={},
                    description="获取任务列表",
                ),
            ],
            context_template="Project: {project_name}",
            output_format="feishu_card",
        )

        self._workflows["daily_briefing"] = Workflow(
            workflow_id="daily_briefing",
            user_id="",
            name="daily_briefing",
            steps=[
                WorkflowStep(
                    tool_name="feishu_calendar_list",
                    action="query",
                    args={},
                    description="获取主日历",
                ),
                WorkflowStep(
                    tool_name="feishu_calendar_events",
                    action="query",
                    args={"days": "1"},
                    description="获取今日事件",
                ),
                WorkflowStep(
                    tool_name="feishu_task_list",
                    action="query",
                    args={},
                    description="获取今日任务",
                ),
            ],
            context_template="User: {user_id}",
            output_format="feishu_card",
        )

        self._workflows["project_research"] = Workflow(
            workflow_id="project_research",
            user_id="",
            name="project_research",
            steps=[
                WorkflowStep(
                    tool_name="feishu_doc_search",
                    action="query",
                    args={"query": "{topic}"},
                    description="搜索飞书文档",
                ),
            ],
            context_template="Topic: {topic}",
            output_format="text",
        )


def _fill_template(template: str, context: dict[str, Any]) -> str:
    """Simple template filling: {key} → context[key]."""
    result = template
    for key, value in context.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


class IntentToWorkflowMapper:
    """
    Maps intent names to workflow templates.

    Usage:
        mapper = IntentToWorkflowMapper()
        wf = mapper.map("check_project_status", user_id="alice")
    """

    _MAPPINGS: dict[str, str] = {
        "check_project_status": "check_project_status",
        "daily_briefing": "daily_briefing",
        "project_research": "project_research",
        "deploy": "deploy_service",
        "fix_bug": "debug_and_fix",
    }

    def map(self, intent_name: str, user_id: str) -> Workflow | None:
        """Map an intent to a workflow, or None if no mapping exists."""
        wf_name = self._MAPPINGS.get(intent_name)
        if not wf_name:
            return None

        engine = WorkflowEngine()
        wf_template = engine._workflows.get(wf_name)
        if not wf_template:
            return None

        # Clone with user_id set
        return Workflow(
            workflow_id=f"{wf_name}_{user_id}",
            user_id=user_id,
            name=wf_name,
            steps=wf_template.steps,
            context_template=wf_template.context_template,
            output_format=wf_template.output_format,
        )