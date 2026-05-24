// 文件作用：
// 本文件实现 GoFrame 后端的 MySQL 数据访问层。
// 它负责初始化 schema，写入 articles/posts/feedback_logs/run_logs/user_profile_snapshot/mcp_call_logs，
// 并提供 posts、run_logs 和用户画像快照的查询能力。
//
// 在项目中的位置：
// 本文件属于 GoFrame 后端的 store/dao 层，位于 logic/harness 与 MySQL 数据库之间。
//
// 主要内容：
// 1. Store：保存 MySQL DSN 和复用的 *sql.DB。
// 2. InitSchema：执行 shared/sql/init.sql 并补齐 mcp_call_logs 兼容列。
// 3. InsertArticle / InsertPost / InsertFeedbackLog / InsertRunLog / InsertUserProfileSnapshot / InsertMcpCallLogs。
// 4. LatestUserProfileSnapshot：读取 user_profile_snapshot 最新快照。
// 5. ListPosts / ListRunLogs：提供查询接口。
//
// 关键调用关系：
// - 被 handler.Health、harness.RunArticles、harness.ProcessFeedback 调用。
// - 数据库表结构来自 shared/sql/init.sql。
// - mcp_call_logs 的数据来自 Python Agent 返回的 McpCallLog。
//
// 初学者阅读建议：
// 先对照 shared/sql/init.sql 理解每张表，再看每个 Insert 方法如何把 model 字段写入 SQL。
package store

import (
	// context.Context 用于给数据库调用传递取消和超时。
	"context"
	// database/sql 是 Go 标准库数据库接口。
	"database/sql"
	// encoding/json 用于把 tags、metadata、snapshot、MCP 请求响应等结构序列化成 JSON 文本。
	"encoding/json"
	// errors 用于构造错误和判断 sql.ErrNoRows。
	"errors"
	// os 用于读取初始化 SQL 文件。
	"os"
	// strings 用于拆分 SQL、处理 JSON 字符串和判断空白。
	"strings"
	// time 用于生成默认 ID 和配置连接生命周期。
	"time"

	// model 定义数据库读写使用的业务结构体。
	"knowledge-post-agent/goframe-backend/internal/model"

	// mysql driver 通过空白导入注册到 database/sql，代码中不直接引用包名。
	_ "github.com/go-sql-driver/mysql"
)

// Store 是 MySQL 数据访问对象。
// 它集中管理连接和 SQL 操作，避免业务层直接拼 SQL。
type Store struct {
	// dsn 是 MySQL 连接串。
	dsn string
	// db 是复用的数据库连接池对象，首次 open 成功后缓存。
	db *sql.DB
}

// 函数作用：
// 创建 Store 实例。
//
// 参数说明：
// - dsn：MySQL 连接串。
//
// 返回值：
// - 返回 *Store；此时还不会立即连接数据库。
func New(dsn string) *Store {
	return &Store{dsn: dsn}
}

// 函数作用：
// 检查 MySQL 是否可连接。
//
// 参数说明：
// - ctx：上下文，用于控制 Ping 超时或取消。
//
// 返回值：
// - 成功返回 nil，失败返回 error。
func (s *Store) Ping(ctx context.Context) error {
	// open 会懒加载并缓存 *sql.DB。
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	// PingContext 真正验证数据库连接是否可用。
	return db.PingContext(ctx)
}

// 函数作用：
// 初始化数据库 schema。
//
// 参数说明：
// - ctx：数据库调用上下文。
// - path：SQL 文件路径，通常是 ../shared/sql/init.sql。
//
// 返回值：
// - 成功返回 nil，失败返回 error。
//
// 调用关系：
// - main.go 启动时调用。
func (s *Store) InitSchema(ctx context.Context, path string) error {
	// path 为空时认为调用方不需要初始化 schema。
	if path == "" {
		return nil
	}
	// 读取 SQL 初始化脚本。
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	// 获取数据库连接。
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	// 将 SQL 文件拆成多条语句逐条执行。
	for _, statement := range splitSQLStatements(string(data)) {
		if _, err := db.ExecContext(ctx, statement); err != nil {
			return err
		}
	}
	// 兼容旧库：如果 mcp_call_logs 缺少新列，则自动 ALTER TABLE 补齐。
	return s.ensureMcpCallLogColumns(ctx, db)
}

// 函数作用：
// 写入一篇文章到 articles 表。
//
// 参数说明：
// - ctx：数据库调用上下文。
// - article：文章模型。
//
// 返回值：
// - bool 表示是否新插入；如果因 INSERT IGNORE 命中重复则为 false。
// - error 表示数据库错误。
func (s *Store) InsertArticle(ctx context.Context, article model.Article) (bool, error) {
	// 文章 ID 缺失时优先使用 URL 作为稳定标识。
	if article.ID == "" {
		article.ID = article.URL
	}
	// URL 也缺失时用时间戳生成人工 ID。
	if article.ID == "" {
		article.ID = "manual-" + time.Now().UTC().Format("20060102150405")
	}
	// Tags 写入 JSON 列/文本列，便于保留多标签结构。
	tags, _ := json.Marshal(article.Tags)
	// raw_json 保存完整 Article，便于后续排查抓取原始数据。
	raw, _ := json.Marshal(article)
	// 获取数据库连接。
	db, err := s.open(ctx)
	if err != nil {
		return false, err
	}
	// INSERT IGNORE 避免重复 article_uid 导致任务失败。
	result, err := db.ExecContext(
		ctx,
		`INSERT IGNORE INTO articles (article_uid, source, url, title, content, author, tags, raw_json)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		article.ID,
		article.Source,
		article.URL,
		article.Title,
		article.Content,
		article.Author,
		string(tags),
		string(raw),
	)
	if err != nil {
		return false, err
	}
	// RowsAffected 为 1 表示新插入；为 0 表示被 IGNORE 的重复记录。
	rows, _ := result.RowsAffected()
	return rows > 0, nil
}

// 函数作用：
// 写入或更新生成后的 post 到 posts 表。
//
// 参数说明：
// - ctx：数据库调用上下文。
// - post：生成内容模型。
//
// 返回值：
// - 成功返回 nil，失败返回 error。
func (s *Store) InsertPost(ctx context.Context, post model.Post) error {
	// PostUID 缺失时生成时间戳 ID。
	if post.PostUID == "" {
		post.PostUID = "post-" + time.Now().UTC().Format("20060102150405")
	}
	// 默认状态为 draft；harness 通常会传 ready 或 check_failed。
	if post.Status == "" {
		post.Status = "draft"
	}
	// tags 序列化成 JSON 字符串。
	tags, _ := json.Marshal(post.Tags)
	// 获取数据库连接。
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	// ON DUPLICATE KEY UPDATE 让同一个 post_uid 的重跑结果可覆盖旧内容。
	_, err = db.ExecContext(
		ctx,
		`INSERT INTO posts (post_uid, article_uid, title, markdown, status, tags)
		 VALUES (?, ?, ?, ?, ?, ?)
		 ON DUPLICATE KEY UPDATE title = VALUES(title), markdown = VALUES(markdown), status = VALUES(status), tags = VALUES(tags), updated_at = CURRENT_TIMESTAMP`,
		post.PostUID,
		post.ArticleUID,
		post.Title,
		post.Markdown,
		post.Status,
		string(tags),
	)
	return err
}

// 函数作用：
// 查询最近生成的 posts。
//
// 参数说明：
// - ctx：数据库调用上下文。
// - limit：返回数量上限，非法或过大时会归一化。
//
// 返回值：
// - 返回 Post 列表和 error。
func (s *Store) ListPosts(ctx context.Context, limit int) ([]model.Post, error) {
	// 限制最大 100，防止接口一次返回太多数据。
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	// 获取数据库连接。
	db, err := s.open(ctx)
	if err != nil {
		return nil, err
	}
	// 查询 posts 表，COALESCE 确保 tags 为空时返回 []。
	rows, err := db.QueryContext(
		ctx,
		`SELECT post_uid, article_uid, title, markdown, status, COALESCE(CAST(tags AS CHAR), '[]'), created_at
		 FROM posts ORDER BY id DESC LIMIT ?`,
		limit,
	)
	if err != nil {
		return nil, err
	}
	// defer 确保函数返回时关闭 rows，释放数据库连接资源。
	defer rows.Close()

	// 预创建空切片，避免返回 nil 给 JSON 调用方。
	posts := make([]model.Post, 0)
	// 遍历查询结果。
	for rows.Next() {
		var post model.Post
		var tagsRaw string
		// Scan 按 SELECT 字段顺序填充结构体。
		if err := rows.Scan(&post.PostUID, &post.ArticleUID, &post.Title, &post.Markdown, &post.Status, &tagsRaw, &post.CreatedAt); err != nil {
			return nil, err
		}
		// tagsRaw 是 JSON 字符串，解析失败时保留 Tags 为空，不中断查询。
		_ = json.Unmarshal([]byte(tagsRaw), &post.Tags)
		posts = append(posts, post)
	}
	// rows.Err 捕获遍历期间的延迟错误。
	return posts, rows.Err()
}

// 函数作用：
// 写入用户反馈日志到 feedback_logs 表。
//
// 参数说明：
// - ctx：数据库调用上下文。
// - feedback：反馈日志模型。
//
// 返回值：
// - 成功返回 nil，失败返回 error。
func (s *Store) InsertFeedbackLog(ctx context.Context, feedback model.FeedbackLog) error {
	// Metadata 序列化成 JSON 字符串。
	metadata, _ := json.Marshal(feedback.Metadata)
	// 获取数据库连接。
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	// feedback_logs 保存原始反馈，ProcessFeedback 后续会基于它更新用户画像。
	_, err = db.ExecContext(
		ctx,
		`INSERT INTO feedback_logs (run_id, post_uid, article_uid, user_id, feedback_type, rating, comment, metadata)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		feedback.RunID,
		feedback.PostUID,
		feedback.ArticleUID,
		feedback.UserID,
		feedback.FeedbackType,
		feedback.Rating,
		feedback.Comment,
		string(metadata),
	)
	return err
}

// 函数作用：
// 写入或更新一次任务运行日志到 run_logs 表。
//
// 参数说明：
// - ctx：数据库调用上下文。
// - run：运行日志模型。
//
// 返回值：
// - 成功返回 nil，失败返回 error。
func (s *Store) InsertRunLog(ctx context.Context, run model.RunLog) error {
	// run_id 缺失时生成默认任务 id。
	if run.RunID == "" {
		run.RunID = "run-" + time.Now().UTC().Format("20060102150405")
	}
	// status 缺失时认为任务刚开始。
	if run.Status == "" {
		run.Status = "started"
	}
	// Metadata 序列化成 JSON，保存步骤、计数、Markdown 路径等。
	metadata, _ := json.Marshal(run.Metadata)
	// 获取数据库连接。
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	// run_logs 使用 run_id 做唯一键时，重复写入同一任务会更新状态和统计。
	_, err = db.ExecContext(
		ctx,
		`INSERT INTO run_logs (run_id, status, input_count, output_count, error_message, metadata, started_at, finished_at)
		 VALUES (?, ?, ?, ?, ?, ?, NOW(), IF(? IN ('completed', 'failed'), NOW(), NULL))
		 ON DUPLICATE KEY UPDATE status = VALUES(status), input_count = VALUES(input_count), output_count = VALUES(output_count),
		 error_message = VALUES(error_message), metadata = VALUES(metadata),
		 finished_at = IF(VALUES(status) IN ('completed', 'failed'), NOW(), finished_at),
		 updated_at = CURRENT_TIMESTAMP`,
		run.RunID,
		run.Status,
		run.InputCount,
		run.OutputCount,
		run.ErrorMessage,
		string(metadata),
		run.Status,
	)
	return err
}

// 函数作用：
// 查询最近任务运行日志。
//
// 参数说明：
// - ctx：数据库调用上下文。
// - limit：返回数量上限。
//
// 返回值：
// - 返回 RunLog 列表和 error。
func (s *Store) ListRunLogs(ctx context.Context, limit int) ([]model.RunLog, error) {
	// 保护查询上限，避免接口返回过多日志。
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	// 获取数据库连接。
	db, err := s.open(ctx)
	if err != nil {
		return nil, err
	}
	// 查询 run_logs，metadata 为空时返回 {}。
	rows, err := db.QueryContext(
		ctx,
		`SELECT run_id, status, input_count, output_count, COALESCE(error_message, ''), COALESCE(CAST(metadata AS CHAR), '{}'), created_at
		 FROM run_logs ORDER BY id DESC LIMIT ?`,
		limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	// logs 用于保存查询结果。
	logs := make([]model.RunLog, 0)
	for rows.Next() {
		var run model.RunLog
		var metadataRaw string
		// metadataRaw 是 JSON 字符串，后面再解析到 map。
		if err := rows.Scan(&run.RunID, &run.Status, &run.InputCount, &run.OutputCount, &run.ErrorMessage, &metadataRaw, &run.CreatedAt); err != nil {
			return nil, err
		}
		// metadata 解析失败时忽略，避免单条脏数据导致整个列表接口失败。
		_ = json.Unmarshal([]byte(metadataRaw), &run.Metadata)
		logs = append(logs, run)
	}
	return logs, rows.Err()
}

// 函数作用：
// 写入用户画像快照到 user_profile_snapshot 表。
//
// 参数说明：
// - ctx：数据库调用上下文。
// - userID：用户 id。
// - snapshot：更新后的画像快照。
// - summary：本次画像更新摘要，当前反馈流程使用 sentiment。
//
// 返回值：
// - 成功返回 nil，失败返回 error。
func (s *Store) InsertUserProfileSnapshot(ctx context.Context, userID string, snapshot map[string]string, summary string) error {
	// snapshot_json 保存完整画像快照，Python Agent 返回 map<string,string>。
	raw, _ := json.Marshal(snapshot)
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	// 每次反馈更新都插入一条新快照，LatestUserProfileSnapshot 按 id DESC 读取最新版本。
	_, err = db.ExecContext(
		ctx,
		`INSERT INTO user_profile_snapshot (user_id, summary, snapshot_json)
		 VALUES (?, ?, ?)`,
		userID,
		summary,
		string(raw),
	)
	return err
}

// 函数作用：
// 读取某个用户最新的画像快照。
//
// 参数说明：
// - ctx：数据库调用上下文。
// - userID：用户 id。
//
// 返回值：
// - 返回 map[string]string 快照；没有记录时返回空 map。
//
// 调用关系：
// - harness.loadProfile 调用它，再补齐默认 user_id 和 interests。
func (s *Store) LatestUserProfileSnapshot(ctx context.Context, userID string) (map[string]string, error) {
	// 获取数据库连接。
	db, err := s.open(ctx)
	if err != nil {
		return nil, err
	}
	// raw 保存 snapshot_json 的字符串形式。
	var raw string
	// 按 id 倒序取最新一条快照。
	err = db.QueryRowContext(
		ctx,
		`SELECT COALESCE(CAST(snapshot_json AS CHAR), '{}')
		 FROM user_profile_snapshot WHERE user_id = ? ORDER BY id DESC LIMIT 1`,
		userID,
	).Scan(&raw)
	// 没有快照不是错误，业务层会使用默认画像。
	if errors.Is(err, sql.ErrNoRows) {
		return map[string]string{}, nil
	}
	if err != nil {
		return nil, err
	}
	// 解析 JSON 快照到 map。
	snapshot := map[string]string{}
	if err := json.Unmarshal([]byte(raw), &snapshot); err != nil {
		return nil, err
	}
	return snapshot, nil
}

// 函数作用：
// 批量写入 MCP 调用日志到 mcp_call_logs 表。
//
// 参数说明：
// - ctx：数据库调用上下文。
// - logs：MCP 调用日志列表，来自 Python Agent protobuf 响应。
//
// 返回值：
// - 成功返回 nil，失败返回 error。
func (s *Store) InsertMcpCallLogs(ctx context.Context, logs []model.McpCallLog) error {
	// 没有日志时直接返回，避免开启空事务。
	if len(logs) == 0 {
		return nil
	}
	// 获取数据库连接。
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	// 使用事务保证一批 MCP 日志要么全部写入，要么失败回滚。
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	// 预编译 INSERT 语句，提高批量写入效率。
	stmt, err := tx.PrepareContext(
		ctx,
		`INSERT INTO mcp_call_logs (run_id, agent_name, server_name, tool_name, request_json, response_json, status, error_message, success, latency_ms)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
	)
	if err != nil {
		_ = tx.Rollback()
		return err
	}
	// defer 确保 statement 被关闭。
	defer stmt.Close()

	// 逐条写入 MCP 调用日志。
	for _, log := range logs {
		// request_json 需要保证是合法 JSON；非法时会包装为 {"raw": "..."}。
		req := normalizeJSON(log.RequestJSON)
		// response_json 同样做合法 JSON 归一化。
		resp := normalizeJSON(log.ResponseJSON)
		// status 为空时根据 success 推导，兼容旧版本 Python Agent 响应。
		status := log.Status
		if status == "" {
			if log.Success {
				status = "success"
			} else {
				status = "failed"
			}
		}
		// 执行单条日志写入。
		if _, err := stmt.ExecContext(ctx, log.RunID, log.AgentName, log.ServerName, log.ToolName, req, resp, status, log.ErrorMessage, log.Success, log.LatencyMS); err != nil {
			_ = tx.Rollback()
			return err
		}
	}
	// 所有日志写入成功后提交事务。
	return tx.Commit()
}

// 函数作用：
// 获取或创建 MySQL 连接池。
//
// 参数说明：
// - ctx：上下文，用于 Ping 超时。
//
// 返回值：
// - 返回 *sql.DB 或 error。
func (s *Store) open(ctx context.Context) (*sql.DB, error) {
	// DSN 为空无法连接数据库，返回明确错误。
	if s.dsn == "" {
		return nil, errors.New("mysql dsn is empty")
	}
	// 已经创建过连接池时直接复用。
	if s.db != nil {
		return s.db, nil
	}
	// sql.Open 不会立即建立连接，只创建连接池对象。
	db, err := sql.Open("mysql", s.dsn)
	if err != nil {
		return nil, err
	}
	// 设置连接池参数，避免无限连接占满 MySQL。
	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(5)
	db.SetConnMaxLifetime(30 * time.Minute)
	// 用短超时 Ping 验证数据库实际可用。
	pingCtx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	if err := db.PingContext(pingCtx); err != nil {
		// Ping 失败时关闭连接池，避免保存不可用 db。
		_ = db.Close()
		return nil, err
	}
	// 缓存连接池供后续复用。
	s.db = db
	return s.db, nil
}

// 函数作用：
// 将 SQL 文件文本拆分为可执行语句。
//
// 参数说明：
// - raw：SQL 文件完整文本。
//
// 返回值：
// - 返回去空后的 SQL 语句列表。
func splitSQLStatements(raw string) []string {
	// 当前 init.sql 较简单，用分号拆分即可；复杂存储过程场景不适用。
	parts := strings.Split(raw, ";")
	// 预分配语句列表容量。
	statements := make([]string, 0, len(parts))
	for _, part := range parts {
		// 去除每段前后空白。
		statement := strings.TrimSpace(part)
		// 空语句或纯注释段跳过。
		if statement == "" || strings.HasPrefix(statement, "--") {
			continue
		}
		// 追加可执行语句。
		statements = append(statements, statement)
	}
	return statements
}

// 函数作用：
// 归一化 JSON 字符串，确保写入 MySQL JSON 列的内容合法。
//
// 参数说明：
// - raw：原始 JSON 字符串。
//
// 返回值：
// - 合法 JSON 返回压缩后的 JSON；空字符串返回 {}；非法 JSON 包装为 {"raw": "..."}。
func normalizeJSON(raw string) string {
	// 空字符串用空对象兜底。
	if strings.TrimSpace(raw) == "" {
		return "{}"
	}
	// 尝试解析为任意 JSON 值。
	var value any
	if err := json.Unmarshal([]byte(raw), &value); err != nil {
		// 非法 JSON 不能直接写入 JSON 列，所以包装成合法对象。
		encoded, _ := json.Marshal(map[string]string{"raw": raw})
		return string(encoded)
	}
	// 重新 Marshal 可以压缩格式并规范化 JSON。
	encoded, _ := json.Marshal(value)
	return string(encoded)
}

// 函数作用：
// 兼容旧数据库结构，确保 mcp_call_logs 表包含当前代码需要的列。
//
// 参数说明：
// - ctx：数据库调用上下文。
// - db：已打开的数据库连接池。
//
// 返回值：
// - 成功返回 nil，失败返回 error。
func (s *Store) ensureMcpCallLogColumns(ctx context.Context, db *sql.DB) error {
	// columns 列出需要检查并可能补齐的列。
	columns := []struct {
		// name 是 information_schema 中要查询的列名。
		name string
		// ddl 是列不存在时执行的 ALTER TABLE 语句。
		ddl string
	}{
		{name: "agent_name", ddl: "ALTER TABLE mcp_call_logs ADD COLUMN agent_name VARCHAR(128) NOT NULL DEFAULT '' AFTER run_id"},
		{name: "status", ddl: "ALTER TABLE mcp_call_logs ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'success' AFTER response_json"},
		{name: "error_message", ddl: "ALTER TABLE mcp_call_logs ADD COLUMN error_message TEXT NULL AFTER status"},
	}
	// 逐列检查。
	for _, column := range columns {
		var count int
		// information_schema.columns 可查询当前数据库表是否已有某列。
		err := db.QueryRowContext(
			ctx,
			`SELECT COUNT(*) FROM information_schema.columns
			 WHERE table_schema = DATABASE() AND table_name = 'mcp_call_logs' AND column_name = ?`,
			column.name,
		).Scan(&count)
		if err != nil {
			return err
		}
		// count 为 0 表示列不存在，需要执行 DDL 补齐。
		if count == 0 {
			if _, err := db.ExecContext(ctx, column.ddl); err != nil {
				return err
			}
		}
	}
	return nil
}
