"""TDD tests for topic_tracker.py — cross-session memory continuity.

Phase 1: 千人千面管家
P0: 记忆粘性 — 当用户说「接着上次那件事继续」时，无缝续接

核心场景：
1. 用户开始一个新任务 → TopicTracker 记录 last_task_id + last_topic
2. 用户断开连接后再来 → 系统能查询「用户最后一个未完成的任务」
3. 用户说「接着上次」→ 系统能定位到那个任务并续接
4. 任务完成 → 更新 last_topic 为空或新任务
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Test: TopicTracker — 记录当前话题
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_topic_creates_context_file(tmp_path: Path) -> None:
    """record_topic() should create/update brain/LAST_TOPIC.md."""
    from hermes_os.topic_tracker import TopicTracker

    tracker = TopicTracker(user_id="user_topic1", base_path=tmp_path)

    await tracker.record_topic(
        topic="陆总的投资组合分析",
        task_id="task_123",
        intent="investment",
    )

    # Verify file was created
    topic_file = tmp_path / "user_topic1" / "brain" / "LAST_TOPIC.md"
    assert topic_file.exists()

    content = topic_file.read_text()
    assert "陆总的投资组合分析" in content
    assert "task_123" in content
    assert "investment" in content


@pytest.mark.asyncio
async def test_record_topic_overwrites_previous_topic(tmp_path: Path) -> None:
    """record_topic() should overwrite the previous topic (new task replaces old)."""
    from hermes_os.topic_tracker import TopicTracker

    tracker = TopicTracker(user_id="user_overwrite", base_path=tmp_path)

    # Record first topic
    await tracker.record_topic(
        topic="第一件事：合同审查",
        task_id="task_old",
        intent="legal",
    )

    # Record new topic (simulating new task)
    await tracker.record_topic(
        topic="第二件事：代码开发",
        task_id="task_new",
        intent="code",
    )

    topic_file = tmp_path / "user_overwrite" / "brain" / "LAST_TOPIC.md"
    content = topic_file.read_text()

    assert "task_new" in content
    assert "第二件事" in content
    assert "task_old" not in content


@pytest.mark.asyncio
async def test_get_current_topic_returns_none_when_no_topic(tmp_path: Path) -> None:
    """get_current_topic() should return None when no topic has been recorded."""
    from hermes_os.topic_tracker import TopicTracker

    tracker = TopicTracker(user_id="user_no_topic", base_path=tmp_path)
    result = await tracker.get_current_topic()

    assert result is None


@pytest.mark.asyncio
async def test_get_current_topic_returns_last_recorded(tmp_path: Path) -> None:
    """get_current_topic() should return the most recently recorded topic."""
    from hermes_os.topic_tracker import TopicTracker

    tracker = TopicTracker(user_id="user_current", base_path=tmp_path)

    await tracker.record_topic(
        topic="技术方案设计",
        task_id="task_456",
        intent="code",
    )

    result = await tracker.get_current_topic()

    assert result is not None
    assert result.topic == "技术方案设计"
    assert result.task_id == "task_456"
    assert result.intent == "code"


@pytest.mark.asyncio
async def test_get_current_topic_with_incomplete_task(tmp_path: Path) -> None:
    """get_current_topic() should return topic even when task is incomplete."""
    from hermes_os.topic_tracker import TopicTracker

    tracker = TopicTracker(user_id="user_incomplete", base_path=tmp_path)

    await tracker.record_topic(
        topic="投资报告撰写",
        task_id="task_incomplete",
        intent="investment",
    )

    result = await tracker.get_current_topic()

    assert result is not None
    assert result.task_id == "task_incomplete"
    assert result.is_incomplete is True  # task not marked complete


@pytest.mark.asyncio
async def test_complete_topic_clears_current_topic(tmp_path: Path) -> None:
    """complete_topic() should clear the current topic (or mark it complete)."""
    from hermes_os.topic_tracker import TopicTracker

    tracker = TopicTracker(user_id="user_complete", base_path=tmp_path)

    await tracker.record_topic(
        topic="合同审查",
        task_id="task_complete",
        intent="legal",
    )

    await tracker.complete_topic(task_id="task_complete")

    result = await tracker.get_current_topic()
    # After completion, current topic should be cleared or marked complete
    assert result is None or result.is_incomplete is False


# ---------------------------------------------------------------------------
# Test: TopicContext dataclass
# ---------------------------------------------------------------------------


def test_topic_context_fields() -> None:
    """TopicContext should have all required fields for resuming a task."""
    from hermes_os.topic_tracker import TopicContext

    ctx = TopicContext(
        topic="技术方案",
        task_id="task_789",
        intent="code",
        recorded_at="2026-05-06T10:00:00",
    )

    assert ctx.topic == "技术方案"
    assert ctx.task_id == "task_789"
    assert ctx.intent == "code"
    assert ctx.is_incomplete is True  # default


def test_topic_context_is_incomplete_default() -> None:
    """TopicContext.is_incomplete should default to True (task is ongoing)."""
    from hermes_os.topic_tracker import TopicContext

    ctx = TopicContext(
        topic="测试",
        task_id="task_test",
        intent="test",
        recorded_at="2026-05-06",
    )
    assert ctx.is_incomplete is True


# ---------------------------------------------------------------------------
# Test: TopicTracker — 与 TaskScheduler 集成
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_from_topic_links_to_task(tmp_path: Path) -> None:
    """resume_from_topic() should return task details for continuing work."""
    from hermes_os.topic_tracker import TopicTracker

    tracker = TopicTracker(user_id="user_resume", base_path=tmp_path)

    await tracker.record_topic(
        topic="FastAPI 接口开发",
        task_id="task_fastapi",
        intent="code",
    )

    # Simulate user coming back and saying "接着上次继续"
    context = await tracker.resume_from_topic()

    assert context is not None
    assert context.task_id == "task_fastapi"
    assert "FastAPI" in context.topic


@pytest.mark.asyncio
async def test_resume_from_topic_returns_none_when_no_topic(tmp_path: Path) -> None:
    """resume_from_topic() should return None when no topic has been recorded."""
    from hermes_os.topic_tracker import TopicTracker

    tracker = TopicTracker(user_id="user_no_resume", base_path=tmp_path)
    result = await tracker.resume_from_topic()

    assert result is None


@pytest.mark.asyncio
async def test_topic_tracker_with_task_scheduler_integration(tmp_path: Path) -> None:
    """TopicTracker should work with TaskScheduler to find user's last incomplete task."""
    from hermes_os.topic_tracker import TopicTracker

    # Simulate TaskScheduler storage
    tasks_file = tmp_path / "user_scheduler" / "tasks.json"
    tasks_file.parent.mkdir(parents=True, exist_ok=True)
    tasks_file.write_text("""[
        {"task_id": "task_1", "title": "已完成任务", "status": "completed", "user_id": "user_scheduler"},
        {"task_id": "task_2", "title": "未完成合同审查", "status": "pending", "user_id": "user_scheduler"}
    ]""")

    tracker = TopicTracker(user_id="user_scheduler", base_path=tmp_path)

    # Record topic pointing to incomplete task
    await tracker.record_topic(
        topic="未完成合同审查",
        task_id="task_2",
        intent="legal",
    )

    # User says "接着上次继续"
    context = await tracker.resume_from_topic()

    assert context is not None
    assert context.task_id == "task_2"
    assert context.is_incomplete is True


# ---------------------------------------------------------------------------
# Test: TopicTracker — 「接着」检测
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_continuation_intent_接着(tmp_path: Path) -> None:
    """detect_and_resume() should return True when user says 接着/继续/然后 AND has topic."""
    from hermes_os.topic_tracker import TopicTracker

    tracker = TopicTracker(user_id="user_detect", base_path=tmp_path)
    await tracker.record_topic(
        topic="投资组合分析",
        task_id="task_invest",
        intent="investment",
    )

    # Various "接着" patterns — should all resume when topic exists
    should_resume, ctx = await tracker.detect_and_resume("接着上次那件事继续")
    assert should_resume is True

    should_resume2, _ = await tracker.detect_and_resume("继续上次的任务")
    assert should_resume2 is True

    should_resume3, _ = await tracker.detect_and_resume("然后呢")
    assert should_resume3 is True

    should_resume4, _ = await tracker.detect_and_resume("继续")
    assert should_resume4 is True


@pytest.mark.asyncio
async def test_detect_continuation_returns_false_for_new_task(tmp_path: Path) -> None:
    """detect_and_resume() should return False for new task requests (no continuation signal)."""
    from hermes_os.topic_tracker import TopicTracker

    tracker = TopicTracker(user_id="user_new_task", base_path=tmp_path)
    await tracker.record_topic(
        topic="旧任务",
        task_id="task_old",
        intent="unknown",
    )

    should_resume1, _ = await tracker.detect_and_resume("帮我查一下天气")
    assert should_resume1 is False

    should_resume2, _ = await tracker.detect_and_resume("写一篇文章")
    assert should_resume2 is False


@pytest.mark.asyncio
async def test_detect_continuation_returns_false_when_no_topic(tmp_path: Path) -> None:
    """detect_and_resume() should return False when no topic recorded."""
    from hermes_os.topic_tracker import TopicTracker

    tracker = TopicTracker(user_id="user_empty", base_path=tmp_path)
    # No topic recorded

    # detect_and_resume checks both message intent AND topic existence
    should_resume, ctx = await tracker.detect_and_resume("接着上次继续")
    assert should_resume is False
    assert ctx is None


# ---------------------------------------------------------------------------
# Test: TopicTracker — 话题摘要生成
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_topic_summary(tmp_path: Path) -> None:
    """get_topic_summary() should return a human-readable summary of current topic."""
    from hermes_os.topic_tracker import TopicTracker

    tracker = TopicTracker(user_id="user_summary", base_path=tmp_path)

    await tracker.record_topic(
        topic="陆总的投资组合分析",
        task_id="task_summary",
        intent="investment",
    )

    summary = await tracker.get_topic_summary()

    assert summary is not None
    assert "投资" in summary or "上次" in summary


@pytest.mark.asyncio
async def test_get_topic_summary_returns_none_when_no_topic(tmp_path: Path) -> None:
    """get_topic_summary() should return None when no topic recorded."""
    from hermes_os.topic_tracker import TopicTracker

    tracker = TopicTracker(user_id="user_no_summary", base_path=tmp_path)
    result = await tracker.get_topic_summary()

    assert result is None


# ---------------------------------------------------------------------------
# Test: TopicTracker — 跨 session 持久化
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topic_persists_across_sessions(tmp_path: Path) -> None:
    """Topic recorded in one session should be accessible in another session."""
    from hermes_os.topic_tracker import TopicTracker

    # Session 1: User works on a task
    tracker1 = TopicTracker(user_id="user_persist", base_path=tmp_path)
    await tracker1.record_topic(
        topic="技术方案设计",
        task_id="task_persist",
        intent="code",
    )

    # Session 2: User comes back (new tracker instance)
    tracker2 = TopicTracker(user_id="user_persist", base_path=tmp_path)
    context = await tracker2.get_current_topic()

    assert context is not None
    assert context.task_id == "task_persist"
    assert context.topic == "技术方案设计"
