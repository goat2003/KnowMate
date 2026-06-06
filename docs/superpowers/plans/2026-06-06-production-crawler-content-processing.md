# 生产级抓取器与正文处理流程实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 将 GoFrame 当前仅支持基础 RSS 的抓取链路升级为可离线验证的生产级多来源抓取、正文清洗、多级去重和来源失败隔离流程。

**架构：** 用来源适配器将 RSS、Atom、Arxiv、GitHub Release 和 HuggingFace Papers 转换为统一 `RawEntry`，再由统一管线执行 URL 规范化、robots.txt、按域名限速、HTTP 重试、正文提取、语言识别和哈希生成。Harness 只负责跨来源编排和持久化，Store 负责文章及来源运行记录写入，所有公网行为通过 `httptest.Server` fixture 验证。

**技术栈：** Go 1.25、GoFrame v2、`gofeed`、`golang.org/x/net/html`、`github.com/jimsmart/grobotstxt`、MySQL 8、`github.com/DATA-DOG/go-sqlmock`、PowerShell。

---

## 执行约束

- 当前工作区包含大量与本任务无关的未提交修改。每个提交只能暂存当前任务明确列出的文件，不得使用 `git add .`，不得覆盖或回退已有修改。
- 执行每个提交前，先对该 Task 提交步骤中显式列出的路径运行 `git diff --`。如果某个既有文件在本任务开始前已包含用户修改，保留该文件改动但跳过当次提交，避免把用户修改误带入提交；新建文件和确认无预存修改的文件仍可按计划提交。
- 严格执行 TDD：先添加单个行为测试，运行并确认因缺少行为而失败，再实现最小代码使其通过。
- 所有抓取测试必须使用 `httptest.Server`、`mock://` 或 `testdata` fixture，不得访问公网。
- 不修改 Python Agent protobuf。`model.Article.Content` 继续映射到现有 `Article.raw_text`，其值改为清洗正文。
- 每个任务完成后至少运行该任务的聚焦测试；最终任务再运行全量测试与集成检查。

## 文件结构

### 新增文件

- `goframe-backend/internal/crawler/types.go`：统一来源、原始条目、来源结果和错误类型。
- `goframe-backend/internal/crawler/normalize.go`：URL、标题、稳定 ID 和哈希。
- `goframe-backend/internal/crawler/normalize_test.go`：规范化与哈希测试。
- `goframe-backend/internal/crawler/language.go`：中文、英文、混合语言识别。
- `goframe-backend/internal/crawler/language_test.go`：语言识别测试。
- `goframe-backend/internal/crawler/errors.go`：抓取错误分类。
- `goframe-backend/internal/crawler/errors_test.go`：错误分类测试。
- `goframe-backend/internal/crawler/http_client.go`：User-Agent、超时、限速、重试、退避和响应大小限制。
- `goframe-backend/internal/crawler/http_client_test.go`：HTTP 策略离线测试。
- `goframe-backend/internal/crawler/robots.go`：robots.txt 获取、缓存和判断。
- `goframe-backend/internal/crawler/robots_test.go`：robots 离线测试。
- `goframe-backend/internal/crawler/extractor.go`：DOM 正文提取、HTML 清洗和网页元数据识别。
- `goframe-backend/internal/crawler/extractor_test.go`：正文提取测试。
- `goframe-backend/internal/crawler/adapters.go`：来源适配器接口、注册和 Feed 系列映射。
- `goframe-backend/internal/crawler/adapters_test.go`：五类来源解析测试。
- `goframe-backend/internal/crawler/pipeline.go`：统一文章处理管线。
- `goframe-backend/internal/crawler/pipeline_test.go`：回退、状态和字段生成测试。
- `goframe-backend/internal/crawler/deduplicate.go`：多级去重。
- `goframe-backend/internal/crawler/deduplicate_test.go`：多级去重测试。
- `goframe-backend/internal/crawler/integration_test.go`：多来源本地抓取集成测试。
- `goframe-backend/internal/crawler/testdata/rss.xml`：RSS fixture。
- `goframe-backend/internal/crawler/testdata/atom.xml`：Atom fixture。
- `goframe-backend/internal/crawler/testdata/arxiv.xml`：Arxiv fixture。
- `goframe-backend/internal/crawler/testdata/github_releases.xml`：GitHub Release fixture。
- `goframe-backend/internal/crawler/testdata/huggingface_papers.xml`：HuggingFace Papers fixture。
- `goframe-backend/internal/crawler/testdata/article_zh.html`：中文正文 fixture。
- `goframe-backend/internal/crawler/testdata/article_en.html`：英文正文 fixture。
- `goframe-backend/internal/config/config_test.go`：通用来源配置与旧 RSS 兼容测试。
- `goframe-backend/internal/logic/harness/crawler_test.go`：来源失败隔离与状态持久化编排测试。
- `shared/sql/migrations/20260606_production_crawler.sql`：已有数据库向前迁移。

### 修改文件

- `goframe-backend/go.mod`、`goframe-backend/go.sum`：增加 robots.txt 与 SQL mock 测试依赖。
- `goframe-backend/internal/crawler/rss.go`：迁移或删除已被新组件替代的旧职责，保留 mock fixture 兼容。
- `goframe-backend/internal/config/config.go`：通用来源和抓取策略配置，兼容 `rss.sources`。
- `goframe-backend/internal/model/model.go`：扩展 Article，增加 CrawlSourceRun。
- `goframe-backend/internal/store/mysql.go`：写入完整 Article 和来源运行记录。
- `goframe-backend/internal/store/mysql_test.go`：SQL 写入契约测试。
- `goframe-backend/internal/logic/harness/harness.go`：使用统一 Crawler，持久化来源运行结果，只发送可处理文章。
- `shared/sql/init.sql`：新环境完整 schema。
- `goframe-backend/manifest/config/config.yaml`：默认抓取策略和 mock 来源。
- `shared/config/e2e.config.yaml`：E2E 通用来源配置。
- `shared/config/rss_sources.example.yaml`：改为多来源示例并说明兼容格式。
- `.env.example`：抓取器环境变量。
- `README.md`：多来源、回退、migration 和测试说明。
- `scripts/smoke_e2e.ps1`：重置和验证 `crawl_source_runs`。
- `scripts/integration_test.ps1`：显式运行离线抓取测试和 schema 验证。

## Task 1：统一类型、URL 规范化、哈希和语言识别

**文件：**

- 新增：`goframe-backend/internal/crawler/types.go`
- 新增：`goframe-backend/internal/crawler/normalize.go`
- 新增：`goframe-backend/internal/crawler/normalize_test.go`
- 新增：`goframe-backend/internal/crawler/language.go`
- 新增：`goframe-backend/internal/crawler/language_test.go`
- 新增：`goframe-backend/internal/crawler/errors.go`
- 新增：`goframe-backend/internal/crawler/errors_test.go`

- [ ] **Step 1：编写 URL 规范化失败测试**

在 `normalize_test.go` 添加表驱动测试，至少断言：

```go
func TestNormalizeURL(t *testing.T) {
    got, err := NormalizeURL("HTTPS://Example.COM:443/a/../post?utm_source=x&b=2&a=1#section")
    if err != nil {
        t.Fatal(err)
    }
    if got != "https://example.com/post?a=1&b=2" {
        t.Fatalf("got %q", got)
    }
}

func TestNormalizeURLRejectsUnsupportedScheme(t *testing.T) {
    _, err := NormalizeURL("ftp://example.com/file")
    if !errors.Is(err, ErrInvalidURL) {
        t.Fatalf("got %v", err)
    }
}
```

- [ ] **Step 2：运行测试并确认失败**

运行：

```powershell
cd goframe-backend
go test ./internal/crawler -run 'TestNormalizeURL' -v
```

预期：编译失败，提示 `NormalizeURL` 或 `ErrInvalidURL` 未定义。

- [ ] **Step 3：实现统一类型与规范化**

在 `types.go` 定义：

```go
type SourceType string

const (
    SourceTypeFeed              SourceType = "feed"
    SourceTypeArxiv             SourceType = "arxiv"
    SourceTypeGitHubRelease     SourceType = "github_release"
    SourceTypeHuggingFacePapers SourceType = "huggingface_papers"
    SourceTypeMock              SourceType = "mock"
)

type RawEntry struct {
    SourceName    string
    SourceType    SourceType
    ExternalID    string
    URL           string
    Title         string
    SourceContent string
    Author        string
    PublishedAt   string
    Tags          []string
    RawPayload    any
}

type Source struct {
    Name     string
    Type     SourceType
    URL      string
    Enabled  bool
    MaxItems int
}

type ErrorType string

type CrawlError struct {
    Type       ErrorType
    Message    string
    HTTPStatus int
    Retryable  bool
    Err        error
}
```

在 `normalize.go` 实现：

```go
func NormalizeURL(raw string) (string, error)
func NormalizeTitle(raw string) string
func SHA256Hex(raw string) string
func StableArticleID(entry RawEntry, normalizedURL, titleHash, contentHash string) string
```

URL 规范化必须使用 `net/url`，删除 `utm_*`、`fbclid`、`gclid`，排序查询参数，移除 fragment、默认端口和路径中的 `.`/`..`。

- [ ] **Step 4：实现语言识别和错误分类测试**

在 `language_test.go` 断言：

```go
func TestDetectLanguage(t *testing.T) {
    cases := map[string]string{
        "这是一个中文正文，包含足够多的中文字符。": "zh",
        "This is a sufficiently long English article body.": "en",
        "这是中文 and this is English mixed together": "mixed",
        "123": "unknown",
    }
    for input, want := range cases {
        if got := DetectLanguage(input); got != want {
            t.Fatalf("%q: got %q want %q", input, got, want)
        }
    }
}
```

在 `errors_test.go` 断言 `context.DeadlineExceeded`、`net.DNSError`、HTTP `429`、`404`、`503` 分别映射到稳定错误类型。

- [ ] **Step 5：运行新增测试并确认失败**

运行：

```powershell
cd goframe-backend
go test ./internal/crawler -run 'TestDetectLanguage|TestClassify' -v
```

预期：编译失败，提示 `DetectLanguage` 或分类函数未定义。

- [ ] **Step 6：实现语言识别和错误分类**

在 `language.go` 实现：

```go
func DetectLanguage(text string) string
```

按有效中文字符和英文字母比例返回 `zh`、`en`、`mixed`、`unknown`。

在 `errors.go` 定义设计文档中的错误常量，并实现：

```go
func ClassifyError(err error, statusCode int) *CrawlError
func NewCrawlError(errorType ErrorType, message string, status int, retryable bool, err error) *CrawlError
```

- [ ] **Step 7：运行聚焦测试**

运行：

```powershell
cd goframe-backend
go test ./internal/crawler -run 'TestNormalizeURL|TestDetectLanguage|TestClassify' -v
```

预期：全部通过。

- [ ] **Step 8：提交**

```powershell
git add -- goframe-backend/internal/crawler/types.go goframe-backend/internal/crawler/normalize.go goframe-backend/internal/crawler/normalize_test.go goframe-backend/internal/crawler/language.go goframe-backend/internal/crawler/language_test.go goframe-backend/internal/crawler/errors.go goframe-backend/internal/crawler/errors_test.go
git commit -m "feat: add crawler normalization and classification"
```

## Task 2：可配置 HTTP 客户端、限速、重试和 robots.txt

**文件：**

- 新增：`goframe-backend/internal/crawler/http_client.go`
- 新增：`goframe-backend/internal/crawler/http_client_test.go`
- 新增：`goframe-backend/internal/crawler/robots.go`
- 新增：`goframe-backend/internal/crawler/robots_test.go`
- 修改：`goframe-backend/go.mod`
- 修改：`goframe-backend/go.sum`

- [ ] **Step 1：添加 HTTP 策略失败测试**

使用 `httptest.Server` 添加测试，验证：

- 请求包含配置的 User-Agent。
- `503` 两次后 `200` 会重试并最终成功。
- `404` 不重试。
- 同一域名连续请求会调用限速等待，不同域名互不阻塞。
- 超过最大响应大小返回 `response_too_large`。
- `context` 取消会立即停止退避。

通过注入等待函数避免真实休眠：

```go
type WaitFunc func(context.Context, time.Duration) error

client := NewHTTPClient(HTTPOptions{
    UserAgent:        "KnowMateCrawler/1.0",
    Timeout:          time.Second,
    RetryTimes:       3,
    BackoffBase:      time.Millisecond,
    MaxResponseBytes: 1024,
    Wait: func(context.Context, time.Duration) error {
        waits++
        return nil
    },
})
```

- [ ] **Step 2：运行测试并确认失败**

运行：

```powershell
cd goframe-backend
go test ./internal/crawler -run 'TestHTTPClient' -v
```

预期：编译失败，提示 `NewHTTPClient` 或 `HTTPOptions` 未定义。

- [ ] **Step 3：实现 HTTP 客户端**

实现：

```go
type HTTPOptions struct {
    UserAgent        string
    Timeout          time.Duration
    RetryTimes       int
    BackoffBase      time.Duration
    PerHostInterval  time.Duration
    MaxResponseBytes int64
    Wait             WaitFunc
    Transport        http.RoundTripper
}

type Response struct {
    URL         string
    StatusCode  int
    ContentType string
    Body        []byte
}

func NewHTTPClient(options HTTPOptions) *HTTPClient
func (c *HTTPClient) Get(ctx context.Context, rawURL string) (Response, error)
```

实现要求：

- 每个域名单独记录上次请求时间。
- `429`、`5xx`、超时和连接错误可重试。
- 优先尊重 `Retry-After`。
- 使用 `io.LimitReader` 读取最大大小加一字节，准确识别超限。
- 所有最终错误返回 `*CrawlError`。

- [ ] **Step 4：添加 robots.txt 失败测试**

在 `robots_test.go` 使用一个本地 Server，断言：

```go
func TestRobotsManagerDeniesAndCaches(t *testing.T) {
    // /robots.txt 返回 Disallow: /private
    // 连续两次检查只请求一次 robots.txt
    // /private/a 返回 allowed=false，/public/a 返回 allowed=true
}

func TestRobotsManagerTreats404AsAllowed(t *testing.T) {
    // robots.txt 404 时允许正文请求
}
```

- [ ] **Step 5：运行 robots 测试并确认失败**

运行：

```powershell
cd goframe-backend
go test ./internal/crawler -run 'TestRobotsManager' -v
```

预期：编译失败，提示 `RobotsManager` 未定义。

- [ ] **Step 6：查询并添加 robots 依赖**

使用已确认的 API：

```go
allowed := grobotstxt.AgentAllowed(robotsText, userAgent, targetURL)
```

运行：

```powershell
cd goframe-backend
go get github.com/jimsmart/grobotstxt
```

- [ ] **Step 7：实现 robots 管理器**

实现：

```go
type RobotsManager struct {
    client    *HTTPClient
    userAgent string
    ttl       time.Duration
}

func NewRobotsManager(client *HTTPClient, userAgent string, ttl time.Duration) *RobotsManager
func (m *RobotsManager) Allowed(ctx context.Context, targetURL string) (bool, error)
```

缓存键为 `scheme://host`；`404` 视为允许；明确禁止返回 `robots_denied`；robots 临时获取失败按设计默认允许，但返回可记录诊断错误。

- [ ] **Step 8：运行聚焦测试**

运行：

```powershell
cd goframe-backend
go test ./internal/crawler -run 'TestHTTPClient|TestRobotsManager' -v
```

预期：全部通过。

- [ ] **Step 9：提交**

```powershell
git add -- goframe-backend/go.mod goframe-backend/go.sum goframe-backend/internal/crawler/http_client.go goframe-backend/internal/crawler/http_client_test.go goframe-backend/internal/crawler/robots.go goframe-backend/internal/crawler/robots_test.go
git commit -m "feat: add crawler http policy and robots"
```

## Task 3：HTML 清洗、正文提取和网页元数据识别

**文件：**

- 新增：`goframe-backend/internal/crawler/extractor.go`
- 新增：`goframe-backend/internal/crawler/extractor_test.go`
- 新增：`goframe-backend/internal/crawler/testdata/article_zh.html`
- 新增：`goframe-backend/internal/crawler/testdata/article_en.html`

- [ ] **Step 1：添加正文提取失败测试**

fixture 必须包含导航、脚本、侧栏、正文、作者和发布时间。测试断言：

```go
func TestExtractDocumentPrefersArticleAndRemovesNoise(t *testing.T) {
    doc, err := ExtractDocument(loadFixture(t, "article_en.html"), "https://example.test/post")
    if err != nil {
        t.Fatal(err)
    }
    if strings.Contains(doc.CleanText, "navigation") || strings.Contains(doc.CleanText, "alert(") {
        t.Fatalf("noise remained: %q", doc.CleanText)
    }
    if !strings.Contains(doc.CleanText, "Primary article paragraph") {
        t.Fatalf("body missing: %q", doc.CleanText)
    }
    if doc.Author != "Fixture Author" || doc.PublishedAt == "" {
        t.Fatalf("metadata missing: %#v", doc)
    }
}
```

另加无有效正文时返回 `content_extraction_error` 的测试。

- [ ] **Step 2：运行测试并确认失败**

运行：

```powershell
cd goframe-backend
go test ./internal/crawler -run 'TestExtractDocument' -v
```

预期：编译失败，提示 `ExtractDocument` 未定义。

- [ ] **Step 3：实现 DOM 正文提取**

使用 `golang.org/x/net/html` 实现：

```go
type ExtractedDocument struct {
    CleanText   string
    Title       string
    Author      string
    PublishedAt string
}

func ExtractDocument(rawHTML []byte, pageURL string) (ExtractedDocument, error)
func CleanHTMLFragment(raw string) string
```

实现要求：

- 移除设计文档列出的噪声节点和隐藏节点。
- 优先 `article`、其次 `main`、最后按段落文本长度减链接文本长度选择容器。
- 保留段落、列表和代码块的可读换行。
- 从 meta、Open Graph 和 JSON-LD 补齐标题、作者和发布时间。
- 正文低于可配置最小有效长度时返回分类错误。

- [ ] **Step 4：运行聚焦测试**

运行：

```powershell
cd goframe-backend
go test ./internal/crawler -run 'TestExtractDocument|TestCleanHTMLFragment' -v
```

预期：全部通过。

- [ ] **Step 5：提交**

```powershell
git add -- goframe-backend/internal/crawler/extractor.go goframe-backend/internal/crawler/extractor_test.go goframe-backend/internal/crawler/testdata/article_zh.html goframe-backend/internal/crawler/testdata/article_en.html
git commit -m "feat: add crawler content extraction"
```

## Task 4：五类来源适配器与本地 fixture

**文件：**

- 新增：`goframe-backend/internal/crawler/adapters.go`
- 新增：`goframe-backend/internal/crawler/adapters_test.go`
- 新增：`goframe-backend/internal/crawler/testdata/rss.xml`
- 新增：`goframe-backend/internal/crawler/testdata/atom.xml`
- 新增：`goframe-backend/internal/crawler/testdata/arxiv.xml`
- 新增：`goframe-backend/internal/crawler/testdata/github_releases.xml`
- 新增：`goframe-backend/internal/crawler/testdata/huggingface_papers.xml`
- 修改：`goframe-backend/internal/crawler/rss.go`

- [ ] **Step 1：添加适配器失败测试**

使用 Task 1 已定义的 `Source`，定义期望接口：

```go
type SourceAdapter interface {
    Type() SourceType
    Parse(source Source, payload []byte) ([]RawEntry, error)
}
```

测试每个 fixture 至少断言来源类型、外部 ID、URL、标题、来源正文、作者、发布时间、标签和可 JSON 序列化的 `RawPayload`。

- [ ] **Step 2：运行测试并确认失败**

运行：

```powershell
cd goframe-backend
go test ./internal/crawler -run 'TestFeedAdapter|TestArxivAdapter|TestGitHubReleaseAdapter|TestHuggingFaceAdapter' -v
```

预期：编译失败，提示适配器未定义。

- [ ] **Step 3：实现适配器**

实现：

```go
func NewAdapter(sourceType SourceType) (SourceAdapter, error)
```

规则：

- `feed`：使用 `gofeed`，同时支持 RSS 和 Atom。
- `arxiv`：解析 Atom，作者合并为稳定字符串，论文摘要作为来源正文。
- `github_release`：解析 Releases Atom，Release notes 作为来源正文。
- `huggingface_papers`：解析 Papers Feed，保留论文 URL、标题、摘要、作者和发布时间。
- `mock`：迁移现有 `mockArticles` 为返回 `RawEntry` 的本地适配器。
- 所有适配器只解析 payload，不主动联网。

- [ ] **Step 4：运行聚焦测试**

运行：

```powershell
cd goframe-backend
go test ./internal/crawler -run 'TestFeedAdapter|TestArxivAdapter|TestGitHubReleaseAdapter|TestHuggingFaceAdapter|TestMockAdapter' -v
```

预期：全部通过。

- [ ] **Step 5：提交**

```powershell
git add -- goframe-backend/internal/crawler/adapters.go goframe-backend/internal/crawler/adapters_test.go goframe-backend/internal/crawler/rss.go goframe-backend/internal/crawler/testdata/rss.xml goframe-backend/internal/crawler/testdata/atom.xml goframe-backend/internal/crawler/testdata/arxiv.xml goframe-backend/internal/crawler/testdata/github_releases.xml goframe-backend/internal/crawler/testdata/huggingface_papers.xml
git commit -m "feat: add crawler source adapters"
```

## Task 5：统一处理管线、回退状态和多级去重

**文件：**

- 新增：`goframe-backend/internal/crawler/pipeline.go`
- 新增：`goframe-backend/internal/crawler/pipeline_test.go`
- 新增：`goframe-backend/internal/crawler/deduplicate.go`
- 新增：`goframe-backend/internal/crawler/deduplicate_test.go`
- 修改：`goframe-backend/internal/model/model.go`

- [ ] **Step 1：添加网页成功与来源正文回退失败测试**

使用本地 Server 测试：

```go
func TestPipelineUsesExtractedWebContent(t *testing.T) {
    // 网页正文成功：
    // FetchStatus=success
    // RawContent 保存 HTML
    // CleanContent 和 Content 保存清洗正文
    // ContentHash、Language、NormalizedURL、URLHash、TitleHash 已生成
}

func TestPipelineFallsBackToSourceContent(t *testing.T) {
    // 网页返回 500 或 robots 禁止：
    // FetchStatus=partial
    // Content 使用清洗后的 SourceContent
    // FetchErrorType 保存稳定类型
}

func TestPipelineFailsWithoutUsableContent(t *testing.T) {
    // 网页失败且来源正文为空：
    // FetchStatus=failed
}
```

- [ ] **Step 2：运行管线测试并确认失败**

运行：

```powershell
cd goframe-backend
go test ./internal/crawler -run 'TestPipeline' -v
```

预期：编译失败，提示 `Pipeline` 或 Article 新字段未定义。

- [ ] **Step 3：扩展 Article 模型并实现管线**

在 `model.Article` 增加设计文档字段，并实现：

```go
type Article struct {
    ID              string
    URL             string
    NormalizedURL   string
    URLHash         string
    Title           string
    NormalizedTitle string
    TitleHash       string
    RawContent      string
    CleanContent    string
    Content         string
    ContentHash     string
    Language        string
    Author          string
    PublishedAt     string
    Source          string
    SourceType      string
    Tags            []string
    FetchStatus     string
    FetchErrorType  string
    FetchError      string
    HTTPStatus      int
    RawPayload      any
    FetchedAt       time.Time
    CreatedAt       time.Time
}

type Pipeline struct {
    http   *HTTPClient
    robots *RobotsManager
}

func NewPipeline(client *HTTPClient, robots *RobotsManager) *Pipeline
func (p *Pipeline) Process(ctx context.Context, entry RawEntry) model.Article
```

字段规则：

- 成功网页正文优先。
- 网页失败时清洗 `SourceContent` 回退为 `partial`。
- 没有可用正文为 `failed`。
- `Content` 始终等于最终发送给 Agent 的清洗正文。
- `RawPayload` 使用可序列化来源原始条目。
- 错误消息写入前限制长度。

- [ ] **Step 4：添加多级去重失败测试**

在 `deduplicate_test.go` 分别构造 URL、标题、正文哈希和 ID 重复，断言保留第一次出现的文章，并跳过 `failed` 文章进入 Agent 可处理集合。

期望 API：

```go
func Deduplicate(articles []model.Article, maxItems int) []model.Article
func Processable(articles []model.Article) []model.Article
```

- [ ] **Step 5：运行去重测试并确认失败**

运行：

```powershell
cd goframe-backend
go test ./internal/crawler -run 'TestDeduplicate|TestProcessable' -v
```

预期：测试失败，因为旧实现只按 ID 去重或 `Processable` 不存在。

- [ ] **Step 6：实现多级去重**

按 `URLHash -> TitleHash -> ContentHash -> ID` 顺序去重，空哈希不参与对应层级比较。`maxItems <= 0` 时不截断。

- [ ] **Step 7：运行聚焦测试**

运行：

```powershell
cd goframe-backend
go test ./internal/crawler -run 'TestPipeline|TestDeduplicate|TestProcessable' -v
```

预期：全部通过。

- [ ] **Step 8：提交**

```powershell
git add -- goframe-backend/internal/model/model.go goframe-backend/internal/crawler/pipeline.go goframe-backend/internal/crawler/pipeline_test.go goframe-backend/internal/crawler/deduplicate.go goframe-backend/internal/crawler/deduplicate_test.go
git commit -m "feat: add crawler processing pipeline"
```

## Task 6：配置模型、环境变量和旧 RSS 配置兼容

**文件：**

- 修改：`goframe-backend/internal/config/config.go`
- 新增：`goframe-backend/internal/config/config_test.go`
- 修改：`goframe-backend/manifest/config/config.yaml`
- 修改：`shared/config/e2e.config.yaml`
- 修改：`shared/config/rss_sources.example.yaml`
- 修改：`.env.example`

- [ ] **Step 1：添加配置失败测试**

测试必须断言：

- 新 `crawler.sources` 可以加载来源类型和来源参数。
- 仅配置旧 `rss.sources` 时会映射为 `feed` 来源。
- 新配置与旧配置同时存在时仅使用新 `crawler.sources`，避免重复抓取。
- 非法或空值会被 `Normalize` 修正。
- `CRAWLER_USER_AGENT` 等环境变量可覆盖 YAML。

期望配置结构：

```go
type SourceConfig struct {
    Name     string `yaml:"name"`
    Type     string `yaml:"type"`
    URL      string `yaml:"url"`
    Enabled  bool   `yaml:"enabled"`
    MaxItems int    `yaml:"max_items"`
}

type CrawlerConfig struct {
    UserAgent                    string         `yaml:"user_agent"`
    RequestTimeoutSeconds        int            `yaml:"request_timeout_seconds"`
    RetryTimes                   int            `yaml:"retry_times"`
    RetryBackoffMilliseconds     int            `yaml:"retry_backoff_milliseconds"`
    PerHostIntervalMilliseconds  int            `yaml:"per_host_interval_milliseconds"`
    MaxResponseBytes             int64          `yaml:"max_response_bytes"`
    RobotsCacheSeconds           int            `yaml:"robots_cache_seconds"`
    SourceMaxItems               int            `yaml:"source_max_items"`
    RunMaxArticles               int            `yaml:"run_max_articles"`
    Sources                      []SourceConfig `yaml:"sources"`
}
```

- [ ] **Step 2：运行测试并确认失败**

运行：

```powershell
cd goframe-backend
go test ./internal/config -v
```

预期：编译或断言失败，因为通用来源和抓取策略配置尚不存在。

- [ ] **Step 3：实现配置兼容和环境变量覆盖**

修改 `Load` 和 `Normalize`：

- 旧 `rss.sources` 仅作为新来源为空时的兼容输入。
- 默认来源为 `mock://sample`、类型 `mock`。
- 补齐设计文档中的安全默认值。
- 使用现有 `strconv` 解析所有整数和 `int64` 环境变量。

- [ ] **Step 4：更新 YAML 与环境变量示例**

配置示例必须包含五类来源，但真实公网来源默认 `enabled: false`。保留旧 `rss.sources` 示例并明确标注仅用于兼容。

- [ ] **Step 5：运行聚焦测试**

运行：

```powershell
cd goframe-backend
go test ./internal/config -v
```

预期：全部通过。

- [ ] **Step 6：提交**

```powershell
git add -- goframe-backend/internal/config/config.go goframe-backend/internal/config/config_test.go goframe-backend/manifest/config/config.yaml shared/config/e2e.config.yaml shared/config/rss_sources.example.yaml .env.example
git commit -m "feat: configure production crawler sources"
```

## Task 7：数据库 migration、完整文章写入和来源运行记录

**文件：**

- 修改：`shared/sql/init.sql`
- 新增：`shared/sql/migrations/20260606_production_crawler.sql`
- 修改：`goframe-backend/internal/model/model.go`
- 修改：`goframe-backend/internal/store/mysql.go`
- 修改：`goframe-backend/internal/store/mysql_test.go`
- 修改：`goframe-backend/go.mod`
- 修改：`goframe-backend/go.sum`

- [ ] **Step 1：添加 Store SQL 契约失败测试**

先增加 `go-sqlmock` 测试依赖：

```powershell
cd goframe-backend
go get github.com/DATA-DOG/go-sqlmock
```

为 Store 增加仅包内测试使用的构造方式：

```go
func newWithDB(db *sql.DB) *Store {
    return &Store{db: db}
}
```

在 `mysql_test.go` 使用当前 API：

```go
db, mock, err := sqlmock.New()
if err != nil {
    t.Fatal(err)
}
defer db.Close()

mock.ExpectExec("INSERT IGNORE INTO articles").
    WithArgs(
        article.ID,
        article.Source,
        article.SourceType,
        article.URL,
        article.NormalizedURL,
        article.URLHash,
        article.Title,
        article.NormalizedTitle,
        article.TitleHash,
        article.Content,
        article.RawContent,
        article.CleanContent,
        article.ContentHash,
        article.Language,
        article.Author,
        article.PublishedAt,
        sqlmock.AnyArg(), // tags JSON
        article.FetchStatus,
        article.FetchErrorType,
        article.FetchError,
        article.HTTPStatus,
        sqlmock.AnyArg(), // raw_payload JSON
        sqlmock.AnyArg(), // raw_json JSON
        article.FetchedAt,
    ).
    WillReturnResult(sqlmock.NewResult(1, 1))
```

测试必须验证：

- `InsertArticle` 写入 `published_at`、原始内容、清洗内容、URL/标题/内容哈希、语言和抓取状态。
- 唯一冲突返回 `inserted=false` 而不是 error。
- `UpsertCrawlSourceRun` 可以先写 `running`，再更新为 `success/partial/failed`。

- [ ] **Step 2：运行 Store 测试并确认失败**

运行：

```powershell
cd goframe-backend
go test ./internal/store -run 'TestInsertArticle|TestUpsertCrawlSourceRun' -v
```

预期：编译或 SQL expectation 失败，因为新字段和方法未实现。

- [ ] **Step 3：实现模型和 Store 写入**

在 `model.go` 增加：

```go
type CrawlSourceRun struct {
    RunID        string
    SourceName   string
    SourceType   string
    Status       string
    ErrorType    string
    ErrorMessage string
    HTTPStatus   int
    ItemsFound   int
    ItemsSaved   int
    ItemsPartial int
    ItemsFailed  int
    StartedAt    time.Time
    FinishedAt   *time.Time
}
```

在 Store 实现：

```go
func (s *Store) InsertArticle(ctx context.Context, article model.Article) (bool, error)
func (s *Store) UpsertCrawlSourceRun(ctx context.Context, run model.CrawlSourceRun) error
```

`InsertArticle` 继续使用 `INSERT IGNORE`，任何一个唯一哈希冲突都视为已有文章。

- [ ] **Step 4：编写 init.sql 与 migration**

`init.sql` 增加最新字段、索引和 `crawl_source_runs`。

migration 必须：

1. 使用 `ADD COLUMN` 增加可空字段或安全默认值。
2. 保守回填已有记录：`normalized_url=NULLIF(url,'')`，`url_hash=SHA2(normalized_url,256)`，`normalized_title=LOWER(TRIM(REGEXP_REPLACE(title,'[[:space:]]+',' ')))`，`title_hash=SHA2(normalized_title,256)`，`content_hash=SHA2(TRIM(content),256)`。完整 URL 规范化只对新抓取记录执行。
3. 每组重复哈希仅保留最早记录的哈希，后续重复项设为 `NULL`。
4. 增加唯一哈希索引和查询索引。
5. 创建 `crawl_source_runs`。
6. 可重复执行时不因已存在列、索引或表而失败；如果 MySQL 8 DDL 限制导致不能直接幂等，使用 `information_schema` 检查和动态 SQL。

- [ ] **Step 5：运行聚焦测试与 SQL 静态检查**

运行：

```powershell
cd goframe-backend
go test ./internal/store -v
cd ..
Select-String -Path shared/sql/init.sql,shared/sql/migrations/20260606_production_crawler.sql -Pattern "crawl_source_runs|content_hash|url_hash|title_hash|fetch_status"
```

预期：Store 测试通过，SQL 中包含所有必要字段和表。

- [ ] **Step 6：提交**

```powershell
git add -- goframe-backend/go.mod goframe-backend/go.sum goframe-backend/internal/model/model.go goframe-backend/internal/store/mysql.go goframe-backend/internal/store/mysql_test.go shared/sql/init.sql shared/sql/migrations/20260606_production_crawler.sql
git commit -m "feat: persist crawler content and source runs"
```

## Task 8：多来源 Crawler 与 Harness 失败隔离

**文件：**

- 新增：`goframe-backend/internal/crawler/crawler.go`
- 新增：`goframe-backend/internal/crawler/integration_test.go`
- 修改：`goframe-backend/internal/logic/harness/harness.go`
- 新增：`goframe-backend/internal/logic/harness/crawler_test.go`

- [ ] **Step 1：添加抓取器离线集成失败测试**

启动一个 `httptest.Server`，提供：

- `/rss.xml`、`/atom.xml`、`/arxiv.xml`、`/github.xml`、`/huggingface.xml`
- `/robots.txt`
- `/article/zh`、`/article/en`
- `/article/denied`
- `/source/fail`

期望 API：

```go
type SourceResult struct {
    Source       Source
    Status       string
    ErrorType    string
    ErrorMessage string
    HTTPStatus   int
    Articles     []model.Article
    ItemsFound   int
    ItemsPartial int
    ItemsFailed  int
}

type Options struct {
    HTTP            HTTPOptions
    RobotsCacheTTL  time.Duration
    SourceMaxItems  int
}

type Crawler struct {
    adapters       map[SourceType]SourceAdapter
    http           *HTTPClient
    pipeline       *Pipeline
    sourceMaxItems int
}

func New(options Options) *Crawler
func (c *Crawler) FetchSource(ctx context.Context, source Source) SourceResult
```

测试断言五类来源均产出统一 Article，一个来源失败不会影响单独调用其他来源，网页失败和 robots 禁止会回退为 `partial`。

- [ ] **Step 2：运行集成测试并确认失败**

运行：

```powershell
cd goframe-backend
go test ./internal/crawler -run 'TestCrawlerIntegration' -v
```

预期：编译失败，提示 `Crawler` 或 `FetchSource` 未定义。

- [ ] **Step 3：实现多来源 Crawler**

实现职责：

1. 处理 `mock://` 来源或用 HTTP 客户端请求来源 payload。
2. 根据来源类型选择适配器。
3. 限制单来源条目数量。
4. 对每条 RawEntry 调用 Pipeline。
5. 汇总来源级状态、错误和计数。
6. 单条失败不会中断同一来源其他条目。

- [ ] **Step 4：添加 Harness 失败隔离测试**

为避免真实 MySQL 和 Agent，先把 Harness 依赖收窄为内部接口：

```go
type articleStore interface {
    InsertArticle(context.Context, model.Article) (bool, error)
    UpsertCrawlSourceRun(context.Context, model.CrawlSourceRun) error
    InsertPost(context.Context, model.Post) error
    InsertFeedbackLog(context.Context, model.FeedbackLog) error
    InsertRunLog(context.Context, model.RunLog) error
    InsertUserProfileSnapshot(context.Context, string, map[string]string, string) error
    InsertMcpCallLogs(context.Context, []model.McpCallLog) error
    LatestUserProfileSnapshot(context.Context, string) (map[string]string, error)
}

type sourceCrawler interface {
    FetchSource(context.Context, crawler.Source) crawler.SourceResult
}
```

测试注入一个首来源失败、次来源成功的 fake crawler，断言：

- 两个来源均被调用。
- 两条 `crawl_source_runs` 均写入。
- 成功来源文章仍被保存。
- 仅 `success/partial` 新文章进入后续 Agent 列表。
- 所有来源失败时 `RunArticles` 标记失败并且不调用 Agent。

- [ ] **Step 5：运行 Harness 测试并确认失败**

运行：

```powershell
cd goframe-backend
go test ./internal/logic/harness -run 'TestFetchSources|TestRunArticlesAllSourcesFailed' -v
```

预期：编译或断言失败，因为 Harness 仍绑定 `*store.Store` 和 `*RSSCrawler`。

- [ ] **Step 6：重构 Harness 编排**

修改 `New` 创建统一 `crawler.Crawler`；新增测试构造器或依赖注入构造器。更新 `fetchArticles`：

- 每个启用来源开始时写 `running`。
- 抓取结束后写最终 `success/partial/failed`。
- 继续处理后续来源。
- 汇总后运行多级去重。
- 保存 failed 文章用于诊断，但只将 `crawler.Processable(newArticles)` 发送给 Python Agent。
- 所有来源失败且没有可处理文章时将总运行标记为失败。

- [ ] **Step 7：运行聚焦测试**

运行：

```powershell
cd goframe-backend
go test ./internal/crawler -run 'TestCrawlerIntegration' -v
go test ./internal/logic/harness -run 'TestFetchSources|TestRunArticlesAllSourcesFailed' -v
```

预期：全部通过。

- [ ] **Step 8：提交**

```powershell
git add -- goframe-backend/internal/crawler/crawler.go goframe-backend/internal/crawler/integration_test.go goframe-backend/internal/logic/harness/harness.go goframe-backend/internal/logic/harness/crawler_test.go
git commit -m "feat: isolate crawler source failures"
```

## Task 9：README、配置说明和集成脚本

**文件：**

- 修改：`README.md`
- 修改：`scripts/smoke_e2e.ps1`
- 修改：`scripts/integration_test.ps1`
- 修改：`shared/config/README.md`

- [ ] **Step 1：更新 README**

README 必须说明：

- 支持五类来源。
- `crawler.sources` 配置和旧 `rss.sources` 兼容策略。
- robots、限速、User-Agent、超时、重试和指数退避。
- 网页正文失败时回退来源正文并标记 `partial`。
- `success/partial/failed` 与错误分类含义。
- 原始内容、清洗内容和 `crawl_source_runs` 的数据库位置。
- 新环境使用 `init.sql`，已有环境执行 migration。
- 抓取单元和集成测试不访问公网。

- [ ] **Step 2：更新 E2E smoke**

`scripts/smoke_e2e.ps1`：

- 重置时加入 `crawl_source_runs`。
- 运行后断言 `crawl_source_runs` 至少有一条当前 `run_id` 记录。
- 断言新文章至少一个 `fetch_status IN ('success','partial')`，且 `content_hash` 非空。

- [ ] **Step 3：更新集成脚本**

`scripts/integration_test.ps1` 在 Go 全量测试前明确运行：

```powershell
go test ./internal/crawler -run 'TestCrawlerIntegration' -v
```

当 Docker 可用时执行 migration 验证。PowerShell 使用管道传递 SQL：

```powershell
$migration = Get-Content -Raw (Join-Path $Root "shared/sql/migrations/20260606_production_crawler.sql")
$migration | docker compose exec -T mysql mysql "-uroot" "-p$RootPassword" knowledge_post_agent
```

不得依赖 Bash 重定向。

- [ ] **Step 4：运行文档和脚本静态验证**

运行：

```powershell
rg -n "crawl_source_runs|fetch_status|robots|HuggingFace|GitHub Release|Arxiv" README.md shared/config/README.md scripts/integration_test.ps1 scripts/smoke_e2e.ps1
git diff --check -- README.md shared/config/README.md scripts/integration_test.ps1 scripts/smoke_e2e.ps1
```

预期：必要说明和断言均存在，`git diff --check` 无输出。

- [ ] **Step 5：提交**

```powershell
git add -- README.md shared/config/README.md scripts/integration_test.ps1 scripts/smoke_e2e.ps1
git commit -m "docs: document production crawler workflow"
```

## Task 10：全量验证与需求审计

**文件：**

- 仅修改验证发现确实需要修复的本任务文件。

- [ ] **Step 1：格式化并检查差异**

运行：

```powershell
cd goframe-backend
gofmt -w internal/crawler internal/config/config.go internal/config/config_test.go internal/model/model.go internal/store/mysql.go internal/store/mysql_test.go internal/logic/harness/harness.go internal/logic/harness/crawler_test.go
cd ..
git diff --check
git status --short
```

预期：`git diff --check` 无输出；确认没有覆盖与本任务无关的现有改动。

- [ ] **Step 2：运行 Go 全量测试**

运行：

```powershell
cd goframe-backend
go test ./... -count=1
```

预期：全部通过，抓取测试无公网请求。

- [ ] **Step 3：运行离线抓取集成测试**

运行：

```powershell
cd goframe-backend
go test ./internal/crawler -run 'TestCrawlerIntegration' -count=1 -v
```

预期：五类来源、robots、回退和来源失败隔离全部通过。

- [ ] **Step 4：验证 Compose 配置**

运行：

```powershell
docker compose config
```

预期：退出码为 0。

- [ ] **Step 5：运行 MySQL migration 验证**

Docker 可用时：

```powershell
docker compose up -d mysql
$rootPassword = if ($env:MYSQL_ROOT_PASSWORD) { $env:MYSQL_ROOT_PASSWORD } else { "rootpass" }
$sql = Get-Content -Raw shared/sql/migrations/20260606_production_crawler.sql
$sql | docker compose exec -T mysql mysql "-uroot" "-p$rootPassword" knowledge_post_agent
$sql | docker compose exec -T mysql mysql "-uroot" "-p$rootPassword" knowledge_post_agent
docker compose exec -T mysql mysql "-uroot" "-p$rootPassword" knowledge_post_agent -e "SHOW CREATE TABLE articles; SHOW CREATE TABLE crawl_source_runs;"
```

预期：migration 连续执行两次均成功；表和索引存在。若 Docker 或凭据不可用，记录精确阻塞原因，不声称 migration 已验证。

- [ ] **Step 6：运行项目集成检查**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\integration_test.ps1
```

预期：Go、Python、MCP 测试和 E2E smoke 全部通过。若当前工作区其他未完成改动导致失败，记录与本任务无关的具体失败，不回退用户改动。

- [ ] **Step 7：逐项审计设计验收标准**

对照 `docs/superpowers/specs/2026-06-06-production-crawler-content-processing-design.md`，确认：

- 五类来源均有 fixture 和集成覆盖。
- URL、标题和内容哈希多级去重存在。
- robots、限速、User-Agent、超时、重试、指数退避存在。
- 原始内容、清洗内容、语言、状态和错误持久化。
- 单来源失败隔离。
- migration、索引、配置示例和 README 完整。

- [ ] **Step 8：归档验证修复**

验证产生的修复归入对应 Task 的文件范围和提交；不要创建会一次性暂存多个预存修改文件的兜底提交。最终运行 `git status --short`，列出仍未提交的本任务文件和工作区原有文件，确认二者均未被误回退。
