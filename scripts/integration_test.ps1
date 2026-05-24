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
  [string]$Python = "python"
)

# 遇到错误立即停止，避免后续步骤在失败状态下继续执行。
$ErrorActionPreference = "Stop"
# $PSScriptRoot 是当前脚本所在目录，.. 是项目根目录。
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

Write-Host "Running unit checks"
# 进入 GoFrame 后端目录，运行全部 Go 测试。
Push-Location (Join-Path $Root "goframe-backend")
go test ./...
# Pop-Location 返回脚本原目录，避免后续路径错乱。
Pop-Location

# 进入 Python Agent 目录，运行 unittest 测试。
Push-Location (Join-Path $Root "python-agent")
& $Python -m unittest discover -s tests
Pop-Location

Write-Host "Running full E2E smoke"
# 调用完整端到端冒烟脚本，并把 Python 可执行文件参数继续传下去。
& (Join-Path $PSScriptRoot "smoke_e2e.ps1") -Python $Python
