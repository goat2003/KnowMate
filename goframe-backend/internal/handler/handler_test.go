package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	"knowledge-post-agent/goframe-backend/internal/agentpb"
	"knowledge-post-agent/goframe-backend/internal/logic/harness"
	"knowledge-post-agent/goframe-backend/internal/model"

	"github.com/gogf/gf/v2/frame/g"
	"github.com/gogf/gf/v2/net/gclient"
	"github.com/gogf/gf/v2/os/gctx"
	"github.com/google/uuid"
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

func (fake *handlerFakeStore) ListPosts(context.Context, int) ([]model.Post, error) { return nil, nil }

func (fake *handlerFakeStore) ListRunLogs(context.Context, int) ([]model.RunLog, error) {
	return []model.RunLog{{RunID: "run-1", Status: harness.TaskStatusRunning}}, nil
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

type handlerFakeRunner struct{}

func (fake *handlerFakeRunner) AgentHealth(context.Context) (*agentpb.HealthCheckResponse, error) {
	return &agentpb.HealthCheckResponse{Status: "SERVING"}, nil
}

func (fake *handlerFakeRunner) RunArticles(context.Context) harness.RunArticlesResult {
	return harness.RunArticlesResult{RunID: "articles-test", Status: "completed"}
}

func (fake *handlerFakeRunner) ProcessFeedback(context.Context, harness.FeedbackRequest) harness.FeedbackResult {
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
