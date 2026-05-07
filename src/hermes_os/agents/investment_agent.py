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

# Lazy import to avoid hard dependency
_tavily_client: Any = None


def _get_tavily() -> Any:
    global _tavily_client
    if _tavily_client is None:
        try:
            from tavily import TavilyClient

            _tavily_client = TavilyClient("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")
        except Exception:
            pass
    return _tavily_client


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


def _call_blend_direct(
    prompt: str,
    system_prompt: str | None = None,
    max_tokens: int = 4096,
) -> tuple[bool, str]:
    """Call blend via OpenAI-compatible endpoint — no real API key needed."""
    from openai import OpenAI

    client = OpenAI(
        base_url="http://localhost:8000/v1",
        api_key="dummy",  # blend 不需要真实key
    )

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        resp = client.chat.completions.create(
            model="claude-sonnet-4-6",
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
        )
        text = resp.choices[0].message.content or ""
        return True, text
    except Exception as e:
        return False, str(e)


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

        # Build market data — use Tavily for live stock data
        tavily = _get_tavily()
        market_data = ""
        if tavily and any(kw in message for kw in ["涨", "跌", "股价", "行情", "走势", "投资", "分析", "A股"]):
            try:
                queries = [
                    "贵州茅台股价 今日 2026",
                    "宁德时代股价 今日 2026",
                    "A股大盘 上证指数 今日 2026",
                ]
                results = []
                for q in queries:
                    resp = tavily.search(q, search_depth="advanced")
                    for r in (resp.get("results") or [])[:2]:
                        title = r.get("title", "")[:60]
                        snippet = r.get("content", "")[:200]
                        results.append(f"**{title}**\n{snippet}\n")
                if results:
                    market_data = "\n\n## 📈 最新市场数据\n" + "\n".join(results)
            except Exception:
                pass

        prompt = f"""## 投资分析任务

### 用户需求
{message}
{market_data}

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

        system = persona_prefix + "\n" + INVESTMENT_SYSTEM_PROMPT if persona_prefix else INVESTMENT_SYSTEM_PROMPT

        # Try direct HTTP to blend (avoids claude CLI auth issue on MacBook)
        try:
            ok, output = _call_blend_direct(prompt, system)
            if ok:
                return AgentResult(success=True, output=output, token_usage=len(output) // 4)
        except Exception:
            pass

        # Fall back to invoke() — may work on production LEGION machine
        try:
            result = await invoke(
                prompt=prompt,
                system_prompt=system,
                cwd=context.get("workspace", "/tmp"),
                model=context.get("model", "blend"),
                allowed_tools=context.get("allowed_tools", "Bash,Read,Edit,Write,Glob,Grep,WebSearch"),
            )
            if result.ok:
                return AgentResult(
                    success=True,
                    output=result.stdout,
                    token_usage=len(result.stdout) // 4,
                )
            else:
                return AgentResult(success=False, error=result.stderr or "Investment analysis failed")
        except Exception as e:
            return AgentResult(success=False, error=str(e))
