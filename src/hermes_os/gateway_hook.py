"""HermesOS gateway hook — enriches each message with user context and knowledge."""

from __future__ import annotations

from dataclasses import dataclass

from hermes_os.gateway_hook_router import HermesOSRouter
from hermes_os.knowledge_cli import KnowledgeCLI
from hermes_os.router import GatewayEvent


@dataclass
class HookConfig:
    """Runtime configuration for the gateway hook."""
    db_path: str = "hermes_os.db"
    knowledge_db_path: str = "hermes_knowledge.db"


class HermesOSHook:
    """Gateway hook that injects per-user context before agent:start.

    Events subscribed: agent:start

    This hook runs before hermes-agent processes each message. It:
      1. Creates a HermesOSRouter and routes the incoming event
      2. Replaces the raw message text with the enriched version
         (user block + memory context + knowledge block)
      3. Stores the agent's response in long-term memory
    """

    name: str = "hermes-os"
    events: list[str] = ["agent:start"]

    def __init__(self, config: HookConfig | None = None) -> None:
        self._config = config or HookConfig()
        self._router: HermesOSRouter | None = None
        self._cli: KnowledgeCLI | None = None

    async def _get_router(self) -> HermesOSRouter:
        if self._router is None:
            self._router = HermesOSRouter(
                db_path=self._config.db_path,
                knowledge_db_path=self._config.knowledge_db_path,
            )
            await self._router.initialize()
        return self._router

    async def _get_cli(self) -> KnowledgeCLI:
        if self._cli is None:
            self._cli = KnowledgeCLI(db_path=self._config.knowledge_db_path)
            await self._cli.initialize()
        return self._cli

    async def handle(self, event_type: str, context: dict) -> None:
        """Enrich the gateway event's message text before agent:start.

        Mutates ``context["event"].text`` in-place.
        """
        if event_type != "agent:start":
            return

        event = context.get("event")
        if event is None:
            return

        raw_message = getattr(event, "text", None)
        if not raw_message:
            return

        router = await self._get_router()
        gateway_event = GatewayEvent(
            platform=context.get("platform", ""),
            platform_user_id=context.get("user_id", ""),
            message=raw_message,
            user_name=context.get("user_name", "Unknown"),
        )

        routed = await router.route(gateway_event)
        event.text = routed.enriched_message

    async def _enrich_message(
        self,
        platform: str,
        platform_user_id: str,
        message: str,
        user_name: str,
    ) -> str:
        """Enrich a raw message with user context and knowledge. Returns enriched text."""
        router = await self._get_router()
        gateway_event = GatewayEvent(
            platform=platform,
            platform_user_id=platform_user_id,
            message=message,
            user_name=user_name,
        )
        routed = await router.route(gateway_event)
        return routed.enriched_message

    async def close(self) -> None:
        """Release resources."""
        if self._router:
            await self._router.close()
            self._router = None
        if self._cli:
            await self._cli.close()
            self._cli = None
