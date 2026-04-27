"""Multi-user request router — the main entry point."""

from __future__ import annotations

from dataclasses import dataclass

from hermes_os.context_injector import ContextInjector
from hermes_os.memory_router import MemoryRouter
from hermes_os.models import User
from hermes_os.session_manager import SessionManager
from hermes_os.storage import Storage
from hermes_os.user_registry import UserRegistry


@dataclass
class GatewayEvent:
    """A raw event coming from hermes-agent gateway."""

    platform: str           # telegram | discord | feishu | ...
    platform_user_id: str  # native user id on that platform
    message: str           # raw text from user
    user_name: str = "Unknown"


@dataclass
class RoutedRequest:
    """A fully-enriched request ready to send to hermes-agent."""

    user: User
    enriched_message: str
    session_id: str


class UserRouter:
    """Orchestrates all per-user routing logic."""

    def __init__(
        self,
        registry: UserRegistry | None = None,
        sessions: SessionManager | None = None,
        memory: MemoryRouter | None = None,
        storage: Storage | None = None,
    ) -> None:
        self.storage = storage or Storage()
        self.registry = registry or UserRegistry(storage=self.storage)
        self.sessions = sessions or SessionManager(storage=self.storage)
        self.memory = memory or MemoryRouter()
        self.injector = ContextInjector()

    async def initialize(self) -> None:
        """Prepare the storage and other async resources."""
        await self.storage.initialize()

    async def route(self, event: GatewayEvent) -> RoutedRequest:
        """Process a gateway event and return an enriched request for hermes-agent."""
        # Now async
        user = await self.registry.upsert_from_pairing(
            platform=event.platform,
            platform_user_id=event.platform_user_id,
            name=event.user_name,
        )

        await self.sessions.add_message(user.user_id, "user", event.message)

        session = await self.sessions.get(user.user_id)
        history = session.get_history_for_agent() if session else []

        enriched_history = self.injector.inject_history(user, history)
        enriched_message = enriched_history[-1]["content"] if enriched_history else event.message

        return RoutedRequest(
            user=user,
            enriched_message=enriched_message,
            session_id=session.session_id if session else "",
        )

    async def store_response(self, session_id: str, user_id: str, response: str) -> None:
        """Record hermes-agent's response in the session."""
        await self.sessions.add_message(user_id, "assistant", response)
