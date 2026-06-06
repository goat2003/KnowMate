package crawler

import (
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestHTTPClientSendsUserAgentAndReturnsResponse(t *testing.T) {
	const userAgent = "KnowMateBot/1.0"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.Header.Get("User-Agent"); got != userAgent {
			t.Errorf("User-Agent = %q, want %q", got, userAgent)
		}
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		_, _ = w.Write([]byte("ok"))
	}))
	t.Cleanup(server.Close)

	client := NewHTTPClient(HTTPOptions{
		UserAgent:        userAgent,
		Timeout:          time.Second,
		MaxResponseBytes: 1024,
	})
	response, err := client.Get(context.Background(), server.URL+"/article")
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if response.URL != server.URL+"/article" {
		t.Fatalf("URL = %q, want %q", response.URL, server.URL+"/article")
	}
	if response.StatusCode != http.StatusOK {
		t.Fatalf("StatusCode = %d, want %d", response.StatusCode, http.StatusOK)
	}
	if response.ContentType != "text/plain; charset=utf-8" {
		t.Fatalf("ContentType = %q, want text/plain with charset", response.ContentType)
	}
	if got := string(response.Body); got != "ok" {
		t.Fatalf("Body = %q, want %q", got, "ok")
	}
}

func TestHTTPClientPreservesOriginalRequestQuery(t *testing.T) {
	const rawQuery = "b=2&utm_source=signed&a=1&b=1"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.RawQuery != rawQuery {
			t.Errorf("RawQuery = %q, want %q", r.URL.RawQuery, rawQuery)
		}
		_, _ = w.Write([]byte("ok"))
	}))
	t.Cleanup(server.Close)

	client := NewHTTPClient(HTTPOptions{Timeout: time.Second, MaxResponseBytes: 1024})
	response, err := client.Get(context.Background(), server.URL+"/article?"+rawQuery)
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if response.URL != server.URL+"/article?"+rawQuery {
		t.Fatalf("URL = %q, want original request URL", response.URL)
	}
}

func TestHTTPClientRetries503WithExponentialBackoff(t *testing.T) {
	var attempts atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		if attempts.Add(1) <= 2 {
			http.Error(w, "unavailable", http.StatusServiceUnavailable)
			return
		}
		_, _ = w.Write([]byte("ready"))
	}))
	t.Cleanup(server.Close)

	var waits []time.Duration
	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		RetryTimes:       2,
		BackoffBase:      25 * time.Millisecond,
		MaxResponseBytes: 1024,
		Wait: func(_ context.Context, delay time.Duration) error {
			waits = append(waits, delay)
			return nil
		},
	})

	response, err := client.Get(context.Background(), server.URL)
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if got := string(response.Body); got != "ready" {
		t.Fatalf("Body = %q, want %q", got, "ready")
	}
	if got := attempts.Load(); got != 3 {
		t.Fatalf("attempts = %d, want 3", got)
	}
	if len(waits) != 2 || waits[0] != 25*time.Millisecond || waits[1] != 50*time.Millisecond {
		t.Fatalf("waits = %v, want [25ms 50ms]", waits)
	}
}

func TestHTTPClientDoesNotRetry404(t *testing.T) {
	var attempts atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		attempts.Add(1)
		http.NotFound(w, nil)
	}))
	t.Cleanup(server.Close)

	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		RetryTimes:       3,
		BackoffBase:      time.Millisecond,
		MaxResponseBytes: 1024,
		Wait: func(context.Context, time.Duration) error {
			t.Fatal("Wait() called for non-retryable 404")
			return nil
		},
	})

	response, err := client.Get(context.Background(), server.URL)
	if response != nil {
		t.Fatalf("response = %#v, want nil", response)
	}
	assertCrawlError(t, err, ErrorHTTP4xx, http.StatusNotFound, false)
	if got := attempts.Load(); got != 1 {
		t.Fatalf("attempts = %d, want 1", got)
	}
}

func TestHTTPClientWaitsBetweenRequestsToSameHost(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("ok"))
	}))
	t.Cleanup(server.Close)

	var waits []time.Duration
	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		PerHostInterval:  250 * time.Millisecond,
		MaxResponseBytes: 1024,
		Wait: func(_ context.Context, delay time.Duration) error {
			waits = append(waits, delay)
			return nil
		},
	})

	if _, err := client.Get(context.Background(), server.URL+"/first"); err != nil {
		t.Fatalf("first Get() error = %v", err)
	}
	if _, err := client.Get(context.Background(), server.URL+"/second"); err != nil {
		t.Fatalf("second Get() error = %v", err)
	}

	if len(waits) != 1 {
		t.Fatalf("Wait() calls = %d, want 1; waits=%v", len(waits), waits)
	}
	if waits[0] <= 0 || waits[0] > 250*time.Millisecond {
		t.Fatalf("same-host wait = %v, want > 0 and <= 250ms", waits[0])
	}
}

func TestHTTPClientDoesNotBlockDifferentHosts(t *testing.T) {
	firstReached := make(chan struct{}, 1)
	first := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		firstReached <- struct{}{}
		_, _ = w.Write([]byte("first"))
	}))
	t.Cleanup(first.Close)
	secondReached := make(chan struct{}, 1)
	second := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		secondReached <- struct{}{}
		_, _ = w.Write([]byte("second"))
	}))
	t.Cleanup(second.Close)

	waitStarted := make(chan struct{}, 1)
	releaseWait := make(chan struct{})
	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		PerHostInterval:  time.Hour,
		MaxResponseBytes: 1024,
		Wait: func(ctx context.Context, _ time.Duration) error {
			waitStarted <- struct{}{}
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-releaseWait:
				return nil
			}
		},
	})

	if _, err := client.Get(context.Background(), first.URL); err != nil {
		t.Fatalf("seed Get() error = %v", err)
	}
	<-firstReached

	firstResult := make(chan error, 1)
	go func() {
		_, err := client.Get(context.Background(), first.URL)
		firstResult <- err
	}()
	select {
	case <-waitStarted:
	case <-time.After(time.Second):
		t.Fatal("same-host request did not begin waiting")
	}

	secondResult := make(chan error, 1)
	go func() {
		_, err := client.Get(context.Background(), second.URL)
		secondResult <- err
	}()
	select {
	case <-secondReached:
	case <-time.After(time.Second):
		t.Fatal("different-host request was blocked by same-host wait")
	}
	select {
	case err := <-secondResult:
		if err != nil {
			t.Fatalf("different-host Get() error = %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("different-host request did not complete")
	}

	close(releaseWait)
	select {
	case err := <-firstResult:
		if err != nil {
			t.Fatalf("same-host Get() error = %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("same-host request did not complete after wait release")
	}
}

func TestHTTPClientSameHostConcurrentWaitCanBeCanceled(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("ok"))
	}))
	t.Cleanup(server.Close)

	waitStarted := make(chan struct{}, 1)
	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		PerHostInterval:  time.Hour,
		MaxResponseBytes: 1024,
		Wait: func(ctx context.Context, _ time.Duration) error {
			waitStarted <- struct{}{}
			<-ctx.Done()
			return ctx.Err()
		},
	})
	if _, err := client.Get(context.Background(), server.URL); err != nil {
		t.Fatalf("seed Get() error = %v", err)
	}

	firstCtx, cancelFirst := context.WithCancel(context.Background())
	defer cancelFirst()
	firstResult := make(chan error, 1)
	go func() {
		_, err := client.Get(firstCtx, server.URL+"/first")
		firstResult <- err
	}()
	select {
	case <-waitStarted:
	case <-time.After(time.Second):
		t.Fatal("first request did not begin waiting")
	}

	secondCtx, cancelSecond := context.WithCancel(context.Background())
	secondResult := make(chan error, 1)
	go func() {
		_, err := client.Get(secondCtx, server.URL+"/second")
		secondResult <- err
	}()
	cancelSecond()
	select {
	case err := <-secondResult:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("second Get() error = %v, want context.Canceled", err)
		}
	case <-time.After(time.Second):
		t.Fatal("second request did not stop after cancellation")
	}

	cancelFirst()
	select {
	case err := <-firstResult:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("first Get() error = %v, want context.Canceled", err)
		}
	case <-time.After(time.Second):
		t.Fatal("first request did not stop after cancellation")
	}
}

func TestHTTPClientCanceledHostWaitDoesNotDelayNextRequest(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("ok"))
	}))
	t.Cleanup(server.Close)

	waitStarted := make(chan struct{}, 1)
	var waitsMu sync.Mutex
	var waits []time.Duration
	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		PerHostInterval:  time.Hour,
		MaxResponseBytes: 1024,
		Wait: func(ctx context.Context, delay time.Duration) error {
			waitsMu.Lock()
			waits = append(waits, delay)
			call := len(waits)
			waitsMu.Unlock()
			if call == 1 {
				waitStarted <- struct{}{}
				<-ctx.Done()
				return ctx.Err()
			}
			return nil
		},
	})
	if _, err := client.Get(context.Background(), server.URL); err != nil {
		t.Fatalf("seed Get() error = %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	result := make(chan error, 1)
	go func() {
		_, err := client.Get(ctx, server.URL+"/canceled")
		result <- err
	}()
	<-waitStarted
	cancel()
	if err := <-result; !errors.Is(err, context.Canceled) {
		t.Fatalf("canceled Get() error = %v, want context.Canceled", err)
	}

	if _, err := client.Get(context.Background(), server.URL+"/next"); err != nil {
		t.Fatalf("next Get() error = %v", err)
	}
	waitsMu.Lock()
	defer waitsMu.Unlock()
	if len(waits) != 2 {
		t.Fatalf("waits = %v, want two waits", waits)
	}
	if waits[1] > time.Hour {
		t.Fatalf("next wait = %v, want at most original 1h interval after cancellation", waits[1])
	}
}

func TestHTTPClientRejectsOversizedResponse(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("12345"))
	}))
	t.Cleanup(server.Close)

	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		MaxResponseBytes: 4,
	})
	response, err := client.Get(context.Background(), server.URL)
	if response != nil {
		t.Fatalf("response = %#v, want nil", response)
	}
	assertCrawlError(t, err, ErrorResponseTooLarge, http.StatusOK, false)
}

func TestHTTPClientCancellationStopsBackoffImmediately(t *testing.T) {
	var attempts atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		attempts.Add(1)
		http.Error(w, "unavailable", http.StatusServiceUnavailable)
	}))
	t.Cleanup(server.Close)

	waitStarted := make(chan struct{})
	var once sync.Once
	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		RetryTimes:       3,
		BackoffBase:      time.Hour,
		MaxResponseBytes: 1024,
		Wait: func(ctx context.Context, _ time.Duration) error {
			once.Do(func() { close(waitStarted) })
			<-ctx.Done()
			return ctx.Err()
		},
	})

	ctx, cancel := context.WithCancel(context.Background())
	result := make(chan error, 1)
	go func() {
		_, err := client.Get(ctx, server.URL)
		result <- err
	}()

	select {
	case <-waitStarted:
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for retry backoff")
	}
	cancel()

	select {
	case err := <-result:
		var crawlErr *CrawlError
		if !errors.As(err, &crawlErr) {
			t.Fatalf("error = %T, want *CrawlError", err)
		}
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("error = %v, want context.Canceled", err)
		}
		if crawlErr.Retryable {
			t.Fatal("Retryable = true, want false after cancellation")
		}
	case <-time.After(time.Second):
		t.Fatal("Get() did not stop after context cancellation")
	}

	if got := attempts.Load(); got != 1 {
		t.Fatalf("attempts = %d, want 1", got)
	}
}

func TestHTTPClientUsesRetryAfterBeforeBackoff(t *testing.T) {
	var attempts atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		if attempts.Add(1) == 1 {
			w.Header().Set("Retry-After", "7")
			http.Error(w, "slow down", http.StatusTooManyRequests)
			return
		}
		_, _ = w.Write([]byte("ok"))
	}))
	t.Cleanup(server.Close)

	var waits []time.Duration
	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		RetryTimes:       1,
		BackoffBase:      25 * time.Millisecond,
		MaxResponseBytes: 1024,
		Wait: func(_ context.Context, delay time.Duration) error {
			waits = append(waits, delay)
			return nil
		},
	})

	if _, err := client.Get(context.Background(), server.URL); err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if len(waits) != 1 || waits[0] != 7*time.Second {
		t.Fatalf("waits = %v, want [7s]", waits)
	}
}

func TestHTTPClientClampsRetryAfterToMaxRetryDelay(t *testing.T) {
	var attempts atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		if attempts.Add(1) == 1 {
			w.Header().Set("Retry-After", "120")
			http.Error(w, "slow down", http.StatusTooManyRequests)
			return
		}
		_, _ = w.Write([]byte("ok"))
	}))
	t.Cleanup(server.Close)

	var waits []time.Duration
	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		RetryTimes:       1,
		BackoffBase:      time.Second,
		MaxRetryDelay:    3 * time.Second,
		MaxResponseBytes: 1024,
		Wait: func(_ context.Context, delay time.Duration) error {
			waits = append(waits, delay)
			return nil
		},
	})
	if _, err := client.Get(context.Background(), server.URL); err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if len(waits) != 1 || waits[0] != 3*time.Second {
		t.Fatalf("waits = %v, want [3s]", waits)
	}
}

func TestHTTPClientClampsExponentialBackoffToMaxRetryDelay(t *testing.T) {
	var attempts atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		if attempts.Add(1) <= 2 {
			http.Error(w, "unavailable", http.StatusServiceUnavailable)
			return
		}
		_, _ = w.Write([]byte("ok"))
	}))
	t.Cleanup(server.Close)

	var waits []time.Duration
	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		RetryTimes:       2,
		BackoffBase:      5 * time.Second,
		MaxRetryDelay:    3 * time.Second,
		MaxResponseBytes: 1024,
		Wait: func(_ context.Context, delay time.Duration) error {
			waits = append(waits, delay)
			return nil
		},
	})
	if _, err := client.Get(context.Background(), server.URL); err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if len(waits) != 2 || waits[0] != 3*time.Second || waits[1] != 3*time.Second {
		t.Fatalf("waits = %v, want [3s 3s]", waits)
	}
}

func TestHTTPClientRedirectAppliesTargetHostRateLimit(t *testing.T) {
	const userAgent = "KnowMateCrawler/1.0 (+https://example.test/bot)"
	var targetRequests atomic.Int32
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		targetRequests.Add(1)
		if got := r.Header.Get("User-Agent"); got != userAgent {
			t.Errorf("redirected User-Agent = %q, want %q", got, userAgent)
		}
		_, _ = w.Write([]byte("target"))
	}))
	t.Cleanup(target.Close)

	source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, target.URL+"/article", http.StatusFound)
	}))
	t.Cleanup(source.Close)

	var waitsMu sync.Mutex
	var waits []time.Duration
	client := NewHTTPClient(HTTPOptions{
		UserAgent:        userAgent,
		Timeout:          time.Second,
		PerHostInterval:  time.Hour,
		MaxResponseBytes: 1024,
		Wait: func(_ context.Context, delay time.Duration) error {
			waitsMu.Lock()
			waits = append(waits, delay)
			waitsMu.Unlock()
			return nil
		},
	})
	if _, err := client.Get(context.Background(), target.URL+"/seed"); err != nil {
		t.Fatalf("seed Get() error = %v", err)
	}

	response, err := client.Get(context.Background(), source.URL+"/start")
	if err != nil {
		t.Fatalf("redirect Get() error = %v", err)
	}
	if response.URL != target.URL+"/article" {
		t.Fatalf("URL = %q, want redirect target %q", response.URL, target.URL+"/article")
	}
	if got := targetRequests.Load(); got != 2 {
		t.Fatalf("target requests = %d, want 2", got)
	}
	waitsMu.Lock()
	defer waitsMu.Unlock()
	if len(waits) != 1 || waits[0] <= 0 {
		t.Fatalf("target-host waits = %v, want one positive wait", waits)
	}
}

func TestHTTPClientRedirectWithoutLocationReturnsStableError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusFound)
	}))
	t.Cleanup(server.Close)

	client := NewHTTPClient(HTTPOptions{Timeout: time.Second, MaxResponseBytes: 1024})
	response, err := client.Get(context.Background(), server.URL)
	if response != nil {
		t.Fatalf("response = %#v, want nil", response)
	}
	assertCrawlError(t, err, ErrorParse, http.StatusFound, false)
}

func TestHTTPClientRedirectPreservesResolvedQuery(t *testing.T) {
	const rawQuery = "z=2&utm_source=signed&a=1"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/start" {
			w.Header().Set("Location", "/target?"+rawQuery)
			w.WriteHeader(http.StatusFound)
			return
		}
		if r.URL.RawQuery != rawQuery {
			t.Errorf("redirect RawQuery = %q, want %q", r.URL.RawQuery, rawQuery)
		}
		_, _ = w.Write([]byte("ok"))
	}))
	t.Cleanup(server.Close)

	client := NewHTTPClient(HTTPOptions{Timeout: time.Second, MaxResponseBytes: 1024})
	response, err := client.Get(context.Background(), server.URL+"/start")
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if response.URL != server.URL+"/target?"+rawQuery {
		t.Fatalf("URL = %q, want resolved redirect with original query", response.URL)
	}
}

func TestHTTPClientDeadlineReturnsTimeout(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		<-r.Context().Done()
	}))
	t.Cleanup(server.Close)

	client := NewHTTPClient(HTTPOptions{
		Timeout:          20 * time.Millisecond,
		MaxResponseBytes: 1024,
	})
	response, err := client.Get(context.Background(), server.URL)
	if response != nil {
		t.Fatalf("response = %#v, want nil", response)
	}
	assertCrawlError(t, err, ErrorTimeout, 0, true)
}

func TestHTTPClientRetriesTemporaryNetworkError(t *testing.T) {
	var attempts atomic.Int32
	transport := roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if attempts.Add(1) == 1 {
			return nil, temporaryNetworkError{}
		}
		return responseForRequest(request, http.StatusOK, "ok"), nil
	})

	var waits []time.Duration
	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		RetryTimes:       1,
		BackoffBase:      10 * time.Millisecond,
		MaxResponseBytes: 1024,
		Transport:        transport,
		Wait: func(_ context.Context, delay time.Duration) error {
			waits = append(waits, delay)
			return nil
		},
	})
	response, err := client.Get(context.Background(), "https://example.test/article")
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if got := string(response.Body); got != "ok" {
		t.Fatalf("Body = %q, want ok", got)
	}
	if got := attempts.Load(); got != 2 {
		t.Fatalf("attempts = %d, want 2", got)
	}
	if len(waits) != 1 || waits[0] != 10*time.Millisecond {
		t.Fatalf("waits = %v, want [10ms]", waits)
	}
}

func TestHTTPClientUsesInjectedTransport(t *testing.T) {
	const userAgent = "KnowMateCrawler/1.0"
	var called atomic.Bool
	transport := roundTripFunc(func(request *http.Request) (*http.Response, error) {
		called.Store(true)
		if got := request.Header.Get("User-Agent"); got != userAgent {
			t.Errorf("User-Agent = %q, want %q", got, userAgent)
		}
		return responseForRequest(request, http.StatusOK, "injected"), nil
	})

	client := NewHTTPClient(HTTPOptions{
		UserAgent:        userAgent,
		Timeout:          time.Second,
		MaxResponseBytes: 1024,
		Transport:        transport,
	})
	response, err := client.Get(context.Background(), "https://example.test/article")
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if !called.Load() {
		t.Fatal("injected Transport was not called")
	}
	if got := string(response.Body); got != "injected" {
		t.Fatalf("Body = %q, want injected", got)
	}
}

func TestHTTPClientHostLimiterMapIsBounded(t *testing.T) {
	transport := roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return responseForRequest(request, http.StatusOK, "ok"), nil
	})
	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		PerHostInterval:  time.Nanosecond,
		MaxResponseBytes: 1024,
		Transport:        transport,
		Wait: func(context.Context, time.Duration) error {
			return nil
		},
	})

	for index := 0; index < maxHostLimiters+50; index++ {
		rawURL := "https://host-" + strconv.Itoa(index) + ".example.test/article"
		if _, err := client.Get(context.Background(), rawURL); err != nil {
			t.Fatalf("Get(%q) error = %v", rawURL, err)
		}
	}
	if got := len(client.hostLimiters); got > maxHostLimiters {
		t.Fatalf("host limiter count = %d, want <= %d", got, maxHostLimiters)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return fn(request)
}

type temporaryNetworkError struct{}

func (temporaryNetworkError) Error() string   { return "temporary network failure" }
func (temporaryNetworkError) Timeout() bool   { return false }
func (temporaryNetworkError) Temporary() bool { return true }

func responseForRequest(request *http.Request, status int, body string) *http.Response {
	return &http.Response{
		StatusCode: status,
		Header:     make(http.Header),
		Body:       io.NopCloser(strings.NewReader(body)),
		Request:    request,
	}
}

var _ net.Error = temporaryNetworkError{}

func assertCrawlError(t *testing.T, err error, errorType ErrorType, status int, retryable bool) {
	t.Helper()

	var crawlErr *CrawlError
	if !errors.As(err, &crawlErr) {
		t.Fatalf("error = %T %v, want *CrawlError", err, err)
	}
	if crawlErr.Type != errorType {
		t.Fatalf("Type = %q, want %q", crawlErr.Type, errorType)
	}
	if crawlErr.HTTPStatus != status {
		t.Fatalf("HTTPStatus = %d, want %d", crawlErr.HTTPStatus, status)
	}
	if crawlErr.Retryable != retryable {
		t.Fatalf("Retryable = %t, want %t", crawlErr.Retryable, retryable)
	}
}
