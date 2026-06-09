param(
  [string]$Python = "python",
  [switch]$SkipGo,
  [switch]$SkipPython,
  [switch]$SkipWeb,
  [switch]$SkipDockerBuild,
  [switch]$SkipComposeConfig,
  [switch]$SkipKubernetesDryRun,
  [switch]$RunE2E,
  [switch]$RunAdminE2E,
  [switch]$RealMemoryServices
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Artifacts = Join-Path $Root "artifacts\final-acceptance"
New-Item -ItemType Directory -Force -Path $Artifacts | Out-Null

function Invoke-Step {
  param([string]$Name, [scriptblock]$Body)
  Write-Host ""
  Write-Host "==> $Name"
  & $Body
  if ($LASTEXITCODE -ne 0) {
    throw "$Name failed"
  }
}

function Invoke-WithEnv {
  param([hashtable]$Values, [scriptblock]$Body)
  $previous = @{}
  foreach ($key in $Values.Keys) {
    $previous[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
    [Environment]::SetEnvironmentVariable($key, [string]$Values[$key], "Process")
  }
  try {
    & $Body
  } finally {
    foreach ($key in $Values.Keys) {
      [Environment]::SetEnvironmentVariable($key, $previous[$key], "Process")
    }
  }
}

Invoke-Step "Deployment asset contract tests" {
  & $Python -m unittest scripts.test_deployment_assets -v
}

Invoke-Step "Migration static validation" {
  & (Join-Path $Root "scripts\verify_migrations.ps1")
}

if (-not $SkipGo) {
  Push-Location (Join-Path $Root "goframe-backend")
  try {
    Invoke-Step "Go tests" {
      go test ./... -count=1
    }
  } finally {
    Pop-Location
  }
}

if (-not $SkipPython) {
  Push-Location (Join-Path $Root "python-agent")
  try {
    Invoke-Step "Python Agent tests" {
      & $Python -m unittest discover -s tests
    }
  } finally {
    Pop-Location
  }

  Push-Location (Join-Path $Root "mcp-servers")
  try {
    Invoke-Step "MCP Server tests" {
      & $Python -m unittest discover -s tests
    }
  } finally {
    Pop-Location
  }
}

if (-not $SkipWeb) {
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is required for Web Admin acceptance; pass -SkipWeb to skip"
  }
  Push-Location (Join-Path $Root "web-admin")
  try {
    if (-not (Test-Path -LiteralPath "node_modules")) {
      Invoke-Step "Web Admin dependencies" {
        npm ci
      }
    }
    Invoke-Step "Web Admin unit tests" {
      npm test
    }
    Invoke-Step "Web Admin production build" {
      npm run build
    }
    if ($RunAdminE2E) {
      Invoke-Step "Web Admin Playwright flow" {
        npm run playwright
      }
    }
  } finally {
    Pop-Location
  }
}

if (-not $SkipComposeConfig) {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker is required for Compose validation; pass -SkipComposeConfig to skip"
  }
  Invoke-WithEnv @{
    MYSQL_ROOT_PASSWORD = "acceptance-root"
    MYSQL_PASSWORD = "acceptance-app"
    GOFRAME_API_TOKEN = "acceptance-http-token"
    AGENT_GRPC_AUTH_TOKEN = "acceptance-grpc-token"
    OPENAI_API_KEY = "acceptance-openai-key"
    NEO4J_PASSWORD = "acceptance-neo4j"
    MINIO_ROOT_USER = "acceptance-minio"
    MINIO_ROOT_PASSWORD = "acceptance-minio-password"
    GRAFANA_ADMIN_USER = "admin"
    GRAFANA_ADMIN_PASSWORD = "acceptance-grafana"
  } {
    Invoke-Step "Production Compose config" {
      $rendered = & docker compose -f (Join-Path $Root "docker-compose.prod.yml") config
      if ($LASTEXITCODE -ne 0) { throw "docker compose config failed" }
      $rendered | Set-Content -Path (Join-Path $Artifacts "docker-compose-prod.rendered.yml") -Encoding UTF8
    }
  }
}

if (-not $SkipKubernetesDryRun) {
  if (Get-Command kubectl -ErrorAction SilentlyContinue) {
    $clusterExit = 1
    try {
      kubectl cluster-info *> $null
      $clusterExit = $LASTEXITCODE
    } catch {
      $clusterExit = 1
    }
    if ($clusterExit -eq 0) {
      Invoke-Step "Kubernetes manifest dry-run" {
        kubectl apply --dry-run=client --validate=false -f (Join-Path $Root "deploy\kubernetes")
      }
    } else {
      Write-Host "kubectl found but no reachable cluster; Kubernetes API dry-run skipped"
    }
  } else {
    Write-Host "kubectl not found; Kubernetes dry-run skipped"
  }
}

if (-not $SkipDockerBuild) {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker is required for image builds; pass -SkipDockerBuild to skip"
  }
  Invoke-Step "Docker image build: goframe-backend" {
    docker build -f (Join-Path $Root "goframe-backend\Dockerfile") -t knowmate/goframe-backend:acceptance $Root
  }
  Invoke-Step "Docker image build: python-agent" {
    docker build -f (Join-Path $Root "python-agent\Dockerfile") -t knowmate/python-agent:acceptance $Root
  }
  Invoke-Step "Docker image build: mcp-servers" {
    docker build -f (Join-Path $Root "mcp-servers\Dockerfile") -t knowmate/mcp-servers:acceptance $Root
  }
  Invoke-Step "Docker image build: web-admin" {
    docker build -f (Join-Path $Root "web-admin\Dockerfile") -t knowmate/web-admin:acceptance $Root
  }
}

if ($RunE2E) {
  if ($RealMemoryServices) {
    Invoke-Step "Full integration with real Milvus and Neo4j" {
      & (Join-Path $Root "scripts\integration_test.ps1") -Python $Python -RealMemoryServices
    }
  } else {
    Invoke-Step "Fixture E2E smoke" {
      & (Join-Path $Root "scripts\smoke_e2e.ps1") -SkipBuild:$SkipDockerBuild
    }
  }
}

Write-Host ""
Write-Host "Final acceptance checks completed"
Write-Host "Artifacts: $Artifacts"
