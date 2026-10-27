import builtins
import importlib
from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError

from config import langfuse_client, llm
import observability
from observability import flush_langfuse, observe


def _response(text="answer", reason="stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=reason,
                message=SimpleNamespace(content=text),
            )
        ]
    )


class _Completions:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        response = self.replies.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _client(completions):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
    )


def test_invoke_llm_builds_simple_tier_json_request(monkeypatch):
    completions = _Completions([_response()])
    monkeypatch.setattr(llm, "client", _client(completions))

    assert llm.invoke_llm(
        llm.SIMPLE_MODEL_ALIAS,
        "prompt",
        json_mode=True,
        max_completion_tokens=12,
    ) == "answer"
    assert completions.requests == [
        {
            "model": llm.SIMPLE_MODEL_ALIAS,
            "messages": [{"role": "user", "content": "prompt"}],
            "response_format": {"type": "json_object"},
            "max_tokens": 12,
        }
    ]


def test_invoke_llm_uses_complex_tier_budget_and_returns_empty_content(monkeypatch):
    completions = _Completions([_response(text=None)])
    monkeypatch.setattr(llm, "client", _client(completions))

    assert llm.invoke_llm("another-tier", "prompt", max_completion_tokens=3) == ""
    assert completions.requests[0]["max_completion_tokens"] == 3
    assert "response_format" not in completions.requests[0]


@pytest.mark.parametrize("value", [0, -1])
def test_invoke_llm_rejects_non_positive_budget_before_request(monkeypatch, value):
    completions = _Completions([])
    monkeypatch.setattr(llm, "client", _client(completions))

    with pytest.raises(ValueError, match="positive integer"):
        llm.invoke_llm("model", "prompt", max_completion_tokens=value)
    assert not completions.requests


def test_invoke_llm_retries_truncated_responses_with_doubling_budget(monkeypatch):
    completions = _Completions(
        [_response("partial", "length"), _response("complete", "stop")]
    )
    monkeypatch.setattr(llm, "client", _client(completions))

    assert llm.invoke_llm("model", "prompt", max_completion_tokens=20) == "complete"
    assert [request["max_completion_tokens"] for request in completions.requests] == [20, 40]


def test_invoke_llm_caps_truncation_retries_at_8192(monkeypatch):
    completions = _Completions([_response("partial", "length"), _response("partial", "length")])
    monkeypatch.setattr(llm, "client", _client(completions))

    assert llm.invoke_llm("model", "prompt", max_completion_tokens=7000) == "partial"
    assert [request["max_completion_tokens"] for request in completions.requests] == [
        7000,
        8192,
    ]


def test_invoke_llm_converts_initial_timeout(monkeypatch):
    completions = _Completions(
        [APITimeoutError(request=httpx.Request("POST", "http://localhost"))]
    )
    monkeypatch.setattr(llm, "client", _client(completions))

    with pytest.raises(TimeoutError, match="timed out"):
        llm.invoke_llm("model", "prompt")


def test_invoke_llm_converts_retry_timeout(monkeypatch):
    completions = _Completions(
        [
            _response("partial", "length"),
            APITimeoutError(request=httpx.Request("POST", "http://localhost")),
        ]
    )
    monkeypatch.setattr(llm, "client", _client(completions))

    with pytest.raises(TimeoutError, match="timed out"):
        llm.invoke_llm("model", "prompt", max_completion_tokens=10)


def test_invoke_llm_propagates_non_timeout_client_errors(monkeypatch):
    completions = _Completions([RuntimeError("offline")])
    monkeypatch.setattr(llm, "client", _client(completions))

    with pytest.raises(RuntimeError, match="offline"):
        llm.invoke_llm("model", "prompt")


def test_llm_rejects_non_positive_configured_timeout_and_recovers(monkeypatch):
    monkeypatch.setenv("LLM_CALL_TIMEOUT_SECONDS", "0")
    with pytest.raises(ValueError, match="greater than zero"):
        importlib.reload(llm)

    monkeypatch.setenv("LLM_CALL_TIMEOUT_SECONDS", "60")
    importlib.reload(llm)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", True),
        (" true ", True),
        ("YES", True),
        ("On", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("", False),
    ],
)
def test_langfuse_enabled_env_values(monkeypatch, value, expected):
    monkeypatch.setenv("LANGFUSE_ENABLED", value)
    assert observability._is_langfuse_enabled() is expected


def test_observe_is_direct_noop_decorator_when_disabled(monkeypatch):
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")

    def target():
        return "ok"

    assert observe(target) is target
    assert observe(name="test")(target) is target
    assert target() == "ok"


def test_observe_delegates_when_enabled(monkeypatch):
    calls = []

    def decorator(*args, **kwargs):
        calls.append((args, kwargs))
        return lambda function: ("wrapped", function)

    monkeypatch.setattr(observability, "_langfuse_observe", decorator)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    def target():
        return None

    assert observe(name="span")(target) == ("wrapped", target)
    assert calls == [((), {"name": "span"})]


def test_observability_client_accessor_and_flush(monkeypatch):
    class Client:
        def __init__(self):
            self.flush_count = 0

        def flush(self):
            self.flush_count += 1

    client = Client()
    monkeypatch.setattr(observability, "_langfuse_get_client", lambda: client)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    assert observability.get_client() is client
    flush_langfuse()
    assert client.flush_count == 1

    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    flush_langfuse()
    assert client.flush_count == 1


def test_flush_langfuse_does_not_raise_when_client_fails(monkeypatch):
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")

    def fail():
        raise RuntimeError("client failure")

    monkeypatch.setattr(observability, "get_client", fail)
    flush_langfuse()


def test_observability_reports_missing_langfuse_dependency(monkeypatch):
    original_import = builtins.__import__

    def fail_langfuse_import(name, *args, **kwargs):
        if name == "langfuse":
            raise ImportError("simulated missing package")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_langfuse_import)
    with pytest.raises(ImportError, match="requires the 'langfuse' package"):
        importlib.reload(observability)
    monkeypatch.undo()
    importlib.reload(observability)


def test_langfuse_client_requires_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="must be configured"):
        langfuse_client.create_langfuse_client()


def test_langfuse_client_passes_host_aliases(monkeypatch):
    calls = []
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret")
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.setenv("LANGFUSE_HOST", "https://example.test")
    monkeypatch.setattr(
        langfuse_client,
        "Langfuse",
        lambda **kwargs: calls.append(kwargs) or "client",
    )

    assert langfuse_client.create_langfuse_client() == "client"
    assert calls == [
        {
            "public_key": "public",
            "secret_key": "secret",
            "host": "https://example.test",
        }
    ]
