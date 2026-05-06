"""Structured JSON logging for Hermes OS with correlation context.

Provides:
- HermesJSONFormatter: emits JSON log lines with correlation_id, user_id, session_id
- set_log_context(): thread-local context injection
- setup_structured_logging(): factory for pre-configured loggers
"""

from __future__ import annotations

import json
import logging
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

# Thread-safe context variables for correlation IDs
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_user_id: ContextVar[str] = ContextVar("user_id", default="")
_session_id: ContextVar[str] = ContextVar("session_id", default="")


def set_log_context(
    correlation_id: str = "",
    user_id: str = "",
    session_id: str = "",
) -> None:
    """Set correlation context for the current async context.

    Call with no arguments to clear all context.
    """
    _correlation_id.set(correlation_id)
    _user_id.set(user_id)
    _session_id.set(session_id)


class HermesJSONFormatter(logging.Formatter):
    """JSON log formatter with correlation context fields.

    Output fields: timestamp, level, logger, message, module, line,
    correlation_id, user_id, session_id, and any extra fields.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as a JSON string."""
        timestamp = datetime.now(UTC).isoformat()

        # Gather context fields
        correlation_id = _correlation_id.get()
        user_id = _user_id.get()
        session_id = _session_id.get()

        log_entry: dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }

        if correlation_id:
            log_entry["correlation_id"] = correlation_id
        if user_id:
            log_entry["user_id"] = user_id
        if session_id:
            log_entry["session_id"] = session_id

        # Include extra fields
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id

        # Include exception info if present
        if record.exc_info:
            log_entry["traceback"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)

    def formatException(self, exc_info: tuple) -> str:
        """Format exception traceback as a string."""
        return "".join(traceback.format_exception(*exc_info))


def setup_structured_logging(
    name: str | None = None,
    level: int = logging.INFO,
    json_format: bool = True,
) -> logging.Logger:
    """Configure and return a logger with structured JSON logging.

    Args:
        name: Logger name. None = root logger.
        level: Logging level.
        json_format: Use JSON formatter (True) or standard formatter (False).

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()

    handler = logging.StreamHandler()
    if json_format:
        handler.setFormatter(HermesJSONFormatter())
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        handler.setFormatter(formatter)

    logger.addHandler(handler)
    return logger
