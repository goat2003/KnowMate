package crawler

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/jimsmart/grobotstxt"
)

const maxRobotsCacheEntries = 256

type RobotsManager struct {
	client    *HTTPClient
	userAgent string
	ttl       time.Duration
	mu        sync.Mutex
	cache     map[string]robotsCacheEntry
	inflight  map[string]*robotsInflight
}

type robotsCacheEntry struct {
	content   string
	expiresAt time.Time
	lastUsed  time.Time
}

type robotsInflight struct {
	done    chan struct{}
	content string
	err     error
}

func NewRobotsManager(client *HTTPClient, userAgent string, ttl time.Duration) *RobotsManager {
	return &RobotsManager{
		client:    client,
		userAgent: robotsUserAgentProductToken(userAgent),
		ttl:       ttl,
		cache:     make(map[string]robotsCacheEntry),
		inflight:  make(map[string]*robotsInflight),
	}
}

func (m *RobotsManager) Allowed(ctx context.Context, targetURL string) (bool, error) {
	if err := ctx.Err(); err != nil {
		return false, ClassifyError(err, 0)
	}

	normalizedURL, err := NormalizeURL(targetURL)
	if err != nil {
		return false, ClassifyError(err, 0)
	}
	parsedURL, err := url.Parse(normalizedURL)
	if err != nil {
		return false, ClassifyError(err, 0)
	}

	origin := parsedURL.Scheme + "://" + parsedURL.Host
	content, err := m.robotsContent(ctx, origin)
	if err != nil {
		classified := ClassifyError(err, 0)
		if classified.Retryable {
			return true, classified
		}
		return false, classified
	}

	if !grobotstxt.AgentAllowed(content, m.userAgent, targetURL) {
		return false, NewCrawlError(
			ErrorRobotsDenied,
			fmt.Sprintf("robots.txt denies %s", targetURL),
			0,
			false,
			nil,
		)
	}
	return true, nil
}

func (m *RobotsManager) cached(origin string) (string, bool) {
	if m.ttl <= 0 {
		return "", false
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	return m.cachedLocked(origin, time.Now())
}

func (m *RobotsManager) cachedLocked(origin string, now time.Time) (string, bool) {
	entry, ok := m.cache[origin]
	if !ok || !now.Before(entry.expiresAt) {
		delete(m.cache, origin)
		return "", false
	}
	entry.lastUsed = now
	m.cache[origin] = entry
	return entry.content, true
}

func (m *RobotsManager) store(origin, content string) {
	if m.ttl <= 0 {
		return
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.storeLocked(origin, content, time.Now())
}

func (m *RobotsManager) storeLocked(origin, content string, now time.Time) {
	if m.ttl <= 0 {
		return
	}
	if _, exists := m.cache[origin]; !exists && len(m.cache) >= maxRobotsCacheEntries {
		m.cleanupCacheLocked(now)
	}
	m.cache[origin] = robotsCacheEntry{
		content:   content,
		expiresAt: now.Add(m.ttl),
		lastUsed:  now,
	}
}

func (m *RobotsManager) cleanupCacheLocked(now time.Time) {
	for origin, entry := range m.cache {
		if !now.Before(entry.expiresAt) {
			delete(m.cache, origin)
		}
	}
	for len(m.cache) >= maxRobotsCacheEntries {
		var oldestOrigin string
		var oldestTime time.Time
		for origin, entry := range m.cache {
			if oldestOrigin == "" || entry.lastUsed.Before(oldestTime) {
				oldestOrigin = origin
				oldestTime = entry.lastUsed
			}
		}
		delete(m.cache, oldestOrigin)
	}
}

func (m *RobotsManager) robotsContent(ctx context.Context, origin string) (string, error) {
	if content, ok := m.cached(origin); ok {
		return content, nil
	}

	m.mu.Lock()
	if content, ok := m.cachedLocked(origin, time.Now()); ok {
		m.mu.Unlock()
		return content, nil
	}
	if call := m.inflight[origin]; call != nil {
		m.mu.Unlock()
		return waitForRobotsCall(ctx, call)
	}
	call := &robotsInflight{done: make(chan struct{})}
	m.inflight[origin] = call
	m.mu.Unlock()

	go m.runRobotsFetch(origin, call)
	return waitForRobotsCall(ctx, call)
}

func (m *RobotsManager) runRobotsFetch(origin string, call *robotsInflight) {
	timeout := defaultHTTPTimeout
	if m.client != nil && m.client.client != nil && m.client.client.Timeout > 0 {
		timeout = m.client.client.Timeout
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	content, cacheable, err := m.fetchRobots(ctx, origin)
	m.mu.Lock()
	if cacheable {
		m.storeLocked(origin, content, time.Now())
	}
	call.content = content
	call.err = err
	delete(m.inflight, origin)
	close(call.done)
	m.mu.Unlock()
}

func waitForRobotsCall(ctx context.Context, call *robotsInflight) (string, error) {
	select {
	case <-ctx.Done():
		return "", ctx.Err()
	case <-call.done:
		return call.content, call.err
	}
}

func (m *RobotsManager) fetchRobots(ctx context.Context, origin string) (string, bool, error) {
	response, err := m.client.Get(ctx, origin+"/robots.txt")
	if err != nil {
		var crawlErr *CrawlError
		if errors.As(err, &crawlErr) && crawlErr.HTTPStatus == http.StatusNotFound {
			return "", true, nil
		}
		return "", false, err
	}
	return string(response.Body), true, nil
}

func robotsUserAgentProductToken(userAgent string) string {
	fields := strings.Fields(userAgent)
	if len(fields) == 0 {
		return ""
	}
	product, _, _ := strings.Cut(fields[0], "/")
	return product
}
