"""TestAgent — professional testing strategy and implementation agent for Hermes OS.

Responsibilities:
- Test strategy design (unit, integration, E2E)
- Test case design and coverage analysis
- Test automation framework setup
- Testing best practices and tooling guidance

Note: TestAgent is a testing strategy advisor. It designs testing approaches
and generates test code, not a test runner. Actual test execution uses
CodeAgent or dedicated testing infrastructure.
"""

from __future__ import annotations

from typing import Any

from hermes_os.claude_code_invocator import invoke
from hermes_os.vertical_agent import AgentRequest, AgentResult


TEST_SYSTEM_PROMPT = """你是 Hermes OS 的测试工程专家。

擅长领域：
- 测试策略设计（单元测试/集成测试/E2E）
- 测试用例设计和场景覆盖分析
- 测试框架和工具选型（pytest/Jest/JUnit等）
- 测试自动化和 CI/CD 集成
- 性能测试和负载测试

测试原则：
1. 全面覆盖：核心路径必须被测试覆盖
2. 独立可重复：测试不依赖执行顺序，可重复运行
3. 快速反馈：优先设计能快速执行的测试
4. 真实场景：测试用例贴近真实使用场景

输出风格：
- 测试策略用分层结构（单元→集成→E2E）
- 测试用例用 描述 + given/when/then 格式
- 覆盖率指标用百分比
- 工具推荐用 工具名:用途 格式

当用户询问测试相关问题时，给出专业的测试策略和实施方案。"""


class TestAgent:
    """Testing strategy vertical agent."""

    name = "TestAgent"

    async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
        """Execute testing strategy task."""
        message = request.params.get("message", "")
        persona_block = context.get("persona_block")

        persona_prefix = persona_block.render() if persona_block else ""

        prompt = f"""## 测试任务

### 用户需求
{message}

### 分析要求
1. 确定测试类型和测试范围
2. 设计测试用例和覆盖场景
3. 规划测试工具和框架
4. 给出测试实施步骤

### 输出格式
请以测试方案形式输出，包含：
- **测试范围**：需要测试的功能和模块
- **测试策略**：单元/集成/E2E 分层设计
- **测试用例**：关键场景的 given/when/then
- **工具选型**：推荐的测试框架和工具
- **实施计划**：测试开发步骤和时间线

请直接输出测试方案，不需要解释测试方法论。"""

        try:
            result = await invoke(
                prompt=prompt,
                system_prompt=persona_prefix + "\n" + TEST_SYSTEM_PROMPT if persona_prefix else TEST_SYSTEM_PROMPT,
                cwd=context.get("workspace", "/tmp"),
                model=context.get("model", "sonnet"),
            )

            if result.ok:
                return AgentResult(
                    success=True,
                    output=result.stdout,
                    token_usage=len(result.stdout) // 4,
                )
            else:
                return AgentResult(
                    success=False,
                    error=result.stderr or "Testing planning failed",
                )
        except Exception as e:
            return AgentResult(success=False, error=str(e))