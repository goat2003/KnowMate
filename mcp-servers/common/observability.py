from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from inspect import isawaitable
from typing import Any, TypeVar

from opentelemetry import context as otel_context_api
from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import ProxyTracerProvider
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest


_NORMALIZED_SENSITIVE_KEYS = {
    "apikey",
    "authorization",
    "proxyauthorization",
    "xapikey",
    "accesstoken",
    "refreshtoken",
    "token",
    "password",
    "secret",
    "clientsecret",
    "credential",
    "cookie",
    "setcookie",
    "dsn",
}
_REDACTED = "[REDACTED]"
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_BASIC_AUTH_RE = re.compile(r"(?i)\bBasic\s+[A-Za-z0-9._~+/=-]+")
_KEY_VALUE_RE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|token|password|secret|client[_-]?secret|credential)=([^&\s;]+)"
)
_MYSQL_DSN_RE = re.compile(r"(?i)\b(mysql(?:\+\w+)?://[^:\s/@]+:)([^@\s]+)(@)")
_MYSQL_GO_DSN_RE = re.compile(r"(?i)\b([A-Za-z0-9_.-]+:)([^@\s]+)(@tcp\()")

T = TypeVar("T")
_http_headers: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar("knowmate_mcp_http_headers", default={})
_tracing_configured = False


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
            "trace_id": _format_trace_id(span_context.trace_id),
            "span_id": _format_span_id(span_context.span_id),
        }
        extra_payload = getattr(record, "payload", None)
        if extra_payload is not None:
            payload["payload"] = _json_safe(redact_sensitive(extra_payload))
        if record.exc_info:
            payload["exception"] = redact_sensitive(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


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
        if _is_sensitive_pair(value):
            return [value[0], _REDACTED]
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        if _is_sensitive_pair(value):
            return (value[0], _REDACTED)
        return tuple(redact_sensitive(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return [redact_sensitive(item) for item in sorted(value, key=str)]
    if isinstance(value, bytes):
        return _redact_string(value.decode("utf-8", errors="replace"))
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, BaseException):
        return _redact_string(str(value))
    return value


def extract_trace_context(headers: dict[str, str]) -> otel_context_api.Context:
    return propagate.extract(headers)


def set_current_http_headers(headers: dict[str, str]) -> contextvars.Token[dict[str, str]]:
    return _http_headers.set({str(key).lower(): str(value) for key, value in headers.items()})


def reset_current_http_headers(token: contextvars.Token[dict[str, str]]) -> None:
    _http_headers.reset(token)


def current_trace_context() -> otel_context_api.Context:
    return extract_trace_context(_http_headers.get())


def init_observability(service_name: str) -> None:
    global _tracing_configured

    set_global_textmap(CompositePropagator([TraceContextTextMapPropagator()]))
    configure_json_logging(service_name)
    if _otel_disabled():
        return
    if _tracing_configured or _has_real_tracer_provider():
        _tracing_configured = True
        return

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    try:
        trace.set_tracer_provider(provider)
    except Exception:
        logging.getLogger(__name__).debug("OpenTelemetry tracer provider already configured", exc_info=True)
    _tracing_configured = True


def configure_json_logging(service_name: str) -> None:
    root = logging.getLogger()
    root.handlers = []
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter(service_name))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


class Metrics:
    def __init__(self, namespace: str = "knowmate", registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.mcp_tool_calls = Counter(
            "mcp_tool_calls_total",
            "Total MCP server tool calls.",
            ["server", "tool", "status"],
            namespace=namespace,
            registry=self.registry,
        )
        self.mcp_tool_duration = Histogram(
            "mcp_tool_duration_seconds",
            "MCP server tool call duration in seconds.",
            ["server", "tool", "status"],
            namespace=namespace,
            registry=self.registry,
        )
        self.mcp_tool_failures = Counter(
            "mcp_tool_failures_total",
            "Total failed MCP server tool calls.",
            ["server", "tool"],
            namespace=namespace,
            registry=self.registry,
        )

    def record_tool_call(self, server: str, tool: str, status: str, duration_seconds: float) -> None:
        labels = {"server": server, "tool": tool, "status": status}
        self.mcp_tool_calls.labels(**labels).inc()
        self.mcp_tool_duration.labels(**labels).observe(_non_negative_float(duration_seconds))
        if status != "success":
            self.mcp_tool_failures.labels(server=server, tool=tool).inc()

    def render_text(self) -> bytes:
        return generate_latest(self.registry)


METRICS = Metrics()


async def record_tool(
    server_name: str,
    tool_name: str,
    handler: Callable[[], T | Awaitable[T]],
    context: otel_context_api.Context | None = None,
) -> T:
    started = time.perf_counter()
    tracer = trace.get_tracer(__name__)
    status = "failed"
    with tracer.start_as_current_span(f"mcp.tool.{tool_name}", context=context) as span:
        span.set_attribute("mcp.server", server_name)
        span.set_attribute("mcp.tool", tool_name)
        try:
            result = handler()
            if isawaitable(result):
                result = await result
            status = "success"
            return result
        except Exception as exc:
            span.record_exception(exc)
            span.set_attribute("mcp.status", "failed")
            raise
        finally:
            span.set_attribute("mcp.status", status)
            METRICS.record_tool_call(server_name, tool_name, status, time.perf_counter() - started)


def _is_sensitive_key(key: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).strip().lower())
    return (
        normalized in _NORMALIZED_SENSITIVE_KEYS
        or normalized.endswith("secret")
        or normalized.endswith("password")
        or normalized.endswith("token")
    )


def _is_sensitive_pair(value: list[Any] | tuple[Any, ...]) -> bool:
    return len(value) == 2 and _is_sensitive_key(value[0])


def _redact_string(value: str) -> str:
    value = _BEARER_RE.sub(f"Bearer {_REDACTED}", value)
    value = _BASIC_AUTH_RE.sub(f"Basic {_REDACTED}", value)
    value = _MYSQL_DSN_RE.sub(rf"\1{_REDACTED}\3", value)
    value = _MYSQL_GO_DSN_RE.sub(rf"\1{_REDACTED}\3", value)
    return _KEY_VALUE_RE.sub(lambda match: f"{match.group(1)}={_REDACTED}", value)


def _non_negative_float(value: int | float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, number)


def _otel_disabled() -> bool:
    return os.getenv("OTEL_ENABLED", "").strip().lower() in {"0", "false", "no", "off"}


def _has_real_tracer_provider() -> bool:
    return not isinstance(trace.get_tracer_provider(), ProxyTracerProvider)


def _format_trace_id(trace_id: int) -> str | None:
    if not trace_id:
        return None
    return f"{trace_id:032x}"


def _format_span_id(span_id: int) -> str | None:
    if not span_id:
        return None
    return f"{span_id:016x}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_safe(item) for item in sorted(value, key=str)]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, BaseException):
        return str(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            return str(value)
    return value
