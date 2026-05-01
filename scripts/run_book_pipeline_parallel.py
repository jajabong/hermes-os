"""Book Pipeline with Parallel Chapter Writing.

Reads the already-generated outline, splits it into chapters,
then writes each chapter in parallel via Claude Code invoke().
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hermes_os.outline_splitter import OutlineSplitter, build_merge_manifest, sanitize_filename
from hermes_os.pipeline_engine import PipelineEngine, PipelineDefinition
from hermes_os.notification_manager import NotificationManager, NotificationEvent


class ConsoleNotifier:
    async def send_notification(self, user_id: str, task_title: str, task_id: str, event: NotificationEvent, result: str = "", error: str = "", **kwargs):
        icon_map = {NotificationEvent.STARTED: "🔄", NotificationEvent.RUNNING: "🔄", NotificationEvent.COMPLETED: "✅", NotificationEvent.FAILED: "❌", NotificationEvent.WARNING: "⚠️"}
        icon = icon_map.get(event, "📋")
        print(f"\n{icon} {task_title}")


async def write_chapter_parallel(
    pipeline_id: str,
    chapters: list,
    outline: str,
    topic: str,
    workspace: Path,
    concurrency: int = 5,
) -> dict[int, dict]:
    """Write multiple chapters in parallel using invoke()."""
    from hermes_os.claude_code_invocator import invoke

    semaphore = asyncio.Semaphore(concurrency)
    results: dict[int, dict] = {}

    async def write_one(chapter_num: int, chapter_title: str, prompt: str) -> dict:
        async with semaphore:
            start = time.monotonic()
            try:
                result = await invoke(
                    prompt=prompt,
                    max_turns=15,
                    timeout_sec=180,  # 3 minutes per chapter
                    system_prompt=(
                        "You are a professional book author. "
                        "Write a complete, engaging book chapter in Chinese. "
                        "Use markdown formatting. Do not include placeholder text. "
                        "Generate substantial content (1500+ words)."
                    ),
                )
                duration = time.monotonic() - start
                filename = f"ch{chapter_num:02d}_{sanitize_filename(chapter_title)}.md"
                output_path = workspace / filename
                output_path.write_text(result.stdout, "utf-8")
                return {"success": True, "filename": filename, "duration": duration, "size": len(result.stdout)}
            except Exception as e:
                duration = time.monotonic() - start
                return {"success": False, "error": str(e), "duration": duration}

    # Build tasks
    tasks = []
    for ch in chapters:
        prompt = f"""Write a complete book chapter titled "**{ch['title']}**" for a book about {topic}.

## Chapter Description
{ch['description']}

## Book Outline (for context)
{outline}

## Requirements
- Write in Chinese, approximately 2000-3000 words
- Use markdown formatting with headings and paragraphs
- Include historical facts, examples, and analysis
- Write as a professional non-fiction book chapter
- Do NOT include placeholder text like "This chapter will cover..."
- Begin directly with the chapter content

This is Chapter {ch['number']} of the book."""
        tasks.append((ch['number'], ch['title'], prompt))

    # Run in parallel
    print(f"\n🔄 Writing {len(tasks)} chapters in parallel (concurrency={concurrency})...")
    task_objects = [asyncio.create_task(write_one(num, title, prompt)) for num, title, prompt in tasks]
    results_list = await asyncio.gather(*task_objects, return_exceptions=True)

    for ch, result in zip(chapters, results_list):
        results[ch["number"]] = result
        if isinstance(result, Exception):
            print(f"   ❌ Chapter {ch['number']} failed: {result}")
        elif result.get("success"):
            print(f"   ✅ Chapter {ch['number']} ({result['duration']:.0f}s, {result['size']} bytes)")
        else:
            print(f"   ❌ Chapter {ch['number']} failed: {result.get('error', 'unknown')[:80]}")

    return results


async def main():
    """Run the parallel chapter writing pipeline."""
    artifact_base = Path("/tmp/hermes_demo/artifacts")
    pipeline_id = "book-demo-1777602864"

    # Load existing workspace
    ws_path = artifact_base / pipeline_id
    outline_path = ws_path / "src" / "01_outline.md"
    if not outline_path.exists():
        print(f"❌ Outline not found: {outline_path}")
        print("Run scripts/run_book_pipeline.py first to generate the outline.")
        return

    outline = outline_path.read_text("utf-8")
    topic = "人工智能发展史：从图灵到GPT时代"

    # Parse outline into chapters
    splitter = OutlineSplitter()
    chapters = splitter.split(outline)
    print(f"📋 Parsed {len(chapters)} chapters from outline")

    # Write all 15 chapters in parallel
    demo_chapters = [ch.to_dict() for ch in chapters]
    print(f"🎯 Writing all {len(demo_chapters)} chapters in parallel:")
    for ch in demo_chapters:
        print(f"   {ch['number']}. {ch['title']}")

    start = time.monotonic()
    results = await write_chapter_parallel(
        pipeline_id=pipeline_id,
        chapters=demo_chapters,
        outline=outline,
        topic=topic,
        workspace=ws_path / "src",
        concurrency=3,
    )
    total_time = time.monotonic() - start

    # Summary
    success_count = sum(1 for r in results.values() if isinstance(r, dict) and r.get("success"))
    print(f"\n{'='*60}")
    print(f"🏁 Parallel Write Complete!")
    print(f"   Chapters: {success_count}/{len(demo_chapters)} succeeded")
    print(f"   Total time: {total_time:.0f}s ({total_time/60:.1f} min)")
    print(f"{'='*60}")

    # List output files
    src_dir = ws_path / "src"
    print(f"\n📦 Generated Chapters:")
    for p in sorted(src_dir.glob("ch*_*.md")):
        size = len(p.read_bytes())
        print(f"   {p.name} ({size} bytes)")

    # Generate merge manifest
    manifest = build_merge_manifest([chapters[0]] * len(demo_chapters), src_dir)
    manifest_path = src_dir / "merge_manifest.md"
    manifest_path.write_text(manifest, "utf-8")
    print(f"\n📝 Merge manifest: {manifest_path}")


if __name__ == "__main__":
    asyncio.run(main())
