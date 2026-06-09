param(
  [string]$Python = "python",
  [int]$GoCoverageThreshold = 40,
  [int]$PythonCoverageThreshold = 55,
  [switch]$SkipDocker,
  [switch]$SkipIntegration,
  [switch]$SkipE2E,
  [switch]$SkipVulnerabilityScan,
  [switch]$SkipBenchmarks,
  [switch]$RequireMigrationDatabase
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Artifacts = Join-Path $Root "artifacts\quality"
New-Item -ItemType Directory -Force -Path $Artifacts | Out-Null

function Invoke-Step {
  param([string]$Name, [scriptblock]$Body)
  Write-Host ""
  Write-Host "==> $Name"
  & $Body
  if ($LASTEXITCODE -ne 0) { throw "$Name failed" }
}

function Assert-PythonModule {
  param([string]$Module, [string]$InstallHint)
  & $Python -c "import $Module" *> $null
  if ($LASTEXITCODE -ne 0) {
    throw "missing Python dev dependency '$Module'. Install with: $InstallHint"
  }
}

Invoke-Step "Secret scan" {
  & $Python (Join-Path $Root "scripts\check_secrets.py") --all
}

Invoke-Step "Proto contract" {
  & (Join-Path $Root "scripts\check_proto_contract.ps1") -Python $Python
}

Invoke-Step "Migration validation" {
  if ($RequireMigrationDatabase) {
    & (Join-Path $Root "scripts\verify_migrations.ps1") -RequireDatabase
  } else {
    & (Join-Path $Root "scripts\verify_migrations.ps1")
  }
}

Push-Location (Join-Path $Root "goframe-backend")
try {
  Invoke-Step "Go format" {
    $files = gofmt -l .
    if ($LASTEXITCODE -ne 0) { throw "gofmt check failed" }
    if ($files) {
      $files | ForEach-Object { Write-Host $_ }
      throw "go fmt changed files; commit formatted output"
    }
  }
  Invoke-Step "Go vet" {
    go vet ./...
  }
  Invoke-Step "Go tests with coverage" {
    go test ./... -coverprofile (Join-Path $Artifacts "go-coverage.out") -covermode=atomic -count=1
  }
  Invoke-Step "Go coverage threshold" {
    $coverage = go tool cover -func (Join-Path $Artifacts "go-coverage.out") | Select-String "total:"
    Write-Host $coverage
    $percentText = (($coverage -split "\s+")[-1]).TrimEnd("%")
    if ([double]$percentText -lt $GoCoverageThreshold) {
      throw "Go coverage $percentText% is below threshold $GoCoverageThreshold%"
    }
  }
  if (-not $SkipVulnerabilityScan) {
    Invoke-Step "Go vulnerability scan" {
      if (-not (Get-Command govulncheck -ErrorAction SilentlyContinue)) {
        go install golang.org/x/vuln/cmd/govulncheck@latest
      }
      govulncheck ./...
    }
  }
} finally {
  Pop-Location
}

Invoke-Step "Python lint" {
  Assert-PythonModule "ruff" "python -m pip install -r requirements-dev.txt"
  & $Python -m ruff check python-agent mcp-servers scripts
}

Invoke-Step "Python type check" {
  Assert-PythonModule "mypy" "python -m pip install -r requirements-dev.txt"
  & $Python -m mypy python-agent/app/contracts.py python-agent/app/config.py python-agent/app/recommendation/config.py python-agent/app/mcp/policy.py mcp-servers/common/provider.py mcp-servers/common/observability.py scripts/check_secrets.py
}

Invoke-Step "Python tests with coverage" {
  Assert-PythonModule "pytest_cov" "python -m pip install -r requirements-dev.txt"
  & $Python -m pytest python-agent/tests mcp-servers/tests --cov=python-agent/app --cov=mcp-servers --cov-report=term-missing --cov-report=xml:$Artifacts/python-coverage.xml --cov-fail-under=$PythonCoverageThreshold
}

if (-not $SkipVulnerabilityScan) {
  Invoke-Step "Python dependency vulnerability scan" {
    pip-audit -r python-agent/requirements.txt -r mcp-servers/requirements.txt -r requirements-dev.txt
  }
}

if (-not $SkipBenchmarks) {
  Invoke-Step "Benchmark tests" {
    & (Join-Path $Root "scripts\run_benchmarks.ps1") -Python $Python
  }
}

if (-not $SkipDocker) {
  Invoke-Step "Docker image build: goframe-backend" {
    docker build -f goframe-backend/Dockerfile -t knowmate/goframe-backend:ci .
  }
  Invoke-Step "Docker image build: python-agent" {
    docker build -f python-agent/Dockerfile -t knowmate/python-agent:ci .
  }
  Invoke-Step "Docker image build: mcp-servers" {
    docker build -f mcp-servers/Dockerfile -t knowmate/mcp-servers:ci .
  }
}

if (-not $SkipIntegration) {
  Invoke-Step "Integration tests" {
    & (Join-Path $Root "scripts\integration_test.ps1") -Python $Python
  }
}

if (-not $SkipE2E) {
  Invoke-Step "E2E smoke" {
    & (Join-Path $Root "scripts\smoke_e2e.ps1")
  }
}

Write-Host ""
Write-Host "quality gate passed"
