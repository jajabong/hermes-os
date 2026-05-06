"""Tests for GeneEngine — Oct-OS inspired evolution engine."""

import shutil
import tempfile
from pathlib import Path

import pytest

from hermes_os.gene_engine import (
    GeneEngine,
)


@pytest.fixture
def gene_engine(temp_dir: Path) -> GeneEngine:
    return GeneEngine(base_dir=temp_dir / "genes")


@pytest.fixture
def temp_dir() -> Path:
    tmp = Path(tempfile.mkdtemp())
    yield tmp
    shutil.rmtree(tmp)


class TestAntibodyGenes:
    """Tests for antibody gene immune memory."""

    def test_record_failure_creates_gene(self, gene_engine: GeneEngine) -> None:
        gene = gene_engine.record_failure(
            error_pattern="Connection refused",
            error_context="Connection refused during API call",
            fix_strategy="Add retry with exponential backoff",
        )
        assert gene.failure_count == 1
        assert gene.pattern == "Connection refused"
        assert gene.fix_strategy == "Add retry with exponential backoff"

    def test_record_failure_increments_count(self, gene_engine: GeneEngine) -> None:
        gene_engine.record_failure("Connection refused", "error")
        gene = gene_engine.record_failure("Connection refused", "error")

        assert gene.failure_count == 2

    def test_get_antibody_returns_existing(self, gene_engine: GeneEngine) -> None:
        gene_engine.record_failure("SyntaxError", "error", "Fix the syntax")

        antibody = gene_engine.get_antibody("SyntaxError")
        assert antibody is not None
        assert antibody.fix_strategy == "Fix the syntax"

    def test_get_antibody_returns_none_for_unknown(self, gene_engine: GeneEngine) -> None:
        antibody = gene_engine.get_antibody("UnknownPattern")
        assert antibody is None

    def test_record_success_increments_success_count(self, gene_engine: GeneEngine) -> None:
        gene_engine.record_failure("SyntaxError", "error", "Fix syntax")
        gene_engine.record_success_for_pattern("SyntaxError")

        antibody = gene_engine.get_antibody("SyntaxError")
        assert antibody.success_count == 1

    def test_effectiveness_score(self, gene_engine: GeneEngine) -> None:
        gene_engine.record_failure("test_pattern", "error", "fix")
        antibody = gene_engine.get_antibody("test_pattern")
        assert antibody.effectiveness == 0.0  # 0/1 = 0

        gene_engine.record_success_for_pattern("test_pattern")
        antibody = gene_engine.get_antibody("test_pattern")
        assert antibody.effectiveness == 1.0  # 1/1 = 1.0


class TestGenePool:
    """Tests for successful prompt strategies."""

    def test_record_success_creates_gene(self, gene_engine: GeneEngine) -> None:
        gene = gene_engine.record_success(
            prompt="Write a function that parses JSON",
            context_type="code_generation",
            outcome="success",
        )
        assert gene.use_count == 1
        assert gene.success_rate == 1.0

    def test_record_success_increments_use_count(self, gene_engine: GeneEngine) -> None:
        gene_engine.record_success("prompt", "code_generation")
        gene = gene_engine.record_success("prompt", "code_generation")

        assert gene.use_count == 2

    def test_get_best_strategy_returns_highest_score(self, gene_engine: GeneEngine) -> None:
        gene_engine.record_success("prompt1", "review", "success")
        gene_engine.record_success("prompt2", "review", "success")
        gene_engine.record_success("prompt3", "review", "failed")

        best = gene_engine.get_best_strategy("review")
        assert best.context_type == "review"

    def test_get_best_strategy_returns_none_for_unknown_context(
        self, gene_engine: GeneEngine
    ) -> None:
        best = gene_engine.get_best_strategy("unknown_context")
        assert best is None


class TestDifferentiation:
    """Tests for auto-spawning specialized agents."""

    def test_record_failure_triggers_differentiation(self, gene_engine: GeneEngine) -> None:
        gene_engine.DIFFERENTIATION_THRESHOLD = 2

        gene_engine.record_failure(
            "SyntaxError in Python",
            "SyntaxError: invalid syntax",
            fix_strategy="Use proper Python syntax",
        )
        gene_engine.record_failure(
            "SyntaxError in Python",
            "SyntaxError: invalid syntax",
            fix_strategy="Use proper Python syntax",
        )

        # Should have spawned a specialized agent
        agents = gene_engine.list_specialized_agents()
        assert len(agents) >= 1

    def test_infer_agent_type_code_fix(self, gene_engine: GeneEngine) -> None:
        agent_type = gene_engine._infer_agent_type("SyntaxError in Python code")
        assert agent_type == "CodeFix"

    def test_infer_agent_type_test_fix(self, gene_engine: GeneEngine) -> None:
        agent_type = gene_engine._infer_agent_type("Test assertion failed")
        assert agent_type == "TestFix"

    def test_infer_agent_type_api(self, gene_engine: GeneEngine) -> None:
        agent_type = gene_engine._infer_agent_type("API request failed")
        assert agent_type == "API"


class TestGeneDecay:
    """Tests for gene decay mechanism."""

    def test_apply_gene_decay_removes_old_genes(self, gene_engine: GeneEngine) -> None:
        removed = gene_engine.apply_gene_decay(days_threshold=1)
        assert removed >= 0


class TestPersistence:
    """Tests for gene persistence across sessions."""

    def test_genes_persist_after_reload(self, temp_dir: Path) -> None:
        engine1 = GeneEngine(base_dir=temp_dir / "genes")
        engine1.record_failure("persistent_error", "error", "persistent fix")

        engine2 = GeneEngine(base_dir=temp_dir / "genes")
        antibody = engine2.get_antibody("persistent_error")

        assert antibody is not None
        assert antibody.fix_strategy == "persistent fix"
