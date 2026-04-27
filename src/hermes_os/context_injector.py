"""Injects per-user context into messages before they reach hermes-agent."""

from __future__ import annotations

from hermes_os.models import User


class ContextInjector:
    """Prepends a <current_user> XML block to each user message."""

    def inject(self, user: User, message: str) -> str:
        """Return message with user context injected at the top."""
        return f"{user.to_context_block()}\n\n{message}"

    def inject_history(self, user: User, history: list[dict]) -> list[dict]:
        """Inject context into the first user message of a history list."""
        if not history:
            return history

        enriched = list(history)
        for i, msg in enumerate(enriched):
            if msg.get("role") == "user":
                enriched[i] = {
                    **msg,
                    "content": self.inject(user, msg["content"]),
                }
                break

        return enriched
