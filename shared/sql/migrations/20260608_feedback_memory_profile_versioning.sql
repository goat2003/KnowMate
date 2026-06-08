-- Feedback memory profile versioning schema migration for existing MySQL 8 databases.
-- This migration is idempotent and preserves historical feedback/profile rows.

DELIMITER $$

DROP PROCEDURE IF EXISTS add_column_if_missing$$
CREATE PROCEDURE add_column_if_missing(
  IN table_name_value VARCHAR(128),
  IN column_name_value VARCHAR(128),
  IN ddl_value TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = table_name_value
      AND column_name = column_name_value
  ) THEN
    SET @ddl_statement = ddl_value;
    PREPARE ddl_prepared FROM @ddl_statement;
    EXECUTE ddl_prepared;
    DEALLOCATE PREPARE ddl_prepared;
  END IF;
END$$

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

CALL add_column_if_missing('posts', 'metadata', 'ALTER TABLE posts ADD COLUMN metadata JSON NULL AFTER tags');

CALL add_column_if_missing('feedback_logs', 'idempotency_key', 'ALTER TABLE feedback_logs ADD COLUMN idempotency_key VARCHAR(128) NOT NULL DEFAULT '''' AFTER metadata');
CALL add_column_if_missing('feedback_logs', 'raw_feedback_json', 'ALTER TABLE feedback_logs ADD COLUMN raw_feedback_json JSON NULL AFTER idempotency_key');
CALL add_column_if_missing('feedback_logs', 'structured_feedback_json', 'ALTER TABLE feedback_logs ADD COLUMN structured_feedback_json JSON NULL AFTER raw_feedback_json');
CALL add_column_if_missing('feedback_logs', 'process_status', 'ALTER TABLE feedback_logs ADD COLUMN process_status VARCHAR(32) NOT NULL DEFAULT ''received'' AFTER structured_feedback_json');
CALL add_column_if_missing('feedback_logs', 'profile_version', 'ALTER TABLE feedback_logs ADD COLUMN profile_version INT NULL AFTER process_status');
CALL add_column_if_missing('feedback_logs', 'error_message', 'ALTER TABLE feedback_logs ADD COLUMN error_message TEXT NULL AFTER profile_version');
CALL add_column_if_missing('feedback_logs', 'processed_at', 'ALTER TABLE feedback_logs ADD COLUMN processed_at DATETIME NULL AFTER error_message');

UPDATE feedback_logs
SET idempotency_key = run_id
WHERE idempotency_key = '';

CALL add_index_if_missing('feedback_logs', 'uk_feedback_idempotency', 'CREATE UNIQUE INDEX uk_feedback_idempotency ON feedback_logs (user_id, idempotency_key)');
CALL add_index_if_missing('feedback_logs', 'idx_feedback_status_created', 'CREATE INDEX idx_feedback_status_created ON feedback_logs (process_status, created_at)');
CALL add_index_if_missing('feedback_logs', 'idx_feedback_user_profile_version', 'CREATE INDEX idx_feedback_user_profile_version ON feedback_logs (user_id, profile_version)');

CALL add_column_if_missing('user_profile_snapshot', 'version', 'ALTER TABLE user_profile_snapshot ADD COLUMN version INT NOT NULL DEFAULT 1 AFTER snapshot_json');
CALL add_column_if_missing('user_profile_snapshot', 'base_version', 'ALTER TABLE user_profile_snapshot ADD COLUMN base_version INT NULL AFTER version');
CALL add_column_if_missing('user_profile_snapshot', 'run_id', 'ALTER TABLE user_profile_snapshot ADD COLUMN run_id VARCHAR(128) NOT NULL DEFAULT '''' AFTER base_version');
CALL add_column_if_missing('user_profile_snapshot', 'diff_json', 'ALTER TABLE user_profile_snapshot ADD COLUMN diff_json JSON NULL AFTER run_id');
CALL add_column_if_missing('user_profile_snapshot', 'change_reason', 'ALTER TABLE user_profile_snapshot ADD COLUMN change_reason VARCHAR(128) NOT NULL DEFAULT '''' AFTER diff_json');
CALL add_column_if_missing('user_profile_snapshot', 'source_feedback_id', 'ALTER TABLE user_profile_snapshot ADD COLUMN source_feedback_id BIGINT UNSIGNED NULL AFTER change_reason');
CALL add_column_if_missing('user_profile_snapshot', 'is_active', 'ALTER TABLE user_profile_snapshot ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT FALSE AFTER source_feedback_id');
CALL add_column_if_missing('user_profile_snapshot', 'rolled_back_from_version', 'ALTER TABLE user_profile_snapshot ADD COLUMN rolled_back_from_version INT NULL AFTER is_active');

UPDATE user_profile_snapshot s
JOIN (
  SELECT user_id, MAX(id) AS max_id
  FROM user_profile_snapshot
  GROUP BY user_id
) latest ON latest.user_id = s.user_id
SET s.version = 1,
    s.is_active = (s.id = latest.max_id)
WHERE s.version = 1;

CALL add_index_if_missing('user_profile_snapshot', 'uk_profile_user_version', 'CREATE UNIQUE INDEX uk_profile_user_version ON user_profile_snapshot (user_id, version)');
CALL add_index_if_missing('user_profile_snapshot', 'idx_profile_user_active', 'CREATE INDEX idx_profile_user_active ON user_profile_snapshot (user_id, is_active)');
CALL add_index_if_missing('user_profile_snapshot', 'idx_profile_run_id', 'CREATE INDEX idx_profile_run_id ON user_profile_snapshot (run_id)');

CREATE TABLE IF NOT EXISTS memory_compensation_tasks (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  task_id VARCHAR(128) NOT NULL,
  run_id VARCHAR(128) NOT NULL,
  user_id VARCHAR(128) NOT NULL,
  task_type VARCHAR(64) NOT NULL,
  target_system VARCHAR(32) NOT NULL,
  payload_json JSON NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  attempt_count INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 5,
  next_retry_at DATETIME NULL,
  last_error TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_memory_compensation_task_id (task_id),
  KEY idx_memory_compensation_status_retry (status, next_retry_at),
  KEY idx_memory_compensation_run (run_id),
  KEY idx_memory_compensation_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP PROCEDURE IF EXISTS add_column_if_missing;
DROP PROCEDURE IF EXISTS add_index_if_missing;
