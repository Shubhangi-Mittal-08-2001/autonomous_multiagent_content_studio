# Purpose: Defines intended platform delegation and quality routing responsibilities.

"""Conditional routing functions for the Plan-Act-Check workflow."""

import logging
from typing import Any

from langgraph.graph import END

logger = logging.getLogger(__name__)


PLATFORM_NODES = {
    "linkedin": "linkedin_agent",
    "x": "x_agent",
    "instagram": "instagram_agent",
    "youtube": "youtube_agent",
    "facebook": "facebook_agent",
}


def route_after_manager(state: dict[str, Any]) -> list[str] | str:
    """Fan the manager's current plan out to its requested platform agent nodes."""
    if state.get("task_failed") or state.get("task_completed"):
        logger.info(
            "Manager routing ended; task_failed=%s task_completed=%s",
            state.get("task_failed"),
            state.get("task_completed"),
        )
        return END

    plan = state.get("current_plan")
    if not isinstance(plan, dict):
        raise ValueError("Manager routing requires a current_plan dictionary.")

    platform_tasks = plan.get("platform_tasks")
    if not isinstance(platform_tasks, list):
        raise ValueError("Manager routing requires a platform task list.")
    if not platform_tasks:
        if (
            plan.get("request_status") == "clarification_required"
            and isinstance(plan.get("clarification_message"), str)
            and plan["clarification_message"].strip()
        ):
            return END
        raise ValueError("A plan without platform tasks must include a clarification message.")

    destinations: list[str] = []
    # Track seen platforms to avoid duplicates in the routing list.
    seen: set[str] = set()
    for task in platform_tasks:
        if not isinstance(task, dict):
            raise ValueError("Each manager platform task must be a dictionary.")
        platform = task.get("platform")
        if not isinstance(platform, str) or not platform.strip():
            raise ValueError("Each manager platform task must name a platform.")

        platform_key = platform.strip().lower()
        node_name = PLATFORM_NODES.get(platform_key)
        if node_name is None:
            logger.error("No agent route is registered for platform=%s", platform)
            raise ValueError(
                f"No platform agent is implemented for requested platform '{platform}'."
            )
        if node_name not in seen:
            destinations.append(node_name)
            seen.add(node_name)

    logger.info("Manager routed platform tasks to agent nodes=%s", destinations)
    return destinations


def route_after_review(state: dict[str, Any]) -> str:
    """Loop failed quality checks back to the manager, or finish the workflow."""
    if state.get("task_failed") or state.get("task_completed"):
        logger.info(
            "Review routing ended; task_failed=%s task_completed=%s",
            state.get("task_failed"),
            state.get("task_completed"),
        )
        return END

    if not state.get("replan_required"):
        logger.info("Review approved the workflow or did not request refinement; ending graph")
        return END

    iteration_count = state.get("iteration_count", 0)
    max_iterations = state.get("max_iterations", 0)
    if iteration_count >= max_iterations:
        logger.info(
            "Review requested refinement but iteration limit is reached (%s/%s); ending graph",
            iteration_count,
            max_iterations,
        )
        return END

    logger.info(
        "Review requested another planning cycle; routing to manager at iteration=%s/%s",
        iteration_count,
        max_iterations,
    )
    return "manager"
