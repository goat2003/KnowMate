package chat

// Web OAuth endpoints for ordinary WeChat users. This surface deliberately does
// not share the administrator chat routes: identity always comes from a signed
// HttpOnly cookie and never from a request parameter.
import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/gogf/gf/v2/net/ghttp"
)

const webCookie = "knowmate_wechat_session"
const webStateCookie = "knowmate_wechat_oauth_state"

var webLimiter = struct {
	sync.Mutex
	seen map[string][]time.Time
}{seen: map[string][]time.Time{}}

func (s *Service) webSecret() []byte {
	if s.cfg.WeChat.SessionSecret != "" {
		return []byte(s.cfg.WeChat.SessionSecret)
	}
	// Development-only fallback. Production validation rejects this mode.
	return []byte("knowmate-development-wechat-session-secret")
}

func signWeb(value string, secret []byte) string {
	h := hmac.New(sha256.New, secret)
	h.Write([]byte(value))
	return base64.RawURLEncoding.EncodeToString(h.Sum(nil))
}

func (s *Service) makeSession(uid string) string {
	value := uid + "|" + fmt.Sprint(time.Now().Add(7*24*time.Hour).Unix())
	return base64.RawURLEncoding.EncodeToString([]byte(value)) + "." + signWeb(value, s.webSecret())
}

func (s *Service) sessionUser(r *ghttp.Request) (string, bool) {
	c, err := r.Request.Cookie(webCookie)
	if err != nil {
		return "", false
	}
	parts := strings.Split(c.Value, ".")
	if len(parts) != 2 {
		return "", false
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil || !hmac.Equal([]byte(parts[1]), []byte(signWeb(string(raw), s.webSecret()))) {
		return "", false
	}
	fields := strings.Split(string(raw), "|")
	if len(fields) != 2 || !validID.MatchString(fields[0]) {
		return "", false
	}
	var expiry int64
	if _, err = fmt.Sscan(fields[1], &expiry); err != nil || expiry < time.Now().Unix() {
		return "", false
	}
	return fields[0], true
}

func webCookieOptions(r *ghttp.Request, name, value string, maxAge int) {
	secure := r.Request.TLS != nil || strings.EqualFold(r.Header.Get("X-Forwarded-Proto"), "https")
	http.SetCookie(r.Response.RawWriter(), &http.Cookie{Name: name, Value: value, Path: "/", MaxAge: maxAge, HttpOnly: true, Secure: secure, SameSite: http.SameSiteLaxMode})
}

func webFail(r *ghttp.Request, status int, message string) { fail(r, status, message) }

func (s *Service) requireWebUser(r *ghttp.Request) (string, bool) {
	uid, ok := s.sessionUser(r)
	if !ok {
		webFail(r, http.StatusUnauthorized, "微信授权已失效，请重新授权")
	}
	return uid, ok
}

func allowWebRequest(r *ghttp.Request) bool {
	key := r.Header.Get("X-Real-IP")
	if key == "" {
		key = strings.Split(r.Header.Get("X-Forwarded-For"), ",")[0]
	}
	if key == "" {
		key = r.RemoteAddr
	}
	if key == "" {
		key = "unknown"
	}
	now := time.Now()
	webLimiter.Lock()
	defer webLimiter.Unlock()
	items := webLimiter.seen[key][:0]
	for _, t := range webLimiter.seen[key] {
		if now.Sub(t) < time.Minute {
			items = append(items, t)
		}
	}
	if len(items) >= 30 {
		webLimiter.seen[key] = items
		return false
	}
	webLimiter.seen[key] = append(items, now)
	return true
}

func (s *Service) webOriginAllowed(r *ghttp.Request) bool {
	origin := strings.TrimSpace(r.Header.Get("Origin"))
	if origin == "" || strings.TrimSpace(s.cfg.WeChat.AllowedOrigins) == "" {
		return true
	}
	for _, allowed := range strings.Split(s.cfg.WeChat.AllowedOrigins, ",") {
		if strings.TrimSpace(allowed) == origin {
			return true
		}
	}
	return false
}

func randomText(n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		return fmt.Sprintf("%d", time.Now().UnixNano())
	}
	return base64.RawURLEncoding.EncodeToString(b)
}

func validOAuthState(cookieValue, state string, secret []byte, now time.Time) bool {
	parts := strings.Split(cookieValue, ".")
	if len(parts) != 2 || !hmac.Equal([]byte(parts[1]), []byte(signWeb(parts[0], secret))) {
		return false
	}
	stateParts := strings.Split(parts[0], "|")
	if len(stateParts) != 2 || stateParts[0] != state {
		return false
	}
	var expiry int64
	_, err := fmt.Sscan(stateParts[1], &expiry)
	return err == nil && expiry >= now.Unix()
}

func (s *Service) webAuth(r *ghttp.Request) {
	if !allowWebRequest(r) {
		webFail(r, http.StatusTooManyRequests, "请求过于频繁，请稍后再试")
		return
	}
	if _, ok := s.sessionUser(r); ok {
		r.Response.RedirectTo(s.cfg.WeChat.ChatPageURL)
		return
	}
	if s.cfg.WeChat.DevAnonymous {
		uid := "dev_" + randomText(12)
		webCookieOptions(r, webCookie, s.makeSession(uid), 7*24*3600)
		r.Response.RedirectTo(s.cfg.WeChat.ChatPageURL)
		return
	}
	if s.cfg.WeChat.AppID == "" || s.cfg.WeChat.AppSecret == "" || s.cfg.WeChat.OAuthRedirect == "" || len(s.cfg.WeChat.SessionSecret) < 32 {
		webFail(r, http.StatusServiceUnavailable, "微信授权配置不完整")
		return
	}
	state := randomText(24)
	statePayload := state + "|" + fmt.Sprint(time.Now().Add(5*time.Minute).Unix())
	webCookieOptions(r, webStateCookie, statePayload+"."+signWeb(statePayload, s.webSecret()), 300)
	query := url.Values{"appid": {s.cfg.WeChat.AppID}, "redirect_uri": {s.cfg.WeChat.OAuthRedirect}, "response_type": {"code"}, "scope": {"snsapi_base"}, "state": {state}}
	r.Response.RedirectTo("https://open.weixin.qq.com/connect/oauth2/authorize?" + query.Encode() + "#wechat_redirect")
}

func (s *Service) webCallback(r *ghttp.Request) {
	state := r.GetQuery("state").String()
	code := r.GetQuery("code").String()
	if state == "" || code == "" || len(code) > 512 {
		webFail(r, http.StatusBadRequest, "微信授权参数无效")
		return
	}
	c, err := r.Request.Cookie(webStateCookie)
	if err != nil {
		webFail(r, http.StatusForbidden, "微信授权状态已过期，请重新授权")
		return
	}
	if !validOAuthState(c.Value, state, s.webSecret(), time.Now()) {
		webFail(r, http.StatusForbidden, "微信授权状态校验失败，请重新授权")
		return
	}
	// OAuth state is single-use; clearing it before the token exchange prevents replay.
	webCookieOptions(r, webStateCookie, "", -1)
	ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
	defer cancel()
	var token struct {
		OpenID  string `json:"openid"`
		ErrCode int    `json:"errcode"`
	}
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, "https://api.weixin.qq.com/sns/oauth2/access_token", nil)
	params := req.URL.Query()
	params.Set("appid", s.cfg.WeChat.AppID)
	params.Set("secret", s.cfg.WeChat.AppSecret)
	params.Set("code", code)
	params.Set("grant_type", "authorization_code")
	req.URL.RawQuery = params.Encode()
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		webFail(r, http.StatusBadGateway, "微信授权服务暂时不可用，请稍后重试")
		return
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 32*1024))
	if resp.StatusCode != http.StatusOK || json.Unmarshal(body, &token) != nil || token.OpenID == "" || token.ErrCode != 0 {
		webFail(r, http.StatusBadGateway, "微信授权失败，请重新授权")
		return
	}
	uid := wxUser(s.cfg.WeChat.AppID, token.OpenID)
	webCookieOptions(r, webCookie, s.makeSession(uid), 7*24*3600)
	webCookieOptions(r, webStateCookie, "", -1)
	r.Response.RedirectTo(s.cfg.WeChat.ChatPageURL)
}

func (s *Service) webMe(r *ghttp.Request) {
	uid, ok := s.requireWebUser(r)
	if ok {
		r.Response.WriteJson(map[string]any{"ok": true, "user": map[string]any{"id": uid}})
	}
}

func (s *Service) webConversations(r *ghttp.Request) {
	uid, ok := s.requireWebUser(r)
	if !ok {
		return
	}
	s.conversationsFor(r, uid)
}

func (s *Service) conversationsFor(r *ghttp.Request, uid string) {
	rows, err := s.db.QueryContext(r.Context(), `SELECT `+jobColumns+` FROM chat_jobs WHERE user_id=? ORDER BY id DESC LIMIT 60`, uid)
	if err != nil {
		webFail(r, 503, "会话暂时不可用")
		return
	}
	defer rows.Close()
	items := []Job{}
	for rows.Next() {
		j, e := scanJob(rows)
		if e != nil {
			webFail(r, 500, "读取会话失败")
			return
		}
		items = append(items, j)
	}
	for i, j := 0, len(items)-1; i < j; i, j = i+1, j-1 {
		items[i], items[j] = items[j], items[i]
	}
	r.Response.WriteJson(map[string]any{"ok": true, "items": items})
}

func (s *Service) webMessages(r *ghttp.Request) {
	uid, ok := s.requireWebUser(r)
	if !ok || !allowWebRequest(r) {
		if ok {
			webFail(r, 429, "请求过于频繁，请稍后再试")
		}
		return
	}
	if !s.webOriginAllowed(r) {
		webFail(r, http.StatusForbidden, "请求来源不受允许")
		return
	}
	var body struct {
		RequestID string `json:"request_id"`
		Text      string `json:"text"`
		Remember  bool   `json:"remember"`
	}
	if json.NewDecoder(io.LimitReader(r.Body, 16*1024)).Decode(&body) != nil || !validID.MatchString(body.RequestID) || strings.TrimSpace(body.Text) == "" || len([]rune(body.Text)) > 4000 {
		webFail(r, 400, "消息长度或格式无效")
		return
	}
	id, err := s.enqueue(r.Context(), Job{RequestID: body.RequestID, UserID: uid, Text: body.Text, Remember: body.Remember, Channel: "webchat"}, 0)
	if err != nil {
		webFail(r, 400, err.Error())
		return
	}
	r.Response.WriteJson(map[string]any{"ok": true, "result": map[string]any{"id": id}})
}

func (s *Service) webMemories(r *ghttp.Request) {
	uid, ok := s.requireWebUser(r)
	if ok {
		items, err := s.readMemories(r.Context(), uid)
		if err != nil {
			webFail(r, 503, "记忆暂时不可用")
			return
		}
		r.Response.WriteJson(map[string]any{"ok": true, "items": items})
	}
}
func (s *Service) webDeleteMemory(r *ghttp.Request) {
	uid, ok := s.requireWebUser(r)
	if !ok {
		return
	}
	if !s.webOriginAllowed(r) {
		webFail(r, http.StatusForbidden, "请求来源不受允许")
		return
	}
	key := webMemoryKey(r)
	if key != "" && !memoryKeys[key] {
		webFail(r, 400, "invalid memory key")
		return
	}
	if err := s.erase(r.Context(), uid, key); err != nil {
		webFail(r, 503, "删除失败")
		return
	}
	r.Response.WriteJson(map[string]any{"ok": true})
}

func webMemoryKey(r *ghttp.Request) string {
	key := r.GetQuery("key").String()
	if key != "" {
		return key
	}
	path := r.URL.Path
	if path == "/api/wechat/memories" || path == "/wechat/memories" {
		return ""
	}
	key = strings.TrimPrefix(path, "/api/wechat/memories/")
	return strings.TrimPrefix(key, "/wechat/memories/")
}
func (s *Service) webRecommendations(r *ghttp.Request) {
	uid, ok := s.requireWebUser(r)
	if !ok {
		return
	}
	rows, err := s.db.QueryContext(r.Context(), `SELECT result_json FROM chat_jobs WHERE user_id=? AND status='completed' ORDER BY id DESC LIMIT 20`, uid)
	if err != nil {
		webFail(r, 503, "推荐暂时不可用")
		return
	}
	defer rows.Close()
	seen := map[string]bool{}
	out := []Recommendation{}
	for rows.Next() {
		var raw string
		if rows.Scan(&raw) != nil {
			continue
		}
		var result Result
		if json.Unmarshal([]byte(raw), &result) != nil {
			continue
		}
		for _, item := range result.Recommendations {
			if !seen[item.ID] {
				seen[item.ID] = true
				out = append(out, item)
			}
		}
	}
	if len(out) > 20 {
		out = out[:20]
	}
	r.Response.WriteJson(map[string]any{"ok": true, "items": out})
}
