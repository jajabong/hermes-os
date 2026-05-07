"""TDD tests for TaskScheduler hermes-agent SDK integration.

Tests:
1. hermes-agent SDK availability detection works
2. TaskScheduler routes to SDK when available, subprocess when not
3. Invocation params are passed correctly to AIAgent
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Test: hermes-agent SDK availability detection
# ---------------------------------------------------------------------------


def test_hermes_agent_sdk_importable() -> None:
    """AIAgent should be importable from hermes_agent.run_agent."""
    try:
        from hermes_agent.run_agent import AIAgent
        assert callable(AIAgent)
    except ImportError:
        pytest.skip("hermes-agent not installed")


def test_task_scheduler_detects_hermes_agent_sdk(tmp_path: Path) -> None:
    """TaskScheduler should detect when hermes-agent SDK is available."""
    # The SDK detection is done via try/except import at module level
    # This test verifies the detection mechanism exists
    from hermes_os.task_scheduler import HERMES_AGENT_SDK_AVAILABLE
    # Just check the variable exists - it may be True or False depending on install
    assert isinstance(HERMES_AGENT_SDK_AVAILABLE, bool)


# ---------------------------------------------------------------------------
# Test: AIAgent can be instantiated with correct params
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hermes_agent_invoker_passes_correct_params() -> None:
    """Verify that invoke_hermes_agent passes model, system_prompt to AIAgent."""
    # hermes-agent SDK is in ~/.hermes/hermes-agent/ - not pip-installable
    # Mock AIAgent to capture init params
    import sys
    from pathlib import Path

    # Add hermes-agent path to sys.path for testing
    hermes_path = Path.home() / ".hermes" / "hermes-agent"
    if hermes_path.exists():
        sys.path.insert(0, str(hermes_path))

    try:
        from hermes_agent.run_agent import AIAgent
    except ImportError:
        pytest.skip("hermes-agent not available in sys.path")

    # Mock AIAgent to capture init params
    init_params = {}

    original_init = AIAgent.__init__

    def capturing_init(self, *args, **kwargs):
        init_params.update(kwargs)
        return original_init(self, *args, **kwargs)

    with patch.object(AIAgent, "__init__", capturing_init):
        with patch.object(AIAgent, "run_conversation", return_value={"final_response": "done", "message_history": []}):
            from hermes_os.hermes_agent_invoker import invoke_hermes_agent

            result = await invoke_hermes_agent(
                prompt="test prompt",
                model="claude-sonnet-4-6",
                system_prompt="You are a helpful assistant",
                max_turns=20,
            )

    # Verify AIAgent was initialized with correct params
    assert init_params.get("model") == "claude-sonnet-4-6"
    assert "You are a helpful assistant" in str(init_params.get("ephemeral_system_prompt", ""))


# ---------------------------------------------------------------------------
# Test: Error handling maps to InvocationError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hermes_agent_error_becomes_invocation_error() -> None:
    """AIAgent errors should be wrapped as InvocationError."""
    from hermes_os.claude_code_invocator import InvocationError

    with patch("hermes_os.hermes_agent_invoker.AIAgent") as mock_agent_class:
        mock_agent = MagicMock()
        mock_agent.run_conversation.side_effect = RuntimeError("API error")
        mock_agent_class.return_value = mock_agent

        from hermes_os.hermes_agent_invoker import invoke_hermes_agent

        with pytest.raises(InvocationError):
            await invoke_hermes_agent(prompt="test prompt")


# ---------------------------------------------------------------------------
# Test: Fallback to subprocess when SDK unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_to_subprocess_when_sdk_unavailable(tmp_path: Path) -> None:
    """When HERMES_AGENT_SDK_AVAILABLE=False, TaskScheduler uses subprocess invoke()."""
    from hermes_os.task_scheduler import TaskScheduler

    scheduler = TaskScheduler(db_path=str(tmp_path / "test_fallback.db"))
    scheduler._jarvis = AsyncMock()

    task = await scheduler.create_task(
        user_id="alice",
        title="Fallback Test",
        description="Test fallback",
        metadata={"retry_count": 0, "skip_confirmation": True},
    )

    mock_result = AsyncMock()
    mock_result.stdout = "done"
    mock_result.ok = True

    with patch("hermes_os.task_scheduler.HERMES_AGENT_SDK_AVAILABLE", False):
        with patch("hermes_os.task_scheduler.invoke", return_value=mock_result) as mock_invoke:
            with patch.object(scheduler._skill_discovery, "detect_gap", new_callable=AsyncMock):
                try:
                    await scheduler._process_pending_tasks()
                except Exception:
                    pass

    # invoke (subprocess) should have been called
    assert mock_invoke.call_count >= 1