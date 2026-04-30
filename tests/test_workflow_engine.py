"""Tests for WorkflowEngine — intent-driven tool orchestration."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from hermes_os.workflow_engine import (
    WorkflowEngine,
    WorkflowStep,
    Workflow,
    WorkflowResult,
    IntentToWorkflowMapper,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def engine() -> WorkflowEngine:
    return WorkflowEngine()


# ---------------------------------------------------------------------------
# WorkflowStep & Workflow data model tests
# ---------------------------------------------------------------------------

class TestWorkflowStep:
    def test_workflow_step_creation(self) -> None:
        step = WorkflowStep(
            tool_name="feishu_calendar_events",
            action="query",
            args={"calendar_id": "primary", "days": 7},
            description="获取未来7天日历事件",
        )
        assert step.tool_name == "feishu_calendar_events"
        assert step.action == "query"
        assert step.args["days"] == 7

    def test_workflow_step_to_dict(self) -> None:
        step = WorkflowStep(
            tool_name="browser_navigate",
            action="execute",
            args={"url": "https://example.com"},
            description="打开网页",
        )
        d = step.to_dict()
        assert d["tool_name"] == "browser_navigate"
        assert d["action"] == "execute"


class TestWorkflow:
    def test_workflow_creation(self) -> None:
        steps = [
            WorkflowStep("tool1", "query", {}, "step1"),
            WorkflowStep("tool2", "create", {}, "step2"),
        ]
        wf = Workflow(
            workflow_id="wf-001",
            user_id="alice",
            name="测试流程",
            steps=steps,
            context_template="Context: {context}",
            output_format="feishu_card",
        )
        assert len(wf.steps) == 2
        assert wf.output_format == "feishu_card"

    def test_workflow_to_dict(self) -> None:
        wf = Workflow(
            workflow_id="wf-002",
            user_id="alice",
            name="项目检查",
            steps=[],
            context_template="",
            output_format="text",
        )
        d = wf.to_dict()
        assert d["workflow_id"] == "wf-002"
        assert d["output_format"] == "text"


class TestWorkflowResult:
    def test_workflow_result_success(self) -> None:
        result = WorkflowResult(
            workflow_id="wf-001",
            success=True,
            steps_completed=3,
            results=["event1", "event2", "event3"],
            output="汇总内容",
            error=None,
        )
        assert result.success is True
        assert result.steps_completed == 3
        assert len(result.results) == 3

    def test_workflow_result_failure(self) -> None:
        result = WorkflowResult(
            workflow_id="wf-001",
            success=False,
            steps_completed=1,
            results=["partial"],
            output="",
            error="Tool timeout",
        )
        assert result.success is False
        assert result.error == "Tool timeout"


# ---------------------------------------------------------------------------
# IntentToWorkflowMapper tests
# ---------------------------------------------------------------------------

class TestIntentToWorkflowMapper:
    def test_map_check_project_status(self) -> None:
        mapper = IntentToWorkflowMapper()
        wf = mapper.map("check_project_status", user_id="alice")
        assert wf is not None
        assert wf.name == "check_project_status"
        # Should have: feishu_calendar + feishu_task + feishu_doc steps
        tool_names = {s.tool_name for s in wf.steps}
        assert "feishu_calendar_events" in tool_names or "feishu_calendar_list" in tool_names
        assert "feishu_task_list" in tool_names or "feishu_bitable_records" in tool_names

    def test_map_daily_briefing(self) -> None:
        mapper = IntentToWorkflowMapper()
        wf = mapper.map("daily_briefing", user_id="alice")
        assert wf is not None
        # Should have calendar + task steps
        assert len(wf.steps) >= 2

    def test_map_unknown_returns_none(self) -> None:
        mapper = IntentToWorkflowMapper()
        wf = mapper.map("some_unknown_workflow", user_id="alice")
        assert wf is None


# ---------------------------------------------------------------------------
# WorkflowEngine execute tests
# ---------------------------------------------------------------------------

class TestWorkflowEngineExecute:
    @pytest.mark.asyncio
    async def test_execute_unknown_workflow_returns_error(self, engine: WorkflowEngine) -> None:
        result = await engine.execute(
            user_id="alice",
            workflow_name="nonexistent_workflow",
            context={},
        )
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_execute_check_project_status(self, engine: WorkflowEngine) -> None:
        # Mock all feishu tools to return fake data
        with patch.object(engine, "_execute_tool", new=AsyncMock(return_value="mock result")):
            result = await engine.execute(
                user_id="alice",
                workflow_name="check_project_status",
                context={"project_name": "Hermes-OS"},
            )
            # Should complete all steps
            assert result.steps_completed >= 1

    @pytest.mark.asyncio
    async def test_execute_daily_briefing(self, engine: WorkflowEngine) -> None:
        with patch.object(engine, "_execute_tool", new=AsyncMock(return_value="mock")):
            result = await engine.execute(
                user_id="alice",
                workflow_name="daily_briefing",
                context={"user_id": "alice"},
            )
            assert result.workflow_id is not None


# ---------------------------------------------------------------------------
# WorkflowEngine tool registration tests
# ---------------------------------------------------------------------------

class TestWorkflowEngineToolRegistry:
    def test_register_tool(self) -> None:
        engine = WorkflowEngine()
        engine.register_tool("test_tool", lambda **kwargs: "ok")
        assert "test_tool" in engine._tools

    @pytest.mark.asyncio
    async def test_call_registered_tool(self) -> None:
        engine = WorkflowEngine()
        engine.register_tool("echo", lambda args, **_: f"echo: {args.get('msg', '')}")
        result = await engine._execute_tool("echo", {"msg": "hello"})
        assert result == "echo: hello"

    def test_unregister_tool(self) -> None:
        engine = WorkflowEngine()
        engine.register_tool("temp_tool", lambda **kwargs: "x")
        engine.unregister_tool("temp_tool")
        assert "temp_tool" not in engine._tools


# ---------------------------------------------------------------------------
# Output format tests
# ---------------------------------------------------------------------------

class TestWorkflowResultOutput:
    def test_feishu_card_format(self) -> None:
        result = WorkflowResult(
            workflow_id="wf-001",
            success=True,
            steps_completed=2,
            results=[
                "📅 会议: 项目评审 10:00",
                "📋 任务: 代码审查 进行中",
            ],
            output="",
            error=None,
        )
        card = result.to_feishu_card(title="项目状态汇总")
        assert "header" in card
        assert card["header"]["title"]["content"] == "项目状态汇总"
        assert card["header"]["template"] == "blue"
        assert "elements" in card

    def test_text_format(self) -> None:
        result = WorkflowResult(
            workflow_id="wf-001",
            success=True,
            steps_completed=1,
            results=["result1", "result2"],
            output="",
            error=None,
        )
        text = result.to_text()
        assert "result1" in text
        assert "result2" in text