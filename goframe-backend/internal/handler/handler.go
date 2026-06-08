// 文件作用：
// 本文件实现 GoFrame 后端的 HTTP handler。
// 它负责把 HTTP 请求转换成业务调用，并把 Store/Harness 的结果以 JSON 返回给调用方。
//
// 在项目中的位置：
// 本文件相当于 GoFrame 后端的 controller/handler 层，位于 HTTP 路由和 logic/harness 之间。
//
// 主要内容：
// 1. Handler 结构体：保存数据库 Store 和业务 Harness。
// 2. Register：注册 HTTP 路由。
// 3. Health：检查 MySQL 和 Python Agent Service。
// 4. RunArticles：触发文章抓取、Agent 处理、入库和 Markdown 输出。
// 5. Feedback：接收用户反馈并触发用户画像更新。
// 6. ListPosts / ListRunLogs：查询生成内容和运行日志。
//
// 关键调用关系：
// - 被 main.go 创建并注册到 g.Server。
// - 调用 harness.RunArticles / harness.ProcessFeedback。
// - 调用 store.ListPosts / store.ListRunLogs / store.Ping。
//
// 初学者阅读建议：
// 先看 Register 了解有哪些 HTTP 接口，再看每个 handler 如何把请求交给 harness 或 store。
package handler

import (
	"context"
	// encoding/json 用于解析 POST /feedback 的 JSON 请求体。
	"encoding/json"
	// strconv 用于把 query 参数 limit 转成 int。
	"strconv"

	"knowledge-post-agent/goframe-backend/internal/agentpb"
	// harness 是业务编排层，负责调用 RSS、MySQL、Python gRPC 和 Markdown 输出。
	"knowledge-post-agent/goframe-backend/internal/logic/harness"
	"knowledge-post-agent/goframe-backend/internal/model"
	"knowledge-post-agent/goframe-backend/internal/observability"
	// store 是 MySQL 数据访问层。
	"knowledge-post-agent/goframe-backend/internal/store"

	// g.Map 是 GoFrame 提供的 map[string]any 便捷类型，常用于 JSON 响应。
	"github.com/gogf/gf/v2/frame/g"
	// ghttp 是 GoFrame HTTP Server 和 Request 类型所在包。
	"github.com/gogf/gf/v2/net/ghttp"
)

// Handler 是 HTTP 层对象。
// 它不直接写 SQL 或调用 gRPC，而是把请求委托给 store 和 harness。
type Handler struct {
	// store 用于健康检查、查询 posts 和 run_logs。
	store handlerStore
	// harness 用于执行完整文章任务和反馈任务。
	harness handlerRunner
}

type handlerStore interface {
	Ping(context.Context) error
	ListPosts(context.Context, int) ([]model.Post, error)
	ListRunLogs(context.Context, int) ([]model.RunLog, error)
	ListTaskRuns(context.Context, model.TaskRunFilter) ([]model.TaskRun, error)
	TaskRun(context.Context, string) (model.TaskRun, error)
	ListTaskSteps(context.Context, string) ([]model.TaskStep, error)
	ActiveUserProfileSnapshot(context.Context, string) (model.UserProfileSnapshot, error)
	ListUserProfileSnapshots(context.Context, string, int) ([]model.UserProfileSnapshot, error)
	RollbackUserProfileSnapshot(context.Context, string, int, string) (model.UserProfileSnapshot, error)
	RecommendationExplanationByPostID(context.Context, string) (model.RecommendationExplanation, error)
}

type handlerRunner interface {
	AgentHealth(context.Context) (*agentpb.HealthCheckResponse, error)
	RunArticles(context.Context) harness.RunArticlesResult
	ProcessFeedback(context.Context, harness.FeedbackRequest) harness.FeedbackResult
	RebuildProfile(context.Context, harness.RebuildProfileRequest) harness.RebuildProfileResult
	ListTaskRuns(context.Context, model.TaskRunFilter) ([]model.TaskRun, error)
	GetTaskRun(context.Context, string) (model.TaskRun, error)
	CancelTask(context.Context, string) (model.TaskRun, error)
	RetryTaskRun(context.Context, string) harness.RetryTaskResult
}

// 函数作用：
// 创建 Handler 实例并注入依赖。
//
// 参数说明：
// - store：MySQL 数据访问对象。
// - runner：业务编排对象。
//
// 返回值：
// - 返回 *Handler。
func New(store *store.Store, runner *harness.Harness) *Handler {
	// 使用结构体字面量保存依赖，后续方法通过接收者 h 访问。
	return &Handler{store: store, harness: runner}
}

func NewWithDependencies(store handlerStore, runner handlerRunner) *Handler {
	return &Handler{store: store, harness: runner}
}

// 函数作用：
// 注册 GoFrame HTTP 路由。
//
// 参数说明：
// - server：GoFrame HTTP Server。
//
// 返回值：
// - 无。
//
// 调用关系：
// - 被 main.go 调用。
func (h *Handler) Register(server *ghttp.Server) {
	server.Use(observability.GoFrameTraceMiddleware("goframe-backend"))
	// Group("/") 表示以下路由都挂在根路径下。
	server.Group("/", func(group *ghttp.RouterGroup) {
		// GET /health 同时检查数据库和 Python Agent。
		group.GET("/health", h.Health)
		group.GET("/metrics", h.Metrics)
		// POST /runs/articles 触发一次完整文章处理任务。
		group.POST("/runs/articles", h.RunArticles)
		// POST /feedback 接收用户反馈并触发画像更新。
		group.POST("/feedback", h.Feedback)
		// GET /posts 查询最近生成的推文/知识笔记。
		group.GET("/posts", h.ListPosts)

		// GET /run-logs 查询最近任务运行日志。
		group.GET("/run-logs", h.ListRunLogs)
		group.GET("/runs", h.ListRuns)
		group.GET("/runs/{run_id}", h.GetRun)
		group.POST("/runs/{run_id}/cancel", h.CancelRun)
		group.POST("/runs/{run_id}/retry", h.RetryRun)
		group.GET("/profile", h.GetProfile)
		group.GET("/profile/history", h.ListProfileHistory)
		group.POST("/profile/rollback", h.RollbackProfile)
		group.GET("/recommendations/explain", h.GetRecommendationExplanation)
		group.POST("/profile/rebuild", h.RebuildProfile)
	})
}

// 函数作用：
// 健康检查接口，返回数据库和 Python Agent 的可用状态。
//
// 参数说明：
// - r：GoFrame HTTP 请求对象，包含上下文、请求参数和响应对象。
//
// 返回值：
// - 通过 r.Response.WriteJson 写出 JSON 响应。
func (h *Handler) Metrics(r *ghttp.Request) {
	observability.MetricsHandler().ServeHTTP(r.Response.RawWriter(), r.Request)
}

func (h *Handler) Health(r *ghttp.Request) {
	// 默认认为数据库可用。
	db := g.Map{"status": "ok"}
	// Ping 使用请求上下文检查 MySQL 连接。
	if err := h.store.Ping(r.Context()); err != nil {
		// 数据库不可用时，保留错误信息给调用方。
		db = g.Map{"status": "unavailable", "error": err.Error()}
	}

	// 默认认为 Agent 可用，随后通过 gRPC healthcheck 覆盖实际状态。
	agent := g.Map{"status": "ok"}
	// 调用 Python Agent HealthCheck。
	if response, err := h.harness.AgentHealth(r.Context()); err != nil {
		agent = g.Map{"status": "unavailable", "error": err.Error()}
	} else {
		// 将 protobuf 响应转换为 JSON 友好的 map。
		agent = g.Map{
			"status":         response.Status,
			"version":        response.Version,
			"enabled_agents": response.EnabledAgents,
			"mock_mode":      response.MockMode,
		}
	}

	// 总体 HTTP 层可正常响应时 status 固定为 ok，具体依赖状态在 db/agent 中展示。
	r.Response.WriteJson(g.Map{
		"status": "ok",
		"db":     db,
		"agent":  agent,
	})
}

// 函数作用：
// 触发一次文章抓取和 Agent 处理任务。
//
// 参数说明：
// - r：GoFrame HTTP 请求对象。
//
// 返回值：
// - JSON 响应包含 ok 和 result，result 是 harness.RunArticlesResult。
//
// 调用关系：
// - HTTP POST /runs/articles 调用。
// - 内部调用 h.harness.RunArticles。
func (h *Handler) RunArticles(r *ghttp.Request) {
	// RunArticles 内部会抓 RSS、写 articles、调用 Python gRPC、写 posts/run_logs/mcp_call_logs、生成 Markdown。
	result := h.harness.RunArticles(r.Context())
	// ok 根据业务状态是否 completed 计算。
	r.Response.WriteJson(g.Map{
		"ok":     result.Status == "completed",
		"result": result,
	})
}

// 函数作用：
// 接收用户反馈并触发反馈处理流程。
//
// 参数说明：
// - r：GoFrame HTTP 请求对象，请求体应是 JSON。
//
// 返回值：
// - JSON 响应包含 ok 和 result。
func (h *Handler) Feedback(r *ghttp.Request) {
	// req 对应 harness.FeedbackRequest，decodeJSON 会把请求体填充到该结构体。
	var req harness.FeedbackRequest
	// JSON 解析失败时 decodeJSON 已经写响应，因此这里直接 return。
	if !decodeJSON(r, &req) {
		return
	}
	// post_id 和 feedback_text 是反馈处理的最小必需字段。
	if req.PostID == "" || req.FeedbackText == "" {
		r.Response.WriteJson(g.Map{"ok": false, "error": "post_id and feedback_text are required"})
		return
	}
	// ProcessFeedback 会写 feedback_logs、调用 Python Agent、更新 user_profile_snapshot，并保存 MCP 日志。
	result := h.harness.ProcessFeedback(r.Context(), req)
	r.Response.WriteJson(g.Map{
		"ok":     result.Status == "completed",
		"result": result,
	})
}

// 函数作用：
// 查询最近生成的 posts。
//
// 参数说明：
// - r：GoFrame HTTP 请求对象，可通过 ?limit= 控制返回数量。
//
// 返回值：
// - JSON 响应包含 ok 和 items。
func (h *Handler) ListPosts(r *ghttp.Request) {
	// queryLimit 解析并限制 limit，避免一次返回过多数据。
	posts, err := h.store.ListPosts(r.Context(), queryLimit(r))
	if err != nil {
		r.Response.WriteJson(g.Map{"ok": false, "error": err.Error()})
		return
	}
	// 查询成功时返回 posts 列表。
	r.Response.WriteJson(g.Map{"ok": true, "items": posts})
}

// 函数作用：
// 查询最近运行日志。
//
// 参数说明：
// - r：GoFrame HTTP 请求对象，可通过 ?limit= 控制返回数量。
//
// 返回值：
// - JSON 响应包含 ok 和 items。
func (h *Handler) ListRunLogs(r *ghttp.Request) {
	// run_logs 由 harness 在任务开始、失败和完成时写入。
	logs, err := h.store.ListRunLogs(r.Context(), queryLimit(r))
	if err != nil {
		r.Response.WriteJson(g.Map{"ok": false, "error": err.Error()})
		return
	}
	r.Response.WriteJson(g.Map{"ok": true, "items": logs})
}

func (h *Handler) ListRuns(r *ghttp.Request) {
	filter := model.TaskRunFilter{
		TaskType: r.GetQuery("task_type").String(),
		UserID:   r.GetQuery("user_id").String(),
		Status:   r.GetQuery("status").String(),
		Limit:    queryLimit(r),
	}
	items, err := h.harness.ListTaskRuns(r.Context(), filter)
	if err != nil {
		r.Response.WriteJson(g.Map{"ok": false, "error": err.Error()})
		return
	}
	r.Response.WriteJson(g.Map{"ok": true, "items": items})
}

func (h *Handler) GetRun(r *ghttp.Request) {
	runID := r.Get("run_id").String()
	if runID == "" {
		r.Response.WriteJson(g.Map{"ok": false, "error": "run_id is required"})
		return
	}
	task, err := h.harness.GetTaskRun(r.Context(), runID)
	if err != nil {
		r.Response.WriteJson(g.Map{"ok": false, "error": err.Error()})
		return
	}
	r.Response.WriteJson(g.Map{"ok": true, "run": task})
}

func (h *Handler) CancelRun(r *ghttp.Request) {
	runID := r.Get("run_id").String()
	if runID == "" {
		r.Response.WriteJson(g.Map{"ok": false, "error": "run_id is required"})
		return
	}
	task, err := h.harness.CancelTask(r.Context(), runID)
	if err != nil {
		r.Response.WriteJson(g.Map{"ok": false, "error": err.Error()})
		return
	}
	r.Response.WriteJson(g.Map{"ok": task.Status == harness.TaskStatusCancelled, "run": task})
}

func (h *Handler) RetryRun(r *ghttp.Request) {
	runID := r.Get("run_id").String()
	if runID == "" {
		r.Response.WriteJson(g.Map{"ok": false, "error": "run_id is required"})
		return
	}
	result := h.harness.RetryTaskRun(r.Context(), runID)
	r.Response.WriteJson(g.Map{
		"ok":     result.Status == harness.TaskStatusCompleted || result.Status == harness.TaskStatusPartiallyCompleted,
		"result": result,
	})
}

type RollbackProfileRequest struct {
	UserID        string `json:"user_id"`
	TargetVersion int    `json:"target_version"`
	Reason        string `json:"reason"`
}

func (h *Handler) GetProfile(r *ghttp.Request) {
	userID := r.GetQuery("user_id").String()
	profile, err := h.store.ActiveUserProfileSnapshot(r.Context(), userID)
	if err != nil {
		r.Response.WriteJson(g.Map{"ok": false, "error": err.Error()})
		return
	}
	r.Response.WriteJson(g.Map{"ok": true, "profile": profile})
}

func (h *Handler) ListProfileHistory(r *ghttp.Request) {
	userID := r.GetQuery("user_id").String()
	items, err := h.store.ListUserProfileSnapshots(r.Context(), userID, queryLimit(r))
	if err != nil {
		r.Response.WriteJson(g.Map{"ok": false, "error": err.Error()})
		return
	}
	r.Response.WriteJson(g.Map{"ok": true, "items": items})
}

func (h *Handler) RollbackProfile(r *ghttp.Request) {
	var req RollbackProfileRequest
	if !decodeJSON(r, &req) {
		return
	}
	if req.TargetVersion <= 0 {
		r.Response.WriteJson(g.Map{"ok": false, "error": "target_version is required"})
		return
	}
	profile, err := h.store.RollbackUserProfileSnapshot(r.Context(), req.UserID, req.TargetVersion, req.Reason)
	if err != nil {
		r.Response.WriteJson(g.Map{"ok": false, "error": err.Error()})
		return
	}
	r.Response.WriteJson(g.Map{"ok": true, "profile": profile})
}

func (h *Handler) GetRecommendationExplanation(r *ghttp.Request) {
	postID := r.GetQuery("post_id").String()
	if postID == "" {
		r.Response.WriteJson(g.Map{"ok": false, "error": "post_id is required"})
		return
	}
	explanation, err := h.store.RecommendationExplanationByPostID(r.Context(), postID)
	if err != nil {
		r.Response.WriteJson(g.Map{"ok": false, "error": err.Error()})
		return
	}
	r.Response.WriteJson(g.Map{"ok": true, "explanation": explanation})
}

func (h *Handler) RebuildProfile(r *ghttp.Request) {
	var req harness.RebuildProfileRequest
	if !decodeJSON(r, &req) {
		return
	}
	result := h.harness.RebuildProfile(r.Context(), req)
	r.Response.WriteJson(g.Map{"ok": result.Status == "completed", "result": result})
}

// 函数作用：
// 将 HTTP 请求体中的 JSON 解码到目标结构体。
//
// 参数说明：
// - r：GoFrame HTTP 请求对象。
// - target：要填充的目标对象，通常是结构体指针。
//
// 返回值：
// - 解析成功返回 true；失败时写出错误响应并返回 false。
func decodeJSON(r *ghttp.Request, target any) bool {
	// Body 为空时认为没有可解码内容，保留 target 默认值。
	if r.Request.Body == nil {
		return true
	}
	// 使用标准库 JSON decoder 解析请求体。
	decoder := json.NewDecoder(r.Request.Body)
	if err := decoder.Decode(target); err != nil {
		// JSON 格式错误时返回明确错误，避免进入业务层。
		r.Response.WriteJson(g.Map{"ok": false, "error": "invalid json: " + err.Error()})
		return false
	}
	return true
}

// 函数作用：
// 解析查询参数 limit，并给出默认值。
//
// 参数说明：
// - r：GoFrame HTTP 请求对象。
//
// 返回值：
// - 返回正整数 limit；缺失或非法时返回 20。
func queryLimit(r *ghttp.Request) int {
	// r.GetQuery("limit").String() 读取 URL query 中的 limit。
	limit, _ := strconv.Atoi(r.GetQuery("limit").String())
	// 非正数使用默认 20。
	if limit <= 0 {
		return 20
	}
	return limit
}
