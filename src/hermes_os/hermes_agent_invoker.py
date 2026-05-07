"""HermesAgentInvoker — bridge between TaskScheduler and hermes-agent AIAgent SDK.

Provides a Python API wrapper around hermes-agent's AIAgent.run_conversation()
as an alternative to the raw `claude -p` subprocess invocation.

When hermes-agent SDK is available, uses AIAgent Python API for:
- Better conversation history management
- Token counting and context management
- Multi-turn conversation loops
- Improved error handling and recovery

When SDK is unavailable, falls back to subprocess invoke() via claude_code_invocator.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from hermes_os.claude_code_invocator import InvocationError, InvocationResult

# Try to import hermes-agent SDK
HERMES_AGENT_SDK_AVAILABLE = False
AIAgent = None

try:
    from hermes_agent.run_agent import AIAgent
    HERMES_AGENT_SDK_AVAILABLE = True
except ImportError:
    AIAgent = None


async def invoke_hermes_agent(
    prompt: str,
    cwd: str | None = None,
    model: str = "claude-sonnet-4-6",
    max_turns: int = 20,
    timeout_sec: int = 120,
    allowed_tools: str | None = None,
    system_prompt: str | None = None,
    extra_flags: list[str] | None = None,
) -> InvocationResult:
    """
    Invoke via hermes-agent AIAgent Python SDK (not subprocess).

    Falls back to subprocess invoke() if SDK is not available.

    Args:
        prompt: Task description
        cwd: Working directory
        model: Model name
        max_turns: Max tool-calling iterations
        timeout_sec: Timeout in seconds
        allowed_tools: Comma-separated tool whitelist
        system_prompt: System prompt to prepend
        extra_flags: Additional CLI flags

    Returns:
        InvocationResult

    Raises:
        InvocationError: On failure
    """
    if not HERMES_AGENT_SDK_AVAILABLE or AIAgent is None:
        # Fallback to subprocess
        from hermes_os.claude_code_invocator import invoke as subprocess_invoke

        return await subprocess_invoke(
            prompt=prompt,
            cwd=cwd,
            model=model,
            max_turns=max_turns,
            timeout_sec=timeout_sec,
            allowed_tools=allowed_tools,
            system_prompt=system_prompt,
            extra_flags=extra_flags,
        )

    # Use AIAgent Python API
    start = datetime.now()

    try:
        agent = AIAgent(
            base_url=_get_base_url(),
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            model=model,
            max_iterations=max_turns * 2,  # AIAgent uses iterations, not turns
            ephemeral_system_prompt=system_prompt,
            enabled_toolsets=_parse_toolsets(allowed_tools),
            verbose_logging=False,
            quiet_mode=True,
        )

        result = agent.run_conversation(
            user_message=prompt,
            system_message=system_prompt,
            conversation_history=[],
        )

        duration_ms = int((datetime.now() - start).total_seconds() * 1000)

        # AIAgent returns dict with final_response and message_history
        if isinstance(result, dict):
            return InvocationResult(
                stdout=result.get("final_response", ""),
                stderr="",
                exit_code=0,
                duration_ms=duration_ms,
                model=model,
            )
        else:
            return InvocationResult(
                stdout=str(result),
                stderr="",
                exit_code=0,
                duration_ms=duration_ms,
                model=model,
            )

    except Exception as e:
        duration_ms = int((datetime.now() - start).total_seconds() * 1000)
        raise InvocationError(
            f"hermes-agent AIAgent failed: {str(e)[:500]}",
            InvocationResult(
                stdout="",
                stderr=str(e)[:500],
                exit_code=-1,
                duration_ms=duration_ms,
                model=model,
            ),
        )


def _get_base_url() -> str:
    """Get API base URL from environment."""
    return os.environ.get(
        "ANTHROPIC_BASE_URL",
        "https://api.anthropic.com",
    )


def _parse_toolsets(allowed_tools: str | None) -> list[str]:
    """Convert allowed_tools string to AIAgent toolsets list."""
    if not allowed_tools:
        return ["code", "bash", "read", "write", "edit", "glob", "grep"]

    # Map common tool names to hermes-agent toolset names
    tool_map = {
        "bash": "bash",
        "read": "read",
        "write": "write",
        "edit": "edit",
        "glob": "glob",
        "grep": "grep",
        "notebook": "notebook",
    }

    tools = [t.strip() for t in allowed_tools.split(",")]
    toolsets = []
    for tool in tools:
        if tool in tool_map:
            toolsets.append(tool_map[tool])

    return toolsets if toolsets else ["code", "bash", "read", "write", "edit", "glob", "grep"]