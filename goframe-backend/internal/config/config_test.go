package config

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestNormalizeMapsLegacyRSSSourcesWhenCrawlerSourcesAreEmpty(t *testing.T) {
	cfg := Config{
		RSS: RSSConfig{Sources: []RSSSource{
			{Name: "legacy", URL: "https://example.com/feed.xml", Enabled: true, MaxItems: 3},
			{Name: "mock", URL: "mock://sample", Enabled: true, MaxItems: 2},
		}},
	}.Normalize()

	if len(cfg.Crawler.Sources) != 2 {
		t.Fatalf("sources=%#v", cfg.Crawler.Sources)
	}
	if cfg.Crawler.Sources[0].Type != "feed" || cfg.Crawler.Sources[1].Type != "mock" {
		t.Fatalf("legacy source types=%#v", cfg.Crawler.Sources)
	}
}

func TestNormalizePrefersCrawlerSourcesOverLegacyRSS(t *testing.T) {
	cfg := Config{
		RSS:     RSSConfig{Sources: []RSSSource{{Name: "legacy", URL: "https://example.com/rss", Enabled: true}}},
		Crawler: CrawlerConfig{Sources: []SourceConfig{{Name: "arxiv", Type: "arxiv", URL: "https://example.com/arxiv", Enabled: true}}},
	}.Normalize()

	if len(cfg.Crawler.Sources) != 1 || cfg.Crawler.Sources[0].Name != "arxiv" {
		t.Fatalf("sources=%#v", cfg.Crawler.Sources)
	}
}

func TestNormalizeCrawlerDefaults(t *testing.T) {
	cfg := (Config{}).Normalize()
	if cfg.Crawler.UserAgent == "" || cfg.Crawler.RequestTimeoutSeconds <= 0 || cfg.Crawler.RetryTimes <= 0 ||
		cfg.Crawler.RetryBackoffMilliseconds <= 0 || cfg.Crawler.MaxRetryDelayMilliseconds <= 0 ||
		cfg.Crawler.PerHostIntervalMilliseconds <= 0 || cfg.Crawler.MaxResponseBytes <= 0 || cfg.Crawler.RobotsCacheSeconds <= 0 {
		t.Fatalf("crawler defaults incomplete: %#v", cfg.Crawler)
	}
}

func TestLoadCrawlerEnvironmentOverrides(t *testing.T) {
	temp := t.TempDir()
	configPath := filepath.Join(temp, "config.yaml")
	if err := os.WriteFile(configPath, []byte(`crawler:
  user_agent: "yaml-agent"
  request_timeout_seconds: 2
  retry_times: 1
  retry_backoff_milliseconds: 10
  max_retry_delay_milliseconds: 20
  per_host_interval_milliseconds: 30
  max_response_bytes: 1024
  robots_cache_seconds: 40
  sources:
    - name: "feed"
      type: "feed"
      url: "https://example.com/feed"
      enabled: true
`), 0o600); err != nil {
		t.Fatal(err)
	}

	t.Setenv("CONFIG_PATH", configPath)
	t.Setenv("CRAWLER_USER_AGENT", "env-agent")
	t.Setenv("CRAWLER_REQUEST_TIMEOUT_SECONDS", "11")
	t.Setenv("CRAWLER_RETRY_TIMES", "4")
	t.Setenv("CRAWLER_RETRY_BACKOFF_MILLISECONDS", "120")
	t.Setenv("CRAWLER_MAX_RETRY_DELAY_MILLISECONDS", "450")
	t.Setenv("CRAWLER_PER_HOST_INTERVAL_MILLISECONDS", "250")
	t.Setenv("CRAWLER_MAX_RESPONSE_BYTES", "4096")
	t.Setenv("CRAWLER_ROBOTS_CACHE_SECONDS", "90")
	t.Setenv("CRAWLER_SOURCE_MAX_ITEMS", "7")
	t.Setenv("CRAWLER_RUN_MAX_ARTICLES", "15")

	cfg := Load(context.Background())
	if cfg.Crawler.UserAgent != "env-agent" || cfg.Crawler.RequestTimeoutSeconds != 11 ||
		cfg.Crawler.RetryTimes != 4 || cfg.Crawler.RetryBackoffMilliseconds != 120 ||
		cfg.Crawler.MaxRetryDelayMilliseconds != 450 || cfg.Crawler.PerHostIntervalMilliseconds != 250 ||
		cfg.Crawler.MaxResponseBytes != 4096 || cfg.Crawler.RobotsCacheSeconds != 90 ||
		cfg.Crawler.SourceMaxItems != 7 || cfg.Crawler.RunMaxArticles != 15 {
		t.Fatalf("overrides not applied: %#v", cfg.Crawler)
	}
	if len(cfg.Crawler.Sources) != 1 || cfg.Crawler.Sources[0].Name != "feed" {
		t.Fatalf("sources=%#v", cfg.Crawler.Sources)
	}
}

func TestLoadSecurityEnvironmentOverrides(t *testing.T) {
	temp := t.TempDir()
	configPath := filepath.Join(temp, "config.yaml")
	if err := os.WriteFile(configPath, []byte(`security:
  api_token: "yaml-token"
  max_request_body_bytes: 1000
  rate_limit_burst: 2
agent:
  auth_token: "yaml-agent-token"
`), 0o600); err != nil {
		t.Fatal(err)
	}

	t.Setenv("CONFIG_PATH", configPath)
	t.Setenv("GOFRAME_API_TOKEN", "env-token")
	t.Setenv("GOFRAME_MAX_REQUEST_BODY_BYTES", "2048")
	t.Setenv("GOFRAME_RATE_LIMIT_BURST", "7")
	t.Setenv("AGENT_GRPC_AUTH_TOKEN", "env-agent-token")

	cfg := Load(context.Background())

	if cfg.Security.APIToken != "env-token" {
		t.Fatalf("api token=%q", cfg.Security.APIToken)
	}
	if cfg.Security.MaxRequestBodyBytes != 2048 {
		t.Fatalf("max request body=%d", cfg.Security.MaxRequestBodyBytes)
	}
	if cfg.Security.RateLimitBurst != 7 {
		t.Fatalf("rate limit burst=%d", cfg.Security.RateLimitBurst)
	}
	if cfg.Agent.AuthToken != "env-agent-token" {
		t.Fatalf("agent auth token=%q", cfg.Agent.AuthToken)
	}
}
