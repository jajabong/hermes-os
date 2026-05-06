"""EmotionEngine — lightweight emotion detection and personality tuning."""

from __future__ import annotations

import re

from hermes_os.emotion_types import EmotionState, ToneConfig

_EMOTION_KEYWORDS = {
    EmotionState.POSITIVE: [
        r"太棒了",
        r"谢谢",
        r"厉害",
        r"完美",
        r"棒",
        r"👍",
        r"✨",
        r"🎉",
        r"感谢",
        r"太好了",
        r"赞",
        r"非常好",
    ],
    EmotionState.STRESSED: [
        r"太忙",
        r"来不及",
        r"没时间",
        r"急死了",
        r"忙",
        r"赶",
        r"压力",
        r"焦虑",
        r"紧张",
        r"崩溃",
        r"头疼",
    ],
    EmotionState.FRUSTRATED: [
        r"烦死了",
        r"太难了",
        r"失败",
        r"不行",
        r"搞不定",
        r"没救了",
        r"绝望",
        r"受够了",
        r"郁闷",
        r"糟糕",
    ],
}

_STRESS_BOOST_THRESHOLD = 2


class EmotionEngine:
    """
    Lightweight emotion detection using keyword matching.

    No LLM required — uses regex + frequency tracking per user.
    """

    def __init__(self) -> None:
        self._recent_signals: dict[str, list[tuple[str, float]]] = {}

    def detect(self, message: str, user_id: str = "default") -> EmotionState:
        """
        Detect emotion from a message string.

        Uses keyword matching; multiple stress signals in short window
        boost result to STRESSED.
        """
        msg = message.strip()
        if not msg:
            return EmotionState.NEUTRAL

        # Check frustration first (strongest signal)
        if self._matches_any(msg, _EMOTION_KEYWORDS[EmotionState.FRUSTRATED]):
            return EmotionState.FRUSTRATED

        # Check stress signals
        stress_count = self._count_matches(msg, _EMOTION_KEYWORDS[EmotionState.STRESSED])
        if stress_count >= 2:
            return EmotionState.STRESSED

        # Per-user recent signals boost
        recent = self._recent_signals.get(user_id, [])
        recent_stress = sum(
            1 for s, _ in recent if self._matches_any(s, _EMOTION_KEYWORDS[EmotionState.STRESSED])
        )
        if recent_stress >= _STRESS_BOOST_THRESHOLD:
            return EmotionState.STRESSED

        if stress_count == 1:
            # Record signal
            self._record_signal(user_id, msg, 0.9)
            return EmotionState.STRESSED

        # Check positive signals
        if self._matches_any(msg, _EMOTION_KEYWORDS[EmotionState.POSITIVE]):
            return EmotionState.POSITIVE

        return EmotionState.NEUTRAL

    def get_tone_adjustment(self, emotion: EmotionState) -> ToneConfig:
        """Return tone config for a given emotion state."""
        if emotion == EmotionState.STRESSED:
            return ToneConfig(max_length=150, emoji_prefix="", encouraging=True)
        if emotion == EmotionState.FRUSTRATED:
            return ToneConfig(max_length=180, emoji_prefix="", encouraging=True)
        if emotion == EmotionState.POSITIVE:
            return ToneConfig(max_length=200, emoji_prefix="🎉 ", encouraging=False)
        return ToneConfig(max_length=200, emoji_prefix="", encouraging=False)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _matches_any(self, text: str, patterns: list[str]) -> bool:
        for pat in patterns:
            if re.search(pat, text):
                return True
        return False

    def _count_matches(self, text: str, patterns: list[str]) -> int:
        count = 0
        for pat in patterns:
            if re.search(pat, text):
                count += 1
        return count

    def _record_signal(self, user_id: str, signal: str, weight: float) -> None:
        if user_id not in self._recent_signals:
            self._recent_signals[user_id] = []
        self._recent_signals[user_id].append((signal, weight))
        # Keep window small
        if len(self._recent_signals[user_id]) > 20:
            self._recent_signals[user_id] = self._recent_signals[user_id][-20:]


__all__ = ["EmotionEngine", "EmotionState", "ToneConfig"]
