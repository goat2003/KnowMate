package grpcclient

import (
	"context"
	"net"
	"strings"
	"testing"
	"time"

	"knowledge-post-agent/goframe-backend/internal/agentpb"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/trace"
	oteltrace "go.opentelemetry.io/otel/trace"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
)

func TestClientInjectsTraceContext(t *testing.T) {
	otel.SetTextMapPropagator(propagation.TraceContext{})
	provider := trace.NewTracerProvider(trace.WithSampler(trace.AlwaysSample()))
	otel.SetTracerProvider(provider)
	defer otel.SetTracerProvider(oteltrace.NewNoopTracerProvider())
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	server := grpc.NewServer()
	health := &traceHealthServer{traceparent: make(chan string, 1)}
	agentpb.RegisterAgentServiceServer(server, health)
	go func() {
		_ = server.Serve(listener)
	}()
	defer server.Stop()

	ctx, span := otel.Tracer("grpcclient-test").Start(context.Background(), "client-span")
	defer span.End()

	client, err := NewWithDialOptions(ctx, listener.Addr().String(), time.Second, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatalf("NewWithDialOptions: %v", err)
	}
	defer client.Close()

	if _, err := client.HealthCheck(ctx); err != nil {
		t.Fatalf("HealthCheck: %v", err)
	}

	select {
	case traceparent := <-health.traceparent:
		if !strings.HasPrefix(traceparent, "00-") {
			t.Fatalf("traceparent = %q, want prefix 00-", traceparent)
		}
	case <-time.After(time.Second):
		t.Fatal("server did not receive traceparent metadata")
	}
}

type traceHealthServer struct {
	agentpb.UnimplementedAgentServiceServer
	traceparent chan string
}

func (s *traceHealthServer) HealthCheck(ctx context.Context, _ *agentpb.HealthCheckRequest) (*agentpb.HealthCheckResponse, error) {
	md, _ := metadata.FromIncomingContext(ctx)
	values := md.Get("traceparent")
	if len(values) > 0 {
		s.traceparent <- values[0]
	}
	return &agentpb.HealthCheckResponse{Status: "ok"}, nil
}
