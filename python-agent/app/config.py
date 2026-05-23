from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - keeps compile/import usable before deps install
    yaml = None


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists() or yaml is None:
        return {}
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


@dataclass(slots=True)
class OpenAISettings:
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "gpt-4.1-mini"


@dataclass(slots=True)
class ClaudeSettings:
    api_key_env: str = "ANTHROPIC_API_KEY"
    model: str = "claude-3-5-sonnet-latest"


@dataclass(slots=True)
class LLMSettings:
    provider: str = "mock"
    openai: OpenAISettings = field(default_factory=OpenAISettings)
    claude: ClaudeSettings = field(default_factory=ClaudeSettings)


@dataclass(slots=True)
class Settings:
    host: str = "0.0.0.0"
    port: int = 50051
    version: str = "0.1.0"
    mock_llm: bool = True
    mock_mcp: bool = True
    mcp_urls: dict[str, str] = field(default_factory=dict)
    llm: LLMSettings = field(default_factory=LLMSettings)


def load_settings() -> Settings:
    root = Path(__file__).resolve().parents[1]
    raw = _read_yaml(root / "config.yaml")
    agent = raw.get("agent", {})
    mock = raw.get("mock", {})
    mcp = raw.get("mcp", {})
    llm = raw.get("llm", {})
    llm_settings = _load_llm_settings(llm, mock)

    return Settings(
        host=os.getenv("AGENT_HOST", agent.get("host", "0.0.0.0")),
        port=int(os.getenv("AGENT_PORT", agent.get("port", 50051))),
        version=os.getenv("AGENT_VERSION", agent.get("version", "0.1.0")),
        mock_llm=llm_settings.provider == "mock",
        mock_mcp=_bool_env("MOCK_MCP", bool(mock.get("mcp", True))),
        llm=llm_settings,
        mcp_urls={
            "embedding": os.getenv("EMBEDDING_MCP_URL", mcp.get("embedding", "http://127.0.0.1:7001")),
            "fetch": os.getenv("FETCH_MCP_URL", mcp.get("fetch", "http://127.0.0.1:7002")),
            "milvus": os.getenv("MILVUS_MCP_URL", mcp.get("milvus", "http://127.0.0.1:7003")),
            "neo4j": os.getenv("NEO4J_MCP_URL", mcp.get("neo4j", "http://127.0.0.1:7004")),
        },
    )


def _load_llm_settings(raw: dict[str, Any], mock: dict[str, Any]) -> LLMSettings:
    provider = str(raw.get("provider") or ("mock" if bool(mock.get("llm", True)) else "openai")).strip().lower()
    if os.getenv("LLM_PROVIDER"):
        provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()
    if os.getenv("MOCK_LLM") is not None and _bool_env("MOCK_LLM", False):
        provider = "mock"

    openai = raw.get("openai", {})
    claude = raw.get("claude", {})
    return LLMSettings(
        provider=provider or "mock",
        openai=OpenAISettings(
            base_url=os.getenv("OPENAI_BASE_URL", openai.get("base_url") or "https://api.openai.com/v1"),
            api_key_env=os.getenv("OPENAI_API_KEY_ENV", openai.get("api_key_env") or "OPENAI_API_KEY"),
            model=os.getenv("OPENAI_MODEL", openai.get("model") or "gpt-4.1-mini"),
        ),
        claude=ClaudeSettings(
            api_key_env=os.getenv("ANTHROPIC_API_KEY_ENV", claude.get("api_key_env") or "ANTHROPIC_API_KEY"),
            model=os.getenv("ANTHROPIC_MODEL", claude.get("model") or "claude-3-5-sonnet-latest"),
        ),
    )
