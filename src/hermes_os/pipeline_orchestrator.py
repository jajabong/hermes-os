"""PipelineOrchestrator — chains multiple pipelines via project.yaml.

Implements the Artifact Handover Protocol and Project Orchestration Layer:
  1. Loads project.yaml defining ordered steps with dependencies
  2. Runs pipelines in dependency order (topological sort)
  3. Sets parent_artifact_id on child pipelines automatically
  4. Supports arbitrary pipeline definitions per step

Usage:
    orch = ProjectOrchestrator(engine=engine, artifact_manager=am)
    await orch.run_project(Path("my-book/project.yaml"))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ProjectStep:
    """A single step in a project pipeline chain."""
    pipeline: str          # e.g. "P3_Intelligence", "P1_Content_Assembly"
    task_id: str          # Unique task ID for this step
    depends_on: list[str] = field(default_factory=list)  # IDs of steps that must run first
    context: dict[str, Any] = field(default_factory=dict)
    input_artifact: str | None = None  # Override for artifact linkage

    def waiting_on(self, completed: set[str]) -> bool:
        """Return True if this step is still waiting on dependencies."""
        return not all(dep in completed for dep in self.depends_on)


@dataclass
class ProjectDefinition:
    """A complete project definition loaded from project.yaml."""
    name: str
    description: str
    version: str
    steps: list[ProjectStep] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path | str) -> "ProjectDefinition":
        """Load project definition from a YAML file."""
        data = yaml.safe_load(Path(path).read_text("utf-8"))
        steps = []
        for s in data.get("steps", []):
            steps.append(
                ProjectStep(
                    pipeline=s.get("pipeline", ""),
                    task_id=s.get("task_id", ""),
                    depends_on=s.get("depends_on", []),
                    context=s.get("context", {}),
                    input_artifact=s.get("input_artifact"),
                )
            )
        return cls(
            name=data.get("name", "Unnamed Project"),
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            steps=steps,
            metadata=data.get("metadata", {}),
        )

    def ordered_steps(self) -> list[ProjectStep]:
        """Return steps sorted by dependency order (topological sort).

        Uses Kahn's algorithm: steps with no unmet dependencies come first.
        """
        remaining = {s.task_id: s for s in self.steps}
        completed: list[ProjectStep] = []
        completed_ids: set[str] = set()

        while remaining:
            # Find steps whose dependencies are all satisfied
            ready = [
                s for s in remaining.values()
                if all(dep in completed_ids for dep in s.depends_on)
            ]
            if not ready:
                # Circular dependency or missing step — bail
                remaining_vals = list(remaining.values())
                completed.extend(remaining_vals)
                break
            for step in ready:
                completed.append(step)
                completed_ids.add(step.task_id)
                del remaining[step.task_id]

        return completed


class ProjectOrchestrator:
    """
    Orchestrates multiple pipelines in dependency order.

    Sets parent_artifact_id automatically when a child pipeline depends
    on a parent pipeline's output (Artifact Handover Protocol).
    """

    def __init__(
        self,
        engine: Any,  # PipelineEngine
        artifact_manager: Any,  # ArtifactManager
    ) -> None:
        self._engine = engine
        self._artifact_manager = artifact_manager

    async def run_project(self, project_path: Path | str) -> dict[str, Any]:
        """
        Run a complete project defined in project.yaml.

        1. Load and topologically sort steps
        2. For each step in order:
           a. Create artifact workspace (with parent_artifact_id if depends_on)
           b. Execute the pipeline
           c. Register child artifact under parent
        3. Return execution summary
        """
        project = ProjectDefinition.from_yaml(project_path)
        results: dict[str, Any] = {}
        completed_ids: set[str] = set()

        for step in project.ordered_steps():
            # Determine parent artifact (last completed step in depends_on chain)
            parent_artifact_id = ""
            if step.depends_on:
                # Use the last completed dependency as parent
                parent_artifact_id = step.depends_on[-1]

            # Build context with input artifact hint
            context = dict(step.context)
            if parent_artifact_id:
                context["parent_artifact_id"] = parent_artifact_id
                context["input_artifact"] = step.input_artifact

            # Create artifact workspace with parent link
            ws = await self._artifact_manager.create_workspace(
                task_id=step.task_id,
                user_id=context.get("user_id", ""),
                context=context,
            )
            if parent_artifact_id:
                await self._artifact_manager.set_parent_artifact_id(
                    step.task_id, parent_artifact_id
                )
                await self._artifact_manager.register_child_artifact(
                    parent_artifact_id, step.task_id
                )

            # Execute pipeline (actual pipeline type resolved from step.pipeline)
            try:
                result = await self._engine.execute_pipeline(
                    task_id=step.task_id,
                    definition=self._build_pipeline_definition(step),
                    context=context,
                )
                results[step.task_id] = {"success": True, "result": result}
            except Exception as e:
                results[step.task_id] = {"success": False, "error": str(e)}

            completed_ids.add(step.task_id)

        return results

    def _build_pipeline_definition(self, step: ProjectStep) -> Any:
        """Build a minimal PipelineDefinition for a step."""
        from hermes_os.pipeline_engine import PipelineDefinition, PipelineStage

        # Map pipeline name to stage sequence
        stages_map: dict[str, list[dict[str, Any]]] = {
            "P3_Intelligence": [
                {"name": "research", "labor_type": "content", "description": "Topic research"},
            ],
            "P1_Content_Assembly": [
                {"name": "outline", "labor_type": "content", "description": "Create outline"},
                {"name": "write", "labor_type": "content", "description": "Write content"},
                {"name": "review", "labor_type": "review", "description": "Review content"},
            ],
            "P4_Delivery": [
                {"name": "format", "labor_type": "format", "description": "Format for delivery"},
                {"name": "deliver", "labor_type": "browser", "description": "Deploy/publish"},
            ],
        }

        stage_defs = stages_map.get(step.pipeline, [])
        stages = []
        for i, sd in enumerate(stage_defs):
            stages.append(
                PipelineStage(
                    name=sd["name"],
                    sequence=i,
                    labor_type=sd["labor_type"],
                    description=sd["description"],
                )
            )

        return PipelineDefinition(
            name=step.pipeline,
            description=f"Step: {step.task_id}",
            version="1.0",
            stages=stages,
        )
