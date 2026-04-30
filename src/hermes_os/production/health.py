"""Production health check endpoint for Hermes OS.

GET /health — returns component status for:
- hermes_db: SQLite database connectivity
- knowledge_db: knowledge base path existence
- claude_binary: Claude CLI binary presence
- anthropic_api: ANTHROPIC_API_KEY env var
- event_bus: registered handler count
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse

from hermes_os.claude_code_invocator import find_claude_binary
from hermes_os.event_loop import get_event_bus

app = FastAPI(title="Hermes OS Health")

# Default paths
DEFAULT_HERMES_DB_PATH = os.environ.get("HERMES_DB_PATH", "hermes.db")
DEFAULT_KNOWLEDGE_DB_PATH = os.environ.get("KNOWLEDGE_DB_PATH", "hermes_knowledge.db")


# ---------------------------------------------------------------------------
# Component checks
# ---------------------------------------------------------------------------


async def _check_hermes_db() -> dict:
    """Check SQLite connectivity for hermes_db via SELECT 1."""
    db_path = DEFAULT_HERMES_DB_PATH
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("SELECT 1")
            await db.commit()
        return {"status": "up", "path": db_path}
    except Exception as e:
        return {"status": "down", "path": db_path, "error": str(e)}


async def _check_knowledge_db() -> dict:
    """Check knowledge_db path exists."""
    db_path = DEFAULT_KNOWLEDGE_DB_PATH
    if Path(db_path).exists():
        return {"status": "up", "path": db_path}
    return {"status": "down", "path": db_path, "error": "path does not exist"}


async def _check_claude_binary() -> dict:
    """Check if Claude binary exists and is accessible."""
    path = find_claude_binary()
    if Path(path).exists():
        return {"status": "up", "path": path}
    return {"status": "down", "path": path, "error": "binary not found"}


async def _check_anthropic_api() -> dict:
    """Check ANTHROPIC_API_KEY environment variable is set."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        return {"status": "up"}
    return {"status": "down", "error": "ANTHROPIC_API_KEY not set"}


async def _check_event_bus() -> dict:
    """Check event_bus registered handler count."""
    bus = get_event_bus()
    # Count total handlers across all event types
    handler_count = sum(len(handlers) for handlers in bus._handlers.values())
    return {"status": "up", "handlers": handler_count}


# ---------------------------------------------------------------------------
# Main health check
# ---------------------------------------------------------------------------


async def health_check() -> dict:
    """Run all component checks and return aggregate health status."""
    hermes_db, knowledge_db, claude_binary, anthropic_api, event_bus = await asyncio.gather(
        _check_hermes_db(),
        _check_knowledge_db(),
        _check_claude_binary(),
        _check_anthropic_api(),
        _check_event_bus(),
    )

    components = {
        "hermes_db": hermes_db,
        "knowledge_db": knowledge_db,
        "claude_binary": claude_binary,
        "anthropic_api": anthropic_api,
        "event_bus": event_bus,
    }

    # hermes_db is critical — if it's down, overall is unhealthy
    is_healthy = hermes_db["status"] == "up"

    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "components": components,
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------


@app.get("/health")
async def get_health(response: Response) -> JSONResponse:
    """GET /health — returns component health status.

    Returns 200 if healthy, 503 if any critical component is down.
    No authentication required.
    """
    result = await health_check()

    if result["status"] == "healthy":
        response.status_code = 200
    else:
        response.status_code = 503

    return JSONResponse(content=result)
