"""Integration test: hermes-os gateway hook end-to-end."""

import pytest

from hermes_os.memory_router import MemoryRouter
from hermes_os.router import GatewayEvent, UserRouter
from hermes_os.session_manager import SessionManager
from hermes_os.storage import Storage
from hermes_os.user_registry import UserRegistry


@pytest.fixture
async def router() -> UserRouter:
    storage = Storage(db_path=":memory:")
    router = UserRouter(
        registry=UserRegistry(storage=storage),
        sessions=SessionManager(storage=storage),
        memory=MemoryRouter(),
        storage=storage,
    )
    await router.storage.initialize()
    return router


@pytest.mark.asyncio
async def test_hook_integration(router: UserRouter) -> None:
    # --- User Alice (Telegram) ---
    alice_event = GatewayEvent(
        platform="telegram",
        platform_user_id="alice_tg_123",
        message="我叫 Alice，我是一名产品经理",
        user_name="Alice",
    )
    alice_routed = await router.route(alice_event)

    # --- User Bob (Discord) ---
    bob_event = GatewayEvent(
        platform="discord",
        platform_user_id="bob_dc_456",
        message="我是 Bob，工程师，最近在写 Python",
        user_name="Bob",
    )
    bob_routed = await router.route(bob_event)

    # Verify isolation
    assert alice_routed.user.user_id != bob_routed.user.user_id
    assert "<current_user>" in alice_routed.enriched_message
    assert "<current_user>" in bob_routed.enriched_message
    assert "Alice" in alice_routed.enriched_message
    assert "Bob" in bob_routed.enriched_message
    assert "Bob" not in alice_routed.enriched_message
    assert "Alice" not in bob_routed.enriched_message
