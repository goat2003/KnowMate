package crawler

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

func BenchmarkNormalizeURL(b *testing.B) {
	raw := "HTTPS://Example.COM:443/a/../post?utm_source=x&b=2&a=1#section"
	for b.Loop() {
		if _, err := NormalizeURL(raw); err != nil {
			b.Fatal(err)
		}
	}
}

func BenchmarkExtractDocument(b *testing.B) {
	raw := []byte(`<html><head><title>Bench</title></head><body><article><h1>Bench</h1><p>` +
		`This benchmark article contains enough useful text for the extraction pipeline. ` +
		`It is intentionally deterministic and uses no public network dependency. ` +
		`</p></article></body></html>`)
	for b.Loop() {
		if _, err := ExtractDocument(raw, "https://example.com/bench"); err != nil {
			b.Fatal(err)
		}
	}
}

func BenchmarkPipelineProcess(b *testing.B) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		writer.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = writer.Write([]byte(`<article><p>This benchmark page is stable, local, and long enough for content extraction.</p></article>`))
	}))
	defer server.Close()

	pipeline := NewPipeline(NewHTTPClient(HTTPOptions{RetryTimes: 0}), nil)
	entry := RawEntry{
		SourceName: "bench",
		SourceType: SourceTypeFeed,
		ExternalID: "bench-entry",
		URL:        server.URL + "/post?utm_source=bench",
		Title:      "Benchmark article",
	}

	for b.Loop() {
		article := pipeline.Process(context.Background(), entry)
		if article.FetchStatus != "success" {
			b.Fatalf("FetchStatus = %q", article.FetchStatus)
		}
	}
}
