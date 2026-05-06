"""ContentLabor — Worker for LLM-based content generation.

Adheres to the Hermes OS LaborInterface protocol.
Responsible for content generation based on spec and task description.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from hermes_os.claude_code_invocator import invoke
from hermes_os.labor_registry import LaborResult
from hermes_os.org_memory import OrgMemory

logger = logging.getLogger(__name__)


class ContentLabor:
    """Labor unit that uses Claude to generate content."""

    def __init__(self, org_memory: OrgMemory | None = None, **kwargs) -> None:
        self._org_memory = org_memory or OrgMemory()

    async def execute(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> LaborResult:
        """
        Execute content generation.
        1. Context Loading: Load outline/spec from workspace.
        2. Content Gen: Invoke LLM.
        3. Persist: Save result to workspace/render/content.md.
        """
        render_dir = workspace / "render"
        render_dir.mkdir(parents=True, exist_ok=True)

        # 1. Load context (e.g., outline from M1_OUTLINE)
        src_path = workspace / "src" / "outline.md"
        outline = src_path.read_text(encoding="utf-8") if src_path.exists() else ""

        # 2. Inject Memory
        memory_context = self._org_memory.search_relevant_memory(task_description)

        # 3. Generate
        prompt = f"""
        Objective: {task_description}
        
        Context:
        {outline}
        
        Knowledge:
        {memory_context}
        
        Generate the content section. Output raw Markdown.
        """

        logger.info("ContentLabor executing stage: %s", meta.get("stage"))

        try:
            result = await invoke(
                prompt=prompt,
                cwd=str(workspace),
                model=meta.get("model", "sonnet"),
                system_prompt="You are a professional content creator for Hermes OS.",
            )

            if result.ok:
                output_file = render_dir / "content.md"
                output_file.write_text(result.stdout, encoding="utf-8")

                # Estimate token usage (rough approximation: 1 token per 4 chars)
                estimated_tokens = len(result.stdout) // 4 + len(prompt) // 4
                cost_per_million = 15.0 if "sonnet" in result.model else 3.0  # Simplified
                api_cost = (estimated_tokens / 1_000_000) * cost_per_million

                return LaborResult(
                    success=True, token_usage=estimated_tokens, api_cost_usd=api_cost
                )
            else:
                logger.error("ContentLabor failed: %s", result.stderr)
                return LaborResult(success=False, error=result.stderr)

        except Exception as e:
            logger.exception("ContentLabor exception")
            return LaborResult(success=False, error=str(e))
