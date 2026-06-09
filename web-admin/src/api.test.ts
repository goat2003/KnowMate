import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient } from "./api";

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });

afterEach(() => {
  vi.restoreAllMocks();
});

describe("api client", () => {
  it("calls backend routes through the Vite proxy prefix", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true, items: [] }));
    const client = createApiClient({ fetcher: fetchMock });

    await client.listArticles({ source: "arxiv", status: "success", q: "agent" });

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/articles?source=arxiv&status=success&q=agent");
  });

  it("throws ApiError for GoFrame business errors", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: false, error: "mysql unavailable" }));
    const client = createApiClient({ fetcher: fetchMock });

    await expect(client.health()).rejects.toMatchObject({
      message: "mysql unavailable",
      status: 200
    });
  });

  it("marks 401 and 403 responses as forbidden", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: false, error: "unauthorized" }, 401));
    const client = createApiClient({ fetcher: fetchMock });

    const error = await client.listPosts().catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ forbidden: true });
  });
});
