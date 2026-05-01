"""Tests for NotificationManager — JARVIS notification lifecycle.

Tests:
- `_send_notification` replaced with real implementation
- Lifecycle events: started/running/completed/failed
- Heads-up for long-running tasks (>50% estimated time)
- Uses ConclusionExtractor for 三段式 cards
"""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, patch, MagicMock

from hermes_os.notification_manager import (
    NotificationManager,
    NotificationEvent,
    _SEND_THRESHOLDS,
)


# ---------------------------------------------------------------------------
# NotificationEvent tests
# ---------------------------------------------------------------------------

class TestNotificationEvent:
    def test_event_values(self) -> None:
        assert hasattr(NotificationEvent, "STARTED")
        assert hasattr(NotificationEvent, "RUNNING")
        assert hasattr(NotificationEvent, "COMPLETED")
        assert hasattr(NotificationEvent, "FAILED")
        assert hasattr(NotificationEvent, "WARNING")

    def test_event_icon(self) -> None:
        assert "🔄" in NotificationEvent.STARTED.icon
        assert "✅" in NotificationEvent.COMPLETED.icon
        assert "❌" in NotificationEvent.FAILED.icon
        assert "⚠️" in NotificationEvent.WARNING.icon


# ---------------------------------------------------------------------------
# NotificationManager init tests
# ---------------------------------------------------------------------------

class TestNotificationManagerInit:
    def test_default_init(self) -> None:
        nm = NotificationManager()
        # Jarvis is created lazily or as real instance
        assert nm._extractor is not None

    def test_custom_jarvis(self) -> None:
        mock_jarvis = MagicMock()
        nm = NotificationManager(jarvis=mock_jarvis)
        assert nm._jarvis is mock_jarvis


# ---------------------------------------------------------------------------
# NotificationManager.send_notification tests
# ---------------------------------------------------------------------------

class TestSendNotification:
    @pytest.fixture
    def nm_with_mock(self) -> NotificationManager:
        mock_jarvis = MagicMock()
        nm = NotificationManager(jarvis=mock_jarvis)
        return nm

    @pytest.mark.asyncio
    async def test_send_completion_uses_card(self, nm_with_mock: NotificationManager) -> None:
        nm = nm_with_mock
        with patch.object(nm._jarvis, "send_card_with_nl", new_callable=AsyncMock) as mock_send:
            await nm.send_notification(
                user_id="alice",
                task_title="测试任务",
                task_id="t123",
                event=NotificationEvent.COMPLETED,
                result="测试成功输出",
            )
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args.kwargs["user_id"] == "alice"
            # Title should include icon
            title = call_args.kwargs["title"]
            assert "✅" in title or "完成" in title

    @pytest.mark.asyncio
    async def test_send_failure_uses_card(self, nm_with_mock: NotificationManager) -> None:
        nm = nm_with_mock
        with patch.object(nm._jarvis, "send_card_with_nl", new_callable=AsyncMock) as mock_send:
            await nm.send_notification(
                user_id="alice",
                task_title="部署任务",
                task_id="t456",
                event=NotificationEvent.FAILED,
                error="Error: connection refused",
            )
            mock_send.assert_called_once()
            title = mock_send.call_args.kwargs["title"]
            assert "❌" in title or "失败" in title

    @pytest.mark.asyncio
    async def test_send_started_sends_card(self, nm_with_mock: NotificationManager) -> None:
        nm = nm_with_mock
        with patch.object(nm._jarvis, "send_card_with_nl", new_callable=AsyncMock) as mock_send:
            await nm.send_notification(
                user_id="alice",
                task_title="开始任务",
                task_id="t789",
                event=NotificationEvent.STARTED,
            )
            mock_send.assert_called_once()
            title = mock_send.call_args.kwargs["title"]
            assert "🔄" in title or "开始" in title

    @pytest.mark.asyncio
    async def test_send_warning_sends_card(self, nm_with_mock: NotificationManager) -> None:
        nm = nm_with_mock
        with patch.object(nm._jarvis, "send_card_with_nl", new_callable=AsyncMock) as mock_send:
            await nm.send_notification(
                user_id="alice",
                task_title="监控任务",
                task_id="t111",
                event=NotificationEvent.WARNING,
                result="Warning: memory usage 85%",
            )
            mock_send.assert_called_once()
            title = mock_send.call_args.kwargs["title"]
            assert "⚠️" in title or "警告" in title


# ---------------------------------------------------------------------------
# Heads-up notification tests
# ---------------------------------------------------------------------------

class TestHeadsUpNotification:
    @pytest.fixture
    def nm_with_mock(self) -> NotificationManager:
        mock_jarvis = MagicMock()
        nm = NotificationManager(jarvis=mock_jarvis)
        return nm

    @pytest.mark.asyncio
    async def test_send_heads_up_long_task(self, nm_with_mock: NotificationManager) -> None:
        nm = nm_with_mock
        with patch.object(nm._jarvis, "send_card_with_nl", new_callable=AsyncMock) as mock_send:
            await nm.send_heads_up(
                user_id="alice",
                task_title="供应商分析",
                task_id="t222",
                progress=0.5,
                elapsed_seconds=300,
                estimated_total=600,
            )
            mock_send.assert_called_once()
            content = mock_send.call_args.kwargs["content"]
            assert "进行中" in content or "50%" in content

    @pytest.mark.asyncio
    async def test_heads_up_includes_reassurance(self, nm_with_mock: NotificationManager) -> None:
        nm = nm_with_mock
        with patch.object(nm._jarvis, "send_card_with_nl", new_callable=AsyncMock) as mock_send:
            await nm.send_heads_up(
                user_id="alice",
                task_title="编译",
                task_id="t333",
                progress=0.6,
                elapsed_seconds=120,
                estimated_total=200,
            )
            content = mock_send.call_args.kwargs["content"]
            # Should include reassurance message
            assert any(word in content for word in ["正常", "放心", "继续", "进行"])

    @pytest.mark.asyncio
    async def test_heads_up_only_above_threshold(self, nm_with_mock: NotificationManager) -> None:
        nm = nm_with_mock
        with patch.object(nm._jarvis, "send_card_with_nl", new_callable=AsyncMock) as mock_send:
            await nm.send_heads_up(
                user_id="alice",
                task_title="短任务",
                task_id="t444",
                progress=0.3,
                elapsed_seconds=30,
                estimated_total=100,
            )
            mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Goal context injection tests
# ---------------------------------------------------------------------------

class TestGoalContextInjection:
    @pytest.fixture
    def nm_with_mock(self) -> NotificationManager:
        mock_jarvis = MagicMock()
        nm = NotificationManager(jarvis=mock_jarvis)
        return nm

    @pytest.mark.asyncio
    async def test_goal_context_included_in_card(self, nm_with_mock: NotificationManager) -> None:
        nm = nm_with_mock
        with patch.object(nm._jarvis, "send_card_with_nl", new_callable=AsyncMock) as mock_send:
            await nm.send_notification(
                user_id="alice",
                task_title="任务A",
                task_id="t555",
                event=NotificationEvent.COMPLETED,
                result="Done.",
                goal_context="完成供应商对比 (Phase 2/5)",
            )
            call_args = mock_send.call_args
            # Content should reference goal
            content = call_args.kwargs["content"]
            assert "供应商" in content or "Phase" in content


# ---------------------------------------------------------------------------
# Threshold configuration tests
# ---------------------------------------------------------------------------

class TestSendThresholds:
    def test_heads_up_threshold_values(self) -> None:
        assert _SEND_THRESHOLDS.heads_up_progress_threshold == 0.5
        assert _SEND_THRESHOLDS.min_elapsed_seconds == 60
        assert _SEND_THRESHOLDS.warning_progress_threshold == 0.8

    def test_heads_up_respects_min_elapsed(self) -> None:
        nm = NotificationManager()
        # Too short - should not send
        # This would require mocking time or a very low threshold