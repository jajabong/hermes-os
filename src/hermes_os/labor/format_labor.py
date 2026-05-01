"""FormatLabor — Content Assembly Pipeline rendering and formatting labor.

Implements Content Assembly Pipeline stages:
- M4_RENDERING: Format content into final output (MD/DOCX/PDF)
- M5_AUDIT: Verify quality and consistency (via CheckerLabor)

Note: M5_AUDIT is handled by CheckerLabor in pipeline definitions.
FormatLabor handles the rendering/formatting aspects.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FormatLabor:
    """Labor unit for content formatting and rendering."""

    def __init__(self, **kwargs) -> None:
        pass

    async def execute(self, workspace: Path, task_description: str, meta: dict[str, Any]) -> bool:
        """
        Execute formatting/rendering task.

        Stage-specific behavior:
        - M4_RENDERING: Format content into final output
        """
        stage = meta.get("stage", "M4_RENDERING")

        if stage == "M4_RENDERING":
            return await self._execute_m4_rendering(workspace, task_description, meta)
        else:
            logger.warning("FormatLabor: unknown stage %s", stage)
            return False

    async def _execute_m4_rendering(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> bool:
        """M4_RENDERING: Format content into final output (MD/DOCX/PDF)."""
        output_format = meta.get("format", "markdown")
        artifact_dir = workspace / "delivery"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        logger.info("FormatLabor M4_RENDERING: format=%s", output_format)

        try:
            # Find content to render
            content_file = workspace / "src" / "content" / "full_draft.md"
            if not content_file.exists():
                # Try finding any draft content
                src_content = workspace / "src" / "content"
                if src_content.exists():
                    md_files = list(src_content.glob("*.md"))
                    if md_files:
                        content_file = md_files[0]

            if content_file.exists():
                content = content_file.read_text(encoding="utf-8")
                rendered = self._render_content(content, output_format, meta)

                output_path = artifact_dir / f"output.{output_format}"
                output_path.write_text(rendered, encoding="utf-8")

                logger.info("M4_RENDERING: rendered to %s", output_path)
                return True

            logger.warning("M4_RENDERING: no content found to render")
            return False

        except Exception as e:
            logger.exception("M4_RENDERING failed")
            return False

    def _render_content(self, content: str, format: str, meta: dict[str, Any]) -> str:
        """Render content to specified format."""
        # Placeholder - in production, use pandoc or similar for format conversion
        if format == "markdown":
            return content
        elif format == "html":
            return f"<html><body>\n{content}\n</body></html>"
        else:
            return content


# ---------------------------------------------------------------------------
# Verification functions (used by PipelineEngine)
# ---------------------------------------------------------------------------

from hermes_os.universal_pipeline import VerificationResult


async def verify_rendering_complete(rendering_json: str) -> VerificationResult:
    """Verify rendering produced output."""
    errors = []
    try:
        data = json.loads(rendering_json)
        if "output_path" not in data and "content" not in data:
            errors.append("No rendering output produced")
    except json.JSONDecodeError:
        errors.append("Invalid JSON rendering result")
    return VerificationResult(passed=len(errors) == 0, errors=errors)