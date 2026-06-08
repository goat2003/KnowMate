package crawler

import (
	"bytes"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"net/url"
	"strings"
	"time"

	"github.com/mmcdole/gofeed"
	"github.com/mmcdole/gofeed/atom"
	"golang.org/x/net/html/charset"
)

type SourceAdapter interface {
	Type() SourceType
	Parse(source Source, payload []byte) ([]RawEntry, error)
}

type feedAdapter struct{}

type arxivAdapter struct{}

type githubReleaseAdapter struct{}

type huggingFaceAdapter struct{}

type mockAdapter struct{}

func NewAdapter(sourceType SourceType) (SourceAdapter, error) {
	switch sourceType {
	case SourceTypeFeed:
		return feedAdapter{}, nil
	case SourceTypeArxiv:
		return arxivAdapter{}, nil
	case SourceTypeGitHubRelease:
		return githubReleaseAdapter{}, nil
	case SourceTypeHuggingFacePapers:
		return huggingFaceAdapter{}, nil
	case SourceTypeMock:
		return mockAdapter{}, nil
	default:
		return nil, adapterParseError(fmt.Sprintf("unknown source type %q", sourceType), nil)
	}
}

func (feedAdapter) Type() SourceType {
	return SourceTypeFeed
}

func (a feedAdapter) Parse(source Source, payload []byte) ([]RawEntry, error) {
	feed, err := parseUniversalFeed(payload)
	if err != nil {
		return nil, err
	}
	return mapUniversalItems(source, a.Type(), feed.Items), nil
}

func (arxivAdapter) Type() SourceType {
	return SourceTypeArxiv
}

func (a arxivAdapter) Parse(source Source, payload []byte) ([]RawEntry, error) {
	entries, err := parseAtomEntries(payload)
	if err != nil {
		return nil, err
	}

	result := make([]RawEntry, 0, len(entries))
	for _, entry := range entries {
		if entry == nil {
			continue
		}
		entryURL := atomEntryURL(entry)
		result = append(result, RawEntry{
			SourceName:       source.Name,
			SourceType:       a.Type(),
			ExternalID:       firstAdapterNonEmpty(entry.ID, entryURL, entry.Title),
			URL:              entryURL,
			Title:            strings.TrimSpace(entry.Title),
			RawSourceContent: entry.Summary,
			SourceContent:    CleanHTMLFragment(entry.Summary),
			Author:           atomAuthors(entry.Authors),
			PublishedAt:      adapterPublishedAt(entry.PublishedParsed, entry.UpdatedParsed, entry.Published, entry.Updated),
			Tags:             atomCategories(entry.Categories),
			RawPayload:       entry,
		})
	}
	return result, nil
}

func (githubReleaseAdapter) Type() SourceType {
	return SourceTypeGitHubRelease
}

func (a githubReleaseAdapter) Parse(source Source, payload []byte) ([]RawEntry, error) {
	entries, err := parseAtomEntries(payload)
	if err != nil {
		return nil, err
	}

	result := make([]RawEntry, 0, len(entries))
	for _, entry := range entries {
		if entry == nil {
			continue
		}
		entryURL := atomEntryURL(entry)
		tags := atomCategories(entry.Categories)
		tags = appendUnique(tags, githubReleaseTag(entryURL))
		content := entry.Summary
		if entry.Content != nil {
			content = firstAdapterNonEmpty(entry.Content.Value, content)
		}
		result = append(result, RawEntry{
			SourceName:       source.Name,
			SourceType:       a.Type(),
			ExternalID:       firstAdapterNonEmpty(entry.ID, entryURL, entry.Title),
			URL:              entryURL,
			Title:            strings.TrimSpace(entry.Title),
			RawSourceContent: content,
			SourceContent:    CleanHTMLFragment(content),
			Author:           atomAuthors(entry.Authors),
			PublishedAt:      adapterPublishedAt(entry.PublishedParsed, entry.UpdatedParsed, entry.Published, entry.Updated),
			Tags:             tags,
			RawPayload:       entry,
		})
	}
	return result, nil
}

func (huggingFaceAdapter) Type() SourceType {
	return SourceTypeHuggingFacePapers
}

func (a huggingFaceAdapter) Parse(source Source, payload []byte) ([]RawEntry, error) {
	feed, err := parseUniversalFeed(payload)
	if err != nil {
		return nil, err
	}
	if !isHuggingFacePapersFeed(feed) {
		return nil, adapterParseError("payload is not a Hugging Face Papers feed", nil)
	}

	result := make([]RawEntry, 0, len(feed.Items))
	for _, item := range feed.Items {
		if item == nil {
			continue
		}
		paperURL := huggingFacePaperURL(item)
		result = append(result, RawEntry{
			SourceName:       source.Name,
			SourceType:       a.Type(),
			ExternalID:       firstAdapterNonEmpty(item.GUID, paperURL, item.Title),
			URL:              paperURL,
			Title:            strings.TrimSpace(item.Title),
			RawSourceContent: firstAdapterNonEmpty(item.Content, item.Description),
			SourceContent:    CleanHTMLFragment(firstAdapterNonEmpty(item.Content, item.Description)),
			Author:           universalAuthors(item),
			PublishedAt:      adapterPublishedAt(item.PublishedParsed, item.UpdatedParsed, item.Published, item.Updated),
			Tags:             appendUnique(nil, item.Categories...),
			RawPayload:       item,
		})
	}
	return result, nil
}

func (mockAdapter) Type() SourceType {
	return SourceTypeMock
}

func (a mockAdapter) Parse(source Source, _ []byte) ([]RawEntry, error) {
	seeds := []struct {
		id      string
		url     string
		title   string
		content string
		tags    []string
	}{
		{
			id:      "mock-agent-workflow",
			url:     "https://example.com/mock-agent-workflow",
			title:   "Agent Workflow for Knowledge Posts",
			content: "This article explains how to compose filter, summary, rewrite, and check nodes for reliable knowledge post generation.",
			tags:    []string{"AI", "workflow"},
		},
		{
			id:      "mock-knowledge-memory",
			url:     "https://example.com/mock-knowledge-memory",
			title:   "Personal Knowledge Memory with Graph Signals",
			content: "A practical note about combining user feedback, profile snapshots, and graph context for personalized recommendations.",
			tags:    []string{"knowledge-management", "memory"},
		},
	}
	result := make([]RawEntry, 0, len(seeds))
	for _, seed := range seeds {
		result = append(result, RawEntry{
			SourceName:       source.Name,
			SourceType:       a.Type(),
			ExternalID:       seed.id,
			URL:              seed.url,
			Title:            seed.title,
			RawSourceContent: seed.content,
			SourceContent:    seed.content,
			Tags:             seed.tags,
			RawPayload: map[string]any{
				"external_id": seed.id,
				"url":         seed.url,
				"title":       seed.title,
				"content":     seed.content,
				"tags":        seed.tags,
			},
		})
	}
	return result, nil
}

func parseUniversalFeed(payload []byte) (*gofeed.Feed, error) {
	if err := validateXMLPayload(payload); err != nil {
		return nil, err
	}
	feed, err := gofeed.NewParser().Parse(bytes.NewReader(payload))
	if err != nil {
		return nil, adapterParseError("could not parse feed payload", err)
	}
	return feed, nil
}

func parseAtomEntries(payload []byte) ([]*atom.Entry, error) {
	if err := validateXMLPayload(payload); err != nil {
		return nil, err
	}
	feed, err := (&atom.Parser{}).Parse(bytes.NewReader(payload))
	if err != nil {
		return nil, adapterParseError("could not parse Atom payload", err)
	}
	return feed.Entries, nil
}

func validateXMLPayload(payload []byte) error {
	if len(bytes.TrimSpace(payload)) == 0 {
		return adapterParseError("XML payload is empty", errors.New("empty payload"))
	}
	decoder := xml.NewDecoder(bytes.NewReader(payload))
	decoder.Strict = true
	decoder.CharsetReader = charset.NewReaderLabel
	depth := 0
	rootCount := 0
	for {
		token, err := decoder.Token()
		switch {
		case errors.Is(err, io.EOF):
			if rootCount != 1 {
				return adapterParseError("XML payload must contain exactly one root element", nil)
			}
			return nil
		case err != nil:
			return adapterParseError("XML payload is not well-formed", err)
		}
		switch value := token.(type) {
		case xml.StartElement:
			if depth == 0 {
				rootCount++
				if rootCount > 1 {
					return adapterParseError("XML payload must contain exactly one root element", nil)
				}
			}
			depth++
		case xml.EndElement:
			depth--
		case xml.CharData:
			if depth == 0 && strings.TrimSpace(string(value)) != "" {
				return adapterParseError("XML payload contains text outside the root element", nil)
			}
		}
	}
}

func mapUniversalItems(source Source, sourceType SourceType, items []*gofeed.Item) []RawEntry {
	result := make([]RawEntry, 0, len(items))
	for _, item := range items {
		if item == nil {
			continue
		}
		result = append(result, RawEntry{
			SourceName:       source.Name,
			SourceType:       sourceType,
			ExternalID:       firstAdapterNonEmpty(item.GUID, item.Link, item.Title),
			URL:              strings.TrimSpace(item.Link),
			Title:            strings.TrimSpace(item.Title),
			RawSourceContent: firstAdapterNonEmpty(item.Content, item.Description),
			SourceContent:    CleanHTMLFragment(firstAdapterNonEmpty(item.Content, item.Description)),
			Author:           universalAuthors(item),
			PublishedAt:      adapterPublishedAt(item.PublishedParsed, item.UpdatedParsed, item.Published, item.Updated),
			Tags:             appendUnique(nil, item.Categories...),
			RawPayload:       item,
		})
	}
	return result
}

func universalAuthors(item *gofeed.Item) string {
	names := make([]string, 0, len(item.Authors))
	for _, author := range item.Authors {
		if author != nil {
			names = appendUnique(names, author.Name)
		}
	}
	if item.DublinCoreExt != nil {
		names = appendUnique(names, item.DublinCoreExt.Creator...)
		names = appendUnique(names, item.DublinCoreExt.Author...)
	}
	if len(names) == 0 && item.Author != nil {
		names = appendUnique(names, item.Author.Name)
	}
	return strings.Join(names, ", ")
}

func isHuggingFacePapersFeed(feed *gofeed.Feed) bool {
	if feed == nil {
		return false
	}
	title := strings.ToLower(strings.TrimSpace(feed.Title))
	if !strings.Contains(title, "hugging face") || !strings.Contains(title, "paper") {
		return false
	}
	if !isHuggingFacePapersURL(feed.Link) {
		return false
	}
	for _, item := range feed.Items {
		if item != nil && huggingFacePaperURL(item) != "" {
			return true
		}
	}
	return false
}

func huggingFacePaperURL(item *gofeed.Item) string {
	candidates := make([]string, 0, 2+len(item.Links))
	candidates = append(candidates, item.Link, item.GUID)
	candidates = append(candidates, item.Links...)
	for _, candidate := range candidates {
		if isHuggingFacePaperURL(candidate) {
			return strings.TrimSpace(candidate)
		}
	}
	return ""
}

func isHuggingFacePapersURL(rawURL string) bool {
	parsed, err := url.Parse(strings.TrimSpace(rawURL))
	if err != nil || !strings.EqualFold(parsed.Hostname(), "huggingface.co") {
		return false
	}
	path := strings.TrimSuffix(parsed.EscapedPath(), "/")
	return path == "/papers"
}

func isHuggingFacePaperURL(rawURL string) bool {
	parsed, err := url.Parse(strings.TrimSpace(rawURL))
	if err != nil || !strings.EqualFold(parsed.Hostname(), "huggingface.co") {
		return false
	}
	return strings.HasPrefix(parsed.EscapedPath(), "/papers/") && strings.TrimPrefix(parsed.EscapedPath(), "/papers/") != ""
}

func atomAuthors(authors []*atom.Person) string {
	names := make([]string, 0, len(authors))
	for _, author := range authors {
		if author != nil {
			names = appendUnique(names, author.Name)
		}
	}
	return strings.Join(names, ", ")
}

func atomEntryURL(entry *atom.Entry) string {
	for _, link := range entry.Links {
		if link != nil && (link.Rel == "" || strings.EqualFold(link.Rel, "alternate")) && strings.TrimSpace(link.Href) != "" {
			return strings.TrimSpace(link.Href)
		}
	}
	for _, link := range entry.Links {
		if link != nil && strings.TrimSpace(link.Href) != "" {
			return strings.TrimSpace(link.Href)
		}
	}
	return ""
}

func atomCategories(categories []*atom.Category) []string {
	tags := make([]string, 0, len(categories))
	for _, category := range categories {
		if category != nil {
			tags = appendUnique(tags, category.Term)
		}
	}
	return tags
}

func githubReleaseTag(rawURL string) string {
	parsed, err := url.Parse(strings.TrimSpace(rawURL))
	if err != nil {
		return ""
	}
	const marker = "/releases/tag/"
	index := strings.Index(parsed.EscapedPath(), marker)
	if index < 0 {
		return ""
	}
	tag, err := url.PathUnescape(strings.TrimPrefix(parsed.EscapedPath()[index:], marker))
	if err != nil {
		return ""
	}
	return strings.TrimSpace(tag)
}

func adapterPublishedAt(publishedParsed, updatedParsed *time.Time, published, updated string) string {
	if publishedParsed != nil {
		return publishedParsed.Format(time.RFC3339)
	}
	if value := parseAdapterTime(published); value != "" {
		return value
	}
	if updatedParsed != nil {
		return updatedParsed.Format(time.RFC3339)
	}
	return parseAdapterTime(updated)
}

func parseAdapterTime(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	parsed, err := time.Parse(time.RFC3339, value)
	if err != nil {
		return ""
	}
	return parsed.Format(time.RFC3339)
}

func appendUnique(values []string, candidates ...string) []string {
	for _, candidate := range candidates {
		candidate = strings.TrimSpace(candidate)
		if candidate == "" {
			continue
		}
		found := false
		for _, value := range values {
			if value == candidate {
				found = true
				break
			}
		}
		if !found {
			values = append(values, candidate)
		}
	}
	return values
}

func firstAdapterNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return strings.TrimSpace(value)
		}
	}
	return ""
}

func adapterParseError(message string, err error) error {
	return NewCrawlError(ErrorParse, message, 0, false, err)
}
