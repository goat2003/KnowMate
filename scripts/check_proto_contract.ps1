# 文件作用：
# 本脚本检查 Go/Python 两侧 protobuf 协议契约是否一致。
# 它先确认 shared/proto/agent.proto 与 proto/agent.proto 内容相同，再分别运行 Python 和 Go 的协议字段检查。
#
# 在项目中的位置：
# 本脚本属于项目脚本层，适合在修改 proto 后运行。
#
# 主要内容：
# 1. 对比两个 agent.proto 文件 SHA256。
# 2. 用 Python 检查 agent_pb2 描述中是否有关键 service/message/field。
# 3. 用 Go 测试检查 internal/agentpb 的协议契约。
#
# 初学者阅读建议：
# 如果该脚本失败，通常意味着两个 proto 文件不同步，或生成的 protobuf 代码没有重新生成。
param(
  # Python 可执行文件路径，默认使用系统 python。
  [string]$Python = "python"
)

# 任何命令失败就停止脚本。
$ErrorActionPreference = "Stop"
# 计算项目根目录。
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

# 分别计算 shared/proto 和 proto 下 agent.proto 的 SHA256。
$shared = Get-FileHash (Join-Path $Root "shared\proto\agent.proto") -Algorithm SHA256
$legacy = Get-FileHash (Join-Path $Root "proto\agent.proto") -Algorithm SHA256
# 两份 proto 不一致会导致 Go/Python 生成代码协议不同，因此直接失败。
if ($shared.Hash -ne $legacy.Hash) {
  throw "shared/proto/agent.proto and proto/agent.proto differ"
}

# 进入 Python Agent 目录，使用内联 Python 代码检查生成的 agent_pb2。
Push-Location (Join-Path $Root "python-agent")
@'
import agent_pb2

# 读取 AgentService 描述，确认关键 RPC 方法存在。
service = agent_pb2.DESCRIPTOR.services_by_name["AgentService"]
for name in ["HealthCheck", "ProcessArticles", "ProcessFeedback"]:
    assert name in service.methods_by_name, name
# 检查 Article 输入字段。
article = agent_pb2.Article.DESCRIPTOR
for name in ["article_id", "url", "title", "raw_text", "source", "published_at", "tags"]:
    assert name in article.fields_by_name, name
# 检查 ArticleProcessResult 输出字段。
result = agent_pb2.ArticleProcessResult.DESCRIPTOR
for name in ["article_id", "keep", "score", "summary", "post_text", "check_pass", "issues", "mcp_call_logs"]:
    assert name in result.fields_by_name, name
print("python proto contract ok")
'@ | & $Python -
Pop-Location

# 进入 GoFrame 后端目录，运行 Go 端 protobuf 契约测试。
Push-Location (Join-Path $Root "goframe-backend")
go test ./internal/agentpb
# PowerShell 中检查上一条命令退出码，失败时抛出明确错误。
if ($LASTEXITCODE -ne 0) { throw "go proto contract test failed" }
Pop-Location

# 输出通过信息和 proto hash，便于 CI 日志确认是哪一份协议。
Write-Host "proto contract ok: $($shared.Hash)"
