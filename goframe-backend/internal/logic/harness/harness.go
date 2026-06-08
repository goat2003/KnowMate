// 文件作用：
// 本文件实现 GoFrame 后端的核心业务编排。
// 它串联 RSS 抓取、文章入库、用户画像读取、Python Agent gRPC 调用、posts 持久化、
// MCP 调用日志写入、run_logs 更新和 Markdown 文件输出。
//
// 在项目中的位置：
// 本文件属于 GoFrame 后端的 logic 层，位于 HTTP handler 和 store/grpcclient/crawler 之间。
//
// 主要内容：
// 1. Harness：业务编排对象。
// 2. RunArticles：完整文章处理任务。
// 3. ProcessFeedback：完整反馈处理任务。
// 4. callProcessArticles / callProcessFeedback：带重试的 Python gRPC 调用。
// 5. loadProfile：读取并补齐 user_profile_snapshot。
// 6. persistAgentResults / protoMcpLogs：保存 Agent 结果和 MCP 调用日志。
// 7. writeMarkdown / writeRunLog：生成 Markdown 和运行日志。
//
// 关键调用关系：
// - 被 handler.RunArticles、handler.Feedback、handler.Health 调用。
// - 调用 crawler、store、grpcclient、agentpb。
// - Python Agent 返回的 post_text、updated_profile_snapshot、mcp_call_logs 都在这里落地。
//
// 初学者阅读建议：
// 先通读 RunArticles 的步骤，再看 ProcessFeedback；
// 两条链路都遵循“创建 run_id -> 写 run_logs -> 调 Python -> 持久化结果 -> 完成 run_logs”的模式。
package harness

import (
	// context.Context 用于贯穿 HTTP、数据库和 gRPC 调用。
	"context"
	// crypto/rand 用于生成 run_id 的随机后缀。
	"crypto/rand"
	"crypto/sha256"
	// encoding/hex 用于把随机字节转成字符串。
	"encoding/hex"
	"encoding/json"
	"errors"
	// fmt 用于格式化步骤消息和 Markdown 文本。
	"fmt"
	"math"
	"net"
	// os 用于创建输出目录和写 Markdown 文件。
	"os"
	// filepath 用于处理输出目录的绝对路径和文件路径。
	"path/filepath"
	// strings 用于拼接 Markdown 和清理 post id。
	"strings"
	// time 用于超时、重试等待、run_id 时间戳和步骤时间。
	"time"

	// agentpb 是根据 agent.proto 生成的 Go protobuf 类型。
	"knowledge-post-agent/goframe-backend/internal/agentpb"
	// config 保存后端配置结构。
	"knowledge-post-agent/goframe-backend/internal/config"
	// crawler 负责 RSS 抓取和去重。
	"knowledge-post-agent/goframe-backend/internal/crawler"
	// grpcclient 封装 Python Agent gRPC 调用。
	"knowledge-post-agent/goframe-backend/internal/grpcclient"
	// model 定义数据库模型。
	"knowledge-post-agent/goframe-backend/internal/model"
	"knowledge-post-agent/goframe-backend/internal/observability"
	// store 是 MySQL 数据访问层。
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"knowledge-post-agent/goframe-backend/internal/store"
)

const (
	TaskStatusPending            = "pending"
	TaskStatusRunning            = "running"
	TaskStatusCompleted          = "completed"
	TaskStatusFailed             = "failed"
	TaskStatusPartiallyCompleted = "partially_completed"
	TaskStatusCancelled          = "cancelled"

	StepStatusRunning   = "running"
	StepStatusCompleted = "completed"
	StepStatusFailed    = "failed"
	StepStatusSkipped   = "skipped"
	StepStatusRetrying  = "retrying"

	TaskTypeArticles       = "articles"
	TaskTypeFeedback       = "feedback"
	TaskTypeProfileRebuild = "profile_rebuild"
)

// Harness 是 GoFrame 后端的业务编排器。
// 它让 HTTP handler 不需要知道 RSS、gRPC、MySQL 和 Markdown 的具体细节。
type articleStore interface {
	InsertArticle(context.Context, model.Article) (bool, error)
	UpsertCrawlSourceRun(context.Context, model.CrawlSourceRun) error
	InsertPost(context.Context, model.Post) error
	InsertFeedbackLog(context.Context, model.FeedbackLog) error
	UpsertFeedbackReceived(context.Context, model.FeedbackLog, string, map[string]any) (model.FeedbackRecord, bool, error)
	MarkFeedbackProcessing(context.Context, uint64) error
	MarkFeedbackCompleted(context.Context, uint64, string, int) error
	MarkFeedbackFailed(context.Context, uint64, string) error
	ListCompletedStructuredFeedback(context.Context, string) ([]model.FeedbackRecord, error)
	InsertRunLog(context.Context, model.RunLog) error
	CreateTaskRun(context.Context, model.TaskRun) (model.TaskRun, error)
	UpdateTaskRun(context.Context, model.TaskRun) error
	MarkTaskRunStatus(context.Context, string, string, string, map[string]any) error
	UpsertTaskStep(context.Context, model.TaskStep) error
	TaskRun(context.Context, string) (model.TaskRun, error)
	ListTaskRuns(context.Context, model.TaskRunFilter) ([]model.TaskRun, error)
	ListTaskSteps(context.Context, string) ([]model.TaskStep, error)
	RecoverInterruptedTaskRuns(context.Context, string) ([]model.TaskRun, error)
	RequestTaskCancellation(context.Context, string) (model.TaskRun, error)
	ArticleHasPost(context.Context, string) (bool, error)
	InsertUserProfileSnapshot(context.Context, string, map[string]string, string) error
	ActiveUserProfileSnapshot(context.Context, string) (model.UserProfileSnapshot, error)
	ListUserProfileSnapshots(context.Context, string, int) ([]model.UserProfileSnapshot, error)
	InsertUserProfileSnapshotVersion(context.Context, model.UserProfileSnapshot) (model.UserProfileSnapshot, error)
	RollbackUserProfileSnapshot(context.Context, string, int, string) (model.UserProfileSnapshot, error)
	InsertMemoryCompensationTask(context.Context, model.MemoryCompensationTask) error
	InsertMcpCallLogs(context.Context, []model.McpCallLog) error
	LatestUserProfileSnapshot(context.Context, string) (map[string]string, error)
}

type sourceCrawler interface {
	FetchSource(context.Context, crawler.Source) crawler.SourceResult
}

type Harness struct {
	// cfg 是归一化后的服务配置。
	cfg config.Config
	// store 用于所有 MySQL 读写。
	store articleStore
	// crawler 用于抓取 RSS 或 mock 文章。
	crawler sourceCrawler
	// processFeedbackFunc 仅用于测试注入，生产路径继续走 gRPC。
	processFeedbackFunc func(context.Context, string, string, FeedbackRequest, map[string]string, *stepRecorder) (*agentpb.ProcessFeedbackResponse, error)
	processArticlesFunc func(context.Context, string, []model.Article, map[string]string, *stepRecorder) (*agentpb.ProcessArticlesResponse, error)
	instanceID          string
	running             chan struct{}
}

// StepLog 表示任务执行中的一个步骤。
// 它会写入 run_logs.metadata.steps，方便接口返回和排查失败位置。
type StepLog struct {
	// Name 是步骤名称，例如 fetch、grpc_process_articles。
	Name string `json:"name"`
	// Status 是 ok、failed、retry、skipped 等状态。
	Status string `json:"status"`
	// Message 保存步骤补充信息。
	Message string `json:"message,omitempty"`
	// At 是步骤发生时间。
	At            string `json:"at"`
	StartedAt     string `json:"started_at,omitempty"`
	CompletedAt   string `json:"completed_at,omitempty"`
	InputSummary  string `json:"input_summary,omitempty"`
	OutputSummary string `json:"output_summary,omitempty"`
	ErrorMessage  string `json:"error_message,omitempty"`
	RetryCount    int    `json:"retry_count,omitempty"`
}

// RunArticlesResult 是 POST /runs/articles 返回的任务结果。
type RunArticlesResult struct {
	// RunID 是本次文章任务 id。
	RunID string `json:"run_id"`
	// Status 表示 running、completed 或 failed。
	Status string `json:"status"`
	// SourcesFetched 是参与抓取的 RSS 源数量。
	SourcesFetched int `json:"sources_fetched"`
	// CandidateCount 是抓取到的候选文章数量。
	CandidateCount int `json:"candidate_count"`
	// NewArticles 是成功新入库的文章数量。
	NewArticles int `json:"new_articles"`
	// ProcessedCount 是 Python Agent 返回的处理结果数量。
	ProcessedCount int `json:"processed_count"`
	// PostsSaved 是写入 posts 表的数量。
	PostsSaved int `json:"posts_saved"`
	// MarkdownPath 是本次输出的 Markdown 文件路径。
	MarkdownPath string `json:"markdown_path"`
	// Steps 保存任务执行步骤。
	Steps []StepLog `json:"steps"`
	// Error 保存失败原因。
	Error string `json:"error,omitempty"`
}

// FeedbackRequest 是 POST /feedback 的请求结构。
type FeedbackRequest struct {
	// PostID 是被反馈的 post_uid。
	PostID string `json:"post_id"`
	// ArticleID 是关联 article_uid。
	ArticleID string `json:"article_id"`
	// UserID 是反馈用户；缺失时使用配置默认用户。
	UserID string `json:"user_id"`
	// FeedbackText 是用户反馈正文。
	FeedbackText string `json:"feedback_text"`
	// FeedbackType 是反馈类型，缺失时默认 text。
	FeedbackType string `json:"feedback_type"`
	// Rating 是评分。
	Rating int `json:"rating"`
}

// FeedbackResult 是 POST /feedback 返回的任务结果。
type FeedbackResult struct {
	// RunID 是本次反馈任务 id。
	RunID string `json:"run_id"`
	// Status 表示 running、completed 或 failed。
	Status string `json:"status"`
	// Sentiment 是 Python FeedbackAgent 返回的整体情绪。
	Sentiment string `json:"sentiment"`
	// ExtractedFeedback 是 Python Agent 提取出的偏好信号。
	ExtractedFeedback []string `json:"extracted_feedback"`
	// UpdatedProfileSnapshot 是更新后的用户画像快照。
	UpdatedProfileSnapshot map[string]string `json:"updated_profile_snapshot"`
	// Error 保存失败原因。
	Error string `json:"error,omitempty"`
	// Steps 保存执行步骤。
	Steps []StepLog `json:"steps"`
}

type RebuildProfileRequest struct {
	UserID      string `json:"user_id"`
	FromVersion int    `json:"from_version"`
	DryRun      bool   `json:"dry_run"`
}

type RebuildProfileResult struct {
	RunID          string    `json:"run_id"`
	Status         string    `json:"status"`
	UserID         string    `json:"user_id"`
	ProfileVersion int       `json:"profile_version"`
	Error          string    `json:"error,omitempty"`
	Steps          []StepLog `json:"steps"`
}

type RetryTaskResult struct {
	RunID          string                `json:"run_id"`
	TaskType       string                `json:"task_type"`
	Status         string                `json:"status"`
	Articles       *RunArticlesResult    `json:"articles,omitempty"`
	Feedback       *FeedbackResult       `json:"feedback,omitempty"`
	RebuildProfile *RebuildProfileResult `json:"rebuild_profile,omitempty"`
	Error          string                `json:"error,omitempty"`
}

// 函数作用：
// 创建 Harness。
//
// 参数说明：
// - cfg：后端配置。
// - store：MySQL 数据访问对象。
//
// 返回值：
// - 返回 *Harness。
func New(cfg config.Config, store *store.Store) *Harness {
	cfg = cfg.Normalize()
	return newWithDependencies(cfg, store, crawler.New(crawler.Options{
		HTTP: crawler.HTTPOptions{
			UserAgent:        cfg.Crawler.UserAgent,
			Timeout:          time.Duration(cfg.Crawler.RequestTimeoutSeconds) * time.Second,
			RetryTimes:       cfg.Crawler.RetryTimes,
			BackoffBase:      time.Duration(cfg.Crawler.RetryBackoffMilliseconds) * time.Millisecond,
			MaxRetryDelay:    time.Duration(cfg.Crawler.MaxRetryDelayMilliseconds) * time.Millisecond,
			PerHostInterval:  time.Duration(cfg.Crawler.PerHostIntervalMilliseconds) * time.Millisecond,
			MaxResponseBytes: cfg.Crawler.MaxResponseBytes,
		},
		RobotsCacheTTL: time.Duration(cfg.Crawler.RobotsCacheSeconds) * time.Second,
		SourceMaxItems: cfg.Crawler.SourceMaxItems,
	}))
}

func newWithDependencies(cfg config.Config, store articleStore, sourceCrawler sourceCrawler) *Harness {
	cfg = cfg.Normalize()
	limit := cfg.Harness.MaxConcurrentTasks
	if limit <= 0 {
		limit = 2
	}
	return &Harness{
		cfg:        cfg,
		store:      store,
		crawler:    sourceCrawler,
		instanceID: newInstanceID(),
		running:    make(chan struct{}, limit),
	}
}

func newInstanceID() string {
	host, err := os.Hostname()
	if err != nil || host == "" {
		host = "localhost"
	}
	addrs, _ := net.InterfaceAddrs()
	return fmt.Sprintf("%s-%d-%d", host, len(addrs), time.Now().UTC().UnixNano())
}

// 函数作用：
// 检查 Python Agent Service 健康状态。
//
// 参数说明：
// - ctx：调用上下文。
// - cfg：配置，主要读取 Agent 地址和超时。
//
// 返回值：
// - 返回 HealthCheckResponse 或 error。
//
// 调用关系：
// - 被 main.go healthcheck 模式和 Handler.Health 调用。
func AgentHealth(ctx context.Context, cfg config.Config) (*agentpb.HealthCheckResponse, error) {
	// 根据配置计算 gRPC 连接和调用超时。
	timeout := time.Duration(cfg.Agent.TimeoutSeconds) * time.Second
	// 创建 gRPC client。
	client, err := grpcclient.New(ctx, cfg.Agent.Address, timeout)
	if err != nil {
		return nil, err
	}
	// 函数返回前关闭连接，避免泄漏。
	defer client.Close()
	// 每次 RPC 调用也使用独立超时上下文。
	callCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	// 调用 Python Agent HealthCheck。
	return client.HealthCheck(callCtx)
}

// 函数作用：
// 使用 Harness 自身配置检查 Python Agent 健康状态。
//
// 参数说明：
// - ctx：调用上下文。
//
// 返回值：
// - 返回 HealthCheckResponse 或 error。
func (h *Harness) AgentHealth(ctx context.Context) (*agentpb.HealthCheckResponse, error) {
	return AgentHealth(ctx, h.cfg)
}

func (h *Harness) startTask(ctx context.Context, task model.TaskRun) (model.TaskRun, error) {
	if h.running != nil {
		select {
		case h.running <- struct{}{}:
		case <-ctx.Done():
			return model.TaskRun{}, ctx.Err()
		default:
			return model.TaskRun{}, errors.New("concurrent task limit reached")
		}
	}
	if task.Status == "" {
		task.Status = TaskStatusPending
	}
	task.MaxRetries = h.cfg.Harness.StepMaxRetries
	task.TimeoutSeconds = h.cfg.Harness.TaskTimeoutSeconds
	task.LockedBy = h.instanceID
	created, err := h.store.CreateTaskRun(ctx, task)
	if err != nil {
		h.releaseTaskSlot()
		return model.TaskRun{}, err
	}
	if created.RunID != task.RunID && (created.Status == TaskStatusPending || created.Status == TaskStatusRunning) {
		h.releaseTaskSlot()
		return created, nil
	}
	if created.Status == TaskStatusCancelled {
		h.releaseTaskSlot()
		return created, nil
	}
	if created.TimeoutSeconds <= 0 {
		created.TimeoutSeconds = h.cfg.Harness.TaskTimeoutSeconds
	}
	startedAt := time.Now().UTC()
	created.Status = TaskStatusRunning
	created.StartedAt = &startedAt
	created.LockedBy = h.instanceID
	if err := h.store.UpdateTaskRun(ctx, created); err != nil {
		h.releaseTaskSlot()
		return model.TaskRun{}, err
	}
	return created, nil
}

func (h *Harness) releaseTaskSlot() {
	if h.running == nil {
		return
	}
	select {
	case <-h.running:
	default:
	}
}

func (h *Harness) finishTask(ctx context.Context, runID string, status string, errorMessage string, partial map[string]any) {
	if status == "" {
		status = TaskStatusFailed
	}
	_ = h.store.MarkTaskRunStatus(ctx, runID, status, errorMessage, partial)
}

func (h *Harness) updateTaskPartial(ctx context.Context, runID string, currentStep string, partial map[string]any) {
	_ = h.store.UpdateTaskRun(ctx, model.TaskRun{
		RunID:         runID,
		Status:        TaskStatusRunning,
		CurrentStep:   currentStep,
		PartialResult: partial,
		LockedBy:      h.instanceID,
	})
}

func (h *Harness) taskCancelled(ctx context.Context, runID string) bool {
	task, err := h.store.TaskRun(ctx, runID)
	if err != nil {
		return false
	}
	return task.CancelRequested || task.Status == TaskStatusCancelled
}

func (h *Harness) finishArticlesCancelled(ctx context.Context, result RunArticlesResult, steps *stepRecorder) RunArticlesResult {
	result.Status = TaskStatusCancelled
	result.Error = "task cancellation requested"
	steps.add("cancel", TaskStatusCancelled, result.Error)
	h.finishTask(ctx, result.RunID, TaskStatusCancelled, result.Error, articlesPartialResult(result))
	h.writeRunLog(ctx, result, TaskStatusCancelled, result.Error)
	return result
}

func articlesPartialResult(result RunArticlesResult) map[string]any {
	return map[string]any{
		"sources_fetched":  result.SourcesFetched,
		"candidate_count":  result.CandidateCount,
		"new_articles":     result.NewArticles,
		"processed_count":  result.ProcessedCount,
		"posts_saved":      result.PostsSaved,
		"markdown_path":    result.MarkdownPath,
		"last_error":       result.Error,
		"terminal_status":  result.Status,
		"partial_saved_at": time.Now().UTC().Format(time.RFC3339),
	}
}

func articlesPartialResultWithArticles(result RunArticlesResult, articles []model.Article) map[string]any {
	partial := articlesPartialResult(result)
	partial["processable_articles"] = articleSnapshots(articles)
	return partial
}

func articleSnapshots(articles []model.Article) []map[string]any {
	out := make([]map[string]any, 0, len(articles))
	for _, article := range articles {
		out = append(out, map[string]any{
			"id":           article.ID,
			"url":          article.URL,
			"title":        article.Title,
			"content":      article.Content,
			"source":       article.Source,
			"source_type":  article.SourceType,
			"published_at": article.PublishedAt,
			"tags":         article.Tags,
			"fetch_status": article.FetchStatus,
		})
	}
	return out
}

func articlesFromPartialResult(partial map[string]any) []model.Article {
	raw, ok := partial["processable_articles"]
	if !ok || raw == nil {
		return nil
	}
	encoded, err := json.Marshal(raw)
	if err != nil {
		return nil
	}
	var snapshots []map[string]any
	if err := json.Unmarshal(encoded, &snapshots); err != nil {
		return nil
	}
	out := make([]model.Article, 0, len(snapshots))
	for _, snapshot := range snapshots {
		article := model.Article{
			ID:          stringFromMap(snapshot, "id"),
			URL:         stringFromMap(snapshot, "url"),
			Title:       stringFromMap(snapshot, "title"),
			Content:     stringFromMap(snapshot, "content"),
			Source:      stringFromMap(snapshot, "source"),
			SourceType:  stringFromMap(snapshot, "source_type"),
			PublishedAt: stringFromMap(snapshot, "published_at"),
			FetchStatus: stringFromMap(snapshot, "fetch_status"),
		}
		if article.FetchStatus == "" {
			article.FetchStatus = "success"
		}
		if tags, ok := snapshot["tags"].([]any); ok {
			for _, tag := range tags {
				article.Tags = append(article.Tags, fmt.Sprint(tag))
			}
		}
		if article.ID != "" {
			out = append(out, article)
		}
	}
	return out
}

func stringFromMap(values map[string]any, key string) string {
	if value, ok := values[key]; ok {
		return fmt.Sprint(value)
	}
	return ""
}

func intFromPartial(partial map[string]any, key string, fallback int) int {
	if value, ok := partial[key]; ok {
		return int(anyFloat(value, float64(fallback)))
	}
	return fallback
}

func feedbackRequestPayload(req FeedbackRequest, userID string) map[string]any {
	return map[string]any{
		"post_id":       req.PostID,
		"article_id":    req.ArticleID,
		"user_id":       userID,
		"feedback_text": req.FeedbackText,
		"feedback_type": req.FeedbackType,
		"rating":        req.Rating,
	}
}

func feedbackRequestFromPayload(payload map[string]any) FeedbackRequest {
	return FeedbackRequest{
		PostID:       stringFromMap(payload, "post_id"),
		ArticleID:    stringFromMap(payload, "article_id"),
		UserID:       stringFromMap(payload, "user_id"),
		FeedbackText: stringFromMap(payload, "feedback_text"),
		FeedbackType: stringFromMap(payload, "feedback_type"),
		Rating:       intFromPartial(payload, "rating", 0),
	}
}

func feedbackPartialResult(result FeedbackResult) map[string]any {
	return map[string]any{
		"sentiment":                result.Sentiment,
		"extracted_feedback_count": len(result.ExtractedFeedback),
		"has_profile_snapshot":     result.UpdatedProfileSnapshot != nil,
		"last_error":               result.Error,
		"terminal_status":          result.Status,
		"partial_saved_at":         time.Now().UTC().Format(time.RFC3339),
	}
}

func rebuildRequestPayload(req RebuildProfileRequest, userID string) map[string]any {
	return map[string]any{
		"user_id":      userID,
		"from_version": req.FromVersion,
		"dry_run":      req.DryRun,
	}
}

func rebuildRequestFromPayload(payload map[string]any) RebuildProfileRequest {
	return RebuildProfileRequest{
		UserID:      stringFromMap(payload, "user_id"),
		FromVersion: intFromPartial(payload, "from_version", 0),
		DryRun:      boolFromMap(payload, "dry_run"),
	}
}

func rebuildPartialResult(result RebuildProfileResult, feedbackCount int) map[string]any {
	return map[string]any{
		"user_id":          result.UserID,
		"profile_version":  result.ProfileVersion,
		"feedback_count":   feedbackCount,
		"last_error":       result.Error,
		"terminal_status":  result.Status,
		"partial_saved_at": time.Now().UTC().Format(time.RFC3339),
	}
}

func boolFromMap(values map[string]any, key string) bool {
	value, ok := values[key]
	if !ok {
		return false
	}
	switch typed := value.(type) {
	case bool:
		return typed
	case string:
		return strings.EqualFold(typed, "true") || typed == "1"
	default:
		return anyFloat(value, 0) != 0
	}
}

func partialStatus(savedOutputs int, savedInputs int) string {
	if savedOutputs > 0 || savedInputs > 0 {
		return TaskStatusPartiallyCompleted
	}
	return TaskStatusFailed
}

func (h *Harness) filterArticlesWithoutPosts(ctx context.Context, articles []model.Article, steps *stepRecorder) ([]model.Article, error) {
	out := make([]model.Article, 0, len(articles))
	skipped := 0
	for _, article := range articles {
		exists, err := h.store.ArticleHasPost(ctx, article.ID)
		if err != nil {
			return nil, err
		}
		if exists {
			skipped++
			continue
		}
		out = append(out, article)
	}
	if skipped > 0 {
		steps.add("dedupe_posts", StepStatusCompleted, fmt.Sprintf("skipped %d articles with existing posts", skipped))
	}
	return out, nil
}

func (h *Harness) CancelTask(ctx context.Context, runID string) (model.TaskRun, error) {
	return h.store.RequestTaskCancellation(ctx, runID)
}

func (h *Harness) GetTaskRun(ctx context.Context, runID string) (model.TaskRun, error) {
	task, err := h.store.TaskRun(ctx, runID)
	if err != nil {
		return model.TaskRun{}, err
	}
	steps, err := h.store.ListTaskSteps(ctx, runID)
	if err != nil {
		return model.TaskRun{}, err
	}
	task.Steps = steps
	return task, nil
}

func (h *Harness) ListTaskRuns(ctx context.Context, filter model.TaskRunFilter) ([]model.TaskRun, error) {
	return h.store.ListTaskRuns(ctx, filter)
}

func (h *Harness) RecoverInterruptedTasks(ctx context.Context) ([]model.TaskRun, error) {
	return h.store.RecoverInterruptedTaskRuns(ctx, h.instanceID)
}

func (h *Harness) RetryTask(ctx context.Context, runID string) RunArticlesResult {
	task, err := h.store.TaskRun(ctx, runID)
	if err != nil {
		return RunArticlesResult{RunID: runID, Status: TaskStatusFailed, Error: err.Error()}
	}
	if task.TaskType != TaskTypeArticles {
		return RunArticlesResult{RunID: runID, Status: TaskStatusFailed, Error: "only article tasks can be retried by this endpoint"}
	}
	if task.Status != TaskStatusFailed && task.Status != TaskStatusPartiallyCompleted && task.Status != TaskStatusPending {
		return RunArticlesResult{RunID: runID, Status: task.Status, Error: "task is not retryable"}
	}
	task.Status = TaskStatusPending
	task.CancelRequested = false
	task.RetryCount++
	if err := h.store.UpdateTaskRun(ctx, task); err != nil {
		return RunArticlesResult{RunID: runID, Status: TaskStatusFailed, Error: err.Error()}
	}
	return h.runArticles(ctx, runID, &task)
}

func (h *Harness) RetryTaskRun(ctx context.Context, runID string) RetryTaskResult {
	task, err := h.store.TaskRun(ctx, runID)
	if err != nil {
		return RetryTaskResult{RunID: runID, Status: TaskStatusFailed, Error: err.Error()}
	}
	if task.Status != TaskStatusFailed && task.Status != TaskStatusPartiallyCompleted && task.Status != TaskStatusPending {
		return RetryTaskResult{RunID: runID, TaskType: task.TaskType, Status: task.Status, Error: "task is not retryable"}
	}
	switch task.TaskType {
	case TaskTypeArticles:
		result := h.RetryTask(ctx, runID)
		return RetryTaskResult{RunID: result.RunID, TaskType: TaskTypeArticles, Status: result.Status, Articles: &result, Error: result.Error}
	case TaskTypeFeedback:
		req := feedbackRequestFromPayload(task.InputPayload)
		result := h.processFeedback(ctx, runID, &task, req)
		return RetryTaskResult{RunID: result.RunID, TaskType: TaskTypeFeedback, Status: result.Status, Feedback: &result, Error: result.Error}
	case TaskTypeProfileRebuild:
		req := rebuildRequestFromPayload(task.InputPayload)
		result := h.rebuildProfile(ctx, runID, &task, req)
		return RetryTaskResult{RunID: result.RunID, TaskType: TaskTypeProfileRebuild, Status: result.Status, RebuildProfile: &result, Error: result.Error}
	default:
		return RetryTaskResult{RunID: runID, TaskType: task.TaskType, Status: TaskStatusFailed, Error: "unsupported task type"}
	}
}

// 函数作用：
// 执行一次完整文章处理任务。
//
// 参数说明：
// - ctx：HTTP 请求上下文，会传递到数据库和 gRPC。
//
// 返回值：
// - 返回 RunArticlesResult，包含步骤、计数、Markdown 路径和错误信息。
//
// 流程说明：
// 1. 创建 run_id 并写入 running run_logs。
// 2. 抓取 RSS/mock 文章并去重。
// 3. 写入 articles 表，只保留新文章。
// 4. 读取 user_profile_snapshot。
// 5. 调用 Python Agent ProcessArticles。
// 6. 保存 posts 和 mcp_call_logs。
// 7. 生成 Markdown，写入 completed run_logs。
func (h *Harness) RunArticles(ctx context.Context) RunArticlesResult {
	return h.runArticles(ctx, newRunID("articles"), nil)
}

func (h *Harness) runArticles(ctx context.Context, runID string, existing *model.TaskRun) RunArticlesResult {
	startedAt := time.Now()
	ctx = observability.WithRunID(ctx, runID)
	userID := h.cfg.Profile.UserID
	if existing != nil && existing.UserID != "" {
		userID = existing.UserID
	}
	result := RunArticlesResult{RunID: runID, Status: TaskStatusPending}
	defer func() {
		observability.RecordTaskRun(ctx, TaskTypeArticles, metricTaskStatus(result.Status), time.Since(startedAt).Seconds())
	}()
	task, err := h.startTask(ctx, model.TaskRun{
		RunID:          runID,
		TaskType:       TaskTypeArticles,
		UserID:         userID,
		Status:         TaskStatusPending,
		IdempotencyKey: runID,
		InputSummary:   "crawler articles run",
		InputPayload: map[string]any{
			"source_count": len(h.cfg.Crawler.Sources),
			"user_id":      userID,
		},
	})
	if err != nil {
		result.Status = TaskStatusFailed
		result.Error = err.Error()
		return result
	}
	if task.Status == TaskStatusCancelled {
		result.Status = TaskStatusCancelled
		result.Error = task.ErrorMessage
		return result
	}
	if task.RunID != runID && (task.Status == TaskStatusPending || task.Status == TaskStatusRunning) {
		result = RunArticlesResult{
			RunID:  task.RunID,
			Status: task.Status,
			Error:  "user already has an active article task",
		}
		return result
	}
	ctx, cancel := context.WithTimeout(ctx, time.Duration(task.TimeoutSeconds)*time.Second)
	defer cancel()
	defer h.releaseTaskSlot()

	result.Status = TaskStatusRunning
	// stepRecorder 用指针写 result.Steps，便于各 helper 统一追加步骤。
	steps := stepRecorder{ctx: ctx, runID: result.RunID, store: h.store, steps: &result.Steps}
	steps.add("start", StepStatusCompleted, "created run")
	// 任务开始时写入 run_logs，方便长任务执行中也能被查询到。
	h.writeRunLog(ctx, result, TaskStatusRunning, "")

	// 抓取已启用的统一来源。
	if h.taskCancelled(ctx, result.RunID) {
		return h.finishArticlesCancelled(ctx, result, &steps)
	}
	articles, sourceResults := h.fetchArticles(ctx, result.RunID, &steps)
	result.SourcesFetched = len(sourceResults)
	result.CandidateCount = len(articles)
	// 按 article ID 去重，并限制单次任务处理数量。
	deduped := crawler.Deduplicate(articles, h.cfg.Crawler.RunMaxArticles)
	steps.add("dedupe", "ok", fmt.Sprintf("%d candidates -> %d unique", len(articles), len(deduped)))

	// newArticles 只保存本次新插入 articles 表的文章。
	newArticles := make([]model.Article, 0, len(deduped))
	savedBySource := make(map[string]int)
	for _, article := range deduped {
		// InsertArticle 使用 INSERT IGNORE，重复文章不会报错。
		inserted, err := h.store.InsertArticle(ctx, article)
		if err != nil {
			// 写库失败时结束任务并写 failed run_logs。
			result.Status = TaskStatusFailed
			result.Error = err.Error()
			steps.add("save_articles", StepStatusFailed, err.Error())
			h.finishTask(ctx, result.RunID, result.Status, result.Error, articlesPartialResult(result))
			h.writeRunLog(ctx, result, TaskStatusFailed, result.Error)
			return result
		}
		// 只有新文章才进入 Python Agent，避免重复生成 posts。
		if inserted {
			newArticles = append(newArticles, article)
			savedBySource[article.Source]++
		}
	}
	h.updateSourceRunSavedCounts(ctx, result.RunID, sourceResults, savedBySource, &steps)
	result.NewArticles = len(newArticles)
	steps.add("save_articles", StepStatusCompleted, fmt.Sprintf("%d new articles", len(newArticles)))
	h.updateTaskPartial(ctx, result.RunID, "save_articles", articlesPartialResult(result))
	h.writeRunLog(ctx, result, TaskStatusRunning, "")
	if existing != nil && len(newArticles) == 0 {
		if recovered := articlesFromPartialResult(existing.PartialResult); len(recovered) > 0 {
			newArticles = recovered
			result.NewArticles = intFromPartial(existing.PartialResult, "new_articles", len(recovered))
			steps.add("resume_articles", StepStatusCompleted, fmt.Sprintf("%d articles from partial_result", len(recovered)))
		}
	}

	processableArticles := crawler.Processable(newArticles)
	processableArticles, err = h.filterArticlesWithoutPosts(ctx, processableArticles, &steps)
	if err != nil {
		result.Status = TaskStatusFailed
		result.Error = err.Error()
		steps.add("dedupe_posts", StepStatusFailed, err.Error())
		h.finishTask(ctx, result.RunID, result.Status, result.Error, articlesPartialResult(result))
		h.writeRunLog(ctx, result, TaskStatusFailed, result.Error)
		return result
	}
	if allSourcesFailed(sourceResults) && len(processableArticles) == 0 {
		result.Status = TaskStatusFailed
		result.Error = "all crawler sources failed"
		steps.add("process_articles", StepStatusFailed, result.Error)
		h.finishTask(ctx, result.RunID, result.Status, result.Error, articlesPartialResult(result))
		h.writeRunLog(ctx, result, TaskStatusFailed, result.Error)
		return result
	}
	// 没有可处理的新文章时跳过 Python Agent 调用。
	if len(processableArticles) == 0 {
		result.Status = TaskStatusCompleted
		steps.add("process_articles", StepStatusSkipped, "no new processable articles")
		h.finishTask(ctx, result.RunID, result.Status, "", articlesPartialResult(result))
		h.writeRunLog(ctx, result, TaskStatusCompleted, "")
		return result
	}
	h.updateTaskPartial(ctx, result.RunID, "process_articles", articlesPartialResultWithArticles(result, processableArticles))

	if h.taskCancelled(ctx, result.RunID) {
		return h.finishArticlesCancelled(ctx, result, &steps)
	}
	// 读取最新用户画像快照，并补齐默认 user_id/interests。
	profileSnapshot := h.loadProfileSnapshot(ctx)
	profile := normalizeProfile(profileSnapshot.Snapshot, h.cfg.Profile.UserID, h.cfg.Profile.Interests)
	// 调用 Python Agent ProcessArticles。
	response, err := h.callProcessArticles(ctx, result.RunID, processableArticles, profile, &steps)
	if err != nil {
		// gRPC 调用最终失败时，任务失败并记录 run_logs。
		result.Status = partialStatus(result.PostsSaved, result.NewArticles)
		result.Error = err.Error()
		steps.add("process_articles", StepStatusFailed, err.Error())
		h.finishTask(ctx, result.RunID, result.Status, result.Error, articlesPartialResultWithArticles(result, processableArticles))
		h.writeRunLog(ctx, result, result.Status, result.Error)
		return result
	}
	// Python 返回的结果数量。
	result.ProcessedCount = len(response.Results)
	// 建立 article_id -> Article 的 map，便于把 Agent 结果对应回标题和标签。
	articleByID := mapArticles(processableArticles)
	// 保存 posts，并收集 Python Agent 返回的 MCP 调用日志。
	posts, mcpLogs := h.persistAgentResults(ctx, result.RunID, response, articleByID, profileSnapshot.Version, &steps)
	result.PostsSaved = len(posts)
	// 将 MCP 调用日志批量写入 mcp_call_logs 表。
	if len(mcpLogs) > 0 {
		if err := h.store.InsertMcpCallLogs(ctx, mcpLogs); err != nil {
			steps.add("save_mcp_logs", StepStatusFailed, err.Error())
		} else {
			steps.add("save_mcp_logs", StepStatusCompleted, fmt.Sprintf("%d logs", len(mcpLogs)))
		}
	}
	h.updateTaskPartial(ctx, result.RunID, "save_posts", articlesPartialResult(result))

	// 将本次生成的 posts 输出成 Markdown 文件。
	markdownPath, err := h.writeMarkdown(result.RunID, posts)
	if err != nil {
		result.Status = partialStatus(result.PostsSaved, result.NewArticles)
		result.Error = err.Error()
		steps.add("write_markdown", StepStatusFailed, err.Error())
		h.finishTask(ctx, result.RunID, result.Status, result.Error, articlesPartialResult(result))
		h.writeRunLog(ctx, result, result.Status, result.Error)
		return result
	}
	result.MarkdownPath = markdownPath
	steps.add("write_markdown", StepStatusCompleted, markdownPath)

	// 所有步骤完成，写 completed run_logs。
	result.Status = TaskStatusCompleted
	h.finishTask(ctx, result.RunID, result.Status, "", articlesPartialResult(result))
	h.writeRunLog(ctx, result, TaskStatusCompleted, "")
	return result
}

// 函数作用：
// 执行一次用户反馈处理任务。
//
// 参数说明：
// - ctx：HTTP 请求上下文。
// - req：反馈请求。
//
// 返回值：
// - 返回 FeedbackResult。
//
// 流程说明：
// 1. 创建反馈 run_id 并写 running run_logs。
// 2. 写 feedback_logs 保存原始反馈。
// 3. 读取 user_profile_snapshot。
// 4. 调用 Python Agent ProcessFeedback。
// 5. 写入新的 user_profile_snapshot。
// 6. 写入 mcp_call_logs 并完成 run_logs。
func (h *Harness) ProcessFeedback(ctx context.Context, req FeedbackRequest) FeedbackResult {
	return h.processFeedback(ctx, newRunID("feedback"), nil, req)
}

func (h *Harness) processFeedback(ctx context.Context, runID string, existing *model.TaskRun, req FeedbackRequest) FeedbackResult {
	startedAt := time.Now()
	ctx = observability.WithRunID(ctx, runID)
	// 初始化反馈任务结果。
	result := FeedbackResult{RunID: runID, Status: TaskStatusPending}
	defer func() {
		observability.RecordTaskRun(ctx, TaskTypeFeedback, metricTaskStatus(result.Status), time.Since(startedAt).Seconds())
	}()
	// userID 优先使用请求值，缺失时用配置默认用户。
	userID := firstNonEmpty(req.UserID, h.cfg.Profile.UserID)
	// feedback_type 缺失时默认 text。
	if req.FeedbackType == "" {
		req.FeedbackType = "text"
	}
	task, err := h.startTask(ctx, model.TaskRun{
		RunID:          runID,
		TaskType:       TaskTypeFeedback,
		UserID:         userID,
		Status:         TaskStatusPending,
		IdempotencyKey: store.FeedbackIdempotencyKey(userID, req.PostID, req.ArticleID, req.FeedbackType, req.Rating, req.FeedbackText),
		InputSummary:   "feedback processing",
		InputPayload:   feedbackRequestPayload(req, userID),
	})
	if err != nil {
		result.Status = TaskStatusFailed
		result.Error = err.Error()
		return result
	}
	if task.Status == TaskStatusCancelled {
		result.Status = TaskStatusCancelled
		result.Error = task.ErrorMessage
		return result
	}
	if task.RunID != runID && (task.Status == TaskStatusPending || task.Status == TaskStatusRunning) {
		result = FeedbackResult{RunID: task.RunID, Status: task.Status, Error: "user already has an active feedback task"}
		return result
	}
	ctx, cancel := context.WithTimeout(ctx, time.Duration(task.TimeoutSeconds)*time.Second)
	defer cancel()
	defer h.releaseTaskSlot()

	result.Status = TaskStatusRunning
	steps := stepRecorder{ctx: ctx, runID: result.RunID, store: h.store, steps: &result.Steps}
	steps.add("start", StepStatusCompleted, "created feedback run")
	h.writeFeedbackRunLog(ctx, result, TaskStatusRunning, "")

	feedback := model.FeedbackLog{
		RunID:        result.RunID,
		PostUID:      req.PostID,
		ArticleUID:   req.ArticleID,
		UserID:       userID,
		FeedbackType: req.FeedbackType,
		Rating:       req.Rating,
		Comment:      req.FeedbackText,
		Metadata:     map[string]any{"source": "api"},
	}
	idempotencyKey := store.FeedbackIdempotencyKey(userID, req.PostID, req.ArticleID, req.FeedbackType, req.Rating, req.FeedbackText)
	rawFeedback := map[string]any{
		"post_id":       req.PostID,
		"article_id":    req.ArticleID,
		"user_id":       userID,
		"feedback_text": req.FeedbackText,
		"feedback_type": req.FeedbackType,
		"rating":        req.Rating,
	}
	record, inserted, err := h.store.UpsertFeedbackReceived(ctx, feedback, idempotencyKey, rawFeedback)
	if err != nil {
		// 写反馈失败时结束任务。
		result.Status = TaskStatusFailed
		result.Error = err.Error()
		steps.add("save_feedback", StepStatusFailed, err.Error())
		h.finishTask(ctx, result.RunID, result.Status, result.Error, feedbackPartialResult(result))
		h.writeFeedbackRunLog(ctx, result, TaskStatusFailed, result.Error)
		return result
	}
	if inserted {
		observability.RecordUserFeedback(ctx, req.FeedbackType, "received", 1)
	}
	if !inserted && record.ProcessStatus == "completed" {
		result.RunID = record.RunID
		result.Status = TaskStatusCompleted
		result.Sentiment = "cached"
		result.UpdatedProfileSnapshot = h.loadProfile(ctx)
		steps.add("feedback_idempotent_hit", StepStatusCompleted, fmt.Sprintf("profile_version=%d", record.ProfileVersion))
		h.finishTask(ctx, result.RunID, result.Status, "", feedbackPartialResult(result))
		h.writeFeedbackRunLog(ctx, result, TaskStatusCompleted, "")
		return result
	}
	steps.add("save_feedback", StepStatusCompleted, "feedback log saved")
	h.updateTaskPartial(ctx, result.RunID, "save_feedback", feedbackPartialResult(result))
	if err := h.store.MarkFeedbackProcessing(ctx, record.ID); err != nil {
		observability.RecordUserFeedback(ctx, req.FeedbackType, "failed", 1)
		result.Status = TaskStatusFailed
		result.Error = err.Error()
		steps.add("save_feedback", StepStatusFailed, err.Error())
		h.finishTask(ctx, result.RunID, result.Status, result.Error, feedbackPartialResult(result))
		h.writeFeedbackRunLog(ctx, result, TaskStatusFailed, result.Error)
		return result
	}

	if h.taskCancelled(ctx, result.RunID) {
		result.Status = TaskStatusCancelled
		result.Error = "task cancellation requested"
		steps.add("cancel", TaskStatusCancelled, result.Error)
		h.finishTask(ctx, result.RunID, result.Status, result.Error, feedbackPartialResult(result))
		h.writeFeedbackRunLog(ctx, result, TaskStatusCancelled, result.Error)
		return result
	}
	// 读取当前最新用户画像，作为 Python MemoryAgent 更新的基础。
	profile := h.loadProfile(ctx)
	// 调用 Python Agent ProcessFeedback。
	response, err := h.callProcessFeedback(ctx, result.RunID, userID, req, profile, &steps)
	if err != nil {
		_ = h.store.MarkFeedbackFailed(ctx, record.ID, err.Error())
		observability.RecordUserFeedback(ctx, req.FeedbackType, "failed", 1)
		result.Status = TaskStatusFailed
		result.Error = err.Error()
		steps.add("process_feedback", StepStatusFailed, err.Error())
		h.finishTask(ctx, result.RunID, result.Status, result.Error, feedbackPartialResult(result))
		h.writeFeedbackRunLog(ctx, result, TaskStatusFailed, result.Error)
		return result
	}
	// 保存 Python FeedbackAgent 返回的结构化结果。
	result.Sentiment = response.Sentiment
	result.ExtractedFeedback = response.ExtractedFeedback
	result.UpdatedProfileSnapshot = response.UpdatedProfileSnapshot
	diff := decodeJSONObject(response.ProfileDiffJson)
	snapshot, err := h.store.InsertUserProfileSnapshotVersion(ctx, model.UserProfileSnapshot{
		UserID:           userID,
		RunID:            result.RunID,
		Summary:          response.Sentiment,
		Snapshot:         response.UpdatedProfileSnapshot,
		Diff:             diff,
		ChangeReason:     "feedback",
		SourceFeedbackID: record.ID,
	})
	if err != nil {
		_ = h.store.MarkFeedbackFailed(ctx, record.ID, err.Error())
		observability.RecordUserFeedback(ctx, req.FeedbackType, "failed", 1)
		result.Status = TaskStatusFailed
		result.Error = err.Error()
		steps.add("save_profile_version", StepStatusFailed, err.Error())
		h.finishTask(ctx, result.RunID, result.Status, result.Error, feedbackPartialResult(result))
		h.writeFeedbackRunLog(ctx, result, TaskStatusFailed, result.Error)
		return result
	}
	steps.add("save_profile_version", StepStatusCompleted, fmt.Sprintf("version=%d", snapshot.Version))
	if err := h.store.MarkFeedbackCompleted(ctx, record.ID, response.StructuredFeedbackJson, snapshot.Version); err != nil {
		observability.RecordUserFeedback(ctx, req.FeedbackType, "failed", 1)
		result.Status = TaskStatusFailed
		result.Error = err.Error()
		steps.add("save_feedback", StepStatusFailed, err.Error())
		h.finishTask(ctx, result.RunID, result.Status, result.Error, feedbackPartialResult(result))
		h.writeFeedbackRunLog(ctx, result, TaskStatusFailed, result.Error)
		return result
	}
	observability.RecordUserFeedback(ctx, req.FeedbackType, "processed", 1)

	// 转换并写入反馈流程产生的 MCP 调用日志。
	logs := protoMcpLogs(result.RunID, response.McpCallLogs)
	if err := h.store.InsertMcpCallLogs(ctx, logs); err != nil {
		steps.add("save_mcp_logs", StepStatusFailed, err.Error())
	} else {
		steps.add("save_mcp_logs", StepStatusCompleted, fmt.Sprintf("%d logs", len(logs)))
	}
	createdCompensation := 0
	for _, log := range logs {
		if log.Status != "failed" && log.Status != "denied" && log.Success {
			continue
		}
		task := compensationTaskForLog(userID, result.RunID, log)
		if task.TargetSystem == "" {
			continue
		}
		if err := h.store.InsertMemoryCompensationTask(ctx, task); err != nil {
			steps.add("create_compensation", StepStatusFailed, err.Error())
			continue
		}
		createdCompensation++
	}
	if createdCompensation > 0 {
		steps.add("create_compensation", StepStatusCompleted, fmt.Sprintf("%d tasks", createdCompensation))
	}

	// 标记任务完成。
	result.Status = TaskStatusCompleted
	h.finishTask(ctx, result.RunID, result.Status, "", feedbackPartialResult(result))
	h.writeFeedbackRunLog(ctx, result, TaskStatusCompleted, "")
	return result
}

func (h *Harness) RebuildProfile(ctx context.Context, req RebuildProfileRequest) RebuildProfileResult {
	return h.rebuildProfile(ctx, newRunID("profile-rebuild"), nil, req)
}

func (h *Harness) rebuildProfile(ctx context.Context, runID string, existing *model.TaskRun, req RebuildProfileRequest) RebuildProfileResult {
	startedAt := time.Now()
	ctx = observability.WithRunID(ctx, runID)
	result := RebuildProfileResult{
		RunID:  runID,
		Status: TaskStatusPending,
		UserID: firstNonEmpty(req.UserID, h.cfg.Profile.UserID),
	}
	defer func() {
		observability.RecordTaskRun(ctx, TaskTypeProfileRebuild, metricTaskStatus(result.Status), time.Since(startedAt).Seconds())
	}()
	task, err := h.startTask(ctx, model.TaskRun{
		RunID:          runID,
		TaskType:       TaskTypeProfileRebuild,
		UserID:         result.UserID,
		Status:         TaskStatusPending,
		IdempotencyKey: runID,
		InputSummary:   "profile rebuild",
		InputPayload:   rebuildRequestPayload(req, result.UserID),
	})
	if err != nil {
		result.Status = TaskStatusFailed
		result.Error = err.Error()
		return result
	}
	if task.Status == TaskStatusCancelled {
		result.Status = TaskStatusCancelled
		result.Error = task.ErrorMessage
		return result
	}
	if task.RunID != runID && (task.Status == TaskStatusPending || task.Status == TaskStatusRunning) {
		result = RebuildProfileResult{RunID: task.RunID, UserID: result.UserID, Status: task.Status, Error: "user already has an active profile rebuild task"}
		return result
	}
	ctx, cancel := context.WithTimeout(ctx, time.Duration(task.TimeoutSeconds)*time.Second)
	defer cancel()
	defer h.releaseTaskSlot()

	result.Status = TaskStatusRunning
	steps := stepRecorder{ctx: ctx, runID: result.RunID, store: h.store, steps: &result.Steps}
	steps.add("start", StepStatusCompleted, "created profile rebuild run")

	feedback, err := h.store.ListCompletedStructuredFeedback(ctx, result.UserID)
	if err != nil {
		result.Status = TaskStatusFailed
		result.Error = err.Error()
		steps.add("load_feedback", StepStatusFailed, err.Error())
		h.finishTask(ctx, result.RunID, result.Status, result.Error, rebuildPartialResult(result, 0))
		return result
	}
	steps.add("load_feedback", StepStatusCompleted, fmt.Sprintf("%d feedback records", len(feedback)))
	h.updateTaskPartial(ctx, result.RunID, "load_feedback", rebuildPartialResult(result, len(feedback)))

	if h.taskCancelled(ctx, result.RunID) {
		result.Status = TaskStatusCancelled
		result.Error = "task cancellation requested"
		steps.add("cancel", TaskStatusCancelled, result.Error)
		h.finishTask(ctx, result.RunID, result.Status, result.Error, rebuildPartialResult(result, len(feedback)))
		return result
	}

	active, activeErr := h.store.ActiveUserProfileSnapshot(ctx, result.UserID)
	if activeErr != nil {
		active = model.UserProfileSnapshot{
			UserID:   result.UserID,
			Version:  0,
			Snapshot: map[string]string{},
		}
	}
	before := normalizeProfile(active.Snapshot, result.UserID, h.cfg.Profile.Interests)
	rebuilt, changes := rebuildProfileFromFeedback(before, feedback)
	diff := map[string]any{
		"before":  before,
		"after":   rebuilt,
		"changes": changes,
	}
	payload := map[string]any{
		"user_id":        result.UserID,
		"from_version":   req.FromVersion,
		"dry_run":        req.DryRun,
		"feedback_count": len(feedback),
	}
	if err := h.store.InsertMemoryCompensationTask(ctx, model.MemoryCompensationTask{
		TaskID:       result.RunID,
		RunID:        result.RunID,
		UserID:       result.UserID,
		TaskType:     "profile_rebuild",
		TargetSystem: "mysql",
		Payload:      payload,
		Status:       "completed",
	}); err != nil {
		result.Status = TaskStatusFailed
		result.Error = err.Error()
		steps.add("record_rebuild_task", StepStatusFailed, err.Error())
		h.finishTask(ctx, result.RunID, result.Status, result.Error, rebuildPartialResult(result, len(feedback)))
		return result
	}
	steps.add("record_rebuild_task", StepStatusCompleted, "profile rebuild task recorded")
	if req.DryRun {
		result.ProfileVersion = active.Version
		steps.add("save_profile_version", StepStatusSkipped, "dry_run")
		result.Status = TaskStatusCompleted
		h.finishTask(ctx, result.RunID, result.Status, "", rebuildPartialResult(result, len(feedback)))
		return result
	}
	snapshot, err := h.store.InsertUserProfileSnapshotVersion(ctx, model.UserProfileSnapshot{
		UserID:       result.UserID,
		BaseVersion:  active.Version,
		RunID:        result.RunID,
		Summary:      "rebuilt from structured feedback",
		Snapshot:     rebuilt,
		Diff:         diff,
		ChangeReason: "rebuild",
	})
	if err != nil {
		result.Status = TaskStatusFailed
		result.Error = err.Error()
		steps.add("save_profile_version", StepStatusFailed, err.Error())
		h.finishTask(ctx, result.RunID, result.Status, result.Error, rebuildPartialResult(result, len(feedback)))
		return result
	}
	result.ProfileVersion = snapshot.Version
	steps.add("save_profile_version", StepStatusCompleted, fmt.Sprintf("version=%d", snapshot.Version))
	result.Status = TaskStatusCompleted
	h.finishTask(ctx, result.RunID, result.Status, "", rebuildPartialResult(result, len(feedback)))
	return result
}

// 函数作用：
// 遍历配置中的 RSS 源并抓取文章。
//
// 参数说明：
// - ctx：上下文。
// - steps：步骤记录器。
//
// 返回值：
// - 返回所有抓到的文章和各来源结果。
func (h *Harness) fetchArticles(ctx context.Context, runID string, steps *stepRecorder) ([]model.Article, []crawler.SourceResult) {
	// all 汇总所有源的文章。
	all := make([]model.Article, 0)
	results := make([]crawler.SourceResult, 0)
	for _, source := range h.cfg.Crawler.Sources {
		// 未启用的源跳过。
		if !source.Enabled {
			continue
		}
		startedAt := time.Now().UTC()
		_ = h.store.UpsertCrawlSourceRun(ctx, model.CrawlSourceRun{
			RunID: runID, SourceName: source.Name, SourceType: source.Type, Status: "running", StartedAt: startedAt,
		})
		result := h.crawler.FetchSource(ctx, crawler.Source{
			Name: source.Name, Type: crawler.SourceType(source.Type), URL: source.URL, Enabled: source.Enabled, MaxItems: source.MaxItems,
		})
		if result.Status == "" {
			result.Status = "success"
		}
		observability.RecordCrawlerArticle(ctx, result.Source.Name, string(result.Source.Type), result.Status, metricSourceItemCount(result))
		finishedAt := time.Now().UTC()
		_ = h.store.UpsertCrawlSourceRun(ctx, sourceRunModel(runID, result, startedAt, &finishedAt, 0))
		results = append(results, result)
		if result.Status == "failed" {
			steps.add("fetch:"+source.Name, "failed", result.ErrorMessage)
		} else {
			steps.add("fetch:"+source.Name, result.Status, fmt.Sprintf("%d articles", len(result.Articles)))
		}
		all = append(all, result.Articles...)
	}
	return all, results
}

func (h *Harness) updateSourceRunSavedCounts(ctx context.Context, runID string, results []crawler.SourceResult, savedBySource map[string]int, steps *stepRecorder) {
	for _, result := range results {
		finishedAt := time.Now().UTC()
		if err := h.store.UpsertCrawlSourceRun(ctx, sourceRunModel(runID, result, finishedAt, &finishedAt, savedBySource[result.Source.Name])); err != nil {
			steps.add("save_source_run:"+result.Source.Name, "failed", err.Error())
		}
	}
}

func sourceRunModel(runID string, result crawler.SourceResult, startedAt time.Time, finishedAt *time.Time, itemsSaved int) model.CrawlSourceRun {
	return model.CrawlSourceRun{
		RunID:        runID,
		SourceName:   result.Source.Name,
		SourceType:   string(result.Source.Type),
		Status:       result.Status,
		ErrorType:    result.ErrorType,
		ErrorMessage: result.ErrorMessage,
		HTTPStatus:   result.HTTPStatus,
		ItemsFound:   result.ItemsFound,
		ItemsSaved:   itemsSaved,
		ItemsPartial: result.ItemsPartial,
		ItemsFailed:  result.ItemsFailed,
		StartedAt:    startedAt,
		FinishedAt:   finishedAt,
	}
}

func metricTaskStatus(status string) string {
	switch status {
	case TaskStatusPending, TaskStatusRunning, TaskStatusCompleted, TaskStatusFailed, TaskStatusPartiallyCompleted, TaskStatusCancelled:
		return status
	default:
		return TaskStatusFailed
	}
}

func metricSourceItemCount(result crawler.SourceResult) int {
	if result.ItemsFound > len(result.Articles) {
		return result.ItemsFound
	}
	return len(result.Articles)
}

func allSourcesFailed(results []crawler.SourceResult) bool {
	if len(results) == 0 {
		return false
	}
	for _, result := range results {
		if result.Status != "failed" {
			return false
		}
	}
	return true
}

// 函数作用：
// 带重试调用 Python Agent ProcessArticles。
//
// 参数说明：
// - ctx：调用上下文。
// - runID：任务 id。
// - articles：待处理新文章。
// - profile：用户画像快照。
// - steps：步骤记录器。
//
// 返回值：
// - 返回 ProcessArticlesResponse 或 error。
func (h *Harness) callProcessArticles(ctx context.Context, runID string, articles []model.Article, profile map[string]string, steps *stepRecorder) (*agentpb.ProcessArticlesResponse, error) {
	if h.processArticlesFunc != nil {
		return h.processArticlesFunc(ctx, runID, articles, profile, steps)
	}
	// lastErr 保存最后一次失败原因。
	var lastErr error
	// 按配置重试 Python Agent 调用。
	maxAttempts := h.cfg.Harness.StepMaxRetries
	baseDelay := time.Duration(h.cfg.Harness.RetryBackoffMilliseconds) * time.Millisecond
	maxDelay := time.Duration(h.cfg.Harness.MaxRetryDelayMilliseconds) * time.Millisecond
	for attempt := 1; attempt <= maxAttempts; attempt++ {
		// 构造 protobuf 请求并调用 Python Agent。
		response, err := h.withArticlesClient(ctx, &agentpb.ProcessArticlesRequest{
			RunId:               runID,
			UserProfileSnapshot: profile,
			McpPolicy:           defaultMcpPolicy(),
			Articles:            toProtoArticles(articles),
		})
		if err == nil {
			steps.complete("grpc_process_articles", fmt.Sprintf("attempt %d", attempt), "", attempt-1)
			return response, nil
		}
		// 记录失败并等待下一次重试。
		lastErr = err
		if !isRetryableGRPCError(err) || attempt == maxAttempts {
			steps.complete("grpc_process_articles", "", fmt.Sprintf("attempt %d: %v", attempt, err), attempt-1)
			break
		}
		steps.finish("grpc_process_articles", StepStatusRetrying, "", fmt.Sprintf("attempt %d: %v", attempt, err), "", attempt)
		if err := waitForRetry(ctx, retryDelay(attempt, baseDelay, maxDelay)); err != nil {
			return nil, err
		}
	}
	// 所有重试失败后返回最后一次错误。
	return nil, lastErr
}

// 函数作用：
// 带重试调用 Python Agent ProcessFeedback。
//
// 参数说明：
// - ctx：调用上下文。
// - runID：任务 id。
// - userID：反馈用户 id。
// - req：HTTP 反馈请求。
// - profile：用户画像快照。
// - steps：步骤记录器。
//
// 返回值：
// - 返回 ProcessFeedbackResponse 或 error。
func (h *Harness) callProcessFeedback(ctx context.Context, runID string, userID string, req FeedbackRequest, profile map[string]string, steps *stepRecorder) (*agentpb.ProcessFeedbackResponse, error) {
	if h.processFeedbackFunc != nil {
		return h.processFeedbackFunc(ctx, runID, userID, req, profile, steps)
	}
	var lastErr error
	maxAttempts := h.cfg.Harness.StepMaxRetries
	baseDelay := time.Duration(h.cfg.Harness.RetryBackoffMilliseconds) * time.Millisecond
	maxDelay := time.Duration(h.cfg.Harness.MaxRetryDelayMilliseconds) * time.Millisecond
	for attempt := 1; attempt <= maxAttempts; attempt++ {
		// 构造 protobuf 请求，把 HTTP 反馈转换成 FeedbackItem。
		response, err := h.withFeedbackClient(ctx, &agentpb.ProcessFeedbackRequest{
			RunId:               runID,
			UserProfileSnapshot: profile,
			McpPolicy:           defaultMcpPolicy(),
			Feedback: []*agentpb.FeedbackItem{
				{
					FeedbackId:   runID + "-item",
					UserId:       userID,
					ArticleId:    req.ArticleID,
					PostId:       req.PostID,
					FeedbackText: req.FeedbackText,
					FeedbackType: req.FeedbackType,
					Rating:       int32(req.Rating),
					Metadata:     map[string]string{"source": "goframe-backend"},
				},
			},
		})
		if err == nil {
			steps.complete("grpc_process_feedback", fmt.Sprintf("attempt %d", attempt), "", attempt-1)
			return response, nil
		}
		// 记录本次失败并指数式增加一点等待时间。
		lastErr = err
		if !isRetryableGRPCError(err) || attempt == maxAttempts {
			steps.complete("grpc_process_feedback", "", fmt.Sprintf("attempt %d: %v", attempt, err), attempt-1)
			break
		}
		steps.finish("grpc_process_feedback", StepStatusRetrying, "", fmt.Sprintf("attempt %d: %v", attempt, err), "", attempt)
		if err := waitForRetry(ctx, retryDelay(attempt, baseDelay, maxDelay)); err != nil {
			return nil, err
		}
	}
	return nil, lastErr
}

func decodeJSONObject(raw string) map[string]any {
	out := map[string]any{}
	if strings.TrimSpace(raw) == "" {
		return out
	}
	if err := json.Unmarshal([]byte(raw), &out); err != nil {
		return map[string]any{"raw": raw}
	}
	return out
}

func rebuildProfileFromFeedback(base map[string]string, feedback []model.FeedbackRecord) (map[string]string, []model.ProfileDiffChange) {
	snapshot := copyStringMap(base)
	topics := jsonFloatMap(snapshot["topics"])
	negativeTopics := jsonFloatMap(snapshot["negative_topics"])
	stylePreferences := jsonStringMap(snapshot["style_preferences"])
	changes := make([]model.ProfileDiffChange, 0)
	for _, record := range feedback {
		structured := decodeJSONObject(record.StructuredFeedbackJSON)
		for _, item := range structuredItems(structured, "positive") {
			topic := strings.TrimSpace(structuredString(item, "topic"))
			if topic == "" {
				continue
			}
			old := topics[topic]
			signal := math.Min(clampWeight(math.Abs(structuredFloat(item, "weight_delta", 0.08))), 0.12)
			next := clampWeight(old*0.92 + signal)
			topics[topic] = next
			changes = append(changes, model.ProfileDiffChange{Path: "topics." + topic, Before: old, After: next, Reason: "positive_feedback"})
		}
		for _, item := range structuredItems(structured, "negative") {
			topic := strings.TrimSpace(structuredString(item, "topic"))
			if topic == "" {
				continue
			}
			oldNegative := negativeTopics[topic]
			signal := math.Min(clampWeight(math.Abs(structuredFloat(item, "weight_delta", 0.1))), 0.12)
			nextNegative := clampWeight(oldNegative*0.90 + signal)
			negativeTopics[topic] = nextNegative
			changes = append(changes, model.ProfileDiffChange{Path: "negative_topics." + topic, Before: oldNegative, After: nextNegative, Reason: "negative_feedback"})
			if oldTopic, ok := topics[topic]; ok {
				nextTopic := clampWeight(oldTopic * 0.90)
				topics[topic] = nextTopic
				changes = append(changes, model.ProfileDiffChange{Path: "topics." + topic, Before: oldTopic, After: nextTopic, Reason: "negative_feedback_decay"})
			}
		}
		for _, item := range structuredItems(structured, "style_preferences") {
			name := strings.TrimSpace(structuredString(item, "name"))
			value := strings.TrimSpace(structuredString(item, "value"))
			if name == "" || value == "" {
				continue
			}
			old := stylePreferences[name]
			stylePreferences[name] = value
			changes = append(changes, model.ProfileDiffChange{Path: "style_preferences." + name, Before: old, After: value, Reason: "style_preference"})
		}
	}
	snapshot["topics"] = marshalJSONMap(topics)
	snapshot["negative_topics"] = marshalJSONMap(negativeTopics)
	snapshot["style_preferences"] = marshalJSONMap(stylePreferences)
	return snapshot, changes
}

func copyStringMap(in map[string]string) map[string]string {
	out := make(map[string]string, len(in))
	for key, value := range in {
		out[key] = value
	}
	return out
}

func jsonFloatMap(raw string) map[string]float64 {
	values := map[string]any{}
	out := map[string]float64{}
	if strings.TrimSpace(raw) == "" {
		return out
	}
	if err := json.Unmarshal([]byte(raw), &values); err != nil {
		return out
	}
	for key, value := range values {
		out[key] = clampWeight(anyFloat(value, 0))
	}
	return out
}

func jsonStringMap(raw string) map[string]string {
	values := map[string]any{}
	out := map[string]string{}
	if strings.TrimSpace(raw) == "" {
		return out
	}
	if err := json.Unmarshal([]byte(raw), &values); err != nil {
		return out
	}
	for key, value := range values {
		out[key] = fmt.Sprint(value)
	}
	return out
}

func structuredItems(structured map[string]any, key string) []any {
	items, ok := structured[key].([]any)
	if !ok {
		return nil
	}
	return items
}

func structuredString(item any, key string) string {
	values, ok := item.(map[string]any)
	if !ok {
		return ""
	}
	if value, ok := values[key]; ok {
		return fmt.Sprint(value)
	}
	return ""
}

func structuredFloat(item any, key string, fallback float64) float64 {
	values, ok := item.(map[string]any)
	if !ok {
		return fallback
	}
	return anyFloat(values[key], fallback)
}

func anyFloat(value any, fallback float64) float64 {
	switch typed := value.(type) {
	case float64:
		return typed
	case float32:
		return float64(typed)
	case int:
		return float64(typed)
	case int32:
		return float64(typed)
	case int64:
		return float64(typed)
	case json.Number:
		out, err := typed.Float64()
		if err == nil {
			return out
		}
	case string:
		var out float64
		if _, err := fmt.Sscan(typed, &out); err == nil {
			return out
		}
	}
	return fallback
}

func clampWeight(value float64) float64 {
	if value < 0 {
		value = 0
	}
	if value > 1 {
		value = 1
	}
	return math.Round(value*10000) / 10000
}

func marshalJSONMap(value any) string {
	raw, err := json.Marshal(value)
	if err != nil {
		return "{}"
	}
	return string(raw)
}

func compensationTaskForLog(userID string, runID string, log model.McpCallLog) model.MemoryCompensationTask {
	target := compensationTargetSystem(log.ServerName)
	if target == "" {
		return model.MemoryCompensationTask{}
	}
	taskType := "retry_mcp_call"
	value := strings.Join([]string{runID, userID, target, log.AgentName, log.ToolName, log.RequestJSON}, "\x00")
	return model.MemoryCompensationTask{
		TaskID:       fmt.Sprintf("%x", sha256.Sum256([]byte(value))),
		RunID:        runID,
		UserID:       userID,
		TaskType:     taskType,
		TargetSystem: target,
		Payload: map[string]any{
			"agent_name":    log.AgentName,
			"server_name":   log.ServerName,
			"tool_name":     log.ToolName,
			"request_json":  log.RequestJSON,
			"response_json": log.ResponseJSON,
			"status":        log.Status,
		},
		Status:    "pending",
		LastError: log.ErrorMessage,
	}
}

func compensationTargetSystem(serverName string) string {
	name := strings.ToLower(serverName)
	switch {
	case strings.Contains(name, "milvus"):
		return "milvus"
	case strings.Contains(name, "neo4j"):
		return "neo4j"
	case strings.Contains(name, "mysql"):
		return "mysql"
	default:
		return ""
	}
}

func waitForRetry(ctx context.Context, delay time.Duration) error {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

func isRetryableGRPCError(err error) bool {
	if err == nil {
		return false
	}
	code := status.Code(err)
	return code == codes.Unknown ||
		code == codes.Unavailable ||
		code == codes.DeadlineExceeded ||
		code == codes.ResourceExhausted ||
		code == codes.Aborted
}

// 函数作用：
// 创建 gRPC Client 并调用 ProcessArticles。
//
// 参数说明：
// - ctx：上下文。
// - request：文章处理 protobuf 请求。
//
// 返回值：
// - 返回 ProcessArticlesResponse 或 error。
func (h *Harness) withArticlesClient(ctx context.Context, request *agentpb.ProcessArticlesRequest) (*agentpb.ProcessArticlesResponse, error) {
	// 读取配置中的超时时间。
	timeout := time.Duration(h.cfg.Agent.TimeoutSeconds) * time.Second
	// 建立到 Python Agent 的连接。
	client, err := grpcclient.New(ctx, h.cfg.Agent.Address, timeout)
	if err != nil {
		return nil, err
	}
	// 调用结束后关闭连接。
	defer client.Close()
	// 为单次 RPC 调用创建超时上下文。
	callCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	return client.ProcessArticles(callCtx, request)
}

// 函数作用：
// 创建 gRPC Client 并调用 ProcessFeedback。
//
// 参数说明：
// - ctx：上下文。
// - request：反馈处理 protobuf 请求。
//
// 返回值：
// - 返回 ProcessFeedbackResponse 或 error。
func (h *Harness) withFeedbackClient(ctx context.Context, request *agentpb.ProcessFeedbackRequest) (*agentpb.ProcessFeedbackResponse, error) {
	timeout := time.Duration(h.cfg.Agent.TimeoutSeconds) * time.Second
	client, err := grpcclient.New(ctx, h.cfg.Agent.Address, timeout)
	if err != nil {
		return nil, err
	}
	defer client.Close()
	callCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	return client.ProcessFeedback(callCtx, request)
}

// 函数作用：
// 读取最新用户画像快照，并补齐默认字段。
//
// 参数说明：
// - ctx：数据库调用上下文。
//
// 返回值：
// - 返回 map[string]string 画像快照。
//
// 数据流说明：
// - 从 user_profile_snapshot 表读取最新 snapshot_json。
// - 如果没有记录或读取失败，使用空 map。
// - 补齐 user_id 和 interests，作为 Python Agent 的 user_profile_snapshot。
func (h *Harness) loadProfile(ctx context.Context) map[string]string {
	snapshot := h.loadProfileSnapshot(ctx)
	return normalizeProfile(snapshot.Snapshot, h.cfg.Profile.UserID, h.cfg.Profile.Interests)
}

func (h *Harness) loadProfileSnapshot(ctx context.Context) model.UserProfileSnapshot {
	userID := h.cfg.Profile.UserID
	snapshot, err := h.store.ActiveUserProfileSnapshot(ctx, userID)
	if err != nil {
		return model.UserProfileSnapshot{
			UserID:   userID,
			Version:  0,
			Snapshot: map[string]string{},
		}
	}
	if snapshot.UserID == "" {
		snapshot.UserID = userID
	}
	if snapshot.Snapshot == nil {
		snapshot.Snapshot = map[string]string{}
	}
	return snapshot
}

func normalizeProfile(profile map[string]string, userID string, interests string) map[string]string {
	out := make(map[string]string, len(profile)+2)
	for key, value := range profile {
		out[key] = value
	}
	// 确保 user_id 存在，Python Neo4jClient 会读取该字段。
	if out["user_id"] == "" {
		out["user_id"] = userID
	}
	// 确保 interests 存在，Python FilterAgent 会用它匹配文章关键词。
	if out["interests"] == "" {
		out["interests"] = interests
	}
	return out
}

// 函数作用：
// 持久化 Python Agent 的文章处理结果。
//
// 参数说明：
// - ctx：数据库调用上下文。
// - runID：任务 id。
// - response：Python Agent ProcessArticles 响应。
// - articleByID：输入文章映射，用于补充标题和标签。
// - steps：步骤记录器。
//
// 返回值：
// - 返回保存成功的 posts 和收集到的 MCP 调用日志。
func (h *Harness) persistAgentResults(ctx context.Context, runID string, response *agentpb.ProcessArticlesResponse, articleByID map[string]model.Article, profileVersion int, steps *stepRecorder) ([]model.Post, []model.McpCallLog) {
	// posts 保存成功入库的生成结果。
	posts := make([]model.Post, 0)
	// mcpLogs 汇总所有文章的 MCP 调用日志。
	mcpLogs := make([]model.McpCallLog, 0)
	for _, item := range response.Results {
		// protobuf 日志先转换成 model.McpCallLog，后续批量写库。
		mcpLogs = append(mcpLogs, protoMcpLogs(runID, item.McpCallLogs)...)
		if item.Keep {
			observability.RecordRecommendation(ctx, "kept", 1)
		} else {
			observability.RecordRecommendation(ctx, "dropped", 1)
			observability.RecordPostGenerated(ctx, "skipped", 1)
		}
		// FilterAgent 不保留的文章不生成 posts。
		if !item.Keep {
			continue
		}
		// 根据 article_id 找回原文章标题和标签。
		article := articleByID[item.ArticleId]
		// 默认 ready；校验失败时标记 check_failed，但仍可保存供人工查看。
		status := "ready"
		if !item.CheckPass {
			status = "check_failed"
		}
		// 构造 Post 模型，Markdown 内容直接来自 Python RewriteAgent 的 post_text。
		post := model.Post{
			PostUID:    stablePostID(runID, item.ArticleId),
			ArticleUID: item.ArticleId,
			Title:      article.Title,
			Markdown:   item.PostText,
			Status:     status,
			Tags:       article.Tags,
			Metadata: map[string]any{
				"score":                  item.Score,
				"rank_position":          item.RankPosition,
				"score_breakdown":        item.ScoreBreakdown,
				"recommendation_reasons": item.RecommendationReasons,
				"rejection_reasons":      item.RejectionReasons,
				"profile_version":        profileVersion,
			},
		}
		// 标题缺失时使用 article_id 兜底。
		if post.Title == "" {
			post.Title = item.ArticleId
		}
		// 没有 Markdown 内容时跳过，避免写入空 post。
		if post.Markdown == "" {
			observability.RecordPostGenerated(ctx, "failed", 1)
			continue
		}
		// 写入 posts 表。
		if err := h.store.InsertPost(ctx, post); err != nil {
			observability.RecordPostGenerated(ctx, "failed", 1)
			steps.add("save_post:"+item.ArticleId, "failed", err.Error())
			continue
		}
		if item.CheckPass {
			observability.RecordPostGenerated(ctx, "success", 1)
		} else {
			observability.RecordPostGenerated(ctx, "failed", 1)
		}
		posts = append(posts, post)
	}
	steps.add("save_posts", "ok", fmt.Sprintf("%d posts", len(posts)))
	return posts, mcpLogs
}

// 函数作用：
// 将本次保存的 posts 输出为 Markdown 文件。
//
// 参数说明：
// - runID：任务 id。
// - posts：要写入文件的生成内容。
//
// 返回值：
// - 返回 Markdown 文件路径和 error。
func (h *Harness) writeMarkdown(runID string, posts []model.Post) (string, error) {
	// 输出目录来自配置。
	outputDir := h.cfg.Output.Dir
	// 相对路径转换为绝对路径，方便接口返回后直接定位文件。
	if !filepath.IsAbs(outputDir) {
		abs, err := filepath.Abs(outputDir)
		if err != nil {
			return "", err
		}
		outputDir = abs
	}
	// 创建输出目录，0o755 是 Go 的八进制权限写法。
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return "", err
	}
	// 文件名使用 runID，保证每次任务输出独立文件。
	path := filepath.Join(outputDir, runID+".md")
	// strings.Builder 适合多次追加字符串，减少中间字符串分配。
	var builder strings.Builder
	// 写入文件头信息。
	builder.WriteString("# Knowledge Post Run\n\n")
	builder.WriteString(fmt.Sprintf("- run_id: `%s`\n", runID))
	builder.WriteString(fmt.Sprintf("- generated_at: `%s`\n\n", time.Now().Format(time.RFC3339)))
	// 逐篇写入 post markdown。
	for _, post := range posts {
		// HTML 注释保存 post/article id，不影响 Markdown 展示但方便追踪。
		builder.WriteString(fmt.Sprintf("<!-- post_uid: %s article_uid: %s -->\n\n", post.PostUID, post.ArticleUID))
		builder.WriteString(post.Markdown)
		builder.WriteString("\n\n---\n\n")
	}
	// 写文件，0o644 表示用户可读写、其他用户可读。
	return path, os.WriteFile(path, []byte(builder.String()), 0o644)
}

// 函数作用：
// 写文章任务运行日志到 run_logs 表。
//
// 参数说明：
// - ctx：数据库上下文。
// - result：文章任务结果。
// - status：要写入的状态。
// - errorMessage：错误消息。
func (h *Harness) writeRunLog(ctx context.Context, result RunArticlesResult, status string, errorMessage string) {
	// 忽略写 run_logs 错误，避免日志失败覆盖主业务错误。
	_ = h.store.InsertRunLog(ctx, model.RunLog{
		RunID:        result.RunID,
		Status:       status,
		InputCount:   result.CandidateCount,
		OutputCount:  result.PostsSaved,
		ErrorMessage: errorMessage,
		Metadata: map[string]any{
			"sources_fetched": result.SourcesFetched,
			"new_articles":    result.NewArticles,
			"processed_count": result.ProcessedCount,
			"markdown_path":   result.MarkdownPath,
			"steps":           result.Steps,
		},
	})
}

// 函数作用：
// 写反馈任务运行日志到 run_logs 表。
//
// 参数说明：
// - ctx：数据库上下文。
// - result：反馈任务结果。
// - status：要写入的状态。
// - errorMessage：错误消息。
func (h *Harness) writeFeedbackRunLog(ctx context.Context, result FeedbackResult, status string, errorMessage string) {
	// feedback 任务的 InputCount 固定为 1，因为当前接口一次提交一条反馈请求。
	_ = h.store.InsertRunLog(ctx, model.RunLog{
		RunID:        result.RunID,
		Status:       status,
		InputCount:   1,
		OutputCount:  len(result.ExtractedFeedback),
		ErrorMessage: errorMessage,
		Metadata: map[string]any{
			"sentiment": result.Sentiment,
			"steps":     result.Steps,
		},
	})
}

// stepRecorder 是步骤记录器，持有 StepLog 切片指针。
type stepRecorder struct {
	// steps 指向 result.Steps。
	steps *[]StepLog
	ctx   context.Context
	runID string
	store articleStore
}

// 函数作用：
// 追加一个步骤日志。
//
// 参数说明：
// - name：步骤名称。
// - status：步骤状态。
// - message：步骤说明。
func (r *stepRecorder) add(name string, status string, message string) {
	if status == "ok" {
		status = StepStatusCompleted
	}
	if status == "retry" {
		status = StepStatusRetrying
	}
	if status == "failed" {
		r.finish(name, status, "", "", message, 0)
		return
	}
	if status == "skipped" {
		r.finish(name, StepStatusSkipped, "", message, "", 0)
		return
	}
	r.finish(name, status, "", message, "", 0)
}

func (r *stepRecorder) start(name string, inputSummary string) {
	now := time.Now().UTC()
	step := StepLog{
		Name:         name,
		Status:       StepStatusRunning,
		At:           now.Format(time.RFC3339),
		StartedAt:    now.Format(time.RFC3339),
		InputSummary: inputSummary,
	}
	r.upsertInMemory(step)
	r.persist(model.TaskStep{
		RunID:        r.runID,
		StepName:     name,
		Status:       StepStatusRunning,
		StartedAt:    &now,
		InputSummary: inputSummary,
	})
}

func (r *stepRecorder) complete(name string, outputSummary string, errorMessage string, retryCount int) {
	status := StepStatusCompleted
	if errorMessage != "" {
		status = StepStatusFailed
	}
	r.finish(name, status, "", outputSummary, errorMessage, retryCount)
}

func (r *stepRecorder) finish(name string, status string, inputSummary string, outputSummary string, errorMessage string, retryCount int) {
	now := time.Now().UTC()
	step := StepLog{
		Name:          name,
		Status:        status,
		Message:       firstNonEmpty(errorMessage, outputSummary, inputSummary),
		At:            now.Format(time.RFC3339),
		StartedAt:     now.Format(time.RFC3339),
		CompletedAt:   now.Format(time.RFC3339),
		InputSummary:  inputSummary,
		OutputSummary: outputSummary,
		ErrorMessage:  errorMessage,
		RetryCount:    retryCount,
	}
	r.upsertInMemory(step)
	r.persist(model.TaskStep{
		RunID:         r.runID,
		StepName:      name,
		Status:        status,
		StartedAt:     &now,
		CompletedAt:   &now,
		InputSummary:  inputSummary,
		OutputSummary: outputSummary,
		ErrorMessage:  errorMessage,
		RetryCount:    retryCount,
	})
}

func (r *stepRecorder) upsertInMemory(step StepLog) {
	if r.steps == nil {
		return
	}
	for index := range *r.steps {
		if (*r.steps)[index].Name == step.Name {
			existing := (*r.steps)[index]
			if step.StartedAt == "" {
				step.StartedAt = existing.StartedAt
			}
			if step.InputSummary == "" {
				step.InputSummary = existing.InputSummary
			}
			if step.Message == "" {
				step.Message = existing.Message
			}
			(*r.steps)[index] = step
			return
		}
	}
	*r.steps = append(*r.steps, step)
}

func (r *stepRecorder) persist(step model.TaskStep) {
	if r.store == nil || r.runID == "" {
		return
	}
	if step.RunID == "" {
		step.RunID = r.runID
	}
	if r.ctx == nil {
		r.ctx = context.Background()
	}
	_ = r.store.UpsertTaskStep(r.ctx, step)
}

func canTransitionTaskStatus(from string, to string) bool {
	if from == to {
		return true
	}
	switch from {
	case "", TaskStatusPending:
		return to == TaskStatusRunning || to == TaskStatusCancelled || to == TaskStatusFailed
	case TaskStatusRunning:
		return to == TaskStatusCompleted || to == TaskStatusFailed || to == TaskStatusPartiallyCompleted || to == TaskStatusCancelled
	case TaskStatusFailed, TaskStatusPartiallyCompleted:
		return to == TaskStatusPending || to == TaskStatusRunning || to == TaskStatusCancelled
	default:
		return false
	}
}

func retryDelay(attempt int, base time.Duration, maxDelay time.Duration) time.Duration {
	if attempt <= 1 {
		return base
	}
	delay := base
	for i := 1; i < attempt; i++ {
		delay *= 2
		if maxDelay > 0 && delay >= maxDelay {
			return maxDelay
		}
	}
	return delay
}

// 函数作用：
// 生成任务 run_id。
//
// 参数说明：
// - prefix：任务前缀，例如 articles 或 feedback。
//
// 返回值：
// - 返回 prefix-UTC时间戳-随机后缀 格式字符串。
func newRunID(prefix string) string {
	// 4 个随机字节会生成 8 个十六进制字符。
	buf := make([]byte, 4)
	// rand.Read 失败概率很低；这里忽略错误，失败时 buf 保持零值。
	_, _ = rand.Read(buf)
	return fmt.Sprintf("%s-%s-%s", prefix, time.Now().UTC().Format("20060102150405"), hex.EncodeToString(buf))
}

// 函数作用：
// 将内部 Article 模型转换为 protobuf Article 列表。
//
// 参数说明：
// - articles：内部文章模型列表。
//
// 返回值：
// - 返回 []*agentpb.Article，用于 ProcessArticlesRequest。
func toProtoArticles(articles []model.Article) []*agentpb.Article {
	// 预分配输出切片容量。
	out := make([]*agentpb.Article, 0, len(articles))
	for _, article := range articles {
		// 字段映射：model.Article.Content 对应 proto raw_text。
		out = append(out, &agentpb.Article{
			ArticleId:   article.ID,
			Url:         article.URL,
			Title:       article.Title,
			RawText:     article.Content,
			Source:      article.Source,
			PublishedAt: article.PublishedAt,
			Tags:        article.Tags,
		})
	}
	return out
}

// 函数作用：
// 构造默认 MCP 策略。
//
// 参数说明：
// - 无。
//
// 返回值：
// - 返回 *agentpb.McpPolicy。
//
// 说明：
// - MockTransport=false 表示请求侧不要求 mock；Python 是否 mock 仍由 settings.mock_mcp 决定。
// - 默认启用 embedding/milvus/neo4j，禁用 fetch，避免任务主动访问外部网页。
func defaultMcpPolicy() *agentpb.McpPolicy {
	return &agentpb.McpPolicy{
		MockTransport:   false,
		EnableEmbedding: true,
		EnableFetch:     false,
		EnableMilvus:    true,
		EnableNeo4J:     true,
	}
}

// 函数作用：
// 将文章列表转换为 article_id -> Article 的映射。
//
// 参数说明：
// - articles：文章列表。
//
// 返回值：
// - 返回 map[string]model.Article。
func mapArticles(articles []model.Article) map[string]model.Article {
	// make(map, len) 预分配容量。
	out := make(map[string]model.Article, len(articles))
	for _, article := range articles {
		out[article.ID] = article
	}
	return out
}

// 函数作用：
// 将 protobuf MCP 日志转换为数据库模型。
//
// 参数说明：
// - runID：当前任务 id，用于补齐日志中缺失的 run_id。
// - logs：Python Agent 返回的 protobuf McpCallLog 列表。
//
// 返回值：
// - 返回 []model.McpCallLog。
func protoMcpLogs(runID string, logs []*agentpb.McpCallLog) []model.McpCallLog {
	// 预分配输出容量。
	out := make([]model.McpCallLog, 0, len(logs))
	for _, log := range logs {
		// 优先使用 Python 返回的 run_id，缺失时用当前任务 runID 兜底。
		logRunID := log.RunId
		if logRunID == "" {
			logRunID = runID
		}
		// status 缺失时用 success 推导，兼容旧版日志。
		status := log.Status
		if status == "" {
			if log.Success {
				status = "success"
			} else {
				status = "failed"
			}
		}
		// 字段一一映射到数据库模型。
		out = append(out, model.McpCallLog{
			CallID:       log.CallId,
			RunID:        logRunID,
			AgentName:    log.AgentName,
			ServerName:   log.ServerName,
			ToolName:     log.ToolName,
			RequestJSON:  log.RequestJson,
			ResponseJSON: log.ResponseJson,
			Status:       status,
			ErrorMessage: log.ErrorMessage,
			Success:      log.Success,
			LatencyMS:    log.LatencyMs,
		})
	}
	return out
}

// 函数作用：
// 根据 runID 和 articleID 生成稳定 post_uid。
//
// 参数说明：
// - runID：任务 id。
// - articleID：文章 id。
//
// 返回值：
// - 返回用于 posts.post_uid 的字符串。
func stablePostID(runID string, articleID string) string {
	// 替换不适合放进 id 的字符。
	clean := strings.NewReplacer("/", "-", ":", "-", " ", "-").Replace(articleID)
	// 限制 articleID 部分长度，避免 post_uid 过长。
	if len(clean) > 80 {
		clean = clean[:80]
	}
	return "post-" + clean
}

// 函数作用：
// 返回第一个非空字符串。
//
// 参数说明：
// - values：候选字符串列表。
//
// 返回值：
// - 返回第一个非空值；都为空时返回空字符串。
func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}
