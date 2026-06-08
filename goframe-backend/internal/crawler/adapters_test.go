package crawler

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestNewAdapterReturnsAllSupportedAdapters(t *testing.T) {
	tests := []SourceType{
		SourceTypeFeed,
		SourceTypeArxiv,
		SourceTypeGitHubRelease,
		SourceTypeHuggingFacePapers,
		SourceTypeMock,
	}

	for _, sourceType := range tests {
		t.Run(string(sourceType), func(t *testing.T) {
			adapter, err := NewAdapter(sourceType)
			if err != nil {
				t.Fatalf("NewAdapter(%q) error = %v", sourceType, err)
			}
			if got := adapter.Type(); got != sourceType {
				t.Fatalf("Type() = %q, want %q", got, sourceType)
			}
		})
	}
}

func TestMockAdapterReturnsDemoEntriesWithoutPayload(t *testing.T) {
	adapter := mustAdapter(t, SourceTypeMock)
	entries, err := adapter.Parse(Source{Name: "demo-source", Type: SourceTypeMock, MaxItems: 1}, nil)
	if err != nil {
		t.Fatalf("Parse() error = %v", err)
	}
	if len(entries) < 2 {
		t.Fatalf("len(entries) = %d, want at least 2 and no MaxItems truncation", len(entries))
	}
	for _, entry := range entries {
		if entry.SourceName != "demo-source" || entry.SourceType != SourceTypeMock {
			t.Fatalf("entry source = %q/%q, want demo-source/%q", entry.SourceName, entry.SourceType, SourceTypeMock)
		}
		if entry.ExternalID == "" || entry.URL == "" || entry.Title == "" || entry.SourceContent == "" {
			t.Fatalf("demo entry has missing core fields: %+v", entry)
		}
		assertRawPayload(t, entry.RawPayload, entry.ExternalID)
	}
}

func TestNewAdapterRejectsUnknownType(t *testing.T) {
	_, err := NewAdapter(SourceType("unknown"))
	assertAdapterParseError(t, err)
	if !strings.Contains(err.Error(), "unknown") {
		t.Fatalf("error = %q, want clear unknown source type message", err)
	}
}

func TestFeedAdapterParsesRSSAndAtom(t *testing.T) {
	adapter := mustAdapter(t, SourceTypeFeed)
	tests := []struct {
		name          string
		fixture       string
		wantCount     int
		wantFirst     RawEntry
		wantContent   string
		wantRawMarker string
	}{
		{
			name:      "RSS",
			fixture:   "rss.xml",
			wantCount: 2,
			wantFirst: RawEntry{
				SourceName:  "engineering-feed",
				SourceType:  SourceTypeFeed,
				ExternalID:  "rss-entry-001",
				URL:         "https://example.com/engineering/rss-entry",
				Title:       "RSS adapter article",
				Author:      "Ada Lovelace",
				PublishedAt: "2026-06-02T02:30:00Z",
				Tags:        []string{"Go", "Feeds"},
			},
			wantContent:   "Full RSS content.",
			wantRawMarker: "Short RSS description.",
		},
		{
			name:      "Atom",
			fixture:   "atom.xml",
			wantCount: 1,
			wantFirst: RawEntry{
				SourceName:  "engineering-feed",
				SourceType:  SourceTypeFeed,
				ExternalID:  "tag:example.com,2026:atom-entry-001",
				URL:         "https://example.com/engineering/atom-entry",
				Title:       "Atom adapter article",
				Author:      "Grace Hopper, Margaret Hamilton",
				PublishedAt: "2026-06-03T11:45:00Z",
				Tags:        []string{"Atom", "Engineering"},
			},
			wantContent:   "Full Atom content.",
			wantRawMarker: "Short Atom summary.",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			source := Source{Name: "engineering-feed", Type: SourceTypeFeed, MaxItems: 1}
			entries, err := adapter.Parse(source, fixtureBytes(t, tt.fixture))
			if err != nil {
				t.Fatalf("Parse() error = %v", err)
			}
			if len(entries) != tt.wantCount {
				t.Fatalf("len(entries) = %d, want %d; adapter must ignore MaxItems", len(entries), tt.wantCount)
			}
			assertRawEntryFields(t, entries[0], tt.wantFirst)
			if entries[0].SourceContent != tt.wantContent {
				t.Fatalf("SourceContent = %q, want %q", entries[0].SourceContent, tt.wantContent)
			}
			if !strings.Contains(entries[0].RawSourceContent, "<") {
				t.Fatalf("RawSourceContent = %q, want original markup", entries[0].RawSourceContent)
			}
			assertRawPayload(t, entries[0].RawPayload, tt.wantRawMarker)
		})
	}

	rssEntries, err := adapter.Parse(Source{Name: "engineering-feed", Type: SourceTypeFeed}, fixtureBytes(t, "rss.xml"))
	if err != nil {
		t.Fatalf("Parse(RSS) error = %v", err)
	}
	missing := rssEntries[1]
	if missing.Author != "" || missing.PublishedAt != "" {
		t.Fatalf("missing metadata entry = %+v, want empty author and published date", missing)
	}
	if missing.SourceContent != "Fallback description only." {
		t.Fatalf("SourceContent = %q, want description fallback", missing.SourceContent)
	}
}

func TestFeedAdapterRejectsEmptyAndMalformedPayload(t *testing.T) {
	assertAdapterRejectsInvalidPayloads(t, SourceTypeFeed)
}

func TestFeedAdapterParsesISO88591XML(t *testing.T) {
	const xmlText = `<?xml version="1.0" encoding="ISO-8859-1"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Café Papers</title>
    <link>https://example.com/cafe</link>
    <description>Résumé feed</description>
    <item>
      <guid>cafe-paper-1</guid>
      <link>https://example.com/cafe/paper-1</link>
      <title>Résumé déjà publié</title>
      <description>Étude révisée.</description>
      <dc:creator>André Auteur</dc:creator>
    </item>
  </channel>
</rss>`

	adapter := mustAdapter(t, SourceTypeFeed)
	entries, err := adapter.Parse(Source{Name: "latin-feed", Type: SourceTypeFeed}, iso88591Bytes(t, xmlText))
	if err != nil {
		t.Fatalf("Parse() error = %v", err)
	}
	if len(entries) != 1 {
		t.Fatalf("len(entries) = %d, want 1", len(entries))
	}
	entry := entries[0]
	if entry.Title != "Résumé déjà publié" || entry.SourceContent != "Étude révisée." || entry.Author != "André Auteur" {
		t.Fatalf("decoded entry = title %q content %q author %q, want ISO-8859-1 characters preserved", entry.Title, entry.SourceContent, entry.Author)
	}
	assertRawPayload(t, entry.RawPayload, "Résumé déjà publié")
}

func TestArxivAdapterMapsAtomEntry(t *testing.T) {
	adapter := mustAdapter(t, SourceTypeArxiv)
	entries, err := adapter.Parse(Source{Name: "arxiv-ai", Type: SourceTypeArxiv, MaxItems: 1}, fixtureBytes(t, "arxiv.xml"))
	if err != nil {
		t.Fatalf("Parse() error = %v", err)
	}
	if len(entries) != 2 {
		t.Fatalf("len(entries) = %d, want 2 and no MaxItems truncation", len(entries))
	}

	want := RawEntry{
		SourceName:  "arxiv-ai",
		SourceType:  SourceTypeArxiv,
		ExternalID:  "http://arxiv.org/abs/2606.01234v2",
		URL:         "https://arxiv.org/abs/2606.01234v2",
		Title:       "Reliable Knowledge Agents",
		Author:      "Alice Researcher, Bob Scientist",
		PublishedAt: "2026-06-01T09:15:00Z",
		Tags:        []string{"cs.AI", "cs.IR"},
	}
	assertRawEntryFields(t, entries[0], want)
	if entries[0].SourceContent != "We study reliable agents for maintaining personal knowledge bases." {
		t.Fatalf("SourceContent = %q, want cleaned arXiv summary", entries[0].SourceContent)
	}
	assertRawPayload(t, entries[0].RawPayload, "Accepted at ExampleConf 2026")
	assertMissingAuthorAndTime(t, entries[1])
	if entries[1].ExternalID != "http://arxiv.org/abs/2606.09999v1" || entries[1].URL != "https://arxiv.org/abs/2606.09999v1" {
		t.Fatalf("sparse arXiv entry identity = %q/%q, want stable ID and paper URL", entries[1].ExternalID, entries[1].URL)
	}
}

func TestArxivAdapterRejectsInvalidPayloads(t *testing.T) {
	assertAdapterRejectsInvalidPayloads(t, SourceTypeArxiv)
}

func TestGitHubReleaseAdapterMapsReleaseAtom(t *testing.T) {
	adapter := mustAdapter(t, SourceTypeGitHubRelease)
	entries, err := adapter.Parse(Source{Name: "knowledge-agent-releases", Type: SourceTypeGitHubRelease, MaxItems: 1}, fixtureBytes(t, "github_releases.xml"))
	if err != nil {
		t.Fatalf("Parse() error = %v", err)
	}
	if len(entries) != 2 {
		t.Fatalf("len(entries) = %d, want 2 and no MaxItems truncation", len(entries))
	}

	want := RawEntry{
		SourceName:  "knowledge-agent-releases",
		SourceType:  SourceTypeGitHubRelease,
		ExternalID:  "tag:github.com,2008:Repository/123456789/v1.2.0",
		URL:         "https://github.com/acme/knowledge-agent/releases/tag/v1.2.0",
		Title:       "Knowledge Agent v1.2.0",
		Author:      "release-bot",
		PublishedAt: "2026-06-05T04:30:00Z",
		Tags:        []string{"stable", "crawler", "v1.2.0"},
	}
	assertRawEntryFields(t, entries[0], want)
	for _, text := range []string{"What's changed", "Added source adapters."} {
		if !strings.Contains(entries[0].SourceContent, text) {
			t.Fatalf("SourceContent = %q, want %q", entries[0].SourceContent, text)
		}
	}
	assertRawPayload(t, entries[0].RawPayload, "release-bot")
	assertMissingAuthorAndTime(t, entries[1])
	if !reflect.DeepEqual(entries[1].Tags, []string{"maintenance", "v1.1.0"}) {
		t.Fatalf("sparse release tags = %v, want category and URL tag fallback", entries[1].Tags)
	}
}

func TestGitHubReleaseAdapterRejectsInvalidPayloads(t *testing.T) {
	assertAdapterRejectsInvalidPayloads(t, SourceTypeGitHubRelease)
}

func TestHuggingFaceAdapterMapsPapersFeed(t *testing.T) {
	adapter := mustAdapter(t, SourceTypeHuggingFacePapers)
	entries, err := adapter.Parse(Source{Name: "hf-daily-papers", Type: SourceTypeHuggingFacePapers, MaxItems: 1}, fixtureBytes(t, "huggingface_papers.xml"))
	if err != nil {
		t.Fatalf("Parse() error = %v", err)
	}
	if len(entries) != 2 {
		t.Fatalf("len(entries) = %d, want 2 and no MaxItems truncation", len(entries))
	}

	want := RawEntry{
		SourceName:  "hf-daily-papers",
		SourceType:  SourceTypeHuggingFacePapers,
		ExternalID:  "https://huggingface.co/papers/2606.01234",
		URL:         "https://huggingface.co/papers/2606.01234",
		Title:       "Compact Models for Knowledge Work",
		Author:      "Carol Author, Dan Author",
		PublishedAt: "2026-06-06T07:00:00Z",
		Tags:        []string{"Machine Learning", "Retrieval"},
	}
	assertRawEntryFields(t, entries[0], want)
	if entries[0].SourceContent != "A compact model that improves retrieval and grounded generation." {
		t.Fatalf("SourceContent = %q, want cleaned paper summary", entries[0].SourceContent)
	}
	assertRawPayload(t, entries[0].RawPayload, "Compact Models for Knowledge Work")
	assertMissingAuthorAndTime(t, entries[1])
	if entries[1].URL != "https://huggingface.co/papers/2606.09999" {
		t.Fatalf("sparse paper URL = %q, want Hugging Face paper URL", entries[1].URL)
	}
}

func TestHuggingFaceAdapterRejectsOrdinaryFeeds(t *testing.T) {
	adapter := mustAdapter(t, SourceTypeHuggingFacePapers)
	for _, fixture := range []string{"rss.xml", "atom.xml"} {
		t.Run(fixture, func(t *testing.T) {
			_, err := adapter.Parse(Source{Name: "not-hugging-face", Type: SourceTypeHuggingFacePapers}, fixtureBytes(t, fixture))
			assertAdapterParseError(t, err)
		})
	}
}

func TestHuggingFaceAdapterAcceptsPapersAtom(t *testing.T) {
	const payload = `<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Hugging Face - Daily Papers</title>
  <link rel="alternate" href="https://huggingface.co/papers"/>
  <entry>
    <id>https://huggingface.co/papers/2606.07777</id>
    <link rel="alternate" href="https://huggingface.co/papers/2606.07777"/>
    <title>Atom Paper</title>
    <summary>Atom paper summary.</summary>
  </entry>
</feed>`
	adapter := mustAdapter(t, SourceTypeHuggingFacePapers)
	entries, err := adapter.Parse(Source{Name: "hf-atom", Type: SourceTypeHuggingFacePapers}, []byte(payload))
	if err != nil {
		t.Fatalf("Parse() error = %v", err)
	}
	if len(entries) != 1 || entries[0].URL != "https://huggingface.co/papers/2606.07777" || entries[0].SourceContent != "Atom paper summary." {
		t.Fatalf("entries = %+v, want mapped Hugging Face Atom paper", entries)
	}
}

func TestHuggingFaceAdapterRejectsInvalidPayloads(t *testing.T) {
	assertAdapterRejectsInvalidPayloads(t, SourceTypeHuggingFacePapers)
}

func assertAdapterRejectsInvalidPayloads(t *testing.T, sourceType SourceType) {
	t.Helper()
	adapter := mustAdapter(t, sourceType)
	for _, payload := range [][]byte{
		nil,
		{},
		[]byte("<feed><entry>"),
		[]byte("<feed><entry></feed>"),
		[]byte("<feed></feed><feed></feed>"),
	} {
		_, err := adapter.Parse(Source{Name: "invalid", Type: sourceType}, payload)
		assertAdapterParseError(t, err)
	}
}

func assertMissingAuthorAndTime(t *testing.T, entry RawEntry) {
	t.Helper()
	if entry.Author != "" || entry.PublishedAt != "" {
		t.Fatalf("sparse entry author/time = %q/%q, want empty values", entry.Author, entry.PublishedAt)
	}
	assertRawPayload(t, entry.RawPayload, entry.Title)
}

func assertAdapterParseError(t *testing.T, err error) {
	t.Helper()
	if err == nil {
		t.Fatal("error = nil, want parse error")
	}
	var crawlErr *CrawlError
	if !errors.As(err, &crawlErr) {
		t.Fatalf("error type = %T, want *CrawlError", err)
	}
	if crawlErr.Type != ErrorParse {
		t.Fatalf("CrawlError.Type = %q, want %q", crawlErr.Type, ErrorParse)
	}
	if crawlErr.Retryable {
		t.Fatal("CrawlError.Retryable = true, want false")
	}
}

func assertRawEntryFields(t *testing.T, got, want RawEntry) {
	t.Helper()
	if got.SourceName != want.SourceName ||
		got.SourceType != want.SourceType ||
		got.ExternalID != want.ExternalID ||
		got.URL != want.URL ||
		got.Title != want.Title ||
		got.Author != want.Author ||
		got.PublishedAt != want.PublishedAt ||
		!reflect.DeepEqual(got.Tags, want.Tags) {
		t.Fatalf("entry fields = %+v, want %+v", got, want)
	}
}

func assertRawPayload(t *testing.T, payload any, wantMarker string) {
	t.Helper()
	encoded, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("json.Marshal(RawPayload) error = %v", err)
	}
	if !strings.Contains(string(encoded), wantMarker) {
		t.Fatalf("RawPayload JSON = %s, want marker %q", encoded, wantMarker)
	}
}

func fixtureBytes(t *testing.T, name string) []byte {
	t.Helper()
	payload, err := os.ReadFile(filepath.Join("testdata", name))
	if err != nil {
		t.Fatalf("read fixture %q: %v", name, err)
	}
	return payload
}

func iso88591Bytes(t *testing.T, value string) []byte {
	t.Helper()
	payload := make([]byte, 0, len(value))
	for _, r := range value {
		if r > 0xff {
			t.Fatalf("rune %q cannot be encoded as ISO-8859-1", r)
		}
		payload = append(payload, byte(r))
	}
	return payload
}

func mustAdapter(t *testing.T, sourceType SourceType) SourceAdapter {
	t.Helper()
	adapter, err := NewAdapter(sourceType)
	if err != nil {
		t.Fatalf("NewAdapter(%q) error = %v", sourceType, err)
	}
	return adapter
}
