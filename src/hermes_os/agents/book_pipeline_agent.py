"""BookPipelineAgent — book writing pipeline orchestration agent for Hermes OS.

Responsibilities:
- Orchestrate the Book_Pipeline.yaml multi-stage pipeline
- Coordinate: research → outline → write_chapters → merge → review → epub/pdf
- Track progress and handle failures

This agent is the bridge between the agent dispatch layer and the PipelineEngine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hermes_os.pipeline_engine import PipelineDefinition, PipelineEngine
from hermes_os.vertical_agent import AgentRequest, AgentResult


BOOK_PIPELINE_YAML = "pipelines/Book_Pipeline.yaml"


class BookPipelineAgent:
    """Book pipeline orchestration vertical agent."""

    name = "BookPipelineAgent"

    async def invoke(self, request: AgentRequest, context: dict[str, Any]) -> AgentResult:
        """Execute book pipeline orchestration task."""
        message = request.params.get("message", "")
        user = context.get("user")
        user_id = getattr(user, "user_id", "unknown") if user else "unknown"

        workspace = Path(context.get("workspace", "/tmp"))
        pipeline_path = context.get("pipeline_path", BOOK_PIPELINE_YAML)

        try:
            # Load pipeline definition
            pipeline_def = PipelineDefinition.from_yaml(Path(pipeline_path))
            engine = PipelineEngine(artifact_base=workspace / "artifacts")

            # Execute the pipeline
            stage_results = await engine.execute_pipeline(
                task_id=f"book-{user_id}",
                definition=pipeline_def,
                context={
                    "user_id": user_id,
                    "topic": message,
                },
            )

            # Analyze results
            all_success = all(r.success for r in stage_results.values())
            failed_stages = [s for s, r in stage_results.items() if not r.success]
            completed_stages = [s for s, r in stage_results.items() if r.success]

            if all_success:
                stages_summary = "\n".join(
                    f"  ✅ {s}" for s in stage_results.keys()
                )
                output = f"""## 书籍 Pipeline 执行完成

### 主题
{message}

### 执行结果
✅ 全部 {len(stage_results)} 个阶段完成

### 阶段详情
{stages_summary}

---
Pipeline completed successfully."""

                return AgentResult(
                    success=True,
                    output=output,
                    token_usage=0,
                    metadata={
                        "stage_results": {s: r.success for s, r in stage_results.items()},
                        "artifacts": [r.output_artifact for r in stage_results.values() if r.output_artifact],
                    },
                )
            else:
                return AgentResult(
                    success=False,
                    error=f"Pipeline failed at stages: {', '.join(failed_stages)}",
                )
        except FileNotFoundError:
            return AgentResult(
                success=False,
                error=f"Pipeline file not found: {pipeline_path}",
            )
        except Exception as e:
            return AgentResult(success=False, error=str(e))