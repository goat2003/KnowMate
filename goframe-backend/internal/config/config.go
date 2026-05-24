// 文件作用：
// 本文件负责加载 GoFrame 后端配置。
// 配置来源包括默认值、manifest/config/config.yaml 和环境变量，最终合并为 Config。
//
// 在项目中的位置：
// 本文件属于 GoFrame 后端的配置层，被 main.go 和 logic/harness 使用。
//
// 主要内容：
// 1. Config 及其子配置结构体：描述 HTTP、Agent、MySQL、RSS、输出和用户画像配置。
// 2. Load：读取配置文件和环境变量。
// 3. Normalize：补齐必要默认值。
// 4. defaults：提供本地开发默认配置。
//
// 关键调用关系：
// - main.go 调用 Load。
// - harness 读取 Agent、RSS、Crawler、Output、Profile 配置。
// - store 使用 MySQL.DSN 和 Schema.Path。
//
// 初学者阅读建议：
// 先看 Config 中有哪些配置段，再看 Load 如何让环境变量覆盖 YAML。
package config

import (
	// context.Context 作为 GoFrame/服务调用中的标准上下文类型。
	"context"
	// os 用于读取环境变量和配置文件。
	"os"
	// filepath 用于拼接默认配置文件路径。
	"path/filepath"
	// strconv 用于解析环境变量中的整数。
	"strconv"

	// yaml.v3 用于解析 manifest/config/config.yaml。
	"gopkg.in/yaml.v3"
)

// Config 是 GoFrame 后端完整配置。
// 每个字段的 yaml tag 对应 config.yaml 中的顶层 key。
type Config struct {
	// Server 是 HTTP 服务配置。
	Server ServerConfig `yaml:"server"`
	// Agent 是 Python Agent gRPC Client 配置。
	Agent AgentConfig `yaml:"agent"`
	// MySQL 是数据库连接配置。
	MySQL MySQLConfig `yaml:"mysql"`
	// Schema 是数据库初始化 SQL 路径配置。
	Schema SchemaConfig `yaml:"schema"`
	// RSS 是 RSS 源列表配置。
	RSS RSSConfig `yaml:"rss"`
	// Crawler 控制抓取数量。
	Crawler CrawlerConfig `yaml:"crawler"`
	// Output 控制 Markdown 输出目录。
	Output OutputConfig `yaml:"output"`
	// Profile 保存默认用户画像配置。
	Profile ProfileConfig `yaml:"profile"`
}

// ServerConfig 保存 HTTP Server 监听地址。
type ServerConfig struct {
	// Address 例如 ":8080"。
	Address string `yaml:"address"`
}

// AgentConfig 保存 Python Agent gRPC 连接配置。
type AgentConfig struct {
	// Address 是 Python Agent gRPC 地址，例如 "127.0.0.1:50051"。
	Address string `yaml:"address"`
	// TimeoutSeconds 是每次 gRPC 连接和调用的超时时间。
	TimeoutSeconds int `yaml:"timeout_seconds"`
	// RetryTimes 是调用 Python Agent 失败后的重试次数。
	RetryTimes int `yaml:"retry_times"`
}

// MySQLConfig 保存 MySQL DSN。
type MySQLConfig struct {
	// DSN 是 database/sql 使用的 MySQL 连接串。
	DSN string `yaml:"dsn"`
}

// SchemaConfig 保存初始化 SQL 文件路径。
type SchemaConfig struct {
	// Path 指向 shared/sql/init.sql。
	Path string `yaml:"path"`
}

// RSSConfig 保存 RSS 源列表。
type RSSConfig struct {
	// Sources 是可抓取的 RSSSource 列表。
	Sources []RSSSource `yaml:"sources"`
}

// RSSSource 表示一个 RSS 源配置。
type RSSSource struct {
	// Name 是源名称，会写入 Article.Source。
	Name string `yaml:"name"`
	// URL 是 RSS 地址；mock:// 前缀表示使用本地模拟文章。
	URL string `yaml:"url"`
	// Enabled 控制该源是否参与本次抓取。
	Enabled bool `yaml:"enabled"`
	// MaxItems 是该源最多抓取多少条。
	MaxItems int `yaml:"max_items"`
}

// CrawlerConfig 控制抓取和去重后的文章数量。
type CrawlerConfig struct {
	// SourceMaxItems 是单个源默认最多抓取数量。
	SourceMaxItems int `yaml:"source_max_items"`
	// RunMaxArticles 是一次任务最多处理的文章数量。
	RunMaxArticles int `yaml:"run_max_articles"`
}

// OutputConfig 保存输出目录配置。
type OutputConfig struct {
	// Dir 是 Markdown 文件输出目录。
	Dir string `yaml:"dir"`
}

// ProfileConfig 保存默认用户画像配置。
type ProfileConfig struct {
	// UserID 是默认用户 id。
	UserID string `yaml:"user_id"`
	// Interests 是默认兴趣关键词，Python FilterAgent 会读取 user_profile_snapshot 中的 interests。
	Interests string `yaml:"interests"`
}

// 函数作用：
// 加载后端配置。
//
// 参数说明：
// - ctx：上下文参数，当前函数不直接使用，保留以匹配 GoFrame 调用习惯。
//
// 返回值：
// - 返回归一化后的 Config。
//
// 配置优先级：
// - defaults() < config.yaml < 环境变量。
func Load(ctx context.Context) Config {
	// 当前函数暂不使用 ctx，赋值给空标识符避免编译器报未使用。
	_ = ctx
	// 先加载默认配置，保证即使没有配置文件也能本地运行。
	cfg := defaults()
	// CONFIG_PATH 可覆盖默认配置文件路径。
	configPath := envOrDefault("CONFIG_PATH", filepath.Join("manifest", "config", "config.yaml"))
	// 如果配置文件存在，就用 YAML 覆盖默认值。
	if data, err := os.ReadFile(configPath); err == nil {
		// yaml.Unmarshal 会按结构体 yaml tag 填充 cfg。
		_ = yaml.Unmarshal(data, &cfg)
	}

	// 以下环境变量用于部署时覆盖关键配置，不需要改动配置文件。
	cfg.Server.Address = envOrDefault("GOFRAME_HTTP_ADDR", cfg.Server.Address)
	cfg.Agent.Address = envOrDefault("AGENT_GRPC_ADDR", cfg.Agent.Address)
	cfg.MySQL.DSN = envOrDefault("MYSQL_DSN", cfg.MySQL.DSN)
	cfg.Output.Dir = envOrDefault("OUTPUT_DIR", cfg.Output.Dir)
	// AGENT_TIMEOUT_SECONDS 可覆盖 gRPC 超时时间。
	if value := os.Getenv("AGENT_TIMEOUT_SECONDS"); value != "" {
		if parsed, err := strconv.Atoi(value); err == nil {
			cfg.Agent.TimeoutSeconds = parsed
		}
	}
	// AGENT_RETRY_TIMES 可覆盖 gRPC 重试次数。
	if value := os.Getenv("AGENT_RETRY_TIMES"); value != "" {
		if parsed, err := strconv.Atoi(value); err == nil {
			cfg.Agent.RetryTimes = parsed
		}
	}
	// Normalize 补齐空值和非法值。
	return cfg.Normalize()
}

// 函数作用：
// 归一化配置，补齐必要默认值。
//
// 参数说明：
// - c：Config 值接收者，方法内部修改的是副本。
//
// 返回值：
// - 返回补齐后的 Config。
func (c Config) Normalize() Config {
	// HTTP 地址为空时使用 :8080。
	if c.Server.Address == "" {
		c.Server.Address = ":8080"
	}
	// Agent gRPC 地址为空时使用本地默认端口。
	if c.Agent.Address == "" {
		c.Agent.Address = "127.0.0.1:50051"
	}
	// 超时时间必须为正数。
	if c.Agent.TimeoutSeconds <= 0 {
		c.Agent.TimeoutSeconds = 8
	}
	// 重试次数必须为正数。
	if c.Agent.RetryTimes <= 0 {
		c.Agent.RetryTimes = 3
	}
	// 单源抓取数量必须为正数。
	if c.Crawler.SourceMaxItems <= 0 {
		c.Crawler.SourceMaxItems = 10
	}
	// 单次任务文章数量必须为正数。
	if c.Crawler.RunMaxArticles <= 0 {
		c.Crawler.RunMaxArticles = 20
	}
	// 输出目录为空时使用 shared/outputs。
	if c.Output.Dir == "" {
		c.Output.Dir = "../shared/outputs"
	}
	// 默认用户 id 为空时使用 default-user。
	if c.Profile.UserID == "" {
		c.Profile.UserID = "default-user"
	}
	return c
}

// 函数作用：
// 提供本地开发默认配置。
//
// 参数说明：
// - 无。
//
// 返回值：
// - 返回 Config 默认值。
func defaults() Config {
	// 这些默认值让项目在不提供 config.yaml 的情况下也能使用 mock RSS 和本地服务地址启动。
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

// 函数作用：
// 读取环境变量，如果为空则返回 fallback。
//
// 参数说明：
// - key：环境变量名。
// - fallback：默认值。
//
// 返回值：
// - 返回环境变量值或 fallback。
func envOrDefault(key string, fallback string) string {
	// os.Getenv 不区分变量不存在和变量为空字符串；本项目把空字符串视为未设置。
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
