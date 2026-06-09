// 文件作用：
// 本文件定义 GoFrame 后端内部使用的数据模型结构体。
// 这些结构体连接 HTTP JSON 响应、MySQL 表字段和 harness 业务流程。
//
// 在项目中的位置：
// 本文件属于 GoFrame 后端的 model 层，被 store、crawler、harness 使用。
//
// 主要内容：
// 1. Article：对应 articles 表和 RSS 抓取结果。
// 2. Post：对应 posts 表和 Markdown 输出内容。
// 3. FeedbackLog：对应 feedback_logs 表。
// 4. RunLog：对应 run_logs 表。
// 5. McpCallLog：对应 mcp_call_logs 表。
//
// 关键调用关系：
// - crawler.Fetch 返回 []Article。
// - store.InsertArticle / InsertPost / InsertRunLog 等使用这些模型写 MySQL。
// - handler 查询 posts/run_logs 后直接把这些结构体序列化为 JSON。
//
// 初学者阅读建议：
// 先对照 shared/sql/init.sql 看表结构，再看这些结构体字段如何映射到 SQL INSERT/SELECT。
package model

// time.Time 用于保存数据库 created_at 等时间字段。
import "time"

// Article 表示一篇文章。
// 它既是 RSS 抓取结果，也是写入 articles 表的业务模型。
type Article struct {
	// ID 对应 articles.article_uid，也是 Python Agent 的 article_id。
	ID string `json:"id"`
	// URL 对应 articles.url，表示原文链接。
	URL           string `json:"url"`
	NormalizedURL string `json:"normalized_url"`
	URLHash       string `json:"url_hash"`
	// Title 对应 articles.title。
	Title           string `json:"title"`
	NormalizedTitle string `json:"normalized_title"`
	TitleHash       string `json:"title_hash"`
	RawContent      string `json:"raw_content"`
	CleanContent    string `json:"clean_content"`
	// Content 对应 articles.content，会作为 proto Article.raw_text 发送给 Python Agent。
	Content     string `json:"content"`
	ContentHash string `json:"content_hash"`
	Language    string `json:"language"`
	// Author 对应 articles.author。
	Author string `json:"author"`
	// PublishedAt 保存 RSS 发布时间字符串。
	PublishedAt string `json:"published_at"`
	// Source 表示 RSS 源名称。
	Source     string `json:"source"`
	SourceType string `json:"source_type"`
	// Tags 保存文章标签，写库时会序列化为 JSON。
	Tags           []string  `json:"tags"`
	FetchStatus    string    `json:"fetch_status"`
	FetchErrorType string    `json:"fetch_error_type"`
	FetchError     string    `json:"fetch_error"`
	HTTPStatus     int       `json:"http_status"`
	RawPayload     any       `json:"raw_payload"`
	FetchedAt      time.Time `json:"fetched_at"`
	// CreatedAt 对应数据库创建时间。
	CreatedAt time.Time `json:"created_at"`
}

// Post 表示 Python Agent 生成后的推文/知识笔记。
// 它对应 posts 表，也会被 writeMarkdown 输出到 Markdown 文件。
type Post struct {
	// PostUID 是生成内容唯一 id。
	PostUID string `json:"post_uid"`
	// ArticleUID 关联原文章 article_uid。
	ArticleUID string `json:"article_uid"`
	// Title 是输出标题。
	Title string `json:"title"`
	// Markdown 是最终生成的 Markdown/推文正文。
	Markdown string `json:"markdown"`
	// Status 表示 ready、draft、check_failed 等状态。
	Status string `json:"status"`
	// Tags 继承文章标签，写库时序列化为 JSON。
	Tags []string `json:"tags"`
	// Metadata 保存推荐解释、排序分数等附加信息。
	Metadata map[string]any `json:"metadata"`
	// CreatedAt 对应 posts.created_at。
	CreatedAt time.Time `json:"created_at"`
}

// FeedbackLog 表示用户反馈日志。
// 它对应 feedback_logs 表，harness.ProcessFeedback 在调用 Python Agent 前先写入。
type FeedbackLog struct {
	// RunID 关联本次反馈处理任务。
	RunID string `json:"run_id"`
	// PostUID 关联被反馈的生成内容。
	PostUID string `json:"post_uid"`
	// ArticleUID 关联原文章。
	ArticleUID string `json:"article_uid"`
	// UserID 是反馈用户。
	UserID string `json:"user_id"`
	// FeedbackType 表示 text、like、dislike 等类型。
	FeedbackType string `json:"feedback_type"`
	// Rating 是用户评分。
	Rating int `json:"rating"`
	// Comment 是用户反馈文本。
	Comment string `json:"comment"`
	// Metadata 保存额外上下文，写库时序列化为 JSON。
	Metadata map[string]any `json:"metadata"`
}

type FeedbackRecord struct {
	ID                     uint64         `json:"id"`
	RunID                  string         `json:"run_id"`
	PostUID                string         `json:"post_uid"`
	ArticleUID             string         `json:"article_uid"`
	UserID                 string         `json:"user_id"`
	FeedbackType           string         `json:"feedback_type"`
	Rating                 int            `json:"rating"`
	Comment                string         `json:"comment"`
	IdempotencyKey         string         `json:"idempotency_key"`
	RawFeedback            map[string]any `json:"raw_feedback"`
	StructuredFeedbackJSON string         `json:"structured_feedback_json"`
	ProcessStatus          string         `json:"process_status"`
	ProfileVersion         int            `json:"profile_version"`
	ErrorMessage           string         `json:"error_message"`
	CreatedAt              time.Time      `json:"created_at"`
}

type UserProfileSnapshot struct {
	ID                    uint64            `json:"id"`
	UserID                string            `json:"user_id"`
	Version               int               `json:"version"`
	BaseVersion           int               `json:"base_version"`
	RunID                 string            `json:"run_id"`
	Summary               string            `json:"summary"`
	Snapshot              map[string]string `json:"snapshot"`
	Diff                  map[string]any    `json:"diff"`
	ChangeReason          string            `json:"change_reason"`
	SourceFeedbackID      uint64            `json:"source_feedback_id"`
	IsActive              bool              `json:"is_active"`
	RolledBackFromVersion int               `json:"rolled_back_from_version"`
	CreatedAt             time.Time         `json:"created_at"`
}

type ProfileDiffChange struct {
	Path   string `json:"path"`
	Before any    `json:"before"`
	After  any    `json:"after"`
	Reason string `json:"reason"`
}

type ProfileDiffResult struct {
	Before  map[string]string   `json:"before"`
	After   map[string]string   `json:"after"`
	Changes []ProfileDiffChange `json:"changes"`
}

type MemoryCompensationTask struct {
	TaskID       string         `json:"task_id"`
	RunID        string         `json:"run_id"`
	UserID       string         `json:"user_id"`
	TaskType     string         `json:"task_type"`
	TargetSystem string         `json:"target_system"`
	Payload      map[string]any `json:"payload"`
	Status       string         `json:"status"`
	LastError    string         `json:"last_error"`
}

type RecommendationExplanation struct {
	PostUID    string         `json:"post_uid"`
	ArticleUID string         `json:"article_uid"`
	Metadata   map[string]any `json:"metadata"`
}

// RunLog 表示一次任务运行日志。
// 文章处理和反馈处理都会写 run_logs，便于查询任务状态和步骤。
type RunLog struct {
	// RunID 是任务 id。
	RunID string `json:"run_id"`
	// Status 表示 running、completed、failed 等状态。
	Status string `json:"status"`
	// InputCount 是输入数量，例如候选文章数或反馈条数。
	InputCount int `json:"input_count"`
	// OutputCount 是输出数量，例如保存的 posts 数或提取反馈数量。
	OutputCount int `json:"output_count"`
	// ErrorMessage 保存失败原因。
	ErrorMessage string `json:"error_message"`
	// Metadata 保存步骤、路径、计数等额外信息。
	Metadata map[string]any `json:"metadata"`
	// CreatedAt 对应 run_logs.created_at。
	CreatedAt time.Time `json:"created_at"`
}

type TaskRun struct {
	RunID           string         `json:"run_id"`
	TaskType        string         `json:"task_type"`
	UserID          string         `json:"user_id"`
	Status          string         `json:"status"`
	CurrentStep     string         `json:"current_step"`
	IdempotencyKey  string         `json:"idempotency_key"`
	InputSummary    string         `json:"input_summary"`
	OutputSummary   string         `json:"output_summary"`
	ErrorMessage    string         `json:"error_message"`
	InputPayload    map[string]any `json:"input_payload"`
	PartialResult   map[string]any `json:"partial_result"`
	RetryCount      int            `json:"retry_count"`
	MaxRetries      int            `json:"max_retries"`
	TimeoutSeconds  int            `json:"timeout_seconds"`
	CancelRequested bool           `json:"cancel_requested"`
	LockedBy        string         `json:"locked_by"`
	StartedAt       *time.Time     `json:"started_at"`
	FinishedAt      *time.Time     `json:"finished_at"`
	NextRetryAt     *time.Time     `json:"next_retry_at"`
	CreatedAt       time.Time      `json:"created_at"`
	UpdatedAt       time.Time      `json:"updated_at"`
	Steps           []TaskStep     `json:"steps,omitempty"`
}

type TaskStep struct {
	RunID         string     `json:"run_id"`
	StepName      string     `json:"step_name"`
	Status        string     `json:"status"`
	StartedAt     *time.Time `json:"started_at"`
	CompletedAt   *time.Time `json:"completed_at"`
	InputSummary  string     `json:"input_summary"`
	OutputSummary string     `json:"output_summary"`
	ErrorMessage  string     `json:"error_message"`
	RetryCount    int        `json:"retry_count"`
	CreatedAt     time.Time  `json:"created_at"`
	UpdatedAt     time.Time  `json:"updated_at"`
}

type TaskRunFilter struct {
	TaskType string `json:"task_type"`
	UserID   string `json:"user_id"`
	Status   string `json:"status"`
	Limit    int    `json:"limit"`
}

type ArticleFilter struct {
	Source     string `json:"source"`
	SourceType string `json:"source_type"`
	Status     string `json:"status"`
	Language   string `json:"language"`
	Query      string `json:"q"`
	Limit      int    `json:"limit"`
}

type CrawlSourceRun struct {
	RunID        string     `json:"run_id"`
	SourceName   string     `json:"source_name"`
	SourceType   string     `json:"source_type"`
	Status       string     `json:"status"`
	ErrorType    string     `json:"error_type"`
	ErrorMessage string     `json:"error_message"`
	HTTPStatus   int        `json:"http_status"`
	ItemsFound   int        `json:"items_found"`
	ItemsSaved   int        `json:"items_saved"`
	ItemsPartial int        `json:"items_partial"`
	ItemsFailed  int        `json:"items_failed"`
	StartedAt    time.Time  `json:"started_at"`
	FinishedAt   *time.Time `json:"finished_at"`
}

// McpCallLog 表示一次 MCP Tool 调用日志。
// 它对应 mcp_call_logs 表，由 Python Agent 返回，GoFrame 后端负责持久化。
type McpCallLog struct {
	CallID string `json:"call_id"`
	// RunID 关联一次任务。
	RunID string `json:"run_id"`
	// AgentName 表示发起 MCP 调用的 Agent。
	AgentName string `json:"agent_name"`
	// ServerName 是 MCP Server 名称。
	ServerName string `json:"server_name"`
	// ToolName 是 MCP Tool 名称。
	ToolName string `json:"tool_name"`
	// RequestJSON 是 JSON-RPC 请求体。
	RequestJSON string `json:"request_json"`
	// ResponseJSON 是 JSON-RPC 响应体。
	ResponseJSON string `json:"response_json"`
	// Status 是 success、failed、denied 等状态。
	Status string `json:"status"`
	// ErrorMessage 是失败或权限拒绝原因。
	ErrorMessage string `json:"error_message"`
	// Success 是布尔成功标记。
	Success bool `json:"success"`
	// LatencyMS 是调用耗时毫秒数。
	LatencyMS int64     `json:"latency_ms"`
	CreatedAt time.Time `json:"created_at"`
}

type McpCallLogFilter struct {
	RunID      string `json:"run_id"`
	Status     string `json:"status"`
	ServerName string `json:"server_name"`
	ToolName   string `json:"tool_name"`
	Limit      int    `json:"limit"`
}
