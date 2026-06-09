package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"testing"

	"knowledge-post-agent/goframe-backend/internal/agentpb"
	"knowledge-post-agent/goframe-backend/internal/config"
	"knowledge-post-agent/goframe-backend/internal/logic/harness"
	"knowledge-post-agent/goframe-backend/internal/model"

	"github.com/gogf/gf/v2/frame/g"
	"github.com/gogf/gf/v2/net/gclient"
	"github.com/gogf/gf/v2/net/ghttp"
	"github.com/gogf/gf/v2/os/gctx"
	"github.com/google/uuid"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

func TestProfileHandlersReturnJSON(t *testing.T) {
	client, shutdown := startHandlerTestServer(t)
	defer shutdown()

	profile := getJSON(t, client, "/profile")
	if profile["ok"] != true {
		t.Fatalf("expected profile ok response, got %#v", profile)
	}
	history := getJSON(t, client, "/profile/history")
	if _, ok := history["items"]; !ok {
		t.Fatalf("expected history items, got %#v", history)
	}
}

func TestRollbackProfileRequiresTargetVersion(t *testing.T) {
	client, shutdown := startHandlerTestServer(t)
	defer shutdown()

	response := postJSON(t, client, "/profile/rollback", `{}`)
	if response["ok"] != false {
		t.Fatalf("expected rollback validation failure, got %#v", response)
	}
}

func TestRecommendationExplanationReturnsStoredMetadata(t *testing.T) {
	client, shutdown := startHandlerTestServer(t)
	defer shutdown()

	response := getJSON(t, client, "/recommendations/explain?post_id=p1")
	if response["ok"] != true || response["explanation"] == nil {
		t.Fatalf("expected explanation response, got %#v", response)
	}
}

func TestProfileRebuildReturnsRunResult(t *testing.T) {
	client, shutdown := startHandlerTestServer(t)
	defer shutdown()

	response := postJSON(t, client, "/profile/rebuild", `{"user_id":"u1"}`)
	if response["ok"] != true || response["result"] == nil {
		t.Fatalf("expected rebuild result, got %#v", response)
	}
}

func TestRunControlHandlersReturnTaskState(t *testing.T) {
	client, shutdown := startHandlerTestServer(t)
	defer shutdown()

	list := getJSON(t, client, "/runs?status=running")
	if list["ok"] != true || list["items"] == nil {
		t.Fatalf("expected run list response, got %#v", list)
	}
	detail := getJSON(t, client, "/runs/run-1")
	if detail["ok"] != true || detail["run"] == nil {
		t.Fatalf("expected run detail response, got %#v", detail)
	}
	cancelled := postJSON(t, client, "/runs/run-1/cancel", `{}`)
	if cancelled["ok"] != true || cancelled["run"] == nil {
		t.Fatalf("expected cancel response, got %#v", cancelled)
	}
	retry := postJSON(t, client, "/runs/run-1/retry", `{}`)
	if retry["ok"] != true || retry["result"] == nil {
		t.Fatalf("expected retry response, got %#v", retry)
	}
}

func TestRunLogsStillReturnLegacyLogs(t *testing.T) {
	client, shutdown := startHandlerTestServer(t)
	defer shutdown()

	response := getJSON(t, client, "/run-logs")
	if response["ok"] != true || response["items"] == nil {
		t.Fatalf("expected legacy run logs response, got %#v", response)
	}
}

func TestAdminArticlesReturnsFilteredItems(t *testing.T) {
	client, shutdown := startHandlerTestServer(t)
	defer shutdown()

	response := getJSON(t, client, "/articles?source=arxiv&status=success&q=agent")
	if response["ok"] != true {
		t.Fatalf("expected articles ok response, got %#v", response)
	}
	items, ok := response["items"].([]any)
	if !ok || len(items) != 1 {
		t.Fatalf("expected one article item, got %#v", response["items"])
	}
	item, ok := items[0].(map[string]any)
	if !ok {
		t.Fatalf("expected article object, got %#v", items[0])
	}
	if item["id"] != "article-1" || item["fetch_status"] != "success" {
		t.Fatalf("unexpected article payload: %#v", item)
	}
}

func TestAdminPostDetailReturnsStoredPost(t *testing.T) {
	client, shutdown := startHandlerTestServer(t)
	defer shutdown()

	response := getJSON(t, client, "/posts/post-1")
	if response["ok"] != true || response["post"] == nil {
		t.Fatalf("expected post detail response, got %#v", response)
	}
	post := response["post"].(map[string]any)
	if post["post_uid"] != "post-1" || post["article_uid"] != "article-1" {
		t.Fatalf("unexpected post detail payload: %#v", post)
	}
}

func TestAdminMcpCallLogsReturnsFilteredItems(t *testing.T) {
	client, shutdown := startHandlerTestServer(t)
	defer shutdown()

	response := getJSON(t, client, "/mcp-call-logs?run_id=run-1&status=failed&server=embedding-mcp&tool=embed_text")
	if response["ok"] != true {
		t.Fatalf("expected mcp call logs ok response, got %#v", response)
	}
	items, ok := response["items"].([]any)
	if !ok || len(items) != 1 {
		t.Fatalf("expected one mcp log item, got %#v", response["items"])
	}
	item, ok := items[0].(map[string]any)
	if !ok {
		t.Fatalf("expected mcp log object, got %#v", items[0])
	}
	if item["call_id"] != "call-1" || item["status"] != "failed" {
		t.Fatalf("unexpected mcp log payload: %#v", item)
	}
}

func TestSecurityMiddlewareRequiresTokenForProtectedRoutes(t *testing.T) {
	server, runner, shutdown := startHandlerSecurityTestServer(t, config.SecurityConfig{
		APIToken: "secret-token",
	})
	defer shutdown()

	responseHTTP := doTestRequest(t, server, http.MethodPost, "/runs/articles", `{}`, nil)
	defer responseHTTP.Body.Close()

	if responseHTTP.StatusCode != http.StatusUnauthorized {
		t.Fatalf("status=%d, want 401", responseHTTP.StatusCode)
	}
	if runner.articleRuns != 0 {
		t.Fatalf("runner invoked without token")
	}
}

func TestSecurityMiddlewareAcceptsBearerToken(t *testing.T) {
	server, runner, shutdown := startHandlerSecurityTestServer(t, config.SecurityConfig{
		APIToken: "secret-token",
	})
	defer shutdown()

	responseHTTP := doTestRequest(t, server, http.MethodPost, "/runs/articles", `{}`, map[string]string{
		"Authorization": "Bearer secret-token",
	})
	defer responseHTTP.Body.Close()

	if responseHTTP.StatusCode != http.StatusOK {
		t.Fatalf("status=%d, want 200", responseHTTP.StatusCode)
	}
	if runner.articleRuns != 1 {
		t.Fatalf("runner articleRuns=%d, want 1", runner.articleRuns)
	}
}

func TestSecurityMiddlewareRejectsLargeBodiesBeforeHandler(t *testing.T) {
	server, runner, shutdown := startHandlerSecurityTestServer(t, config.SecurityConfig{
		APIToken:            "secret-token",
		MaxRequestBodyBytes: 8,
	})
	defer shutdown()

	responseHTTP := doTestRequest(t, server, http.MethodPost, "/feedback", `{"feedback_text":"too large"}`, map[string]string{
		"Authorization": "Bearer secret-token",
		"Content-Type":  "application/json",
	})
	defer responseHTTP.Body.Close()

	if responseHTTP.StatusCode != http.StatusRequestEntityTooLarge {
		t.Fatalf("status=%d, want 413", responseHTTP.StatusCode)
	}
	if runner.feedbackRuns != 0 {
		t.Fatalf("runner feedbackRuns=%d, want 0", runner.feedbackRuns)
	}
}

func TestSecurityMiddlewareRateLimitsByClient(t *testing.T) {
	server, _, shutdown := startHandlerSecurityTestServer(t, config.SecurityConfig{
		APIToken:       "secret-token",
		RateLimitBurst: 1,
	})
	defer shutdown()

	headers := map[string]string{"Authorization": "Bearer secret-token"}
	first := doTestRequest(t, server, http.MethodGet, "/posts", "", headers)
	defer first.Body.Close()
	if first.StatusCode != http.StatusOK {
		t.Fatalf("first status=%d, want 200", first.StatusCode)
	}
	second := doTestRequest(t, server, http.MethodGet, "/posts", "", headers)
	defer second.Body.Close()
	if second.StatusCode != http.StatusTooManyRequests {
		t.Fatalf("second status=%d, want 429", second.StatusCode)
	}
}

func TestRegisterTraceMiddlewareExtractsIncomingTraceparent(t *testing.T) {
	previousProvider := otel.GetTracerProvider()
	previousPropagator := otel.GetTextMapPropagator()
	t.Cleanup(func() {
		otel.SetTracerProvider(previousProvider)
		otel.SetTextMapPropagator(previousPropagator)
	})
	otel.SetTextMapPropagator(propagation.TraceContext{})
	otel.SetTracerProvider(sdktrace.NewTracerProvider(sdktrace.WithSampler(sdktrace.AlwaysSample())))

	store := newHandlerFakeStore()
	runner := &handlerFakeRunner{}
	h := NewWithDependencies(store, runner)
	server := g.Server(uuid.NewString())
	server.SetAddr("127.0.0.1:0")
	h.Register(server)
	if err := server.Start(); err != nil {
		t.Fatalf("start server: %v", err)
	}
	defer func() { _ = server.Shutdown() }()

	request, err := http.NewRequest(http.MethodPost, fmt.Sprintf("http://127.0.0.1:%d/runs/articles", server.GetListenedPort()), strings.NewReader(`{}`))
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("traceparent", "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01")
	responseHTTP, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatalf("post: %v", err)
	}
	defer responseHTTP.Body.Close()
	body, err := io.ReadAll(responseHTTP.Body)
	if err != nil {
		t.Fatalf("read body: %v", err)
	}
	raw := string(body)
	response := decodeResponse(t, raw)
	if response["ok"] != true {
		t.Fatalf("expected run response, got %#v", response)
	}
	spanContext := trace.SpanContextFromContext(runner.lastArticlesContext)
	if !spanContext.IsValid() {
		t.Fatalf("expected valid incoming span context")
	}
	if spanContext.TraceID().String() != "1234567890abcdef1234567890abcdef" {
		t.Fatalf("trace id = %s", spanContext.TraceID().String())
	}
}

func startHandlerTestServer(t *testing.T) (*gclient.Client, func()) {
	t.Helper()
	store := newHandlerFakeStore()
	runner := &handlerFakeRunner{}
	h := NewWithDependencies(store, runner)
	server := g.Server(uuid.NewString())
	server.SetAddr("127.0.0.1:0")
	h.Register(server)
	if err := server.Start(); err != nil {
		t.Fatalf("start server: %v", err)
	}
	client := g.Client().ContentJson()
	client.SetPrefix(fmt.Sprintf("http://127.0.0.1:%d", server.GetListenedPort()))
	return client, func() { _ = server.Shutdown() }
}

func startHandlerSecurityTestServer(t *testing.T, security config.SecurityConfig) (*ghttp.Server, *handlerFakeRunner, func()) {
	t.Helper()
	store := newHandlerFakeStore()
	runner := &handlerFakeRunner{}
	h := NewWithDependencies(store, runner)
	h.SetSecurityConfig(security)
	server := g.Server(uuid.NewString())
	server.SetAddr("127.0.0.1:0")
	h.Register(server)
	if err := server.Start(); err != nil {
		t.Fatalf("start server: %v", err)
	}
	return server, runner, func() { _ = server.Shutdown() }
}

func doTestRequest(t *testing.T, server *ghttp.Server, method string, path string, body string, headers map[string]string) *http.Response {
	t.Helper()
	var reader io.Reader
	if body != "" {
		reader = strings.NewReader(body)
	}
	request, err := http.NewRequest(method, fmt.Sprintf("http://127.0.0.1:%d%s", server.GetListenedPort(), path), reader)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	for key, value := range headers {
		request.Header.Set(key, value)
	}
	responseHTTP, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatalf("%s %s: %v", method, path, err)
	}
	return responseHTTP
}

func getJSON(t *testing.T, client *gclient.Client, path string) map[string]any {
	t.Helper()
	raw := client.GetContent(gctx.New(), path)
	return decodeResponse(t, raw)
}

func postJSON(t *testing.T, client *gclient.Client, path string, body string) map[string]any {
	t.Helper()
	raw := client.PostContent(gctx.New(), path, body)
	return decodeResponse(t, raw)
}

func decodeResponse(t *testing.T, raw string) map[string]any {
	t.Helper()
	if strings.TrimSpace(raw) == "" {
		t.Fatal("empty response")
	}
	var response map[string]any
	if err := json.Unmarshal([]byte(raw), &response); err != nil {
		t.Fatalf("decode %q: %v", raw, err)
	}
	return response
}

type handlerFakeStore struct {
	profile model.UserProfileSnapshot
	task    model.TaskRun
}

func newHandlerFakeStore() *handlerFakeStore {
	return &handlerFakeStore{
		profile: model.UserProfileSnapshot{
			UserID:   "u1",
			Version:  2,
			Snapshot: map[string]string{"user_id": "u1", "topics": `{"AI":0.8}`},
			Diff:     map[string]any{"changes": []any{}},
			IsActive: true,
		},
		task: model.TaskRun{RunID: "run-1", TaskType: harness.TaskTypeArticles, UserID: "u1", Status: harness.TaskStatusRunning},
	}
}

func (fake *handlerFakeStore) Ping(context.Context) error { return nil }

func (fake *handlerFakeStore) ListArticles(context.Context, model.ArticleFilter) ([]model.Article, error) {
	return []model.Article{{
		ID:          "article-1",
		Source:      "arxiv",
		SourceType:  "arxiv",
		URL:         "https://example.com/article-1",
		Title:       "Agent ranking",
		Content:     "Agent ranking content",
		FetchStatus: "success",
		Tags:        []string{"agent"},
	}}, nil
}

func (fake *handlerFakeStore) ListPosts(context.Context, int) ([]model.Post, error) { return nil, nil }

func (fake *handlerFakeStore) PostByID(context.Context, string) (model.Post, error) {
	return model.Post{
		PostUID:    "post-1",
		ArticleUID: "article-1",
		Title:      "Agent ranking",
		Markdown:   "## Agent ranking",
		Status:     "ready",
		Metadata:   map[string]any{"score": 8.5},
	}, nil
}

func (fake *handlerFakeStore) ListRunLogs(context.Context, int) ([]model.RunLog, error) {
	return []model.RunLog{{RunID: "run-1", Status: harness.TaskStatusRunning}}, nil
}

func (fake *handlerFakeStore) ListMcpCallLogs(context.Context, model.McpCallLogFilter) ([]model.McpCallLog, error) {
	return []model.McpCallLog{{
		CallID:       "call-1",
		RunID:        "run-1",
		AgentName:    "filter",
		ServerName:   "embedding-mcp",
		ToolName:     "embed_text",
		RequestJSON:  `{"text":"hello"}`,
		ResponseJSON: `{"ok":false}`,
		Status:       "failed",
		ErrorMessage: "timeout",
		Success:      false,
		LatencyMS:    1234,
	}}, nil
}

func (fake *handlerFakeStore) ListTaskRuns(context.Context, model.TaskRunFilter) ([]model.TaskRun, error) {
	return []model.TaskRun{fake.task}, nil
}

func (fake *handlerFakeStore) TaskRun(context.Context, string) (model.TaskRun, error) {
	return fake.task, nil
}

func (fake *handlerFakeStore) ListTaskSteps(context.Context, string) ([]model.TaskStep, error) {
	return []model.TaskStep{{RunID: "run-1", StepName: "fetch", Status: harness.StepStatusCompleted}}, nil
}

func (fake *handlerFakeStore) ActiveUserProfileSnapshot(context.Context, string) (model.UserProfileSnapshot, error) {
	return fake.profile, nil
}

func (fake *handlerFakeStore) ListUserProfileSnapshots(context.Context, string, int) ([]model.UserProfileSnapshot, error) {
	return []model.UserProfileSnapshot{fake.profile}, nil
}

func (fake *handlerFakeStore) RollbackUserProfileSnapshot(_ context.Context, userID string, targetVersion int, reason string) (model.UserProfileSnapshot, error) {
	fake.profile.UserID = userID
	fake.profile.Version++
	fake.profile.RolledBackFromVersion = targetVersion
	fake.profile.ChangeReason = reason
	return fake.profile, nil
}

func (fake *handlerFakeStore) RecommendationExplanationByPostID(context.Context, string) (model.RecommendationExplanation, error) {
	return model.RecommendationExplanation{
		PostUID: "p1",
		Metadata: map[string]any{
			"score":                  0.92,
			"recommendation_reasons": []string{"topic match"},
		},
	}, nil
}

type handlerFakeRunner struct {
	lastArticlesContext context.Context
	articleRuns         int
	feedbackRuns        int
}

func (fake *handlerFakeRunner) AgentHealth(context.Context) (*agentpb.HealthCheckResponse, error) {
	return &agentpb.HealthCheckResponse{Status: "SERVING"}, nil
}

func (fake *handlerFakeRunner) RunArticles(ctx context.Context) harness.RunArticlesResult {
	fake.lastArticlesContext = ctx
	fake.articleRuns++
	return harness.RunArticlesResult{RunID: "articles-test", Status: "completed"}
}

func (fake *handlerFakeRunner) ProcessFeedback(context.Context, harness.FeedbackRequest) harness.FeedbackResult {
	fake.feedbackRuns++
	return harness.FeedbackResult{RunID: "feedback-test", Status: "completed"}
}

func (fake *handlerFakeRunner) RebuildProfile(_ context.Context, req harness.RebuildProfileRequest) harness.RebuildProfileResult {
	return harness.RebuildProfileResult{RunID: "rebuild-test", Status: "completed", UserID: req.UserID, ProfileVersion: 3}
}

func (fake *handlerFakeRunner) ListTaskRuns(context.Context, model.TaskRunFilter) ([]model.TaskRun, error) {
	return []model.TaskRun{{RunID: "run-1", TaskType: harness.TaskTypeArticles, Status: harness.TaskStatusRunning}}, nil
}

func (fake *handlerFakeRunner) GetTaskRun(context.Context, string) (model.TaskRun, error) {
	return model.TaskRun{
		RunID:    "run-1",
		TaskType: harness.TaskTypeArticles,
		Status:   harness.TaskStatusRunning,
		Steps:    []model.TaskStep{{RunID: "run-1", StepName: "fetch", Status: harness.StepStatusCompleted}},
	}, nil
}

func (fake *handlerFakeRunner) CancelTask(context.Context, string) (model.TaskRun, error) {
	return model.TaskRun{RunID: "run-1", TaskType: harness.TaskTypeArticles, Status: harness.TaskStatusCancelled}, nil
}

func (fake *handlerFakeRunner) RetryTaskRun(context.Context, string) harness.RetryTaskResult {
	return harness.RetryTaskResult{RunID: "run-1", TaskType: harness.TaskTypeArticles, Status: harness.TaskStatusPartiallyCompleted}
}
