"""OutputAdapter — style adaptation layer for Hermes OS.

Adapts VerticalAgent output to match user-preferred style:
- Tone: neutral / casual / concise / technical
- Language: auto / zh / en
- Format: markdown / plain / card
- max_length: truncation threshold
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# OutputStyle
# ---------------------------------------------------------------------------


@dataclass
class OutputStyle:
    """User output style preferences."""

    tone: str = "neutral"  # "technical" | "casual" | "concise" | "neutral"
    language: str = "auto"  # "zh" | "en" | "auto"
    format: str = "markdown"  # "markdown" | "plain" | "card"
    max_length: int = 2000
    include_metadata: bool = False


# ---------------------------------------------------------------------------
# OutputAdapter
# ---------------------------------------------------------------------------


class OutputAdapter:
    """Adapts agent output to user-preferred style.

    Transformations:
    - Truncation to max_length
    - Tone adaptation (concise summarization)
    - Language pass-through (auto-detect)
    - Format preservation or stripping (markdown ↔ plain)
    """

    def __init__(self, preferences: dict | None = None) -> None:
        """Initialize with user preferences dict.

        Args:
            preferences: Dict with keys like tone, language, format, max_length.
                       If None, uses OutputStyle defaults.
        """
        self._prefs = preferences or {}

    def adapt(self, output: str | None) -> str:
        """Adapt output to user preferences.

        Args:
            output: Raw output from a VerticalAgent.

        Returns:
            Adapted string tailored to user preferences.
            Empty string if output is None or empty.
        """
        if not output:
            return ""

        style = self._build_style()
        result = output

        # 1. Truncate to max_length
        result = self._truncate(result, style.max_length)

        # 2. Tone adaptation (concise summarization)
        if style.tone == "concise":
            result = self._make_concise(result)

        # 3. Format adaptation
        if style.format == "plain":
            result = self._strip_markdown(result)

        # 4. Language adaptation (pass-through for zh/en, detect for auto)
        # Currently a no-op — auto-detection happens at output time

        return result

    def _build_style(self) -> OutputStyle:
        """Build OutputStyle from preferences dict."""
        return OutputStyle(
            tone=self._prefs.get("tone", self._prefs.get("communication_style", "neutral")),
            language=self._prefs.get("language", "auto"),
            format=self._prefs.get("format", "markdown"),
            max_length=self._prefs.get("max_length", 2000),
            include_metadata=self._prefs.get("include_metadata", False),
        )

    def _truncate(self, text: str, max_length: int) -> str:
        """Truncate text to max_length, adding '...' if truncated."""
        if len(text) <= max_length:
            return text
        # Find a good break point (end of sentence or clause)
        truncated = text[:max_length]
        # Try to break at sentence boundary
        sentence_breaks = list(re.finditer(r"[。！？\n]", truncated))
        if sentence_breaks:
            last_break = sentence_breaks[-1]
            return truncated[: last_break.end()] + "..."
        return truncated.rstrip() + "..."

    def _make_concise(self, text: str) -> str:
        """Reduce text length while preserving key information.

        Strategy:
        - Remove repeated phrases
        - Collapse multiple bullet points to summary
        - Keep first sentence + key facts
        """
        if len(text) < 200:
            return text

        # Split into sentences
        sentences = re.split(r"[。！？\n]", text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if len(sentences) <= 2:
            return text

        # Keep first sentence and last sentence (often conclusion)
        concise = sentences[0]
        if sentences[-1] != sentences[0]:
            concise += "。" + sentences[-1]

        # If still too long, take only first sentence + key numbers
        if len(concise) > 300:
            # Extract numbers and key terms
            numbers = re.findall(r"[\d.]+%?|[\d.]+倍", text)
            key_terms = re.findall(r"[^，。\n]{2,5}(?:投资|股票|基金|收益|风险|回报)", text)
            if numbers:
                concise = sentences[0] + "。"
                concise += "关键数据：" + "、".join(numbers[:5])
            else:
                concise = sentences[0][:200] + "..."

        return concise

    def _strip_markdown(self, text: str) -> str:
        """Strip markdown syntax to produce plain text."""
        # Remove headers
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Remove bold/italic
        text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
        text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
        # Remove inline code
        text = re.sub(r"`([^`]+)`", r"\1", text)
        # Remove code blocks (keep content)
        text = re.sub(r"```[\w]*\n(.*?)```", r"\1", text, flags=re.DOTALL)
        # Remove links
        text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
        # Remove list markers
        text = re.sub(r"^[\s]*[-*+]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^[\s]*\d+\.\s+", "", text, flags=re.MULTILINE)
        # Clean up extra whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
