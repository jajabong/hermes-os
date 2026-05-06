"""TDD tests for PersonaAssembler integration into gateway_hook handle().

Tests what needs to be built:
1. gateway_hook.handle() calls PersonaAssembler and prepends <assistant_persona> to message
2. Per-user preferences (communication_style, detail_level, tone) are reflected in the persona block
3. Falls back to defaults when no user preferences exist
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hermes_os.persona_assembler import PersonaAssembler


@pytest.mark.asyncio
async def test_persona_assembler_loads_preferences_from_brain_files(tmp_path: Path) -> None:
    """PersonaAssembler reads brain/PREFERENCES.md and brain/USER.md."""
    user_id = "alice"
    base = tmp_path / ".hermes" / "users" / user_id
    brain = base / "brain"
    brain.mkdir(parents=True)

    # Write preferences
    (brain / "PREFERENCES.md").write_text('{"communication_style": "brief", "detail_level": "low"}')
    # Write identity (uses Chinese colon "：" to match parser in persona_assembler.py)
    (brain / "USER.md").write_text("name：Alice\nrole：Engineer\n")

    assembler = PersonaAssembler(user_id=user_id, base_path=tmp_path / ".hermes" / "users")
    block = await assembler.assemble()

    assert block.communication_style == "brief"
    assert block.detail_level == "low"
    assert "Alice" in block.system_prefix


@pytest.mark.asyncio
async def test_persona_assembler_falls_back_to_defaults(tmp_path: Path) -> None:
    """PersonaAssembler uses defaults when brain files don't exist."""
    assembler = PersonaAssembler(user_id="nobody", base_path=tmp_path / ".hermes" / "users")
    block = await assembler.assemble()

    assert block.communication_style == "neutral"
    assert block.detail_level == "medium"
    assert block.tone == "neutral"


@pytest.mark.asyncio
async def test_persona_assembler_brief_style_produces_conclusion_first_directive(
    tmp_path: Path,
) -> None:
    """brief + direct style generates 'conclusion first' system directive."""
    user_id = "boss"
    base = tmp_path / ".hermes" / "users" / user_id
    brain = base / "brain"
    brain.mkdir(parents=True)

    (brain / "PREFERENCES.md").write_text(
        '{"communication_style": "brief", "detail_level": "medium", "tone": "direct"}'
    )
    (brain / "USER.md").write_text("name: 陆总\n")

    assembler = PersonaAssembler(user_id=user_id, base_path=tmp_path / ".hermes" / "users")
    block = await assembler.assemble()

    rendered = block.render()
    assert "结论先行" in rendered or "conclusion" in rendered.lower()


@pytest.mark.asyncio
async def test_persona_assembler_high_detail_produces_rigorous_directive(tmp_path: Path) -> None:
    """high detail + conservative tone generates rigorous citation directive."""
    user_id = "analyst"
    base = tmp_path / ".hermes" / "users" / user_id
    brain = base / "brain"
    brain.mkdir(parents=True)

    (brain / "PREFERENCES.md").write_text(
        '{"communication_style": "formal", "detail_level": "high", "tone": "conservative"}'
    )
    (brain / "USER.md").write_text("name: 周局\n")

    assembler = PersonaAssembler(user_id=user_id, base_path=tmp_path / ".hermes" / "users")
    block = await assembler.assemble()

    rendered = block.render()
    assert "严谨" in rendered or "rigorous" in rendered.lower()
    assert "<detail_level>high</detail_level>" in rendered


@pytest.mark.asyncio
async def test_persona_assembler_render_produces_valid_xml_block(tmp_path: Path) -> None:
    """PersonaBlock.render() produces a valid XML block with required fields."""
    assembler = PersonaAssembler(user_id="test", base_path=tmp_path / ".hermes" / "users")
    block = await assembler.assemble()

    rendered = block.render()
    assert "<assistant_persona>" in rendered
    assert "<system_instructions>" in rendered
    assert "<communication>" in rendered
    assert "<detail_level>" in rendered
    assert "<tone>" in rendered
    assert "<format>" in rendered
    assert "<max_length>" in rendered
    assert "</assistant_persona>" in rendered


@pytest.mark.asyncio
async def test_gateway_hook_injects_persona_block_in_handle(
    tmp_path: Path,
) -> None:
    """gateway_hook.handle() prepends <assistant_persona> block to the message."""
    from hermes_os.gateway_hook import GatewayEvent, HermesOSHook, HookConfig

    # Create a minimal brain with user preferences
    user_id = "alice_test"
    brain = tmp_path / ".hermes" / "users" / user_id / "brain"
    brain.mkdir(parents=True)
    (brain / "PREFERENCES.md").write_text(
        '{"communication_style": "brief", "detail_level": "low", "tone": "direct"}'
    )
    (brain / "USER.md").write_text("name: Alice\n")

    # Create hook with in-memory DBs
    config = HookConfig(
        db_path=str(tmp_path / "test.db"),
        knowledge_db_path=str(tmp_path / "test_knowledge.db"),
        enable_event_loop=False,
    )
    hook = HermesOSHook(config=config)

    # Create gateway event and context (set text attribute as hermes-agent does)
    event = GatewayEvent(
        platform="feishu",
        platform_user_id="alice_test",
        message="帮我看看项目进度",
        user_name="Alice",
        user_id_alt="alice_test",
    )
    event.text = "帮我看看项目进度"  # hermes-agent sets this dynamically
    context = {"event": event, "platform": "feishu", "user_id": "alice_test"}

    # Mock the internal router to return a mock user
    mock_user = MagicMock()
    mock_user.user_id = user_id
    mock_user.name = "Alice"

    mock_routed = MagicMock()
    mock_routed.user = mock_user
    mock_routed.enriched_message = "帮我看看项目进度"  # raw message enriched

    # Patch router.route to return our mock
    original_get_router = hook._get_router

    async def mock_get_router():
        router = await original_get_router()
        router.route = AsyncMock(return_value=mock_routed)
        return router

    hook._get_router = mock_get_router

    # Mock chief agent and _process_intent_and_schedule to avoid side effects
    hook._chief = AsyncMock()
    hook._process_intent_and_schedule = AsyncMock()

    # Call handle
    await hook.handle("agent:start", context)

    # Verify <assistant_persona> block was prepended
    assert "<assistant_persona>" in event.text
    assert "<system_instructions>" in event.text
    assert "<communication>" in event.text
    # Owner falls back to "用户" when ~/.hermes/users/{user_id}/brain/USER.md doesn't exist
    assert "用户" in event.text or "Alice" in event.text
