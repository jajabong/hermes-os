"""HermesToolRegistry — bridges hermes-agent tool registry to WorkflowEngine."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# hermes-agent tools directory
_HERMES_TOOLS_DIR = Path.home() / ".hermes" / "hermes-agent" / "tools"


class HermesToolRegistry:
    """
    Discovers and exposes hermes-agent tool handlers for direct invocation.

    hermes-agent tools are Python modules that define `_handle_*` functions
    and register them via `registry.register(name=..., handler=...)`. This class
    imports those modules to extract handlers for WorkflowEngine's direct-call mode.

    Usage:
        registry = HermesToolRegistry()
        registry.discover()  # scans ~/.hermes/hermes-agent/tools/
        engine = WorkflowEngine()
        for name, handler in registry.handlers.items():
            engine.register_tool(name, handler)
    """

    def __init__(self, tools_dir: Path | None = None) -> None:
        self._tools_dir = tools_dir or _HERMES_TOOLS_DIR
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._names_by_module: dict[str, list[str]] = {}

    def discover(self) -> None:
        """Scan tools directory and register all discovered tool handlers."""
        if not self._tools_dir.exists():
            logger.warning("HermesToolRegistry: tools dir not found at %s", self._tools_dir)
            return

        # Ensure hermes-agent source is in sys.path for imports
        agent_src = self._tools_dir.parent
        if str(agent_src) not in sys.path:
            sys.path.insert(0, str(agent_src))

        for tool_file in sorted(self._tools_dir.glob("*.py")):
            if tool_file.stem in ("__init__", "__pycache__"):
                continue
            self._import_module(tool_file)

        logger.info(
            "HermesToolRegistry: discovered %d tools across %d modules",
            len(self._handlers),
            len(self._names_by_module),
        )

    def _import_module(self, tool_file: Path) -> None:
        """Import a single tool module and collect its registered handlers."""
        try:
            # Use importlib for controlled imports
            import importlib.util
            spec = importlib.util.spec_from_file_location(tool_file.stem, tool_file)
            if spec is None or spec.loader is None:
                return
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Collect handlers defined in this module
            module_handlers: list[str] = []
            for name in dir(module):
                if name.startswith("_handle_"):
                    handler = getattr(module, name, None)
                    if callable(handler):
                        tool_name = self._handler_to_tool_name(name)
                        self._handlers[tool_name] = handler
                        module_handlers.append(tool_name)

            if module_handlers:
                self._names_by_module[tool_file.stem] = module_handlers

        except Exception as e:
            logger.debug("HermesToolRegistry: failed to import %s — %s", tool_file.stem, e)

    def _handler_to_tool_name(self, handler_name: str) -> str:
        """Convert _handle_feishu_calendar_events → feishu_calendar_events."""
        if handler_name.startswith("_handle_"):
            return handler_name[8:]  # strip _handle_
        return handler_name

    @property
    def handlers(self) -> dict[str, Callable[..., Any]]:
        """Return all discovered tool handlers."""
        return dict(self._handlers)

    def get(self, name: str) -> Callable[..., Any] | None:
        """Get a handler by tool name, or None if not found."""
        return self._handlers.get(name)

    def register_all_with(self, engine: "WorkflowEngine") -> None:
        """Register all discovered handlers with a WorkflowEngine instance."""
        for name, handler in self._handlers.items():
            engine.register_tool(name, handler)


# Singleton for gateway hook reuse
_tool_registry: HermesToolRegistry | None = None


def get_tool_registry() -> HermesToolRegistry:
    """Get or create the singleton HermesToolRegistry."""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = HermesToolRegistry()
        _tool_registry.discover()
    return _tool_registry
