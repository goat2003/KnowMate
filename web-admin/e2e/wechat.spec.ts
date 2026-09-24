import { expect, test } from "@playwright/test";

test("wechat chat works in a mobile viewport", async ({ page }) => {
  await page.route("**/api/wechat/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (path.endsWith("/me")) return route.fulfill({ json: { ok: true, user: { id: "wx-test" } } });
    if (path.endsWith("/conversations")) return route.fulfill({ json: { ok: true, items: [] } });
    if (path.endsWith("/memories") && method === "GET") return route.fulfill({ json: { ok: true, items: [{ key: "goal", value: "准备面试", evidence: "我的目标是准备面试" }] } });
    if (path.endsWith("/recommendations")) return route.fulfill({ json: { ok: true, items: [{ id: "a1", title: "Go 实践", summary: "工程案例", reason: "目标匹配", published_at: "2026-09-21", url: "https://example.org/go", score: 1 }] } });
    if (path.endsWith("/messages") && method === "POST") return route.fulfill({ json: { ok: true, result: { id: 1 } } });
    if (path.endsWith("/memories") && method === "DELETE") return route.fulfill({ json: { ok: true } });
    return route.fulfill({ status: 404, json: { ok: false, error: "unhandled route" } });
  });

  await page.goto("/wechat/chat");
  await expect(page.getByRole("heading", { name: "KnowMate" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Go 实践/ })).toHaveAttribute("href", "https://example.org/go");
  await page.getByRole("textbox", { name: "输入消息" }).fill("请推荐");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByRole("button", { name: "删除目标" })).toBeVisible();
  await page.getByRole("button", { name: "删除目标" }).click();
  await expect(page.getByRole("button", { name: "发送" })).toBeVisible();
});
