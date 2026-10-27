# Purpose: Defines the intended workflow construction entry point.

"""Build and compile the manager-led content creation graph."""

from collections.abc import Callable
import logging
from typing import Any

from langgraph.graph import END, StateGraph

from agents.instagram_agent import instagram_agent
from agents.facebook_agent import facebook_agent
from agents.linkedin_agent import linkedin_agent
from agents.manager import manager_node
from agents.review_refine import review_refine_node
from agents.x_agent import x_agent
from agents.youtube_agent import youtube_agent
from graph.routing import PLATFORM_NODES, route_after_manager, route_after_review
from state.content_state import ContentCreationState

logger = logging.getLogger(__name__)


def _agent_without_step_update(
    agent: Callable[[dict[str, Any]], dict[str, Any]],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Prevent parallel agents from writing the same single-value state channel."""

    def run_agent(state: dict[str, Any]) -> dict[str, Any]:
        """Run an agent while leaving the shared workflow step to the reviewer."""
        result = agent(state)
        # Platform agents run in parallel; review_refine_node sets current_step after they join.
        return {key: value for key, value in result.items() if key != "current_step"}

    return run_agent


def build_graph():
    """Construct and compile the Plan-Act-Check workflow."""
    workflow = StateGraph(ContentCreationState)
    workflow.add_node("manager", manager_node)
    workflow.add_node("linkedin_agent", _agent_without_step_update(linkedin_agent))
    workflow.add_node("x_agent", _agent_without_step_update(x_agent))
    workflow.add_node("instagram_agent", _agent_without_step_update(instagram_agent))
    workflow.add_node("youtube_agent", _agent_without_step_update(youtube_agent))
    workflow.add_node("facebook_agent", _agent_without_step_update(facebook_agent))
    workflow.add_node("review_refine", review_refine_node)

    workflow.set_entry_point("manager")
    workflow.add_conditional_edges(
        "manager",
        route_after_manager,
        path_map={
            **{node_name: node_name for node_name in PLATFORM_NODES.values()},
            END: END,
        },
    )

    # All selected agent branches converge before the reviewer checks their merged results.
    for agent_name in (
        "linkedin_agent",
        "x_agent",
        "instagram_agent",
        "youtube_agent",
        "facebook_agent",
    ):
        workflow.add_edge(agent_name, "review_refine")

    workflow.add_conditional_edges(
        "review_refine",
        route_after_review,
        path_map={"manager": "manager", END: END},
    )
    return workflow.compile()


app_graph = build_graph()


def render_graph_image(output_path: str = "content_graph.png") -> None:
    """Render the compiled workflow graph to a PNG at the requested path."""
    graph_image = app_graph.get_graph().draw_mermaid_png()
    with open(output_path, "wb") as image_file:
        image_file.write(graph_image)
    logger.info("Saved workflow graph image path=%s", output_path)
