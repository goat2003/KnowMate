CREATE DATABASE IF NOT EXISTS knowledge_post_agent
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE knowledge_post_agent;

CREATE TABLE IF NOT EXISTS articles (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  article_uid VARCHAR(128) NOT NULL,
  source VARCHAR(128) NOT NULL DEFAULT '',
  url VARCHAR(1024) NOT NULL DEFAULT '',
  title VARCHAR(512) NOT NULL,
  content MEDIUMTEXT NULL,
  author VARCHAR(255) NOT NULL DEFAULT '',
  published_at DATETIME NULL,
  tags JSON NULL,
  raw_json JSON NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_articles_article_uid (article_uid),
  KEY idx_articles_source_created (source, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS posts (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  post_uid VARCHAR(128) NOT NULL,
  article_uid VARCHAR(128) NOT NULL DEFAULT '',
  title VARCHAR(512) NOT NULL,
  markdown MEDIUMTEXT NOT NULL,
  status VARCHAR(64) NOT NULL DEFAULT 'draft',
  tags JSON NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_posts_post_uid (post_uid),
  KEY idx_posts_article_uid (article_uid),
  KEY idx_posts_status_created (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS feedback_logs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  run_id VARCHAR(128) NOT NULL DEFAULT '',
  post_uid VARCHAR(128) NOT NULL DEFAULT '',
  article_uid VARCHAR(128) NOT NULL DEFAULT '',
  user_id VARCHAR(128) NOT NULL DEFAULT '',
  feedback_type VARCHAR(64) NOT NULL DEFAULT '',
  rating INT NULL,
  comment TEXT NULL,
  metadata JSON NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_feedback_user_created (user_id, created_at),
  KEY idx_feedback_run_id (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS run_logs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  run_id VARCHAR(128) NOT NULL,
  status VARCHAR(64) NOT NULL,
  input_count INT NOT NULL DEFAULT 0,
  output_count INT NOT NULL DEFAULT 0,
  error_message TEXT NULL,
  metadata JSON NULL,
  started_at DATETIME NULL,
  finished_at DATETIME NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_run_logs_run_id (run_id),
  KEY idx_run_logs_status_created (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_profile_snapshot (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id VARCHAR(128) NOT NULL,
  summary TEXT NULL,
  snapshot_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_user_profile_user_created (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mcp_call_logs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  run_id VARCHAR(128) NOT NULL DEFAULT '',
  agent_name VARCHAR(128) NOT NULL DEFAULT '',
  server_name VARCHAR(128) NOT NULL,
  tool_name VARCHAR(128) NOT NULL,
  request_json JSON NULL,
  response_json JSON NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'success',
  error_message TEXT NULL,
  success BOOLEAN NOT NULL DEFAULT TRUE,
  latency_ms BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_mcp_call_run_id (run_id),
  KEY idx_mcp_call_agent_tool (agent_name, tool_name),
  KEY idx_mcp_call_status (status),
  KEY idx_mcp_call_server_tool (server_name, tool_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
