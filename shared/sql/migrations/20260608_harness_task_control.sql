-- Harness task execution control schema for existing MySQL 8 databases.
-- This migration is idempotent and adds durable run/step state for retry, cancellation, recovery, and partial results.

DELIMITER $$

DROP PROCEDURE IF EXISTS add_index_if_missing$$
CREATE PROCEDURE add_index_if_missing(
  IN table_name_value VARCHAR(128),
  IN index_name_value VARCHAR(128),
  IN ddl_value TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = table_name_value
      AND index_name = index_name_value
  ) THEN
    SET @ddl_statement = ddl_value;
    PREPARE ddl_prepared FROM @ddl_statement;
    EXECUTE ddl_prepared;
    DEALLOCATE PREPARE ddl_prepared;
  END IF;
END$$

DELIMITER ;

CREATE TABLE IF NOT EXISTS task_runs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  run_id VARCHAR(128) NOT NULL,
  task_type VARCHAR(64) NOT NULL,
  user_id VARCHAR(128) NOT NULL DEFAULT '',
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  current_step VARCHAR(128) NOT NULL DEFAULT '',
  idempotency_key VARCHAR(128) NOT NULL DEFAULT '',
  input_summary TEXT NULL,
  output_summary TEXT NULL,
  error_message TEXT NULL,
  input_payload_json JSON NULL,
  partial_result_json JSON NULL,
  retry_count INT NOT NULL DEFAULT 0,
  max_retries INT NOT NULL DEFAULT 3,
  timeout_seconds INT NOT NULL DEFAULT 120,
  cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
  locked_by VARCHAR(128) NOT NULL DEFAULT '',
  started_at DATETIME NULL,
  finished_at DATETIME NULL,
  next_retry_at DATETIME NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_task_runs_run_id (run_id),
  KEY idx_task_runs_idempotency (task_type, user_id, idempotency_key),
  KEY idx_task_runs_status_created (status, created_at),
  KEY idx_task_runs_user_status (user_id, status),
  KEY idx_task_runs_type_status (task_type, status),
  KEY idx_task_runs_retry (status, next_retry_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS task_steps (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  run_id VARCHAR(128) NOT NULL,
  step_name VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  started_at DATETIME NULL,
  completed_at DATETIME NULL,
  input_summary TEXT NULL,
  output_summary TEXT NULL,
  error_message TEXT NULL,
  retry_count INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_task_steps_run_step (run_id, step_name),
  KEY idx_task_steps_run_status (run_id, status),
  KEY idx_task_steps_status_updated (status, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO task_runs (
  run_id, task_type, user_id, status, input_summary, output_summary,
  error_message, partial_result_json, started_at, finished_at, created_at, updated_at
)
SELECT
  run_id,
  CASE
    WHEN run_id LIKE 'feedback-%' THEN 'feedback'
    WHEN run_id LIKE 'profile-rebuild-%' THEN 'profile_rebuild'
    ELSE 'articles'
  END AS task_type,
  '',
  CASE
    WHEN status IN ('pending', 'running', 'completed', 'failed', 'partially_completed', 'cancelled') THEN status
    ELSE 'failed'
  END AS status,
  CONCAT('legacy run_log input_count=', input_count),
  CONCAT('legacy run_log output_count=', output_count),
  error_message,
  COALESCE(metadata, JSON_OBJECT()),
  started_at,
  finished_at,
  created_at,
  updated_at
FROM run_logs
WHERE run_id IS NOT NULL AND run_id <> '';

CALL add_index_if_missing('task_runs', 'uk_task_runs_run_id', 'CREATE UNIQUE INDEX uk_task_runs_run_id ON task_runs (run_id)');
CALL add_index_if_missing('task_runs', 'idx_task_runs_idempotency', 'CREATE INDEX idx_task_runs_idempotency ON task_runs (task_type, user_id, idempotency_key)');
CALL add_index_if_missing('task_runs', 'idx_task_runs_status_created', 'CREATE INDEX idx_task_runs_status_created ON task_runs (status, created_at)');
CALL add_index_if_missing('task_runs', 'idx_task_runs_user_status', 'CREATE INDEX idx_task_runs_user_status ON task_runs (user_id, status)');
CALL add_index_if_missing('task_runs', 'idx_task_runs_type_status', 'CREATE INDEX idx_task_runs_type_status ON task_runs (task_type, status)');
CALL add_index_if_missing('task_runs', 'idx_task_runs_retry', 'CREATE INDEX idx_task_runs_retry ON task_runs (status, next_retry_at)');
CALL add_index_if_missing('task_steps', 'uk_task_steps_run_step', 'CREATE UNIQUE INDEX uk_task_steps_run_step ON task_steps (run_id, step_name)');
CALL add_index_if_missing('task_steps', 'idx_task_steps_run_status', 'CREATE INDEX idx_task_steps_run_status ON task_steps (run_id, status)');
CALL add_index_if_missing('task_steps', 'idx_task_steps_status_updated', 'CREATE INDEX idx_task_steps_status_updated ON task_steps (status, updated_at)');

DROP PROCEDURE IF EXISTS add_index_if_missing;
