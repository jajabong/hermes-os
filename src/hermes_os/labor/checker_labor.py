"""CheckerLabor — Quality assurance labor for pipeline artifacts.

Performs quality checks on generated content/artifacts.
Used by M5_AUDIT in Content Assembly Pipeline.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CheckerLabor:
    """Labor unit for quality assurance checks."""

    def __init__(self, **kwargs) -> None:
        # Accept any kwargs for registry compatibility
        pass

    async def execute(self, workspace: Path, task_description: str, meta: dict[str, Any]) -> bool:
        """
        Execute quality checks.

        Returns True if quality passes, False if it fails.
        """
        stage = meta.get("stage", "M5_AUDIT")
        logger.info("CheckerLabor executing stage: %s", stage)

        try:
            # Read content to check
            content_file = workspace / "render" / "content.md"
            if content_file.exists():
                content = content_file.read_text(encoding="utf-8")
            else:
                # Try src directory
                src_files = list((workspace / "src").glob("*.md"))
                content = "\n".join(f.read_text() for f in src_files if f.exists())

            # Run basic quality checks
            passed = self._check_quality(content, meta)

            if passed:
                logger.info("CheckerLabor: quality passed")
            else:
                logger.warning("CheckerLabor: quality failed")

            return passed

        except Exception:
            logger.exception("CheckerLabor exception")
            return False

    def _check_quality(self, content: str, meta: dict[str, Any]) -> bool:
        """Run basic quality checks."""
        # Check minimum length
        if len(content) < 100:
            logger.warning("Content too short: %d chars", len(content))
            return False

        # Check for placeholder text
        placeholders = ["TODO", "FIXME", "XXX", "待完成", "待修复"]
        for p in placeholders:
            if p in content:
                logger.warning("Found placeholder: %s", p)
                return False

        # Check audit_score if provided
        audit_score = meta.get("audit_score")
        if audit_score is not None and audit_score < 0.8:
            logger.warning("Audit score too low: %f", audit_score)
            return False

        return True
