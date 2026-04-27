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
            f"</current_user>\n\n"
            f"## File Delivery Instructions\n"
            f"When you generate or have a local file to send to the user:\n"
            f"- IMMEDIATELY append a line with the absolute file path prefixed by MEDIA:\n"
            f"  Example: MEDIA:/tmp/report.pdf\n"
            f"- Do NOT paste file paths as plain text — always use MEDIA: prefix\n"
            f"- Do NOT try upload services, cloud links, or share links\n"
            f"- The MEDIA: prefix triggers automatic attachment delivery\n"
            f"- Supported: PDF, images (png/jpg/gif/webp), video, audio, docx, xlsx, pptx\n\n"
            f"## Message History\n"
            f"If the user asks to recall earlier messages, check conversation history,\n"
            f"or reference what they said before, use the feishu_message_history tool.\n"
            f"Example: feishu_message_history(chat_id=None, limit=20)\n"
            f"  (chat_id is optional — it defaults to the current session)\n"
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
