"""HermesOSRouter — unified router combining UserRouter and KnowledgeCLI."""

from __future__ import annotations

from hermes_os.knowledge_cli import KnowledgeCLI
from hermes_os.router import GatewayEvent, RoutedRequest, UserRouter


class HermesOSRouter:
    """Unified router wrapping UserRouter + KnowledgeCLI for gateway hook use."""

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

    async def initialize(self) -> None:
        await self._user_router.storage.initialize()
        await self._user_router.knowledge.initialize()
        await self._cli.initialize()

    async def route(self, event: GatewayEvent) -> RoutedRequest:
        """Route and enrich a gateway event."""
        return await self._user_router.route(event)

    async def close(self) -> None:
        await self._user_router.close()
        await self._cli.close()
