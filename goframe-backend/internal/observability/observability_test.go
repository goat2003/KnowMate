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
	if _, ok := record["span_id"]; !ok {
		t.Fatalf("missing span_id: %#v", record)
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
	for _, metric := range []string{"knowmate_grpc_client_duration_seconds", "knowmate_recommendation_items_total", "knowmate_posts_generated_total", "knowmate_feedback_received_total"} {
		if !strings.Contains(body, metric) {
			t.Fatalf("missing %s in %s", metric, body)
		}
	}
}
