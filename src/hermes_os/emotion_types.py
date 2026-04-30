"""Shared emotion types — broken out to avoid circular imports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EmotionState(Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    STRESSED = "stressed"
    FRUSTRATED = "frustrated"


class TonePreference(Enum):
    RELAXED = "relaxed"
    STRICT = "strict"
    CASUAL = "casual"


@dataclass
class ToneConfig:
    max_length: int = 200
    emoji_prefix: str = ""
    encouraging: bool = False
