// Package chat owns durable, single-worker conversations shared by admin web and WeChat.
package chat

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/gogf/gf/v2/net/ghttp"
	"knowledge-post-agent/goframe-backend/internal/agentpb"
	"knowledge-post-agent/goframe-backend/internal/config"
	"knowledge-post-agent/goframe-backend/internal/grpcclient"
	"knowledge-post-agent/goframe-backend/internal/model"
	"knowledge-post-agent/goframe-backend/internal/store"
)

var validID = regexp.MustCompile(`^[A-Za-z0-9_:.\-]{1,128}$`)
var memoryKeys = map[string]bool{"interests": true, "goal": true, "avoid": true, "style": true, "level": true}

type Memory struct {
	Key      string `json:"key"`
	Value    string `json:"value"`
	Evidence string `json:"evidence"`
	Source   int64  `json:"source_job_id"`
}
type Recommendation struct {
	ID          string  `json:"id"`
	Title       string  `json:"title"`
	Summary     string  `json:"summary"`
	URL         string  `json:"url"`
	Reason      string  `json:"reason"`
	PublishedAt string  `json:"published_at"`
	Score       float64 `json:"score"`
}
type Result struct {
	Reply           string           `json:"reply"`
	Updates         []Memory         `json:"memory_updates"`
	Recommendations []Recommendation `json:"recommendations"`
	Mock            bool             `json:"mock"`
	MemoryStatus    string           `json:"memory_status,omitempty"`
}
type Job struct {
	ID        int64   `json:"id"`
	RequestID string  `json:"request_id"`
	UserID    string  `json:"user_id"`
	Channel   string  `json:"channel"`
	Recipient string  `json:"-"`
	Text      string  `json:"text"`
	Remember  bool    `json:"remember"`
	Status    string  `json:"status"`
	Result    *Result `json:"result"`
	Error     string  `json:"error"`
	Delivery  string  `json:"delivery"`
}
type Service struct {
	db     *sql.DB
	store  *store.Store
	cfg    config.Config
	wechat *WeChat
	memory MemoryProvider
}

func New(cfg config.Config, data *store.Store) (*Service, error) {
	if cfg.WeChat.Enabled && !cfg.WeChat.DevAnonymous && (cfg.WeChat.AppID == "" || cfg.WeChat.AppSecret == "" || cfg.WeChat.OAuthRedirect == "" || len(cfg.WeChat.SessionSecret) < 32) {
		return nil, errors.New("enabled WeChat web OAuth requires AppID, AppSecret, redirect URI, and a 32+ character session secret")
	}
	db, err := sql.Open("mysql", cfg.MySQL.DSN)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(8)
	wx, err := NewWeChatFromEnv()
	if err != nil {
		db.Close()
		return nil, err
	}
	return &Service{db: db, store: data, cfg: cfg, wechat: wx, memory: newMemoryProvider(cfg.Memory)}, nil
}

func (s *Service) Start(ctx context.Context) error {
	// One backend instance is the documented deployment boundary.
	if _, err := s.db.ExecContext(ctx, `UPDATE chat_jobs SET status='pending' WHERE status='processing'`); err != nil {
		return err
	}
	if _, err := s.db.ExecContext(ctx, `UPDATE chat_jobs SET delivery='uncertain' WHERE delivery='sending'`); err != nil {
		return err
	}
	go func() {
		tick := time.NewTicker(time.Second)
		defer tick.Stop()
		defer s.db.Close()
		for {
			select {
			case <-ctx.Done():
				return
			case <-tick.C:
				work, cancel := context.WithTimeout(ctx, 150*time.Second)
				s.work(work)
				cancel()
			}
		}
	}()
	return nil
}

func (s *Service) Register(server *ghttp.Server) {
	server.BindHandler("GET:/chat/messages", s.messages)
	server.BindHandler("POST:/chat/messages", s.send)
	server.BindHandler("GET:/chat/memories", s.memories)
	server.BindHandler("DELETE:/chat/memories", s.forget)
	server.BindHandler("GET:/chat/users", s.users)
	server.BindHandler("GET:/wechat/status", s.wxStatus)
	server.BindHandler("GET:/memory/health", s.memoryHealth)
	server.BindHandler("GET:/wechat/callback", s.callback)
	server.BindHandler("POST:/wechat/callback", s.callback)
	server.BindHandler("GET:/api/wechat/auth", s.webAuth)
	server.BindHandler("GET:/api/wechat/callback", s.webCallback)
	server.BindHandler("GET:/api/wechat/me", s.webMe)
	server.BindHandler("GET:/api/wechat/conversations", s.webConversations)
	server.BindHandler("POST:/api/wechat/messages", s.webMessages)
	server.BindHandler("GET:/api/wechat/memories", s.webMemories)
	server.BindHandler("DELETE:/api/wechat/memories", s.webDeleteMemory)
	server.BindHandler("DELETE:/api/wechat/memories/{key}", s.webDeleteMemory)
	server.BindHandler("GET:/api/wechat/recommendations", s.webRecommendations)
	server.BindHandler("GET:/wechat/auth", s.webAuth)
	server.BindHandler("GET:/wechat/me", s.webMe)
	server.BindHandler("GET:/wechat/conversations", s.webConversations)
	server.BindHandler("POST:/wechat/messages", s.webMessages)
	server.BindHandler("GET:/wechat/memories", s.webMemories)
	server.BindHandler("DELETE:/wechat/memories", s.webDeleteMemory)
	server.BindHandler("DELETE:/wechat/memories/{key}", s.webDeleteMemory)
	server.BindHandler("GET:/wechat/recommendations", s.webRecommendations)
}

func fail(r *ghttp.Request, status int, message string) {
	r.Response.WriteStatus(status, map[string]any{"ok": false, "error": message})
}
func user(r *ghttp.Request) string {
	v := r.GetQuery("user_id").String()
	if v == "" {
		v = "default-user"
	}
	return v
}

func (s *Service) enqueue(ctx context.Context, j Job, wxTimestamp int64) (int64, error) {
	if !validID.MatchString(j.UserID) || !validID.MatchString(j.RequestID) || strings.TrimSpace(j.Text) == "" || len([]rune(j.Text)) > 4000 {
		return 0, errors.New("invalid message")
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()
	if _, err = tx.ExecContext(ctx, `INSERT IGNORE INTO chat_users(user_id) VALUES (?)`, j.UserID); err != nil {
		return 0, err
	}
	// Lock the user before de-duplication and quota updates.
	var id string
	var epoch int64
	if err = tx.QueryRowContext(ctx, `SELECT user_id,memory_epoch FROM chat_users WHERE user_id=? FOR UPDATE`, j.UserID).Scan(&id, &epoch); err != nil {
		return 0, err
	}
	var oldID int64
	var oldText string
	err = tx.QueryRowContext(ctx, `SELECT id,text FROM chat_jobs WHERE user_id=? AND request_id=?`, j.UserID, j.RequestID).Scan(&oldID, &oldText)
	if err == nil {
		if oldText != j.Text {
			return 0, errors.New("request ID was already used for another message")
		}
		return oldID, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return 0, err
	}
	var queued int
	if err = tx.QueryRowContext(ctx, `SELECT COUNT(*) FROM chat_jobs WHERE status IN ('pending','processing') AND user_id=?`, j.UserID).Scan(&queued); err != nil {
		return 0, err
	}
	if queued >= 10 {
		return 0, errors.New("too many pending messages")
	}
	var total int
	if err = tx.QueryRowContext(ctx, `SELECT COUNT(*) FROM chat_jobs WHERE status IN ('pending','processing')`).Scan(&total); err != nil {
		return 0, err
	}
	if total >= 200 {
		return 0, errors.New("chat queue is full")
	}
	result, err := tx.ExecContext(ctx, `INSERT INTO chat_jobs(request_id,user_id,channel,recipient,text,remember,memory_epoch) VALUES(?,?,?,?,?,?,?)`, j.RequestID, j.UserID, j.Channel, j.Recipient, j.Text, j.Remember, epoch)
	if err != nil {
		return 0, err
	}
	if j.Channel == "wechat" {
		_, err = tx.ExecContext(ctx, `INSERT INTO wechat_sessions(user_id,last_message_at,remaining) VALUES(?,?,5) ON DUPLICATE KEY UPDATE remaining=IF(VALUES(last_message_at)>last_message_at,5,remaining),last_message_at=GREATEST(last_message_at,VALUES(last_message_at))`, j.UserID, wxTimestamp)
		if err != nil {
			return 0, err
		}
	}
	jobID, _ := result.LastInsertId()
	return jobID, tx.Commit()
}

const jobColumns = `id,request_id,user_id,channel,recipient,text,remember,status,COALESCE(CAST(result_json AS CHAR),'null'),error_message,delivery`

func scanJob(row interface{ Scan(...any) error }) (Job, error) {
	var j Job
	var raw string
	err := row.Scan(&j.ID, &j.RequestID, &j.UserID, &j.Channel, &j.Recipient, &j.Text, &j.Remember, &j.Status, &raw, &j.Error, &j.Delivery)
	if err == nil {
		err = json.Unmarshal([]byte(raw), &j.Result)
	}
	return j, err
}
func (s *Service) send(r *ghttp.Request) {
	var body struct {
		UserID    string `json:"user_id"`
		RequestID string `json:"request_id"`
		Text      string `json:"text"`
		Remember  bool   `json:"remember"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		fail(r, 400, "消息格式不正确")
		return
	}
	if body.UserID == "" {
		body.UserID = "default-user"
	}
	id, err := s.enqueue(r.Context(), Job{RequestID: body.RequestID, UserID: body.UserID, Text: body.Text, Remember: body.Remember, Channel: "web"}, 0)
	if err != nil {
		fail(r, 400, err.Error())
		return
	}
	r.Response.WriteJson(map[string]any{"ok": true, "result": map[string]any{"id": id}})
}
func (s *Service) messages(r *ghttp.Request) {
	uid := user(r)
	if !validID.MatchString(uid) {
		fail(r, 400, "invalid user")
		return
	}
	rows, err := s.db.QueryContext(r.Context(), `SELECT `+jobColumns+` FROM chat_jobs WHERE user_id=? ORDER BY id DESC LIMIT 60`, uid)
	if err != nil {
		fail(r, 503, "会话暂时不可用")
		return
	}
	defer rows.Close()
	jobs := []Job{}
	for rows.Next() {
		j, e := scanJob(rows)
		if e != nil {
			fail(r, 500, "读取会话失败")
			return
		}
		jobs = append(jobs, j)
	}
	if rows.Err() != nil {
		fail(r, 503, "读取会话失败")
		return
	}
	for i, k := 0, len(jobs)-1; i < k; i, k = i+1, k-1 {
		jobs[i], jobs[k] = jobs[k], jobs[i]
	}
	r.Response.WriteJson(map[string]any{"ok": true, "items": jobs})
}
func (s *Service) readMemories(ctx context.Context, uid string) ([]Memory, error) {
	if s.memory != nil {
		items, err := s.memory.List(ctx, uid)
		if err == nil {
			return items, nil
		}
		// Mem_Pro is the long-term source of truth. Do not silently expose a
		// stale local copy when it is configured but unavailable.
		return nil, err
	}
	rows, err := s.db.QueryContext(ctx, `SELECT memory_key,value,evidence,source_job_id FROM chat_memories WHERE user_id=? ORDER BY memory_key`, uid)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []Memory{}
	for rows.Next() {
		var m Memory
		if err = rows.Scan(&m.Key, &m.Value, &m.Evidence, &m.Source); err != nil {
			return nil, err
		}
		result = append(result, m)
	}
	return result, rows.Err()
}
func (s *Service) memories(r *ghttp.Request) {
	items, err := s.readMemories(r.Context(), user(r))
	if err != nil {
		fail(r, 503, "记忆暂时不可用")
		return
	}
	r.Response.WriteJson(map[string]any{"ok": true, "items": items})
}
func (s *Service) erase(ctx context.Context, uid, key string) error {
	if s.memory != nil {
		if err := s.memory.Delete(ctx, uid, key); err != nil {
			return err
		}
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err = tx.ExecContext(ctx, `UPDATE chat_users SET memory_epoch=memory_epoch+1 WHERE user_id=?`, uid); err != nil {
		return err
	}
	if key == "" {
		_, err = tx.ExecContext(ctx, `DELETE FROM chat_memories WHERE user_id=?`, uid)
	} else {
		_, err = tx.ExecContext(ctx, `DELETE FROM chat_memories WHERE user_id=? AND memory_key=?`, uid, key)
	}
	if err != nil {
		return err
	}
	// Old conversation remains visible for audit, but is excluded from model context after forget.
	if _, err = tx.ExecContext(ctx, `UPDATE chat_jobs SET remember=FALSE WHERE user_id=?`, uid); err != nil {
		return err
	}
	return tx.Commit()
}
func (s *Service) forget(r *ghttp.Request) {
	key := r.GetQuery("key").String()
	if key != "" && !memoryKeys[key] {
		fail(r, 400, "invalid memory key")
		return
	}
	if err := s.erase(r.Context(), user(r), key); err != nil {
		fail(r, 503, "删除失败")
		return
	}
	r.Response.WriteJson(map[string]any{"ok": true})
}
func (s *Service) users(r *ghttp.Request) {
	rows, err := s.db.QueryContext(r.Context(), `SELECT user_id FROM chat_users ORDER BY created_at DESC LIMIT 100`)
	if err != nil {
		fail(r, 503, "用户列表不可用")
		return
	}
	defer rows.Close()
	items := []string{}
	for rows.Next() {
		var id string
		if rows.Scan(&id) != nil {
			fail(r, 500, "读取失败")
			return
		}
		items = append(items, id)
	}
	r.Response.WriteJson(map[string]any{"ok": true, "items": items})
}

func (s *Service) work(ctx context.Context) {
	j, err := scanJob(s.db.QueryRowContext(ctx, `SELECT `+jobColumns+` FROM chat_jobs WHERE status='pending' ORDER BY id LIMIT 1`))
	if err == nil {
		claimed, e := s.db.ExecContext(ctx, `UPDATE chat_jobs SET status='processing' WHERE id=? AND status='pending'`, j.ID)
		if e == nil {
			n, _ := claimed.RowsAffected()
			if n == 1 {
				s.process(ctx, j)
			}
		}
	}
	if s.wechat != nil {
		s.deliver(ctx)
	}
}
func (s *Service) process(ctx context.Context, j Job) {
	var result Result
	var err error
	var epoch int64
	var optin bool
	err = s.db.QueryRowContext(ctx, `SELECT memory_epoch,remember FROM chat_users WHERE user_id=?`, j.UserID).Scan(&epoch, &optin)
	if err != nil {
		s.failed(j.ID, "读取记忆失败")
		return
	}
	var queuedEpoch int64
	if err = s.db.QueryRowContext(ctx, `SELECT memory_epoch FROM chat_jobs WHERE id=?`, j.ID).Scan(&queuedEpoch); err != nil || queuedEpoch != epoch {
		s.failed(j.ID, "记忆已清除，旧的排队消息已取消，请重新发送。")
		return
	}
	if j.Channel == "wechat" {
		j.Remember = optin || strings.HasPrefix(j.Text, "记住")
	}
	if strings.Contains(j.Text, "不要记住") || strings.Contains(j.Text, "别记住") || strings.Contains(j.Text, "不要保存") {
		j.Remember = false
	}
	switch strings.TrimSpace(j.Text) {
	case "开启记忆", "关闭记忆":
		enabled := strings.TrimSpace(j.Text) == "开启记忆"
		_, err = s.db.ExecContext(ctx, `UPDATE chat_users SET remember=? WHERE user_id=?`, enabled, j.UserID)
		result.Reply = "已关闭微信自动记忆；已有记忆仍保留，可发送“忘记全部记忆”清除。"
		if enabled {
			result.Reply = "已开启微信偏好记忆。以后明确表达的学习目标和内容偏好会被记住，可发送“关闭记忆”停止，或“忘记全部记忆”清除。"
		}
	case "忘记全部记忆":
		err = s.erase(ctx, j.UserID, "")
		epoch++
		result.Reply = "已清除聊天偏好记忆。旧对话保留在历史记录中，但不再作为模型上下文。"
	default:
		var payload map[string]any
		payload, err = s.context(ctx, j, epoch)
		if err == nil {
			raw, _ := json.Marshal(payload)
			var client *grpcclient.Client
			client, err = grpcclient.NewWithAuth(ctx, s.cfg.Agent.Address, 5*time.Second, s.cfg.Agent.AuthToken)
			if err == nil {
				defer client.Close()
				var response *agentpb.ChatResponse
				response, err = client.Chat(ctx, &agentpb.ChatRequest{RequestId: j.RequestID, UserId: j.UserID, Text: j.Text, ContextJson: string(raw), Remember: j.Remember})
				if err == nil {
					err = json.Unmarshal([]byte(response.ResultJson), &result)
				}
			}
		}
	}
	if err != nil {
		s.failed(j.ID, "助手暂时无法回复，请稍后重新发送。")
		return
	}
	if err = s.finish(ctx, j, result, epoch); err != nil {
		s.failed(j.ID, "记忆或会话已变化，请重新发送。")
		return
	}
	// Long-term memory is written only after the chat result is durable. A
	// provider outage must not turn a usable answer into a failed chat job.
	if s.memory == nil {
		result.MemoryStatus = "disabled"
	} else if j.Remember && strings.TrimSpace(result.Reply) != "" {
		result.MemoryStatus = "pending"
		dialogues := []map[string]string{{"user": j.Text, "assistant": result.Reply}}
		// Convert only server-validated model updates into the provider's
		// dialogue contract; assistant text is never treated as memory evidence.
		for _, m := range result.Updates {
			if !memoryKeys[m.Key] || m.Value == "" || len([]rune(m.Value)) > 500 || len([]rune(m.Evidence)) < 2 || len([]rune(m.Evidence)) > 500 || !strings.Contains(j.Text, m.Evidence) {
				continue
			}
			label := map[string]string{"interests": "兴趣", "goal": "目标", "avoid": "避开", "style": "风格", "level": "水平"}[m.Key]
			dialogues = append(dialogues, map[string]string{"user": "记住" + label + "：" + m.Value, "assistant": ""})
		}
		if raw, err := json.Marshal(result); err == nil {
			_, _ = s.db.ExecContext(ctx, `UPDATE chat_jobs SET result_json=? WHERE id=? AND status='completed'`, string(raw), j.ID)
		}
		result.MemoryStatus = "saved"
		if err := s.memory.Build(ctx, j.UserID, dialogues); err != nil {
			result.MemoryStatus = "unavailable"
		}
		updateCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if raw, err := json.Marshal(result); err == nil {
			_, _ = s.db.ExecContext(updateCtx, `UPDATE chat_jobs SET result_json=? WHERE id=? AND status='completed'`, string(raw), j.ID)
		}
	}
}

func (s *Service) failed(id int64, message string) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	// WeChat users also receive an explicit failure, rather than silently waiting forever.
	result, _ := json.Marshal(Result{Reply: message})
	_, _ = s.db.ExecContext(ctx, `UPDATE chat_jobs SET status='failed',error_message=?,result_json=?,delivery=IF(channel='wechat','ready','none') WHERE id=?`, message, string(result), id)
}
func (s *Service) context(ctx context.Context, j Job, epoch int64) (map[string]any, error) {
	memory := map[string]string{}
	retrievalContext := []string{}
	if s.memory != nil {
		// Retrieval failures degrade to the local conversation context so the
		// assistant remains available while memory status is reported separately.
		if result, e := s.memory.Retrieve(ctx, j.UserID, j.Text); e == nil {
			if raw, ok := result["memory"].(map[string]any); ok {
				for k, v := range raw {
					if memoryKeys[k] {
						memory[k] = fmt.Sprint(v)
					}
				}
			}
			if raw, ok := result["items"].([]any); ok {
				for _, item := range raw {
					if entry, ok := item.(map[string]any); ok {
						k, _ := entry["key"].(string)
						v, _ := entry["value"].(string)
						if memoryKeys[k] && v != "" {
							memory[k] = v
						}
					}
				}
			}
			if raw, ok := result["retrieval"].(map[string]any); ok {
				if prompt, ok := raw["prompt_context"].(string); ok && strings.TrimSpace(prompt) != "" {
					retrievalContext = append(retrievalContext, truncateRunes(strings.TrimSpace(prompt), 6000))
				}
				if items, ok := raw["items"].([]any); ok {
					for _, item := range items {
						entry, ok := item.(map[string]any)
						if !ok {
							continue
						}
						content, _ := entry["content"].(string)
						content = strings.TrimSpace(content)
						if content != "" {
							retrievalContext = append(retrievalContext, truncateRunes(content, 1200))
						}
						if len(retrievalContext) >= 12 {
							break
						}
					}
				}
			}
		}
	} else if memories, e := s.readMemories(ctx, j.UserID); e == nil {
		for _, m := range memories {
			memory[m.Key] = m.Value
		}
	} else {
		return nil, e
	}
	// Once any forget action occurred, exclude older dialogue. New memories remain available.
	history := []map[string]string{}
	{
		rows, e := s.db.QueryContext(ctx, `SELECT text,CAST(result_json AS CHAR) FROM chat_jobs WHERE user_id=? AND id<? AND memory_epoch=? AND status='completed' ORDER BY id DESC LIMIT 6`, j.UserID, j.ID, epoch)
		if e != nil {
			return nil, e
		}
		for rows.Next() {
			var text, raw string
			if e = rows.Scan(&text, &raw); e != nil {
				rows.Close()
				return nil, e
			}
			var r Result
			_ = json.Unmarshal([]byte(raw), &r)
			history = append(history, map[string]string{"user": text, "assistant": r.Reply})
		}
		e = rows.Err()
		rows.Close()
		if e != nil {
			return nil, e
		}
		for i, k := 0, len(history)-1; i < k; i, k = i+1, k-1 {
			history[i], history[k] = history[k], history[i]
		}
	}
	profile, e := s.store.LatestUserProfileSnapshot(ctx, j.UserID)
	if e != nil {
		return nil, e
	}
	articles, e := s.store.ListArticles(ctx, model.ArticleFilter{Limit: 60})
	if e != nil {
		return nil, e
	}
	candidates := []map[string]any{}
	for _, a := range articles {
		content := []rune(a.Content)
		if len(content) > 1800 {
			content = content[:1800]
		}
		candidates = append(candidates, map[string]any{"article_id": a.ID, "title": a.Title, "url": a.URL, "source": a.Source, "tags": a.Tags, "raw_text": string(content), "published_at": a.PublishedAt})
	}
	return map[string]any{"memory": memory, "retrieval_context": retrievalContext, "profile": profile, "history": history, "articles": candidates}, nil
}

func truncateRunes(value string, limit int) string {
	if limit <= 0 {
		return ""
	}
	runes := []rune(value)
	if len(runes) < limit {
		return value
	}
	return string(runes[:limit])
}
func (s *Service) finish(ctx context.Context, j Job, r Result, epoch int64) error {
	if strings.TrimSpace(r.Reply) == "" || len([]rune(r.Reply)) > 3000 {
		return errors.New("invalid agent reply")
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var current int64
	if err = tx.QueryRowContext(ctx, `SELECT memory_epoch FROM chat_users WHERE user_id=? FOR UPDATE`, j.UserID).Scan(&current); err != nil {
		return err
	}
	if current != epoch {
		return errors.New("memory changed during generation")
	}
	updates := []Memory{}
	for _, m := range r.Updates {
		if !j.Remember || !memoryKeys[m.Key] || m.Value == "" || len([]rune(m.Value)) > 500 || len([]rune(m.Evidence)) < 2 || len([]rune(m.Evidence)) > 500 || !strings.Contains(j.Text, m.Evidence) {
			continue
		}
		m.Source = j.ID
		if s.memory == nil {
			_, err = tx.ExecContext(ctx, `INSERT INTO chat_memories(user_id,memory_key,value,evidence,source_job_id) VALUES(?,?,?,?,?) ON DUPLICATE KEY UPDATE value=VALUES(value),evidence=VALUES(evidence),source_job_id=VALUES(source_job_id)`, j.UserID, m.Key, m.Value, m.Evidence, j.ID)
			if err != nil {
				return err
			}
		}
		updates = append(updates, m)
	}
	r.Updates = updates
	raw, err := json.Marshal(r)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `UPDATE chat_jobs SET status='completed',result_json=?,memory_epoch=?,delivery=IF(channel='wechat','ready','none') WHERE id=?`, string(raw), epoch, j.ID)
	if err != nil {
		return err
	}
	return tx.Commit()
}

func wxUser(appid, openid string) string {
	sum := sha256.Sum256([]byte(appid + "\x00" + openid))
	return "wx_" + hex.EncodeToString(sum[:16])
}
func formatReply(r Result) string {
	text := r.Reply
	for i, a := range r.Recommendations {
		text += fmt.Sprintf("\n\n%d. %s\n%s\n%s", i+1, a.Title, a.Reason, a.URL)
	}
	if len(r.Updates) > 0 {
		text += "\n\n已记住："
		for _, m := range r.Updates {
			text += m.Value + "；"
		}
	}
	// WeChat text is bounded by UTF-8 bytes, not runes. Keep a single reply per incoming message.
	for len([]byte(text)) > 1950 {
		text = string([]rune(text)[:len([]rune(text))-1])
	}
	return text
}

func (s *Service) memoryHealth(r *ghttp.Request) {
	if s.memory == nil {
		r.Response.WriteJson(map[string]any{"status": "disabled", "configured": false})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	status, err := s.memory.Health(ctx)
	if err != nil {
		r.Response.WriteStatus(503, map[string]any{"status": "unavailable", "configured": true})
		return
	}
	// Provider health is already sanitized by the private service; do not add
	// URLs, tokens, or database connection details to this response.
	r.Response.WriteJson(map[string]any{"status": "ok", "configured": true, "dependencies": status})
}
