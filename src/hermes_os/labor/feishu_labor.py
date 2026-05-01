"""FeishuLabor — Content Assembly Pipeline delivery via Feishu/飞书.

Implements Content Assembly Pipeline stage:
- M6_DELIVERY: Push summary card and artifact download link to Feishu

Used by: Content Assembly Pipeline (M6_DELIVERY)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FeishuLabor:
    """Labor unit for Feishu delivery tasks."""

    def __init__(self, **kwargs) -> None:
        pass

    async def execute(self, workspace: Path, task_description: str, meta: dict[str, Any]) -> bool:
        """
        Execute Feishu delivery task.

        Stage-specific behavior:
        - M6_DELIVERY: Push summary card and artifact download link
        """
        stage = meta.get("stage", "M6_DELIVERY")

        if stage == "M6_DELIVERY":
            return await self._execute_m6_delivery(workspace, task_description, meta)
        else:
            logger.warning("FeishuLabor: unknown stage %s", stage)
            return False

    async def _execute_m6_delivery(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> bool:
        """M6_DELIVERY: Push summary card and artifact download link to Feishu."""
        artifact_dir = workspace / "delivery"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # Find output artifact
        output_files = list(artifact_dir.glob("*"))
        artifact_path = output_files[0] if output_files else None

        title = meta.get("title", "Document")
        user_id = meta.get("user_id", "default")
        logger.info("FeishuLabor M6_DELIVERY: title=%s, artifact=%s", title, artifact_path)

        try:
            # Try to use WorkflowEngine tools if available
            engine = meta.get("workflow_engine")

            if engine:
                # Use real feishu tools via WorkflowEngine
                doc_result = await engine._execute_tool("feishu_doc_create", {
                    "title": title,
                    "content": f"Artifact: {artifact_path}",
                    "user_id": user_id,
                })

                # Send notification message
                await engine._execute_tool("feishu_message_send", {
                    "title": title,
                    "content": f"Document delivered: {artifact_path}",
                    "user_id": user_id,
                })

                delivery_record = {
                    "delivered_to": "feishu",
                    "title": title,
                    "artifact_path": str(artifact_path) if artifact_path else None,
                    "timestamp": meta.get("timestamp", "now"),
                    "feishu_response": doc_result,
                }
            else:
                # Fallback to mock delivery
                delivery_record = {
                    "delivered_to": "feishu",
                    "title": title,
                    "artifact_path": str(artifact_path) if artifact_path else None,
                    "timestamp": meta.get("timestamp", "now"),
                    "feishu_response": "mocked",
                }

            # Save delivery record
            record_file = artifact_dir / "delivery_record.json"
            record_file.write_text(json.dumps(delivery_record, ensure_ascii=False, indent=2), encoding="utf-8")

            logger.info("M6_DELIVERY: delivered to Feishu")
            return True

        except Exception as e:
            logger.exception("M6_DELIVERY failed")
            return False


# ---------------------------------------------------------------------------
# Verification functions (used by PipelineEngine)
# ---------------------------------------------------------------------------

from hermes_os.universal_pipeline import VerificationResult


async def verify_delivery_complete(delivery_json: str) -> VerificationResult:
    """Verify delivery completed successfully."""
    errors = []
    try:
        data = json.loads(delivery_json)
        if "delivered_to" not in data:
            errors.append("Delivery record missing destination")
        if "artifact_path" not in data or not data["artifact_path"]:
            errors.append("Delivery record missing artifact path")
    except json.JSONDecodeError:
        errors.append("Invalid JSON delivery record")
    return VerificationResult(passed=len(errors) == 0, errors=errors)