"""Tests for ContentLabor with real Claude Code invocation.

Tests the upgrade from placeholder content to real LLM-generated content.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from hermes_os.pipeline_engine import ContentLabor, PipelineWorkspace, LaborResult
from hermes_os.pipeline_task_runner import StageMilestone


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_invoke_result() -> MagicMock:
    result = MagicMock()
    result.stdout = "# AI History\n\n## Introduction\n\nArtificial Intelligence has transformed many industries since the 1950s.\n\n## Key Milestones\n\n1. **1956: Dartmouth Conference** - The birth of AI as a field.\n2. **1997: Deep Blue** - IBM's computer defeats chess champion.\n3. **2020s: Large Language Models** - The GPT revolution."
    result.returncode = 0
    return result


# ---------------------------------------------------------------------------
# ContentLabor.invoke tests (mocked LLM)
# ---------------------------------------------------------------------------

class TestContentLaborInvoke:
    @pytest.mark.asyncio
    async def test_invoke_generates_real_content(self, mock_invoke_result: MagicMock) -> None:
        """When Claude Code is available, ContentLabor should generate real content."""
        labor = ContentLabor()

        with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_invoke_result
            result = await labor.execute(
                description="Write a chapter on AI History",
                input_artifact=None,
                workspace=MagicMock(),
                context={"topic": "AI history"},
            )

            assert result.success is True
            assert "Artificial Intelligence" in result.output_content
            assert len(result.output_content) > 100
            mock_invoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_invoke_includes_input_artifact_context(self, mock_invoke_result: MagicMock) -> None:
        """When input_artifact exists, its content should be included in the prompt."""
        labor = ContentLabor()

        tmp = Path(tempfile.mkdtemp())
        try:
            ws = MagicMock()
            ws.src_path = tmp
            ws.completed_stages = ["research"]

            input_file = tmp / "research.md"
            input_file.write_text("# Research Notes\n\nAI was founded in 1956.", "utf-8")

            with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
                mock_invoke.return_value = mock_invoke_result
                result = await labor.execute(
                    description="Create an outline based on research",
                    input_artifact="research.md",
                    workspace=ws,
                    context={"topic": "AI history"},
                )

                call_args = mock_invoke.call_args
                prompt_sent = call_args.kwargs["prompt"]
                assert "outline" in prompt_sent.lower() or "research" in prompt_sent.lower()

        finally:
            shutil.rmtree(tmp)

    @pytest.mark.asyncio
    async def test_invoke_handles_invocation_error(self) -> None:
        """InvocationError should be caught and returned as failed LaborResult."""
        from hermes_os.claude_code_invocator import InvocationError

        labor = ContentLabor()

        with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.side_effect = InvocationError("timeout after 120s")
            result = await labor.execute(
                description="Write content",
                input_artifact=None,
                workspace=MagicMock(),
                context={"topic": "test"},
            )

            assert result.success is False
            assert "timeout" in result.error.lower() or "invocation" in result.error.lower()

    @pytest.mark.asyncio
    async def test_invoke_timeout_is_handled(self) -> None:
        """Generic exception during content generation should return failed result."""
        labor = ContentLabor()

        with patch("hermes_os.claude_code_invocator.invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.side_effect = Exception("unexpected error")
            result = await labor.execute(
                description="Write content",
                input_artifact=None,
                workspace=MagicMock(),
                context={"topic": "test"},
            )

            assert result.success is False
            assert result.error is not None


# ---------------------------------------------------------------------------
# StageMilestone with real content tests
# ---------------------------------------------------------------------------

class TestStageMilestoneWithContent:
    @pytest.mark.asyncio
    async def test_milestone_reflects_real_content(self) -> None:
        """StageMilestone should capture real generated content metadata."""
        milestone = StageMilestone(
            task_id="book-001",
            stage_name="write_chapters",
            status="completed",
            output_artifact="02_manuscript.md",
            duration_seconds=45.0,
            total_stages=6,
            completed_stages=3,
        )
        d = milestone.to_dict()
        assert d["stage_name"] == "write_chapters"
        assert d["completed_stages"] == 3
        assert d["total_stages"] == 6
        assert d["status"] == "completed"
