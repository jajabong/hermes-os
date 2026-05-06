"""Portfolio_View — Unified view of 100+ assets across domains.

Manages the "Business Cube" portfolio:
- Domain axis: publication, patent, short_drama
- Process axis: stages (M1-M6)
- Value axis: ROI, revenue, status

Usage:
    view = PortfolioView(base_dir="/artifacts")
    view.add_artifact("book-001", "My Book", "publication", "in_progress")
    patents = view.filter_by_domain("patent")
    summary = view.aggregate_status()
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PortfolioArtifact:
    """A single artifact in the portfolio."""

    artifact_id: str
    title: str
    domain: str  # "publication", "patent", "short_drama"
    status: str  # "in_progress", "completed", "failed"
    current_stage: str = ""
    roi: float = 0.0
    revenue: float = 0.0
    cost: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "title": self.title,
            "domain": self.domain,
            "status": self.status,
            "current_stage": self.current_stage,
            "roi": self.roi,
            "revenue": self.revenue,
            "cost": self.cost,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


@dataclass
class PortfolioSummary:
    """Aggregated portfolio statistics."""

    total: int
    completed: int
    in_progress: int
    failed: int
    total_revenue: float
    total_cost: float
    overall_roi: float
    domains: dict[str, int]


class PortfolioView:
    """
    Unified view of all business empire assets.

    Usage:
        view = PortfolioView(base_dir="/artifacts/portfolio")
        view.add_artifact("book-001", "My Book", "publication", "completed")
        summary = view.aggregate_status()
    """

    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._portfolio_file = self.base_dir / "portfolio.json"
        self._artifacts: dict[str, PortfolioArtifact] = {}
        self._load()

    def _load(self) -> None:
        """Load portfolio from disk."""
        if self._portfolio_file.exists():
            try:
                data = json.loads(self._portfolio_file.read_text(encoding="utf-8"))
                for artifact_data in data.get("artifacts", []):
                    artifact = PortfolioArtifact(**artifact_data)
                    self._artifacts[artifact.artifact_id] = artifact
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("Failed to load portfolio: %s", e)

    def _save(self) -> None:
        """Persist portfolio to disk."""
        data = {
            "artifacts": [a.to_dict() for a in self._artifacts.values()],
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self._portfolio_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_artifact(
        self,
        artifact_id: str,
        title: str,
        domain: str,
        status: str = "in_progress",
        current_stage: str = "",
        roi: float = 0.0,
        revenue: float = 0.0,
        cost: float = 0.0,
        **metadata: Any,
    ) -> PortfolioArtifact:
        """
        Add an artifact to the portfolio.

        Args:
            artifact_id: Unique identifier
            title: Human-readable title
            domain: One of "publication", "patent", "short_drama"
            status: One of "in_progress", "completed", "failed"
            current_stage: Current pipeline stage
            roi: Return on investment
            revenue: Total revenue
            cost: Total cost
            **metadata: Additional metadata
        """
        artifact = PortfolioArtifact(
            artifact_id=artifact_id,
            title=title,
            domain=domain,
            status=status,
            current_stage=current_stage,
            roi=roi,
            revenue=revenue,
            cost=cost,
            metadata=metadata,
        )
        self._artifacts[artifact_id] = artifact
        self._save()
        logger.info("Added artifact %s to portfolio (domain: %s)", artifact_id, domain)
        return artifact

    def get_artifact(self, artifact_id: str) -> PortfolioArtifact | None:
        """Get an artifact by ID."""
        return self._artifacts.get(artifact_id)

    def update_artifact(self, artifact_id: str, **updates: Any) -> bool:
        """
        Update an artifact's fields.

        Args:
            artifact_id: ID of artifact to update
            **updates: Fields to update

        Returns:
            True if updated, False if artifact not found
        """
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            return False

        for key, value in updates.items():
            if hasattr(artifact, key):
                setattr(artifact, key, value)
        artifact.updated_at = datetime.now(UTC).isoformat()
        self._save()
        return True

    def remove_artifact(self, artifact_id: str) -> bool:
        """Remove an artifact from portfolio."""
        if artifact_id in self._artifacts:
            del self._artifacts[artifact_id]
            self._save()
            return True
        return False

    def filter_by_domain(self, domain: str) -> list[PortfolioArtifact]:
        """Filter artifacts by domain."""
        return [a for a in self._artifacts.values() if a.domain == domain]

    def filter_by_status(self, status: str) -> list[PortfolioArtifact]:
        """Filter artifacts by status."""
        return [a for a in self._artifacts.values() if a.status == status]

    def filter_by_stage(self, stage: str) -> list[PortfolioArtifact]:
        """Filter artifacts by current pipeline stage."""
        return [a for a in self._artifacts.values() if a.current_stage == stage]

    def list_domains(self) -> list[str]:
        """List all domains in portfolio."""
        return list(set(a.domain for a in self._artifacts.values()))

    def list_all(self) -> list[PortfolioArtifact]:
        """List all artifacts."""
        return list(self._artifacts.values())

    def aggregate_status(self) -> PortfolioSummary:
        """
        Aggregate portfolio status across all artifacts.

        Returns:
            PortfolioSummary with totals and domain breakdown
        """
        artifacts = list(self._artifacts.values())
        total = len(artifacts)
        completed = sum(1 for a in artifacts if a.status == "completed")
        in_progress = sum(1 for a in artifacts if a.status == "in_progress")
        failed = sum(1 for a in artifacts if a.status == "failed")

        total_revenue = sum(a.revenue for a in artifacts)
        total_cost = sum(a.cost for a in artifacts)
        overall_roi = total_revenue / total_cost if total_cost > 0 else 0.0

        # Count by domain
        domains: dict[str, int] = {}
        for a in artifacts:
            domains[a.domain] = domains.get(a.domain, 0) + 1

        return PortfolioSummary(
            total=total,
            completed=completed,
            in_progress=in_progress,
            failed=failed,
            total_revenue=total_revenue,
            total_cost=total_cost,
            overall_roi=overall_roi,
            domains=domains,
        )

    def get_top_roi(self, n: int = 10) -> list[PortfolioArtifact]:
        """Get top N artifacts by ROI."""
        return sorted(
            [a for a in self._artifacts.values() if a.roi > 0],
            key=lambda a: a.roi,
            reverse=True,
        )[:n]

    def get_domain_summary(self, domain: str) -> dict[str, Any]:
        """Get summary for a specific domain."""
        domain_artifacts = self.filter_by_domain(domain)
        if not domain_artifacts:
            return {}

        total = len(domain_artifacts)
        completed = sum(1 for a in domain_artifacts if a.status == "completed")
        total_revenue = sum(a.revenue for a in domain_artifacts)
        total_cost = sum(a.cost for a in domain_artifacts)
        avg_roi = sum(a.roi for a in domain_artifacts) / total if total > 0 else 0

        return {
            "domain": domain,
            "total": total,
            "completed": completed,
            "in_progress": total - completed,
            "total_revenue": total_revenue,
            "total_cost": total_cost,
            "avg_roi": avg_roi,
        }
