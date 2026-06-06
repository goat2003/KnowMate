# 生产级抓取器与正文处理流程设计

日期：2026-06-06

## 目标

完善 GoFrame 后端的内容抓取与正文处理流程，使其能够稳定处理真实内容源，同时保持本地开发和自动化测试完全不依赖公网。

本设计覆盖：

- RSS、Atom、Arxiv、GitHub Release、HuggingFace Papers 数据源
- URL 规范化
- 基于 URL、标题和内容哈希的多级去重
- robots.txt、按域名请求频率限制
- User-Agent、超时、重试和指数退避
- 网页正文提取和 HTML 清洗
- 发布时间、作者和来源识别
- 中文与英文内容识别
- 抓取失败原因分类
- 单个来源失败隔离
- 原始内容、清洗内容和抓取状态持久化
- 数据库 migration、查询索引和去重索引
- 本地 fixture 单元测试与抓取集成测试
- 配置示例和 README 更新

## 已确认决策

- 使用“统一抓取管线 + 来源适配器”架构。
- 新增 `crawl_source_runs` 表，持久化来源级抓取状态和失败原因。
- `articles` 表保留文章级 `fetch_status`、`fetch_error` 和 `fetch_error_type`。
- 优先抓取文章链接网页并提取正文。
- 网页抓取失败时回退使用 Feed 或 API 提供的正文、摘要，并将文章标记为 `partial`。
- robots.txt 禁止抓取网页时不绕过限制，回退来源正文并记录 `robots_denied`。
- Arxiv、GitHub Release 和 HuggingFace Papers 保留 Feed 或 API 原始内容作为回退。
- 多级去重顺序为规范化 URL、规范化标题、清洗正文 SHA-256、稳定 `article_uid`。
- 单个来源失败不会终止其他来源。
- 自动化测试全部使用本地 fixture 和 `httptest.Server`，不访问公网。
- 正文提取使用通用 DOM 规则，不引入浏览器渲染和站点专用解析规则。

## 现状与问题

当前 GoFrame 抓取链路集中在 `goframe-backend/internal/crawler/rss.go`：

- 真实来源仅通过 `gofeed` 抓取 RSS 或 Atom。
- 文章正文直接使用 Feed 的 `Content` 或 `Description`。
- 去重仅按 `article_uid`。
- 请求策略未统一配置 User-Agent、超时、重试、指数退避和响应大小限制。
- 未检查 robots.txt，也没有按域名限速。
- 未提取网页正文和清洗 HTML。
- 未识别内容语言，也没有统一失败类型。
- 单个来源失败虽然不会终止循环，但失败信息仅存在于运行步骤中，无法按来源持久查询。
- `articles.published_at` 已存在，但当前文章写入语句未写入该字段。
- `raw_json` 保存的是归一化后的 Article，而不是来源返回的原始条目内容。

## 方案对比

### 方案一：统一抓取管线 + 来源适配器

每种来源只负责把来源响应解析成统一的原始条目，公共管线负责网络策略、正文处理、去重和持久化字段生成。

优点：

- 公共行为一致，避免每个来源重复实现 robots、重试、清洗和去重。
- 来源适配器可以独立测试。
- 新增来源时只需实现适配器。
- 单源失败隔离和错误分类更清晰。

这是选定方案。

### 方案二：每个来源独立实现完整流程

实现初期文件较少，但会重复请求、清洗、语言识别和去重逻辑，难以保证不同来源行为一致，因此不采用。

### 方案三：引入外部爬虫框架

外部框架通常包含调度、持久队列、浏览器渲染和站点规则，能力完整但会明显增加依赖、部署和迁移成本，不符合当前项目规模，因此不采用。

## 总体架构

```text
配置中的来源
  -> SourceAdapter
  -> RawEntry
  -> 统一 FetchPipeline
     -> URL 规范化
     -> robots.txt 检查
     -> 按域名限速
     -> HTTP 请求、重试和指数退避
     -> 网页正文提取和 HTML 清洗
     -> 元数据与语言识别
     -> 内容哈希和文章状态生成
  -> 单次运行内多级去重
  -> 数据库跨运行去重
  -> articles + crawl_source_runs
  -> 仅将 success/partial 文章发送给 Python Agent
```

## 组件边界

### 来源适配器

来源适配器负责：

- 请求或读取来源列表响应。
- 把来源条目转换为统一 `RawEntry`。
- 保留来源返回的原始条目数据。
- 提供来源名称、来源类型、候选 URL、标题、摘要、正文、作者、发布时间和标签。

来源适配器不负责：

- 网页正文抓取。
- robots.txt。
- 通用请求重试和限速。
- HTML 清洗。
- 语言识别。
- 多级去重。
- 数据库写入。

计划支持的来源类型：

- `feed`：RSS 与 Atom，继续使用 `gofeed`。
- `arxiv`：解析 Arxiv Atom Feed。
- `github_release`：解析 GitHub Releases Atom Feed。
- `huggingface_papers`：解析 HuggingFace Papers Feed。
- `mock`：保留现有本地演示数据。

RSS 和 Atom 使用同一个 `feed` 适配器，由解析器识别具体格式。Arxiv、GitHub Release 和 HuggingFace Papers 使用独立适配器，即使底层格式也是 Atom 或 RSS，仍保留独立来源类型和元数据映射规则。

### 统一 HTTP 客户端

统一 HTTP 客户端负责：

- 设置可配置 User-Agent。
- 设置请求超时。
- 限制最大响应大小。
- 识别可重试错误。
- 对超时、连接错误、HTTP `429` 和 `5xx` 执行指数退避重试。
- 解析 `Retry-After`，存在时优先使用服务端指定等待时间。
- 按域名执行最小请求间隔。
- 为 robots.txt 提供相同的超时和响应大小保护。

HTTP 客户端不重试：

- robots.txt 明确禁止。
- 无效 URL。
- 普通 HTTP `4xx`。
- 不支持的内容类型。
- 响应超过大小限制。
- 已被调用方取消的上下文。

### robots.txt 管理器

robots.txt 管理器按 `scheme + host` 缓存规则，并使用配置中的 User-Agent 判断文章 URL 是否允许抓取。

行为规则：

- 明确禁止：不抓网页，返回 `robots_denied`，允许回退来源正文。
- robots.txt 为 `404`：视为没有限制。
- robots.txt 临时请求失败：记录错误，但允许按照配置的保守策略继续抓取。默认策略为允许抓取并保留诊断信息。
- 缓存仅在进程内生效，避免同一运行中重复请求。

### 正文处理器

正文处理器接收 HTML，输出可供 Agent 使用的纯文本正文。

处理顺序：

1. 验证 Content-Type 是 HTML 或可解析文本。
2. 解析 DOM。
3. 移除 `script`、`style`、`noscript`、`iframe`、`svg`、`nav`、`footer`、`header`、`aside`、表单和隐藏节点。
4. 优先选择 `article` 或 `main`。
5. 没有语义正文节点时，根据段落文本长度与链接文本比例选择正文容器。
6. 保留标题、段落、列表和代码块的可读分隔。
7. 解码 HTML entity，合并连续空白，限制连续空行。
8. 正文为空或低于最小有效长度时返回 `content_extraction_error`。

正文处理器不执行 JavaScript，不处理登录墙，不实现站点专用选择器。

### 元数据与语言识别

字段优先级：

- 标题：网页 Open Graph 或 HTML 标题优先于来源标题时，仅用于补齐空值，不覆盖有效来源标题。
- 作者：来源作者优先，其次使用网页 `meta[name=author]`、Open Graph 或 JSON-LD。
- 发布时间：来源解析时间优先，其次使用网页 Open Graph、Article meta 或 JSON-LD。
- 来源名称：始终使用配置中的来源名称。
- 来源类型：使用适配器类型。

语言识别只区分当前业务需要的主要结果：

- `zh`：中文字符达到有效文本字符的主要比例。
- `en`：拉丁英文字母达到有效文本字符的主要比例。
- `mixed`：中文和英文均达到显著比例。
- `unknown`：正文过短或无法可靠判断。

语言识别使用清洗后的正文；正文不可用时回退标题和来源摘要。

## 统一数据结构

### RawEntry

`RawEntry` 表示来源适配器解析出的候选条目：

```text
source_name
source_type
external_id
url
title
source_content
author
published_at
tags
raw_payload
```

`raw_payload` 保存来源条目的原始 JSON 或 XML 片段，供诊断和未来重新处理。

### Article

内部 `Article` 模型扩展为同时表达来源内容、网页正文和抓取状态：

```text
ID
URL
NormalizedURL
URLHash
Title
NormalizedTitle
RawContent
CleanContent
Content
ContentHash
Language
Author
PublishedAt
Source
SourceType
Tags
FetchStatus
FetchErrorType
FetchError
HTTPStatus
RawPayload
FetchedAt
CreatedAt
```

兼容规则：

- `Content` 继续作为发送给 Python Agent 的字段。
- `Content` 优先等于网页提取的 `CleanContent`。
- 网页正文不可用但来源正文可用时，`Content` 等于清洗后的来源正文。
- `RawContent` 保存未经清洗的网页 HTML；未成功抓取网页时保存来源正文或摘要。
- `RawPayload` 保存来源条目的原始数据，不与 `RawContent` 混用。

## URL 规范化

URL 规范化用于去重，不改变用户可访问的原始 URL 字段。

规范化规则：

- 仅接受绝对 `http` 和 `https` URL。
- scheme 和 host 转为小写。
- 移除默认端口 `:80` 和 `:443`。
- 移除 fragment。
- 清理路径中的 `.` 和 `..`。
- 空路径规范化为 `/`。
- 删除常见追踪参数，例如 `utm_*`、`fbclid`、`gclid`。
- 查询参数按键和值排序。
- 保留可能影响内容的其他查询参数。
- 保留 `http` 与 `https` 差异，不自动强制升级。
- 不自动删除尾部 `/`，避免改变服务端语义。

无效 URL 返回 `invalid_url`。来源正文仍可处理，但无法执行网页正文抓取和 URL 级去重。

## 多级去重

### 单次运行内去重

统一管线按以下顺序保留首次出现的文章：

1. `normalized_url` 完全相同。
2. 规范化标题完全相同。
3. `content_hash` 完全相同。
4. 稳定 `article_uid` 完全相同。

标题规范化规则：

- 去除首尾空白。
- 合并连续空白。
- 转为小写。
- 保留标点，避免过度合并不同标题。

`content_hash` 使用清洗正文的 SHA-256 十六进制字符串。正文不可用时不生成内容哈希。

`article_uid` 根据以下首个可用值稳定生成：

1. 来源类型、来源名称和来源外部 ID。
2. 规范化 URL。
3. 规范化标题与内容哈希组合。

### 数据库跨运行去重

数据库通过唯一索引和插入冲突处理阻止跨任务重复：

- `article_uid` 唯一。
- `url_hash` 唯一，但允许空值。
- `title_hash` 唯一，但允许空值。
- `content_hash` 唯一，但允许空值。

`url_hash` 是规范化 URL 的 SHA-256。`normalized_url` 保留完整值，用于查询和诊断。

`title_hash` 是规范化标题的 SHA-256，用于避免对长标题直接建立唯一索引。

遇到数据库唯一冲突时，该文章被视为已存在，不应导致来源或整个运行失败。

## 抓取状态

### 文章级状态

- `success`：网页正文抓取和提取成功。
- `partial`：网页正文不可用，但来源正文或摘要可用。
- `failed`：来源条目已识别，但没有可供后续 Agent 使用的正文。

只有 `success` 和 `partial` 文章会发送给 Python Agent。`failed` 文章在能够形成稳定身份时仍可保存，用于诊断和后续重试。

### 来源级状态

- `success`：来源请求和解析成功，且没有条目级失败。
- `partial`：来源请求成功，但部分条目处理失败或回退。
- `failed`：来源无法请求、无法解析，或没有产生可处理条目。

来源状态不会决定其他来源是否继续执行。

## 失败原因分类

统一错误类型：

- `invalid_url`
- `robots_denied`
- `rate_limited`
- `timeout`
- `dns_error`
- `connection_error`
- `http_4xx`
- `http_5xx`
- `response_too_large`
- `unsupported_content_type`
- `parse_error`
- `content_extraction_error`
- `database_error`
- `unknown`

错误对象至少包含：

- 稳定错误类型。
- 可读错误消息。
- HTTP 状态码，适用时填写。
- 是否可重试。
- 原始错误作为内部诊断信息。

数据库仅保存稳定错误类型和经过长度限制的可读错误消息，避免无限增长或泄漏响应正文。

## 单来源失败隔离

每个启用来源独立执行：

1. 创建 `crawl_source_runs` 的 `running` 记录。
2. 请求并解析来源。
3. 逐条执行统一处理管线。
4. 保存文章。
5. 更新来源运行状态和统计。

任何来源失败时：

- 更新对应来源运行记录为 `failed`。
- 将失败加入总运行步骤。
- 继续处理后续来源。

整个文章运行只有在以下情况标记为失败：

- 所有启用来源均失败或没有产生可处理文章。
- 数据库或 Python Agent 等全局依赖失败，并且当前流程无法继续。

## 数据库设计

### articles 表变更

新增字段：

```sql
source_type VARCHAR(64) NOT NULL DEFAULT ''
normalized_url VARCHAR(2048) NULL
url_hash CHAR(64) NULL
normalized_title VARCHAR(512) NOT NULL DEFAULT ''
title_hash CHAR(64) NULL
raw_content MEDIUMTEXT NULL
clean_content MEDIUMTEXT NULL
content_hash CHAR(64) NULL
language VARCHAR(16) NOT NULL DEFAULT 'unknown'
fetch_status VARCHAR(32) NOT NULL DEFAULT 'success'
fetch_error_type VARCHAR(64) NOT NULL DEFAULT ''
fetch_error TEXT NULL
http_status INT NULL
raw_payload JSON NULL
fetched_at DATETIME NULL
```

兼容处理：

- 保留 `content`，写入发送给 Agent 的清洗正文。
- 保留 `raw_json` 兼容已有数据和调用方。
- 修复 `InsertArticle`，确保写入 `published_at`。

新增索引：

```sql
UNIQUE KEY uk_articles_url_hash (url_hash)
UNIQUE KEY uk_articles_title_hash (title_hash)
UNIQUE KEY uk_articles_content_hash (content_hash)
KEY idx_articles_normalized_url (normalized_url(768))
KEY idx_articles_source_type_published (source_type, published_at)
KEY idx_articles_language_created (language, created_at)
KEY idx_articles_fetch_status_created (fetch_status, created_at)
```

URL 去重始终使用完整规范化 URL 的 `url_hash`，不依赖前缀索引表达完整 URL 唯一性。

### crawl_source_runs 表

```sql
CREATE TABLE crawl_source_runs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  run_id VARCHAR(128) NOT NULL,
  source_name VARCHAR(128) NOT NULL,
  source_type VARCHAR(64) NOT NULL DEFAULT '',
  status VARCHAR(32) NOT NULL,
  error_type VARCHAR(64) NOT NULL DEFAULT '',
  error_message TEXT NULL,
  http_status INT NULL,
  items_found INT NOT NULL DEFAULT 0,
  items_saved INT NOT NULL DEFAULT 0,
  items_partial INT NOT NULL DEFAULT 0,
  items_failed INT NOT NULL DEFAULT 0,
  started_at DATETIME NOT NULL,
  finished_at DATETIME NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_crawl_source_run (run_id, source_name),
  KEY idx_crawl_source_status_created (status, created_at),
  KEY idx_crawl_source_name_created (source_name, created_at)
);
```

### Migration 策略

- 在 `shared/sql/migrations/` 新增版本化 migration。
- migration 只执行向前兼容变更，不删除已有字段或数据。
- 新字段提供安全默认值或允许空值。
- 先回填已有文章的 `normalized_url`、`url_hash`、`normalized_title`、`title_hash` 和 `content_hash`，再建立唯一索引。
- 回填时发现已有重复数据，不自动删除。每组重复记录仅为最早记录保留对应哈希，后续重复记录将该哈希保留为 `NULL`，使唯一索引能够建立并保留全部历史数据。
- `shared/sql/init.sql` 同步为最新完整结构，供新环境初始化。

## 配置设计

现有 `rss.sources` 扩展为通用 `crawler.sources`。为兼容已有配置，加载器在过渡期继续接受 `rss.sources`，并将其映射为 `feed` 来源。

来源配置示例：

```yaml
crawler:
  user_agent: "KnowMateCrawler/1.0 (+https://example.com/crawler)"
  request_timeout_seconds: 10
  retry_times: 3
  retry_backoff_milliseconds: 250
  per_host_interval_milliseconds: 500
  max_response_bytes: 5242880
  robots_cache_seconds: 3600
  source_max_items: 10
  run_max_articles: 20
  sources:
    - name: "local-rss"
      type: "feed"
      url: "http://fixture.local/rss.xml"
      enabled: true
      max_items: 5
```

环境变量至少支持覆盖：

- `CRAWLER_USER_AGENT`
- `CRAWLER_REQUEST_TIMEOUT_SECONDS`
- `CRAWLER_RETRY_TIMES`
- `CRAWLER_RETRY_BACKOFF_MILLISECONDS`
- `CRAWLER_PER_HOST_INTERVAL_MILLISECONDS`
- `CRAWLER_MAX_RESPONSE_BYTES`

默认值适合本地开发，并继续保留 `mock://sample` 默认来源。

## 测试设计

### 单元测试

使用表驱动测试覆盖：

- RSS 和 Atom 条目解析。
- Arxiv 元数据映射。
- GitHub Release 元数据映射。
- HuggingFace Papers 元数据映射。
- URL 规范化和追踪参数移除。
- 标题规范化和标题哈希。
- 清洗正文内容哈希。
- 中文、英文、混合和未知语言识别。
- HTML 节点移除与正文选择。
- 错误分类。
- 基于 URL、标题、内容哈希和 ID 的多级去重。

### HTTP 行为测试

使用 `httptest.Server` 覆盖：

- User-Agent 设置。
- robots.txt 允许和禁止。
- robots.txt 缓存。
- 按域名最小请求间隔。
- 请求超时。
- HTTP `429` 和 `5xx` 重试。
- 普通 `4xx` 不重试。
- 指数退避。
- 最大响应大小限制。
- 不支持的 Content-Type。

测试中的等待通过可注入时钟或等待函数控制，避免真实长时间休眠。

### 抓取集成测试

集成测试启动一个本地 `httptest.Server`，同时提供：

- RSS fixture。
- Atom fixture。
- Arxiv fixture。
- GitHub Release fixture。
- HuggingFace Papers fixture。
- 多个 HTML 正文页面。
- robots.txt。
- 固定失败和重试端点。

集成测试验证：

- 五类来源可以进入统一管线。
- 原始内容和清洗内容均被保留。
- 发布时间、作者、来源和语言正确。
- URL、标题和内容重复被正确去除。
- 一个来源失败时其他来源仍然成功。
- 网页失败时回退来源正文并标记 `partial`。
- robots 禁止时不请求文章页面。
- 来源运行状态和统计正确。

### 数据库测试

数据库测试验证：

- 新环境执行 `init.sql` 后字段和索引存在。
- 旧环境执行 migration 后字段和索引存在。
- `InsertArticle` 写入原始内容、清洗内容、哈希、语言、抓取状态和发布时间。
- URL、标题和内容哈希唯一冲突不会中断整个来源。
- `crawl_source_runs` 可以写入和更新来源状态。

数据库测试可以使用项目现有 MySQL 集成环境，但不得依赖公网。

## 文档更新

更新内容包括：

- 根目录 `README.md`：说明支持的来源、抓取策略、失败回退和运行方式。
- `goframe-backend/manifest/config/config.yaml`：提供本地安全默认值。
- `shared/config/rss_sources.example.yaml`：替换或扩展为通用来源配置示例。
- `.env.example`：增加抓取器环境变量。
- 数据库 migration 说明：写明新环境和已有环境的执行方式。
- 测试说明：写明 fixture 测试不需要公网。

## 预期文件结构

具体实现计划可以调整文件名，但职责边界保持如下：

```text
goframe-backend/internal/crawler/
  crawler.go          统一入口和来源调度
  adapter.go          SourceAdapter 和 RawEntry
  feed.go             RSS/Atom 适配器
  arxiv.go            Arxiv 适配器
  github_release.go   GitHub Release 适配器
  huggingface.go      HuggingFace Papers 适配器
  http_client.go      HTTP 策略、重试和限速
  robots.go           robots.txt 缓存和判断
  normalize.go        URL、标题和哈希
  extractor.go        HTML 清洗与正文提取
  language.go         语言识别
  errors.go           失败分类
  deduplicate.go      多级去重
  testdata/           本地 fixture
```

`rss.go` 中仍有价值的逻辑会迁移到对应小文件，避免继续扩大单文件职责。

## 不在本次范围内

- JavaScript 渲染和无头浏览器。
- 登录、Cookie、付费墙和验证码处理。
- 站点专用正文选择器。
- 分布式任务队列和跨进程限速。
- 内容语义相似度去重。
- 自动删除已有重复数据库记录。
- 将失败文章自动定时重试。

## 验收标准

- 五类来源都能通过本地 fixture 集成测试产生统一 Article。
- 所有测试均不访问公网。
- 网页正文成功时保存原始 HTML 和清洗正文。
- 网页正文失败时按规则回退来源内容并标记 `partial`。
- robots.txt 禁止的页面不会被抓取。
- 请求具备可配置 User-Agent、超时、重试、指数退避、响应大小限制和按域名限速。
- URL、标题和内容哈希多级去重在单次运行与数据库跨运行中生效。
- 文章保存 `content_hash`、`language`、`fetch_status`、`fetch_error` 等必要字段。
- 来源级运行状态保存到 `crawl_source_runs`。
- 单个来源失败不会影响其他来源。
- migration 和最新 `init.sql` 均可用。
- 配置示例和 README 与实现保持一致。
