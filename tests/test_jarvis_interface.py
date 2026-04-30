"""Tests for JarvisInterface — unified outbound communication."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from hermes_os.jarvis_interface import JarvisInterface


class TestJarvisInterfaceCardWithNl:
    """Tests for send_card_with_nl."""

    @pytest.mark.asyncio
    async def test_send_card_saves_to_user_file(self) -> None:
        """Card is sent via Feishu and persisted to user file directory."""
        jarvis = JarvisInterface()
        jarvis._feishu = MagicMock()
        jarvis._feishu.send_action_card = AsyncMock()
        jarvis._files = MagicMock()
        jarvis._files.save_card = AsyncMock()

        await jarvis.send_card_with_nl(
            user_id="ou_abc123",
            title="Test Card",
            content="Hello **world**",
            actions=[{"text": "Run", "value": "run_now", "type": "primary", "task_id": "t-001"}],
            nl_summary="Test card sent",
            task_id="t-001",
        )

        jarvis._feishu.send_action_card.assert_called_once()
        jarvis._files.save_card.assert_called_once_with(
            user_id="ou_abc123",
            task_id="t-001",
            card_payload=jarvis._build_card("Test Card", "Hello **world**", [
                {"text": "Run", "value": "run_now", "type": "primary", "task_id": "t-001"}
            ]),
            nl_summary="Test card sent",
        )

    @pytest.mark.asyncio
    async def test_send_card_without_task_id_does_not_save(self) -> None:
        """Card is sent but not saved when task_id is None."""
        jarvis = JarvisInterface()
        jarvis._feishu = MagicMock()
        jarvis._feishu.send_action_card = AsyncMock()
        jarvis._files = MagicMock()
        jarvis._files.save_card = AsyncMock()

        await jarvis.send_card_with_nl(
            user_id="ou_abc123",
            title="No Task Card",
            content="Just a card",
            actions=[],
            nl_summary="No task",
            task_id=None,
        )

        jarvis._feishu.send_action_card.assert_called_once()
        jarvis._files.save_card.assert_not_called()


class TestJarvisInterfaceConfirmation:
    """Tests for send_confirmation_request."""

    @pytest.mark.asyncio
    async def test_send_confirmation_has_accept_and_decline(self) -> None:
        """Confirmation card has Accept + Decline buttons."""
        jarvis = JarvisInterface()
        jarvis._feishu = MagicMock()
        jarvis._feishu.send_action_card = AsyncMock()
        jarvis._files = MagicMock()
        jarvis._files.save_card = AsyncMock()

        await jarvis.send_confirmation_request(
            user_id="ou_abc123",
            question="Execute task t-001?",
            task_id="t-001",
        )

        call_kwargs = jarvis._feishu.send_action_card.call_args.kwargs
        actions = call_kwargs["actions"]
        action_values = [a["value"] for a in actions]

        assert "run_now" in action_values  # Accept
        assert "stop_task" in action_values  # Decline


class TestJarvisInterfaceProgress:
    """Tests for send_progress_update."""

    @pytest.mark.asyncio
    async def test_progress_update_contains_percentage(self) -> None:
        """Progress update NL message contains correct percentage."""
        jarvis = JarvisInterface()
        jarvis._feishu = MagicMock()
        jarvis._feishu.send_message_to_user = AsyncMock()
        jarvis._files = MagicMock()
        jarvis._files.save_card = AsyncMock()

        await jarvis.send_progress_update(
            user_id="ou_abc123",
            task_title="Fix bug",
            progress=0.75,
            detail="Step 2/3",
            task_id="t-002",
        )

        msg_call = jarvis._feishu.send_message_to_user.call_args
        message = msg_call.kwargs.get("message") or msg_call[1].get("message")
        assert "[75%]" in message
        assert "Fix bug" in message


class TestBuildCard:
    """Tests for _build_card."""

    def test_build_card_structure(self) -> None:
        """Card has correct Feishu Message Card structure."""
        jarvis = JarvisInterface()
        card = jarvis._build_card(
            title="Test Title",
            content="Some **content**",
            actions=[{"text": "OK", "value": "ok", "type": "primary", "task_id": "t-1"}],
        )

        assert card["config"]["wide_screen_mode"] is True
        assert card["header"]["title"]["content"] == "Test Title"
        assert card["header"]["template"] == "blue"
        assert len(card["elements"]) == 2
        assert card["elements"][1]["tag"] == "action"

    def test_build_card_action_button_format(self) -> None:
        """Button action value contains hermes_action and task_id."""
        jarvis = JarvisInterface()
        card = jarvis._build_card(
            title="T",
            content="C",
            actions=[{"text": "Run", "value": "run_now", "type": "primary", "task_id": "t-99"}],
        )

        btn = card["elements"][1]["actions"][0]
        assert btn["tag"] == "button"
        assert btn["value"]["hermes_action"] == "run_now"
        assert btn["value"]["task_id"] == "t-99"