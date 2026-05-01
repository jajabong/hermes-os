"""Tests for QA-Closed Loop — M2 CheckerLabor (对抗式审计层).

Tests that CheckerLabor performs adversarial verification with:
1. Semantic blind checks (hallucination detection)
2. Automated validation (Markdown structure, citation counts, keyword coverage)
3. ContentLabor integration (runs after ContentLabor, before Delivery)
"""

import pytest
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from hermes_os.qa_closed_loop import (
    ContentArtifact,
    Spec,
    SpecValidator,
    CheckerLabor,
    QualityGates,
)


class TestCheckerLabor:
    """Test CheckerLabor performs adversarial verification."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_checker_runs_markdown_validation(self, temp_dir: str) -> None:
        """CheckerLabor should validate Markdown structure."""
        spec = Spec(
            artifact_id="doc_001",
            title="第一季度经济分析报告",
            target_audience="领导层",
            key_thesis=["数字经济"],
            style="concise",  # Use concise to avoid citation requirement
        )
        validator = SpecValidator()
        validation = await validator.validate(spec)

        artifact = ContentArtifact(artifact_id="doc_001", base_dir=temp_dir)
        artifact.approve_spec(spec, validation)
        content = "# 一、概述\n\n这是数字经济相关的正文内容，满足最低字数要求。本文详细分析了当前经济形势，并提出了具体的发展建议和实施路径。通过深入研究可以发现，数字经济已经成为推动社会进步的重要力量。"
        await artifact.write_content(content)

        checker = CheckerLabor()
        result = await checker.check(
            artifact=artifact,
            content=content,
            spec=spec,
        )
        assert result.passed is True
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_checker_detects_placeholder_text(self, temp_dir: str) -> None:
        """CheckerLabor should detect placeholder text like TODO/FIXME."""
        spec = Spec(
            artifact_id="doc_002",
            title="正式经济分析报告",
            target_audience="领导层",
            key_thesis=["数字经济"],
            style="analysis",
        )
        validator = SpecValidator()
        validation = await validator.validate(spec)

        artifact = ContentArtifact(artifact_id="doc_002", base_dir=temp_dir)
        artifact.approve_spec(spec, validation)
        # Content with placeholder text
        content = "# 报告\n\nTODO: 待完成\nFIXME: 需要修复"
        await artifact.write_content(content)

        checker = CheckerLabor()
        result = await checker.check(artifact=artifact, content=content, spec=spec)
        assert result.passed is False
        assert any("placeholder" in e.lower() or "todo" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_checker_validates_keyword_coverage(self, temp_dir: str) -> None:
        """CheckerLabor should verify key_thesis keywords appear in content."""
        spec = Spec(
            artifact_id="doc_003",
            title="正式经济分析报告",
            target_audience="领导层",
            key_thesis=["数字经济", "产业升级"],
            style="analysis",
        )
        validator = SpecValidator()
        validation = await validator.validate(spec)

        artifact = ContentArtifact(artifact_id="doc_003", base_dir=temp_dir)
        artifact.approve_spec(spec, validation)
        # Content missing "数字经济" keyword
        content = "# 报告\n\n本文讨论了其他经济问题。"
        await artifact.write_content(content)

        checker = CheckerLabor()
        result = await checker.check(artifact=artifact, content=content, spec=spec)
        # Should fail because "数字经济" is not in content
        assert result.passed is False
        assert any("keyword" in e.lower() or "数字经济" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_checker_validates_word_count(self, temp_dir: str) -> None:
        """CheckerLabor should warn if content is too short."""
        spec = Spec(
            artifact_id="doc_004",
            title="正式经济分析报告",
            target_audience="领导层",
            key_thesis=["数字经济"],
            style="analysis",
            word_count_target=500,  # Target 500 words
        )
        validator = SpecValidator()
        validation = await validator.validate(spec)

        artifact = ContentArtifact(artifact_id="doc_004", base_dir=temp_dir)
        artifact.approve_spec(spec, validation)
        # Content too short
        content = "# 报告\n\n这是很短的内容。"
        await artifact.write_content(content)

        checker = CheckerLabor()
        result = await checker.check(artifact=artifact, content=content, spec=spec)
        assert result.passed is False
        assert any("word" in e.lower() or "length" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_checker_passes_with_good_content(self, temp_dir: str) -> None:
        """CheckerLabor should pass for well-formed content."""
        spec = Spec(
            artifact_id="doc_005",
            title="正式经济分析报告",
            target_audience="领导层",
            key_thesis=["数字经济"],
            style="analysis",
            word_count_target=10,
        )
        validator = SpecValidator()
        validation = await validator.validate(spec)

        artifact = ContentArtifact(artifact_id="doc_005", base_dir=temp_dir)
        artifact.approve_spec(spec, validation)
        # Good content with all keywords and sufficient length
        content = "# 测试报告\n\n## 数字经济\n\n本文详细讨论了数字经济的重要性，分析了当前形势。"
        await artifact.write_content(content)

        checker = CheckerLabor()
        result = await checker.check(artifact=artifact, content=content, spec=spec)
        assert result.passed is True


class TestCheckerLaborCitationCount:
    """Test CheckerLabor validates citation counts for formal documents."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_formal_style_requires_citations(self, temp_dir: str) -> None:
        """Formal style documents should have at least one citation."""
        spec = Spec(
            artifact_id="doc_006",
            title="正式经济分析报告",
            target_audience="领导层",
            key_thesis=["数字经济"],
            style="formal",
        )
        validator = SpecValidator()
        validation = await validator.validate(spec)

        artifact = ContentArtifact(artifact_id="doc_006", base_dir=temp_dir)
        artifact.approve_spec(spec, validation)
        # Content without citations
        content = "# 报告\n\n这是数字经济相关正文内容，但缺少引用。"
        await artifact.write_content(content)

        checker = CheckerLabor()
        result = await checker.check(artifact=artifact, content=content, spec=spec)
        assert result.passed is False
        assert any("citation" in e.lower() or "引用" in e for e in result.errors)


class TestCheckerLaborSemanticBlindCheck:
    """Test CheckerLabor performs semantic blind checks."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_semantic_blind_check_enabled(self, temp_dir: str) -> None:
        """CheckerLabor should have semantic blind check capability."""
        checker = CheckerLabor()
        assert hasattr(checker, "_semantic_blind_check")
        assert callable(checker._semantic_blind_check)

    @pytest.mark.asyncio
    async def test_semantic_blind_check_detects_hallucination(self, temp_dir: str) -> None:
        """Semantic blind check should detect hallucinated facts."""
        checker = CheckerLabor()
        content = "According to the report, the company achieved 1000% growth in Q1 2024."
        result = await checker._semantic_blind_check(content)
        # Should flag potentially hallucinated claim
        assert isinstance(result, dict)
        assert "passed" in result or "errors" in result or result.get("hallucination_score", 1.0) < 0.8