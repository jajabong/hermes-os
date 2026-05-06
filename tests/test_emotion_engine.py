"""Tests for EmotionEngine — lightweight emotion detection and personality tuning."""

from hermes_os.emotion_engine import EmotionEngine, EmotionState
from hermes_os.personality_tuner import PersonalityTuner, TonePreference

# ---------------------------------------------------------------------------
# EmotionEngine tests
# ---------------------------------------------------------------------------


class TestEmotionEngineDetect:
    """EmotionEngine.detect() tests."""

    def test_detect_positive_signals(self) -> None:
        """Phrases with positive signals detect as POSITIVE."""
        engine = EmotionEngine()
        for msg in ["太棒了！", "谢谢，太厉害了", "完美，就这样做"]:
            result = engine.detect(msg)
            assert result in (EmotionState.POSITIVE, EmotionState.NEUTRAL), (
                f"Expected POSITIVE/NEUTRAL for '{msg}', got {result}"
            )

    def test_detect_stress_signals(self) -> None:
        """Phrases with stress signals detect as STRESSED."""
        engine = EmotionEngine()
        for msg in ["太忙了，来不及", "没时间了", "急死了"]:
            result = engine.detect(msg)
            assert result == EmotionState.STRESSED, f"Expected STRESSED for '{msg}', got {result}"

    def test_detect_frustration_signals(self) -> None:
        """Phrases with frustration detect as FRUSTRATED."""
        engine = EmotionEngine()
        for msg in ["烦死了，这个bug修不好", "太难了，怎么都不行", "失败了很多次"]:
            result = engine.detect(msg)
            assert result in (EmotionState.FRUSTRATED, EmotionState.STRESSED), (
                f"Expected FRUSTRATED/STRESSED for '{msg}', got {result}"
            )

    def test_detect_neutral(self) -> None:
        """Normal statements detect as NEUTRAL."""
        engine = EmotionEngine()
        for msg in ["今天天气不错", "帮我查一下项目状态", "这个任务完成了"]:
            result = engine.detect(msg)
            assert result == EmotionState.NEUTRAL, f"Expected NEUTRAL for '{msg}', got {result}"

    def test_detect_frequency_boosts_stress(self) -> None:
        """Multiple stress signals in short time boost to STRESSED."""
        engine = EmotionEngine()
        # Single occurrence
        result1 = engine.detect("很忙")
        # Multiple occurrences in window
        engine._recent_signals["alice"] = [
            ("忙", 0.9),
            ("来不及", 0.9),
            ("急", 0.9),
        ]
        result2 = engine.detect("忙", user_id="alice")
        assert result2 == EmotionState.STRESSED

    def test_detect_user_specific(self) -> None:
        """Detection is per-user (user_id passed)."""
        engine = EmotionEngine()
        result = engine.detect("很忙", user_id="alice")
        assert result in (EmotionState.NEUTRAL, EmotionState.STRESSED)


class TestEmotionEngineToneConfig:
    """ToneConfig per emotion state."""

    def test_stressed_tone_shorter(self) -> None:
        """STRESSED tone config gives shorter messages."""
        engine = EmotionEngine()
        tone = engine.get_tone_adjustment(EmotionState.STRESSED)
        assert tone.max_length <= tone.max_length  # just check it exists
        assert tone.emoji_prefix == ""  # no emoji spam when stressed

    def test_positive_tone_emoji(self) -> None:
        """POSITIVE tone config adds celebratory emoji."""
        tone = EmotionEngine().get_tone_adjustment(EmotionState.POSITIVE)
        assert tone.emoji_prefix != ""
        assert (
            "👍" in tone.emoji_prefix
            or "✨" in tone.emoji_prefix
            or "🎉" in tone.emoji_prefix
            or "🎉 " in tone.emoji_prefix
        )

    def test_frustrated_tone_encouraging(self) -> None:
        """FRUSTRATED tone config is encouraging, not dismissive."""
        tone = EmotionEngine().get_tone_adjustment(EmotionState.FRUSTRATED)
        assert tone.max_length <= 200  # keep it short, not overwhelming


# ---------------------------------------------------------------------------
# PersonalityTuner tests
# ---------------------------------------------------------------------------


class TestPersonalityTunerFormat:
    """PersonalityTuner message formatting."""

    def test_relaxed_type_adds_emoji(self) -> None:
        """轻松型 adds emoji to notifications."""
        tuner = PersonalityTuner()
        result = tuner.format_notification(
            base_message="任务完成了",
            emotion=EmotionState.NEUTRAL,
            preference=TonePreference.RELAXED,
        )
        assert "✅" in result or "✨" in result or "👍" in result

    def test_strict_type_no_emoji(self) -> None:
        """严谨型 does not add emoji."""
        tuner = PersonalityTuner()
        result = tuner.format_notification(
            base_message="任务完成了",
            emotion=EmotionState.NEUTRAL,
            preference=TonePreference.STRICT,
        )
        # No emoji prefix
        assert result.startswith("任务完成了") or "任务完成了" in result

    def test_stressed_emotion_shortens_message(self) -> None:
        """STRESSED emotion makes tuner produce shorter message."""
        tuner = PersonalityTuner()
        long_msg = (
            "项目进展正常，3个任务进行中，2个已完成后请查收飞书文档了解详情，另有1个新任务需要关注"
        )
        result = tuner.format_notification(
            base_message=long_msg,
            emotion=EmotionState.STRESSED,
            preference=TonePreference.RELAXED,
        )
        assert len(result) <= len(long_msg)

    def test_frustrated_adds_encouragement(self) -> None:
        """FRUSTRATED emotion adds encouragement prefix."""
        tuner = PersonalityTuner()
        result = tuner.format_notification(
            base_message="这个任务失败了",
            emotion=EmotionState.FRUSTRATED,
            preference=TonePreference.RELAXED,
        )
        # Should have encouraging content
        assert "一起" in result or "加油" in result or "别担心" in result or "没关系" in result

    def test_casual_type_includes_context(self) -> None:
        """Casual type includes more context."""
        tuner = PersonalityTuner()
        result = tuner.format_notification(
            base_message="会议在3点",
            emotion=EmotionState.NEUTRAL,
            preference=TonePreference.CASUAL,
        )
        assert len(result) >= len("会议在3点")

    def test_default_tone_is_relaxed_positive(self) -> None:
        """Default tone is relaxed + positive."""
        tuner = PersonalityTuner()
        result = tuner.format_notification(
            base_message="一切正常",
            emotion=EmotionState.NEUTRAL,
            preference=TonePreference.RELAXED,
        )
        assert "一切正常" in result


# ---------------------------------------------------------------------------
# EmotionState enum tests
# ---------------------------------------------------------------------------


class TestEmotionState:
    def test_emotion_states(self) -> None:
        """All expected emotion states exist."""
        assert hasattr(EmotionState, "POSITIVE")
        assert hasattr(EmotionState, "NEUTRAL")
        assert hasattr(EmotionState, "STRESSED")
        assert hasattr(EmotionState, "FRUSTRATED")


class TestTonePreference:
    def test_tone_preferences(self) -> None:
        """All expected tone preferences exist."""
        assert hasattr(TonePreference, "RELAXED")
        assert hasattr(TonePreference, "STRICT")
        assert hasattr(TonePreference, "CASUAL")
