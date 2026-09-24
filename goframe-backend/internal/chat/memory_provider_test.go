package chat

import (
	"context"
	"encoding/json"
	"io"
	"knowledge-post-agent/goframe-backend/internal/config"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestMemoryRoleIDStableAndIsolated(t *testing.T) {
	p := newMemoryProvider(config.MemoryConfig{URL: "http://memory", Token: "secret", RoleSecret: strings.Repeat("r", 32), TimeoutSeconds: 1}).(*memoryHTTPProvider)
	a := p.RoleID("user-a")
	if a != p.RoleID("user-a") {
		t.Fatal("role id is not stable")
	}
	if a == p.RoleID("user-b") || !strings.HasPrefix(a, "km_") {
		t.Fatal("role ids are not isolated")
	}
	if len(a) != 43 {
		t.Fatalf("unexpected role id length: %d", len(a))
	}
}

func TestMemoryProviderRejectsWeakRoleSecret(t *testing.T) {
	if got := newMemoryProvider(config.MemoryConfig{URL: "http://memory", RoleSecret: "short"}); got != nil {
		t.Fatal("weak role secret must disable the provider")
	}
}

func TestMemoryProviderBearerAndServerRole(t *testing.T) {
	var gotAuth, gotRole string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = r.Header.Get("Authorization")
		raw, _ := io.ReadAll(r.Body)
		var body map[string]any
		_ = json.Unmarshal(raw, &body)
		gotRole, _ = body["role_id"].(string)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte("{\"ok\":true,\"items\":[]}"))
	}))
	defer server.Close()
	p := newMemoryProvider(config.MemoryConfig{URL: server.URL, Token: strings.Repeat("t", 32), RoleSecret: strings.Repeat("r", 32), TimeoutSeconds: 1})
	_, err := p.List(context.Background(), "backend-user")
	if err != nil {
		t.Fatal(err)
	}
	if gotAuth != "Bearer "+strings.Repeat("t", 32) {
		t.Fatalf("missing bearer token: %q", gotAuth)
	}
	if gotRole != p.RoleID("backend-user") || strings.Contains(gotRole, "backend-user") {
		t.Fatalf("unexpected role id: %q", gotRole)
	}
}

func TestMemoryProviderUsesLongBuildTimeout(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/memory/build" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte("{\"ok\":true}"))
	}))
	defer server.Close()
	p := newMemoryProvider(config.MemoryConfig{URL: server.URL, Token: strings.Repeat("t", 32), RoleSecret: strings.Repeat("r", 32), TimeoutSeconds: 1, BuildTimeoutSeconds: 2})
	if err := p.Build(context.Background(), "backend-user", []map[string]string{{"user": "hello"}}); err != nil {
		t.Fatal(err)
	}
}

func TestMemoryProviderTimeoutIsError(t *testing.T) {
	gate := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { <-gate }))
	defer server.Close()
	p := newMemoryProvider(config.MemoryConfig{URL: server.URL, Token: strings.Repeat("t", 32), RoleSecret: strings.Repeat("r", 32), TimeoutSeconds: 1})
	_, err := p.Retrieve(context.Background(), "backend-user", "hello")
	close(gate)
	if err == nil {
		t.Fatal("expected timeout")
	}
}
