"""Tests for Deployment/Release Pipeline — BrowserLabor.

RED phase: Define BrowserLabor contract first.

Deployment Pipeline stages:
- M1_STATEDAUTH: Check login state (Session/Cookie)
- M2_FORMFILLING: Automate form filling
- M3_UPLOAD: Upload files to platform
- M4_VERIFICATION: Verify via UI state/screenshot
- M5_FINALIZE: Record release result
"""

import pytest
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from hermes_os.labor.browser_labor import BrowserLabor


class TestBrowserLaborInterface:
    """Test BrowserLabor implements LaborInterface correctly."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_browser_labor_execute_returns_bool(self, temp_dir: str) -> None:
        """BrowserLabor.execute() must return bool."""
        labor = BrowserLabor()
        workspace = Path(temp_dir) / "test_workspace"
        workspace.mkdir(parents=True)

        result = await labor.execute(
            workspace=workspace,
            task_description="Check login state",
            meta={"stage": "M1_STATEDAUTH", "platform": "amazon"},
        )
        assert isinstance(result, bool)


class TestDeploymentPipelineStages:
    """Test the 5 stages of Deployment Pipeline."""

    def test_deployment_pipeline_has_5_stages(self) -> None:
        """Deployment Pipeline: M1_STATEDAUTH → M5_FINALIZE."""
        from hermes_os.universal_pipeline import UniversalPipelineLoader

        loader = UniversalPipelineLoader()
        config = loader.load_pipeline("deployment")
        stages = [s.stage for s in config.steps]
        assert stages == ["M1_STATEDAUTH", "M2_FORMFILLING", "M3_UPLOAD", "M4_VERIFICATION", "M5_FINALIZE"]

    def test_deployment_all_use_browserlabor(self) -> None:
        """All deployment stages M1-M4 should use BrowserLabor (M5 uses ContentLabor)."""
        from hermes_os.universal_pipeline import UniversalPipelineLoader

        loader = UniversalPipelineLoader()
        config = loader.load_pipeline("deployment")
        # M1-M4 use BrowserLabor, M5 uses ContentLabor
        for step in config.steps:
            if step.stage.startswith("M1") or step.stage.startswith("M2") or step.stage.startswith("M3") or step.stage.startswith("M4"):
                assert step.labor == "BrowserLabor", f"Stage {step.stage} should use BrowserLabor"
            elif step.stage == "M5_FINALIZE":
                assert step.labor == "ContentLabor", f"Stage {step.stage} should use ContentLabor"


class TestBrowserLaborM1StateAuth:
    """Test M1_STATEDAUTH stage - verify login state."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_checks_login_state(self, temp_dir: str) -> None:
        """M1_STATEDAUTH should check if user is logged in."""
        labor = BrowserLabor()
        workspace = Path(temp_dir) / "test_workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        with patch("hermes_os.labor.browser_labor.check_login_state", new_callable=AsyncMock) as mock:
            mock.return_value = True  # Logged in

            result = await labor.execute(
                workspace=workspace,
                task_description="Check Amazon login state",
                meta={"stage": "M1_STATEDAUTH", "platform": "amazon"},
            )

            assert result is True
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_detects_not_logged_in(self, temp_dir: str) -> None:
        """M1_STATEDAUTH should return False if not logged in."""
        labor = BrowserLabor()
        workspace = Path(temp_dir) / "test_workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        with patch("hermes_os.labor.browser_labor.check_login_state", new_callable=AsyncMock) as mock:
            mock.return_value = False  # Not logged in

            result = await labor.execute(
                workspace=workspace,
                task_description="Check Amazon login state",
                meta={"stage": "M1_STATEDAUTH", "platform": "amazon"},
            )

            assert result is False


class TestBrowserLaborM2FormFilling:
    """Test M2_FORMFILLING stage - automate form filling."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_fills_form_fields(self, temp_dir: str) -> None:
        """M2_FORMFILLING should fill form fields."""
        labor = BrowserLabor()
        workspace = Path(temp_dir) / "test_workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        with patch("hermes_os.labor.browser_labor.fill_form", new_callable=AsyncMock) as mock:
            mock.return_value = True

            result = await labor.execute(
                workspace=workspace,
                task_description="Fill Amazon product form",
                meta={
                    "stage": "M2_FORMFILLING",
                    "platform": "amazon",
                    "form_fields": {"title": "Product Name", "price": "99.99"},
                },
            )

            assert result is True


class TestBrowserLaborM3Upload:
    """Test M3_UPLOAD stage - upload files."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_uploads_file(self, temp_dir: str) -> None:
        """M3_UPLOAD should upload file to platform."""
        labor = BrowserLabor()
        workspace = Path(temp_dir) / "test_workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        # Create a file to upload
        upload_dir = workspace / "delivery"
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / "product.pdf").write_text("fake pdf content", encoding="utf-8")

        with patch("hermes_os.labor.browser_labor.upload_file", new_callable=AsyncMock) as mock:
            mock.return_value = "https://amazon.com/uploaded/file.pdf"

            result = await labor.execute(
                workspace=workspace,
                task_description="Upload product PDF",
                meta={"stage": "M3_UPLOAD", "platform": "amazon", "file_path": "product.pdf"},
            )

            assert result is True


class TestBrowserLaborM4Verification:
    """Test M4_VERIFICATION stage - verify via UI/screenshot."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_verifies_ui_state(self, temp_dir: str) -> None:
        """M4_VERIFICATION should verify UI shows correct state."""
        labor = BrowserLabor()
        workspace = Path(temp_dir) / "test_workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        with patch("hermes_os.labor.browser_labor.verify_ui_state", new_callable=AsyncMock) as mock:
            mock.return_value = True  # Verified

            result = await labor.execute(
                workspace=workspace,
                task_description="Verify product listed on Amazon",
                meta={"stage": "M4_VERIFICATION", "platform": "amazon", "expected_text": "Product Name"},
            )

            assert result is True


class TestBrowserLaborVerification:
    """Test verification functions for Deployment Pipeline."""

    @pytest.mark.asyncio
    async def test_verify_auth_valid(self) -> None:
        """Verify login state is valid."""
        from hermes_os.labor.browser_labor import verify_auth_valid

        result = await verify_auth_valid('{"logged_in": true}')
        assert result.passed is True

        result = await verify_auth_valid('{"logged_in": false}')
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_verify_form_filled(self) -> None:
        """Verify form was filled successfully."""
        from hermes_os.labor.browser_labor import verify_form_filled

        result = await verify_form_filled('{"filled": true, "fields": 5}')
        assert result.passed is True

        result = await verify_form_filled('{"filled": false}')
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_verify_upload_success(self) -> None:
        """Verify file upload succeeded."""
        from hermes_os.labor.browser_labor import verify_upload_success

        result = await verify_upload_success('{"url": "https://example.com/file.pdf"}')
        assert result.passed is True

        result = await verify_upload_success('{"error": "File too large"}')
        assert result.passed is False