param(
  [switch]$KeepServices,
  [switch]$IncludeObservability,
  [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$OutputsDir = Join-Path $Root "shared\outputs"
$RootPassword = if ($env:MYSQL_ROOT_PASSWORD) { $env:MYSQL_ROOT_PASSWORD } else { "rootpass" }

function Assert-True {
  param([bool]$Condition, [string]$Message)
  if (-not $Condition) { throw $Message }
}

function Test-IsWindowsHost {
  if (Get-Variable -Name IsWindows -ErrorAction SilentlyContinue) {
    return $IsWindows
  }
  return $env:OS -eq "Windows_NT"
}

function Set-SmokeOutputDirectory {
  New-Item -ItemType Directory -Force -Path $OutputsDir | Out-Null
  if (-not (Test-IsWindowsHost)) {
    chmod "0777" "$OutputsDir"
    if ($LASTEXITCODE -ne 0) { throw "failed to make smoke output directory writable: $OutputsDir" }
  }
}

function Wait-HttpJson {
  param([string]$Url, [int]$Seconds = 180)
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    try {
      return Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 5
    } catch {
      Start-Sleep -Seconds 2
    }
  }
  throw "Timed out waiting for $Url"
}

Push-Location $Root
try {
  Set-SmokeOutputDirectory

  $services = @("mysql", "embedding-mcp", "fetch-mcp", "milvus-mcp", "neo4j-mcp", "python-agent", "goframe-backend")
  if ($IncludeObservability) {
    $services += @("jaeger", "otel-collector", "alertmanager", "prometheus", "grafana")
  }
  $composeArgs = @("up", "-d")
  if (-not $SkipBuild) {
    $composeArgs += "--build"
  }
  $composeArgs += $services
  docker compose @composeArgs
  if ($LASTEXITCODE -ne 0) { throw "docker compose $($composeArgs -join ' ') failed" }

  $health = Wait-HttpJson "http://127.0.0.1:8080/health"
  Assert-True ($health.agent.status -eq "SERVING") "Python Agent health is not SERVING"

  docker compose exec -T mysql mysql "-uroot" "-p$RootPassword" knowledge_post_agent -e "SET FOREIGN_KEY_CHECKS=0; TRUNCATE TABLE mcp_call_logs; TRUNCATE TABLE posts; TRUNCATE TABLE articles; TRUNCATE TABLE crawl_source_runs; TRUNCATE TABLE run_logs; SET FOREIGN_KEY_CHECKS=1;"
  if ($LASTEXITCODE -ne 0) { throw "failed to reset smoke-test tables" }

  Get-ChildItem -LiteralPath $OutputsDir -Filter "articles-*.md" -File -ErrorAction SilentlyContinue | Remove-Item -Force

  $run = Invoke-RestMethod -Uri "http://127.0.0.1:8080/runs/articles" -Method Post -TimeoutSec 120
  Assert-True ([bool]$run.ok) "POST /runs/articles returned ok=false"
  Assert-True ($run.result.posts_saved -ge 1) "No posts were saved"

  $markdownName = Split-Path -Leaf $run.result.markdown_path
  $hostMarkdown = Join-Path $OutputsDir $markdownName
  Assert-True (Test-Path -LiteralPath $hostMarkdown) "Markdown file not found: $hostMarkdown"

  $posts = Invoke-RestMethod -Uri "http://127.0.0.1:8080/posts" -Method Get -TimeoutSec 30
  Assert-True ($posts.items.Count -ge 1) "GET /posts returned no rows"

  $postCount = docker compose exec -T mysql mysql "-uroot" "-p$RootPassword" knowledge_post_agent -N -e "SELECT COUNT(*) FROM posts;"
  $runLogCount = docker compose exec -T mysql mysql "-uroot" "-p$RootPassword" knowledge_post_agent -N -e "SELECT COUNT(*) FROM run_logs WHERE run_id='$($run.result.run_id)';"
  $mcpLogCount = docker compose exec -T mysql mysql "-uroot" "-p$RootPassword" knowledge_post_agent -N -e "SELECT COUNT(*) FROM mcp_call_logs WHERE run_id='$($run.result.run_id)';"
  $stepCount = docker compose exec -T mysql mysql "-uroot" "-p$RootPassword" knowledge_post_agent -N -e "SELECT COALESCE(JSON_LENGTH(JSON_EXTRACT(metadata, '$.steps')), 0) FROM run_logs WHERE run_id='$($run.result.run_id)' LIMIT 1;"
  $sourceRunCount = docker compose exec -T mysql mysql "-uroot" "-p$RootPassword" knowledge_post_agent -N -e "SELECT COUNT(*) FROM crawl_source_runs WHERE run_id='$($run.result.run_id)';"
  $processableArticleCount = docker compose exec -T mysql mysql "-uroot" "-p$RootPassword" knowledge_post_agent -N -e "SELECT COUNT(*) FROM articles WHERE fetch_status IN ('success', 'partial') AND content_hash IS NOT NULL;"

  Assert-True ([int]$postCount -ge 1) "MySQL posts table has no rows"
  Assert-True ([int]$runLogCount -eq 1) "MySQL run_logs must contain exactly one idempotent row"
  Assert-True ([int]$mcpLogCount -ge 1) "MySQL mcp_call_logs has no rows"
  Assert-True ([int]$stepCount -ge 5) "run_logs metadata.steps is incomplete"
  Assert-True ([int]$sourceRunCount -ge 1) "MySQL crawl_source_runs has no rows for the current run"
  Assert-True ([int]$processableArticleCount -ge 1) "MySQL articles has no processable row with content_hash"

  Write-Host "E2E smoke passed: run_id=$($run.result.run_id) posts=$postCount sources=$sourceRunCount mcp_logs=$mcpLogCount markdown=$hostMarkdown"
} catch {
  docker compose ps
  docker compose logs --tail=100
  throw
} finally {
  if (-not $KeepServices) {
    docker compose down
  }
  Pop-Location
}
