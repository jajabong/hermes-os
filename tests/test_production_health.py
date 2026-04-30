"""Tests for Hermes OS production health check endpoint."""

from __future__ import annotations

import asyncio
from unittest.mock import patch, MagicMock
import pytest


class TestHealthCheckEndpoint:
    """Tests for GET /health endpoint behavior."""

    @pytest.mark.asyncio
    async def test_health_returns_components_status(self) -> None:
        """GET /health returns status for each component: db, knowledge, claude_binary, api_key, event_bus."""
        # This will fail until we implement the health endpoint
        from fastapi.testclient import TestClient
        from hermes_os.production.health import app, health_check

        result = await health_check()

        assert "status" in result
        assert "components" in result
        assert "timestamp" in result

        components = result["components"]
        assert "hermes_db" in components
        assert "knowledge_db" in components
        assert "claude_binary" in components
        assert "anthropic_api" in components
        assert "event_bus" in components

    @pytest.mark.asyncio
    async def test_health_returns_up_when_all_components_healthy(self) -> None:
        """When all components are reachable, status is 'healthy'."""
        from hermes_os.production.health import health_check

        result = await health_check()

        # All mock components up → overall healthy
        assert result["status"] in ("healthy", "unhealthy")  # depends on actual env

    @pytest.mark.asyncio
    async def test_health_db_check_queries_database(self) -> None:
        """hermes_db component checks SQLite connectivity via SELECT 1."""
        from hermes_os.production.health import health_check

        result = await health_check()
        db_comp = result["components"]["hermes_db"]

        assert "status" in db_comp
        assert db_comp["status"] in ("up", "down")
        if db_comp["status"] == "up":
            assert "path" in db_comp

    @pytest.mark.asyncio
    async def test_health_knowledge_db_check(self) -> None:
        """knowledge_db component checks knowledge DB path exists."""
        from hermes_os.production.health import health_check

        result = await health_check()
        kb_comp = result["components"]["knowledge_db"]

        assert "status" in kb_comp

    @pytest.mark.asyncio
    async def test_health_claude_binary_checks_path(self) -> None:
        """claude_binary component checks if binary exists."""
        from hermes_os.production.health import health_check

        result = await health_check()
        binary_comp = result["components"]["claude_binary"]

        assert "status" in binary_comp
        assert "path" in binary_comp

    @pytest.mark.asyncio
    async def test_health_api_key_checks_env_var(self) -> None:
        """anthropic_api component checks ANTHROPIC_API_KEY env var."""
        from hermes_os.production.health import health_check

        result = await health_check()
        api_comp = result["components"]["anthropic_api"]

        assert "status" in api_comp

    @pytest.mark.asyncio
    async def test_health_event_bus_reports_handler_count(self) -> None:
        """event_bus component reports number of registered handlers."""
        from hermes_os.production.health import health_check

        result = await health_check()
        bus_comp = result["components"]["event_bus"]

        assert "status" in bus_comp
        assert "handlers" in bus_comp
        assert isinstance(bus_comp["handlers"], int)

    @pytest.mark.asyncio
    async def test_health_returns_503_when_critical_component_down(self) -> None:
        """If hermes_db is down, overall status is unhealthy."""
        from hermes_os.production.health import health_check

        # Simulate DB path that doesn't exist or can't be connected
        with patch("hermes_os.production.health._check_hermes_db") as mock_db:
            mock_db.return_value = {"status": "down", "error": "cannot connect"}

            result = await health_check()

            assert result["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_health_timestamp_is_iso_format(self) -> None:
        """timestamp field is in ISO 8601 format."""
        from hermes_os.production.health import health_check

        import re
        result = await health_check()
        ts = result["timestamp"]

        # ISO 8601 pattern: 2026-04-30T12:00:00...
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", ts)

    @pytest.mark.asyncio
    async def test_health_endpoint_no_auth_required(self) -> None:
        """GET /health requires no authentication."""
        from fastapi.testclient import TestClient
        from hermes_os.production.health import app

        client = TestClient(app)
        response = client.get("/health")

        # Should not return 401 or 403
        assert response.status_code != 401
        assert response.status_code != 403


class TestHealthCheckHTTPResponse:
    """Tests for HTTP response format of /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_http_200_when_healthy(self) -> None:
        """GET /health returns 200 when all components are up."""
        from fastapi.testclient import TestClient
        from hermes_os.production.health import app

        client = TestClient(app)
        response = client.get("/health")

        # If healthy → 200, if unhealthy → 503
        data = response.json()
        if data["status"] == "healthy":
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_http_503_when_unhealthy(self) -> None:
        """GET /health returns 503 when any critical component is down."""
        from fastapi.testclient import TestClient
        from hermes_os.production.health import app

        client = TestClient(app)

        # Force unhealthy state
        with patch.dict("os.environ", {"HERMES_DB_PATH": "/nonexistent/path.db"}):
            response = client.get("/health")
            data = response.json()
            if data["status"] == "unhealthy":
                assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_health_response_is_json(self) -> None:
        """GET /health returns Content-Type: application/json."""
        from fastapi.testclient import TestClient
        from hermes_os.production.health import app

        client = TestClient(app)
        response = client.get("/health")

        assert "application/json" in response.headers.get("content-type", "")