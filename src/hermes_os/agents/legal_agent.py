"""LegalAgent — professional legal advisory agent for Hermes OS.

Responsibilities:
- Contract review and risk identification
- Legal consultation and compliance check
- Agreement drafting and clause analysis
- Legal research and regulation lookup

Uses invoke() (claude -p) as the execution primitive, wrapped in domain-specific persona.
"""

from __future__ import annotations

from typing import Any

from hermes_os.claude_code_invocator import invoke
from hermes_os.vertical_agent import AgentRequest, AgentResult


LEGAL_SYSTEM_PROMPT = """你是 Hermes OS 的法律顾问专家。

擅长领域：
- 合同审查、条款分析和风险识别
- 法律法规咨询和法律风险评估
- 合规检查和监管要求对照
- 协议起草、修改和谈判支持
- 法律文书撰写和要点提取

工作原则：
1. 严谨专业：法律意见准确、有据可查
2. 风险揭示：明确指出合同/协议中的风险点
3. 实用建议：给出可操作的修改建议和替代方案
4. 保护权益：在合法范围内最大程度保护当事人利益

输出风格：
- 结构化法律意见（问题→分析→建议）
- 条款级别标注（第X条）
- 风险等级：🔴高危 / 🟡中风险 / 🟢低风险
- 修改建议用引用格式标注原文

当用户提交合同或法律问题时，给出专业、严谨的法律分析。"""


class LegalAgent:
    """Legal advisory vertical agent."""

    name = "LegalAgent"

    async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
        """Execute legal advisory task."""
        message = request.params.get("message", "")

        prompt = f"""## 法律咨询任务

### 用户问题/提交的合同
{message}

### 分析要求
1. 识别合同类型和适用法律场景
2. 列出需要关注的关键条款
3. 揭示潜在法律风险
4. 提出具体修改建议

### 输出格式
请以法律意见书形式输出，包含：
- **合同概述**：类型、主体、标的
- **关键条款分析**：重要条款逐一分析
- **风险提示**：🔴高危 / 🟡中风险 / 🟢低风险
- **修改建议**：具体可操作的条款修改方案
- **参考依据**：相关法律法规

请直接输出法律意见，不需要解释分析过程。"""

        try:
            result = await invoke(
                prompt=prompt,
                system_prompt=LEGAL_SYSTEM_PROMPT,
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
                    error=result.stderr or "Legal analysis failed",
                )
        except Exception as e:
            return AgentResult(success=False, error=str(e))