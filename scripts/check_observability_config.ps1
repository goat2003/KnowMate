$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

$requiredFiles = @(
    "docker-compose.yml",
    ".env.example",
    "observability/otel-collector.yml",
    "observability/prometheus.yml",
    "observability/alertmanager.yml",
    "observability/alerts.yml",
    "observability/grafana/provisioning/datasources/datasource.yml",
    "observability/grafana/provisioning/dashboards/dashboards.yml",
    "observability/grafana/dashboards/knowmate-overview.json"
)

foreach ($relativePath in $requiredFiles) {
    $fullPath = Join-Path $repoRoot $relativePath
    if (-not (Test-Path $fullPath)) {
        throw "Missing required file: $relativePath"
    }
}

$composePath = Join-Path $repoRoot "docker-compose.yml"
$composeContent = Get-Content $composePath -Raw
$requiredServices = @("otel-collector", "prometheus", "grafana", "jaeger", "alertmanager")

foreach ($serviceName in $requiredServices) {
    if ($composeContent -notmatch "(?m)^  $([regex]::Escape($serviceName)):`r?$") {
        throw "Missing compose service: $serviceName"
    }
}

$dashboardPath = Join-Path $repoRoot "observability/grafana/dashboards/knowmate-overview.json"
$dashboard = Get-Content $dashboardPath -Raw | ConvertFrom-Json

if ($dashboard.title -ne "KnowMate Observability Overview") {
    throw "Unexpected dashboard title: $($dashboard.title)"
}

Write-Host "Observability config files look valid."
