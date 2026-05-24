# 文件作用：
# 本脚本执行 KnowMate 项目的端到端冒烟测试。
# 它会启动 MySQL、MCP Servers、Python Agent 和 GoFrame 后端，然后通过 HTTP 接口跑完整文章处理流程。
#
# 在项目中的位置：
# 本脚本属于项目脚本层，主要用于本地或 CI 验证完整调用链。
#
# 主要内容：
# 1. 可选启动 Docker MySQL。
# 2. 启动 embedding/fetch/milvus/neo4j MCP Server。
# 3. 启动 Python Agent gRPC Server。
# 4. 启动 GoFrame HTTP 后端。
# 5. 调用 /health、/runs/articles、/posts 并检查 MySQL 表。
# 6. 最后清理脚本启动的后台进程。
#
# 初学者阅读建议：
# 这个脚本依赖 Python、Go、Docker 和可用端口；如果环境缺失，失败原因通常在启动或健康检查阶段。
param(
  # Python 可执行文件路径，默认使用系统 python。
  [string]$Python = "python",
  # 跳过 Docker MySQL 启动，适合外部已有数据库时使用。
  [switch]$SkipDocker,
  # 跳过数据库断言，适合只验证 HTTP 主链路。
  [switch]$SkipDatabaseAssertions,
  # 保持脚本启动的服务不被 finally 清理，便于失败后手工排查。
  [switch]$KeepServices
)

# 任一命令失败就停止脚本。
$ErrorActionPreference = "Stop"

# 计算项目根目录和关键子目录。
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$PythonAgentDir = Join-Path $Root "python-agent"
$GoBackendDir = Join-Path $Root "goframe-backend"
$OutputsDir = Join-Path $Root "shared\outputs"
# $script:Processes 保存脚本启动的后台进程，finally 中统一清理。
$script:Processes = @()

# 函数作用：
# 启动一个受脚本管理的后台进程。
#
# 参数说明：
# - Name：进程逻辑名。
# - FilePath：可执行文件。
# - ArgumentList：参数列表。
# - WorkingDirectory：工作目录。
# - Environment：额外环境变量。
function Start-ManagedProcess {
  param(
    [string]$Name,
    [string]$FilePath,
    [string[]]$ArgumentList,
    [string]$WorkingDirectory,
    [hashtable]$Environment = @{}
  )

  # 为每个进程准备标准输出/错误日志路径；当前未重定向，但保留字段便于扩展。
  $out = Join-Path $env:TEMP "knowmate-$Name-out.log"
  $err = Join-Path $env:TEMP "knowmate-$Name-err.log"
  # 清理旧日志文件。
  Remove-Item -Force -ErrorAction SilentlyContinue $out, $err

  # 使用 ProcessStartInfo 精确配置工作目录、参数和环境变量。
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $FilePath
  # ArgumentList 逐个添加，避免手动拼接命令行造成空格转义问题。
  foreach ($arg in $ArgumentList) { [void]$psi.ArgumentList.Add($arg) }
  $psi.WorkingDirectory = $WorkingDirectory
  # UseShellExecute=false 才能设置环境变量。
  $psi.UseShellExecute = $false
  $psi.RedirectStandardOutput = $false
  $psi.RedirectStandardError = $false
  $psi.CreateNoWindow = $true
  # 写入额外环境变量。
  foreach ($key in $Environment.Keys) { $psi.Environment[$key] = [string]$Environment[$key] }

  # 启动进程并记录到全局列表。
  $p = New-Object System.Diagnostics.Process
  $p.StartInfo = $psi
  [void]$p.Start()
  $script:Processes += [pscustomobject]@{ Name = $Name; Process = $p; Out = $out; Err = $err }
  return $p
}

# 函数作用：
# 等待一个 HTTP JSON 接口可访问。
#
# 参数说明：
# - Url：目标地址。
# - Seconds：最大等待秒数。
function Wait-HttpJson {
  param([string]$Url, [int]$Seconds = 30)
  # deadline 是等待截止时间。
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    try {
      # Invoke-RestMethod 成功时会解析 JSON 并返回对象。
      return Invoke-RestMethod -Uri $Url -Method Get
    } catch {
      # 服务未启动时短暂等待后重试。
      Start-Sleep -Milliseconds 500
    }
  }
  throw "Timed out waiting for $Url"
}

# 函数作用：
# 简单断言工具。
function Assert-True {
  param([bool]$Condition, [string]$Message)
  if (-not $Condition) { throw $Message }
}

try {
  # 启动 MySQL Docker 容器，除非调用方明确跳过。
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
    # MySQL 未准备好时终止脚本。
    Assert-True $ready "MySQL did not become ready"
  }

  # 创建输出目录并清理旧文章 Markdown，避免测试误读历史文件。
  New-Item -ItemType Directory -Force -Path $OutputsDir | Out-Null
  Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $OutputsDir "articles-*.md")

  # 启动四个 MCP Server。
  Start-ManagedProcess "embedding-mcp" $Python @("server.py") (Join-Path $Root "mcp-servers\embedding-mcp") | Out-Null
  Start-ManagedProcess "fetch-mcp" $Python @("server.py") (Join-Path $Root "mcp-servers\fetch-mcp") | Out-Null
  Start-ManagedProcess "milvus-mcp" $Python @("server.py") (Join-Path $Root "mcp-servers\milvus-mcp") | Out-Null
  Start-ManagedProcess "neo4j-mcp" $Python @("server.py") (Join-Path $Root "mcp-servers\neo4j-mcp") | Out-Null
  # 等待每个 MCP Server 的 /health 可访问。
  Wait-HttpJson "http://127.0.0.1:7001/health" 20 | Out-Null
  Wait-HttpJson "http://127.0.0.1:7002/health" 20 | Out-Null
  Wait-HttpJson "http://127.0.0.1:7003/health" 20 | Out-Null
  Wait-HttpJson "http://127.0.0.1:7004/health" 20 | Out-Null

  # Python Agent 使用真实 MCP HTTP 地址，但 LLM 使用 mock，避免测试依赖外部模型 API。
  $agentEnv = @{
    "MOCK_MCP" = "false"
    "MOCK_LLM" = "true"
    "EMBEDDING_MCP_URL" = "http://127.0.0.1:7001"
    "FETCH_MCP_URL" = "http://127.0.0.1:7002"
    "MILVUS_MCP_URL" = "http://127.0.0.1:7003"
    "NEO4J_MCP_URL" = "http://127.0.0.1:7004"
  }
  # 启动 Python Agent gRPC Server。
  Start-ManagedProcess "python-agent" $Python @("server.py") $PythonAgentDir $agentEnv | Out-Null
  Start-Sleep -Seconds 2

  # GoFrame 后端连接 Docker MySQL。
  $backendEnv = @{
    "MYSQL_DSN" = "root:rootpass@tcp(127.0.0.1:3306)/knowledge_post_agent?charset=utf8mb4&parseTime=true&loc=Local"
  }
  # 启动 GoFrame 后端。
  Start-ManagedProcess "goframe-backend" "go" @("run", ".") $GoBackendDir $backendEnv | Out-Null
  # 等待 HTTP /health 可用，并断言 Python Agent 状态。
  $health = Wait-HttpJson "http://127.0.0.1:8080/health" 60
  Assert-True ($health.agent.status -eq "SERVING") "Python Agent health is not SERVING"

  # 触发完整文章处理任务。
  $run = Invoke-RestMethod -Uri "http://127.0.0.1:8080/runs/articles" -Method Post
  Assert-True ([bool]$run.ok) "POST /runs/articles returned ok=false: $($run | ConvertTo-Json -Depth 10)"
  Assert-True ($run.result.posts_saved -ge 1) "No posts were saved"
  Assert-True (Test-Path $run.result.markdown_path) "Markdown file not found: $($run.result.markdown_path)"

  # 查询 posts 接口，确认至少有一条结果。
  $posts = Invoke-RestMethod -Uri "http://127.0.0.1:8080/posts" -Method Get
  Assert-True ($posts.items.Count -ge 1) "GET /posts returned no rows"

  # 默认数据库断言结果标记为 skipped，便于输出摘要。
  $postCount = "skipped"
  $runLogCount = "skipped"
  $mcpLogCount = "skipped"
  $stepCount = "skipped"
  # 通过 docker exec 查询 MySQL 表，验证 posts/run_logs/mcp_call_logs 都产生了记录。
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

  # 输出端到端通过摘要。
  Write-Host "E2E smoke passed"
  Write-Host "run_id=$($run.result.run_id)"
  Write-Host "markdown=$($run.result.markdown_path)"
  Write-Host "posts=$postCount run_logs=$runLogCount mcp_call_logs=$mcpLogCount steps=$stepCount"
}
finally {
  # 除非指定 -KeepServices，否则清理本脚本启动的后台进程。
  if (-not $KeepServices) {
    foreach ($entry in $Processes) {
      if ($entry.Process -and -not $entry.Process.HasExited) {
        Stop-Process -Id $entry.Process.Id -Force -ErrorAction SilentlyContinue
      }
    }
  }
}
