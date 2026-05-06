"""DeployAgent — professional deployment and DevOps strategy agent for Hermes OS.

Responsibilities:
- Deployment strategy and architecture planning
- CI/CD pipeline design and optimization
- Docker/Kubernetes configuration review
- Cloud deployment and environment management

Note: DeployAgent is a professional strategy advisor, NOT a tool executor.
It provides deployment expertise and generates configs/scripts, but actual
execution is handled by CodeAgent or dedicated DevOps tools.
"""

from __future__ import annotations

from typing import Any

from hermes_os.claude_code_invocator import invoke
from hermes_os.vertical_agent import AgentRequest, AgentResult


DEPLOY_SYSTEM_PROMPT = """你是 Hermes OS 的部署运维专家。

擅长领域：
- Docker 容器化和镜像优化
- Kubernetes 部署和服务编排
- CI/CD 流水线设计和优化
- 云平台部署（AWS/GCP/Azure）
- 环境配置和运维自动化

部署原则：
1. 零停机：优先考虑蓝绿部署、滚动更新
2. 幂等性：部署操作可重复执行不影响结果
3. 可回滚：每次变更都能快速回退
4. 监控先行：部署前已规划监控和告警

输出风格：
- 步骤化部署计划（阶段一、阶段二...）
- 关键配置用代码块
- 风险点用 ⚠️ 标注
- 验证步骤用 ✅ 标注

当用户询问部署、运维相关问题时，给出专业、可靠的部署方案。"""


class DeployAgent:
    """Deployment strategy vertical agent."""

    name = "DeployAgent"

    async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
        """Execute deployment strategy task."""
        message = request.params.get("message", "")

        prompt = f"""## 部署方案任务

### 用户需求
{message}

### 分析要求
1. 明确部署目标环境和技术栈
2. 设计部署架构和流程
3. 生成关键配置文件
4. 规划回滚策略

### 输出格式
请以部署方案形式输出，包含：
- **环境概述**：目标环境和技术栈
- **架构设计**：部署拓扑和服务关系
- **部署步骤**：分阶段操作流程
- **配置文件**：关键配置的完整代码
- **验证方案**：部署后的验证步骤 ✅
- **回滚计划**：出问题时的回退方案

请直接输出部署方案，不需要解释分析过程。"""

        try:
            result = await invoke(
                prompt=prompt,
                system_prompt=DEPLOY_SYSTEM_PROMPT,
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
                    error=result.stderr or "Deployment planning failed",
                )
        except Exception as e:
            return AgentResult(success=False, error=str(e))