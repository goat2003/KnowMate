// 文件作用：
// 本文件是 GoFrame 后端服务的进程入口。
// 它负责加载配置、初始化 MySQL schema、创建业务 Harness、注册 HTTP 路由并启动 GoFrame HTTP Server。
//
// 在项目中的位置：
// 本文件属于 GoFrame 后端的入口层，位于 controller/handler、logic、store 等模块之前。
//
// 主要内容：
// 1. main 函数：启动 HTTP 服务，或在 healthcheck 模式下只检查 Python Agent。
//
// 关键调用关系：
// - 调用 internal/config.Load 读取配置。
// - 调用 internal/store.New 和 InitSchema 初始化数据库。
// - 调用 internal/logic/harness.New 创建业务编排对象。
// - 调用 internal/handler.New 注册 HTTP 接口。
//
// 初学者阅读建议：
// 先看 main 中对象创建顺序，再看 handler 如何把 HTTP 请求交给 harness。
package main

import (
	"context"
	// encoding/json 用于 healthcheck 命令把 Python Agent 健康检查结果格式化输出到 stdout。
	"encoding/json"
	// fmt 用于向 stderr 输出 healthcheck 错误。
	"fmt"
	// os 用于读取命令行参数、stdout/stderr 和进程退出码。
	"os"
	"time"

	// config 负责加载 manifest/config/config.yaml 和环境变量。
	"knowledge-post-agent/goframe-backend/internal/config"
	// handler 负责注册 GoFrame HTTP 路由。
	"knowledge-post-agent/goframe-backend/internal/handler"
	// harness 是后端业务编排层，串联 RSS、MySQL、Python gRPC 和 Markdown 输出。
	"knowledge-post-agent/goframe-backend/internal/logic/harness"
	"knowledge-post-agent/goframe-backend/internal/observability"
	// store 是 MySQL 访问层。
	"knowledge-post-agent/goframe-backend/internal/store"

	// g 是 GoFrame 常用入口，提供 g.Server、g.Log 等便捷对象。
	"github.com/gogf/gf/v2/frame/g"
	// gctx 提供 GoFrame 初始化上下文。
	"github.com/gogf/gf/v2/os/gctx"
)

// 函数作用：
// 启动 GoFrame 后端服务。
//
// 参数说明：
// - 无；命令行参数通过 os.Args 读取。
//
// 返回值：
// - 无；HTTP Server 会阻塞运行，healthcheck 模式会输出结果后退出。
//
// 调用关系：
// - 程序启动时由 Go runtime 自动调用。
func main() {
	// 获取 GoFrame 初始化上下文。
	// context.Context 用于在数据库、gRPC 等调用中传递取消、超时和日志上下文。
	ctx := gctx.GetInitCtx()
	// 加载后端配置，包含 HTTP 地址、Agent gRPC 地址、MySQL DSN、RSS 源等。
	cfg := config.Load(ctx)
	shutdown, err := observability.Init(ctx, observability.OptionsFromEnv("goframe-backend"))
	if err != nil {
		_ = observability.WriteJSONLog(os.Stderr, ctx, "goframe-backend", "warning", "observability init failed", map[string]any{"error": err})
	} else {
		defer func() {
			shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			if err := shutdown(shutdownCtx); err != nil {
				_ = observability.WriteJSONLog(os.Stderr, ctx, "goframe-backend", "warning", "observability shutdown failed", map[string]any{"error": err})
			}
		}()
	}

	// 支持命令行健康检查模式：go run . healthcheck。
	// 该模式只检查 Python Agent，不启动 HTTP 服务，适合 Docker healthcheck 或脚本检查。
	if len(os.Args) > 1 && os.Args[1] == "healthcheck" {
		// 调用 harness.AgentHealth，通过 gRPC 请求 Python Agent HealthCheck。
		response, err := harness.AgentHealth(ctx, cfg)
		if err != nil {
			// 健康检查失败写入 stderr，并用非 0 退出码表示失败。
			fmt.Fprintf(os.Stderr, "agent healthcheck failed: %v\n", err)
			os.Exit(1)
		}
		// 创建 JSON encoder，把响应格式化输出到 stdout。
		encoder := json.NewEncoder(os.Stdout)
		// SetIndent 让输出更适合人类阅读。
		encoder.SetIndent("", "  ")
		// 健康检查输出失败不影响主流程，因此忽略 Encode 错误。
		_ = encoder.Encode(response)
		return
	}

	// 创建 MySQL Store；此处只是保存 DSN，真正连接在第一次 open/Ping/Exec 时发生。
	mysqlStore := store.New(cfg.MySQL.DSN)
	// 初始化数据库 schema。
	// 如果 MySQL 不可用或 schema 文件缺失，当前服务只记录警告，方便开发环境先启动 HTTP。
	if err := mysqlStore.InitSchema(ctx, cfg.Schema.Path); err != nil {
		_ = observability.WriteJSONLog(os.Stderr, ctx, "goframe-backend", "error", "schema init failed", map[string]any{"error": err})
		os.Exit(1)
	}
	// 创建业务编排对象，后续 HTTP handler 会调用它完成文章任务和反馈任务。
	runner := harness.New(cfg, mysqlStore)
	if recovered, err := runner.RecoverInterruptedTasks(ctx); err != nil {
		_ = observability.WriteJSONLog(os.Stderr, ctx, "goframe-backend", "warning", "task recovery scan failed", map[string]any{"error": err})
	} else if len(recovered) > 0 {
		_ = observability.WriteJSONLog(os.Stdout, ctx, "goframe-backend", "info", "recovered interrupted tasks", map[string]any{"count": len(recovered)})
	}
	// 创建 HTTP handler，把 Store 和 Harness 注入进去。
	httpHandler := handler.New(mysqlStore, runner, cfg.Security)

	// 创建 GoFrame HTTP Server。
	server := g.Server()
	// 设置监听地址，例如 :8080。
	server.SetAddr(cfg.Server.Address)
	server.SetGraceful(true)
	server.SetGracefulShutdownTimeout(15)
	// 注册 /health、/runs/articles、/feedback、/posts、/run-logs 等路由。
	httpHandler.Register(server)
	// 启动 HTTP 服务并阻塞当前进程。
	server.Run()
}
