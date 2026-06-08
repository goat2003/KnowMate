# 文件作用：
# 本脚本运行 KnowMate 项目的集成检查。
# 它先运行 Go 和 Python 单元测试，再调用 smoke_e2e.ps1 执行完整端到端冒烟测试。
#
# 在项目中的位置：
# 本脚本属于项目脚本层，供开发者在 Windows PowerShell 中执行。
#
# 主要内容：
# 1. go test ./...：检查 GoFrame 后端。
# 2. python -m unittest discover -s tests：检查 Python Agent。
# 3. smoke_e2e.ps1：启动依赖服务并跑端到端流程。
#
# 初学者阅读建议：
# 如果本机没有 Python、Go 或 Docker，本脚本会失败；这不是代码逻辑错误，而是运行环境缺失。
param(
  # Python 参数允许调用方指定 Python 可执行文件路径，例如 .venv\Scripts\python.exe。
  [string]$Python = "python",
  [switch]$KeepServices,
  [switch]$RealMemoryServices
)

# 遇到错误立即停止，避免后续步骤在失败状态下继续执行。
$ErrorActionPreference = "Stop"
# $PSScriptRoot 是当前脚本所在目录，.. 是项目根目录。
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

Write-Host "Running unit checks"
& (Join-Path $PSScriptRoot "check_proto_contract.ps1") -Python $Python
# 进入 GoFrame 后端目录，运行全部 Go 测试。
Push-Location (Join-Path $Root "goframe-backend")
go test ./internal/crawler -run 'TestCrawlerIntegration' -count=1 -v
if ($LASTEXITCODE -ne 0) { throw "offline crawler integration tests failed" }
go test ./...
if ($LASTEXITCODE -ne 0) { throw "Go tests failed" }
# Pop-Location 返回脚本原目录，避免后续路径错乱。
Pop-Location

if (Get-Command docker -ErrorAction SilentlyContinue) {
  docker info *> $null
  if ($LASTEXITCODE -eq 0) {
    $migrationContainer = "knowmate-crawler-migration-$PID"
    try {
      docker run -d --name $migrationContainer -e MYSQL_ROOT_PASSWORD=rootpass -e MYSQL_DATABASE=knowledge_post_agent mysql:8.0 | Out-Null
      if ($LASTEXITCODE -ne 0) { throw "failed to start temporary MySQL for crawler migration validation" }
      $ready = $false
      for ($attempt = 0; $attempt -lt 60; $attempt++) {
        docker exec -e MYSQL_PWD=rootpass $migrationContainer mysqladmin ping -h 127.0.0.1 -uroot --silent *> $null
        if ($LASTEXITCODE -eq 0) {
          $ready = $true
          break
        }
        Start-Sleep -Seconds 2
      }
      if (-not $ready) { throw "temporary MySQL did not become ready" }
      $legacySchema = @'
CREATE TABLE articles (
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
  UNIQUE KEY uk_articles_article_uid (article_uid)
);
INSERT INTO articles(article_uid, source, url, title, content) VALUES
  ('old-1', 'legacy', 'https://example.com/a', 'Same Title', 'Same historical content'),
  ('old-2', 'legacy', 'https://example.com/a', 'Same Title', 'Same historical content');
'@
      $legacySchema | docker exec -i -e MYSQL_PWD=rootpass $migrationContainer mysql -uroot knowledge_post_agent
      if ($LASTEXITCODE -ne 0) { throw "failed to create legacy crawler schema fixture" }
      $migration = Get-Content -Raw (Join-Path $Root "shared/sql/migrations/20260606_production_crawler.sql")
      $migration | docker exec -i -e MYSQL_PWD=rootpass $migrationContainer mysql -uroot knowledge_post_agent
      if ($LASTEXITCODE -ne 0) { throw "crawler migration first execution failed" }
      $migration | docker exec -i -e MYSQL_PWD=rootpass $migrationContainer mysql -uroot knowledge_post_agent
      if ($LASTEXITCODE -ne 0) { throw "crawler migration idempotency validation failed" }
      $backfill = docker exec -e MYSQL_PWD=rootpass $migrationContainer mysql -uroot knowledge_post_agent -N -e "SELECT COUNT(*), COUNT(url_hash), COUNT(title_hash), COUNT(content_hash), COUNT(clean_content) FROM articles;"
      if (($backfill -join "`n").Trim() -ne "2`t1`t1`t1`t2") { throw "crawler migration backfill or duplicate handling validation failed: $backfill" }
      $indexCount = docker exec -e MYSQL_PWD=rootpass $migrationContainer mysql -uroot knowledge_post_agent -N -e "SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='articles' AND index_name IN ('uk_articles_url_hash','uk_articles_title_hash','uk_articles_content_hash');"
      if ([int]$indexCount -ne 3) { throw "crawler migration unique indexes are incomplete" }
      $initSql = Get-Content -Raw (Join-Path $Root "shared/sql/init.sql")
      $initSql | docker exec -i -e MYSQL_PWD=rootpass $migrationContainer mysql -uroot knowledge_post_agent
      if ($LASTEXITCODE -ne 0) { throw "failed to create profile memory base schema" }
      $profileMigration = Get-Content -Raw (Join-Path $Root "shared/sql/migrations/20260608_feedback_memory_profile_versioning.sql")
      $profileMigration | docker exec -i -e MYSQL_PWD=rootpass $migrationContainer mysql -uroot knowledge_post_agent
      if ($LASTEXITCODE -ne 0) { throw "profile memory migration first execution failed" }
      $profileMigration | docker exec -i -e MYSQL_PWD=rootpass $migrationContainer mysql -uroot knowledge_post_agent
      if ($LASTEXITCODE -ne 0) { throw "profile memory migration idempotency validation failed" }
      $profileColumns = docker exec -e MYSQL_PWD=rootpass $migrationContainer mysql -uroot knowledge_post_agent -N -e "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='user_profile_snapshot' AND column_name IN ('version','diff_json','is_active');"
      if ([int]($profileColumns -join "`n").Trim() -lt 3) { throw "profile versioning migration did not create expected columns" }
      $feedbackColumns = docker exec -e MYSQL_PWD=rootpass $migrationContainer mysql -uroot knowledge_post_agent -N -e "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='feedback_logs' AND column_name IN ('idempotency_key','raw_feedback_json','structured_feedback_json','process_status','profile_version');"
      if ([int]($feedbackColumns -join "`n").Trim() -lt 5) { throw "feedback migration did not create expected columns" }
      $compensationTables = docker exec -e MYSQL_PWD=rootpass $migrationContainer mysql -uroot knowledge_post_agent -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='memory_compensation_tasks';"
      if ([int]($compensationTables -join "`n").Trim() -ne 1) { throw "memory compensation task table is missing" }
    } finally {
      docker rm -f -v $migrationContainer *> $null
    }
  }
}

# 进入 Python Agent 目录，运行 unittest 测试。
Push-Location (Join-Path $Root "python-agent")
& $Python -m unittest discover -s tests
Pop-Location

Push-Location (Join-Path $Root "mcp-servers")
& $Python -m unittest discover -s tests
Pop-Location

if ($RealMemoryServices) {
  if (-not $env:MINIO_ROOT_USER -or -not $env:MINIO_ROOT_PASSWORD -or -not $env:NEO4J_PASSWORD) {
    throw "Real memory-service integration requires MINIO_ROOT_USER, MINIO_ROOT_PASSWORD, and NEO4J_PASSWORD"
  }
  Push-Location $Root
  docker compose --profile production up -d --wait milvus-etcd milvus-minio milvus-standalone neo4j
  if ($LASTEXITCODE -ne 0) { throw "failed to start real Milvus and Neo4j integration dependencies" }
  Pop-Location

  Push-Location (Join-Path $Root "mcp-servers")
  try {
    $env:RUN_MEMORY_SERVICES_INTEGRATION = "1"
    & $Python -m unittest tests.test_real_services_integration.RealMemoryServicesIntegrationTest -v
    if ($LASTEXITCODE -ne 0) { throw "real memory-service integration tests failed" }
  } finally {
    Remove-Item Env:RUN_MEMORY_SERVICES_INTEGRATION -ErrorAction SilentlyContinue
    Pop-Location
  }
}

Write-Host "Running full E2E smoke"
# 调用完整端到端冒烟脚本，并把 Python 可执行文件参数继续传下去。
& (Join-Path $PSScriptRoot "smoke_e2e.ps1") -KeepServices:$KeepServices
