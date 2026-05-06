"""PipelineTaskRunner — PipelineEngine ↔ TaskScheduler integration.

Bridges TaskScheduler's BackgroundWorker with PipelineEngine:

1. Task.metadata carries {pipeline_name, stage_name, pipeline_task_id}
2. PipelineTaskRunner.execute_pipeline_task() loads YAML, executes stage, checkpoints via Guardian
3. MilestoneNotifier sends JARVIS cards on stage completion

Integration point:
    # In BackgroundWorker.execute_task():
    if PipelineTaskRunner.is_pipeline_task(task.metadata):
        ws = await runner.execute_pipeline_task(task.task_id, task.metadata, context)
    else:
        # normal invoke() path...
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_os.guardian_controller import (
    CheckpointData,
    EscalationDecision,
    GuardianConfig,
    GuardianController,
)
from hermes_os.notification_manager import NotificationEvent, NotificationManager
from hermes_os.pipeline_engine import (
    PipelineDefinition,
    PipelineEngine,
    PipelineStage,
    PipelineWorkspace,
)

logger = logging.getLogger("hermes_os.pipeline_runner")


# ---------------------------------------------------------------------------
# Pipeline Task Context
# ---------------------------------------------------------------------------


@dataclass
class PipelineTaskContext:
    """Context extracted from Task.metadata for pipeline execution."""

    pipeline_task_id: str
    stage_name: str
    pipeline_name: str = ""
    pipeline_path: str = ""  # Path to YAML file
    user_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_metadata(cls, meta: dict[str, Any]) -> PipelineTaskContext | None:
        """Extract pipeline context from task metadata."""
        pipeline_name = meta.get("pipeline_name", "")
        stage_name = meta.get("stage_name", "")
        pipeline_task_id = meta.get("pipeline_task_id", "")

        if not pipeline_name or not stage_name:
            return None

        return cls(
            pipeline_task_id=pipeline_task_id,
            stage_name=stage_name,
            pipeline_name=pipeline_name,
            pipeline_path=meta.get("pipeline_path", ""),
            user_id=meta.get("user_id", ""),
            metadata=meta,
        )


# ---------------------------------------------------------------------------
# Stage Milestone
# ---------------------------------------------------------------------------


@dataclass
class StageMilestone:
    """Record of a completed (or failed) pipeline stage."""

    task_id: str
    stage_name: str
    status: str  # "completed" | "failed"
    output_artifact: str = ""
    error: str = ""
    duration_seconds: float = 0.0
    total_stages: int = 0
    completed_stages: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "stage_name": self.stage_name,
            "status": self.status,
            "output_artifact": self.output_artifact,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "total_stages": self.total_stages,
            "completed_stages": self.completed_stages,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# MilestoneNotifier
# ---------------------------------------------------------------------------


class MilestoneNotifier:
    """Sends JARVIS milestone cards when pipeline stages complete."""

    def __init__(self, notification_manager: NotificationManager | None = None) -> None:
        self._nm = notification_manager

    async def notify_stage(self, milestone: StageMilestone, user_id: str) -> None:
        """Send a milestone notification card."""
        if self._nm is None:
            return

        event = (
            NotificationEvent.COMPLETED
            if milestone.status == "completed"
            else NotificationEvent.FAILED
        )

        # Build progress string
        progress_str = ""
        if milestone.total_stages > 0:
            progress_str = f" ({milestone.completed_stages}/{milestone.total_stages} stages)"

        title = f"📋 {milestone.stage_name}{progress_str}"
        if milestone.status == "completed":
            icon = "✅"
            title = f"{icon} {milestone.stage_name} 完成"
        else:
            icon = "❌"
            title = f"{icon} {milestone.stage_name} 失败"

        content = f"**阶段**: {milestone.stage_name}\n"
        if milestone.output_artifact:
            content += f"**产出**: `{milestone.output_artifact}`\n"
        if milestone.duration_seconds > 0:
            mins = int(milestone.duration_seconds // 60)
            secs = int(milestone.duration_seconds % 60)
            content += f"**耗时**: {mins}分{secs}秒\n"
        if milestone.total_stages > 0:
            content += f"**进度**: {milestone.completed_stages}/{milestone.total_stages} 阶段完成\n"
        if milestone.error:
            content += f"\n**错误**: {milestone.error}"

        try:
            await self._nm.send_notification(
                user_id=user_id,
                task_title=title,
                task_id=milestone.task_id,
                event=event,
                result=content,
                error=milestone.error if milestone.status == "failed" else "",
            )
        except Exception:
            logger.warning("MilestoneNotifier: failed to send notification to %s", user_id)


# ---------------------------------------------------------------------------
# PipelineTaskRunner
# ---------------------------------------------------------------------------


class PipelineTaskRunner:
    """
    Executes pipeline stages as Tasks within TaskScheduler.

    Usage (in BackgroundWorker.execute_task):
        if PipelineTaskRunner.is_pipeline_task(task.metadata):
            runner = PipelineTaskRunner(artifact_base=..., notification_manager=nm)
            ws = await runner.execute_pipeline_task(task.task_id, task.metadata, context)
        else:
            # normal invoke() path...
    """

    def __init__(
        self,
        artifact_base: Path | str,
        notification_manager: NotificationManager | None = None,
        guardian: GuardianController | None = None,
        storage: Any = None,
    ) -> None:
        self._artifact_base = Path(artifact_base)
        self._artifact_base.mkdir(parents=True, exist_ok=True)
        self._notification_manager = notification_manager
        self._guardian = guardian
        self._storage = storage
        self._notifier = MilestoneNotifier(notification_manager)
        self._pipeline_cache: dict[str, PipelineDefinition] = {}

    @staticmethod
    def is_pipeline_task(metadata: dict[str, Any]) -> bool:
        """Check if task metadata describes a pipeline stage task."""
        return bool(metadata.get("pipeline_name")) and bool(metadata.get("stage_name"))

    # -------------------------------------------------------------------------
    # Pipeline discovery
    # -------------------------------------------------------------------------

    def _discover_pipeline_path(self, pipeline_name: str) -> Path | None:
        """Find pipeline YAML file by name in standard search directories."""
        for yaml_file in self._discover_all_pipeline_files():
            try:
                import yaml

                data = yaml.safe_load(yaml_file.read_text("utf-8"))
                if data.get("name") == pipeline_name:
                    return yaml_file
            except Exception:
                continue
        return None

    def _discover_all_pipeline_files(self) -> list[Path]:
        """Discover all pipeline YAML files from standard search directories."""
        search_dirs = [
            Path("pipelines"),
            Path.home() / ".hermes" / "pipelines",
            Path(__file__).parent.parent.parent / "pipelines",
        ]
        files = []
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            # Support both .yaml and .yml extensions
            for pattern in ["*.yaml", "*.yml"]:
                files.extend(search_dir.glob(pattern))
        return files

    def list_pipelines(self) -> list[dict[str, str]]:
        """List all available pipelines with their names and descriptions.

        Returns:
            List of dicts with 'name', 'description', 'path' keys.
            Deduplicated by absolute path.
        """
        import yaml

        seen: set[str] = set()
        pipelines = []
        for yaml_file in self._discover_all_pipeline_files():
            abs_path = str(yaml_file.resolve())
            if abs_path in seen:
                continue
            seen.add(abs_path)
            try:
                data = yaml.safe_load(yaml_file.read_text("utf-8"))
                pipelines.append(
                    {
                        "name": data.get("name", "Unnamed"),
                        "description": data.get("description", ""),
                        "path": abs_path,
                        "version": data.get("version", "1.0"),
                        "stages": len(data.get("stages", [])),
                    }
                )
            except Exception:
                continue
        return pipelines

    def _load_pipeline(
        self, pipeline_name: str, pipeline_path: str = ""
    ) -> PipelineDefinition | None:
        """Load pipeline definition (with caching)."""
        cache_key = pipeline_name
        if cache_key in self._pipeline_cache:
            return self._pipeline_cache[cache_key]

        path_str = pipeline_path
        if not path_str:
            path = self._discover_pipeline_path(pipeline_name)
        else:
            path = Path(path_str)

        if path is None or not path.exists():
            logger.error("PipelineTaskRunner: pipeline not found: %s", pipeline_name)
            return None

        try:
            pd = PipelineDefinition.from_yaml(path)
            self._pipeline_cache[cache_key] = pd
            return pd
        except Exception as e:
            logger.error("PipelineTaskRunner: failed to load pipeline %s: %s", pipeline_name, e)
            return None

    def _find_stage(self, definition: PipelineDefinition, stage_name: str) -> PipelineStage | None:
        """Find stage by name in pipeline definition."""
        for stage in definition.stages:
            if stage.name == stage_name:
                return stage
        return None

    # -------------------------------------------------------------------------
    # Pipeline Progress API
    # -------------------------------------------------------------------------

    async def get_pipeline_progress(
        self,
        pipeline_task_id: str,
        pipeline_name: str,
        pipeline_path: str = "",
    ) -> dict[str, Any] | None:
        """Get execution progress for a pipeline.

        Returns a dict with:
        - task_id: pipeline task ID
        - pipeline_name: name of the pipeline
        - total_stages: total number of stages
        - completed_stages: list of completed stage names
        - failed_stages: list of failed stage names
        - current_stage: name of currently executing stage (or None)
        - progress_percentage: 0-100 float
        - stage_details: list of {name, status, duration_seconds} for each stage
        """
        # Load pipeline definition
        definition = self._load_pipeline(pipeline_name, pipeline_path)
        if definition is None:
            return None

        # Load workspace
        engine = PipelineEngine(artifact_base=self._artifact_base)
        ws = await engine.load_pipeline_workspace(pipeline_task_id)
        if ws is None:
            return None

        total = len(definition.stages)
        completed = len(ws.completed_stages)
        progress = (completed / total * 100) if total > 0 else 0.0

        # Build stage details
        stage_details = []
        for stage in definition.stages:
            status = ws.stage_statuses.get(stage.name, "pending")
            duration = 0.0  # Duration not tracked per-stage in current impl
            stage_details.append(
                {
                    "name": stage.name,
                    "status": status,
                    "duration_seconds": duration,
                }
            )

        return {
            "task_id": pipeline_task_id,
            "pipeline_name": pipeline_name,
            "total_stages": total,
            "completed_stages": ws.completed_stages,
            "failed_stages": ws.failed_stages,
            "current_stage": ws.current_stage,
            "progress_percentage": round(progress, 1),
            "stage_details": stage_details,
        }

    # -------------------------------------------------------------------------
    # Checkpoint helpers (Guardian integration)
    # -------------------------------------------------------------------------

    def _get_guardian(self) -> GuardianController:
        if self._guardian is None:
            self._guardian = GuardianController(
                config=GuardianConfig(
                    checkpoint_dir=str(Path.home() / ".hermes" / "checkpoints"),
                    max_retries=3,
                )
            )
        return self._guardian

    # -------------------------------------------------------------------------
    # Main entry: execute_pipeline_task
    # -------------------------------------------------------------------------

    async def execute_pipeline_task(
        self,
        task_id: str,
        metadata: dict[str, Any],
        context: dict[str, Any],
    ) -> PipelineWorkspace | None:
        """
        Execute a single pipeline stage as a Task.

        Returns the PipelineWorkspace after stage execution.
        Sends milestone notification on completion.
        """
        ctx = PipelineTaskContext.from_metadata(metadata)
        if ctx is None:
            logger.error("PipelineTaskRunner: invalid pipeline metadata for task %s", task_id)
            return None

        # Load pipeline definition
        definition = self._load_pipeline(ctx.pipeline_name, ctx.pipeline_path)
        if definition is None:
            return None

        # Find the target stage
        stage = self._find_stage(definition, ctx.stage_name)
        if stage is None:
            logger.error(
                "PipelineTaskRunner: stage '%s' not found in pipeline '%s'",
                ctx.stage_name,
                ctx.pipeline_name,
            )
            return None

        # Create or load workspace
        ws = await self._get_or_create_workspace(ctx.pipeline_task_id, definition.name)
        if ws is None:
            return None

        # Check if stage already completed (checkpoint-based skip)
        if ctx.stage_name in ws.completed_stages:
            logger.info(
                "PipelineTaskRunner: stage '%s' already completed, skipping",
                ctx.stage_name,
            )
            return ws

        # Save Guardian checkpoint before execution
        guardian = self._get_guardian()
        await guardian.save_checkpoint(
            CheckpointData(
                task_id=task_id,
                stage=ctx.stage_name,
                status="in_progress",
                completed_stages=ws.completed_stages,
                metadata={"user_id": ctx.user_id, "pipeline_task_id": ctx.pipeline_task_id},
            )
        )

        # Execute the stage
        import time

        start = time.monotonic()
        engine = PipelineEngine(artifact_base=self._artifact_base)
        result = await engine.execute_stage(ctx.pipeline_task_id, stage, context)
        duration = time.monotonic() - start

        # Update workspace
        ws = await engine.load_pipeline_workspace(ctx.pipeline_task_id)
        if ws is None:
            return None

        # Build milestone
        milestone = StageMilestone(
            task_id=task_id,
            stage_name=ctx.stage_name,
            status="completed" if result.success else "failed",
            output_artifact=result.output_artifact or stage.output_artifact or "",
            error=result.error or "",
            duration_seconds=duration,
            total_stages=len(definition.stages),
            completed_stages=len(ws.completed_stages),
        )

        # Send milestone notification
        if ctx.user_id:
            await self._notifier.notify_stage(milestone, ctx.user_id)

        # Persist milestone to database (Guardian integration for checkpoint resume)
        if self._storage is not None:
            await self._storage.save_milestone(
                task_id=task_id,
                stage_name=ctx.stage_name,
                status=milestone.status,
                output_artifact=milestone.output_artifact,
                error=milestone.error,
                duration_seconds=milestone.duration_seconds,
                total_stages=milestone.total_stages,
                completed_stages=milestone.completed_stages,
                pipeline_task_id=ctx.pipeline_task_id,
                user_id=ctx.user_id,
            )

        # Handle Guardian error path
        if not result.success:
            handle_result = await guardian.handle_invocation_error(
                task_id, result.error or "Unknown error"
            )
            if handle_result.decision == EscalationDecision.ESCALATE:
                await guardian.escalate(task_id)

        return ws

    async def _get_or_create_workspace(
        self, pipeline_task_id: str, pipeline_name: str
    ) -> PipelineWorkspace | None:
        """Get existing workspace or create new one."""
        engine = PipelineEngine(artifact_base=self._artifact_base)
        ws = await engine.load_pipeline_workspace(pipeline_task_id)
        if ws is None:
            ws = await engine.create_pipeline_workspace(pipeline_task_id, pipeline_name)
        return ws
