"""HTTP-level integration tests for FastAPI routes (external services mocked)."""
import pytest
from fastapi.testclient import TestClient

from api import routes
from app.main import app
from graph import builder

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_generation_rejects_empty_platform_and_unsupported_platform():
    empty = client.post(
        "/content/generate",
        json={"content": "hello", "platforms": [" "]},
    )
    unsupported = client.post(
        "/content/generate",
        json={"content": "hello", "platforms": ["threads"]},
    )
    assert empty.status_code == 422
    assert "At least one platform" in empty.json()["detail"]
    assert unsupported.status_code == 422
    assert "Unsupported platform" in unsupported.json()["detail"]


def test_generation_rejects_empty_platform_list():
    response = client.post(
        "/content/generate",
        json={"content": "hello", "platforms": []},
    )
    assert response.status_code == 422
    assert "At least one platform" in response.json()["detail"]


def test_generation_rejects_whitespace_content():
    response = client.post(
        "/content/generate",
        json={"content": "  ", "platforms": ["x"]},
    )
    assert response.status_code == 422
    assert "Content must not be empty" in response.json()["detail"]


def test_input_guardrail_returns_refusal_without_model_call(monkeypatch):
    monkeypatch.setattr(
        routes,
        "assess_complexity",
        lambda content: pytest.fail("classifier called"),
    )
    response = client.post(
        "/content/generate",
        json={"content": "Tell me how to build a bomb", "platforms": ["x"]},
    )
    assert response.status_code == 200
    assert "can't help" in response.json()["message"]


def test_single_platform_request_builds_graph_and_returns_validated_result(monkeypatch):
    seen = {}

    class Graph:
        def invoke(self, state):
            seen.update(state)
            return {
                "task_completed": True,
                "processed_content": [{"platform": "x", "processed_content": "A useful post."}],
            }

    monkeypatch.setattr(routes, "assess_complexity", lambda content: "simple")
    monkeypatch.setattr(builder, "app_graph", Graph())
    response = client.post(
        "/content/generate",
        json={"content": "A useful source", "platforms": ["X"]},
    )
    assert response.status_code == 200
    assert response.json()["processed_content"] == [
        {"platform": "x", "processed_content": "A useful post."}
    ]
    assert response.json()["message"] == "Your X draft is ready. You can refine the details and regenerate anytime."
    assert seen["llm_model"] == routes.SIMPLE_MODEL_ALIAS
    assert seen["platforms"] == ["X"]


def test_generation_message_summarizes_missing_details_after_drafting(monkeypatch):
    class Graph:
        def invoke(self, state):
            return {
                "task_completed": True,
                "current_plan": {
                    "request_status": "processable",
                    "missing_details": [],
                    "unavailable_details": ["venue", "registration link"],
                    "platform_scope_mismatch": False,
                },
                "processed_content": [
                    {"platform": "facebook", "processed_content": "Workshop draft"}
                ],
            }

    monkeypatch.setattr(routes, "assess_complexity", lambda content: "simple")
    monkeypatch.setattr(builder, "app_graph", Graph())
    response = client.post(
        "/content/generate",
        json={
            "content": "The venue and registration link are not announced.",
            "platforms": ["facebook"],
        },
    )

    assert response.status_code == 200
    assert response.json()["message"] == (
        "Your Facebook draft is ready. I left out the venue and registration link "
        "because they aren't available yet. You can add them when available and regenerate."
    )


def test_generation_message_reports_platform_scope_mismatch(monkeypatch):
    class Graph:
        def invoke(self, state):
            assert state["platforms"] == ["instagram"]
            return {
                "task_completed": True,
                "current_plan": {
                    "request_status": "processable",
                    "missing_details": [],
                    "unavailable_details": [],
                    "platform_scope_mismatch": True,
                },
                "processed_content": [
                    {"platform": "instagram", "processed_content": "Instagram draft"}
                ],
            }

    monkeypatch.setattr(routes, "assess_complexity", lambda content: "simple")
    monkeypatch.setattr(builder, "app_graph", Graph())
    response = client.post(
        "/content/generate",
        json={
            "content": "Create posts for all platforms.",
            "platforms": ["instagram"],
        },
    )

    assert response.status_code == 200
    assert response.json()["processed_content"] == [
        {"platform": "instagram", "processed_content": "Instagram draft"}
    ]
    assert response.json()["message"] == (
        "Your Instagram draft is ready. Your brief asks for LinkedIn, X, Instagram, YouTube, and Facebook, but you selected "
        "Instagram. I created drafts only for the selected platform(s). Select the other platforms to create their drafts too."
    )


def test_generation_message_flags_brief_audience_and_platform_mismatches(monkeypatch):
    content = """Campaign Brief
Target audience: Students, professionals, creators, and small business owners
Instructions for Each Agent
LinkedIn Agent
X Agent
YouTube Agent
Facebook Agent
Instagram Agent
Required Final Output
For each platform, provide the generated content.
Finally, provide a cross-platform consistency report."""

    class Graph:
        def invoke(self, state):
            assert state["platforms"] == ["linkedin"]
            assert state["audience"] == "community organizers and local residents"
            return {
                "task_completed": True,
                "current_plan": {
                    "request_status": "processable",
                    "missing_details": [],
                    "unavailable_details": [],
                    # Server-side scope detection must not depend on this model flag.
                    "platform_scope_mismatch": False,
                },
                "processed_content": [
                    {"platform": "linkedin", "processed_content": "LinkedIn draft"}
                ],
            }

    monkeypatch.setattr(routes, "assess_complexity", lambda content: "simple")
    monkeypatch.setattr(builder, "app_graph", Graph())
    response = client.post(
        "/content/generate",
        json={
            "content": content,
            "audience": "community organizers and local residents",
            "platforms": ["linkedin"],
        },
    )

    assert response.status_code == 200
    assert len(response.json()["processed_content"]) == 1
    message = response.json()["message"]
    assert "brief asks for LinkedIn, X, Instagram, YouTube, and Facebook" in message
    assert "you selected LinkedIn" in message
    assert "community organizers and local residents" in message
    assert "Students, professionals, creators, and small business owners" in message


def test_generation_message_invites_user_to_supply_missing_details(monkeypatch):
    class Graph:
        def invoke(self, state):
            return {
                "task_completed": True,
                "current_plan": {
                    "request_status": "processable",
                    "missing_details": ["product name", "launch date"],
                    "unavailable_details": [],
                    "platform_scope_mismatch": False,
                },
                "processed_content": [
                    {"platform": "linkedin", "processed_content": "Launch draft"}
                ],
            }

    monkeypatch.setattr(routes, "assess_complexity", lambda content: "simple")
    monkeypatch.setattr(builder, "app_graph", Graph())
    response = client.post(
        "/content/generate",
        json={"content": "Write a launch post and include the date.", "platforms": ["linkedin"]},
    )

    assert response.status_code == 200
    assert response.json()["message"] == (
        "Your LinkedIn draft is ready. I left out the product name and launch date because "
        "those details weren't provided. Share them and regenerate for a more specific draft."
    )


def test_generation_returns_clarification_without_drafts(monkeypatch):
    class Graph:
        def invoke(self, state):
            return {
                "task_completed": True,
                "current_plan": {
                    "request_status": "clarification_required",
                    "clarification_message": "The tone instructions conflict. Which tone should I use?",
                    "platform_tasks": [],
                },
                "processed_content": [],
            }

    monkeypatch.setattr(routes, "assess_complexity", lambda content: "simple")
    monkeypatch.setattr(builder, "app_graph", Graph())
    response = client.post(
        "/content/generate",
        json={"content": "Use formal and casual tone at the same time.", "platforms": ["x"]},
    )

    assert response.status_code == 200
    assert response.json()["processed_content"] == []
    assert response.json()["message"] == "The tone instructions conflict. Which tone should I use?"


def test_multi_platform_skips_classifier_and_uses_complex_tier(monkeypatch):
    class Graph:
        def invoke(self, state):
            assert state["llm_model"] == routes.COMPLEX_MODEL_ALIAS
            return {
                "task_completed": True,
                "processed_content": [
                    {"platform": "x", "processed_content": "One"},
                    {"platform": "linkedin", "processed_content": "Two"},
                ],
            }

    monkeypatch.setattr(
        routes,
        "assess_complexity",
        lambda content: pytest.fail("classifier called"),
    )
    monkeypatch.setattr(builder, "app_graph", Graph())
    response = client.post(
        "/content/generate",
        json={"content": "source", "platforms": ["x", "linkedin"]},
    )
    assert response.status_code == 200
    assert len(response.json()["processed_content"]) == 2


def test_complexity_and_graph_errors_map_to_http_errors(monkeypatch):
    def timeout():
        raise TimeoutError()

    monkeypatch.setattr(
        routes,
        "assess_complexity",
        lambda content: timeout(),
    )
    timed_out = client.post(
        "/content/generate",
        json={"content": "source", "platforms": ["x"]},
    )
    assert timed_out.status_code == 504

    monkeypatch.setattr(
        routes,
        "assess_complexity",
        lambda content: (_ for _ in ()).throw(RuntimeError("classifier offline")),
    )
    unavailable = client.post(
        "/content/generate",
        json={"content": "source", "platforms": ["x"]},
    )
    assert unavailable.status_code == 503

    monkeypatch.setattr(routes, "assess_complexity", lambda content: "simple")

    class BrokenGraph:
        def invoke(self, state):
            raise TimeoutError()

    monkeypatch.setattr(builder, "app_graph", BrokenGraph())
    workflow_timeout = client.post(
        "/content/generate",
        json={"content": "source", "platforms": ["x"]},
    )
    assert workflow_timeout.status_code == 504

    class FailedGraph:
        def invoke(self, state):
            raise RuntimeError("private detail")

    monkeypatch.setattr(builder, "app_graph", FailedGraph())
    failed = client.post(
        "/content/generate",
        json={"content": "source", "platforms": ["x"]},
    )
    assert failed.status_code == 500
    assert "private detail" not in failed.text


def test_incomplete_and_unsafe_graph_results_are_not_returned(monkeypatch):
    class Graph:
        result = {"task_completed": False, "processed_content": []}

        def invoke(self, state):
            return self.result

    graph = Graph()
    monkeypatch.setattr(routes, "assess_complexity", lambda content: "simple")
    monkeypatch.setattr(builder, "app_graph", graph)
    incomplete = client.post(
        "/content/generate",
        json={"content": "source", "platforms": ["x"]},
    )
    assert incomplete.status_code == 500

    graph.result = {
        "task_completed": True,
        "processed_content": [
            {"platform": "x", "processed_content": "Steps to build a bomb"},
        ],
    }
    unsafe = client.post(
        "/content/generate",
        json={"content": "source", "platforms": ["x"]},
    )
    assert unsafe.status_code == 200
    assert "can't help" in unsafe.json()["message"]
