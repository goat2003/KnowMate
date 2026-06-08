-- Production crawler schema migration for existing MySQL 8 databases.
-- This migration is idempotent and preserves all historical article rows.

DELIMITER $$

DROP PROCEDURE IF EXISTS add_column_if_missing$$
CREATE PROCEDURE add_column_if_missing(IN table_name_value VARCHAR(64), IN column_name_value VARCHAR(64), IN ddl_value TEXT)
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = table_name_value AND column_name = column_name_value
  ) THEN
    SET @ddl_statement = ddl_value;
    PREPARE ddl_prepared FROM @ddl_statement;
    EXECUTE ddl_prepared;
    DEALLOCATE PREPARE ddl_prepared;
  END IF;
END$$

DROP PROCEDURE IF EXISTS add_index_if_missing$$
CREATE PROCEDURE add_index_if_missing(IN table_name_value VARCHAR(64), IN index_name_value VARCHAR(64), IN ddl_value TEXT)
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = table_name_value AND index_name = index_name_value
  ) THEN
    SET @ddl_statement = ddl_value;
    PREPARE ddl_prepared FROM @ddl_statement;
    EXECUTE ddl_prepared;
    DEALLOCATE PREPARE ddl_prepared;
  END IF;
END$$

DELIMITER ;

CALL add_column_if_missing('articles', 'source_type', 'ALTER TABLE articles ADD COLUMN source_type VARCHAR(64) NOT NULL DEFAULT '''' AFTER source');
CALL add_column_if_missing('articles', 'normalized_url', 'ALTER TABLE articles ADD COLUMN normalized_url VARCHAR(2048) NULL AFTER url');
CALL add_column_if_missing('articles', 'url_hash', 'ALTER TABLE articles ADD COLUMN url_hash CHAR(64) NULL AFTER normalized_url');
CALL add_column_if_missing('articles', 'normalized_title', 'ALTER TABLE articles ADD COLUMN normalized_title VARCHAR(512) NOT NULL DEFAULT '''' AFTER title');
CALL add_column_if_missing('articles', 'title_hash', 'ALTER TABLE articles ADD COLUMN title_hash CHAR(64) NULL AFTER normalized_title');
CALL add_column_if_missing('articles', 'raw_content', 'ALTER TABLE articles ADD COLUMN raw_content MEDIUMTEXT NULL AFTER content');
CALL add_column_if_missing('articles', 'clean_content', 'ALTER TABLE articles ADD COLUMN clean_content MEDIUMTEXT NULL AFTER raw_content');
CALL add_column_if_missing('articles', 'content_hash', 'ALTER TABLE articles ADD COLUMN content_hash CHAR(64) NULL AFTER clean_content');
CALL add_column_if_missing('articles', 'language', 'ALTER TABLE articles ADD COLUMN language VARCHAR(16) NOT NULL DEFAULT ''unknown'' AFTER content_hash');
CALL add_column_if_missing('articles', 'fetch_status', 'ALTER TABLE articles ADD COLUMN fetch_status VARCHAR(32) NOT NULL DEFAULT ''success'' AFTER tags');
CALL add_column_if_missing('articles', 'fetch_error_type', 'ALTER TABLE articles ADD COLUMN fetch_error_type VARCHAR(64) NOT NULL DEFAULT '''' AFTER fetch_status');
CALL add_column_if_missing('articles', 'fetch_error', 'ALTER TABLE articles ADD COLUMN fetch_error TEXT NULL AFTER fetch_error_type');
CALL add_column_if_missing('articles', 'http_status', 'ALTER TABLE articles ADD COLUMN http_status INT NULL AFTER fetch_error');
CALL add_column_if_missing('articles', 'raw_payload', 'ALTER TABLE articles ADD COLUMN raw_payload JSON NULL AFTER http_status');
CALL add_column_if_missing('articles', 'fetched_at', 'ALTER TABLE articles ADD COLUMN fetched_at DATETIME NULL AFTER raw_json');

UPDATE articles
SET source_type = IF(source_type = '', 'feed', source_type),
    normalized_url = COALESCE(normalized_url, NULLIF(url, '')),
    normalized_title = IF(normalized_title = '', LOWER(TRIM(REGEXP_REPLACE(title, '[[:space:]]+', ' '))), normalized_title),
    raw_content = COALESCE(raw_content, content),
    clean_content = COALESCE(clean_content, content),
    fetched_at = COALESCE(fetched_at, created_at);

UPDATE articles current_row
LEFT JOIN articles prior_row
  ON prior_row.id < current_row.id
 AND prior_row.normalized_url = current_row.normalized_url
 AND prior_row.url_hash IS NOT NULL
SET current_row.url_hash = SHA2(current_row.normalized_url, 256)
WHERE current_row.url_hash IS NULL
  AND current_row.normalized_url IS NOT NULL
  AND prior_row.id IS NULL;

UPDATE articles current_row
LEFT JOIN articles prior_row
  ON prior_row.id < current_row.id
 AND prior_row.normalized_title = current_row.normalized_title
 AND prior_row.title_hash IS NOT NULL
SET current_row.title_hash = SHA2(current_row.normalized_title, 256)
WHERE current_row.title_hash IS NULL
  AND current_row.normalized_title <> ''
  AND prior_row.id IS NULL;

UPDATE articles current_row
LEFT JOIN articles prior_row
  ON prior_row.id < current_row.id
 AND prior_row.content_hash = SHA2(TRIM(current_row.clean_content), 256)
SET current_row.content_hash = SHA2(TRIM(current_row.clean_content), 256)
WHERE current_row.content_hash IS NULL
  AND current_row.clean_content IS NOT NULL
  AND TRIM(current_row.clean_content) <> ''
  AND prior_row.id IS NULL;

UPDATE articles current_row
JOIN (
  SELECT grouped.url_hash, grouped.keep_id
  FROM (
    SELECT url_hash, MIN(id) AS keep_id FROM articles
    WHERE url_hash IS NOT NULL GROUP BY url_hash HAVING COUNT(*) > 1
  ) grouped
) duplicate_rows ON duplicate_rows.url_hash = current_row.url_hash AND current_row.id <> duplicate_rows.keep_id
SET current_row.url_hash = NULL;

UPDATE articles current_row
JOIN (
  SELECT grouped.title_hash, grouped.keep_id
  FROM (
    SELECT title_hash, MIN(id) AS keep_id FROM articles
    WHERE title_hash IS NOT NULL GROUP BY title_hash HAVING COUNT(*) > 1
  ) grouped
) duplicate_rows ON duplicate_rows.title_hash = current_row.title_hash AND current_row.id <> duplicate_rows.keep_id
SET current_row.title_hash = NULL;

UPDATE articles current_row
JOIN (
  SELECT grouped.content_hash, grouped.keep_id
  FROM (
    SELECT content_hash, MIN(id) AS keep_id FROM articles
    WHERE content_hash IS NOT NULL GROUP BY content_hash HAVING COUNT(*) > 1
  ) grouped
) duplicate_rows ON duplicate_rows.content_hash = current_row.content_hash AND current_row.id <> duplicate_rows.keep_id
SET current_row.content_hash = NULL;

CALL add_index_if_missing('articles', 'uk_articles_url_hash', 'CREATE UNIQUE INDEX uk_articles_url_hash ON articles (url_hash)');
CALL add_index_if_missing('articles', 'uk_articles_title_hash', 'CREATE UNIQUE INDEX uk_articles_title_hash ON articles (title_hash)');
CALL add_index_if_missing('articles', 'uk_articles_content_hash', 'CREATE UNIQUE INDEX uk_articles_content_hash ON articles (content_hash)');
CALL add_index_if_missing('articles', 'idx_articles_normalized_url', 'CREATE INDEX idx_articles_normalized_url ON articles (normalized_url(768))');
CALL add_index_if_missing('articles', 'idx_articles_source_type_published', 'CREATE INDEX idx_articles_source_type_published ON articles (source_type, published_at)');
CALL add_index_if_missing('articles', 'idx_articles_language_created', 'CREATE INDEX idx_articles_language_created ON articles (language, created_at)');
CALL add_index_if_missing('articles', 'idx_articles_fetch_status_created', 'CREATE INDEX idx_articles_fetch_status_created ON articles (fetch_status, created_at)');

CREATE TABLE IF NOT EXISTS crawl_source_runs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  run_id VARCHAR(128) NOT NULL,
  source_name VARCHAR(128) NOT NULL,
  source_type VARCHAR(64) NOT NULL DEFAULT '',
  status VARCHAR(32) NOT NULL,
  error_type VARCHAR(64) NOT NULL DEFAULT '',
  error_message TEXT NULL,
  http_status INT NULL,
  items_found INT NOT NULL DEFAULT 0,
  items_saved INT NOT NULL DEFAULT 0,
  items_partial INT NOT NULL DEFAULT 0,
  items_failed INT NOT NULL DEFAULT 0,
  started_at DATETIME NOT NULL,
  finished_at DATETIME NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_crawl_source_run (run_id, source_name),
  KEY idx_crawl_source_status_created (status, created_at),
  KEY idx_crawl_source_name_created (source_name, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP PROCEDURE IF EXISTS add_column_if_missing;
DROP PROCEDURE IF EXISTS add_index_if_missing;
