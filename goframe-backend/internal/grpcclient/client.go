package grpcclient

import (
	"context"
	"time"

	"knowledge-post-agent/goframe-backend/internal/agentpb"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

type Client struct {
	conn    *grpc.ClientConn
	service agentpb.AgentServiceClient
}

func New(ctx context.Context, address string, dialTimeout time.Duration) (*Client, error) {
	if dialTimeout <= 0 {
		dialTimeout = 5 * time.Second
	}
	dialCtx, cancel := context.WithTimeout(ctx, dialTimeout)
	defer cancel()

	conn, err := grpc.DialContext(
		dialCtx,
		address,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithBlock(),
	)
	if err != nil {
		return nil, err
	}
	return &Client{conn: conn, service: agentpb.NewAgentServiceClient(conn)}, nil
}

func (c *Client) Close() error {
	return c.conn.Close()
}

func (c *Client) HealthCheck(ctx context.Context) (*agentpb.HealthCheckResponse, error) {
	return c.service.HealthCheck(ctx, &agentpb.HealthCheckRequest{Client: "goframe-backend"})
}

func (c *Client) ProcessArticles(ctx context.Context, request *agentpb.ProcessArticlesRequest) (*agentpb.ProcessArticlesResponse, error) {
	return c.service.ProcessArticles(ctx, request)
}

func (c *Client) ProcessFeedback(ctx context.Context, request *agentpb.ProcessFeedbackRequest) (*agentpb.ProcessFeedbackResponse, error) {
	return c.service.ProcessFeedback(ctx, request)
}
