package crawler

import (
	"context"
	"errors"
	"fmt"
	"net"
	"syscall"
	"testing"
)

func TestCrawlErrorImplementsErrorAndUnwrap(t *testing.T) {
	cause := errors.New("cause")
	err := NewCrawlError(ErrorParse, "could not parse", 0, false, cause)

	if got := err.Error(); got != "could not parse: cause" {
		t.Fatalf("Error() = %q, want %q", got, "could not parse: cause")
	}
	if !errors.Is(err, cause) {
		t.Fatalf("errors.Is() = false, want true")
	}
}

func TestClassifyError(t *testing.T) {
	tests := []struct {
		name          string
		err           error
		statusCode    int
		wantType      ErrorType
		wantRetryable bool
	}{
		{
			name:          "deadline exceeded",
			err:           context.DeadlineExceeded,
			wantType:      ErrorTimeout,
			wantRetryable: true,
		},
		{
			name:          "wrapped deadline exceeded",
			err:           fmt.Errorf("request failed: %w", context.DeadlineExceeded),
			wantType:      ErrorTimeout,
			wantRetryable: true,
		},
		{
			name:          "context canceled",
			err:           context.Canceled,
			wantType:      ErrorUnknown,
			wantRetryable: false,
		},
		{
			name:          "DNS error",
			err:           &net.DNSError{Err: "no such host", Name: "missing.example"},
			wantType:      ErrorDNS,
			wantRetryable: true,
		},
		{
			name:          "connection error",
			err:           &net.OpError{Op: "dial", Net: "tcp", Err: syscall.ECONNREFUSED},
			wantType:      ErrorConnection,
			wantRetryable: true,
		},
		{
			name:          "rate limited",
			statusCode:    429,
			wantType:      ErrorRateLimited,
			wantRetryable: true,
		},
		{
			name:          "ordinary 4xx",
			statusCode:    404,
			wantType:      ErrorHTTP4xx,
			wantRetryable: false,
		},
		{
			name:          "5xx",
			statusCode:    503,
			wantType:      ErrorHTTP5xx,
			wantRetryable: true,
		},
		{
			name:          "unknown",
			err:           errors.New("unexpected"),
			wantType:      ErrorUnknown,
			wantRetryable: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := ClassifyError(tt.err, tt.statusCode)
			if got.Type != tt.wantType {
				t.Fatalf("Type = %q, want %q", got.Type, tt.wantType)
			}
			if got.Retryable != tt.wantRetryable {
				t.Fatalf("Retryable = %t, want %t", got.Retryable, tt.wantRetryable)
			}
			if got.HTTPStatus != tt.statusCode {
				t.Fatalf("HTTPStatus = %d, want %d", got.HTTPStatus, tt.statusCode)
			}
			if got.Err != tt.err {
				t.Fatalf("Err = %v, want original error %v", got.Err, tt.err)
			}
		})
	}
}

func TestClassifyErrorForcesWrappedCrawlErrorCancellationNonRetryable(t *testing.T) {
	canceled := NewCrawlError(ErrorConnection, "request canceled", 0, true, context.Canceled)
	wrapped := fmt.Errorf("fetch failed: %w", canceled)

	got := ClassifyError(wrapped, 0)
	if got.Type != ErrorConnection {
		t.Fatalf("Type = %q, want %q", got.Type, ErrorConnection)
	}
	if got.Retryable {
		t.Fatal("Retryable = true, want false for wrapped context.Canceled")
	}
	if !errors.Is(got, context.Canceled) {
		t.Fatalf("errors.Is(got, context.Canceled) = false, want true")
	}
}

func TestErrorTypeConstantsAreStable(t *testing.T) {
	tests := map[ErrorType]string{
		ErrorInvalidURL:             "invalid_url",
		ErrorRobotsDenied:           "robots_denied",
		ErrorRateLimited:            "rate_limited",
		ErrorTimeout:                "timeout",
		ErrorDNS:                    "dns_error",
		ErrorConnection:             "connection_error",
		ErrorHTTP4xx:                "http_4xx",
		ErrorHTTP5xx:                "http_5xx",
		ErrorResponseTooLarge:       "response_too_large",
		ErrorUnsupportedContentType: "unsupported_content_type",
		ErrorParse:                  "parse_error",
		ErrorContentExtraction:      "content_extraction_error",
		ErrorDatabase:               "database_error",
		ErrorUnknown:                "unknown",
	}

	for got, want := range tests {
		if string(got) != want {
			t.Fatalf("error type = %q, want %q", got, want)
		}
	}
}
