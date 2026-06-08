// 文件作用：
// 本文件封装 GoFrame 后端调用 Python Agent Service 的 gRPC Client。
// 它隐藏连接创建、超时控制、trace 传播和 protobuf service client 细节，让 harness 只关心业务请求。
package grpcclient

import (
	"context"
	"time"

	"knowledge-post-agent/goframe-backend/internal/agentpb"
	"knowledge-post-agent/goframe-backend/internal/observability"

	"go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
)

// Client 是 Python Agent gRPC Client 的封装。
type Client struct {
	conn    *grpc.ClientConn
	service agentpb.AgentServiceClient
}

// New 创建一个使用本地明文凭据的 Python Agent gRPC Client。
func New(ctx context.Context, address string, dialTimeout time.Duration) (*Client, error) {
	return NewWithDialOptions(ctx, address, dialTimeout, grpc.WithTransportCredentials(insecure.NewCredentials()))
}

// NewWithDialOptions 创建 gRPC Client，并允许测试或调用方补充 DialOption。
func NewWithDialOptions(ctx context.Context, address string, dialTimeout time.Duration, opts ...grpc.DialOption) (*Client, error) {
	if dialTimeout <= 0 {
		dialTimeout = 5 * time.Second
	}
	dialCtx, cancel := context.WithTimeout(ctx, dialTimeout)
	defer cancel()

	started := time.Now()
	dialOptions := []grpc.DialOption{
		grpc.WithStatsHandler(otelgrpc.NewClientHandler()),
		grpc.WithBlock(),
	}
	dialOptions = append(dialOptions, opts...)

	conn, err := grpc.DialContext(dialCtx, address, dialOptions...)
	if err != nil {
		observability.RecordGRPCClient(ctx, "Dial", status.Code(err).String(), time.Since(started).Seconds())
		return nil, err
	}
	observability.RecordGRPCClient(ctx, "Dial", "OK", time.Since(started).Seconds())
	return &Client{conn: conn, service: agentpb.NewAgentServiceClient(conn)}, nil
}

// Close 关闭 gRPC 连接。
func (c *Client) Close() error {
	return c.conn.Close()
}

// HealthCheck 调用 Python Agent HealthCheck RPC。
func (c *Client) HealthCheck(ctx context.Context) (*agentpb.HealthCheckResponse, error) {
	started := time.Now()
	response, err := c.service.HealthCheck(ctx, &agentpb.HealthCheckRequest{Client: "goframe-backend"})
	recordGRPCClient(ctx, "HealthCheck", err, started)
	return response, err
}

// ProcessArticles 调用 Python Agent ProcessArticles RPC。
func (c *Client) ProcessArticles(ctx context.Context, request *agentpb.ProcessArticlesRequest) (*agentpb.ProcessArticlesResponse, error) {
	started := time.Now()
	response, err := c.service.ProcessArticles(ctx, request)
	recordGRPCClient(ctx, "ProcessArticles", err, started)
	return response, err
}

// ProcessFeedback 调用 Python Agent ProcessFeedback RPC。
func (c *Client) ProcessFeedback(ctx context.Context, request *agentpb.ProcessFeedbackRequest) (*agentpb.ProcessFeedbackResponse, error) {
	started := time.Now()
	response, err := c.service.ProcessFeedback(ctx, request)
	recordGRPCClient(ctx, "ProcessFeedback", err, started)
	return response, err
}

func recordGRPCClient(ctx context.Context, method string, err error, started time.Time) {
	code := "OK"
	if err != nil {
		code = status.Code(err).String()
	}
	observability.RecordGRPCClient(ctx, method, code, time.Since(started).Seconds())
}
