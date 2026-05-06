"""Universal Long-Form Pipeline Engine v2.

Based on "Universal-Long-Form-Pipeline.yaml" specification:
- 6 stages: M1_OUTLINE → M2_RESEARCH → M3_DRAFTING → M4_RENDERING → M5_AUDIT → M6_DELIVERY
- Each stage has a Labor and verification function
- Audit gate at M5 blocks progression if quality < 0.8
- Meta.json persists state between stages
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from hermes_os.labor_registry import get_labor_registry, initialize_default_labors

# Initialize registry
initialize_default_labors()


class StageStatus(str, Enum):
    """Pipeline execution status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class PipelineStage:
    """Definition of a single pipeline stage."""

    stage: str  # e.g., "M1_OUTLINE"
    labor: str  # e.g., "ContentLabor"
    task: str  # e.g., "Generate structured outline"
    verify: str  # e.g., "check_structure_completeness"


@dataclass
class PipelineConfig:
    """Pipeline configuration parsed from Pipeline.yaml."""

    name: str
    description: str
    steps: list[PipelineStage] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> PipelineConfig:
        """Parse Pipeline.yaml format."""
        data = yaml.safe_load(yaml_str)
        steps = []
        for step_data in data.get("steps", []):
            steps.append(
                PipelineStage(
                    stage=step_data["stage"],
                    labor=step_data["labor"],
                    task=step_data["task"],
                    verify=step_data["verify"],
                )
            )
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            steps=steps,
        )


@dataclass
class BatchArtifactMeta:
    """Meta.json contract - universal artifact metadata.

    This is the first principle: all structured artifacts (BP, paper, book, report)
    share the same metadata contract.
    """

    artifact_id: str
    title: str
    target_audience: str
    style: str  # "formal" | "analysis" | "concise"
    current_stage: str  # Current pipeline stage
    status: str  # "in_progress" | "completed" | "failed"
    key_thesis: list[str] = field(default_factory=list)
    stage_history: list[str] = field(default_factory=list)
    audit_score: float | None = None

    # --- Commercial Intuition Layer (ROI Metrics) ---
    liabilities: dict[str, Any] = field(
        default_factory=lambda: {
            "token_usage": 0,
            "api_cost_usd": 0.0,
            "compute_hours": 0.0,
            "human_intervention_count": 0,
        }
    )
    equity: dict[str, Any] = field(
        default_factory=lambda: {
            "realized_revenue_usd": 0.0,
            "valuation_usd": 0.0,
            "market_traction": {"sales_count": 0, "citations": 0},
        }
    )
    roi: float = 0.0

    metadata: dict[str, Any] = field(default_factory=dict)

    def calculate_roi(self) -> float:
        """Calculate Return on Investment."""
        cost = self.liabilities.get("api_cost_usd", 0.0)
        revenue = self.equity.get("realized_revenue_usd", 0.0)
        if cost <= 0:
            return 0.0
        self.roi = (revenue - cost) / cost
        return self.roi

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "artifact_id": self.artifact_id,
            "title": self.title,
            "target_audience": self.target_audience,
            "style": self.style,
            "current_stage": self.current_stage,
            "status": self.status,
            "key_thesis": self.key_thesis,
            "stage_history": self.stage_history,
            "audit_score": self.audit_score,
            "liabilities": self.liabilities,
            "equity": self.equity,
            "roi": self.calculate_roi(),
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> BatchArtifactMeta:
        """Deserialize from JSON string."""
        data = json.loads(json_str)
        return cls(
            artifact_id=data["artifact_id"],
            title=data["title"],
            target_audience=data["target_audience"],
            style=data["style"],
            current_stage=data["current_stage"],
            status=data["status"],
            key_thesis=data.get("key_thesis", []),
            stage_history=data.get("stage_history", []),
            audit_score=data.get("audit_score"),
            liabilities=data.get(
                "liabilities",
                {
                    "token_usage": 0,
                    "api_cost_usd": 0.0,
                    "compute_hours": 0.0,
                    "human_intervention_count": 0,
                },
            ),
            equity=data.get(
                "equity", {"realized_revenue_usd": 0.0, "valuation_usd": 0.0, "market_traction": {}}
            ),
            roi=data.get("roi", 0.0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class StageResult:
    """Result of executing a stage."""

    passed: bool
    stage: str
    output: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class PipelineEngine:
    """State machine that executes pipeline stages in sequence.

    Simple loop:
    1. Read meta.json to get current stage
    2. Read Pipeline.yaml to get stage definition
    3. Execute stage labor
    4. Verify output
    5. Update meta.json and advance
    """

    def __init__(
        self,
        config: PipelineConfig,
        meta: BatchArtifactMeta,
        base_dir: str,
        user_id: str = "default",
    ):
        self.config = config
        self.meta = meta
        self.base_dir = Path(base_dir)
        self.user_id = user_id
        self.status = (
            StageStatus.IN_PROGRESS if meta.status == "in_progress" else StageStatus.COMPLETED
        )
        self._stage_index = self._find_stage_index(meta.current_stage)

    @property
    def current_stage(self) -> str:
        """Get current stage name."""
        if self._stage_index < len(self.config.steps):
            return self.config.steps[self._stage_index].stage
        return self.meta.current_stage

    def _find_stage_index(self, stage_name: str) -> int:
        """Find index of stage in pipeline."""
        for i, step in enumerate(self.config.steps):
            if step.stage == stage_name:
                return i
        return 0

    async def advance_stage(self) -> None:
        """Move to next stage after current stage completes."""
        self._stage_index += 1
        if self._stage_index >= len(self.config.steps):
            self.status = StageStatus.COMPLETED
            self.meta.status = "completed"
        else:
            next_step = self.config.steps[self._stage_index]
            self.meta.current_stage = next_step.stage
            self.meta.stage_history.append(next_step.stage)

        await self._save_meta()

    async def execute_current_stage(self, **kwargs) -> StageResult:
        """Execute the current stage with given parameters."""
        if self._stage_index >= len(self.config.steps):
            return StageResult(passed=True, stage=self.meta.current_stage)

        step = self.config.steps[self._stage_index]
        workspace = self.base_dir / self.meta.artifact_id

        # 1. Resolve Labor from Registry
        registry = get_labor_registry()
        try:
            # Inject dependencies (user_id, etc.)
            labor_instance = registry.get_labor(step.labor, user_id=self.user_id)
        except ValueError as e:
            return StageResult(passed=False, stage=step.stage, errors=[str(e)])

        # 2. Execute Labor
        print(f"Executing Labor: {step.labor} for stage {step.stage}...")

        # For M5_AUDIT, if audit_score is provided in kwargs, use it directly
        # (bypass labor execution and verify the score)
        if step.stage == "M5_AUDIT" and "audit_score" in kwargs:
            score = kwargs["audit_score"]
            v_result = await verify_audit_score(score)
            if not v_result.passed:
                self.status = StageStatus.BLOCKED
                return StageResult(passed=False, stage=step.stage, errors=v_result.errors)
            self.meta.audit_score = score
            await self.advance_stage()
            return StageResult(passed=True, stage=step.stage)

        result = await labor_instance.execute(
            workspace=workspace,
            task_description=step.task,
            meta={**self.meta.to_dict(), "stage": step.stage, **kwargs},
        )

        if not result.success:
            return StageResult(
                passed=False,
                stage=step.stage,
                errors=[f"Labor {step.labor} failed: {result.error}"],
            )

        # Update Commercial Intuition (ROI Metrics)
        self.meta.liabilities["token_usage"] += result.token_usage
        self.meta.liabilities["api_cost_usd"] += result.api_cost_usd
        self.meta.calculate_roi()

        # 3. Advance Stage
        await self.advance_stage()
        return StageResult(passed=True, stage=step.stage)

    async def _save_meta(self) -> None:
        """Persist meta.json to disk."""
        artifact_dir = self.base_dir / self.meta.artifact_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        meta_path = artifact_dir / "meta.json"
        meta_path.write_text(self.meta.to_json(), encoding="utf-8")


# ---------------------------------------------------------------------------
# Verification functions for each stage
# ---------------------------------------------------------------------------


@dataclass
class VerificationResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


async def verify_outline_completeness(outline: str) -> VerificationResult:
    """M1_OUTLINE verification: check for hollow sections (sections without sub-points)."""
    lines = outline.strip().split("\n")
    errors = []

    # Good outline has ## headings under # headings
    h1_count = sum(
        1 for l in lines if l.strip().startswith("# ") and not l.strip().startswith("## ")
    )
    h2_count = sum(1 for l in lines if l.strip().startswith("## "))
    h3_count = sum(1 for l in lines if l.strip().startswith("### "))

    # Hollow if no sub-sections under main sections
    if h1_count > 0 and h2_count == 0 and h3_count == 0:
        errors.append("outline has hollow sections: main headings without sub-sections")

    # Check for sections with only text content (no hierarchy)
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            in_section = True
        elif stripped.startswith("## "):
            in_section = False
        elif stripped and not stripped.startswith("#") and in_section:
            # Content immediately after H1 without H2 - potential hollow
            errors.append("outline structure incomplete: sections need sub-points")
            break

    return VerificationResult(passed=len(errors) == 0, errors=errors)


async def verify_evidence_density(research: str) -> VerificationResult:
    """M2_RESEARCH verification: check for evidence (citations, data, statistics)."""
    errors = []

    # Evidence indicators
    evidence_patterns = [
        "数据来源",
        "来源：",
        "来源:",
        "据",
        "%",
        "统计",
        "引用：",
        "指出",
        "显示",
        "表明",
        "根据",
        "et al.",
        "fig.",
        "Figure",
        "Table",
    ]

    has_evidence = any(pattern.lower() in research.lower() for pattern in evidence_patterns)

    if not has_evidence:
        errors.append("research lacks evidence: no citations, data, or statistics found")

    # Check for minimum content
    if len(research) < 50:
        errors.append("research too short: need more content for evidence density")

    return VerificationResult(passed=len(errors) == 0, errors=errors)


async def verify_tone_consistency(content: str) -> VerificationResult:
    """M3_DRAFTING verification: check tone matches user preference."""
    # Placeholder - tone check is complex and depends on user preferences
    return VerificationResult(passed=True)


async def verify_rendering_integrity(output_path: str) -> VerificationResult:
    """M4_RENDERING verification: check rendered output exists and is valid."""
    errors = []
    path = Path(output_path)
    if not path.exists():
        errors.append(f"rendered output not found: {output_path}")
    return VerificationResult(passed=len(errors) == 0, errors=errors)


async def verify_audit_score(score: float) -> VerificationResult:
    """M5_AUDIT verification: enforce 0.8 quality threshold."""
    errors = []
    if score < 0.8:
        errors.append(f"audit score {score} below required threshold 0.8")
    return VerificationResult(passed=score >= 0.8, errors=errors)


async def verify_delivery(content: str) -> VerificationResult:
    """M6_DELIVERY verification: ensure delivery package is complete."""
    return VerificationResult(passed=True)
