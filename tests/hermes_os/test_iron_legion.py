"""Tests for Iron Legion — professional domain agents."""

from __future__ import annotations

import pytest

from hermes_os.agents.book_pipeline_agent import BookPipelineAgent
from hermes_os.agents.deploy_agent import DeployAgent
from hermes_os.agents.education_agent import EducationAgent
from hermes_os.agents.investment_agent import InvestmentAgent
from hermes_os.agents.legal_agent import LegalAgent
from hermes_os.agents.review_agent import ReviewAgent
from hermes_os.agents.test_agent import TestAgent
from hermes_os.vertical_agent import AgentRequest, AgentResult


# ---------------------------------------------------------------------------
# InvestmentAgent tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_investment_agent_has_invoke() -> None:
    """InvestmentAgent should have an invoke method."""
    agent = InvestmentAgent()
    assert hasattr(agent, "invoke")


@pytest.mark.asyncio
async def test_investment_agent_invoke_returns_agent_result() -> None:
    """InvestmentAgent.invoke() should return an AgentResult."""
    agent = InvestmentAgent()
    request = AgentRequest(
        intent="investment",
        params={"message": "分析一下我的投资组合"},
        context={},
    )
    result = await agent.invoke(request, {})
    assert isinstance(result, AgentResult)


@pytest.mark.asyncio
async def test_investment_agent_has_domain_system_prompt() -> None:
    """InvestmentAgent should have a domain-specific system prompt."""
    from hermes_os.agents.investment_agent import INVESTMENT_SYSTEM_PROMPT

    assert "投资" in INVESTMENT_SYSTEM_PROMPT
    assert "资产配置" in INVESTMENT_SYSTEM_PROMPT
    assert "风险" in INVESTMENT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# LegalAgent tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legal_agent_has_invoke() -> None:
    """LegalAgent should have an invoke method."""
    agent = LegalAgent()
    assert hasattr(agent, "invoke")


@pytest.mark.asyncio
async def test_legal_agent_invoke_returns_agent_result() -> None:
    """LegalAgent.invoke() should return an AgentResult."""
    agent = LegalAgent()
    request = AgentRequest(
        intent="legal",
        params={"message": "帮我审查这份合同"},
        context={},
    )
    result = await agent.invoke(request, {})
    assert isinstance(result, AgentResult)


@pytest.mark.asyncio
async def test_legal_agent_has_domain_system_prompt() -> None:
    """LegalAgent should have a domain-specific system prompt."""
    from hermes_os.agents.legal_agent import LEGAL_SYSTEM_PROMPT

    assert "法律" in LEGAL_SYSTEM_PROMPT
    assert "合同" in LEGAL_SYSTEM_PROMPT
    assert "风险" in LEGAL_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# EducationAgent tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_education_agent_has_invoke() -> None:
    """EducationAgent should have an invoke method."""
    agent = EducationAgent()
    assert hasattr(agent, "invoke")


@pytest.mark.asyncio
async def test_education_agent_invoke_returns_agent_result() -> None:
    """EducationAgent.invoke() should return an AgentResult."""
    agent = EducationAgent()
    request = AgentRequest(
        intent="education",
        params={"message": "帮我规划一下学习路径"},
        context={},
    )
    result = await agent.invoke(request, {})
    assert isinstance(result, AgentResult)


@pytest.mark.asyncio
async def test_education_agent_has_domain_system_prompt() -> None:
    """EducationAgent should have a domain-specific system prompt."""
    from hermes_os.agents.education_agent import EDUCATION_SYSTEM_PROMPT

    assert "教育" in EDUCATION_SYSTEM_PROMPT
    assert "学习" in EDUCATION_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# DeployAgent tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deploy_agent_has_invoke() -> None:
    """DeployAgent should have an invoke method."""
    agent = DeployAgent()
    assert hasattr(agent, "invoke")


@pytest.mark.asyncio
async def test_deploy_agent_invoke_returns_agent_result() -> None:
    """DeployAgent.invoke() should return an AgentResult."""
    agent = DeployAgent()
    request = AgentRequest(
        intent="deploy",
        params={"message": "帮我设计 K8s 部署方案"},
        context={},
    )
    result = await agent.invoke(request, {})
    assert isinstance(result, AgentResult)


@pytest.mark.asyncio
async def test_deploy_agent_has_domain_system_prompt() -> None:
    """DeployAgent should have a domain-specific system prompt."""
    from hermes_os.agents.deploy_agent import DEPLOY_SYSTEM_PROMPT

    assert "部署" in DEPLOY_SYSTEM_PROMPT
    assert "K8s" in DEPLOY_SYSTEM_PROMPT or "Kubernetes" in DEPLOY_SYSTEM_PROMPT or "Docker" in DEPLOY_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# ReviewAgent tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_agent_has_invoke() -> None:
    """ReviewAgent should have an invoke method."""
    agent = ReviewAgent()
    assert hasattr(agent, "invoke")


@pytest.mark.asyncio
async def test_review_agent_invoke_returns_agent_result() -> None:
    """ReviewAgent.invoke() should return an AgentResult."""
    agent = ReviewAgent()
    request = AgentRequest(
        intent="review",
        params={"message": "帮我审查这段代码"},
        context={},
    )
    result = await agent.invoke(request, {})
    assert isinstance(result, AgentResult)


@pytest.mark.asyncio
async def test_review_agent_has_domain_system_prompt() -> None:
    """ReviewAgent should have a domain-specific system prompt."""
    from hermes_os.agents.review_agent import REVIEW_SYSTEM_PROMPT

    assert "审查" in REVIEW_SYSTEM_PROMPT
    assert "代码" in REVIEW_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# TestAgent tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_agent_has_invoke() -> None:
    """TestAgent should have an invoke method."""
    agent = TestAgent()
    assert hasattr(agent, "invoke")


@pytest.mark.asyncio
async def test_test_agent_invoke_returns_agent_result() -> None:
    """TestAgent.invoke() should return an AgentResult."""
    agent = TestAgent()
    request = AgentRequest(
        intent="test",
        params={"message": "帮我设计测试策略"},
        context={},
    )
    result = await agent.invoke(request, {})
    assert isinstance(result, AgentResult)


@pytest.mark.asyncio
async def test_test_agent_has_domain_system_prompt() -> None:
    """TestAgent should have a domain-specific system prompt."""
    from hermes_os.agents.test_agent import TEST_SYSTEM_PROMPT

    assert "测试" in TEST_SYSTEM_PROMPT
    assert "pytest" in TEST_SYSTEM_PROMPT or "测试框架" in TEST_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# BookPipelineAgent tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_book_pipeline_agent_has_invoke() -> None:
    """BookPipelineAgent should have an invoke method."""
    agent = BookPipelineAgent()
    assert hasattr(agent, "invoke")


@pytest.mark.asyncio
async def test_book_pipeline_agent_invoke_returns_agent_result() -> None:
    """BookPipelineAgent.invoke() should return an AgentResult."""
    agent = BookPipelineAgent()
    request = AgentRequest(
        intent="write_book",
        params={"message": "帮我写一本关于 AI 的书"},
        context={"workspace": "/tmp"},
    )
    result = await agent.invoke(request, {})
    assert isinstance(result, AgentResult)


# ---------------------------------------------------------------------------
# All Iron Legion agents registered
# ---------------------------------------------------------------------------


def test_iron_legion_agents_all_have_invoke() -> None:
    """All 7 Iron Legion agents should have working invoke methods."""
    agents = [
        InvestmentAgent(),
        LegalAgent(),
        EducationAgent(),
        DeployAgent(),
        ReviewAgent(),
        TestAgent(),
        BookPipelineAgent(),
    ]
    for agent in agents:
        assert callable(agent.invoke), f"{agent.name} missing invoke()"


def test_iron_legion_names_match_intent_constants() -> None:
    """Iron Legion agent names should match INTENT_AGENT_MAP."""
    from hermes_os.intent_constants import INTENT_AGENT_MAP

    expected = [
        "InvestmentAgent",
        "LegalAgent",
        "EducationAgent",
        "DeployAgent",
        "ReviewAgent",
        "TestAgent",
        "BookPipelineAgent",
    ]
    for name in expected:
        assert name in INTENT_AGENT_MAP.values(), f"{name} not in INTENT_AGENT_MAP"