"""TDD tests for persona_assembler.py — dynamic System Prompt from user preferences.

Phase 1: 千人千面管家
- P0: 用户偏好 (L2 PREFERENCES) → 动态 System Prompt 组装
- P0: 不同偏好用户 → 不同响应风格（陆总 brief vs 周局 high-detail）
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hermes_os.persona_assembler import PersonaAssembler, PersonaBlock

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_brain(tmp_path: Path) -> Path:
    """Create a temporary brain directory structure."""
    brain = tmp_path / "brain"
    brain.mkdir(parents=True, exist_ok=True)
    return brain


@pytest.fixture
def memory_hub_mock() -> MagicMock:
    """Create a mock MemoryHub that returns test user context."""
    hub = MagicMock()
    hub.get_preferences = AsyncMock(
        return_value={
            "communication_style": "neutral",
            "detail_level": "medium",
            "language": "auto",
            "tone": "neutral",
            "format": "markdown",
            "max_length": 2000,
            "timezone": "Asia/Shanghai",
            "active_hours": [9, 10, 11, 14, 15, 16, 17, 20, 21],
        }
    )
    hub.get_identity = AsyncMock(
        return_value={
            "name": "测试用户",
            "role": "user",
            "team": "default",
        }
    )
    return hub


# ---------------------------------------------------------------------------
# Unit tests: PersonaBlock dataclass
# ---------------------------------------------------------------------------


def test_persona_block_default_values() -> None:
    """PersonaBlock should have sensible defaults."""
    block = PersonaBlock()
    assert block.system_prefix == ""
    assert block.communication_style == "neutral"
    assert block.detail_level == "medium"
    assert block.tone == "neutral"
    assert block.format == "markdown"


def test_persona_block_full_init() -> None:
    """PersonaBlock should accept all fields."""
    block = PersonaBlock(
        system_prefix="<assistant>\n你是陆总的私人助理。\n</assistant>",
        communication_style="brief",
        detail_level="high",
        tone="direct",
        format="card",
    )
    assert block.communication_style == "brief"
    assert block.detail_level == "high"
    assert block.tone == "direct"


def test_persona_block_render() -> None:
    """PersonaBlock.render() should produce valid XML output."""
    block = PersonaBlock(
        system_prefix="<assistant>\n你是陆总的私人助理。\n</assistant>",
        communication_style="brief",
        detail_level="high",
        tone="direct",
        format="card",
    )
    rendered = block.render()

    assert "<assistant_persona>" in rendered
    assert "陆总" in rendered
    assert "brief" in rendered or "high" in rendered
    assert "</assistant_persona>" in rendered


# ---------------------------------------------------------------------------
# Unit tests: PersonaAssembler — communication style variants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assemble_brief_style_lu_zong(temp_brain: Path) -> None:
    """陆总偏好 (brief) → System Prompt 必须强调简洁、结论先行。

    RED phase: verify assemble() produces brief-style persona.
    """
    # GIVEN: 陆总的偏好设置 (matching PersonaAssembler's path structure)
    prefs_path = temp_brain / "lu_zong" / "brain" / "PREFERENCES.md"
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(
        '{"communication_style": "brief", "detail_level": "medium", "tone": "direct"}'
    )

    user_path = temp_brain / "lu_zong" / "brain" / "USER.md"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text("name：陆总\nrole：executive\nteam：leadership")

    assembler = PersonaAssembler(user_id="lu_zong", base_path=temp_brain)

    # WHEN: 组装性格 System Prompt
    block = await assembler.assemble()

    # THEN: 必须是 brief 风格
    assert block.communication_style == "brief"
    assert block.tone == "direct"
    rendered = block.render()

    # 验证核心指令：简洁、结论先行
    assert "简洁" in rendered or "brief" in rendered.lower()
    assert "结论" in rendered or "conclusion" in rendered.lower()


@pytest.mark.asyncio
async def test_assemble_high_detail_zhou_ju(temp_brain: Path) -> None:
    """周局偏好 (high detail) → System Prompt 必须强调严谨、依据、风险评估。

    RED phase: verify assemble() produces high-detail persona.
    """
    # GIVEN: 周局的偏好设置 (matching PersonaAssembler's path structure)
    prefs_path = temp_brain / "zhou_ju" / "brain" / "PREFERENCES.md"
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(
        '{"communication_style": "formal", "detail_level": "high", "tone": "conservative"}'
    )

    user_path = temp_brain / "zhou_ju" / "brain" / "USER.md"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text("name：周局\nrole：director\nteam：operations")

    assembler = PersonaAssembler(user_id="zhou_ju", base_path=temp_brain)

    # WHEN: 组装性格 System Prompt
    block = await assembler.assemble()

    # THEN: 必须是 high-detail 风格
    assert block.detail_level == "high"
    rendered = block.render()

    # 验证核心指令：详细、依据、风险评估
    assert "详细" in rendered or "detail" in rendered.lower() or "high" in rendered
    assert "依据" in rendered or "evidence" in rendered.lower() or "source" in rendered.lower()


@pytest.mark.asyncio
async def test_assemble_casual_style(temp_brain: Path) -> None:
    """casual 风格 → 可以更随意，用口语化表达。"""
    prefs_path = temp_brain / "xiao_wang" / "brain" / "PREFERENCES.md"
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(
        '{"communication_style": "casual", "detail_level": "low", "tone": "friendly"}'
    )

    user_path = temp_brain / "xiao_wang" / "brain" / "USER.md"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text("name：小王\nrole：engineer\nteam：backend")

    assembler = PersonaAssembler(user_id="xiao_wang", base_path=temp_brain)
    block = await assembler.assemble()

    assert block.communication_style == "casual"
    rendered = block.render()
    # casual 风格应该避免过于正式的表达
    assert "正式" not in rendered


# ---------------------------------------------------------------------------
# Unit tests: PersonaAssembler — format variants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assemble_markdown_format(temp_brain: Path) -> None:
    """format=markdown → 输出使用 markdown 格式。"""
    prefs_path = temp_brain / "test_md" / "brain" / "PREFERENCES.md"
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(
        '{"communication_style": "neutral", "detail_level": "medium", "format": "markdown"}'
    )

    user_path = temp_brain / "test_md" / "brain" / "USER.md"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text("name：测试\n")

    assembler = PersonaAssembler(user_id="test_md", base_path=temp_brain)
    block = await assembler.assemble()

    assert block.format == "markdown"
    rendered = block.render()
    assert "markdown" in rendered.lower() or "**" in rendered


@pytest.mark.asyncio
async def test_assemble_card_format(temp_brain: Path) -> None:
    """format=card → 输出使用卡片格式（适合飞书）。"""
    prefs_path = temp_brain / "test_card" / "brain" / "PREFERENCES.md"
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(
        '{"communication_style": "brief", "detail_level": "medium", "format": "card"}'
    )

    user_path = temp_brain / "test_card" / "brain" / "USER.md"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text("name：测试\n")

    assembler = PersonaAssembler(user_id="test_card", base_path=temp_brain)
    block = await assembler.assemble()

    assert block.format == "card"
    rendered = block.render()
    assert "card" in rendered.lower() or "📋" in rendered


# ---------------------------------------------------------------------------
# Unit tests: PersonaAssembler — language variants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assemble_zh_language(temp_brain: Path) -> None:
    """language=zh → System Prompt 使用中文指令。"""
    prefs_path = temp_brain / "test_zh" / "brain" / "PREFERENCES.md"
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(
        '{"communication_style": "neutral", "detail_level": "medium", "language": "zh"}'
    )

    user_path = temp_brain / "test_zh" / "brain" / "USER.md"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text("name：测试\n")

    assembler = PersonaAssembler(user_id="test_zh", base_path=temp_brain)
    block = await assembler.assemble()

    rendered = block.render()
    # 应该包含中文指令
    assert any(c >= "一" for c in rendered)


@pytest.mark.asyncio
async def test_assemble_en_language(temp_brain: Path) -> None:
    """language=en → System Prompt 使用英文指令。"""
    prefs_path = temp_brain / "test_en" / "brain" / "PREFERENCES.md"
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(
        '{"communication_style": "neutral", "detail_level": "medium", "language": "en"}'
    )

    user_path = temp_brain / "test_en" / "brain" / "USER.md"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text("name：Test\n")

    assembler = PersonaAssembler(user_id="test_en", base_path=temp_brain)
    block = await assembler.assemble()

    rendered = block.render()
    # 应该包含英文指令
    assert (
        rendered.count(" ") > 3
    )  # English sentence has spaces (at least 4: "You are Test's personal assistant.")


# ---------------------------------------------------------------------------
# Integration tests: PersonaAssembler with MemoryHub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assemble_with_memory_hub(memory_hub_mock: MagicMock) -> None:
    """PersonaAssembler should accept MemoryHub directly for context loading."""
    assembler = PersonaAssembler(
        user_id="test_hub_user",
        memory_hub=memory_hub_mock,
    )
    block = await assembler.assemble()

    # Verify MemoryHub was called
    memory_hub_mock.get_preferences.assert_called_once()
    memory_hub_mock.get_identity.assert_called_once()

    assert isinstance(block, PersonaBlock)
    assert block.communication_style == "neutral"


@pytest.mark.asyncio
async def test_assemble_graceful_fallback_no_preferences_file(
    tmp_path: Path, temp_brain: Path
) -> None:
    """When PREFERENCES.md doesn't exist, fall back to DEFAULT_PREFERENCES."""
    # No brain directory at all — user directory doesn't exist
    assembler = PersonaAssembler(user_id="brand_new_user", base_path=temp_brain)
    block = await assembler.assemble()

    # Should not raise, should use defaults
    assert block.communication_style == "neutral"  # DEFAULT
    assert block.detail_level == "medium"  # DEFAULT


# ---------------------------------------------------------------------------
# Unit tests: assemble() output structure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assemble_returns_valid_persona_block(temp_brain: Path) -> None:
    """assemble() must return a PersonaBlock with all required fields populated."""
    prefs_path = temp_brain / "zhang_zong" / "brain" / "PREFERENCES.md"
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text('{"communication_style": "brief", "detail_level": "high"}')

    user_path = temp_brain / "zhang_zong" / "brain" / "USER.md"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text("name：张总\n")

    assembler = PersonaAssembler(user_id="zhang_zong", base_path=temp_brain)
    block = await assembler.assemble()

    # Validate PersonaBlock structure
    assert isinstance(block, PersonaBlock)
    assert block.system_prefix
    assert block.communication_style == "brief"
    assert block.detail_level == "high"


@pytest.mark.asyncio
async def test_assemble_output_is_valid_xml_structure(temp_brain: Path) -> None:
    """render() output must be valid XML with matching tags."""
    prefs_path = temp_brain / "li_dong" / "brain" / "PREFERENCES.md"
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text('{"communication_style": "formal", "detail_level": "high"}')

    user_path = temp_brain / "li_dong" / "brain" / "USER.md"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text("name：李董\n")

    assembler = PersonaAssembler(user_id="li_dong", base_path=temp_brain)
    block = await assembler.assemble()
    rendered = block.render()

    # Count opening and closing tags
    assert rendered.count("<assistant_persona>") == 1
    assert rendered.count("</assistant_persona>") == 1
    assert rendered.count("<communication>") == 1
    assert rendered.count("</communication>") == 1
    assert rendered.count("<detail_level>") == 1
    assert rendered.count("</detail_level>") == 1


# ---------------------------------------------------------------------------
# Unit tests: different users get different personas
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_users_same_prefs_different_names(temp_brain: Path) -> None:
    """Two users with same preferences but different names → different personas."""
    prefs1 = temp_brain / "user_a" / "brain" / "PREFERENCES.md"
    prefs1.parent.mkdir(parents=True, exist_ok=True)
    prefs1.write_text('{"communication_style": "brief", "detail_level": "medium"}')

    user1 = temp_brain / "user_a" / "brain" / "USER.md"
    user1.write_text("name：陆总\n")

    prefs2 = temp_brain / "user_b" / "brain" / "PREFERENCES.md"
    prefs2.parent.mkdir(parents=True, exist_ok=True)
    prefs2.write_text('{"communication_style": "brief", "detail_level": "medium"}')

    user2 = temp_brain / "user_b" / "brain" / "USER.md"
    user2.write_text("name：周局\n")

    base = temp_brain.parent

    block_a = await PersonaAssembler(user_id="user_a", base_path=temp_brain).assemble()
    block_b = await PersonaAssembler(user_id="user_b", base_path=temp_brain).assemble()

    # Both should be brief, but names differ
    assert block_a.communication_style == "brief"
    assert block_b.communication_style == "brief"

    rendered_a = block_a.render()
    rendered_b = block_b.render()

    assert "陆总" in rendered_a
    assert "周局" in rendered_b
    assert rendered_a != rendered_b


# ---------------------------------------------------------------------------
# Unit tests: max_length respected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assemble_respects_max_length_from_preferences(temp_brain: Path) -> None:
    """PersonaBlock should carry max_length from preferences."""
    prefs_path = temp_brain / "jian_zong" / "brain" / "PREFERENCES.md"
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(
        '{"communication_style": "brief", "detail_level": "medium", "max_length": 500}'
    )

    user_path = temp_brain / "jian_zong" / "brain" / "USER.md"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text("name：简总\n")

    assembler = PersonaAssembler(user_id="jian_zong", base_path=temp_brain)
    block = await assembler.assemble()

    # max_length should be embedded in the rendered output
    rendered = block.render()
    assert "500" in rendered or "max" in rendered.lower()
