# 文件作用：
# 本文件是 Python Agent Service 的 gRPC 客户端示例。
# 它演示如何从 Python 侧直接调用 HealthCheck、ProcessArticles 和 ProcessFeedback。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 examples 示例层，不参与 GoFrame 正式运行链路。
#
# 主要内容：
# 1. main 函数：创建 gRPC channel 和 stub，依次调用三个 RPC。
#
# 关键调用关系：
# - 调用 agent_pb2_grpc.AgentServiceStub。
# - 请求字段与 shared/proto/agent.proto 保持一致。
#
# 初学者阅读建议：
# 先启动 python-agent/server.py，再运行本示例；它可以帮助理解 GoFrame 后端实际会发送什么样的 gRPC 请求。
from __future__ import annotations

# grpc 是 Python gRPC 客户端库。
import grpc

# agent_pb2 / agent_pb2_grpc 是 protoc 生成的 Python protobuf/gRPC 代码。
import agent_pb2
import agent_pb2_grpc


# 函数作用：
# 演示如何调用 Python Agent gRPC 服务。
#
# 参数说明：
# - 无。
#
# 返回值：
# - 无；结果直接打印到控制台。
def main() -> None:
    # insecure_channel 创建不带 TLS 的 gRPC 连接，地址与 Python Agent 默认监听端口一致。
    with grpc.insecure_channel("127.0.0.1:50051") as channel:
        # Stub 是 gRPC 客户端代理对象，方法名与 proto 中的 rpc 名称一致。
        stub = agent_pb2_grpc.AgentServiceStub(channel)

        # 调用 HealthCheck，确认服务是否在线。
        health = stub.HealthCheck(agent_pb2.HealthCheckRequest(client="python-example"))
        print("HealthCheck:", health)

        # 调用 ProcessArticles，模拟 GoFrame 发送一篇文章给 Python Agent。
        articles = stub.ProcessArticles(
            agent_pb2.ProcessArticlesRequest(
                # run_id 用于串联本次任务日志。
                run_id="example-run",
                # user_profile_snapshot 会被 FilterAgent 用来判断文章是否匹配用户兴趣。
                user_profile_snapshot={"interests": "AI,知识管理,工程实践"},
                # mcp_policy 控制本次请求允许的 MCP 能力。
                mcp_policy=agent_pb2.McpPolicy(
                    mock_transport=True,
                    enable_embedding=True,
                    enable_milvus=True,
                    enable_neo4j=True,
                ),
                # articles 是 repeated Article，因此即使只有一篇也要放在列表中。
                articles=[
                    agent_pb2.Article(
                        article_id="article-001",
                        url="https://example.com/article-001",
                        title="Agent Workflow for Knowledge Posts",
                        raw_text="This article explains how to compose filter, summary, rewrite, and check nodes.",
                        tags=["agent", "workflow"],
                    )
                ],
            )
        )
        print("ProcessArticles:", articles)

        # 调用 ProcessFeedback，模拟用户对生成内容的反馈。
        feedback = stub.ProcessFeedback(
            agent_pb2.ProcessFeedbackRequest(
                run_id="feedback-run",
                # 反馈流程会在这个快照基础上生成 updated_profile_snapshot。
                user_profile_snapshot={"feedback_count": "0"},
                # MemoryAgent 需要 embedding 和 neo4j 开关来写入 mock/真实记忆。
                mcp_policy=agent_pb2.McpPolicy(mock_transport=True, enable_embedding=True, enable_neo4j=True),
                feedback=[
                    agent_pb2.FeedbackItem(
                        feedback_id="feedback-001",
                        user_id="user-001",
                        article_id="article-001",
                        feedback_text="摘要有用，但希望保留更多工程实践细节",
                        rating=5,
                    )
                ],
            )
        )
        print("ProcessFeedback:", feedback)


# 入口保护：直接运行本示例时调用 main，被 import 时不会自动执行。
if __name__ == "__main__":
    main()
