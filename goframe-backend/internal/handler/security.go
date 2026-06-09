package handler

import (
	"crypto/subtle"
	"net"
	"net/http"
	"strings"
	"sync"
	"time"

	"knowledge-post-agent/goframe-backend/internal/config"

	"github.com/gogf/gf/v2/frame/g"
	"github.com/gogf/gf/v2/net/ghttp"
)

type securityMiddleware struct {
	apiToken            string
	maxRequestBodyBytes int64
	rateLimitBurst      int
	mu                  sync.Mutex
	clients             map[string]*rateWindow
}

type rateWindow struct {
	start time.Time
	count int
}

func newSecurityMiddleware(cfg config.SecurityConfig) *securityMiddleware {
	cfg = config.Config{Security: cfg}.Normalize().Security
	return &securityMiddleware{
		apiToken:            cfg.APIToken,
		maxRequestBodyBytes: cfg.MaxRequestBodyBytes,
		rateLimitBurst:      cfg.RateLimitBurst,
		clients:             map[string]*rateWindow{},
	}
}

func (m *securityMiddleware) Handle(r *ghttp.Request) {
	r.Response.Header().Set("X-Content-Type-Options", "nosniff")
	r.Response.Header().Set("Referrer-Policy", "no-referrer")
	r.Response.Header().Set("Cache-Control", "no-store")

	if m.maxRequestBodyBytes > 0 && r.Request.Body != nil {
		r.Request.Body = http.MaxBytesReader(r.Response.RawWriter(), r.Request.Body, m.maxRequestBodyBytes)
		if r.Request.ContentLength > m.maxRequestBodyBytes {
			r.Response.WriteStatusExit(http.StatusRequestEntityTooLarge, g.Map{"ok": false, "error": "request body too large"})
			return
		}
	}

	if m.isPublicPath(r.URL.Path) {
		r.Middleware.Next()
		return
	}
	if m.apiToken != "" && !m.authorized(r) {
		r.Response.WriteStatusExit(http.StatusUnauthorized, g.Map{"ok": false, "error": "unauthorized"})
		return
	}
	if !m.allow(r) {
		r.Response.WriteStatusExit(http.StatusTooManyRequests, g.Map{"ok": false, "error": "rate limit exceeded"})
		return
	}
	r.Middleware.Next()
}

func (m *securityMiddleware) isPublicPath(path string) bool {
	return path == "/health"
}

func (m *securityMiddleware) authorized(r *ghttp.Request) bool {
	token := strings.TrimSpace(r.GetHeader("X-API-Key"))
	auth := strings.TrimSpace(r.GetHeader("Authorization"))
	if token == "" && strings.HasPrefix(strings.ToLower(auth), "bearer ") {
		token = strings.TrimSpace(auth[len("bearer "):])
	}
	if token == "" {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(token), []byte(m.apiToken)) == 1
}

func (m *securityMiddleware) allow(r *ghttp.Request) bool {
	if m.rateLimitBurst <= 0 {
		return true
	}
	key := m.clientKey(r)
	now := time.Now()
	m.mu.Lock()
	defer m.mu.Unlock()
	window := m.clients[key]
	if window == nil || now.Sub(window.start) >= time.Minute {
		m.clients[key] = &rateWindow{start: now, count: 1}
		return true
	}
	if window.count >= m.rateLimitBurst {
		return false
	}
	window.count++
	return true
}

func (m *securityMiddleware) clientKey(r *ghttp.Request) string {
	token := strings.TrimSpace(r.GetHeader("X-API-Key"))
	if token == "" {
		token = strings.TrimSpace(r.GetHeader("Authorization"))
	}
	if token != "" {
		return "token:" + token
	}
	host, _, err := net.SplitHostPort(r.Request.RemoteAddr)
	if err != nil || host == "" {
		return "ip:" + r.Request.RemoteAddr
	}
	return "ip:" + host
}
