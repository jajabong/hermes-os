"""PersonalityTuner — adjusts message tone based on emotion and user preference."""

from __future__ import annotations

from hermes_os.emotion_types import EmotionState, TonePreference


_ENCOURAGEMENT_PHRASES = ["一起加油", "别担心", "没关系", "慢慢来", "你能行的"]


class PersonalityTuner:
    """
    Adjusts notification tone based on emotion + user preference.

    Combines EmotionEngine's tone config with personality style.
    """

    def format_notification(
        self,
        base_message: str,
        emotion: EmotionState,
        preference: TonePreference,
    ) -> str:
        """
        Format a notification for a user with given emotion and preference.

        Rules:
        - RELAXED: adds emoji, friendly tone
        - STRICT: plain, no emoji, concise
        - CASUAL: more context, conversational
        - STRESSED: shorter messages, no emoji spam
        - FRUSTRATED: adds encouragement prefix
        """
        # Determine tone config
        if emotion == EmotionState.STRESSED:
            max_length = 150
            emoji_prefix = ""
            encouraging = True
        elif emotion == EmotionState.FRUSTRATED:
            max_length = 180
            emoji_prefix = ""
            encouraging = True
        elif emotion == EmotionState.POSITIVE:
            max_length = 200
            emoji_prefix = "🎉 "
            encouraging = False
        else:
            max_length = 200
            emoji_prefix = ""
            encouraging = False

        # Frustrated always gets encouragement
        if emotion == EmotionState.FRUSTRATED:
            phrase = _ENCOURAGEMENT_PHRASES[0]
            base_message = f"{phrase}，{base_message}"

        # Apply emotion-based shortening
        if len(base_message) > max_length:
            base_message = base_message[: max_length - 3] + "..."

        # Apply preference-based formatting
        if preference == TonePreference.RELAXED:
            return self._format_relaxed(base_message, emoji_prefix, emotion)
        if preference == TonePreference.STRICT:
            return self._format_strict(base_message, emotion)
        if preference == TonePreference.CASUAL:
            return self._format_casual(base_message, emotion)

        return base_message

    def _format_relaxed(
        self, message: str, emoji_prefix: str, emotion: EmotionState
    ) -> str:
        if emoji_prefix:
            return f"{emoji_prefix}{message}"
        # Default emoji for neutral/relaxed
        if emotion == EmotionState.NEUTRAL:
            return f"✅ {message}"
        return message

    def _format_strict(self, message: str, emotion: EmotionState) -> str:
        """Strict: no emoji, plain message."""
        return message

    def _format_casual(self, message: str, emotion: EmotionState) -> str:
        """Casual: conversational, slightly longer."""
        prefix = ""
        if emotion == EmotionState.POSITIVE:
            prefix = "嘿～"
        elif emotion == EmotionState.NEUTRAL:
            prefix = "对了，"
        return f"{prefix}{message}"


__all__ = ["PersonalityTuner", "TonePreference"]
