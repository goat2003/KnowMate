package crawler

import (
	"errors"
	"strings"
	"testing"
)

func TestSourceTypeConstantsAreStable(t *testing.T) {
	tests := map[SourceType]string{
		SourceTypeFeed:              "feed",
		SourceTypeArxiv:             "arxiv",
		SourceTypeGitHubRelease:     "github_release",
		SourceTypeHuggingFacePapers: "huggingface_papers",
		SourceTypeMock:              "mock",
	}

	for got, want := range tests {
		if string(got) != want {
			t.Fatalf("source type = %q, want %q", got, want)
		}
	}
}

func TestNormalizeURL(t *testing.T) {
	tests := []struct {
		name string
		raw  string
		want string
	}{
		{
			name: "normalizes canonical example",
			raw:  "HTTPS://Example.COM:443/a/../post?utm_source=x&b=2&a=1#section",
			want: "https://example.com/post?a=1&b=2",
		},
		{
			name: "normalizes empty path and removes tracking parameters",
			raw:  "http://EXAMPLE.com:80?GCLID=x&utm_medium=email&keep=yes&fbclid=y",
			want: "http://example.com/?keep=yes",
		},
		{
			name: "preserves scheme non-default port and trailing slash",
			raw:  "http://Example.com:8080/a/./b/../",
			want: "http://example.com:8080/a/",
		},
		{
			name: "preserves directory semantics for terminal parent segment",
			raw:  "https://example.com/a/b/..",
			want: "https://example.com/a/",
		},
		{
			name: "preserves repeated slashes while resolving dot segments",
			raw:  "https://example.com/a//b/./c/../",
			want: "https://example.com/a//b/",
		},
		{
			name: "resolves percent encoded parent segment",
			raw:  "https://example.com/%2e%2e/a",
			want: "https://example.com/a",
		},
		{
			name: "preserves ordinary percent encoded path characters",
			raw:  "https://example.com/a%2Fb/%2Ename",
			want: "https://example.com/a%2Fb/%2Ename",
		},
		{
			name: "removes numerically equivalent default HTTPS port",
			raw:  "https://Example.com:0443/path",
			want: "https://example.com/path",
		},
		{
			name: "removes numerically equivalent default HTTP port",
			raw:  "http://Example.com:080/path",
			want: "http://example.com/path",
		},
		{
			name: "sorts query keys and values",
			raw:  "https://example.com/path?z=2&a=3&a=1&z=1",
			want: "https://example.com/path?a=1&a=3&z=1&z=2",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := NormalizeURL(tt.raw)
			if err != nil {
				t.Fatalf("NormalizeURL() error = %v", err)
			}
			if got != tt.want {
				t.Fatalf("NormalizeURL() = %q, want %q", got, tt.want)
			}
		})
	}
}

func TestNormalizeURLRejectsInvalidURLs(t *testing.T) {
	tests := []string{
		"",
		"/relative/path",
		"ftp://example.com/file",
		"https:///missing-host",
		"://malformed",
		"https://example.com:65536/path",
		"https://example.com:not-a-port/path",
	}

	for _, raw := range tests {
		t.Run(raw, func(t *testing.T) {
			_, err := NormalizeURL(raw)
			if !errors.Is(err, ErrInvalidURL) {
				t.Fatalf("NormalizeURL(%q) error = %v, want ErrInvalidURL", raw, err)
			}
		})
	}
}

func TestNormalizeTitle(t *testing.T) {
	got := NormalizeTitle(" \t Hello \n WORLD  ")
	if got != "hello world" {
		t.Fatalf("NormalizeTitle() = %q, want %q", got, "hello world")
	}
}

func TestSHA256Hex(t *testing.T) {
	const want = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
	if got := SHA256Hex("abc"); got != want {
		t.Fatalf("SHA256Hex() = %q, want %q", got, want)
	}
}

func TestStableArticleIDUsesIdentityPriority(t *testing.T) {
	base := RawEntry{
		SourceName:    "source-a",
		SourceType:    SourceTypeFeed,
		ExternalID:    "external-1",
		URL:           "https://example.com/original",
		Title:         "Title",
		SourceContent: "Content",
	}

	tests := []struct {
		name      string
		first     RawEntry
		second    RawEntry
		firstURL  string
		secondURL string
		firstTH   string
		secondTH  string
		firstCH   string
		secondCH  string
		wantEqual bool
	}{
		{
			name:      "external ID ignores lower priority values",
			first:     base,
			second:    base,
			firstURL:  "https://example.com/one",
			secondURL: "https://example.com/two",
			firstTH:   "title-one",
			secondTH:  "title-two",
			firstCH:   "content-one",
			secondCH:  "content-two",
			wantEqual: true,
		},
		{
			name:  "external ID includes source identity",
			first: base,
			second: RawEntry{
				SourceName: "source-b",
				SourceType: SourceTypeFeed,
				ExternalID: "external-1",
			},
			wantEqual: false,
		},
		{
			name:      "normalized URL is used without external ID",
			first:     RawEntry{SourceName: "source-a", SourceType: SourceTypeFeed},
			second:    RawEntry{SourceName: "source-b", SourceType: SourceTypeArxiv},
			firstURL:  "https://example.com/post",
			secondURL: "https://example.com/post",
			firstTH:   "title-one",
			secondTH:  "title-two",
			wantEqual: true,
		},
		{
			name:      "title and content hashes are final fallback",
			first:     RawEntry{},
			second:    RawEntry{},
			firstTH:   "same-title",
			secondTH:  "same-title",
			firstCH:   "content-one",
			secondCH:  "content-two",
			wantEqual: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			first := StableArticleID(tt.first, tt.firstURL, tt.firstTH, tt.firstCH)
			second := StableArticleID(tt.second, tt.secondURL, tt.secondTH, tt.secondCH)

			if !strings.HasPrefix(first, "article-") || len(first) != len("article-")+64 {
				t.Fatalf("StableArticleID() = %q, want article- plus SHA-256 hex", first)
			}
			if (first == second) != tt.wantEqual {
				t.Fatalf("IDs equality = %t, want %t; first=%q second=%q", first == second, tt.wantEqual, first, second)
			}
		})
	}
}

func TestStableArticleIDRequiresCompleteIdentity(t *testing.T) {
	tests := []struct {
		name          string
		entry         RawEntry
		normalizedURL string
		titleHash     string
		contentHash   string
		want          string
	}{
		{
			name: "all identities empty",
		},
		{
			name:  "external ID without source identity has no fallback",
			entry: RawEntry{ExternalID: "external-1"},
		},
		{
			name:          "external ID without source name falls back to URL",
			entry:         RawEntry{SourceType: SourceTypeFeed, ExternalID: "external-1"},
			normalizedURL: "https://example.com/post",
			want:          StableArticleID(RawEntry{}, "https://example.com/post", "", ""),
		},
		{
			name:        "external ID without source type falls back to hashes",
			entry:       RawEntry{SourceName: "source-a", ExternalID: "external-1"},
			titleHash:   "title-hash",
			contentHash: "content-hash",
			want:        StableArticleID(RawEntry{}, "", "title-hash", "content-hash"),
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := StableArticleID(tt.entry, tt.normalizedURL, tt.titleHash, tt.contentHash)
			if got != tt.want {
				t.Fatalf("StableArticleID() = %q, want %q", got, tt.want)
			}
		})
	}
}
