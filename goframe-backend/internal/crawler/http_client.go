package crawler

import (
	"context"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	defaultHTTPTimeout      = 30 * time.Second
	defaultBackoffBase      = 500 * time.Millisecond
	defaultMaxRetryDelay    = 30 * time.Second
	defaultMaxResponseBytes = 10 << 20
	maxRedirects            = 10
	maxHostLimiters         = 256
)

type WaitFunc func(context.Context, time.Duration) error

type HTTPOptions struct {
	UserAgent        string
	Timeout          time.Duration
	RetryTimes       int
	BackoffBase      time.Duration
	MaxRetryDelay    time.Duration
	PerHostInterval  time.Duration
	MaxResponseBytes int64
	Wait             WaitFunc
	Transport        http.RoundTripper
}

type Response struct {
	URL         string
	StatusCode  int
	ContentType string
	Body        []byte
}

type HTTPClient struct {
	client           *http.Client
	userAgent        string
	retryTimes       int
	backoffBase      time.Duration
	maxRetryDelay    time.Duration
	perHostInterval  time.Duration
	maxResponseBytes int64
	wait             WaitFunc
	hostLimitersMu   sync.Mutex
	hostLimiters     map[string]*hostLimiter
	overflowLimiter  *hostLimiter
}

type hostLimiter struct {
	gate        chan struct{}
	lastRequest time.Time
	lastUsed    time.Time
}

func NewHTTPClient(options HTTPOptions) *HTTPClient {
	if options.Timeout <= 0 {
		options.Timeout = defaultHTTPTimeout
	}
	if options.RetryTimes < 0 {
		options.RetryTimes = 0
	}
	if options.BackoffBase <= 0 {
		options.BackoffBase = defaultBackoffBase
	}
	if options.MaxRetryDelay <= 0 {
		options.MaxRetryDelay = defaultMaxRetryDelay
	}
	if options.PerHostInterval < 0 {
		options.PerHostInterval = 0
	}
	if options.MaxResponseBytes <= 0 {
		options.MaxResponseBytes = defaultMaxResponseBytes
	}
	if options.Wait == nil {
		options.Wait = waitWithTimer
	}

	return &HTTPClient{
		client: &http.Client{
			Timeout:   options.Timeout,
			Transport: options.Transport,
			CheckRedirect: func(*http.Request, []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
		userAgent:        options.UserAgent,
		retryTimes:       options.RetryTimes,
		backoffBase:      options.BackoffBase,
		maxRetryDelay:    options.MaxRetryDelay,
		perHostInterval:  options.PerHostInterval,
		maxResponseBytes: options.MaxResponseBytes,
		wait:             options.Wait,
		hostLimiters:     make(map[string]*hostLimiter),
		overflowLimiter:  newHostLimiter(),
	}
}

func (c *HTTPClient) Get(ctx context.Context, rawURL string) (*Response, error) {
	_, err := validateRequestURL(rawURL)
	if err != nil {
		return nil, ClassifyError(err, 0)
	}

	for attempt := 0; ; attempt++ {
		response, retryAfter, retryAfterSet, err := c.getOnce(ctx, rawURL)
		if err == nil {
			return response, nil
		}

		crawlErr := ClassifyError(err, 0)
		if !crawlErr.Retryable || attempt >= c.retryTimes {
			return nil, crawlErr
		}

		delay := exponentialBackoff(c.backoffBase, attempt)
		if retryAfterSet {
			delay = retryAfter
		}
		delay = clampDelay(delay, c.maxRetryDelay)
		if err := c.wait(ctx, delay); err != nil {
			return nil, ClassifyError(err, 0)
		}
	}
}

func (c *HTTPClient) getOnce(ctx context.Context, rawURL string) (*Response, time.Duration, bool, error) {
	currentURL := rawURL
	visited := map[string]struct{}{rawURL: {}}

	for redirects := 0; ; {
		parsedURL, err := validateRequestURL(currentURL)
		if err != nil {
			return nil, 0, false, ClassifyError(err, 0)
		}
		if err := c.waitForHost(ctx, strings.ToLower(parsedURL.Host)); err != nil {
			return nil, 0, false, ClassifyError(err, 0)
		}

		request, err := http.NewRequestWithContext(ctx, http.MethodGet, currentURL, nil)
		if err != nil {
			return nil, 0, false, ClassifyError(err, 0)
		}
		if c.userAgent != "" {
			request.Header.Set("User-Agent", c.userAgent)
		}

		httpResponse, err := c.client.Do(request)
		if err != nil {
			return nil, 0, false, ClassifyError(err, 0)
		}

		if isRedirectStatus(httpResponse.StatusCode) {
			if redirects >= maxRedirects {
				httpResponse.Body.Close()
				return nil, 0, false, redirectError(httpResponse.StatusCode, "too many redirects", nil)
			}

			location, err := httpResponse.Location()
			httpResponse.Body.Close()
			if err != nil {
				return nil, 0, false, redirectError(httpResponse.StatusCode, "invalid redirect location", err)
			}
			nextURL := location.String()
			if _, err := validateRequestURL(nextURL); err != nil {
				return nil, 0, false, redirectError(httpResponse.StatusCode, "invalid redirect target", err)
			}
			if _, exists := visited[nextURL]; exists {
				return nil, 0, false, redirectError(httpResponse.StatusCode, "redirect loop detected", nil)
			}
			visited[nextURL] = struct{}{}
			currentURL = nextURL
			redirects++
			continue
		}

		if httpResponse.StatusCode < http.StatusOK || httpResponse.StatusCode >= http.StatusMultipleChoices {
			httpResponse.Body.Close()
			retryAfter, retryAfterSet := parseRetryAfter(httpResponse.Header.Get("Retry-After"))
			return nil, retryAfter, retryAfterSet, classifyHTTPStatus(httpResponse.StatusCode)
		}

		body, err := readLimited(httpResponse.Body, c.maxResponseBytes)
		httpResponse.Body.Close()
		if err != nil {
			return nil, 0, false, ClassifyError(err, httpResponse.StatusCode)
		}
		if int64(len(body)) > c.maxResponseBytes {
			return nil, 0, false, NewCrawlError(
				ErrorResponseTooLarge,
				fmt.Sprintf("response exceeds %d bytes", c.maxResponseBytes),
				httpResponse.StatusCode,
				false,
				nil,
			)
		}

		return &Response{
			URL:         httpResponse.Request.URL.String(),
			StatusCode:  httpResponse.StatusCode,
			ContentType: httpResponse.Header.Get("Content-Type"),
			Body:        body,
		}, 0, false, nil
	}
}

func (c *HTTPClient) waitForHost(ctx context.Context, host string) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if c.perHostInterval <= 0 {
		return nil
	}

	limiter := c.hostLimiter(host)
	select {
	case limiter.gate <- struct{}{}:
	case <-ctx.Done():
		return ctx.Err()
	}
	defer func() { <-limiter.gate }()

	if delay := c.perHostInterval - time.Since(limiter.lastRequest); delay > 0 {
		if err := c.wait(ctx, delay); err != nil {
			return err
		}
	}
	limiter.lastRequest = time.Now()
	return nil
}

func (c *HTTPClient) hostLimiter(host string) *hostLimiter {
	now := time.Now()
	c.hostLimitersMu.Lock()
	defer c.hostLimitersMu.Unlock()

	if limiter := c.hostLimiters[host]; limiter != nil {
		limiter.lastUsed = now
		return limiter
	}

	if len(c.hostLimiters) >= maxHostLimiters {
		c.cleanupHostLimitersLocked(now)
	}
	if len(c.hostLimiters) >= maxHostLimiters {
		c.overflowLimiter.lastUsed = now
		return c.overflowLimiter
	}

	limiter := newHostLimiter()
	limiter.lastUsed = now
	c.hostLimiters[host] = limiter
	return limiter
}

func (c *HTTPClient) cleanupHostLimitersLocked(now time.Time) {
	staleAfter := c.perHostInterval
	if staleAfter < time.Minute {
		staleAfter = time.Minute
	}
	for host, limiter := range c.hostLimiters {
		if now.Sub(limiter.lastUsed) < staleAfter {
			continue
		}
		select {
		case limiter.gate <- struct{}{}:
			<-limiter.gate
			delete(c.hostLimiters, host)
		default:
		}
	}
}

func newHostLimiter() *hostLimiter {
	return &hostLimiter{gate: make(chan struct{}, 1)}
}

func isRedirectStatus(statusCode int) bool {
	switch statusCode {
	case http.StatusMovedPermanently,
		http.StatusFound,
		http.StatusSeeOther,
		http.StatusTemporaryRedirect,
		http.StatusPermanentRedirect:
		return true
	default:
		return false
	}
}

func redirectError(statusCode int, message string, err error) *CrawlError {
	return NewCrawlError(ErrorParse, message, statusCode, false, err)
}

func classifyHTTPStatus(statusCode int) *CrawlError {
	if statusCode >= http.StatusBadRequest {
		return ClassifyError(nil, statusCode)
	}
	return NewCrawlError(
		ErrorParse,
		fmt.Sprintf("unexpected HTTP status %d", statusCode),
		statusCode,
		false,
		nil,
	)
}

func validateRequestURL(rawURL string) (*url.URL, error) {
	parsedURL, err := url.Parse(rawURL)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrInvalidURL, err)
	}
	if !parsedURL.IsAbs() ||
		(parsedURL.Scheme != "http" && parsedURL.Scheme != "https") ||
		parsedURL.Host == "" {
		return nil, fmt.Errorf("%w: only absolute http and https URLs are supported", ErrInvalidURL)
	}
	return parsedURL, nil
}

func clampDelay(delay, maxDelay time.Duration) time.Duration {
	if delay < 0 {
		return 0
	}
	if delay > maxDelay {
		return maxDelay
	}
	return delay
}

func waitWithTimer(ctx context.Context, delay time.Duration) error {
	if delay <= 0 {
		return ctx.Err()
	}

	timer := time.NewTimer(delay)
	defer timer.Stop()

	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

func exponentialBackoff(base time.Duration, retry int) time.Duration {
	delay := base
	for range retry {
		if delay > time.Duration(math.MaxInt64)/2 {
			return time.Duration(math.MaxInt64)
		}
		delay *= 2
	}
	return delay
}

func parseRetryAfter(value string) (time.Duration, bool) {
	value = strings.TrimSpace(value)
	if value == "" {
		return 0, false
	}

	if seconds, err := strconv.ParseInt(value, 10, 64); err == nil && seconds >= 0 {
		if seconds > int64(math.MaxInt64/time.Second) {
			return time.Duration(math.MaxInt64), true
		}
		return time.Duration(seconds) * time.Second, true
	}

	retryAt, err := http.ParseTime(value)
	if err != nil {
		return 0, false
	}
	delay := time.Until(retryAt)
	if delay < 0 {
		delay = 0
	}
	return delay, true
}

func readLimited(reader io.Reader, maxBytes int64) ([]byte, error) {
	if maxBytes == math.MaxInt64 {
		return io.ReadAll(reader)
	}
	return io.ReadAll(io.LimitReader(reader, maxBytes+1))
}
