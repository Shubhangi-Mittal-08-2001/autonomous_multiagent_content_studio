# Purpose: Defines the shared state responsibilities for the workflow.

import operator
from typing import Annotated, Any, TypedDict


class ContentCreationState(TypedDict):
    """Shared state for the manager-led LangGraph content publishing workflow."""

    # Original request
    content: str
    """Original idea, article, transcript, or source text."""

    platforms: list[str]
    """Platforms requested by the user, such as LinkedIn, X, Instagram, or YouTube."""

    audience: str
    """Target audience for the generated content."""

    llm_model: str
    """LiteLLM proxy model alias selected for this request."""

    # Planning and execution
    current_plan: dict[str, Any]
    """Latest overall plan created by the manager."""

    manager_note: str
    """Manager clarification note when planning stops without draft tasks."""

    node_plans: Annotated[list[dict[str, Any]], operator.add]
    """Append-only history of platform-specific plans."""

    current_step: str
    """Name of the workflow step currently being executed."""

    execution_history: Annotated[list[dict[str, Any]], operator.add]
    """Append-only history of platform executions and generated draft versions."""

    latest_results: Annotated[dict[str, Any], operator.or_]
    """Latest draft and execution details keyed by platform; merges independent platform updates."""

    # Review and quality tracking
    quality_score: float
    """Overall quality score assigned to the latest review cycle."""

    quality_threshold: float
    """Minimum quality score required for approval."""

    review_history: Annotated[list[dict[str, Any]], operator.add]
    """Append-only history of review scores, feedback, and refinement decisions."""

    review_feedback: dict[str, str]
    """Latest review feedback keyed by platform."""

    platform_status: dict[str, str]
    """Latest status for each platform, such as pending, approved, or needs_refinement."""

    # Re-planning and iteration control
    replan_required: bool
    """Whether another manager-led refinement cycle is required."""

    replan_count: int
    """Number of times the manager has revised the execution plan."""

    max_iterations: int
    """Maximum number of refinement cycles allowed after initial generation."""

    iteration_count: int
    """Number of refinement cycles completed so far."""

    # Final output and workflow status
    processed_content: list[dict[str, str]]
    """Final content package returned to the API, containing the latest draft per platform."""

    task_completed: bool
    """Whether the workflow has reached a terminal state."""

    task_failed: bool
    """Whether an unrecoverable error prevented successful execution."""

    error_message: str
    """Error details when execution fails; otherwise an empty string."""
