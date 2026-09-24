package chat

import (
	"bytes"
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/sha1"
	"crypto/subtle"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gogf/gf/v2/net/ghttp"
)

type WeChat struct {
	AppID       string
	secret      string
	token       string
	key         []byte
	client      *http.Client
	mu          sync.Mutex
	accessToken string
	expires     time.Time
}
type wxMessage struct {
	To      string `xml:"ToUserName"`
	From    string `xml:"FromUserName"`
	Created int64  `xml:"CreateTime"`
	Type    string `xml:"MsgType"`
	Content string `xml:"Content"`
	ID      string `xml:"MsgId"`
	Event   string `xml:"Event"`
	Encrypt string `xml:"Encrypt"`
}

func secret(name string) string {
	if path := os.Getenv(name + "_FILE"); path != "" {
		b, e := os.ReadFile(path)
		if e == nil {
			return strings.TrimSpace(string(b))
		}
		return ""
	}
	return strings.TrimSpace(os.Getenv(name))
}
func NewWeChatFromEnv() (*WeChat, error) {
	if !strings.EqualFold(os.Getenv("WECHAT_ENABLED"), "true") {
		return nil, nil
	}
	appid := secret("WECHAT_APP_ID")
	appsecret := secret("WECHAT_APP_SECRET")
	token := secret("WECHAT_TOKEN")
	keyText := secret("WECHAT_ENCODING_AES_KEY")
	if appid == "" || appsecret == "" {
		if strings.EqualFold(os.Getenv("WECHAT_DEV_ANONYMOUS"), "true") {
			return nil, nil
		}
		return nil, errors.New("WECHAT_ENABLED requires WECHAT_APP_ID and WECHAT_APP_SECRET")
	}
	// Web OAuth can be enabled independently from the encrypted message callback.
	// In that mode the ordinary-user APIs work while the passive callback remains off.
	if token == "" && keyText == "" {
		return nil, nil
	}
	w := &WeChat{AppID: appid, secret: appsecret, token: token, client: &http.Client{Timeout: 15 * time.Second}}
	w.client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	var err error
	w.key, err = base64.StdEncoding.DecodeString(keyText + "=")
	if err != nil || len(w.key) != 32 || len(w.token) < 16 || w.AppID == "" || w.secret == "" {
		return nil, errors.New("WECHAT_ENABLED requires AppID, AppSecret, Token (16+ characters), and 43-character EncodingAESKey")
	}
	return w, nil
}
func (w *WeChat) verify(signature, timestamp, nonce, encrypted string, now time.Time) bool {
	sec, err := strconv.ParseInt(timestamp, 10, 64)
	if err != nil || sec < now.Unix()-300 || sec > now.Unix()+60 || nonce == "" || len(nonce) > 256 {
		return false
	}
	values := []string{w.token, timestamp, nonce}
	if encrypted != "" {
		values = append(values, encrypted)
	}
	sort.Strings(values)
	sum := sha1.Sum([]byte(strings.Join(values, "")))
	return subtle.ConstantTimeCompare([]byte(signature), []byte(hex.EncodeToString(sum[:]))) == 1
}
func (w *WeChat) decrypt(encoded string) ([]byte, error) {
	data, err := base64.StdEncoding.DecodeString(encoded)
	if err != nil || len(data) == 0 || len(data)%aes.BlockSize != 0 {
		return nil, errors.New("invalid encrypted message")
	}
	block, err := aes.NewCipher(w.key)
	if err != nil {
		return nil, err
	}
	cipher.NewCBCDecrypter(block, w.key[:aes.BlockSize]).CryptBlocks(data, data)
	pad := int(data[len(data)-1])
	if pad < 1 || pad > 32 || pad > len(data) {
		return nil, errors.New("invalid padding")
	}
	for _, v := range data[len(data)-pad:] {
		if int(v) != pad {
			return nil, errors.New("invalid padding")
		}
	}
	data = data[:len(data)-pad]
	if len(data) < 20 {
		return nil, errors.New("invalid message length")
	}
	n := uint64(binary.BigEndian.Uint32(data[16:20]))
	if n > uint64(len(data)-20) {
		return nil, errors.New("invalid message length")
	}
	if string(data[20+n:]) != w.AppID {
		return nil, errors.New("wrong receiver appid")
	}
	return data[20 : 20+n], nil
}
func (s *Service) wxStatus(r *ghttp.Request) {
	r.Response.WriteJson(map[string]any{"ok": true, "result": map[string]any{"enabled": s.cfg.WeChat.Enabled || s.wechat != nil, "callback_path": "/wechat/callback", "mode": "安全模式", "reply_window_hours": 48, "max_messages_per_interaction": 5}})
}
func (s *Service) callback(r *ghttp.Request) {
	if r.GetQuery("code").String() != "" || r.GetQuery("state").String() != "" {
		s.webCallback(r)
		return
	}
	if s.wechat == nil {
		fail(r, 404, "WeChat is disabled")
		return
	}
	w := s.wechat
	stamp := r.GetQuery("timestamp").String()
	nonce := r.GetQuery("nonce").String()
	if r.Method == http.MethodGet {
		echo := r.GetQuery("echostr").String()
		if len(echo) > 8192 {
			fail(r, 400, "invalid challenge")
			return
		}
		if r.GetQuery("encrypt_type").String() == "aes" {
			if !w.verify(r.GetQuery("msg_signature").String(), stamp, nonce, echo, time.Now()) {
				fail(r, 403, "invalid signature")
				return
			}
			plain, err := w.decrypt(echo)
			if err != nil {
				fail(r, 403, "invalid challenge")
				return
			}
			r.Response.Write(string(plain))
			return
		}
		if !w.verify(r.GetQuery("signature").String(), stamp, nonce, "", time.Now()) {
			fail(r, 403, "invalid signature")
			return
		}
		r.Response.Write(echo)
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, 65537))
	if err != nil || len(body) > 65536 {
		fail(r, 400, "invalid message size")
		return
	}
	var envelope wxMessage
	if xml.Unmarshal(body, &envelope) != nil || envelope.Encrypt == "" {
		fail(r, 400, "安全模式 required")
		return
	}
	if !w.verify(r.GetQuery("msg_signature").String(), stamp, nonce, envelope.Encrypt, time.Now()) {
		fail(r, 403, "invalid signature")
		return
	}
	plain, err := w.decrypt(envelope.Encrypt)
	if err != nil {
		fail(r, 403, "invalid encrypted message")
		return
	}
	var msg wxMessage
	if xml.Unmarshal(plain, &msg) != nil || !validID.MatchString(msg.From) {
		fail(r, 400, "invalid message")
		return
	}
	uid := wxUser(w.AppID, msg.From)
	if msg.Type == "event" && msg.Event == "unsubscribe" {
		if _, err = s.db.ExecContext(r.Context(), `UPDATE wechat_sessions SET remaining=0 WHERE user_id=?`, uid); err != nil {
			fail(r, 503, "try again")
			return
		}
	}
	if msg.Type != "text" {
		r.Response.Write("success")
		return
	}
	if !validID.MatchString(msg.ID) || msg.Created > time.Now().Unix()+60 || msg.Created < time.Now().Unix()-300 {
		fail(r, 400, "invalid message metadata")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()
	_, err = s.enqueue(ctx, Job{RequestID: "wx:" + msg.ID, UserID: uid, Channel: "wechat", Recipient: msg.From, Text: msg.Content}, msg.Created)
	if err != nil {
		fail(r, 503, "try again")
		return
	}
	r.Response.Write("success")
}

type apiError struct{ Code int }

func (e *apiError) Error() string { return fmt.Sprintf("WeChat API rejected request: %d", e.Code) }
func (w *WeChat) post(ctx context.Context, path string, body any, target any) error {
	raw, err := json.Marshal(body)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, "https://api.weixin.qq.com"+path, bytes.NewReader(raw))
	if err != nil {
		return errors.New("invalid WeChat request")
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := w.client.Do(req)
	if err != nil {
		return errors.New("WeChat transport failed; delivery may be uncertain")
	}
	defer resp.Body.Close()
	raw, err = io.ReadAll(io.LimitReader(resp.Body, 1024*1024))
	if err != nil {
		return errors.New("WeChat response unreadable")
	}
	if resp.StatusCode != 200 {
		return errors.New("WeChat response status was not OK")
	}
	var status struct {
		Code int `json:"errcode"`
	}
	if json.Unmarshal(raw, &status) != nil {
		return errors.New("invalid WeChat response")
	}
	if status.Code != 0 {
		return &apiError{Code: status.Code}
	}
	return json.Unmarshal(raw, target)
}
func (w *WeChat) access(ctx context.Context) (string, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if time.Now().Before(w.expires) {
		return w.accessToken, nil
	}
	var result struct {
		Token   string `json:"access_token"`
		Expires int    `json:"expires_in"`
	}
	if err := w.post(ctx, "/cgi-bin/stable_token", map[string]any{"grant_type": "client_credential", "appid": w.AppID, "secret": w.secret}, &result); err != nil {
		return "", err
	}
	if result.Token == "" || result.Expires <= 0 {
		return "", errors.New("WeChat token missing")
	}
	w.accessToken = result.Token
	w.expires = time.Now().Add(time.Duration(result.Expires-60) * time.Second)
	return result.Token, nil
}
func (w *WeChat) send(ctx context.Context, recipient, text string) error {
	token, err := w.access(ctx)
	if err != nil {
		return err
	}
	var response map[string]any
	if err := w.post(ctx, "/cgi-bin/message/custom/send?access_token="+token, map[string]any{"touser": recipient, "msgtype": "text", "text": map[string]string{"content": text}}, &response); err != nil {
		return err
	}
	if code, ok := response["errcode"].(float64); !ok || code != 0 {
		return errors.New("WeChat delivery was not explicitly acknowledged")
	}
	return nil
}
func (s *Service) deliver(ctx context.Context) {
	j, err := scanJob(s.db.QueryRowContext(ctx, `SELECT `+jobColumns+` FROM chat_jobs WHERE channel='wechat' AND delivery='ready' ORDER BY id LIMIT 1`))
	if err != nil {
		return
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return
	}
	defer tx.Rollback()
	var when int64
	var remaining int
	err = tx.QueryRowContext(ctx, `SELECT last_message_at,remaining FROM wechat_sessions WHERE user_id=? FOR UPDATE`, j.UserID).Scan(&when, &remaining)
	if err != nil {
		return
	}
	if time.Now().Unix()-when >= 48*3600 || remaining <= 0 {
		_, err = tx.ExecContext(ctx, `UPDATE chat_jobs SET delivery='expired' WHERE id=?`, j.ID)
		if err == nil {
			_ = tx.Commit()
		}
		return
	}
	claim, err := tx.ExecContext(ctx, `UPDATE chat_jobs SET delivery='sending' WHERE id=? AND delivery='ready'`, j.ID)
	if err != nil {
		return
	}
	n, _ := claim.RowsAffected()
	if n != 1 {
		return
	}
	if _, err = tx.ExecContext(ctx, `UPDATE wechat_sessions SET remaining=remaining-1 WHERE user_id=?`, j.UserID); err != nil {
		return
	}
	if tx.Commit() != nil {
		return
	}
	if j.Result == nil {
		return
	}
	err = s.wechat.send(ctx, j.Recipient, formatReply(*j.Result))
	state := "sent"
	deliveryError := ""
	if err != nil {
		state = "uncertain"
		deliveryError = "WeChat delivery uncertain; inspect connection before retrying"
		var rejected *apiError
		if errors.As(err, &rejected) {
			state = "rejected"
			deliveryError = rejected.Error()
		}
	}
	// Never blindly resend after timeout/crash: WeChat has no idempotency key on custom/send.
	save, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_, _ = s.db.ExecContext(save, `UPDATE chat_jobs SET delivery=?,error_message=IF(?='',error_message,?) WHERE id=?`, state, deliveryError, deliveryError, j.ID)
}
