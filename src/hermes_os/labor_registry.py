"""LaborRegistry — The central registry for all 'Labor Units' in Hermes OS.

Enables the PipelineEngine to dynamically resolve labor names (from YAML)
to actual implementation classes, injecting necessary dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class LaborResult:
    """Standard result for all Labor Units."""

    success: bool
    token_usage: int = 0
    api_cost_usd: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LaborInterface(Protocol):
    """The standard contract for all Labor Units."""

    async def execute(
        self, workspace: Any, task_description: str, meta: dict[str, Any]
    ) -> LaborResult:
        """Execute the labor task within a workspace."""
        ...


class LaborRegistry:
    """
    Registry for Labor Units.
    Acts as a factory for creating labor instances with proper context.
    """

    def __init__(self) -> None:
        self._registry: dict[str, type[LaborInterface]] = {}

    def register(self, name: str, labor_class: type[LaborInterface]) -> None:
        """Register a labor class with a unique name."""
        self._registry[name] = labor_class
        logger.debug("Registered labor: %s", name)

    def get_labor(self, name: str, **kwargs) -> LaborInterface:
        """
        Resolve a labor name to an instance.
        Allows for dependency injection via kwargs (e.g., user_id, db_path).
        """
        labor_class = self._registry.get(name)
        if not labor_class:
            raise ValueError(f"Labor '{name}' not found in registry.")

        # Instantiate with provided dependencies
        try:
            return labor_class(**kwargs)  # type: ignore
        except TypeError as e:
            logger.error("Failed to instantiate labor %s: %s", name, e)
            raise

    def unregister(self, name: str) -> bool:
        """Remove a labor from the registry.

        Returns:
            True if the labor was removed, False if it wasn't registered.
        """
        if name in self._registry:
            del self._registry[name]
            logger.debug("Unregistered labor: %s", name)
            return True
        return False

    def list_labors(self) -> list[str]:
        """Return a list of all registered labor names."""
        return list(self._registry.keys())

    def get_labor_names(self) -> list[str]:
        """Alias for list_labors() for backward compatibility."""
        return self.list_labors()


_global_registry = LaborRegistry()


def get_labor_registry() -> LaborRegistry:
    """Get the global singleton registry."""
    return _global_registry


# ---------------------------------------------------------------------------
# Auto-registration helper
# ---------------------------------------------------------------------------


def initialize_default_labors() -> None:
    """Bootstrap the registry with built-in labors."""
    from hermes_os.labor.browser_labor import BrowserLabor
    from hermes_os.labor.checker_labor import CheckerLabor
    from hermes_os.labor.code_labor import CodeLabor
    from hermes_os.labor.content_labor import ContentLabor
    from hermes_os.labor.data_labor import DataLabor
    from hermes_os.labor.feishu_labor import FeishuLabor
    from hermes_os.labor.format_labor import FormatLabor
    from hermes_os.labor.github_labor import GitHubLabor
    from hermes_os.labor.governance_labor import GovernanceLabor
    from hermes_os.labor.research_labor import ResearchLabor

    registry = get_labor_registry()
    registry.register("ContentLabor", ContentLabor)
    registry.register("CodeLabor", CodeLabor)
    registry.register("GitHubLabor", GitHubLabor)
    registry.register("CheckerLabor", CheckerLabor)
    registry.register("DataLabor", DataLabor)
    registry.register("BrowserLabor", BrowserLabor)
    registry.register("ResearchLabor", ResearchLabor)
    registry.register("FormatLabor", FormatLabor)
    registry.register("FeishuLabor", FeishuLabor)
    registry.register("GovernanceLabor", GovernanceLabor)
