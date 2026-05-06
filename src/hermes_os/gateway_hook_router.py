"""HermesOSRouter — unified router combining UserRouter, KnowledgeCLI, and Phase 1 components."""

from __future__ import annotations

from pathlib import Path

from hermes_os.agents.registry_initializer import initialize_agents
from hermes_os.delegation_protocol import DelegationProtocol
from hermes_os.knowledge_cli import KnowledgeCLI
from hermes_os.router import GatewayEvent, RoutedRequest, UserRouter
from hermes_os.topic_tracker import TopicTracker
from hermes_os.unified_router import UnifiedRouter, RouteResult

initialize_agents()

_USER_BRAIN_BASE = Path.home() / ".hermes" / "users"


class HermesOSRouter:
    """Unified router wrapping UserRouter + KnowledgeCLI + Phase 1 (UnifiedRouter) for gateway hook use.

    Phase 1 components wired:
    - IntentClarifier (模糊意图澄清)
    - TopicTracker (跨session记忆粘性)
    - PersonaAssembler (千人千面)
    - DelegationProtocol (委派协议)
    """

    def __init__(
        self,
        db_path: str = "hermes_os.db",
        knowledge_db_path: str = "hermes_knowledge.db",
    ) -> None:
        self._user_router = UserRouter(
            storage=None,
            registry=None,
            sessions=None,
            memory=None,
            knowledge=None,
        )
        storage = self._user_router.storage.__class__(db_path=db_path)
        self._user_router.storage = storage
        self._user_router.registry = self._user_router.registry.__class__(storage=storage)
        self._user_router.sessions = self._user_router.sessions.__class__(storage=storage)
        self._cli = KnowledgeCLI(db_path=knowledge_db_path)
        self._unified_router: UnifiedRouter | None = None
        self._delegation_protocol: DelegationProtocol | None = None
        self._db_path = db_path

    async def initialize(self) -> None:
        await self._user_router.storage.initialize()
        await self._user_router.knowledge.initialize()
        await self._cli.initialize()

        def topic_tracker_factory(user_id: str) -> TopicTracker:
            base_path = _USER_BRAIN_BASE / user_id / "brain"
            return TopicTracker(user_id=user_id, base_path=base_path.parent)

        self._delegation_protocol = DelegationProtocol(
            topic_tracker_factory=topic_tracker_factory,
        )
        self._unified_router = UnifiedRouter(
            user_registry=self._user_router.registry,
            topic_tracker_factory=topic_tracker_factory,
            delegation_protocol=self._delegation_protocol,
        )

    async def route(self, event: GatewayEvent) -> RoutedRequest:
        """Route and enrich a gateway event using UnifiedRouter (Phase 1)."""
        if self._unified_router is None:
            await self.initialize()
        assert self._unified_router is not None

        route_result = await self._unified_router.route(event)

        return RoutedRequest(
            user=route_result.metadata.get("user"),
            enriched_message=route_result.message,
            session_id=route_result.metadata.get("session_id", ""),
            model_tier=route_result.model_tier,
        )

    async def close(self) -> None:
        await self._user_router.close()
        await self._cli.close()
