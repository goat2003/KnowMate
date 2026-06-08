// 文件作用：
// 本文件测试 Go 端生成的 protobuf 描述是否仍然符合 KnowMate 的 gRPC 协议约定。
// 它不测试业务逻辑，而是防止 agent.proto 关键服务、方法或字段被误删。
//
// 在项目中的位置：
// 本文件属于 GoFrame 后端的 protobuf 契约测试层。
//
// 主要内容：
// 1. TestAgentProtoContract：检查 package、service、rpc method 和关键 message 字段是否存在。
//
// 关键调用关系：
// - go test ./... 会执行本测试。
// - 依赖 agent.pb.go 中生成的 File_agent_proto 描述对象。
//
// 初学者阅读建议：
// 先理解这是“协议契约测试”，不是业务流程测试；它保证 GoFrame 和 Python Agent 对同一 proto 有共同理解。
package agentpb

import (
	// testing 是 Go 标准测试包。
	"testing"

	// protoreflect 用于按名称读取 protobuf 描述中的服务、方法和字段。
	"google.golang.org/protobuf/reflect/protoreflect"
)

// 函数作用：
// 检查 agent.proto 生成后的 Go 描述对象仍包含关键协议元素。
//
// 参数说明：
// - t：Go 测试对象，用于报告失败。
//
// 返回值：
// - 测试函数不返回值，失败时调用 t.Fatal/t.Fatalf。
func TestAgentProtoContract(t *testing.T) {
	// File_agent_proto 是 protoc 生成代码中的文件描述对象。
	file := File_agent_proto
	// 确认 proto package 仍为 agent。
	if got := string(file.Package()); got != "agent" {
		t.Fatalf("package = %q, want agent", got)
	}

	// 查找 AgentService 服务定义。
	service := file.Services().ByName("AgentService")
	if service == nil {
		t.Fatal("AgentService is missing")
	}
	// 检查三个 RPC 方法都存在，防止协议被破坏。
	for _, name := range []string{"HealthCheck", "ProcessArticles", "ProcessFeedback"} {
		if service.Methods().ByName(protoreflect.Name(name)) == nil {
			t.Fatalf("method %s is missing", name)
		}
	}

	// 检查 Article 输入消息的关键字段。
	article := file.Messages().ByName("Article")
	for _, name := range []string{"article_id", "url", "title", "raw_text", "source", "published_at", "tags"} {
		if article.Fields().ByName(protoreflect.Name(name)) == nil {
			t.Fatalf("Article.%s is missing", name)
		}
	}

	breakdown := file.Messages().ByName("ScoreBreakdownItem")
	if breakdown == nil {
		t.Fatal("ScoreBreakdownItem is missing")
	}
	for _, name := range []string{"dimension", "available", "raw_score", "normalized_score", "weight", "contribution", "evidence"} {
		if breakdown.Fields().ByName(protoreflect.Name(name)) == nil {
			t.Fatalf("ScoreBreakdownItem.%s is missing", name)
		}
	}

	// 检查文章处理结果消息的关键字段。
	result := file.Messages().ByName("ArticleProcessResult")
	for _, name := range []string{
		"article_id", "keep", "score", "summary", "post_text", "check_pass",
		"issues", "mcp_call_logs", "score_breakdown", "recommendation_reasons",
		"rejection_reasons", "rank_position",
	} {
		if result.Fields().ByName(protoreflect.Name(name)) == nil {
			t.Fatalf("ArticleProcessResult.%s is missing", name)
		}
	}

	// 检查 MCP 调用日志消息字段，确保 GoFrame 能持久化 Python Agent 返回的日志。
	mcpLog := file.Messages().ByName("McpCallLog")
	for _, name := range []string{"run_id", "agent_name", "server_name", "tool_name", "request_json", "response_json", "status", "error_message", "success", "latency_ms", "call_id"} {
		if mcpLog.Fields().ByName(protoreflect.Name(name)) == nil {
			t.Fatalf("McpCallLog.%s is missing", name)
		}
	}

	feedback := file.Messages().ByName("ProcessFeedbackResponse")
	for _, name := range []string{
		"run_id", "sentiment", "extracted_feedback", "updated_profile_snapshot",
		"mcp_call_logs", "structured_feedback_json", "profile_diff_json",
	} {
		if feedback.Fields().ByName(protoreflect.Name(name)) == nil {
			t.Fatalf("ProcessFeedbackResponse.%s is missing", name)
		}
	}
}
