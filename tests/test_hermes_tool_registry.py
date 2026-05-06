"""Tests for HermesToolRegistry — bridges hermes-agent tools to WorkflowEngine."""

import pytest

from hermes_os.hermes_tool_registry import (
    HermesToolRegistry,
    get_tool_registry,
)


class TestHermesToolRegistryDiscover:
    """HermesToolRegistry.discovery() tests."""

    def test_discover_finds_tools(self) -> None:
        """discover() finds and registers tool handlers from hermes-agent tools/."""
        registry = HermesToolRegistry()
        registry.discover()

        # Should find feishu tools
        assert "feishu_calendar_events" in registry.handlers
        assert "feishu_task_list" in registry.handlers
        assert "feishu_doc_read" in registry.handlers
        # Should find 40+ tools total
        assert len(registry.handlers) >= 40

    def test_handler_is_callable(self) -> None:
        """Discovered handlers are callable."""
        registry = HermesToolRegistry()
        registry.discover()

        handler = registry.get("feishu_calendar_list")
        assert callable(handler)

    def test_get_returns_none_for_unknown(self) -> None:
        """get() returns None for unknown tool name."""
        registry = HermesToolRegistry()
        registry.discover()

        assert registry.get("nonexistent_tool_xyz") is None


class TestHermesToolRegistryWorkflowEngine:
    """HermesToolRegistry wiring to WorkflowEngine tests."""

    @pytest.mark.asyncio
    async def test_register_all_with_wires_tools(self) -> None:
        """register_all_with() wires all discovered tools into WorkflowEngine."""
        from hermes_os.workflow_engine import WorkflowEngine

        registry = HermesToolRegistry()
        registry.discover()
        engine = WorkflowEngine()
        registry.register_all_with(engine)

        # Tools should now be registered
        assert "feishu_calendar_events" in engine._tools
        assert "feishu_task_list" in engine._tools
        assert "feishu_doc_read" in engine._tools

    @pytest.mark.asyncio
    async def test_execute_workflow_with_real_tools(self) -> None:
        """execute() can call real hermes-agent tool handlers when registered."""
        from hermes_os.workflow_engine import WorkflowEngine

        registry = HermesToolRegistry()
        registry.discover()
        engine = WorkflowEngine()
        registry.register_all_with(engine)

        # execute() should not return "Tool not found" for feishu tools
        result = await engine.execute(
            user_id="test_user",
            workflow_name="check_project_status",
            context={"project_name": "TestProject"},
        )

        # Steps complete without "Tool not found"
        for r in result.results:
            assert "[Tool not found" not in r


class TestHermesToolRegistrySingleton:
    def test_get_tool_registry_returns_singleton(self) -> None:
        """get_tool_registry() returns the same instance on repeated calls."""
        r1 = get_tool_registry()
        r2 = get_tool_registry()
        assert r1 is r2
        # Should already be discovered from first call
        assert len(r1.handlers) >= 40
