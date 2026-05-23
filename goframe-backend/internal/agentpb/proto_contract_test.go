package agentpb

import (
	"testing"

	"google.golang.org/protobuf/reflect/protoreflect"
)

func TestAgentProtoContract(t *testing.T) {
	file := File_agent_proto
	if got := string(file.Package()); got != "agent" {
		t.Fatalf("package = %q, want agent", got)
	}

	service := file.Services().ByName("AgentService")
	if service == nil {
		t.Fatal("AgentService is missing")
	}
	for _, name := range []string{"HealthCheck", "ProcessArticles", "ProcessFeedback"} {
		if service.Methods().ByName(protoreflect.Name(name)) == nil {
			t.Fatalf("method %s is missing", name)
		}
	}

	article := file.Messages().ByName("Article")
	for _, name := range []string{"article_id", "url", "title", "raw_text", "source", "published_at", "tags"} {
		if article.Fields().ByName(protoreflect.Name(name)) == nil {
			t.Fatalf("Article.%s is missing", name)
		}
	}

	result := file.Messages().ByName("ArticleProcessResult")
	for _, name := range []string{"article_id", "keep", "score", "summary", "post_text", "check_pass", "issues", "mcp_call_logs"} {
		if result.Fields().ByName(protoreflect.Name(name)) == nil {
			t.Fatalf("ArticleProcessResult.%s is missing", name)
		}
	}

	mcpLog := file.Messages().ByName("McpCallLog")
	for _, name := range []string{"run_id", "agent_name", "server_name", "tool_name", "request_json", "response_json", "status", "error_message", "success", "latency_ms"} {
		if mcpLog.Fields().ByName(protoreflect.Name(name)) == nil {
			t.Fatalf("McpCallLog.%s is missing", name)
		}
	}
}
