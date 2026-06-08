# Unified Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 GoFrame、Python Agent、MCP Server 增加统一 OpenTelemetry tracing、结构化 JSON 日志、Prometheus Metrics、Grafana Dashboard、告警规则和运维文档。

**Architecture:** 新增 Go/Python/MCP 三套轻量 observability 边界模块，分别在 HTTP、gRPC、workflow、MCP tool、LLM 调用边界记录 span 和 metrics。`trace_id` 由 OpenTelemetry/W3C TraceContext 跨进程传播，`run_id` 继续作为业务任务 ID 写入 span attributes 和 JSON 日志；Prometheus scrape 各服务 `/metrics`，OTel Collector 接收 traces 并转发 Jaeger，Grafana 读取 Prometheus Dashboard，Alertmanager 接收 Prometheus 告警。

**Tech Stack:** GoFrame v2、Go OpenTelemetry、otelgrpc、Prometheus Go client、Python OpenTelemetry、prometheus-client、grpcio、MCP Python SDK FastMCP、Docker Compose、Prometheus、Grafana、Jaeger、Alertmanager、PowerShell 验证脚本。

---

## File Structure

- Create: `goframe-backend/internal/observability/observability.go`
  - GoFrame 侧统一初始化 OTel、Prometheus metrics、run context、JSON 日志字段和脱敏函数。
- Create: `goframe-backend/internal/observability/metrics.go`
  - GoFrame 业务指标注册和记录函数。
- Create: `goframe-backend/internal/observability/observability_test.go`
  - Go 脱敏、run context、metrics handler、trace propagation 单元测试。
- Modify: `goframe-backend/go.mod`
  - 增加 Go OTel gRPC instrumentation、OTLP exporter、Prometheus exporter/client 依赖。
- Modify: `goframe-backend/main.go`
  - 启动时初始化 observability，退出时 shutdown。
- Modify: `goframe-backend/internal/handler/handler.go`
  - 注册 HTTP observability middleware 和 `/metrics`。
- Modify: `goframe-backend/internal/grpcclient/client.go`
  - gRPC client 接入 `otelgrpc.NewClientHandler`。
- Create: `goframe-backend/internal/grpcclient/client_test.go`
  - 验证 gRPC client 注入 trace context。
- Modify: `goframe-backend/internal/logic/harness/harness.go`
  - 任务、抓取、Agent 调用、posts、feedback 业务指标。
- Modify: `goframe-backend/internal/logic/harness/crawler_test.go`
  - 增加抓取和任务 metrics 断言。
- Create: `python-agent/app/observability.py`
  - Python Agent OTel、Prometheus metrics、JSON logging、run context、脱敏函数。
- Modify: `python-agent/requirements.txt`
  - 增加 Python OTel 和 Prometheus client 依赖。
- Modify: `python-agent/server.py`
  - 启动 Python observability。
- Modify: `python-agent/app/grpc_server.py`
  - gRPC server instrumentation、run context、RPC metrics。
- Modify: `python-agent/app/workflow/graph.py`
  - Agent 执行 span 和 Agent metrics。
- Modify: `python-agent/app/tools/llm_tool.py`
  - LLM request/token/cost metrics 与 span attributes。
- Modify: `python-agent/app/mcp/base_client.py`
  - 复用 `app.observability.redact_sensitive` 并记录 MCP client metrics。
- Modify: `python-agent/app/mcp/sdk_transport.py`
  - HTTP MCP 调用注入 trace context headers。
- Create: `python-agent/tests/test_observability.py`
  - Python JSON logging、脱敏、metrics 单元测试。
- Create: `python-agent/tests/test_grpc_observability.py`
  - Python gRPC run context 和 trace context 测试。
- Create: `python-agent/tests/test_mcp_observability.py`
  - Python MCP metrics 和 trace header 注入测试。
- Create: `mcp-servers/common/observability.py`
  - MCP Server 侧 OTel、Prometheus metrics、JSON logging、trace extraction。
- Modify: `mcp-servers/common/simple_http_mcp.py`
  - MCP tool wrapper、`/metrics` route、trace context extraction。
- Modify: `mcp-servers/requirements.txt`
  - 增加 Python OTel 和 Prometheus client 依赖。
- Create: `mcp-servers/tests/test_observability.py`
  - MCP Server metrics、trace extraction、tool failure metrics 测试。
- Create: `observability/otel-collector.yml`
  - OTel Collector receiver/exporter/service pipeline。
- Create: `observability/prometheus.yml`
  - Prometheus scrape 和 rule files 配置。
- Create: `observability/alerts.yml`
  - KnowMate 告警规则。
- Create: `observability/alertmanager.yml`
  - 本地空接收器 Alertmanager 配置。
- Create: `observability/grafana/provisioning/datasources/prometheus.yml`
  - Grafana Prometheus 数据源 provisioning。
- Create: `observability/grafana/provisioning/dashboards/dashboards.yml`
  - Grafana Dashboard provisioning。
- Create: `observability/grafana/dashboards/knowmate-overview.json`
  - KnowMate Overview Dashboard。
- Modify: `docker-compose.yml`
  - 增加 OTel Collector、Prometheus、Grafana、Jaeger、Alertmanager，并给业务服务补 observability 环境变量。
- Modify: `.env.example`
  - 增加观测端口和 OTel 环境变量。
- Create: `scripts/check_observability_config.ps1`
  - 校验 observability YAML、Dashboard JSON、compose 服务。
- Create: `docs/observability.md`
  - 指标字典、日志字段、trace/span 命名、告警排查。
- Modify: `README.md`
  - 增加可观测性启动、访问地址和验证说明。

## Task 1: Go Observability Foundation

**Files:**
- Create: `goframe-backend/internal/observability/observability_test.go`
- Create: `goframe-backend/internal/observability/observability.go`
- Create: `goframe-backend/internal/observability/metrics.go`
- Modify: `goframe-backend/go.mod`

- [ ] **Step 1: Write the failing Go observability tests**

Create `goframe-backend/internal/observability/observability_test.go`:

```go
package observability

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/trace"
)

func TestRedactSensitiveMasksNestedValues(t *testing.T) {
	input := map[string]any{
		"authorization": "Bearer secret-token",
		"mysql_dsn":     "app:apppass@tcp(mysql:3306)/knowledge_post_agent",
		"nested": map[string]any{
			"api_key": "sk-secret",
			"items": []any{
				map[string]any{"password": "plain-password"},
				"refresh_token=abc123",
			},
		},
	}

	encoded, err := json.Marshal(RedactSensitive(input))
	if err != nil {
		t.Fatalf("marshal redacted value: %v", err)
	}
	text := string(encoded)

	for _, secret := range []string{"secret-token", "apppass", "sk-secret", "plain-password", "abc123"} {
		if strings.Contains(text, secret) {
			t.Fatalf("secret %q leaked in %s", secret, text)
		}
	}
	if !strings.Contains(text, "[REDACTED]") {
		t.Fatalf("expected redaction marker in %s", text)
	}
}

func TestRunIDContextRoundTrip(t *testing.T) {
	ctx := WithRunID(context.Background(), "articles-run")

	if got := RunIDFromContext(ctx); got != "articles-run" {
		t.Fatalf("unexpected run id %q", got)
	}
	if got := RunIDFromContext(context.Background()); got != "" {
		t.Fatalf("empty context returned run id %q", got)
	}
}

func TestJSONLogRecordIncludesTraceAndRunID(t *testing.T) {
	ctx := WithRunID(context.Background(), "run-log")
	ctx, span := otel.Tracer("test").Start(ctx, "log-test")
	defer span.End()

	record := JSONLogRecord(ctx, "goframe-backend", "info", "message", map[string]any{"token": "secret"})
	encoded, err := json.Marshal(record)
	if err != nil {
		t.Fatalf("marshal log record: %v", err)
	}
	text := string(encoded)

	if record["service"] != "goframe-backend" || record["run_id"] != "run-log" {
		t.Fatalf("missing service/run_id fields: %#v", record)
	}
	if _, ok := record["trace_id"]; !ok {
		t.Fatalf("missing trace_id: %#v", record)
	}
	if strings.Contains(text, "secret") {
		t.Fatalf("sensitive field leaked in log record: %s", text)
	}
}

func TestTraceHeadersRoundTripThroughPropagator(t *testing.T) {
	carrier := propagation.HeaderCarrier(http.Header{})
	ctx := context.Background()
	ctx, span := otel.Tracer("test").Start(ctx, "inject-test")
	defer span.End()

	InjectTraceContext(ctx, carrier)
	extracted := ExtractTraceContext(context.Background(), carrier)
	spanContext := trace.SpanContextFromContext(extracted)

	if !spanContext.IsValid() {
		t.Fatalf("expected valid extracted span context")
	}
}

func TestMetricsHandlerExposesKnowmateMetric(t *testing.T) {
	ResetMetricsForTest()
	RecordTaskRun(context.Background(), "articles", "completed", 1.2)
	RecordGRPCClient(context.Background(), "AgentService/ProcessArticles", "OK", 0.2)
	RecordRecommendation(context.Background(), "kept", 2)
	RecordPostGenerated(context.Background(), "success", 1)
	RecordUserFeedback(context.Background(), "text", "received", 1)

	recorder := httptest.NewRecorder()
	MetricsHandler().ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/metrics", bytes.NewReader(nil)))

	body := recorder.Body.String()
	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, body)
	}
	if !strings.Contains(body, "knowmate_task_runs_total") {
		t.Fatalf("missing task metric in %s", body)
	}
	for _, metric := range []string{
		"knowmate_grpc_client_duration_seconds",
		"knowmate_recommendation_items_total",
		"knowmate_posts_generated_total",
		"knowmate_feedback_received_total",
	} {
		if !strings.Contains(body, metric) {
			t.Fatalf("missing %s in %s", metric, body)
		}
	}
}
```

- [ ] **Step 2: Run Go observability tests to verify they fail**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\goframe-backend
go test ./internal/observability -count=1
```

Expected: FAIL because `internal/observability` package and exported functions do not exist.

- [ ] **Step 3: Add Go dependencies**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\goframe-backend
go get go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc
go get go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc
go get github.com/prometheus/client_golang/prometheus
go get github.com/prometheus/client_golang/prometheus/promhttp
```

Expected: `go.mod` and `go.sum` gain the required direct or indirect dependencies.

- [ ] **Step 4: Implement Go observability helpers**

Create `goframe-backend/internal/observability/observability.go`:

```go
package observability

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"regexp"
	"strings"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
	"google.golang.org/grpc/credentials/insecure"
)

type runIDKey struct{}

type ShutdownFunc func(context.Context) error

type Options struct {
	ServiceName  string
	OTLPEndpoint string
	Enabled      bool
}

var sensitiveKeys = map[string]struct{}{
	"api_key": {}, "apikey": {}, "authorization": {}, "access_token": {},
	"refresh_token": {}, "token": {}, "password": {}, "secret": {},
	"credential": {}, "cookie": {}, "set-cookie": {}, "mysql_dsn": {}, "dsn": {},
}

var (
	bearerPattern    = regexp.MustCompile(`(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+`)
	keyValuePattern  = regexp.MustCompile(`(?i)\b(api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|password|secret|cookie)\s*[:=]\s*([^\s,;]+)`)
	mysqlDSNPattern  = regexp.MustCompile(`([A-Za-z0-9_.-]+):([^@]+)@tcp\(([^)]+)\)`)
	defaultService   = "goframe-backend"
	defaultEndpoint  = "otel-collector:4317"
	redactionMarker  = "[REDACTED]"
)

func Init(ctx context.Context, opts Options) (ShutdownFunc, error) {
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))
	if !opts.Enabled {
		return func(context.Context) error { return nil }, nil
	}
	if opts.ServiceName == "" {
		opts.ServiceName = defaultService
	}
	if opts.OTLPEndpoint == "" {
		opts.OTLPEndpoint = defaultEndpoint
	}
	exporter, err := otlptracegrpc.New(
		ctx,
		otlptracegrpc.WithEndpoint(opts.OTLPEndpoint),
		otlptracegrpc.WithTLSCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		return nil, err
	}
	res, err := resource.New(ctx, resource.WithAttributes(attribute.String("service.name", opts.ServiceName)))
	if err != nil {
		return nil, err
	}
	provider := sdktrace.NewTracerProvider(sdktrace.WithBatcher(exporter), sdktrace.WithResource(res))
	otel.SetTracerProvider(provider)
	return provider.Shutdown, nil
}

func WithRunID(ctx context.Context, runID string) context.Context {
	if runID == "" {
		return ctx
	}
	return context.WithValue(ctx, runIDKey{}, runID)
}

func RunIDFromContext(ctx context.Context) string {
	value, _ := ctx.Value(runIDKey{}).(string)
	return value
}

func JSONLogRecord(ctx context.Context, service string, level string, message string, fields map[string]any) map[string]any {
	if service == "" {
		service = defaultService
	}
	record := map[string]any{
		"time":    time.Now().UTC().Format(time.RFC3339Nano),
		"level":   level,
		"service": service,
		"message": message,
		"run_id":  RunIDFromContext(ctx),
	}
	spanContext := trace.SpanContextFromContext(ctx)
	if spanContext.IsValid() {
		record["trace_id"] = spanContext.TraceID().String()
		record["span_id"] = spanContext.SpanID().String()
	} else {
		record["trace_id"] = ""
		record["span_id"] = ""
	}
	for key, value := range fields {
		record[key] = RedactSensitive(value)
	}
	return record
}

func WriteJSONLog(ctx context.Context, service string, level string, message string, fields map[string]any) {
	encoded, err := json.Marshal(JSONLogRecord(ctx, service, level, message, fields))
	if err != nil {
		_, _ = fmt.Fprintf(os.Stderr, `{"level":"error","message":"log marshal failed","error":%q}`+"\n", err.Error())
		return
	}
	_, _ = os.Stdout.Write(append(encoded, '\n'))
}

func RedactSensitive(value any) any {
	switch typed := value.(type) {
	case map[string]any:
		out := make(map[string]any, len(typed))
		for key, item := range typed {
			if _, ok := sensitiveKeys[strings.ToLower(key)]; ok {
				out[key] = redactionMarker
				continue
			}
			out[key] = RedactSensitive(item)
		}
		return out
	case map[string]string:
		out := make(map[string]string, len(typed))
		for key, item := range typed {
			if _, ok := sensitiveKeys[strings.ToLower(key)]; ok {
				out[key] = redactionMarker
				continue
			}
			out[key] = fmt.Sprint(RedactSensitive(item))
		}
		return out
	case []any:
		out := make([]any, 0, len(typed))
		for _, item := range typed {
			out = append(out, RedactSensitive(item))
		}
		return out
	case string:
		text := bearerPattern.ReplaceAllString(typed, "Bearer "+redactionMarker)
		text = keyValuePattern.ReplaceAllString(text, "$1="+redactionMarker)
		text = mysqlDSNPattern.ReplaceAllString(text, "$1:"+redactionMarker+"@tcp($3)")
		return text
	default:
		return typed
	}
}

func InjectTraceContext(ctx context.Context, carrier propagation.TextMapCarrier) {
	otel.GetTextMapPropagator().Inject(ctx, carrier)
}

func ExtractTraceContext(ctx context.Context, carrier propagation.TextMapCarrier) context.Context {
	return otel.GetTextMapPropagator().Extract(ctx, carrier)
}

func SpanAttributes(runID string, taskType string) []attribute.KeyValue {
	return []attribute.KeyValue{
		attribute.String("run_id", runID),
		attribute.String("task_type", taskType),
	}
}

func EnabledFromEnv() bool {
	value := strings.ToLower(strings.TrimSpace(os.Getenv("OTEL_ENABLED")))
	return value == "" || value == "1" || value == "true" || value == "yes" || value == "on"
}

func OptionsFromEnv(serviceName string) Options {
	return Options{
		ServiceName:  firstNonEmpty(os.Getenv("OTEL_SERVICE_NAME"), serviceName),
		OTLPEndpoint: strings.TrimPrefix(firstNonEmpty(os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT"), defaultEndpoint), "http://"),
		Enabled:      EnabledFromEnv(),
	}
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

func TraceMiddleware(service string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			ctx := ExtractTraceContext(r.Context(), propagation.HeaderCarrier(r.Header))
			ctx, span := otel.Tracer(service).Start(ctx, r.Method+" "+r.URL.Path)
			defer span.End()
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}
```

Create `goframe-backend/internal/observability/metrics.go`:

```go
package observability

import (
	"context"
	"net/http"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

var registry = prometheus.NewRegistry()

var taskRuns = prometheus.NewCounterVec(
	prometheus.CounterOpts{
		Name: "knowmate_task_runs_total",
		Help: "Total KnowMate task runs by task type and status.",
	},
	[]string{"task_type", "status"},
)

var taskDuration = prometheus.NewHistogramVec(
	prometheus.HistogramOpts{
		Name:    "knowmate_task_duration_seconds",
		Help:    "KnowMate task duration in seconds.",
		Buckets: prometheus.DefBuckets,
	},
	[]string{"task_type", "status"},
)

var crawlerArticles = prometheus.NewCounterVec(
	prometheus.CounterOpts{
		Name: "knowmate_crawler_articles_total",
		Help: "Crawler article counts by source, source type, and status.",
	},
	[]string{"source", "type", "status"},
)

var grpcClientRequests = prometheus.NewCounterVec(
	prometheus.CounterOpts{
		Name: "knowmate_grpc_client_requests_total",
		Help: "gRPC client requests by method and status code.",
	},
	[]string{"method", "status_code"},
)

var grpcClientDuration = prometheus.NewHistogramVec(
	prometheus.HistogramOpts{
		Name:    "knowmate_grpc_client_duration_seconds",
		Help:    "gRPC client duration in seconds.",
		Buckets: prometheus.DefBuckets,
	},
	[]string{"method", "status_code"},
)

var recommendationItems = prometheus.NewCounterVec(
	prometheus.CounterOpts{
		Name: "knowmate_recommendation_items_total",
		Help: "Recommendation decisions by kept or dropped outcome.",
	},
	[]string{"decision"},
)

var postsGenerated = prometheus.NewCounterVec(
	prometheus.CounterOpts{
		Name: "knowmate_posts_generated_total",
		Help: "Generated posts by status.",
	},
	[]string{"status"},
)

var feedbackReceived = prometheus.NewCounterVec(
	prometheus.CounterOpts{
		Name: "knowmate_feedback_received_total",
		Help: "User feedback events by feedback type and processing status.",
	},
	[]string{"feedback_type", "status"},
)

func init() {
	registerCollectors(registry)
}

func registerCollectors(target *prometheus.Registry) {
	target.MustRegister(
		taskRuns,
		taskDuration,
		crawlerArticles,
		grpcClientRequests,
		grpcClientDuration,
		recommendationItems,
		postsGenerated,
		feedbackReceived,
	)
}

func ResetMetricsForTest() {
	registry = prometheus.NewRegistry()
	taskRuns.Reset()
	taskDuration.Reset()
	crawlerArticles.Reset()
	grpcClientRequests.Reset()
	grpcClientDuration.Reset()
	recommendationItems.Reset()
	postsGenerated.Reset()
	feedbackReceived.Reset()
	registerCollectors(registry)
}

func MetricsHandler() http.Handler {
	return promhttp.HandlerFor(registry, promhttp.HandlerOpts{})
}

func RecordTaskRun(_ context.Context, taskType string, status string, durationSeconds float64) {
	taskRuns.WithLabelValues(taskType, status).Inc()
	if durationSeconds >= 0 {
		taskDuration.WithLabelValues(taskType, status).Observe(durationSeconds)
	}
}

func RecordCrawlerArticle(_ context.Context, source string, sourceType string, status string, count int) {
	if count <= 0 {
		return
	}
	crawlerArticles.WithLabelValues(source, sourceType, status).Add(float64(count))
}

func RecordGRPCClient(_ context.Context, method string, statusCode string, durationSeconds float64) {
	grpcClientRequests.WithLabelValues(method, statusCode).Inc()
	grpcClientDuration.WithLabelValues(method, statusCode).Observe(nonNegativeSeconds(durationSeconds))
}

func RecordRecommendation(_ context.Context, decision string, count int) {
	if count <= 0 {
		return
	}
	recommendationItems.WithLabelValues(decision).Add(float64(count))
}

func RecordPostGenerated(_ context.Context, status string, count int) {
	if count <= 0 {
		return
	}
	postsGenerated.WithLabelValues(status).Add(float64(count))
}

func RecordUserFeedback(_ context.Context, feedbackType string, status string, count int) {
	if count <= 0 {
		return
	}
	feedbackReceived.WithLabelValues(feedbackType, status).Add(float64(count))
}

func nonNegativeSeconds(value float64) float64 {
	if value < 0 {
		return 0
	}
	return value
}
```

- [ ] **Step 5: Run Go observability tests to verify they pass**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\goframe-backend
go test ./internal/observability -count=1
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
git add goframe-backend/go.mod goframe-backend/go.sum goframe-backend/internal/observability
git commit -m "feat: add go observability foundation"
```

## Task 2: GoFrame HTTP, gRPC, and Business Metrics

**Files:**
- Modify: `goframe-backend/main.go`
- Modify: `goframe-backend/internal/handler/handler.go`
- Modify: `goframe-backend/internal/grpcclient/client.go`
- Create: `goframe-backend/internal/grpcclient/client_test.go`
- Modify: `goframe-backend/internal/logic/harness/harness.go`
- Modify: `goframe-backend/internal/logic/harness/crawler_test.go`

- [ ] **Step 1: Write failing gRPC client trace propagation test**

Create `goframe-backend/internal/grpcclient/client_test.go`:

```go
package grpcclient

import (
	"context"
	"net"
	"strings"
	"testing"

	"knowledge-post-agent/goframe-backend/internal/agentpb"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
)

type recordingAgentServer struct {
	agentpb.UnimplementedAgentServiceServer
	traceparent string
}

func (server *recordingAgentServer) HealthCheck(ctx context.Context, _ *agentpb.HealthCheckRequest) (*agentpb.HealthCheckResponse, error) {
	md, _ := metadata.FromIncomingContext(ctx)
	values := md.Get("traceparent")
	if len(values) > 0 {
		server.traceparent = values[0]
	}
	return &agentpb.HealthCheckResponse{Status: "SERVING"}, nil
}

func TestClientInjectsTraceContext(t *testing.T) {
	otel.SetTextMapPropagator(propagation.TraceContext{})
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer listener.Close()
	server := grpc.NewServer()
	recording := &recordingAgentServer{}
	agentpb.RegisterAgentServiceServer(server, recording)
	go func() {
		_ = server.Serve(listener)
	}()
	defer server.Stop()

	ctx, span := otel.Tracer("grpcclient-test").Start(context.Background(), "client-call")
	defer span.End()
	client, err := NewWithDialOptions(
		ctx,
		listener.Addr().String(),
		0,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		t.Fatalf("new client: %v", err)
	}
	defer client.Close()

	if _, err := client.HealthCheck(ctx); err != nil {
		t.Fatalf("healthcheck: %v", err)
	}
	if !strings.HasPrefix(recording.traceparent, "00-") {
		t.Fatalf("missing traceparent: %q", recording.traceparent)
	}
}
```

- [ ] **Step 2: Run gRPC client test to verify it fails**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\goframe-backend
go test ./internal/grpcclient -run TestClientInjectsTraceContext -count=1
```

Expected: FAIL because `NewWithDialOptions` does not exist or gRPC client does not inject trace context.

- [ ] **Step 3: Implement gRPC client instrumentation seam**

Modify `goframe-backend/internal/grpcclient/client.go`:

```go
import (
	"knowledge-post-agent/goframe-backend/internal/observability"

	"go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"
)

func New(ctx context.Context, address string, dialTimeout time.Duration) (*Client, error) {
	return NewWithDialOptions(ctx, address, dialTimeout, grpc.WithTransportCredentials(insecure.NewCredentials()))
}

func NewWithDialOptions(ctx context.Context, address string, dialTimeout time.Duration, opts ...grpc.DialOption) (*Client, error) {
	if dialTimeout <= 0 {
		dialTimeout = 5 * time.Second
	}
	started := time.Now()
	dialCtx, cancel := context.WithTimeout(ctx, dialTimeout)
	defer cancel()

	dialOptions := []grpc.DialOption{
		grpc.WithBlock(),
		grpc.WithStatsHandler(otelgrpc.NewClientHandler()),
	}
	dialOptions = append(dialOptions, opts...)
	conn, err := grpc.DialContext(dialCtx, address, dialOptions...)
	if err != nil {
		observability.RecordGRPCClient(ctx, "AgentService/Dial", "error", time.Since(started).Seconds())
		return nil, err
	}
	observability.RecordGRPCClient(ctx, "AgentService/Dial", "OK", time.Since(started).Seconds())
	return &Client{conn: conn, service: agentpb.NewAgentServiceClient(conn)}, nil
}

func (c *Client) HealthCheck(ctx context.Context) (*agentpb.HealthCheckResponse, error) {
	started := time.Now()
	response, err := c.service.HealthCheck(ctx, &agentpb.HealthCheckRequest{Client: "goframe-backend"})
	if err != nil {
		observability.RecordGRPCClient(ctx, "AgentService/HealthCheck", "error", time.Since(started).Seconds())
		return nil, err
	}
	observability.RecordGRPCClient(ctx, "AgentService/HealthCheck", "OK", time.Since(started).Seconds())
	return response, nil
}
```

Update `ProcessArticles`:

```go
func (c *Client) ProcessArticles(ctx context.Context, request *agentpb.ProcessArticlesRequest) (*agentpb.ProcessArticlesResponse, error) {
	started := time.Now()
	response, err := c.service.ProcessArticles(ctx, request)
	if err != nil {
		observability.RecordGRPCClient(ctx, "AgentService/ProcessArticles", "error", time.Since(started).Seconds())
		return nil, err
	}
	observability.RecordGRPCClient(ctx, "AgentService/ProcessArticles", "OK", time.Since(started).Seconds())
	return response, nil
}
```

Update `ProcessFeedback`:

```go
func (c *Client) ProcessFeedback(ctx context.Context, request *agentpb.ProcessFeedbackRequest) (*agentpb.ProcessFeedbackResponse, error) {
	started := time.Now()
	response, err := c.service.ProcessFeedback(ctx, request)
	if err != nil {
		observability.RecordGRPCClient(ctx, "AgentService/ProcessFeedback", "error", time.Since(started).Seconds())
		return nil, err
	}
	observability.RecordGRPCClient(ctx, "AgentService/ProcessFeedback", "OK", time.Since(started).Seconds())
	return response, nil
}
```

- [ ] **Step 4: Run gRPC client test to verify it passes**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\goframe-backend
go test ./internal/grpcclient -run TestClientInjectsTraceContext -count=1
```

Expected: PASS.

- [ ] **Step 5: Write failing GoFrame business metrics test**

Append to `goframe-backend/internal/logic/harness/crawler_test.go`:

```go
func TestRunArticlesRecordsTaskAndCrawlerMetrics(t *testing.T) {
	observability.ResetMetricsForTest()
	store := &fakeArticleStore{}
	sourceClient := &fakeSourceCrawler{results: map[string]crawler.SourceResult{
		"working": {
			Source: crawler.Source{Name: "working", Type: crawler.SourceTypeMock},
			Status: "success",
			Articles: []model.Article{{
				ID: "article-working", Source: "working", SourceType: "mock", FetchStatus: "success", Content: "processable content",
			}},
			ItemsFound: 1,
		},
	}}
	harness := newWithDependencies(testCrawlerConfig("working"), store, sourceClient)
	harness.processArticlesFunc = func(_ context.Context, runID string, _ []model.Article, _ map[string]string, _ *stepRecorder) (*agentpb.ProcessArticlesResponse, error) {
		return &agentpb.ProcessArticlesResponse{
			RunId: runID,
			Results: []*agentpb.ArticleProcessResult{{
				ArticleId: "article-working",
				Keep: true,
				Score: 8,
				Summary: "summary",
				PostText: "post",
				CheckPass: true,
			}},
		}, nil
	}

	result := harness.RunArticles(context.Background())

	if result.Status != TaskStatusCompleted {
		t.Fatalf("unexpected status: %#v", result)
	}
	body := metricsBody(t)
	if !strings.Contains(body, `knowmate_task_runs_total{status="completed",task_type="articles"} 1`) {
		t.Fatalf("missing task metric: %s", body)
	}
	if !strings.Contains(body, `knowmate_crawler_articles_total{source="working",status="success",type="mock"} 1`) {
		t.Fatalf("missing crawler article metric: %s", body)
	}
	if !strings.Contains(body, `knowmate_recommendation_items_total{decision="kept"} 1`) {
		t.Fatalf("missing recommendation retention metric: %s", body)
	}
	if !strings.Contains(body, `knowmate_posts_generated_total{status="success"} 1`) {
		t.Fatalf("missing post generation metric: %s", body)
	}
}

func metricsBody(t *testing.T) string {
	t.Helper()
	recorder := httptest.NewRecorder()
	observability.MetricsHandler().ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	return recorder.Body.String()
}
```

Add imports to `crawler_test.go`:

```go
import (
	"net/http"
	"net/http/httptest"
	"strings"

	"knowledge-post-agent/goframe-backend/internal/observability"
)
```

Append to `goframe-backend/internal/logic/harness/feedback_test.go`:

```go
func TestProcessFeedbackRecordsFeedbackAndTaskMetrics(t *testing.T) {
	observability.ResetMetricsForTest()
	store := newFeedbackFakeStore()
	h := newWithDependencies(config.Config{Profile: config.ProfileConfig{UserID: "u1"}}, store, &fakeSourceCrawler{})
	h.processFeedbackFunc = store.processFeedback

	result := h.ProcessFeedback(context.Background(), FeedbackRequest{
		PostID: "p1", ArticleID: "a1", UserID: "u1", FeedbackText: "useful", FeedbackType: "text", Rating: 5,
	})

	if result.Status != TaskStatusCompleted {
		t.Fatalf("expected completed feedback task, got %#v", result)
	}
	body := metricsBody(t)
	for _, metric := range []string{
		`knowmate_feedback_received_total{feedback_type="text",status="received"} 1`,
		`knowmate_feedback_received_total{feedback_type="text",status="processed"} 1`,
		`knowmate_task_runs_total{status="completed",task_type="feedback"} 1`,
	} {
		if !strings.Contains(body, metric) {
			t.Fatalf("missing %s in %s", metric, body)
		}
	}
}
```

Add imports to `feedback_test.go`:

```go
import (
	"strings"

	"knowledge-post-agent/goframe-backend/internal/observability"
)
```

- [ ] **Step 6: Run business metrics test to verify it fails**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\goframe-backend
go test ./internal/logic/harness -run TestRunArticlesRecordsTaskAndCrawlerMetrics -count=1
```

Expected: FAIL because Harness does not record task/crawler metrics.

- [ ] **Step 7: Record GoFrame business metrics and initialize observability**

Modify `goframe-backend/internal/logic/harness/harness.go`:

Add the import:

```go
import "knowledge-post-agent/goframe-backend/internal/observability"
```

Replace the beginning of `runArticles`, from `func (h *Harness) runArticles...` through the `result := ...` line, with this block. The next statement after this block must be `task, err := h.startTask(...)`.

```go
func (h *Harness) runArticles(ctx context.Context, runID string, existing *model.TaskRun) RunArticlesResult {
	startedAt := time.Now()
	ctx = observability.WithRunID(ctx, runID)

	userID := h.cfg.Profile.UserID
	if existing != nil && existing.UserID != "" {
		userID = existing.UserID
	}
	result := RunArticlesResult{RunID: runID, Status: TaskStatusPending}
	defer func() {
		status := result.Status
		if status == "" || status == TaskStatusPending || status == TaskStatusRunning {
			status = TaskStatusFailed
		}
		observability.RecordTaskRun(ctx, TaskTypeArticles, status, time.Since(startedAt).Seconds())
	}()
```

Modify `fetchArticles` in the same file immediately after the `if result.Status == ""` block:

```go
		itemCount := result.ItemsFound
		if itemCount < len(result.Articles) {
			itemCount = len(result.Articles)
		}
		observability.RecordCrawlerArticle(ctx, result.Source.Name, string(result.Source.Type), result.Status, itemCount)
		finishedAt := time.Now().UTC()
```

Replace the beginning of `processFeedback`, from `func (h *Harness) processFeedback...` through the `result := ...` block, with this block. The next statement after this block must be `userID := firstNonEmpty(...)`.

```go
func (h *Harness) processFeedback(ctx context.Context, runID string, existing *model.TaskRun, req FeedbackRequest) FeedbackResult {
	startedAt := time.Now()
	ctx = observability.WithRunID(ctx, runID)

	result := FeedbackResult{RunID: runID, Status: TaskStatusPending}
	defer func() {
		status := result.Status
		if status == "" || status == TaskStatusPending || status == TaskStatusRunning {
			status = TaskStatusFailed
		}
		observability.RecordTaskRun(ctx, TaskTypeFeedback, status, time.Since(startedAt).Seconds())
	}()
```

In `processFeedback`, immediately after a successful `UpsertFeedbackReceived` and before the cached-feedback branch:

```go
	if inserted {
		observability.RecordUserFeedback(ctx, req.FeedbackType, "received", 1)
	}
```

In `processFeedback`, add the failure metric before each of these four existing `return result` statements:

- the branch where `MarkFeedbackProcessing(ctx, record.ID)` returns an error
- the branch where `callProcessFeedback(...)` returns an error, immediately after `MarkFeedbackFailed`
- the branch where `InsertUserProfileSnapshotVersion(...)` returns an error, immediately after `MarkFeedbackFailed`
- the branch where `MarkFeedbackCompleted(...)` returns an error

```go
	observability.RecordUserFeedback(ctx, req.FeedbackType, "failed", 1)
```

Immediately after `MarkFeedbackCompleted` succeeds, add:

```go
	observability.RecordUserFeedback(ctx, req.FeedbackType, "processed", 1)
```

Replace the beginning of `rebuildProfile`, from `func (h *Harness) rebuildProfile...` through the `result := ...` block, with this block. The next statement after this block must be `task, err := h.startTask(...)`.

```go
func (h *Harness) rebuildProfile(ctx context.Context, runID string, existing *model.TaskRun, req RebuildProfileRequest) RebuildProfileResult {
	startedAt := time.Now()
	ctx = observability.WithRunID(ctx, runID)

	result := RebuildProfileResult{
		RunID:  runID,
		Status: TaskStatusPending,
		UserID: firstNonEmpty(req.UserID, h.cfg.Profile.UserID),
	}
	defer func() {
		status := result.Status
		if status == "" || status == TaskStatusPending || status == TaskStatusRunning {
			status = TaskStatusFailed
		}
		observability.RecordTaskRun(ctx, TaskTypeProfileRebuild, status, time.Since(startedAt).Seconds())
	}()
```

In `persistAgentResults`, insert this block immediately after `mcpLogs = append(mcpLogs, protoMcpLogs(runID, item.McpCallLogs)...)`:

```go
		decision := "dropped"
		if item.Keep {
			decision = "kept"
		}
		observability.RecordRecommendation(ctx, decision, 1)
		if !item.Keep {
			observability.RecordPostGenerated(ctx, "skipped", 1)
			continue
		}
		postStatus := "success"
		if strings.TrimSpace(item.PostText) == "" || !item.CheckPass {
			postStatus = "failed"
		}
		observability.RecordPostGenerated(ctx, postStatus, 1)
```

Modify `goframe-backend/main.go`:

```go
shutdown, err := observability.Init(ctx, observability.OptionsFromEnv("goframe-backend"))
if err != nil {
	g.Log().Warningf(ctx, "observability init failed: %v", err)
} else {
	defer func() {
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = shutdown(shutdownCtx)
	}()
}
```

Modify `goframe-backend/internal/handler/handler.go` in `Register`:

```go
server.BindHandler("/metrics", func(r *ghttp.Request) {
	observability.MetricsHandler().ServeHTTP(r.Response.RawWriter(), r.Request)
})
```

The GoFrame v2 response exposes `RawWriter()`, so use that exact method for the Prometheus handler.

- [ ] **Step 8: Run GoFrame tests**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\goframe-backend
go test ./internal/grpcclient ./internal/logic/harness ./internal/handler ./internal/observability -count=1
```

Expected: PASS.

- [ ] **Step 9: Commit Task 2**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
git add goframe-backend/main.go goframe-backend/internal/handler/handler.go goframe-backend/internal/grpcclient goframe-backend/internal/logic/harness
git commit -m "feat: instrument goframe observability"
```

## Task 3: Python Observability Foundation

**Files:**
- Create: `python-agent/app/observability.py`
- Create: `python-agent/tests/test_observability.py`
- Modify: `python-agent/requirements.txt`
- Modify: `python-agent/server.py`

- [ ] **Step 1: Write failing Python observability tests**

Create `python-agent/tests/test_observability.py`:

```python
from __future__ import annotations

import json
import logging
import unittest

from opentelemetry import trace

from app.observability import (
    JSONFormatter,
    Metrics,
    clear_run_id,
    current_run_id,
    redact_sensitive,
    set_run_id,
)


class ObservabilityTest(unittest.TestCase):
    def tearDown(self) -> None:
        clear_run_id()

    def test_redact_sensitive_masks_nested_values_and_dsn(self) -> None:
        payload = {
            "authorization": "Bearer secret-token",
            "mysql_dsn": "app:apppass@tcp(mysql:3306)/knowledge_post_agent",
            "nested": {"api_key": "sk-secret", "items": [{"password": "plain"}]},
        }

        encoded = json.dumps(redact_sensitive(payload), ensure_ascii=False)

        for secret in ["secret-token", "apppass", "sk-secret", "plain"]:
            self.assertNotIn(secret, encoded)
        self.assertIn("[REDACTED]", encoded)

    def test_run_context_round_trip(self) -> None:
        set_run_id("run-python")

        self.assertEqual(current_run_id(), "run-python")

    def test_json_formatter_includes_trace_and_run_id(self) -> None:
        set_run_id("run-log")
        formatter = JSONFormatter(service_name="python-agent")
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("format-test"):
            record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello %s", ("world",), None)
            output = formatter.format(record)

        payload = json.loads(output)
        self.assertEqual(payload["service"], "python-agent")
        self.assertEqual(payload["run_id"], "run-log")
        self.assertEqual(payload["message"], "hello world")
        self.assertIn("trace_id", payload)
        self.assertIn("span_id", payload)

    def test_metrics_render_agent_and_llm_values(self) -> None:
        metrics = Metrics(namespace="knowmate_test")
        metrics.record_agent_run("filter", "success", 0.25)
        metrics.record_grpc_server("ProcessArticles", "OK", 0.02)
        metrics.record_llm_usage("mock", "mock-model", "summary", "success", 12, 7, 0.001, 0.1)

        text = metrics.render_text().decode("utf-8")

        self.assertIn("knowmate_test_agent_runs_total", text)
        self.assertIn("knowmate_test_grpc_server_duration_seconds", text)
        self.assertIn("knowmate_test_llm_tokens_total", text)
        self.assertIn("knowmate_test_llm_cost_usd_total", text)
```

- [ ] **Step 2: Run Python observability tests to verify they fail**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_observability.py -q
```

Expected: FAIL because `app.observability` does not exist.

- [ ] **Step 3: Add Python dependencies**

Append to `python-agent/requirements.txt`:

```text
opentelemetry-api>=1.30,<2
opentelemetry-sdk>=1.30,<2
opentelemetry-exporter-otlp-proto-grpc>=1.30,<2
opentelemetry-instrumentation-grpc>=0.51b0,<1
opentelemetry-instrumentation-logging>=0.51b0,<1
opentelemetry-instrumentation-starlette>=0.51b0,<1
prometheus-client>=0.21,<1
```

- [ ] **Step 4: Implement Python observability module**

Create `python-agent/app/observability.py`:

```python
from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import time
from typing import Any

from opentelemetry import metrics, propagate, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.instrumentation.grpc import GrpcInstrumentorServer
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

_run_id: contextvars.ContextVar[str] = contextvars.ContextVar("knowmate_run_id", default="")

SENSITIVE_KEYS = {
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

BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
KEY_VALUE_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|password|secret|cookie)\s*[:=]\s*([^\s,;]+)"
)
MYSQL_DSN_RE = re.compile(r"([A-Za-z0-9_.-]+):([^@]+)@tcp\(([^)]+)\)")


def set_run_id(run_id: str) -> None:
    _run_id.set(run_id or "")


def clear_run_id() -> None:
    _run_id.set("")


def current_run_id() -> str:
    return _run_id.get("")


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str):
        text = BEARER_RE.sub("Bearer [REDACTED]", value)
        text = KEY_VALUE_RE.sub(r"\1=[REDACTED]", text)
        return MYSQL_DSN_RE.sub(r"\1:[REDACTED]@tcp(\3)", text)
    return value


class JSONFormatter(logging.Formatter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        span_context = trace.get_current_span().get_span_context()
        payload: dict[str, Any] = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname.lower(),
            "service": self.service_name,
            "logger": record.name,
            "message": record.getMessage(),
            "run_id": current_run_id(),
            "trace_id": format(span_context.trace_id, "032x") if span_context.is_valid else "",
            "span_id": format(span_context.span_id, "016x") if span_context.is_valid else "",
        }
        if record.exc_info:
            payload["error_message"] = redact_sensitive(self.formatException(record.exc_info))
        return json.dumps(redact_sensitive(payload), ensure_ascii=False, sort_keys=True)


class Metrics:
    def __init__(self, namespace: str = "knowmate", registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.agent_runs = Counter(
            f"{namespace}_agent_runs_total",
            "Agent executions by agent and status.",
            ["agent", "status"],
            registry=self.registry,
        )
        self.agent_duration = Histogram(
            f"{namespace}_agent_duration_seconds",
            "Agent execution duration.",
            ["agent", "status"],
            registry=self.registry,
        )
        self.grpc_server_requests = Counter(
            f"{namespace}_grpc_server_requests_total",
            "gRPC server requests by method and status code.",
            ["method", "status_code"],
            registry=self.registry,
        )
        self.grpc_server_duration = Histogram(
            f"{namespace}_grpc_server_duration_seconds",
            "gRPC server request duration.",
            ["method", "status_code"],
            registry=self.registry,
        )
        self.llm_tokens = Counter(
            f"{namespace}_llm_tokens_total",
            "LLM token usage.",
            ["provider", "model", "task", "token_type"],
            registry=self.registry,
        )
        self.llm_cost = Counter(
            f"{namespace}_llm_cost_usd_total",
            "LLM cost in USD.",
            ["provider", "model", "task"],
            registry=self.registry,
        )
        self.llm_requests = Counter(
            f"{namespace}_llm_requests_total",
            "LLM requests by provider, model, task, and status.",
            ["provider", "model", "task", "status"],
            registry=self.registry,
        )
        self.llm_duration = Histogram(
            f"{namespace}_llm_duration_seconds",
            "LLM request duration.",
            ["provider", "model", "task", "status"],
            registry=self.registry,
        )
        self.mcp_tool_calls = Counter(
            f"{namespace}_mcp_tool_calls_total",
            "MCP tool calls.",
            ["server", "tool", "status"],
            registry=self.registry,
        )
        self.mcp_tool_duration = Histogram(
            f"{namespace}_mcp_tool_duration_seconds",
            "MCP tool call duration.",
            ["server", "tool", "status"],
            registry=self.registry,
        )

    def record_agent_run(self, agent: str, status: str, duration_seconds: float) -> None:
        self.agent_runs.labels(agent=agent, status=status).inc()
        self.agent_duration.labels(agent=agent, status=status).observe(max(duration_seconds, 0))

    def record_grpc_server(self, method: str, status_code: str, duration_seconds: float) -> None:
        self.grpc_server_requests.labels(method=method, status_code=status_code).inc()
        self.grpc_server_duration.labels(method=method, status_code=status_code).observe(max(duration_seconds, 0))

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
        self.llm_requests.labels(provider=provider, model=model, task=task, status=status).inc()
        self.llm_tokens.labels(provider=provider, model=model, task=task, token_type="prompt").inc(max(prompt_tokens, 0))
        self.llm_tokens.labels(provider=provider, model=model, task=task, token_type="completion").inc(max(completion_tokens, 0))
        self.llm_cost.labels(provider=provider, model=model, task=task).inc(max(cost_usd, 0))
        self.llm_duration.labels(provider=provider, model=model, task=task, status=status).observe(max(duration_seconds, 0))

    def record_mcp_tool(self, server: str, tool: str, status: str, duration_seconds: float) -> None:
        self.mcp_tool_calls.labels(server=server, tool=tool, status=status).inc()
        self.mcp_tool_duration.labels(server=server, tool=tool, status=status).observe(max(duration_seconds, 0))

    def render_text(self) -> bytes:
        return generate_latest(self.registry)


METRICS = Metrics()


def init_observability(service_name: str) -> None:
    propagate.set_global_textmap(CompositePropagator([TraceContextTextMapPropagator()]))
    GrpcInstrumentorServer().instrument()
    if os.getenv("OTEL_ENABLED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        configure_json_logging(service_name)
        return
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
    trace.set_tracer_provider(provider)
    configure_json_logging(service_name)


def configure_json_logging(service_name: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter(service_name))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def tracer(name: str):
    return trace.get_tracer(name)
```

- [ ] **Step 5: Initialize Python observability at startup**

Modify `python-agent/server.py`:

```python
from app.observability import init_observability

def main() -> None:
    settings = load_settings()
    init_observability("python-agent")
    serve(settings)
```

- [ ] **Step 6: Run Python observability tests**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_observability.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
git add python-agent/requirements.txt python-agent/server.py python-agent/app/observability.py python-agent/tests/test_observability.py
git commit -m "feat: add python observability foundation"
```

## Task 4: Python gRPC, Workflow, and LLM Metrics

**Files:**
- Modify: `python-agent/app/grpc_server.py`
- Modify: `python-agent/app/workflow/graph.py`
- Modify: `python-agent/app/tools/llm_tool.py`
- Create: `python-agent/tests/test_grpc_observability.py`

- [ ] **Step 1: Write failing gRPC run context test**

Create `python-agent/tests/test_grpc_observability.py`:

```python
from __future__ import annotations

import unittest

import agent_pb2
from app.config import Settings
from app.grpc_server import AgentService
from app.observability import clear_run_id, current_run_id


class GrpcObservabilityTest(unittest.TestCase):
    def tearDown(self) -> None:
        clear_run_id()

    def test_process_articles_sets_and_clears_run_context(self) -> None:
        service = AgentService(Settings(mock_mcp=True))
        seen_run_ids: list[str] = []
        original = service.workflow.process_articles

        def wrapped(request):
            seen_run_ids.append(current_run_id())
            return original(request)

        service.workflow.process_articles = wrapped

        service.ProcessArticles(
            agent_pb2.ProcessArticlesRequest(
                run_id="grpc-observe",
                mcp_policy=agent_pb2.McpPolicy(mock_transport=True),
                articles=[
                    agent_pb2.Article(
                        article_id="a1",
                        url="https://example.com/a1",
                        title="A1",
                        raw_text="Agent observability content",
                    )
                ],
            ),
            None,
        )

        self.assertEqual(seen_run_ids, ["grpc-observe"])
        self.assertEqual(current_run_id(), "")
```

- [ ] **Step 2: Run gRPC run context test to verify it fails**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_grpc_observability.py -q
```

Expected: FAIL because gRPC methods do not set and clear `app.observability` run context.

- [ ] **Step 3: Implement gRPC run context and RPC metrics**

Modify `python-agent/app/grpc_server.py`:

```python
import time
from app.observability import METRICS, clear_run_id, set_run_id, tracer

def _status_name(context: grpc.ServicerContext | None) -> str:
    if context is None:
        return "OK"
    code = context.code()
    return code.name if code is not None else "OK"

class AgentService(agent_pb2_grpc.AgentServiceServicer):
    def ProcessArticles(self, request: agent_pb2.ProcessArticlesRequest, context: grpc.ServicerContext):
        started = time.perf_counter()
        set_run_id(request.run_id)
        with tracer(__name__).start_as_current_span("AgentService.ProcessArticles") as span:
            span.set_attribute("run_id", request.run_id)
            span.set_attribute("article_count", len(request.articles))
            try:
                response = self.response_cache.get_or_compute(
                    _request_key("ProcessArticles", request),
                    agent_pb2.ProcessArticlesResponse,
                    lambda: self._process_articles(request),
                )
                METRICS.record_agent_run("grpc.ProcessArticles", "success", time.perf_counter() - started)
                METRICS.record_grpc_server("ProcessArticles", "OK", time.perf_counter() - started)
                return response
            except Exception as exc:
                span.record_exception(exc)
                METRICS.record_agent_run("grpc.ProcessArticles", "failed", time.perf_counter() - started)
                METRICS.record_grpc_server("ProcessArticles", "error", time.perf_counter() - started)
                raise
            finally:
                clear_run_id()
```

Update `ProcessFeedback`:

```python
    def ProcessFeedback(self, request: agent_pb2.ProcessFeedbackRequest, context: grpc.ServicerContext):
        if not request.run_id:
            _invalid_argument(context, "run_id is required")
        if not request.feedback:
            _invalid_argument(context, "at least one feedback item is required")
        if len(request.feedback) > self.settings.max_feedback_per_request:
            _invalid_argument(
                context,
                f"feedback count exceeds max_feedback_per_request={self.settings.max_feedback_per_request}",
            )
        started = time.perf_counter()
        set_run_id(request.run_id)
        with tracer(__name__).start_as_current_span("AgentService.ProcessFeedback") as span:
            span.set_attribute("run_id", request.run_id)
            span.set_attribute("feedback_count", len(request.feedback))
            try:
                response = self.response_cache.get_or_compute(
                    _request_key("ProcessFeedback", request),
                    agent_pb2.ProcessFeedbackResponse,
                    lambda: self._process_feedback(request),
                )
                METRICS.record_agent_run("grpc.ProcessFeedback", "success", time.perf_counter() - started)
                METRICS.record_grpc_server("ProcessFeedback", "OK", time.perf_counter() - started)
                return response
            except Exception as exc:
                span.record_exception(exc)
                METRICS.record_agent_run("grpc.ProcessFeedback", "failed", time.perf_counter() - started)
                METRICS.record_grpc_server("ProcessFeedback", "error", time.perf_counter() - started)
                raise
            finally:
                clear_run_id()
```

- [ ] **Step 4: Run gRPC run context test**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_grpc_observability.py -q
```

Expected: PASS.

- [ ] **Step 5: Write failing workflow Agent metrics test**

Append to `python-agent/tests/test_observability.py`:

```python
    def test_workflow_records_agent_metrics(self) -> None:
        from app.config import Settings
        from app.workflow import ArticleWorkflow
        from app.observability import METRICS

        before = METRICS.render_text().decode("utf-8")
        workflow = ArticleWorkflow(Settings(mock_mcp=True))
        workflow.process_articles(
            {
                "run_id": "agent-metrics",
                "mcp_policy": {"mock_transport": True},
                "articles": [
                    {
                        "article_id": "a1",
                        "url": "https://example.com/a1",
                        "title": "A1",
                        "raw_text": "Agent metrics content",
                    }
                ],
            }
        )
        after = METRICS.render_text().decode("utf-8")

        self.assertNotEqual(before, after)
        self.assertIn('agent="filter"', after)
        self.assertIn('agent="summary"', after)
        self.assertIn('agent="rewrite"', after)
        self.assertIn('agent="check"', after)
```

- [ ] **Step 6: Run workflow Agent metrics test to verify it fails**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_observability.py::ObservabilityTest::test_workflow_records_agent_metrics -q
```

Expected: FAIL because workflow does not record Agent metrics.

- [ ] **Step 7: Instrument workflow Agent execution**

Modify `python-agent/app/workflow/graph.py`:

```python
import time
from app.observability import METRICS, tracer

def _run_agent_with_observability(agent, state: JsonDict) -> JsonDict:
    started = time.perf_counter()
    status = "success"
    with tracer(__name__).start_as_current_span(f"agent.{agent.name}") as span:
        span.set_attribute("agent.name", agent.name)
        span.set_attribute("run_id", str(state.get("run_id", "")))
        try:
            return agent.run(state)
        except Exception as exc:
            status = "failed"
            span.record_exception(exc)
            span.set_attribute("error_type", type(exc).__name__)
            raise
        finally:
            METRICS.record_agent_run(agent.name, status, time.perf_counter() - started)

def _run_article_sequential(self, state: JsonDict) -> JsonDict:
    for agent in [self.filter_agent, self.summary_agent, self.rewrite_agent, self.check_agent]:
        state = _run_agent_with_observability(agent, state)
    return state

def _run_feedback_sequential(self, state: JsonDict) -> JsonDict:
    for agent in [self.feedback_agent, self.memory_agent]:
        state = _run_agent_with_observability(agent, state)
    return state
```

For LangGraph nodes, register wrappers instead of raw `agent.run`:

```python
graph.add_node("filter", lambda state: _run_agent_with_observability(self.filter_agent, state))
```

- [ ] **Step 8: Instrument LLM usage**

Modify `python-agent/app/tools/llm_tool.py`:

```python
import time
from app.observability import METRICS, redact_sensitive, tracer

def _estimate_tokens(text: str) -> int:
    return max(len(text) // 4, 1) if text else 0

def _estimated_cost_usd(provider: str, prompt_tokens: int, completion_tokens: int) -> float:
    if provider == "mock":
        return 0.0
    return ((prompt_tokens + completion_tokens) / 1_000_000) * 0.15
```

Wrap `_generate_structured` primary call:

```python
started = time.perf_counter()
provider = self.client.provider_name
prompt_tokens = _estimate_tokens(system_prompt) + _estimate_tokens(user_prompt)
with tracer(__name__).start_as_current_span(f"llm.{task}") as span:
    span.set_attribute("llm.provider", provider)
    span.set_attribute("llm.task", task)
    try:
        raw = self.client.complete_json(task, system_prompt, user_prompt)
        completion_tokens = _estimate_tokens(raw)
        METRICS.record_llm_usage(provider, getattr(self.client, "model", provider), task, "success", prompt_tokens, completion_tokens, _estimated_cost_usd(provider, prompt_tokens, completion_tokens), time.perf_counter() - started)
        return _validate_schema(schema, _parse_json(raw))
    except Exception as first_error:
        span.record_exception(first_error)
        LOGGER.warning("LLM %s output failed validation for %s: %s", provider, task, redact_sensitive(str(first_error)))
```

Keep existing repair/fallback behavior; record `status="fallback"` when fallback returns.

- [ ] **Step 9: Run Python Agent observability tests**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_observability.py tests/test_grpc_observability.py tests/test_workflow.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit Task 4**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
git add python-agent/app/grpc_server.py python-agent/app/workflow/graph.py python-agent/app/tools/llm_tool.py python-agent/tests/test_observability.py python-agent/tests/test_grpc_observability.py
git commit -m "feat: instrument python agent observability"
```

## Task 5: MCP Client and Server Observability

**Files:**
- Modify: `python-agent/app/mcp/base_client.py`
- Modify: `python-agent/app/mcp/sdk_transport.py`
- Create: `python-agent/tests/test_mcp_observability.py`
- Create: `mcp-servers/common/observability.py`
- Modify: `mcp-servers/common/simple_http_mcp.py`
- Modify: `mcp-servers/requirements.txt`
- Create: `mcp-servers/tests/test_observability.py`

- [ ] **Step 1: Write failing MCP client metrics and trace header tests**

Create `python-agent/tests/test_mcp_observability.py`:

```python
from __future__ import annotations

import unittest

from opentelemetry import trace

from app.config import McpServerSettings
from app.mcp.sdk_transport import OfficialMcpTransport
from app.observability import METRICS
from tests.test_mcp_client import RecordingTransport, TestClient
from app.mcp import MCPPolicy


class RecordingHTTPClient:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}


class McpObservabilityTest(unittest.TestCase):
    def test_base_client_records_mcp_metrics(self) -> None:
        before = METRICS.render_text().decode("utf-8")
        client = TestClient(RecordingTransport(), policy=MCPPolicy({"filter": {"embed_text"}}))

        client.call_tool("embed_text", {"text": "hello"}, agent_name="filter", run_id="mcp-metrics")

        after = METRICS.render_text().decode("utf-8")
        self.assertNotEqual(before, after)
        self.assertIn("knowmate_mcp_tool_calls_total", after)
        self.assertIn('server="embedding-mcp"', after)
        self.assertIn('tool="embed_text"', after)

    def test_http_headers_include_traceparent(self) -> None:
        transport = OfficialMcpTransport(
            {"embedding-mcp": McpServerSettings(transport="streamable_http", url="http://127.0.0.1:1/mcp")},
            timeout_seconds=1,
        )
        carrier: dict[str, str] = {}
        with trace.get_tracer(__name__).start_as_current_span("mcp-http"):
            transport._inject_trace_headers(carrier)

        self.assertIn("traceparent", carrier)
```

- [ ] **Step 2: Run MCP client observability tests to verify they fail**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_mcp_observability.py -q
```

Expected: FAIL because MCP metrics and `_inject_trace_headers` do not exist.

- [ ] **Step 3: Implement MCP client metrics and trace header injection**

Modify `python-agent/app/mcp/base_client.py`:

```python
from app.observability import METRICS, redact_sensitive

def _result(...):
    METRICS.record_mcp_tool(
        self.server_name,
        tool_name,
        status,
        latency_ms / 1000,
    )
    return McpCallResult(...)
```

Replace the local `redact_sensitive` implementation with:

```python
from app.observability import redact_sensitive
```

Modify `python-agent/app/mcp/sdk_transport.py`:

```python
from opentelemetry import propagate

def _inject_trace_headers(self, headers: dict[str, str]) -> None:
    propagate.inject(headers)

async def _connect(self, server_name: str) -> _Connection:
    headers = dict(config.headers)
    self._inject_trace_headers(headers)
    http_client = await stack.enter_async_context(
        create_mcp_http_client(headers=headers or None, timeout=self.timeout_seconds)
    )
```

- [ ] **Step 4: Run MCP client observability tests**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_mcp_observability.py tests/test_mcp_client.py -q
```

Expected: PASS.

- [ ] **Step 5: Write failing MCP server observability tests**

Create `mcp-servers/tests/test_observability.py`:

```python
from __future__ import annotations

import unittest

from common.observability import Metrics, extract_trace_context, redact_sensitive
from common.simple_http_mcp import ToolError, ToolSpec, create_server


class McpServerObservabilityTest(unittest.TestCase):
    def test_redact_sensitive_masks_headers(self) -> None:
        encoded = str(redact_sensitive({"authorization": "Bearer server-secret"}))

        self.assertNotIn("server-secret", encoded)

    def test_metrics_render_tool_call(self) -> None:
        metrics = Metrics(namespace="knowmate_test_mcp")
        metrics.record_tool_call("embedding-mcp", "embed_text", "success", 0.1)

        text = metrics.render_text().decode("utf-8")
        self.assertIn("knowmate_test_mcp_mcp_tool_calls_total", text)
        self.assertIn('tool="embed_text"', text)

    def test_create_server_registers_metrics_route(self) -> None:
        server = create_server(
            "test-mcp",
            7999,
            [ToolSpec(name="echo", description="echo", input_schema={"type": "object"}, output_schema={}, examples=[])],
            lambda name, payload: {"ok": True},
        )

        paths = {getattr(route, "path", "") for route in server._custom_starlette_routes}
        self.assertIn("/metrics", paths)
```

- [ ] **Step 6: Run MCP server observability tests to verify they fail**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers
python -m pytest tests/test_observability.py -q
```

Expected: FAIL because `common.observability` and `/metrics` route do not exist.

- [ ] **Step 7: Implement MCP server observability**

Append dependencies to `mcp-servers/requirements.txt`:

```text
opentelemetry-api>=1.30,<2
opentelemetry-sdk>=1.30,<2
opentelemetry-exporter-otlp-proto-grpc>=1.30,<2
opentelemetry-instrumentation-starlette>=0.51b0,<1
prometheus-client>=0.21,<1
```

Create `mcp-servers/common/observability.py`:

```python
from __future__ import annotations

import re
import time
from typing import Any

from opentelemetry import propagate, trace
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

SENSITIVE_KEYS = {"authorization", "api_key", "token", "password", "secret", "cookie", "set-cookie"}
BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else redact_sensitive(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str):
        return BEARER_RE.sub("Bearer [REDACTED]", value)
    return value


def extract_trace_context(headers: dict[str, str]):
    return propagate.extract(headers)


class Metrics:
    def __init__(self, namespace: str = "knowmate", registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.tool_calls = Counter(
            f"{namespace}_mcp_tool_calls_total",
            "MCP tool calls.",
            ["server", "tool", "status"],
            registry=self.registry,
        )
        self.tool_duration = Histogram(
            f"{namespace}_mcp_tool_duration_seconds",
            "MCP tool duration.",
            ["server", "tool", "status"],
            registry=self.registry,
        )
        self.tool_failures = Counter(
            f"{namespace}_mcp_tool_failures_total",
            "MCP tool failures.",
            ["server", "tool", "error_type"],
            registry=self.registry,
        )

    def record_tool_call(self, server: str, tool: str, status: str, duration_seconds: float, error_type: str = "") -> None:
        self.tool_calls.labels(server=server, tool=tool, status=status).inc()
        self.tool_duration.labels(server=server, tool=tool, status=status).observe(max(duration_seconds, 0))
        if error_type:
            self.tool_failures.labels(server=server, tool=tool, error_type=error_type).inc()

    def render_text(self) -> bytes:
        return generate_latest(self.registry)


METRICS = Metrics()


def record_tool(server_name: str, tool_name: str, handler):
    started = time.perf_counter()
    status = "success"
    error_type = ""
    with trace.get_tracer(__name__).start_as_current_span(f"mcp.tool.{tool_name}") as span:
        span.set_attribute("mcp.server", server_name)
        span.set_attribute("mcp.tool", tool_name)
        try:
            return handler()
        except Exception as exc:
            status = "failed"
            error_type = type(exc).__name__
            span.record_exception(exc)
            raise
        finally:
            METRICS.record_tool_call(server_name, tool_name, status, time.perf_counter() - started, error_type)
```

Modify `mcp-servers/common/simple_http_mcp.py`:

```python
from starlette.responses import PlainTextResponse
from common.observability import METRICS, record_tool

@server._mcp_server.call_tool()
async def call_tool(name: str, arguments: JsonDict) -> JsonDict:
    if name not in tool_map:
        raise ToolError(f"unknown tool `{name}`", code=-32601, data={"tool": name})
    return record_tool(name=name, server_name=name, handler=lambda: handler(name, arguments))

@server.custom_route("/metrics", methods=["GET"], include_in_schema=False)
async def metrics(_request: Request) -> PlainTextResponse:
    return PlainTextResponse(METRICS.render_text().decode("utf-8"), media_type="text/plain; version=0.0.4")
```

Use this helper signature in `mcp-servers/common/observability.py`:

```python
def record_tool(server_name: str, tool_name: str, handler):
    started = time.perf_counter()
    status = "success"
    error_type = ""
    with trace.get_tracer(__name__).start_as_current_span(f"mcp.tool.{tool_name}") as span:
        span.set_attribute("mcp.server", server_name)
        span.set_attribute("mcp.tool", tool_name)
        try:
            return handler()
        except Exception as exc:
            status = "failed"
            error_type = type(exc).__name__
            span.record_exception(exc)
            raise
        finally:
            METRICS.record_tool_call(server_name, tool_name, status, time.perf_counter() - started, error_type)
```

- [ ] **Step 8: Run MCP server tests**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers
python -m pytest tests/test_observability.py tests/test_http_mcp.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit Task 5**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
git add python-agent/app/mcp/base_client.py python-agent/app/mcp/sdk_transport.py python-agent/tests/test_mcp_observability.py mcp-servers/common/observability.py mcp-servers/common/simple_http_mcp.py mcp-servers/requirements.txt mcp-servers/tests/test_observability.py
git commit -m "feat: instrument mcp observability"
```

## Task 6: Observability Docker and Prometheus Configuration

**Files:**
- Create: `observability/otel-collector.yml`
- Create: `observability/prometheus.yml`
- Create: `observability/alertmanager.yml`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Create: `scripts/check_observability_config.ps1`

- [ ] **Step 1: Write failing observability config validation script**

Create `scripts/check_observability_config.ps1`:

```powershell
$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$required = @(
  "observability/otel-collector.yml",
  "observability/prometheus.yml",
  "observability/alerts.yml",
  "observability/alertmanager.yml",
  "observability/grafana/provisioning/datasources/prometheus.yml",
  "observability/grafana/provisioning/dashboards/dashboards.yml",
  "observability/grafana/dashboards/knowmate-overview.json"
)

foreach ($relative in $required) {
  $path = Join-Path $root $relative
  if (-not (Test-Path $path)) {
    throw "Missing required observability file: $relative"
  }
}

$compose = Get-Content (Join-Path $root "docker-compose.yml") -Raw
foreach ($service in @("otel-collector", "prometheus", "grafana", "jaeger", "alertmanager")) {
  if ($compose -notmatch "(?m)^\s{2}$service:") {
    throw "docker-compose.yml missing service: $service"
  }
}

$dashboard = Get-Content (Join-Path $root "observability/grafana/dashboards/knowmate-overview.json") -Raw | ConvertFrom-Json
if (-not $dashboard.title) {
  throw "Grafana dashboard must contain title"
}

Write-Host "Observability config files look valid."
```

- [ ] **Step 2: Run config validation to verify it fails**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
powershell -ExecutionPolicy Bypass -File scripts/check_observability_config.ps1
```

Expected: FAIL because observability config files and compose services are not present.

- [ ] **Step 3: Add OTel Collector config**

Create `observability/otel-collector.yml`:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch: {}

exporters:
  otlp/jaeger:
    endpoint: jaeger:4317
    tls:
      insecure: true
  debug:
    verbosity: basic

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/jaeger, debug]
```

- [ ] **Step 4: Add Prometheus and Alertmanager configs**

Create `observability/prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - /etc/prometheus/alerts.yml

alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - alertmanager:9093

scrape_configs:
  - job_name: prometheus
    static_configs:
      - targets: ["prometheus:9090"]
  - job_name: goframe-backend
    metrics_path: /metrics
    static_configs:
      - targets: ["goframe-backend:8080"]
  - job_name: python-agent
    metrics_path: /metrics
    static_configs:
      - targets: ["python-agent:9101"]
  - job_name: mcp-servers
    metrics_path: /metrics
    static_configs:
      - targets:
          - embedding-mcp:7001
          - fetch-mcp:7002
          - milvus-mcp:7003
          - neo4j-mcp:7004
  - job_name: otel-collector
    static_configs:
      - targets: ["otel-collector:8888"]
```

Create `observability/alertmanager.yml`:

```yaml
route:
  receiver: local-null
  group_by: ["alertname", "service"]
  group_wait: 10s
  group_interval: 1m
  repeat_interval: 1h

receivers:
  - name: local-null
```

- [ ] **Step 5: Modify docker-compose.yml**

Add services to `docker-compose.yml`:

```yaml
  jaeger:
    image: jaegertracing/all-in-one:1.63.0
    restart: unless-stopped
    environment:
      COLLECTOR_OTLP_ENABLED: "true"
    ports:
      - "${JAEGER_UI_PORT:-16686}:16686"
      - "4319:4317"

  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.116.1
    restart: unless-stopped
    command: ["--config=/etc/otel-collector.yml"]
    volumes:
      - ./observability/otel-collector.yml:/etc/otel-collector.yml:ro
    ports:
      - "${OTEL_GRPC_PORT:-4317}:4317"
      - "${OTEL_HTTP_PORT:-4318}:4318"
    depends_on:
      - jaeger

  alertmanager:
    image: prom/alertmanager:v0.28.0
    restart: unless-stopped
    command: ["--config.file=/etc/alertmanager/alertmanager.yml"]
    volumes:
      - ./observability/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
    ports:
      - "${ALERTMANAGER_PORT:-9093}:9093"

  prometheus:
    image: prom/prometheus:v3.0.1
    restart: unless-stopped
    command: ["--config.file=/etc/prometheus/prometheus.yml"]
    volumes:
      - ./observability/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./observability/alerts.yml:/etc/prometheus/alerts.yml:ro
      - prometheus-data:/prometheus
    ports:
      - "${PROMETHEUS_PORT:-9090}:9090"
    depends_on:
      - alertmanager

  grafana:
    image: grafana/grafana:11.4.0
    restart: unless-stopped
    environment:
      GF_SECURITY_ADMIN_USER: ${GRAFANA_ADMIN_USER:-admin}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-admin}
    volumes:
      - ./observability/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./observability/grafana/dashboards:/var/lib/grafana/dashboards:ro
      - grafana-data:/var/lib/grafana
    ports:
      - "${GRAFANA_PORT:-3000}:3000"
    depends_on:
      - prometheus
```

Add `OTEL_*` environment variables to `python-agent`, `goframe-backend`, and MCP services:

```yaml
      OTEL_ENABLED: ${OTEL_ENABLED:-true}
      OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4317
      OTEL_EXPORTER_OTLP_PROTOCOL: grpc
      OTEL_RESOURCE_ATTRIBUTES: deployment.environment=local,service.namespace=knowmate
```

Set `OTEL_SERVICE_NAME` per service.

Add volumes:

```yaml
  prometheus-data:
  grafana-data:
```

- [ ] **Step 6: Update .env.example**

Append to `.env.example`:

```dotenv
OTEL_ENABLED=true
OTEL_GRPC_PORT=4317
OTEL_HTTP_PORT=4318
PROMETHEUS_PORT=9090
GRAFANA_PORT=3000
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=admin
JAEGER_UI_PORT=16686
ALERTMANAGER_PORT=9093
```

- [ ] **Step 7: Commit Task 6 after Task 7 adds alerts/dashboard**

Do not commit this task until Task 7 creates `alerts.yml` and Grafana files, because the validation script expects them.

## Task 7: Alerts and Grafana Dashboard

**Files:**
- Create: `observability/alerts.yml`
- Create: `observability/grafana/provisioning/datasources/prometheus.yml`
- Create: `observability/grafana/provisioning/dashboards/dashboards.yml`
- Create: `observability/grafana/dashboards/knowmate-overview.json`

- [ ] **Step 1: Add Prometheus alert rules**

Create `observability/alerts.yml`:

```yaml
groups:
  - name: knowmate-service
    rules:
      - alert: KnowMateServiceDown
        expr: up{job=~"goframe-backend|python-agent|mcp-servers"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "KnowMate service {{ $labels.job }} is down"
          description: "{{ $labels.instance }} has been unavailable for more than 2 minutes."

      - alert: KnowMateTaskFailureRateHigh
        expr: |
          sum(rate(knowmate_task_runs_total{status=~"failed|partially_completed"}[5m]))
          /
          clamp_min(sum(rate(knowmate_task_runs_total[5m])), 1) > 0.2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "KnowMate task failure rate is high"
          description: "More than 20% of task runs failed or partially completed in the last 5 minutes."

      - alert: KnowMateCrawlerFailureRateHigh
        expr: |
          sum(rate(knowmate_crawler_articles_total{status!="success"}[5m]))
          /
          clamp_min(sum(rate(knowmate_crawler_articles_total[5m])), 1) > 0.3
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Crawler failure rate is high"
          description: "More than 30% of crawler article events are not successful."

      - alert: KnowMateGrpcClientFailureRateHigh
        expr: |
          sum(rate(knowmate_grpc_client_requests_total{status_code!="OK"}[5m]))
          /
          clamp_min(sum(rate(knowmate_grpc_client_requests_total[5m])), 1) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "gRPC client failure rate is high"
          description: "More than 10% of GoFrame gRPC client calls failed."

      - alert: KnowMateGrpcClientLatencyHigh
        expr: |
          histogram_quantile(0.95, sum by (le, method) (rate(knowmate_grpc_client_duration_seconds_bucket[5m]))) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "gRPC client latency is high"
          description: "GoFrame gRPC client P95 latency exceeded 10 seconds."

      - alert: KnowMateGrpcServerFailureRateHigh
        expr: |
          sum(rate(knowmate_grpc_server_requests_total{status_code!="OK"}[5m]))
          /
          clamp_min(sum(rate(knowmate_grpc_server_requests_total[5m])), 1) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "gRPC server failure rate is high"
          description: "More than 10% of Python Agent gRPC server calls failed."

      - alert: KnowMateGrpcServerLatencyHigh
        expr: |
          histogram_quantile(0.95, sum by (le, method) (rate(knowmate_grpc_server_duration_seconds_bucket[5m]))) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "gRPC server latency is high"
          description: "Python Agent gRPC server P95 latency exceeded 10 seconds."

      - alert: KnowMateMcpToolFailureRateHigh
        expr: |
          sum(rate(knowmate_mcp_tool_calls_total{status!="success"}[5m]))
          /
          clamp_min(sum(rate(knowmate_mcp_tool_calls_total[5m])), 1) > 0.15
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "MCP tool failure rate is high"
          description: "More than 15% of MCP tool calls failed."

      - alert: KnowMateMcpToolLatencyHigh
        expr: |
          histogram_quantile(0.95, sum by (le, server, tool) (rate(knowmate_mcp_tool_duration_seconds_bucket[5m]))) > 8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "MCP tool latency is high"
          description: "MCP tool P95 latency exceeded 8 seconds."

      - alert: KnowMateAgentFailureRateHigh
        expr: |
          sum(rate(knowmate_agent_runs_total{status!="success"}[5m]))
          /
          clamp_min(sum(rate(knowmate_agent_runs_total[5m])), 1) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Python Agent failure rate is high"
          description: "More than 10% of Agent executions failed."

      - alert: KnowMateLlmCostSpike
        expr: sum(increase(knowmate_llm_cost_usd_total[1h])) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "LLM cost spike"
          description: "LLM cost exceeded 5 USD in the last hour."

      - alert: KnowMateRecommendationRetentionLow
        expr: |
          (
            sum(rate(knowmate_recommendation_items_total{decision="kept"}[15m]))
            /
            clamp_min(sum(rate(knowmate_recommendation_items_total[15m])), 1)
          ) < 0.2
          and sum(rate(knowmate_recommendation_items_total[15m])) > 0
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Recommendation retention is low"
          description: "Fewer than 20% of recommendation candidates were retained."

      - alert: KnowMatePostGenerationFailureHigh
        expr: |
          (
            sum(rate(knowmate_posts_generated_total{status="failed"}[10m]))
            /
            clamp_min(sum(rate(knowmate_posts_generated_total{status=~"success|failed"}[10m])), 1)
          ) > 0.1
          and sum(rate(knowmate_posts_generated_total{status=~"success|failed"}[10m])) > 0
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Post generation failure rate is high"
          description: "More than 10% of generated posts failed validation or were empty."

      - alert: KnowMateFeedbackProcessingFailureHigh
        expr: |
          (
            sum(rate(knowmate_feedback_received_total{status="failed"}[10m]))
            /
            clamp_min(sum(rate(knowmate_feedback_received_total{status=~"processed|failed"}[10m])), 1)
          ) > 0.1
          and sum(rate(knowmate_feedback_received_total{status=~"processed|failed"}[10m])) > 0
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Feedback processing failure rate is high"
          description: "More than 10% of feedback processing events failed."
```

- [ ] **Step 2: Add Grafana provisioning**

Create `observability/grafana/provisioning/datasources/prometheus.yml`:

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
```

Create `observability/grafana/provisioning/dashboards/dashboards.yml`:

```yaml
apiVersion: 1

providers:
  - name: KnowMate
    orgId: 1
    folder: KnowMate
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
```

- [ ] **Step 3: Add Grafana overview dashboard**

Create `observability/grafana/dashboards/knowmate-overview.json`:

```json
{
  "uid": "knowmate-overview",
  "title": "KnowMate Observability Overview",
  "schemaVersion": 40,
  "version": 1,
  "refresh": "30s",
  "tags": ["knowmate", "observability"],
  "timezone": "browser",
  "panels": [
    {
      "id": 1,
      "type": "stat",
      "title": "Task Runs",
      "gridPos": {"h": 4, "w": 6, "x": 0, "y": 0},
      "targets": [{"expr": "sum(increase(knowmate_task_runs_total[1h]))", "legendFormat": "runs"}]
    },
    {
      "id": 2,
      "type": "timeseries",
      "title": "Task Failure Rate",
      "gridPos": {"h": 6, "w": 12, "x": 6, "y": 0},
      "targets": [
        {
          "expr": "sum(rate(knowmate_task_runs_total{status=~\"failed|partially_completed\"}[5m])) / clamp_min(sum(rate(knowmate_task_runs_total[5m])), 1)",
          "legendFormat": "failure rate"
        }
      ]
    },
    {
      "id": 3,
      "type": "timeseries",
      "title": "Crawler Articles",
      "gridPos": {"h": 6, "w": 12, "x": 0, "y": 6},
      "targets": [{"expr": "sum by (status) (rate(knowmate_crawler_articles_total[5m]))", "legendFormat": "{{status}}"}]
    },
    {
      "id": 4,
      "type": "timeseries",
      "title": "Agent Duration P95",
      "gridPos": {"h": 6, "w": 12, "x": 12, "y": 6},
      "targets": [
        {
          "expr": "histogram_quantile(0.95, sum by (le, agent) (rate(knowmate_agent_duration_seconds_bucket[5m])))",
          "legendFormat": "{{agent}}"
        }
      ]
    },
    {
      "id": 5,
      "type": "timeseries",
      "title": "MCP Tool Failure Rate",
      "gridPos": {"h": 6, "w": 12, "x": 0, "y": 12},
      "targets": [
        {
          "expr": "sum by (server, tool) (rate(knowmate_mcp_tool_calls_total{status!=\"success\"}[5m])) / clamp_min(sum by (server, tool) (rate(knowmate_mcp_tool_calls_total[5m])), 1)",
          "legendFormat": "{{server}} {{tool}}"
        }
      ]
    },
    {
      "id": 6,
      "type": "timeseries",
      "title": "LLM Cost USD",
      "gridPos": {"h": 6, "w": 12, "x": 12, "y": 12},
      "targets": [{"expr": "sum by (provider, model, task) (increase(knowmate_llm_cost_usd_total[1h]))", "legendFormat": "{{provider}} {{model}} {{task}}"}]
    },
    {
      "id": 7,
      "type": "timeseries",
      "title": "gRPC Client P95",
      "gridPos": {"h": 6, "w": 12, "x": 0, "y": 18},
      "targets": [{"expr": "histogram_quantile(0.95, sum by (le, method) (rate(knowmate_grpc_client_duration_seconds_bucket[5m])))", "legendFormat": "{{method}}"}]
    },
    {
      "id": 8,
      "type": "timeseries",
      "title": "gRPC Server Failure Rate",
      "gridPos": {"h": 6, "w": 12, "x": 12, "y": 18},
      "targets": [{"expr": "sum by (method) (rate(knowmate_grpc_server_requests_total{status_code!=\"OK\"}[5m])) / clamp_min(sum by (method) (rate(knowmate_grpc_server_requests_total[5m])), 1)", "legendFormat": "{{method}}"}]
    },
    {
      "id": 9,
      "type": "timeseries",
      "title": "MCP Tool P95",
      "gridPos": {"h": 6, "w": 12, "x": 0, "y": 24},
      "targets": [{"expr": "histogram_quantile(0.95, sum by (le, server, tool) (rate(knowmate_mcp_tool_duration_seconds_bucket[5m])))", "legendFormat": "{{server}} {{tool}}"}]
    },
    {
      "id": 10,
      "type": "stat",
      "title": "Recommendation Retention",
      "gridPos": {"h": 4, "w": 6, "x": 12, "y": 24},
      "targets": [{"expr": "sum(rate(knowmate_recommendation_items_total{decision=\"kept\"}[15m])) / clamp_min(sum(rate(knowmate_recommendation_items_total[15m])), 1)", "legendFormat": "retention"}]
    },
    {
      "id": 11,
      "type": "stat",
      "title": "Post Generation Success",
      "gridPos": {"h": 4, "w": 6, "x": 18, "y": 24},
      "targets": [{"expr": "sum(rate(knowmate_posts_generated_total{status=\"success\"}[10m])) / clamp_min(sum(rate(knowmate_posts_generated_total{status=~\"success|failed\"}[10m])), 1)", "legendFormat": "success"}]
    },
    {
      "id": 12,
      "type": "timeseries",
      "title": "User Feedback Events",
      "gridPos": {"h": 6, "w": 12, "x": 12, "y": 28},
      "targets": [{"expr": "sum by (feedback_type, status) (rate(knowmate_feedback_received_total[5m]))", "legendFormat": "{{feedback_type}} {{status}}"}]
    }
  ]
}
```

- [ ] **Step 4: Run config validation to verify Tasks 6 and 7 pass**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
powershell -ExecutionPolicy Bypass -File scripts/check_observability_config.ps1
```

Expected: PASS with `Observability config files look valid.`

- [ ] **Step 5: Commit Tasks 6 and 7**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
git add docker-compose.yml .env.example scripts/check_observability_config.ps1 observability
git commit -m "feat: add observability stack configuration"
```

## Task 8: Operations Documentation and Full Verification

**Files:**
- Create: `docs/observability.md`
- Modify: `README.md`

- [ ] **Step 1: Write docs content**

Create `docs/observability.md`:

```markdown
# 可观测性运维手册

## 本地启动

```powershell
docker compose up -d mysql embedding-mcp fetch-mcp milvus-mcp neo4j-mcp python-agent goframe-backend otel-collector jaeger prometheus alertmanager grafana
```

## 访问地址

- GoFrame API: http://127.0.0.1:8080
- Prometheus: http://127.0.0.1:9090
- Grafana: http://127.0.0.1:3000
- Jaeger: http://127.0.0.1:16686
- Alertmanager: http://127.0.0.1:9093

## Metrics URL

- GoFrame: http://127.0.0.1:8080/metrics
- Python Agent: http://127.0.0.1:9101/metrics
- embedding-mcp: http://127.0.0.1:7001/metrics
- fetch-mcp: http://127.0.0.1:7002/metrics
- milvus-mcp: http://127.0.0.1:7003/metrics
- neo4j-mcp: http://127.0.0.1:7004/metrics

## 关键指标

- `knowmate_task_runs_total`: 任务完成率和失败率。
- `knowmate_crawler_articles_total`: 抓取文章数量和失败状态。
- `knowmate_agent_runs_total`: 每个 Agent 执行次数和失败率。
- `knowmate_agent_duration_seconds`: 每个 Agent 延迟。
- `knowmate_grpc_client_requests_total`: GoFrame 到 Python Agent 的 gRPC 调用状态。
- `knowmate_grpc_client_duration_seconds`: GoFrame gRPC client 延迟。
- `knowmate_grpc_server_requests_total`: Python Agent gRPC server 调用状态。
- `knowmate_grpc_server_duration_seconds`: Python Agent gRPC server 延迟。
- `knowmate_mcp_tool_calls_total`: MCP Tool 调用状态。
- `knowmate_mcp_tool_duration_seconds`: MCP Tool 调用延迟。
- `knowmate_llm_tokens_total`: LLM token 使用量。
- `knowmate_llm_cost_usd_total`: LLM 估算成本。
- `knowmate_recommendation_items_total`: 推荐候选保留/丢弃计数。
- `knowmate_posts_generated_total`: 推文/知识笔记生成成功、失败和跳过计数。
- `knowmate_feedback_received_total`: 用户反馈接收、处理和失败计数。

## 日志字段

- `trace_id`: 分布式追踪 ID，在 Jaeger 中查询。
- `span_id`: 当前 span ID。
- `run_id`: KnowMate 业务任务 ID。
- `service`: 产生日志的服务。
- `level`: 日志级别。
- `message`: 事件说明。

## 排查流程

1. 从接口响应或日志中找到 `run_id`。
2. 在容器日志中搜索 `run_id`，确认任务状态。
3. 从同一条日志取得 `trace_id`。
4. 在 Jaeger 中按 `trace_id` 查询跨服务调用链。
5. 在 Grafana 中查看同一时间窗口的任务、Agent、MCP、LLM 指标。

## 本地端口冲突

如 MySQL 3306、Grafana 3000、Prometheus 9090 已被占用，在 `.env` 中设置：

```dotenv
MYSQL_PORT=3307
GRAFANA_PORT=3001
PROMETHEUS_PORT=9091
```
```

Append a short section to `README.md`:

```markdown
## Observability

The local compose stack includes OpenTelemetry Collector, Jaeger, Prometheus, Grafana, and Alertmanager.

Start the stack:

```powershell
docker compose up -d mysql embedding-mcp fetch-mcp milvus-mcp neo4j-mcp python-agent goframe-backend otel-collector jaeger prometheus alertmanager grafana
```

Open:

- Grafana: http://127.0.0.1:3000
- Prometheus: http://127.0.0.1:9090
- Jaeger: http://127.0.0.1:16686
- Alertmanager: http://127.0.0.1:9093

See `docs/observability.md` for metric names, log fields, alert rules, and runbook steps.
```

- [ ] **Step 2: Run config validation**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
powershell -ExecutionPolicy Bypass -File scripts/check_observability_config.ps1
```

Expected: PASS.

- [ ] **Step 3: Run Go tests**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\goframe-backend
go test ./... -count=1
go vet ./...
```

Expected: PASS.

- [ ] **Step 4: Run Python tests**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
python -m pytest python-agent/tests mcp-servers/tests -q
```

Expected: PASS.

- [ ] **Step 5: Run compose config check**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
docker compose config --quiet
```

Expected: exits 0. If Docker reports mirror EOF or image pull failures during a later smoke test, classify that as an environment issue before changing code.

- [ ] **Step 6: Commit Task 8**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
git add docs/observability.md README.md
git commit -m "docs: add observability operations guide"
```

## Self-Review Checklist

These checks describe the plan review result. Task checkboxes above remain open until implementation.

- [x] Every requirement from the design spec maps to at least one task.
- [x] `trace_id` and `run_id` are represented in Go, Python, MCP logs and spans.
- [x] gRPC trace context propagation is tested.
- [x] MCP HTTP trace header injection is tested.
- [x] Sensitive fields are tested in Go and Python.
- [x] Prometheus metrics cover crawler, Agent, gRPC, MCP, LLM, recommendation, posts, feedback, and tasks.
- [x] Grafana and alert rules are versioned under `observability/`.
- [x] Docker Compose includes OTel Collector, Prometheus, Grafana, Jaeger, and Alertmanager.
- [x] Verification commands do not require public network APIs.
