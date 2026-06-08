package observability

import (
	"context"
	"net/http"
	"sync"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

var metricsState = newMetricsState()

type state struct {
	mu sync.RWMutex

	registry *prometheus.Registry

	taskRuns            *prometheus.CounterVec
	taskDuration        *prometheus.HistogramVec
	crawlerArticles     *prometheus.CounterVec
	grpcClientRequests  *prometheus.CounterVec
	grpcClientDuration  *prometheus.HistogramVec
	recommendationItems *prometheus.CounterVec
	postsGenerated      *prometheus.CounterVec
	feedbackReceived    *prometheus.CounterVec
}

func newMetricsState() *state {
	s := &state{}
	s.reset()
	return s
}

func MetricsHandler() http.Handler {
	metricsState.mu.RLock()
	registry := metricsState.registry
	metricsState.mu.RUnlock()
	return promhttp.HandlerFor(registry, promhttp.HandlerOpts{})
}

func RecordTaskRun(_ context.Context, taskType, status string, durationSeconds float64) {
	metricsState.mu.RLock()
	defer metricsState.mu.RUnlock()
	metricsState.taskRuns.WithLabelValues(taskType, status).Inc()
	metricsState.taskDuration.WithLabelValues(taskType, status).Observe(durationSeconds)
}

func RecordCrawlerArticle(_ context.Context, source, articleType, status string, count int) {
	if count <= 0 {
		return
	}
	metricsState.mu.RLock()
	defer metricsState.mu.RUnlock()
	metricsState.crawlerArticles.WithLabelValues(source, articleType, status).Add(float64(count))
}

func RecordGRPCClient(_ context.Context, method, statusCode string, durationSeconds float64) {
	metricsState.mu.RLock()
	defer metricsState.mu.RUnlock()
	metricsState.grpcClientRequests.WithLabelValues(method, statusCode).Inc()
	metricsState.grpcClientDuration.WithLabelValues(method, statusCode).Observe(durationSeconds)
}

func RecordRecommendation(_ context.Context, decision string, count int) {
	if count <= 0 {
		return
	}
	metricsState.mu.RLock()
	defer metricsState.mu.RUnlock()
	metricsState.recommendationItems.WithLabelValues(decision).Add(float64(count))
}

func RecordPostGenerated(_ context.Context, status string, count int) {
	if count <= 0 {
		return
	}
	metricsState.mu.RLock()
	defer metricsState.mu.RUnlock()
	metricsState.postsGenerated.WithLabelValues(status).Add(float64(count))
}

func RecordUserFeedback(_ context.Context, feedbackType, status string, count int) {
	if count <= 0 {
		return
	}
	metricsState.mu.RLock()
	defer metricsState.mu.RUnlock()
	metricsState.feedbackReceived.WithLabelValues(feedbackType, status).Add(float64(count))
}

func ResetMetricsForTest() {
	metricsState.mu.Lock()
	defer metricsState.mu.Unlock()
	metricsState.reset()
}

func (s *state) reset() {
	s.registry = prometheus.NewRegistry()
	s.taskRuns = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "knowmate_task_runs_total",
			Help: "Total task runs partitioned by task type and status.",
		},
		[]string{"task_type", "status"},
	)
	s.taskDuration = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "knowmate_task_duration_seconds",
			Help:    "Task run duration in seconds partitioned by task type and status.",
			Buckets: prometheus.DefBuckets,
		},
		[]string{"task_type", "status"},
	)
	s.crawlerArticles = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "knowmate_crawler_articles_total",
			Help: "Total crawler articles partitioned by source, type, and status.",
		},
		[]string{"source", "type", "status"},
	)
	s.grpcClientRequests = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "knowmate_grpc_client_requests_total",
			Help: "Total gRPC client requests partitioned by method and status code.",
		},
		[]string{"method", "status_code"},
	)
	s.grpcClientDuration = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "knowmate_grpc_client_duration_seconds",
			Help:    "gRPC client request duration in seconds partitioned by method and status code.",
			Buckets: prometheus.DefBuckets,
		},
		[]string{"method", "status_code"},
	)
	s.recommendationItems = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "knowmate_recommendation_items_total",
			Help: "Total recommendation items partitioned by decision.",
		},
		[]string{"decision"},
	)
	s.postsGenerated = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "knowmate_posts_generated_total",
			Help: "Total generated posts partitioned by status.",
		},
		[]string{"status"},
	)
	s.feedbackReceived = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "knowmate_feedback_received_total",
			Help: "Total received feedback partitioned by feedback type and status.",
		},
		[]string{"feedback_type", "status"},
	)

	s.registry.MustRegister(
		s.taskRuns,
		s.taskDuration,
		s.crawlerArticles,
		s.grpcClientRequests,
		s.grpcClientDuration,
		s.recommendationItems,
		s.postsGenerated,
		s.feedbackReceived,
	)
}
