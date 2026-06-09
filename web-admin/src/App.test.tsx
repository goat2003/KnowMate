import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError, type ApiClient } from "./api";
import { App } from "./App";

function createClient(overrides: Partial<ApiClient> = {}): ApiClient {
  const client = {
    health: vi.fn().mockResolvedValue({ status: "ok", db: { status: "ok" }, agent: { status: "SERVING" } }),
    runArticles: vi.fn().mockResolvedValue({ run_id: "articles-1", status: "completed" }),
    listRuns: vi.fn().mockResolvedValue([
      { run_id: "run-1", task_type: "articles", status: "failed", current_step: "grpc" }
    ]),
    getRun: vi.fn().mockResolvedValue({
      run_id: "run-1",
      task_type: "articles",
      status: "failed",
      error_message: "grpc timeout",
      steps: [{ run_id: "run-1", step_name: "fetch", status: "completed", output_summary: "2 articles" }]
    }),
    retryRun: vi.fn().mockResolvedValue({ run_id: "run-1", status: "partially_completed" }),
    listArticles: vi.fn().mockResolvedValue([
      { id: "article-1", title: "Agent ranking", url: "https://example.com/a", source: "arxiv", fetch_status: "success" }
    ]),
    listPosts: vi.fn().mockResolvedValue([
      {
        post_uid: "post-1",
        article_uid: "article-1",
        title: "Agent ranking",
        markdown: "## Agent ranking",
        status: "ready",
        metadata: { score: 8.5, recommendation_reasons: ["topic match"] }
      }
    ]),
    getPost: vi.fn().mockResolvedValue({
      post_uid: "post-1",
      article_uid: "article-1",
      title: "Agent ranking",
      markdown: "## Agent ranking",
      status: "ready",
      metadata: {
        score: 8.5,
        rank_position: 1,
        profile_version: 3,
        score_breakdown: [{ dimension: "keyword_match", normalized_score: 9, evidence: ["agent"] }],
        recommendation_reasons: ["topic match"]
      }
    }),
    explainPost: vi.fn().mockResolvedValue({ post_uid: "post-1", article_uid: "article-1", metadata: {} }),
    submitFeedback: vi.fn().mockResolvedValue({ run_id: "feedback-1", status: "completed" }),
    getProfile: vi.fn().mockResolvedValue({
      user_id: "default-user",
      version: 2,
      is_active: true,
      snapshot: { topics: "{\"AI\":0.8}" }
    }),
    listProfileHistory: vi.fn().mockResolvedValue([
      { user_id: "default-user", version: 2, change_reason: "feedback" },
      { user_id: "default-user", version: 1, change_reason: "seed" }
    ]),
    rollbackProfile: vi.fn().mockResolvedValue({ user_id: "default-user", version: 3 }),
    listMcpCallLogs: vi.fn().mockResolvedValue([
      {
        call_id: "call-1",
        run_id: "run-1",
        server_name: "embedding-mcp",
        tool_name: "embed_text",
        status: "failed",
        error_message: "timeout",
        latency_ms: 1200
      }
    ]),
    ...overrides
  };
  return client as unknown as ApiClient;
}

describe("App", () => {
  it("shows loading states and overview data", async () => {
    render(<App client={createClient()} />);

    expect(screen.getAllByLabelText("正在加载").length).toBeGreaterThan(0);
    expect(await screen.findByText("run-1")).toBeInTheDocument();
  });

  it("shows empty states for empty API lists", async () => {
    render(<App client={createClient({ listRuns: vi.fn().mockResolvedValue([]) })} />);

    expect(await screen.findByText("暂无任务运行记录")).toBeInTheDocument();
  });

  it("renders permission state for forbidden API errors", async () => {
    render(<App client={createClient({ listRuns: vi.fn().mockRejectedValue(new ApiError("unauthorized", 401)) })} />);

    expect(await screen.findByText("无权限访问，请配置 API Token。")).toBeInTheDocument();
  });

  it("triggers an article run from overview", async () => {
    const client = createClient();
    render(<App client={client} />);

    await userEvent.click(await screen.findByRole("button", { name: /手动触发抓取/ }));

    await waitFor(() => expect(client.runArticles).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/已触发抓取任务/)).toBeInTheDocument();
  });

  it("opens post detail and displays recommendation reasons", async () => {
    render(<App client={createClient()} />);

    await userEvent.click(screen.getByRole("button", { name: /推文列表与详情/ }));
    await userEvent.click(await screen.findByRole("button", { name: /Agent ranking/ }));

    expect(await screen.findByText("评分明细")).toBeInTheDocument();
    expect(await screen.findByText("topic match")).toBeInTheDocument();
  });

  it("submits feedback through the real feedback API shape", async () => {
    const client = createClient();
    render(<App client={client} />);

    await userEvent.click(screen.getByRole("button", { name: "用户反馈" }));
    await userEvent.type(screen.getByLabelText("Post ID"), "post-1");
    await userEvent.type(screen.getByLabelText("反馈内容"), "保留更多工程细节");
    await userEvent.click(screen.getByRole("button", { name: "提交反馈" }));

    await waitFor(() => expect(client.submitFeedback).toHaveBeenCalledWith(expect.objectContaining({
      post_id: "post-1",
      feedback_text: "保留更多工程细节"
    })));
  });
});
