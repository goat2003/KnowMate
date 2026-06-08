package harness

import (
	"context"
	"errors"
	"testing"
	"time"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"knowledge-post-agent/goframe-backend/internal/agentpb"
	"knowledge-post-agent/goframe-backend/internal/crawler"
	"knowledge-post-agent/goframe-backend/internal/model"
)

func TestTaskStatusMachineTransitions(t *testing.T) {
	for _, item := range []struct {
		from string
		to   string
	}{
		{TaskStatusPending, TaskStatusRunning},
		{TaskStatusRunning, TaskStatusCompleted},
		{TaskStatusRunning, TaskStatusFailed},
		{TaskStatusRunning, TaskStatusPartiallyCompleted},
		{TaskStatusRunning, TaskStatusCancelled},
		{TaskStatusFailed, TaskStatusPending},
		{TaskStatusPartiallyCompleted, TaskStatusPending},
	} {
		if !canTransitionTaskStatus(item.from, item.to) {
			t.Fatalf("expected %s -> %s to be allowed", item.from, item.to)
		}
	}

	for _, item := range []struct {
		from string
		to   string
	}{
		{TaskStatusCompleted, TaskStatusRunning},
		{TaskStatusCancelled, TaskStatusRunning},
		{TaskStatusFailed, TaskStatusCompleted},
	} {
		if canTransitionTaskStatus(item.from, item.to) {
			t.Fatalf("expected %s -> %s to be rejected", item.from, item.to)
		}
	}
}

func TestStepRecorderPersistsRichStepMetadata(t *testing.T) {
	store := &fakeArticleStore{}
	steps := []StepLog{}
	recorder := stepRecorder{
		ctx:   context.Background(),
		runID: "run-1",
		store: store,
		steps: &steps,
	}

	recorder.start("fetch", "source=fixture")
	recorder.complete("fetch", "1 article", "", 2)

	if len(steps) != 1 {
		t.Fatalf("expected one in-memory step, got %#v", steps)
	}
	step := steps[0]
	if step.Status != StepStatusCompleted || step.StartedAt == "" || step.CompletedAt == "" {
		t.Fatalf("expected completed step with timestamps, got %#v", step)
	}
	if step.InputSummary != "source=fixture" || step.OutputSummary != "1 article" || step.RetryCount != 2 {
		t.Fatalf("expected rich step summaries, got %#v", step)
	}
	if len(store.taskSteps) != 2 {
		t.Fatalf("expected start and completion persisted, got %#v", store.taskSteps)
	}
	if store.taskSteps[len(store.taskSteps)-1].RetryCount != 2 {
		t.Fatalf("expected persisted retry count, got %#v", store.taskSteps)
	}
}

func TestRetryDelayUsesExponentialBackoffWithCap(t *testing.T) {
	base := 100 * time.Millisecond
	maxDelay := 250 * time.Millisecond
	if got := retryDelay(1, base, maxDelay); got != base {
		t.Fatalf("attempt 1 delay = %v", got)
	}
	if got := retryDelay(2, base, maxDelay); got != 200*time.Millisecond {
		t.Fatalf("attempt 2 delay = %v", got)
	}
	if got := retryDelay(3, base, maxDelay); got != maxDelay {
		t.Fatalf("attempt 3 delay = %v", got)
	}
}

func TestStablePostIDIsRunIndependent(t *testing.T) {
	first := stablePostID("articles-run-a", "article-1")
	second := stablePostID("articles-run-b", "article-1")
	if first != second {
		t.Fatalf("expected post IDs to be stable across retries/runs, got %q and %q", first, second)
	}
}

func TestRunArticlesSkipsAlreadyGeneratedArticlePosts(t *testing.T) {
	store := &fakeArticleStore{existingPostArticles: map[string]bool{"article-1": true}}
	sourceClient := &fakeSourceCrawler{results: map[string]crawler.SourceResult{
		"working": {
			Source: crawler.Source{Name: "working", Type: crawler.SourceTypeMock},
			Status: "success",
			Articles: []model.Article{{
				ID: "article-1", Source: "working", FetchStatus: "success", Content: "processable content",
			}},
			ItemsFound: 1,
		},
	}}
	h := newWithDependencies(testCrawlerConfig("working"), store, sourceClient)
	h.processArticlesFunc = func(context.Context, string, []model.Article, map[string]string, *stepRecorder) (*agentpb.ProcessArticlesResponse, error) {
		t.Fatal("article with an existing post must not be sent to Python Agent")
		return nil, nil
	}

	result := h.RunArticles(context.Background())

	if result.Status != TaskStatusCompleted {
		t.Fatalf("expected completed duplicate-safe run, got %#v", result)
	}
	if result.ProcessedCount != 0 || result.PostsSaved != 0 {
		t.Fatalf("expected no regenerated output, got %#v", result)
	}
}

func TestTaskCancellationBeforeRun(t *testing.T) {
	store := &fakeArticleStore{cancelledRunIDs: map[string]bool{"run-1": true}}
	h := newWithDependencies(testCrawlerConfig("working"), store, &fakeSourceCrawler{})

	result, err := h.CancelTask(context.Background(), "run-1")

	if err != nil {
		t.Fatalf("cancel task: %v", err)
	}
	if result.Status != TaskStatusCancelled {
		t.Fatalf("expected cancelled task, got %#v", result)
	}
}

func TestRetryTaskResetsFailedRunToPending(t *testing.T) {
	store := &fakeArticleStore{taskRuns: map[string]model.TaskRun{
		"run-1": {
			RunID:    "run-1",
			TaskType: TaskTypeArticles,
			UserID:   "u1",
			Status:   TaskStatusFailed,
			PartialResult: map[string]any{
				"new_articles": 1,
				"processable_articles": []map[string]any{{
					"id":           "article-1",
					"title":        "Article 1",
					"content":      "processable content",
					"source":       "working",
					"fetch_status": "success",
				}},
			},
		},
	}}
	h := newWithDependencies(testCrawlerConfig("working"), store, &fakeSourceCrawler{})
	h.processArticlesFunc = func(context.Context, string, []model.Article, map[string]string, *stepRecorder) (*agentpb.ProcessArticlesResponse, error) {
		return nil, status.Error(codes.Unavailable, "agent unavailable")
	}

	result := h.RetryTask(context.Background(), "run-1")

	if result.RunID != "run-1" {
		t.Fatalf("expected retry to keep run_id, got %#v", result)
	}
	if result.Status != TaskStatusPartiallyCompleted {
		t.Fatalf("expected retried run to execute and preserve partial success at agent step, got %#v", result)
	}
	if !errors.Is(store.lastTaskStatusErr, nil) {
		t.Fatalf("unexpected task status update error: %v", store.lastTaskStatusErr)
	}
}
