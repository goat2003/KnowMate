param(
  [string]$MySqlHost = "127.0.0.1",
  [int]$MySqlPort = 3306,
  [string]$Database = "knowledge_post_agent_ci",
  [string]$User = "root",
  [string]$Password = $env:MYSQL_PWD,
  [string]$MySql = "mysql",
  [switch]$RequireDatabase
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$InitSql = Join-Path $Root "shared\sql\init.sql"
$MigrationDir = Join-Path $Root "shared\sql\migrations"

function Invoke-Checked {
  param([scriptblock]$Command, [string]$Message)
  & $Command
  if ($LASTEXITCODE -ne 0) { throw $Message }
}

if (-not (Test-Path -LiteralPath $InitSql)) {
  throw "shared/sql/init.sql is missing"
}

$migrations = Get-ChildItem -LiteralPath $MigrationDir -Filter "*.sql" -File | Sort-Object Name
if ($migrations.Count -eq 0) {
  throw "no SQL migrations found under shared/sql/migrations"
}

$initText = Get-Content -Raw -LiteralPath $InitSql
foreach ($table in @("articles", "crawl_source_runs", "posts", "feedback_logs", "run_logs", "task_runs", "task_steps", "user_profile_snapshot", "memory_compensation_tasks", "mcp_call_logs")) {
  if ($initText -notmatch "CREATE TABLE IF NOT EXISTS\s+$table\b") {
    throw "init.sql does not create required table: $table"
  }
}

foreach ($migration in $migrations) {
  $text = Get-Content -Raw -LiteralPath $migration.FullName
  if ($text -notmatch "(?is)IF\s+NOT\s+EXISTS|add_column_if_missing|add_index_if_missing|INSERT\s+IGNORE|ON\s+DUPLICATE\s+KEY|DROP\s+PROCEDURE\s+IF\s+EXISTS") {
    throw "migration $($migration.Name) does not look idempotent"
  }
}

Write-Host "migration static validation ok: $($migrations.Count) files"

if (-not $RequireDatabase) {
  Write-Host "database migration execution skipped; pass -RequireDatabase to run against MySQL"
  exit 0
}

if (-not (Get-Command $MySql -ErrorAction SilentlyContinue)) {
  throw "mysql client not found: $MySql"
}
if (-not $Password) {
  throw "MYSQL password is required via -Password or MYSQL_PWD"
}

$env:MYSQL_PWD = $Password
$serverArgs = @("-h", $MySqlHost, "-P", "$MySqlPort", "-u", $User, "--protocol=tcp")
$dbArgs = $serverArgs + @($Database)

Invoke-Checked { & $MySql @serverArgs -e "DROP DATABASE IF EXISTS ``$Database``; CREATE DATABASE ``$Database`` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" } "failed to recreate migration validation database"
Get-Content -Raw -LiteralPath $InitSql | & $MySql @dbArgs
if ($LASTEXITCODE -ne 0) { throw "init.sql execution failed" }

foreach ($migration in $migrations) {
  Write-Host "applying migration $($migration.Name)"
  Get-Content -Raw -LiteralPath $migration.FullName | & $MySql @dbArgs
  if ($LASTEXITCODE -ne 0) { throw "migration failed: $($migration.Name)" }
}

foreach ($migration in $migrations) {
  Write-Host "replaying migration $($migration.Name)"
  Get-Content -Raw -LiteralPath $migration.FullName | & $MySql @dbArgs
  if ($LASTEXITCODE -ne 0) { throw "migration replay failed: $($migration.Name)" }
}

Write-Host "migration database validation ok"
