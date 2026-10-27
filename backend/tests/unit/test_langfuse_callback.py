import sys
from types import ModuleType
from unittest.mock import patch

import pytest

_langfuse_langchain = ModuleType("langfuse.langchain")
_langfuse_langchain.CallbackHandler = object
with patch.dict(sys.modules, {"langfuse.langchain": _langfuse_langchain}):
    from callbacks import langfuse_callback as callbacks


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("true", True), ("YES", True), ("on", True), ("0", False), ("false", False)],
)
def test_callback_langfuse_enabled_values(monkeypatch, value, expected):
    monkeypatch.setenv("LANGFUSE_ENABLED", value)
    assert callbacks._is_langfuse_enabled() is expected


def test_callback_manager_is_disabled_without_enabled_flag_or_credentials(monkeypatch):
    manager = callbacks.LangfuseCallbackManager(public_key="public", secret_key="secret")
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    assert manager.get_callback_handler() is None

    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert callbacks.LangfuseCallbackManager().get_callback_handler() is None


def test_callback_handler_uses_less_specific_constructor_when_needed(monkeypatch):
    class Client:
        def auth_check(self):
            raise RuntimeError("auth unavailable")

    class Handler:
        def __init__(self, **kwargs):
            if "session_id" in kwargs:
                raise TypeError("old SDK signature")
            self.client = Client()
            self.kwargs = kwargs

    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setattr(callbacks, "Langfuse", lambda **kwargs: Client())
    monkeypatch.setattr(callbacks, "CallbackHandler", Handler)
    manager = callbacks.LangfuseCallbackManager(
        public_key="public",
        secret_key="secret",
        host="https://langfuse.test",
        session_id="default-session",
        user_id="default-user",
    )

    handler = manager.get_callback_handler(trace_name="trace")

    assert handler.kwargs == {
        "public_key": "public",
        "secret_key": "secret",
        "host": "https://langfuse.test",
    }
    assert handler._explicit_langfuse_client.__class__ is Client
    assert handler._langfuse_client is handler.client
    assert handler.kwargs["public_key"] == "public"


def test_callback_handler_uses_call_overrides_and_sets_environment(monkeypatch):
    captured = {}

    class Handler:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setattr(callbacks, "Langfuse", lambda **kwargs: object())
    monkeypatch.setattr(callbacks, "CallbackHandler", Handler)
    manager = callbacks.LangfuseCallbackManager(
        public_key="public",
        secret_key="secret",
        host="https://host",
        session_id="default-session",
        user_id="default-user",
    )

    assert manager.get_callback_handler(
        session_id="override-session",
        user_id="override-user",
        trace_name="trace",
    ) is not None
    assert captured == {
        "public_key": "public",
        "secret_key": "secret",
        "host": "https://host",
        "session_id": "override-session",
        "user_id": "override-user",
        "trace_name": "trace",
    }
    assert __import__("os").environ["LANGFUSE_BASE_URL"] == "https://host"


def test_callback_handler_returns_none_if_every_constructor_fails(monkeypatch):
    class Handler:
        def __init__(self, **kwargs):
            raise RuntimeError("constructor unavailable")

    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setattr(callbacks, "Langfuse", lambda **kwargs: object())
    monkeypatch.setattr(callbacks, "CallbackHandler", Handler)
    manager = callbacks.LangfuseCallbackManager(public_key="public", secret_key="secret")

    assert manager.get_callback_handler() is None


def test_callback_handler_keeps_working_when_client_initialization_fails(monkeypatch):
    class Handler:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def fail_client(**kwargs):
        raise RuntimeError("Langfuse client unavailable")

    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setattr(callbacks, "Langfuse", fail_client)
    monkeypatch.setattr(callbacks, "CallbackHandler", Handler)
    manager = callbacks.LangfuseCallbackManager(public_key="public", secret_key="secret")

    handler = manager.get_callback_handler()

    assert handler.kwargs["public_key"] == "public"
    assert not hasattr(handler, "_explicit_langfuse_client")


def test_callback_manager_flush_is_a_noop_and_global_manager_is_cached(monkeypatch):
    monkeypatch.setattr(callbacks, "_langfuse_manager", None)
    first = callbacks.get_langfuse_manager()
    second = callbacks.get_langfuse_manager()

    assert first is second
    assert first.flush() is None
