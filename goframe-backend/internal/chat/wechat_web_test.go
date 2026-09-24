package chat

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gogf/gf/v2/net/ghttp"
	"knowledge-post-agent/goframe-backend/internal/config"
)

func TestWebSessionRoundTripAndTamper(t *testing.T) {
	s := &Service{cfg: config.Config{WeChat: config.WeChatConfig{SessionSecret: strings.Repeat("s", 32)}}}
	req := httptest.NewRequest("GET", "/", nil)
	value := s.makeSession("wx_test")
	req.AddCookie(&http.Cookie{Name: webCookie, Value: value})
	got, ok := s.sessionUser(&ghttp.Request{Request: req})
	if !ok || got != "wx_test" {
		t.Fatalf("session did not validate: %q %v", got, ok)
	}
	req2 := httptest.NewRequest("GET", "/", nil)
	req2.AddCookie(&http.Cookie{Name: webCookie, Value: value[:len(value)-1] + "x"})
	if _, ok := s.sessionUser(&ghttp.Request{Request: req2}); ok {
		t.Fatal("tampered session accepted")
	}
}

func TestOAuthStateValidation(t *testing.T) {
	secret := []byte(strings.Repeat("s", 32))
	state := "state-123"
	validPayload := state + "|" + "4102444800"
	valid := validPayload + "." + signWeb(validPayload, secret)
	if !validOAuthState(valid, state, secret, time.Unix(0, 0)) {
		t.Fatal("valid state rejected")
	}
	if validOAuthState(valid, "other", secret, time.Unix(0, 0)) {
		t.Fatal("state mismatch accepted")
	}
	expiredPayload := state + "|1"
	expired := expiredPayload + "." + signWeb(expiredPayload, secret)
	if validOAuthState(expired, state, secret, time.Unix(2, 0)) {
		t.Fatal("expired state accepted")
	}
}

func TestWebMemoryKeySupportsDeleteAllRoutes(t *testing.T) {
	cases := []struct {
		path string
		want string
	}{
		{path: "/api/wechat/memories", want: ""},
		{path: "/wechat/memories", want: ""},
		{path: "/api/wechat/memories/interests", want: "interests"},
		{path: "/wechat/memories/goal", want: "goal"},
	}
	for _, tc := range cases {
		req := httptest.NewRequest("DELETE", tc.path, nil)
		if got := webMemoryKey(&ghttp.Request{Request: req}); got != tc.want {
			t.Fatalf("path %q: key=%q, want %q", tc.path, got, tc.want)
		}
	}
	query := httptest.NewRequest("DELETE", "/api/wechat/memories?key=style", nil)
	if got := webMemoryKey(&ghttp.Request{Request: query}); got != "style" {
		t.Fatalf("query key=%q, want style", got)
	}
}

func TestWebOnlyWeChatConfigurationDoesNotRequireCallbackKey(t *testing.T) {
	t.Setenv("WECHAT_ENABLED", "true")
	t.Setenv("WECHAT_APP_ID", "wx-web-test")
	t.Setenv("WECHAT_APP_SECRET", "secret-web-test")
	t.Setenv("WECHAT_APP_ID_FILE", "")
	t.Setenv("WECHAT_APP_SECRET_FILE", "")
	t.Setenv("WECHAT_TOKEN_FILE", "")
	t.Setenv("WECHAT_ENCODING_AES_KEY_FILE", "")
	t.Setenv("WECHAT_TOKEN", "")
	t.Setenv("WECHAT_ENCODING_AES_KEY", "")
	wx, err := NewWeChatFromEnv()
	if err != nil || wx != nil {
		t.Fatalf("web-only OAuth should not require encrypted callback fields: %#v %v", wx, err)
	}
}
