-- 文件作用：
-- 本文件负责初始化 KnowMate 项目的 MySQL 数据库和核心业务表。
--
-- 主要内容：
-- 1. articles：保存 GoFrame 抓取到的原始文章。
-- 2. posts：保存 Python Agent 生成后的推文/知识笔记结果。
-- 3. feedback_logs：保存用户对 post/article 的反馈。
-- 4. run_logs：保存文章任务和反馈任务的运行日志。
-- 5. user_profile_snapshot：保存用户画像快照，Python Agent 会读取并更新它。
-- 6. mcp_call_logs：保存 Python Agent 调用 MCP Tool 的日志。
--
-- 阅读建议：
-- 先看每张表的唯一键和索引，再对照 goframe-backend/internal/store/mysql.go 中的 Insert/List 方法。
-- 本次任务只添加注释，不改变表结构、索引、字段类型和默认值。

-- 创建项目数据库；utf8mb4 支持中文、emoji 和更完整的 Unicode 字符集。
CREATE DATABASE IF NOT EXISTS knowledge_post_agent
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

-- 切换到项目数据库，后续 CREATE TABLE 都在该库中执行。
USE knowledge_post_agent;

-- articles 表保存 RSS 抓取或手动输入的原始文章。
-- GoFrame 的 Store.InsertArticle 会写入该表，article_uid 用于去重。
CREATE TABLE IF NOT EXISTS articles (
  -- 自增主键，仅数据库内部使用。
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  -- article_uid 是业务唯一文章 id，会传给 Python Agent 作为 article_id。
  article_uid VARCHAR(128) NOT NULL,
  -- source 表示文章来源，例如 RSS 源名称。
  source VARCHAR(128) NOT NULL DEFAULT '',
  -- url 是原文链接。
  url VARCHAR(1024) NOT NULL DEFAULT '',
  -- title 是文章标题。
  title VARCHAR(512) NOT NULL,
  -- content 是文章正文，GoFrame 会映射到 protobuf Article.raw_text。
  content MEDIUMTEXT NULL,
  -- author 是文章作者。
  author VARCHAR(255) NOT NULL DEFAULT '',
  -- published_at 是发布时间。
  published_at DATETIME NULL,
  -- tags 保存标签数组 JSON。
  tags JSON NULL,
  -- raw_json 保存抓取到的完整 Article JSON，便于排查。
  raw_json JSON NULL,
  -- created_at 是创建时间。
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- updated_at 在行更新时自动刷新。
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  -- article_uid 唯一，配合 INSERT IGNORE 防止重复文章入库。
  UNIQUE KEY uk_articles_article_uid (article_uid),
  -- 按 source 和 created_at 查询时使用该索引。
  KEY idx_articles_source_created (source, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- posts 表保存 Python Agent RewriteAgent 生成后的 Markdown/推文文本。
-- GoFrame 的 Store.InsertPost 会写入或更新该表。
CREATE TABLE IF NOT EXISTS posts (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  -- post_uid 是生成结果唯一 id，由 run_id 和 article_id 拼出。
  post_uid VARCHAR(128) NOT NULL,
  -- article_uid 关联 articles.article_uid。
  article_uid VARCHAR(128) NOT NULL DEFAULT '',
  -- title 是生成内容标题。
  title VARCHAR(512) NOT NULL,
  -- markdown 是最终生成的正文。
  markdown MEDIUMTEXT NOT NULL,
  -- status 表示 draft、ready、check_failed 等状态。
  status VARCHAR(64) NOT NULL DEFAULT 'draft',
  -- tags 保存标签数组 JSON。
  tags JSON NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  -- post_uid 唯一，支持重跑时 ON DUPLICATE KEY UPDATE。
  UNIQUE KEY uk_posts_post_uid (post_uid),
  -- 按文章查询生成结果。
  KEY idx_posts_article_uid (article_uid),
  -- 按状态和创建时间查询列表。
  KEY idx_posts_status_created (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- feedback_logs 表保存用户反馈原始记录。
-- GoFrame 在调用 Python ProcessFeedback 之前先写该表，确保原始反馈可追溯。
CREATE TABLE IF NOT EXISTS feedback_logs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  -- run_id 关联本次反馈处理任务。
  run_id VARCHAR(128) NOT NULL DEFAULT '',
  -- post_uid 是被反馈的生成内容。
  post_uid VARCHAR(128) NOT NULL DEFAULT '',
  -- article_uid 是被反馈内容对应的原文章。
  article_uid VARCHAR(128) NOT NULL DEFAULT '',
  -- user_id 是反馈用户。
  user_id VARCHAR(128) NOT NULL DEFAULT '',
  -- feedback_type 表示 text、like、dislike 等反馈类型。
  feedback_type VARCHAR(64) NOT NULL DEFAULT '',
  -- rating 是用户评分。
  rating INT NULL,
  -- comment 是用户自然语言反馈。
  comment TEXT NULL,
  -- metadata 保存额外上下文。
  metadata JSON NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- 支持按用户和时间查看反馈。
  KEY idx_feedback_user_created (user_id, created_at),
  -- 支持按任务查询反馈。
  KEY idx_feedback_run_id (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- run_logs 表保存任务运行状态。
-- 文章处理和反馈处理都会写入 running、completed 或 failed 状态，metadata 中包含 steps。
CREATE TABLE IF NOT EXISTS run_logs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  -- run_id 是任务唯一 id。
  run_id VARCHAR(128) NOT NULL,
  -- status 表示 running、completed、failed 等。
  status VARCHAR(64) NOT NULL,
  -- input_count 是输入数量，例如候选文章数。
  input_count INT NOT NULL DEFAULT 0,
  -- output_count 是输出数量，例如保存 post 数。
  output_count INT NOT NULL DEFAULT 0,
  -- error_message 保存失败原因。
  error_message TEXT NULL,
  -- metadata 保存步骤、路径、计数等 JSON。
  metadata JSON NULL,
  -- started_at 是任务开始时间。
  started_at DATETIME NULL,
  -- finished_at 是任务完成或失败时间。
  finished_at DATETIME NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  -- run_id 唯一，Store.InsertRunLog 会用 ON DUPLICATE KEY UPDATE 更新同一任务。
  UNIQUE KEY uk_run_logs_run_id (run_id),
  -- 支持按状态和创建时间查询任务。
  KEY idx_run_logs_status_created (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- user_profile_snapshot 表保存用户画像快照。
-- GoFrame 读取最新快照传给 Python Agent；反馈流程完成后写入新快照。
CREATE TABLE IF NOT EXISTS user_profile_snapshot (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  -- user_id 是用户标识。
  user_id VARCHAR(128) NOT NULL,
  -- summary 保存本次快照摘要；当前反馈流程写入 sentiment。
  summary TEXT NULL,
  -- snapshot_json 保存完整画像快照，例如 interests、feedback_count、latest_feedback。
  snapshot_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- 支持按用户和时间读取最新画像。
  KEY idx_user_profile_user_created (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- mcp_call_logs 表保存 Python Agent 调用 MCP Tool 的日志。
-- BaseMcpClient 生成日志，GoFrame Store.InsertMcpCallLogs 批量写入。
CREATE TABLE IF NOT EXISTS mcp_call_logs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  -- run_id 关联文章任务或反馈任务。
  run_id VARCHAR(128) NOT NULL DEFAULT '',
  -- agent_name 表示发起工具调用的 Agent。
  agent_name VARCHAR(128) NOT NULL DEFAULT '',
  -- server_name 表示 MCP Server，例如 embedding-mcp。
  server_name VARCHAR(128) NOT NULL,
  -- tool_name 表示 MCP Tool，例如 embed_text。
  tool_name VARCHAR(128) NOT NULL,
  -- request_json 保存 JSON-RPC 请求体。
  request_json JSON NULL,
  -- response_json 保存 JSON-RPC 响应体。
  response_json JSON NULL,
  -- status 表示 success、failed、denied。
  status VARCHAR(32) NOT NULL DEFAULT 'success',
  -- error_message 保存失败或权限拒绝原因。
  error_message TEXT NULL,
  -- success 是布尔成功标记。
  success BOOLEAN NOT NULL DEFAULT TRUE,
  -- latency_ms 是调用耗时毫秒数。
  latency_ms BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- 支持按任务查询所有 MCP 调用。
  KEY idx_mcp_call_run_id (run_id),
  -- 支持按 Agent 和工具分析调用情况。
  KEY idx_mcp_call_agent_tool (agent_name, tool_name),
  -- 支持按状态筛选失败或拒绝日志。
  KEY idx_mcp_call_status (status),
  -- 支持按 MCP Server 和 Tool 查询。
  KEY idx_mcp_call_server_tool (server_name, tool_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
