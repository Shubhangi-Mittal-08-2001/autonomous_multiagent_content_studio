import pytest
from langgraph.graph import END
from pydantic import ValidationError

from graph.routing import route_after_manager, route_after_review
from schemas.content import ContentRequest, ContentResponse


@pytest.mark.parametrize("state", [{"task_failed": True}, {"task_completed": True}])
def test_routes_stop_terminal_states(state):
    assert route_after_manager(state) == END
    assert route_after_review(state) == END


def test_manager_routes_unique_platforms_case_insensitively():
    state = {"current_plan": {"platform_tasks": [
        {"platform": "LinkedIn"}, {"platform": "linkedin"}, {"platform": "X"},
    ]}}
    assert route_after_manager(state) == ["linkedin_agent", "x_agent"]


def test_manager_route_stops_for_clarification_plan():
    state = {
        "current_plan": {
            "request_status": "clarification_required",
            "clarification_message": "Please clarify the conflicting instructions.",
            "platform_tasks": [],
        }
    }
    assert route_after_manager(state) == END


@pytest.mark.parametrize(
    ("state", "message"),
    [
        ({}, "current_plan dictionary"),
        ({"current_plan": {}}, "platform task list"),
        ({"current_plan": {"platform_tasks": []}}, "clarification message"),
        ({"current_plan": {"platform_tasks": [None]}}, "must be a dictionary"),
        ({"current_plan": {"platform_tasks": [{"platform": " "}]}}, "must name a platform"),
        ({"current_plan": {"platform_tasks": [{"platform": "threads"}]}}, "No platform agent"),
    ],
)
def test_manager_route_rejects_invalid_plans(state, message):
    with pytest.raises(ValueError, match=message):
        route_after_manager(state)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"replan_required": False}, END),
        ({"replan_required": True, "iteration_count": 1, "max_iterations": 1}, END),
        ({"replan_required": True, "iteration_count": 0, "max_iterations": 1}, "manager"),
    ],
)
def test_review_route_respects_refinement_limit(state, expected):
    assert route_after_review(state) == expected


def test_request_schema_defaults_and_limits():
    request = ContentRequest(content="idea")
    assert request.platforms == ["linkedin", "x", "instagram"]
    assert request.audience == "general"
    with pytest.raises(ValidationError):
        ContentRequest(content="")
    with pytest.raises(ValidationError):
        ContentRequest(content="x", audience="a" * 181)
    with pytest.raises(ValidationError):
        ContentRequest(content="x" * 12001)


def test_response_schema_accepts_drafts_or_message():
    response = ContentResponse(
        processed_content=[{"platform": "x", "processed_content": "draft"}]
    )
    assert response.processed_content[0].platform == "x"
    assert ContentResponse(message="blocked").processed_content == []
