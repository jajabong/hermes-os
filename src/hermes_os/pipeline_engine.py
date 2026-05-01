"""PipelineEngine — YAML-driven pipeline execution for Hermes OS.

Executes multi-stage pipelines:
  Research → Outline → Write → Render → Deliver

Each stage:
  - Has a labor_type (content, format, browser)
  - Reads input_artifact from artifact workspace
  - Writes output_artifact to artifact workspace
  - Updates pipeline meta.json with completion status
"""

from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class StageStatus(str, Enum):
    """Status of a pipeline stage."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PipelineStage:
    """A single stage in a pipeline."""
    name: str
    sequence: int
    labor_type: str
    description: str
    input_artifact: str | None = None
    output_artifact: str | None = None
    estimated_minutes: int = 30
    verification_gate: str | None = None
    parallel: bool = False
    parallel_max_concurrent: int = 5
    parallel_failure_threshold: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sequence": self.sequence,
            "labor_type": self.labor_type,
            "description": self.description,
            "input_artifact": self.input_artifact,
            "output_artifact": self.output_artifact,
            "estimated_minutes": self.estimated_minutes,
            "verification_gate": self.verification_gate,
            "parallel": self.parallel,
            "parallel_max_concurrent": self.parallel_max_concurrent,
            "parallel_failure_threshold": self.parallel_failure_threshold,
        }


@dataclass
class LaborResult:
    """Result from executing a labor task."""
    success: bool
    output_artifact: str | None = None
    output_content: str | None = None
    error: str | None = None
    duration_seconds: float = 0.0
    chapter_results: dict[int, dict[str, Any]] | None = None


@dataclass
class PipelineDefinition:
    """A complete pipeline definition loaded from YAML."""
    name: str
    description: str
    version: str
    stages: list[PipelineStage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path | str) -> PipelineDefinition:
        """Load pipeline definition from a YAML file."""
        data = yaml.safe_load(Path(path).read_text("utf-8"))
        stages = []
        for i, s in enumerate(data.get("stages", [])):
            stages.append(
                PipelineStage(
                    name=s["name"],
                    sequence=i,
                    labor_type=s.get("labor_type", "content"),
                    description=s.get("description", ""),
                    input_artifact=s.get("input_artifact"),
                    output_artifact=s.get("output_artifact"),
                    estimated_minutes=s.get("estimated_minutes", 30),
                    verification_gate=s.get("verification_gate"),
                    parallel=s.get("parallel", False),
                    parallel_max_concurrent=s.get("parallel_max_concurrent", 5),
                    parallel_failure_threshold=s.get("parallel_failure_threshold", 0.5),
                )
            )
        return cls(
            name=data.get("name", "Unnamed Pipeline"),
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            stages=stages,
            metadata=data.get("metadata", {}),
        )


@dataclass
class PipelineWorkspace:
    """Artifact workspace for a pipeline execution."""
    task_id: str
    pipeline_name: str
    root_path: Path
    completed_stages: list[str] = field(default_factory=list)
    failed_stages: list[str] = field(default_factory=list)
    current_stage: str | None = None
    stage_statuses: dict[str, str] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None

    @property
    def src_path(self) -> Path:
        return self.root_path / "src"

    @property
    def render_path(self) -> Path:
        return self.root_path / "render"

    @property
    def delivery_path(self) -> Path:
        return self.root_path / "delivery"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "pipeline_name": self.pipeline_name,
            "completed_stages": self.completed_stages,
            "failed_stages": self.failed_stages,
            "current_stage": self.current_stage,
            "stage_statuses": self.stage_statuses,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], root_path: Path) -> PipelineWorkspace:
        return cls(
            task_id=data["task_id"],
            pipeline_name=data["pipeline_name"],
            root_path=root_path,
            completed_stages=data.get("completed_stages", []),
            failed_stages=data.get("failed_stages", []),
            current_stage=data.get("current_stage"),
            stage_statuses=data.get("stage_statuses", {}),
            started_at=data.get("started_at", datetime.now(UTC).isoformat()),
            finished_at=data.get("finished_at"),
        )


class ContentLabor:
    """Labor for producing text content via Claude Code invocation."""

    async def execute(
        self,
        description: str,
        input_artifact: str | None,
        workspace: PipelineWorkspace,
        context: dict[str, Any],
    ) -> LaborResult:
        """Execute content production labor via Claude Code.

        Reads input_artifact from workspace if present,
        then generates content using Claude Code invoke().
        """
        import time
        start = time.monotonic()

        try:
            from hermes_os.claude_code_invocator import invoke

            # Build prompt with context from input artifact
            input_content = ""
            if input_artifact:
                input_path = workspace.src_path / input_artifact
                if input_path.exists():
                    input_content = input_path.read_text("utf-8")

            topic = context.get("topic", context.get("research", ""))

            # Compose generation prompt
            prompt_parts = [
                f"Task: {description}",
            ]
            if topic:
                prompt_parts.append(f"Topic: {topic}")
            if input_content:
                prompt_parts.append(f"\n## Reference Material\n\n{input_content}")
            prompt_parts.append(
                "\n## Requirements\n"
                "Write high-quality, well-structured content.\n"
                "Use markdown formatting with proper headings, lists, and emphasis.\n"
                "Do not include any placeholder text like 'This is placeholder content'."
            )
            prompt = "\n\n".join(prompt_parts)

            # Configurable via context: max_turns, timeout_sec
            max_turns = context.get("max_turns", 20)
            timeout_sec = context.get("timeout_sec", 300)  # 5 minutes default

            result = await invoke(
                prompt=prompt,
                max_turns=max_turns,
                timeout_sec=timeout_sec,
                system_prompt=(
                    "You are a professional content writer. "
                    "Generate high-quality, well-structured content based on the user's request. "
                    "Use markdown formatting. Do not include placeholder text."
                ),
            )

            duration = time.monotonic() - start
            return LaborResult(
                success=True,
                output_artifact=None,
                output_content=result.stdout,
                duration_seconds=duration,
            )

        except Exception as e:
            duration = time.monotonic() - start
            return LaborResult(
                success=False,
                error=str(e),
                duration_seconds=duration,
            )


class FormatLabor:
    """Labor for formatting content (Markdown → EPUB/PDF/HTML).

    Uses pandoc for conversion with configurable output formats.
    """

    SUPPORTED_FORMATS = {"epub", "pdf", "html", "docx"}

    async def execute(
        self,
        description: str,
        input_artifact: str | None,
        workspace: PipelineWorkspace,
        context: dict[str, Any],
    ) -> LaborResult:
        """Execute format labor (Markdown → EPUB/PDF/HTML).

        Context parameters:
        - output_artifact: output filename (e.g., "book.epub")
        - output_format: "epub", "pdf", "html", "docx" (default: from output_artifact ext)
        - epub_metadata: dict with title, author, lang for EPUB
        - pdf_options: dict with geometry, fontsize, etc.
        """
        import time
        import subprocess
        start = time.monotonic()

        try:
            if not input_artifact:
                return LaborResult(
                    success=False,
                    error="Format labor requires input_artifact",
                    duration_seconds=time.monotonic() - start,
                )

            input_path = workspace.src_path / input_artifact
            if not input_path.exists():
                return LaborResult(
                    success=False,
                    error=f"Input artifact not found: {input_artifact}",
                    duration_seconds=time.monotonic() - start,
                )

            output_artifact = context.get("output_artifact", "output.epub")
            output_path = workspace.render_path / output_artifact

            # Determine format from extension
            ext = output_artifact.rsplit(".", 1)[-1].lower() if "." in output_artifact else "epub"
            output_format = context.get("output_format", ext)

            if output_format not in self.SUPPORTED_FORMATS:
                return LaborResult(
                    success=False,
                    error=f"Unsupported format: {output_format}. Supported: {self.SUPPORTED_FORMATS}",
                    duration_seconds=time.monotonic() - start,
                )

            # Build pandoc command
            cmd = ["pandoc", str(input_path), "-o", str(output_path)]

            if output_format == "epub":
                # EPUB-specific options
                metadata = context.get("epub_metadata", {})
                if metadata:
                    for key, value in metadata.items():
                        if value:
                            cmd.extend([f"--metadata={key}={value}"])

            elif output_format == "pdf":
                # PDF via LaTeX
                pdf_opts = context.get("pdf_options", {})
                geometry = pdf_opts.get("geometry", "a4")
                fontsize = pdf_opts.get("fontsize", "11pt")
                cmd.extend([
                    f"--pdf-engine=xelatex",
                    f"-V", f"geometry={geometry}",
                    f"-V", f"fontsize={fontsize}",
                ])

            elif output_format == "html":
                # HTML output
                cmd.append("--standalone")
                cmd.append("--self-contained")
                cmd.append("--mathjax")

            elif output_format == "docx":
                # Word document
                reference_doc = context.get("reference_doc")
                if reference_doc:
                    cmd.extend(["--reference-doc", reference_doc])

            # Execute pandoc
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=context.get("timeout_sec", 60),
            )

            if result.returncode != 0:
                return LaborResult(
                    success=False,
                    error=f"pandoc failed: {result.stderr}",
                    duration_seconds=time.monotonic() - start,
                )

            if not output_path.exists():
                return LaborResult(
                    success=False,
                    error="pandoc succeeded but output file not created",
                    duration_seconds=time.monotonic() - start,
                )

            duration = time.monotonic() - start
            return LaborResult(
                success=True,
                output_artifact=output_artifact,
                duration_seconds=duration,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return LaborResult(
                success=False,
                error="pandoc timed out",
                duration_seconds=duration,
            )
        except FileNotFoundError:
            duration = time.monotonic() - start
            return LaborResult(
                success=False,
                error="pandoc not found. Install: brew install pandoc",
                duration_seconds=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start
            return LaborResult(
                success=False,
                error=str(e),
                duration_seconds=duration,
            )


@dataclass
class ChapterWriteResult:
    """Result of writing a single chapter."""
    chapter_number: int
    chapter_title: str
    success: bool
    output_artifact: str | None = None
    output_content: str | None = None
    error: str | None = None
    duration_seconds: float = 0.0


class ParallelChapterLabor:
    """Labor that writes multiple chapters in parallel using asyncio.gather.

    Used when a stage has `parallel: true` in its definition.
    Reads outline, splits into ChapterWriteTasks, executes in parallel,
    writes individual chapter files, and aggregates results.
    """

    def __init__(
        self,
        max_concurrent: int = 5,
        failure_threshold: float = 0.5,
    ) -> None:
        self._semaphore = asyncio.Semaphore(value=max_concurrent)
        self._max_concurrent = max_concurrent
        self._failure_threshold = failure_threshold

    async def execute(
        self,
        description: str,
        input_artifact: str | None,
        workspace: PipelineWorkspace,
        context: dict[str, Any],
    ) -> LaborResult:
        """Execute parallel chapter writing."""
        import time
        from hermes_os.outline_splitter import (
            OutlineSplitter,
            split_write_stage,
            ChapterWriteTask,
            sanitize_filename,
        )
        from hermes_os.claude_code_invocator import invoke

        start = time.monotonic()

        try:
            if not input_artifact:
                return LaborResult(
                    success=False,
                    error="ParallelChapterLabor requires input_artifact (outline path)",
                    duration_seconds=time.monotonic() - start,
                )

            outline_path = workspace.src_path / input_artifact
            if not outline_path.exists():
                return LaborResult(
                    success=False,
                    error=f"Outline not found: {outline_path}",
                    duration_seconds=time.monotonic() - start,
                )

            outline_content = outline_path.read_text("utf-8")
            topic = context.get("topic", "Untitled Book")

            splitter = OutlineSplitter()
            chapters = splitter.split(outline_content)

            if not chapters:
                return LaborResult(
                    success=False,
                    error="No chapters found in outline",
                    duration_seconds=time.monotonic() - start,
                )

            tasks = split_write_stage(
                outline_splitter=splitter,
                outline_content=outline_content,
                topic=topic,
                pipeline_id=workspace.task_id,
                workspace=workspace.src_path,
                concurrency=self._max_concurrent,
            )

            chapter_results: dict[int, ChapterWriteResult] = {}

            async def write_one_chapter(task: ChapterWriteTask) -> ChapterWriteResult:
                async with self._semaphore:
                    chapter_start = time.monotonic()
                    try:
                        system_prompt = (
                            "You are a professional book author. "
                            "Write a complete, engaging book chapter. "
                            "Use markdown formatting. Do not include placeholder text. "
                            "Generate substantial content."
                        )

                        result = await invoke(
                            prompt=task.prompt,
                            max_turns=context.get("max_turns", 15),
                            timeout_sec=context.get("chapter_timeout_sec", 180),
                            system_prompt=system_prompt,
                        )

                        filename = f"ch{task.chapter_number:02d}_{sanitize_filename(task.chapter_title)}.md"
                        output_path = workspace.src_path / filename
                        output_path.write_text(result.stdout, "utf-8")

                        return ChapterWriteResult(
                            chapter_number=task.chapter_number,
                            chapter_title=task.chapter_title,
                            success=True,
                            output_artifact=filename,
                            output_content=result.stdout,
                            duration_seconds=time.monotonic() - chapter_start,
                        )
                    except Exception as e:
                        return ChapterWriteResult(
                            chapter_number=task.chapter_number,
                            chapter_title=task.chapter_title,
                            success=False,
                            error=str(e),
                            duration_seconds=time.monotonic() - chapter_start,
                        )

            results = await asyncio.gather(
                *[write_one_chapter(task) for task in tasks],
                return_exceptions=True,
            )

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    task = tasks[i]
                    chapter_results[task.chapter_number] = ChapterWriteResult(
                        chapter_number=task.chapter_number,
                        chapter_title=task.chapter_title,
                        success=False,
                        error=str(result),
                    )
                else:
                    chapter_results[result.chapter_number] = result

            total = len(chapter_results)
            failed = sum(1 for r in chapter_results.values() if not r.success)
            failure_ratio = failed / total if total > 0 else 0.0
            overall_success = failure_ratio <= self._failure_threshold

            duration = time.monotonic() - start
            return LaborResult(
                success=overall_success,
                output_artifact=None,
                output_content=None,
                error=None if overall_success else (
                    f"{failed}/{total} chapters failed (failure_ratio={failure_ratio:.2f}, "
                    f"threshold={self._failure_threshold})"
                ),
                duration_seconds=duration,
                chapter_results={
                    k: {
                        "chapter_number": v.chapter_number,
                        "chapter_title": v.chapter_title,
                        "success": v.success,
                        "output_artifact": v.output_artifact,
                        "error": v.error,
                        "duration_seconds": v.duration_seconds,
                    }
                    for k, v in chapter_results.items()
                },
            )

        except Exception as e:
            return LaborResult(
                success=False,
                error=f"ParallelChapterLabor exception: {str(e)}",
                duration_seconds=time.monotonic() - start,
            )


class MergeLabor:
    """Labor for merging chapter files into a single manuscript."""

    async def execute(
        self,
        description: str,
        input_artifact: str | None,
        workspace: PipelineWorkspace,
        context: dict[str, Any],
    ) -> LaborResult:
        """Execute chapter merge labor.

        Reads all ch*.md files from workspace.src_path, merges in order,
        prepends book header, and writes manuscript.md.
        """
        import time
        start = time.monotonic()

        try:
            from hermes_os.outline_splitter import sanitize_filename

            topic = context.get("topic", "Untitled Book")
            outline = context.get("outline", "")

            # Find all chapter files
            chapter_files = sorted(workspace.src_path.glob("ch*_*.md"))
            if not chapter_files:
                return LaborResult(
                    success=False,
                    error=f"No chapter files found in {workspace.src_path}",
                    duration_seconds=time.monotonic() - start,
                )

            sections = []
            for ch_file in chapter_files:
                content = ch_file.read_text("utf-8")
                # Remove the first heading (chapter title) since we add it back
                lines = content.split("\n")
                if lines and lines[0].startswith("# "):
                    lines = lines[1:]
                content = "\n".join(lines).strip()

                # Extract chapter number from filename: ch01_xxx.md
                basename = ch_file.stem  # e.g. ch01_思想的火种
                num_str = basename.split("_")[0].replace("ch", "").lstrip("0")
                chapter_num = int(num_str) if num_str.isdigit() else 0

                sections.append(f"\n\n{'='*60}\n")
                sections.append(f"# 第{chapter_num}章\n\n")
                sections.append(content)

            manuscript = "\n".join(sections)

            # Prepend book header
            header = f"""# {topic}

*Generated by Hermes OS Book Pipeline*\n
---
## 大纲\n\n{outline}\n
---
"""
            manuscript = header + manuscript

            output_artifact = context.get("merge_output", "02_manuscript.md")
            output_path = workspace.src_path / output_artifact
            output_path.write_text(manuscript, "utf-8")

            duration = time.monotonic() - start
            return LaborResult(
                success=True,
                output_artifact=output_artifact,
                output_content=manuscript,
                duration_seconds=duration,
            )

        except Exception as e:
            duration = time.monotonic() - start
            return LaborResult(
                success=False,
                error=str(e),
                duration_seconds=duration,
            )


class ReviewLabor:
    """Labor for reviewing manuscript via Claude Code."""

    async def execute(
        self,
        description: str,
        input_artifact: str | None,
        workspace: PipelineWorkspace,
        context: dict[str, Any],
    ) -> LaborResult:
        """Execute manuscript review via Claude Code invoke()."""
        import time
        start = time.monotonic()

        try:
            from hermes_os.claude_code_invocator import invoke

            if not input_artifact:
                return LaborResult(
                    success=False,
                    error="Review labor requires input_artifact",
                    duration_seconds=time.monotonic() - start,
                )

            input_path = workspace.src_path / input_artifact
            if not input_path.exists():
                return LaborResult(
                    success=False,
                    error=f"Input artifact not found: {input_artifact}",
                    duration_seconds=time.monotonic() - start,
                )

            content = input_path.read_text("utf-8")
            topic = context.get("topic", "")
            # Truncate for review (send last 4000 chars which is most critical)
            review_content = content[-4000:]

            result = await invoke(
                prompt=f"""Review this book manuscript excerpt for quality and consistency.

## Book Topic
{topic}

## Manuscript Excerpt (last section)
{review_content}

## Review Criteria
1. **Coherence**: Does the content flow logically?
2. **Completeness**: Are key points covered adequately?
3. **Style**: Is the writing professional and engaging?
4. **Consistency**: Is terminology consistent?

Provide a brief assessment (2-3 sentences) and rate overall quality: Excellent / Good / Needs Work.
Return your assessment as a short paragraph.""",
                max_turns=5,
                timeout_sec=120,
                system_prompt="You are a professional book editor. Provide constructive, concise feedback.",
            )

            duration = time.monotonic() - start
            return LaborResult(
                success=True,
                output_content=result.stdout.strip(),
                duration_seconds=duration,
            )

        except Exception as e:
            duration = time.monotonic() - start
            return LaborResult(
                success=False,
                error=str(e),
                duration_seconds=duration,
            )


class EpubRenderLabor:
    """Labor for rendering Markdown manuscript as EPUB using pandoc."""

    async def execute(
        self,
        description: str,
        input_artifact: str | None,
        workspace: PipelineWorkspace,
        context: dict[str, Any],
    ) -> LaborResult:
        """Execute EPUB rendering via pandoc."""
        import time
        import subprocess
        start = time.monotonic()

        try:
            if not input_artifact:
                return LaborResult(
                    success=False,
                    error="EpubRender labor requires input_artifact",
                    duration_seconds=time.monotonic() - start,
                )

            input_path = workspace.src_path / input_artifact
            if not input_path.exists():
                return LaborResult(
                    success=False,
                    error=f"Input artifact not found: {input_artifact}",
                    duration_seconds=time.monotonic() - start,
                )

            topic = context.get("topic", "Book")
            output_artifact = context.get("epub_output", "book.epub")
            epub_path = workspace.render_path / output_artifact
            epub_path.parent.mkdir(parents=True, exist_ok=True)

            # Create minimal EPUB metadata
            metadata_yaml = workspace.render_path / "metadata.yaml"
            metadata_yaml.write_text(
                f"title: {topic}\nauthor: Hermes OS\nlang: zh-CN\n",
                "utf-8",
            )

            # Use pandoc to convert Markdown → EPUB
            result = subprocess.run(
                [
                    "pandoc",
                    str(input_path),
                    "-o", str(epub_path),
                    "--epub-metadata", str(metadata_yaml),
                    "--toc",
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return LaborResult(
                    success=False,
                    error=f"pandoc failed: {result.stderr}",
                    duration_seconds=time.monotonic() - start,
                )

            epub_size = epub_path.stat().st_size if epub_path.exists() else 0
            duration = time.monotonic() - start
            return LaborResult(
                success=True,
                output_artifact=output_artifact,
                duration_seconds=duration,
            )

        except Exception as e:
            duration = time.monotonic() - start
            return LaborResult(
                success=False,
                error=str(e),
                duration_seconds=duration,
            )


class PdfRenderLabor:
    """Labor for rendering Markdown manuscript as PDF using pandoc."""

    async def execute(
        self,
        description: str,
        input_artifact: str | None,
        workspace: PipelineWorkspace,
        context: dict[str, Any],
    ) -> LaborResult:
        """Execute PDF rendering via pandoc."""
        import time
        import subprocess
        start = time.monotonic()

        try:
            if not input_artifact:
                return LaborResult(
                    success=False,
                    error="PdfRender labor requires input_artifact",
                    duration_seconds=time.monotonic() - start,
                )

            input_path = workspace.src_path / input_artifact
            if not input_path.exists():
                return LaborResult(
                    success=False,
                    error=f"Input artifact not found: {input_artifact}",
                    duration_seconds=time.monotonic() - start,
                )

            output_artifact = context.get("pdf_output", "book.pdf")
            pdf_path = workspace.render_path / output_artifact
            pdf_path.parent.mkdir(parents=True, exist_ok=True)

            # Two-step: pandoc markdown → HTML, then weasyprint HTML → PDF
            html_path = workspace.render_path / "book_intermediate.html"
            result = subprocess.run(
                ["pandoc", str(input_path), "-o", str(html_path), "--standalone"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return LaborResult(
                    success=False,
                    error=f"pandoc markdown→html failed: {result.stderr}",
                    duration_seconds=time.monotonic() - start,
                )

            result = subprocess.run(
                ["weasyprint", str(html_path), str(pdf_path)],
                capture_output=True,
                text=True,
            )
            html_path.unlink(missing_ok=True)  # Clean up intermediate

            if result.returncode != 0:
                return LaborResult(
                    success=False,
                    error=f"weasyprint failed: {result.stderr}",
                    duration_seconds=time.monotonic() - start,
                )

            duration = time.monotonic() - start
            return LaborResult(
                success=True,
                output_artifact=output_artifact,
                duration_seconds=duration,
            )

        except Exception as e:
            duration = time.monotonic() - start
            return LaborResult(
                success=False,
                error=str(e),
                duration_seconds=duration,
            )


class BrowserLabor:
    """Labor for browser automation using Playwright.

    Supports:
    - Session persistence (cookies, localStorage)
    - Form filling and submission
    - Screenshot capture
    - Navigation and extraction
    """

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None

    async def execute(
        self,
        description: str,
        input_artifact: str | None,
        workspace: PipelineWorkspace,
        context: dict[str, Any],
    ) -> LaborResult:
        """Execute browser automation labor.

        Context parameters:
        - action: "navigate" | "fill" | "submit" | "screenshot" | "extract"
        - url: Target URL for navigation
        - selector: CSS selector for elements
        - form_data: Dict of form field values
        - session_persist: Whether to persist session cookies
        """
        import time
        start = time.monotonic()

        try:
            pw = await self._get_playwright()
            if pw is None:
                return LaborResult(
                    success=False,
                    error="BrowserLabor requires Playwright. Install with: pip install playwright && playwright install",
                    duration_seconds=time.monotonic() - start,
                )

            action = context.get("action", "navigate")
            url = context.get("url", "")

            # Ensure we have a browser context
            if self._browser is None:
                self._browser = await pw.chromium.launch(headless=True)
            if self._context is None:
                self._context = await self._browser.new_context(
                    persist_sessions=context.get("session_persist", True)
                )

            page = await self._context.new_page()

            if action == "navigate":
                await page.goto(url, wait_until="networkidle")
                content = await page.content()
                await page.close()
                return LaborResult(
                    success=True,
                    output_content=content,
                    duration_seconds=time.monotonic() - start,
                )

            elif action == "screenshot":
                path = workspace.render_path / context.get("filename", "screenshot.png")
                await page.goto(url, wait_until="networkidle")
                await page.screenshot(path=str(path), full_page=True)
                await page.close()
                return LaborResult(
                    success=True,
                    output_artifact=str(path),
                    duration_seconds=time.monotonic() - start,
                )

            elif action == "fill":
                selector = context.get("selector", "")
                form_data = context.get("form_data", {})
                await page.goto(url, wait_until="networkidle")
                for field_sel, value in form_data.items():
                    await page.fill(field_sel, str(value))
                await page.close()
                return LaborResult(
                    success=True,
                    output_content=f"Filled {len(form_data)} fields",
                    duration_seconds=time.monotonic() - start,
                )

            elif action == "submit":
                selector = context.get("selector", "form")
                await page.goto(url, wait_until="networkidle")
                # Fill form if provided
                form_data = context.get("form_data", {})
                for field_sel, value in form_data.items():
                    await page.fill(field_sel, str(value))
                # Submit
                await page.click(selector)
                await page.wait_for_load_state("networkidle")
                content = await page.content()
                await page.close()
                return LaborResult(
                    success=True,
                    output_content=content,
                    duration_seconds=time.monotonic() - start,
                )

            elif action == "extract":
                selector = context.get("selector", "body")
                await page.goto(url, wait_until="networkidle")
                elements = await page.query_selector_all(selector)
                extracted = []
                for el in elements:
                    text = await el.inner_text()
                    extracted.append(text)
                await page.close()
                return LaborResult(
                    success=True,
                    output_content="\n".join(extracted),
                    duration_seconds=time.monotonic() - start,
                )

            else:
                await page.close()
                return LaborResult(
                    success=False,
                    error=f"Unknown action: {action}",
                    duration_seconds=time.monotonic() - start,
                )

        except Exception as e:
            return LaborResult(
                success=False,
                error=f"BrowserLabor error: {str(e)}",
                duration_seconds=time.monotonic() - start,
            )

    async def _get_playwright(self):
        """Lazy-load Playwright to avoid hard dependency."""
        if self._playwright is None:
            try:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()
            except ImportError:
                return None
        return self._playwright

    async def close(self) -> None:
        """Close browser and Playwright."""
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None


class PipelineEngine:
    """
    Executes YAML-defined pipelines using LaborInterfaces.

    Usage:
        engine = PipelineEngine(
            artifact_base=Path("/artifacts"),
            notification_manager=nm,
        )
        ws = await engine.create_pipeline_workspace("book-001", "book_pipeline")
        definition = PipelineDefinition.from_yaml(Path("Book_Pipeline.yaml"))
        for stage in definition.stages:
            result = await engine.execute_stage("book-001", stage, context)

    Hooks:
        engine.register_hook("pre_execute", async def(task_id, stage_name, context): ...)
        engine.register_hook("post_execute", async def(task_id, stage_name, context, result): ...)
    """

    def __init__(
        self,
        artifact_base: Path | str,
        notification_manager: Any = None,
        max_gate_retries: int = 3,
        checker_labor: Any = None,
    ) -> None:
        self._artifact_base = Path(artifact_base)
        self._notification_manager = notification_manager
        self._max_gate_retries = max_gate_retries
        self._checker_labor = checker_labor
        self._labor_registry: dict[str, Any] = {
            "content": ContentLabor(),
            "format": FormatLabor(),
            "browser": BrowserLabor(),
            "merge": MergeLabor(),
            "review": ReviewLabor(),
            "epub": EpubRenderLabor(),
            "pdf": PdfRenderLabor(),
        }
        # Gate implementations: verification_gate name -> callable
        self._gate_registry: dict[str, Any] = {}
        # pre/post execute hooks for cross-cutting concerns (P5 Governance)
        self._hooks: dict[str, list[Any]] = {
            "pre_execute": [],
            "post_execute": [],
        }
        # Auto-register built-in gates
        self._register_builtin_gates()

    def _register_builtin_gates(self) -> None:
        """Register built-in verification gate implementations."""
        # checker_labor gate is registered lazily on first use
        # to avoid circular imports
        pass

    async def _run_checker_labor_gate(
        self,
        task_id: str,
        stage_name: str,
        context: dict[str, Any],
    ) -> bool:
        """Built-in gate that runs CheckerLabor verification."""
        if self._checker_labor is None:
            # Lazy import to avoid circular dependency
            from hermes_os.qa_closed_loop import CheckerLabor
            self._checker_labor = CheckerLabor()

        stage = context.get("_current_stage")
        if not stage:
            return True

        # Get the content artifact from workspace
        ws = await self.load_pipeline_workspace(task_id)
        if not ws:
            return False

        content = ""
        if stage.output_artifact:
            content_path = ws.src_path / stage.output_artifact
            if content_path.exists():
                content = content_path.read_text("utf-8")

        if not content:
            return False

        # Create a minimal spec from context
        from hermes_os.qa_closed_loop import Spec, ContentArtifact
        spec = Spec(
            artifact_id=task_id,
            title=context.get("title", "Untitled"),
            target_audience=context.get("target_audience", ""),
            key_thesis=context.get("key_thesis", []),
            style=context.get("style", "formal"),
        )
        artifact = ContentArtifact(task_id, str(ws.root_path))

        result = await self._checker_labor.check(artifact, content, spec)
        return result.passed

    # ---------------------------------------------------------------------------
    # Workspace management
    # ---------------------------------------------------------------------------

    async def create_pipeline_workspace(
        self,
        task_id: str,
        pipeline_name: str,
    ) -> PipelineWorkspace:
        """Create a new pipeline workspace."""
        root = self._artifact_base / task_id
        root.mkdir(parents=True, exist_ok=True)
        (root / "src").mkdir(exist_ok=True)
        (root / "render").mkdir(exist_ok=True)
        (root / "delivery").mkdir(exist_ok=True)

        ws = PipelineWorkspace(
            task_id=task_id,
            pipeline_name=pipeline_name,
            root_path=root,
        )
        self._write_meta(ws)

        return ws

    async def load_pipeline_workspace(
        self,
        task_id: str,
    ) -> PipelineWorkspace | None:
        """Load an existing pipeline workspace."""
        root = self._artifact_base / task_id
        meta_path = root / "pipeline_meta.json"
        if not meta_path.exists():
            return None

        data = json.loads(meta_path.read_text("utf-8"))
        return PipelineWorkspace.from_dict(data, root)

    def _write_meta(self, ws: PipelineWorkspace) -> None:
        """Write pipeline meta.json."""
        (ws.root_path / "pipeline_meta.json").write_text(
            json.dumps(ws.to_dict(), ensure_ascii=False, indent=2), "utf-8"
        )

    # ---------------------------------------------------------------------------
    # Stage execution
    # ---------------------------------------------------------------------------

    async def execute_stage(
        self,
        task_id: str,
        stage: PipelineStage,
        context: dict[str, Any],
    ) -> LaborResult:
        """Execute a single pipeline stage."""
        ws = await self.load_pipeline_workspace(task_id)
        if ws is None:
            raise ValueError(f"Pipeline workspace {task_id} not found")

        # Mark stage as running
        ws.current_stage = stage.name
        ws.stage_statuses[stage.name] = StageStatus.RUNNING.value
        self._write_meta(ws)

        # Get labor — parallel content stages use ParallelChapterLabor
        labor = None
        if stage.parallel and stage.labor_type == "content":
            # Parallel content labor (e.g., write_chapters)
            labor = ParallelChapterLabor(
                max_concurrent=stage.parallel_max_concurrent,
                failure_threshold=stage.parallel_failure_threshold,
            )
        else:
            labor = self._labor_registry.get(stage.labor_type)

        if labor is None:
            result = LaborResult(
                success=False,
                error=f"Unknown labor type: {stage.labor_type}",
            )
            ws.stage_statuses[stage.name] = StageStatus.FAILED.value
            self._write_meta(ws)
            return result

        # Fire pre-execute hooks (P5 Governance)
        await self._call_hooks("pre_execute", task_id, stage.name, context)

        # Execute labor
        result = await labor.execute(
            description=stage.description,
            input_artifact=stage.input_artifact,
            workspace=ws,
            context=context,
        )

        # Fire post-execute hooks (P5 Governance)
        await self._call_hooks("post_execute", task_id, stage.name, context, result)

        # Update stage status
        if result.success:
            ws.stage_statuses[stage.name] = StageStatus.COMPLETED.value
            if stage.name not in ws.completed_stages:
                ws.completed_stages.append(stage.name)

            # Write output artifact if provided
            if result.output_artifact and result.output_content:
                output_path = ws.src_path / result.output_artifact
                output_path.write_text(result.output_content, "utf-8")
            elif stage.output_artifact and result.output_content:
                output_path = ws.src_path / stage.output_artifact
                output_path.write_text(result.output_content, "utf-8")

            # Run verification gate if defined
            if stage.verification_gate:
                context["_current_stage"] = stage
                gate_passed = await self.execute_verification_gate(
                    task_id, stage.name, context
                )
                if not gate_passed:
                    # Mark stage as failed due to gate failure
                    ws.stage_statuses[stage.name] = StageStatus.FAILED.value
                    if stage.name in ws.completed_stages:
                        ws.completed_stages.remove(stage.name)
                    result = LaborResult(
                        success=False,
                        output_artifact=result.output_artifact,
                        output_content=result.output_content,
                        error=f"verification_gate '{stage.verification_gate}' failed after {self._max_gate_retries} retries",
                    )
                    self._write_meta(ws)
                    return result
        else:
            ws.stage_statuses[stage.name] = StageStatus.FAILED.value
            # Mark failed so pipeline skips this stage on resume
            if stage.name not in ws.failed_stages:
                ws.failed_stages.append(stage.name)

        ws.current_stage = None
        self._write_meta(ws)

        return result

    async def execute_verification_gate(
        self,
        task_id: str,
        stage_name: str,
        context: dict[str, Any],
    ) -> bool:
        """Execute verification gate for a stage.

        Returns True if gate passes, False otherwise.
        """
        stage = context.get("_current_stage")
        if not stage or not stage.verification_gate:
            return True

        gate_name = stage.verification_gate
        gate_impl = self._gate_registry.get(gate_name)

        if gate_impl is None:
            # Check if it's a built-in gate
            if gate_name == "checker_labor":
                gate_impl = self._run_checker_labor_gate
            else:
                # No gate registered, skip
                return True

        for attempt in range(1, self._max_gate_retries + 1):
            try:
                passed = await gate_impl(task_id, stage_name, context)
                if passed:
                    return True
            except Exception:
                pass

            if attempt < self._max_gate_retries:
                await asyncio.sleep(0.5 * attempt)  # Exponential backoff

        return False

    async def register_gate(self, name: str, gate_fn: Any) -> None:
        """Register a verification gate implementation."""
        self._gate_registry[name] = gate_fn

    def register_hook(self, hook_type: str, hook_fn: Any) -> None:
        """Register a pre/post execute hook.

        hook_type: "pre_execute" or "post_execute"
        pre_execute: async def(task_id, stage_name, context)
        post_execute: async def(task_id, stage_name, context, result: LaborResult)
        """
        if hook_type in self._hooks:
            self._hooks[hook_type].append(hook_fn)

    async def _call_hooks(
        self,
        hook_type: str,
        task_id: str,
        stage_name: str,
        context: dict[str, Any],
        result: Any = None,
    ) -> None:
        """Fire all hooks of the given type."""
        for hook in self._hooks.get(hook_type, []):
            try:
                if hook_type == "pre_execute":
                    await hook(task_id, stage_name, context)
                elif hook_type == "post_execute":
                    await hook(task_id, stage_name, context, result)
            except Exception:
                pass

    # ---------------------------------------------------------------------------
    # Pipeline execution
    # ---------------------------------------------------------------------------

    async def execute_pipeline(
        self,
        task_id: str,
        definition: PipelineDefinition,
        context: dict[str, Any],
    ) -> dict[str, LaborResult]:
        """Execute a full pipeline from definition."""
        ws = await self.create_pipeline_workspace(task_id, definition.name)
        results = {}

        for stage in definition.stages:
            result = await self.execute_stage(task_id, stage, context)
            results[stage.name] = result
            if not result.success:
                break  # Stop on failure

        return results
