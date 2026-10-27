import json

import pytest

from agents import manager
from config.llm import COMPLEX_MODEL_ALIAS, SIMPLE_MODEL_ALIAS


def _state(**overrides):
    state = {
        "content": "A source article",
        "platforms": ["x"],
        "audience": "readers",
        "llm_model": SIMPLE_MODEL_ALIAS,
        "iteration_count": 0,
        "max_iterations": 1,
    }
    state.update(overrides)
    return state


def _task(platform="x"):
    return {
        "platform": platform,
        "task": "Write a post",
        "tone": "friendly",
        "format_requirements": "short",
        "key_points": ["source fact"],
    }


def _plan(platforms, **overrides):
    plan = {
        "request_status": "processable",
        "clarification_message": "",
        "missing_details": [],
        "unavailable_details": [],
        "platform_scope_mismatch": False,
        "platform_tasks": [_task(platform) for platform in platforms],
        "quality_requirements": [],
    }
    plan.update(overrides)
    return plan


def test_decode_plan_normalizes_expected_tasks_and_ignores_extras():
    tasks = [
        "not a task",
        {},
        {"platform": 12},
        _task("X: short post"),
        _task("x duplicate"),
        _task("threads"),
    ]
    result = manager._decode_plan(
        json.dumps(
            _plan(
                ["x"],
                platform_tasks=tasks,
                missing_details=["launch date"],
                unavailable_details=["registration link"],
                platform_scope_mismatch=True,
                quality_requirements=[" "],
            )
        ),
        ["x"],
    )

    assert result["platform_tasks"] == [_task("x")]
    assert result["quality_requirements"] == []
    assert result["missing_details"] == ["launch date"]
    assert result["unavailable_details"] == ["registration link"]
    assert result["platform_scope_mismatch"] is True
    assert manager._platform_lookup(None) == {}
    assert manager._platform_lookup({12: " value "}) == {"12": " value "}


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (json.dumps(_plan([], platform_tasks=[])), "processable Manager plan must include platform tasks"),
        (json.dumps(_plan(["linkedin"])), "omitted requested"),
        (json.dumps(_plan(["x"], platform_tasks=[{"platform": "x", "task": "draft"}])), "missing required fields"),
        (json.dumps(_plan([], platform_tasks=None)), "platform_tasks list"),
        (json.dumps({"platform_tasks": []}), "request_status"),
    ],
)
def test_decode_plan_rejects_missing_or_malformed_tasks(response, expected):
    with pytest.raises(ValueError, match=expected):
        manager._decode_plan(response, ["x"])


def test_manager_node_validates_content_and_platforms():
    with pytest.raises(ValueError, match="non-empty source"):
        manager.manager_node(_state(content="  "))
    with pytest.raises(ValueError, match="at least one requested platform"):
        manager.manager_node(_state(platforms=[]))
    with pytest.raises(ValueError, match="at least one requested platform"):
        manager.manager_node(_state(platforms=[" ", None]))


def test_simple_tier_still_uses_manager_planning_for_request_analysis():
    result = manager.manager_node(_state())

    assert result["current_step"] == "manager_planning"
    assert result["current_plan"]["is_refinement"] is False
    assert result["current_plan"]["audience"] == "readers"
    assert result["node_plans"] == result["current_plan"]["platform_tasks"]
    assert result["node_plans"][0]["platform"] == "x"
    assert result["current_plan"]["request_status"] == "processable"


def test_simple_refinement_targets_only_unapproved_platforms():
    result = manager.manager_node(
        _state(
            platforms=["linkedin", "x"],
            replan_required=True,
            platform_status={"LinkedIn": "needs_refinement", "x": "approved"},
            review_feedback={"LINKEDIN": "Add a source citation"},
            latest_results={"linkedin": {"processed_content": "previous draft"}},
            replan_count=2,
        )
    )
    task = result["node_plans"][0]

    assert [entry["platform"] for entry in result["node_plans"]] == ["linkedin"]
    assert task["review_feedback"] == "Add a source citation"
    assert task["existing_draft"] == {"processed_content": "previous draft"}
    assert result["current_plan"]["is_refinement"] is True
    assert result["replan_count"] == 3


def test_refinement_requires_a_platform_with_review_work():
    with pytest.raises(ValueError, match="no unapproved platform"):
        manager.manager_node(
            _state(
                replan_required=True,
                platform_status={"x": "approved"},
                review_feedback={},
            )
        )


def test_refinement_limit_returns_latest_usable_drafts_without_model_call(monkeypatch):
    monkeypatch.setattr(
        manager,
        "invoke_llm",
        lambda *args, **kwargs: pytest.fail("planner should not run at the limit"),
    )
    result = manager.manager_node(
        _state(
            platforms=["x", "linkedin", "facebook"],
            replan_required=True,
            iteration_count=1,
            max_iterations=1,
            latest_results={
                "X": {"content": "latest x", "platform": "X"},
                "linkedin": "latest linkedin",
                "facebook": {"draft": "  "},
            },
        )
    )

    assert result["task_completed"] is True
    assert result["task_failed"] is False
    assert result["replan_required"] is False
    assert result["processed_content"] == [
        {"platform": "X", "processed_content": "latest x"},
        {"platform": "linkedin", "processed_content": "latest linkedin"},
    ]


class _Prompt:
    def __init__(self):
        self.values = {}

    def compile(self, **values):
        self.values = values
        return "manager prompt"


class _Client:
    def __init__(self):
        self.prompt = _Prompt()

    def get_prompt(self, *args, **kwargs):
        return self.prompt


@pytest.fixture(autouse=True)
def stub_manager_llm(monkeypatch):
    client = _Client()
    monkeypatch.setattr(manager, "get_client", lambda: client)

    def invoke(model, prompt, **kwargs):
        task_context = json.loads(client.prompt.values["platform_tasks"])
        platforms = [item["platform"] for item in task_context]
        return json.dumps(_plan(platforms))

    monkeypatch.setattr(manager, "invoke_llm", invoke)


def test_complex_plan_repairs_invalid_model_response_once(monkeypatch):
    client = _Client()
    calls = []
    replies = [
        "not json",
        json.dumps(_plan(["X"], quality_requirements=["accurate"])),
    ]
    monkeypatch.setattr(manager, "get_client", lambda: client)
    def invoke(model, prompt, **kwargs):
        calls.append((model, prompt, kwargs))
        return replies.pop(0)

    monkeypatch.setattr(manager, "invoke_llm", invoke)

    result = manager.manager_node(_state(llm_model=COMPLEX_MODEL_ALIAS))

    assert result["current_plan"]["platform_tasks"] == [_task("x")]
    assert len(calls) == 2
    assert calls[0][0] == COMPLEX_MODEL_ALIAS
    assert calls[0][2] == {"json_mode": True, "max_completion_tokens": 1800}
    assert "Correction:" in calls[1][1]
    assert calls[1][2]["max_completion_tokens"] == 3600
    assert client.prompt.values["content"] == "A source article"


def test_complex_plan_propagates_model_service_errors(monkeypatch):
    monkeypatch.setattr(manager, "get_client", lambda: _Client())

    def fail(*args, **kwargs):
        raise RuntimeError("model offline")

    monkeypatch.setattr(manager, "invoke_llm", fail)
    with pytest.raises(RuntimeError, match="model offline"):
        manager.manager_node(_state(llm_model=COMPLEX_MODEL_ALIAS))


def test_complex_refinement_passes_only_requested_platform_context(monkeypatch):
    client = _Client()
    calls = []
    monkeypatch.setattr(manager, "get_client", lambda: client)
    def invoke(model, prompt, **kwargs):
        calls.append(prompt)
        return json.dumps(_plan(["X"]))

    monkeypatch.setattr(manager, "invoke_llm", invoke)
    result = manager.manager_node(
        _state(
            llm_model=COMPLEX_MODEL_ALIAS,
            replan_required=True,
            platform_status={"x": "needs_refinement"},
            review_feedback={"x": "Be more specific"},
            latest_results={"x": "old draft"},
        )
    )
    context = json.loads(client.prompt.values["platform_tasks"])

    assert result["current_plan"]["is_refinement"] is True
    assert context[0]["review_feedback"] == "Be more specific"
    assert context[0]["existing_draft"] == "old draft"
    assert json.loads(client.prompt.values["selected_platforms"]) == ["x"]
    assert result["current_plan"]["platform_tasks"][0]["review_feedback"] == "Be more specific"
    assert calls


@pytest.mark.parametrize(
    ("decoded_plan", "message"),
    [
        ({"platform_tasks": "bad"}, "platform_tasks list"),
        (_plan(["x"], platform_tasks=[{"platform": "x", "task": "draft"}]), "missing task fields"),
    ],
)
def test_manager_revalidates_decoded_plan(monkeypatch, decoded_plan, message):
    monkeypatch.setattr(manager, "get_client", lambda: _Client())
    monkeypatch.setattr(manager, "invoke_llm", lambda *args, **kwargs: "response")
    monkeypatch.setattr(manager, "_decode_plan", lambda *args: decoded_plan)

    with pytest.raises(ValueError, match=message):
        manager.manager_node(_state(llm_model=COMPLEX_MODEL_ALIAS))


def test_manager_node_stops_cleanly_for_clarification(monkeypatch):
    client = _Client()
    monkeypatch.setattr(manager, "get_client", lambda: client)
    monkeypatch.setattr(
        manager,
        "invoke_llm",
        lambda *args, **kwargs: json.dumps(
            {
                "request_status": "clarification_required",
                "clarification_message": "The instructions conflict. Which tone should I use?",
                "missing_details": [],
                "unavailable_details": [],
                "platform_scope_mismatch": False,
                "platform_tasks": [],
            }
        ),
    )

    result = manager.manager_node(_state(llm_model=COMPLEX_MODEL_ALIAS))

    assert result["task_completed"] is True
    assert result["processed_content"] == []
    assert result["current_plan"]["request_status"] == "clarification_required"
    assert result["manager_note"] == "The instructions conflict. Which tone should I use?"
