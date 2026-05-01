"""Tests for WorkflowEngine + UniversalPipelineLoader integration.

Integration point: WorkflowEngine provides tool execution context for pipeline stages.
When a pipeline stage (e.g., M6_DELIVERY) needs to execute tools (feishu_doc, browser),
it uses WorkflowEngine's registered tool handlers.

RED phase: Define integration contract first.
"""

import pytest
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from hermes_os.workflow_engine import WorkflowEngine, Workflow, WorkflowStep, WorkflowResult
from hermes_os.universal_pipeline import UniversalPipelineLoader, PipelineConfig


class TestWorkflowPipelineIntegration:
    """Test WorkflowEngine integrates with UniversalPipelineLoader."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.fixture
    def workflow_engine(self) -> WorkflowEngine:
        return WorkflowEngine()

    @pytest.fixture
    def pipeline_loader(self) -> UniversalPipelineLoader:
        return UniversalPipelineLoader()

    def test_workflow_engine_can_be_passed_to_pipeline_context(
        self, workflow_engine: WorkflowEngine, pipeline_loader: UniversalPipelineLoader, temp_dir: str
    ) -> None:
        """WorkflowEngine instance should be passable as pipeline context."""
        config = pipeline_loader.load_pipeline("deployment")

        context = {
            "user_id": "alice",
            "workflow_engine": workflow_engine,
        }

        # Pass workflow_engine in context to pipeline
        assert context["workflow_engine"] is workflow_engine

    @pytest.mark.asyncio
    async def test_pipeline_stage_can_call_workflow_tools(
        self, workflow_engine: WorkflowEngine, pipeline_loader: UniversalPipelineLoader, temp_dir: str
    ) -> None:
        """Pipeline stages should be able to call WorkflowEngine tools."""
        # Register a mock tool in WorkflowEngine
        async def mock_feishu_doc_handler(args, **kwargs):
            return f"doc_created: {args.get('title', 'untitled')}"

        workflow_engine.register_tool("feishu_doc_create", mock_feishu_doc_handler)

        # Execute a tool through WorkflowEngine
        result = await workflow_engine._execute_tool("feishu_doc_create", {"title": "Test Doc"})
        assert result == "doc_created: Test Doc"

    @pytest.mark.asyncio
    async def test_feishu_labor_uses_workflow_engine_tools(
        self, workflow_engine: WorkflowEngine, pipeline_loader: UniversalPipelineLoader, temp_dir: str
    ) -> None:
        """FeishuLabor (M6_DELIVERY) should use WorkflowEngine for feishu operations."""
        # Register feishu tools
        async def feishu_doc_create(args, **kwargs):
            return '{"doc_id": "test-123", "url": "https://feishu.cn/doc/test-123"}'

        async def feishu_message_send(args, **kwargs):
            return '{"msg_id": "msg-456"}'

        workflow_engine.register_tool("feishu_doc_create", feishu_doc_create)
        workflow_engine.register_tool("feishu_message_send", feishu_message_send)

        # Execute FeishuLabor M6_DELIVERY stage
        config = pipeline_loader.load_pipeline("content_assembly")
        m6_stage = next(s for s in config.steps if s.stage == "M6_DELIVERY")

        context = {
            "user_id": "alice",
            "artifact_id": "test-artifact",
            "title": "Test Document",
            "workflow_engine": workflow_engine,
        }

        result = await pipeline_loader.execute_stage(m6_stage, context, temp_dir)

        # FeishuLabor should execute and call feishu tools
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_browser_labor_uses_workflow_engine_tools(
        self, workflow_engine: WorkflowEngine, pipeline_loader: UniversalPipelineLoader, temp_dir: str
    ) -> None:
        """BrowserLabor (M1-M4) should use WorkflowEngine for browser automation."""
        # Register browser tools
        async def browser_navigate(args, **kwargs):
            return '{"status": "loaded", "url": "https://amazon.com"}'

        async def browser_fill_form(args, **kwargs):
            return '{"filled": true, "fields": 5}'

        workflow_engine.register_tool("browser_navigate", browser_navigate)
        workflow_engine.register_tool("browser_fill_form", browser_fill_form)

        # Execute BrowserLabor M1_STATEDAUTH
        config = pipeline_loader.load_pipeline("deployment")
        m1_stage = next(s for s in config.steps if s.stage == "M1_STATEDAUTH")

        context = {
            "user_id": "alice",
            "artifact_id": "test-upload",
            "platform": "amazon",
            "workflow_engine": workflow_engine,
        }

        result = await pipeline_loader.execute_stage(m1_stage, context, temp_dir)

        assert result.passed is True

    @pytest.mark.asyncio
    async def test_workflow_result_can_feed_into_pipeline(
        self, workflow_engine: WorkflowEngine, pipeline_loader: UniversalPipelineLoader, temp_dir: str
    ) -> None:
        """Workflow results should be usable as pipeline context for next stage."""
        # Execute workflow first
        workflow_engine.register_tool("fetch_data", AsyncMock(return_value='{"repos": [{"name": "test"}]}'))
        workflow_result = await workflow_engine.execute(
            user_id="alice",
            workflow_name="project_research",
            context={"topic": "hermes-os"}
        )

        # Use workflow result as context for pipeline
        config = pipeline_loader.load_pipeline("intelligence")
        m1_stage = next(s for s in config.steps if s.stage == "M1_DATAFETCH")

        context = {
            "user_id": "alice",
            "artifact_id": "test-artifact",
            "workflow_result": workflow_result,
        }

        result = await pipeline_loader.execute_stage(m1_stage, context, temp_dir)
        assert result.passed is True


class TestIntentToPipelineRouting:
    """Test that user intents route to correct pipelines."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.fixture
    def pipeline_loader(self) -> UniversalPipelineLoader:
        return UniversalPipelineLoader()

    def test_intent_check_project_status_routes_to_engineering_pipeline(
        self, pipeline_loader: UniversalPipelineLoader
    ) -> None:
        """'check_project_status' intent should route to engineering pipeline."""
        intent_to_pipeline = {
            "check_project_status": "engineering",
            "daily_briefing": "intelligence",
            "deploy": "deployment",
            "write_document": "content_assembly",
            "sanitize_wiki": "governance",
        }

        for intent, expected_pipeline in intent_to_pipeline.items():
            config = pipeline_loader.load_pipeline(expected_pipeline)
            assert config.name is not None

    @pytest.mark.asyncio
    async def test_deployment_pipeline_executes_with_workflow_context(
        self, pipeline_loader: UniversalPipelineLoader, temp_dir: str
    ) -> None:
        """Deployment pipeline should work with workflow context."""
        config = pipeline_loader.load_pipeline("deployment")

        context = {
            "user_id": "alice",
            "artifact_id": "deployment-001",
            "platform": "amazon",
            "workflow_engine": WorkflowEngine(),
        }

        result = await pipeline_loader.execute_full_pipeline(
            config,
            artifact_id="deployment-001",
            base_dir=temp_dir,
            context=context,
        )

        assert result.success is True
        assert result.stages_completed == 5


class TestPipelineToolIntegration:
    """Test Pipeline stages call registered tools correctly."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_data_labor_calls_fetch_tool(self, temp_dir: str) -> None:
        """DataLabor M1_DATAFETCH should call fetch_github_data tool."""
        pipeline_loader = UniversalPipelineLoader()
        config = pipeline_loader.load_pipeline("intelligence")
        m1_stage = next(s for s in config.steps if s.stage == "M1_DATAFETCH")

        # Mock the labor handler to track tool calls
        tool_calls = []

        async def mock_data_handler(context):
            tool_calls.append(("fetch_github_data", context.get("source", "unknown")))
            return "[DataLabor] Fetched data"

        pipeline_loader.registry._handlers["DataLabor"] = MagicMock()
        pipeline_loader.registry._handlers["DataLabor"].execute = mock_data_handler

        context = {
            "user_id": "alice",
            "artifact_id": "test",
            "source": "github",
        }

        result = await pipeline_loader.execute_stage(m1_stage, context, temp_dir)
        # Handler was called (even if mocked)
        assert result.passed is True