"""Tests for Intelligence & Analytics Pipeline — DataLabor.

RED phase: Define DataLabor contract first.

Intelligence Pipeline stages:
- M1_DATAFETCH: Fetch data from GitHub/Feishu/Wiki/Web
- M2_NORMALIZE: Clean and normalize data
- M3_REASONING: Compute metrics and analyze patterns
- M4_VISUALIZE: Generate charts and visualizations
- M5_INSIGHT: Synthesize findings into insights
"""

import pytest
import asyncio
import tempfile
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from hermes_os.labor.data_labor import DataLabor


class TestDataLaborInterface:
    """Test DataLabor implements LaborInterface correctly."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_data_labor_execute_returns_bool(self, temp_dir: str) -> None:
        """DataLabor.execute() must return bool (True=success)."""
        labor = DataLabor()
        workspace = Path(temp_dir) / "test_workspace"
        workspace.mkdir(parents=True)

        result = await labor.execute(
            workspace=workspace,
            task_description="Fetch GitHub data",
            meta={"stage": "M1_DATAFETCH", "data_source": "github"},
        )
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_data_labor_writes_to_workspace(self, temp_dir: str) -> None:
        """DataLabor should write fetched data to workspace/src/data/."""
        labor = DataLabor()
        workspace = Path(temp_dir) / "test_workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        with patch("hermes_os.labor.data_labor.fetch_github_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = {"repos": [{"name": "test-repo", "stars": 100}]}

            result = await labor.execute(
                workspace=workspace,
                task_description="Fetch GitHub repositories",
                meta={"stage": "M1_DATAFETCH", "data_source": "github", "query": "hermes-os"},
            )

            assert result is True
            data_dir = workspace / "src" / "data"
            assert data_dir.exists()


class TestIntelligencePipelineStages:
    """Test the 5 stages of Intelligence Pipeline."""

    def test_intelligence_pipeline_has_5_stages(self) -> None:
        """Intelligence Pipeline: M1_DATAFETCH → M5_INSIGHT."""
        from hermes_os.universal_pipeline import UniversalPipelineLoader

        loader = UniversalPipelineLoader()
        config = loader.load_pipeline("intelligence")
        stages = [s.stage for s in config.steps]
        assert stages == ["M1_DATAFETCH", "M2_NORMALIZE", "M3_REASONING", "M4_VISUALIZE", "M5_INSIGHT"]

    def test_intelligence_pipeline_m1_uses_datalabor(self) -> None:
        """M1_DATAFETCH should use DataLabor."""
        from hermes_os.universal_pipeline import UniversalPipelineLoader

        loader = UniversalPipelineLoader()
        config = loader.load_pipeline("intelligence")
        m1 = config.steps[0]
        assert m1.labor == "DataLabor"
        assert "fetch" in m1.task.lower() or "data" in m1.task.lower()

    def test_intelligence_pipeline_m2_uses_datalabor(self) -> None:
        """M2_NORMALIZE should use DataLabor."""
        from hermes_os.universal_pipeline import UniversalPipelineLoader

        loader = UniversalPipelineLoader()
        config = loader.load_pipeline("intelligence")
        m2 = config.steps[1]
        assert m2.labor == "DataLabor"
        assert "normaliz" in m2.task.lower() or "clean" in m2.task.lower()

    def test_intelligence_pipeline_m3_uses_researchlabor(self) -> None:
        """M3_REASONING should use ResearchLabor."""
        from hermes_os.universal_pipeline import UniversalPipelineLoader

        loader = UniversalPipelineLoader()
        config = loader.load_pipeline("intelligence")
        m3 = config.steps[2]
        assert m3.labor == "ResearchLabor"
        assert "reason" in m3.task.lower() or "anal" in m3.task.lower()

    def test_intelligence_pipeline_m4_uses_datalabor(self) -> None:
        """M4_VISUALIZE should use DataLabor."""
        from hermes_os.universal_pipeline import UniversalPipelineLoader

        loader = UniversalPipelineLoader()
        config = loader.load_pipeline("intelligence")
        m4 = config.steps[3]
        assert m4.labor == "DataLabor"
        assert "visual" in m4.task.lower() or "chart" in m4.task.lower()

    def test_intelligence_pipeline_m5_uses_contentlabor(self) -> None:
        """M5_INSIGHT should use ContentLabor."""
        from hermes_os.universal_pipeline import UniversalPipelineLoader

        loader = UniversalPipelineLoader()
        config = loader.load_pipeline("intelligence")
        m5 = config.steps[4]
        assert m5.labor == "ContentLabor"
        assert "insight" in m5.task.lower() or "conclusion" in m5.task.lower()


class TestDataLaborM1DataFetch:
    """Test M1_DATAFETCH stage."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_fetches_github_data(self, temp_dir: str) -> None:
        """M1_DATAFETCH should fetch GitHub data."""
        labor = DataLabor()
        workspace = Path(temp_dir) / "test_workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        with patch("hermes_os.labor.data_labor.fetch_github_data", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "repos": [
                    {"name": "hermes-os", "stars": 100, "forks": 20},
                    {"name": "other-repo", "stars": 50, "forks": 10},
                ]
            }

            result = await labor.execute(
                workspace=workspace,
                task_description="Fetch GitHub repositories",
                meta={"stage": "M1_DATAFETCH", "source": "github", "query": "test"},
            )

            assert result is True
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetches_feishu_data(self, temp_dir: str) -> None:
        """M1_DATAFETCH should fetch Feishu data."""
        labor = DataLabor()
        workspace = Path(temp_dir) / "test_workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        with patch("hermes_os.labor.data_labor.fetch_feishu_data", new_callable=AsyncMock) as mock:
            mock.return_value = {"docs": [{"title": "Test Doc", "content": "..."}]}

            result = await labor.execute(
                workspace=workspace,
                task_description="Fetch Feishu documents",
                meta={"stage": "M1_DATAFETCH", "source": "feishu"},
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_handles_fetch_failure(self, temp_dir: str) -> None:
        """M1_DATAFETCH should return False on fetch failure."""
        labor = DataLabor()
        workspace = Path(temp_dir) / "test_workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        with patch("hermes_os.labor.data_labor.fetch_github_data", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("API rate limit exceeded")

            result = await labor.execute(
                workspace=workspace,
                task_description="Fetch GitHub data",
                meta={"stage": "M1_DATAFETCH", "source": "github"},
            )

            assert result is False


class TestDataLaborM2Normalize:
    """Test M2_NORMALIZE stage."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_normalizes_raw_data(self, temp_dir: str) -> None:
        """M2_NORMALIZE should clean and structure raw data."""
        labor = DataLabor()
        workspace = Path(temp_dir) / "test_workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        # Create raw data
        data_dir = workspace / "src" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        raw_file = data_dir / "raw.json"
        raw_file.write_text(json.dumps({"raw": "data", "null_value": None, "extra": "field"}), encoding="utf-8")

        result = await labor.execute(
            workspace=workspace,
            task_description="Normalize data",
            meta={"stage": "M2_NORMALIZE"},
        )

        assert result is True
        normalized_file = data_dir / "normalized.json"
        assert normalized_file.exists()


class TestDataLaborM4Visualize:
    """Test M4_VISUALIZE stage."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_generates_chart_spec(self, temp_dir: str) -> None:
        """M4_VISUALIZE should generate chart specifications."""
        labor = DataLabor()
        workspace = Path(temp_dir) / "test_workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        # Create normalized data with repos (what generate_chart expects)
        data_dir = workspace / "src" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        norm_file = data_dir / "normalized.json"
        norm_file.write_text(json.dumps({
            "repos": [
                {"name": "repo1", "stars": 100, "forks": 20},
                {"name": "repo2", "stars": 200, "forks": 30},
            ]
        }), encoding="utf-8")

        result = await labor.execute(
            workspace=workspace,
            task_description="Generate visualizations",
            meta={"stage": "M4_VISUALIZE", "chart_type": "bar"},
        )

        assert result is True
        # Verify charts were created
        charts_file = data_dir / "charts.json"
        assert charts_file.exists()


class TestDataLaborVerification:
    """Test verification functions for Intelligence Pipeline."""

    @pytest.mark.asyncio
    async def test_verify_data_fetched(self) -> None:
        """Verify data was successfully fetched."""
        from hermes_os.labor.data_labor import verify_data_fetched

        result = await verify_data_fetched('{"repos": [{"name": "test"}]}')
        assert result.passed is True

        result = await verify_data_fetched("")
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_verify_data_clean(self) -> None:
        """Verify data cleaning completed."""
        from hermes_os.labor.data_labor import verify_data_clean

        clean_data = '{"name": "test", "value": 100}'
        result = await verify_data_clean(clean_data)
        assert result.passed is True

        dirty_data = '{"name": "test", "null_value": null, "undefined": undefined}'
        result = await verify_data_clean(dirty_data)
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_verify_analysis_complete(self) -> None:
        """Verify analysis produced results."""
        from hermes_os.labor.data_labor import verify_analysis_complete

        result = await verify_analysis_complete('{"metrics": {"avg": 100, "total": 1000}}')
        assert result.passed is True

        result = await verify_analysis_complete('{}')
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_verify_charts_generated(self) -> None:
        """Verify charts were generated."""
        from hermes_os.labor.data_labor import verify_charts_generated

        result = await verify_charts_generated('{"charts": [{"type": "bar"}]}')
        assert result.passed is True

        result = await verify_charts_generated('{"charts": []}')
        assert result.passed is False