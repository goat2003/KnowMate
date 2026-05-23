package harness

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"knowledge-post-agent/goframe-backend/internal/agentpb"
	"knowledge-post-agent/goframe-backend/internal/config"
	"knowledge-post-agent/goframe-backend/internal/crawler"
	"knowledge-post-agent/goframe-backend/internal/grpcclient"
	"knowledge-post-agent/goframe-backend/internal/model"
	"knowledge-post-agent/goframe-backend/internal/store"
)

type Harness struct {
	cfg     config.Config
	store   *store.Store
	crawler *crawler.RSSCrawler
}

type StepLog struct {
	Name    string `json:"name"`
	Status  string `json:"status"`
	Message string `json:"message,omitempty"`
	At      string `json:"at"`
}

type RunArticlesResult struct {
	RunID          string    `json:"run_id"`
	Status         string    `json:"status"`
	SourcesFetched int       `json:"sources_fetched"`
	CandidateCount int       `json:"candidate_count"`
	NewArticles    int       `json:"new_articles"`
	ProcessedCount int       `json:"processed_count"`
	PostsSaved     int       `json:"posts_saved"`
	MarkdownPath   string    `json:"markdown_path"`
	Steps          []StepLog `json:"steps"`
	Error          string    `json:"error,omitempty"`
}

type FeedbackRequest struct {
	PostID       string `json:"post_id"`
	ArticleID    string `json:"article_id"`
	UserID       string `json:"user_id"`
	FeedbackText string `json:"feedback_text"`
	FeedbackType string `json:"feedback_type"`
	Rating       int    `json:"rating"`
}

type FeedbackResult struct {
	RunID                  string            `json:"run_id"`
	Status                 string            `json:"status"`
	Sentiment              string            `json:"sentiment"`
	ExtractedFeedback      []string          `json:"extracted_feedback"`
	UpdatedProfileSnapshot map[string]string `json:"updated_profile_snapshot"`
	Error                  string            `json:"error,omitempty"`
	Steps                  []StepLog         `json:"steps"`
}

func New(cfg config.Config, store *store.Store) *Harness {
	return &Harness{cfg: cfg.Normalize(), store: store, crawler: crawler.NewRSSCrawler()}
}

func AgentHealth(ctx context.Context, cfg config.Config) (*agentpb.HealthCheckResponse, error) {
	timeout := time.Duration(cfg.Agent.TimeoutSeconds) * time.Second
	client, err := grpcclient.New(ctx, cfg.Agent.Address, timeout)
	if err != nil {
		return nil, err
	}
	defer client.Close()
	callCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	return client.HealthCheck(callCtx)
}

func (h *Harness) AgentHealth(ctx context.Context) (*agentpb.HealthCheckResponse, error) {
	return AgentHealth(ctx, h.cfg)
}

func (h *Harness) RunArticles(ctx context.Context) RunArticlesResult {
	result := RunArticlesResult{RunID: newRunID("articles"), Status: "running"}
	steps := stepRecorder{steps: &result.Steps}
	steps.add("start", "ok", "created run")
	h.writeRunLog(ctx, result, "running", "")

	articles, sourceCount := h.fetchArticles(ctx, &steps)
	result.SourcesFetched = sourceCount
	result.CandidateCount = len(articles)
	deduped := crawler.Deduplicate(articles, h.cfg.Crawler.RunMaxArticles)
	steps.add("dedupe", "ok", fmt.Sprintf("%d candidates -> %d unique", len(articles), len(deduped)))

	newArticles := make([]model.Article, 0, len(deduped))
	for _, article := range deduped {
		inserted, err := h.store.InsertArticle(ctx, article)
		if err != nil {
			result.Status = "failed"
			result.Error = err.Error()
			steps.add("save_articles", "failed", err.Error())
			h.writeRunLog(ctx, result, "failed", result.Error)
			return result
		}
		if inserted {
			newArticles = append(newArticles, article)
		}
	}
	result.NewArticles = len(newArticles)
	steps.add("save_articles", "ok", fmt.Sprintf("%d new articles", len(newArticles)))
	h.writeRunLog(ctx, result, "running", "")

	if len(newArticles) == 0 {
		result.Status = "completed"
		steps.add("process_articles", "skipped", "no new articles")
		h.writeRunLog(ctx, result, "completed", "")
		return result
	}

	profile := h.loadProfile(ctx)
	response, err := h.callProcessArticles(ctx, result.RunID, newArticles, profile, &steps)
	if err != nil {
		result.Status = "failed"
		result.Error = err.Error()
		steps.add("process_articles", "failed", err.Error())
		h.writeRunLog(ctx, result, "failed", result.Error)
		return result
	}
	result.ProcessedCount = len(response.Results)
	articleByID := mapArticles(newArticles)
	posts, mcpLogs := h.persistAgentResults(ctx, result.RunID, response, articleByID, &steps)
	result.PostsSaved = len(posts)
	if len(mcpLogs) > 0 {
		if err := h.store.InsertMcpCallLogs(ctx, mcpLogs); err != nil {
			steps.add("save_mcp_logs", "failed", err.Error())
		} else {
			steps.add("save_mcp_logs", "ok", fmt.Sprintf("%d logs", len(mcpLogs)))
		}
	}

	markdownPath, err := h.writeMarkdown(result.RunID, posts)
	if err != nil {
		result.Status = "failed"
		result.Error = err.Error()
		steps.add("write_markdown", "failed", err.Error())
		h.writeRunLog(ctx, result, "failed", result.Error)
		return result
	}
	result.MarkdownPath = markdownPath
	steps.add("write_markdown", "ok", markdownPath)

	result.Status = "completed"
	h.writeRunLog(ctx, result, "completed", "")
	return result
}

func (h *Harness) ProcessFeedback(ctx context.Context, req FeedbackRequest) FeedbackResult {
	result := FeedbackResult{RunID: newRunID("feedback"), Status: "running"}
	steps := stepRecorder{steps: &result.Steps}
	userID := firstNonEmpty(req.UserID, h.cfg.Profile.UserID)
	if req.FeedbackType == "" {
		req.FeedbackType = "text"
	}
	steps.add("start", "ok", "created feedback run")
	h.writeFeedbackRunLog(ctx, result, "running", "")

	if err := h.store.InsertFeedbackLog(ctx, model.FeedbackLog{
		RunID:        result.RunID,
		PostUID:      req.PostID,
		ArticleUID:   req.ArticleID,
		UserID:       userID,
		FeedbackType: req.FeedbackType,
		Rating:       req.Rating,
		Comment:      req.FeedbackText,
		Metadata:     map[string]any{"source": "api"},
	}); err != nil {
		result.Status = "failed"
		result.Error = err.Error()
		steps.add("save_feedback", "failed", err.Error())
		h.writeFeedbackRunLog(ctx, result, "failed", result.Error)
		return result
	}
	steps.add("save_feedback", "ok", "feedback log saved")

	profile := h.loadProfile(ctx)
	response, err := h.callProcessFeedback(ctx, result.RunID, userID, req, profile, &steps)
	if err != nil {
		result.Status = "failed"
		result.Error = err.Error()
		steps.add("process_feedback", "failed", err.Error())
		h.writeFeedbackRunLog(ctx, result, "failed", result.Error)
		return result
	}
	result.Sentiment = response.Sentiment
	result.ExtractedFeedback = response.ExtractedFeedback
	result.UpdatedProfileSnapshot = response.UpdatedProfileSnapshot
	if err := h.store.InsertUserProfileSnapshot(ctx, userID, response.UpdatedProfileSnapshot, response.Sentiment); err != nil {
		result.Status = "failed"
		result.Error = err.Error()
		steps.add("save_profile", "failed", err.Error())
		h.writeFeedbackRunLog(ctx, result, "failed", result.Error)
		return result
	}
	steps.add("save_profile", "ok", "profile snapshot updated")

	logs := protoMcpLogs(result.RunID, response.McpCallLogs)
	if err := h.store.InsertMcpCallLogs(ctx, logs); err != nil {
		steps.add("save_mcp_logs", "failed", err.Error())
	} else {
		steps.add("save_mcp_logs", "ok", fmt.Sprintf("%d logs", len(logs)))
	}

	result.Status = "completed"
	h.writeFeedbackRunLog(ctx, result, "completed", "")
	return result
}

func (h *Harness) fetchArticles(ctx context.Context, steps *stepRecorder) ([]model.Article, int) {
	all := make([]model.Article, 0)
	sourceCount := 0
	for _, source := range h.cfg.RSS.Sources {
		if !source.Enabled {
			continue
		}
		sourceCount++
		articles, err := h.crawler.Fetch(ctx, source, h.cfg.Crawler.SourceMaxItems)
		if err != nil {
			steps.add("fetch:"+source.Name, "failed", err.Error())
			continue
		}
		steps.add("fetch:"+source.Name, "ok", fmt.Sprintf("%d articles", len(articles)))
		all = append(all, articles...)
	}
	return all, sourceCount
}

func (h *Harness) callProcessArticles(ctx context.Context, runID string, articles []model.Article, profile map[string]string, steps *stepRecorder) (*agentpb.ProcessArticlesResponse, error) {
	var lastErr error
	for attempt := 1; attempt <= h.cfg.Agent.RetryTimes; attempt++ {
		response, err := h.withArticlesClient(ctx, &agentpb.ProcessArticlesRequest{
			RunId:               runID,
			UserProfileSnapshot: profile,
			McpPolicy:           defaultMcpPolicy(),
			Articles:            toProtoArticles(articles),
		})
		if err == nil {
			steps.add("grpc_process_articles", "ok", fmt.Sprintf("attempt %d", attempt))
			return response, nil
		}
		lastErr = err
		steps.add("grpc_process_articles", "retry", fmt.Sprintf("attempt %d: %v", attempt, err))
		time.Sleep(time.Duration(attempt) * 200 * time.Millisecond)
	}
	return nil, lastErr
}

func (h *Harness) callProcessFeedback(ctx context.Context, runID string, userID string, req FeedbackRequest, profile map[string]string, steps *stepRecorder) (*agentpb.ProcessFeedbackResponse, error) {
	var lastErr error
	for attempt := 1; attempt <= h.cfg.Agent.RetryTimes; attempt++ {
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
			steps.add("grpc_process_feedback", "ok", fmt.Sprintf("attempt %d", attempt))
			return response, nil
		}
		lastErr = err
		steps.add("grpc_process_feedback", "retry", fmt.Sprintf("attempt %d: %v", attempt, err))
		time.Sleep(time.Duration(attempt) * 200 * time.Millisecond)
	}
	return nil, lastErr
}

func (h *Harness) withArticlesClient(ctx context.Context, request *agentpb.ProcessArticlesRequest) (*agentpb.ProcessArticlesResponse, error) {
	timeout := time.Duration(h.cfg.Agent.TimeoutSeconds) * time.Second
	client, err := grpcclient.New(ctx, h.cfg.Agent.Address, timeout)
	if err != nil {
		return nil, err
	}
	defer client.Close()
	callCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	return client.ProcessArticles(callCtx, request)
}

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

func (h *Harness) loadProfile(ctx context.Context) map[string]string {
	profile, err := h.store.LatestUserProfileSnapshot(ctx, h.cfg.Profile.UserID)
	if err != nil || profile == nil {
		profile = map[string]string{}
	}
	if profile["user_id"] == "" {
		profile["user_id"] = h.cfg.Profile.UserID
	}
	if profile["interests"] == "" {
		profile["interests"] = h.cfg.Profile.Interests
	}
	return profile
}

func (h *Harness) persistAgentResults(ctx context.Context, runID string, response *agentpb.ProcessArticlesResponse, articleByID map[string]model.Article, steps *stepRecorder) ([]model.Post, []model.McpCallLog) {
	posts := make([]model.Post, 0)
	mcpLogs := make([]model.McpCallLog, 0)
	for _, item := range response.Results {
		mcpLogs = append(mcpLogs, protoMcpLogs(runID, item.McpCallLogs)...)
		if !item.Keep {
			continue
		}
		article := articleByID[item.ArticleId]
		status := "ready"
		if !item.CheckPass {
			status = "check_failed"
		}
		post := model.Post{
			PostUID:    stablePostID(runID, item.ArticleId),
			ArticleUID: item.ArticleId,
			Title:      article.Title,
			Markdown:   item.PostText,
			Status:     status,
			Tags:       article.Tags,
		}
		if post.Title == "" {
			post.Title = item.ArticleId
		}
		if post.Markdown == "" {
			continue
		}
		if err := h.store.InsertPost(ctx, post); err != nil {
			steps.add("save_post:"+item.ArticleId, "failed", err.Error())
			continue
		}
		posts = append(posts, post)
	}
	steps.add("save_posts", "ok", fmt.Sprintf("%d posts", len(posts)))
	return posts, mcpLogs
}

func (h *Harness) writeMarkdown(runID string, posts []model.Post) (string, error) {
	outputDir := h.cfg.Output.Dir
	if !filepath.IsAbs(outputDir) {
		abs, err := filepath.Abs(outputDir)
		if err != nil {
			return "", err
		}
		outputDir = abs
	}
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return "", err
	}
	path := filepath.Join(outputDir, runID+".md")
	var builder strings.Builder
	builder.WriteString("# Knowledge Post Run\n\n")
	builder.WriteString(fmt.Sprintf("- run_id: `%s`\n", runID))
	builder.WriteString(fmt.Sprintf("- generated_at: `%s`\n\n", time.Now().Format(time.RFC3339)))
	for _, post := range posts {
		builder.WriteString(fmt.Sprintf("<!-- post_uid: %s article_uid: %s -->\n\n", post.PostUID, post.ArticleUID))
		builder.WriteString(post.Markdown)
		builder.WriteString("\n\n---\n\n")
	}
	return path, os.WriteFile(path, []byte(builder.String()), 0o644)
}

func (h *Harness) writeRunLog(ctx context.Context, result RunArticlesResult, status string, errorMessage string) {
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

func (h *Harness) writeFeedbackRunLog(ctx context.Context, result FeedbackResult, status string, errorMessage string) {
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

type stepRecorder struct {
	steps *[]StepLog
}

func (r *stepRecorder) add(name string, status string, message string) {
	*r.steps = append(*r.steps, StepLog{
		Name:    name,
		Status:  status,
		Message: message,
		At:      time.Now().Format(time.RFC3339),
	})
}

func newRunID(prefix string) string {
	buf := make([]byte, 4)
	_, _ = rand.Read(buf)
	return fmt.Sprintf("%s-%s-%s", prefix, time.Now().UTC().Format("20060102150405"), hex.EncodeToString(buf))
}

func toProtoArticles(articles []model.Article) []*agentpb.Article {
	out := make([]*agentpb.Article, 0, len(articles))
	for _, article := range articles {
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

func defaultMcpPolicy() *agentpb.McpPolicy {
	return &agentpb.McpPolicy{
		MockTransport:   false,
		EnableEmbedding: true,
		EnableFetch:     false,
		EnableMilvus:    true,
		EnableNeo4J:     true,
	}
}

func mapArticles(articles []model.Article) map[string]model.Article {
	out := make(map[string]model.Article, len(articles))
	for _, article := range articles {
		out[article.ID] = article
	}
	return out
}

func protoMcpLogs(runID string, logs []*agentpb.McpCallLog) []model.McpCallLog {
	out := make([]model.McpCallLog, 0, len(logs))
	for _, log := range logs {
		logRunID := log.RunId
		if logRunID == "" {
			logRunID = runID
		}
		status := log.Status
		if status == "" {
			if log.Success {
				status = "success"
			} else {
				status = "failed"
			}
		}
		out = append(out, model.McpCallLog{
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

func stablePostID(runID string, articleID string) string {
	clean := strings.NewReplacer("/", "-", ":", "-", " ", "-").Replace(articleID)
	if len(clean) > 80 {
		clean = clean[:80]
	}
	return runID + "-" + clean
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}
