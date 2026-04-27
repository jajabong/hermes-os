"""Core domain models."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class User:
    """Represents a platform user."""

    user_id: str
    name: str
    role: str = "user"
    team: str = "default"
    platform: str = "unknown"
    platform_user_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_context_block(self) -> str:
        """Render as XML context block injected into hermes-agent prompt."""
        return (
            f"<current_user>\n"
            f"id: {self.user_id}\n"
            f"name: {self.name}\n"
            f"role: {self.role}\n"
            f"team: {self.team}\n"
            f"</current_user>"
        )


@dataclass
class Message:
    """A single message in a conversation."""

    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Session:
    """Represents a user session with conversation history."""

    session_id: str
    user_id: str
    conversation_history: list[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_active: datetime = field(default_factory=lambda: datetime.now(UTC))

    def add_message(self, role: str, content: str) -> None:
        """Append a message to history."""
        self.conversation_history.append(Message(role=role, content=content))
        self.last_active = datetime.now(UTC)

    def get_history_for_agent(self) -> list[dict]:
        """Return history in a format suitable for the agent."""
        return [
            {"role": m.role, "content": m.content} for m in self.conversation_history
        ]
