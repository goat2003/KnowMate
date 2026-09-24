package handler

import (
	"context"
	"net/http"
	"testing"
	"time"

	"github.com/gogf/gf/v2/frame/g"
	"github.com/google/uuid"
	"knowledge-post-agent/goframe-backend/internal/agentpb"
)

type stalledHealthRunner struct{ handlerFakeRunner }

func (*stalledHealthRunner) AgentHealth(ctx context.Context) (*agentpb.HealthCheckResponse, error) {
	<-ctx.Done()
	return nil, ctx.Err()
}

func TestReadinessBoundsUnavailableAgent(t *testing.T) {
	h := NewWithDependencies(newHandlerFakeStore(), &stalledHealthRunner{})
	server := g.Server(uuid.NewString())
	server.SetAddr("127.0.0.1:0")
	h.Register(server)
	if err := server.Start(); err != nil {
		t.Fatal(err)
	}
	defer server.Shutdown()
	start := time.Now()
	response := doTestRequest(t, server, "GET", "/ready", "", nil)
	defer response.Body.Close()
	if response.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("status=%d", response.StatusCode)
	}
	if time.Since(start) > 4*time.Second {
		t.Fatal("readiness exceeded its bounded timeout")
	}
}
