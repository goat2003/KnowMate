# 运行：powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-all.ps1
[CmdletBinding()]
param(
    [string]$ProjectName = "knowmate-dev",
    [switch]$Build,
    [switch]$NoWeb
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "未找到 $Name。请先安装并启动对应运行环境。"
    }
}

Require-Command "docker"
if (-not $NoWeb) { Require-Command "npm.cmd" }

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop 未运行，无法启动 KnowMate 服务。"
}

$composeArgs = @(
    "compose",
    "--project-name", $ProjectName,
    "--env-file", (Join-Path $root "configs/env/dev.env"),
    "-f", (Join-Path $root "docker-compose.yml"),
    "up", "-d", "--wait", "--wait-timeout", "240"
)
if ($Build) { $composeArgs += "--build" }

Write-Host "启动 Docker 服务（项目：$ProjectName）..." -ForegroundColor Cyan
& docker @composeArgs
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose 启动失败。"
}

if (-not $NoWeb) {
    $webPortBusy = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
    if ($webPortBusy) {
        Write-Warning "5173 端口已有进程监听，跳过启动 Web Admin；请打开现有的 http://127.0.0.1:5173。"
    } else {
        $stdout = Join-Path $root "web-admin/dev-server.out.log"
        $stderr = Join-Path $root "web-admin/dev-server.err.log"
        Write-Host "启动 Web Admin（Vite）..." -ForegroundColor Cyan
        $web = Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "dev") `
            -WorkingDirectory (Join-Path $root "web-admin") `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
        Write-Host "Web Admin 进程已启动：$($web.Id)" -ForegroundColor Green
        $webReady = $false
        1..20 | ForEach-Object {
            if ($webReady) { return }
            Start-Sleep -Seconds 1
            try {
                $probe = Invoke-WebRequest -Uri "http://127.0.0.1:5173" -UseBasicParsing -TimeoutSec 2
                $webReady = $probe.StatusCode -ge 200 -and $probe.StatusCode -lt 500
            } catch { }
        }
        if (-not $webReady) {
            Write-Warning "Web Admin 尚未响应，请查看 web-admin/dev-server.err.log。"
        }
    }
}

Write-Host "" 
Write-Host "KnowMate 服务已提交启动。" -ForegroundColor Green
Write-Host "Web Admin:       http://127.0.0.1:5173"
Write-Host "GoFrame API:     http://127.0.0.1:8080"
Write-Host "健康检查:        http://127.0.0.1:8080/health"
Write-Host "查看服务状态:    docker compose --project-name $ProjectName --env-file configs/env/dev.env -f docker-compose.yml ps"
Write-Host "停止 Docker:     docker compose --project-name $ProjectName --env-file configs/env/dev.env -f docker-compose.yml stop"
Write-Host "Vite 日志:       web-admin/dev-server.out.log / web-admin/dev-server.err.log"
