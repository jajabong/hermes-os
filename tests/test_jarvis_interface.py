"""Tests for JarvisInterface — unified outbound communication."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from hermes_os.emotion_engine import EmotionState
from hermes_os.emotion_types import TonePreference
from hermes_os.jarvis_interface import JarvisInterface
from hermes_os.personality_tuner import PersonalityTuner


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
        jarvis._files.save_card.assert_called_once()
        # With default emotion=NEUTRAL and preference=RELAXED, emoji prefix added
        saved_nl = jarvis._files.save_card.call_args[1]["nl_summary"]
        assert "Test card sent" in saved_nl

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


# ---------------------------------------------------------------------------
# PersonalityTuner integration tests
# ---------------------------------------------------------------------------

class TestPersonalityTunerIntegration:
    """Tests for PersonalityTuner integration in JarvisInterface."""

    @pytest.mark.asyncio
    async def test_send_completion_formats_with_personality_tuner(self) -> None:
        """send_completion_notification formats nl via PersonalityTuner."""
        jarvis = JarvisInterface()
        jarvis._feishu = MagicMock()
        jarvis._feishu.send_message_to_user = AsyncMock()
        jarvis._files = MagicMock()
        jarvis._files.save_card = AsyncMock()

        await jarvis.send_completion_notification(
            user_id="ou_abc123",
            task_title="项目报告",
            result_summary="已完成数据整理",
            task_id="t-003",
            emotion=EmotionState.POSITIVE,
            preference=TonePreference.RELAXED,
        )

        msg_call = jarvis._feishu.send_message_to_user.call_args
        message = msg_call.kwargs.get("message") or msg_call[1].get("message")
        # RELAXED + POSITIVE should add emoji
        assert "项目报告" in message
        assert "已完成数据整理" in message

    @pytest.mark.asyncio
    async def test_send_failure_formats_with_personality_tuner(self) -> None:
        """send_failure_notification uses PersonalityTuner for encouraging tone."""
        jarvis = JarvisInterface()
        jarvis._feishu = MagicMock()
        jarvis._feishu.send_message_to_user = AsyncMock()
        jarvis._files = MagicMock()
        jarvis._files.save_card = AsyncMock()

        await jarvis.send_failure_notification(
            user_id="ou_abc123",
            task_title="数据分析",
            error_summary="数据源不可达",
            task_id="t-004",
            emotion=EmotionState.FRUSTRATED,
            preference=TonePreference.RELAXED,
        )

        msg_call = jarvis._feishu.send_message_to_user.call_args
        message = msg_call.kwargs.get("message") or msg_call[1].get("message")
        # FRUSTRATED emotion should add encouraging phrase
        assert "数据分析" in message
        assert "数据源不可达" in message
        assert ("一起" in message or "加油" in message or "别担心" in message or "没关系" in message)

    @pytest.mark.asyncio
    async def test_send_progress_shortens_when_stressed(self) -> None:
        """send_progress_update shortens message when user is STRESSED."""
        jarvis = JarvisInterface()
        jarvis._feishu = MagicMock()
        jarvis._feishu.send_message_to_user = AsyncMock()
        jarvis._files = MagicMock()
        jarvis._files.save_card = AsyncMock()

        long_task = "这是一个非常长的任务名称需要被缩短"
        await jarvis.send_progress_update(
            user_id="ou_abc123",
            task_title=long_task,
            progress=0.5,
            detail="包含很多详细信息的进度描述内容",
            task_id="t-005",
            emotion=EmotionState.STRESSED,
            preference=TonePreference.RELAXED,
        )

        msg_call = jarvis._feishu.send_message_to_user.call_args
        message = msg_call.kwargs.get("message") or msg_call[1].get("message")
        # STRESSED emotion should result in a shorter max_length (150 vs 200)
        # The detail line should be removed due to STRESSED shortening
        assert "📋 [50%]" in message
        assert "50%" in message

    @pytest.mark.asyncio
    async def test_send_card_with_nl_formats_with_tuner(self) -> None:
        """send_card_with_nl formats nl_summary via PersonalityTuner."""
        jarvis = JarvisInterface()
        jarvis._feishu = MagicMock()
        jarvis._feishu.send_action_card = AsyncMock()
        jarvis._files = MagicMock()
        jarvis._files.save_card = AsyncMock()

        await jarvis.send_card_with_nl(
            user_id="ou_abc123",
            title="任务卡",
            content="详情内容",
            actions=[{"text": "OK", "value": "ok", "type": "primary", "task_id": "t-006"}],
            nl_summary="原始摘要信息",
            task_id="t-006",
            emotion=EmotionState.NEUTRAL,
            preference=TonePreference.STRICT,
        )

        # save_card should be called with formatted nl_summary
        save_call = jarvis._files.save_card.call_args
        nl_summary = save_call.kwargs.get("nl_summary") or save_call[1].get("nl_summary")
        # STRICT preference means plain message
        assert "原始摘要信息" in nl_summary

    @pytest.mark.asyncio
    async def test_no_emotion_defaults_to_neutral_relaxed(self) -> None:
        """When no emotion/preference passed, defaults to NEUTRAL + RELAXED."""
        jarvis = JarvisInterface()
        jarvis._feishu = MagicMock()
        jarvis._feishu.send_message_to_user = AsyncMock()
        jarvis._files = MagicMock()
        jarvis._files.save_card = AsyncMock()

        # Should not raise even without emotion/preference
        await jarvis.send_completion_notification(
            user_id="ou_abc123",
            task_title="普通任务",
            result_summary="完成",
            task_id="t-007",
        )

        msg_call = jarvis._feishu.send_message_to_user.call_args
        message = msg_call.kwargs.get("message") or msg_call[1].get("message")
        assert "普通任务" in message
        assert "完成" in message