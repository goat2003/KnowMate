package store

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"knowledge-post-agent/goframe-backend/internal/model"
)

func TestSplitSQLStatementsKeepsStatementAfterComment(t *testing.T) {
	raw := `
-- table comment
CREATE TABLE first_table (id BIGINT);

-- another comment
CREATE TABLE second_table (id BIGINT);
`

	statements := splitSQLStatements(raw)
	if len(statements) != 2 {
		t.Fatalf("expected 2 statements, got %d: %#v", len(statements), statements)
	}
}

func TestLegacyMcpCallIDIsStableAndRequestSensitive(t *testing.T) {
	log := model.McpCallLog{
		RunID:      "run-1",
		AgentName:  "filter",
		ServerName: "embedding-mcp",
		ToolName:   "embed_text",
	}

	first := legacyMcpCallID(log, `{"text":"one"}`)
	second := legacyMcpCallID(log, `{"text":"one"}`)
	different := legacyMcpCallID(log, `{"text":"two"}`)

	if first != second {
		t.Fatalf("expected stable IDs, got %q and %q", first, second)
	}
	if first == different {
		t.Fatalf("expected request-sensitive IDs, both were %q", first)
	}
	if len(first) != 64 {
		t.Fatalf("expected SHA-256 hex ID, got length %d", len(first))
	}
}

func TestFeedbackIdempotencyKeyIsStableAndContentSensitive(t *testing.T) {
	first := FeedbackIdempotencyKey("u1", "p1", "a1", "text", 5, "  有用  ")
	second := FeedbackIdempotencyKey("u1", "p1", "a1", "text", 5, "有用")
	different := FeedbackIdempotencyKey("u1", "p1", "a1", "text", 1, "有用")

	if first != second {
		t.Fatalf("expected normalized feedback text to produce same key")
	}
	if first == different {
		t.Fatalf("expected rating to affect key")
	}
	if len(first) != 64 {
		t.Fatalf("expected SHA-256 hex key, got %d", len(first))
	}
}

func TestProfileDiffDetectsChangedFields(t *testing.T) {
	diff := ProfileDiff(
		map[string]string{"topics": "{\"AI\":0.7}", "feedback_count": "1"},
		map[string]string{"topics": "{\"AI\":0.8}", "feedback_count": "2"},
		"feedback",
	)
	if len(diff.Changes) == 0 {
		t.Fatal("expected profile diff changes")
	}
}

func TestNullableArticleFields(t *testing.T) {
	if nullableString("  ") != nil {
		t.Fatal("expected blank string to map to nil")
	}
	if nullableInt(0) != nil {
		t.Fatal("expected zero integer to map to nil")
	}
	if nullableTime(time.Time{}) != nil {
		t.Fatal("expected zero time to map to nil")
	}

	value := nullableTimeString("2026-06-06T12:30:00Z")
	parsed, ok := value.(time.Time)
	if !ok || !parsed.Equal(time.Date(2026, 6, 6, 12, 30, 0, 0, time.UTC)) {
		t.Fatalf("unexpected parsed time: %#v", value)
	}
	if nullableTimeString("not-a-time") != nil {
		t.Fatal("expected invalid time to map to nil")
	}
}

func TestCrawlerSchemaContracts(t *testing.T) {
	root := filepath.Join("..", "..", "..")
	for _, relativePath := range []string{
		filepath.Join("shared", "sql", "init.sql"),
		filepath.Join("shared", "sql", "migrations", "20260606_production_crawler.sql"),
	} {
		data, err := os.ReadFile(filepath.Join(root, relativePath))
		if err != nil {
			t.Fatalf("read %s: %v", relativePath, err)
		}
		sql := strings.ToLower(string(data))
		for _, required := range []string{
			"normalized_url",
			"url_hash",
			"title_hash",
			"raw_content",
			"clean_content",
			"content_hash",
			"language",
			"fetch_status",
			"fetch_error",
			"crawl_source_runs",
			"idx_articles_fetch_status_created",
			"idx_articles_source_type_published",
		} {
			if !strings.Contains(sql, required) {
				t.Fatalf("%s is missing %q", relativePath, required)
			}
		}
	}

	migration, err := os.ReadFile(filepath.Join(root, "shared", "sql", "migrations", "20260606_production_crawler.sql"))
	if err != nil {
		t.Fatal(err)
	}
	for _, required := range []string{"add_column_if_missing", "add_index_if_missing", "information_schema.columns", "information_schema.statistics"} {
		if !strings.Contains(strings.ToLower(string(migration)), required) {
			t.Fatalf("migration is missing idempotency contract %q", required)
		}
	}
}

func TestFeedbackMemoryProfileSchemaContracts(t *testing.T) {
	root := filepath.Join("..", "..", "..")
	for _, relativePath := range []string{
		filepath.Join("shared", "sql", "init.sql"),
		filepath.Join("shared", "sql", "migrations", "20260608_feedback_memory_profile_versioning.sql"),
	} {
		data, err := os.ReadFile(filepath.Join(root, relativePath))
		if err != nil {
			t.Fatalf("read %s: %v", relativePath, err)
		}
		sql := strings.ToLower(string(data))
		for _, required := range []string{
			"idempotency_key",
			"raw_feedback_json",
			"structured_feedback_json",
			"process_status",
			"profile_version",
			"diff_json",
			"is_active",
			"rolled_back_from_version",
			"memory_compensation_tasks",
			"posts",
			"metadata",
			"uk_feedback_idempotency",
			"uk_profile_user_version",
		} {
			if !strings.Contains(sql, required) {
				t.Fatalf("%s is missing %q", relativePath, required)
			}
		}
	}

	migration, err := os.ReadFile(filepath.Join(root, "shared", "sql", "migrations", "20260608_feedback_memory_profile_versioning.sql"))
	if err != nil {
		t.Fatal(err)
	}
	for _, required := range []string{"add_column_if_missing", "add_index_if_missing", "information_schema.columns", "information_schema.statistics"} {
		if !strings.Contains(strings.ToLower(string(migration)), required) {
			t.Fatalf("migration is missing idempotency contract %q", required)
		}
	}
}

func TestHarnessTaskControlSchemaContracts(t *testing.T) {
	root := filepath.Join("..", "..", "..")
	for _, relativePath := range []string{
		filepath.Join("shared", "sql", "init.sql"),
		filepath.Join("shared", "sql", "migrations", "20260608_harness_task_control.sql"),
	} {
		data, err := os.ReadFile(filepath.Join(root, relativePath))
		if err != nil {
			t.Fatalf("read %s: %v", relativePath, err)
		}
		sql := strings.ToLower(string(data))
		for _, required := range []string{
			"task_runs",
			"task_steps",
			"pending",
			"running",
			"completed",
			"failed",
			"partially_completed",
			"cancelled",
			"input_summary",
			"output_summary",
			"error_message",
			"retry_count",
			"cancel_requested",
			"locked_by",
			"partial_result_json",
			"idx_task_runs_idempotency",
			"uk_task_steps_run_step",
		} {
			if !strings.Contains(sql, required) {
				t.Fatalf("%s is missing %q", relativePath, required)
			}
		}
	}

	migration, err := os.ReadFile(filepath.Join(root, "shared", "sql", "migrations", "20260608_harness_task_control.sql"))
	if err != nil {
		t.Fatal(err)
	}
	for _, required := range []string{"add_index_if_missing", "information_schema.statistics", "insert ignore into task_runs"} {
		if !strings.Contains(strings.ToLower(string(migration)), required) {
			t.Fatalf("migration is missing idempotency/backfill contract %q", required)
		}
	}
}
