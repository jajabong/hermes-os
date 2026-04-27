"""Tests for HermesOS gateway hook."""

import pytest

from hermes_os.gateway_hook import HermesOSHook, HookConfig
from hermes_os.gateway_hook_router import HermesOSRouter


@pytest.fixture
async def hook() -> HermesOSHook:
    h = HermesOSHook(config=HookConfig(
        db_path=":memory:",
        knowledge_db_path=":memory:",
    ))
    await h._get_router()
    await h._get_cli()
    return h


class TestHookManifest:
    """Hook metadata validation."""

    def test_hook_name(self) -> None:
        assert HermesOSHook.name == "hermes-os"

    def test_hook_events(self) -> None:
        assert "agent:start" in HermesOSHook.events


class TestEnrichMessage:
    """Tests for _enrich_message()."""

    @pytest.mark.asyncio
    async def test_enrich_message_returns_text(self, hook: HermesOSHook) -> None:
        """_enrich_message() returns the enriched message text."""
        enriched = await hook._enrich_message(
            platform="telegram",
            platform_user_id="alice_123",
            message="你好",
            user_name="Alice",
        )
        assert isinstance(enriched, str)
        assert len(enriched) > 0

    @pytest.mark.asyncio
    async def test_enrich_message_injects_current_user(self, hook: HermesOSHook) -> None:
        """Enriched message contains <current_user> block."""
        enriched = await hook._enrich_message(
            platform="discord",
            platform_user_id="bob_456",
            message="我是 Bob",
            user_name="Bob",
        )
        assert "<current_user>" in enriched

    @pytest.mark.asyncio
    async def test_enrich_message_injects_knowledge(self, hook: HermesOSHook) -> None:
        """Enriched message contains <knowledge> block when docs exist."""
        cli = await hook._get_cli()
        await cli.add(
            doc_id="test-doc",
            team="engineering",
            title="Test Doc",
            content="Test content about engineering.",
        )
        results = await cli.search("engineering", team="engineering")
        assert len(results) >= 1
        assert any("Test Doc" in r.get("title", "") for r in results)


class TestHandle:
    """Tests for handle() — the hook entry point."""

    @pytest.mark.asyncio
    async def test_handle_fires_on_agent_start(self, hook: HermesOSHook) -> None:
        """handle() enriches the message for agent:start events."""
        class FakeEvent:
            text = "Hello Hermes"

        hook_ctx = {
            "platform": "telegram",
            "user_id": "alice_tg",
            "session_id": "sess-1",
            "message": "Hello Hermes",
            "event": FakeEvent(),
        }

        await hook.handle("agent:start", hook_ctx)

        assert hook_ctx["event"].text != "Hello Hermes"
        assert "<current_user>" in hook_ctx["event"].text

    @pytest.mark.asyncio
    async def test_handle_ignores_non_agent_start(self, hook: HermesOSHook) -> None:
        """handle() is a no-op for events other than agent:start."""
        class FakeEvent:
            text = "unchanged"

        hook_ctx = {
            "platform": "telegram",
            "user_id": "alice",
            "event": FakeEvent(),
        }

        await hook.handle("session:start", hook_ctx)

        assert hook_ctx["event"].text == "unchanged"

    @pytest.mark.asyncio
    async def test_handle_noop_when_event_missing(self, hook: HermesOSHook) -> None:
        """handle() is a no-op when context has no event."""
        await hook.handle("agent:start", {"platform": "telegram", "user_id": "x"})  # no raise

    @pytest.mark.asyncio
    async def test_handle_noop_when_text_empty(self, hook: HermesOSHook) -> None:
        """handle() is a no-op when event.text is empty."""
        class FakeEvent:
            text = ""

        await hook.handle("agent:start", {
            "platform": "telegram",
            "user_id": "x",
            "event": FakeEvent(),
        })  # no raise

    @pytest.mark.asyncio
    async def test_close_releases_resources(self) -> None:
        """close() releases router and cli resources without raising."""
        hook = HermesOSHook()
        await hook._get_router()
        await hook._get_cli()
        await hook.close()  # must not raise


class TestHermesOSRouter:
    """Tests for HermesOSRouter."""

    @pytest.mark.asyncio
    async def test_router_route_enriches_message(self) -> None:
        """route() returns enriched message with current_user block."""
        router = HermesOSRouter(
            db_path=":memory:",
            knowledge_db_path=":memory:",
        )
        await router.initialize()
        try:
            from hermes_os.router import GatewayEvent
            req = await router.route(GatewayEvent(
                platform="telegram",
                platform_user_id="user_1",
                message="Hello",
                user_name="TestUser",
            ))
            assert "<current_user>" in req.enriched_message
        finally:
            await router.close()
