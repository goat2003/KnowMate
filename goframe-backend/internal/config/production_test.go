package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestProductionRejectsMockSources(t *testing.T) {
	t.Setenv("APP_ENV", "production")
	t.Setenv("CONFIG_PATH", "sources.yaml")
	cfg := defaults().Normalize()
	cfg.Security.APIToken = strings.Repeat("a", 32)
	cfg.Agent.AuthToken = strings.Repeat("b", 32)
	if cfg.ValidateProduction() == nil {
		t.Fatal("mock source must be rejected")
	}
	cfg.Crawler.Sources = []SourceConfig{{Type: "feed", URL: "https://example.org/feed", Enabled: true}}
	if err := cfg.ValidateProduction(); err != nil {
		t.Fatal(err)
	}
	cfg.Security.APIToken = ""
	if cfg.ValidateProduction() == nil {
		t.Fatal("missing token must be rejected")
	}
}

func TestSecretFilePrecedesEnvironment(t *testing.T) {
	path := filepath.Join(t.TempDir(), "token")
	if err := os.WriteFile(path, []byte("file-value\n"), 0600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("GOFRAME_API_TOKEN", "old-value")
	t.Setenv("GOFRAME_API_TOKEN_FILE", path)
	if value := envOrDefault("GOFRAME_API_TOKEN", ""); value != "file-value" {
		t.Fatal("file ignored")
	}
}
