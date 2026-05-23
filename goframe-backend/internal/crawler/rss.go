package crawler

import (
	"context"
	"crypto/sha1"
	"encoding/hex"
	"fmt"
	"strings"

	"knowledge-post-agent/goframe-backend/internal/config"
	"knowledge-post-agent/goframe-backend/internal/model"

	"github.com/mmcdole/gofeed"
)

type RSSCrawler struct {
	parser *gofeed.Parser
}

func NewRSSCrawler() *RSSCrawler {
	return &RSSCrawler{parser: gofeed.NewParser()}
}

func (c *RSSCrawler) Fetch(ctx context.Context, source config.RSSSource, fallbackLimit int) ([]model.Article, error) {
	limit := source.MaxItems
	if limit <= 0 || limit > fallbackLimit {
		limit = fallbackLimit
	}
	if limit <= 0 {
		limit = 10
	}
	if strings.HasPrefix(source.URL, "mock://") {
		return mockArticles(source, limit), nil
	}

	feed, err := c.parser.ParseURLWithContext(source.URL, ctx)
	if err != nil {
		return nil, err
	}
	articles := make([]model.Article, 0, min(limit, len(feed.Items)))
	for idx, item := range feed.Items {
		if idx >= limit {
			break
		}
		content := firstNonEmpty(item.Content, item.Description)
		published := ""
		if item.PublishedParsed != nil {
			published = item.PublishedParsed.Format("2006-01-02T15:04:05Z07:00")
		} else {
			published = item.Published
		}
		author := ""
		if item.Author != nil {
			author = item.Author.Name
		}
		articles = append(articles, model.Article{
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

func mockArticles(source config.RSSSource, limit int) []model.Article {
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
	if limit > len(seeds) {
		limit = len(seeds)
	}
	return seeds[:limit]
}

func stableArticleID(value string) string {
	if value == "" {
		value = "empty"
	}
	sum := sha1.Sum([]byte(value))
	return "article-" + hex.EncodeToString(sum[:])[:16]
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

func Deduplicate(articles []model.Article, maxItems int) []model.Article {
	seen := map[string]bool{}
	out := make([]model.Article, 0, len(articles))
	for _, article := range articles {
		key := article.ID
		if key == "" {
			key = stableArticleID(fmt.Sprintf("%s|%s", article.URL, article.Title))
			article.ID = key
		}
		if seen[key] {
			continue
		}
		seen[key] = true
		out = append(out, article)
		if maxItems > 0 && len(out) >= maxItems {
			break
		}
	}
	return out
}
