import importlib

import pytest
import dotenv


def test_settings_require_all_credentials_and_load_configured_values(monkeypatch):
    values = {
        "AZURE_OPENAI_ENDPOINT": "https://example.test",
        "AZURE_OPENAI_API_KEY": "test-key",
        "AZURE_OPENAI_API_VERSION": "test-version",
        "AZURE_OPENAI_MODEL": "test-model",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    settings = importlib.import_module("config.settings")
    monkeypatch.setattr(dotenv, "load_dotenv", lambda: None)

    monkeypatch.delenv("AZURE_OPENAI_MODEL")
    with pytest.raises(ValueError, match="Missing Azure OpenAI credentials"):
        importlib.reload(settings)

    for key, value in values.items():
        monkeypatch.setenv(key, value)
    importlib.reload(settings)

    assert settings.AZURE_OPENAI_ENDPOINT == values["AZURE_OPENAI_ENDPOINT"]
    assert settings.AZURE_OPENAI_API_KEY == values["AZURE_OPENAI_API_KEY"]
    assert settings.AZURE_OPENAI_API_VERSION == values["AZURE_OPENAI_API_VERSION"]
    assert settings.AZURE_OPENAI_MODEL == values["AZURE_OPENAI_MODEL"]
