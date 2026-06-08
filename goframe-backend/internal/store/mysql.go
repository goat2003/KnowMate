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
	"crypto/sha256"
	"fmt"
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
	"sort"
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
	tags, err := json.Marshal(article.Tags)
	if err != nil {
		return false, err
	}
	rawPayload, err := json.Marshal(article.RawPayload)
	if err != nil {
		return false, err
	}
	// raw_json 保存完整 Article，便于后续排查抓取原始数据。
	raw, err := json.Marshal(article)
	if err != nil {
		return false, err
	}
	// 获取数据库连接。
	db, err := s.open(ctx)
	if err != nil {
		return false, err
	}
	// INSERT IGNORE 避免重复 article_uid 导致任务失败。
	result, err := db.ExecContext(
		ctx,
		`INSERT IGNORE INTO articles (
		 article_uid, source, source_type, url, normalized_url, url_hash, title, normalized_title, title_hash,
		 content, raw_content, clean_content, content_hash, language, author, published_at, tags,
		 fetch_status, fetch_error_type, fetch_error, http_status, raw_payload, raw_json, fetched_at
		 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		article.ID,
		article.Source,
		article.SourceType,
		article.URL,
		nullableString(article.NormalizedURL),
		nullableString(article.URLHash),
		article.Title,
		article.NormalizedTitle,
		nullableString(article.TitleHash),
		article.Content,
		article.RawContent,
		article.CleanContent,
		nullableString(article.ContentHash),
		article.Language,
		article.Author,
		nullableTimeString(article.PublishedAt),
		string(tags),
		article.FetchStatus,
		article.FetchErrorType,
		nullableString(article.FetchError),
		nullableInt(article.HTTPStatus),
		string(rawPayload),
		string(raw),
		nullableTime(article.FetchedAt),
	)
	if err != nil {
		return false, err
	}
	// RowsAffected 为 1 表示新插入；为 0 表示被 IGNORE 的重复记录。
	rows, _ := result.RowsAffected()
	return rows > 0, nil
}

func (s *Store) UpsertCrawlSourceRun(ctx context.Context, run model.CrawlSourceRun) error {
	if run.Status == "" {
		run.Status = "running"
	}
	if run.StartedAt.IsZero() {
		run.StartedAt = time.Now().UTC()
	}
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	_, err = db.ExecContext(
		ctx,
		`INSERT INTO crawl_source_runs (
		 run_id, source_name, source_type, status, error_type, error_message, http_status,
		 items_found, items_saved, items_partial, items_failed, started_at, finished_at
		 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		 ON DUPLICATE KEY UPDATE source_type = VALUES(source_type), status = VALUES(status),
		 error_type = VALUES(error_type), error_message = VALUES(error_message), http_status = VALUES(http_status),
		 items_found = VALUES(items_found), items_saved = VALUES(items_saved), items_partial = VALUES(items_partial),
		 items_failed = VALUES(items_failed), finished_at = VALUES(finished_at), updated_at = CURRENT_TIMESTAMP`,
		run.RunID,
		run.SourceName,
		run.SourceType,
		run.Status,
		run.ErrorType,
		nullableString(run.ErrorMessage),
		nullableInt(run.HTTPStatus),
		run.ItemsFound,
		run.ItemsSaved,
		run.ItemsPartial,
		run.ItemsFailed,
		run.StartedAt,
		run.FinishedAt,
	)
	return err
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
	metadata, _ := json.Marshal(post.Metadata)
	// 获取数据库连接。
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	// ON DUPLICATE KEY UPDATE 让同一个 post_uid 的重跑结果可覆盖旧内容。
	_, err = db.ExecContext(
		ctx,
		`INSERT INTO posts (post_uid, article_uid, title, markdown, status, tags, metadata)
		 VALUES (?, ?, ?, ?, ?, ?, ?)
		 ON DUPLICATE KEY UPDATE title = VALUES(title), markdown = VALUES(markdown), status = VALUES(status),
		 tags = VALUES(tags), metadata = VALUES(metadata), updated_at = CURRENT_TIMESTAMP`,
		post.PostUID,
		post.ArticleUID,
		post.Title,
		post.Markdown,
		post.Status,
		string(tags),
		string(metadata),
	)
	return err
}

func (s *Store) ArticleHasPost(ctx context.Context, articleUID string) (bool, error) {
	if strings.TrimSpace(articleUID) == "" {
		return false, nil
	}
	db, err := s.open(ctx)
	if err != nil {
		return false, err
	}
	var count int
	err = db.QueryRowContext(ctx, `SELECT COUNT(*) FROM posts WHERE article_uid = ? LIMIT 1`, articleUID).Scan(&count)
	return count > 0, err
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
		`SELECT post_uid, article_uid, title, markdown, status,
		        COALESCE(CAST(tags AS CHAR), '[]'), COALESCE(CAST(metadata AS CHAR), '{}'), created_at
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
		var metadataRaw string
		// Scan 按 SELECT 字段顺序填充结构体。
		if err := rows.Scan(&post.PostUID, &post.ArticleUID, &post.Title, &post.Markdown, &post.Status, &tagsRaw, &metadataRaw, &post.CreatedAt); err != nil {
			return nil, err
		}
		// tagsRaw 是 JSON 字符串，解析失败时保留 Tags 为空，不中断查询。
		_ = json.Unmarshal([]byte(tagsRaw), &post.Tags)
		_ = json.Unmarshal([]byte(metadataRaw), &post.Metadata)
		posts = append(posts, post)
	}
	// rows.Err 捕获遍历期间的延迟错误。
	return posts, rows.Err()
}

func (s *Store) RecommendationExplanationByPostID(ctx context.Context, postID string) (model.RecommendationExplanation, error) {
	db, err := s.open(ctx)
	if err != nil {
		return model.RecommendationExplanation{}, err
	}
	var explanation model.RecommendationExplanation
	var metadataRaw string
	err = db.QueryRowContext(
		ctx,
		`SELECT post_uid, article_uid, COALESCE(CAST(metadata AS CHAR), '{}')
		   FROM posts
		  WHERE post_uid = ?
		  LIMIT 1`,
		postID,
	).Scan(&explanation.PostUID, &explanation.ArticleUID, &metadataRaw)
	if err != nil {
		return model.RecommendationExplanation{}, err
	}
	explanation.Metadata = map[string]any{}
	_ = json.Unmarshal([]byte(metadataRaw), &explanation.Metadata)
	return explanation, nil
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
	idempotencyKey := FeedbackIdempotencyKey(
		feedback.UserID,
		feedback.PostUID,
		feedback.ArticleUID,
		feedback.FeedbackType,
		feedback.Rating,
		feedback.Comment,
	)
	rawFeedback := map[string]any{
		"run_id":        feedback.RunID,
		"post_uid":      feedback.PostUID,
		"article_uid":   feedback.ArticleUID,
		"user_id":       feedback.UserID,
		"feedback_type": feedback.FeedbackType,
		"rating":        feedback.Rating,
		"comment":       feedback.Comment,
		"metadata":      feedback.Metadata,
	}
	rawJSON, _ := json.Marshal(rawFeedback)
	// 获取数据库连接。
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	// feedback_logs 保存原始反馈，ProcessFeedback 后续会基于它更新用户画像。
	_, err = db.ExecContext(
		ctx,
		`INSERT INTO feedback_logs (
		 run_id, post_uid, article_uid, user_id, feedback_type, rating, comment, metadata,
		 idempotency_key, raw_feedback_json, process_status
		 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'received')
		 ON DUPLICATE KEY UPDATE post_uid = VALUES(post_uid), article_uid = VALUES(article_uid),
		 user_id = VALUES(user_id), feedback_type = VALUES(feedback_type), rating = VALUES(rating),
		 comment = VALUES(comment), metadata = VALUES(metadata), raw_feedback_json = VALUES(raw_feedback_json)`,
		feedback.RunID,
		feedback.PostUID,
		feedback.ArticleUID,
		feedback.UserID,
		feedback.FeedbackType,
		feedback.Rating,
		feedback.Comment,
		string(metadata),
		idempotencyKey,
		string(rawJSON),
	)
	return err
}

func (s *Store) UpsertFeedbackReceived(ctx context.Context, feedback model.FeedbackLog, idempotencyKey string, raw map[string]any) (model.FeedbackRecord, bool, error) {
	if idempotencyKey == "" {
		idempotencyKey = FeedbackIdempotencyKey(
			feedback.UserID,
			feedback.PostUID,
			feedback.ArticleUID,
			feedback.FeedbackType,
			feedback.Rating,
			feedback.Comment,
		)
	}
	if raw == nil {
		raw = map[string]any{}
	}
	db, err := s.open(ctx)
	if err != nil {
		return model.FeedbackRecord{}, false, err
	}
	if existing, err := s.feedbackRecordByIdempotency(ctx, db, feedback.UserID, idempotencyKey); err == nil {
		return existing, false, nil
	} else if !errors.Is(err, sql.ErrNoRows) {
		return model.FeedbackRecord{}, false, err
	}
	metadata, _ := json.Marshal(feedback.Metadata)
	rawJSON, _ := json.Marshal(raw)
	result, err := db.ExecContext(
		ctx,
		`INSERT INTO feedback_logs (
		 run_id, post_uid, article_uid, user_id, feedback_type, rating, comment, metadata,
		 idempotency_key, raw_feedback_json, process_status
		 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'received')
		 ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)`,
		feedback.RunID,
		feedback.PostUID,
		feedback.ArticleUID,
		feedback.UserID,
		feedback.FeedbackType,
		feedback.Rating,
		feedback.Comment,
		string(metadata),
		idempotencyKey,
		string(rawJSON),
	)
	if err != nil {
		return model.FeedbackRecord{}, false, err
	}
	id, err := result.LastInsertId()
	if err != nil {
		return model.FeedbackRecord{}, false, err
	}
	rows, _ := result.RowsAffected()
	record, err := s.feedbackRecordByID(ctx, db, uint64(id))
	return record, rows == 1, err
}

func (s *Store) MarkFeedbackProcessing(ctx context.Context, id uint64) error {
	return s.updateFeedbackStatus(ctx, id, "processing", "", 0, "")
}

func (s *Store) MarkFeedbackCompleted(ctx context.Context, id uint64, structuredJSON string, profileVersion int) error {
	return s.updateFeedbackStatus(ctx, id, "completed", structuredJSON, profileVersion, "")
}

func (s *Store) MarkFeedbackFailed(ctx context.Context, id uint64, message string) error {
	return s.updateFeedbackStatus(ctx, id, "failed", "", 0, message)
}

func (s *Store) ListCompletedStructuredFeedback(ctx context.Context, userID string) ([]model.FeedbackRecord, error) {
	db, err := s.open(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := db.QueryContext(
		ctx,
		`SELECT id, run_id, post_uid, article_uid, user_id, feedback_type, COALESCE(rating, 0),
		        COALESCE(comment, ''), idempotency_key, COALESCE(CAST(raw_feedback_json AS CHAR), '{}'),
		        COALESCE(CAST(structured_feedback_json AS CHAR), ''), process_status,
		        COALESCE(profile_version, 0), COALESCE(error_message, ''), created_at
		   FROM feedback_logs
		  WHERE user_id = ?
		    AND process_status = 'completed'
		    AND structured_feedback_json IS NOT NULL
		    AND COALESCE(CAST(structured_feedback_json AS CHAR), '{}') <> '{}'
		  ORDER BY id ASC`,
		userID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	records := make([]model.FeedbackRecord, 0)
	for rows.Next() {
		record, err := scanFeedbackRecord(rows)
		if err != nil {
			return nil, err
		}
		records = append(records, record)
	}
	return records, rows.Err()
}

func (s *Store) feedbackRecordByIdempotency(ctx context.Context, db *sql.DB, userID string, idempotencyKey string) (model.FeedbackRecord, error) {
	return scanFeedbackRecord(db.QueryRowContext(
		ctx,
		`SELECT id, run_id, post_uid, article_uid, user_id, feedback_type, COALESCE(rating, 0),
		        COALESCE(comment, ''), idempotency_key, COALESCE(CAST(raw_feedback_json AS CHAR), '{}'),
		        COALESCE(CAST(structured_feedback_json AS CHAR), ''), process_status,
		        COALESCE(profile_version, 0), COALESCE(error_message, ''), created_at
		   FROM feedback_logs
		  WHERE user_id = ? AND idempotency_key = ?
		  LIMIT 1`,
		userID,
		idempotencyKey,
	))
}

func (s *Store) feedbackRecordByID(ctx context.Context, db *sql.DB, id uint64) (model.FeedbackRecord, error) {
	return scanFeedbackRecord(db.QueryRowContext(
		ctx,
		`SELECT id, run_id, post_uid, article_uid, user_id, feedback_type, COALESCE(rating, 0),
		        COALESCE(comment, ''), idempotency_key, COALESCE(CAST(raw_feedback_json AS CHAR), '{}'),
		        COALESCE(CAST(structured_feedback_json AS CHAR), ''), process_status,
		        COALESCE(profile_version, 0), COALESCE(error_message, ''), created_at
		   FROM feedback_logs
		  WHERE id = ?
		  LIMIT 1`,
		id,
	))
}

func (s *Store) updateFeedbackStatus(ctx context.Context, id uint64, status string, structuredJSON string, profileVersion int, message string) error {
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	switch status {
	case "processing":
		_, err = db.ExecContext(ctx, `UPDATE feedback_logs SET process_status = 'processing' WHERE id = ?`, id)
	case "completed":
		_, err = db.ExecContext(
			ctx,
			`UPDATE feedback_logs
			    SET process_status = 'completed',
			        structured_feedback_json = ?,
			        profile_version = ?,
			        error_message = NULL,
			        processed_at = NOW()
			  WHERE id = ?`,
			normalizeJSON(structuredJSON),
			profileVersion,
			id,
		)
	case "failed":
		_, err = db.ExecContext(
			ctx,
			`UPDATE feedback_logs
			    SET process_status = 'failed',
			        error_message = ?,
			        processed_at = NOW()
			  WHERE id = ?`,
			message,
			id,
		)
	default:
		err = fmt.Errorf("unknown feedback status %q", status)
	}
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

func (s *Store) CreateTaskRun(ctx context.Context, task model.TaskRun) (model.TaskRun, error) {
	if task.RunID == "" {
		return model.TaskRun{}, errors.New("run_id is required")
	}
	if task.Status == "" {
		task.Status = "pending"
	}
	inputPayload, _ := json.Marshal(nonNilMap(task.InputPayload))
	partialResult, _ := json.Marshal(nonNilMap(task.PartialResult))
	db, err := s.open(ctx)
	if err != nil {
		return model.TaskRun{}, err
	}
	if task.UserID != "" && task.TaskType != "" {
		existing, err := scanTaskRun(db.QueryRowContext(
			ctx,
			`SELECT run_id, task_type, user_id, status, current_step, idempotency_key,
			        input_summary, output_summary, COALESCE(error_message, ''),
			        COALESCE(CAST(input_payload_json AS CHAR), '{}'),
			        COALESCE(CAST(partial_result_json AS CHAR), '{}'),
			        retry_count, max_retries, timeout_seconds, cancel_requested, locked_by,
			        started_at, finished_at, next_retry_at, created_at, updated_at
			   FROM task_runs
			  WHERE task_type = ? AND user_id = ?
			    AND status IN ('pending', 'running')
			  ORDER BY id DESC
			  LIMIT 1`,
			task.TaskType,
			task.UserID,
		))
		if err == nil {
			return existing, nil
		}
		if !errors.Is(err, sql.ErrNoRows) {
			return model.TaskRun{}, err
		}
	}
	_, err = db.ExecContext(
		ctx,
		`INSERT INTO task_runs (
		 run_id, task_type, user_id, status, current_step, idempotency_key,
		 input_summary, output_summary, error_message, input_payload_json, partial_result_json,
		 retry_count, max_retries, timeout_seconds, cancel_requested, locked_by
		 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		 ON DUPLICATE KEY UPDATE run_id = run_id`,
		task.RunID,
		task.TaskType,
		task.UserID,
		task.Status,
		task.CurrentStep,
		task.IdempotencyKey,
		task.InputSummary,
		task.OutputSummary,
		task.ErrorMessage,
		string(inputPayload),
		string(partialResult),
		task.RetryCount,
		task.MaxRetries,
		task.TimeoutSeconds,
		task.CancelRequested,
		task.LockedBy,
	)
	if err != nil {
		return model.TaskRun{}, err
	}
	return s.TaskRun(ctx, task.RunID)
}

func (s *Store) UpdateTaskRun(ctx context.Context, task model.TaskRun) error {
	if task.RunID == "" {
		return errors.New("run_id is required")
	}
	inputPayload, _ := json.Marshal(nonNilMap(task.InputPayload))
	partialResult, _ := json.Marshal(nonNilMap(task.PartialResult))
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	_, err = db.ExecContext(
		ctx,
		`UPDATE task_runs
		    SET status = IF(? = '', status, ?),
		        current_step = IF(? = '', current_step, ?),
		        output_summary = IF(? = '', output_summary, ?),
		        error_message = IF(? = '', error_message, ?),
		        input_payload_json = IF(? = '{}', input_payload_json, ?),
		        partial_result_json = IF(? = '{}', partial_result_json, ?),
		        retry_count = IF(? = 0, retry_count, ?),
		        max_retries = IF(? = 0, max_retries, ?),
		        timeout_seconds = IF(? = 0, timeout_seconds, ?),
		        cancel_requested = IF(? = TRUE, TRUE, cancel_requested),
		        locked_by = IF(? = '', locked_by, ?),
		        started_at = COALESCE(?, started_at),
		        finished_at = COALESCE(?, finished_at),
		        next_retry_at = COALESCE(?, next_retry_at),
		        updated_at = CURRENT_TIMESTAMP
		  WHERE run_id = ?`,
		task.Status, task.Status,
		task.CurrentStep, task.CurrentStep,
		task.OutputSummary, task.OutputSummary,
		task.ErrorMessage, task.ErrorMessage,
		string(inputPayload), string(inputPayload),
		string(partialResult), string(partialResult),
		task.RetryCount, task.RetryCount,
		task.MaxRetries, task.MaxRetries,
		task.TimeoutSeconds, task.TimeoutSeconds,
		task.CancelRequested,
		task.LockedBy, task.LockedBy,
		task.StartedAt,
		task.FinishedAt,
		task.NextRetryAt,
		task.RunID,
	)
	return err
}

func (s *Store) MarkTaskRunStatus(ctx context.Context, runID string, status string, errorMessage string, partial map[string]any) error {
	if runID == "" {
		return errors.New("run_id is required")
	}
	finishedAt := time.Now().UTC()
	partialResult, _ := json.Marshal(nonNilMap(partial))
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	_, err = db.ExecContext(
		ctx,
		`UPDATE task_runs
		    SET status = ?,
		        error_message = ?,
		        partial_result_json = ?,
		        cancel_requested = IF(? = 'cancelled', TRUE, cancel_requested),
		        locked_by = '',
		        finished_at = ?,
		        updated_at = CURRENT_TIMESTAMP
		  WHERE run_id = ?`,
		status,
		errorMessage,
		string(partialResult),
		status,
		finishedAt,
		runID,
	)
	return err
}

func (s *Store) UpsertTaskStep(ctx context.Context, step model.TaskStep) error {
	if step.RunID == "" || step.StepName == "" {
		return nil
	}
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	_, err = db.ExecContext(
		ctx,
		`INSERT INTO task_steps (
		 run_id, step_name, status, started_at, completed_at,
		 input_summary, output_summary, error_message, retry_count
		 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
		 ON DUPLICATE KEY UPDATE status = VALUES(status), started_at = COALESCE(task_steps.started_at, VALUES(started_at)),
		 completed_at = VALUES(completed_at), input_summary = IF(VALUES(input_summary) = '', task_steps.input_summary, VALUES(input_summary)),
		 output_summary = VALUES(output_summary), error_message = VALUES(error_message), retry_count = VALUES(retry_count),
		 updated_at = CURRENT_TIMESTAMP`,
		step.RunID,
		step.StepName,
		step.Status,
		step.StartedAt,
		step.CompletedAt,
		step.InputSummary,
		step.OutputSummary,
		step.ErrorMessage,
		step.RetryCount,
	)
	return err
}

func (s *Store) TaskRun(ctx context.Context, runID string) (model.TaskRun, error) {
	db, err := s.open(ctx)
	if err != nil {
		return model.TaskRun{}, err
	}
	return scanTaskRun(db.QueryRowContext(
		ctx,
		`SELECT run_id, task_type, user_id, status, current_step, idempotency_key,
		        input_summary, output_summary, COALESCE(error_message, ''),
		        COALESCE(CAST(input_payload_json AS CHAR), '{}'),
		        COALESCE(CAST(partial_result_json AS CHAR), '{}'),
		        retry_count, max_retries, timeout_seconds, cancel_requested, locked_by,
		        started_at, finished_at, next_retry_at, created_at, updated_at
		   FROM task_runs
		  WHERE run_id = ?
		  LIMIT 1`,
		runID,
	))
}

func (s *Store) ListTaskRuns(ctx context.Context, filter model.TaskRunFilter) ([]model.TaskRun, error) {
	if filter.Limit <= 0 || filter.Limit > 100 {
		filter.Limit = 20
	}
	db, err := s.open(ctx)
	if err != nil {
		return nil, err
	}
	conditions := []string{"1 = 1"}
	args := []any{}
	if filter.TaskType != "" {
		conditions = append(conditions, "task_type = ?")
		args = append(args, filter.TaskType)
	}
	if filter.UserID != "" {
		conditions = append(conditions, "user_id = ?")
		args = append(args, filter.UserID)
	}
	if filter.Status != "" {
		conditions = append(conditions, "status = ?")
		args = append(args, filter.Status)
	}
	args = append(args, filter.Limit)
	rows, err := db.QueryContext(
		ctx,
		`SELECT run_id, task_type, user_id, status, current_step, idempotency_key,
		        input_summary, output_summary, COALESCE(error_message, ''),
		        COALESCE(CAST(input_payload_json AS CHAR), '{}'),
		        COALESCE(CAST(partial_result_json AS CHAR), '{}'),
		        retry_count, max_retries, timeout_seconds, cancel_requested, locked_by,
		        started_at, finished_at, next_retry_at, created_at, updated_at
		   FROM task_runs
		  WHERE `+strings.Join(conditions, " AND ")+`
		  ORDER BY id DESC
		  LIMIT ?`,
		args...,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]model.TaskRun, 0)
	for rows.Next() {
		item, err := scanTaskRun(rows)
		if err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (s *Store) ListTaskSteps(ctx context.Context, runID string) ([]model.TaskStep, error) {
	db, err := s.open(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := db.QueryContext(
		ctx,
		`SELECT run_id, step_name, status, started_at, completed_at,
		        input_summary, output_summary, COALESCE(error_message, ''), retry_count, created_at, updated_at
		   FROM task_steps
		  WHERE run_id = ?
		  ORDER BY id ASC`,
		runID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]model.TaskStep, 0)
	for rows.Next() {
		item, err := scanTaskStep(rows)
		if err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (s *Store) RecoverInterruptedTaskRuns(ctx context.Context, lockedBy string) ([]model.TaskRun, error) {
	db, err := s.open(ctx)
	if err != nil {
		return nil, err
	}
	now := time.Now().UTC()
	_, err = db.ExecContext(
		ctx,
		`UPDATE task_runs
		    SET status = 'pending',
		        locked_by = '',
		        next_retry_at = ?,
		        error_message = IF(error_message = '', 'recovered after service restart', error_message),
		        updated_at = CURRENT_TIMESTAMP
		  WHERE status IN ('running', 'pending')
		    AND cancel_requested = FALSE`,
		now,
	)
	if err != nil {
		return nil, err
	}
	return s.ListTaskRuns(ctx, model.TaskRunFilter{Status: "pending", Limit: 100})
}

func (s *Store) RequestTaskCancellation(ctx context.Context, runID string) (model.TaskRun, error) {
	db, err := s.open(ctx)
	if err != nil {
		return model.TaskRun{}, err
	}
	finishedAt := time.Now().UTC()
	_, err = db.ExecContext(
		ctx,
		`UPDATE task_runs
		    SET cancel_requested = TRUE,
		        status = IF(status IN ('pending', 'running'), 'cancelled', status),
		        error_message = IF(error_message = '', 'task cancellation requested', error_message),
		        locked_by = '',
		        finished_at = IF(status IN ('pending', 'running'), ?, finished_at),
		        updated_at = CURRENT_TIMESTAMP
		  WHERE run_id = ?`,
		finishedAt,
		runID,
	)
	if err != nil {
		return model.TaskRun{}, err
	}
	return s.TaskRun(ctx, runID)
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
	_, err := s.InsertUserProfileSnapshotVersion(ctx, model.UserProfileSnapshot{
		UserID:       userID,
		Summary:      summary,
		Snapshot:     snapshot,
		Diff:         map[string]any{},
		ChangeReason: "compat_insert",
	})
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
	snapshot, err := s.ActiveUserProfileSnapshot(ctx, userID)
	if errors.Is(err, sql.ErrNoRows) {
		return map[string]string{}, nil
	}
	if err != nil {
		return nil, err
	}
	return snapshot.Snapshot, nil
}

func (s *Store) ActiveUserProfileSnapshot(ctx context.Context, userID string) (model.UserProfileSnapshot, error) {
	db, err := s.open(ctx)
	if err != nil {
		return model.UserProfileSnapshot{}, err
	}
	return scanUserProfileSnapshot(db.QueryRowContext(
		ctx,
		`SELECT id, user_id, version, COALESCE(base_version, 0), run_id, COALESCE(summary, ''),
		        COALESCE(CAST(snapshot_json AS CHAR), '{}'), COALESCE(CAST(diff_json AS CHAR), '{}'),
		        change_reason, COALESCE(source_feedback_id, 0), is_active,
		        COALESCE(rolled_back_from_version, 0), created_at
		   FROM user_profile_snapshot
		  WHERE user_id = ?
		  ORDER BY is_active DESC, version DESC, id DESC
		  LIMIT 1`,
		userID,
	))
}

func (s *Store) ListUserProfileSnapshots(ctx context.Context, userID string, limit int) ([]model.UserProfileSnapshot, error) {
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	db, err := s.open(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := db.QueryContext(
		ctx,
		`SELECT id, user_id, version, COALESCE(base_version, 0), run_id, COALESCE(summary, ''),
		        COALESCE(CAST(snapshot_json AS CHAR), '{}'), COALESCE(CAST(diff_json AS CHAR), '{}'),
		        change_reason, COALESCE(source_feedback_id, 0), is_active,
		        COALESCE(rolled_back_from_version, 0), created_at
		   FROM user_profile_snapshot
		  WHERE user_id = ?
		  ORDER BY version DESC, id DESC
		  LIMIT ?`,
		userID,
		limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]model.UserProfileSnapshot, 0)
	for rows.Next() {
		item, err := scanUserProfileSnapshot(rows)
		if err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (s *Store) InsertUserProfileSnapshotVersion(ctx context.Context, snapshot model.UserProfileSnapshot) (model.UserProfileSnapshot, error) {
	if snapshot.UserID == "" {
		return model.UserProfileSnapshot{}, errors.New("user_id is required")
	}
	if snapshot.Snapshot == nil {
		snapshot.Snapshot = map[string]string{}
	}
	if snapshot.Diff == nil {
		snapshot.Diff = map[string]any{}
	}
	db, err := s.open(ctx)
	if err != nil {
		return model.UserProfileSnapshot{}, err
	}
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		return model.UserProfileSnapshot{}, err
	}
	var latestVersion int
	if err := tx.QueryRowContext(ctx, `SELECT COALESCE(MAX(version), 0) FROM user_profile_snapshot WHERE user_id = ?`, snapshot.UserID).Scan(&latestVersion); err != nil {
		_ = tx.Rollback()
		return model.UserProfileSnapshot{}, err
	}
	if snapshot.Version == 0 {
		snapshot.Version = latestVersion + 1
	}
	if snapshot.BaseVersion == 0 && latestVersion > 0 {
		snapshot.BaseVersion = latestVersion
	}
	if snapshot.ChangeReason == "" {
		snapshot.ChangeReason = "feedback"
	}
	rawSnapshot, _ := json.Marshal(snapshot.Snapshot)
	rawDiff, _ := json.Marshal(snapshot.Diff)
	if _, err := tx.ExecContext(ctx, `UPDATE user_profile_snapshot SET is_active = FALSE WHERE user_id = ?`, snapshot.UserID); err != nil {
		_ = tx.Rollback()
		return model.UserProfileSnapshot{}, err
	}
	result, err := tx.ExecContext(
		ctx,
		`INSERT INTO user_profile_snapshot (
		 user_id, summary, snapshot_json, version, base_version, run_id, diff_json,
		 change_reason, source_feedback_id, is_active, rolled_back_from_version
		 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, ?)`,
		snapshot.UserID,
		snapshot.Summary,
		string(rawSnapshot),
		snapshot.Version,
		nullableInt(snapshot.BaseVersion),
		snapshot.RunID,
		string(rawDiff),
		snapshot.ChangeReason,
		nullableUint64(snapshot.SourceFeedbackID),
		nullableInt(snapshot.RolledBackFromVersion),
	)
	if err != nil {
		_ = tx.Rollback()
		return model.UserProfileSnapshot{}, err
	}
	id, err := result.LastInsertId()
	if err != nil {
		_ = tx.Rollback()
		return model.UserProfileSnapshot{}, err
	}
	if err := tx.Commit(); err != nil {
		return model.UserProfileSnapshot{}, err
	}
	snapshot.ID = uint64(id)
	snapshot.IsActive = true
	return snapshot, nil
}

func (s *Store) RollbackUserProfileSnapshot(ctx context.Context, userID string, targetVersion int, reason string) (model.UserProfileSnapshot, error) {
	if targetVersion <= 0 {
		return model.UserProfileSnapshot{}, errors.New("target version is required")
	}
	db, err := s.open(ctx)
	if err != nil {
		return model.UserProfileSnapshot{}, err
	}
	target, err := scanUserProfileSnapshot(db.QueryRowContext(
		ctx,
		`SELECT id, user_id, version, COALESCE(base_version, 0), run_id, COALESCE(summary, ''),
		        COALESCE(CAST(snapshot_json AS CHAR), '{}'), COALESCE(CAST(diff_json AS CHAR), '{}'),
		        change_reason, COALESCE(source_feedback_id, 0), is_active,
		        COALESCE(rolled_back_from_version, 0), created_at
		   FROM user_profile_snapshot
		  WHERE user_id = ? AND version = ?
		  LIMIT 1`,
		userID,
		targetVersion,
	))
	if err != nil {
		return model.UserProfileSnapshot{}, err
	}
	active, activeErr := s.ActiveUserProfileSnapshot(ctx, userID)
	baseVersion := 0
	diff := map[string]any{}
	if activeErr == nil {
		baseVersion = active.Version
		diffResult := ProfileDiff(active.Snapshot, target.Snapshot, reason)
		diff = map[string]any{
			"before":  diffResult.Before,
			"after":   diffResult.After,
			"changes": diffResult.Changes,
		}
	}
	if reason == "" {
		reason = "rollback"
	}
	return s.InsertUserProfileSnapshotVersion(ctx, model.UserProfileSnapshot{
		UserID:                userID,
		BaseVersion:           baseVersion,
		RunID:                 fmt.Sprintf("rollback-%d-%d", targetVersion, time.Now().UTC().UnixNano()),
		Summary:               target.Summary,
		Snapshot:              target.Snapshot,
		Diff:                  diff,
		ChangeReason:          reason,
		RolledBackFromVersion: targetVersion,
	})
}

func (s *Store) InsertMemoryCompensationTask(ctx context.Context, task model.MemoryCompensationTask) error {
	if task.TaskID == "" {
		value := strings.Join([]string{task.RunID, task.UserID, task.TaskType, task.TargetSystem}, "\x00")
		task.TaskID = fmt.Sprintf("%x", sha256.Sum256([]byte(value)))
	}
	if task.Status == "" {
		task.Status = "pending"
	}
	payload, _ := json.Marshal(task.Payload)
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	_, err = db.ExecContext(
		ctx,
		`INSERT INTO memory_compensation_tasks (
		 task_id, run_id, user_id, task_type, target_system, payload_json, status, last_error
		 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
		 ON DUPLICATE KEY UPDATE status = VALUES(status), last_error = VALUES(last_error), updated_at = CURRENT_TIMESTAMP`,
		task.TaskID,
		task.RunID,
		task.UserID,
		task.TaskType,
		task.TargetSystem,
		string(payload),
		task.Status,
		task.LastError,
	)
	return err
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
		`INSERT INTO mcp_call_logs (call_id, run_id, agent_name, server_name, tool_name, request_json, response_json, status, error_message, success, latency_ms)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		 ON DUPLICATE KEY UPDATE response_json = VALUES(response_json), status = VALUES(status),
		 error_message = VALUES(error_message), success = VALUES(success), latency_ms = VALUES(latency_ms)`,
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
		if log.CallID == "" {
			log.CallID = legacyMcpCallID(log, req)
		}
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
		if _, err := stmt.ExecContext(ctx, log.CallID, log.RunID, log.AgentName, log.ServerName, log.ToolName, req, resp, status, log.ErrorMessage, log.Success, log.LatencyMS); err != nil {
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
	lines := strings.Split(raw, "\n")
	cleaned := make([]string, 0, len(lines))
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if trimmed == "" || strings.HasPrefix(trimmed, "--") {
			continue
		}
		cleaned = append(cleaned, line)
	}
	parts := strings.Split(strings.Join(cleaned, "\n"), ";")
	// 预分配语句列表容量。
	statements := make([]string, 0, len(parts))
	for _, part := range parts {
		// 去除每段前后空白。
		statement := strings.TrimSpace(part)
		// 空语句或纯注释段跳过。
		if statement == "" {
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

func nullableString(value string) any {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	return value
}

func nullableInt(value int) any {
	if value == 0 {
		return nil
	}
	return value
}

func nullableUint64(value uint64) any {
	if value == 0 {
		return nil
	}
	return value
}

func nullableTime(value time.Time) any {
	if value.IsZero() {
		return nil
	}
	return value
}

func nullableTimeString(value string) any {
	value = strings.TrimSpace(value)
	if value == "" {
		return nil
	}
	for _, layout := range []string{time.RFC3339Nano, time.RFC3339, "2006-01-02 15:04:05"} {
		if parsed, err := time.Parse(layout, value); err == nil {
			return parsed
		}
	}
	return nil
}

func legacyMcpCallID(log model.McpCallLog, requestJSON string) string {
	value := strings.Join([]string{
		log.RunID,
		log.AgentName,
		log.ServerName,
		log.ToolName,
		requestJSON,
	}, "\x00")
	return fmt.Sprintf("%x", sha256.Sum256([]byte(value)))
}

func FeedbackIdempotencyKey(userID, postID, articleID, feedbackType string, rating int, text string) string {
	normalizedText := strings.Join(strings.Fields(strings.TrimSpace(text)), " ")
	value := strings.Join([]string{userID, postID, articleID, feedbackType, fmt.Sprintf("%d", rating), normalizedText}, "\x00")
	return fmt.Sprintf("%x", sha256.Sum256([]byte(value)))
}

func ProfileDiff(before map[string]string, after map[string]string, reason string) model.ProfileDiffResult {
	result := model.ProfileDiffResult{
		Before:  before,
		After:   after,
		Changes: []model.ProfileDiffChange{},
	}
	keys := map[string]struct{}{}
	for key := range before {
		keys[key] = struct{}{}
	}
	for key := range after {
		keys[key] = struct{}{}
	}
	ordered := make([]string, 0, len(keys))
	for key := range keys {
		ordered = append(ordered, key)
	}
	sort.Strings(ordered)
	for _, key := range ordered {
		if before[key] != after[key] {
			result.Changes = append(result.Changes, model.ProfileDiffChange{
				Path:   key,
				Before: before[key],
				After:  after[key],
				Reason: reason,
			})
		}
	}
	return result
}

type rowScanner interface {
	Scan(dest ...any) error
}

func scanFeedbackRecord(row rowScanner) (model.FeedbackRecord, error) {
	var record model.FeedbackRecord
	var rawFeedback string
	if err := row.Scan(
		&record.ID,
		&record.RunID,
		&record.PostUID,
		&record.ArticleUID,
		&record.UserID,
		&record.FeedbackType,
		&record.Rating,
		&record.Comment,
		&record.IdempotencyKey,
		&rawFeedback,
		&record.StructuredFeedbackJSON,
		&record.ProcessStatus,
		&record.ProfileVersion,
		&record.ErrorMessage,
		&record.CreatedAt,
	); err != nil {
		return model.FeedbackRecord{}, err
	}
	record.RawFeedback = map[string]any{}
	_ = json.Unmarshal([]byte(rawFeedback), &record.RawFeedback)
	return record, nil
}

func scanUserProfileSnapshot(row rowScanner) (model.UserProfileSnapshot, error) {
	var snapshot model.UserProfileSnapshot
	var rawSnapshot string
	var rawDiff string
	if err := row.Scan(
		&snapshot.ID,
		&snapshot.UserID,
		&snapshot.Version,
		&snapshot.BaseVersion,
		&snapshot.RunID,
		&snapshot.Summary,
		&rawSnapshot,
		&rawDiff,
		&snapshot.ChangeReason,
		&snapshot.SourceFeedbackID,
		&snapshot.IsActive,
		&snapshot.RolledBackFromVersion,
		&snapshot.CreatedAt,
	); err != nil {
		return model.UserProfileSnapshot{}, err
	}
	snapshot.Snapshot = map[string]string{}
	snapshot.Diff = map[string]any{}
	_ = json.Unmarshal([]byte(rawSnapshot), &snapshot.Snapshot)
	_ = json.Unmarshal([]byte(rawDiff), &snapshot.Diff)
	return snapshot, nil
}

func scanTaskRun(row rowScanner) (model.TaskRun, error) {
	var task model.TaskRun
	var inputPayload string
	var partialResult string
	var startedAt sql.NullTime
	var finishedAt sql.NullTime
	var nextRetryAt sql.NullTime
	if err := row.Scan(
		&task.RunID,
		&task.TaskType,
		&task.UserID,
		&task.Status,
		&task.CurrentStep,
		&task.IdempotencyKey,
		&task.InputSummary,
		&task.OutputSummary,
		&task.ErrorMessage,
		&inputPayload,
		&partialResult,
		&task.RetryCount,
		&task.MaxRetries,
		&task.TimeoutSeconds,
		&task.CancelRequested,
		&task.LockedBy,
		&startedAt,
		&finishedAt,
		&nextRetryAt,
		&task.CreatedAt,
		&task.UpdatedAt,
	); err != nil {
		return model.TaskRun{}, err
	}
	task.InputPayload = map[string]any{}
	task.PartialResult = map[string]any{}
	_ = json.Unmarshal([]byte(inputPayload), &task.InputPayload)
	_ = json.Unmarshal([]byte(partialResult), &task.PartialResult)
	if startedAt.Valid {
		task.StartedAt = &startedAt.Time
	}
	if finishedAt.Valid {
		task.FinishedAt = &finishedAt.Time
	}
	if nextRetryAt.Valid {
		task.NextRetryAt = &nextRetryAt.Time
	}
	return task, nil
}

func scanTaskStep(row rowScanner) (model.TaskStep, error) {
	var step model.TaskStep
	var startedAt sql.NullTime
	var completedAt sql.NullTime
	if err := row.Scan(
		&step.RunID,
		&step.StepName,
		&step.Status,
		&startedAt,
		&completedAt,
		&step.InputSummary,
		&step.OutputSummary,
		&step.ErrorMessage,
		&step.RetryCount,
		&step.CreatedAt,
		&step.UpdatedAt,
	); err != nil {
		return model.TaskStep{}, err
	}
	if startedAt.Valid {
		step.StartedAt = &startedAt.Time
	}
	if completedAt.Valid {
		step.CompletedAt = &completedAt.Time
	}
	return step, nil
}

func nonNilMap(value map[string]any) map[string]any {
	if value == nil {
		return map[string]any{}
	}
	return value
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
		{name: "call_id", ddl: "ALTER TABLE mcp_call_logs ADD COLUMN call_id VARCHAR(64) NOT NULL DEFAULT '' FIRST"},
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
	if _, err := db.ExecContext(ctx, "UPDATE mcp_call_logs SET call_id = SHA2(CONCAT('legacy:', id), 256) WHERE call_id = ''"); err != nil {
		return err
	}
	if _, err := db.ExecContext(ctx, "CREATE UNIQUE INDEX uk_mcp_call_id ON mcp_call_logs (call_id)"); err != nil && !strings.Contains(err.Error(), "Duplicate key name") {
		return err
	}
	if _, err := db.ExecContext(ctx, "CREATE UNIQUE INDEX uk_feedback_run_id ON feedback_logs (run_id)"); err != nil && !strings.Contains(err.Error(), "Duplicate key name") {
		return err
	}
	return nil
}
