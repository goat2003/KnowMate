package chat

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"knowledge-post-agent/goframe-backend/internal/config"
)

// MemoryProvider is the only boundary between KnowMate and Mem_Pro. The
// browser never supplies role_id; it is derived from the authenticated user.
type MemoryProvider interface {
	RoleID(userID string) string
	Retrieve(ctx context.Context, userID, query string) (map[string]any, error)
	Build(ctx context.Context, userID string, dialogues []map[string]string) error
	List(ctx context.Context, userID string) ([]Memory, error)
	Delete(ctx context.Context, userID, key string) error
	Health(ctx context.Context) (map[string]any, error)
}

type memoryHTTPProvider struct {
	baseURL     string
	token       string
	secret      []byte
	client      *http.Client
	buildClient *http.Client
}

type memoryEnvelope struct {
	RoleID    string              `json:"role_id"`
	Query     string              `json:"query,omitempty"`
	Dialogues []map[string]string `json:"dialogues,omitempty"`
	Key       string              `json:"key,omitempty"`
}

func newMemoryProvider(cfg config.MemoryConfig) MemoryProvider {
	if strings.TrimSpace(cfg.URL) == "" || len([]byte(strings.TrimSpace(cfg.RoleSecret))) < 32 {
		return nil
	}
	buildTimeout := cfg.BuildTimeoutSeconds
	if buildTimeout <= 0 {
		buildTimeout = 180
	}
	return &memoryHTTPProvider{
		baseURL:     strings.TrimRight(cfg.URL, "/"),
		token:       strings.TrimSpace(cfg.Token),
		secret:      []byte(cfg.RoleSecret),
		client:      &http.Client{Timeout: time.Duration(cfg.TimeoutSeconds) * time.Second},
		buildClient: &http.Client{Timeout: time.Duration(buildTimeout) * time.Second},
	}
}

func (p *memoryHTTPProvider) RoleID(userID string) string {
	mac := hmac.New(sha256.New, p.secret)
	_, _ = mac.Write([]byte(userID))
	return "km_" + hex.EncodeToString(mac.Sum(nil)[:20])
}

func (p *memoryHTTPProvider) call(ctx context.Context, method, path string, body any, out any) error {
	return p.callWithClient(ctx, p.client, method, path, body, out)
}

func (p *memoryHTTPProvider) callWithClient(ctx context.Context, client *http.Client, method, path string, body any, out any) error {
	var reader io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reader = bytes.NewReader(raw)
	}
	req, err := http.NewRequestWithContext(ctx, method, p.baseURL+path, reader)
	if err != nil {
		return err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if p.token != "" {
		req.Header.Set("Authorization", "Bearer "+p.token)
	}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 2<<20))
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("memory provider returned %d", resp.StatusCode)
	}
	if out != nil && len(raw) > 0 && json.Unmarshal(raw, out) != nil {
		return errors.New("invalid memory provider response")
	}
	return nil
}

func (p *memoryHTTPProvider) Retrieve(ctx context.Context, userID, query string) (map[string]any, error) {
	var out map[string]any
	err := p.call(ctx, http.MethodPost, "/memory/retrieve", memoryEnvelope{RoleID: p.RoleID(userID), Query: query}, &out)
	return out, err
}

func (p *memoryHTTPProvider) Build(ctx context.Context, userID string, dialogues []map[string]string) error {
	return p.callWithClient(ctx, p.buildClient, http.MethodPost, "/memory/build", memoryEnvelope{RoleID: p.RoleID(userID), Dialogues: dialogues}, nil)
}

func (p *memoryHTTPProvider) List(ctx context.Context, userID string) ([]Memory, error) {
	var out struct {
		Items []Memory `json:"items"`
	}
	err := p.call(ctx, http.MethodPost, "/memory/list", memoryEnvelope{RoleID: p.RoleID(userID)}, &out)
	return out.Items, err
}

func (p *memoryHTTPProvider) Delete(ctx context.Context, userID, key string) error {
	return p.call(ctx, http.MethodPost, "/memory/delete", memoryEnvelope{RoleID: p.RoleID(userID), Key: key}, nil)
}

func (p *memoryHTTPProvider) Health(ctx context.Context) (map[string]any, error) {
	var out map[string]any
	err := p.call(ctx, http.MethodGet, "/health", nil, &out)
	return out, err
}
