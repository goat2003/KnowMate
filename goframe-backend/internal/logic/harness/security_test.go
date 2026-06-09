package harness

import (
	"path/filepath"
	"strings"
	"testing"

	"knowledge-post-agent/goframe-backend/internal/config"
	"knowledge-post-agent/goframe-backend/internal/model"
)

func TestWriteMarkdownKeepsRunIDInsideOutputDir(t *testing.T) {
	outputDir := t.TempDir()
	harness := newWithDependencies(
		config.Config{Output: config.OutputConfig{Dir: outputDir}},
		&fakeArticleStore{},
		&fakeSourceCrawler{},
	)

	path, err := harness.writeMarkdown("../escape\\system:prompt", []model.Post{
		{PostUID: "p1", ArticleUID: "a1", Markdown: "hello"},
	})
	if err != nil {
		t.Fatalf("writeMarkdown: %v", err)
	}

	rel, err := filepath.Rel(outputDir, path)
	if err != nil {
		t.Fatalf("rel: %v", err)
	}
	if rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) || filepath.IsAbs(rel) {
		t.Fatalf("path escaped output dir: %s", path)
	}
	if strings.Contains(rel, "..") || strings.ContainsAny(filepath.Base(rel), `\/:`) {
		t.Fatalf("unsafe markdown filename: %q", rel)
	}
}
