param(
  [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

$shared = Get-FileHash (Join-Path $Root "shared\proto\agent.proto") -Algorithm SHA256
$legacy = Get-FileHash (Join-Path $Root "proto\agent.proto") -Algorithm SHA256
if ($shared.Hash -ne $legacy.Hash) {
  throw "shared/proto/agent.proto and proto/agent.proto differ"
}

Push-Location (Join-Path $Root "python-agent")
@'
import agent_pb2

service = agent_pb2.DESCRIPTOR.services_by_name["AgentService"]
for name in ["HealthCheck", "ProcessArticles", "ProcessFeedback"]:
    assert name in service.methods_by_name, name
article = agent_pb2.Article.DESCRIPTOR
for name in ["article_id", "url", "title", "raw_text", "source", "published_at", "tags"]:
    assert name in article.fields_by_name, name
result = agent_pb2.ArticleProcessResult.DESCRIPTOR
for name in ["article_id", "keep", "score", "summary", "post_text", "check_pass", "issues", "mcp_call_logs"]:
    assert name in result.fields_by_name, name
print("python proto contract ok")
'@ | & $Python -
Pop-Location

Push-Location (Join-Path $Root "goframe-backend")
go test ./internal/agentpb
if ($LASTEXITCODE -ne 0) { throw "go proto contract test failed" }
Pop-Location

Write-Host "proto contract ok: $($shared.Hash)"
