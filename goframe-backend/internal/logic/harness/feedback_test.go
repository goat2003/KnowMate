package harness

import (
	"context"
	"strings"
	"testing"

	"knowledge-post-agent/goframe-backend/internal/agentpb"
	"knowledge-post-agent/goframe-backend/internal/config"
	"knowledge-post-agent/goframe-backend/internal/model"
	"knowledge-post-agent/goframe-backend/internal/observability"
)

func TestProcessFeedbackReturnsCompletedResultForDuplicateFeedback(t *testing.T) {
	store := newFeedbackFakeStore()
	h := newWithDependencies(config.Config{Profile: config.ProfileConfig{UserID: "u1"}}, store, &fakeSourceCrawler{})
	h.processFeedbackFunc = store.processFeedback
	req := FeedbackRequest{PostID: "p1", ArticleID: "a1", UserID: "u1", FeedbackText: "有用", FeedbackType: "text", Rating: 5}

	first := h.ProcessFeedback(context.Background(), req)
	second := h.ProcessFeedback(context.Background(), req)

	if first.Status != "completed" || second.Status != "completed" {
		t.Fatalf("expected completed duplicate results: %#v %#v", first, second)
	}
	if store.agentCalls != 1 {
		t.Fatalf("expected one agent call, got %d", store.agentCalls)
	}
	if len(store.profiles) != 1 {
		t.Fatalf("expected one profile version, got %d", len(store.profiles))
	}
}

func TestFailedMcpLogsCreateCompensationTasks(t *testing.T) {
	store := newFeedbackFakeStore()
	store.nextMcpLogs = []model.McpCallLog{{
		RunID:        "r1",
		AgentName:    "memory",
		ServerName:   "milvus-mcp",
		ToolName:     "insert_memory_vector",
		Status:       "failed",
		Success:      false,
		ErrorMessage: "milvus down",
	}}
	h := newWithDependencies(config.Config{Profile: config.ProfileConfig{UserID: "u1"}}, store, &fakeSourceCrawler{})
	h.processFeedbackFunc = store.processFeedback

	result := h.ProcessFeedback(context.Background(), FeedbackRequest{PostID: "p1", UserID: "u1", FeedbackText: "有用", Rating: 5})

	if result.Status != "completed" {
		t.Fatalf("expected completed with compensation, got %#v", result)
	}
	if len(store.compensationTasks) != 1 || store.compensationTasks[0].TargetSystem != "milvus" {
		t.Fatalf("expected milvus compensation task, got %#v", store.compensationTasks)
	}
}

func TestProfileRebuildReplaysStructuredFeedback(t *testing.T) {
	store := newFeedbackFakeStore()
	store.completedFeedback = []model.FeedbackRecord{
		{
			UserID:                 "u1",
			StructuredFeedbackJSON: `{"positive":[{"topic":"工程实践","weight_delta":0.08,"evidence":"有用"}],"negative":[],"style_preferences":[{"name":"detail_level","value":"high"}]}`,
			ProcessStatus:          "completed",
		},
	}
	h := newWithDependencies(config.Config{Profile: config.ProfileConfig{UserID: "u1"}}, store, &fakeSourceCrawler{})

	result := h.RebuildProfile(context.Background(), RebuildProfileRequest{UserID: "u1"})

	if result.Status != "completed" {
		t.Fatalf("expected completed rebuild, got %#v", result)
	}
	if len(store.profiles) != 1 {
		t.Fatalf("expected rebuilt profile version, got %#v", store.profiles)
	}
	if store.profiles[0].ChangeReason != "rebuild" {
		t.Fatalf("expected rebuild reason, got %#v", store.profiles[0])
	}
	if store.profiles[0].Snapshot["topics"] == "" || store.profiles[0].Snapshot["style_preferences"] == "" {
		t.Fatalf("expected rebuilt profile details, got %#v", store.profiles[0].Snapshot)
	}
}

func TestProcessFeedbackRecordsFeedbackAndTaskMetrics(t *testing.T) {
	observability.ResetMetricsForTest()
	store := newFeedbackFakeStore()
	h := newWithDependencies(config.Config{Profile: config.ProfileConfig{UserID: "u1"}}, store, &fakeSourceCrawler{})
	h.processFeedbackFunc = store.processFeedback

	result := h.ProcessFeedback(context.Background(), FeedbackRequest{PostID: "p1", ArticleID: "a1", UserID: "u1", FeedbackText: "useful", FeedbackType: "text", Rating: 5})

	if result.Status != TaskStatusCompleted {
		t.Fatalf("expected completed feedback result, got %#v", result)
	}
	body := metricsBody(t)
	for _, want := range []string{
		`knowmate_feedback_received_total{feedback_type="text",status="received"} 1`,
		`knowmate_feedback_received_total{feedback_type="text",status="processed"} 1`,
		`knowmate_task_runs_total{status="completed",task_type="feedback"} 1`,
	} {
		if !strings.Contains(body, want) {
			t.Fatalf("missing metric %q in:\n%s", want, body)
		}
	}
}

type feedbackFakeStore struct {
	feedbackByKey     map[string]model.FeedbackRecord
	nextFeedbackID    uint64
	agentCalls        int
	profiles          []model.UserProfileSnapshot
	completedFeedback []model.FeedbackRecord
	compensationTasks []model.MemoryCompensationTask
	nextMcpLogs       []model.McpCallLog
	runLogs           []model.RunLog
	mcpLogs           []model.McpCallLog
	taskRuns          map[string]model.TaskRun
	taskSteps         []model.TaskStep
}

func newFeedbackFakeStore() *feedbackFakeStore {
	return &feedbackFakeStore{feedbackByKey: map[string]model.FeedbackRecord{}}
}

func (fake *feedbackFakeStore) processFeedback(_ context.Context, runID string, userID string, req FeedbackRequest, profile map[string]string, _ *stepRecorder) (*agentpb.ProcessFeedbackResponse, error) {
	fake.agentCalls++
	updated := map[string]string{}
	for key, value := range profile {
		updated[key] = value
	}
	updated["feedback_count"] = "1"
	logs := make([]*agentpb.McpCallLog, 0, len(fake.nextMcpLogs))
	for _, item := range fake.nextMcpLogs {
		logs = append(logs, &agentpb.McpCallLog{
			RunId:        runID,
			AgentName:    item.AgentName,
			ServerName:   item.ServerName,
			ToolName:     item.ToolName,
			Status:       item.Status,
			Success:      item.Success,
			ErrorMessage: item.ErrorMessage,
		})
	}
	return &agentpb.ProcessFeedbackResponse{
		RunId:                  runID,
		Sentiment:              "positive",
		ExtractedFeedback:      []string{req.FeedbackText},
		UpdatedProfileSnapshot: updated,
		StructuredFeedbackJson: `{"positive":[{"topic":"general","weight_delta":0.08}]}`,
		ProfileDiffJson:        `{"changes":[{"path":"feedback_count","before":"0","after":"1"}]}`,
		McpCallLogs:            logs,
	}, nil
}

func (fake *feedbackFakeStore) InsertArticle(context.Context, model.Article) (bool, error) {
	return true, nil
}

func (fake *feedbackFakeStore) UpsertCrawlSourceRun(context.Context, model.CrawlSourceRun) error {
	return nil
}

func (fake *feedbackFakeStore) InsertPost(context.Context, model.Post) error { return nil }

func (fake *feedbackFakeStore) InsertFeedbackLog(context.Context, model.FeedbackLog) error {
	return nil
}

func (fake *feedbackFakeStore) UpsertFeedbackReceived(_ context.Context, feedback model.FeedbackLog, idempotencyKey string, raw map[string]any) (model.FeedbackRecord, bool, error) {
	if existing, ok := fake.feedbackByKey[idempotencyKey]; ok {
		return existing, false, nil
	}
	fake.nextFeedbackID++
	record := model.FeedbackRecord{
		ID:             fake.nextFeedbackID,
		RunID:          feedback.RunID,
		PostUID:        feedback.PostUID,
		ArticleUID:     feedback.ArticleUID,
		UserID:         feedback.UserID,
		FeedbackType:   feedback.FeedbackType,
		Rating:         feedback.Rating,
		Comment:        feedback.Comment,
		IdempotencyKey: idempotencyKey,
		RawFeedback:    raw,
		ProcessStatus:  "received",
	}
	fake.feedbackByKey[idempotencyKey] = record
	return record, true, nil
}

func (fake *feedbackFakeStore) MarkFeedbackProcessing(context.Context, uint64) error {
	return nil
}

func (fake *feedbackFakeStore) MarkFeedbackCompleted(_ context.Context, id uint64, structuredJSON string, profileVersion int) error {
	for key, record := range fake.feedbackByKey {
		if record.ID == id {
			record.ProcessStatus = "completed"
			record.StructuredFeedbackJSON = structuredJSON
			record.ProfileVersion = profileVersion
			fake.feedbackByKey[key] = record
			return nil
		}
	}
	return nil
}

func (fake *feedbackFakeStore) MarkFeedbackFailed(context.Context, uint64, string) error {
	return nil
}

func (fake *feedbackFakeStore) ListCompletedStructuredFeedback(context.Context, string) ([]model.FeedbackRecord, error) {
	return fake.completedFeedback, nil
}

func (fake *feedbackFakeStore) InsertRunLog(_ context.Context, run model.RunLog) error {
	fake.runLogs = append(fake.runLogs, run)
	return nil
}

func (fake *feedbackFakeStore) CreateTaskRun(_ context.Context, task model.TaskRun) (model.TaskRun, error) {
	if fake.taskRuns == nil {
		fake.taskRuns = map[string]model.TaskRun{}
	}
	if existing, ok := fake.taskRuns[task.RunID]; ok {
		return existing, nil
	}
	fake.taskRuns[task.RunID] = task
	return task, nil
}

func (fake *feedbackFakeStore) UpdateTaskRun(_ context.Context, task model.TaskRun) error {
	if fake.taskRuns == nil {
		fake.taskRuns = map[string]model.TaskRun{}
	}
	existing := fake.taskRuns[task.RunID]
	if task.Status != "" {
		existing.Status = task.Status
	}
	if task.PartialResult != nil {
		existing.PartialResult = task.PartialResult
	}
	fake.taskRuns[task.RunID] = existing
	return nil
}

func (fake *feedbackFakeStore) MarkTaskRunStatus(_ context.Context, runID string, status string, errorMessage string, partial map[string]any) error {
	if fake.taskRuns == nil {
		fake.taskRuns = map[string]model.TaskRun{}
	}
	task := fake.taskRuns[runID]
	task.RunID = runID
	task.Status = status
	task.ErrorMessage = errorMessage
	task.PartialResult = partial
	fake.taskRuns[runID] = task
	return nil
}

func (fake *feedbackFakeStore) UpsertTaskStep(_ context.Context, step model.TaskStep) error {
	fake.taskSteps = append(fake.taskSteps, step)
	return nil
}

func (fake *feedbackFakeStore) TaskRun(_ context.Context, runID string) (model.TaskRun, error) {
	if fake.taskRuns != nil {
		if task, ok := fake.taskRuns[runID]; ok {
			return task, nil
		}
	}
	return model.TaskRun{RunID: runID, Status: TaskStatusRunning}, nil
}

func (fake *feedbackFakeStore) ListTaskRuns(context.Context, model.TaskRunFilter) ([]model.TaskRun, error) {
	items := make([]model.TaskRun, 0, len(fake.taskRuns))
	for _, task := range fake.taskRuns {
		items = append(items, task)
	}
	return items, nil
}

func (fake *feedbackFakeStore) ListTaskSteps(context.Context, string) ([]model.TaskStep, error) {
	return fake.taskSteps, nil
}

func (fake *feedbackFakeStore) RecoverInterruptedTaskRuns(context.Context, string) ([]model.TaskRun, error) {
	return nil, nil
}

func (fake *feedbackFakeStore) RequestTaskCancellation(context.Context, string) (model.TaskRun, error) {
	return model.TaskRun{}, nil
}

func (fake *feedbackFakeStore) ArticleHasPost(context.Context, string) (bool, error) {
	return false, nil
}

func (fake *feedbackFakeStore) InsertUserProfileSnapshot(context.Context, string, map[string]string, string) error {
	return nil
}

func (fake *feedbackFakeStore) InsertMcpCallLogs(_ context.Context, logs []model.McpCallLog) error {
	fake.mcpLogs = append(fake.mcpLogs, logs...)
	return nil
}

func (fake *feedbackFakeStore) LatestUserProfileSnapshot(context.Context, string) (map[string]string, error) {
	return map[string]string{"feedback_count": "0"}, nil
}

func (fake *feedbackFakeStore) ActiveUserProfileSnapshot(context.Context, string) (model.UserProfileSnapshot, error) {
	if len(fake.profiles) == 0 {
		return model.UserProfileSnapshot{Snapshot: map[string]string{"feedback_count": "0"}}, nil
	}
	return fake.profiles[len(fake.profiles)-1], nil
}

func (fake *feedbackFakeStore) ListUserProfileSnapshots(context.Context, string, int) ([]model.UserProfileSnapshot, error) {
	return fake.profiles, nil
}

func (fake *feedbackFakeStore) InsertUserProfileSnapshotVersion(_ context.Context, snapshot model.UserProfileSnapshot) (model.UserProfileSnapshot, error) {
	snapshot.Version = len(fake.profiles) + 1
	snapshot.IsActive = true
	fake.profiles = append(fake.profiles, snapshot)
	return snapshot, nil
}

func (fake *feedbackFakeStore) RollbackUserProfileSnapshot(context.Context, string, int, string) (model.UserProfileSnapshot, error) {
	return model.UserProfileSnapshot{}, nil
}

func (fake *feedbackFakeStore) InsertMemoryCompensationTask(_ context.Context, task model.MemoryCompensationTask) error {
	fake.compensationTasks = append(fake.compensationTasks, task)
	return nil
}
