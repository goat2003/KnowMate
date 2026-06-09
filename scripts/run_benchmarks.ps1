param(
  [string]$Python = "python",
  [string]$GoBenchTime = "1s",
  [switch]$SkipPython
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

Push-Location (Join-Path $Root "goframe-backend")
try {
  go test ./... -run '^$' -bench=Benchmark -benchmem "-benchtime=$GoBenchTime"
  if ($LASTEXITCODE -ne 0) { throw "Go benchmark tests failed" }
} finally {
  Pop-Location
}

if (-not $SkipPython) {
  Push-Location (Join-Path $Root "python-agent")
  try {
    @'
from datetime import datetime, timezone
import time

from app.recommendation import RecommendationRanker

articles = [
    {
        "article_id": f"a-{i}",
        "url": f"https://example.com/{i}",
        "title": "AI workflow knowledge graph",
        "raw_text": "AI workflow knowledge graph " * 20,
        "source": "rss",
        "tags": ["AI", "workflow"],
    }
    for i in range(200)
]
ranker = RecommendationRanker()
start = time.perf_counter()
for _ in range(10):
    ranked = ranker.rank(articles, {"keywords": "AI,workflow"}, now=datetime(2026, 6, 8, tzinfo=timezone.utc))
elapsed = time.perf_counter() - start
assert len(ranked) == len(articles)
print(f"python recommendation benchmark ok: {elapsed:.4f}s")
'@ | & $Python -
    if ($LASTEXITCODE -ne 0) { throw "Python benchmark smoke failed" }
  } finally {
    Pop-Location
  }
}
