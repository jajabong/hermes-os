"""Tests for QA-Closed Loop — Spec Gate (规格约束层).

Tests that:
1. Artifact has .spec file generated before writing begins
2. SpecCheck verifies spec before ContentLabor starts
3. SpecCheck rejects specs that are incomplete/ambiguous
4. Spec is stored at the same level as the artifact
"""

import tempfile
from pathlib import Path

import pytest

from hermes_os.qa_closed_loop import (
    ContentArtifact,
    Spec,
    SpecGate,
    SpecNotApprovedError,
    SpecValidator,
)


class TestSpecGate:
    """Test SpecGate creates and validates artifact specs."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil

        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_spec_generated_before_content(self, temp_dir: str) -> None:
        """Spec must exist BEFORE ContentLabor writes content."""
        gate = SpecGate(base_dir=temp_dir)
        spec = await gate.create_spec(
            artifact_id="doc_001",
            title="一季度经济分析报告",
            target_audience="领导层",
            key_thesis=["数字经济", "产业升级"],
            style="formal",
        )
        # Spec should be saved to .spec.json BEFORE any content exists
        spec_path = Path(temp_dir) / "doc_001" / "artifact.spec.json"
        assert spec_path.exists()

    @pytest.mark.asyncio
    async def test_spec_validates_before_content_labor(self, temp_dir: str) -> None:
        """SpecCheck must pass before ContentLabor is authorized to start."""
        gate = SpecGate(base_dir=temp_dir)
        spec = await gate.create_spec(
            artifact_id="doc_001",
            title="供应商对比分析",
            target_audience="投资委员会",
            key_thesis=["A供应商成本低", "B供应商质量高"],
            style="analysis",
        )
        # Validator should return passed=True
        validator = SpecValidator()
        result = await validator.validate(spec)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_spec_rejects_empty_thesis(self, temp_dir: str) -> None:
        """Spec with empty key_thesis should be REJECTED by gate."""
        gate = SpecGate(base_dir=temp_dir)
        spec = await gate.create_spec(
            artifact_id="doc_001",
            title="报告",
            target_audience="领导",
            key_thesis=[],  # Empty thesis = ambiguous
            style="formal",
        )
        validator = SpecValidator()
        result = await validator.validate(spec)
        assert result.passed is False
        assert "key_thesis" in result.errors

    @pytest.mark.asyncio
    async def test_spec_rejects_ambiguous_title(self, temp_dir: str) -> None:
        """Spec with too-short title should be REJECTED."""
        gate = SpecGate(base_dir=temp_dir)
        spec = await gate.create_spec(
            artifact_id="doc_001",
            title="报告",  # Too generic
            target_audience="领导",
            key_thesis=["论点1", "论点2"],
            style="formal",
        )
        validator = SpecValidator()
        result = await validator.validate(spec)
        assert result.passed is False
        assert any("title" in e.lower() for e in result.errors)


class TestContentArtifact:
    """Test ContentArtifact creation with spec gate."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil

        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_artifact_requires_spec_before_content(self, temp_dir: str) -> None:
        """Artifact.content should NOT be writable until spec is validated."""
        gate = SpecGate(base_dir=temp_dir)
        artifact = ContentArtifact(
            artifact_id="doc_001",
            base_dir=temp_dir,
        )
        # Trying to write content without spec should fail
        try:
            await artifact.write_content("some content")
            assert False, "Should have raised SpecNotApprovedError"
        except SpecNotApprovedError:
            pass  # Expected

    @pytest.mark.asyncio
    async def test_artifact_writes_after_spec_approved(self, temp_dir: str) -> None:
        """Once spec is approved, content write should succeed."""
        gate = SpecGate(base_dir=temp_dir)
        spec = await gate.create_spec(
            artifact_id="doc_001",
            title="一季度经济分析报告",
            target_audience="领导层",
            key_thesis=["数字经济"],
            style="formal",
        )
        validator = SpecValidator()
        validation = await validator.validate(spec)
        assert validation.passed

        artifact = ContentArtifact(artifact_id="doc_001", base_dir=temp_dir)
        artifact.approve_spec(spec, validation)
        await artifact.write_content("这是报告正文...")
        content_path = Path(temp_dir) / "doc_001" / "artifact.md"
        assert content_path.exists()


class TestSpecStructure:
    """Test that Spec has required fields."""

    def test_spec_has_required_fields(self) -> None:
        spec = Spec(
            artifact_id="test",
            title="Test Report",
            target_audience="leaders",
            key_thesis=["thesis1"],
            style="formal",
        )
        assert spec.artifact_id == "test"
        assert spec.title == "Test Report"
        assert spec.target_audience == "leaders"
        assert spec.key_thesis == ["thesis1"]
        assert spec.style == "formal"

    def test_spec_optional_fields_default(self) -> None:
        spec = Spec(
            artifact_id="test",
            title="Report",
            target_audience="leaders",
            key_thesis=["t"],
            style="formal",
        )
        assert spec.word_count_target is None
        assert spec.deadline is None
        assert spec.metadata == {}
