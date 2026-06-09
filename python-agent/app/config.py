# 文件作用：
# 本文件负责加载 Python Agent Service 的运行配置。
# 配置来源包括 python-agent/config.yaml 和环境变量，最终合并为 Settings 数据类。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的配置层，被 server.py、ArticleWorkflow、LLMTool 等模块使用。
#
# 主要内容：
# 1. _bool_env：把环境变量解析为布尔值。
# 2. _read_yaml：读取 YAML 配置文件。
# 3. OpenAISettings / ClaudeSettings / LLMSettings / Settings：配置数据结构。
# 4. load_settings：加载完整服务配置。
# 5. _load_llm_settings：加载 LLM provider 相关配置。
#
# 关键调用关系：
# - server.py 调用 load_settings 启动服务。
# - ArticleWorkflow 读取 Settings.mock_mcp 和 Settings.mcp_urls 初始化 MCP transport。
# - build_llm_tool 读取 Settings.llm 决定使用 mock/openai/claude provider。
#
# 初学者阅读建议：
# 先看 Settings 包含哪些字段，再看 load_settings 如何让环境变量覆盖 config.yaml。
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from types import ModuleType
from typing import Any

from app.recommendation import RecommendationSettings

# yaml 是可选依赖；缺失时仍允许模块导入，便于只做语法检查或部分单元测试。
yaml: ModuleType | None
try:
    import yaml as _yaml

    yaml = _yaml
except ImportError:  # pragma: no cover - keeps compile/import usable before deps install
    # 没有安装 PyYAML 时设置为 None，_read_yaml 会返回空配置。
    yaml = None


# 函数作用：
# 从环境变量读取布尔值。
#
# 参数说明：
# - name：环境变量名。
# - default：环境变量不存在时使用的默认值。
#
# 返回值：
# - 返回 True 或 False。
def _bool_env(name: str, default: bool) -> bool:
    # os.getenv 返回字符串或 None。
    raw = os.getenv(name)
    # 环境变量未设置时使用调用方传入的默认值。
    if raw is None:
        return default
    # 支持常见真值写法，例如 1、true、yes、y、on。
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


# 函数作用：
# 读取 YAML 文件并返回字典。
#
# 参数说明：
# - path：YAML 文件路径。
#
# 返回值：
# - 文件不存在、PyYAML 未安装或文件为空时返回空字典。
def _read_yaml(path: Path) -> dict[str, Any]:
    # 如果文件不存在或 yaml 依赖缺失，就不抛错，使用默认配置继续启动。
    if not path.exists() or yaml is None:
        return {}
    # with 会自动关闭文件句柄，encoding="utf-8" 确保中文配置可正确读取。
    with path.open("r", encoding="utf-8") as file:
        # safe_load 避免执行任意 YAML 对象构造；文件为空时用 {} 兜底。
        return yaml.safe_load(file) or {}


# 类作用：
# OpenAISettings 保存 OpenAI 兼容 provider 的配置。
# dataclass(slots=True) 自动生成构造函数，并限制实例字段固定。
@dataclass(slots=True)
class OpenAISettings:
    # base_url 是 OpenAI 兼容 API 根地址。
    base_url: str = "https://api.openai.com/v1"
    # api_key_env 指定从哪个环境变量读取 API Key。
    api_key_env: str = "OPENAI_API_KEY"
    # model 是 chat completions 请求使用的模型名称。
    model: str = "gpt-4.1-mini"


# 类作用：
# ClaudeSettings 保存 Claude provider 的配置。
# 当前 Claude 调用在 LLMTool 中是预留接口，尚未实现真实 HTTP 调用。
@dataclass(slots=True)
class ClaudeSettings:
    base_url: str = "https://api.anthropic.com/v1"
    # api_key_env 指定 Claude API Key 的环境变量名。
    api_key_env: str = "ANTHROPIC_API_KEY"
    # model 是未来 Claude 调用使用的模型名称。
    model: str = "claude-3-5-sonnet-latest"


# 类作用：
# LLMSettings 保存 LLM provider 的总配置。
# provider 决定 build_llm_client 选择 mock、openai-compatible 还是 claude。
@dataclass(slots=True)
class LLMSettings:
    # 默认使用 mock，保证本地没有 API Key 时也能运行。
    provider: str = "mock"
    # field(default_factory=...) 避免多个 LLMSettings 实例共享同一个 OpenAISettings 对象。
    openai: OpenAISettings = field(default_factory=OpenAISettings)
    # Claude 配置同样使用 default_factory 创建独立实例。
    claude: ClaudeSettings = field(default_factory=ClaudeSettings)


@dataclass(slots=True)
class McpServerSettings:
    transport: str = "memory"
    url: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)


# 类作用：
# Settings 是 Python Agent Service 的完整运行配置。
# server.py、grpc_server.py、workflow/graph.py 都会读取它。
@dataclass(slots=True)
class Settings:
    # host 是 gRPC Server 监听地址。
    host: str = "0.0.0.0"
    # port 是 gRPC Server 监听端口。
    port: int = 50051
    metrics_host: str = "0.0.0.0"
    metrics_port: int = 9101
    # version 会在 HealthCheck 响应中返回。
    version: str = "0.1.0"
    api_token: str = ""
    # mock_llm 表示是否使用 mock LLM provider。
    mock_llm: bool = True
    # mock_mcp 是旧配置兼容开关；新配置优先使用每个 server 的 transport。
    mock_mcp: bool = True
    # mcp_urls 保存真实 MCP Server 的 endpoint 配置。
    mcp_urls: dict[str, str] = field(default_factory=dict)
    # llm 保存 provider 和模型相关配置。
    llm: LLMSettings = field(default_factory=LLMSettings)
    grpc_max_workers: int = 10
    grpc_max_message_bytes: int = 4 * 1024 * 1024
    max_articles_per_request: int = 100
    max_feedback_per_request: int = 100
    idempotency_cache_size: int = 1024
    mcp_timeout_seconds: float = 8.0
    mcp_max_retries: int = 2
    mcp_retry_backoff_seconds: float = 0.1
    mcp_circuit_failure_threshold: int = 3
    mcp_circuit_reset_seconds: float = 30.0
    mcp_memory_fallback: bool = False
    mcp_servers: dict[str, McpServerSettings] = field(default_factory=dict)
    recommendation: RecommendationSettings = field(default_factory=RecommendationSettings)


# 函数作用：
# 加载完整服务配置。
#
# 参数说明：
# - 无。
#
# 返回值：
# - 返回 Settings 实例。
#
# 配置优先级：
# - 默认值 < config.yaml < 环境变量。
#
# 调用关系：
# - 被 server.py main 调用。
def load_settings() -> Settings:
    # 当前文件位于 app/config.py，parents[1] 是 python-agent 目录。
    root = Path(__file__).resolve().parents[1]
    # 读取 python-agent/config.yaml；读取失败时 raw 为空字典。
    raw = _read_yaml(root / "config.yaml")
    # 各配置段按 YAML 顶层 key 拆开，缺失时使用空字典。
    agent = raw.get("agent", {})
    mock = raw.get("mock", {})
    mcp = raw.get("mcp", {})
    limits = raw.get("limits", {})
    llm = raw.get("llm", {})
    recommendation = raw.get("recommendation", {})
    # 单独加载 LLM 配置，因为 provider 选择涉及 mock 配置和环境变量覆盖。
    llm_settings = _load_llm_settings(llm, mock)

    # 创建最终 Settings；每个字段都允许环境变量覆盖 YAML。
    mock_mcp = _bool_env("MOCK_MCP", bool(mock.get("mcp", True)))
    mcp_servers = _load_mcp_servers(mcp, mock_mcp)
    return Settings(
        host=os.getenv("AGENT_HOST", agent.get("host", "0.0.0.0")),
        port=int(os.getenv("AGENT_PORT", agent.get("port", 50051))),
        metrics_host=os.getenv("METRICS_HOST", agent.get("metrics_host", "0.0.0.0")),
        metrics_port=int(os.getenv("METRICS_PORT", agent.get("metrics_port", 9101))),
        version=os.getenv("AGENT_VERSION", agent.get("version", "0.1.0")),
        api_token=os.getenv("AGENT_GRPC_AUTH_TOKEN", agent.get("api_token", "")),
        # mock_llm 由最终 provider 是否为 mock 推导，避免 YAML 和实际 provider 不一致。
        mock_llm=llm_settings.provider == "mock",
        # MOCK_MCP 环境变量优先，其次使用 config.yaml 中 mock.mcp，最后默认 True。
        mock_mcp=mock_mcp,
        llm=llm_settings,
        grpc_max_workers=max(int(os.getenv("GRPC_MAX_WORKERS", limits.get("grpc_max_workers", 10))), 1),
        grpc_max_message_bytes=max(int(os.getenv("GRPC_MAX_MESSAGE_BYTES", limits.get("grpc_max_message_bytes", 4 * 1024 * 1024))), 1024),
        max_articles_per_request=max(int(os.getenv("MAX_ARTICLES_PER_REQUEST", limits.get("max_articles_per_request", 100))), 1),
        max_feedback_per_request=max(int(os.getenv("MAX_FEEDBACK_PER_REQUEST", limits.get("max_feedback_per_request", 100))), 1),
        idempotency_cache_size=max(int(os.getenv("IDEMPOTENCY_CACHE_SIZE", limits.get("idempotency_cache_size", 1024))), 1),
        mcp_timeout_seconds=max(float(os.getenv("MCP_TIMEOUT_SECONDS", limits.get("mcp_timeout_seconds", 8))), 0.1),
        mcp_max_retries=max(int(os.getenv("MCP_MAX_RETRIES", limits.get("mcp_max_retries", 2))), 0),
        mcp_retry_backoff_seconds=max(
            float(os.getenv("MCP_RETRY_BACKOFF_SECONDS", limits.get("mcp_retry_backoff_seconds", 0.1))),
            0,
        ),
        mcp_circuit_failure_threshold=max(
            int(os.getenv("MCP_CIRCUIT_FAILURE_THRESHOLD", limits.get("mcp_circuit_failure_threshold", 3))),
            1,
        ),
        mcp_circuit_reset_seconds=max(
            float(os.getenv("MCP_CIRCUIT_RESET_SECONDS", limits.get("mcp_circuit_reset_seconds", 30))),
            0,
        ),
        mcp_memory_fallback=_bool_env(
            "MCP_MEMORY_FALLBACK",
            bool(mcp.get("memory_fallback", False)),
        ),
        mcp_servers=mcp_servers,
        recommendation=RecommendationSettings.from_dict(recommendation),
        # MCP endpoint 既可来自环境变量，也可来自 config.yaml。
        mcp_urls={
            "embedding": os.getenv("EMBEDDING_MCP_URL", mcp.get("embedding", "http://127.0.0.1:7001")),
            "fetch": os.getenv("FETCH_MCP_URL", mcp.get("fetch", "http://127.0.0.1:7002")),
            "milvus": os.getenv("MILVUS_MCP_URL", mcp.get("milvus", "http://127.0.0.1:7003")),
            "neo4j": os.getenv("NEO4J_MCP_URL", mcp.get("neo4j", "http://127.0.0.1:7004")),
        },
    )


def _load_mcp_servers(raw: dict[str, Any], mock_mcp: bool) -> dict[str, McpServerSettings]:
    server_names = ["embedding-mcp", "fetch-mcp", "milvus-mcp", "neo4j-mcp"]
    legacy_keys = {
        "embedding-mcp": "embedding",
        "fetch-mcp": "fetch",
        "milvus-mcp": "milvus",
        "neo4j-mcp": "neo4j",
    }
    url_envs = {
        "embedding-mcp": "EMBEDDING_MCP_URL",
        "fetch-mcp": "FETCH_MCP_URL",
        "milvus-mcp": "MILVUS_MCP_URL",
        "neo4j-mcp": "NEO4J_MCP_URL",
    }
    transport_envs = {
        "embedding-mcp": "EMBEDDING_MCP_TRANSPORT",
        "fetch-mcp": "FETCH_MCP_TRANSPORT",
        "milvus-mcp": "MILVUS_MCP_TRANSPORT",
        "neo4j-mcp": "NEO4J_MCP_TRANSPORT",
    }
    configured = raw.get("servers", {})
    servers: dict[str, McpServerSettings] = {}
    for name in server_names:
        item = configured.get(name, {}) if isinstance(configured, dict) else {}
        default_transport = "memory" if mock_mcp else "streamable_http"
        transport = os.getenv(
            transport_envs[name],
            str(item.get("transport", default_transport)),
        ).strip().lower().replace("-", "_")
        legacy_url = str(raw.get(legacy_keys[name], ""))
        url = os.getenv(url_envs[name], str(item.get("url") or legacy_url))
        servers[name] = McpServerSettings(
            transport=transport,
            url=url,
            command=str(item.get("command", "")),
            args=[str(value) for value in item.get("args", [])],
            env={str(key): str(value) for key, value in item.get("env", {}).items()},
            headers={str(key): str(value) for key, value in item.get("headers", {}).items()},
        )
    return servers


# 函数作用：
# 加载 LLM provider 相关配置。
#
# 参数说明：
# - raw：config.yaml 中 llm 段。
# - mock：config.yaml 中 mock 段。
#
# 返回值：
# - 返回 LLMSettings。
def _load_llm_settings(raw: dict[str, Any], mock: dict[str, Any]) -> LLMSettings:
    # provider 优先读取 llm.provider；如果未设置，则根据 mock.llm 决定 mock 或 openai。
    provider = str(raw.get("provider") or ("mock" if bool(mock.get("llm", True)) else "openai")).strip().lower()
    # LLM_PROVIDER 环境变量可强制覆盖 provider。
    if os.getenv("LLM_PROVIDER"):
        provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()
    # MOCK_LLM=true 时强制使用 mock provider，适合本地和 CI。
    if os.getenv("MOCK_LLM") is not None and _bool_env("MOCK_LLM", False):
        provider = "mock"

    # 读取 provider 子配置，缺失时用空字典。
    openai = raw.get("openai", {})
    claude = raw.get("claude", {})
    # 创建 LLMSettings，并允许环境变量覆盖各个细项。
    return LLMSettings(
        provider=provider or "mock",
        openai=OpenAISettings(
            base_url=os.getenv("OPENAI_BASE_URL", openai.get("base_url") or "https://api.openai.com/v1"),
            api_key_env=os.getenv("OPENAI_API_KEY_ENV", openai.get("api_key_env") or "OPENAI_API_KEY"),
            model=os.getenv("OPENAI_MODEL", openai.get("model") or "gpt-4.1-mini"),
        ),
        claude=ClaudeSettings(
            base_url=os.getenv("ANTHROPIC_BASE_URL", claude.get("base_url") or "https://api.anthropic.com/v1"),
            api_key_env=os.getenv("ANTHROPIC_API_KEY_ENV", claude.get("api_key_env") or "ANTHROPIC_API_KEY"),
            model=os.getenv("ANTHROPIC_MODEL", claude.get("model") or "claude-3-5-sonnet-latest"),
        ),
    )
