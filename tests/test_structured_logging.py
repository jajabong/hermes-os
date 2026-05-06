"""Tests for Hermes OS structured JSON logging with correlation context."""

from __future__ import annotations

import json
import logging
from io import StringIO


class TestStructuredJsonFormatter:
    """Tests for HermesJSONFormatter — structured JSON log output."""

    def test_formatter_outputs_valid_json(self) -> None:
        """Log record formatted as JSON string is valid parseable JSON."""
        from hermes_os.production.logging import HermesJSONFormatter

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(HermesJSONFormatter())
        logger = logging.getLogger("test_json_valid")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("Hello world")
        output = stream.getvalue()
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_formatter_includes_timestamp(self) -> None:
        """JSON log includes ISO timestamp field."""
        from hermes_os.production.logging import HermesJSONFormatter

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(HermesJSONFormatter())
        logger = logging.getLogger("test_ts")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("test")
        output = stream.getvalue()
        parsed = json.loads(output)
        assert "timestamp" in parsed

    def test_formatter_includes_level(self) -> None:
        """JSON log includes log level field."""
        from hermes_os.production.logging import HermesJSONFormatter

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(HermesJSONFormatter())
        logger = logging.getLogger("test_level")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.warning("test warning")
        output = stream.getvalue()
        parsed = json.loads(output)
        assert parsed["level"] == "WARNING"

    def test_formatter_includes_logger_name(self) -> None:
        """JSON log includes logger name field."""
        from hermes_os.production.logging import HermesJSONFormatter

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(HermesJSONFormatter())
        logger = logging.getLogger("com.test.logger")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("test")
        output = stream.getvalue()
        parsed = json.loads(output)
        assert parsed["logger"] == "com.test.logger"

    def test_formatter_includes_message(self) -> None:
        """JSON log includes message field."""
        from hermes_os.production.logging import HermesJSONFormatter

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(HermesJSONFormatter())
        logger = logging.getLogger("test_msg")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("my test message")
        output = stream.getvalue()
        parsed = json.loads(output)
        assert parsed["message"] == "my test message"

    def test_formatter_includes_module_and_line(self) -> None:
        """JSON log includes module and line number."""
        from hermes_os.production.logging import HermesJSONFormatter

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(HermesJSONFormatter())
        logger = logging.getLogger("test_loc")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("test")
        output = stream.getvalue()
        parsed = json.loads(output)
        assert "module" in parsed
        assert "line" in parsed


class TestCorrelationContext:
    """Tests for correlation ID / user_id / session_id context propagation."""

    def test_context_injected_via_log_record_factory(self) -> None:
        """correlation_id, user_id, session_id appear in log output when set in context."""
        from hermes_os.production.logging import HermesJSONFormatter, set_log_context

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(HermesJSONFormatter())
        logger = logging.getLogger("test_ctx")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        set_log_context(correlation_id="corr-123", user_id="user-alice", session_id="sess-456")
        logger.info("context test")
        set_log_context()  # clear

        output = stream.getvalue()
        parsed = json.loads(output)
        assert parsed["correlation_id"] == "corr-123"
        assert parsed["user_id"] == "user-alice"
        assert parsed["session_id"] == "sess-456"

    def test_context_omitted_when_not_set(self) -> None:
        """Fields omitted from JSON when context values are not set."""
        from hermes_os.production.logging import HermesJSONFormatter, set_log_context

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(HermesJSONFormatter())
        logger = logging.getLogger("test_no_ctx")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        set_log_context()  # clear all
        logger.info("no context")
        output = stream.getvalue()
        parsed = json.loads(output)
        assert "correlation_id" not in parsed
        assert "user_id" not in parsed
        assert "session_id" not in parsed

    def test_extra_fields_passed_through(self) -> None:
        """Extra fields passed via Logger work appear in JSON output."""
        from hermes_os.production.logging import HermesJSONFormatter

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(HermesJSONFormatter())
        logger = logging.getLogger("test_extra")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("with extra", extra={"request_id": "req-789"})
        output = stream.getvalue()
        parsed = json.loads(output)
        assert parsed["request_id"] == "req-789"

    def test_exception_info_included_on_error(self) -> None:
        """Exception traceback is included when logging an error with exc_info."""
        from hermes_os.production.logging import HermesJSONFormatter

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(HermesJSONFormatter())
        logger = logging.getLogger("test_exc")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        try:
            raise ValueError("test error")
        except ValueError:
            logger.error("caught error", exc_info=True)

        output = stream.getvalue()
        parsed = json.loads(output)
        assert parsed["level"] == "ERROR"
        assert "traceback" in parsed


class TestSetupStructuredLogging:
    """Tests for setup_structured_logging() factory."""

    def test_setup_returns_configured_logger(self) -> None:
        """setup_structured_logging returns a logger with JSON handler."""
        from hermes_os.production.logging import setup_structured_logging

        logger = setup_structured_logging("test_setup")
        assert logger.name == "test_setup"
        assert len(logger.handlers) >= 1

    def test_setup_accepts_log_level(self) -> None:
        """setup_structured_logging accepts log_level parameter."""
        from hermes_os.production.logging import setup_structured_logging

        logger = setup_structured_logging("test_level", level=logging.DEBUG)
        assert logger.level == logging.DEBUG

    def test_root_logger_gets_json_handler(self) -> None:
        """Calling setup_structured_logging without name configures root logger."""
        from hermes_os.production.logging import setup_structured_logging

        # Remove existing handlers first
        root = logging.getLogger()
        for h in root.handlers[:]:
            root.removeHandler(h)

        logger = setup_structured_logging()
        # Should have handler
        assert len(logger.handlers) >= 1
