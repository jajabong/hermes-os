"""EducationAgent — professional education and tutoring agent for Hermes OS.

Responsibilities:
- Course design and learning path planning
- Homework help and concept explanation
- Academic planning and college preparation
- Training program development

Uses invoke() (claude -p) as the execution primitive, wrapped in domain-specific persona.
"""

from __future__ import annotations

from typing import Any

from hermes_os.claude_code_invocator import invoke
from hermes_os.vertical_agent import AgentRequest, AgentResult


EDUCATION_SYSTEM_PROMPT = """你是 Hermes OS 的教育辅导专家。

擅长领域：
- 课程设计和学习路径规划
- 作业辅导和概念讲解
- 升学规划和教育资源分析
- 培训方案设计和教材开发
- 因材施教和学习风格适配

教学原则：
1. 循循善诱：引导思考，不直接给答案
2. 激发兴趣：让学习变得有趣味
3. 扎实基础：确保核心概念理解透彻
4. 循序渐进：从已知到未知，步步推进

输出风格：
- 启发式提问（用问句引导思考）
- 概念解释用比喻和实例
- 步骤清晰（1、2、3...）
- 重点内容用 **加粗**
- 鼓励性语言（👍 你分析得很到位）

当用户询问学习、教育、升学问题时，给出专业、温暖的教育支持。"""


class EducationAgent:
    """Education vertical agent."""

    name = "EducationAgent"

    async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
        """Execute education tutoring task."""
        message = request.params.get("message", "")
        persona_block = context.get("persona_block")

        persona_prefix = persona_block.render() if persona_block else ""

        prompt = f"""## 教育辅导任务

### 用户需求
{message}

### 分析要求
1. 明确用户的教育阶段和目标
2. 分析需要掌握的核心知识点
3. 设计学习路径和练习计划
4. 提供具体的学习资源推荐

### 输出格式
请以教育方案形式输出，包含：
- **目标分析**：学习目标和当前水平
- **知识点梳理**：核心概念和技能
- **学习计划**：阶段性学习路径
- **练习建议**：配套练习和检测方法
- **资源推荐**：优质学习材料

请直接输出教育方案，不需要解释分析过程。"""

        try:
            result = await invoke(
                prompt=prompt,
                system_prompt=persona_prefix + "\n" + EDUCATION_SYSTEM_PROMPT if persona_prefix else EDUCATION_SYSTEM_PROMPT,
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
                    error=result.stderr or "Education tutoring failed",
                )
        except Exception as e:
            return AgentResult(success=False, error=str(e))