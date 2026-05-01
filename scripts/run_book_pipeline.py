"""Book Pipeline End-to-End Demo.

Run the full Book Authoring Pipeline:
  research → outline → write_chapters → review → render_epub → render_pdf

Usage:
  uv run python scripts/run_book_pipeline.py

No Feishu required — uses console output + file artifacts.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# Add src to path for direct import
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hermes_os.pipeline_engine import PipelineEngine, PipelineDefinition, PipelineWorkspace
from hermes_os.notification_manager import NotificationManager, NotificationEvent


class ConsoleNotifier:
    """Console-only notification notifier (replaces Feishu for demo)."""

    async def send_notification(
        self,
        user_id: str,
        task_title: str,
        task_id: str,
        event: NotificationEvent,
        result: str = "",
        error: str = "",
        goal_context: str | None = None,
        **kwargs,
    ) -> None:
        icon_map = {
            NotificationEvent.STARTED: "🔄",
            NotificationEvent.RUNNING: "🔄",
            NotificationEvent.COMPLETED: "✅",
            NotificationEvent.FAILED: "❌",
            NotificationEvent.WARNING: "⚠️",
        }
        icon = icon_map.get(event, "📋")
        print(f"\n{icon} {task_title}")
        if result:
            for line in result.split("\n")[:8]:
                print(f"   {line}")
        if error:
            print(f"   ❗ Error: {error[:200]}")


async def run_pipeline(
    pipeline_name: str,
    pipeline_task_id: str,
    topic: str,
    artifact_base: Path,
) -> PipelineWorkspace:
    """Run the full pipeline and return the final workspace."""
    print(f"\n{'='*60}")
    print(f"📚 Starting: {pipeline_name}")
    print(f"🎯 Topic: {topic}")
    print(f"🆔 Pipeline ID: {pipeline_task_id}")
    print(f"{'='*60}\n")

    # Load pipeline definition
    import yaml
    search_dirs = [Path("pipelines"), Path.home() / ".hermes" / "pipelines"]
    pipeline_path = None
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for yaml_file in search_dir.glob("*.yaml"):
            data = yaml.safe_load(yaml_file.read_text("utf-8"))
            if data.get("name") == pipeline_name:
                pipeline_path = yaml_file
                break
        if pipeline_path:
            break

    if not pipeline_path:
        raise FileNotFoundError(f"Pipeline '{pipeline_name}' not found")

    definition = PipelineDefinition.from_yaml(pipeline_path)
    print(f"📋 Loaded: {definition.name} (v{definition.version})")
    print(f"📊 Stages: {len(definition.stages)}")
    for i, stage in enumerate(definition.stages):
        print(f"   {i+1}. {stage.name} ({stage.labor_type}) → {stage.output_artifact}")

    engine = PipelineEngine(artifact_base=artifact_base)

    # Create workspace once
    ws = await engine.create_pipeline_workspace(pipeline_task_id, definition.name)
    print(f"\n{'─'*60}")

    # Execute each stage
    start_total = time.monotonic()
    for i, stage in enumerate(definition.stages):
        stage_start = time.monotonic()

        print(f"\n📍 Stage {i+1}/{len(definition.stages)}: {stage.name}")
        print(f"   Labor: {stage.labor_type} | Input: {stage.input_artifact or 'none'} → Output: {stage.output_artifact}")

        context = {"topic": topic, "pipeline_task_id": pipeline_task_id}
        result = await engine.execute_stage(pipeline_task_id, stage, context)

        stage_duration = time.monotonic() - stage_start

        if result.success:
            print(f"   ✅ Done in {stage_duration:.1f}s")
            if result.output_artifact and result.output_content:
                output_path = ws.src_path / (result.output_artifact or stage.output_artifact or "output.md")
                size = len(output_path.read_bytes()) if output_path.exists() else 0
                print(f"   📄 {result.output_artifact} ({size} bytes)")

            # Reload workspace to get updated completed_stages
            ws = await engine.load_pipeline_workspace(pipeline_task_id)
            print(f"   📍 Progress: {len(ws.completed_stages)}/{len(definition.stages)} stages")
        else:
            print(f"   ❌ Failed in {stage_duration:.1f}s: {result.error}")

    total_duration = time.monotonic() - start_total

    # Final summary
    print(f"\n{'='*60}")
    print(f"🏁 Pipeline Complete!")
    print(f"   Total time: {total_duration:.1f}s ({total_duration/60:.1f} min)")
    print(f"   Stages completed: {len(ws.completed_stages)}/{len(definition.stages)}")
    print(f"   Workspace: {ws.root_path}")
    print(f"{'='*60}")

    # Final artifact listing
    print(f"\n📦 Final Artifacts:")
    for p in ws.root_path.rglob("*"):
        if p.is_file() and not p.name.startswith('.') and not p.name.endswith('.json'):
            size = len(p.read_bytes())
            print(f"   {p.relative_to(ws.root_path)} ({size} bytes)")

    return ws


async def main():
    """Run the Book Pipeline demo."""
    artifact_base = Path("/tmp/hermes_demo/artifacts")
    artifact_base.mkdir(parents=True, exist_ok=True)

    topic = "人工智能发展史：从图灵到GPT时代"

    ws = await run_pipeline(
        pipeline_name="Book Authoring Pipeline",
        pipeline_task_id=f"book-demo-{int(time.time())}",
        topic=topic,
        artifact_base=artifact_base,
    )

    # Save summary to file
    summary_path = artifact_base / ws.task_id / "pipeline_summary.json"
    summary = {
        "pipeline_task_id": ws.task_id,
        "completed_stages": ws.completed_stages,
        "workspace": str(ws.root_path),
        "topic": topic,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n📝 Summary saved to: {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
