import pytest

from agents import (
    common_implementation,
    facebook_agent,
    instagram_agent,
    linkedin_agent,
    x_agent,
    youtube_agent,
)


def _state(**overrides):
    state = {
        "content": "Source text",
        "platforms": ["x"],
        "current_plan": {
            "platform_tasks": [
                {
                    "platform": "X",
                    "task": "Create an accurate post",
                    "review_feedback": "Use plain language",
                }
            ]
        },
        "llm_model": "test-model",
        "iteration_count": 2,
        "review_feedback": {"x": "State feedback"},
        "latest_results": {"x": {"content": "Previous draft"}},
    }
    state.update(overrides)
    return state


class _Prompt:
    def __init__(self):
        self.values = {}

    def compile(self, **values):
        self.values = values
        return "compiled prompt"


class _Client:
    def __init__(self):
        self.prompt = _Prompt()

    def get_prompt(self, *args, **kwargs):
        return self.prompt


def test_get_content_prompt_fetches_and_compiles_prompt(monkeypatch):
    client = _Client()
    monkeypatch.setattr(common_implementation, "get_client", lambda: client)

    result = common_implementation.get_content_prompt(
        "x", "guidance", "audience", "source", "task",
        is_refinement=True, feedback="revise", existing_draft="draft",
    )

    assert result == "compiled prompt"
    assert client.prompt.values == {
        "platform": "x",
        "platform_guidance": "guidance",
        "audience": "audience",
        "source": "source",
        "task": "task",
        "is_refinement": "True",
        "feedback": "revise",
        "existing_draft": "draft",
    }


def test_get_content_prompt_supplies_initial_draft_defaults(monkeypatch):
    client = _Client()
    monkeypatch.setattr(common_implementation, "get_client", lambda: client)

    common_implementation.get_content_prompt("x", "g", "a", "s", "t")

    assert client.prompt.values["is_refinement"] == "False"
    assert client.prompt.values["feedback"] == "None; create the initial draft."
    assert client.prompt.values["existing_draft"] == "None; create the initial draft."


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"content": [{"text": '{"ok": true}'}]}, {"ok": True}),
        (
            '{"outer":{"text":"} { \\"quoted\\""},"ok":true}',
            {"outer": {"text": '} { "quoted"'}, "ok": True},
        ),
    ],
)
def test_parse_json_object_handles_object_content_and_nested_braces(response, expected):
    class Response:
        def __init__(self, content):
            self.content = content

    if isinstance(response, dict):
        response = Response(response["content"])
    assert common_implementation.parse_json_object(response, description="test") == expected


def test_parse_json_object_reports_incomplete_or_malformed_candidates():
    with pytest.raises(ValueError, match="incomplete JSON object"):
        common_implementation.parse_json_object("prefix {not closed", description="test")
    with pytest.raises(ValueError, match="valid JSON object"):
        common_implementation.parse_json_object("{broken} trailing", description="test")
    with pytest.raises(ValueError, match="with 'required'"):
        common_implementation.parse_json_object(
            '{"other": 1}',
            description="test",
            required_key="required",
        )


def test_invoke_text_uses_configured_default_model(monkeypatch):
    calls = []

    def invoke(model, prompt, **kwargs):
        calls.append((model, prompt, kwargs))
        return " answer "

    monkeypatch.setattr("config.llm.invoke_llm", invoke)
    result = common_implementation.invoke_text(
        "prompt", model_name="chosen", json_mode=True, max_completion_tokens=20
    )

    assert result == "answer"
    assert calls == [
        (
            "chosen",
            "prompt",
            {"json_mode": True, "max_completion_tokens": 20},
        )
    ]


def test_invoke_text_ignores_non_text_content_blocks():
    class Model:
        def invoke(self, _prompt):
            return type(
                "Response",
                (),
                {"content": [{"text": "hello"}, "ignored", {"text": 4}]},
            )()

    assert common_implementation.invoke_text("prompt", Model()) == "hello"


def test_platform_task_falls_back_when_current_plan_has_no_tasks():
    state = {
        "current_plan": {"platform_tasks": []},
        "node_plans": [{"platform": " X ", "task": "fallback"}],
    }
    assert common_implementation.platform_task(state, "x")["task"] == "fallback"
    assert common_implementation.platform_mapping(None) == {}
    assert common_implementation.latest_draft(
        {"latest_results": {" X ": {"processed_content": "", "content": "draft"}}},
        "x",
    ) == "draft"


def test_generate_platform_draft_builds_expected_state_update(monkeypatch):
    client = _Client()
    prompt_values = {}
    monkeypatch.setattr(common_implementation, "get_client", lambda: client)

    def compile_prompt(**values):
        prompt_values.update(values)
        return "compiled"

    client.prompt.compile = compile_prompt
    calls = []
    monkeypatch.setattr(
        common_implementation,
        "invoke_text",
        lambda *args, **kwargs: calls.append((args, kwargs)) or "final draft",
    )

    result = common_implementation.generate_platform_draft(
        _state(replan_required=True),
        "x",
        "X guidance",
    )

    assert result["latest_results"]["x"] == {
        "platform": "x",
        "processed_content": "final draft",
        "iteration": 2,
        "is_refinement": True,
    }
    assert result["execution_history"] == [result["latest_results"]["x"]]
    assert result["current_step"] == "x_drafted"
    assert prompt_values["feedback"] == "Use plain language"
    assert prompt_values["existing_draft"] == "Previous draft"
    assert calls[0][1]["max_completion_tokens"] == 700


def test_generate_platform_draft_uses_state_feedback_and_default_platform_budget(monkeypatch):
    client = _Client()
    monkeypatch.setattr(common_implementation, "get_client", lambda: client)
    calls = []
    monkeypatch.setattr(
        common_implementation,
        "invoke_text",
        lambda *args, **kwargs: calls.append(kwargs) or "draft",
    )
    state = _state(
        platforms=["threads"],
        current_plan={"platform_tasks": [{"platform": "threads", "task": "write"}]},
        review_feedback={"THREADS": "state note"},
        latest_results={},
        iteration_count=0,
    )

    common_implementation.generate_platform_draft(state, "threads", "guidance")

    assert client.prompt.values["feedback"] == "state note"
    assert calls[0]["max_completion_tokens"] == 1800


@pytest.mark.parametrize(
    "agent_module",
    [facebook_agent, instagram_agent, linkedin_agent, x_agent, youtube_agent],
)
def test_platform_agent_delegates_to_shared_generator(monkeypatch, agent_module):
    calls = []
    monkeypatch.setattr(
        agent_module,
        "generate_platform_draft",
        lambda *args: calls.append(args) or {"latest_results": {"x": "draft"}},
    )

    result = getattr(agent_module, f"{agent_module.__name__.split('.')[-1]}")(
        _state(), llm="injected-model"
    )

    assert result == {"latest_results": {"x": "draft"}}
    assert calls[0][0] == _state()
    assert calls[0][1] == agent_module.__name__.split(".")[-1].removesuffix("_agent")
    assert calls[0][3] == "injected-model"


@pytest.mark.parametrize(
    "agent_module",
    [facebook_agent, instagram_agent, linkedin_agent, x_agent, youtube_agent],
)
def test_platform_agent_propagates_generation_failures(monkeypatch, agent_module):
    def fail(*args):
        raise RuntimeError("generation failed")

    monkeypatch.setattr(agent_module, "generate_platform_draft", fail)
    agent_function = getattr(agent_module, agent_module.__name__.split(".")[-1])

    with pytest.raises(RuntimeError, match="generation failed"):
        agent_function(_state())


def test_generate_platform_draft_rejects_empty_source():
    with pytest.raises(ValueError, match="non-empty source"):
        common_implementation.generate_platform_draft(
            _state(content=" "), "x", "guidance"
        )
