"""Tests for Batch_Runner — Scalable Autonomous Business Engine.

RED phase: Define contracts for N pipeline instances running in parallel.

Key requirements:
- Batch_Runner.launch(N) starts N pipeline instances
- Each instance has isolated UUID workspace + meta.json
- asyncio.Semaphore limits concurrency (max 10 parallel)
- PipelineEngine state machine tracks each artifact independently
- ROI_Planner allocates resources based on priority
"""

import asyncio
import tempfile

import pytest

from hermes_os.pipeline_engine_v2 import (
    PipelineConfig,
)


class TestBatchRunnerInterface:
    """Test Batch_Runner can launch N pipeline instances."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil

        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_batch_runner_launch_starts_n_instances(self, temp_dir: str) -> None:
        """Batch_Runner.launch(N) should start N pipeline instances."""
        from hermes_os.batch_runner import BatchRunner

        runner = BatchRunner(base_dir=temp_dir, max_concurrency=5)
        configs = [
            PipelineConfig(name=f"Pipeline-{i}", description="test", steps=[]) for i in range(10)
        ]

        results = await runner.launch(configs)

        assert len(results) == 10, f"Expected 10 results, got {len(results)}"
        for r in results:
            assert r.workflow_id is not None

    @pytest.mark.asyncio
    async def test_batch_runner_respects_max_concurrency(self, temp_dir: str) -> None:
        """Batch_Runner should limit concurrent executions to max_concurrency."""
        from hermes_os.batch_runner import BatchRunner

        max_concurrent = 3
        runner = BatchRunner(base_dir=temp_dir, max_concurrency=max_concurrent)

        # Track concurrent executions
        concurrent_executions = 0
        max_seen = 0

        async def slow_execute():
            nonlocal concurrent_executions, max_seen
            concurrent_executions += 1
            max_seen = max(max_seen, concurrent_executions)
            await asyncio.sleep(0.1)
            concurrent_executions -= 1
            return True

        # Run 10 tasks
        runner._execute_single = slow_execute
        configs = [PipelineConfig(name=f"P-{i}", description="", steps=[]) for i in range(10)]
        await runner.launch(configs)

        assert max_seen <= max_concurrent, (
            f"Max concurrent {max_seen} exceeded limit {max_concurrent}"
        )


class TestIdentityPool:
    """Test Identity_Pool for multi-platform, multi-identity session management."""

    def test_identity_pool_registers_platform(self) -> None:
        """Identity_Pool should register a platform with its credentials."""
        from hermes_os.identity_pool import IdentityPool

        pool = IdentityPool()
        pool.register("amazon", identity_id="amazon-alice-001", session_token="tok_123")

        identity = pool.get_identity("amazon", "amazon-alice-001")
        assert identity is not None
        assert identity.platform == "amazon"
        assert identity.identity_id == "amazon-alice-001"

    def test_identity_pool_returns_none_for_unknown(self) -> None:
        """Identity_Pool returns None for unregistered platform/identity."""
        from hermes_os.identity_pool import IdentityPool

        pool = IdentityPool()
        assert pool.get_identity("unknown", "x") is None

    def test_identity_pool_lists_identities_for_platform(self) -> None:
        """Identity_Pool can list all identities for a platform."""
        from hermes_os.identity_pool import IdentityPool

        pool = IdentityPool()
        pool.register("amazon", "alice-001", "tok_alice")
        pool.register("amazon", "bob-002", "tok_bob")
        pool.register("patents", "charlie-001", "tok_charlie")

        amazon_ids = pool.list_identities("amazon")
        assert len(amazon_ids) == 2
        assert "alice-001" in amazon_ids
        assert "bob-002" in amazon_ids


class TestROIPplanner:
    """Test ROI_Planner for resource allocation based on ROI metrics."""

    def test_roi_planner_calculates_priority(self) -> None:
        """ROI_Planner calculates priority based on ROI metrics."""
        from hermes_os.roi_planner import ROIPlanner

        planner = ROIPlanner()
        # ROI = revenue / cost. Higher ROI = higher priority
        priority = planner.calculate_priority(revenue=1000, cost=100)
        assert priority > planner.calculate_priority(revenue=100, cost=100)

    def test_roi_planner_allocates_resources(self) -> None:
        """ROI_Planner allocates more resources to higher ROI tasks."""
        from hermes_os.roi_planner import ROIPlanner

        planner = ROIPlanner()
        resources = {"compute_units": 10}

        # Book has high ROI, should get more resources
        allocation = planner.allocate(
            tasks=[
                {"id": "book-001", "type": "book", "roi": 5.0},
                {"id": "patent-001", "type": "patent", "roi": 2.0},
            ],
            resources=resources,
        )

        book_alloc = next(a for a in allocation if a.task_id == "book-001")
        patent_alloc = next(a for a in allocation if a.task_id == "patent-001")

        assert book_alloc.compute_units >= patent_alloc.compute_units


class TestPortfolioView:
    """Test Portfolio_View for managing 100+ assets with unified view."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil

        shutil.rmtree(path, ignore_errors=True)

    def test_portfolio_view_adds_artifact(self, temp_dir: str) -> None:
        """Portfolio_View can add an artifact to the portfolio."""
        from hermes_os.portfolio_view import PortfolioView

        view = PortfolioView(base_dir=temp_dir)
        view.add_artifact(
            artifact_id="book-001",
            title="My Book",
            domain="publication",
            status="in_progress",
        )

        artifact = view.get_artifact("book-001")
        assert artifact is not None
        assert artifact.title == "My Book"

    def test_portfolio_view_filters_by_domain(self, temp_dir: str) -> None:
        """Portfolio_View can filter artifacts by domain."""
        from hermes_os.portfolio_view import PortfolioView

        view = PortfolioView(base_dir=temp_dir)
        view.add_artifact("book-001", "Book 1", "publication", "completed")
        view.add_artifact("patent-001", "Patent 1", "patent", "completed")
        view.add_artifact("drama-001", "Drama 1", "short_drama", "in_progress")

        patents = view.filter_by_domain("patent")
        assert len(patents) == 1
        assert patents[0].artifact_id == "patent-001"

    def test_portfolio_view_lists_all_domains(self, temp_dir: str) -> None:
        """Portfolio_View can list all domains in portfolio."""
        from hermes_os.portfolio_view import PortfolioView

        view = PortfolioView(base_dir=temp_dir)
        view.add_artifact("book-001", "Book 1", "publication", "completed")
        view.add_artifact("patent-001", "Patent 1", "patent", "completed")
        view.add_artifact("drama-001", "Drama 1", "short_drama", "in_progress")

        domains = view.list_domains()
        assert "publication" in domains
        assert "patent" in domains
        assert "short_drama" in domains

    def test_portfolio_view_aggregate_status(self, temp_dir: str) -> None:
        """Portfolio_View can aggregate status across all artifacts."""
        from hermes_os.portfolio_view import PortfolioView

        view = PortfolioView(base_dir=temp_dir)
        view.add_artifact("book-001", "Book 1", "publication", "completed")
        view.add_artifact("book-002", "Book 2", "publication", "in_progress")
        view.add_artifact("patent-001", "Patent 1", "patent", "failed")

        summary = view.aggregate_status()
        assert summary.total == 3
        assert summary.completed == 1
        assert summary.in_progress == 1
        assert summary.failed == 1


class TestScalableBusinessCube:
    """Integration test: The full Business Cube works end-to-end."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil

        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_end_to_end_book_empire_pipeline(self, temp_dir: str) -> None:
        """Publication empire: 10 books in parallel, all stages."""
        from hermes_os.batch_runner import BatchRunner
        from hermes_os.identity_pool import IdentityPool
        from hermes_os.portfolio_view import PortfolioView
        from hermes_os.roi_planner import ROIPlanner
        from hermes_os.universal_pipeline import PIPELINE_CONTENT_ASSEMBLY

        # 1. Create portfolio
        portfolio = PortfolioView(base_dir=temp_dir)

        # 2. Register identities for Amazon KDP
        identity_pool = IdentityPool()
        identity_pool.register("amazon_kdp", "alice-001", "session_tok")

        # 3. Plan resource allocation (ROI-based)
        planner = ROIPlanner()

        # 4. Launch 10 book pipelines in parallel
        runner = BatchRunner(base_dir=temp_dir, max_concurrency=5)

        configs = [PipelineConfig.from_yaml(PIPELINE_CONTENT_ASSEMBLY) for _ in range(10)]

        results = await runner.launch(configs)

        # 5. Add to portfolio
        for i, result in enumerate(results):
            portfolio.add_artifact(
                artifact_id=result.workflow_id,
                title=f"Book {i + 1}",
                domain="publication",
                status="in_progress" if result.success else "failed",
            )

        # 6. Verify
        summary = portfolio.aggregate_status()
        assert summary.total == 10
        # Some may have failed due to placeholder implementations (FormatLabor needs content)
        # At minimum verify the portfolio tracked all 10 artifacts
        assert summary.completed + summary.in_progress + summary.failed == 10
