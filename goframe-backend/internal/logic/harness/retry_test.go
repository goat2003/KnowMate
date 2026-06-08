package harness

import (
	"context"
	"errors"
	"testing"
	"time"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func TestWaitForRetryStopsOnContextCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	started := time.Now()
	err := waitForRetry(ctx, time.Second)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("expected context.Canceled, got %v", err)
	}
	if time.Since(started) > 100*time.Millisecond {
		t.Fatal("waitForRetry did not stop promptly after cancellation")
	}
}

func TestIsRetryableGRPCError(t *testing.T) {
	if !isRetryableGRPCError(status.Error(codes.Unavailable, "temporary")) {
		t.Fatal("Unavailable must be retryable")
	}
	if isRetryableGRPCError(status.Error(codes.InvalidArgument, "permanent")) {
		t.Fatal("InvalidArgument must not be retryable")
	}
	if isRetryableGRPCError(nil) {
		t.Fatal("nil must not be retryable")
	}
}
