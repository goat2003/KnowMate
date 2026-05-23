package main

import (
	"encoding/json"
	"fmt"
	"os"

	"knowledge-post-agent/goframe-backend/internal/config"
	"knowledge-post-agent/goframe-backend/internal/handler"
	"knowledge-post-agent/goframe-backend/internal/logic/harness"
	"knowledge-post-agent/goframe-backend/internal/store"

	"github.com/gogf/gf/v2/frame/g"
	"github.com/gogf/gf/v2/os/gctx"
)

func main() {
	ctx := gctx.GetInitCtx()
	cfg := config.Load(ctx)

	if len(os.Args) > 1 && os.Args[1] == "healthcheck" {
		response, err := harness.AgentHealth(ctx, cfg)
		if err != nil {
			fmt.Fprintf(os.Stderr, "agent healthcheck failed: %v\n", err)
			os.Exit(1)
		}
		encoder := json.NewEncoder(os.Stdout)
		encoder.SetIndent("", "  ")
		_ = encoder.Encode(response)
		return
	}

	mysqlStore := store.New(cfg.MySQL.DSN)
	if err := mysqlStore.InitSchema(ctx, cfg.Schema.Path); err != nil {
		g.Log().Warningf(ctx, "schema init skipped or failed: %v", err)
	}
	runner := harness.New(cfg, mysqlStore)
	httpHandler := handler.New(mysqlStore, runner)

	server := g.Server()
	server.SetAddr(cfg.Server.Address)
	httpHandler.Register(server)
	server.Run()
}
