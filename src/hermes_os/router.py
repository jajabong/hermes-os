"""Multi-user request router — the main entry point."""

from __future__ import annotations

from dataclasses import dataclass

from hermes_os.context_injector import ContextInjector
from hermes_os.knowledge_router import KnowledgeRouter
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
        knowledge: KnowledgeRouter | None = None,
        storage: Storage | None = None,
    ) -> None:
        self.storage = storage or Storage()
        self.registry = registry or UserRegistry(storage=self.storage)
        self.sessions = sessions or SessionManager(storage=self.storage)
        self.memory = memory or MemoryRouter()
        self.knowledge = knowledge or KnowledgeRouter()
        self.injector = ContextInjector()

    async def initialize(self) -> None:
        """Prepare the storage and other async resources."""
        await self.storage.initialize()
        await self.knowledge.initialize()

    async def __aenter__(self) -> UserRouter:
        await self.initialize()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.storage.close()
        await self.knowledge.close()

    async def route(self, event: GatewayEvent) -> RoutedRequest:
        """Process a gateway event and return an enriched request for hermes-agent."""
        user = await self.registry.upsert_from_pairing(
            platform=event.platform,
            platform_user_id=event.platform_user_id,
            name=event.user_name,
        )

        await self.sessions.add_message(user.user_id, "user", event.message)

        session = await self.sessions.get(user.user_id)
        if session is None:
            session = await self.sessions.get_or_create(user.user_id)
        history = session.get_history_for_agent()

        # Search long-term memory and inject results into context
        memory_results = await self.memory.search(user, event.message)
        memory_context = self._format_memory_context(memory_results)

        # Search shared knowledge base for the user's team
        knowledge_results = await self.knowledge.search(event.message, team=user.team)
        knowledge_context = self._format_knowledge_context(knowledge_results)

        enriched_history = self.injector.inject_history(user, history)
        enriched_message = (
            enriched_history[-1]["content"]
            if enriched_history
            else event.message
        )
        if memory_context:
            enriched_message = f"{memory_context}\n\n{enriched_message}"
        if knowledge_context:
            enriched_message = f"{enriched_message}\n\n{knowledge_context}"

        return RoutedRequest(
            user=user,
            enriched_message=enriched_message,
            session_id=session.session_id if session else "",
        )

    def _format_memory_context(self, results: list[dict]) -> str:
        """Format memory search results as a readable context block."""
        if not results:
            return ""
        lines = ["## Relevant Memory"]
        for r in results:
            lines.append(f"- {r.get('text', '')}")
        return "\n".join(lines)

    def _format_knowledge_context(self, results: list[dict]) -> str:
        """Format knowledge search results as a <knowledge> block."""
        if not results:
            return ""
        lines = ["<knowledge>"]
        for r in results:
            title = r.get("title", "")
            content = r.get("content", "")
            lines.append(f"**{title}**: {content}")
        lines.append("</knowledge>")
        return "\n".join(lines)

    async def store_response(self, user: User, session_id: str, response: str) -> None:
        """Record hermes-agent's response in session and long-term memory."""
        await self.sessions.add_message(user.user_id, "assistant", response)
        await self.memory.store(user, response, metadata={"session_id": session_id})
