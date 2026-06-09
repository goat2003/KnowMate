import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api/, "");
    const method = route.request().method();

    if (path === "/health") {
      return route.fulfill({ json: { status: "ok", db: { status: "ok" }, agent: { status: "SERVING" } } });
    }
    if (path === "/runs/articles" && method === "POST") {
      return route.fulfill({ json: { ok: true, result: { run_id: "articles-1", status: "completed" } } });
    }
    if (path === "/runs") {
      return route.fulfill({
        json: {
          ok: true,
          items: [{ run_id: "run-1", task_type: "articles", status: "failed", current_step: "grpc" }]
        }
      });
    }
    if (path === "/runs/run-1") {
      return route.fulfill({
        json: {
          ok: true,
          run: {
            run_id: "run-1",
            task_type: "articles",
            status: "failed",
            error_message: "grpc timeout",
            steps: [{ run_id: "run-1", step_name: "fetch", status: "completed", output_summary: "2 articles" }]
          }
        }
      });
    }
    if (path === "/runs/run-1/retry" && method === "POST") {
      return route.fulfill({ json: { ok: true, result: { run_id: "run-1", status: "partially_completed" } } });
    }
    if (path === "/articles") {
      return route.fulfill({
        json: {
          ok: true,
          items: [{ id: "article-1", title: "Agent ranking", url: "https://example.com/a", source: "arxiv", fetch_status: "success" }]
        }
      });
    }
    if (path === "/posts") {
      return route.fulfill({
        json: {
          ok: true,
          items: [{ post_uid: "post-1", article_uid: "article-1", title: "Agent ranking", markdown: "## Agent ranking", status: "ready" }]
        }
      });
    }
    if (path === "/posts/post-1") {
      return route.fulfill({
        json: {
          ok: true,
          post: {
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
          }
        }
      });
    }
    if (path === "/feedback" && method === "POST") {
      return route.fulfill({ json: { ok: true, result: { run_id: "feedback-1", status: "completed" } } });
    }
    if (path === "/profile") {
      return route.fulfill({
        json: {
          ok: true,
          profile: { user_id: "default-user", version: 2, is_active: true, snapshot: { topics: "{\"AI\":0.8}" } }
        }
      });
    }
    if (path === "/profile/history") {
      return route.fulfill({
        json: {
          ok: true,
          items: [
            { user_id: "default-user", version: 2, change_reason: "feedback" },
            { user_id: "default-user", version: 1, change_reason: "seed" }
          ]
        }
      });
    }
    if (path === "/profile/rollback" && method === "POST") {
      return route.fulfill({ json: { ok: true, profile: { user_id: "default-user", version: 3 } } });
    }
    if (path === "/mcp-call-logs") {
      return route.fulfill({
        json: {
          ok: true,
          items: [
            {
              call_id: "call-1",
              run_id: "run-1",
              server_name: "embedding-mcp",
              tool_name: "embed_text",
              status: "failed",
              error_message: "timeout",
              latency_ms: 1200
            }
          ]
        }
      });
    }

    return route.fulfill({ status: 404, json: { ok: false, error: `unhandled ${method} ${path}` } });
  });
});

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

test("main admin workflow", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading").filter({ hasText: /系统概览|绯荤粺姒傝/ })).toBeVisible();
  await page.getByRole("button", { name: /手动触发抓取/ }).click();
  await expect(page.getByText(/已触发抓取任务/)).toBeVisible();

  await page.getByTestId("nav-runs").click();
  await page.getByRole("button", { name: /run-1/ }).click();
  await expect(page.getByText("grpc timeout")).toBeVisible();
  await page.getByRole("button", { name: /重试失败任务/ }).click();
  await expect(page.getByText(/已重试任务/)).toBeVisible();

  await page.getByTestId("nav-posts").click();
  await page.getByRole("button", { name: /Agent ranking/ }).click();
  await expect(page.getByText("评分明细")).toBeVisible();
  await expect(page.getByText("topic match")).toBeVisible();

  await page.getByTestId("nav-feedback").click();
  await page.getByLabel("Post ID").fill("post-1");
  await page.getByLabel("反馈内容").fill("保留更多工程细节");
  await page.getByRole("button", { name: "提交反馈" }).click();
  await expect(page.getByText(/反馈已提交/)).toBeVisible();

  await page.getByTestId("nav-mcp").click();
  await expect(page.getByText("embedding-mcp")).toBeVisible();
  await expect(page.getByText("timeout")).toBeVisible();
});
