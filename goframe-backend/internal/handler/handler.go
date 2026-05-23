package handler

import (
	"encoding/json"
	"strconv"

	"knowledge-post-agent/goframe-backend/internal/logic/harness"
	"knowledge-post-agent/goframe-backend/internal/store"

	"github.com/gogf/gf/v2/frame/g"
	"github.com/gogf/gf/v2/net/ghttp"
)

type Handler struct {
	store   *store.Store
	harness *harness.Harness
}

func New(store *store.Store, runner *harness.Harness) *Handler {
	return &Handler{store: store, harness: runner}
}

func (h *Handler) Register(server *ghttp.Server) {
	server.Group("/", func(group *ghttp.RouterGroup) {
		group.GET("/health", h.Health)
		group.POST("/runs/articles", h.RunArticles)
		group.POST("/feedback", h.Feedback)
		group.GET("/posts", h.ListPosts)

		group.GET("/run-logs", h.ListRunLogs)
	})
}

func (h *Handler) Health(r *ghttp.Request) {
	db := g.Map{"status": "ok"}
	if err := h.store.Ping(r.Context()); err != nil {
		db = g.Map{"status": "unavailable", "error": err.Error()}
	}

	agent := g.Map{"status": "ok"}
	if response, err := h.harness.AgentHealth(r.Context()); err != nil {
		agent = g.Map{"status": "unavailable", "error": err.Error()}
	} else {
		agent = g.Map{
			"status":         response.Status,
			"version":        response.Version,
			"enabled_agents": response.EnabledAgents,
			"mock_mode":      response.MockMode,
		}
	}

	r.Response.WriteJson(g.Map{
		"status": "ok",
		"db":     db,
		"agent":  agent,
	})
}

func (h *Handler) RunArticles(r *ghttp.Request) {
	result := h.harness.RunArticles(r.Context())
	r.Response.WriteJson(g.Map{
		"ok":     result.Status == "completed",
		"result": result,
	})
}

func (h *Handler) Feedback(r *ghttp.Request) {
	var req harness.FeedbackRequest
	if !decodeJSON(r, &req) {
		return
	}
	if req.PostID == "" || req.FeedbackText == "" {
		r.Response.WriteJson(g.Map{"ok": false, "error": "post_id and feedback_text are required"})
		return
	}
	result := h.harness.ProcessFeedback(r.Context(), req)
	r.Response.WriteJson(g.Map{
		"ok":     result.Status == "completed",
		"result": result,
	})
}

func (h *Handler) ListPosts(r *ghttp.Request) {
	posts, err := h.store.ListPosts(r.Context(), queryLimit(r))
	if err != nil {
		r.Response.WriteJson(g.Map{"ok": false, "error": err.Error()})
		return
	}
	r.Response.WriteJson(g.Map{"ok": true, "items": posts})
}

func (h *Handler) ListRunLogs(r *ghttp.Request) {
	logs, err := h.store.ListRunLogs(r.Context(), queryLimit(r))
	if err != nil {
		r.Response.WriteJson(g.Map{"ok": false, "error": err.Error()})
		return
	}
	r.Response.WriteJson(g.Map{"ok": true, "items": logs})
}

func decodeJSON(r *ghttp.Request, target any) bool {
	if r.Request.Body == nil {
		return true
	}
	decoder := json.NewDecoder(r.Request.Body)
	if err := decoder.Decode(target); err != nil {
		r.Response.WriteJson(g.Map{"ok": false, "error": "invalid json: " + err.Error()})
		return false
	}
	return true
}

func queryLimit(r *ghttp.Request) int {
	limit, _ := strconv.Atoi(r.GetQuery("limit").String())
	if limit <= 0 {
		return 20
	}
	return limit
}
