import type {
  Article,
  FeedbackResult,
  HealthResponse,
  McpCallLog,
  Post,
  RecommendationExplanation,
  RunArticlesResult,
  TaskRun,
  UserProfileSnapshot
} from "./types";

type Fetcher = typeof fetch;

interface ClientOptions {
  baseUrl?: string;
  fetcher?: Fetcher;
  token?: string;
}

interface Envelope<T> {
  ok?: boolean;
  error?: string;
  items?: T;
  item?: T;
  post?: T;
  profile?: T;
  run?: T;
  result?: T;
  explanation?: T;
  status?: string;
  db?: Record<string, unknown>;
  agent?: Record<string, unknown>;
}

type QueryValue = string | number | boolean | undefined | null;

export class ApiError extends Error {
  readonly status: number;
  readonly forbidden: boolean;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.forbidden = status === 401 || status === 403;
  }
}

export function createApiClient(options: ClientOptions = {}) {
  const baseUrl = options.baseUrl ?? "/api";
  const fetcher = options.fetcher ?? fetch;

  async function request<T>(path: string, init: RequestInit = {}, resultKey?: keyof Envelope<T>): Promise<T> {
    const headers = new Headers(init.headers);
    if (!headers.has("Content-Type") && init.body) {
      headers.set("Content-Type", "application/json");
    }
    if (options.token) {
      headers.set("Authorization", `Bearer ${options.token}`);
    }

    const response = await fetcher(`${baseUrl}${path}`, { ...init, headers });
    const text = await response.text();
    let payload: Envelope<T> | undefined;
    try {
      payload = text ? (JSON.parse(text) as Envelope<T>) : undefined;
    } catch {
      throw new ApiError(text || response.statusText, response.status);
    }

    if (!response.ok) {
      throw new ApiError(payload?.error || response.statusText, response.status);
    }
    if (payload?.ok === false) {
      throw new ApiError(payload.error || "request failed", response.status);
    }

    if (resultKey && payload && resultKey in payload) {
      return payload[resultKey] as T;
    }
    return payload as T;
  }

  return {
    health: () => request<HealthResponse>("/health"),
    runArticles: () => request<RunArticlesResult>("/runs/articles", { method: "POST" }, "result"),
    listRuns: (query: Record<string, QueryValue> = {}) => request<TaskRun[]>(`/runs${toQuery(query)}`, {}, "items"),
    getRun: (runID: string) => request<TaskRun>(`/runs/${encodeURIComponent(runID)}`, {}, "run"),
    retryRun: (runID: string) => request<RunArticlesResult>(`/runs/${encodeURIComponent(runID)}/retry`, { method: "POST" }, "result"),
    listArticles: (query: Record<string, QueryValue> = {}) => request<Article[]>(`/articles${toQuery(query)}`, {}, "items"),
    listPosts: () => request<Post[]>("/posts", {}, "items"),
    getPost: (postID: string) => request<Post>(`/posts/${encodeURIComponent(postID)}`, {}, "post"),
    explainPost: (postID: string) =>
      request<RecommendationExplanation>(`/recommendations/explain${toQuery({ post_id: postID })}`, {}, "explanation"),
    submitFeedback: (body: { post_id: string; user_id?: string; feedback_text: string; feedback_type?: string; rating?: number }) =>
      request<FeedbackResult>("/feedback", { method: "POST", body: JSON.stringify(body) }, "result"),
    getProfile: (userID = "default-user") => request<UserProfileSnapshot>(`/profile${toQuery({ user_id: userID })}`, {}, "profile"),
    listProfileHistory: (userID = "default-user") =>
      request<UserProfileSnapshot[]>(`/profile/history${toQuery({ user_id: userID, limit: 20 })}`, {}, "items"),
    rollbackProfile: (body: { user_id: string; target_version: number; reason: string }) =>
      request<UserProfileSnapshot>("/profile/rollback", { method: "POST", body: JSON.stringify(body) }, "profile"),
    listMcpCallLogs: (query: Record<string, QueryValue> = {}) => request<McpCallLog[]>(`/mcp-call-logs${toQuery(query)}`, {}, "items")
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;

export function toQuery(values: Record<string, QueryValue>) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}
