"""Batch_Runner — Scalable Autonomous Business Engine batch pipeline executor.

Enables launching N pipeline instances in parallel with:
- asyncio.Semaphore for concurrency control
- Isolated UUID workspaces per artifact
- PipelineEngine state machine per instance
- ROI-based resource allocation
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    """Result of a batch pipeline execution."""

    workflow_id: str
    success: bool
    stages_completed: int
    error: str | None = None


class BatchRunner:
    """
    Launch N pipeline instances in parallel with concurrency control.

    Usage:
        runner = BatchRunner(base_dir="/artifacts", max_concurrency=10)
        results = await runner.launch(pipeline_configs)
    """

    def __init__(self, base_dir: str, max_concurrency: int = 10) -> None:
        self.base_dir = Path(base_dir)
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def launch(self, configs: list[Any]) -> list[BatchResult]:
        """
        Launch N pipeline instances in parallel.

        Args:
            configs: List of PipelineConfig objects to execute

        Returns:
            List of BatchResult, one per config
        """
        tasks = []
        for i, config in enumerate(configs):
            task_id = f"{config.name}-{uuid.uuid4().hex[:8]}"
            task = self._run_with_semaphore(task_id, config)
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to BatchResult errors
        batch_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                batch_results.append(
                    BatchResult(
                        workflow_id=f"{configs[i].name}-{i}",
                        success=False,
                        stages_completed=0,
                        error=str(result),
                    )
                )
            else:
                batch_results.append(result)

        return batch_results

    async def _run_with_semaphore(self, task_id: str, config: Any) -> BatchResult:
        """Execute a single pipeline with semaphore control."""
        async with self._semaphore:
            return await self._execute_single(task_id, config)

    async def _execute_single(self, task_id: str, config: Any) -> BatchResult:
        """
        Execute a single pipeline instance.

        Override this method to customize execution logic.
        """
        try:
            # Import here to avoid circular imports
            from hermes_os.pipeline_engine_v2 import BatchArtifactMeta, PipelineEngine

            # Create artifact workspace
            artifact_dir = self.base_dir / task_id
            artifact_dir.mkdir(parents=True, exist_ok=True)

            # Create initial meta
            meta = BatchArtifactMeta(
                artifact_id=task_id,
                title=config.name,
                target_audience="",
                style="formal",
                current_stage="M1_OUTLINE",
                status="in_progress",
            )

            # Execute pipeline
            engine = PipelineEngine(
                config=config,
                meta=meta,
                base_dir=str(self.base_dir),
            )

            stages_completed = 0
            for step in config.steps:
                result = await engine.execute_current_stage()
                if not result.passed:
                    return BatchResult(
                        workflow_id=task_id,
                        success=False,
                        stages_completed=stages_completed,
                        error=result.errors[0] if result.errors else "Stage failed",
                    )
                stages_completed += 1

            return BatchResult(
                workflow_id=task_id,
                success=True,
                stages_completed=stages_completed,
            )

        except Exception as e:
            logger.exception("Batch execution failed for %s", task_id)
            return BatchResult(
                workflow_id=task_id,
                success=False,
                stages_completed=0,
                error=str(e),
            )
