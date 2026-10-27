import pytest

from config import complexity


class Prompt:
    def compile(self, **values):
        return "classify: " + values["content"]


class Client:
    def get_prompt(self, name, **kwargs):
        assert name == "complexity_prompt"
        return Prompt()


def test_assess_complexity_uses_simple_tier_and_normalizes_label(monkeypatch):
    calls = []
    monkeypatch.setattr(complexity, "get_client", lambda: Client())
    monkeypatch.setattr(
        complexity,
        "invoke_llm",
        lambda model, prompt, **kw: calls.append((model, prompt, kw))
        or " SIMPLE\n",
    )
    assert complexity.assess_complexity("  a topic  ") == "simple"
    assert calls[0][0] == complexity.SIMPLE_MODEL_ALIAS
    assert calls[0][1] == "classify: a topic"
    assert calls[0][2]["max_completion_tokens"] == 8


def test_assess_complexity_falls_back_to_complex_tier(monkeypatch):
    calls = []
    monkeypatch.setattr(complexity, "get_client", lambda: Client())
    def classify(model, prompt, **kwargs):
        calls.append(model)
        if len(calls) == 1:
            raise RuntimeError("simple unavailable")
        return "COMPLEX"
    monkeypatch.setattr(complexity, "invoke_llm", classify)
    assert complexity.assess_complexity("topic") == "complex"
    assert calls == [complexity.SIMPLE_MODEL_ALIAS, complexity.COMPLEX_MODEL_ALIAS]


def test_assess_complexity_rejects_invalid_fallback_and_empty_query(monkeypatch):
    monkeypatch.setattr(complexity, "get_client", lambda: Client())
    monkeypatch.setattr(complexity, "invoke_llm", lambda *args, **kwargs: "unknown")
    with pytest.raises(ValueError, match="exactly"):
        complexity.assess_complexity("topic")
    with pytest.raises(ValueError, match="non-empty"):
        complexity.assess_complexity("  ")
