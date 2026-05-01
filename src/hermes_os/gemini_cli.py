"""Gemini CLI Invoker — Gemini CLI 调用层 for Hermes OS.

支持两种调用模式：
1. 非交互模式 (gemini -p "prompt") — 适合 sub-agent 执行
2. MCP 模式 — 通过 MCP 协议调用 Gemini 的各种扩展工具

设计原则与 claude_code_invocator.py 保持一致：
- --bare 模式：跳过配置自动发现
- --no-session-persistence：每次调用独立 session
- 超时保护：SIGTERM 强制终止
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator


# =============================================================================
# 配置
# =============================================================================

# None = let Gemini CLI choose its default model
DEFAULT_MODEL: str | None = None
DEFAULT_TIMEOUT_SEC = 120


@dataclass
class GeminiResult:
    """一次 gemini -p 调用的结果"""
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    model: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def find_gemini_binary() -> str:
    """找到 gemini 可执行文件路径"""
    path = shutil.which("gemini")
    if path:
        return path
    for p in ["/opt/homebrew/bin/gemini", "/usr/local/bin/gemini"]:
        if Path(p).exists():
            return p
    return "gemini"


async def invoke(
    prompt: str,
    cwd: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    extra_flags: list[str] | None = None,
) -> GeminiResult:
    """
    调用 gemini -p 并返回结果。

    gemini -p 输出的是 JSON（带 node 警告），需要解析 JSON 提取 response 字段。

    Args:
        prompt: 要执行的提示词
        cwd: 工作目录
        model: 模型名称
        timeout_sec: 超时秒数
        extra_flags: 额外 CLI 标志

    Returns:
        GeminiResult (stdout 包含纯文本 response)

    Raises:
        RuntimeError: 调用失败
    """
    binary = find_gemini_binary()
    args = [binary, "-p", prompt]
    if model:
        args.extend(["--model", model])

    if extra_flags:
        args.extend(extra_flags)

    env = {**os.environ.copy()}

    start = datetime.now()
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=str(cwd) if cwd else None,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_sec
        )
    except asyncio.TimeoutError:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

        duration_ms = int((datetime.now() - start).total_seconds() * 1000)
        raise RuntimeError(f"gemini -p timed out after {timeout_sec}s")

    duration_ms = int((datetime.now() - start).total_seconds() * 1000)
    raw_stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

    # gemini -p 输出 JSON，需要解析并提取 response 字段
    stdout = _extract_gemini_response(raw_stdout)

    return GeminiResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=proc.returncode or 0,
        duration_ms=duration_ms,
        model=model,
    )


def _extract_gemini_response(raw_output: str) -> str:
    """
    从 gemini -p 原始输出中提取 response 字段。

    gemini 输出格式:
    {
      "session_id": "...",
      "response": "实际响应文本",
      "stats": {...}
    }

    Node 警告可能混在输出前面，需要找到第一个 { 开始解析。
    """
    # 找到第一个 { 开始的位置（跳过 node 警告）
    json_start = raw_output.find("{")
    if json_start == -1:
        return raw_output.strip()

    json_str = raw_output[json_start:]
    try:
        data = json.loads(json_str)
        return data.get("response", "").strip()
    except json.JSONDecodeError:
        return raw_output.strip()


async def invoke_stream(
    prompt: str,
    cwd: str | Path | None = None,
    model: str = DEFAULT_MODEL,
) -> AsyncGenerator[str, None]:
    """
    流式调用 gemini -p，yield 每行输出。
    """
    binary = find_gemini_binary()
    args = [binary, "-p", prompt]
    if model:
        args.extend(["--model", model])

    env = {**os.environ.copy()}

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=str(cwd) if cwd else None,
    )

    assert proc.stdout is not None
    try:
        async for line in proc.stdout:
            decoded = line.decode("utf-8", errors="replace").strip()
            if decoded:
                yield decoded
    finally:
        await proc.wait()


async def health_check(timeout_sec: int = 10) -> dict[str, Any]:
    """
    检查 gemini CLI 是否可用。
    """
    diagnosis: dict[str, Any] = {
        "binary": find_gemini_binary(),
        "binary_exists": Path(find_gemini_binary()).exists(),
        "version_works": False,
        "error": None,
    }

    try:
        result = await invoke(
            prompt="Reply with exactly: OK",
            timeout_sec=timeout_sec,
        )
        diagnosis["version_works"] = result.ok
        diagnosis["stdout"] = result.stdout[:100]
    except Exception as e:
        diagnosis["error"] = str(e)[:200]

    return diagnosis
