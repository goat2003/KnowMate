import os
from unittest.mock import patch

import pytest

from app.config import LLMSettings, McpServerSettings, Settings, validate_production_settings
from app.tools.llm_tool import LLMTool, build_llm_client


def valid_settings():
    return Settings(environment="production", api_token="t" * 32, mock_llm=False, mock_mcp=False,
                    llm=LLMSettings(provider="openai"),
                    mcp_servers={"embedding-mcp": McpServerSettings(transport="streamable_http")})


def test_production_requires_key():
    with patch.dict(os.environ, {}, clear=True), pytest.raises(ValueError, match="API key"):
        validate_production_settings(valid_settings())


@pytest.mark.parametrize("option", ["mock_llm", "mock_mcp", "mcp_memory_fallback"])
def test_production_rejects_mock(option):
    settings = valid_settings()
    setattr(settings, option, True)
    with pytest.raises(ValueError, match="forbids"):
        validate_production_settings(settings)


def test_mounted_key_and_production_strict(tmp_path):
    key = tmp_path / "model-key"
    key.write_text("test-key")
    with patch.dict(os.environ, {"OPENAI_API_KEY_FILE": str(key)}, clear=True):
        settings = valid_settings()
        validate_production_settings(settings)
        assert settings.llm.strict
        client, warnings = build_llm_client(settings.llm)
        assert client.provider_name == "openai"
        assert not warnings


def test_production_failure_never_becomes_mock_content():
    class FailingClient:
        provider_name = "openai"

        def complete_json(self, *args):
            raise TimeoutError("provider unavailable")

    with pytest.raises(RuntimeError, match="mock fallback is disabled"):
        LLMTool(FailingClient(), strict=True).summarize({"title": "test"}, {}, "")


def test_strict_client_refuses_unknown_provider():
    with pytest.raises(ValueError, match="supported real"):
        build_llm_client(LLMSettings(provider="misspelled", strict=True))
