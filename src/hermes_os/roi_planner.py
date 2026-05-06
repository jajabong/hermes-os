"""ROI_Planner — Resource allocation based on ROI metrics.

Calculates priority and allocates compute resources based on:
- ROI = revenue / cost
- Strategic value (long-term vs short-term)
- Domain priority (publication, patent, short_drama)

Usage:
    planner = ROIPlanner()
    priority = planner.calculate_priority(revenue=1000, cost=100)
    allocation = planner.allocate(tasks=[...], resources={"compute_units": 10})
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TaskAllocation:
    """Allocation result for a single task."""

    task_id: str
    task_type: str
    compute_units: int
    priority: float
    roi: float


# Domain weights for strategic prioritization
DOMAIN_WEIGHTS = {
    "publication": 1.0,  # Core business
    "patent": 1.2,  # High strategic value
    "short_drama": 0.8,  # Experimental
    "default": 1.0,
}


class ROIPlanner:
    """
    Calculate ROI-based priority and allocate resources.

    Usage:
        planner = ROIPlanner()
        allocation = planner.allocate(tasks=[...], resources={"compute_units": 10})
    """

    def __init__(self, base_compute: int = 1) -> None:
        self.base_compute = base_compute

    def calculate_roi(self, revenue: float, cost: float) -> float:
        """
        Calculate ROI (Return on Investment).

        ROI = revenue / cost
        """
        if cost == 0:
            return float("inf") if revenue > 0 else 0.0
        return revenue / cost

    def calculate_priority(
        self,
        revenue: float,
        cost: float,
        domain: str = "default",
        strategic_bonus: float = 0.0,
    ) -> float:
        """
        Calculate task priority based on ROI and domain weight.

        Priority = ROI * domain_weight + strategic_bonus
        """
        roi = self.calculate_roi(revenue, cost)
        domain_weight = DOMAIN_WEIGHTS.get(domain, DOMAIN_WEIGHTS["default"])
        priority = roi * domain_weight + strategic_bonus
        return priority

    def allocate(
        self,
        tasks: list[dict[str, Any]],
        resources: dict[str, int],
    ) -> list[TaskAllocation]:
        """
        Allocate resources to tasks based on ROI priority.

        Higher ROI tasks get more compute units.

        Args:
            tasks: List of task dicts with id, type, roi, revenue, cost
            resources: Available resources (e.g., {"compute_units": 10})

        Returns:
            List of TaskAllocation for each task
        """
        compute_units = resources.get("compute_units", 5)

        # Calculate priority for each task
        task_priorities = []
        for task in tasks:
            roi = task.get("roi")
            if roi is None:
                revenue = task.get("revenue", 0)
                cost = task.get("cost", 1)
                roi = self.calculate_roi(revenue, cost)

            priority = self.calculate_priority(
                revenue=task.get("revenue", 0),
                cost=task.get("cost", 1),
                domain=task.get("domain", "default"),
                strategic_bonus=task.get("strategic_bonus", 0),
            )
            task_priorities.append((task["id"], task.get("type", "default"), priority, roi))

        # Sort by priority descending
        task_priorities.sort(key=lambda x: x[2], reverse=True)

        # Allocate compute units proportionally
        total_priority = sum(p for _, _, p, _ in task_priorities)
        if total_priority == 0:
            # Equal split
            per_task = compute_units // len(tasks) if tasks else 0
            return [
                TaskAllocation(
                    task_id=t["id"],
                    task_type=t.get("type", "default"),
                    compute_units=per_task,
                    priority=0,
                    roi=0,
                )
                for t in tasks
            ]

        allocations = []
        for task_id, task_type, priority, roi in task_priorities:
            # Proportional allocation with minimum 1
            proportion = priority / total_priority
            allocated = max(1, int(compute_units * proportion))
            allocations.append(
                TaskAllocation(
                    task_id=task_id,
                    task_type=task_type,
                    compute_units=allocated,
                    priority=priority,
                    roi=roi,
                )
            )

        logger.info(
            "Allocated %d compute units across %d tasks (max priority: %.2f)",
            compute_units,
            len(tasks),
            max(p for _, _, p, _ in task_priorities) if task_priorities else 0,
        )
        return allocations

    def suggest_next_action(
        self,
        completed_tasks: list[dict[str, Any]],
        pending_tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Suggest next action based on ROI performance.

        Analyzes completed vs pending to recommend:
        - Continue current domain
        - Pivot to higher ROI domain
        - Scale up/down
        """
        if not completed_tasks:
            return {"action": "continue", "reason": "No completed tasks to analyze"}

        # Calculate average ROI per domain
        domain_roi: dict[str, list[float]] = {}
        for task in completed_tasks:
            domain = task.get("domain", "default")
            roi = task.get("roi", 0)
            if domain not in domain_roi:
                domain_roi[domain] = []
            domain_roi[domain].append(roi)

        avg_roi = {domain: sum(rois) / len(rois) for domain, rois in domain_roi.items()}

        # Find best performing domain
        best_domain = max(avg_roi, key=avg_roi.get) if avg_roi else "default"
        best_roi = avg_roi.get(best_domain, 0)

        # Check pending tasks
        pending_domains = set(t.get("domain", "default") for t in pending_tasks)

        if best_domain in pending_domains:
            return {
                "action": "continue",
                "domain": best_domain,
                "reason": f"Domain '{best_domain}' has highest avg ROI ({best_roi:.2f})",
                "recommended_compute": 2,  # Scale up
            }

        return {
            "action": "pivot",
            "to_domain": best_domain,
            "reason": f"Domain '{best_domain}' has highest ROI ({best_roi:.2f})",
        }
