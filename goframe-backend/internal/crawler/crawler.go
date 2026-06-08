package crawler

import (
	"context"
	"errors"
	"strings"
	"time"

	"knowledge-post-agent/goframe-backend/internal/model"
)

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
	HTTP           HTTPOptions
	RobotsCacheTTL time.Duration
	SourceMaxItems int
}

type Crawler struct {
	adapters       map[SourceType]SourceAdapter
	http           *HTTPClient
	pipeline       *Pipeline
	sourceMaxItems int
}

func New(options Options) *Crawler {
	client := NewHTTPClient(options.HTTP)
	robots := NewRobotsManager(client, options.HTTP.UserAgent, options.RobotsCacheTTL)
	adapters := make(map[SourceType]SourceAdapter)
	for _, sourceType := range []SourceType{
		SourceTypeFeed,
		SourceTypeArxiv,
		SourceTypeGitHubRelease,
		SourceTypeHuggingFacePapers,
		SourceTypeMock,
	} {
		adapter, err := NewAdapter(sourceType)
		if err == nil {
			adapters[sourceType] = adapter
		}
	}
	if options.SourceMaxItems <= 0 {
		options.SourceMaxItems = 10
	}
	return &Crawler{
		adapters:       adapters,
		http:           client,
		pipeline:       NewPipeline(client, robots),
		sourceMaxItems: options.SourceMaxItems,
	}
}

func (c *Crawler) FetchSource(ctx context.Context, source Source) SourceResult {
	result := SourceResult{Source: source, Status: "failed", Articles: make([]model.Article, 0)}
	adapter := c.adapters[source.Type]
	if adapter == nil {
		setSourceResultError(&result, NewCrawlError(ErrorParse, "unsupported source type "+string(source.Type), 0, false, nil))
		return result
	}

	var payload []byte
	if source.Type != SourceTypeMock {
		if c.pipeline != nil && c.pipeline.robots != nil {
			allowed, err := c.pipeline.robots.Allowed(ctx, source.URL)
			if !allowed {
				setSourceResultError(&result, err)
				return result
			}
			if err != nil {
				if !isDiagnosticRobotsError(err) {
					setSourceResultError(&result, err)
					return result
				}
				setSourceResultError(&result, err)
			}
		}
		response, err := c.http.Get(ctx, source.URL)
		if err != nil {
			setSourceResultError(&result, err)
			return result
		}
		payload = response.Body
		result.HTTPStatus = response.StatusCode
	}

	entries, err := adapter.Parse(source, payload)
	if err != nil {
		setSourceResultError(&result, err)
		return result
	}
	entries = entries[:limitedEntryCount(len(entries), source.MaxItems, c.sourceMaxItems)]
	result.ItemsFound = len(entries)
	if len(entries) == 0 {
		setSourceResultError(&result, NewCrawlError(ErrorParse, "source returned no entries", result.HTTPStatus, false, nil))
		return result
	}

	for _, entry := range entries {
		article := c.pipeline.Process(ctx, entry)
		result.Articles = append(result.Articles, article)
		switch article.FetchStatus {
		case "partial":
			result.ItemsPartial++
			setSourceResultArticleError(&result, article)
		case "failed":
			result.ItemsFailed++
			setSourceResultArticleError(&result, article)
		}
	}

	switch {
	case result.ItemsFailed == result.ItemsFound:
		result.Status = "failed"
	case result.ItemsPartial > 0 || result.ItemsFailed > 0:
		result.Status = "partial"
	default:
		result.Status = "success"
	}
	return result
}

func limitedEntryCount(count, sourceMax, defaultMax int) int {
	limit := defaultMax
	if sourceMax > 0 && (limit <= 0 || sourceMax < limit) {
		limit = sourceMax
	}
	if limit <= 0 || count < limit {
		return count
	}
	return limit
}

func setSourceResultArticleError(result *SourceResult, article model.Article) {
	if result.ErrorType != "" {
		return
	}
	result.ErrorType = article.FetchErrorType
	result.ErrorMessage = article.FetchError
	if result.HTTPStatus == 0 {
		result.HTTPStatus = article.HTTPStatus
	}
}

func setSourceResultError(result *SourceResult, err error) {
	classified := ClassifyError(err, result.HTTPStatus)
	result.ErrorType = string(classified.Type)
	result.ErrorMessage = strings.TrimSpace(classified.Error())
	result.HTTPStatus = classified.HTTPStatus
	var crawlErr *CrawlError
	if errors.As(err, &crawlErr) && crawlErr.HTTPStatus != 0 {
		result.HTTPStatus = crawlErr.HTTPStatus
	}
}
