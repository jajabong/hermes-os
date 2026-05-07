"""Preference Learning — StyleSignalDetector for Hermes OS personal assistant.

Monitors conversation for explicit style feedback and implicit behavioral signals,
aggregates them via sliding window, and exposes preferences ready for persistence.

Explicit signals: "太长了", "太啰嗦", "简洁点", etc.
Implicit signals: brevity follow-up, correction patterns, tone shifts.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

# Minimum signal occurrences before persisting to preferences
PERSISTENCE_THRESHOLD = 2

# Sliding window size per signal type
MAX_WINDOW_SIZE = 20


@dataclass
class PreferenceSignal:
    """A single observed preference signal with confidence tracking."""

    key: str
    value: Any
    weight: float  # 0.0-1.0
    source: str  # "explicit" | "implicit"


# ---------------------------------------------------------------------------
# Explicit signal patterns
# ---------------------------------------------------------------------------

EXPLICIT_PATTERNS: list[tuple[str, str, dict[str, Any]]] = [
    # (pattern, description, {key, value})
    ("太长了", "response too long", {"key": "max_length", "value": "shorter"}),
    ("太啰嗦", "too verbose", {"key": "detail_level", "value": "low"}),
    ("说重点", "get to the point", {"key": "communication_style", "value": "brief"}),
    ("简洁点", "be more concise", {"key": "communication_style", "value": "brief"}),
    ("简短", "be brief", {"key": "communication_style", "value": "brief"}),
    ("太短了", "too short", {"key": "detail_level", "value": "high"}),
    ("太简单", "too simple", {"key": "detail_level", "value": "high"}),
    ("详细点", "more detail", {"key": "detail_level", "value": "high"}),
    ("详细一些", "more detailed", {"key": "detail_level", "value": "high"}),
    ("太随便", "too casual", {"key": "tone", "value": "formal"}),
    ("太正式了", "too formal", {"key": "tone", "value": "casual"}),
    ("正式一点", "more formal", {"key": "tone", "value": "formal"}),
    ("太笼统", "too vague", {"key": "detail_level", "value": "high"}),
    ("具体点", "more specific", {"key": "detail_level", "value": "high"}),
    ("太无聊", "too boring", {"key": "engagement", "value": "interesting"}),
    ("有趣一点", "more interesting", {"key": "engagement", "value": "interesting"}),
]


# ---------------------------------------------------------------------------
# StyleSignalDetector
# ---------------------------------------------------------------------------


class StyleSignalDetector:
    """Detects and aggregates style preference signals from conversation.

    Signals flow through:
    1. detect_signals() — scan message + context for explicit/implicit signals
    2. Internal sliding window tracks per-user signal frequency
    3. pending_persists() — returns signals that crossed PERSISTENCE_THRESHOLD
    4. clear_persisted() — reset after writing to preferences
    """

    def __init__(self) -> None:
        # {user_id: [(signal_key, signal_value, weight), ...]}
        self._signal_window: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
        # Set of (key, value) already pending persist
        self._pending: set[tuple[str, str]] = set()

    def detect_signals(
        self,
        user_message: str,
        prior_response: str,
        conversation_history: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Scan for preference signals and update internal window.

        Returns signals observed in this turn (may not yet be ready to persist).
        """
        signals: dict[str, Any] = {}

        # 1. Explicit style feedback
        for pattern, _, mapping in EXPLICIT_PATTERNS:
            if re.search(pattern, user_message):
                key, value = mapping["key"], mapping["value"]
                signals[key] = value
                # Weight explicit signals higher
                self._record_signal("", key, value, weight=1.0)

        # 2. Implicit: brevity follow-up (short message after verbose response)
        is_short = len(user_message.strip()) < 15 and prior_response and len(prior_response) > 200
        is_continuation = any(
            kw in user_message for kw in ["继续", "然后呢", "接着", "还有吗"]
        )
        if is_short and is_continuation and "谢谢" not in user_message:
            signals.setdefault("communication_style", "brief")
            self._record_signal("", "communication_style", "brief", weight=0.8)

        # 3. Implicit: correction pattern (user corrects assistant)
        if any(kw in user_message for kw in ["不对", "不是", "错了", "重新来"]):
            # Correction could mean response was wrong/confusing
            signals.setdefault("tone", "precise")
            self._record_signal("", "tone", "precise", weight=0.6)

        return signals

    def _record_signal(self, user_id: str, key: str, value: str, weight: float) -> None:
        """Record a signal in the sliding window for the user."""
        self._signal_window[user_id].append((key, value, weight))
        if len(self._signal_window[user_id]) > MAX_WINDOW_SIZE:
            self._signal_window[user_id] = self._signal_window[user_id][-MAX_WINDOW_SIZE:]

        # Check if this crosses the persistence threshold
        self._update_pending(key, value)

    def _update_pending(self, key: str, value: str) -> None:
        """Check if a signal has crossed PERSISTENCE_THRESHOLD."""
        # Count recent occurrences of this (key, value) pair
        window = self._signal_window.get("", [])
        count = sum(
            1 for k, v, _ in window if k == key and v == value
        )
        if count >= PERSISTENCE_THRESHOLD:
            self._pending.add((key, value))

    def signal_confidence(self, key: str) -> float:
        """Return current confidence 0.0-1.0 for a preference key."""
        window = self._signal_window.get("", [])
        if not window:
            return 0.0
        # Count signals matching this key
        matches = [w for w in window if w[0] == key]
        return len(matches) / MAX_WINDOW_SIZE

    def pending_persists(self) -> list[dict[str, Any]]:
        """Return signals that have crossed the persistence threshold."""
        return [{"key": k, "value": v} for k, v in self._pending]

    def clear_persisted(self) -> None:
        """Clear pending persists after they have been written."""
        self._pending.clear()


__all__ = ["StyleSignalDetector", "PreferenceSignal", "PERSISTENCE_THRESHOLD"]
