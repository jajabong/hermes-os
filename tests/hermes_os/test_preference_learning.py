"""TDD: Preference Learning loop — StyleSignalDetector.

RED Phase: Write tests that expose the missing preference learning.
GREEN Phase: Implement StyleSignalDetector and wire into UnifiedRouter.

Signal types:
1. Explicit: user says "太长了", "太啰嗦", "简洁点" directly
2. Implicit: brevity follow-up, correction patterns, tone shifts
"""

from __future__ import annotations

import pytest

from hermes_os.preference_learning import StyleSignalDetector


class TestStyleSignalDetectorExplicit:
    """Explicit style feedback detection."""

    def test_detects_too_long(self) -> None:
        detector = StyleSignalDetector()
        signals = detector.detect_signals(
            user_message="太长了，看不完",
            prior_response="这是一段很长的分析...",
            conversation_history=[],
        )
        assert "max_length" in signals or "detail_level" in signals

    def test_detects_too_verbose(self) -> None:
        detector = StyleSignalDetector()
        signals = detector.detect_signals(
            user_message="太啰嗦了，说重点",
            prior_response="详细分析如下...",
            conversation_history=[],
        )
        assert "detail_level" in signals

    def test_detects_brief_request(self) -> None:
        detector = StyleSignalDetector()
        signals = detector.detect_signals(
            user_message="简洁点",
            prior_response="详细说明...",
            conversation_history=[],
        )
        assert signals.get("communication_style") == "brief"

    def test_detects_detail_request(self) -> None:
        detector = StyleSignalDetector()
        signals = detector.detect_signals(
            user_message="太简单了，详细一些",
            prior_response="简短结论...",
            conversation_history=[],
        )
        assert signals.get("detail_level") == "high"

    def test_detects_formal_request(self) -> None:
        detector = StyleSignalDetector()
        signals = detector.detect_signals(
            user_message="太随便了，正式一点",
            prior_response="随便说说...",
            conversation_history=[],
        )
        assert signals.get("tone") == "formal"

    def test_no_signal_for_neutral_message(self) -> None:
        detector = StyleSignalDetector()
        signals = detector.detect_signals(
            user_message="帮我分析一下茅台股票",
            prior_response="贵州茅台分析...",
            conversation_history=[],
        )
        assert signals == {}

    def test_no_signal_for_thanks(self) -> None:
        detector = StyleSignalDetector()
        signals = detector.detect_signals(
            user_message="谢谢，很好",
            prior_response="分析报告已完成",
            conversation_history=[],
        )
        assert signals == {}


class TestStyleSignalDetectorImplicit:
    """Implicit style inference from conversation patterns."""

    def test_short_follow_up_implies_brief_style(self) -> None:
        detector = StyleSignalDetector()
        # Prior response is long (>200 chars), user follows up with very short message
        long_response = "以下是对该项目的详细分析。首先，我们需要考虑多个因素。第一，技术可行性方面，该项目采用了最新的分布式架构设计。第二，市场前景方面，经过深入调研，我们发现该领域正在快速增长。第三，团队能力方面，成员们都拥有丰富的行业经验。" * 2
        signals = detector.detect_signals(
            user_message="继续",
            prior_response=long_response,
            conversation_history=[
                {"role": "user", "content": "分析一下这个项目"},
                {"role": "assistant", "content": "这是一个复杂项目..."},
            ],
        )
        # Short continuation after verbose response = brief style preference
        assert signals.get("communication_style") == "brief"

    def test_correction_implies_style_mismatch(self) -> None:
        detector = StyleSignalDetector()
        signals = detector.detect_signals(
            user_message="不对，不是这样",
            prior_response="分析如下...",
            conversation_history=[],
        )
        assert len(signals) > 0  # Some style adjustment signal

    def test_repeated_short_follow_ups_strengthens_brief(self) -> None:
        detector = StyleSignalDetector()
        long_response = "详细分析如下。以下是关于该项目的全面讨论。" * 10
        # Record multiple brief follow-up signals
        for msg in ["继续", "然后呢", "还有吗", "继续说"]:
            detector.detect_signals(
                user_message=msg,
                prior_response=long_response,
                conversation_history=[],
            )
        # With 4 signals in a 20-slot window, confidence = 4/20 = 0.2
        assert detector.signal_confidence("communication_style") >= 0.1
        # Pending persists should be empty (need PERSISTENCE_THRESHOLD=2 same-value signals)
        # But here the key is the same, so pending should have it
        assert len(detector.pending_persists()) >= 1


class TestStyleSignalDetectorPersistence:
    """Signal aggregation and persistence threshold."""

    def test_single_signal_below_persistence_threshold(self) -> None:
        detector = StyleSignalDetector()
        signals = detector.detect_signals(
            user_message="太长了",
            prior_response="长文本...",
            conversation_history=[],
        )
        # Below threshold, nothing to persist yet
        assert len(detector.pending_persists()) == 0

    def test_repeated_signals_cross_threshold(self) -> None:
        detector = StyleSignalDetector()
        # Fire the same signal 2 times
        detector.detect_signals("太长了", "长文本1", [])
        detector.detect_signals("太长了", "长文本2", [])
        # Now should be above threshold
        pending = detector.pending_persists()
        assert len(pending) >= 1
        assert any(p.get("key") in ("max_length", "detail_level") for p in pending)

    def test_different_signals_dont_cross_threshold_together(self) -> None:
        detector = StyleSignalDetector()
        # One "太长了" + one "太正式了" = 2 signals but 2 different types
        detector.detect_signals("太长了", "长文本", [])
        detector.detect_signals("太正式了", "正式文本", [])
        # Neither crosses 2x threshold alone
        pending = detector.pending_persists()
        assert len(pending) == 0

    def test_clear_stale_signals(self) -> None:
        detector = StyleSignalDetector()
        detector.detect_signals("太长了", "长文本", [])
        detector.detect_signals("太长了", "长文本2", [])
        # Clear after persistence
        detector.clear_persisted()
        assert len(detector.pending_persists()) == 0
