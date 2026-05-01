"""
claude_code_invocator.py — Hermes OS 的 Claude Code 调用层
=============================================================

核心职责：封装 claude -p 的正确调用方式，作为 Hermes OS 的 sub-agent 执行层。

设计决策：
1. --bare 模式：跳过 CLAUDE.md 自动发现，避免目录递归导致的超时
2. --add-dir 显式添加目录：保留工具访问能力
3. --no-session-persistence：每次调用独立 session，不污染会话历史
4. --output-format json：机器可解析的输出
5. --max-turns 控制：防止失控的长时间任务
6. 超时保护：SIGTERM 强制终止，不等待自然退出
7. alias 环境变量：自动解析 claude-mini alias 中的 API 配置

调用模式：
    invoke(prompt, cwd=project_path)     → 单次任务（分析/规划）
    invoke_stream(prompt, cwd)           → 流式任务（代码生成）
    invoke_bash(cmd)                      → 纯命令执行（不启动 LLM）
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator

import aiosqlite

# =============================================================================
# 配置
# =============================================================================

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TURNS = 20
DEFAULT_TIMEOUT_SEC = 120
DEFAULT_ALLOWED_TOOLS = "Bash,Read,Edit,Write,Glob,Grep,Notebook,Bash(git *),Bash(ls *),Bash(find *),Bash(cat *),Bash(head *),Bash(wc *),Bash(jq *),Bash(curl *)"


@dataclass
class InvocationResult:
    """一次 claude -p 调用的结果"""

    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    model: str
    turns: int = 0
    session_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "model": self.model,
            "turns": self.turns,
            "session_id": self.session_id,
        }


class InvocationError(Exception):
    """调用失败（超时、退出码非0、工具缺失等）"""

    def __init__(self, message: str, result: InvocationResult | None = None):
        super().__init__(message)
        self.result = result


# =============================================================================
# 核心调用函数
# =============================================================================

_claude_binary_cache: str | None = None
_claude_env_cache: dict[str, str] | None = None


def find_claude_binary() -> str:
    """
    找到 claude 可执行文件路径。

    优先使用 /opt/homebrew/bin/claude（Homebrew 安装的 Claude Code CLI），
    而不是 shutil.which("claude") 返回的 cmux wrapper。
    Homebrew 版本与 MiniMax API alias 环境变量配合工作。
    """
    global _claude_binary_cache
    if _claude_binary_cache:
        return _claude_binary_cache

    # 优先用 Homebrew 安装的 Claude Code（与 MiniMax alias 配合）
    for path in ["/opt/homebrew/bin/claude", "/usr/local/bin/claude"]:
        if Path(path).exists():
            _claude_binary_cache = path
            return _claude_binary_cache

    # 回退到 which
    which_result = shutil.which("claude")
    if which_result:
        _claude_binary_cache = which_result
    else:
        _claude_binary_cache = "claude"
    return _claude_binary_cache


def get_claude_env() -> dict[str, str]:
    """
    从 claude-mini alias 提取环境变量（API URL、API Key、TLS 设置等）。

    这是关键修复：直接调 /opt/homebrew/bin/claude 会因为缺少
    ANTHROPIC_BASE_URL 和 NODE_TLS_REJECT_UNAUTHORIZED 而报 API Key 无效。
    通过解析 alias 获取完整环境配置。
    """
    global _claude_env_cache
    if _claude_env_cache is not None:
        return _claude_env_cache

    env_vars: dict[str, str] = {}

    try:
        # 尝试交互式 shell 获取完整 alias（包括 env 设置）
        result = subprocess.run(
            ["zsh", "-i", "-c", "alias claude-mini 2>/dev/null || alias claude 2>/dev/null || echo NOT_FOUND"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        alias_str = result.stdout.strip()

        if alias_str and alias_str != "NOT_FOUND":
            # 从 alias 中提取所有 KEY=VALUE 环境变量
            # 格式: env KEY1="val1" KEY2="val2" ... /path/to/binary --flags
            # 找到 'env' 后面的所有 KEY=VALUE 对
            env_match = re.search(r'^[^=]+=\'env\s+(.+?)\s+/', alias_str, re.DOTALL)
            if env_match:
                env_part = env_match.group(1)
                # 匹配 KEY="VALUE" 或 KEY='' 或 KEY=VALUE 格式
                for match in re.finditer(r'(\w+)=["\']([^"\']*?)["\']|\.(\w+)=(["\']?)([^"\']*?)\3', env_part):
                    if match.group(1):  # KEY="VALUE" 格式
                        key, val = match.group(1), match.group(2)
                        if key.isupper():
                            env_vars[key] = val
            # 回退：直接搜索所有 KEY="value" 模式
            if not env_vars:
                for match in re.finditer(r'(\w+)=["\']([^"\']*?)["\']', alias_str):
                    key, val = match.group(1), match.group(2)
                    if key.isupper() and val:
                        env_vars[key] = val

    except Exception:
        pass

    # 如果 alias 解析失败，从当前进程环境继承
    if not env_vars:
        for key in ["ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "NODE_TLS_REJECT_UNAUTHORIZED", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"]:
            val = os.environ.get(key)
            if val:
                env_vars[key] = val

    _claude_env_cache = env_vars
    return env_vars


def build_args(
    prompt: str,
    cwd: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    max_turns: int = DEFAULT_MAX_TURNS,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    allowed_tools: str | None = None,
    output_format: str = "text",
    add_dirs: list[str] | None = None,
    system_prompt: str | None = None,
    extra_flags: list[str] | None = None,
) -> list[str]:
    """构建 claude -p 命令行参数"""
    args = [find_claude_binary(), "-p", prompt]

    # 关键标志：bare 跳过 CLAUDE.md 自动发现，保证速度
    args.append("--bare")

    # 输出格式
    args.extend(["--output-format", output_format])

    # 不持久化 session，每次独立
    args.append("--no-session-persistence")

    # MiniMax 等第三方 API 需要 bypassPermissions
    args.append("--permission-mode")
    args.append("bypassPermissions")

    # 模型
    if model:
        args.extend(["--model", model])

    # 最大回合
    args.extend(["--max-turns", str(max_turns)])

    # 允许的工具（默认白名单）
    if allowed_tools:
        args.extend(["--allowed-tools", allowed_tools])

    # 显式添加工作目录（补充 --bare 跳过的工具访问）
    if cwd:
        args.extend(["--add-dir", str(cwd)])
    if add_dirs:
        for d in add_dirs:
            args.extend(["--add-dir", d])

    # 系统提示词追加
    if system_prompt:
        args.extend(["--append-system-prompt", system_prompt])

    # 额外标志
    if extra_flags:
        args.extend(extra_flags)

    return args


async def invoke(
    prompt: str,
    cwd: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    max_turns: int = DEFAULT_MAX_TURNS,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    allowed_tools: str | None = DEFAULT_ALLOWED_TOOLS,
    output_format: str = "text",
    add_dirs: list[str] | None = None,
    system_prompt: str | None = None,
    extra_flags: list[str] | None = None,
    log_db_path: str | Path | None = None,
) -> InvocationResult:
    """
    调用 claude -p 并返回结果。

    这是同步入口，内部用 asyncio.create_subprocess_exec 实现超时控制。

    Args:
        prompt: 要执行的提示词
        cwd: 工作目录（会同时作为 --add-dir 传入）
        model: 模型名称
        max_turns: 最大自主回合数
        timeout_sec: 超时秒数（到达后 SIGTERM）
        allowed_tools: 工具白名单
        output_format: text | json | stream-json
        add_dirs: 额外允许访问的目录
        system_prompt: 追加的系统提示词
        extra_flags: 额外 CLI 标志
        log_db_path: 可选：写入调用日志到 SQLite

    Returns:
        InvocationResult

    Raises:
        InvocationError: 调用失败（超时或退出码非0）
    """
    start = datetime.now()
    args = build_args(
        prompt=prompt,
        cwd=cwd,
        model=model,
        max_turns=max_turns,
        timeout_sec=timeout_sec,
        allowed_tools=allowed_tools,
        output_format=output_format,
        add_dirs=add_dirs,
        system_prompt=system_prompt,
        extra_flags=extra_flags,
    )

    env = {**os.environ.copy()}
    # 合并 claude-mini alias 中的环境变量（API URL、API Key、TLS 设置等）
    # 这是关键修复：直接调 /opt/homebrew/bin/claude 需要这些变量才能正确路由到 MiniMax API
    claude_env = get_claude_env()
    env.update(claude_env)

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
        # 超时：SIGTERM 强制终止
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

        duration_ms = int((datetime.now() - start).total_seconds() * 1000)
        result = InvocationResult(
            stdout="",
            stderr=f"Invocation timed out after {timeout_sec}s (SIGTERM sent)",
            exit_code=-1,
            duration_ms=duration_ms,
            model=model,
        )
        raise InvocationError(f"claude -p timed out after {timeout_sec}s", result)

    duration_ms = int((datetime.now() - start).total_seconds() * 1000)

    stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

    result = InvocationResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=proc.returncode or 0,
        duration_ms=duration_ms,
        model=model,
    )

    # 写调用日志
    if log_db_path:
        await _log_invocation(log_db_path, args, result)

    if result.exit_code != 0:
        raise InvocationError(
            f"claude -p failed with exit code {result.exit_code}\nstderr: {result.stderr[:500]}",
            result,
        )

    return result


async def invoke_stream(
    prompt: str,
    cwd: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    max_turns: int = DEFAULT_MAX_TURNS,
    allowed_tools: str | None = DEFAULT_ALLOWED_TOOLS,
    add_dirs: list[str] | None = None,
    system_prompt: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    流式调用 claude -p，yield 每行输出。

    适用于长时间任务，调用方可以实时看到输出。
    注意：流式模式下不支持超时保护（process 永不退出直到完成）。
    """
    args = build_args(
        prompt=prompt,
        cwd=cwd,
        model=model,
        max_turns=max_turns,
        timeout_sec=999999,  # 流式不用这个，依赖 max-turns 保护
        allowed_tools=allowed_tools,
        output_format="stream-json",
        add_dirs=add_dirs,
        system_prompt=system_prompt,
    )

    env = {**os.environ.copy()}
    env.update(get_claude_env())

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=str(cwd) if cwd else None,
    )

    # 读 stdout（流式）
    assert proc.stdout is not None
    try:
        async for line in proc.stdout:
            decoded = line.decode("utf-8", errors="replace").strip()
            if decoded:
                yield decoded
    finally:
        # 等待 process 结束
        await proc.wait()


async def invoke_bash(
    command: str,
    cwd: str | Path | None = None,
    timeout_sec: int = 30,
) -> InvocationResult:
    """
    纯 Bash 调用：不启动 LLM，只执行 shell 命令。

    等同于 hermes-tools 的 terminal()，但通过 claude 的沙箱执行
    （受 allowed-tools 约束）。
    """
    prompt = f"Execute this bash command and output only the result: `{command}`"
    return await invoke(
        prompt=prompt,
        cwd=cwd,
        max_turns=1,
        timeout_sec=timeout_sec,
        allowed_tools="Bash",
        system_prompt="You are a bash executor. Output only the raw command output.",
    )


# =============================================================================
# 调用日志（可选的 SQLite 持久化）
# =============================================================================

INVOCATION_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS claude_invocation_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    prompt      TEXT,
    cwd         TEXT,
    model       TEXT,
    exit_code   INTEGER,
    duration_ms INTEGER,
    stdout_len  INTEGER,
    stderr_len  INTEGER,
    ok          INTEGER
);
"""


async def _log_invocation(
    db_path: str | Path,
    args: list[str],
    result: InvocationResult,
) -> None:
    """写入一条调用日志"""
    # 提取 prompt（第二个元素）
    prompt = args[1] if len(args) > 1 else ""
    cwd = None
    for i, a in enumerate(args):
        if a == "--add-dir" and i + 1 < len(args):
            cwd = args[i + 1]
            break

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO claude_invocation_log (ts, prompt, cwd, model, exit_code, duration_ms, stdout_len, stderr_len, ok) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now().isoformat(),
                prompt[:500],  # 截断防止 DB 膨胀
                cwd,
                result.model,
                result.exit_code,
                result.duration_ms,
                len(result.stdout),
                len(result.stderr),
                int(result.ok),
            ),
        )
        await db.commit()


async def init_invocation_log(db_path: str | Path) -> None:
    """初始化调用日志表"""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(INVOCATION_LOG_SCHEMA)
        await db.commit()


# =============================================================================
# 健康检查
# =============================================================================

async def health_check(timeout_sec: int = 10) -> dict[str, Any]:
    """
    检查 claude -p 是否可用，返回诊断信息。
    """
    diagnosis: dict[str, Any] = {
        "binary": find_claude_binary(),
        "binary_exists": Path(find_claude_binary()).exists(),
        "api_key_set": bool(subprocess.os.environ.get("ANTHROPIC_API_KEY")),
        "bare_mode_works": False,
        "full_diagnostic": "",
        "error": None,
    }

    try:
        result = await invoke(
            prompt="Reply with exactly: OK",
            timeout_sec=timeout_sec,
            max_turns=1,
            system_prompt="You are a health check responder.",
        )
        diagnosis["bare_mode_works"] = result.ok
        diagnosis["full_diagnostic"] = result.stdout
    except InvocationError as e:
        diagnosis["error"] = str(e)[:200]

    return diagnosis


# =============================================================================
# 辅助
# =============================================================================

