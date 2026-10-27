from types import SimpleNamespace

import pytest

from agents.common_implementation import (
    invoke_text,
    latest_draft,
    parse_json_object,
    platform_mapping,
    platform_task,
)


@pytest.mark.parametrize(
    "response",
    [
        '{"title":"hello"}',
        'Here is the result: {"title":"hello","meta":{"n":1}} thanks',
        '```json\n{"title":"hello"}\n```',
        SimpleNamespace(
            content=[{"type": "text", "text": '{"title":'}, {"text": '"hello"}'}]
        ),
    ],
)
def test_parse_json_object_extracts_balanced_json(response):
    parsed = parse_json_object(response, description="test", required_key="title")
    assert parsed == {"title": "hello"} or parsed.get("meta") == {"n": 1}


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ("no json here", "did not contain a JSON object with 'title'"),
        ('{"other":1}', "did not contain a JSON object with 'title'"),
        ('prefix {"title": 1', "incomplete JSON object"),
        (123, "must contain a JSON object"),
    ],
)
def test_parse_json_object_rejects_invalid_content(response, message):
    with pytest.raises(ValueError, match=message):
        parse_json_object(response, description="test", required_key="title")


def test_parse_json_object_can_skip_invalid_candidate_for_later_valid_object():
    assert parse_json_object('{bad} then {"ok": true}', description="test") == {"ok": True}


def test_invoke_text_handles_text_blocks_and_rejects_empty_output():
    class Model:
        def invoke(self, prompt):
            assert prompt == "prompt"
            return type("Response", (), {"content": [{"text": " hello "}]})()

    assert invoke_text("prompt", Model()) == "hello"
    with pytest.raises(ValueError, match="non-empty text"):
        invoke_text("prompt", type("Model", (), {"invoke": lambda self, prompt: "  "})())


def test_invoke_text_propagates_model_errors():
    class Model:
        def invoke(self, prompt):
            raise RuntimeError("offline")

    with pytest.raises(RuntimeError, match="offline"):
        invoke_text("prompt", Model())


def test_platform_helpers_normalize_and_find_saved_data():
    assert platform_mapping({" LinkedIn ": 1, "X": 2}) == {"linkedin": 1, "x": 2}
    assert platform_mapping(["no"]) == {}
    state = {
        "current_plan": {"platform_tasks": [{"platform": "LinkedIn", "task": "write"}]},
        "latest_results": {" LinkedIn ": {"content": "draft"}},
    }
    assert platform_task(state, "linkedin")["task"] == "write"
    assert latest_draft(state, "linkedin") == "draft"
    assert latest_draft({"latest_results": {"x": "raw"}}, "x") == "raw"
    assert latest_draft({"latest_results": {"x": {"draft": "fallback"}}}, "x") == "fallback"


def test_platform_task_falls_back_to_node_plans_and_errors_when_missing():
    assert platform_task({"node_plans": [{"platform": "x"}]}, "x")["platform"] == "x"
    with pytest.raises(ValueError, match="does not include"):
        platform_task({}, "x")
