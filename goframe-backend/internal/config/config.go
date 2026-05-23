package config

import (
	"context"
	"os"
	"path/filepath"
	"strconv"

	"gopkg.in/yaml.v3"
)

type Config struct {
	Server  ServerConfig  `yaml:"server"`
	Agent   AgentConfig   `yaml:"agent"`
	MySQL   MySQLConfig   `yaml:"mysql"`
	Schema  SchemaConfig  `yaml:"schema"`
	RSS     RSSConfig     `yaml:"rss"`
	Crawler CrawlerConfig `yaml:"crawler"`
	Output  OutputConfig  `yaml:"output"`
	Profile ProfileConfig `yaml:"profile"`
}

type ServerConfig struct {
	Address string `yaml:"address"`
}

type AgentConfig struct {
	Address        string `yaml:"address"`
	TimeoutSeconds int    `yaml:"timeout_seconds"`
	RetryTimes     int    `yaml:"retry_times"`
}

type MySQLConfig struct {
	DSN string `yaml:"dsn"`
}

type SchemaConfig struct {
	Path string `yaml:"path"`
}

type RSSConfig struct {
	Sources []RSSSource `yaml:"sources"`
}

type RSSSource struct {
	Name     string `yaml:"name"`
	URL      string `yaml:"url"`
	Enabled  bool   `yaml:"enabled"`
	MaxItems int    `yaml:"max_items"`
}

type CrawlerConfig struct {
	SourceMaxItems int `yaml:"source_max_items"`
	RunMaxArticles int `yaml:"run_max_articles"`
}

type OutputConfig struct {
	Dir string `yaml:"dir"`
}

type ProfileConfig struct {
	UserID    string `yaml:"user_id"`
	Interests string `yaml:"interests"`
}

func Load(ctx context.Context) Config {
	_ = ctx
	cfg := defaults()
	configPath := envOrDefault("CONFIG_PATH", filepath.Join("manifest", "config", "config.yaml"))
	if data, err := os.ReadFile(configPath); err == nil {
		_ = yaml.Unmarshal(data, &cfg)
	}

	cfg.Server.Address = envOrDefault("GOFRAME_HTTP_ADDR", cfg.Server.Address)
	cfg.Agent.Address = envOrDefault("AGENT_GRPC_ADDR", cfg.Agent.Address)
	cfg.MySQL.DSN = envOrDefault("MYSQL_DSN", cfg.MySQL.DSN)
	cfg.Output.Dir = envOrDefault("OUTPUT_DIR", cfg.Output.Dir)
	if value := os.Getenv("AGENT_TIMEOUT_SECONDS"); value != "" {
		if parsed, err := strconv.Atoi(value); err == nil {
			cfg.Agent.TimeoutSeconds = parsed
		}
	}
	if value := os.Getenv("AGENT_RETRY_TIMES"); value != "" {
		if parsed, err := strconv.Atoi(value); err == nil {
			cfg.Agent.RetryTimes = parsed
		}
	}
	return cfg.Normalize()
}

func (c Config) Normalize() Config {
	if c.Server.Address == "" {
		c.Server.Address = ":8080"
	}
	if c.Agent.Address == "" {
		c.Agent.Address = "127.0.0.1:50051"
	}
	if c.Agent.TimeoutSeconds <= 0 {
		c.Agent.TimeoutSeconds = 8
	}
	if c.Agent.RetryTimes <= 0 {
		c.Agent.RetryTimes = 3
	}
	if c.Crawler.SourceMaxItems <= 0 {
		c.Crawler.SourceMaxItems = 10
	}
	if c.Crawler.RunMaxArticles <= 0 {
		c.Crawler.RunMaxArticles = 20
	}
	if c.Output.Dir == "" {
		c.Output.Dir = "../shared/outputs"
	}
	if c.Profile.UserID == "" {
		c.Profile.UserID = "default-user"
	}
	return c
}

func defaults() Config {
	return Config{
		Server: ServerConfig{Address: ":8080"},
		Agent: AgentConfig{
			Address:        "127.0.0.1:50051",
			TimeoutSeconds: 8,
			RetryTimes:     3,
		},
		MySQL: MySQLConfig{
			DSN: "root:rootpass@tcp(127.0.0.1:3306)/knowledge_post_agent?charset=utf8mb4&parseTime=true&loc=Local",
		},
		Schema: SchemaConfig{Path: "../shared/sql/init.sql"},
		RSS: RSSConfig{Sources: []RSSSource{
			{Name: "mock-knowledge-feed", URL: "mock://sample", Enabled: true, MaxItems: 5},
		}},
		Crawler: CrawlerConfig{SourceMaxItems: 10, RunMaxArticles: 20},
		Output:  OutputConfig{Dir: "../shared/outputs"},
		Profile: ProfileConfig{
			UserID:    "default-user",
			Interests: "AI,knowledge-management,engineering",
		},
	}
}

func envOrDefault(key string, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
