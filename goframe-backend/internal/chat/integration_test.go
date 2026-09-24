package chat

import (
	"bytes"
	"context"
	"crypto/sha1"
	"database/sql"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/gogf/gf/v2/frame/g"
	"knowledge-post-agent/goframe-backend/internal/store"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

// Opt-in: isolated rehearsal only, with synthetic users and exact-row cleanup.
func TestLocalDatabaseWechatAndMemory(t *testing.T) {
	path := os.Getenv("KNOWMATE_CHAT_TEST_DSN_FILE")
	if path == "" {
		t.Skip("requires isolated rehearsal DB")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal("DSN file unavailable")
	}
	dsn := strings.TrimSpace(string(raw))
	db, err := sql.Open("mysql", dsn)
	if err != nil {
		t.Fatal("open DB")
	}
	defer db.Close()
	ctx := context.Background()
	suffix := fmt.Sprintf("%d", time.Now().UnixNano())
	uid := "chat-test-" + suffix
	wx := &WeChat{AppID: "wx-test-" + suffix, token: strings.Repeat("test", 8), key: bytes.Repeat([]byte{5}, 32)}
	wxid := wxUser(wx.AppID, "openid-test")
	defer func() {
		for _, id := range []string{uid, wxid} {
			for _, table := range []string{"chat_memories", "chat_jobs", "wechat_sessions", "chat_users"} {
				if _, e := db.Exec(`DELETE FROM `+table+` WHERE user_id=?`, id); e != nil {
					t.Error("fixture cleanup failed")
				}
			}
		}
	}()
	s := &Service{db: db, store: store.New(dsn), wechat: wx}
	j := Job{RequestID: "first", UserID: uid, Channel: "web", Text: "我喜欢 Go", Remember: true}
	j.ID, err = s.enqueue(ctx, j, 0)
	if err != nil {
		t.Fatal(err)
	}
	duplicate, err := s.enqueue(ctx, j, 0)
	if err != nil || duplicate != j.ID {
		t.Fatal("enqueue not idempotent")
	}
	altered := j
	altered.Text = "another payload"
	if _, err = s.enqueue(ctx, altered, 0); err == nil {
		t.Fatal("accepted idempotency collision")
	}
	result := Result{Reply: "收到", Updates: []Memory{{Key: "interests", Value: "Go", Evidence: "喜欢 Go"}, {Key: "goal", Value: "invented", Evidence: "not in message"}}}
	if err = s.finish(ctx, j, result, 0); err != nil {
		t.Fatal(err)
	}
	memories, err := s.readMemories(ctx, uid)
	if err != nil || len(memories) != 1 || memories[0].Value != "Go" {
		t.Fatal("memory evidence boundary failed")
	}
	other, _ := s.readMemories(ctx, wxid)
	if len(other) != 0 {
		t.Fatal("cross-user memory leak")
	}
	queued := Job{RequestID: "before-forget", UserID: uid, Channel: "web", Text: "开启记忆", Remember: true}
	queued.ID, err = s.enqueue(ctx, queued, 0)
	if err != nil {
		t.Fatal(err)
	}
	if err = s.erase(ctx, uid, ""); err != nil {
		t.Fatal(err)
	}
	if err = s.finish(ctx, j, result, 0); err == nil {
		t.Fatal("inflight reply resurrected forgotten memory")
	}
	s.process(ctx, queued)
	var queuedStatus string
	if err = db.QueryRow(`SELECT status FROM chat_jobs WHERE id=?`, queued.ID).Scan(&queuedStatus); err != nil || queuedStatus != "failed" {
		t.Fatal("pre-forget queued message was processed")
	}
	follow := j
	follow.ID = j.ID + 1
	payload, err := s.context(ctx, follow, 1)
	if err != nil {
		t.Fatal(err)
	}
	if len(payload["history"].([]map[string]string)) != 0 || len(payload["memory"].(map[string]string)) != 0 {
		t.Fatal("forgotten context reused")
	}

	server := g.Server("chat-test-" + suffix)
	server.SetAddr("127.0.0.1:0")
	s.Register(server)
	if err = server.Start(); err != nil {
		t.Fatal(err)
	}
	defer server.Shutdown()
	stamp := fmt.Sprintf("%d", time.Now().Unix())
	plain := fmt.Sprintf("<xml><FromUserName>openid-test</FromUserName><MsgType>text</MsgType><Content>推荐内容</Content><MsgId>123</MsgId><CreateTime>%s</CreateTime></xml>", stamp)
	encoded := encryptFixture(t, wx, plain, wx.AppID)
	parts := []string{wx.token, stamp, "nonce", encoded}
	sort.Strings(parts)
	sum := sha1.Sum([]byte(strings.Join(parts, "")))
	address := fmt.Sprintf("http://127.0.0.1:%d/wechat/callback?timestamp=%s&nonce=nonce&msg_signature=%s", server.GetListenedPort(), stamp, hex.EncodeToString(sum[:]))
	post := func(address string) int {
		resp, e := http.Post(address, "application/xml", strings.NewReader("<xml><Encrypt>"+encoded+"</Encrypt></xml>"))
		if e != nil {
			t.Fatal(e)
		}
		defer resp.Body.Close()
		body, _ := io.ReadAll(resp.Body)
		if resp.StatusCode == 200 && string(body) != "success" {
			t.Fatal("callback did not ACK")
		}
		return resp.StatusCode
	}
	if post(address) != 200 || post(address) != 200 {
		t.Fatal("callback failed")
	}
	var count int
	if err = db.QueryRow(`SELECT COUNT(*) FROM chat_jobs WHERE user_id=?`, wxid).Scan(&count); err != nil || count != 1 {
		t.Fatal("callback duplicate created another turn")
	}
	bad, _ := url.Parse(address)
	query := bad.Query()
	query.Set("msg_signature", "bad")
	bad.RawQuery = query.Encode()
	if post(bad.String()) != 403 {
		t.Fatal("bad signature accepted")
	}
	wxjob, err := scanJob(db.QueryRow(`SELECT `+jobColumns+` FROM chat_jobs WHERE user_id=?`, wxid))
	if err != nil {
		t.Fatal(err)
	}
	if err = s.finish(ctx, wxjob, Result{Reply: "推荐已准备", Recommendations: []Recommendation{{ID: "a1", Title: "文章", URL: "https://example.org/article", Reason: "兴趣匹配"}}}, 0); err != nil {
		t.Fatal(err)
	}
	sends := 0
	wx.client = &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.URL.Host != "api.weixin.qq.com" {
			t.Fatal("unexpected destination")
		}
		body := `{"access_token":"fake-local-token","expires_in":7200}`
		if r.URL.Path == "/cgi-bin/message/custom/send" {
			sends++
			payload, _ := io.ReadAll(r.Body)
			if !strings.Contains(string(payload), "openid-test") || !strings.Contains(string(payload), "https://example.org/article") {
				t.Fatal("wrong recommendation recipient/payload")
			}
			body = `{"errcode":0,"errmsg":"ok"}`
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(body)), Header: make(http.Header)}, nil
	})}
	s.deliver(ctx)
	s.deliver(ctx)
	if sends != 1 {
		t.Fatal("outbox duplicated delivery")
	}
	if post(address) != 200 {
		t.Fatal("retry callback failed")
	}
	var remaining int
	if db.QueryRow(`SELECT remaining FROM wechat_sessions WHERE user_id=?`, wxid).Scan(&remaining) != nil || remaining != 4 {
		t.Fatal("replay replenished quota")
	}
	_, _ = db.Exec(`UPDATE chat_jobs SET delivery='ready' WHERE id=?`, wxjob.ID)
	_, _ = db.Exec(`UPDATE wechat_sessions SET last_message_at=? WHERE user_id=?`, time.Now().Add(-49*time.Hour).Unix(), wxid)
	s.deliver(ctx)
	var delivery string
	_ = db.QueryRow(`SELECT delivery FROM chat_jobs WHERE id=?`, wxjob.ID).Scan(&delivery)
	if delivery != "expired" || sends != 1 {
		t.Fatal("sent outside allowed window")
	}
	t.Log("PASS: persisted idempotency, tenant isolation, forget/inflight protection, encrypted callback, fake recommendation delivery, replay quota, expiry")
}
