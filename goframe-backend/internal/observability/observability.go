package observability

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"io"
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
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
)

const (
	defaultOTLPEndpoint = "otel-collector:4317"
	redactedMarker      = "[REDACTED]"
)

type ShutdownFunc func(context.Context) error

type Options struct {
	ServiceName     string
	OTLPEndpoint    string
	OTLPInsecure    bool
	OTLPInsecureSet bool
	Enabled         bool
}

type runIDContextKey struct{}

var (
	bearerPattern   = regexp.MustCompile(`(?i)bearer\s+[^\s,;]+`)
	keyValuePattern = regexp.MustCompile(`(?i)(api[_-]?key|authorization|token|password|secret|cookie|refresh[_-]?token)=([^&\s,;]+)`)
	mysqlDSNPattern = regexp.MustCompile(`([^:\s/@]+):([^@\s]+)@tcp\(`)
)

func Init(ctx context.Context, opts Options) (ShutdownFunc, error) {
	configurePropagator()

	if !opts.Enabled {
		return func(context.Context) error { return nil }, nil
	}

	serviceName := strings.TrimSpace(opts.ServiceName)
	if serviceName == "" {
		serviceName = "knowmate"
	}

	endpoint, insecureTransport := normalizeOTLPOptions(opts)
	exporterOptions := []otlptracegrpc.Option{otlptracegrpc.WithEndpoint(endpoint)}
	if insecureTransport {
		exporterOptions = append(exporterOptions, otlptracegrpc.WithTLSCredentials(insecure.NewCredentials()))
	} else {
		exporterOptions = append(exporterOptions, otlptracegrpc.WithTLSCredentials(credentials.NewTLS(&tls.Config{})))
	}
	exp, err := otlptracegrpc.New(ctx, exporterOptions...)
	if err != nil {
		return nil, err
	}

	res, err := resource.New(ctx,
		resource.WithAttributes(attribute.String("service.name", serviceName)),
	)
	if err != nil {
		return nil, err
	}

	provider := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exp),
		sdktrace.WithResource(res),
	)
	otel.SetTracerProvider(provider)
	return provider.Shutdown, nil
}

func configurePropagator() {
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))
}

func WithRunID(ctx context.Context, runID string) context.Context {
	return context.WithValue(ctx, runIDContextKey{}, runID)
}

func RunIDFromContext(ctx context.Context) string {
	runID, _ := ctx.Value(runIDContextKey{}).(string)
	return runID
}

func JSONLogRecord(ctx context.Context, service, level, message string, fields map[string]any) map[string]any {
	record := map[string]any{
		"time":    time.Now().UTC().Format(time.RFC3339Nano),
		"level":   level,
		"service": service,
		"message": message,
	}

	if runID := RunIDFromContext(ctx); runID != "" {
		record["run_id"] = runID
	}

	spanContext := trace.SpanContextFromContext(ctx)
	if spanContext.HasTraceID() {
		record["trace_id"] = spanContext.TraceID().String()
	}
	if spanContext.HasSpanID() {
		record["span_id"] = spanContext.SpanID().String()
	}

	for key, value := range fields {
		record[key] = RedactSensitive(map[string]any{key: value}).(map[string]any)[key]
	}

	return record
}

func WriteJSONLog(w io.Writer, ctx context.Context, service, level, message string, fields map[string]any) error {
	encoder := json.NewEncoder(w)
	return encoder.Encode(JSONLogRecord(ctx, service, level, message, fields))
}

func RedactSensitive(value any) any {
	switch typed := value.(type) {
	case http.Header:
		return RedactSensitive(map[string][]string(typed))
	case map[string]any:
		redacted := make(map[string]any, len(typed))
		for key, item := range typed {
			if isSensitiveKey(key) {
				redacted[key] = redactedMarker
				continue
			}
			redacted[key] = RedactSensitive(item)
		}
		return redacted
	case map[string][]string:
		redacted := make(map[string][]string, len(typed))
		for key, item := range typed {
			if isSensitiveKey(key) {
				redacted[key] = []string{redactedMarker}
				continue
			}
			redacted[key] = RedactSensitive(item).([]string)
		}
		return redacted
	case map[string]string:
		redacted := make(map[string]string, len(typed))
		for key, item := range typed {
			if isSensitiveKey(key) {
				redacted[key] = redactedMarker
				continue
			}
			redacted[key] = redactString(item)
		}
		return redacted
	case []map[string]any:
		redacted := make([]map[string]any, len(typed))
		for i, item := range typed {
			redacted[i] = RedactSensitive(item).(map[string]any)
		}
		return redacted
	case []map[string]string:
		redacted := make([]map[string]string, len(typed))
		for i, item := range typed {
			redacted[i] = RedactSensitive(item).(map[string]string)
		}
		return redacted
	case []any:
		redacted := make([]any, len(typed))
		for i, item := range typed {
			redacted[i] = RedactSensitive(item)
		}
		return redacted
	case []string:
		redacted := make([]string, len(typed))
		for i, item := range typed {
			redacted[i] = redactString(item)
		}
		return redacted
	case string:
		return redactString(typed)
	default:
		return value
	}
}

func InjectTraceContext(ctx context.Context, carrier propagation.TextMapCarrier) {
	otel.GetTextMapPropagator().Inject(ctx, carrier)
}

func ExtractTraceContext(ctx context.Context, carrier propagation.TextMapCarrier) context.Context {
	return otel.GetTextMapPropagator().Extract(ctx, carrier)
}

func SpanAttributes(runID, taskType string) []attribute.KeyValue {
	attrs := make([]attribute.KeyValue, 0, 2)
	if runID != "" {
		attrs = append(attrs, attribute.String("run_id", runID))
	}
	if taskType != "" {
		attrs = append(attrs, attribute.String("task_type", taskType))
	}
	return attrs
}

func EnabledFromEnv() bool {
	value := strings.TrimSpace(strings.ToLower(os.Getenv("OTEL_ENABLED")))
	return value == "1" || value == "true" || value == "yes" || value == "on"
}

func OptionsFromEnv(serviceName string) Options {
	if envService := strings.TrimSpace(os.Getenv("OTEL_SERVICE_NAME")); envService != "" {
		serviceName = envService
	}
	endpoint := strings.TrimSpace(os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
	if endpoint == "" {
		endpoint = defaultOTLPEndpoint
	}
	endpoint, insecureTransport := normalizeOTLPEndpoint(endpoint)
	return Options{
		ServiceName:     serviceName,
		OTLPEndpoint:    endpoint,
		OTLPInsecure:    insecureTransport,
		OTLPInsecureSet: true,
		Enabled:         EnabledFromEnv(),
	}
}

func TraceMiddleware(service string) func(http.Handler) http.Handler {
	tracer := otel.Tracer(service)
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			ctx := ExtractTraceContext(r.Context(), propagation.HeaderCarrier(r.Header))
			ctx, span := tracer.Start(ctx, r.Method+" "+r.URL.Path)
			defer span.End()
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

func normalizeOTLPEndpoint(endpoint string) (string, bool) {
	endpoint = strings.TrimSpace(endpoint)
	if endpoint == "" {
		return defaultOTLPEndpoint, true
	}
	lower := strings.ToLower(endpoint)
	switch {
	case strings.HasPrefix(lower, "http://"):
		return endpoint[len("http://"):], true
	case strings.HasPrefix(lower, "https://"):
		return endpoint[len("https://"):], false
	default:
		return endpoint, true
	}
}

func normalizeOTLPOptions(opts Options) (string, bool) {
	endpoint, insecureTransport := normalizeOTLPEndpoint(opts.OTLPEndpoint)
	if opts.OTLPInsecureSet {
		insecureTransport = opts.OTLPInsecure
	}
	return endpoint, insecureTransport
}

func isSensitiveKey(key string) bool {
	normalized := strings.ToLower(strings.ReplaceAll(strings.ReplaceAll(key, "-", "_"), ".", "_"))
	for _, marker := range []string{"api_key", "authorization", "token", "password", "secret", "cookie", "mysql_dsn", "dsn"} {
		if strings.Contains(normalized, marker) {
			return true
		}
	}
	return false
}

func redactString(value string) string {
	value = bearerPattern.ReplaceAllString(value, "Bearer "+redactedMarker)
	value = keyValuePattern.ReplaceAllString(value, "$1="+redactedMarker)
	value = mysqlDSNPattern.ReplaceAllString(value, "$1:"+redactedMarker+"@tcp(")
	return value
}
