package crawler

import (
	"context"
	"errors"
	"fmt"
	"net"
)

const (
	ErrorInvalidURL             ErrorType = "invalid_url"
	ErrorRobotsDenied           ErrorType = "robots_denied"
	ErrorRateLimited            ErrorType = "rate_limited"
	ErrorTimeout                ErrorType = "timeout"
	ErrorDNS                    ErrorType = "dns_error"
	ErrorConnection             ErrorType = "connection_error"
	ErrorHTTP4xx                ErrorType = "http_4xx"
	ErrorHTTP5xx                ErrorType = "http_5xx"
	ErrorResponseTooLarge       ErrorType = "response_too_large"
	ErrorUnsupportedContentType ErrorType = "unsupported_content_type"
	ErrorParse                  ErrorType = "parse_error"
	ErrorContentExtraction      ErrorType = "content_extraction_error"
	ErrorDatabase               ErrorType = "database_error"
	ErrorUnknown                ErrorType = "unknown"
)

func NewCrawlError(errorType ErrorType, message string, status int, retryable bool, err error) *CrawlError {
	return &CrawlError{
		Type:       errorType,
		Message:    message,
		HTTPStatus: status,
		Retryable:  retryable,
		Err:        err,
	}
}

func ClassifyError(err error, statusCode int) *CrawlError {
	var classified *CrawlError
	if errors.Is(err, context.Canceled) {
		if errors.As(err, &classified) {
			copy := *classified
			copy.Retryable = false
			return &copy
		}
		return NewCrawlError(ErrorUnknown, errorMessage(err, statusCode), statusCode, false, err)
	}

	if errors.As(err, &classified) {
		return classified
	}

	message := errorMessage(err, statusCode)
	switch {
	case errors.Is(err, context.DeadlineExceeded):
		return NewCrawlError(ErrorTimeout, message, statusCode, true, err)
	case errors.Is(err, ErrInvalidURL):
		return NewCrawlError(ErrorInvalidURL, message, statusCode, false, err)
	}

	var dnsErr *net.DNSError
	if errors.As(err, &dnsErr) {
		return NewCrawlError(ErrorDNS, message, statusCode, true, err)
	}

	var netErr net.Error
	if errors.As(err, &netErr) {
		if netErr.Timeout() {
			return NewCrawlError(ErrorTimeout, message, statusCode, true, err)
		}
		return NewCrawlError(ErrorConnection, message, statusCode, true, err)
	}

	switch {
	case statusCode == 429:
		return NewCrawlError(ErrorRateLimited, message, statusCode, true, err)
	case statusCode >= 400 && statusCode <= 499:
		return NewCrawlError(ErrorHTTP4xx, message, statusCode, false, err)
	case statusCode >= 500 && statusCode <= 599:
		return NewCrawlError(ErrorHTTP5xx, message, statusCode, true, err)
	default:
		return NewCrawlError(ErrorUnknown, message, statusCode, false, err)
	}
}

func errorMessage(err error, statusCode int) string {
	if err != nil {
		return err.Error()
	}
	if statusCode != 0 {
		return fmt.Sprintf("HTTP status %d", statusCode)
	}
	return "unknown crawl error"
}
