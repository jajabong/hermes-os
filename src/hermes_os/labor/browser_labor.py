"""BrowserLabor — Deployment/Release Pipeline browser automation labor.

Implements the Deployment Pipeline stages:
- M1_STATEDAUTH: Check login state (Session/Cookie)
- M2_FORMFILLING: Automate form filling
- M3_UPLOAD: Upload files to platform
- M4_VERIFICATION: Verify via UI state/screenshot

M5_FINALIZE uses ContentLabor.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hermes_os.labor_registry import LaborResult

logger = logging.getLogger(__name__)


class BrowserLabor:
    """Labor unit for browser automation in deployment pipeline."""

    def __init__(self, **kwargs) -> None:
        pass

    async def execute(self, workspace: Path, task_description: str, meta: dict[str, Any]) -> LaborResult:
        """
        Execute browser automation task.

        Stage-specific behavior:
        - M1_STATEDAUTH: Check login state
        - M2_FORMFILLING: Fill form fields
        - M3_UPLOAD: Upload files to platform
        - M4_VERIFICATION: Verify UI state
        """
        stage = meta.get("stage", "M1_STATEDAUTH")

        if stage == "M1_STATEDAUTH":
            return await self._execute_m1_statedauth(workspace, task_description, meta)
        elif stage == "M2_FORMFILLING":
            return await self._execute_m2_formfilling(workspace, task_description, meta)
        elif stage == "M3_UPLOAD":
            return await self._execute_m3_upload(workspace, task_description, meta)
        elif stage == "M4_VERIFICATION":
            return await self._execute_m4_verification(workspace, task_description, meta)
        else:
            logger.warning("BrowserLabor: unknown stage %s", stage)
            return LaborResult(
                success=False,
                output="",
                token_usage=0,
                error=f"Unknown stage: {stage}",
            )

    async def _execute_m1_statedauth(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> LaborResult:
        """M1_STATEDAUTH: Check login state (Session/Cookie)."""
        platform = meta.get("platform", "unknown")
        delivery_dir = workspace / "delivery"
        delivery_dir.mkdir(parents=True, exist_ok=True)

        logger.info("BrowserLabor M1_STATEDAUTH: platform=%s", platform)

        try:
            engine = meta.get("workflow_engine")
            if engine:
                result = await engine._execute_tool(
                    "browser_check_login",
                    {
                        "platform": platform,
                    },
                )
                logged_in = result is not None and "logged_in" in str(result).lower()
                if logged_in:
                    return LaborResult(
                        success=True,
                        output=f"M1_STATEDAUTH: logged in to {platform}",
                        token_usage=0,
                    )
                else:
                    return LaborResult(
                        success=False,
                        output="",
                        token_usage=0,
                        error="Login check failed",
                    )
            result = await check_login_state(platform, meta)
            if result:
                return LaborResult(
                    success=True,
                    output=f"M1_STATEDAUTH: logged in to {platform}",
                    token_usage=0,
                )
            else:
                return LaborResult(
                    success=False,
                    output="",
                    token_usage=0,
                    error="Login check returned False",
                )
        except Exception as e:
            logger.exception("M1_STATEDAUTH failed")
            return LaborResult(
                success=False,
                output="",
                token_usage=0,
                error=str(e),
            )

    async def _execute_m2_formfilling(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> LaborResult:
        """M2_FORMFILLING: Automate form filling."""
        platform = meta.get("platform", "unknown")
        form_fields = meta.get("form_fields", {})
        delivery_dir = workspace / "delivery"
        delivery_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "BrowserLabor M2_FORMFILLING: platform=%s, fields=%s",
            platform,
            list(form_fields.keys()),
        )

        try:
            engine = meta.get("workflow_engine")
            if engine:
                result = await engine._execute_tool(
                    "browser_fill_form",
                    {
                        "platform": platform,
                        "fields": form_fields,
                    },
                )
                filled = result is not None and "filled" in str(result).lower()
                if filled:
                    return LaborResult(
                        success=True,
                        output=f"M2_FORMFILLING: filled form on {platform}",
                        token_usage=0,
                    )
                else:
                    return LaborResult(
                        success=False,
                        output="",
                        token_usage=0,
                        error="Form filling failed",
                    )
            result = await fill_form(platform, form_fields, meta)
            if result:
                return LaborResult(
                    success=True,
                    output=f"M2_FORMFILLING: filled form on {platform}",
                    token_usage=0,
                )
            else:
                return LaborResult(
                    success=False,
                    output="",
                    token_usage=0,
                    error="Form filling returned False",
                )
        except Exception as e:
            logger.exception("M2_FORMFILLING failed")
            return LaborResult(
                success=False,
                output="",
                token_usage=0,
                error=str(e),
            )

    async def _execute_m3_upload(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> LaborResult:
        """M3_UPLOAD: Upload files to platform."""
        platform = meta.get("platform", "unknown")
        file_path = meta.get("file_path", "")
        delivery_dir = workspace / "delivery"
        delivery_dir.mkdir(parents=True, exist_ok=True)

        logger.info("BrowserLabor M3_UPLOAD: platform=%s, file=%s", platform, file_path)

        try:
            engine = meta.get("workflow_engine")
            if engine:
                result = await engine._execute_tool(
                    "browser_upload_file",
                    {
                        "platform": platform,
                        "file_path": file_path,
                    },
                )
                has_url = result is not None and "url" in str(result).lower()
                if has_url:
                    return LaborResult(
                        success=True,
                        output=f"M3_UPLOAD: uploaded {file_path} to {platform}",
                        token_usage=0,
                    )
                else:
                    return LaborResult(
                        success=False,
                        output="",
                        token_usage=0,
                        error="File upload failed",
                    )
            upload_url = await upload_file(platform, file_path, workspace, meta)
            if upload_url is not None:
                return LaborResult(
                    success=True,
                    output=f"M3_UPLOAD: uploaded to {upload_url}",
                    token_usage=0,
                )
            else:
                return LaborResult(
                    success=False,
                    output="",
                    token_usage=0,
                    error="upload_file returned None",
                )
        except Exception as e:
            logger.exception("M3_UPLOAD failed")
            return LaborResult(
                success=False,
                output="",
                token_usage=0,
                error=str(e),
            )

    async def _execute_m4_verification(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> LaborResult:
        """M4_VERIFICATION: Verify via UI state/screenshot."""
        platform = meta.get("platform", "unknown")
        expected_text = meta.get("expected_text", "")

        logger.info(
            "BrowserLabor M4_VERIFICATION: platform=%s, expected=%s", platform, expected_text
        )

        try:
            engine = meta.get("workflow_engine")
            if engine:
                result = await engine._execute_tool(
                    "browser_verify_ui",
                    {
                        "platform": platform,
                        "expected_text": expected_text,
                    },
                )
                verified = result is not None and "verified" in str(result).lower()
                if verified:
                    return LaborResult(
                        success=True,
                        output=f"M4_VERIFICATION: verified {platform}",
                        token_usage=0,
                    )
                else:
                    return LaborResult(
                        success=False,
                        output="",
                        token_usage=0,
                        error="UI verification failed",
                    )
            result = await verify_ui_state(platform, expected_text, meta)
            if result:
                return LaborResult(
                    success=True,
                    output=f"M4_VERIFICATION: verified {platform}",
                    token_usage=0,
                )
            else:
                return LaborResult(
                    success=False,
                    output="",
                    token_usage=0,
                    error="UI verification returned False",
                )
        except Exception as e:
            logger.exception("M4_VERIFICATION failed")
            return LaborResult(
                success=False,
                output="",
                token_usage=0,
                error=str(e),
            )


# ---------------------------------------------------------------------------
# Browser automation functions (mock implementations - replace with real browser APIs)
# ---------------------------------------------------------------------------


async def check_login_state(platform: str, meta: dict[str, Any]) -> bool:
    """Check if user is logged in to the platform."""
    logger.info("Checking login state for platform: %s", platform)
    # Placeholder - in production, use browser automation to check session/cookie
    return True


async def fill_form(platform: str, form_fields: dict[str, Any], meta: dict[str, Any]) -> bool:
    """Fill form fields on the platform."""
    logger.info("Filling form on platform: %s with fields: %s", platform, list(form_fields.keys()))
    # Placeholder - in production, use browser automation to fill forms
    return True


async def upload_file(
    platform: str, file_path: str, workspace: Path, meta: dict[str, Any]
) -> str | None:
    """Upload file to platform and return URL."""
    logger.info("Uploading file %s to platform: %s", file_path, platform)
    # Placeholder - in production, use browser automation to upload
    return f"https://{platform}.com/uploaded/{file_path}"


async def verify_ui_state(platform: str, expected_text: str, meta: dict[str, Any]) -> bool:
    """Verify UI shows expected state/text."""
    logger.info("Verifying UI state on platform: %s, expected: %s", platform, expected_text)
    # Placeholder - in production, use browser automation to verify UI
    return True


# ---------------------------------------------------------------------------
# Verification functions (used by PipelineEngine)
# ---------------------------------------------------------------------------

from hermes_os.universal_pipeline import VerificationResult


async def verify_auth_valid(auth_state_json: str) -> VerificationResult:
    """Verify login state is valid."""
    errors = []
    try:
        data = json.loads(auth_state_json)
        logged_in = data.get("logged_in", False)
        if not logged_in:
            errors.append("User is not logged in")
    except json.JSONDecodeError:
        errors.append("Invalid JSON auth state")
    return VerificationResult(passed=len(errors) == 0, errors=errors)


async def verify_form_filled(form_result_json: str) -> VerificationResult:
    """Verify form was filled successfully."""
    errors = []
    try:
        data = json.loads(form_result_json)
        if not data.get("filled", False):
            errors.append("Form was not filled successfully")
        fields = data.get("fields", 0)
        if fields == 0:
            errors.append("No form fields were filled")
    except json.JSONDecodeError:
        errors.append("Invalid JSON form result")
    return VerificationResult(passed=len(errors) == 0, errors=errors)


async def verify_upload_success(upload_result_json: str) -> VerificationResult:
    """Verify file upload succeeded."""
    errors = []
    try:
        data = json.loads(upload_result_json)
        if "url" not in data and "error" not in data:
            errors.append("Upload result missing URL or error")
        if "error" in data:
            errors.append(f"Upload error: {data['error']}")
    except json.JSONDecodeError:
        errors.append("Invalid JSON upload result")
    return VerificationResult(passed=len(errors) == 0, errors=errors)