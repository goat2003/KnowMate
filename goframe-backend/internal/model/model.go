package model

import "time"

type Article struct {
	ID          string    `json:"id"`
	URL         string    `json:"url"`
	Title       string    `json:"title"`
	Content     string    `json:"content"`
	Author      string    `json:"author"`
	PublishedAt string    `json:"published_at"`
	Source      string    `json:"source"`
	Tags        []string  `json:"tags"`
	CreatedAt   time.Time `json:"created_at"`
}

type Post struct {
	PostUID    string    `json:"post_uid"`
	ArticleUID string    `json:"article_uid"`
	Title      string    `json:"title"`
	Markdown   string    `json:"markdown"`
	Status     string    `json:"status"`
	Tags       []string  `json:"tags"`
	CreatedAt  time.Time `json:"created_at"`
}

type FeedbackLog struct {
	RunID        string         `json:"run_id"`
	PostUID      string         `json:"post_uid"`
	ArticleUID   string         `json:"article_uid"`
	UserID       string         `json:"user_id"`
	FeedbackType string         `json:"feedback_type"`
	Rating       int            `json:"rating"`
	Comment      string         `json:"comment"`
	Metadata     map[string]any `json:"metadata"`
}

type RunLog struct {
	RunID        string         `json:"run_id"`
	Status       string         `json:"status"`
	InputCount   int            `json:"input_count"`
	OutputCount  int            `json:"output_count"`
	ErrorMessage string         `json:"error_message"`
	Metadata     map[string]any `json:"metadata"`
	CreatedAt    time.Time      `json:"created_at"`
}

type McpCallLog struct {
	RunID        string `json:"run_id"`
	AgentName    string `json:"agent_name"`
	ServerName   string `json:"server_name"`
	ToolName     string `json:"tool_name"`
	RequestJSON  string `json:"request_json"`
	ResponseJSON string `json:"response_json"`
	Status       string `json:"status"`
	ErrorMessage string `json:"error_message"`
	Success      bool   `json:"success"`
	LatencyMS    int64  `json:"latency_ms"`
}
