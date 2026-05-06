"""InvestmentAgent — professional investment analysis agent for Hermes OS.

Responsibilities:
- Portfolio analysis and asset allocation recommendations
- Stock/fund research and performance analysis
- Risk assessment and management
- Financial planning and investment strategy

Uses invoke() (claude -p) as the execution primitive, wrapped in domain-specific persona.
"""

from __future__ import annotations

from typing import Any

from hermes_os.claude_code_invocator import invoke
from hermes_os.vertical_agent import AgentRequest, AgentResult


INVESTMENT_SYSTEM_PROMPT = """你是 Hermes OS 的投资分析专家。

擅长领域：
- 股票、基金、债券、期货等金融产品分析
- 资产配置和组合管理
- 风险评估和收益分析
- 投资策略制定和优化
- 市场研究和竞品分析

分析原则：
1. 数据驱动：所有结论基于客观数据，不掺杂主观情绪
2. 风险优先：充分揭示风险，给出缓释建议
3. 组合优化：在风险和收益间找到最优平衡
4. 可执行性：建议具有实际可操作性

输出风格：
- 结构化分析报告（背景→数据→分析→建议）
- 数据可视化建议（图表类型、指标选择）
- 风险提示醒目（⚠️）
- 关键指标用 **加粗**

当用户询问投资相关问题时，给出专业、全面的分析。"""


class InvestmentAgent:
    """Investment analysis vertical agent."""

    name = "InvestmentAgent"

    async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
        """Execute investment analysis task."""
        message = request.params.get("message", "")
        user = context.get("user")
        user_id = getattr(user, "user_id", "unknown") if user else "unknown"
        persona_block = context.get("persona_block")

        persona_prefix = persona_block.render() if persona_block else ""

        prompt = f"""## 投资分析任务

### 用户需求
{message}

### 分析要求
1. 明确分析对象和分析维度
2. 给出数据来源和建议指标
3. 提供可执行的投资建议
4. 揭示主要风险因素

### 输出格式
请以结构化报告形式输出，包含：
- **背景**：分析目标和范围
- **关键指标**：核心数据和指标
- **分析**：数据解读和趋势判断
- **建议**：具体可执行的投资建议
- **风险提示**：⚠️ 需要关注的风险因素

请直接输出分析报告，不需要解释你将如何分析。"""

        try:
            result = await invoke(
                prompt=prompt,
                system_prompt=persona_prefix + "\n" + INVESTMENT_SYSTEM_PROMPT if persona_prefix else INVESTMENT_SYSTEM_PROMPT,
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
                    error=result.stderr or "Investment analysis failed",
                )
        except Exception as e:
            return AgentResult(success=False, error=str(e))