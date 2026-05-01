"""UniversalPipelineLoader — unified entry point for all 5 Pipelines.

Metaprogramming approach:
1. LaborRegistry: single source of truth for all Labor handlers
2. UniversalPipelineLoader: loads Pipeline.yaml, executes stages via Registry
3. 5 Pipeline definitions as constants (can be loaded from YAML files)

The key insight: don't write 5 pipeline classes.
Write ONE engine that loads different YAML configs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml


# ---------------------------------------------------------------------------
# Pipeline Definitions (YAML strings - can be loaded from files)
# ---------------------------------------------------------------------------

PIPELINE_CONTENT_ASSEMBLY = """
name: "Content Assembly Pipeline"
description: "Structured content generation: book, BP, industry report"
version: "1.0"
steps:
  - stage: M1_OUTLINE
    labor: ContentLabor
    task: "Generate structured outline based on goals"
    verify: "check_structure_completeness"
    template: "outline_template.md"
  - stage: M2_RESEARCH
    labor: ResearchLabor
    task: "Retrieve context from GlobalWiki and PrivateWiki"
    verify: "check_evidence_density"
  - stage: M3_DRAFTING
    labor: ContentLabor
    task: "Generate content section by section"
    verify: "check_tone_consistency"
  - stage: M4_RENDERING
    labor: FormatLabor
    task: "Render Markdown to PDF/EPUB"
    verify: "check_rendering_integrity"
  - stage: M5_AUDIT
    labor: CheckerLabor
    task: "Audit logic and semantic flow"
    verify: "check_audit_score"
  - stage: M6_DELIVERY
    labor: FeishuLabor
    task: "Push summary card and artifact download link"
    verify: "check_delivery"
"""

PIPELINE_ENGINEERING = """
name: "Engineering Pipeline"
description: "Code generation, testing, and deployment"
version: "1.0"
steps:
  - stage: M1_SPEC
    labor: CodeLabor
    task: "Generate modification spec with LSP checks"
    verify: "check_spec_completeness"
  - stage: M2_CODING
    labor: CodeLabor
    task: "Write code via Claude Code"
    verify: "check_code_compiles"
  - stage: M3_SELFTEST
    labor: CodeLabor
    task: "Execute test cases automatically"
    verify: "check_tests_pass"
  - stage: M4_LINTING
    labor: CodeLabor
    task: "Validate code style and conventions"
    verify: "check_lint_clean"
  - stage: M5_GITMERGE
    labor: GitHubLabor
    task: "Create PR and merge to main"
    verify: "check_merge_success"
"""

PIPELINE_INTELLIGENCE = """
name: "Intelligence & Analytics Pipeline"
description: "Data fetch, analysis, and insight generation"
version: "1.0"
steps:
  - stage: M1_DATAFETCH
    labor: DataLabor
    task: "Fetch data from GitHub/Feishu/Wiki/Web"
    verify: "check_data_fetched"
  - stage: M2_NORMALIZE
    labor: DataLabor
    task: "Clean and normalize data"
    verify: "check_data_clean"
  - stage: M3_REASONING
    labor: ResearchLabor
    task: "Compute metrics and analyze patterns"
    verify: "check_analysis_complete"
  - stage: M4_VISUALIZE
    labor: DataLabor
    task: "Generate charts and visualizations"
    verify: "check_charts_generated"
  - stage: M5_INSIGHT
    labor: ContentLabor
    task: "Synthesize findings into insights"
    verify: "check_insight_quality"
"""

PIPELINE_DEPLOYMENT = """
name: "Deployment/Release Pipeline"
description: "Deploy to external platforms (Amazon, servers, WeChat)"
version: "1.0"
steps:
  - stage: M1_STATEDAUTH
    labor: BrowserLabor
    task: "Check login state (Session/Cookie)"
    verify: "check_auth_valid"
  - stage: M2_FORMFILLING
    labor: BrowserLabor
    task: "Automate form filling"
    verify: "check_form_filled"
  - stage: M3_UPLOAD
    labor: BrowserLabor
    task: "Upload files to platform"
    verify: "check_upload_success"
  - stage: M4_VERIFICATION
    labor: BrowserLabor
    task: "Verify via UI state/screenshot"
    verify: "check_ui_confirmed"
  - stage: M5_FINALIZE
    labor: ContentLabor
    task: "Record release result"
    verify: "check_release_recorded"
"""

PIPELINE_GOVERNANCE = """
name: "Governance Pipeline"
description: "Knowledge sanitization and promotion"
version: "1.0"
steps:
  - stage: M1_DETECTION
    labor: GovernanceLabor
    task: "Detect new Wiki writes"
    verify: "check_new_content"
  - stage: M2_SANITIZE
    labor: GovernanceLabor
    task: "PII redaction and sanitization"
    verify: "check_pii_removed"
  - stage: M3_PROMOTION
    labor: GovernanceLabor
    task: "Promote to GlobalWiki"
    verify: "check_promoted"
  - stage: M4_SYNC
    labor: GovernanceLabor
    task: "Update all active indexes"
    verify: "check_sync_complete"
"""

PIPELINE_REGISTRY = {
    "content_assembly": PIPELINE_CONTENT_ASSEMBLY,
    "engineering": PIPELINE_ENGINEERING,
    "intelligence": PIPELINE_INTELLIGENCE,
    "deployment": PIPELINE_DEPLOYMENT,
    "governance": PIPELINE_GOVERNANCE,
}


# ---------------------------------------------------------------------------
# Core Classes
# ---------------------------------------------------------------------------

@dataclass
class StageDefinition:
    """Definition of a single pipeline stage."""
    stage: str
    labor: str
    task: str
    verify: str
    template: str | None = None


@dataclass
class PipelineConfig:
    """Configuration for a pipeline."""
    name: str
    description: str
    version: str = "1.0"
    steps: list[StageDefinition] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "PipelineConfig":
        """Parse pipeline from YAML string."""
        data = yaml.safe_load(yaml_str)
        steps = []
        for step_data in data.get("steps", []):
            steps.append(StageDefinition(
                stage=step_data["stage"],
                labor=step_data["labor"],
                task=step_data["task"],
                verify=step_data["verify"],
                template=step_data.get("template"),
            ))
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            steps=steps,
        )


@dataclass
class LaborHandler:
    """A registered Labor handler."""
    name: str
    execute: Callable[..., Any]


@dataclass
class StageResult:
    """Result of executing a single stage."""
    passed: bool
    stage: str
    output: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class VerificationResult:
    """Result of a verification check."""
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PipelineExecutionResult:
    """Result of executing a full pipeline."""
    pipeline_name: str
    artifact_id: str
    success: bool
    stages_completed: int
    stage_results: list[StageResult] = field(default_factory=list)
    error: str | None = None


class PipelineLoadError(Exception):
    """Raised when pipeline loading fails."""
    pass


class LaborRegistry:
    """Single source of truth for all Labor handlers.

    This enables metaprogramming: the pipeline engine doesn't need to know
    which labor does what - it just looks up the handler by name.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, LaborHandler] = {}
        self._register_default_labors()

    def _register_default_labors(self) -> None:
        """Register all 5 pipeline labors with default handlers."""
        self._handlers["ContentLabor"] = LaborHandler(
            name="ContentLabor",
            execute=self._default_content_labor,
        )
        self._handlers["ResearchLabor"] = LaborHandler(
            name="ResearchLabor",
            execute=self._default_research_labor,
        )
        self._handlers["CheckerLabor"] = LaborHandler(
            name="CheckerLabor",
            execute=self._default_checker_labor,
        )
        self._handlers["FormatLabor"] = LaborHandler(
            name="FormatLabor",
            execute=self._default_format_labor,
        )
        self._handlers["FeishuLabor"] = LaborHandler(
            name="FeishuLabor",
            execute=self._default_feishu_labor,
        )
        self._handlers["CodeLabor"] = LaborHandler(
            name="CodeLabor",
            execute=self._default_code_labor,
        )
        self._handlers["GitHubLabor"] = LaborHandler(
            name="GitHubLabor",
            execute=self._default_github_labor,
        )
        self._handlers["BrowserLabor"] = LaborHandler(
            name="BrowserLabor",
            execute=self._default_browser_labor,
        )
        self._handlers["DataLabor"] = LaborHandler(
            name="DataLabor",
            execute=self._default_data_labor,
        )
        self._handlers["GovernanceLabor"] = LaborHandler(
            name="GovernanceLabor",
            execute=self._default_governance_labor,
        )

    async def _default_content_labor(self, context: dict, **kwargs) -> str:
        """Default ContentLabor handler - returns placeholder."""
        return f"[ContentLabor] Generated content for {context.get('artifact_id', 'unknown')}"

    async def _default_research_labor(self, context: dict, **kwargs) -> str:
        """Default ResearchLabor handler - returns placeholder."""
        return f"[ResearchLabor] Research context for {context.get('artifact_id', 'unknown')}"

    async def _default_checker_labor(self, context: dict, **kwargs) -> str:
        """Default CheckerLabor handler - returns placeholder."""
        return f"[CheckerLabor] Checked artifact for {context.get('artifact_id', 'unknown')}"

    async def _default_format_labor(self, context: dict, **kwargs) -> str:
        """Default FormatLabor handler - returns placeholder."""
        return f"[FormatLabor] Formatted artifact for {context.get('artifact_id', 'unknown')}"

    async def _default_feishu_labor(self, context: dict, **kwargs) -> str:
        """Default FeishuLabor handler - returns placeholder."""
        return f"[FeishuLabor] Delivered artifact to {context.get('user_id', 'unknown')}"

    async def _default_code_labor(self, context: dict, **kwargs) -> str:
        """Default CodeLabor handler - returns placeholder."""
        return f"[CodeLabor] Code generated for {context.get('artifact_id', 'unknown')}"

    async def _default_github_labor(self, context: dict, **kwargs) -> str:
        """Default GitHubLabor handler - returns placeholder."""
        return f"[GitHubLabor] GitHub operation for {context.get('artifact_id', 'unknown')}"

    async def _default_browser_labor(self, context: dict, **kwargs) -> str:
        """Default BrowserLabor handler - returns placeholder."""
        return f"[BrowserLabor] Browser automation for {context.get('artifact_id', 'unknown')}"

    async def _default_data_labor(self, context: dict, **kwargs) -> str:
        """Default DataLabor handler - returns placeholder."""
        return f"[DataLabor] Data processed for {context.get('artifact_id', 'unknown')}"

    async def _default_governance_labor(self, context: dict, **kwargs) -> str:
        """Default GovernanceLabor handler - returns placeholder."""
        return f"[GovernanceLabor] Governance applied for {context.get('artifact_id', 'unknown')}"

    def register(self, labor_name: str, handler: LaborHandler) -> None:
        """Register a new labor handler."""
        self._handlers[labor_name] = handler

    def unregister(self, labor_name: str) -> None:
        """Unregister a labor handler."""
        self._handlers.pop(labor_name, None)

    def get(self, labor_name: str) -> LaborHandler | None:
        """Get a labor handler by name."""
        return self._handlers.get(labor_name)


class UniversalPipelineLoader:
    """Unified entry point for all 5 Pipelines.

    Key metaprogramming insight: ONE class loads ALL pipeline YAMLs.
    No need to write 5 pipeline classes.
    """

    def __init__(self) -> None:
        self.registry = LaborRegistry()

    def load(self, yaml_path: str) -> PipelineConfig:
        """Load pipeline from a YAML file."""
        path = Path(yaml_path)
        if not path.exists():
            raise PipelineLoadError(f"Pipeline file not found: {yaml_path}")

        try:
            yaml_content = path.read_text(encoding="utf-8")
            return PipelineConfig.from_yaml(yaml_content)
        except yaml.YAMLError as e:
            raise PipelineLoadError(f"Invalid YAML: {e}")

    def load_pipeline(self, pipeline_name: str) -> PipelineConfig:
        """Load one of the 5 built-in pipelines by name."""
        if pipeline_name not in PIPELINE_REGISTRY:
            raise PipelineLoadError(f"Unknown pipeline: {pipeline_name}. Available: {list(PIPELINE_REGISTRY.keys())}")

        return PipelineConfig.from_yaml(PIPELINE_REGISTRY[pipeline_name])

    async def execute_stage(
        self,
        stage: StageDefinition,
        context: dict,
        base_dir: str,
    ) -> StageResult:
        """Execute a single stage via its registered Labor handler."""
        handler = self.registry.get(stage.labor)
        if handler is None:
            return StageResult(
                passed=False,
                stage=stage.stage,
                errors=[f"Unknown labor: {stage.labor}"],
            )

        try:
            output = await handler.execute(context)
            return StageResult(
                passed=True,
                stage=stage.stage,
                output=output,
            )
        except Exception as e:
            return StageResult(
                passed=False,
                stage=stage.stage,
                errors=[str(e)],
            )

    async def execute_full_pipeline(
        self,
        pipeline_config: PipelineConfig,
        artifact_id: str,
        base_dir: str,
        context: dict | None = None,
    ) -> PipelineExecutionResult:
        """Execute all stages in sequence."""
        stage_results: list[StageResult] = []
        ctx = context or {}
        ctx["artifact_id"] = artifact_id

        for step in pipeline_config.steps:
            result = await self.execute_stage(step, ctx, base_dir)
            stage_results.append(result)
            if not result.passed:
                return PipelineExecutionResult(
                    pipeline_name=pipeline_config.name,
                    artifact_id=artifact_id,
                    success=False,
                    stages_completed=len(stage_results) - 1,
                    stage_results=stage_results,
                    error=f"Stage {step.stage} failed",
                )

        return PipelineExecutionResult(
            pipeline_name=pipeline_config.name,
            artifact_id=artifact_id,
            success=True,
            stages_completed=len(stage_results),
            stage_results=stage_results,
        )
