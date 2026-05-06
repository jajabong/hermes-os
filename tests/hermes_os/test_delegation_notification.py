"""TDD tests for delegation notification —管家 "收到，我去安排" feedback.

Tests what needs to be built:
1. When create_task_dag succeeds, gateway_hook sends immediate delegation feedback to user
2. Feedback message reflects task type (research/code/deploy) and subtask count
3. Works with skip_confirmation tasks (auto-execute) and confirmed tasks
4. Does NOT send feedback when should_auto_create_task returns False (low confidence)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_send_delegation_feedback_calls_feishu(tmp_path: Path) -> None:
    """_send_delegation_feedback calls FeishuEnhancer.send_message_to_user with correct message."""
    from hermes_os.feishu_enhancer import FeishuEnhancer
    from hermes_os.gateway_hook import HermesOSHook, HookConfig

    config = HookConfig(
        db_path=str(tmp_path / "test.db"),
        knowledge_db_path=str(tmp_path / "test_kb.db"),
        enable_event_loop=False,
    )
    hook = HermesOSHook(config=config)

    mock_send = AsyncMock()
    with patch.object(FeishuEnhancer, "send_message_to_user", mock_send):
        await hook._send_delegation_feedback(
            user_id="alice",
            task_type="research",
            task_count=3,
        )

        assert mock_send.call_count == 1
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["user_id"] == "alice"
        assert "调研" in call_kwargs["message"]
        assert "3" in call_kwargs["message"]


@pytest.mark.asyncio
async def test_send_delegation_feedback_deploy_verb(tmp_path: Path) -> None:
    """deploy task type uses 部署 verb in delegation message."""
    from hermes_os.feishu_enhancer import FeishuEnhancer
    from hermes_os.gateway_hook import HermesOSHook, HookConfig

    config = HookConfig(
        db_path=str(tmp_path / "test.db"),
        knowledge_db_path=str(tmp_path / "test_kb.db"),
        enable_event_loop=False,
    )
    hook = HermesOSHook(config=config)

    mock_send = AsyncMock()
    with patch.object(FeishuEnhancer, "send_message_to_user", mock_send):
        await hook._send_delegation_feedback(
            user_id="bob",
            task_type="deploy",
            task_count=1,
        )

        call_kwargs = mock_send.call_args.kwargs
        assert "部署" in call_kwargs["message"]


@pytest.mark.asyncio
async def test_send_delegation_feedback_unknown_verb(tmp_path: Path) -> None:
    """Unknown task type uses generic 处理 verb."""
    from hermes_os.feishu_enhancer import FeishuEnhancer
    from hermes_os.gateway_hook import HermesOSHook, HookConfig

    config = HookConfig(
        db_path=str(tmp_path / "test.db"),
        knowledge_db_path=str(tmp_path / "test_kb.db"),
        enable_event_loop=False,
    )
    hook = HermesOSHook(config=config)

    mock_send = AsyncMock()
    with patch.object(FeishuEnhancer, "send_message_to_user", mock_send):
        await hook._send_delegation_feedback(
            user_id="alice",
            task_type="unknown_action",
            task_count=2,
        )

        call_kwargs = mock_send.call_args.kwargs
        assert "处理" in call_kwargs["message"]
        assert "2" in call_kwargs["message"]


@pytest.mark.asyncio
async def test_process_intent_calls_send_delegation_feedback(tmp_path: Path) -> None:
    """_process_intent_and_schedule calls _send_delegation_feedback after task creation."""
    from hermes_os.feishu_enhancer import FeishuEnhancer
    from hermes_os.gateway_hook import HermesOSHook, HookConfig

    config = HookConfig(
        db_path=str(tmp_path / "test.db"),
        knowledge_db_path=str(tmp_path / "test_kb.db"),
        enable_event_loop=False,
    )
    hook = HermesOSHook(config=config)

    mock_send = AsyncMock()
    spawned_coros = []

    # Patch _spawn to capture coroutines for synchronous execution in test
    original_spawn = hook._spawn

    def tracking_spawn(coro):
        spawned_coros.append(coro)
        # Don't call original_spawn — we run them manually in test

    hook._spawn = tracking_spawn

    with patch.object(FeishuEnhancer, "send_message_to_user", mock_send):
        mock_intent = MagicMock()
        mock_intent.action.value = "research"
        mock_intent.confidence = 0.92
        mock_intent.raw_text = "研究"
        mock_intent.entities = {}

        mock_task = MagicMock()
        mock_task.task_id = "task-001"

        hook._chief.parse_intent = AsyncMock(return_value=mock_intent)
        hook._chief.should_auto_create_task = AsyncMock(return_value=True)
        hook._chief.create_task_dag = AsyncMock(return_value=[mock_task])
        hook._scheduler = AsyncMock()

        await hook._process_intent_and_schedule(
            message="研究一下",
            user_id="alice",
            user_id_alt="alice_open_id",
        )

        # Run the spawned coroutines so delegation feedback fires
        if spawned_coros:
            await asyncio.gather(*spawned_coros)

        assert mock_send.call_count >= 1
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["user_id"] == "alice"


@pytest.mark.asyncio
async def test_no_feedback_when_auto_create_is_false(tmp_path: Path) -> None:
    """When should_auto_create_task returns False, no delegation feedback is sent."""
    from hermes_os.feishu_enhancer import FeishuEnhancer
    from hermes_os.gateway_hook import HermesOSHook, HookConfig

    config = HookConfig(
        db_path=str(tmp_path / "test.db"),
        knowledge_db_path=str(tmp_path / "test_kb.db"),
        enable_event_loop=False,
    )
    hook = HermesOSHook(config=config)

    mock_send = AsyncMock()
    spawned_coros = []

    def tracking_spawn(coro):
        spawned_coros.append(coro)

    hook._spawn = tracking_spawn

    with patch.object(FeishuEnhancer, "send_message_to_user", mock_send):
        mock_intent = MagicMock()
        mock_intent.action.value = "unknown"
        mock_intent.confidence = 0.30
        mock_intent.raw_text = "你好啊"

        hook._chief.parse_intent = AsyncMock(return_value=mock_intent)
        hook._chief.should_auto_create_task = AsyncMock(return_value=False)

        await hook._process_intent_and_schedule(
            message="你好啊",
            user_id="alice",
            user_id_alt="alice_open_id",
        )

        # Run any spawned coroutines
        if spawned_coros:
            await asyncio.gather(*spawned_coros)

        # send_message_to_user should NOT be called for low-confidence intents
        assert mock_send.call_count == 0
