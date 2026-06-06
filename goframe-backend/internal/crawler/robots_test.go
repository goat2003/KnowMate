package crawler

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strconv"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestRobotsManagerUsesUserAgentProductToken(t *testing.T) {
	const fullUserAgent = "KnowMateCrawler/1.0 (+https://example.test/bot)"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.Header.Get("User-Agent"); got != fullUserAgent {
			t.Errorf("User-Agent header = %q, want full UA %q", got, fullUserAgent)
		}
		_, _ = w.Write([]byte("User-agent: KnowMateCrawler\nDisallow: /private\n"))
	}))
	t.Cleanup(server.Close)

	client := NewHTTPClient(HTTPOptions{
		UserAgent:        fullUserAgent,
		Timeout:          time.Second,
		MaxResponseBytes: 1024,
	})
	manager := NewRobotsManager(client, fullUserAgent, time.Hour)

	allowed, err := manager.Allowed(context.Background(), server.URL+"/private/article")
	if allowed {
		t.Fatal("Allowed() = true, want false for product-token-specific rule")
	}
	assertCrawlError(t, err, ErrorRobotsDenied, 0, false)
}

func TestRobotsManagerMatchesRulesAgainstOriginalTargetQuery(t *testing.T) {
	const rawQuery = "utm_source=blocked&b=2&a=1"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("User-agent: *\nDisallow: /article?" + rawQuery + "\n"))
	}))
	t.Cleanup(server.Close)

	client := NewHTTPClient(HTTPOptions{Timeout: time.Second, MaxResponseBytes: 1024})
	manager := NewRobotsManager(client, "KnowMateBot", time.Hour)

	allowed, err := manager.Allowed(context.Background(), server.URL+"/article?"+rawQuery)
	if allowed {
		t.Fatal("Allowed() = true, want false for query-specific rule against original target URL")
	}
	assertCrawlError(t, err, ErrorRobotsDenied, 0, false)
}

func TestRobotsManagerDeniesAllowsAndCachesByOrigin(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		if r.URL.Path != "/robots.txt" {
			t.Errorf("path = %q, want /robots.txt", r.URL.Path)
		}
		_, _ = w.Write([]byte("User-agent: KnowMateBot\nDisallow: /private\nAllow: /\n"))
	}))
	t.Cleanup(server.Close)

	client := NewHTTPClient(HTTPOptions{
		UserAgent:        "KnowMateBot",
		Timeout:          time.Second,
		MaxResponseBytes: 1024,
	})
	manager := NewRobotsManager(client, "KnowMateBot", time.Hour)

	allowed, err := manager.Allowed(context.Background(), server.URL+"/private/article")
	if allowed {
		t.Fatal("Allowed() = true, want false for explicitly denied URL")
	}
	assertCrawlError(t, err, ErrorRobotsDenied, 0, false)

	allowed, err = manager.Allowed(context.Background(), server.URL+"/public/article")
	if err != nil {
		t.Fatalf("Allowed() error = %v", err)
	}
	if !allowed {
		t.Fatal("Allowed() = false, want true for allowed URL")
	}
	if got := requests.Load(); got != 1 {
		t.Fatalf("robots.txt requests = %d, want 1 from cache", got)
	}
}

func TestRobotsManagerAllowsAndCaches404(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		requests.Add(1)
		http.NotFound(w, nil)
	}))
	t.Cleanup(server.Close)

	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		MaxResponseBytes: 1024,
	})
	manager := NewRobotsManager(client, "KnowMateBot", time.Hour)

	for _, path := range []string{"/first", "/second"} {
		allowed, err := manager.Allowed(context.Background(), server.URL+path)
		if err != nil {
			t.Fatalf("Allowed(%q) error = %v", path, err)
		}
		if !allowed {
			t.Fatalf("Allowed(%q) = false, want true for missing robots.txt", path)
		}
	}
	if got := requests.Load(); got != 1 {
		t.Fatalf("robots.txt requests = %d, want 1 from cached 404", got)
	}
}

func TestRobotsManagerCoalescesConcurrentCacheMiss(t *testing.T) {
	var requests atomic.Int32
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		requests.Add(1)
		<-release
		_, _ = w.Write([]byte("User-agent: *\nAllow: /\n"))
	}))
	t.Cleanup(server.Close)

	client := NewHTTPClient(HTTPOptions{Timeout: time.Second, MaxResponseBytes: 1024})
	manager := NewRobotsManager(client, "KnowMateBot", time.Hour)

	const callers = 20
	start := make(chan struct{})
	var ready sync.WaitGroup
	ready.Add(callers)
	results := make(chan error, callers)
	for index := 0; index < callers; index++ {
		go func(index int) {
			ready.Done()
			<-start
			allowed, err := manager.Allowed(context.Background(), server.URL+"/article/"+strconv.Itoa(index))
			if err != nil {
				results <- err
				return
			}
			if !allowed {
				results <- errors.New("Allowed() = false, want true")
				return
			}
			results <- nil
		}(index)
	}
	ready.Wait()
	close(start)

	deadline := time.Now().Add(time.Second)
	for requests.Load() == 0 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	time.Sleep(20 * time.Millisecond)
	close(release)

	for range callers {
		if err := <-results; err != nil {
			t.Fatal(err)
		}
	}
	if got := requests.Load(); got != 1 {
		t.Fatalf("robots.txt requests = %d, want 1 for concurrent cache miss", got)
	}
}

func TestRobotsManagerFirstCallerCancellationDoesNotCancelSharedFetch(t *testing.T) {
	var requests atomic.Int32
	requestStarted := make(chan struct{})
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		if requests.Add(1) == 1 {
			close(requestStarted)
		}
		<-release
		_, _ = w.Write([]byte("User-agent: *\nAllow: /\n"))
	}))
	t.Cleanup(server.Close)

	client := NewHTTPClient(HTTPOptions{Timeout: time.Second, MaxResponseBytes: 1024})
	manager := NewRobotsManager(client, "KnowMateBot", time.Hour)

	firstCtx, cancelFirst := context.WithCancel(context.Background())
	firstResult := make(chan error, 1)
	go func() {
		_, err := manager.Allowed(firstCtx, server.URL+"/first")
		firstResult <- err
	}()
	select {
	case <-requestStarted:
	case <-time.After(time.Second):
		t.Fatal("shared robots request did not start")
	}

	secondResult := make(chan error, 1)
	go func() {
		allowed, err := manager.Allowed(context.Background(), server.URL+"/second")
		if err != nil {
			secondResult <- err
			return
		}
		if !allowed {
			secondResult <- errors.New("Allowed() = false, want true")
			return
		}
		secondResult <- nil
	}()

	cancelFirst()
	select {
	case err := <-firstResult:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("first Allowed() error = %v, want context.Canceled", err)
		}
	case <-time.After(time.Second):
		t.Fatal("first caller did not exit after cancellation")
	}

	close(release)
	select {
	case err := <-secondResult:
		if err != nil {
			t.Fatalf("second Allowed() error = %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("second caller did not receive shared robots result")
	}
	if got := requests.Load(); got != 1 {
		t.Fatalf("robots.txt requests = %d, want 1 shared request", got)
	}
}

func TestRobotsManagerFailsOpenWithDiagnosticOnTemporaryFailure(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "unavailable", http.StatusServiceUnavailable)
	}))
	t.Cleanup(server.Close)

	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		RetryTimes:       0,
		MaxResponseBytes: 1024,
	})
	manager := NewRobotsManager(client, "KnowMateBot", time.Hour)

	allowed, err := manager.Allowed(context.Background(), server.URL+"/article")
	if !allowed {
		t.Fatal("Allowed() = false, want true when robots.txt temporarily fails")
	}
	assertCrawlError(t, err, ErrorHTTP5xx, http.StatusServiceUnavailable, true)
}

func TestRobotsManagerFailsClosedOnPermanentFailure(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "forbidden", http.StatusForbidden)
	}))
	t.Cleanup(server.Close)

	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		MaxResponseBytes: 1024,
	})
	manager := NewRobotsManager(client, "KnowMateBot", time.Hour)

	allowed, err := manager.Allowed(context.Background(), server.URL+"/article")
	if allowed {
		t.Fatal("Allowed() = true, want false for permanent robots.txt failure")
	}
	assertCrawlError(t, err, ErrorHTTP4xx, http.StatusForbidden, false)
}

func TestRobotsManagerFailsClosedOnCanceledContext(t *testing.T) {
	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		MaxResponseBytes: 1024,
	})
	manager := NewRobotsManager(client, "KnowMateBot", time.Hour)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	allowed, err := manager.Allowed(ctx, "https://example.test/article")
	if allowed {
		t.Fatal("Allowed() = true, want false for canceled context")
	}
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error = %v, want context.Canceled", err)
	}
	var crawlErr *CrawlError
	if !errors.As(err, &crawlErr) || crawlErr.Retryable {
		t.Fatalf("error = %#v, want non-retryable *CrawlError", err)
	}
}

func TestRobotsManagerFailsClosedOnCanceledContextWithCachedRules(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("User-agent: *\nAllow: /\n"))
	}))
	t.Cleanup(server.Close)

	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		MaxResponseBytes: 1024,
	})
	manager := NewRobotsManager(client, "KnowMateBot", time.Hour)
	if allowed, err := manager.Allowed(context.Background(), server.URL+"/seed"); err != nil || !allowed {
		t.Fatalf("seed Allowed() = %t, %v; want true, nil", allowed, err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	allowed, err := manager.Allowed(ctx, server.URL+"/cached")
	if allowed {
		t.Fatal("Allowed() = true, want false for canceled context with cached robots.txt")
	}
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error = %v, want context.Canceled", err)
	}
}

func TestRobotsManagerFailsClosedOnInvalidTargetURL(t *testing.T) {
	client := NewHTTPClient(HTTPOptions{
		Timeout:          time.Second,
		MaxResponseBytes: 1024,
	})
	manager := NewRobotsManager(client, "KnowMateBot", time.Hour)

	allowed, err := manager.Allowed(context.Background(), "not-a-url")
	if allowed {
		t.Fatal("Allowed() = true, want false for invalid target URL")
	}
	assertCrawlError(t, err, ErrorInvalidURL, 0, false)
}

func TestRobotsManagerCacheIsBounded(t *testing.T) {
	manager := NewRobotsManager(nil, "KnowMateBot", time.Hour)
	for index := 0; index < maxRobotsCacheEntries+50; index++ {
		manager.store("https://host-"+strconv.Itoa(index)+".example.test", "User-agent: *\nAllow: /\n")
	}
	if got := len(manager.cache); got > maxRobotsCacheEntries {
		t.Fatalf("robots cache count = %d, want <= %d", got, maxRobotsCacheEntries)
	}
}
