package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"os"
	"strings"
	"time"

	"knowledge-post-agent/goframe-backend/internal/model"

	_ "github.com/go-sql-driver/mysql"
)

type Store struct {
	dsn string
	db  *sql.DB
}

func New(dsn string) *Store {
	return &Store{dsn: dsn}
}

func (s *Store) Ping(ctx context.Context) error {
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	return db.PingContext(ctx)
}

func (s *Store) InitSchema(ctx context.Context, path string) error {
	if path == "" {
		return nil
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	for _, statement := range splitSQLStatements(string(data)) {
		if _, err := db.ExecContext(ctx, statement); err != nil {
			return err
		}
	}
	return s.ensureMcpCallLogColumns(ctx, db)
}

func (s *Store) InsertArticle(ctx context.Context, article model.Article) (bool, error) {
	if article.ID == "" {
		article.ID = article.URL
	}
	if article.ID == "" {
		article.ID = "manual-" + time.Now().UTC().Format("20060102150405")
	}
	tags, _ := json.Marshal(article.Tags)
	raw, _ := json.Marshal(article)
	db, err := s.open(ctx)
	if err != nil {
		return false, err
	}
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
	rows, _ := result.RowsAffected()
	return rows > 0, nil
}

func (s *Store) InsertPost(ctx context.Context, post model.Post) error {
	if post.PostUID == "" {
		post.PostUID = "post-" + time.Now().UTC().Format("20060102150405")
	}
	if post.Status == "" {
		post.Status = "draft"
	}
	tags, _ := json.Marshal(post.Tags)
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
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

func (s *Store) ListPosts(ctx context.Context, limit int) ([]model.Post, error) {
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	db, err := s.open(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := db.QueryContext(
		ctx,
		`SELECT post_uid, article_uid, title, markdown, status, COALESCE(CAST(tags AS CHAR), '[]'), created_at
		 FROM posts ORDER BY id DESC LIMIT ?`,
		limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	posts := make([]model.Post, 0)
	for rows.Next() {
		var post model.Post
		var tagsRaw string
		if err := rows.Scan(&post.PostUID, &post.ArticleUID, &post.Title, &post.Markdown, &post.Status, &tagsRaw, &post.CreatedAt); err != nil {
			return nil, err
		}
		_ = json.Unmarshal([]byte(tagsRaw), &post.Tags)
		posts = append(posts, post)
	}
	return posts, rows.Err()
}

func (s *Store) InsertFeedbackLog(ctx context.Context, feedback model.FeedbackLog) error {
	metadata, _ := json.Marshal(feedback.Metadata)
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
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

func (s *Store) InsertRunLog(ctx context.Context, run model.RunLog) error {
	if run.RunID == "" {
		run.RunID = "run-" + time.Now().UTC().Format("20060102150405")
	}
	if run.Status == "" {
		run.Status = "started"
	}
	metadata, _ := json.Marshal(run.Metadata)
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
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

func (s *Store) ListRunLogs(ctx context.Context, limit int) ([]model.RunLog, error) {
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	db, err := s.open(ctx)
	if err != nil {
		return nil, err
	}
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

	logs := make([]model.RunLog, 0)
	for rows.Next() {
		var run model.RunLog
		var metadataRaw string
		if err := rows.Scan(&run.RunID, &run.Status, &run.InputCount, &run.OutputCount, &run.ErrorMessage, &metadataRaw, &run.CreatedAt); err != nil {
			return nil, err
		}
		_ = json.Unmarshal([]byte(metadataRaw), &run.Metadata)
		logs = append(logs, run)
	}
	return logs, rows.Err()
}

func (s *Store) InsertUserProfileSnapshot(ctx context.Context, userID string, snapshot map[string]string, summary string) error {
	raw, _ := json.Marshal(snapshot)
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
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

func (s *Store) LatestUserProfileSnapshot(ctx context.Context, userID string) (map[string]string, error) {
	db, err := s.open(ctx)
	if err != nil {
		return nil, err
	}
	var raw string
	err = db.QueryRowContext(
		ctx,
		`SELECT COALESCE(CAST(snapshot_json AS CHAR), '{}')
		 FROM user_profile_snapshot WHERE user_id = ? ORDER BY id DESC LIMIT 1`,
		userID,
	).Scan(&raw)
	if errors.Is(err, sql.ErrNoRows) {
		return map[string]string{}, nil
	}
	if err != nil {
		return nil, err
	}
	snapshot := map[string]string{}
	if err := json.Unmarshal([]byte(raw), &snapshot); err != nil {
		return nil, err
	}
	return snapshot, nil
}

func (s *Store) InsertMcpCallLogs(ctx context.Context, logs []model.McpCallLog) error {
	if len(logs) == 0 {
		return nil
	}
	db, err := s.open(ctx)
	if err != nil {
		return err
	}
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	stmt, err := tx.PrepareContext(
		ctx,
		`INSERT INTO mcp_call_logs (run_id, agent_name, server_name, tool_name, request_json, response_json, status, error_message, success, latency_ms)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
	)
	if err != nil {
		_ = tx.Rollback()
		return err
	}
	defer stmt.Close()

	for _, log := range logs {
		req := normalizeJSON(log.RequestJSON)
		resp := normalizeJSON(log.ResponseJSON)
		status := log.Status
		if status == "" {
			if log.Success {
				status = "success"
			} else {
				status = "failed"
			}
		}
		if _, err := stmt.ExecContext(ctx, log.RunID, log.AgentName, log.ServerName, log.ToolName, req, resp, status, log.ErrorMessage, log.Success, log.LatencyMS); err != nil {
			_ = tx.Rollback()
			return err
		}
	}
	return tx.Commit()
}

func (s *Store) open(ctx context.Context) (*sql.DB, error) {
	if s.dsn == "" {
		return nil, errors.New("mysql dsn is empty")
	}
	if s.db != nil {
		return s.db, nil
	}
	db, err := sql.Open("mysql", s.dsn)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(5)
	db.SetConnMaxLifetime(30 * time.Minute)
	pingCtx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	if err := db.PingContext(pingCtx); err != nil {
		_ = db.Close()
		return nil, err
	}
	s.db = db
	return s.db, nil
}

func splitSQLStatements(raw string) []string {
	parts := strings.Split(raw, ";")
	statements := make([]string, 0, len(parts))
	for _, part := range parts {
		statement := strings.TrimSpace(part)
		if statement == "" || strings.HasPrefix(statement, "--") {
			continue
		}
		statements = append(statements, statement)
	}
	return statements
}

func normalizeJSON(raw string) string {
	if strings.TrimSpace(raw) == "" {
		return "{}"
	}
	var value any
	if err := json.Unmarshal([]byte(raw), &value); err != nil {
		encoded, _ := json.Marshal(map[string]string{"raw": raw})
		return string(encoded)
	}
	encoded, _ := json.Marshal(value)
	return string(encoded)
}

func (s *Store) ensureMcpCallLogColumns(ctx context.Context, db *sql.DB) error {
	columns := []struct {
		name string
		ddl  string
	}{
		{name: "agent_name", ddl: "ALTER TABLE mcp_call_logs ADD COLUMN agent_name VARCHAR(128) NOT NULL DEFAULT '' AFTER run_id"},
		{name: "status", ddl: "ALTER TABLE mcp_call_logs ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'success' AFTER response_json"},
		{name: "error_message", ddl: "ALTER TABLE mcp_call_logs ADD COLUMN error_message TEXT NULL AFTER status"},
	}
	for _, column := range columns {
		var count int
		err := db.QueryRowContext(
			ctx,
			`SELECT COUNT(*) FROM information_schema.columns
			 WHERE table_schema = DATABASE() AND table_name = 'mcp_call_logs' AND column_name = ?`,
			column.name,
		).Scan(&count)
		if err != nil {
			return err
		}
		if count == 0 {
			if _, err := db.ExecContext(ctx, column.ddl); err != nil {
				return err
			}
		}
	}
	return nil
}
