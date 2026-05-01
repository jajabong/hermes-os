"""Tests for Universal Long-Form Pipeline — Meta.json contract and PipelineEngine.

Tests:
1. Meta.json has required fields for pipeline state tracking
2. Pipeline.yaml can be parsed to get stage definitions
3. PipelineEngine state machine advances through 6 stages
4. Each stage produces verifiable output
5. Audit gate blocks progression if quality < 0.8
"""

import pytest
import asyncio
import tempfile
import json
import yaml
from pathlib import Path

from hermes_os.pipeline_engine_v2 import (
    PipelineConfig,
    PipelineStage,
    PipelineEngine,
    StageStatus,
    BatchBatchArtifactMeta,
    verify_outline_completeness,
    verify_evidence_density,
    verify_audit_score,
)


class TestBatchArtifactMeta:
    """Test BatchArtifactMeta is the universal contract for all pipeline artifacts."""

    def test_meta_has_required_fields(self) -> None:
        """Meta.json must have: artifact_id, title, audience, style, status, current_stage."""
        meta = BatchArtifactMeta(
            artifact_id="bp_001",
            title="商业计划书",
            target_audience="投资人",
            style="formal",
            current_stage="M1_OUTLINE",
            status="in_progress",
        )
        assert meta.artifact_id == "bp_001"
        assert meta.title == "商业计划书"
        assert meta.target_audience == "投资人"
        assert meta.style == "formal"
        assert meta.current_stage == "M1_OUTLINE"
        assert meta.status == "in_progress"

    def test_meta_stores_key_thesis(self) -> None:
        """key_thesis must be stored in meta for all artifact types."""
        meta = BatchArtifactMeta(
            artifact_id="bp_001",
            title="商业计划书",
            target_audience="投资人",
            style="formal",
            current_stage="M1_OUTLINE",
            status="in_progress",
            key_thesis=["数字经济", "产业升级"],
        )
        assert meta.key_thesis == ["数字经济", "产业升级"]

    def test_meta_persists_to_json(self) -> None:
        """Meta.json must be parseable JSON for inter-op."""
        meta = BatchArtifactMeta(
            artifact_id="bp_001",
            title="商业计划书",
            target_audience="投资人",
            style="formal",
            current_stage="M1_OUTLINE",
            status="in_progress",
            key_thesis=["数字经济"],
        )
        json_str = meta.to_json()
        parsed = json.loads(json_str)
        assert parsed["artifact_id"] == "bp_001"
        assert parsed["key_thesis"] == ["数字经济"]


class TestPipelineConfig:
    """Test PipelineConfig parses Pipeline.yaml correctly."""

    def test_parses_pipeline_yaml(self) -> None:
        """PipelineConfig should parse a valid Pipeline.yaml structure."""
        yaml_content = """
name: "Universal-Long-Form-Generation"
description: "通用长文生成流水线：从意图解析到最终交付"
steps:
  - stage: M1_OUTLINE
    labor: "ContentLabor"
    task: "Generate structured outline"
    verify: "check_structure_completeness"
  - stage: M2_RESEARCH
    labor: "ResearchLabor"
    task: "Retrieve context from wikis"
    verify: "check_evidence_density"
"""
        config = PipelineConfig.from_yaml(yaml_content)
        assert config.name == "Universal-Long-Form-Generation"
        assert len(config.steps) == 2
        assert config.steps[0].stage == "M1_OUTLINE"
        assert config.steps[0].labor == "ContentLabor"
        assert config.steps[0].verify == "check_structure_completeness"

    def test_sequential_stages_defined(self) -> None:
        """All 6 stages must be defined in sequence."""
        yaml_content = """
name: "Universal-Long-Form-Generation"
description: "Test"
steps:
  - stage: M1_OUTLINE
    labor: "ContentLabor"
    task: "Outline"
    verify: "check_outline"
  - stage: M2_RESEARCH
    labor: "ResearchLabor"
    task: "Research"
    verify: "check_research"
  - stage: M3_DRAFTING
    labor: "ContentLabor"
    task: "Draft"
    verify: "check_draft"
  - stage: M4_RENDERING
    labor: "FormatLabor"
    task: "Render"
    verify: "check_rendering"
  - stage: M5_AUDIT
    labor: "CheckerLabor"
    task: "Audit"
    verify: "check_audit_score"
  - stage: M6_DELIVERY
    labor: "FeishuLabor"
    task: "Deliver"
    verify: "check_delivery"
"""
        config = PipelineConfig.from_yaml(yaml_content)
        assert len(config.steps) == 6
        stage_names = [s.stage for s in config.steps]
        assert stage_names == ["M1_OUTLINE", "M2_RESEARCH", "M3_DRAFTING", "M4_RENDERING", "M5_AUDIT", "M6_DELIVERY"]


class TestPipelineEngine:
    """Test PipelineEngine state machine."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.fixture
    def pipeline_yaml(self) -> str:
        return """
name: "Universal-Long-Form-Generation"
description: "Test pipeline"
steps:
  - stage: M1_OUTLINE
    labor: "ContentLabor"
    task: "Generate outline"
    verify: "check_structure_completeness"
  - stage: M2_RESEARCH
    labor: "ResearchLabor"
    task: "Research"
    verify: "check_evidence_density"
  - stage: M3_DRAFTING
    labor: "ContentLabor"
    task: "Draft"
    verify: "check_tone_consistency"
  - stage: M4_RENDERING
    labor: "FormatLabor"
    task: "Render"
    verify: "check_rendering_integrity"
  - stage: M5_AUDIT
    labor: "CheckerLabor"
    task: "Audit"
    verify: "check_audit_score"
  - stage: M6_DELIVERY
    labor: "FeishuLabor"
    task: "Deliver"
    verify: "check_delivery"
"""

    @pytest.mark.asyncio
    async def test_engine_starts_at_m1_outline(self, temp_dir: str, pipeline_yaml: str) -> None:
        """Engine should initialize at M1_OUTLINE."""
        config = PipelineConfig.from_yaml(pipeline_yaml)
        meta = BatchArtifactMeta(
            artifact_id="doc_001",
            title="测试文档",
            target_audience="领导层",
            style="formal",
            current_stage="M1_OUTLINE",
            status="in_progress",
        )
        engine = PipelineEngine(config=config, meta=meta, base_dir=temp_dir)
        assert engine.current_stage == "M1_OUTLINE"
        assert engine.status == StageStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_engine_advances_to_next_stage(self, temp_dir: str, pipeline_yaml: str) -> None:
        """After successful stage completion, engine advances to next stage."""
        config = PipelineConfig.from_yaml(pipeline_yaml)
        meta = BatchArtifactMeta(
            artifact_id="doc_001",
            title="测试文档",
            target_audience="领导层",
            style="formal",
            current_stage="M1_OUTLINE",
            status="in_progress",
        )
        engine = PipelineEngine(config=config, meta=meta, base_dir=temp_dir)
        await engine.advance_stage()
        assert engine.current_stage == "M2_RESEARCH"

    @pytest.mark.asyncio
    async def test_engine_blocks_on_audit_failure(self, temp_dir: str, pipeline_yaml: str) -> None:
        """Engine should not advance past M5_AUDIT if audit score < 0.8."""
        config = PipelineConfig.from_yaml(pipeline_yaml)
        meta = BatchArtifactMeta(
            artifact_id="doc_001",
            title="测试文档",
            target_audience="领导层",
            style="formal",
            current_stage="M5_AUDIT",
            status="in_progress",
        )
        engine = PipelineEngine(config=config, meta=meta, base_dir=temp_dir)
        result = await engine.execute_current_stage(audit_score=0.5)
        assert result.passed is False
        assert engine.current_stage == "M5_AUDIT"

    @pytest.mark.asyncio
    async def test_engine_advances_on_audit_pass(self, temp_dir: str, pipeline_yaml: str) -> None:
        """Engine should advance from M5_AUDIT when audit score >= 0.8."""
        config = PipelineConfig.from_yaml(pipeline_yaml)
        meta = BatchArtifactMeta(
            artifact_id="doc_001",
            title="测试文档",
            target_audience="领导层",
            style="formal",
            current_stage="M5_AUDIT",
            status="in_progress",
        )
        engine = PipelineEngine(config=config, meta=meta, base_dir=temp_dir)
        result = await engine.execute_current_stage(audit_score=0.85)
        assert result.passed is True
        assert engine.current_stage == "M6_DELIVERY"

    @pytest.mark.asyncio
    async def test_engine_completes_at_final_stage(self, temp_dir: str, pipeline_yaml: str) -> None:
        """Engine should mark as completed after M6_DELIVERY."""
        config = PipelineConfig.from_yaml(pipeline_yaml)
        meta = BatchArtifactMeta(
            artifact_id="doc_001",
            title="测试文档",
            target_audience="领导层",
            style="formal",
            current_stage="M6_DELIVERY",
            status="in_progress",
        )
        engine = PipelineEngine(config=config, meta=meta, base_dir=temp_dir)
        await engine.advance_stage()
        assert engine.status == StageStatus.COMPLETED
        assert engine.current_stage == "M6_DELIVERY"

    @pytest.mark.asyncio
    async def test_meta_json_persists_after_advance(self, temp_dir: str, pipeline_yaml: str) -> None:
        """meta.json should be updated after each stage advance."""
        config = PipelineConfig.from_yaml(pipeline_yaml)
        meta = BatchArtifactMeta(
            artifact_id="doc_001",
            title="测试文档",
            target_audience="领导层",
            style="formal",
            current_stage="M1_OUTLINE",
            status="in_progress",
        )
        engine = PipelineEngine(config=config, meta=meta, base_dir=temp_dir)
        await engine.advance_stage()

        meta_path = Path(temp_dir) / "doc_001" / "meta.json"
        assert meta_path.exists()
        saved = json.loads(meta_path.read_text())
        assert saved["current_stage"] == "M2_RESEARCH"


class TestStageVerification:
    """Test each stage's verification function."""

    @pytest.fixture
    def temp_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_outline_structure_check(self, temp_dir: str) -> None:
        """M1_OUTLINE verify should check for hollow sections."""
        good_outline = """
# 一、概述
## 1.1 背景
## 1.2 目标
# 二、市场分析
## 2.1 市场规模
## 2.2 竞争格局
"""
        result = await verify_outline_completeness(good_outline)
        assert result.passed is True

        hollow_outline = """
# 一、概述
# 二、市场分析
# 三、竞争分析
"""
        result = await verify_outline_completeness(hollow_outline)
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_evidence_density_check(self, temp_dir: str) -> None:
        """M2_RESEARCH verify should check evidence density."""
        good_research = """
数据来源：国家统计局2023年报告
引用：Smith et al. (2022) 指出，全球数字经济规模已达数万亿美元
统计：2023年市场规模达5000亿元，同比增长15%
根据艾瑞咨询数据显示，我国数字经济占GDP比重超过40%
"""
        result = await verify_evidence_density(good_research)
        assert result.passed is True

        poor_research = """
市场非常大。增长非常快。前景非常广阔。
这是一个非常棒的报告，包含了很多重要的信息。
整体来看，各个方面都表现得非常优秀。
"""
        result = await verify_evidence_density(poor_research)
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_audit_score_threshold(self, temp_dir: str) -> None:
        """M5_AUDIT verify should enforce 0.8 threshold."""
        result = await verify_audit_score(0.79)
        assert result.passed is False

        result = await verify_audit_score(0.8)
        assert result.passed is True

        result = await verify_audit_score(0.95)
        assert result.passed is True