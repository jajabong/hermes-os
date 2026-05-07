"""GovernanceLabor — Governance Pipeline knowledge sanitization and promotion.

Implements Governance Pipeline stages:
- M1_DETECTION: Detect new Wiki writes
- M2_SANITIZE: PII redaction and sanitization
- M3_PROMOTION: Promote to GlobalWiki
- M4_SYNC: Update all active indexes

Used by: Governance Pipeline
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from hermes_os.labor_registry import LaborResult

logger = logging.getLogger(__name__)


class GovernanceLabor:
    """Labor unit for governance and knowledge management tasks."""

    def __init__(self, **kwargs) -> None:
        pass

    async def execute(self, workspace: Path, task_description: str, meta: dict[str, Any]) -> LaborResult:
        """
        Execute governance task.

        Stage-specific behavior:
        - M1_DETECTION: Detect new Wiki writes
        - M2_SANITIZE: PII redaction and sanitization
        - M3_PROMOTION: Promote to GlobalWiki
        - M4_SYNC: Update all active indexes
        """
        stage = meta.get("stage", "M1_DETECTION")

        if stage == "M1_DETECTION":
            return await self._execute_m1_detection(workspace, task_description, meta)
        elif stage == "M2_SANITIZE":
            return await self._execute_m2_sanitize(workspace, task_description, meta)
        elif stage == "M3_PROMOTION":
            return await self._execute_m3_promotion(workspace, task_description, meta)
        elif stage == "M4_SYNC":
            return await self._execute_m4_sync(workspace, task_description, meta)
        else:
            logger.warning("GovernanceLabor: unknown stage %s", stage)
            return LaborResult(
                success=False,
                output="",
                token_usage=0,
                error=f"Unknown stage: {stage}",
            )

    async def _execute_m1_detection(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> LaborResult:
        """M1_DETECTION: Detect new Wiki writes."""
        wiki_dir = workspace / "wiki" if workspace else Path("wiki")
        wiki_dir.mkdir(parents=True, exist_ok=True)

        logger.info("GovernanceLabor M1_DETECTION: scanning for new content")

        try:
            # Scan for new/unprocessed wiki entries
            # In production, would check against last sync timestamp
            entries = list(wiki_dir.glob("*.md"))[:10]  # limit

            detection_result = {
                "new_entries": len(entries),
                "entries": [e.name for e in entries],
                "scanned_at": meta.get("timestamp", "now"),
            }

            # Save detection record
            record_file = wiki_dir / "detection_record.json"
            record_file.write_text(
                json.dumps(detection_result, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            return LaborResult(
                success=True,
                output=f"M1_DETECTION: detected {len(entries)} new entries",
                token_usage=0,
            )

        except Exception as e:
            logger.exception("M1_DETECTION failed")
            return LaborResult(
                success=False,
                output="",
                token_usage=0,
                error=str(e),
            )

    async def _execute_m2_sanitize(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> LaborResult:
        """M2_SANITIZE: PII redaction and sanitization."""
        wiki_dir = workspace / "wiki"
        if not wiki_dir.exists():
            wiki_dir = workspace / "src" / "wiki"
            wiki_dir.mkdir(parents=True, exist_ok=True)

        logger.info("GovernanceLabor M2_SANITIZE: redacting PII")

        try:
            # Find content to sanitize
            md_files = list(wiki_dir.glob("*.md"))
            sanitized_count = 0

            for md_file in md_files:
                content = md_file.read_text(encoding="utf-8")
                sanitized = self._redact_pii(content)

                # Write sanitized version
                sanitized_file = wiki_dir / f"sanitized_{md_file.name}"
                sanitized_file.write_text(sanitized, encoding="utf-8")
                sanitized_count += 1

            logger.info("M2_SANITIZE: sanitized %d files", sanitized_count)
            if sanitized_count > 0:
                return LaborResult(
                    success=True,
                    output=f"M2_SANITIZE: sanitized {sanitized_count} files",
                    token_usage=0,
                )
            else:
                return LaborResult(
                    success=False,
                    output="No files found to sanitize",
                    token_usage=0,
                    error="No .md files found in wiki directory",
                )

        except Exception as e:
            logger.exception("M2_SANITIZE failed")
            return LaborResult(
                success=False,
                output="",
                token_usage=0,
                error=str(e),
            )

    async def _execute_m3_promotion(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> LaborResult:
        """M3_PROMOTION: Promote to GlobalWiki."""
        wiki_dir = workspace / "wiki"
        if not wiki_dir.exists():
            wiki_dir = workspace / "src" / "wiki"

        global_wiki_dir = Path("global_wiki")
        global_wiki_dir.mkdir(parents=True, exist_ok=True)

        logger.info("GovernanceLabor M3_PROMOTION: promoting to GlobalWiki")

        try:
            # Find sanitized content
            sanitized_files = list(wiki_dir.glob("sanitized_*.md")) if wiki_dir.exists() else []

            promoted = 0
            for sanitized_file in sanitized_files:
                # Move to global wiki
                dest = global_wiki_dir / sanitized_file.name.replace("sanitized_", "")
                content = sanitized_file.read_text(encoding="utf-8")
                dest.write_text(content, encoding="utf-8")
                promoted += 1

            # Record promotion
            promotion_record = {
                "promoted_count": promoted,
                "timestamp": meta.get("timestamp", "now"),
            }
            record_file = global_wiki_dir / "promotion_record.json"
            record_file.write_text(
                json.dumps(promotion_record, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            logger.info("M3_PROMOTION: promoted %d entries", promoted)
            return LaborResult(
                success=True,
                output=f"M3_PROMOTION: promoted {promoted} entries to GlobalWiki",
                token_usage=0,
            )

        except Exception as e:
            logger.exception("M3_PROMOTION failed")
            return LaborResult(
                success=False,
                output="",
                token_usage=0,
                error=str(e),
            )

    async def _execute_m4_sync(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> LaborResult:
        """M4_SYNC: Update all active indexes."""
        global_wiki_dir = Path("global_wiki")
        global_wiki_dir.mkdir(parents=True, exist_ok=True)

        logger.info("GovernanceLabor M4_SYNC: updating indexes")

        try:
            # Build index of all wiki entries
            all_entries = list(global_wiki_dir.glob("*.md"))

            index = {
                "total_entries": len(all_entries),
                "entries": [
                    {"name": e.name, "path": str(e)}
                    for e in all_entries[:100]  # limit index size
                ],
                "synced_at": meta.get("timestamp", "now"),
            }

            # Save index
            index_file = global_wiki_dir / "wiki_index.json"
            index_file.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

            logger.info("M4_SYNC: indexed %d entries", len(all_entries))
            return LaborResult(
                success=True,
                output=f"M4_SYNC: indexed {len(all_entries)} entries",
                token_usage=0,
            )

        except Exception as e:
            logger.exception("M4_SYNC failed")
            return LaborResult(
                success=False,
                output="",
                token_usage=0,
                error=str(e),
            )

    def _redact_pii(self, content: str) -> str:
        """Redact PII from content."""
        # Redact email addresses
        content = re.sub(r"[\w.-]+@[\w.-]+\.\w+", "[EMAIL_REDACTED]", content)
        # Redact phone numbers
        content = re.sub(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b", "[PHONE_REDACTED]", content)
        # Redact potential ID numbers
        content = re.sub(r"\b\d{10,}\b", "[ID_REDACTED]", content)
        # Redact names (simple pattern)
        content = re.sub(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", "[NAME_REDACTED]", content)

        return content


# ---------------------------------------------------------------------------
# Verification functions (used by PipelineEngine)
# ---------------------------------------------------------------------------

from hermes_os.universal_pipeline import VerificationResult


async def verify_new_content_detected(detection_json: str) -> VerificationResult:
    """Verify new content was detected."""
    errors = []
    try:
        data = json.loads(detection_json)
        if "new_entries" not in data:
            errors.append("Detection record missing entry count")
    except json.JSONDecodeError:
        errors.append("Invalid JSON detection result")
    return VerificationResult(passed=len(errors) == 0, errors=errors)


async def verify_pii_removed(sanitization_json: str) -> VerificationResult:
    """Verify PII was removed."""
    errors = []
    try:
        data = json.loads(sanitization_json)
        if data.get("pii_found", 0) > 0 and not data.get("redacted", False):
            errors.append("PII found but not fully redacted")
    except json.JSONDecodeError:
        errors.append("Invalid JSON sanitization result")
    return VerificationResult(passed=len(errors) == 0, errors=errors)


async def verify_promoted(promotion_json: str) -> VerificationResult:
    """Verify content was promoted to GlobalWiki."""
    errors = []
    try:
        data = json.loads(promotion_json)
        if "promoted_count" not in data:
            errors.append("Promotion record missing count")
    except json.JSONDecodeError:
        errors.append("Invalid JSON promotion result")
    return VerificationResult(passed=len(errors) == 0, errors=errors)


async def verify_sync_complete(sync_json: str) -> VerificationResult:
    """Verify sync completed and index is updated."""
    errors = []
    try:
        data = json.loads(sync_json)
        if "total_entries" not in data:
            errors.append("Sync record missing entry count")
    except json.JSONDecodeError:
        errors.append("Invalid JSON sync result")
    return VerificationResult(passed=len(errors) == 0, errors=errors)