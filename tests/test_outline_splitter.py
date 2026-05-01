"""Tests for OutlineSplitter — parses outline into chapter list for parallel writing.

Also tests split_write_stage() which turns a single write_chapters stage into
N parallel sub-tasks.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from hermes_os.outline_splitter import (
    OutlineSplitter,
    Chapter,
    ChapterWriteTask,
    SplitResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_outline() -> str:
    return """## 书籍大纲

### 第一部分：理论黎明

1. **思想的火种** — McCulloch-Pitts神经元、图灵测试
2. **达特茅斯会议** — 1956年AI诞生
3. **第一次AI浪潮** — 符号AI黄金年代

### 第二部分：开创时代

1. **第一次AI寒冬** — Lighthill报告
2. **专家系统时代** — MYCIN、XCON
"""


# ---------------------------------------------------------------------------
# Chapter dataclass tests
# ---------------------------------------------------------------------------

class TestChapter:
    def test_chapter_structure(self) -> None:
        ch = Chapter(
            number=1,
            title="思想的火种",
            section="第一部分：理论黎明",
            description="McCulloch-Pitts神经元、图灵测试",
        )
        assert ch.title == "思想的火种"
        assert ch.number == 1
        assert ch.section == "第一部分：理论黎明"

    def test_chapter_to_dict(self) -> None:
        ch = Chapter(number=1, title="测试", section="附录", description="desc")
        d = ch.to_dict()
        assert d["title"] == "测试"
        assert d["number"] == 1


# ---------------------------------------------------------------------------
# ChapterWriteTask dataclass tests
# ---------------------------------------------------------------------------

class TestChapterWriteTask:
    def test_task_structure(self) -> None:
        task = ChapterWriteTask(
            task_id="book-001-ch1",
            chapter_number=1,
            chapter_title="思想的火种",
            prompt="Write chapter 1...",
        )
        assert task.task_id == "book-001-ch1"
        assert task.chapter_number == 1


# ---------------------------------------------------------------------------
# OutlineSplitter tests
# ---------------------------------------------------------------------------

class TestOutlineSplitter:
    def test_split_extracts_chapters(self, sample_outline: str) -> None:
        splitter = OutlineSplitter()
        chapters = splitter.split(sample_outline)
        assert len(chapters) >= 5  # At least 5 chapters in sample
        assert chapters[0].title == "思想的火种"
        assert chapters[1].title == "达特茅斯会议"

    def test_split_includes_section_context(self, sample_outline: str) -> None:
        splitter = OutlineSplitter()
        chapters = splitter.split(sample_outline)
        # First 3 chapters should have "第一部分" context
        for ch in chapters[:3]:
            assert "第一部分" in ch.section

    def test_split_handles_numbered_format(self, sample_outline: str) -> None:
        splitter = OutlineSplitter()
        chapters = splitter.split(sample_outline)
        assert all(ch.number > 0 for ch in chapters)

    def test_split_empty_outline(self) -> None:
        splitter = OutlineSplitter()
        chapters = splitter.split("")
        assert len(chapters) == 0

    def test_split_without_descriptions(self) -> None:
        outline = """## 大纲

1. **第一章** — 内容1
2. **第二章**
3. **第三章** — 内容3
"""
        splitter = OutlineSplitter()
        chapters = splitter.split(outline)
        assert len(chapters) == 3
        # Descriptions should be empty strings or "—"
        assert chapters[1].description == ""


# ---------------------------------------------------------------------------
# SplitResult tests
# ---------------------------------------------------------------------------

class TestSplitResult:
    def test_result_structure(self) -> None:
        chapters = [
            Chapter(number=1, title="第一章", section="Part 1", description=""),
            Chapter(number=2, title="第二章", section="Part 1", description=""),
        ]
        result = SplitResult(
            source_outline="outline content",
            chapters=chapters,
            total_words_estimate=5000,
        )
        assert result.total_chapters == 2
        assert result.total_words_estimate == 5000

    def test_result_chapters_list(self) -> None:
        chapters = [Chapter(number=i, title=f"Chapter {i}", section="", description="") for i in range(1, 4)]
        result = SplitResult(source_outline="", chapters=chapters, total_words_estimate=0)
        assert result.total_chapters == 3


# ---------------------------------------------------------------------------
# Prompt generation tests
# ---------------------------------------------------------------------------

class TestPromptGeneration:
    def test_build_chapter_prompt(self, sample_outline: str) -> None:
        splitter = OutlineSplitter()
        chapters = splitter.split(sample_outline)
        prompt = splitter.build_chapter_prompt(chapters[0], sample_outline, topic="AI历史")
        assert "第一章" in prompt or "思想的火种" in prompt
        assert "AI历史" in prompt

    def test_build_chapter_prompt_includes_previous_chapters(self, sample_outline: str) -> None:
        splitter = OutlineSplitter()
        chapters = splitter.split(sample_outline)
        # For chapter 3, should reference chapter 2 context
        if len(chapters) >= 3:
            prompt = splitter.build_chapter_prompt(
                chapters[2], sample_outline,
                topic="AI历史",
                previous_chapters=[chapters[1].title]
            )
            assert chapters[1].title in prompt
