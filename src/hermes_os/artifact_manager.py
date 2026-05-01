"""ArtifactManager — standardized artifact workspace for pipeline production.

Workspace structure:
  /artifacts/{task_id}/
    ├── src/          (raw inputs)
    ├── render/       (intermediate formats: Markdown)
    ├── delivery/     (final output: PDF/EPUB)
    └── meta.json     (stage, status, artifact_uri, dependency_hash)
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path
from typing import Any

import aiosqlite


class ArtifactStage(IntEnum):
    """Stage of artifact production, ordered for pipeline progression."""
    CREATED = 0
    RESEARCH = 1
    WRITING = 2
    RENDERING = 3
    DELIVERING = 4
    COMPLETED = 5
    FAILED = 6


class ArtifactStatus:
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ArtifactMeta:
    """Metadata for an artifact workspace."""
    task_id: str
    stage: ArtifactStage = ArtifactStage.CREATED
    status: ArtifactStatus = ArtifactStatus.IN_PROGRESS
    artifact_uri: str = ""
    dependency_hash: str = ""
    parent_artifact_id: str = ""  # Links to upstream artifact (Artifact Handover Protocol)
    last_updated: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    user_id: str = ""
    
    # --- Commercial Intuition Layer (ROI Metrics) ---
    liabilities: dict[str, Any] = field(default_factory=lambda: {
        "token_usage": 0,
        "api_cost_usd": 0.0,
        "compute_hours": 0.0,
        "human_intervention_count": 0
    })
    equity: dict[str, Any] = field(default_factory=lambda: {
        "realized_revenue_usd": 0.0,
        "valuation_usd": 0.0,
        "market_traction": {"sales_count": 0, "citations": 0}
    })
    roi: float = 0.0
    
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactMeta:
        stage = data.get("stage", ArtifactStage.CREATED)
        if isinstance(stage, str):
            stage = ArtifactStage[stage.upper()]
        elif isinstance(stage, int):
            stage = ArtifactStage(stage)
        return cls(
            task_id=data["task_id"],
            stage=stage,
            status=data.get("status", ArtifactStatus.IN_PROGRESS),
            artifact_uri=data.get("artifact_uri", ""),
            dependency_hash=data.get("dependency_hash", ""),
            parent_artifact_id=data.get("parent_artifact_id", ""),
            last_updated=data.get("last_updated", datetime.now(UTC).isoformat()),
            user_id=data.get("user_id", ""),
            liabilities=data.get("liabilities", {
                "token_usage": 0, "api_cost_usd": 0.0, "compute_hours": 0.0, "human_intervention_count": 0
            }),
            equity=data.get("equity", {
                "realized_revenue_usd": 0.0, "valuation_usd": 0.0, "market_traction": {}
            }),
            roi=data.get("roi", 0.0),
            metadata=data.get("metadata", {}),
        )

    def calculate_roi(self) -> float:
        """Calculate Return on Investment."""
        cost = self.liabilities.get("api_cost_usd", 0.0)
        revenue = self.equity.get("realized_revenue_usd", 0.0)
        if cost <= 0:
            return 0.0
        self.roi = (revenue - cost) / cost
        return self.roi

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "stage": self.stage.value,
            "status": str(self.status),
            "artifact_uri": self.artifact_uri,
            "dependency_hash": self.dependency_hash,
            "parent_artifact_id": self.parent_artifact_id,
            "last_updated": self.last_updated,
            "user_id": self.user_id,
            "liabilities": self.liabilities,
            "equity": self.equity,
            "roi": self.calculate_roi(),
            "metadata": self.metadata,
        }


@dataclass
class ArtifactWorkspace:
    """A single artifact workspace with structured directories."""
    task_id: str
    user_id: str
    root_path: Path
    src_path: Path
    render_path: Path
    delivery_path: Path
    meta: ArtifactMeta

    @property
    def artifact_id(self) -> str:
        """Unique artifact ID derived from task_id and dependency_hash."""
        return f"{self.task_id}-{self.meta.dependency_hash[:8]}"


class ArtifactManager:
    """Manages artifact workspaces for pipeline production.

    Each workspace is a directory with:
      src/       — raw inputs (source documents, notes)
      render/    — intermediate formats (Markdown)
      delivery/  — final output (PDF, EPUB)
      meta.json  — current stage and status
    """

    def __init__(self, base_dir: Path | str) -> None:
        self._base_dir = Path(base_dir)

    # ---------------------------------------------------------------------------
    # Workspace lifecycle
    # ---------------------------------------------------------------------------

    async def create_workspace(self, task_id: str, user_id: str = "", context: dict[str, Any] | None = None) -> ArtifactWorkspace:
        """Create a new artifact workspace for a task.

        Args:
            task_id: Unique identifier for the task
            user_id: User who owns this artifact
            context: Optional context dict used to compute dependency_hash
        """
        root = self._base_dir / task_id
        root.mkdir(parents=True, exist_ok=True)
        (root / "src").mkdir(exist_ok=True)
        (root / "render").mkdir(exist_ok=True)
        (root / "delivery").mkdir(exist_ok=True)

        # Compute dependency_hash from context for incremental re-runs
        dep_hash = self._compute_dependency_hash(context or {})

        meta = ArtifactMeta(
            task_id=task_id,
            user_id=user_id,
            stage=ArtifactStage.CREATED,
            status=ArtifactStatus.IN_PROGRESS,
            dependency_hash=dep_hash,
        )
        self._write_meta(root, meta)

        return ArtifactWorkspace(
            task_id=task_id,
            user_id=user_id,
            root_path=root,
            src_path=root / "src",
            render_path=root / "render",
            delivery_path=root / "delivery",
            meta=meta,
        )

    def _compute_dependency_hash(self, context: dict[str, Any]) -> str:
        """Compute a hash of the pipeline context for dependency tracking.

        This hash is used to determine if a pipeline needs to re-run
        based on changed inputs or configuration.
        """
        # Include relevant context keys that affect pipeline output
        relevant_keys = ["topic", "title", "style", "key_thesis", "target_audience"]
        hash_input = {}
        for key in relevant_keys:
            if key in context:
                hash_input[key] = context[key]

        # Sort keys for consistent hashing
        serialized = json.dumps(hash_input, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

    async def load_workspace(self, task_id: str) -> ArtifactWorkspace | None:
        """Load existing workspace from disk."""
        root = self._base_dir / task_id
        meta_path = root / "meta.json"
        if not meta_path.exists():
            return None

        try:
            data = json.loads(meta_path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        try:
            meta = ArtifactMeta.from_dict(data)
        except (KeyError, ValueError, TypeError):
            return None

        user_id = data.get("user_id", "")
        return ArtifactWorkspace(
            task_id=task_id,
            user_id=user_id,
            root_path=root,
            src_path=root / "src",
            render_path=root / "render",
            delivery_path=root / "delivery",
            meta=meta,
        )

    # ---------------------------------------------------------------------------
    # Stage / status updates
    # ---------------------------------------------------------------------------

    async def update_stage(
        self,
        task_id: str,
        stage: ArtifactStage,
        status: ArtifactStatus | None = None,
    ) -> ArtifactWorkspace | None:
        """Update workspace stage and optionally status."""
        ws = await self.load_workspace(task_id)
        if ws is None:
            return None

        ws.meta.stage = stage
        if status is not None:
            ws.meta.status = status
        ws.meta.last_updated = datetime.now(UTC).isoformat()

        self._write_meta(ws.root_path, ws.meta)
        return ws

    async def update_status(self, task_id: str, status: ArtifactStatus) -> ArtifactWorkspace | None:
        """Update workspace status."""
        ws = await self.load_workspace(task_id)
        if ws is None:
            return None
        ws.meta.status = status
        ws.meta.last_updated = datetime.now(UTC).isoformat()
        self._write_meta(ws.root_path, ws.meta)
        return ws

    # ---------------------------------------------------------------------------
    # Artifact URI
    # ---------------------------------------------------------------------------

    async def set_artifact_uri(self, task_id: str, uri: str) -> ArtifactWorkspace | None:
        """Set the final artifact URI after delivery."""
        ws = await self.load_workspace(task_id)
        if ws is None:
            return None
        ws.meta.artifact_uri = uri
        ws.meta.last_updated = datetime.now(UTC).isoformat()
        self._write_meta(ws.root_path, ws.meta)
        return ws

    async def set_parent_artifact_id(self, task_id: str, parent_artifact_id: str) -> ArtifactWorkspace | None:
        """Set the parent artifact ID for artifact lineage tracking (Artifact Handover Protocol)."""
        ws = await self.load_workspace(task_id)
        if ws is None:
            return None
        ws.meta.parent_artifact_id = parent_artifact_id
        ws.meta.last_updated = datetime.now(UTC).isoformat()
        self._write_meta(ws.root_path, ws.meta)
        return ws

    async def register_child_artifact(self, parent_task_id: str, child_task_id: str) -> None:
        """Register a child artifact under a parent artifact for dependency tracking."""
        ws = await self.load_workspace(parent_task_id)
        if ws is None:
            return
        children: list[str] = ws.meta.metadata.get("child_artifacts", [])
        if child_task_id not in children:
            children.append(child_task_id)
        ws.meta.metadata["child_artifacts"] = children
        ws.meta.last_updated = datetime.now(UTC).isoformat()
        self._write_meta(ws.root_path, ws.meta)

    async def get_child_artifacts(self, task_id: str) -> list[str]:
        """Get list of child artifact IDs for a given artifact."""
        ws = await self.load_workspace(task_id)
        if ws is None:
            return []
        return ws.meta.metadata.get("child_artifacts", [])

    async def get_artifact_lineage(self, task_id: str) -> list[ArtifactWorkspace]:
        """Get full ancestor chain from root to immediate parent of this artifact.

        Returns list from oldest ancestor to immediate parent.
        """
        lineage: list[ArtifactWorkspace] = []
        visited: set[str] = set()
        current_id: str | None = task_id

        while current_id and current_id not in visited:
            visited.add(current_id)
            ws = await self.load_workspace(current_id)
            if ws is None:
                break
            if ws.meta.parent_artifact_id:
                parent_id = ws.meta.parent_artifact_id
                parent_ws = await self.load_workspace(parent_id)
                if parent_ws:
                    lineage.append(parent_ws)
                current_id = parent_id  # Continue to parent in next iteration
            else:
                # Root reached — no more ancestors
                break

        # Return in chronological order (root first)
        return list(reversed(lineage))

    async def get_artifact_tree(self, task_id: str) -> dict[str, Any]:
        """Get full dependency subtree starting from this artifact as root.

        Returns a dict with task_id, stage, and children list recursively.
        """
        ws = await self.load_workspace(task_id)
        if ws is None:
            return {}

        children_ids = ws.meta.metadata.get("child_artifacts", [])
        children_tree: list[dict[str, Any]] = []
        for child_id in children_ids:
            child_tree = await self.get_artifact_tree(child_id)
            if child_tree:
                children_tree.append(child_tree)

        return {
            "task_id": task_id,
            "stage": ws.meta.stage.value,
            "children": children_tree,
        }

    # ---------------------------------------------------------------------------
    # File writing helpers
    # ---------------------------------------------------------------------------

    async def write_src(
        self, task_id: str, filename: str, content: str
    ) -> Path:
        """Write a source file into the workspace src/ directory."""
        ws = await self.load_workspace(task_id)
        if ws is None:
            raise ValueError(f"Workspace {task_id} does not exist")
        path = ws.src_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, "utf-8")
        return path

    async def write_render(
        self, task_id: str, filename: str, content: str
    ) -> Path:
        """Write a render file into the workspace render/ directory."""
        ws = await self.load_workspace(task_id)
        if ws is None:
            raise ValueError(f"Workspace {task_id} does not exist")
        path = ws.render_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, "utf-8")
        return path

    async def write_delivery(
        self, task_id: str, filename: str, content: bytes
    ) -> Path:
        """Write a delivery file into the workspace delivery/ directory."""
        ws = await self.load_workspace(task_id)
        if ws is None:
            raise ValueError(f"Workspace {task_id} does not exist")
        path = ws.delivery_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    async def get_portfolio_stats(self, user_id: str) -> dict[str, Any]:
        """Aggregate ROI metrics across all artifacts for a user."""
        total_cost = 0.0
        total_revenue = 0.0
        total_tokens = 0
        artifact_count = 0

        # Scan base directory for all task folders
        try:
            task_dirs = list(self._base_dir.iterdir())
        except FileNotFoundError:
            return {
                "user_id": user_id,
                "artifact_count": 0,
                "total_cost_usd": 0.0,
                "total_revenue_usd": 0.0,
                "total_tokens": 0,
                "portfolio_roi": 0.0,
            }

        for task_dir in task_dirs:
            if not task_dir.is_dir():
                continue

            try:
                ws = await self.load_workspace(task_dir.name)
            except Exception:
                continue

            if ws and ws.user_id == user_id:
                total_cost += ws.meta.liabilities.get("api_cost_usd", 0.0)
                total_revenue += ws.meta.equity.get("realized_revenue_usd", 0.0)
                total_tokens += ws.meta.liabilities.get("token_usage", 0)
                artifact_count += 1

        avg_roi = (total_revenue - total_cost) / total_cost if total_cost > 0 else 0.0

        return {
            "user_id": user_id,
            "artifact_count": artifact_count,
            "total_cost_usd": total_cost,
            "total_revenue_usd": total_revenue,
            "total_tokens": total_tokens,
            "portfolio_roi": avg_roi,
        }

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

    def _write_meta(self, root: Path, meta: ArtifactMeta) -> None:
        """Write meta.json to workspace root atomically."""
        meta_path = root / "meta.json"
        temp_path = root / "meta.json.tmp"
        try:
            temp_path.write_text(
                json.dumps(meta.to_dict(), ensure_ascii=False, indent=2), "utf-8"
            )
            temp_path.replace(meta_path)
        except OSError:
            # Fallback to direct write if atomic replace fails
            meta_path.write_text(
                json.dumps(meta.to_dict(), ensure_ascii=False, indent=2), "utf-8"
            )
