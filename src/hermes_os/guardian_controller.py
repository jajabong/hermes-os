"""GuardianController — execution robustness via checkpointing, attribution, and escalation.

Guardian Pattern (The Checkpoint Engine + Error Attribution Engine + Human-in-the-Loop Gate):

  1. Checkpoint Engine:
     - Save/restore pipeline state in checkpoint JSON files
     - rescue_in_progress_tasks() scans all checkpoints on startup
     - State machine: PENDING → IN_PROGRESS → COMPLETED/FAILED

  2. Error Attribution Engine:
     - Classify errors as:
       * TRANSIENT_ERROR (503, Timeout, Connection) → Exponential Backoff Retry
       * LOGICAL_ERROR (Syntax, Format, Hallucination) → DiagnosticAgent + Prompt Correction
       * HANG_ERROR (timeout_sec exceeded) → Force kill + escalate
     - Maps error patterns to retry policies

  3. Human-in-the-Loop Gate:
     - When retries exhausted or HANG_ERROR → send EscalationCard
     - Scene protection: zip current workspace and attach to card
     - Decision: ESCALATE / RETRY / CORRECT

Usage:
    guardian = GuardianController(config=GuardianConfig(...))
    await guardian.save_checkpoint(cp)
    result = await guardian.handle_invocation_error(task_id, error_message)
    if result.decision == EscalationDecision.ESCALATE:
        await guardian.escalate(task_id)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from hermes_os.conclusion_extractor import ConclusionExtractor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error Type Classification
# ---------------------------------------------------------------------------

class ErrorType(str, Enum):
    """Error classification based on root cause."""
    TRANSIENT = "transient"    # Network/API — retry with backoff
    LOGICAL = "logical"        # Model/Instruction — need correction
    HANG = "hang"              # Timeout — escalate immediately
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Escalation Decision
# ---------------------------------------------------------------------------

class EscalationDecision(str, Enum):
    """Decision from GuardianController after error analysis."""
    RETRY = "retry"           # Exponential backoff retry
    CORRECT = "correct"       # Prompt correction needed
    ESCALATE = "escalate"     # Human intervention required
    ABORT = "abort"           # Give up, mark failed


# ---------------------------------------------------------------------------
# Error Attribution
# ---------------------------------------------------------------------------

# Module-level pattern lists (built lazily, shared across all instances)
_TRANSIENT_PATTERNS: list = []
_LOGICAL_PATTERNS: list = []
_HANG_PATTERNS: list = []
_PATTERNS_BUILT: bool = False


def _ensure_patterns() -> None:
    global _TRANSIENT_PATTERNS, _LOGICAL_PATTERNS, _HANG_PATTERNS, _PATTERNS_BUILT
    if _PATTERNS_BUILT:
        return
    _TRANSIENT_PATTERNS = [
        re.compile(r"(?i)(connection.*refused|connection.*reset|connection.*timeout)"),
        re.compile(r"(?i)(503|502|504|500)\s+service\s+unavailable"),
        re.compile(r"(?i)(timeout|timed?\s*out|operation\s*timed?\s*out)"),
        re.compile(r"(?i)(network.*error|dns.*fail|host.*unreachable)"),
        re.compile(r"(?i)(rate\s*limit|too\s*many\s*requests)"),
        re.compile(r"(?i)(temporarily\s*unavailable|try\s*again\s*later)"),
    ]
    _LOGICAL_PATTERNS = [
        re.compile(r"(?i)(syntaxerror|syntax\s*error)"),
        re.compile(r"(?i)(indentationerror)"),
        re.compile(r"(?i)(typeerror|valueerror|attributeerror)"),
        re.compile(r"(?i)(hallucin|malform|invalid\s+json|output\s*validation)"),
        re.compile(r"(?i)(model\s*error|llm\s*error|api\s*error.*\d{3})"),
        re.compile(r"(?i)(instruction.*drift|prompt.*mismatch)"),
        re.compile(r"(?i)(unhandled\s*exception|unexpected\s*error)"),
    ]
    _HANG_PATTERNS = [
        re.compile(r"(?i)(execution\s*hang|process\s*hung|hanging)"),
        re.compile(r"(?i)(exceeded\s*timeout_sec)"),
        re.compile(r"(?i)(deadlock|livelock)"),
        re.compile(r"(?i)(stuck\s*in\s*loop|infinite\s*loop)"),
    ]
    _PATTERNS_BUILT = True


@dataclass
class ErrorAttribution:
    """Result of error classification."""
    error_type: ErrorType
    retry_policy: str  # "exponential_backoff" | "prompt_correction" | "escalate"
    suggested_action: str
    diagnosis: str = ""

    @classmethod
    def classify(cls, error_message: str) -> ErrorAttribution:
        """Classify an error message into ErrorType using pattern matching."""
        _ensure_patterns()
        msg = error_message.strip()

        # Check HANG first (highest priority — needs immediate escalation)
        for pattern in _HANG_PATTERNS:
            if pattern.search(msg):
                return cls(
                    error_type=ErrorType.HANG,
                    retry_policy="escalate",
                    suggested_action="Execution exceeded timeout — force kill process and escalate to human",
                    diagnosis="HANG_ERROR: Process exceeded maximum execution time",
                )

        # Check TRANSIENT (network/API errors)
        for pattern in _TRANSIENT_PATTERNS:
            if pattern.search(msg):
                return cls(
                    error_type=ErrorType.TRANSIENT,
                    retry_policy="exponential_backoff",
                    suggested_action="Retry with exponential backoff (2^n seconds)",
                    diagnosis="TRANSIENT_ERROR: External service temporarily unavailable",
                )

        # Check LOGICAL (model/instruction errors)
        for pattern in _LOGICAL_PATTERNS:
            if pattern.search(msg):
                return cls(
                    error_type=ErrorType.LOGICAL,
                    retry_policy="prompt_correction",
                    suggested_action="Analyze error with DiagnosticAgent, generate correction prompt",
                    diagnosis="LOGICAL_ERROR: Task logic or instruction issue requires correction",
                )

        # Default to UNKNOWN
        return cls(
            error_type=ErrorType.UNKNOWN,
            retry_policy="escalate",
            suggested_action="Unknown error type — escalate to human for diagnosis",
            diagnosis=f"UNKNOWN_ERROR: Could not classify error: {msg[:100]}",
        )


# ---------------------------------------------------------------------------
# Checkpoint Data
# ---------------------------------------------------------------------------

@dataclass
class CheckpointData:
    """State snapshot for a task/pipeline execution."""
    task_id: str
    stage: str
    status: str  # "pending" | "in_progress" | "completed" | "failed"
    completed_stages: list[str] = field(default_factory=list)
    artifact_uri: str = ""
    retry_count: int = 0
    error_context: str = ""
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "stage": self.stage,
            "status": self.status,
            "completed_stages": self.completed_stages,
            "artifact_uri": self.artifact_uri,
            "retry_count": self.retry_count,
            "error_context": self.error_context,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CheckpointData:
        return cls(
            task_id=data["task_id"],
            stage=data.get("stage", ""),
            status=data.get("status", "pending"),
            completed_stages=data.get("completed_stages", []),
            artifact_uri=data.get("artifact_uri", ""),
            retry_count=data.get("retry_count", 0),
            error_context=data.get("error_context", ""),
            updated_at=data.get("updated_at", datetime.now(UTC).isoformat()),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Guardian Configuration
# ---------------------------------------------------------------------------

@dataclass
class GuardianConfig:
    """Configuration for GuardianController behavior."""
    checkpoint_dir: Path | str = Path.home() / ".hermes" / "checkpoints"
    max_retries: int = 3
    base_backoff_seconds: float = 2.0
    escalation_threshold: int = 3  # retries before escalation
    hang_threshold_seconds: int = 600  # 10 minutes
    orphaned_threshold_minutes: int = 30  # consider IN_PROGRESS stale after 30 min
    jarvis_factory: Any = None  # callable that returns JarvisInterface


# ---------------------------------------------------------------------------
# GuardianController
# ---------------------------------------------------------------------------

@dataclass
class HandleResult:
    """Result of handle_invocation_error."""
    decision: EscalationDecision
    attribution: ErrorAttribution
    backoff_seconds: float = 0.0
    correction_prompt: str = ""
    message: str = ""


class GuardianController:
    """
    Guardian of execution robustness — wraps task execution with:

    1. Checkpoint Engine — save/restore pipeline state
    2. Error Attribution Engine — classify errors into TRANSIENT/LOGICAL/HANG
    3. Human-in-the-Loop Gate — escalate when retries exhausted

    Usage:
        guardian = GuardianController(config=GuardianConfig(...))

        # Before executing a stage
        await guardian.save_checkpoint(CheckpointData(task_id="t1", stage="write", status="in_progress"))

        # After an error
        result = await guardian.handle_invocation_error("t1", "Connection refused")
        if result.decision == EscalationDecision.RETRY:
            await asyncio.sleep(result.backoff_seconds)
            await execute_stage_again()
        elif result.decision == EscalationDecision.ESCALATE:
            await guardian.escalate("t1")
    """

    def __init__(self, config: GuardianConfig | None = None) -> None:
        self._config = config or GuardianConfig()
        self._checkpoint_dir = Path(self._config.checkpoint_dir)
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._jarvis: Any = None
        self._extractor = ConclusionExtractor()
        self._logger = logging.getLogger("hermes_os.guardian")

    @property
    def jarvis(self) -> Any:
        if self._jarvis is None:
            if self._config.jarvis_factory:
                self._jarvis = self._config.jarvis_factory()
            else:
                from hermes_os.jarvis_interface import JarvisInterface
                self._jarvis = JarvisInterface()
        return self._jarvis

    # -------------------------------------------------------------------------
    # Checkpoint Engine
    # -------------------------------------------------------------------------

    def _checkpoint_path(self, task_id: str) -> Path:
        return self._checkpoint_dir / f"{task_id}.json"

    async def save_checkpoint(self, checkpoint: CheckpointData) -> None:
        """Save checkpoint state to disk. Preserves existing updated_at."""
        path = self._checkpoint_path(checkpoint.task_id)
        path.write_text(json.dumps(checkpoint.to_dict(), ensure_ascii=False, indent=2), "utf-8")

    async def load_checkpoint(self, task_id: str) -> CheckpointData | None:
        """Load checkpoint from disk."""
        path = self._checkpoint_path(task_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text("utf-8"))
            return CheckpointData.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None

    async def delete_checkpoint(self, task_id: str) -> None:
        """Delete checkpoint after task completion."""
        path = self._checkpoint_path(task_id)
        if path.exists():
            path.unlink()

    async def rescue_in_progress_tasks(self) -> list[CheckpointData]:
        """
        Scan all checkpoints on startup. Return tasks that were IN_PROGRESS
        and have an old timestamp (indicating a crash/interrupt).
        Caller should re-queue these tasks.
        """
        rescued: list[CheckpointData] = []
        cutoff = datetime.now(UTC) - timedelta(minutes=self._config.orphaned_threshold_minutes)

        for path in self._checkpoint_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text("utf-8"))
                cp = CheckpointData.from_dict(data)

                if cp.status == "in_progress":
                    updated = datetime.fromisoformat(cp.updated_at)
                    if updated < cutoff:
                        self._logger.warning(
                            "Guardian: rescued stale checkpoint task_id=%s stage=%s updated=%s",
                            cp.task_id, cp.stage, cp.updated_at,
                        )
                        rescued.append(cp)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

        return rescued

    # -------------------------------------------------------------------------
    # Error Attribution Engine
    # -------------------------------------------------------------------------

    async def _classify_error(self, error_message: str) -> ErrorAttribution:
        """Classify error using pattern matching."""
        return ErrorAttribution.classify(error_message)

    async def increment_retry(self, task_id: str) -> None:
        """Increment retry count for a checkpoint."""
        cp = await self.load_checkpoint(task_id)
        if cp is None:
            return
        cp.retry_count += 1
        await self.save_checkpoint(cp)

    async def is_retries_exhausted(self, task_id: str) -> bool:
        """Check if max retries reached."""
        cp = await self.load_checkpoint(task_id)
        if cp is None:
            return True
        return cp.retry_count >= self._config.max_retries

    async def _compute_backoff_delay(self, retry_count: int) -> float:
        """Compute exponential backoff delay: base * 2^retry_count."""
        return self._config.base_backoff_seconds * (2 ** retry_count)

    # -------------------------------------------------------------------------
    # Escalation Decision
    # -------------------------------------------------------------------------

    async def _make_escalation_decision(
        self, checkpoint: CheckpointData
    ) -> EscalationDecision:
        """Decide whether to RETRY, CORRECT, or ESCALATE based on attribution."""
        if checkpoint.error_context:
            attr = await self._classify_error(checkpoint.error_context)

            if attr.error_type == ErrorType.HANG:
                return EscalationDecision.ESCALATE

            if checkpoint.retry_count >= self._config.max_retries:
                return EscalationDecision.ESCALATE

            if attr.error_type == ErrorType.LOGICAL:
                return EscalationDecision.CORRECT

            if attr.error_type == ErrorType.TRANSIENT:
                return EscalationDecision.RETRY

        # No error context yet — default to retry if under threshold
        if checkpoint.retry_count < self._config.max_retries:
            return EscalationDecision.RETRY

        return EscalationDecision.ESCALATE

    # -------------------------------------------------------------------------
    # Main entry: handle_invocation_error
    # -------------------------------------------------------------------------

    async def handle_invocation_error(
        self,
        task_id: str,
        error_message: str,
    ) -> HandleResult:
        """
        Main entry point after an invocation error.

        1. Load checkpoint
        2. Classify error (TRANSIENT / LOGICAL / HANG)
        3. Update error_context and retry_count
        4. Make escalation decision
        5. Return HandleResult with decision + backoff delay
        """
        try:
            cp = await self.load_checkpoint(task_id)
            if cp is None:
                # No checkpoint — create one with error
                cp = CheckpointData(
                    task_id=task_id,
                    stage="unknown",
                    status="in_progress",
                    error_context=error_message,
                )

            # Update error context
            cp.error_context = error_message

            # Classify the error
            attr = await self._classify_error(error_message)

            # Make decision
            decision = await self._make_escalation_decision(cp)

            backoff_seconds = 0.0
            correction_prompt = ""

            if decision == EscalationDecision.RETRY:
                await self.increment_retry(task_id)
                # Reload to get updated retry_count
                cp = await self.load_checkpoint(task_id) or cp
                backoff_seconds = await self._compute_backoff_delay(cp.retry_count)
                message = f"RETRY with {backoff_seconds:.0f}s backoff"

            elif decision == EscalationDecision.CORRECT:
                correction_prompt = await self._generate_correction_prompt(cp, attr)
                message = "CORRECT: prompt correction needed"

            elif decision == EscalationDecision.ESCALATE:
                cp.status = "failed"
                await self.save_checkpoint(cp)
                message = "ESCALATE: human intervention required"

            else:
                message = "ABORT: giving up"

            self._logger.info(
                "Guardian: task_id=%s error_type=%s decision=%s retry_count=%d",
                task_id, attr.error_type.value, decision.value, cp.retry_count,
            )

            return HandleResult(
                decision=decision,
                attribution=attr,
                backoff_seconds=backoff_seconds,
                correction_prompt=correction_prompt,
                message=message,
            )
        except Exception as e:
            self._logger.error(
                "Guardian: unexpected error in handle_invocation_error for task_id=%s: %s",
                task_id, str(e),
            )
            return HandleResult(
                decision=EscalationDecision.ESCALATE,
                attribution=ErrorAttribution(
                    error_type=ErrorType.UNKNOWN,
                    diagnosis="Unexpected error during error handling",
                    suggestion="Manual intervention required due to internal error",
                ),
                backoff_seconds=0.0,
                correction_prompt="",
                message=f"INTERNAL ERROR: {str(e)[:200]}",
            )

    # -------------------------------------------------------------------------
    # DiagnosticAgent — generate correction prompt for LOGICAL errors
    # -------------------------------------------------------------------------

    async def _generate_correction_prompt(
        self, checkpoint: CheckpointData, attr: ErrorAttribution
    ) -> str:
        """Generate a corrected prompt for LOGICAL_ERRORs."""
        template = f"""You encountered an error while executing a task.

## Task Stage: {checkpoint.stage}
## Previous Error: {checkpoint.error_context}

## Diagnosis from Guardian:
{attr.diagnosis}

## Your previous approach:
- Task was working on stage: {checkpoint.stage}
- Completed stages so far: {', '.join(checkpoint.completed_stages) or 'none'}

## Required Correction:
Based on the error diagnosis above, please:
1. Identify what went wrong in the previous attempt
2. Generate a corrected version of the original task
3. Include specific fixes for the error: {checkpoint.error_context}

Generate a corrected task description that avoids the previous error.
"""
        return template

    # -------------------------------------------------------------------------
    # Human-in-the-Loop Escalation
    # -------------------------------------------------------------------------

    async def escalate(self, task_id: str) -> None:
        """
        Send escalation card to user with scene protection (zip snapshot).

        This is called when:
        - Retries exhausted (max_retries reached)
        - HANG_ERROR detected
        - UNKNOWN error type with no clear path
        """
        cp = await self.load_checkpoint(task_id)
        if cp is None:
            self._logger.error("Guardian: cannot escalate — no checkpoint for task_id=%s", task_id)
            return

        # Build diagnosis summary
        attr = await self._classify_error(cp.error_context) if cp.error_context else None

        # Prepare content
        completed = ", ".join(cp.completed_stages) or "none"
        content = f"""## Guardian 诊断报告

**任务 ID**: {task_id}
**故障阶段**: {cp.stage}
**已完成阶段**: {completed}
**重试次数**: {cp.retry_count}/{self._config.max_retries}

### 归因分析
**错误类型**: {attr.error_type.value if attr else 'unknown'}
**诊断**: {attr.diagnosis if attr else '无错误上下文'}
**建议动作**: {attr.suggested_action if attr else '未知'}

### 当前状态
**错误信息**: {cp.error_context or '无'}
**Artifact URI**: {cp.artifact_uri or '未生成'}

### 场景保护
如需接管，Guardian 已将当前工作目录打包为 ZIP 附件。
点击下方按钮可下载并继续调试。
"""

        title = f"Guardian: 任务 {task_id} 需要人工接管"

        try:
            await self.jarvis.send_card_with_nl(
                user_id=cp.metadata.get("user_id", ""),
                title=title,
                content=content,
                actions=[
                    {"text": "接管调试", "value": "takeover", "type": "primary"},
                    {"text": "重试此阶段", "value": "retry_stage", "type": "secondary"},
                    {"text": "中止并打包", "value": "abort", "type": "danger"},
                ],
                nl_summary=f"Guardian escalation: task {task_id} needs human intervention",
                task_id=task_id,
            )
        except Exception as e:
            self._logger.error("Guardian: failed to send escalation card: %s", e)

    # -------------------------------------------------------------------------
    # Scene Protection (zip artifact workspace)
    # -------------------------------------------------------------------------

    async def protect_scene(
        self, task_id: str, workspace_path: Path | str
    ) -> Path | None:
        """
        Create a ZIP snapshot of the current artifact workspace.
        Returns path to the ZIP file.
        """
        workspace = Path(workspace_path)
        if not workspace.exists():
            return None

        zip_name = f"{task_id}_scene_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.zip"
        zip_path = self._checkpoint_dir / zip_name

        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_path in workspace.rglob("*"):
                    if file_path.is_file():
                        zf.write(file_path, file_path.relative_to(workspace.parent))
            self._logger.info("Guardian: scene protected at %s", zip_path)
            return zip_path
        except Exception as e:
            self._logger.error("Guardian: failed to create scene zip: %s", e)
            return None
