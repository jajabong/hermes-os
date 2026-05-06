"""ReviewAgent — professional code review and architecture assessment agent for Hermes OS.

Responsibilities:
- Code quality and best practices review
- Architecture design assessment
- Security vulnerability identification
- Performance and scalability analysis

ReviewAgent provides expert review opinions, NOT automated linting.
It gives thoughtful, actionable feedback like a senior engineer would in PR review.
"""

from __future__ import annotations

from typing import Any

from hermes_os.claude_code_invocator import invoke
from hermes_os.vertical_agent import AgentRequest, AgentResult


REVIEW_SYSTEM_PROMPT = """你是 Hermes OS 的代码审查专家。

擅长领域：
- 代码质量评估和最佳实践检查
- 系统架构设计评审
- 安全漏洞发现和修复建议
- 性能瓶颈和可扩展性问题识别
- 技术债务评估和优化建议

审查原则：
1. 质量优先：确保代码达到生产标准
2. 建设性反馈：指出问题的同时给出解决方案
3. 不遗漏风险：安全、隐私问题优先处理
4. 实际可行：建议考虑团队现有能力

输出风格：
- 问题的严重程度：🔴严重 / 🟡一般 / 🟢建议
- 代码位置用文件:行号标注
- 建议用 "考虑 xxx" / "推荐 xxx" 格式
- 好的实践用 ✅ 肯定

当用户提交代码或架构设计请求审查时，给出专业、细致的评审意见。"""


class ReviewAgent:
    """Code review vertical agent."""

    name = "ReviewAgent"

    async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
        """Execute code review task."""
        message = request.params.get("message", "")
        persona_block = context.get("persona_block")

        persona_prefix = persona_block.render() if persona_block else ""

        prompt = f"""## 代码审查任务

### 待审查内容
{message}

### 审查要求
1. 代码质量：可读性、可维护性、风格一致
2. 架构设计：模块化、解耦、扩展性
3. 安全检查：注入、越权、敏感数据处理
4. 性能分析：时间/空间复杂度、资源效率

### 输出格式
请以审查报告形式输出，包含：
- **概述**：审查范围和目标
- **问题列表**：🔴严重 / 🟡一般 / 🟢建议
- **详细分析**：每个问题的位置、原因、影响
- **修改建议**：具体可操作的改进方案
- **优点肯定**：✅ 做得好的地方

请直接输出审查报告，不需要解释审查方法论。"""

        try:
            result = await invoke(
                prompt=prompt,
                system_prompt=persona_prefix + "\n" + REVIEW_SYSTEM_PROMPT if persona_prefix else REVIEW_SYSTEM_PROMPT,
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
                    error=result.stderr or "Code review failed",
                )
        except Exception as e:
            return AgentResult(success=False, error=str(e))