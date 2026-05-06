"""IntentClarifier — fuzzy intent clarification for Hermes OS.

Phase 1: 千人千面管家
P1: 意图澄清 — 当用户说模糊的话时，管家先问清楚再做
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ClarificationType(str, Enum):
    VAGUE_SUBJECT = "vague_subject"
    VAGUE_ACTION = "vague_action"
    MISSING_CONTEXT = "missing_context"
    MULTIPLE_INTERPRETATIONS = "multiple_interpretations"
    NEEDS_DETAIL = "needs_detail"


@dataclass
class ClarificationResult:
    needs_clarification: bool
    clarification_type: ClarificationType | None = None
    question: str = ""
    suggestions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class IntentClarifier:
    """Fuzzy intent clarification.

    Core method: ask() — returns ClarificationResult with question if vague.
    """

    # Vague: standalone verb + 一下 without object
    VAGUE_STANDALONE_PATTERNS = (
        "处理一下",
        "弄一下",
        "搞一下",
        "试一下",
        "试一下",
        "搞一搞",
    )

    # Vague: demonstrative pronoun without following noun
    VAGUE_DEMONSTRATIVE_PATTERNS = (
        "这个",
        "那个",
        "它",
        "这事",
        "那事",
        "这件事",
        "那件事",
    )

    # Clear: simple responses that don't need clarification
    CLEAR_PATTERNS = (
        "你好",
        "您好",
        "谢谢",
        "谢谢",
        "好的",
        "好",
        "行",
        "知道了",
        "明白",
        "再见",
        "拜拜",
    )

    def is_vague(self, message: str) -> bool:
        """Quick check if message needs clarification."""
        msg = message.strip()
        msg_lower = msg.lower()

        # Simple greetings/acknowledgements — never vague
        for p in self.CLEAR_PATTERNS:
            if msg == p or msg.startswith(p + "，") or msg.startswith(p + "，"):
                return False

        # Vague action: "动词一下" at end or followed by punctuation only
        if self._has_vague_action(msg_lower):
            return True

        # Vague subject: demonstrative pronoun at start followed by punctuation/particle
        if self._has_vague_subject(msg_lower):
            return True

        return False

    def _has_vague_action(self, msg_lower: str) -> bool:
        """Check for standalone vague action (动词一下 without object)."""
        for pattern in self.VAGUE_STANDALONE_PATTERNS:
            idx = msg_lower.find(pattern)
            if idx < 0:
                continue
            after_idx = idx + len(pattern)
            if after_idx >= len(msg_lower):
                # Pattern at end of string → vague
                return True
            after = msg_lower[after_idx:]
            # If followed by punctuation, question particle, or nothing meaningful → vague
            if not after or after[0] in "，．。？!！、；：":
                return True
            # "一下" followed by question particle "呀/啊/么" → vague
            stripped = after.lstrip()
            if stripped.startswith(("呀", "啊", "么", "嘛")):
                return True
        return False

    def _has_vague_subject(self, msg_lower: str) -> bool:
        """Check for vague demonstrative pronoun at start of message.

        "这个" + verb (有/是) → vague. "这个" + noun → not vague.
        """
        for pattern in self.VAGUE_DEMONSTRATIVE_PATTERNS:
            idx = msg_lower.find(pattern)
            if idx < 0:
                continue
            after_idx = idx + len(pattern)
            if after_idx >= len(msg_lower):
                # Pattern at end → vague
                return True
            after = msg_lower[after_idx:]
            # "这个？" or "那个。" → vague (followed by only punctuation)
            if not after or after[0] in "，。？！、；：)）":
                return True
            stripped = after.lstrip()
            # "这个呢" / "那个啊" / "它吗" → vague (followed by question particle)
            if stripped.startswith(("呢", "啊", "呀", "吧", "吗", "么", "嘛")):
                return True
            # "这个有" / "那个是" / "它是" → vague (verb follows, no noun specified)
            if stripped.startswith(("有", "是", "在", "没", "能不能", "会不会", "可不可以")):
                return True
            # "这个怎么样" / "那个怎么了" → vague (fixed phrase, no specific noun)
            if stripped.startswith(("怎么样", "怎么了", "好不好", "行不行", "可以吗")):
                return True
        return False

    def ask(self, message: str) -> ClarificationResult:
        """Determine if clarification is needed."""
        if not self.is_vague(message):
            return ClarificationResult(needs_clarification=False)

        msg_lower = message.lower()
        if self._has_vague_action(msg_lower):
            return self._ask_vague_action(message)
        elif self._has_vague_subject(msg_lower):
            return self._ask_vague_subject(message)
        else:
            return ClarificationResult(
                needs_clarification=True,
                clarification_type=ClarificationType.NEEDS_DETAIL,
                question="您能说得更具体一些吗？",
            )

    def ask_with_context(
        self,
        message: str,
        user_preferences: dict[str, Any] | None = None,
    ) -> ClarificationResult:
        """Generate clarification question with user preference awareness."""
        prefs = user_preferences or {}
        result = self.ask(message)
        if not result.needs_clarification:
            return result

        comm_style = prefs.get("communication_style", "neutral")
        if comm_style == "brief":
            result.question = self._make_brief(result.question)
        return result

    def ask_with_topic_context(
        self,
        message: str,
        topic_context: dict[str, Any] | None = None,
    ) -> ClarificationResult:
        """Disambiguate vague pronouns using topic context."""
        result = self.ask(message)
        if not result.needs_clarification:
            return result

        if topic_context:
            topic = topic_context.get("topic", "")
            if topic:
                result.suggestions = [topic]
                result.question = self._reference_topic(result.question, topic)
        return result

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _ask_vague_action(self, message: str) -> ClarificationResult:
        """Clarification for vague action."""
        msg_lower = message.lower()
        if "处理" in msg_lower:
            question = "您想处理什么？"
        elif "弄" in msg_lower or "搞" in msg_lower:
            question = "您想让我帮您做什么？"
        elif "试" in msg_lower:
            question = "您想试什么？"
        else:
            question = "您能说得更具体一些吗？"
        return ClarificationResult(
            needs_clarification=True,
            clarification_type=ClarificationType.VAGUE_ACTION,
            question=question,
        )

    def _ask_vague_subject(self, message: str) -> ClarificationResult:
        """Clarification for vague subject."""
        msg_lower = message.lower()
        if any(p in msg_lower for p in ("这个", "这事")):
            question = "您想让我看什么？"
        elif any(p in msg_lower for p in ("那个", "那事", "那件事")):
            question = "您是指哪件事？"
        elif "它" in msg_lower:
            question = "您说的「它」是指什么？"
        else:
            question = "您能说得更具体一些吗？"
        return ClarificationResult(
            needs_clarification=True,
            clarification_type=ClarificationType.VAGUE_SUBJECT,
            question=question,
        )

    def _make_brief(self, question: str) -> str:
        brief_map = {
            "您想让我看什么？": "看什么？",
            "您是指哪件事？": "哪件事？",
            "您说的「它」是指什么？": "它是指？",
            "您想处理什么？": "处理什么？",
            "您想让我帮您做什么？": "做什么？",
            "您想试什么？": "试什么？",
            "您能说得更具体一些吗？": "具体说？",
        }
        return brief_map.get(question, question)

    def _reference_topic(self, question: str, topic: str) -> str:
        """Inject topic into question to disambiguate."""
        if "什么" in question or "哪件" in question:
            return question.replace("？", f"（{topic}）？").replace("?", f"（{topic}）?")
        return question
