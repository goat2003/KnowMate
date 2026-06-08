package crawler

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestPipelineUsesExtractedWebContent(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write([]byte(`<html><head><meta name="author" content="Web Author"></head><body><article><h1>Web Title</h1><p>This is the extracted web article body with enough useful English content for processing.</p></article></body></html>`))
	}))
	defer server.Close()

	client := NewHTTPClient(HTTPOptions{RetryTimes: 0})
	pipeline := NewPipeline(client, nil)
	article := pipeline.Process(context.Background(), RawEntry{
		SourceName: "fixture",
		SourceType: SourceTypeFeed,
		ExternalID: "item-1",
		URL:        server.URL + "/post?utm_source=test",
		Title:      "Feed Title",
		RawPayload: map[string]any{"id": "item-1"},
	})

	if article.FetchStatus != "success" {
		t.Fatalf("status=%q error=%q", article.FetchStatus, article.FetchError)
	}
	if !strings.Contains(article.RawContent, "<article>") || !strings.Contains(article.CleanContent, "extracted web article") {
		t.Fatalf("content not retained: %#v", article)
	}
	if article.Content != article.CleanContent || article.ContentHash == "" || article.URLHash == "" || article.TitleHash == "" {
		t.Fatalf("derived fields missing: %#v", article)
	}
	if article.Language != "en" || article.Author != "Web Author" {
		t.Fatalf("metadata mismatch: %#v", article)
	}
	if strings.Contains(article.NormalizedURL, "utm_source") {
		t.Fatalf("tracking parameter remained: %q", article.NormalizedURL)
	}
}

func TestPipelineFallsBackToSourceContent(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "unavailable", http.StatusServiceUnavailable)
	}))
	defer server.Close()

	pipeline := NewPipeline(NewHTTPClient(HTTPOptions{RetryTimes: 0}), nil)
	article := pipeline.Process(context.Background(), RawEntry{
		SourceName:    "fixture",
		SourceType:    SourceTypeFeed,
		ExternalID:    "item-2",
		URL:           server.URL + "/post",
		Title:         "Fallback",
		SourceContent: "<p>This source summary remains usable when the web page cannot be fetched successfully.</p>",
	})

	if article.FetchStatus != "partial" || article.FetchErrorType != string(ErrorHTTP5xx) {
		t.Fatalf("unexpected fallback state: %#v", article)
	}
	if !strings.Contains(article.Content, "source summary") || article.ContentHash == "" {
		t.Fatalf("fallback content missing: %#v", article)
	}
	if !strings.Contains(article.RawContent, "<p>") || strings.Contains(article.CleanContent, "<p>") {
		t.Fatalf("raw and cleaned fallback content were not preserved separately: %#v", article)
	}
}

func TestPipelineFailsWithoutUsableContent(t *testing.T) {
	pipeline := NewPipeline(NewHTTPClient(HTTPOptions{RetryTimes: 0}), nil)
	article := pipeline.Process(context.Background(), RawEntry{
		SourceName: "fixture",
		SourceType: SourceTypeFeed,
		ExternalID: "item-3",
		URL:        "not-a-url",
		Title:      "No content",
	})

	if article.FetchStatus != "failed" || article.FetchErrorType != string(ErrorInvalidURL) || article.Content != "" {
		t.Fatalf("unexpected failed article: %#v", article)
	}
}

func TestPipelineRecordsTemporaryRobotsDiagnosticAfterSuccessfulFetch(t *testing.T) {
	var server *httptest.Server
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/robots.txt" {
			http.Error(w, "temporary", http.StatusServiceUnavailable)
			return
		}
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<article><p>This page remains usable even when robots.txt is temporarily unavailable for the crawler.</p></article>`))
	}))
	defer server.Close()

	client := NewHTTPClient(HTTPOptions{RetryTimes: 0})
	pipeline := NewPipeline(client, NewRobotsManager(client, "KnowMateCrawler/1.0", 0))
	article := pipeline.Process(context.Background(), RawEntry{
		SourceName: "fixture", SourceType: SourceTypeFeed, ExternalID: "robots-diagnostic", URL: server.URL + "/post",
	})

	if article.FetchStatus != "success" || article.FetchErrorType != string(ErrorHTTP5xx) {
		t.Fatalf("expected successful fetch with robots diagnostic, got %#v", article)
	}
}
