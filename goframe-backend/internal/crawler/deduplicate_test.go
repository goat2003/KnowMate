package crawler

import (
	"testing"

	"knowledge-post-agent/goframe-backend/internal/model"
)

func TestDeduplicateUsesURLTitleContentAndID(t *testing.T) {
	articles := []model.Article{
		{ID: "one", URLHash: "url-a", TitleHash: "title-a", ContentHash: "content-a"},
		{ID: "two", URLHash: "url-a", TitleHash: "title-b", ContentHash: "content-b"},
		{ID: "three", URLHash: "url-c", TitleHash: "title-a", ContentHash: "content-c"},
		{ID: "four", URLHash: "url-d", TitleHash: "title-d", ContentHash: "content-a"},
		{ID: "one", URLHash: "url-e", TitleHash: "title-e", ContentHash: "content-e"},
		{ID: "unique", URLHash: "url-f", TitleHash: "title-f", ContentHash: "content-f"},
	}

	got := Deduplicate(articles, 0)
	if len(got) != 2 || got[0].ID != "one" || got[1].ID != "unique" {
		t.Fatalf("unexpected dedupe result: %#v", got)
	}
}

func TestDeduplicateIgnoresEmptyKeysAndHonorsLimit(t *testing.T) {
	articles := []model.Article{{ID: "a"}, {ID: "b"}, {ID: "c"}}
	got := Deduplicate(articles, 2)
	if len(got) != 2 || got[0].ID != "a" || got[1].ID != "b" {
		t.Fatalf("unexpected result: %#v", got)
	}
}

func TestProcessableOnlyReturnsUsableSuccessAndPartial(t *testing.T) {
	articles := []model.Article{
		{ID: "success", FetchStatus: "success", Content: "body"},
		{ID: "partial", FetchStatus: "partial", Content: "summary"},
		{ID: "failed", FetchStatus: "failed", Content: ""},
		{ID: "empty", FetchStatus: "success", Content: ""},
	}
	got := Processable(articles)
	if len(got) != 2 || got[0].ID != "success" || got[1].ID != "partial" {
		t.Fatalf("unexpected processable result: %#v", got)
	}
}
