"""OutlineSplitter — parses outline into parallel chapter writing tasks.

From a generated outline (01_outline.md), extract chapter structure and
build individual prompts for parallel chapter generation.

Also provides split_write_stage() which converts a single write_chapters
stage into N parallel ChapterWriteTask subtasks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Chapter:
    """A single chapter extracted from an outline."""

    number: int
    title: str
    section: str = ""
    description: str = ""
    word_count_estimate: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "section": self.section,
            "description": self.description,
            "word_count_estimate": self.word_count_estimate,
        }


@dataclass
class ChapterWriteTask:
    """A single chapter writing task for TaskScheduler."""

    task_id: str
    chapter_number: int
    chapter_title: str
    prompt: str
    depends_on: list[str] = field(default_factory=list)


@dataclass
class SplitResult:
    """Result of splitting an outline into chapters."""

    source_outline: str
    chapters: list[Chapter]
    total_words_estimate: int
    total_chapters: int = 0

    def __post_init__(self) -> None:
        self.total_chapters = len(self.chapters)


class OutlineSplitter:
    """
    Parse an outline and produce parallel chapter writing tasks.

    Usage:
        splitter = OutlineSplitter()
        result = splitter.split(outline_content)
        for chapter in result.chapters:
            task = splitter.build_chapter_task(
                pipeline_id="book-001",
                chapter=chapter,
                outline_content=outline_content,
                topic="AI历史",
            )
            # Submit task to TaskScheduler for parallel execution
    """

    # Patterns for extracting numbered chapter lines
    CHAPTER_LINE_PATTERNS = [
        # 1. **Title** — description (3 groups: number, title, description)
        re.compile(r"^\s*(\d+)\.\s+\*\*(.+?)\*\*\s*[—\-–]\s*(.+)$", re.MULTILINE),
        # **Title** — description (2 groups: title, description — no number)
        re.compile(r"^\s*\*\*(.+?)\*\*\s*[—\-–]\s*(.+)$", re.MULTILINE),
        # 1. **Title** (1 group: title only, no description)
        re.compile(r"^\s*(\d+)\.\s+\*\*(.+?)\*\*\s*$", re.MULTILINE),
        # **Title** (1 group: title only, no description, no number)
        re.compile(r"^\s*\*\*(.+?)\*\*\s*$", re.MULTILINE),
        # - **Title** — description
        re.compile(r"^\s*-\s+\*\*(.+?)\*\*\s*[—\-–]\s*(.+)$", re.MULTILINE),
        # - **Title** (no description)
        re.compile(r"^\s*-\s+\*\*(.+?)\*\*\s*$", re.MULTILINE),
    ]

    SECTION_PATTERNS = [
        # #### Part name
        re.compile(r"^#{1,4}\s*(.+)$", re.MULTILINE),
        # | Part | Name | ...
        re.compile(r"^\|\s*\*\*(.+?)\*\*", re.MULTILINE),
    ]

    def split(self, outline: str) -> list[Chapter]:
        """Parse outline text into list of Chapter objects."""
        chapters: list[Chapter] = []
        current_section = ""
        chapter_counter = 0

        lines = outline.split("\n")
        for line in lines:
            # Track current section heading
            section_match = re.match(r"^(#{1,4})\s+(.+)$", line)
            if section_match:
                heading = section_match.group(2).strip()
                # Skip chapter-level headings, keep part/section headings
                if "第" in heading and (
                    "部分" in heading or "Part" in heading or "附录" in heading
                ):
                    current_section = heading
                continue

            # Try to match chapter lines
            chapter = self._extract_chapter_line(line, current_section)
            if chapter:
                chapter_counter += 1
                chapter.number = chapter_counter
                chapters.append(chapter)

        return chapters

    def _extract_chapter_line(self, line: str, current_section: str) -> Chapter | None:
        """Try to extract a chapter from a line using multiple patterns."""
        for pattern in self.CHAPTER_LINE_PATTERNS:
            match = re.match(pattern, line.strip())
            if match:
                groups = match.groups()
                n = len(groups)

                if n == 3:
                    # 1. **Title** — description
                    number_str, title, description = groups
                    return Chapter(
                        number=int(number_str) if number_str.isdigit() else 0,
                        title=title.strip(),
                        section=current_section,
                        description=description.strip(),
                    )
                elif n == 2:
                    if groups[0].isdigit():
                        # 1. **Title** (no description) → groups = (number, title)
                        return Chapter(
                            number=int(groups[0]),
                            title=groups[1].strip(),
                            section=current_section,
                            description="",
                        )
                    else:
                        # **Title** — description → groups = (title, description)
                        return Chapter(
                            number=0,
                            title=groups[0].strip(),
                            section=current_section,
                            description=groups[1].strip(),
                        )
                elif n == 1:
                    # **Title** (1 group: title only)
                    return Chapter(
                        number=0,
                        title=groups[0].strip(),
                        section=current_section,
                        description="",
                    )
        return None

    def build_chapter_prompt(
        self,
        chapter: Chapter,
        outline: str,
        topic: str,
        previous_chapters: list[str] | None = None,
        style_guide: str = "",
    ) -> str:
        """Build a writing prompt for a single chapter."""
        prev_context = ""
        if previous_chapters:
            prev_titles = " → ".join(previous_chapters)
            prev_context = f"\n\n## Narrative Continuity\n\nPrevious chapters: {prev_titles}\nEnsure this chapter flows naturally from the previous ones."

        word_target = chapter.word_count_estimate or 3000
        style_section = f"\n\n## Style Guide\n\n{style_guide}" if style_guide else ""

        return f"""Write a book chapter on **{chapter.title}**.

## Book Context
**Topic**: {topic}
**Book Outline**:
{outline}
**Current Chapter**: {chapter.title}
**Section**: {chapter.section}

## This Chapter Description
{chapter.description}

## Task
Write a complete, well-structured book chapter with:
- An engaging opening that connects to the book's theme
- Multiple sections covering key aspects of this topic
- Concrete examples, historical facts, or case studies
- A summary section that ties back to the overall narrative
- Target length: {word_target} words (approximately {word_target // 250} minutes of reading)

## Chapter Numbering
This is Chapter {chapter.number}.

{prev_context}{style_section}

## Formatting
- Use markdown headings (## for main sections, ### for subsections)
- Include **bold** for key terms
- Use bullet points sparingly for lists of examples
- Do NOT include placeholder text like "This chapter will cover..."
- Write in a narrative style suitable for a book about {topic}
"""

    def build_chapter_task(
        self,
        pipeline_id: str,
        chapter: Chapter,
        outline: str,
        topic: str,
        dependencies: list[str] | None = None,
    ) -> ChapterWriteTask:
        """Build a ChapterWriteTask for TaskScheduler submission."""
        task_id = f"{pipeline_id}-ch{chapter.number}"

        prompt = self.build_chapter_prompt(
            chapter=chapter,
            outline=outline,
            topic=topic,
        )

        return ChapterWriteTask(
            task_id=task_id,
            chapter_number=chapter.number,
            chapter_title=chapter.title,
            prompt=prompt,
            depends_on=dependencies or [],
        )

    def estimate_total_words(self, chapters: list[Chapter]) -> int:
        """Estimate total word count across all chapters."""
        return sum(ch.word_count_estimate or 3000 for ch in chapters)

    def split_result(self, outline: str) -> SplitResult:
        """Convenience: split and return structured SplitResult."""
        chapters = self.split(outline)
        return SplitResult(
            source_outline=outline,
            chapters=chapters,
            total_words_estimate=self.estimate_total_words(chapters),
        )


def build_merge_manifest(chapters: list[Chapter], workspace: Path) -> str:
    """Build a merge manifest string for combining chapters into a manuscript."""
    manifest_lines = ["# Merge Manifest\n"]
    for ch in chapters:
        chapter_file = f"ch{ch.number:02d}_{sanitize_filename(ch.title)}.md"
        manifest_lines.append(f"## Chapter {ch.number}: {ch.title}")
        manifest_lines.append(f"File: {chapter_file}")
        manifest_lines.append(f"Section: {ch.section}")
        manifest_lines.append(f"Description: {ch.description}")
        manifest_lines.append("")
    return "\n".join(manifest_lines)


def split_write_stage(
    outline_splitter: OutlineSplitter,
    outline_content: str,
    topic: str,
    pipeline_id: str,
    workspace: Path,
    concurrency: int = 5,
) -> list[ChapterWriteTask]:
    """Split write_chapters into N parallel ChapterWriteTask for TaskScheduler.

    Usage:
        tasks = split_write_stage(splitter, outline, topic, "book-001", ws/src)
        # Submit all tasks to TaskScheduler for parallel execution
    """
    chapters = outline_splitter.split(outline_content)
    return [
        outline_splitter.build_chapter_task(
            pipeline_id=pipeline_id,
            chapter=ch,
            outline=outline_content,
            topic=topic,
        )
        for ch in chapters
    ]


def sanitize_filename(title: str) -> str:
    """Convert a chapter title to a safe filename."""
    s = title.strip()
    s = re.sub(r"[^\w\s一-鿿\-]", "", s)  # keep Chinese chars
    s = re.sub(r"[\s]+", "_", s)
    return s[:50]
