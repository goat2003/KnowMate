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
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
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

func TestRedactSensitiveMasksTypedContainers(t *testing.T) {
	input := map[string]any{
		"headers": http.Header{
			"Authorization": []string{"Bearer header-secret"},
			"Cookie":        []string{"session=abc"},
		},
		"nested": []map[string]any{
			{"token": "nested-token"},
		},
	}

	encoded, err := json.Marshal(RedactSensitive(input))
	if err != nil {
		t.Fatalf("marshal redacted value: %v", err)
	}
	text := string(encoded)

	for _, secret := range []string{"header-secret", "session=abc", "nested-token"} {
		if strings.Contains(text, secret) {
			t.Fatalf("secret %q leaked in %s", secret, text)
		}
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
	installTestOTel(t)

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
	if _, ok := record["span_id"]; !ok {
		t.Fatalf("missing span_id: %#v", record)
	}
	if strings.Contains(text, "secret") {
		t.Fatalf("sensitive field leaked in log record: %s", text)
	}
}

func TestTraceHeadersRoundTripThroughPropagator(t *testing.T) {
	installTestOTel(t)

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

func TestOptionsFromEnvPreservesOTLPEndpointTransport(t *testing.T) {
	tests := []struct {
		name     string
		raw      string
		endpoint string
		insecure bool
	}{
		{name: "http", raw: "http://collector:4317", endpoint: "collector:4317", insecure: true},
		{name: "https", raw: "HTTPS://collector.example:4317", endpoint: "collector.example:4317", insecure: false},
		{name: "plain", raw: "collector:4317", endpoint: "collector:4317", insecure: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Setenv("OTEL_ENABLED", "true")
			t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", tt.raw)

			opts := OptionsFromEnv("goframe-backend")
			if opts.OTLPEndpoint != tt.endpoint {
				t.Fatalf("endpoint = %q, want %q", opts.OTLPEndpoint, tt.endpoint)
			}
			if opts.OTLPInsecure != tt.insecure {
				t.Fatalf("OTLPInsecure = %v, want %v", opts.OTLPInsecure, tt.insecure)
			}
			endpoint, insecure := normalizeOTLPOptions(opts)
			if endpoint != tt.endpoint {
				t.Fatalf("normalized endpoint = %q, want %q", endpoint, tt.endpoint)
			}
			if insecure != tt.insecure {
				t.Fatalf("normalized insecure = %v, want %v", insecure, tt.insecure)
			}
		})
	}
}

func TestMetricsHandlerExposesKnowmateMetric(t *testing.T) {
	ResetMetricsForTest()
	RecordTaskRun(context.Background(), "articles", "completed", 1.2)
	RecordCrawlerArticle(context.Background(), "rss", "feed", "fetched", 3)
	RecordGRPCClient(context.Background(), "AgentService/ProcessArticles", "OK", 0.2)
	RecordRecommendation(context.Background(), "kept", 2)
	RecordPostGenerated(context.Background(), "success", 1)
	RecordUserFeedback(context.Background(), "text", "received", 1)
	RecordCrawlerArticle(context.Background(), "rss", "feed", "ignored", 0)
	RecordRecommendation(context.Background(), "dropped", -1)
	RecordPostGenerated(context.Background(), "failed", -1)
	RecordUserFeedback(context.Background(), "text", "ignored", 0)

	recorder := httptest.NewRecorder()
	MetricsHandler().ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/metrics", bytes.NewReader(nil)))
	body := recorder.Body.String()
	if recorder.Code != http.StatusOK {
		t.Fatalf("unexpected status %d: %s", recorder.Code, body)
	}
	for _, metric := range []string{
		"knowmate_task_runs_total",
		"knowmate_task_duration_seconds",
		"knowmate_crawler_articles_total",
		"knowmate_grpc_client_requests_total",
		"knowmate_grpc_client_duration_seconds",
		"knowmate_recommendation_items_total",
		"knowmate_posts_generated_total",
		"knowmate_feedback_received_total",
	} {
		if !strings.Contains(body, metric) {
			t.Fatalf("missing %s in %s", metric, body)
		}
	}
	for _, line := range []string{
		`knowmate_task_runs_total{status="completed",task_type="articles"} 1`,
		`knowmate_task_duration_seconds_count{status="completed",task_type="articles"} 1`,
		`knowmate_crawler_articles_total{source="rss",status="fetched",type="feed"} 3`,
		`knowmate_grpc_client_requests_total{method="AgentService/ProcessArticles",status_code="OK"} 1`,
		`knowmate_grpc_client_duration_seconds_count{method="AgentService/ProcessArticles",status_code="OK"} 1`,
		`knowmate_recommendation_items_total{decision="kept"} 2`,
		`knowmate_posts_generated_total{status="success"} 1`,
		`knowmate_feedback_received_total{feedback_type="text",status="received"} 1`,
	} {
		if !strings.Contains(body, line) {
			t.Fatalf("missing metric line %q in %s", line, body)
		}
	}
	for _, absent := range []string{"ignored", "dropped", "failed"} {
		if strings.Contains(body, absent) {
			t.Fatalf("unexpected non-positive counter label %q in %s", absent, body)
		}
	}
}

func installTestOTel(t *testing.T) {
	t.Helper()

	previousPropagator := otel.GetTextMapPropagator()
	previousProvider := otel.GetTracerProvider()
	t.Cleanup(func() {
		otel.SetTextMapPropagator(previousPropagator)
		otel.SetTracerProvider(previousProvider)
	})

	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))
	otel.SetTracerProvider(sdktrace.NewTracerProvider())
}
