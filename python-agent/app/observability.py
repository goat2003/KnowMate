from __future__ import annotations

import contextvars
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.grpc import GrpcInstrumentorServer
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("knowmate_run_id", default=None)
_grpc_instrumented = False
_tracing_configured = False

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "token",
    "password",
    "secret",
    "credential",
    "cookie",
    "set-cookie",
    "mysql_dsn",
    "dsn",
}
_REDACTED = "[REDACTED]"
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_KEY_VALUE_RE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|token|password|secret|credential)=([^&\s;]+)"
)
_MYSQL_DSN_RE = re.compile(r"(?i)\b(mysql(?:\+\w+)?://[^:\s/@]+:)([^@\s]+)(@)")
_MYSQL_GO_DSN_RE = re.compile(r"(?i)\b([A-Za-z0-9_.-]+:)([^@\s]+)(@tcp\()")


def set_run_id(run_id: str) -> None:
    _run_id.set(run_id)


def clear_run_id() -> None:
    _run_id.set(None)


def current_run_id() -> str | None:
    return _run_id.get()


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                redacted[key] = _REDACTED
            else:
                redacted[key] = redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    if isinstance(value, str):
        return _redact_string(value)
    return value


class JSONFormatter(logging.Formatter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        span_context = trace.get_current_span().get_span_context()
        payload: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": redact_sensitive(record.getMessage()),
            "run_id": current_run_id(),
            "trace_id": _format_trace_id(span_context.trace_id),
            "span_id": _format_span_id(span_context.span_id),
        }
        extra_payload = getattr(record, "payload", None)
        if extra_payload is not None:
            payload["payload"] = redact_sensitive(extra_payload)
        if record.exc_info:
            payload["exception"] = redact_sensitive(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


class Metrics:
    def __init__(self, namespace: str = "knowmate", registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.agent_runs = Counter(
            "agent_runs_total",
            "Total Python agent runs.",
            ["agent", "status"],
            namespace=namespace,
            registry=self.registry,
        )
        self.agent_duration = Histogram(
            "agent_duration_seconds",
            "Python agent run duration in seconds.",
            ["agent", "status"],
            namespace=namespace,
            registry=self.registry,
        )
        self.grpc_server_requests = Counter(
            "grpc_server_requests_total",
            "Total Python gRPC server requests.",
            ["method", "status_code"],
            namespace=namespace,
            registry=self.registry,
        )
        self.grpc_server_duration = Histogram(
            "grpc_server_duration_seconds",
            "Python gRPC server request duration in seconds.",
            ["method", "status_code"],
            namespace=namespace,
            registry=self.registry,
        )
        self.llm_requests = Counter(
            "llm_requests_total",
            "Total LLM requests.",
            ["provider", "model", "task", "status"],
            namespace=namespace,
            registry=self.registry,
        )
        self.llm_tokens = Counter(
            "llm_tokens_total",
            "Total LLM tokens.",
            ["provider", "model", "task", "status", "token_type"],
            namespace=namespace,
            registry=self.registry,
        )
        self.llm_cost = Counter(
            "llm_cost_usd_total",
            "Total LLM cost in USD.",
            ["provider", "model", "task", "status"],
            namespace=namespace,
            registry=self.registry,
        )
        self.llm_duration = Histogram(
            "llm_duration_seconds",
            "LLM request duration in seconds.",
            ["provider", "model", "task", "status"],
            namespace=namespace,
            registry=self.registry,
        )
        self.mcp_tool_calls = Counter(
            "mcp_tool_calls_total",
            "Total MCP tool calls.",
            ["server", "tool", "status"],
            namespace=namespace,
            registry=self.registry,
        )
        self.mcp_tool_duration = Histogram(
            "mcp_tool_duration_seconds",
            "MCP tool call duration in seconds.",
            ["server", "tool", "status"],
            namespace=namespace,
            registry=self.registry,
        )

    def record_agent_run(self, agent: str, status: str, duration_seconds: float) -> None:
        labels = {"agent": agent, "status": status}
        self.agent_runs.labels(**labels).inc()
        self.agent_duration.labels(**labels).observe(_non_negative_float(duration_seconds))

    def record_grpc_server(self, method: str, status_code: str, duration_seconds: float) -> None:
        labels = {"method": method, "status_code": status_code}
        self.grpc_server_requests.labels(**labels).inc()
        self.grpc_server_duration.labels(**labels).observe(_non_negative_float(duration_seconds))

    def record_llm_usage(
        self,
        provider: str,
        model: str,
        task: str,
        status: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        duration_seconds: float,
    ) -> None:
        labels = {"provider": provider, "model": model, "task": task, "status": status}
        self.llm_requests.labels(**labels).inc()
        self.llm_tokens.labels(**labels, token_type="prompt").inc(_non_negative_float(prompt_tokens))
        self.llm_tokens.labels(**labels, token_type="completion").inc(_non_negative_float(completion_tokens))
        self.llm_cost.labels(**labels).inc(_non_negative_float(cost_usd))
        self.llm_duration.labels(**labels).observe(_non_negative_float(duration_seconds))

    def record_mcp_tool(self, server: str, tool: str, status: str, duration_seconds: float) -> None:
        labels = {"server": server, "tool": tool, "status": status}
        self.mcp_tool_calls.labels(**labels).inc()
        self.mcp_tool_duration.labels(**labels).observe(_non_negative_float(duration_seconds))

    def render_text(self) -> bytes:
        return generate_latest(self.registry)


METRICS = Metrics()


def configure_json_logging(service_name: str) -> None:
    root = logging.getLogger()
    root.handlers = []
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter(service_name))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def init_observability(service_name: str) -> None:
    global _grpc_instrumented, _tracing_configured

    set_global_textmap(CompositePropagator([TraceContextTextMapPropagator()]))
    if not _grpc_instrumented:
        try:
            GrpcInstrumentorServer().instrument()
            _grpc_instrumented = True
        except Exception:
            logging.getLogger(__name__).debug("gRPC server instrumentation skipped", exc_info=True)

    if _otel_disabled():
        configure_json_logging(service_name)
        return

    if not _tracing_configured:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        try:
            trace.set_tracer_provider(provider)
            _tracing_configured = True
        except Exception:
            logging.getLogger(__name__).debug("OpenTelemetry tracer provider already configured", exc_info=True)
            _tracing_configured = True

    configure_json_logging(service_name)


def tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return normalized in {item.replace("-", "_") for item in _SENSITIVE_KEYS}


def _redact_string(value: str) -> str:
    value = _BEARER_RE.sub(f"Bearer {_REDACTED}", value)
    value = _MYSQL_DSN_RE.sub(rf"\1{_REDACTED}\3", value)
    value = _MYSQL_GO_DSN_RE.sub(rf"\1{_REDACTED}\3", value)
    return _KEY_VALUE_RE.sub(lambda match: f"{match.group(1)}={_REDACTED}", value)


def _non_negative_float(value: int | float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, number)


def _format_trace_id(trace_id: int) -> str | None:
    if not trace_id:
        return None
    return f"{trace_id:032x}"


def _format_span_id(span_id: int) -> str | None:
    if not span_id:
        return None
    return f"{span_id:016x}"


def _otel_disabled() -> bool:
    return os.getenv("OTEL_ENABLED", "").strip().lower() in {"0", "false", "no", "off"}
