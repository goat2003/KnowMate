param(
  [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

Write-Host "Running unit checks"
Push-Location (Join-Path $Root "goframe-backend")
go test ./...
Pop-Location

Push-Location (Join-Path $Root "python-agent")
& $Python -m unittest discover -s tests
Pop-Location

Write-Host "Running full E2E smoke"
& (Join-Path $PSScriptRoot "smoke_e2e.ps1") -Python $Python
