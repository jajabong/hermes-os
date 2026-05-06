"""TDD tests for delegation_protocol.py — task delegation with Feishu progress.

Phase 1: 千人千面管家
P0: 委派协议 — 当管家遇到重度任务时，优雅委派 + 飞书进度推送

核心场景：
1. 管家收到重度任务（写代码/长文/分析报告）
2. 即时回复：「收到，我来处理」
3. 创建 TaskScheduler 任务
4. 飞书推送：「任务进行中」
5. 任务完成 → 飞书推送：「已完成，结果如下」
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Test: DelegationTrigger — 判断是否需要委派
# ---------------------------------------------------------------------------


def test_delegation_trigger_requires_heavy_task() -> None:
    """Heavy tasks (code/long-content/research) should require delegation."""
    from hermes_os.delegation_protocol import DelegationTrigger, TaskComplexity

    trigger = DelegationTrigger()

    # 代码任务 → 需要委派
    assert trigger.classify("帮我写一个 Python 函数") == TaskComplexity.HEAVY
    assert trigger.classify("fix this bug") == TaskComplexity.HEAVY
    assert trigger.classify("写一篇文章") == TaskComplexity.HEAVY
    assert trigger.classify("帮我分析这份报告") == TaskComplexity.HEAVY
    assert trigger.classify("研究一下竞品") == TaskComplexity.HEAVY


def test_delegation_trigger_light_task() -> None:
    """Light tasks (casual chat/simple questions) should not require delegation."""
    from hermes_os.delegation_protocol import DelegationTrigger, TaskComplexity

    trigger = DelegationTrigger()

    # 日常对话 → 不需要委派
    assert trigger.classify("今天天气怎么样？") == TaskComplexity.LIGHT
    assert trigger.classify("你好") == TaskComplexity.LIGHT
    assert trigger.classify("谢谢") == TaskComplexity.LIGHT


def test_delegation_trigger_medium_task() -> None:
    """Medium tasks should be delegatable but not required."""
    from hermes_os.delegation_protocol import DelegationTrigger, TaskComplexity

    trigger = DelegationTrigger()

    # 中等复杂度 → 可委派
    assert trigger.classify("帮我查一下这个概念") == TaskComplexity.MEDIUM
    assert trigger.classify("给我解释一下区块链") == TaskComplexity.MEDIUM


# ---------------------------------------------------------------------------
# Test: DelegationResult — 委派结果数据结构
# ---------------------------------------------------------------------------


def test_delegation_result_fields() -> None:
    """DelegationResult should contain all fields for progress tracking."""
    from hermes_os.delegation_protocol import DelegationResult, DelegationStatus

    result = DelegationResult(
        task_id="task_123",
        user_id="user_abc",
        status=DelegationStatus.DELEGATED,
        title="写一个 Python 函数",
        immediate_reply="收到，我来帮您处理这个代码任务，预计需要 2-3 分钟。",
        agent_name="CodeAgent",
    )

    assert result.task_id == "task_123"
    assert result.status == DelegationStatus.DELEGATED
    assert "代码任务" in result.immediate_reply
    assert result.agent_name == "CodeAgent"


def test_delegation_result_not_delegated() -> None:
    """DelegationResult for LIGHT tasks should have NOT_DELEGATED status."""
    from hermes_os.delegation_protocol import DelegationResult, DelegationStatus

    result = DelegationResult(
        task_id="",
        user_id="user_abc",
        status=DelegationStatus.NOT_DELEGATED,
        title="今天天气怎么样？",
        immediate_reply="今天晴天，适合出行。",
    )

    assert result.status == DelegationStatus.NOT_DELEGATED
    assert result.task_id == ""


# ---------------------------------------------------------------------------
# Test: DelegationProtocol — 完整委派流程
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delegate_heavy_task_creates_scheduler_task() -> None:
    """delegate() for HEAVY task should create a TaskScheduler task."""
    from hermes_os.delegation_protocol import DelegationProtocol

    # Mock TaskScheduler
    mock_scheduler = MagicMock()
    mock_task = MagicMock()
    mock_task.task_id = "task_456"
    mock_scheduler.create_task = AsyncMock(return_value=mock_task)

    # Mock FeishuEnhancer
    mock_feishu = MagicMock()
    mock_feishu.send_card_with_nl = AsyncMock()

    # Mock JarvisInterface
    mock_jarvis = MagicMock()
    mock_jarvis.send_card_with_nl = AsyncMock()

    protocol = DelegationProtocol(
        task_scheduler=mock_scheduler,
        feishu_enhancer=mock_feishu,
        jarvis=mock_jarvis,
    )

    # Mock user
    mock_user = MagicMock()
    mock_user.user_id = "user_abc"
    mock_user.platform = "feishu"
    mock_user.platform_user_id = "ou_123"
    mock_user.name = "张三"

    # HEAVY task
    result = await protocol.delegate(
        user=mock_user,
        message="帮我写一个 Python 函数计算斐波那契数列",
        intent="code",
    )

    # Verify task was created in scheduler
    mock_scheduler.create_task.assert_called_once()
    call_kwargs = mock_scheduler.create_task.call_args.kwargs
    assert call_kwargs["user_id"] == "user_abc"
    assert "斐波那契" in call_kwargs["title"]


@pytest.mark.asyncio
async def test_delegate_light_task_does_not_create_task() -> None:
    """delegate() for LIGHT task should NOT create a TaskScheduler task."""
    from hermes_os.delegation_protocol import DelegationProtocol

    mock_scheduler = MagicMock()
    mock_scheduler.create_task = AsyncMock()

    mock_feishu = MagicMock()
    mock_jarvis = MagicMock()

    protocol = DelegationProtocol(
        task_scheduler=mock_scheduler,
        feishu_enhancer=mock_feishu,
        jarvis=mock_jarvis,
    )

    mock_user = MagicMock()
    mock_user.user_id = "user_abc"
    mock_user.platform = "feishu"
    mock_user.platform_user_id = "ou_123"
    mock_user.name = "张三"

    result = await protocol.delegate(
        user=mock_user,
        message="你好",
        intent="unknown",
    )

    # Should NOT create task
    mock_scheduler.create_task.assert_not_called()
    # Should have immediate reply
    assert result.status.value == "not_delegated"
    assert result.task_id == ""


@pytest.mark.asyncio
async def test_delegate_sends_immediate_feishu_reply() -> None:
    """delegate() should return immediate_feishu_reply for the user to see NOW."""
    from hermes_os.delegation_protocol import DelegationProtocol

    mock_scheduler = MagicMock()
    mock_task = MagicMock()
    mock_task.task_id = "task_789"
    mock_scheduler.create_task = AsyncMock(return_value=mock_task)

    mock_feishu = MagicMock()
    mock_jarvis = MagicMock()

    protocol = DelegationProtocol(
        task_scheduler=mock_scheduler,
        feishu_enhancer=mock_feishu,
        jarvis=mock_jarvis,
    )

    mock_user = MagicMock()
    mock_user.user_id = "user_abc"
    mock_user.platform = "feishu"
    mock_user.platform_user_id = "ou_456"
    mock_user.name = "陆总"

    result = await protocol.delegate(
        user=mock_user,
        message="帮我分析这份投资报告",
        intent="investment",
    )

    # immediate_reply should be set (what the user sees right away)
    assert result.immediate_reply != ""
    assert "收到" in result.immediate_reply or "处理" in result.immediate_reply


@pytest.mark.asyncio
async def test_delegate_attaches_notify_target_to_task() -> None:
    """delegate() should attach Feishu notify_target to the task for progress推送."""
    from hermes_os.delegation_protocol import DelegationProtocol

    mock_scheduler = MagicMock()
    mock_task = MagicMock()
    mock_task.task_id = "task_notify"
    mock_scheduler.create_task = AsyncMock(return_value=mock_task)

    mock_feishu = MagicMock()
    mock_jarvis = MagicMock()

    protocol = DelegationProtocol(
        task_scheduler=mock_scheduler,
        feishu_enhancer=mock_feishu,
        jarvis=mock_jarvis,
    )

    mock_user = MagicMock()
    mock_user.user_id = "user_notify"
    mock_user.platform = "feishu"
    mock_user.platform_user_id = "ou_notify"
    mock_user.name = "周局"

    await protocol.delegate(
        user=mock_user,
        message="写一个技术方案",
        intent="code",
    )

    # Verify notify_target was passed to create_task
    call_kwargs = mock_scheduler.create_task.call_args.kwargs
    metadata = call_kwargs.get("metadata", {})
    assert "notify_target" in metadata
    assert metadata["notify_target"]["type"] == "feishu"


@pytest.mark.asyncio
async def test_delegate_light_question_uses_rich_response() -> None:
    """Light task should return NOT_DELEGATED with a direct rich_response."""
    from hermes_os.delegation_protocol import DelegationProtocol, DelegationStatus

    mock_scheduler = MagicMock()
    mock_feishu = MagicMock()
    mock_jarvis = MagicMock()

    protocol = DelegationProtocol(
        task_scheduler=mock_scheduler,
        feishu_enhancer=mock_feishu,
        jarvis=mock_jarvis,
    )

    mock_user = MagicMock()
    mock_user.user_id = "user_light"
    mock_user.platform = "feishu"
    mock_user.platform_user_id = "ou_light"
    mock_user.name = "小王"

    result = await protocol.delegate(
        user=mock_user,
        message="今天吃什么好？",
        intent="unknown",
    )

    assert result.status == DelegationStatus.NOT_DELEGATED
    assert result.task_id == ""


# ---------------------------------------------------------------------------
# Test: Intent → Agent mapping in delegation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delegate_code_task() -> None:
    """Code intent should route to CodeAgent."""
    from hermes_os.delegation_protocol import DelegationProtocol

    mock_scheduler = MagicMock()
    mock_task = MagicMock()
    mock_task.task_id = "task_code"
    mock_scheduler.create_task = AsyncMock(return_value=mock_task)
    mock_feishu = MagicMock()
    mock_jarvis = MagicMock()

    protocol = DelegationProtocol(
        task_scheduler=mock_scheduler,
        feishu_enhancer=mock_feishu,
        jarvis=mock_jarvis,
    )

    mock_user = MagicMock()
    mock_user.user_id = "user_code"
    mock_user.platform = "feishu"
    mock_user.platform_user_id = "ou_code"
    mock_user.name = "工程师"

    result = await protocol.delegate(
        user=mock_user,
        message="写一个 FastAPI 接口",
        intent="code",
    )

    assert result.agent_name == "CodeAgent"


@pytest.mark.asyncio
async def test_delegate_investment_task() -> None:
    """Investment intent should route to InvestmentAgent."""
    from hermes_os.delegation_protocol import DelegationProtocol

    mock_scheduler = MagicMock()
    mock_task = MagicMock()
    mock_task.task_id = "task_invest"
    mock_scheduler.create_task = AsyncMock(return_value=mock_task)
    mock_feishu = MagicMock()
    mock_jarvis = MagicMock()

    protocol = DelegationProtocol(
        task_scheduler=mock_scheduler,
        feishu_enhancer=mock_feishu,
        jarvis=mock_jarvis,
    )

    mock_user = MagicMock()
    mock_user.user_id = "user_invest"
    mock_user.platform = "feishu"
    mock_user.platform_user_id = "ou_invest"
    mock_user.name = "投资者"

    result = await protocol.delegate(
        user=mock_user,
        message="分析一下这个投资组合",
        intent="investment",
    )

    assert result.agent_name == "InvestmentAgent"


# ---------------------------------------------------------------------------
# Test: DelegationProtocol default construction
# ---------------------------------------------------------------------------


def test_delegation_protocol_default_init() -> None:
    """DelegationProtocol should work with lazy defaults (None → real objects)."""
    from hermes_os.delegation_protocol import DelegationProtocol

    # Should not raise — uses lazy defaults
    protocol = DelegationProtocol()
    assert protocol._task_scheduler is None
    assert protocol._feishu_enhancer is None
    assert protocol._jarvis is None


# ---------------------------------------------------------------------------
# Test: should_delegate() convenience method
# ---------------------------------------------------------------------------


def test_should_delegate_heavy_returns_true() -> None:
    """should_delegate() for HEAVY tasks should return True."""
    from hermes_os.delegation_protocol import DelegationProtocol

    protocol = DelegationProtocol()
    assert protocol.should_delegate("写一篇文章") is True
    assert protocol.should_delegate("帮我分析报告") is True


def test_should_delegate_light_returns_false() -> None:
    """should_delegate() for LIGHT tasks should return False."""
    from hermes_os.delegation_protocol import DelegationProtocol

    protocol = DelegationProtocol()
    assert protocol.should_delegate("你好") is False
    assert protocol.should_delegate("谢谢") is False


# ---------------------------------------------------------------------------
# Test: Feishu card formatting for delegation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delegate_sends_acknowledgement_card() -> None:
    """delegate() should send a Feishu card acknowledging the task start."""
    from hermes_os.delegation_protocol import DelegationProtocol

    mock_scheduler = MagicMock()
    mock_task = MagicMock()
    mock_task.task_id = "task_ack"
    mock_scheduler.create_task = AsyncMock(return_value=mock_task)

    mock_feishu = MagicMock()
    mock_jarvis = MagicMock()

    protocol = DelegationProtocol(
        task_scheduler=mock_scheduler,
        feishu_enhancer=mock_feishu,
        jarvis=mock_jarvis,
    )

    mock_user = MagicMock()
    mock_user.user_id = "user_ack"
    mock_user.platform = "feishu"
    mock_user.platform_user_id = "ou_ack"
    mock_user.name = "张三"

    result = await protocol.delegate(
        user=mock_user,
        message="帮我写一份技术方案",
        intent="code",
    )

    # Should have sent acknowledgement via jarvis
    # (jarvis.send_card_with_nl is called for feishu delivery)
    assert result.task_id == "task_ack"
    assert result.status.value == "delegated"
