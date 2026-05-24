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
	URL string `json:"url"`
	// Title 对应 articles.title。
	Title string `json:"title"`
	// Content 对应 articles.content，会作为 proto Article.raw_text 发送给 Python Agent。
	Content string `json:"content"`
	// Author 对应 articles.author。
	Author string `json:"author"`
	// PublishedAt 保存 RSS 发布时间字符串。
	PublishedAt string `json:"published_at"`
	// Source 表示 RSS 源名称。
	Source string `json:"source"`
	// Tags 保存文章标签，写库时会序列化为 JSON。
	Tags []string `json:"tags"`
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

// McpCallLog 表示一次 MCP Tool 调用日志。
// 它对应 mcp_call_logs 表，由 Python Agent 返回，GoFrame 后端负责持久化。
type McpCallLog struct {
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
	LatencyMS int64 `json:"latency_ms"`
}
