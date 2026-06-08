package harness

import (
	"context"
	"testing"

	"knowledge-post-agent/goframe-backend/internal/agentpb"
	"knowledge-post-agent/goframe-backend/internal/config"
	"knowledge-post-agent/goframe-backend/internal/crawler"
	"knowledge-post-agent/goframe-backend/internal/model"
)

func TestFetchSourcesContinuesAfterFailureAndPersistsRuns(t *testing.T) {
	store := &fakeArticleStore{}
	sourceClient := &fakeSourceCrawler{results: map[string]crawler.SourceResult{
		"broken": {
			Source:       crawler.Source{Name: "broken", Type: crawler.SourceTypeFeed},
			Status:       "failed",
			ErrorType:    string(crawler.ErrorHTTP5xx),
			ErrorMessage: "source unavailable",
			HTTPStatus:   503,
		},
		"working": {
			Source: crawler.Source{Name: "working", Type: crawler.SourceTypeMock},
			Status: "success",
			Articles: []model.Article{{
				ID: "article-working", Source: "working", FetchStatus: "success", Content: "processable content",
			}},
			ItemsFound: 1,
		},
	}}
	harness := newWithDependencies(testCrawlerConfig("broken", "working"), store, sourceClient)
	steps := stepRecorder{steps: &[]StepLog{}}

	articles, results := harness.fetchArticles(context.Background(), "run-1", &steps)

	if len(sourceClient.calls) != 2 || sourceClient.calls[0] != "broken" || sourceClient.calls[1] != "working" {
		t.Fatalf("unexpected crawler calls: %#v", sourceClient.calls)
	}
	if len(results) != 2 || len(articles) != 1 || articles[0].ID != "article-working" {
		t.Fatalf("unexpected fetch result: %#v %#v", results, articles)
	}
	if len(store.sourceRuns) != 4 {
		t.Fatalf("expected running and final records for both sources, got %d", len(store.sourceRuns))
	}
}

func TestRunArticlesAllSourcesFailedPersistsDiagnosticsAndFails(t *testing.T) {
	store := &fakeArticleStore{}
	sourceClient := &fakeSourceCrawler{results: map[string]crawler.SourceResult{
		"broken": {
			Source:       crawler.Source{Name: "broken", Type: crawler.SourceTypeFeed},
			Status:       "failed",
			ErrorType:    string(crawler.ErrorHTTP5xx),
			ErrorMessage: "source unavailable",
			Articles: []model.Article{{
				ID: "failed-article", Source: "broken", FetchStatus: "failed", FetchErrorType: string(crawler.ErrorHTTP5xx),
			}},
			ItemsFound:  1,
			ItemsFailed: 1,
		},
	}}
	harness := newWithDependencies(testCrawlerConfig("broken"), store, sourceClient)

	result := harness.RunArticles(context.Background())

	if result.Status != "failed" || result.Error != "all crawler sources failed" {
		t.Fatalf("unexpected run result: %#v", result)
	}
	if len(store.articles) != 1 || store.articles[0].FetchStatus != "failed" {
		t.Fatalf("failed article diagnostics were not saved: %#v", store.articles)
	}
	if len(store.sourceRuns) < 3 || store.sourceRuns[len(store.sourceRuns)-1].ItemsSaved != 1 {
		t.Fatalf("source run saved count was not updated: %#v", store.sourceRuns)
	}
}

func TestPersistAgentResultsStoresRecommendationExplanationMetadata(t *testing.T) {
	store := &fakeArticleStore{}
	harness := newWithDependencies(testCrawlerConfig("working"), store, &fakeSourceCrawler{})
	steps := stepRecorder{steps: &[]StepLog{}}

	posts, _ := harness.persistAgentResults(
		context.Background(),
		"run-1",
		&agentpb.ProcessArticlesResponse{Results: []*agentpb.ArticleProcessResult{{
			ArticleId:             "article-1",
			Keep:                  true,
			Score:                 0.92,
			PostText:              "post body",
			CheckPass:             true,
			RankPosition:          1,
			RecommendationReasons: []string{"topic match"},
			RejectionReasons:      []string{},
			ScoreBreakdown: []*agentpb.ScoreBreakdownItem{{
				Dimension:    "topic",
				Available:    true,
				RawScore:     0.9,
				Weight:       0.5,
				Contribution: 0.45,
				Evidence:     []string{"AI"},
			}},
		}}},
		map[string]model.Article{"article-1": {ID: "article-1", Title: "Article 1"}},
		7,
		&steps,
	)

	if len(posts) != 1 || len(store.posts) != 1 {
		t.Fatalf("expected one saved post, got %#v %#v", posts, store.posts)
	}
	metadata := store.posts[0].Metadata
	if metadata["score"] != 0.92 || metadata["rank_position"] != int32(1) || metadata["profile_version"] != 7 {
		t.Fatalf("unexpected explanation metadata: %#v", metadata)
	}
	if metadata["score_breakdown"] == nil || metadata["recommendation_reasons"] == nil {
		t.Fatalf("missing explanation detail: %#v", metadata)
	}
}

func testCrawlerConfig(sourceNames ...string) config.Config {
	sources := make([]config.SourceConfig, 0, len(sourceNames))
	for _, name := range sourceNames {
		sources = append(sources, config.SourceConfig{Name: name, Type: "feed", URL: "http://fixture.invalid/" + name, Enabled: true})
	}
	return config.Config{
		Crawler: config.CrawlerConfig{Sources: sources, SourceMaxItems: 10, RunMaxArticles: 20},
		Output:  config.OutputConfig{Dir: "test-output"},
	}
}

type fakeSourceCrawler struct {
	results map[string]crawler.SourceResult
	calls   []string
}

func (fake *fakeSourceCrawler) FetchSource(_ context.Context, source crawler.Source) crawler.SourceResult {
	fake.calls = append(fake.calls, source.Name)
	result := fake.results[source.Name]
	result.Source.Name = source.Name
	if result.Source.Type == "" {
		result.Source.Type = source.Type
	}
	return result
}

type fakeArticleStore struct {
	articles             []model.Article
	posts                []model.Post
	sourceRuns           []model.CrawlSourceRun
	runLogs              []model.RunLog
	taskRuns             map[string]model.TaskRun
	taskSteps            []model.TaskStep
	existingPostArticles map[string]bool
	cancelledRunIDs      map[string]bool
	lastTaskStatusErr    error
}

func (fake *fakeArticleStore) InsertArticle(_ context.Context, article model.Article) (bool, error) {
	fake.articles = append(fake.articles, article)
	return true, nil
}

func (fake *fakeArticleStore) UpsertCrawlSourceRun(_ context.Context, run model.CrawlSourceRun) error {
	fake.sourceRuns = append(fake.sourceRuns, run)
	return nil
}

func (fake *fakeArticleStore) InsertPost(_ context.Context, post model.Post) error {
	fake.posts = append(fake.posts, post)
	if fake.existingPostArticles == nil {
		fake.existingPostArticles = map[string]bool{}
	}
	fake.existingPostArticles[post.ArticleUID] = true
	return nil
}

func (fake *fakeArticleStore) InsertFeedbackLog(context.Context, model.FeedbackLog) error { return nil }

func (fake *fakeArticleStore) UpsertFeedbackReceived(_ context.Context, feedback model.FeedbackLog, _ string, raw map[string]any) (model.FeedbackRecord, bool, error) {
	return model.FeedbackRecord{ID: 1, RunID: feedback.RunID, UserID: feedback.UserID, RawFeedback: raw, ProcessStatus: "received"}, true, nil
}

func (fake *fakeArticleStore) MarkFeedbackProcessing(context.Context, uint64) error { return nil }

func (fake *fakeArticleStore) MarkFeedbackCompleted(context.Context, uint64, string, int) error {
	return nil
}

func (fake *fakeArticleStore) MarkFeedbackFailed(context.Context, uint64, string) error { return nil }

func (fake *fakeArticleStore) ListCompletedStructuredFeedback(context.Context, string) ([]model.FeedbackRecord, error) {
	return nil, nil
}

func (fake *fakeArticleStore) InsertRunLog(_ context.Context, run model.RunLog) error {
	fake.runLogs = append(fake.runLogs, run)
	return nil
}

func (fake *fakeArticleStore) CreateTaskRun(_ context.Context, task model.TaskRun) (model.TaskRun, error) {
	if fake.taskRuns == nil {
		fake.taskRuns = map[string]model.TaskRun{}
	}
	if fake.cancelledRunIDs != nil && fake.cancelledRunIDs[task.RunID] {
		task.Status = TaskStatusCancelled
		task.CancelRequested = true
	}
	if existing, ok := fake.taskRuns[task.RunID]; ok {
		return existing, nil
	}
	fake.taskRuns[task.RunID] = task
	return task, nil
}

func (fake *fakeArticleStore) UpdateTaskRun(_ context.Context, task model.TaskRun) error {
	if fake.taskRuns == nil {
		fake.taskRuns = map[string]model.TaskRun{}
	}
	existing := fake.taskRuns[task.RunID]
	if task.Status != "" {
		existing.Status = task.Status
	}
	if task.TaskType != "" {
		existing.TaskType = task.TaskType
	}
	if task.UserID != "" {
		existing.UserID = task.UserID
	}
	if task.CurrentStep != "" {
		existing.CurrentStep = task.CurrentStep
	}
	if task.PartialResult != nil {
		existing.PartialResult = task.PartialResult
	}
	if task.RetryCount != 0 {
		existing.RetryCount = task.RetryCount
	}
	if task.TimeoutSeconds != 0 {
		existing.TimeoutSeconds = task.TimeoutSeconds
	}
	existing.CancelRequested = task.CancelRequested
	fake.taskRuns[task.RunID] = existing
	return nil
}

func (fake *fakeArticleStore) MarkTaskRunStatus(_ context.Context, runID string, status string, errorMessage string, partial map[string]any) error {
	if fake.taskRuns == nil {
		fake.taskRuns = map[string]model.TaskRun{}
	}
	task := fake.taskRuns[runID]
	task.RunID = runID
	task.Status = status
	task.ErrorMessage = errorMessage
	task.PartialResult = partial
	if status == TaskStatusCancelled {
		task.CancelRequested = true
	}
	fake.taskRuns[runID] = task
	fake.lastTaskStatusErr = nil
	return nil
}

func (fake *fakeArticleStore) UpsertTaskStep(_ context.Context, step model.TaskStep) error {
	fake.taskSteps = append(fake.taskSteps, step)
	return nil
}

func (fake *fakeArticleStore) TaskRun(_ context.Context, runID string) (model.TaskRun, error) {
	if fake.cancelledRunIDs != nil && fake.cancelledRunIDs[runID] {
		return model.TaskRun{RunID: runID, Status: TaskStatusCancelled, CancelRequested: true}, nil
	}
	if fake.taskRuns != nil {
		if task, ok := fake.taskRuns[runID]; ok {
			return task, nil
		}
	}
	return model.TaskRun{RunID: runID, Status: TaskStatusRunning}, nil
}

func (fake *fakeArticleStore) ListTaskRuns(context.Context, model.TaskRunFilter) ([]model.TaskRun, error) {
	items := make([]model.TaskRun, 0, len(fake.taskRuns))
	for _, task := range fake.taskRuns {
		items = append(items, task)
	}
	return items, nil
}

func (fake *fakeArticleStore) ListTaskSteps(context.Context, string) ([]model.TaskStep, error) {
	return fake.taskSteps, nil
}

func (fake *fakeArticleStore) RecoverInterruptedTaskRuns(context.Context, string) ([]model.TaskRun, error) {
	return nil, nil
}

func (fake *fakeArticleStore) RequestTaskCancellation(_ context.Context, runID string) (model.TaskRun, error) {
	if fake.cancelledRunIDs == nil {
		fake.cancelledRunIDs = map[string]bool{}
	}
	fake.cancelledRunIDs[runID] = true
	task := model.TaskRun{RunID: runID, Status: TaskStatusCancelled, CancelRequested: true}
	if fake.taskRuns == nil {
		fake.taskRuns = map[string]model.TaskRun{}
	}
	fake.taskRuns[runID] = task
	return task, nil
}

func (fake *fakeArticleStore) ArticleHasPost(_ context.Context, articleUID string) (bool, error) {
	return fake.existingPostArticles != nil && fake.existingPostArticles[articleUID], nil
}

func (fake *fakeArticleStore) InsertUserProfileSnapshot(context.Context, string, map[string]string, string) error {
	return nil
}

func (fake *fakeArticleStore) ActiveUserProfileSnapshot(context.Context, string) (model.UserProfileSnapshot, error) {
	return model.UserProfileSnapshot{Snapshot: map[string]string{}}, nil
}

func (fake *fakeArticleStore) ListUserProfileSnapshots(context.Context, string, int) ([]model.UserProfileSnapshot, error) {
	return nil, nil
}

func (fake *fakeArticleStore) InsertUserProfileSnapshotVersion(_ context.Context, snapshot model.UserProfileSnapshot) (model.UserProfileSnapshot, error) {
	snapshot.Version = 1
	return snapshot, nil
}

func (fake *fakeArticleStore) RollbackUserProfileSnapshot(context.Context, string, int, string) (model.UserProfileSnapshot, error) {
	return model.UserProfileSnapshot{}, nil
}

func (fake *fakeArticleStore) InsertMemoryCompensationTask(context.Context, model.MemoryCompensationTask) error {
	return nil
}

func (fake *fakeArticleStore) InsertMcpCallLogs(context.Context, []model.McpCallLog) error {
	return nil
}

func (fake *fakeArticleStore) LatestUserProfileSnapshot(context.Context, string) (map[string]string, error) {
	return map[string]string{}, nil
}
