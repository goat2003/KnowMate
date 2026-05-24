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
	// encoding/hex 用于把随机字节转成字符串。
	"encoding/hex"
	// fmt 用于格式化步骤消息和 Markdown 文本。
	"fmt"
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
	// store 是 MySQL 数据访问层。
	"knowledge-post-agent/goframe-backend/internal/store"
)

// Harness 是 GoFrame 后端的业务编排器。
// 它让 HTTP handler 不需要知道 RSS、gRPC、MySQL 和 Markdown 的具体细节。
type Harness struct {
	// cfg 是归一化后的服务配置。
	cfg config.Config
	// store 用于所有 MySQL 读写。
	store *store.Store
	// crawler 用于抓取 RSS 或 mock 文章。
	crawler *crawler.RSSCrawler
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
	At string `json:"at"`
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
	// cfg.Normalize 确保 Harness 中读取的配置都有默认值。
	return &Harness{cfg: cfg.Normalize(), store: store, crawler: crawler.NewRSSCrawler()}
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
	// 初始化任务结果，状态先标记为 running。
	result := RunArticlesResult{RunID: newRunID("articles"), Status: "running"}
	// stepRecorder 用指针写 result.Steps，便于各 helper 统一追加步骤。
	steps := stepRecorder{steps: &result.Steps}
	steps.add("start", "ok", "created run")
	// 任务开始时写入 run_logs，方便长任务执行中也能被查询到。
	h.writeRunLog(ctx, result, "running", "")

	// 抓取 RSS/mock 文章。
	articles, sourceCount := h.fetchArticles(ctx, &steps)
	result.SourcesFetched = sourceCount
	result.CandidateCount = len(articles)
	// 按 article ID 去重，并限制单次任务处理数量。
	deduped := crawler.Deduplicate(articles, h.cfg.Crawler.RunMaxArticles)
	steps.add("dedupe", "ok", fmt.Sprintf("%d candidates -> %d unique", len(articles), len(deduped)))

	// newArticles 只保存本次新插入 articles 表的文章。
	newArticles := make([]model.Article, 0, len(deduped))
	for _, article := range deduped {
		// InsertArticle 使用 INSERT IGNORE，重复文章不会报错。
		inserted, err := h.store.InsertArticle(ctx, article)
		if err != nil {
			// 写库失败时结束任务并写 failed run_logs。
			result.Status = "failed"
			result.Error = err.Error()
			steps.add("save_articles", "failed", err.Error())
			h.writeRunLog(ctx, result, "failed", result.Error)
			return result
		}
		// 只有新文章才进入 Python Agent，避免重复生成 posts。
		if inserted {
			newArticles = append(newArticles, article)
		}
	}
	result.NewArticles = len(newArticles)
	steps.add("save_articles", "ok", fmt.Sprintf("%d new articles", len(newArticles)))
	h.writeRunLog(ctx, result, "running", "")

	// 没有新文章时跳过 Python Agent 调用，直接完成任务。
	if len(newArticles) == 0 {
		result.Status = "completed"
		steps.add("process_articles", "skipped", "no new articles")
		h.writeRunLog(ctx, result, "completed", "")
		return result
	}

	// 读取最新用户画像快照，并补齐默认 user_id/interests。
	profile := h.loadProfile(ctx)
	// 调用 Python Agent ProcessArticles。
	response, err := h.callProcessArticles(ctx, result.RunID, newArticles, profile, &steps)
	if err != nil {
		// gRPC 调用最终失败时，任务失败并记录 run_logs。
		result.Status = "failed"
		result.Error = err.Error()
		steps.add("process_articles", "failed", err.Error())
		h.writeRunLog(ctx, result, "failed", result.Error)
		return result
	}
	// Python 返回的结果数量。
	result.ProcessedCount = len(response.Results)
	// 建立 article_id -> Article 的 map，便于把 Agent 结果对应回标题和标签。
	articleByID := mapArticles(newArticles)
	// 保存 posts，并收集 Python Agent 返回的 MCP 调用日志。
	posts, mcpLogs := h.persistAgentResults(ctx, result.RunID, response, articleByID, &steps)
	result.PostsSaved = len(posts)
	// 将 MCP 调用日志批量写入 mcp_call_logs 表。
	if len(mcpLogs) > 0 {
		if err := h.store.InsertMcpCallLogs(ctx, mcpLogs); err != nil {
			steps.add("save_mcp_logs", "failed", err.Error())
		} else {
			steps.add("save_mcp_logs", "ok", fmt.Sprintf("%d logs", len(mcpLogs)))
		}
	}

	// 将本次生成的 posts 输出成 Markdown 文件。
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

	// 所有步骤完成，写 completed run_logs。
	result.Status = "completed"
	h.writeRunLog(ctx, result, "completed", "")
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
	// 初始化反馈任务结果。
	result := FeedbackResult{RunID: newRunID("feedback"), Status: "running"}
	steps := stepRecorder{steps: &result.Steps}
	// userID 优先使用请求值，缺失时用配置默认用户。
	userID := firstNonEmpty(req.UserID, h.cfg.Profile.UserID)
	// feedback_type 缺失时默认 text。
	if req.FeedbackType == "" {
		req.FeedbackType = "text"
	}
	steps.add("start", "ok", "created feedback run")
	h.writeFeedbackRunLog(ctx, result, "running", "")

	// 先写入 feedback_logs，保证原始用户反馈不会因为后续 Agent 失败而丢失。
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
		// 写反馈失败时结束任务。
		result.Status = "failed"
		result.Error = err.Error()
		steps.add("save_feedback", "failed", err.Error())
		h.writeFeedbackRunLog(ctx, result, "failed", result.Error)
		return result
	}
	steps.add("save_feedback", "ok", "feedback log saved")

	// 读取当前最新用户画像，作为 Python MemoryAgent 更新的基础。
	profile := h.loadProfile(ctx)
	// 调用 Python Agent ProcessFeedback。
	response, err := h.callProcessFeedback(ctx, result.RunID, userID, req, profile, &steps)
	if err != nil {
		result.Status = "failed"
		result.Error = err.Error()
		steps.add("process_feedback", "failed", err.Error())
		h.writeFeedbackRunLog(ctx, result, "failed", result.Error)
		return result
	}
	// 保存 Python FeedbackAgent 返回的结构化结果。
	result.Sentiment = response.Sentiment
	result.ExtractedFeedback = response.ExtractedFeedback
	result.UpdatedProfileSnapshot = response.UpdatedProfileSnapshot
	// 将更新后的用户画像快照写入 user_profile_snapshot 表。
	if err := h.store.InsertUserProfileSnapshot(ctx, userID, response.UpdatedProfileSnapshot, response.Sentiment); err != nil {
		result.Status = "failed"
		result.Error = err.Error()
		steps.add("save_profile", "failed", err.Error())
		h.writeFeedbackRunLog(ctx, result, "failed", result.Error)
		return result
	}
	steps.add("save_profile", "ok", "profile snapshot updated")

	// 转换并写入反馈流程产生的 MCP 调用日志。
	logs := protoMcpLogs(result.RunID, response.McpCallLogs)
	if err := h.store.InsertMcpCallLogs(ctx, logs); err != nil {
		steps.add("save_mcp_logs", "failed", err.Error())
	} else {
		steps.add("save_mcp_logs", "ok", fmt.Sprintf("%d logs", len(logs)))
	}

	// 标记任务完成。
	result.Status = "completed"
	h.writeFeedbackRunLog(ctx, result, "completed", "")
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
// - 返回所有抓到的文章和参与抓取的源数量。
func (h *Harness) fetchArticles(ctx context.Context, steps *stepRecorder) ([]model.Article, int) {
	// all 汇总所有源的文章。
	all := make([]model.Article, 0)
	// sourceCount 统计启用的源数量。
	sourceCount := 0
	for _, source := range h.cfg.RSS.Sources {
		// 未启用的源跳过。
		if !source.Enabled {
			continue
		}
		sourceCount++
		// RSSCrawler.Fetch 内部会区分 mock:// 和真实 RSS URL。
		articles, err := h.crawler.Fetch(ctx, source, h.cfg.Crawler.SourceMaxItems)
		if err != nil {
			// 单个源失败不终止整个任务，继续抓其他源。
			steps.add("fetch:"+source.Name, "failed", err.Error())
			continue
		}
		steps.add("fetch:"+source.Name, "ok", fmt.Sprintf("%d articles", len(articles)))
		all = append(all, articles...)
	}
	return all, sourceCount
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
	// lastErr 保存最后一次失败原因。
	var lastErr error
	// 按配置重试 Python Agent 调用。
	for attempt := 1; attempt <= h.cfg.Agent.RetryTimes; attempt++ {
		// 构造 protobuf 请求并调用 Python Agent。
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
		// 记录失败并等待下一次重试。
		lastErr = err
		steps.add("grpc_process_articles", "retry", fmt.Sprintf("attempt %d: %v", attempt, err))
		time.Sleep(time.Duration(attempt) * 200 * time.Millisecond)
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
	var lastErr error
	for attempt := 1; attempt <= h.cfg.Agent.RetryTimes; attempt++ {
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
			steps.add("grpc_process_feedback", "ok", fmt.Sprintf("attempt %d", attempt))
			return response, nil
		}
		// 记录本次失败并指数式增加一点等待时间。
		lastErr = err
		steps.add("grpc_process_feedback", "retry", fmt.Sprintf("attempt %d: %v", attempt, err))
		time.Sleep(time.Duration(attempt) * 200 * time.Millisecond)
	}
	return nil, lastErr
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
	// 从数据库读取最新用户画像快照。
	profile, err := h.store.LatestUserProfileSnapshot(ctx, h.cfg.Profile.UserID)
	// 读取失败不阻断主流程，使用默认画像继续。
	if err != nil || profile == nil {
		profile = map[string]string{}
	}
	// 确保 user_id 存在，Python Neo4jClient 会读取该字段。
	if profile["user_id"] == "" {
		profile["user_id"] = h.cfg.Profile.UserID
	}
	// 确保 interests 存在，Python FilterAgent 会用它匹配文章关键词。
	if profile["interests"] == "" {
		profile["interests"] = h.cfg.Profile.Interests
	}
	return profile
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
func (h *Harness) persistAgentResults(ctx context.Context, runID string, response *agentpb.ProcessArticlesResponse, articleByID map[string]model.Article, steps *stepRecorder) ([]model.Post, []model.McpCallLog) {
	// posts 保存成功入库的生成结果。
	posts := make([]model.Post, 0)
	// mcpLogs 汇总所有文章的 MCP 调用日志。
	mcpLogs := make([]model.McpCallLog, 0)
	for _, item := range response.Results {
		// protobuf 日志先转换成 model.McpCallLog，后续批量写库。
		mcpLogs = append(mcpLogs, protoMcpLogs(runID, item.McpCallLogs)...)
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
		}
		// 标题缺失时使用 article_id 兜底。
		if post.Title == "" {
			post.Title = item.ArticleId
		}
		// 没有 Markdown 内容时跳过，避免写入空 post。
		if post.Markdown == "" {
			continue
		}
		// 写入 posts 表。
		if err := h.store.InsertPost(ctx, post); err != nil {
			steps.add("save_post:"+item.ArticleId, "failed", err.Error())
			continue
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
}

// 函数作用：
// 追加一个步骤日志。
//
// 参数说明：
// - name：步骤名称。
// - status：步骤状态。
// - message：步骤说明。
func (r *stepRecorder) add(name string, status string, message string) {
	// *r.steps 解引用切片指针，然后 append 新 StepLog。
	*r.steps = append(*r.steps, StepLog{
		Name:    name,
		Status:  status,
		Message: message,
		At:      time.Now().Format(time.RFC3339),
	})
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
	return runID + "-" + clean
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
