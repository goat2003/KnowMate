param(
  [string]$Python = "python",
  [switch]$SkipDocker,
  [switch]$SkipDatabaseAssertions,
  [switch]$KeepServices
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$PythonAgentDir = Join-Path $Root "python-agent"
$GoBackendDir = Join-Path $Root "goframe-backend"
$OutputsDir = Join-Path $Root "shared\outputs"
$script:Processes = @()

function Start-ManagedProcess {
  param(
    [string]$Name,
    [string]$FilePath,
    [string[]]$ArgumentList,
    [string]$WorkingDirectory,
    [hashtable]$Environment = @{}
  )

  $out = Join-Path $env:TEMP "knowmate-$Name-out.log"
  $err = Join-Path $env:TEMP "knowmate-$Name-err.log"
  Remove-Item -Force -ErrorAction SilentlyContinue $out, $err

  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $FilePath
  foreach ($arg in $ArgumentList) { [void]$psi.ArgumentList.Add($arg) }
  $psi.WorkingDirectory = $WorkingDirectory
  $psi.UseShellExecute = $false
  $psi.RedirectStandardOutput = $false
  $psi.RedirectStandardError = $false
  $psi.CreateNoWindow = $true
  foreach ($key in $Environment.Keys) { $psi.Environment[$key] = [string]$Environment[$key] }

  $p = New-Object System.Diagnostics.Process
  $p.StartInfo = $psi
  [void]$p.Start()
  $script:Processes += [pscustomobject]@{ Name = $Name; Process = $p; Out = $out; Err = $err }
  return $p
}

function Wait-HttpJson {
  param([string]$Url, [int]$Seconds = 30)
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    try {
      return Invoke-RestMethod -Uri $Url -Method Get
    } catch {
      Start-Sleep -Milliseconds 500
    }
  }
  throw "Timed out waiting for $Url"
}

function Assert-True {
  param([bool]$Condition, [string]$Message)
  if (-not $Condition) { throw $Message }
}

try {
  if (-not $SkipDocker) {
    Push-Location $Root
    docker compose up -d mysql
    if ($LASTEXITCODE -ne 0) { throw "docker compose up -d mysql failed; ensure Docker Desktop is running" }
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
      $status = docker compose exec -T mysql mysqladmin ping -h 127.0.0.1 -uroot -prootpass 2>$null
      if ($LASTEXITCODE -eq 0 -and $status -match "mysqld is alive") {
        $ready = $true
        break
      }
      Start-Sleep -Seconds 1
    }
    Pop-Location
    Assert-True $ready "MySQL did not become ready"
  }

  New-Item -ItemType Directory -Force -Path $OutputsDir | Out-Null
  Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $OutputsDir "articles-*.md")

  Start-ManagedProcess "embedding-mcp" $Python @("server.py") (Join-Path $Root "mcp-servers\embedding-mcp") | Out-Null
  Start-ManagedProcess "fetch-mcp" $Python @("server.py") (Join-Path $Root "mcp-servers\fetch-mcp") | Out-Null
  Start-ManagedProcess "milvus-mcp" $Python @("server.py") (Join-Path $Root "mcp-servers\milvus-mcp") | Out-Null
  Start-ManagedProcess "neo4j-mcp" $Python @("server.py") (Join-Path $Root "mcp-servers\neo4j-mcp") | Out-Null
  Wait-HttpJson "http://127.0.0.1:7001/health" 20 | Out-Null
  Wait-HttpJson "http://127.0.0.1:7002/health" 20 | Out-Null
  Wait-HttpJson "http://127.0.0.1:7003/health" 20 | Out-Null
  Wait-HttpJson "http://127.0.0.1:7004/health" 20 | Out-Null

  $agentEnv = @{
    "MOCK_MCP" = "false"
    "MOCK_LLM" = "true"
    "EMBEDDING_MCP_URL" = "http://127.0.0.1:7001"
    "FETCH_MCP_URL" = "http://127.0.0.1:7002"
    "MILVUS_MCP_URL" = "http://127.0.0.1:7003"
    "NEO4J_MCP_URL" = "http://127.0.0.1:7004"
  }
  Start-ManagedProcess "python-agent" $Python @("server.py") $PythonAgentDir $agentEnv | Out-Null
  Start-Sleep -Seconds 2

  $backendEnv = @{
    "MYSQL_DSN" = "root:rootpass@tcp(127.0.0.1:3306)/knowledge_post_agent?charset=utf8mb4&parseTime=true&loc=Local"
  }
  Start-ManagedProcess "goframe-backend" "go" @("run", ".") $GoBackendDir $backendEnv | Out-Null
  $health = Wait-HttpJson "http://127.0.0.1:8080/health" 60
  Assert-True ($health.agent.status -eq "SERVING") "Python Agent health is not SERVING"

  $run = Invoke-RestMethod -Uri "http://127.0.0.1:8080/runs/articles" -Method Post
  Assert-True ([bool]$run.ok) "POST /runs/articles returned ok=false: $($run | ConvertTo-Json -Depth 10)"
  Assert-True ($run.result.posts_saved -ge 1) "No posts were saved"
  Assert-True (Test-Path $run.result.markdown_path) "Markdown file not found: $($run.result.markdown_path)"

  $posts = Invoke-RestMethod -Uri "http://127.0.0.1:8080/posts" -Method Get
  Assert-True ($posts.items.Count -ge 1) "GET /posts returned no rows"

  $postCount = "skipped"
  $runLogCount = "skipped"
  $mcpLogCount = "skipped"
  $stepCount = "skipped"
  if (-not $SkipDatabaseAssertions) {
    Push-Location $Root
    $postCount = docker compose exec -T mysql mysql -uroot -prootpass knowledge_post_agent -N -e "SELECT COUNT(*) FROM posts;" 2>$null
    $runLogCount = docker compose exec -T mysql mysql -uroot -prootpass knowledge_post_agent -N -e "SELECT COUNT(*) FROM run_logs WHERE run_id='$($run.result.run_id)';" 2>$null
    $mcpLogCount = docker compose exec -T mysql mysql -uroot -prootpass knowledge_post_agent -N -e "SELECT COUNT(*) FROM mcp_call_logs WHERE run_id='$($run.result.run_id)';" 2>$null
    $stepCount = docker compose exec -T mysql mysql -uroot -prootpass knowledge_post_agent -N -e "SELECT COALESCE(JSON_LENGTH(JSON_EXTRACT(metadata, '$.steps')), 0) FROM run_logs WHERE run_id='$($run.result.run_id)' ORDER BY id DESC LIMIT 1;" 2>$null
    Pop-Location
    Assert-True ([int]$postCount -ge 1) "MySQL posts table has no rows"
    Assert-True ([int]$runLogCount -ge 1) "MySQL run_logs has no row for $($run.result.run_id)"
    Assert-True ([int]$mcpLogCount -ge 1) "MySQL mcp_call_logs has no row for $($run.result.run_id)"
    Assert-True ([int]$stepCount -ge 5) "run_logs metadata.steps is incomplete"
  }

  Write-Host "E2E smoke passed"
  Write-Host "run_id=$($run.result.run_id)"
  Write-Host "markdown=$($run.result.markdown_path)"
  Write-Host "posts=$postCount run_logs=$runLogCount mcp_call_logs=$mcpLogCount steps=$stepCount"
}
finally {
  if (-not $KeepServices) {
    foreach ($entry in $Processes) {
      if ($entry.Process -and -not $entry.Process.HasExited) {
        Stop-Process -Id $entry.Process.Id -Force -ErrorAction SilentlyContinue
      }
    }
  }
}
