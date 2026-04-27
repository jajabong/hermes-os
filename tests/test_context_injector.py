"""Tests for ContextInjector."""


from hermes_os.context_injector import ContextInjector
from hermes_os.models import User


class TestContextInjector:
    """Unit tests for ContextInjector."""

    def setup_method(self) -> None:
        self.injector = ContextInjector()
        self.alice = User(
            user_id="alice123",
            name="Alice",
            role="user",
            team="alpha",
            platform="telegram",
            platform_user_id="111",
        )
        self.bob = User(
            user_id="bob456",
            name="Bob",
            role="admin",
            team="beta",
            platform="discord",
            platform_user_id="222",
        )

    # --- inject ---

    def test_inject_prepends_context_block(self) -> None:
        """inject() prepends <current_user> XML block before the message."""
        result = self.injector.inject(self.alice, "Hello agent")

        assert result.startswith("<current_user>")
        assert "<current_user>" in result
        assert "id: alice123" in result
        assert "name: Alice" in result
        assert "role: user" in result
        assert "team: alpha" in result
        assert "</current_user>" in result
        assert "Hello agent" in result

    def test_inject_context_block_appears_before_message(self) -> None:
        """The context block appears before the original message content."""
        result = self.injector.inject(self.alice, "My request")

        block_end = result.find("</current_user>")
        msg_start = result.find("My request")

        assert block_end < msg_start

    def test_inject_context_block_has_correct_format(self) -> None:
        """Context block format matches SPEC.md exactly."""
        result = self.injector.inject(self.alice, "Hi")

        expected = (
            "<current_user>\n"
            "id: alice123\n"
            "name: Alice\n"
            "role: user\n"
            "team: alpha\n"
            "</current_user>"
        )
        assert expected in result

    def test_inject_different_users_different_context(self) -> None:
        """Different users produce different context blocks."""
        result_alice = self.injector.inject(self.alice, "Hi")
        result_bob = self.injector.inject(self.bob, "Hi")

        assert "alice123" in result_alice
        assert "bob456" in result_bob
        assert "Alice" in result_alice
        assert "Bob" in result_bob
        assert "role: user" in result_alice
        assert "role: admin" in result_bob

    def test_inject_preserves_original_message(self) -> None:
        """Original message content is preserved exactly."""
        msg = "Tell me about quantum physics"
        result = self.injector.inject(self.alice, msg)

        assert msg in result

    def test_inject_empty_message(self) -> None:
        """inject() handles empty string message."""
        result = self.injector.inject(self.alice, "")

        assert "<current_user>" in result
        assert "</current_user>" in result

    def test_inject_message_with_newlines(self) -> None:
        """inject() preserves newlines in message content."""
        msg = "Line 1\nLine 2\nLine 3"
        result = self.injector.inject(self.alice, msg)

        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result

    def test_inject_admin_role(self) -> None:
        """Admin users show role: admin in context."""
        result = self.injector.inject(self.bob, "Admin request")

        assert "role: admin" in result

    def test_inject_message_with_special_characters(self) -> None:
        """inject() handles special characters in message."""
        msg = "<script>alert('xss')</script>"
        result = self.injector.inject(self.alice, msg)

        assert msg in result
        assert "<current_user>" in result

    # --- inject_history ---

    def test_inject_history_empty_list(self) -> None:
        """inject_history() returns empty list unchanged."""
        result = self.injector.inject_history(self.alice, [])

        assert result == []

    def test_inject_history_injects_first_user_message(self) -> None:
        """inject_history() injects context into the first user message only."""
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "Second message"},
        ]

        result = self.injector.inject_history(self.alice, history)

        first_msg = result[0]["content"]
        assert "<current_user>" in first_msg
        assert "Hello" in first_msg
        # Second user message should NOT be injected
        second_msg = result[2]["content"]
        assert "<current_user>" not in second_msg

    def test_inject_history_preserves_assistant_messages(self) -> None:
        """inject_history() does not modify assistant messages."""
        history = [
            {"role": "assistant", "content": "Hello, how can I help?"},
        ]

        result = self.injector.inject_history(self.alice, history)

        assert result[0]["content"] == "Hello, how can I help?"
        assert "<current_user>" not in result[0]["content"]

    def test_inject_history_preserves_message_order(self) -> None:
        """inject_history() preserves message ordering."""
        history = [
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "Question?"},
            {"role": "assistant", "content": "Answer."},
        ]

        result = self.injector.inject_history(self.alice, history)

        assert result[0]["role"] == "assistant"
        assert result[1]["role"] == "user"
        assert result[2]["role"] == "assistant"
        assert result[1]["content"].startswith("<current_user>")

    def test_inject_history_does_not_mutate_original(self) -> None:
        """inject_history() returns a new list and new dicts, doesn't mutate original."""
        history = [{"role": "user", "content": "Original"}]
        result = self.injector.inject_history(self.alice, history)

        # Original should be unchanged
        assert history[0]["content"] == "Original"
        assert "<current_user>" not in history[0]["content"]

        # Result should be enriched
        assert "<current_user>" in result[0]["content"]

    def test_inject_history_with_system_message(self) -> None:
        """inject_history() skips system messages and injects first user message."""
        history = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "User request"},
        ]

        result = self.injector.inject_history(self.alice, history)

        assert result[0]["content"] == "You are a helpful assistant."
        assert "<current_user>" in result[1]["content"]
        assert "User request" in result[1]["content"]

    def test_inject_history_with_no_user_messages(self) -> None:
        """inject_history() returns unchanged when there are no user messages."""
        history = [
            {"role": "assistant", "content": "Response"},
        ]

        result = self.injector.inject_history(self.alice, history)

        assert result == [{"role": "assistant", "content": "Response"}]
