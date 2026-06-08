package crawler

import (
	"context"
	"errors"
	"strings"
	"time"

	"knowledge-post-agent/goframe-backend/internal/model"
)

const maxFetchErrorLength = 2048

type Pipeline struct {
	http   *HTTPClient
	robots *RobotsManager
}

func NewPipeline(client *HTTPClient, robots *RobotsManager) *Pipeline {
	return &Pipeline{http: client, robots: robots}
}

func (p *Pipeline) Process(ctx context.Context, entry RawEntry) model.Article {
	article := model.Article{
		URL:         strings.TrimSpace(entry.URL),
		Title:       strings.TrimSpace(entry.Title),
		Author:      strings.TrimSpace(entry.Author),
		PublishedAt: strings.TrimSpace(entry.PublishedAt),
		Source:      entry.SourceName,
		SourceType:  string(entry.SourceType),
		Tags:        append([]string(nil), entry.Tags...),
		RawPayload:  entry.RawPayload,
		FetchedAt:   time.Now().UTC(),
		Language:    "unknown",
	}

	article.NormalizedTitle = NormalizeTitle(article.Title)
	if article.NormalizedTitle != "" {
		article.TitleHash = SHA256Hex(article.NormalizedTitle)
	}

	var fetchErr error
	if article.URL != "" {
		normalizedURL, err := NormalizeURL(article.URL)
		if err != nil {
			fetchErr = err
		} else {
			article.NormalizedURL = normalizedURL
			article.URLHash = SHA256Hex(normalizedURL)
			if entry.SourceType != SourceTypeMock {
				fetchErr = p.fetchWebContent(ctx, &article)
			}
		}
	} else {
		fetchErr = NewCrawlError(ErrorInvalidURL, "article URL is empty", 0, false, ErrInvalidURL)
	}
	if entry.SourceType == SourceTypeMock {
		article.RawContent = rawSourceContent(entry)
		article.CleanContent = CleanHTMLFragment(entry.SourceContent)
		article.Content = article.CleanContent
	}

	if article.CleanContent != "" {
		article.FetchStatus = "success"
	} else {
		if article.CleanContent == "" {
			article.RawContent = rawSourceContent(entry)
			article.CleanContent = CleanHTMLFragment(entry.SourceContent)
			article.Content = article.CleanContent
		}
		if article.CleanContent != "" {
			article.FetchStatus = "partial"
		} else {
			article.FetchStatus = "failed"
		}
	}

	if fetchErr != nil {
		setArticleFetchError(&article, fetchErr)
	}
	if article.Content == "" {
		article.Content = article.CleanContent
	}
	if article.CleanContent != "" {
		article.ContentHash = SHA256Hex(article.CleanContent)
		article.Language = DetectLanguage(article.CleanContent)
	} else {
		article.Language = DetectLanguage(strings.Join([]string{article.Title, entry.SourceContent}, " "))
	}
	article.ID = StableArticleID(entry, article.NormalizedURL, article.TitleHash, article.ContentHash)
	return article
}

func rawSourceContent(entry RawEntry) string {
	if entry.RawSourceContent != "" {
		return entry.RawSourceContent
	}
	return entry.SourceContent
}

func (p *Pipeline) fetchWebContent(ctx context.Context, article *model.Article) error {
	if p == nil || p.http == nil {
		return NewCrawlError(ErrorConnection, "crawler HTTP client is unavailable", 0, false, nil)
	}
	var diagnostic error
	if p.robots != nil {
		allowed, err := p.robots.Allowed(ctx, article.URL)
		if !allowed {
			if err != nil {
				return err
			}
			return NewCrawlError(ErrorRobotsDenied, "robots.txt denies article URL", 0, false, nil)
		}
		if err != nil {
			if !isDiagnosticRobotsError(err) {
				return err
			}
			diagnostic = err
		}
	}

	response, err := p.http.Get(ctx, article.URL)
	if err != nil {
		return err
	}
	article.HTTPStatus = response.StatusCode
	contentType := strings.ToLower(response.ContentType)
	if contentType != "" && !strings.Contains(contentType, "text/html") && !strings.Contains(contentType, "application/xhtml+xml") {
		return NewCrawlError(ErrorUnsupportedContentType, "article response is not HTML", response.StatusCode, false, nil)
	}

	document, err := ExtractDocument(response.Body, response.URL)
	if err != nil {
		return err
	}
	article.RawContent = string(response.Body)
	article.CleanContent = document.CleanText
	article.Content = document.CleanText
	if article.Title == "" {
		article.Title = document.Title
		article.NormalizedTitle = NormalizeTitle(article.Title)
		if article.NormalizedTitle != "" {
			article.TitleHash = SHA256Hex(article.NormalizedTitle)
		}
	}
	if article.Author == "" {
		article.Author = document.Author
	}
	if article.PublishedAt == "" {
		article.PublishedAt = document.PublishedAt
	}
	return diagnostic
}

func isDiagnosticRobotsError(err error) bool {
	var crawlErr *CrawlError
	return errors.As(err, &crawlErr) && crawlErr.Retryable
}

func setArticleFetchError(article *model.Article, err error) {
	classified := ClassifyError(err, article.HTTPStatus)
	article.FetchErrorType = string(classified.Type)
	article.FetchError = classified.Error()
	if len(article.FetchError) > maxFetchErrorLength {
		article.FetchError = article.FetchError[:maxFetchErrorLength]
	}
	if article.HTTPStatus == 0 {
		article.HTTPStatus = classified.HTTPStatus
	}
}
