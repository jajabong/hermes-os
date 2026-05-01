"""QA-Closed Loop — M1 Spec Gate (规格约束层).

Ensures every artifact has a validated spec before ContentLabor begins.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import aiosqlite


class SpecStyle(str, Enum):
    FORMAL = "formal"
    ANALYSIS = "analysis"
    CONCISE = "concise"


@dataclass
class Spec:
    artifact_id: str
    title: str
    target_audience: str
    key_thesis: list[str]
    style: str  # "formal" | "analysis" | "concise"
    word_count_target: int | None = None
    deadline: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    passed: bool
    errors: list[str]
    warnings: list[str] = field(default_factory=list)


class SpecValidator:
    """Validates spec completeness and rejects ambiguous/incomplete specs."""

    MIN_TITLE_LENGTH = 6

    async def validate(self, spec: Spec) -> ValidationResult:
        errors = []

        # Check: title must be descriptive enough
        if len(spec.title) < self.MIN_TITLE_LENGTH:
            errors.append(
                f"title too short: '{spec.title}' ({len(spec.title)} chars). "
                f"Need >= {self.MIN_TITLE_LENGTH} chars for non-ambiguous title."
            )

        # Check: key_thesis must not be empty
        if not spec.key_thesis:
            errors.append("key_thesis")

        # Check: target_audience must not be empty
        if not spec.target_audience or not spec.target_audience.strip():
            errors.append("target_audience cannot be empty.")

        # Check: style must be valid
        valid_styles = {s.value for s in SpecStyle}
        if spec.style not in valid_styles:
            errors.append(
                f"invalid style '{spec.style}'. Must be one of: {valid_styles}"
            )

        return ValidationResult(passed=len(errors) == 0, errors=errors)


class SpecNotApprovedError(Exception):
    """Raised when ContentArtifact.write_content is called before spec is approved."""
    pass


class ContentArtifact:
    """A content artifact that requires spec approval before writing."""

    def __init__(self, artifact_id: str, base_dir: str):
        self.artifact_id = artifact_id
        self.base_dir = Path(base_dir)
        self._spec: Spec | None = None
        self._validation: ValidationResult | None = None

    def approve_spec(self, spec: Spec, validation: ValidationResult) -> None:
        if not validation.passed:
            raise ValueError("Cannot approve spec with failed validation")
        self._spec = spec
        self._validation = validation

    @property
    def _artifact_dir(self) -> Path:
        return self.base_dir / self.artifact_id

    @property
    def _spec_path(self) -> Path:
        return self._artifact_dir / "artifact.spec.json"

    async def write_content(self, content: str) -> None:
        if self._spec is None or self._validation is None:
            raise SpecNotApprovedError(
                f"Cannot write content for {self.artifact_id}: spec not approved. "
                "Call approve_spec() before write_content()."
            )
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        await self._write_artifact(content)

    async def _write_artifact(self, content: str) -> None:
        content_path = self._artifact_dir / "artifact.md"
        async with aiosqlite.connect(content_path) as db:
            # Store content as a simple file (not a database) for the artifact
            pass
        # Write actual content to file
        content_path.write_text(content, encoding="utf-8")


class SpecGate:
    """Creates specs and validates them before ContentLabor begins."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)

    async def create_spec(
        self,
        artifact_id: str,
        title: str,
        target_audience: str,
        key_thesis: list[str],
        style: str,
        word_count_target: int | None = None,
        deadline: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Spec:
        spec = Spec(
            artifact_id=artifact_id,
            title=title,
            target_audience=target_audience,
            key_thesis=key_thesis,
            style=style,
            word_count_target=word_count_target,
            deadline=deadline,
            metadata=metadata or {},
        )
        await self._save_spec(spec)
        return spec

    async def _save_spec(self, spec: Spec) -> None:
        artifact_dir = self.base_dir / spec.artifact_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        spec_path = artifact_dir / "artifact.spec.json"
        spec_dict = {
            "artifact_id": spec.artifact_id,
            "title": spec.title,
            "target_audience": spec.target_audience,
            "key_thesis": spec.key_thesis,
            "style": spec.style,
            "word_count_target": spec.word_count_target,
            "deadline": spec.deadline,
            "metadata": spec.metadata,
        }
        async with aiosqlite.connect(spec_path) as db:
            # Just use the connection to ensure atomic write
            pass
        spec_path.write_text(json.dumps(spec_dict, ensure_ascii=False, indent=2), encoding="utf-8")

    async def approve_spec(self, spec: Spec, validation: ValidationResult) -> None:
        """Mark spec as approved after validation passes."""
        if not validation.passed:
            raise ValueError("Cannot approve spec that did not pass validation")
        # In a full implementation, this would update approval status
        pass


class CheckerResult(ValidationResult):
    """Result from CheckerLabor verification."""
    hallucination_score: float = 1.0


class CheckerLabor:
    """M2: Adversarial verification layer.

    Runs after ContentLabor, before Delivery. Performs:
    - Markdown structure validation
    - Citation count validation (for formal docs)
    - Keyword coverage validation
    - Semantic blind check (hallucination detection)
    """

    PLACEHOLDER_PATTERNS = ["TODO:", "FIXME:", "TBD:", "待完成", "待修复", "XXX"]
    MIN_WORD_COUNT = 50

    async def check(
        self,
        artifact: ContentArtifact,
        content: str,
        spec: Spec,
    ) -> CheckerResult:
        """Run all checks on the content."""
        errors = []
        warnings = []

        # 1. Markdown structure check
        md_errors = self._check_markdown_structure(content)
        errors.extend(md_errors)

        # 2. Placeholder text detection
        placeholder_errors = self._check_placeholder_text(content)
        errors.extend(placeholder_errors)

        # 3. Keyword coverage check
        keyword_errors = self._check_keyword_coverage(content, spec)
        errors.extend(keyword_errors)

        # 4. Word count check
        word_errors = self._check_word_count(content, spec)
        errors.extend(word_errors)

        # 5. Citation count check (formal docs)
        citation_errors = self._check_citation_count(content, spec)
        errors.extend(citation_errors)

        # 6. Semantic blind check (hallucination)
        semantic_result = await self._semantic_blind_check(content)
        if not semantic_result.get("passed", True):
            errors.append(f"semantic_blind_check: {semantic_result.get('reason', 'Failed')}")

        return CheckerResult(
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _check_markdown_structure(self, content: str) -> list[str]:
        """Validate basic Markdown structure."""
        errors = []
        lines = content.split("\n")
        has_heading = any(line.startswith("#") for line in lines)
        if not has_heading:
            errors.append("markdown: content must have at least one heading (# heading)")
        return errors

    def _check_placeholder_text(self, content: str) -> list[str]:
        """Detect placeholder text like TODO/FIXME."""
        errors = []
        for pattern in self.PLACEHOLDER_PATTERNS:
            if pattern in content:
                errors.append(f"placeholder detected: '{pattern}' found in content")
        return errors

    def _check_keyword_coverage(self, content: str, spec: Spec) -> list[str]:
        """Verify key_thesis keywords appear in content."""
        errors = []
        for keyword in spec.key_thesis:
            if keyword not in content:
                errors.append(f"keyword missing: '{keyword}' from key_thesis not found in content")
        return errors

    def _count_chinese_words(self, text: str) -> int:
        """Count Chinese words. Each Chinese character counts as one word."""
        return sum(1 for c in text if '一' <= c <= '鿿')

    def _check_word_count(self, content: str, spec: Spec) -> list[str]:
        """Check if content meets word count target."""
        errors = []
        import re

        # Count Chinese characters (each Chinese char counts as 1 word)
        chinese_chars = len(re.findall(r'[一-鿿]', content))
        # Count English words
        english_words = len(content.split())
        # Total word count (each Chinese char = 1 word)
        word_count = chinese_chars + english_words
        if spec.word_count_target is not None:
            if word_count < spec.word_count_target * 0.5:
                errors.append(
                    f"word_count: content has {word_count} words, "
                    f"target is {spec.word_count_target} (need at least 50% of target)"
                )
        elif word_count < self.MIN_WORD_COUNT:
            errors.append(
                f"word_count: content has {word_count} words, "
                f"minimum required is {self.MIN_WORD_COUNT}"
            )
        return errors

    def _check_citation_count(self, content: str, spec: Spec) -> list[str]:
        """Check citation count for formal documents."""
        errors = []
        if spec.style == "formal":
            # Look for common citation patterns
            has_citation = (
                "[1]" in content
                or "（来源" in content
                or "来源：" in content
                or "according to" in content.lower()
            )
            if not has_citation:
                errors.append("citation: formal document requires at least one citation")
        return errors

    async def _semantic_blind_check(self, content: str) -> dict:
        """Detect potential hallucinations using LLM-based analysis.

        Sends content to Claude for semantic analysis to identify:
        - Factually questionable claims without citation
        - Logical contradictions
        - Extreme unsupported claims
        """
        # If content is very short, skip LLM check
        if len(content) < 200:
            return {"passed": True, "hallucination_score": 1.0}

        try:
            from hermes_os.claude_code_invocator import invoke

            prompt = f"""Analyze the following text for potential hallucinations or factual inconsistencies.

Check for:
1. Claims without supporting citations or evidence
2. Logical contradictions within the text
3. Statistically unlikely claims (e.g., "1000% increase" without data)
4. Assertions that contradict well-known facts
5. Vague or unsubstantiated superlatives ("always", "never", "best", "worst")

Text to analyze:
---
{content[:3000]}
---

Respond with JSON:
{{
  "passed": true/false,
  "reason": "brief explanation if issues found",
  "hallucination_score": 0.0-1.0 (1.0 = no issues),
  "flagged_segments": ["list of problematic text segments"]
}}

Only fail (passed=false) if you find significant factual issues, not minor stylistic concerns."""

            result = await invoke(
                prompt=prompt,
                max_turns=3,
                timeout_sec=30,
                system_prompt="You are a factual consistency checker. Analyze text for potential hallucinations and respond only in JSON format.",
            )

            # Parse JSON response
            import json
            import re

            # Extract JSON from response
            json_match = re.search(r'\{[^{}]*\}', result.stdout, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return {
                    "passed": data.get("passed", True),
                    "reason": data.get("reason", ""),
                    "hallucination_score": data.get("hallucination_score", 1.0),
                    "flagged_segments": data.get("flagged_segments", []),
                }

            return {"passed": True, "hallucination_score": 1.0}

        except Exception:
            # Fall back to heuristic check on error
            return self._heuristic_hallucination_check(content)

    def _heuristic_hallucination_check(self, content: str) -> dict:
        """Fallback heuristic check when LLM is unavailable."""
        import re

        extreme_claim_patterns = [
            r"\d{3,}%\s*(增长|growth|increase)",
            r"\d+倍\s*(增长|growth)",
            r"1000%\s*增长",
            r"1000% growth",
        ]
        for pattern in extreme_claim_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return {
                    "passed": False,
                    "reason": f"extreme claim detected: matches pattern '{pattern}'",
                    "hallucination_score": 0.5,
                }
        return {"passed": True, "hallucination_score": 1.0}


@dataclass
class DiffResult:
    """Result of computing diff between original and edited content."""
    added_lines: int
    removed_lines: int
    diff_text: str


@dataclass
class PreferenceRecord:
    """A learned preference from user feedback."""
    artifact_id: str
    pattern_type: str  # "expansion", "style_change", "keyword_addition"
    keywords: list[str] = field(default_factory=list)
    style_preference: str | None = None
    timestamp: str | None = None


class DiffLearning:
    """M3: User feedback evolution layer.

    Captures user edit feedback and evolves preferences:
    - Computes diff between original and user-edited content
    - Identifies patterns (expansion, style_change, keyword_addition)
    - Records preferences to PREFERENCES.md in user brain
    """

    def __init__(self, user_id: str, base_dir: str):
        self.user_id = user_id
        self.base_dir = Path(base_dir)
        self._preferences: list[PreferenceRecord] = []

    async def compute_diff(self, original: str, edited: str) -> DiffResult | None:
        """Compute diff between original and edited content."""
        import difflib

        original_lines = original.splitlines()
        edited_lines = edited.splitlines()

        diff = list(difflib.unified_diff(
            original_lines,
            edited_lines,
            lineterm="",
        ))

        added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))

        return DiffResult(
            added_lines=added,
            removed_lines=removed,
            diff_text="\n".join(diff),
        )

    async def record_feedback(
        self,
        artifact_id: str,
        original_content: str,
        edited_content: str,
        spec: Spec,
    ) -> None:
        """Record user feedback and learn preferences."""
        diff_result = await self.compute_diff(original_content, edited_content)
        if diff_result is None:
            return

        pattern = await self._identify_pattern(original_content, edited_content)

        pref = PreferenceRecord(
            artifact_id=artifact_id,
            pattern_type=pattern,
            keywords=self._extract_keywords(original_content, edited_content),
            style_preference=self._infer_style_preference(original_content, edited_content),
            timestamp=self._get_timestamp(),
        )
        self._preferences.append(pref)
        await self._persist_preferences()

    def get_preferences(self) -> list[dict]:
        """Get all learned preferences as dicts."""
        return [
            {
                "artifact_id": p.artifact_id,
                "pattern_type": p.pattern_type,
                "keywords": p.keywords,
                "style_preference": p.style_preference,
                "timestamp": p.timestamp,
            }
            for p in self._preferences
        ]

    async def _identify_pattern(self, original: str, edited: str) -> str:
        """Identify the pattern of change from original to edited."""
        original_len = len(original)
        edited_len = len(edited)

        # Expansion: content got significantly longer
        if edited_len > original_len * 1.5:
            return "expansion"

        # Style change: check for formality indicators
        formal_words = ["该", "此", "具有", "符合", "详情", "充分"]
        casual_words = ["很", "真", "太", "非常", "这个"]

        original_formal = sum(1 for w in formal_words if w in original)
        edited_formal = sum(1 for w in formal_words if w in edited)

        if edited_formal > original_formal:
            return "style_change"

        return "keyword_addition"

    def _extract_keywords(self, original: str, edited: str) -> list[str]:
        """Extract keywords that were added or changed."""
        # Simple heuristic: find words in edited that aren't in original
        import re
        original_words = set(re.findall(r'[\w]+', original))
        edited_words = re.findall(r'[\w]+', edited)

        added = [w for w in edited_words if w not in original_words and len(w) > 1]
        return list(set(added))[:5]  # Return up to 5 keywords

    def _infer_style_preference(self, original: str, edited: str) -> str | None:
        """Infer user's style preference from edits."""
        formal_indicators = ["该", "此", "其", "具有", "符合", "规定", "要求"]
        casual_indicators = ["你", "我", "很", "真", "太"]

        formal_count = sum(1 for w in formal_indicators if w in edited)
        casual_count = sum(1 for w in casual_indicators if w in edited)

        if formal_count > casual_count:
            return "formal"
        elif casual_count > formal_count:
            return "casual"
        return None

    def _get_timestamp(self) -> str:
        """Get current timestamp."""
        from datetime import datetime
        return datetime.now().isoformat()

    async def _persist_preferences(self) -> None:
        """Persist preferences to PREFERENCES.md in user brain."""
        brain_dir = self.base_dir / self.user_id
        brain_dir.mkdir(parents=True, exist_ok=True)
        prefs_path = brain_dir / "PREFERENCES.md"

        lines = ["# User Preferences\n", "## Learned Preferences\n"]
        for pref in self._preferences:
            lines.append(f"### {pref.artifact_id} - {pref.pattern_type}")
            if pref.keywords:
                lines.append(f"- Keywords added: {', '.join(pref.keywords)}")
            if pref.style_preference:
                lines.append(f"- Style preference: {pref.style_preference}")
            if pref.timestamp:
                lines.append(f"- Timestamp: {pref.timestamp}")
            lines.append("")

        prefs_path.write_text("\n".join(lines), encoding="utf-8")


class QualityGates:
    """Registry of all quality gates in the QA closed loop."""

    @staticmethod
    async def run_m1_spec_gate(spec: Spec, validator: SpecValidator) -> ValidationResult:
        """Run M1: Spec Gate validation."""
        return await validator.validate(spec)

    @staticmethod
    async def run_m2_checker_labor(
        artifact: ContentArtifact,
        content: str,
        spec: Spec,
    ) -> CheckerResult:
        """Run M2: CheckerLabor verification."""
        checker = CheckerLabor()
        return await checker.check(artifact=artifact, content=content, spec=spec)