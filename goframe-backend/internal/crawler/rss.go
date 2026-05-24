// 文件作用：
// 本文件实现 RSS 文章抓取和去重逻辑。
// 它把配置中的 RSS 源转换为内部 Article 模型，供 harness 后续写入 MySQL 并发送给 Python Agent。
//
// 在项目中的位置：
// 本文件属于 GoFrame 后端的 crawler 层，被 logic/harness 调用。
//
// 主要内容：
// 1. RSSCrawler：封装 gofeed.Parser。
// 2. Fetch：从真实 RSS URL 或 mock:// 源抓取文章。
// 3. mockArticles：生成本地模拟文章，适合离线测试。
// 4. stableArticleID：用稳定 hash 生成 article_uid。
// 5. Deduplicate：按文章 ID 去重并限制数量。
//
// 关键调用关系：
// - harness.fetchArticles 调用 RSSCrawler.Fetch。
// - harness.RunArticles 调用 Deduplicate。
// - 抓取结果会进入 store.InsertArticle 和 Python Agent ProcessArticles。
//
// 初学者阅读建议：
// 先看 Fetch 的 mock:// 分支，再看真实 RSS 解析分支，理解 mock 逻辑和真实逻辑的区别。
package crawler

import (
	// context.Context 用于让 RSS 请求支持取消和超时。
	"context"
	// crypto/sha1 用于根据文章 GUID/URL/标题生成稳定 ID。
	"crypto/sha1"
	// encoding/hex 用于把 hash 字节转换成可读字符串。
	"encoding/hex"
	// fmt 用于拼接去重 fallback key。
	"fmt"
	// strings 用于处理 mock URL、空白和字符串前缀。
	"strings"

	// config 提供 RSSSource 配置结构。
	"knowledge-post-agent/goframe-backend/internal/config"
	// model 提供 Article 业务模型。
	"knowledge-post-agent/goframe-backend/internal/model"

	// gofeed 是成熟 RSS/Atom 解析库，避免手写 XML/RSS 解析逻辑。
	"github.com/mmcdole/gofeed"
)

// RSSCrawler 封装 RSS 解析器。
// 将 parser 放在结构体中可以复用解析器实例，便于未来扩展缓存或统一配置。
type RSSCrawler struct {
	// parser 是 gofeed 提供的 RSS/Atom 解析器。
	parser *gofeed.Parser
}

// 函数作用：
// 创建 RSSCrawler。
//
// 参数说明：
// - 无。
//
// 返回值：
// - 返回 *RSSCrawler。
func NewRSSCrawler() *RSSCrawler {
	// gofeed.NewParser 创建默认解析器。
	return &RSSCrawler{parser: gofeed.NewParser()}
}

// 函数作用：
// 从一个 RSS 源抓取文章。
//
// 参数说明：
// - ctx：上下文，用于控制真实 RSS 请求取消或超时。
// - source：RSS 源配置，包含名称、URL、启用状态和最大数量。
// - fallbackLimit：当 source.MaxItems 未设置或过大时使用的默认上限。
//
// 返回值：
// - 返回文章列表和 error。
//
// mock 与真实逻辑区别：
// - URL 以 mock:// 开头时，不访问网络，直接返回 mockArticles。
// - 其他 URL 使用 gofeed.ParseURLWithContext 真实拉取并解析 RSS。
func (c *RSSCrawler) Fetch(ctx context.Context, source config.RSSSource, fallbackLimit int) ([]model.Article, error) {
	// 优先使用单个 RSS 源自己的 MaxItems。
	limit := source.MaxItems
	// 如果源配置非法或超过全局限制，就使用 fallbackLimit。
	if limit <= 0 || limit > fallbackLimit {
		limit = fallbackLimit
	}
	// fallbackLimit 也非法时，使用硬编码默认 10，保证抓取数量有上限。
	if limit <= 0 {
		limit = 10
	}
	// mock:// 是本项目约定的离线测试源，不访问真实网络。
	if strings.HasPrefix(source.URL, "mock://") {
		return mockArticles(source, limit), nil
	}

	// 真实 RSS 抓取路径：gofeed 会处理 RSS/Atom XML 解析。
	feed, err := c.parser.ParseURLWithContext(source.URL, ctx)
	if err != nil {
		return nil, err
	}
	// 预分配结果切片容量，减少 append 扩容。
	articles := make([]model.Article, 0, min(limit, len(feed.Items)))
	// 遍历 feed.Items，并限制最多处理 limit 条。
	for idx, item := range feed.Items {
		if idx >= limit {
			break
		}
		// RSS 有些源正文在 Content，有些在 Description；firstNonEmpty 取第一个非空值。
		content := firstNonEmpty(item.Content, item.Description)
		// published 保存 ISO 风格时间字符串；如果 Parsed 为空，就保留源中的原始 Published 字符串。
		published := ""
		if item.PublishedParsed != nil {
			published = item.PublishedParsed.Format("2006-01-02T15:04:05Z07:00")
		} else {
			published = item.Published
		}
		// 作者字段可能为空指针，使用前必须判空。
		author := ""
		if item.Author != nil {
			author = item.Author.Name
		}
		// 将 gofeed.Item 转换为项目内部 Article 模型。
		articles = append(articles, model.Article{
			// 使用 GUID、链接或标题生成稳定 ID，避免同一文章重复入库。
			ID:          stableArticleID(firstNonEmpty(item.GUID, item.Link, item.Title)),
			URL:         item.Link,
			Title:       item.Title,
			Content:     content,
			Author:      author,
			PublishedAt: published,
			Source:      source.Name,
			Tags:        item.Categories,
		})
	}
	return articles, nil
}

// 函数作用：
// 生成本地模拟文章。
//
// 参数说明：
// - source：RSS 源配置，主要使用 source.Name。
// - limit：最多返回多少条。
//
// 返回值：
// - 返回模拟 Article 列表。
//
// 调用关系：
// - 被 Fetch 的 mock:// 分支调用。
func mockArticles(source config.RSSSource, limit int) []model.Article {
	// seeds 是固定 mock 文章，内容与 Agent 工作流和知识记忆相关，便于演示完整链路。
	seeds := []model.Article{
		{
			ID:      "mock-agent-workflow",
			URL:     "https://example.com/mock-agent-workflow",
			Title:   "Agent Workflow for Knowledge Posts",
			Content: "This article explains how to compose filter, summary, rewrite, and check nodes for reliable knowledge post generation.",
			Source:  source.Name,
			Tags:    []string{"AI", "workflow"},
		},
		{
			ID:      "mock-knowledge-memory",
			URL:     "https://example.com/mock-knowledge-memory",
			Title:   "Personal Knowledge Memory with Graph Signals",
			Content: "A practical note about combining user feedback, profile snapshots, and graph context for personalized recommendations.",
			Source:  source.Name,
			Tags:    []string{"knowledge-management", "memory"},
		},
	}
	// limit 超过 mock 数量时截断到 seeds 长度。
	if limit > len(seeds) {
		limit = len(seeds)
	}
	// 返回前 limit 条；切片不会复制底层数组，但这里 seeds 是局部只读数据，安全。
	return seeds[:limit]
}

// 函数作用：
// 根据输入字符串生成稳定文章 ID。
//
// 参数说明：
// - value：通常是 RSS GUID、URL 或标题。
//
// 返回值：
// - 返回 article- 开头的短 hash。
func stableArticleID(value string) string {
	// 空值统一写成 "empty"，避免 sha1.Sum([]byte("")) 也可用但语义不清。
	if value == "" {
		value = "empty"
	}
	// sha1.Sum 返回 20 字节摘要；这里用于稳定 ID，不用于安全加密。
	sum := sha1.Sum([]byte(value))
	// 只取前 16 个 hex 字符，足够本地唯一且更短。
	return "article-" + hex.EncodeToString(sum[:])[:16]
}

// 函数作用：
// 返回多个字符串中的第一个非空白值。
//
// 参数说明：
// - values：可变参数，表示候选字符串列表。
//
// 返回值：
// - 返回第一个 TrimSpace 后非空的字符串；都为空时返回空字符串。
func firstNonEmpty(values ...string) string {
	// 可变参数在函数内部表现为 []string。
	for _, value := range values {
		// TrimSpace 避免全空格字符串被当作有效内容。
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

// 函数作用：
// 按文章 ID 去重，并限制最多返回 maxItems 条。
//
// 参数说明：
// - articles：待去重文章列表。
// - maxItems：最多保留数量；小于等于 0 时不按数量截断。
//
// 返回值：
// - 返回去重后的文章列表。
//
// 调用关系：
// - 被 harness.RunArticles 调用，防止重复文章进入数据库和 Python Agent。
func Deduplicate(articles []model.Article, maxItems int) []model.Article {
	// seen 记录已经出现过的文章 ID。
	seen := map[string]bool{}
	// 预分配输出切片容量为输入长度，减少 append 扩容。
	out := make([]model.Article, 0, len(articles))
	// 按原顺序遍历文章，保留第一次出现的记录。
	for _, article := range articles {
		// key 默认使用文章 ID。
		key := article.ID
		// 如果 ID 缺失，就用 URL 和标题生成一个稳定 ID，并回填到 article.ID。
		if key == "" {
			key = stableArticleID(fmt.Sprintf("%s|%s", article.URL, article.Title))
			article.ID = key
		}
		// 已出现过的 ID 直接跳过。
		if seen[key] {
			continue
		}
		// 标记该 ID 已出现。
		seen[key] = true
		// 追加到输出结果。
		out = append(out, article)
		// 达到 maxItems 后提前结束，避免后续处理过多文章。
		if maxItems > 0 && len(out) >= maxItems {
			break
		}
	}
	return out
}
