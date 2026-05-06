"""Tests for ConversationStateManager — event-driven user conversation state."""

import pytest

from hermes_os.conversation_state import (
    ConversationState,
    ConversationStateManager,
    UserConversationState,
)
from hermes_os.storage import Storage


@pytest.fixture
async def csm() -> ConversationStateManager:
    storage = Storage(db_path=":memory:")
    await storage.initialize()
    manager = ConversationStateManager(storage=storage)
    await manager.initialize()
    return manager


class TestConversationStateIdle:
    """Tests for IDLE state transitions."""

    @pytest.mark.asyncio
    async def test_new_user_starts_idle(self, csm: ConversationStateManager) -> None:
        """A user without prior state starts in IDLE."""
        state = await csm.get_state("alice")
        assert state.state == ConversationState.IDLE
        assert state.user_id == "alice"
        assert state.current_task_id is None

    @pytest.mark.asyncio
    async def test_idle_to_awaiting(self, csm: ConversationStateManager) -> None:
        """enter_awaiting_confirmation transitions to AWAITING_CONFIRMATION."""
        await csm.enter_awaiting_confirmation(
            user_id="alice",
            task_id="t-001",
            decision_prompt="Confirm t-001 execution?",
        )
        state = await csm.get_state("alice")
        assert state.state == ConversationState.AWAITING_CONFIRMATION
        assert state.current_task_id == "t-001"
        assert state.pending_decision == "Confirm t-001 execution?"

    @pytest.mark.asyncio
    async def test_confirm_transitions_to_in_progress(self, csm: ConversationStateManager) -> None:
        """confirm() moves state from AWAITING_CONFIRMATION to IN_PROGRESS."""
        await csm.enter_awaiting_confirmation("alice", "t-001", "Confirm?")
        await csm.confirm("alice")
        state = await csm.get_state("alice")
        assert state.state == ConversationState.IN_PROGRESS
        assert state.current_task_id == "t-001"

    @pytest.mark.asyncio
    async def test_intercept_resets_to_idle(self, csm: ConversationStateManager) -> None:
        """intercept() resets state to IDLE."""
        await csm.enter_awaiting_confirmation("alice", "t-001", "Confirm?")
        await csm.intercept("alice")
        state = await csm.get_state("alice")
        assert state.state == ConversationState.IDLE
        assert state.current_task_id is None

    @pytest.mark.asyncio
    async def test_complete_resets_to_idle(self, csm: ConversationStateManager) -> None:
        """complete() transitions to IDLE."""
        await csm.enter_awaiting_confirmation("alice", "t-001", "Confirm?")
        await csm.confirm("alice")
        await csm.complete("alice")
        state = await csm.get_state("alice")
        assert state.state == ConversationState.IDLE


class TestConversationStatePersistence:
    """Tests for SQLite persistence of conversation state."""

    @pytest.mark.asyncio
    async def test_state_persisted_to_storage(self, csm: ConversationStateManager) -> None:
        """State is saved to SQLite and survives manager re-init."""
        await csm.enter_awaiting_confirmation("alice", "t-001", "Confirm?")
        del csm._memory["alice"]  # Clear in-memory cache

        # Re-load from storage
        state = await csm.get_state("alice")
        assert state.state == ConversationState.AWAITING_CONFIRMATION
        assert state.current_task_id == "t-001"

    @pytest.mark.asyncio
    async def test_update_progress(self, csm: ConversationStateManager) -> None:
        """update_progress() changes multi_step_progress."""
        await csm.set_state("alice", ConversationState.IN_PROGRESS, current_task_id="t-001")
        await csm.update_progress("alice", 0.5)
        state = await csm.get_state("alice")
        assert state.multi_step_progress == 0.5


class TestUserConversationState:
    """Tests for UserConversationState model."""

    def test_to_dict(self) -> None:
        """to_dict() returns serializable dict."""
        from datetime import UTC, datetime

        state = UserConversationState(
            user_id="alice",
            state=ConversationState.AWAITING_CONFIRMATION,
            current_task_id="t-001",
            pending_decision="Confirm?",
            multi_step_progress=0.0,
            last_updated=datetime.now(UTC),
            metadata={"key": "value"},
        )
        d = state.to_dict()
        assert d["user_id"] == "alice"
        assert d["state"] == "AWAITING_CONFIRMATION"
        assert d["current_task_id"] == "t-001"
        assert d["metadata"]["key"] == "value"
