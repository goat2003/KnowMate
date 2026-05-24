// 文件作用：
// 本文件封装 GoFrame 后端调用 Python Agent Service 的 gRPC Client。
// 它隐藏连接创建、超时控制和 protobuf service client 细节，让 harness 只关心业务请求。
//
// 在项目中的位置：
// 本文件属于 GoFrame 后端的 gRPC client 层，位于 logic/harness 和 protobuf 生成代码之间。
//
// 主要内容：
// 1. Client 结构体：保存 grpc.ClientConn 和 AgentServiceClient。
// 2. New：创建到 Python Agent 的 gRPC 连接。
// 3. HealthCheck / ProcessArticles / ProcessFeedback：调用 proto 中定义的 RPC。
//
// 关键调用关系：
// - 被 internal/logic/harness 调用。
// - 依赖 internal/agentpb 中的 protobuf 生成类型。
//
// 初学者阅读建议：
// 先对照 proto/agent.proto 看 AgentService 定义，再看本文件如何调用生成的 client 方法。
package grpcclient

import (
	// context.Context 用于控制连接和 RPC 调用的超时、取消。
	"context"
	// time 用于设置 dialTimeout 和默认超时时间。
	"time"

	// agentpb 是根据 agent.proto 生成的 Go protobuf/gRPC 代码。
	"knowledge-post-agent/goframe-backend/internal/agentpb"

	// grpc 是 Google gRPC Go 客户端库。
	"google.golang.org/grpc"
	// insecure 用于创建不带 TLS 的本地/内网连接凭据。
	"google.golang.org/grpc/credentials/insecure"
)

// Client 是 Python Agent gRPC Client 的封装。
// 它持有底层连接和生成的 AgentServiceClient。
type Client struct {
	// conn 是到 Python Agent Service 的 gRPC 连接，使用完需要 Close。
	conn *grpc.ClientConn
	// service 是 protobuf 生成的强类型服务客户端。
	service agentpb.AgentServiceClient
}

// 函数作用：
// 创建一个新的 Python Agent gRPC Client。
//
// 参数说明：
// - ctx：上游上下文，用于控制连接生命周期。
// - address：Python Agent 地址，例如 127.0.0.1:50051。
// - dialTimeout：连接超时时间；小于等于 0 时使用默认 5 秒。
//
// 返回值：
// - 成功返回 *Client，失败返回 error。
//
// 调用关系：
// - 被 harness.AgentHealth、withArticlesClient、withFeedbackClient 调用。
func New(ctx context.Context, address string, dialTimeout time.Duration) (*Client, error) {
	// 防御性默认值，避免调用方传 0 导致没有连接超时控制。
	if dialTimeout <= 0 {
		dialTimeout = 5 * time.Second
	}
	// 为连接过程创建带超时的上下文。
	dialCtx, cancel := context.WithTimeout(ctx, dialTimeout)
	// defer 确保 New 返回前释放定时器资源。
	defer cancel()

	// DialContext 创建 gRPC 连接。
	conn, err := grpc.DialContext(
		dialCtx,
		address,
		// 当前 MVP 使用明文连接，不配置 TLS。
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		// WithBlock 表示 DialContext 会阻塞到连接成功或超时，而不是异步返回。
		grpc.WithBlock(),
	)
	if err != nil {
		return nil, err
	}
	// 用连接创建 protobuf 生成的 AgentServiceClient。
	return &Client{conn: conn, service: agentpb.NewAgentServiceClient(conn)}, nil
}

// 函数作用：
// 关闭 gRPC 连接。
//
// 参数说明：
// - 无。
//
// 返回值：
// - 返回底层 conn.Close 的 error。
func (c *Client) Close() error {
	return c.conn.Close()
}

// 函数作用：
// 调用 Python Agent HealthCheck RPC。
//
// 参数说明：
// - ctx：RPC 调用上下文，通常包含超时。
//
// 返回值：
// - 返回 HealthCheckResponse 或 error。
func (c *Client) HealthCheck(ctx context.Context) (*agentpb.HealthCheckResponse, error) {
	// Client 字段标记调用方是 goframe-backend，便于 Python 侧未来记录来源。
	return c.service.HealthCheck(ctx, &agentpb.HealthCheckRequest{Client: "goframe-backend"})
}

// 函数作用：
// 调用 Python Agent ProcessArticles RPC。
//
// 参数说明：
// - ctx：RPC 调用上下文。
// - request：文章处理 protobuf 请求。
//
// 返回值：
// - 返回 ProcessArticlesResponse 或 error。
func (c *Client) ProcessArticles(ctx context.Context, request *agentpb.ProcessArticlesRequest) (*agentpb.ProcessArticlesResponse, error) {
	// 直接转发给 protobuf 生成的 service client。
	return c.service.ProcessArticles(ctx, request)
}

// 函数作用：
// 调用 Python Agent ProcessFeedback RPC。
//
// 参数说明：
// - ctx：RPC 调用上下文。
// - request：反馈处理 protobuf 请求。
//
// 返回值：
// - 返回 ProcessFeedbackResponse 或 error。
func (c *Client) ProcessFeedback(ctx context.Context, request *agentpb.ProcessFeedbackRequest) (*agentpb.ProcessFeedbackResponse, error) {
	// 直接转发给 protobuf 生成的 service client。
	return c.service.ProcessFeedback(ctx, request)
}
