"""CodeLabor — Engineering Pipeline code generation labor.

Implements the Engineering Pipeline stages:
- M1_SPEC: Generate modification specification
- M2_CODING: Write code via Claude Code
- M3_SELFTEST: Execute test cases
- M4_LINTING: Validate code style
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from hermes_os.claude_code_invocator import invoke
from hermes_os.labor_registry import LaborResult

logger = logging.getLogger(__name__)


class CodeLabor:
    """Labor unit for code generation and validation."""

    def __init__(self) -> None:
        pass

    async def execute(self, workspace: Path, task_description: str, meta: dict[str, Any]) -> LaborResult:
        """
        Execute code generation task.

        Stage-specific behavior:
        - M1_SPEC: Generate modification specification
        - M2_CODING: Write code based on spec
        - M3_SELFTEST: Run test cases
        - M4_LINTING: Validate code style
        """
        stage = meta.get("stage", "M2_CODING")
        src_dir = workspace / "src"
        src_dir.mkdir(parents=True, exist_ok=True)

        if stage == "M1_SPEC":
            return await self._execute_m1_spec(workspace, task_description, meta)
        elif stage == "M2_CODING":
            return await self._execute_m2_coding(workspace, task_description, meta)
        elif stage == "M3_SELFTEST":
            return await self._execute_m3_selftest(workspace, task_description, meta)
        elif stage == "M4_LINTING":
            return await self._execute_m4_linting(workspace, task_description, meta)
        else:
            # Default: generic code generation
            return await self._execute_generic(workspace, task_description, meta)

    async def _execute_m1_spec(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> LaborResult:
        """M1_SPEC: Generate modification specification from task description."""
        spec_path = meta.get("spec_path", workspace / "src" / "spec.md")
        spec_content = (
            Path(spec_path).read_text(encoding="utf-8") if Path(spec_path).exists() else ""
        )

        prompt = f"""
## Task: Generate Modification Specification

### Task Description:
{task_description}

### Existing Specification (if any):
{spec_content}

### Output Format:
Generate a modification specification in Markdown with:
1. Summary of changes
2. Files to modify
3. Functions/classes to add/modify
4. Dependencies (if any)
5. Test strategy

Output ONLY the specification, no additional explanation.
"""
        logger.info("CodeLabor M1_SPEC generating modification spec")

        try:
            result = await invoke(
                prompt=prompt,
                cwd=str(workspace),
                model=meta.get("model", "sonnet"),
                system_prompt="You are a software architect. Generate precise modification specifications.",
            )

            if result.ok:
                output_file = workspace / "src" / "modification_spec.md"
                output_file.write_text(result.stdout, encoding="utf-8")
                return LaborResult(
                    success=True,
                    output=f"M1_SPEC completed for task: {task_description[:50]}",
                    token_usage=0,
                )
            else:
                logger.error("M1_SPEC failed: %s", result.stderr)
                return LaborResult(
                    success=False,
                    output="",
                    token_usage=0,
                    error=f"M1_SPEC failed: {result.stderr}",
                )
        except Exception as e:
            logger.exception("M1_SPEC exception")
            return LaborResult(
                success=False,
                output="",
                token_usage=0,
                error=str(e),
            )

    async def _execute_m2_coding(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> LaborResult:
        """M2_CODING: Write code based on modification spec."""
        spec_file = workspace / "src" / "modification_spec.md"
        spec_content = (
            spec_file.read_text(encoding="utf-8") if spec_file.exists() else task_description
        )

        # Determine output file from spec or use default
        output_file = workspace / "src" / "generated.py"

        prompt = f"""
## Task: Generate Code

### Modification Specification:
{spec_content}

### Task Description:
{task_description}

### Instructions:
1. Read the modification specification carefully
2. Generate the complete code implementation
3. Output ONLY the raw code (no markdown fences, no explanation)
4. Ensure code compiles without syntax errors
5. Follow best practices for the language
"""
        logger.info("CodeLabor M2_CODING generating code")

        try:
            result = await invoke(
                prompt=prompt,
                cwd=str(workspace),
                model=meta.get("model", "sonnet"),
                system_prompt="You are a code generator. Output raw code only, no markdown.",
            )

            if result.ok:
                output_file.write_text(result.stdout, encoding="utf-8")
                return LaborResult(
                    success=True,
                    output=f"M2_CODING generated code: {output_file}",
                    token_usage=0,
                )
            else:
                logger.error("M2_CODING failed: %s", result.stderr)
                return LaborResult(
                    success=False,
                    output="",
                    token_usage=0,
                    error=f"M2_CODING failed: {result.stderr}",
                )
        except Exception as e:
            logger.exception("M2_CODING exception")
            return LaborResult(
                success=False,
                output="",
                token_usage=0,
                error=str(e),
            )

    async def _execute_m3_selftest(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> LaborResult:
        """M3_SELFTEST: Execute test cases."""
        test_command = meta.get("test_command", "python -m pytest -v")

        logger.info("CodeLabor M3_SELFTEST running: %s", test_command)

        try:
            proc = await asyncio.create_subprocess_exec(
                *test_command.split(),
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode("utf-8", errors="replace")

            # Check for test success
            passed = proc.returncode == 0

            # Write test output
            output_file = workspace / "src" / "test_output.txt"
            output_file.write_text(output, encoding="utf-8")

            if passed:
                return LaborResult(
                    success=True,
                    output=f"M3_SELFTEST passed: {test_command}",
                    token_usage=0,
                )
            else:
                return LaborResult(
                    success=False,
                    output=f"M3_SELFTEST failed: {test_command}",
                    token_usage=0,
                    error=f"Test command returned {proc.returncode}",
                )
        except Exception as e:
            logger.exception("M3_SELFTEST exception")
            return LaborResult(
                success=False,
                output="",
                token_usage=0,
                error=str(e),
            )

    async def _execute_m4_linting(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> LaborResult:
        """M4_LINTING: Validate code style and conventions."""
        lint_command = meta.get("lint_command", "python -m ruff check src/")

        logger.info("CodeLabor M4_LINTING running: %s", lint_command)

        try:
            proc = await asyncio.create_subprocess_exec(
                *lint_command.split(),
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode("utf-8", errors="replace")

            # Linting passes if no errors (returncode 0) or only warnings
            # For ruff, returncode 0 means no errors
            passed = proc.returncode == 0

            # Write lint output
            output_file = workspace / "src" / "lint_output.txt"
            output_file.write_text(output, encoding="utf-8")

            if passed:
                return LaborResult(
                    success=True,
                    output=f"M4_LINTING passed: {lint_command}",
                    token_usage=0,
                )
            else:
                return LaborResult(
                    success=False,
                    output=f"M4_LINTING failed: {lint_command}",
                    token_usage=0,
                    error=f"Lint command returned {proc.returncode}",
                )
        except Exception as e:
            logger.exception("M4_LINTING exception")
            return LaborResult(
                success=False,
                output="",
                token_usage=0,
                error=str(e),
            )

    async def _execute_generic(
        self, workspace: Path, task_description: str, meta: dict[str, Any]
    ) -> LaborResult:
        """Generic code generation fallback."""
        prompt = f"""
## Task: {task_description}

Generate code to accomplish the task. Output ONLY raw code, no markdown.
"""
        logger.info("CodeLabor generic code generation")

        try:
            result = await invoke(
                prompt=prompt,
                cwd=str(workspace),
                model=meta.get("model", "sonnet"),
            )

            if result.ok:
                output_file = workspace / "src" / "generated.py"
                output_file.write_text(result.stdout, encoding="utf-8")
                return LaborResult(
                    success=True,
                    output=f"Generic coding completed for task: {task_description[:50]}",
                    token_usage=0,
                )
            else:
                return LaborResult(
                    success=False,
                    output="",
                    token_usage=0,
                    error=f"Generic coding failed: {result.stderr}",
                )
        except Exception as e:
            return LaborResult(
                success=False,
                output="",
                token_usage=0,
                error=str(e),
            )


# ---------------------------------------------------------------------------
# Verification functions (used by PipelineEngine)
# ---------------------------------------------------------------------------

from hermes_os.universal_pipeline import VerificationResult


async def verify_code_compiles(code: str) -> VerificationResult:
    """Verify generated code has no syntax errors."""
    errors = []
    try:
        compile(code, "<string>", "exec")
    except SyntaxError as e:
        errors.append(f"Syntax error: {e}")
    return VerificationResult(passed=len(errors) == 0, errors=errors)


async def verify_tests_pass(test_output: str) -> VerificationResult:
    """Verify test output indicates passing tests."""
    errors = []
    # Look for failure indicators
    if "failed" in test_output.lower() and "0 failed" not in test_output.lower():
        errors.append("Tests failed")
    if "error" in test_output.lower() and "0 error" not in test_output.lower():
        errors.append("Test errors found")
    return VerificationResult(passed=len(errors) == 0, errors=errors)


async def verify_lint_clean(lint_output: str) -> VerificationResult:
    """Verify linting produces no errors."""
    errors = []
    if lint_output.strip():
        # Some linters return non-zero for warnings
        if "error" in lint_output.lower():
            errors.append(f"Linting errors: {lint_output[:100]}")
    return VerificationResult(passed=len(errors) == 0, errors=errors)