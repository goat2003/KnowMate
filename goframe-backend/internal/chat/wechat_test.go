package chat

import (
	"bytes"
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/sha1"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"io"
	"net/http"
	"sort"
	"strings"
	"testing"
	"time"
)

func TestSendRequiresExplicitAcknowledgement(t *testing.T) {
	for _, body := range []string{`{}`, `null`, `{"errcode":null}`, `{"errcode":40001}`, `{"errcode":0}`} {
		w := &WeChat{accessToken: "fake-token", expires: time.Now().Add(time.Hour), client: &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(body)), Header: make(http.Header)}, nil
		})}}
		err := w.send(context.Background(), "fake-user", "test")
		if (err == nil) != (body == `{"errcode":0}`) {
			t.Fatalf("unexpected acknowledgement result for %s: %v", body, err)
		}
	}
}

func encryptFixture(t *testing.T, w *WeChat, payload, appid string) string {
	t.Helper()
	raw := append(bytes.Repeat([]byte{1}, 16), 0, 0, 0, 0)
	binary.BigEndian.PutUint32(raw[16:20], uint32(len(payload)))
	raw = append(raw, []byte(payload+appid)...)
	padding := 32 - len(raw)%32
	raw = append(raw, bytes.Repeat([]byte{byte(padding)}, padding)...)
	block, err := aes.NewCipher(w.key)
	if err != nil {
		t.Fatal(err)
	}
	cipher.NewCBCEncrypter(block, w.key[:16]).CryptBlocks(raw, raw)
	return base64.StdEncoding.EncodeToString(raw)
}
func TestEncryptedMessageRejectsWrongAccountAndMalformedBody(t *testing.T) {
	w := &WeChat{AppID: "wx-app", key: bytes.Repeat([]byte{2}, 32)}
	encoded := encryptFixture(t, w, "<xml>hello</xml>", w.AppID)
	plain, err := w.decrypt(encoded)
	if err != nil || string(plain) != "<xml>hello</xml>" {
		t.Fatalf("%s %v", plain, err)
	}
	if _, err = w.decrypt(encryptFixture(t, w, "hello", "other-app")); err == nil {
		t.Fatal("accepted wrong account")
	}
	for _, bad := range []string{"", "garbage", base64.StdEncoding.EncodeToString([]byte("short"))} {
		if _, err = w.decrypt(bad); err == nil {
			t.Fatal("accepted malformed ciphertext")
		}
	}
}
func TestSignatureAndReplayWindow(t *testing.T) {
	w := &WeChat{token: strings.Repeat("test", 8)}
	stamp := "1789790400"
	now := time.Unix(1789790400, 0)
	parts := []string{w.token, stamp, "nonce", "ciphertext"}
	sort.Strings(parts)
	hash := sha1.Sum([]byte(strings.Join(parts, "")))
	sig := hex.EncodeToString(hash[:])
	if !w.verify(sig, stamp, "nonce", "ciphertext", now) {
		t.Fatal("valid signature rejected")
	}
	if w.verify(sig, stamp, "nonce", "tampered", now) || w.verify(sig, stamp, "nonce", "ciphertext", now.Add(6*time.Minute)) {
		t.Fatal("accepted tamper or stale request")
	}
}
func TestIdentityIsScopedToAccount(t *testing.T) {
	if wxUser("a", "user") == wxUser("b", "user") || wxUser("a", "user") == wxUser("a", "other") {
		t.Fatal("cross-account identity collision")
	}
	if !validID.MatchString(wxUser("a", "user")) {
		t.Fatal("invalid canonical identity")
	}
}
func TestReplyIsSingleBoundedUTF8Message(t *testing.T) {
	r := Result{Reply: strings.Repeat("中文", 2000), Recommendations: []Recommendation{{Title: "article", URL: "https://example.org"}}}
	if len([]byte(formatReply(r))) > 1950 {
		t.Fatal("message exceeds byte budget")
	}
}
